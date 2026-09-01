"""Publishing endpoints: connected accounts, preflight, publish, history.

Status-code contract, which differs deliberately from the rest of the API: if
an attempt was **recorded**, the response is 200 carrying the attempt record —
including a failed one, because a failed publish is a durable result the client
needs the id and error code of. If we **refused to attempt** (unknown item,
already published, preflight blockers), it is a 4xx and nothing was persisted.
"""

from __future__ import annotations

import logging
import urllib.parse
import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.config import Settings, get_settings
from app.content.service import ContentItemNotFoundError
from app.db.base import get_session
from app.db.enums import ContentPlatform
from app.db.models import ContentPublication, SocialAccount, User
from app.publishing.accounts import (
    SocialAccountNotFoundError,
    SocialAccountService,
    is_token_expired,
)
from app.publishing.oauth import (
    PROVIDER_FOR_PLATFORM,
    OAuthError,
    SocialProvider,
    get_oauth_provider,
)
from app.publishing.publishers import PublishError, get_verifier
from app.publishing.rules import LIMITS
from app.publishing.schemas import (
    AccountVerificationOut,
    AuthorizeUrlOut,
    PreflightOut,
    PublicationOut,
    PublishRequestBody,
    SocialAccountOut,
)
from app.publishing.service import (
    AlreadyPublishedError,
    ImageNotFoundError,
    PublishNotAllowedError,
    PublishService,
)
from app.publishing.state import OAuthStateError, sign_state, verify_state

logger = logging.getLogger(__name__)

router = APIRouter(tags=["publishing"], dependencies=[Depends(get_current_user)])


def get_publish_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> PublishService:
    return PublishService(session, settings)


def get_account_service(
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> SocialAccountService:
    return SocialAccountService(session, settings)


def _account_out(account: SocialAccount) -> SocialAccountOut:
    return SocialAccountOut(
        id=str(account.id),
        platform=account.platform.value,
        external_id=account.external_id,
        display_name=account.display_name,
        handle=account.handle,
        scopes=list(account.scopes or []),
        is_active=account.is_active,
        token_expires_at=account.token_expires_at,
        token_expired=is_token_expired(account),
        connected_at=account.created_at,
    )


def _publication_out(publication: ContentPublication) -> PublicationOut:
    return PublicationOut(
        id=str(publication.id),
        content_item_id=str(publication.content_item_id),
        social_account_id=(
            str(publication.social_account_id) if publication.social_account_id else None
        ),
        content_image_id=(
            str(publication.content_image_id) if publication.content_image_id else None
        ),
        status=publication.status.value,
        external_post_id=publication.external_post_id,
        permalink=publication.permalink,
        error=publication.error,
        error_code=publication.error_code,
        request_summary=publication.request_summary,
        created_at=publication.created_at,
        completed_at=publication.completed_at,
    )


# ── connect flow ──


def _settings_redirect(settings: Settings, **params: str) -> RedirectResponse:
    """Send the browser back to the Settings page with an outcome.

    The destination is always built from ``frontend_origin`` in configuration,
    never from anything in the request — otherwise the callback would be an
    open redirect that any crafted link could aim anywhere.
    """
    query = urllib.parse.urlencode(params)
    origin = settings.frontend_origin.rstrip("/")
    return RedirectResponse(
        url=f"{origin}/settings?{query}", status_code=status.HTTP_303_SEE_OTHER
    )


@router.get("/api/social/{platform}/connect", response_model=AuthorizeUrlOut)
async def social_connect(
    platform: ContentPlatform,
    settings: Settings = Depends(get_settings),
    user: User = Depends(get_current_user),
) -> AuthorizeUrlOut:
    """Return the provider's consent URL for the browser to navigate to.

    Returned as JSON rather than a 302 so the caller is a normal fetch: an
    opaque cross-origin redirect would give the frontend nothing to report if
    configuration is missing.
    """
    provider = PROVIDER_FOR_PLATFORM[platform]
    state = sign_state(user_id=user.id, provider=provider.value, settings=settings)
    try:
        url = get_oauth_provider(provider, settings).authorize_url(state=state)
    except OAuthError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return AuthorizeUrlOut(provider=provider.value, authorize_url=url)


def _fail_connect(
    settings: Settings, provider: SocialProvider, stage: str, reason: str
) -> RedirectResponse:
    """Log a failed connect, then send the reason back to the Settings page.

    The redirect alone shows the operator *what* went wrong; without a log line
    there is no record of *which stage* failed, and a connect that silently
    stores nothing is indistinguishable from one that was never attempted. The
    reason is already provider-supplied prose — never a code, token or secret.
    """
    logger.warning("Connect failed for %s at the %s: %s", provider.value, stage, reason)
    return _settings_redirect(settings, error=reason)


@router.get("/api/social/{provider}/callback")
async def social_callback(
    provider: SocialProvider,
    state: str,
    code: str | None = None,
    error: str | None = None,
    error_description: str | None = None,
    accounts: SocialAccountService = Depends(get_account_service),
    settings: Settings = Depends(get_settings),
    user: User = Depends(get_current_user),
) -> RedirectResponse:
    """Finish the connect flow and redirect back to Settings.

    Both the signed state *and* the session cookie are required. This is a
    top-level GET navigation, so the SameSite=lax cookie is sent; state alone
    would only prove the flow started here, not that the browser finishing it
    is still logged in.
    """
    try:
        state_user_id = verify_state(state, provider=provider.value, settings=settings)
    except OAuthStateError as exc:
        return _fail_connect(settings, provider, "state check", str(exc))
    if state_user_id != user.id:
        return _fail_connect(
            settings,
            provider,
            "state check",
            "That connection was started by a different user.",
        )

    if error or not code:
        return _fail_connect(
            settings,
            provider,
            "provider response",
            error_description or error or "No authorization code was returned.",
        )

    try:
        connected = await get_oauth_provider(provider, settings).exchange(code)
    except OAuthError as exc:
        return _fail_connect(settings, provider, "code exchange", str(exc))

    logger.info(
        "Connected %d %s destination(s): %s",
        len(connected),
        provider.value,
        ", ".join(f"{a.platform.value}:{a.external_id}" for a in connected),
    )
    for account in connected:
        await accounts.upsert(
            platform=account.platform,
            external_id=account.external_id,
            display_name=account.display_name,
            access_token=account.access_token,
            actor_id=user.id,
            handle=account.handle,
            refresh_token=account.refresh_token,
            token_expires_at=account.token_expires_at,
            scopes=account.scopes,
            metadata=account.metadata,
        )
    return _settings_redirect(settings, connected=provider.value)


# ── connected accounts ──


@router.get("/api/social/accounts", response_model=list[SocialAccountOut])
async def list_social_accounts(
    accounts: SocialAccountService = Depends(get_account_service),
) -> list[SocialAccountOut]:
    return [_account_out(account) for account in await accounts.list_accounts()]


@router.post("/api/social/accounts/{account_id}/activate", response_model=SocialAccountOut)
async def activate_social_account(
    account_id: uuid.UUID,
    accounts: SocialAccountService = Depends(get_account_service),
    user: User = Depends(get_current_user),
) -> SocialAccountOut:
    try:
        return _account_out(await accounts.activate(account_id, actor_id=user.id))
    except SocialAccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/api/social/accounts/{account_id}/verify", response_model=AccountVerificationOut
)
async def verify_social_account(
    account_id: uuid.UUID,
    accounts: SocialAccountService = Depends(get_account_service),
    settings: Settings = Depends(get_settings),
) -> AccountVerificationOut:
    """Ping the network to see whether the stored token still works.

    A Page token can die silently — a password change or a revoked permission
    leaves the row looking healthy — so "publishing failed" should not be the
    first time anyone finds out.
    """
    try:
        account = await accounts.get(account_id)
    except SocialAccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

    verifier = get_verifier(account.platform, settings)
    try:
        await verifier.verify(accounts.resolve(account))
    except PublishError as exc:
        return AccountVerificationOut(
            account=_account_out(account),
            ok=False,
            error=str(exc),
            error_code=exc.code,
        )
    return AccountVerificationOut(account=_account_out(account), ok=True)


