import logging
import time
from datetime import datetime, timedelta, timezone


def setup_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )


def unix_now() -> int:
    return int(time.time())


def calc_start_time_from_days(days: int) -> int:
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return int(dt.timestamp())


def safe_int(v, default: int = 0) -> int:
    try:
        return int(v)
    except Exception:
        return default
