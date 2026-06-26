import logging
from prometheus_client import generate_latest, Gauge

from . import metrics_blueprint
from ..models import Settings
from ..config import config

logger = logging.getLogger(__name__)

_chain_name = config["CHAIN_NAME"]

evm_fullnode_status = Gauge(
    f"{_chain_name}_fullnode_status", f"Connection status to {_chain_name} fullnode"
)
evm_fullnode_last_block = Gauge(
    f"{_chain_name}_fullnode_last_block", f"Last block loaded to the {_chain_name} fullnode"
)
evm_wallet_last_block = Gauge(
    f"{_chain_name}_wallet_last_block", f"Last checked block for {_chain_name}"
)
evm_fullnode_last_block_timestamp = Gauge(
    f"{_chain_name}_fullnode_last_block_timestamp", f"Fullnode block timestamp for {_chain_name}"
)
evm_wallet_last_block_timestamp = Gauge(
    f"{_chain_name}_wallet_last_block_timestamp", f"Wallet block timestamp for {_chain_name}"
)


def safe_int(value, default=0):
    try:
        return int(value)
    except Exception:
        return default


def get_all_metrics():
    try:
        from ..token import make_provider

        w3 = make_provider()
    except Exception as e:
        logger.exception("Web3 init failed: %s", e)
        return None

    try:
        connected = w3.is_connected()
    except Exception:
        connected = False

    if not connected:
        return {"fullnode_status": 0}

    result = {"fullnode_status": 1}

    # --- fullnode block ---
    try:
        last_block = w3.eth.block_number
        block = w3.eth.get_block(last_block)

        result["last_fullnode_block_number"] = last_block
        result["last_fullnode_block_timestamp"] = block.get("timestamp", 0)
    except Exception as e:
        logger.warning("Failed fullnode block fetch: %s", e)
        result["last_fullnode_block_number"] = 0
        result["last_fullnode_block_timestamp"] = 0

    # --- wallet tracking ---
    try:
        pd = Settings.query.filter_by(name="last_block").first()
        last_checked = safe_int(pd.value if pd else 0)

        wallet_block = w3.eth.get_block(last_checked)

        result["wallet_last_block"] = last_checked
        result["wallet_last_block_timestamp"] = wallet_block.get(
            "timestamp", 0
        )
    except Exception as e:
        logger.warning("Wallet block fetch failed: %s", e)
        result["wallet_last_block"] = 0
        result["wallet_last_block_timestamp"] = 0

    return result


@metrics_blueprint.get("/metrics")
def get_metrics():
    try:
        data = get_all_metrics()

        if not data:
            evm_fullnode_status.set(0)
            return generate_latest().decode()

        evm_fullnode_status.set(data.get("fullnode_status", 0))

        if data["fullnode_status"] == 1:
            evm_fullnode_last_block.set(data.get("last_fullnode_block_number", 0))
            evm_fullnode_last_block_timestamp.set(
                data.get("last_fullnode_block_timestamp", 0)
            )
            evm_wallet_last_block.set(data.get("wallet_last_block", 0))
            evm_wallet_last_block_timestamp.set(
                data.get("wallet_last_block_timestamp", 0)
            )

    except Exception as e:
        logger.exception("Metrics endpoint failed completely: %s", e)
        evm_fullnode_status.set(0)

    # IMPORTANT: always return valid prometheus output
    return generate_latest().decode()
