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
