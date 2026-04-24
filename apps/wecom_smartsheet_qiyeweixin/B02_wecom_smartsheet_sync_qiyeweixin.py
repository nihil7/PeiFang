import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from peifang_core.wecom import sync_smartsheet


def main() -> None:
    parser = argparse.ArgumentParser(
        description="企业微信智能表格同步：首次全量落地，后续按时间排序取前50条合并，并定期全量校验。"
    )
    parser.add_argument("--mode", choices=["auto", "full", "recent", "verify"], default="auto")
    parser.add_argument("--recent-limit", type=int, default=50)
    parser.add_argument("--verify-hours", type=int, default=24)
    args = parser.parse_args()

    summary = sync_smartsheet(
        mode=args.mode,
        recent_limit=args.recent_limit,
        verify_interval_hours=args.verify_hours,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
