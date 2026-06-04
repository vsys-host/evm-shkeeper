from unittest.mock import MagicMock, patch

from app.events import log_loop, process_block, process_internal_transactions
from app.utils import chain_head


class TestChainHeadInEvents:
    def test_chain_head_after_batch_style_tuple(self):
        w3 = MagicMock()
        w3.eth.get_block_number.return_value = (42,)
        assert chain_head(w3) == 42


class TestProcessBlock:
    def test_skips_transactions_without_recipient(self):
        block = MagicMock()
        block.transactions = [
            {
                "from": "0x" + "1" * 40,
                "to": None,
                "hash": MagicMock(hex=lambda: "0xabc"),
            },
        ]
        with patch("app.events.walletnotify_shkeeper") as notify:
            block_txs = process_block(block, set(), 100)
            notify.assert_not_called()
        assert block_txs == []

    def test_returns_involved_addresses(self):
        our_addr = "0x" + "aa" * 20
        sender = "0x" + "bb" * 20
        block = MagicMock()
        block.transactions = [
            {
                "from": sender,
                "to": our_addr,
                "hash": MagicMock(hex=lambda: "0xdead"),
            },
        ]
        with (
            patch("app.events.walletnotify_shkeeper"),
            patch("app.events.handle_event"),
            patch("app.events._should_drain", return_value=False),
        ):
            block_txs = process_block(block, {our_addr}, 100)
        assert our_addr.lower() in block_txs
        assert sender.lower() in block_txs


class TestInternalTransactions:
    @patch("app.events.walletnotify_shkeeper")
    def test_notifies_on_address_in_input(self, notify):
        our_addr = "0x" + "ab" * 20
        accounts = {our_addr}
        block = {
            "number": 100,
            "transactions": [
                {
                    "from": "0x" + "11" * 20,
                    "to": "0x" + "22" * 20,
                    "input": "0x" + "00" * 10 + our_addr[2:],
                    "hash": MagicMock(hex=lambda: "0xdead"),
                },
            ],
        }
        with patch.dict(
            "app.events.config",
            {"ENABLE_INTERNAL_TX_SCAN": True, "COIN_SYMBOL": "ETH"},
        ):
            process_internal_transactions(
                block, accounts, token_addresses=[], block_txs=[]
            )
        notify.assert_called_once_with("ETH", "0xdead")

    @patch("app.events.walletnotify_shkeeper")
    def test_skipped_when_disabled(self, notify):
        block = {"number": 1, "transactions": []}
        with patch.dict(
            "app.events.config",
            {"ENABLE_INTERNAL_TX_SCAN": False, "COIN_SYMBOL": "ETH"},
        ):
            process_internal_transactions(block, set(), [], [])
        notify.assert_not_called()

    @patch("app.events.walletnotify_shkeeper")
    def test_skips_tx_to_token_contract(self, notify):
        our_addr = "0x" + "ab" * 20
        token_contract = "0x" + "cc" * 20
        block = {
            "number": 100,
            "transactions": [
                {
                    "from": "0x" + "11" * 20,
                    "to": token_contract,
                    "input": "0x" + "00" * 10 + our_addr[2:],
                    "hash": MagicMock(hex=lambda: "0xbeef"),
                },
            ],
        }
        with patch.dict(
            "app.events.config",
            {"ENABLE_INTERNAL_TX_SCAN": True, "COIN_SYMBOL": "ETH"},
        ):
            process_internal_transactions(
                block,
                {our_addr},
                token_addresses=[token_contract],
                block_txs=[],
            )
        notify.assert_not_called()

    @patch("app.events.walletnotify_shkeeper")
    def test_skips_already_notified_regular_tx(self, notify):
        our_addr = "0x" + "ab" * 20
        block = {
            "number": 100,
            "transactions": [
                {
                    "from": "0x" + "11" * 20,
                    "to": "0x" + "22" * 20,
                    "input": "0x" + "00" * 10 + our_addr[2:],
                    "hash": MagicMock(hex=lambda: "0xdead"),
                },
            ],
        }
        with patch.dict(
            "app.events.config",
            {"ENABLE_INTERNAL_TX_SCAN": True, "COIN_SYMBOL": "ETH"},
        ):
            process_internal_transactions(
                block,
                {our_addr},
                token_addresses=[],
                block_txs=[our_addr.lower()],
            )
        notify.assert_not_called()

    @patch("app.events.walletnotify_shkeeper")
    def test_skips_short_input(self, notify):
        our_addr = "0x" + "ab" * 20
        block = {
            "number": 100,
            "transactions": [
                {
                    "from": "0x" + "11" * 20,
                    "to": "0x" + "22" * 20,
                    "input": "0x1234",
                    "hash": MagicMock(hex=lambda: "0xdead"),
                },
            ],
        }
        with patch.dict(
            "app.events.config",
            {"ENABLE_INTERNAL_TX_SCAN": True, "COIN_SYMBOL": "ETH"},
        ):
            process_internal_transactions(block, {our_addr}, [], [])
        notify.assert_not_called()

    @patch("app.events.walletnotify_shkeeper")
    def test_handles_bytes_input(self, notify):
        """web3 v6+ returns HexBytes for input, not str."""
        our_addr = "0x" + "ab" * 20
        accounts = {our_addr}
        raw_input = bytes.fromhex("deadbeef" + "00" * 10 + our_addr[2:])
        block = {
            "number": 100,
            "transactions": [
                {
                    "from": "0x" + "11" * 20,
                    "to": "0x" + "22" * 20,
                    "input": raw_input,
                    "hash": MagicMock(hex=lambda: "0xcafe"),
                },
            ],
        }
        with patch.dict(
            "app.events.config",
            {"ENABLE_INTERNAL_TX_SCAN": True, "COIN_SYMBOL": "ETH"},
        ):
            process_internal_transactions(block, accounts, [], [])
        notify.assert_called_once_with("ETH", "0xcafe")

    @patch("app.events.walletnotify_shkeeper")
    def test_dedup_internal_within_block(self, notify):
        """Only one notification per address per block."""
        our_addr = "0x" + "ab" * 20
        accounts = {our_addr}
        input_data = "0x" + "00" * 10 + our_addr[2:]
        block = {
            "number": 100,
            "transactions": [
                {
                    "from": "0x" + "11" * 20,
                    "to": "0x" + "22" * 20,
                    "input": input_data,
                    "hash": MagicMock(hex=lambda: "0xaaa"),
                },
                {
                    "from": "0x" + "33" * 20,
                    "to": "0x" + "44" * 20,
                    "input": input_data,
                    "hash": MagicMock(hex=lambda: "0xbbb"),
                },
            ],
        }
        with patch.dict(
            "app.events.config",
            {"ENABLE_INTERNAL_TX_SCAN": True, "COIN_SYMBOL": "ETH"},
        ):
            process_internal_transactions(block, accounts, [], [])
        notify.assert_called_once_with("ETH", "0xaaa")


