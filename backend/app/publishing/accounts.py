"""Connected social account persistence and token resolution.

Owns the one-active-account-per-platform rule and is the only place a stored
token is decrypted. Everything above this layer works with ``ResolvedAccount``,
which carries a plaintext token but is never serialized.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit import record_audit
from app.config import Settings
from app.db.enums import ContentPlatform
from app.db.models import SocialAccount
from app.publishing.crypto import cipher_from_settings
from app.publishing.publishers.base import ResolvedAccount

# Treat a token as expired slightly early: a token that dies mid-request is a
# far worse experience than one we refuse to use a few minutes sooner.
TOKEN_EXPIRY_SKEW = dt.timedelta(minutes=5)


class SocialAccountNotFoundError(LookupError):
    """Raised when a social account id does not exist."""


def is_token_expired(
    account: SocialAccount, *, now: dt.datetime | None = None
) -> bool:
    if account.token_expires_at is None:
        return False  # Meta Page tokens are long-lived and carry no expiry.
    now = now or dt.datetime.now(dt.UTC)
    expires_at = account.token_expires_at
    if expires_at.tzinfo is None:  # SQLite round-trips naive datetimes
        expires_at = expires_at.replace(tzinfo=dt.UTC)
    return expires_at - TOKEN_EXPIRY_SKEW <= now


class SocialAccountService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self._session = session
        self._settings = settings

    async def list_accounts(self) -> list[SocialAccount]:
        result = await self._session.execute(
            select(SocialAccount).order_by(
                SocialAccount.platform, SocialAccount.created_at.desc()
            )
        )
        return list(result.scalars())

    async def get(self, account_id: uuid.UUID) -> SocialAccount:
        account = await self._session.get(SocialAccount, account_id)
        if account is None:
            raise SocialAccountNotFoundError(f"Social account {account_id} not found.")
        return account

    async def get_active(self, platform: ContentPlatform) -> SocialAccount | None:
        result = await self._session.execute(
            select(SocialAccount).where(
                SocialAccount.platform == platform,
                SocialAccount.is_active.is_(True),
            )
        )
        return result.scalars().first()

    def resolve(self, account: SocialAccount) -> ResolvedAccount:
        """Decrypt the stored token into the shape publishers consume."""
        cipher = cipher_from_settings(self._settings)
        return ResolvedAccount(
            id=str(account.id),
            platform=account.platform,
            external_id=account.external_id,
            display_name=account.display_name,
            access_token=cipher.decrypt(account.access_token_encrypted),
            metadata=dict(account.account_metadata or {}),
        )

    async def upsert(
        self,
        *,
        platform: ContentPlatform,
        external_id: str,
        display_name: str,
        access_token: str,
        actor_id: uuid.UUID | None,
        handle: str | None = None,
        refresh_token: str | None = None,
        token_expires_at: dt.datetime | None = None,
        scopes: list[str] | None = None,
        metadata: dict | None = None,
    ) -> SocialAccount:
        """Store (or re-store) a connection and make it the active destination.

        Re-connecting the same destination updates the existing row rather than
        accumulating duplicates, so the publication history's foreign keys stay
        pointed at one account across token refreshes.
        """
        cipher = cipher_from_settings(self._settings)
        existing = (
            await self._session.execute(
                select(SocialAccount).where(
                    SocialAccount.platform == platform,
                    SocialAccount.external_id == external_id,
                )
            )
        ).scalars().first()

        await self._deactivate_platform(platform, keep=existing.id if existing else None)

        account = existing or SocialAccount(
            platform=platform, external_id=external_id, connected_by=actor_id
        )
        account.display_name = display_name
        account.handle = handle
        account.access_token_encrypted = cipher.encrypt(access_token)
        account.refresh_token_encrypted = (
            cipher.encrypt(refresh_token) if refresh_token else None
        )
        account.token_expires_at = token_expires_at
        account.scopes = list(scopes or [])
        account.account_metadata = dict(metadata or {})
        account.is_active = True
        if existing is None:
            self._session.add(account)
        await self._session.flush()

        record_audit(
            self._session,
            actor_id=actor_id,
            action="social_account_connected",
            entity_type="social_account",
            entity_id=account.id,
            payload_diff={
                "platform": platform.value,
                "external_id": external_id,
                "display_name": display_name,
                "scopes": list(scopes or []),
            },
        )
        # Commits like activate/disconnect do: one connected destination is a
        # complete unit of work, and a Meta exchange stores several in a row.
        await self._session.commit()
        return account

    async def activate(
        self, account_id: uuid.UUID, *, actor_id: uuid.UUID | None
    ) -> SocialAccount:
        account = await self.get(account_id)
        await self._deactivate_platform(account.platform, keep=account.id)
        account.is_active = True
        record_audit(
            self._session,
            actor_id=actor_id,
            action="social_account_activated",
            entity_type="social_account",
            entity_id=account.id,
            payload_diff={"platform": account.platform.value},
        )
        await self._session.commit()
        return account

    async def disconnect(
        self, account_id: uuid.UUID, *, actor_id: uuid.UUID | None
    ) -> None:
        account = await self.get(account_id)
        payload = {
            "platform": account.platform.value,
            "external_id": account.external_id,
        }
        await self._session.delete(account)
        record_audit(
            self._session,
            actor_id=actor_id,
            action="social_account_disconnected",
            entity_type="social_account",
            entity_id=account_id,
            payload_diff=payload,
        )
        await self._session.commit()

    async def _deactivate_platform(
        self, platform: ContentPlatform, *, keep: uuid.UUID | None
    ) -> None:
        """Clear the active flag on the platform's other accounts.

        Done as a read-then-write rather than a bulk UPDATE so the ORM's
        identity map stays consistent with the partial unique index; the row
        count here is at most a handful.
        """
        result = await self._session.execute(
            select(SocialAccount).where(
                SocialAccount.platform == platform,
                SocialAccount.is_active.is_(True),
            )
        )
        for other in result.scalars():
            if other.id != keep:
                other.is_active = False
        await self._session.flush()
