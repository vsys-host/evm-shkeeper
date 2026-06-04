from unittest.mock import MagicMock, patch

import app.unlock_acc as unlock_acc


class TestGetAccountPassword:
    def test_returns_cached_password_without_http_call(self):
        unlock_acc.acc_password = "cached"
        with patch("app.unlock_acc.rq.get") as http_get:
            assert unlock_acc.get_account_password() == "cached"
            http_get.assert_not_called()

    def test_fetches_password_when_encryption_disabled(self):
        response = MagicMock()
        response.json.return_value = {
            "persistent_status": "disabled",
            "key": "plain-key",
        }
        with patch("app.unlock_acc.rq.get", return_value=response) as http_get:
            unlock_acc.acc_password = False
            assert unlock_acc.get_account_password() == "plain-key"
            http_get.assert_called_once()

    def test_returns_false_when_encryption_pending(self):
        response = MagicMock()
        response.json.return_value = {"persistent_status": "pending"}
        with patch("app.unlock_acc.rq.get", return_value=response):
            unlock_acc.acc_password = False
            assert unlock_acc.get_account_password() is False

    def test_returns_false_when_runtime_pending(self):
        response = MagicMock()
        response.json.return_value = {
            "persistent_status": "enabled",
            "runtime_status": "pending",
        }
        with patch("app.unlock_acc.rq.get", return_value=response):
            unlock_acc.acc_password = False
            assert unlock_acc.get_account_password() is False

    def test_returns_key_when_encryption_enabled_and_runtime_success(self):
        response = MagicMock()
        response.json.return_value = {
            "persistent_status": "enabled",
            "runtime_status": "success",
            "key": "runtime-key",
        }
        with patch("app.unlock_acc.rq.get", return_value=response):
            unlock_acc.acc_password = False
            assert unlock_acc.get_account_password() == "runtime-key"
