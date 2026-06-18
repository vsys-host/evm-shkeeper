import decimal
import os
import time
import copy
import requests

from celery.utils.log import get_task_logger
from sqlalchemy import create_engine, text

from . import celery
from .chains import CHAINS
from .config import COIN, config, get_min_token_transfer_threshold
from .encryption import Encryption
from .models import Accounts, db
from .token import Token, Coin, get_all_accounts, make_provider, _get_l1_fee
from .utils import skip_if_running

logger = get_task_logger(__name__)

w3 = make_provider()


def _get_foreign_wallets(db_name):
    """Return all rows from the `wallets` table of a foreign chain's database."""
    engine = create_engine(
        f"mariadb+pymysql://root:shkeeper@mariadb/{db_name}?charset=utf8mb4"
    )
    rows = []
    try:
        with engine.connect() as conn:
            result = conn.execute(
                text("SELECT pub_address, priv_key, type FROM wallets")
            )
            rows = [
                {"pub_address": r[0], "priv_key": r[1], "type": r[2]} for r in result
            ]
    finally:
        engine.dispose()
    return rows


@celery.task()
def make_multipayout(symbol, payout_list, fee):
    logger.warning(f"Start multipayout {symbol} - {payout_list}")
    if symbol == COIN:
        coint_inst = Coin(symbol)
        payout_results = coint_inst.make_multipayout_eth(payout_list, fee)
        post_payout_results.delay(payout_results, symbol)
        return payout_results
    elif symbol in config["TOKENS"][config["CURRENT_NETWORK"]].keys():
        token_inst = Token(symbol)
        payout_results = token_inst.make_token_multipayout(payout_list, fee)
        post_payout_results.delay(payout_results, symbol)
        return payout_results
    else:
        return [{"status": "error", "msg": "Symbol is not in config"}]


@celery.task()
def post_payout_results(data, symbol):
    while True:
        try:
            return requests.post(
                f'http://{config["SHKEEPER_HOST"]}/api/v1/payoutnotify/{symbol}',
                headers={"X-Shkeeper-Backend-Key": config["SHKEEPER_KEY"]},
                json=data,
            )
        except Exception as e:
            logger.exception(f"Shkeeper payout notification failed: {e}")
            time.sleep(10)


@celery.task(bind=True)
@skip_if_running
def refresh_balances(self):
    updated = 0

    try:
        from app import create_app

        app = create_app()
        app.app_context().push()

        list_acccounts = get_all_accounts()
        for account in list_acccounts:
            try:
                pd = Accounts.query.filter_by(address=account).first()
            except Exception:
                db.session.rollback()
                raise Exception(
                    "There was exception during query to the database, try again later"
                )

            acc_balance = decimal.Decimal(
                w3.from_wei(w3.eth.get_balance(account), "ether")
            )
            if Accounts.query.filter_by(address=account, crypto=COIN).first():
                pd = Accounts.query.filter_by(address=account, crypto=COIN).first()
                pd.amount = decimal.Decimal(
                    w3.from_wei(w3.eth.get_balance(account), "ether")
                )
                with app.app_context():
                    db.session.add(pd)
                    db.session.commit()
                    db.session.close()

            have_tokens = False

            for token in config["TOKENS"][config["CURRENT_NETWORK"]].keys():
                token_instance = Token(token)
                token_balance = decimal.Decimal(
                        token_instance.contract.functions.balanceOf(
                            w3.to_checksum_address(account)
                        ).call()
                    )
                normalized_balance = token_balance / decimal.Decimal(
                        10 ** (token_instance.contract.functions.decimals().call())
                    )
                if normalized_balance >= decimal.Decimal(
                    get_min_token_transfer_threshold(token)
                ):
                    have_tokens = copy.deepcopy(token)
                if Accounts.query.filter_by(address=account, crypto=token).first():
                    pd = Accounts.query.filter_by(address=account, crypto=token).first()
                    pd.amount = normalized_balance

                    with app.app_context():
                        db.session.add(pd)
                        db.session.commit()
                        db.session.close()

            if have_tokens in config["TOKENS"][config["CURRENT_NETWORK"]].keys():
                drain_account.delay(have_tokens, account)
            else:
                if acc_balance >= decimal.Decimal(config["MIN_TRANSFER_THRESHOLD"]):
                    drain_account.delay(COIN, account)

            updated = updated + 1

            with app.app_context():
                db.session.add(pd)
                db.session.commit()
                db.session.close()
    finally:
        with app.app_context():
            db.session.remove()
            db.engine.dispose()

    return updated


