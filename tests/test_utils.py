from decimal import Decimal
from unittest.mock import MagicMock

from app.utils import DecimalConverter, chain_head, skip_if_running


class TestChainHead:
    def test_returns_int_from_get_block_number(self):
        w3 = MagicMock()
        w3.eth.get_block_number.return_value = 12345
        assert chain_head(w3) == 12345

    def test_unwraps_tuple_from_batch_quirk(self):
        w3 = MagicMock()
        w3.eth.get_block_number.return_value = (999,)
        assert chain_head(w3) == 999


class TestDecimalConverter:
    def test_to_python_converts_string_to_decimal(self):
        converter = DecimalConverter(None)
        assert converter.to_python("1.25") == Decimal("1.25")


class TestSkipIfRunning:
    def test_skips_when_same_task_already_active(self):
        @skip_if_running
        def sample_task(self, arg):
            return "executed"

        self_mock = MagicMock()
        self_mock.request.id = "current-id"
        self_mock.app.control.inspect.return_value.active.return_value = {
            "worker1": [
                {
                    "id": "other-id",
                    "name": f"{sample_task.__module__}.{sample_task.__name__}",
                    "args": ("x",),
                    "kwargs": {},
                }
            ],
        }

        assert sample_task(self_mock, "x") is None

    def test_runs_when_no_duplicate_task(self):
        @skip_if_running
        def sample_task(self, value):
            return value * 2

        self_mock = MagicMock()
        self_mock.request.id = "current-id"
        self_mock.app.control.inspect.return_value.active.return_value = {}

        assert sample_task(self_mock, 3) == 6
