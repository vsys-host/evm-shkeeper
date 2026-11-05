from . import arbitrum, avalanche, bnb, ethereum, optimism, polygon, xdc

_CHAIN_MODULES = (ethereum, arbitrum, optimism, bnb, polygon, avalanche, xdc)

SUPPORTED_COINS = tuple(module.COIN for module in _CHAIN_MODULES)

CHAINS = {module.COIN: module for module in _CHAIN_MODULES}

WALLET_ALIASES = {
    alias: module.COIN for module in _CHAIN_MODULES for alias in module.WALLET_ALIASES
}