@router.delete("/api/social/accounts/{account_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_social_account(
    account_id: uuid.UUID,
    accounts: SocialAccountService = Depends(get_account_service),
    user: User = Depends(get_current_user),
) -> None:
    try:
        await accounts.disconnect(account_id, actor_id=user.id)
    except SocialAccountNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


# ── publishing ──


@router.get("/api/content/{item_id}/publish/preflight", response_model=PreflightOut)
async def publish_preflight(
    item_id: uuid.UUID,
    image_id: uuid.UUID | None = None,
    service: PublishService = Depends(get_publish_service),
) -> PreflightOut:
    try:
        item, account, image, text, outcome = await service.preflight(
            item_id, image_id=image_id
        )
    except ContentItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ImageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    limits = LIMITS[item.platform]
    return PreflightOut(
        ready=outcome.ready,
        blockers=outcome.blockers,
        warnings=outcome.warnings,
        platform=item.platform.value,
        text=text,
        char_count=len(text),
        char_limit=limits.text_limit,
        hashtag_count=len(item.hashtags or []),
        image_id=str(image.id) if image is not None else None,
        image_required=limits.image_required,
        account=_account_out(account) if account is not None else None,
    )


@router.post("/api/content/{item_id}/publish", response_model=PublicationOut)
async def publish_content(
    item_id: uuid.UUID,
    body: PublishRequestBody | None = None,
    service: PublishService = Depends(get_publish_service),
    user: User = Depends(get_current_user),
) -> PublicationOut:
    try:
        publication = await service.publish(
            item_id, actor_id=user.id, image_id=body.image_id if body else None
        )
    except ContentItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ImageNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AlreadyPublishedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                f"{exc} It is live at {exc.permalink}."
                if exc.permalink
                else str(exc)
            ),
        ) from exc
    except PublishNotAllowedError as exc:
        raise HTTPException(
            # Literal 422: Starlette renamed the constant mid-1.x and the old
            # spelling now warns, while the new one is absent on older pins.
            status_code=422,
            detail=" ".join(exc.blockers),
        ) from exc
    return _publication_out(publication)


@router.get("/api/content/{item_id}/publications", response_model=list[PublicationOut])
async def list_publications(
    item_id: uuid.UUID,
    service: PublishService = Depends(get_publish_service),
) -> list[PublicationOut]:
    try:
        publications = await service.list_publications(item_id)
    except ContentItemNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return [_publication_out(publication) for publication in publications]
