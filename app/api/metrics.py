import logging
from prometheus_client import generate_latest, Gauge

from . import metrics_blueprint
from ..models import Settings

logger = logging.getLogger(__name__)


ethereum_fullnode_status = Gauge(
    "ethereum_fullnode_status", "Connection status to ethereum fullnode"
)
ethereum_fullnode_last_block = Gauge(
    "ethereum_fullnode_last_block", "Last block loaded to the fullnode"
)
ethereum_wallet_last_block = Gauge("ethereum_wallet_last_block", "Last checked block")
ethereum_fullnode_last_block_timestamp = Gauge(
    "ethereum_fullnode_last_block_timestamp", "Fullnode block timestamp"
)
ethereum_wallet_last_block_timestamp = Gauge(
    "ethereum_wallet_last_block_timestamp", "Wallet block timestamp"
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
        connected = w3.is_connected()  # FIX: method, not property
    except Exception:
        connected = False

    if not connected:
        return {"ethereum_fullnode_status": 0}

    result = {"ethereum_fullnode_status": 1}

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

        result["ethereum_wallet_last_block"] = last_checked
        result["ethereum_wallet_last_block_timestamp"] = wallet_block.get(
            "timestamp", 0
        )
    except Exception as e:
        logger.warning("Wallet block fetch failed: %s", e)
        result["ethereum_wallet_last_block"] = 0
        result["ethereum_wallet_last_block_timestamp"] = 0

    return result


@metrics_blueprint.get("/metrics")
def get_metrics():
    try:
        data = get_all_metrics()

        if not data:
            ethereum_fullnode_status.set(0)
            return generate_latest().decode()

        ethereum_fullnode_status.set(data.get("ethereum_fullnode_status", 0))

        if data["ethereum_fullnode_status"] == 1:
            ethereum_fullnode_last_block.set(data.get("last_fullnode_block_number", 0))
            ethereum_fullnode_last_block_timestamp.set(
                data.get("last_fullnode_block_timestamp", 0)
            )
            ethereum_wallet_last_block.set(data.get("ethereum_wallet_last_block", 0))
            ethereum_wallet_last_block_timestamp.set(
                data.get("ethereum_wallet_last_block_timestamp", 0)
            )

    except Exception as e:
        logger.exception("Metrics endpoint failed completely: %s", e)
        ethereum_fullnode_status.set(0)

    # IMPORTANT: always return valid prometheus output
    return generate_latest().decode()
