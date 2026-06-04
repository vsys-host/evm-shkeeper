import sys
from decimal import Decimal

import pytest

from app.chains import CHAINS

# app/__init__.py re-exports config dict as app.config; use the real module.
config_module = sys.modules["app.config"]


class TestEnvHelpers:
    def test_env_first_returns_first_set_key(self, monkeypatch):
        monkeypatch.setenv("A", "1")
        monkeypatch.setenv("B", "2")
        assert config_module._env_first("A", "B", default="x") == "1"

    def test_env_first_returns_default_when_missing(self, monkeypatch):
        monkeypatch.delenv("MISSING_KEY", raising=False)
        assert config_module._env_first("MISSING_KEY", default="fallback") == "fallback"

    def test_env_bool_parses_truthy_values(self, monkeypatch):
        for value in ("1", "true", "yes", "on", "TRUE"):
            monkeypatch.setenv("FLAG", value)
            assert config_module._env_bool("FLAG") is True

    def test_env_bool_returns_default_when_unset(self, monkeypatch):
        monkeypatch.delenv("FLAG", raising=False)
        assert config_module._env_bool("FLAG", default=True) is True
        assert config_module._env_bool("FLAG", default=False) is False


class TestDetectActiveCoin:
    def test_detect_eth_from_wallet(self, monkeypatch):
        monkeypatch.setenv("WALLET", "ETH")
        monkeypatch.delenv("COIN_SYMBOL", raising=False)
        assert config_module.detect_active_coin() == "ETH"

    def test_detect_arbeth_from_arb_alias(self, monkeypatch):
        monkeypatch.setenv("WALLET", "arb")
        monkeypatch.delenv("COIN_SYMBOL", raising=False)
        assert config_module.detect_active_coin() == "ARBETH"

    def test_raises_when_wallet_missing(self, monkeypatch):
        monkeypatch.delenv("WALLET", raising=False)
        monkeypatch.delenv("COIN_SYMBOL", raising=False)
        with pytest.raises(ValueError, match="WALLET env variable is not set"):
            config_module.detect_active_coin()

    def test_raises_for_unsupported_coin(self, monkeypatch):
        monkeypatch.setenv("WALLET", "BTC")
        with pytest.raises(ValueError, match="Unsupported coin"):
            config_module.detect_active_coin()


class TestDetectNetworkAndCredentials:
    def test_detect_network_uses_chain_env_keys(self, monkeypatch, ethereum_chain):
        monkeypatch.setenv("ETH_NETWORK", "main")
        assert config_module.detect_network(ethereum_chain) == "main"

    def test_detect_network_falls_back_to_default(self, monkeypatch, ethereum_chain):
        for key in ethereum_chain.ENV["network"]:
            monkeypatch.delenv(key, raising=False)
        assert config_module.detect_network(ethereum_chain) == "sepolia"

    def test_detect_api_username_from_env(self, monkeypatch, arbitrum_chain):
        monkeypatch.setenv("ARB_USERNAME", "arb-user")
        assert config_module.detect_api_username(arbitrum_chain) == "arb-user"

    def test_detect_api_password_default(self, monkeypatch, ethereum_chain):
        for key in ethereum_chain.ENV["password"]:
            monkeypatch.delenv(key, raising=False)
        assert config_module.detect_api_password(ethereum_chain) == "shkeeper"


class TestRuntimeConfig:
    def test_loaded_config_uses_eth_chain(self):
        assert config_module.COIN == "ETH"
        assert config_module.config["COIN_SYMBOL"] == "ETH"
        assert config_module.config["FULLNODE_URL"] == CHAINS["ETH"].FULLNODE_URL
        assert "sepolia" in config_module.config["TOKENS"]

    def test_get_contract_address_for_sepolia_token(self):
        address = config_module.get_contract_address("ETH-USDT")
        assert (
            address == CHAINS["ETH"].TOKENS["sepolia"]["ETH-USDT"]["contract_address"]
        )

    def test_get_min_token_transfer_threshold_uses_default(self, monkeypatch):
        monkeypatch.setitem(config_module.config, "COIN_NETWORK", "sepolia")
        threshold = config_module.get_min_token_transfer_threshold("ETH-USDT")
        assert threshold == config_module.config["MIN_TOKEN_TRANSFER_THRESHOLD"]

    def test_get_min_token_transfer_threshold_uses_per_token_override(
        self, monkeypatch
    ):
        monkeypatch.setitem(config_module.config, "COIN_NETWORK", "sepolia")
        tokens = config_module.config["TOKENS"]
        tokens["sepolia"]["ETH-USDT"]["min_transfer_threshold"] = Decimal("2.5")
        try:
            assert config_module.get_min_token_transfer_threshold(
                "ETH-USDT"
            ) == Decimal("2.5")
        finally:
            tokens["sepolia"]["ETH-USDT"].pop("min_transfer_threshold", None)
