"""
程序简介：按 full、recent 或 verify 模式同步企业微信智能表格，并把字段、记录和状态写入 data 缓存。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from peifang_core.wecom import sync_all_smartsheets, sync_smartsheet


def main() -> None:
    parser = argparse.ArgumentParser(
        description="企业微信智能表格同步：默认完整拉取目标智能表格，并写入本地 data 缓存。"
    )
    parser.add_argument("--mode", choices=["auto", "full", "recent", "verify"], default="full")
    parser.add_argument("--recent-limit", type=int, default=50)
    parser.add_argument("--verify-hours", type=int, default=24)
    parser.add_argument("--all", action="store_true", help="同步当前公司可发现的全部智能表格和全部工作表")
    parser.add_argument("--profile", default="", help="临时指定一个 WECOM_ENV_PROFILE，不改写 .env")
    parser.add_argument("--profiles", default="", help="逗号/分号分隔多个 WECOM_ENV_PROFILE，例如 COMPANY_A,COMPANY_B")
    parser.add_argument("--include-invalid", action="store_true", help="包含已确认 invalid_docid/no_access 的历史登记表")
    args = parser.parse_args()

    profile_text = args.profiles or args.profile
    profiles = [
        item.strip()
        for part in profile_text.split(";")
        for item in part.split(",")
        if item.strip()
    ]
    if not profiles:
        profiles = [os.getenv("WECOM_ENV_PROFILE", "")]

    results = []
    for profile in profiles:
        if profile:
            os.environ["WECOM_ENV_PROFILE"] = profile
        if args.all:
            summary = sync_all_smartsheets(
                mode=args.mode,
                recent_limit=args.recent_limit,
                verify_interval_hours=args.verify_hours,
                include_invalid_docids=args.include_invalid,
            )
        else:
            summary = sync_smartsheet(
                mode=args.mode,
                recent_limit=args.recent_limit,
                verify_interval_hours=args.verify_hours,
            )
        results.append(summary)

    summary = results[0] if len(results) == 1 else {"profile_count": len(results), "results": results}
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

