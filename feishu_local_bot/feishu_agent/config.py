import os
from dataclasses import dataclass
from typing import List, Optional

from dotenv import load_dotenv


def _split_csv(value: str) -> List[str]:
    return [x.strip() for x in value.split(",") if x.strip()]


def _to_bool(v: str, default: bool = False) -> bool:
    """
    支持 1/0, true/false, yes/no, on/off
    空字符串返回 default
    """
    if v is None:
        return default
    s = str(v).strip().lower()
    if s == "":
        return default
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


@dataclass
class Settings:
    app_id: str
    app_secret: str

    data_dir: str = "./data"
    page_size: int = 50
    target_chat_ids: Optional[List[str]] = None

    history_start_time: Optional[int] = None  # unix seconds
    history_start_days: Optional[int] = None
    history_end_time: Optional[int] = None  # unix seconds

    log_level: str = "INFO"

    server_host: str = "127.0.0.1"
    server_port: int = 8000
    poll_interval_seconds: int = 0

    # ✅ 新增：自动下载消息中的 image_key 图片
    download_images: bool = False
    images_skip_existing: bool = True
    images_dir: str = ""  # 预留，目前默认存到 data/images


def load_settings() -> Settings:
    # 读取 .env（优先当前目录）
    load_dotenv(override=False)

    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise RuntimeError("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET，请先配置 .env")

    data_dir = os.getenv("FEISHU_DATA_DIR", "./data").strip() or "./data"

    page_size_raw = os.getenv("FEISHU_PAGE_SIZE", "50").strip()
    try:
        page_size = int(page_size_raw)
    except ValueError:
        page_size = 50
    page_size = max(1, min(page_size, 50))

    target_chat_ids_raw = os.getenv("FEISHU_TARGET_CHAT_IDS", "").strip()
    target_chat_ids = _split_csv(target_chat_ids_raw) if target_chat_ids_raw else None

    history_start_time = os.getenv("FEISHU_HISTORY_START_TIME", "").strip()
    history_start_time_i = int(history_start_time) if history_start_time else None

    history_start_days = os.getenv("FEISHU_HISTORY_START_DAYS", "").strip()
    history_start_days_i = int(history_start_days) if history_start_days else None

    history_end_time = os.getenv("FEISHU_HISTORY_END_TIME", "").strip()
    history_end_time_i = int(history_end_time) if history_end_time else None

    log_level = os.getenv("FEISHU_LOG_LEVEL", "INFO").strip().upper() or "INFO"

    server_host = os.getenv("FEISHU_SERVER_HOST", "127.0.0.1").strip() or "127.0.0.1"
    server_port_raw = os.getenv("FEISHU_SERVER_PORT", "8000").strip()
    try:
        server_port = int(server_port_raw)
    except ValueError:
        server_port = 8000

    poll_raw = os.getenv("FEISHU_POLL_INTERVAL_SECONDS", "0").strip()
    try:
        poll_interval_seconds = int(poll_raw) if poll_raw else 0
    except ValueError:
        poll_interval_seconds = 0
    poll_interval_seconds = max(0, poll_interval_seconds)

    # ✅ 新增：图片下载开关
    download_images = _to_bool(os.getenv("FEISHU_DOWNLOAD_IMAGES", "0"), default=False)
    images_skip_existing = _to_bool(os.getenv("FEISHU_IMAGES_SKIP_EXISTING", "1"), default=True)
    images_dir = os.getenv("FEISHU_IMAGES_DIR", "").strip()

    return Settings(
        app_id=app_id,
        app_secret=app_secret,
        data_dir=data_dir,
        page_size=page_size,
        target_chat_ids=target_chat_ids,
        history_start_time=history_start_time_i,
        history_start_days=history_start_days_i,
        history_end_time=history_end_time_i,
        log_level=log_level,
        server_host=server_host,
        server_port=server_port,
        poll_interval_seconds=poll_interval_seconds,
        download_images=download_images,
        images_skip_existing=images_skip_existing,
        images_dir=images_dir,
    )
