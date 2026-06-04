from flask import g
from web3 import Web3

from ..config import config
from ..models import Accounts, Settings, Wallets, db
from ..encryption import Encryption
from ..token import Token, Coin, get_all_accounts, make_provider
from ..logging import logger
from ..services.transaction_lookup import TransactionLookupService
from . import api
from app import create_app

w3 = make_provider()

w3l = Web3()

app = create_app()
app.app_context().push()


@api.post("/generate-address")
def generate_new_address():
    acc = w3l.eth.account.create()
    crypto_str = str(g.symbol)
    e = Encryption
    logger.warning(f"Saving wallet {acc.address} to DB")
    try:
        with app.app_context():
            db.session.add(
                Wallets(
                    pub_address=acc.address,
                    priv_key=e.encrypt(acc.key.hex()),
                    type="regular",
                )
            )
            db.session.add(
                Accounts(
                    address=acc.address,
                    crypto=crypto_str,
                    amount=0,
                )
            )
            db.session.commit()
            db.session.close()
            db.engine.dispose()
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()

    logger.info("Added new address and wallet added to DB")
    return {"status": "success", "address": acc.address}


@api.post("/balance")
def get_balance():
    crypto_str = str(g.symbol)
    try:
        if crypto_str == config["COIN_SYMBOL"]:
            inst = Coin(config["COIN_SYMBOL"])
            balance = inst.get_fee_deposit_coin_balance()
        else:
            if crypto_str in config["TOKENS"][config["CURRENT_NETWORK"]].keys():
                token_instance = Token(crypto_str)
                balance = token_instance.get_fee_deposit_token_balance()
            else:
                return {"status": "error", "msg": "token is not defined in config"}
    except ValueError as exc:
        logger.warning("Balance request failed for %s: %s", crypto_str, exc)
        return {"status": "error", "msg": str(exc)}
    return {"status": "success", "balance": balance}


@api.post("/status")
def get_status():
    with app.app_context():
        pd = Settings.query.filter_by(name="last_block").first()

    last_checked_block_number = int(pd.value)
    block = w3.eth.get_block(w3.to_hex(last_checked_block_number))
    return {"status": "success", "last_block_timestamp": block["timestamp"]}


@api.post("/transaction/<txid>")
def get_transaction(txid):
    result = TransactionLookupService(w3).lookup(g.symbol, txid)
    logger.warning(result)
    return result


@api.post("/dump")
def dump():
    w = Coin(config["COIN_SYMBOL"])
    all_wallets = w.get_dump()
    return all_wallets


@api.post("/fee-deposit-account")
def get_fee_deposit_account():
    if g.symbol == config["COIN_SYMBOL"]:
        coin_instance = Coin(g.symbol)
        return {
            "account": coin_instance.get_fee_deposit_account(),
            "balance": coin_instance.get_fee_deposit_coin_balance(),
        }
    elif g.symbol in config["TOKENS"][config["CURRENT_NETWORK"]].keys():
        token_instance = Token(g.symbol)
        return {
            "account": token_instance.get_fee_deposit_account(),
            "balance": token_instance.get_fee_deposit_account_balance(),
        }
    else:
        raise Exception(f"Symbol {g.symbol} cannot be processed")


@api.post("/get_all_addresses")
def get_all_addresses():
    all_addresses_list = get_all_accounts()
    return all_addresses_list
