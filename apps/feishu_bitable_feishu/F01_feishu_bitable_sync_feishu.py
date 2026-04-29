"""
程序简介：按 full、recent 或 verify 模式同步飞书多维表格，并把字段、记录和状态写入 data 缓存。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from peifang_core.feishu import sync_bitable


def main() -> None:
    parser = argparse.ArgumentParser(
        description="飞书多维表格同步：首次全量落地，后续取最新50条合并，并周期性做全量校验。"
    )
    parser.add_argument("--mode", choices=["auto", "full", "recent", "verify"], default="auto")
    parser.add_argument("--recent-limit", type=int, default=50)
    parser.add_argument("--verify-hours", type=int, default=24)
    args = parser.parse_args()

    summary = sync_bitable(
        mode=args.mode,
        recent_limit=args.recent_limit,
        verify_interval_hours=args.verify_hours,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

