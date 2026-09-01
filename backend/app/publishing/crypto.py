"""Symmetric encryption for OAuth tokens at rest (Fernet).

Tokens are the only secrets this application stores on behalf of a third party;
a database dump must not hand someone the ability to post as WRCC. Fernet gives
authenticated encryption (AES-128-CBC + HMAC) with a single key from
``TOKEN_ENCRYPTION_KEY``, so a tampered ciphertext fails loudly rather than
decrypting to garbage.

Pure — no DB, no framework — so it unit-tests directly.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings


class TokenEncryptionError(RuntimeError):
    """Raised when the key is unusable or a stored token cannot be decrypted."""


class TokenCipher:
    """Encrypts and decrypts token strings with one Fernet key."""

    def __init__(self, key: str) -> None:
        if not key:
            raise TokenEncryptionError(
                "TOKEN_ENCRYPTION_KEY is not set. Generate one with: python -c "
                '"from cryptography.fernet import Fernet; '
                'print(Fernet.generate_key().decode())"'
            )
        try:
            self._fernet = Fernet(key.encode("utf-8"))
        except (ValueError, TypeError) as exc:
            raise TokenEncryptionError(
                "TOKEN_ENCRYPTION_KEY is not a valid Fernet key "
                "(expected urlsafe-base64-encoded 32 bytes)."
            ) from exc

    def encrypt(self, plaintext: str) -> str:
        return self._fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, ciphertext: str) -> str:
        """Return the plaintext token.

        Raises ``TokenEncryptionError`` when the ciphertext was produced with a
        different key or has been tampered with — which in practice means the
        key was rotated and the affected accounts must be reconnected.
        """
        try:
            return self._fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
        except InvalidToken as exc:
            raise TokenEncryptionError(
                "Stored token could not be decrypted with the current "
                "TOKEN_ENCRYPTION_KEY. Reconnect the account."
            ) from exc


def cipher_from_settings(settings: Settings) -> TokenCipher:
    return TokenCipher(settings.token_encryption_key)
