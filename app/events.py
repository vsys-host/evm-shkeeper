import time

import ahocorasick
import requests as rq
from .config import config
from .logging import logger
from .models import Settings, db
from .token import Token, get_all_accounts, make_provider
from .utils import chain_head, tx_input_hex

w3 = make_provider()


def _network_key() -> str:
    return config["CURRENT_NETWORK"]


def _token_contract_addresses() -> list[str]:
    """Collect contract addresses of all configured tokens on active network."""
    network = _network_key()
    return [
        config["TOKENS"][network][token]["contract_address"]
        for token in config["TOKENS"][network]
    ]


def handle_event(transaction) -> None:
    logger.info("new transaction: %r", transaction)


def walletnotify_shkeeper(symbol: str, txid: str) -> bool:
    """Notify SHKeeper about a transaction."""
    logger.warning("Notifying about %s/%s", symbol, txid)
    url = f'http://{config["SHKEEPER_HOST"]}/api/v1/walletnotify/{symbol}/{txid}'
    headers = {"X-Shkeeper-Backend-Key": config["SHKEEPER_KEY"]}

    while True:
        try:
            response = rq.post(url, headers=headers).json()
            if response.get("status") == "success":
                logger.warning("Notification success %s/%s", symbol, txid)
                return True
            logger.warning(
                "Notification failed %s/%s, response: %s",
                symbol,
                txid,
                response,
            )
            time.sleep(5)
        except Exception as exc:
            logger.warning("Notification error %s/%s: %s", symbol, txid, exc)
            time.sleep(10)


def _should_drain(sender: str, recipient: str, accounts: set, ref_block: int) -> bool:
    return (
        recipient in accounts
        and sender not in accounts
        and (chain_head(w3) - ref_block) < 40
    )


def process_block(block, accounts: set, last_batch_block: int) -> list[str]:
    """Process native coin transactions (ETH or chain coin)."""
    from .tasks import drain_account

    block_txs = []

    for transaction in block.transactions:
        tx_from = transaction["from"]
        tx_to = transaction.get("to")

        if tx_to is None:
            continue

        is_incoming = tx_to in accounts and tx_from not in accounts

        if tx_from in accounts or tx_to in accounts:
            handle_event(transaction)

            block_txs.append(tx_to.lower())
            block_txs.append(tx_from.lower())

            if is_incoming:
                walletnotify_shkeeper(
                    config["COIN_SYMBOL"],
                    transaction["hash"].hex(),
                )

            if _should_drain(tx_from, tx_to, accounts, last_batch_block):
                drain_account.delay(config["COIN_SYMBOL"], tx_to)

    return block_txs


def process_internal_transactions(
    block,
    accounts: set,
    token_addresses: list[str],
    block_txs: list[str],
) -> None:
    """Detect internal ETH transfers inside contract input data."""
    if not config.get("ENABLE_INTERNAL_TX_SCAN"):
        return

    account_fragments = {addr[2:].lower() for addr in accounts if len(addr) > 2}
    if not account_fragments:
        return

    automaton = ahocorasick.Automaton()
    for idx, fragment in enumerate(account_fragments):
        automaton.add_word(fragment, (idx, fragment))
    automaton.make_automaton()

    token_addrs_lower = {addr.lower() for addr in token_addresses}

    transactions = block["transactions"] if isinstance(block, dict) else block.transactions
    block_number = block["number"] if isinstance(block, dict) else block.number

    block_internal_txs = []

    for transaction in transactions:
        tx_to = transaction.get("to")
        if tx_to is None:
            continue

        if tx_to.lower() in token_addrs_lower:
            continue

        tx_input = tx_input_hex(transaction)
        if len(tx_input) <= 6:
            continue

        for _end_index, (_idx, found_address) in automaton.iter(tx_input):
            full_address = f"0x{found_address}"
            address_lower = full_address.lower()

            if address_lower in block_txs:
                logger.warning(
                    "There was already a regular %s tx to %s in block %s",
                    config["COIN_SYMBOL"],
                    full_address,
                    block_number,
                )
                continue

            if address_lower in block_internal_txs:
                logger.warning(
                    "Duplicate internal tx to %s in block %s skipped",
                    full_address,
                    block_number,
                )
                continue

            logger.warning(
                "Found internal tx %s to %s",
                transaction["hash"].hex(),
                full_address,
            )
            block_internal_txs.append(address_lower)
            walletnotify_shkeeper(
                config["COIN_SYMBOL"],
                transaction["hash"].hex(),
            )
            break


