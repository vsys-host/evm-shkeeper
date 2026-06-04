import os
from unittest.mock import MagicMock, patch

import pytest

# Required before importing app.config (COIN is resolved at import time).
os.environ.setdefault("WALLET", "ETH")

# Load config module before app package shadows it with the config dict.
import app.config  # noqa: F401, E402

_mock_flask_app = MagicMock()
_mock_w3 = MagicMock()
patch("app.token.make_provider", return_value=_mock_w3).start()
patch("app.create_app", return_value=_mock_flask_app).start()
patch("app.api.views.create_app", return_value=_mock_flask_app).start()
patch("app.api.views.Web3", return_value=MagicMock()).start()

import app  # noqa: F401, E402


@pytest.fixture(autouse=True)
def reset_encryption_key():
    from app.encryption import Encryption

    Encryption.key = None
    yield
    Encryption.key = None


@pytest.fixture(autouse=True)
def reset_unlock_acc_cache():
    import app.unlock_acc as unlock_acc

    unlock_acc.acc_password = False
    yield
    unlock_acc.acc_password = False


@pytest.fixture
def ethereum_chain():
    from app.chains import CHAINS

    return CHAINS["ETH"]


@pytest.fixture
def arbitrum_chain():
    from app.chains import CHAINS

    return CHAINS["ARBETH"]
