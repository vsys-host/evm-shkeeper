from unittest.mock import MagicMock, patch

from app.tasks import make_multipayout


class TestMakeMultipayout:
    @patch("app.tasks.post_payout_results")
    @patch("app.tasks.Coin")
    def test_native_coin_path(self, coin_cls, post_payout_results):
        coin_instance = coin_cls.return_value
        coin_instance.make_multipayout_eth.return_value = [{"status": "success"}]
        post_payout_results.delay = MagicMock()

        result = make_multipayout.run("ETH", [{"dest": "0x0", "amount": 1}], "0.001")

        coin_cls.assert_called_once_with("ETH")
        coin_instance.make_multipayout_eth.assert_called_once()
        post_payout_results.delay.assert_called_once_with(
            [{"status": "success"}], "ETH"
        )
        assert result == [{"status": "success"}]

    @patch("app.tasks.post_payout_results")
    @patch("app.tasks.Token")
    def test_token_path(self, token_cls, post_payout_results):
        token_instance = token_cls.return_value
        token_instance.make_token_multipayout.return_value = [{"status": "ok"}]
        post_payout_results.delay = MagicMock()

        result = make_multipayout.run(
            "ETH-USDT", [{"dest": "0x0", "amount": 1}], "0.001"
        )

        token_cls.assert_called_once_with("ETH-USDT")
        token_instance.make_token_multipayout.assert_called_once()
        assert result == [{"status": "ok"}]

    def test_unknown_symbol_returns_error(self):
        result = make_multipayout.run("UNKNOWN", [], "0.001")
        assert result == [{"status": "error", "msg": "Symbol is not in config"}]