class TestLogLoop:
    @patch("app.events._save_last_block")
    @patch("app.events.process_token_transfers")
    @patch("app.events.process_internal_transactions")
    @patch("app.events.process_block", return_value=[])
    @patch("app.events.get_all_accounts", return_value=["0x" + "a" * 40])
    @patch("app.events.chain_head", return_value=10)
    @patch("app.create_app")
    @patch("app.events.w3")
    def test_scans_until_caught_up(
        self,
        mock_w3,
        mock_create_app,
        mock_chain_head,
        *_mocks,
    ):
        mock_app = MagicMock()
        mock_create_app.return_value = mock_app

        batch = MagicMock()
        block = {"number": 1, "transactions": []}
        batch.execute.return_value = [block]
        mock_w3.batch_requests.return_value.__enter__.return_value = batch

        with patch(
            "app.events.config",
            {
                "TOKENS": {"sepolia": {}},
                "CURRENT_NETWORK": "sepolia",
                "BLOCK_SCANNER_BATCH_SIZE": 12,
                "BLOCK_SCAN_LAG": 2,
                "CHECK_NEW_BLOCK_EVERY_SECONDS": 2,
            },
        ), patch("app.events.time.sleep", side_effect=InterruptedError):
            try:
                log_loop(0, 1)
            except InterruptedError:
                pass

        assert batch.add.call_count == 8  # head=10, lag=2 → scan blocks 1..8 only
        assert mock_chain_head.call_count >= 1

    @patch("app.events._save_last_block")
    @patch("app.events.process_token_transfers")
    @patch("app.events.process_internal_transactions")
    @patch("app.events.process_block", return_value=[])
    @patch("app.events.get_all_accounts", return_value=["0x" + "a" * 40])
    @patch("app.events.chain_head", return_value=10)
    @patch("app.create_app")
    @patch("app.events.w3")
    def test_waits_when_already_two_blocks_behind_head(
        self,
        mock_w3,
        mock_create_app,
        *_mocks,
    ):
        mock_create_app.return_value = MagicMock()

        with patch(
            "app.events.config",
            {
                "TOKENS": {"sepolia": {}},
                "CURRENT_NETWORK": "sepolia",
                "BLOCK_SCANNER_BATCH_SIZE": 12,
                "BLOCK_SCAN_LAG": 2,
                "CHECK_NEW_BLOCK_EVERY_SECONDS": 2,
            },
        ), patch("app.events.time.sleep", side_effect=InterruptedError):
            try:
                log_loop(8, 1)  # already at head - 2
            except InterruptedError:
                pass

        mock_w3.batch_requests.assert_not_called()
