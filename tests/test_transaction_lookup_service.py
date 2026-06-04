"""Behavioral tests for TransactionLookupService (post-refactor parity)."""

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.services.transaction_lookup import TransactionLookupService


@pytest.fixture
def accounts():
    return ["0xOurWallet", "0xOther"]


@pytest.fixture
def mock_w3():
    w3 = MagicMock()
    w3.eth.block_number = 110
    w3.from_wei = lambda value, unit: Decimal(value) / Decimal(10**18)
    return w3


@pytest.fixture
def eth_config():
    return {
        "COIN_SYMBOL": "ETH",
        "CURRENT_NETWORK": "sepolia",
        "TOKENS": {
            "sepolia": {
                "ETH-USDT": {"contract_address": "0xTokenContract"},
            },
        },
    }


class TestLookupRouting:
    @patch("app.services.transaction_lookup.get_all_accounts")
    @patch("app.services.transaction_lookup.config", {"COIN_SYMBOL": "ETH", "CURRENT_NETWORK": "sepolia", "TOKENS": {"sepolia": {}}})
    def test_unknown_symbol_returns_error(self, mock_accounts, mock_w3):
        mock_accounts.return_value = []
        service = TransactionLookupService(mock_w3)

        result = service.lookup("UNKNOWN", "0xabc")

        assert result == {
            "status": "error",
            "msg": "Currency is not defined in config",
        }


class TestRegularCoinTransaction:
    @patch("app.services.transaction_lookup.get_all_accounts")
    @patch("app.services.transaction_lookup.config")
    def test_regular_receive(self, mock_config, mock_accounts, mock_w3, accounts, eth_config):
        mock_config.__getitem__ = lambda self, key: eth_config[key]
        mock_config.get = lambda key, default=None: eth_config.get(key, default)
        mock_accounts.return_value = accounts

        tx = {
            "from": "0xSender",
            "to": "0xOurWallet",
            "value": 10**18,
            "blockNumber": 100,
        }
        mock_w3.eth.get_transaction.return_value = tx

        service = TransactionLookupService(mock_w3)
        result = service.lookup("ETH", "0xtx1")

        assert result == [["0xOurWallet", Decimal(1), 10, "receive"]]
        mock_w3.eth.get_block.assert_not_called()

    @patch("app.services.transaction_lookup.get_all_accounts")
    @patch("app.services.transaction_lookup.config")
    def test_regular_internal_both_known(self, mock_config, mock_accounts, mock_w3, eth_config):
        mock_config.__getitem__ = lambda self, key: eth_config[key]
        mock_config.get = lambda key, default=None: eth_config.get(key, default)
        mock_accounts.return_value = ["0xOurWallet", "0xOther"]

        tx = {
            "from": "0xOurWallet",
            "to": "0xOther",
            "value": 0,
            "blockNumber": 100,
        }
        mock_w3.eth.get_transaction.return_value = tx

        service = TransactionLookupService(mock_w3)
        result = service.lookup("ETH", "0xtx1")

        assert result == [["0xOurWallet", Decimal(0), 10, "internal"]]


class TestCoinExceptionHandling:
    @patch("app.services.transaction_lookup.get_all_accounts")
    @patch("app.services.transaction_lookup.config")
    def test_returns_empty_list_on_exception(
        self, mock_config, mock_accounts, mock_w3, eth_config
    ):
        mock_config.__getitem__ = lambda self, key: eth_config[key]
        mock_accounts.return_value = []
        mock_w3.eth.get_transaction.side_effect = RuntimeError("rpc down")

        service = TransactionLookupService(mock_w3)
        result = service.lookup("ETH", "0xtx1")

        assert result == []