@celery.task(bind=True)
@skip_if_running
def drain_account(self, symbol, account):
    logger.warning(f"Start draining from account {account} crypto {symbol}")
    # return False
    if symbol == COIN:
        inst = Coin(symbol)
        destination = inst.get_fee_deposit_account()
        results = inst.drain_account(account, destination)
    elif symbol in config["TOKENS"][config["CURRENT_NETWORK"]].keys():
        inst = Token(symbol)
        destination = inst.get_fee_deposit_account()
        results = inst.drain_tocken_account(account, destination)
    else:
        raise Exception("Symbol is not in config")

    return results


@celery.task(bind=True)
@skip_if_running
def create_fee_deposit_account(self):
    logger.warning("Creating fee-deposit account")
    inst = Coin(COIN)
    inst.set_fee_deposit_account()
    return True


def _sweep_native(
    account, destination, balance, fee, multiplier, priv_key, chain_label
):
    """Sweep native coin from `account` to `destination` using the provided private key."""
    gas_price = w3.eth.gas_price
    max_fee_per_gas = (
        decimal.Decimal(w3.from_wei(gas_price, "ether")) + fee
    ) * multiplier
    gas_count = w3.eth.estimate_gas(
        {
            "from": w3.to_checksum_address(account),
            "to": w3.to_checksum_address(destination),
            "value": w3.to_wei(0, "ether"),
        }
    )
    l1_fee = _get_l1_fee(w3)
    can_send = balance - (gas_count * max_fee_per_gas) - l1_fee

    if can_send <= 0:
        logger.warning(
            f"[SWEEP][{chain_label}] {account}: can_send={can_send} after fees, skipping"
        )
        return None

    tx = {
        "from": w3.to_checksum_address(account),
        "to": w3.to_checksum_address(destination),
        "value": w3.to_hex(w3.to_wei(can_send, "ether")),
        "nonce": w3.eth.get_transaction_count(w3.to_checksum_address(account)),
        "gas": w3.to_hex(gas_count),
        "maxFeePerGas": w3.to_hex(w3.to_wei(max_fee_per_gas, "ether")),
        "maxPriorityFeePerGas": w3.to_hex(w3.to_wei(fee, "ether")),
        "chainId": w3.eth.chain_id,
    }
    signed_tx = w3.eth.account.sign_transaction(tx, priv_key)
    txid = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    logger.warning(
        f"[SWEEP][{chain_label}] Native sweep {account} → {destination}: "
        f"{can_send} {COIN}, txid={txid.hex()}"
    )
    return txid.hex()


