import os
from decimal import Decimal

from .chains import CHAINS, SUPPORTED_COINS, WALLET_ALIASES


def _env_first(*keys, default=None):
    for key in keys:
        value = os.environ.get(key)
        if value is not None:
            return value
    return default


def _env_bool(*keys, default=False):
    value = _env_first(*keys)
    if value is None:
        return default
    return value.lower() in ("1", "true", "yes", "on")


def detect_active_coin():
    coin = _env_first("WALLET", "COIN_SYMBOL")
    if not coin:
        raise ValueError(
            "WALLET env variable is not set. "
            f'Supported coins: {", ".join(SUPPORTED_COINS)}'
        )
    coin = WALLET_ALIASES.get(coin.upper(), coin.upper())
    if coin not in SUPPORTED_COINS:
        raise ValueError(
            f'Unsupported coin: {coin}. Supported: {", ".join(SUPPORTED_COINS)}'
        )
    return coin


def detect_network(chain):
    return _env_first(*chain.ENV["network"], default=chain.ENV["network_default"])


def detect_api_username(chain):
    return _env_first(*chain.ENV["username"], default="shkeeper")


def detect_api_password(chain):
    return _env_first(*chain.ENV["password"], default="shkeeper")


COIN = detect_active_coin()
_chain = CHAINS[COIN]
_coin_defaults = _chain.DEFAULTS
_COIN_NETWORK = detect_network(_chain)

config = {
    "COIN": COIN,
    "COIN_SYMBOL": COIN,
    "COIN_NETWORK": _COIN_NETWORK,
    "CURRENT_NETWORK": _COIN_NETWORK,
    "FULLNODE_URL": _env_first("FULLNODE_URL", default=_chain.FULLNODE_URL),
    "FULLNODE_TIMEOUT": os.environ.get("FULLNODE_TIMEOUT", "60"),
    "CHECK_NEW_BLOCK_EVERY_SECONDS": os.environ.get("CHECK_NEW_BLOCK_EVERY_SECONDS", 2),
    "TOKENS": _chain.TOKENS,
    "DEBUG": os.environ.get("DEBUG", False),
    "LOGGING_LEVEL": os.environ.get("LOGGING_LEVEL", "INFO"),
    "SQLALCHEMY_DATABASE_URI": _env_first(
        "SQLALCHEMY_DATABASE_URI",
        default=f"mariadb+pymysql://root:shkeeper@mariadb/{_chain.DB_NAME}?charset=utf8mb4",
    ),
    "UPDATE_TOKEN_BALANCES_EVERY_SECONDS": int(
        os.environ.get("UPDATE_TOKEN_BALANCES_EVERY_SECONDS", 3600)
    ),
    "API_USERNAME": detect_api_username(_chain),
    "API_PASSWORD": detect_api_password(_chain),
    "SHKEEPER_KEY": os.environ.get("SHKEEPER_BACKEND_KEY", "shkeeper"),
    "SHKEEPER_HOST": os.environ.get("SHKEEPER_HOST", "shkeeper:5000"),
    "MULTIPLIER": os.environ.get("MULTIPLIER", "1.5"),
    "PAYOUT_MULTIPLIER": os.environ.get("PAYOUT_MULTIPLIER", "2"),
    "PRICE_MULTIPLIER": os.environ.get("PRICE_MULTIPLIER", "0.9"),
    "MAX_PRIORITY_FEE": _env_first(
        "MAX_PRIORITY_FEE",
        default=_coin_defaults["MAX_PRIORITY_FEE"],
    ),
    "MAX_PRIORITY_FEE_MODE": os.environ.get("MAX_PRIORITY_FEE_MODE", "static"),
    "DYNAMIC_MAX_PRIORITY_FEE_LIMIT": os.environ.get(
        "DYNAMIC_MAX_PRIORITY_FEE_LIMIT",
        "0.0000000005",
    ),
    "DYNAMIC_MAX_PRIORITY_FEE_PERCENTILE": os.environ.get(
        "DYNAMIC_MAX_PRIORITY_FEE_PERCENTILE",
        "20",
    ),
    "SLEEP_AFTER_SEEDING": int(
        _env_first("SLEEP_AFTER_SEEDING", default=_coin_defaults["SLEEP_AFTER_SEEDING"])
    ),
    "ACCOUNT_PASSWORD": os.environ.get("ACCOUNT_PASSWORD", "shkeeper"),
    "REDIS_HOST": os.environ.get("REDIS_HOST", "localhost"),
    "LAST_BLOCK_LOCKED": os.environ.get("LAST_BLOCK_LOCKED", "True"),
    "MIN_TRANSFER_THRESHOLD": Decimal(
        os.environ.get("MIN_TRANSFER_THRESHOLD", "0.001")
    ),
    "MIN_TOKEN_TRANSFER_THRESHOLD": Decimal(
        os.environ.get("MIN_TOKEN_TRANSFER_THRESHOLD", "0.5")
    ),
    "BLOCK_SCANNER_BATCH_SIZE": int(
        _env_first(
            "BLOCK_SCANNER_BATCH_SIZE",
            default=_coin_defaults["BLOCK_SCANNER_BATCH_SIZE"],
        )
    ),
    "BLOCK_SCAN_LAG": int(os.environ.get("BLOCK_SCAN_LAG", 2)),
    "ENABLE_INTERNAL_TX_SCAN": _env_bool(
        "ENABLE_INTERNAL_TX_SCAN",
        default=_coin_defaults["ENABLE_INTERNAL_TX_SCAN"],
    ),
    "ENABLE_GETH_METRICS": _env_bool(
        "ENABLE_GETH_METRICS",
        default=_coin_defaults["ENABLE_GETH_METRICS"],
    ),
    "ETHEREUM_HOST": _env_first(
        "ETHEREUM_HOST",
        default=_coin_defaults["ETHEREUM_HOST"],
    ),
    "UNLOCK_ACCOUNT_TIME": os.environ.get(
        "UNLOCK_ACCOUNT_TIME",
        _coin_defaults["UNLOCK_ACCOUNT_TIME"],
    ),
    "FORCE_ADD_WALLETS_TO_DB": os.environ.get("FORCE_ADD_WALLETS_TO_DB", "False"),
    "L1_GAS_PRICE_ORACLE": getattr(_chain, "L1_GAS_PRICE_ORACLE", None),
    "USE_POA_MIDDLEWARE": getattr(_chain, "USE_POA_MIDDLEWARE", False),
}


def get_min_token_transfer_threshold(symbol):
    return config["TOKENS"][config["COIN_NETWORK"]][symbol].get(
        "min_transfer_threshold",
        config["MIN_TOKEN_TRANSFER_THRESHOLD"],
    )


def get_contract_address(symbol):
    return config["TOKENS"][config["COIN_NETWORK"]][symbol]["contract_address"]


def get_contract_abi(symbol):
    return config["TOKENS"][config["COIN_NETWORK"]][symbol]["abi"]