class TestInternalCoinTransaction:
    @patch("app.services.transaction_lookup.tx_input_hex")
    @patch("app.services.transaction_lookup.get_all_accounts")
    @patch("app.services.transaction_lookup.config")
    def test_no_related_address_in_input_returns_error(
        self, mock_config, mock_accounts, mock_tx_input, mock_w3, eth_config
    ):
        mock_config.__getitem__ = lambda self, key: eth_config[key]
        mock_accounts.return_value = ["0xOurWallet"]
        mock_tx_input.return_value = "deadbeef"

        tx = {"from": "0xA", "to": "0xB", "value": 0, "blockNumber": 50}
        mock_w3.eth.get_transaction.return_value = tx
        block = MagicMock()
        block.transactions = []
        mock_w3.eth.get_block.return_value = block

        service = TransactionLookupService(mock_w3)
        result = service.lookup("ETH", "0xtx1")

        assert result == {
            "status": "error",
            "msg": "txid is not related to any known address",
        }

    @patch("app.services.transaction_lookup.tx_input_hex")
    @patch("app.services.transaction_lookup.get_all_accounts")
    @patch("app.services.transaction_lookup.config")
    def test_internal_receive_from_balance_delta(
        self, mock_config, mock_accounts, mock_tx_input, mock_w3, eth_config
    ):
        mock_config.__getitem__ = lambda self, key: eth_config[key]
        mock_accounts.return_value = ["0xOurWallet"]

        tx = {"from": "0xContract", "to": "0xContract", "value": 0, "blockNumber": 50}
        mock_w3.eth.get_transaction.return_value = tx

        def tx_input_side_effect(transaction):
            if transaction is tx:
                return "ourwallet"  # matches 0xOurWallet[2:].lower()
            return "00"

        mock_tx_input.side_effect = tx_input_side_effect

        block = MagicMock()
        block.transactions = []
        mock_w3.eth.get_block.return_value = block

        mock_w3.eth.get_balance.side_effect = [
            0,
            2 * 10**18,
        ]

        service = TransactionLookupService(mock_w3)
        result = service.lookup("ETH", "0xtx1")

        assert result == [["0xOurWallet", Decimal(2), 60, "receive"]]

    @patch("app.services.transaction_lookup.tx_input_hex")
    @patch("app.services.transaction_lookup.get_all_accounts")
    @patch("app.services.transaction_lookup.config")
    def test_skips_zero_amount_internal(
        self, mock_config, mock_accounts, mock_tx_input, mock_w3, eth_config
    ):
        mock_config.__getitem__ = lambda self, key: eth_config[key]
        mock_accounts.return_value = ["0xOurWallet"]

        tx = {"from": "0xA", "to": "0xB", "value": 0, "blockNumber": 50}
        mock_w3.eth.get_transaction.return_value = tx
        mock_tx_input.return_value = "ourwallet"

        block = MagicMock()
        block.transactions = []
        mock_w3.eth.get_block.return_value = block
        mock_w3.eth.get_balance.return_value = 10**18

        service = TransactionLookupService(mock_w3)
        result = service.lookup("ETH", "0xtx1")

        assert result == []

    @patch("app.services.transaction_lookup.tx_input_hex")
    @patch("app.services.transaction_lookup.get_all_accounts")
    @patch("app.services.transaction_lookup.config")
    def test_skips_address_when_regular_tx_in_same_block(
        self, mock_config, mock_accounts, mock_tx_input, mock_w3, eth_config
    ):
        mock_config.__getitem__ = lambda self, key: eth_config[key]
        mock_accounts.return_value = ["0xOurWallet"]

        tx = {"from": "0xA", "to": "0xB", "value": 0, "blockNumber": 50}
        mock_w3.eth.get_transaction.return_value = tx
        mock_tx_input.return_value = "ourwallet"

        regular_tx = {
            "from": "0xX",
            "to": "0xOurWallet",
            "hash": MagicMock(hex=MagicMock(return_value="0xother")),
        }
        block = MagicMock()
        block.transactions = [regular_tx]
        mock_w3.eth.get_block.return_value = block

        service = TransactionLookupService(mock_w3)
        result = service.lookup("ETH", "0xtx1")

        assert result == {
            "status": "error",
            "msg": "txid is not related to any known address",
        }

    @patch("app.services.transaction_lookup.tx_input_hex")
    @patch("app.services.transaction_lookup.get_all_accounts")
    @patch("app.services.transaction_lookup.config")
    def test_excludes_address_found_in_another_tx_same_block(
        self, mock_config, mock_accounts, mock_tx_input, mock_w3, eth_config
    ):
        mock_config.__getitem__ = lambda self, key: eth_config[key]
        mock_accounts.return_value = ["0xOurWallet"]

        tx = {"from": "0xA", "to": "0xB", "value": 0, "blockNumber": 50}
        mock_w3.eth.get_transaction.return_value = tx

        other_tx = {
            "from": "0xX",
            "to": "0xY",
            "hash": MagicMock(hex=MagicMock(return_value="0xother")),
        }

        def tx_input_side_effect(tr):
            if tr is tx:
                return "ourwallet"
            if tr is other_tx:
                return "ourwallet"
            return ""

        mock_tx_input.side_effect = tx_input_side_effect

        block = MagicMock()
        block.transactions = [other_tx]
        mock_w3.eth.get_block.return_value = block

        service = TransactionLookupService(mock_w3)
        result = service.lookup("ETH", "0xtx1")

        assert result == []


