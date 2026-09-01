"""Token encryption at rest: round trip, key mismatch, tampering."""

from __future__ import annotations

import base64

import pytest

from app.publishing.crypto import TokenCipher, TokenEncryptionError, cipher_from_settings
from tests.conftest import TEST_TOKEN_KEY, make_settings

OTHER_KEY = base64.urlsafe_b64encode(b"another-key-32-bytes-long-!!!!!!").decode()


def test_round_trips_a_token() -> None:
    cipher = TokenCipher(TEST_TOKEN_KEY)
    assert cipher.decrypt(cipher.encrypt("page-token-123")) == "page-token-123"


def test_ciphertext_does_not_contain_the_plaintext() -> None:
    cipher = TokenCipher(TEST_TOKEN_KEY)
    assert "page-token-123" not in cipher.encrypt("page-token-123")


def test_same_plaintext_encrypts_differently_each_time() -> None:
    # Fernet embeds a random IV; identical tokens must not produce identical
    # rows, or a database reader could tell two accounts share a token.
    cipher = TokenCipher(TEST_TOKEN_KEY)
    assert cipher.encrypt("same") != cipher.encrypt("same")


def test_decrypt_with_a_different_key_fails_loudly() -> None:
    ciphertext = TokenCipher(TEST_TOKEN_KEY).encrypt("page-token-123")
    with pytest.raises(TokenEncryptionError, match="Reconnect the account"):
        TokenCipher(OTHER_KEY).decrypt(ciphertext)


def test_tampered_ciphertext_is_rejected() -> None:
    cipher = TokenCipher(TEST_TOKEN_KEY)
    ciphertext = cipher.encrypt("page-token-123")
    tampered = ciphertext[:-4] + ("AAAA" if not ciphertext.endswith("AAAA") else "BBBB")
    with pytest.raises(TokenEncryptionError):
        cipher.decrypt(tampered)


def test_missing_key_explains_how_to_generate_one() -> None:
    with pytest.raises(TokenEncryptionError, match="Fernet.generate_key"):
        TokenCipher("")


def test_malformed_key_is_rejected() -> None:
    with pytest.raises(TokenEncryptionError, match="valid Fernet key"):
        TokenCipher("not-a-fernet-key")


def test_cipher_from_settings_uses_the_configured_key() -> None:
    cipher = cipher_from_settings(make_settings())
    assert cipher.decrypt(cipher.encrypt("abc")) == "abc"