def _sweep_token(
    account,
    destination,
    token_balance,
    token_inst,
    fee,
    multiplier,
    account_priv_key,
    fee_deposit_priv_key,
    chain_label,
    token_sym,
):
    """Sweep tokens from `account` to `destination`. Seeds gas from fee-deposit if needed."""
    decimals = token_inst.contract.functions.decimals().call()
    token_amount_raw = int(decimal.Decimal(token_balance) * 10**decimals)

    gas = token_inst.contract.functions.transfer(
        destination, token_amount_raw
    ).estimate_gas({"from": account})
    gas = int(gas * multiplier)
    gas_price = w3.eth.gas_price
    max_fee_per_gas = decimal.Decimal(w3.from_wei(gas_price, "ether")) + fee

    dummy_tx = token_inst.contract.functions.transfer(
        destination, token_amount_raw
    ).build_transaction(
        {
            "from": w3.to_checksum_address(account),
            "nonce": w3.eth.get_transaction_count(w3.to_checksum_address(account)),
        }
    )
    l1_fee = _get_l1_fee(w3, dummy_tx["data"])
    need_crypto = (gas * max_fee_per_gas) + l1_fee

    native_balance = decimal.Decimal(
        w3.from_wei(w3.eth.get_balance(w3.to_checksum_address(account)), "ether")
    )
    logger.warning(
        f"[SWEEP][{chain_label}] Token sweep prep {account}: "
        f"token_balance={token_balance} {token_sym}, "
        f"native_balance={native_balance} {COIN}, need_gas={need_crypto} {COIN}"
    )

    # Seed gas from fee-deposit if needed
    if native_balance < need_crypto:
        need_to_send = need_crypto - native_balance
        seed_gas_price = w3.eth.gas_price
        seed_max_fee_per_gas = (
            decimal.Decimal(w3.from_wei(seed_gas_price, "ether")) + fee
        ) * multiplier
        seed_gas = int(
            w3.eth.estimate_gas(
                {
                    "from": w3.to_checksum_address(destination),
                    "to": w3.to_checksum_address(account),
                    "value": w3.to_wei(0, "ether"),
                }
            )
            * multiplier
        )
        seed_tx = {
            "from": w3.to_checksum_address(destination),
            "to": w3.to_checksum_address(account),
            "value": w3.to_hex(w3.to_wei(need_to_send, "ether")),
            "nonce": w3.eth.get_transaction_count(w3.to_checksum_address(destination)),
            "gas": w3.to_hex(seed_gas),
            "maxFeePerGas": w3.to_hex(w3.to_wei(seed_max_fee_per_gas, "ether")),
            "maxPriorityFeePerGas": w3.to_hex(w3.to_wei(fee, "ether")),
            "chainId": w3.eth.chain_id,
        }
        signed_seed = w3.eth.account.sign_transaction(seed_tx, fee_deposit_priv_key)
        seed_txid = w3.eth.send_raw_transaction(signed_seed.raw_transaction)
        logger.warning(
            f"[SWEEP][{chain_label}] Seeded gas to {account}: "
            f"{need_to_send} {COIN}, txid={seed_txid.hex()}"
        )
        time.sleep(int(config["SLEEP_AFTER_SEEDING"]))

    # Transfer tokens
    unsigned_txn = token_inst.contract.functions.transfer(
        w3.to_checksum_address(destination),
        token_amount_raw,
    ).build_transaction(
        {
            "from": w3.to_checksum_address(account),
            "gas": gas,
            "maxFeePerGas": w3.to_wei(max_fee_per_gas, "ether"),
            "maxPriorityFeePerGas": w3.to_wei(fee, "ether"),
            "nonce": w3.eth.get_transaction_count(w3.to_checksum_address(account)),
            "chainId": w3.eth.chain_id,
        }
    )
    signed_txn = w3.eth.account.sign_transaction(
        unsigned_txn, private_key=account_priv_key
    )
    txid = w3.eth.send_raw_transaction(signed_txn.raw_transaction)
    logger.warning(
        f"[SWEEP][{chain_label}] Token sweep {account} → {destination}: "
        f"{token_balance} {token_sym}, txid={txid.hex()}"
    )
    return txid.hex()