class TestTokenTransaction:
    @patch("app.services.transaction_lookup.Token")
    @patch("app.services.transaction_lookup.get_all_accounts")
    @patch("app.services.transaction_lookup.config")
    def test_token_not_found_returns_error(
        self, mock_config, mock_accounts, mock_token_cls, mock_w3, eth_config
    ):
        mock_config.__getitem__ = lambda self, key: eth_config[key]
        mock_accounts.return_value = ["0xOurWallet"]
        mock_token_cls.return_value.get_token_transaction.return_value = []

        service = TransactionLookupService(mock_w3)
        result = service.lookup("ETH-USDT", "0xtx1")

        assert result == {
            "status": "error",
            "msg": "txid is not found for this crypto ",
        }

    @patch("app.services.transaction_lookup.Token")
    @patch("app.services.transaction_lookup.get_all_accounts")
    @patch("app.services.transaction_lookup.config")
    def test_token_transfer_receive(
        self, mock_config, mock_accounts, mock_token_cls, mock_w3, eth_config
    ):
        mock_config.__getitem__ = lambda self, key: eth_config[key]
        mock_accounts.return_value = ["0xOurWallet"]

        token = mock_token_cls.return_value
        token.get_token_transaction.return_value = [
            {
                "from": "0xSender",
                "to": "0xOurWallet",
                "amount": 1_000_000,
                "block_number": 100,
            },
        ]
        token.contract.functions.decimals.return_value.call.return_value = 6
        token.provider.to_checksum_address.side_effect = lambda addr: addr

        service = TransactionLookupService(mock_w3)
        result = service.lookup("ETH-USDT", "0xtx1")

        assert result == [["0xOurWallet", Decimal(1), 10, "receive"]]

    @patch("app.services.transaction_lookup.Token")
    @patch("app.services.transaction_lookup.get_all_accounts")
    @patch("app.services.transaction_lookup.config")
    def test_token_unrelated_returns_error(
        self, mock_config, mock_accounts, mock_token_cls, mock_w3, eth_config
    ):
        mock_config.__getitem__ = lambda self, key: eth_config[key]
        mock_accounts.return_value = ["0xOurWallet"]

        token = mock_token_cls.return_value
        token.get_token_transaction.return_value = [
            {
                "from": "0xA",
                "to": "0xB",
                "amount": 1,
                "block_number": 100,
            },
        ]
        token.contract.functions.decimals.return_value.call.return_value = 6
        token.provider.to_checksum_address.side_effect = lambda addr: addr

        service = TransactionLookupService(mock_w3)
        result = service.lookup("ETH-USDT", "0xtx1")

        assert result == {
            "status": "error",
            "msg": "txid is not related to any known address",
        }

    @patch("app.services.transaction_lookup.Token")
    @patch("app.services.transaction_lookup.get_all_accounts")
    @patch("app.services.transaction_lookup.config")
    def test_token_exception_propagates(
        self, mock_config, mock_accounts, mock_token_cls, mock_w3, eth_config
    ):
        mock_config.__getitem__ = lambda self, key: eth_config[key]
        mock_accounts.return_value = []
        mock_token_cls.return_value.get_token_transaction.side_effect = ValueError(
            "rpc"
        )

        service = TransactionLookupService(mock_w3)

        with pytest.raises(ValueError, match="rpc"):
            service.lookup("ETH-USDT", "0xtx1")
