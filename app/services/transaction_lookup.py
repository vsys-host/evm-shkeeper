from decimal import Decimal
from typing import Any, Optional

from ..config import config
from ..logging import logger
from ..token import Token, get_all_accounts
from ..utils import tx_input_hex


def resolve_transaction_direction(
    tx_from: Optional[str],
    tx_to: Optional[str],
    known_accounts: set,
    provider=None,
) -> tuple[Optional[str], Optional[str]]:
    if provider:
        from_addr = provider.to_checksum_address(tx_from) if tx_from else None
        to_addr = provider.to_checksum_address(tx_to) if tx_to else None
    else:
        from_addr = tx_from
        to_addr = tx_to

    from_known = from_addr in known_accounts
    to_known = to_addr in known_accounts

    if from_known and to_known:
        return from_addr, "internal"
    if to_known:
        return to_addr, "receive"
    if from_known:
        return from_addr, "send"
    return None, None


def _token_contract_addresses(network: str) -> list[str]:
    return [
        config["TOKENS"][network][token]["contract_address"]
        for token in config["TOKENS"][network]
    ]


class TransactionLookupService:
    def __init__(self, w3):
        self.w3 = w3

    def lookup(self, symbol: str, txid: str) -> Any:
        known_accounts = get_all_accounts()
        coin_symbol = config["COIN_SYMBOL"]
        network = config["CURRENT_NETWORK"]

        if symbol == coin_symbol:
            return self._lookup_coin_transaction(txid, coin_symbol, known_accounts)
        if symbol in config["TOKENS"][network]:
            return self._lookup_token_transaction(txid, symbol, known_accounts)
        return {"status": "error", "msg": "Currency is not defined in config"}

    def _lookup_coin_transaction(
        self,
        txid: str,
        coin_symbol: str,
        known_accounts: set,
    ) -> Any:
        try:
            transaction = self.w3.eth.get_transaction(txid)
            logger.warning("Checking transaction %s", txid)
            address, category = resolve_transaction_direction(
                transaction["from"],
                transaction["to"],
                known_accounts,
            )
            if category:
                return self._regular_coin_transaction(
                    transaction, txid, coin_symbol, address, category
                )
            return self._internal_coin_transaction(
                transaction, txid, coin_symbol, known_accounts
            )
        except Exception as exc:
            logger.warning({"status": "error", "msg": str(exc)})
            return []

    def _regular_coin_transaction(
        self,
        transaction,
        txid: str,
        coin_symbol: str,
        address: str,
        category: str,
    ) -> list:
        logger.warning(
            "Found related addresses in %s, checking it as a regular %s transaction",
            txid,
            coin_symbol,
        )
        amount = self.w3.from_wei(transaction["value"], "ether")
        confirmations = int(self.w3.eth.block_number) - int(transaction["blockNumber"])
        return [[address, amount, confirmations, category]]

    def _internal_coin_transaction(
        self,
        transaction,
        txid: str,
        coin_symbol: str,
        known_accounts: set,
    ) -> Any:
        logger.warning(
            "Addresses in %s is not related to any SHKeeper addresses. "
            "Checking %s as a smartcontract internal transaction",
            txid,
            txid,
        )
        block_num = int(transaction["blockNumber"])
        block_eth_tx_addrs = self._block_eth_tx_addresses(block_num, known_accounts)
        logger.warning(
            "Regular %s transactions to our addresses in %s block: %s",
            coin_symbol,
            block_num,
            block_eth_tx_addrs,
        )

        related_internal_addr = self._related_internal_addresses(
            transaction,
            txid,
            block_num,
            known_accounts,
            block_eth_tx_addrs,
            coin_symbol,
        )
        if not related_internal_addr:
            logger.warning("Did not find any related addresses in tx %s", txid)
            return {
                "status": "error",
                "msg": "txid is not related to any known address",
            }

        logger.warning("Found internal transactions to %s", related_internal_addr)
        clear_addresses = self._exclusive_internal_addresses(
            transaction,
            txid,
            block_num,
            related_internal_addr,
        )
        related_transactions = self._internal_amounts_for_addresses(
            clear_addresses,
            block_num,
            transaction,
        )
        if not related_transactions:
            logger.warning(
                "There is not any transactions with amount > 0, respond with empty list"
            )
        return related_transactions

    def _block_eth_tx_addresses(self, block_num: int, known_accounts: set) -> list:
        block = self.w3.eth.get_block(block_num, True)
        block_eth_tx_addrs = []
        for tr in block.transactions:
            if tr["to"] in known_accounts or tr["from"] in known_accounts:
                block_eth_tx_addrs.append(tr["to"])
                block_eth_tx_addrs.append(tr["from"])
        return block_eth_tx_addrs

    def _related_internal_addresses(
        self,
        transaction,
        txid: str,
        block_num: int,
        known_accounts: set,
        block_eth_tx_addrs: list,
        coin_symbol: str,
    ) -> list:
        related_internal_addr = []
        tx_input = tx_input_hex(transaction)

        for acc_addr in known_accounts:
            if acc_addr[2:].lower() not in tx_input:
                continue
            if acc_addr not in block_eth_tx_addrs:
                related_internal_addr.append(acc_addr)
                continue
            logger.warning(
                "Found internal transaction to %s but skip it because there was "
                "already a regular %s transaction to %s in %s block",
                acc_addr,
                coin_symbol,
                acc_addr,
                block_num,
            )
        return related_internal_addr

    def _exclusive_internal_addresses(
        self,
        transaction,
        txid: str,
        block_num: int,
        related_internal_addr: list,
    ) -> set:
        token_addresses = _token_contract_addresses(config["CURRENT_NETWORK"])
        addresses_in_another_txs = []
        block = self.w3.eth.get_block(block_num, True)

        logger.warning(
            "Checking block for another internal txs to related addresses"
        )
        for tr in block.transactions:
            tr_input = tx_input_hex(tr)
            if (
                len(tr_input) <= 6
                or tr["to"] in token_addresses
                or tr["hash"].hex() == txid
            ):
                continue
            for addr in related_internal_addr:
                if addr[2:].lower() in tr_input:
                    logger.warning(
                        "Found another internal transaction %s to our address %s "
                        "in the same block, skip it!",
                        tr["hash"].hex(),
                        addr,
                    )
                    addresses_in_another_txs.append(addr)

        clear_addresses = set(related_internal_addr) - set(addresses_in_another_txs)
        if not clear_addresses:
            logger.warning(
                "No addresses are exclusively associated with the requested "
                "transaction in this block; return an empty list"
            )
        return clear_addresses

    def _internal_amounts_for_addresses(
        self,
        addresses: set,
        block_num: int,
        transaction,
    ) -> list:
        related_transactions = []
        confirmations = int(self.w3.eth.block_number) - int(
            transaction["blockNumber"]
        )

        for acc_addr in addresses:
            balance_before = Decimal(
                self.w3.from_wei(
                    self.w3.eth.get_balance(acc_addr, block_num - 1),
                    "ether",
                )
            )
            balance_after = Decimal(
                self.w3.from_wei(
                    self.w3.eth.get_balance(acc_addr, block_num),
                    "ether",
                )
            )
            amount = balance_after - balance_before
            if amount > 0:
                related_transactions.append(
                    [acc_addr, amount, confirmations, "receive"]
                )
        return related_transactions

    def _lookup_token_transaction(
        self,
        txid: str,
        symbol: str,
        known_accounts: set,
    ) -> Any:
        token_instance = Token(symbol)
        transactions_array = token_instance.get_token_transaction(txid)
        if not transactions_array:
            logger.warning(
                "There is not any token %s transaction with transactionID %s",
                symbol,
                txid,
            )
            return {"status": "error", "msg": "txid is not found for this crypto "}

        logger.warning(transactions_array)
        token_decimals = token_instance.contract.functions.decimals().call()
        related_transactions = []

        for transaction in transactions_array:
            address, category = resolve_transaction_direction(
                transaction["from"],
                transaction["to"],
                known_accounts,
                provider=token_instance.provider,
            )
            if not category:
                continue

            amount = Decimal(transaction["amount"]) / Decimal(10**token_decimals)
            confirmations = int(self.w3.eth.block_number) - int(
                transaction["block_number"]
            )
            related_transactions.append([address, amount, confirmations, category])

        if not related_transactions:
            logger.warning(
                "txid %s is not related to any known address for %s",
                txid,
                symbol,
            )
            return {
                "status": "error",
                "msg": "txid is not related to any known address",
            }
        return related_transactions
