"""
程序简介：读取飞书机器人运行配置，支持默认变量和多公司配置档案变量。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

APP_ROOT = Path(__file__).resolve().parents[1]

from peifang_core.common import get_profiled_env, load_dotenv_for_profile


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
    # 先读取本地机器人自己的 .env，保证 FEISHU_ENV_PROFILE 也能放在子项目内。
    load_dotenv(APP_ROOT / ".env", override=False)
    profile = load_dotenv_for_profile("FEISHU")
    load_dotenv(APP_ROOT / ".env", override=False)

    app_id = get_profiled_env("FEISHU_APP_ID", namespace="FEISHU", profile=profile) or get_profiled_env(
        "APP_ID", namespace="FEISHU", profile=profile
    )
    app_secret = get_profiled_env("FEISHU_APP_SECRET", namespace="FEISHU", profile=profile) or get_profiled_env(
        "APP_SECRET", namespace="FEISHU", profile=profile
    )
    if not app_id or not app_secret:
        raise RuntimeError("缺少 FEISHU_APP_ID / FEISHU_APP_SECRET，请先配置 .env")

    data_dir = get_profiled_env("FEISHU_DATA_DIR", namespace="FEISHU", profile=profile, default="./data") or "./data"

    page_size_raw = get_profiled_env("FEISHU_PAGE_SIZE", namespace="FEISHU", profile=profile, default="50")
    try:
        page_size = int(page_size_raw)
    except ValueError:
        page_size = 50
    page_size = max(1, min(page_size, 50))

    target_chat_ids_raw = get_profiled_env("FEISHU_TARGET_CHAT_IDS", namespace="FEISHU", profile=profile)
    target_chat_ids = _split_csv(target_chat_ids_raw) if target_chat_ids_raw else None

    history_start_time = get_profiled_env("FEISHU_HISTORY_START_TIME", namespace="FEISHU", profile=profile)
    history_start_time_i = int(history_start_time) if history_start_time else None

    history_start_days = get_profiled_env("FEISHU_HISTORY_START_DAYS", namespace="FEISHU", profile=profile)
    history_start_days_i = int(history_start_days) if history_start_days else None

    history_end_time = get_profiled_env("FEISHU_HISTORY_END_TIME", namespace="FEISHU", profile=profile)
    history_end_time_i = int(history_end_time) if history_end_time else None

    log_level = get_profiled_env("FEISHU_LOG_LEVEL", namespace="FEISHU", profile=profile, default="INFO").upper() or "INFO"

    server_host = get_profiled_env(
        "FEISHU_SERVER_HOST", namespace="FEISHU", profile=profile, default="127.0.0.1"
    ) or "127.0.0.1"
    server_port_raw = get_profiled_env("FEISHU_SERVER_PORT", namespace="FEISHU", profile=profile, default="8000")
    try:
        server_port = int(server_port_raw)
    except ValueError:
        server_port = 8000

    poll_raw = get_profiled_env("FEISHU_POLL_INTERVAL_SECONDS", namespace="FEISHU", profile=profile, default="0")
    try:
        poll_interval_seconds = int(poll_raw) if poll_raw else 0
    except ValueError:
        poll_interval_seconds = 0
    poll_interval_seconds = max(0, poll_interval_seconds)

    # ✅ 新增：图片下载开关
    download_images = _to_bool(
        get_profiled_env("FEISHU_DOWNLOAD_IMAGES", namespace="FEISHU", profile=profile, default="0"),
        default=False,
    )
    images_skip_existing = _to_bool(
        get_profiled_env("FEISHU_IMAGES_SKIP_EXISTING", namespace="FEISHU", profile=profile, default="1"),
        default=True,
    )
    images_dir = get_profiled_env("FEISHU_IMAGES_DIR", namespace="FEISHU", profile=profile)

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
