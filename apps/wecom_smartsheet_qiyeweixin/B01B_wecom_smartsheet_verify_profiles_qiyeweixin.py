"""
Verify which company profile can access each registered WeCom smartsheet.

Manual modes:
0 = verify registry doc ownership and correct env_profile
1 = verify/correct, then run the stable two-company sync
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

from peifang_core.common import write_json  # noqa: E402
from peifang_core.wecom import sync_all_smartsheets, verify_registry_doc_profiles  # noqa: E402


DEFAULT_PROFILES = ["COMPANY_A", "COMPANY_B"]


def _profiles(value: str) -> list[str]:
    items = [item.strip() for item in value.replace("，", ",").split(",") if item.strip()]
    return items or DEFAULT_PROFILES


def _ask_mode(default: int = 0) -> int:
    print("请选择运行模式：")
    print("0 = 验证 registry 里所有智能表格归属，并自动纠正 env_profile")
    print("1 = 先纠正归属，然后同步 COMPANY_A / COMPANY_B")
    raw = input(f"MODE [{default}]: ").strip()
    if not raw:
        return default
    try:
        mode = int(raw)
    except ValueError as exc:
        raise RuntimeError("MODE 只能输入 0 或 1") from exc
    if mode not in {0, 1}:
        raise RuntimeError("MODE 只能输入 0 或 1")
    return mode


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify/correct WeCom smartsheet company ownership.")
    parser.add_argument("--mode", type=int, choices=[0, 1], default=None, help="0=verify only, 1=verify then sync")
    parser.add_argument("--profiles", default="COMPANY_A,COMPANY_B", help="Comma-separated profiles to test")
    parser.add_argument("--non-interactive", action="store_true", help="Do not prompt; default to mode 0")
    args = parser.parse_args()

    mode = args.mode
    if mode is None:
        mode = 0 if args.non_interactive else _ask_mode(0)

    profiles = _profiles(args.profiles)
    result = verify_registry_doc_profiles(profiles=profiles)
    summary: dict[str, object] = {"mode": mode, "profile_verification": result}

    if mode == 1:
        sync_results = []
        old_profile = os.environ.get("WECOM_ENV_PROFILE")
        try:
            for profile in profiles:
                os.environ["WECOM_ENV_PROFILE"] = profile
                sync_results.append(sync_all_smartsheets(mode="auto"))
        finally:
            if old_profile is None:
                os.environ.pop("WECOM_ENV_PROFILE", None)
            else:
                os.environ["WECOM_ENV_PROFILE"] = old_profile
        summary["sync_results"] = sync_results
        write_json(PROJECT_ROOT / "output" / "latest" / "wecom_verify_profiles_sync_summary.json", summary)

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