def process_token_transfers(
    token_names: list[str],
    accounts: set,
    start_block: int,
    end_block: int,
) -> None:
    from .tasks import drain_account

    for token_name in token_names:
        token_instance = Token(token_name)
        transfers = token_instance.get_all_transfers(start_block, end_block)

        for transaction in transfers:
            from_addr = token_instance.provider.to_checksum_address(transaction["from"])
            to_addr = token_instance.provider.to_checksum_address(transaction["to"])

            is_incoming = from_addr not in accounts and to_addr in accounts

            if from_addr not in accounts and to_addr not in accounts:
                continue

            handle_event(transaction)
            if is_incoming:
                walletnotify_shkeeper(token_name, transaction["txid"])

            if _should_drain(from_addr, to_addr, accounts, end_block):
                drain_account.delay(token_name, to_addr)


def _save_last_block(app, block_number: int) -> None:
    settings = Settings.query.filter_by(name="last_block").first()
    settings.value = str(block_number)

    with app.app_context():
        db.session.add(settings)
        db.session.commit()
        db.session.close()


def _init_last_block(app) -> None:
    already_set = Settings.query.filter_by(name="last_block").first()
    locked = config["LAST_BLOCK_LOCKED"].lower() == "true"

    if not already_set and not locked:
        head = chain_head(w3)
        logger.warning("Setting last_block to chain head %s (not in DB)", head)

        with app.app_context():
            db.session.add(Settings(name="last_block", value=str(head)))
            db.session.commit()
            db.session.close()
            db.session.remove()
            db.engine.dispose()


# ── main scan loop ───────────────────────────────────────────────────────

def log_loop(last_checked_block: int, check_interval: int) -> None:
    from app import create_app

    app = create_app()
    app.app_context().push()

    network = _network_key()
    token_names = list(config["TOKENS"][network].keys())
    token_addresses = _token_contract_addresses()
    batch_size = int(config["BLOCK_SCANNER_BATCH_SIZE"])
    scan_lag = int(config["BLOCK_SCAN_LAG"])

    while True:
        latest_block = chain_head(w3)
        target_block = max(0, latest_block - scan_lag)

        accounts = set(get_all_accounts())

        if last_checked_block > latest_block:
            logger.warning(
                "last_checked_block (%s) > chain head (%s), waiting",
                last_checked_block,
                latest_block,
            )
            time.sleep(check_interval)
            continue

        if last_checked_block >= target_block:
            logger.debug(
                "Within %s blocks of head (checked=%s, head=%s), waiting",
                scan_lag,
                last_checked_block,
                latest_block,
            )
            time.sleep(check_interval)
            continue

        while last_checked_block < target_block:
            start = last_checked_block + 1
            end = min(last_checked_block + batch_size, target_block)

            logger.warning("Scanning blocks %s - %s", start, end)

            with w3.batch_requests() as batch:
                for block_num in range(start, end + 1):
                    batch.add(w3.eth.get_block(block_num, True))

                for block in batch.execute():
                    block_txs = process_block(block, accounts, end)
                    process_internal_transactions(
                        block,
                        accounts,
                        token_addresses,
                        block_txs,
                    )

            process_token_transfers(token_names, accounts, start, end)

            last_checked_block = end
            _save_last_block(app, end)

        time.sleep(check_interval)


# ── entry point ──────────────────────────────────────────────────────────

def events_listener() -> None:
    from app import create_app

    app = create_app()
    app.app_context().push()

    while True:
        if not get_all_accounts():
            logger.warning("No accounts yet — waiting 60 s before scanning")
            time.sleep(60)
            continue

        _init_last_block(app)

        try:
            settings = Settings.query.filter_by(name="last_block").first()
            log_loop(
                int(settings.value),
                int(config["CHECK_NEW_BLOCK_EVERY_SECONDS"]),
            )
        except Exception as exc:
            logger.exception("Scanner crashed: %s", exc)
            time.sleep(60)
