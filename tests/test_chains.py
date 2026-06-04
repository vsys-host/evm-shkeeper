from app.chains import CHAINS, SUPPORTED_COINS, WALLET_ALIASES
from app.chains import arbitrum, avalanche, ethereum


def test_supported_coins():
    assert SUPPORTED_COINS == (
        "ETH",
        "ARBETH",
        "OPETH",
        "BNB",
        "MATIC",
        "AVAX",
    )


def test_wallet_alias_maps_arb_to_arbeth():
    assert WALLET_ALIASES["ARB"] == "ARBETH"


def test_chains_registry_has_required_fields():
    for coin, module in CHAINS.items():
        assert module.COIN == coin
        assert module.DB_NAME
        assert module.FULLNODE_URL
        assert module.ENV["network"]
        assert module.DEFAULTS
        assert "main" in module.TOKENS or "sepolia" in module.TOKENS


def test_ethereum_chain_defaults():
    assert ethereum.COIN == "ETH"
    assert ethereum.DB_NAME == "ethereum-shkeeper"
    assert ethereum.FULLNODE_URL == "http://ethereum:8545"
    assert ethereum.DEFAULTS["ENABLE_INTERNAL_TX_SCAN"] is True


def test_arbitrum_chain_defaults():
    assert arbitrum.COIN == "ARBETH"
    assert arbitrum.DB_NAME == "arbitrum-shkeeper"
    assert arbitrum.DEFAULTS["ENABLE_INTERNAL_TX_SCAN"] is False


def test_ethereum_sepolia_has_usdt_token():
    assert "ETH-USDT" in ethereum.TOKENS["sepolia"]


def test_arbitrum_sepolia_has_usdc_token():
    assert "ARB-USDC" in arbitrum.TOKENS["sepolia"]


def test_avalanche_chain_defaults():
    assert avalanche.COIN == "AVAX"
    assert avalanche.DB_NAME == "avalanche-shkeeper"
    assert avalanche.FULLNODE_URL == "http://avalanche:9650/ext/bc/C/rpc"
    assert avalanche.USE_POA_MIDDLEWARE is True
    assert avalanche.WALLET_ALIASES == ("AVALANCHE",)


def test_wallet_alias_maps_avalanche_to_avax():
    assert WALLET_ALIASES["AVALANCHE"] == "AVAX"


def test_avalanche_mainnet_has_usdt_token():
    assert "AVALANCHE-USDT" in avalanche.TOKENS["main"]
