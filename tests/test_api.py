from decimal import Decimal
from unittest.mock import patch

import pytest
from flask import Blueprint, Flask, g

from app.api import check_credentials, pull_symbol


@pytest.fixture
def auth_client():
    app = Flask(__name__)
    app.config["TESTING"] = True
    bp = Blueprint("test_api", __name__, url_prefix="/<symbol>")

    @bp.url_value_preprocessor
    def _pull_symbol(endpoint, values):
        pull_symbol(endpoint, values)

    @bp.before_request
    def _auth():
        return check_credentials()

    @bp.route("/ping", methods=["POST"])
    def ping():
        return {"symbol": g.symbol}

    app.register_blueprint(bp)

    with patch(
        "app.api.config",
        {
            "API_USERNAME": "test-user",
            "API_PASSWORD": "test-pass",
        },
    ):
        yield app.test_client()


class TestApiAuth:
    def test_returns_401_without_credentials(self, auth_client):
        response = auth_client.post("/ETH/ping")
        assert response.status_code == 401
        assert response.get_json()["status"] == "error"

    def test_returns_401_with_wrong_credentials(self, auth_client):
        response = auth_client.post("/ETH/ping", auth=("wrong", "creds"))
        assert response.status_code == 401

    def test_allows_request_with_valid_credentials(self, auth_client):
        response = auth_client.post("/ETH/ping", auth=("test-user", "test-pass"))
        assert response.status_code == 200
        assert response.get_json()["symbol"] == "ETH"


class TestSymbolPreprocessor:
    def test_pull_symbol_uppercases_value(self):
        app = Flask(__name__)
        values = {"symbol": "eth-usdt"}

        with app.test_request_context():
            pull_symbol(None, values)
            assert values == {}
            assert g.symbol == "ETH-USDT"


class TestCalcTxFee:
    def test_native_coin_fee(self):
        from app.api.payout import calc_tx_fee

        app = Flask(__name__)
        with app.test_request_context("/ETH/calc-tx-fee/1.0", method="POST"):
            g.symbol = "ETH"
            with patch(
                "app.api.payout.config",
                {
                    "COIN_SYMBOL": "ETH",
                    "CURRENT_NETWORK": "sepolia",
                    "TOKENS": {"sepolia": {"ETH-USDT": {}}},
                },
            ), patch("app.api.payout.Coin") as coin_cls:
                coin_cls.return_value.get_transaction_price.return_value = Decimal(
                    "0.002"
                )
                body = calc_tx_fee(Decimal("1.0"))

        assert body["accounts_num"] == 1
        assert body["fee"] == pytest.approx(0.002)

    def test_unknown_crypto_returns_error(self):
        from app.api.payout import calc_tx_fee

        app = Flask(__name__)
        with app.test_request_context("/UNKNOWN/calc-tx-fee/1.0", method="POST"):
            g.symbol = "UNKNOWN"
            with patch(
                "app.api.payout.config",
                {
                    "COIN_SYMBOL": "ETH",
                    "CURRENT_NETWORK": "sepolia",
                    "TOKENS": {"sepolia": {}},
                },
            ):
                body = calc_tx_fee(Decimal("1.0"))

        assert body["status"] == "error"