@celery.task(bind=True)
@skip_if_running
def sweep_foreign_chains(self):
    """
    Scan all foreign-chain databases for accounts that hold funds on the current chain,
    then sweep those funds to the current chain's fee-deposit account.

    Runs in dry-run mode by default (logs only, no transactions).
    Set SWEEP_FOREIGN_CHAINS_ENABLED=1 (or true/yes/on) to perform actual sweeps.
    Schedule via SWEEP_FOREIGN_CHAINS_EVERY_SECONDS (default 0 = disabled).
    """
    dry_run = os.environ.get("SWEEP_FOREIGN_CHAINS_ENABLED", "").lower() not in (
        "1",
        "true",
        "yes",
        "on",
    )
    api_delay = float(os.environ.get("SWEEP_FOREIGN_CHAINS_API_CALL_DELAY", "0"))
    mode_label = "[DRY-RUN]" if dry_run else "[LIVE]"
    logger.warning(
        f"[SWEEP] Starting sweep_foreign_chains — mode={mode_label}, current_chain={COIN}"
        + (
            ". Set SWEEP_FOREIGN_CHAINS_ENABLED=1 to perform actual sweeps."
            if dry_run
            else "."
        )
    )

    app = None
    try:
        from app import create_app

        app = create_app()
        app.app_context().push()

        coin_inst = Coin(COIN)
        fee_deposit_addr = coin_inst.get_fee_deposit_account()
        fee_deposit_priv_key = (
            None if dry_run else coin_inst.get_seed_from_address(fee_deposit_addr)
        )
        fee = coin_inst.get_max_priority_fee()
        multiplier = decimal.Decimal(config["MULTIPLIER"])
        current_network = config["CURRENT_NETWORK"]
        tokens_on_current_chain = config["TOKENS"].get(current_network, {})
        token_instances = {sym: Token(sym) for sym in tokens_on_current_chain}

        global_summary = {
            "chains_checked": 0,
            "total_accounts": 0,
            "total_with_native": 0,
            "total_native_amount": decimal.Decimal(0),
            "total_token_accounts": {},
            "total_tokens": {},
            "total_swept_native": 0,
            "total_swept_native_amount": decimal.Decimal(0),
            "total_swept_token_accounts": {},
            "total_swept_tokens": {},
        }

        for chain_coin, chain_module in CHAINS.items():
            if chain_coin == COIN:
                continue

            foreign_db = chain_module.DB_NAME
            logger.warning(
                f"[SWEEP] Scanning foreign chain {chain_coin} (db={foreign_db})"
            )

            try:
                wallets = _get_foreign_wallets(foreign_db)
            except Exception as e:
                logger.warning(
                    f"[SWEEP] Cannot connect to foreign DB {foreign_db}: {e}"
                )
                continue

            logger.warning(
                f"[SWEEP][{chain_coin}] Retrieved {len(wallets)} wallet(s) from {foreign_db}"
            )

            chain_summary = {
                "checked": 0,
                "with_native": 0,
                "native_total": decimal.Decimal(0),
                "token_accounts": {sym: 0 for sym in tokens_on_current_chain},
                "token_totals": {
                    sym: decimal.Decimal(0) for sym in tokens_on_current_chain
                },
                "swept_native": 0,
                "swept_native_total": decimal.Decimal(0),
                "swept_token_accounts": {sym: 0 for sym in tokens_on_current_chain},
                "swept_token_totals": {
                    sym: decimal.Decimal(0) for sym in tokens_on_current_chain
                },
            }

            for wallet in wallets:
                account = wallet["pub_address"]
                try:
                    checksum_addr = w3.to_checksum_address(account)
                except Exception:
                    logger.warning(
                        f"[SWEEP][{chain_coin}] Invalid address {account!r}, skipping"
                    )
                    continue

                chain_summary["checked"] += 1

                # --- Native coin balance ---
                try:
                    native_balance = decimal.Decimal(
                        w3.from_wei(w3.eth.get_balance(checksum_addr), "ether")
                    )
                except Exception as e:
                    logger.exception(
                        f"[SWEEP][{chain_coin}] get_balance failed for {checksum_addr}: {e}"
                    )
                    native_balance = decimal.Decimal(0)
                if api_delay:
                    time.sleep(api_delay)

                if native_balance >= decimal.Decimal(config["MIN_TRANSFER_THRESHOLD"]):
                    chain_summary["with_native"] += 1
                    chain_summary["native_total"] += native_balance
                    logger.warning(
                        f"[SWEEP][{chain_coin}] {checksum_addr} (type={wallet['type']}) "
                        f"holds {native_balance} {COIN} on current chain"
                    )

                # --- Token balances (sweep before native to preserve gas) ---
                for token_sym, token_inst in token_instances.items():
                    try:
                        raw_balance = decimal.Decimal(
                            token_inst.contract.functions.balanceOf(
                                checksum_addr
                            ).call()
                        )
                        decimals = token_inst.contract.functions.decimals().call()
                        token_balance = raw_balance / decimal.Decimal(10**decimals)
                        if api_delay:
                            time.sleep(api_delay)
                    except Exception as e:
                        logger.exception(
                            f"[SWEEP][{chain_coin}] balanceOf {token_sym} failed "
                            f"for {checksum_addr}: {e}"
                        )
                        continue

                    threshold = decimal.Decimal(
                        get_min_token_transfer_threshold(token_sym)
                    )
                    if token_balance >= threshold:
                        chain_summary["token_accounts"][token_sym] += 1
                        chain_summary["token_totals"][token_sym] += token_balance
                        logger.warning(
                            f"[SWEEP][{chain_coin}] {checksum_addr} (type={wallet['type']}) "
                            f"holds {token_balance} {token_sym} on current chain"
                        )
                        if not dry_run:
                            if checksum_addr == w3.to_checksum_address(
                                fee_deposit_addr
                            ):
                                logger.warning(
                                    f"[SWEEP][{chain_coin}] {checksum_addr} is the current "
                                    f"fee-deposit address, skipping token sweep"
                                )
                            else:
                                try:
                                    _sweep_token(
                                        checksum_addr,
                                        fee_deposit_addr,
                                        token_balance,
                                        token_inst,
                                        fee,
                                        multiplier,
                                        Encryption.decrypt(wallet["priv_key"]),
                                        fee_deposit_priv_key,
                                        chain_coin,
                                        token_sym,
                                    )
                                    chain_summary["swept_token_accounts"][
                                        token_sym
                                    ] += 1
                                    chain_summary["swept_token_totals"][token_sym] += (
                                        token_balance
                                    )
                                except Exception as e:
                                    logger.exception(
                                        f"[SWEEP][{chain_coin}] Token sweep failed "
                                        f"for {checksum_addr} {token_sym}: {e}"
                                    )

                # --- Native sweep (after tokens, so gas is not prematurely drained) ---
                if native_balance >= decimal.Decimal(config["MIN_TRANSFER_THRESHOLD"]):
                    if not dry_run:
                        if checksum_addr == w3.to_checksum_address(fee_deposit_addr):
                            logger.warning(
                                f"[SWEEP][{chain_coin}] {checksum_addr} is the current "
                                f"fee-deposit address, skipping native sweep"
                            )
                        else:
                            try:
                                _sweep_native(
                                    checksum_addr,
                                    fee_deposit_addr,
                                    native_balance,
                                    fee,
                                    multiplier,
                                    Encryption.decrypt(wallet["priv_key"]),
                                    chain_coin,
                                )
                                chain_summary["swept_native"] += 1
                                chain_summary["swept_native_total"] += native_balance
                            except Exception as e:
                                logger.exception(
                                    f"[SWEEP][{chain_coin}] Native sweep failed "
                                    f"for {checksum_addr}: {e}"
                                )

            # Per-chain summary
            tokens_found = {
                sym: {"accounts": chain_summary["token_accounts"][sym], "total": amt}
                for sym, amt in chain_summary["token_totals"].items()
                if amt > 0
            }
            tokens_swept = {
                sym: {
                    "accounts": chain_summary["swept_token_accounts"][sym],
                    "total": amt,
                }
                for sym, amt in chain_summary["swept_token_totals"].items()
                if amt > 0
            }
            sweep_info = (
                f" | swept_native={chain_summary['swept_native']}"
                f" ({chain_summary['swept_native_total']} {COIN})"
                f" swept_tokens={tokens_swept}"
                if not dry_run
                else ""
            )
            logger.warning(
                f"{mode_label}[SWEEP][{chain_coin}/{foreign_db}] "
                f"checked={chain_summary['checked']} "
                f"with_native={chain_summary['with_native']} "
                f"native_total={chain_summary['native_total']} {COIN} "
                f"tokens={tokens_found}" + sweep_info
            )

            global_summary["chains_checked"] += 1
            global_summary["total_accounts"] += chain_summary["checked"]
            global_summary["total_with_native"] += chain_summary["with_native"]
            global_summary["total_native_amount"] += chain_summary["native_total"]
            global_summary["total_swept_native"] += chain_summary["swept_native"]
            global_summary["total_swept_native_amount"] += chain_summary[
                "swept_native_total"
            ]
            for sym, info in tokens_found.items():
                g = global_summary["total_tokens"].setdefault(
                    sym, {"accounts": 0, "total": decimal.Decimal(0)}
                )
                g["accounts"] += info["accounts"]
                g["total"] += info["total"]
            for sym, info in tokens_swept.items():
                g = global_summary["total_swept_tokens"].setdefault(
                    sym, {"accounts": 0, "total": decimal.Decimal(0)}
                )
                g["accounts"] += info["accounts"]
                g["total"] += info["total"]

        # Global summary
        global_sweep_info = (
            f" | swept_native={global_summary['total_swept_native']}"
            f" ({global_summary['total_swept_native_amount']} {COIN})"
            f" swept_tokens={global_summary['total_swept_tokens']}"
            if not dry_run
            else ""
        )
        logger.warning(
            f"{mode_label}[SWEEP] Global summary —"
            f" chains_checked={global_summary['chains_checked']}"
            f" total_accounts={global_summary['total_accounts']}"
            f" total_with_native={global_summary['total_with_native']}"
            f" total_native={global_summary['total_native_amount']} {COIN}"
            f" tokens={global_summary['total_tokens']}" + global_sweep_info
        )

    finally:
        if app is not None:
            with app.app_context():
                db.session.remove()
                db.engine.dispose()


@celery.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    # sender.add_periodic_task(
    #     crontab(hour=0, minute=0),
    #     transfer_unused_fee.s(),
    # )

    # Update cached account balances
    sender.add_periodic_task(
        int(config["UPDATE_TOKEN_BALANCES_EVERY_SECONDS"]), refresh_balances.s()
    )

    # Sweep funds misrouted from foreign chains (disabled by default)
    # Set SWEEP_FOREIGN_CHAINS_EVERY_SECONDS > 0 to enable scheduling.
    # Set SWEEP_FOREIGN_CHAINS_ENABLED=1 to perform actual sweeps (default: dry-run).
    _sweep_interval = int(os.environ.get("SWEEP_FOREIGN_CHAINS_EVERY_SECONDS", "0"))
    if _sweep_interval > 0:
        sender.add_periodic_task(_sweep_interval, sweep_foreign_chains.s())
