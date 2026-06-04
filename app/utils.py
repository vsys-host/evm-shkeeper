# import logging
from decimal import Decimal

# import time
# from typing import Literal
# import concurrent
# import requests as rq
from functools import wraps

# from flask import current_app
from werkzeug.routing import BaseConverter

# import requests

# from .config import config, get_contract_address
from .logging import logger


def chain_head(w3) -> int:
    """Return current chain head as int (safe after web3 batch_requests)."""
    value = w3.eth.get_block_number()
    if isinstance(value, tuple):
        value = value[0]
    return int(value)


def tx_input_hex(transaction) -> str:
    """Return transaction input as lowercase hex string without 0x prefix.

    Handles both web3 v5 (str) and v6+ (HexBytes) input formats.
    """
    if isinstance(transaction, dict):
        tx_input = transaction.get("input")
    else:
        tx_input = getattr(transaction, "input", None)
    if not tx_input:
        return ""
    if isinstance(tx_input, str):
        return tx_input[2:].lower() if tx_input.startswith("0x") else tx_input.lower()
    return tx_input.hex().lower()


class DecimalConverter(BaseConverter):

    def to_python(self, value):
        return Decimal(value)

    def to_url(self, value):
        return BaseConverter.to_url(value)


def skip_if_running(f):
    task_name = f"{f.__module__}.{f.__name__}"

    @wraps(f)
    def wrapped(self, *args, **kwargs):
        workers = self.app.control.inspect().active()

        for worker, tasks in workers.items():
            for task in tasks:
                if (
                    task_name == task["name"]
                    and tuple(args) == tuple(task["args"])
                    and kwargs == task["kwargs"]
                    and self.request.id != task["id"]
                ):
                    logger.debug(
                        f"task {task_name} ({args}, {kwargs}) is running on {worker}, skipping"
                    )

                    return None
        logger.debug(f"task {task_name} ({args}, {kwargs}) is allowed to run")
        return f(self, *args, **kwargs)

    return wrapped
