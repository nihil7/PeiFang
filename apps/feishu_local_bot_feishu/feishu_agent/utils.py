"""
程序简介：提供日志等飞书机器人子项目复用的小工具。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

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
