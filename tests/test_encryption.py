from unittest.mock import patch

import pytest

from app.encryption import Encryption


class TestEncryption:
    def test_encrypt_decrypt_roundtrip(self):
        with patch("app.encryption.get_account_password", return_value="test-password"):
            Encryption.key = None
            ciphertext = Encryption.encrypt("secret-key")
            assert Encryption.decrypt(ciphertext) == "secret-key"

    def test_raises_when_password_unavailable(self):
        with patch("app.encryption.get_account_password", return_value=False):
            Encryption.key = None
            with pytest.raises(Exception, match="Cannot get password from shkeeper"):
                Encryption.encrypt("data")

    def test_encryption_key_is_cached_between_calls(self):
        with patch("app.encryption.get_account_password", return_value="test-password"):
            Encryption.key = None
            Encryption.encrypt("one")
            cached_key = Encryption.key
            Encryption.encrypt("two")
            assert Encryption.key == cached_key
