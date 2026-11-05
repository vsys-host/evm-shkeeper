from app.chains import CHAINS, SUPPORTED_COINS, WALLET_ALIASES
from app.chains import arbitrum, avalanche, ethereum, xdc


def test_supported_coins():
    assert SUPPORTED_COINS == (
        "ETH",
        "ARBETH",
        "OPETH",
        "BNB",
        "MATIC",
        "AVAX",
        "XDC",
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


def test_xdc_chain_defaults():
    assert xdc.COIN == "XDC"
    assert xdc.CHAIN_NAME == "xdc"
    assert xdc.DB_NAME == "xdc-shkeeper"
    assert xdc.USE_POA_MIDDLEWARE is True
    assert xdc.ENV["username"] == ("XDC_USERNAME",)


def test_xdc_mainnet_has_usdc_and_audd_tokens():
    assert xdc.TOKENS["main"]["XDC-USDC"]["contract_address"] == (
        "0xfA2958CB79b0491CC627c1557F441eF849Ca8eb1"
    )
    assert xdc.TOKENS["main"]["XDC-AUDD"]["contract_address"] == (
        "0x9fe4E6321eEB7c4bc537570F015e4734b15002B8"
    )
    for token in xdc.TOKENS["main"].values():
        assert token["abi"]
