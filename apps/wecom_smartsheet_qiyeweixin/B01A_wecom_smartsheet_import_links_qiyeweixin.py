"""
Import manually collected WeCom smartsheet links into smartsheet_registry.json.

The source file is meant for human maintenance:
data/wecom/manual_smartsheet_links.xlsx
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from peifang_core.wecom import (  # noqa: E402
    MANUAL_LINKS_PATH,
    create_manual_smartsheet_link_template,
    import_smartsheet_links,
)


def _profiles(value: str) -> list[str]:
    return [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="Import manual WeCom smartsheet links and refresh sheet IDs.")
    parser.add_argument("--source", default=str(MANUAL_LINKS_PATH), help="Excel/CSV link list path")
    parser.add_argument("--profiles", default="", help="Optional comma-separated profiles, e.g. COMPANY_A,COMPANY_B")
    parser.add_argument("--init-template", action="store_true", help="Create a starter Excel link list and exit")
    args = parser.parse_args()

    source = Path(args.source)
    if args.init_template:
        path = create_manual_smartsheet_link_template(source)
        print(json.dumps({"template_path": str(path)}, ensure_ascii=False, indent=2))
        return

    if not source.exists():
        path = create_manual_smartsheet_link_template(source)
        print(f"未找到人工链接清单，已创建模板：{path}")
        print("请填写后重新运行本脚本。")
        return

    result = import_smartsheet_links(source_path=source, profiles=_profiles(args.profiles))
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
