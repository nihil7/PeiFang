"""
Recommended daily entrypoint for WeCom smartsheet maintenance.

Modes:
0 = run the standard flow: import manual links, verify company ownership, sync both companies
1 = import manual links only
2 = verify/correct company ownership only
3 = sync both companies only
4 = rebuild the latest document inventory only
5 = create the manual link template
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from peifang_core.common import now_iso, now_tag, write_json  # noqa: E402
from peifang_core.document_inventory import export_document_inventory  # noqa: E402
from peifang_core.output_manager import archive_outputs, publish_latest  # noqa: E402
from peifang_core.wecom import (  # noqa: E402
    MANUAL_LINKS_PATH,
    create_manual_smartsheet_link_template,
    import_smartsheet_links,
    sync_all_smartsheets,
    verify_registry_doc_profiles,
)


DEFAULT_PROFILES = ["COMPANY_A", "COMPANY_B"]
OUTPUT_DIR = PROJECT_ROOT / "output"


def _split_profiles(value: str) -> list[str]:
    normalized = str(value or "").replace("，", ",").replace("；", ";")
    profiles = [
        item.strip()
        for part in normalized.split(";")
        for item in part.split(",")
        if item.strip()
    ]
    return profiles or DEFAULT_PROFILES


def _ask_mode(default: int = 0) -> int:
    print("请选择企业微信智能表格运行模式：")
    print("0 = 标准流程：导入人工链接 -> 纠正归属公司 -> 同步双公司 -> 刷新 latest")
    print("1 = 只导入人工链接清单，并补全 docid / sheet_id")
    print("2 = 只验证并纠正 registry 里的归属公司 env_profile")
    print("3 = 只同步 COMPANY_A / COMPANY_B")
    print("4 = 只重新生成 output/latest/document_inventory.xlsx")
    print("5 = 创建/刷新人工链接清单模板")
    raw = input(f"MODE [{default}]: ").strip()
    if not raw:
        return default
    try:
        mode = int(raw)
    except ValueError as exc:
        raise RuntimeError("MODE 只能输入 0, 1, 2, 3, 4, 5") from exc
    if mode not in {0, 1, 2, 3, 4, 5}:
        raise RuntimeError("MODE 只能输入 0, 1, 2, 3, 4, 5")
    return mode


def _compact_sync_summary(summary: dict[str, Any]) -> dict[str, Any]:
    errors = summary.get("errors") or []
    errcodes: dict[str, int] = {}
    from_ips: dict[str, int] = {}
    for item in errors:
        error_text = str(item.get("error") or "")
        for errcode in re.findall(r"errcode['\"]?:\s*(\d+)", error_text):
            errcodes[errcode] = errcodes.get(errcode, 0) + 1
        for from_ip in re.findall(r"from ip:\s*([0-9.]+)", error_text):
            from_ips[from_ip] = from_ips.get(from_ip, 0) + 1
    return {
        "env_profile": summary.get("env_profile") or "",
        "app_count": summary.get("app_count", 0),
        "candidate_doc_count": summary.get("candidate_doc_count", 0),
        "synced_sheet_count": summary.get("synced_sheet_count", 0),
        "error_count": summary.get("error_count", 0),
        "errcodes": errcodes,
        "from_ips": from_ips,
    }


def _sync_profiles(
    profiles: list[str],
    sync_mode: str,
    recent_limit: int,
    verify_hours: int,
    include_invalid: bool,
) -> dict[str, Any]:
    old_profile = os.environ.get("WECOM_ENV_PROFILE")
    results: list[dict[str, Any]] = []
    try:
        for profile in profiles:
            os.environ["WECOM_ENV_PROFILE"] = profile
            results.append(
                sync_all_smartsheets(
                    mode=sync_mode,
                    recent_limit=recent_limit,
                    verify_interval_hours=verify_hours,
                    include_invalid_docids=include_invalid,
                )
            )
    finally:
        if old_profile is None:
            os.environ.pop("WECOM_ENV_PROFILE", None)
        else:
            os.environ["WECOM_ENV_PROFILE"] = old_profile

    return {
        "profile_count": len(results),
        "total_synced_sheet_count": sum(int(item.get("synced_sheet_count") or 0) for item in results),
        "total_error_count": sum(int(item.get("error_count") or 0) for item in results),
        "profiles_summary": [_compact_sync_summary(item) for item in results],
        "results": results,
    }


def _write_manager_summary(payload: dict[str, Any]) -> dict[str, str]:
    out_path = OUTPUT_DIR / f"wecom_smartsheet_manager_summary_{now_tag()}.json"
    write_json(out_path, payload)
    latest = publish_latest({"wecom_smartsheet_manager_summary.json": out_path}, OUTPUT_DIR)
    archived = archive_outputs({"wecom_smartsheet_manager_summary.json": out_path}, OUTPUT_DIR)
    return {
        "summary_path": str(out_path),
        "latest_summary_path": latest.get("wecom_smartsheet_manager_summary.json", ""),
        "archive_summary_path": archived.get("wecom_smartsheet_manager_summary.json", ""),
    }


def run_manager(
    mode: int,
    profiles: list[str],
    source: Path,
    sync_mode: str,
    recent_limit: int,
    verify_hours: int,
    include_invalid: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "generated_at": now_iso(),
        "mode": mode,
        "profiles": profiles,
        "source": str(source),
        "steps": {},
    }

    if mode == 5:
        payload["steps"]["template"] = {"template_path": str(create_manual_smartsheet_link_template(source))}
        payload.update(_write_manager_summary(payload))
        return payload

    if mode in {0, 1}:
        if not source.exists():
            payload["steps"]["template"] = {"template_path": str(create_manual_smartsheet_link_template(source))}
            payload["stopped_reason"] = "manual link template was missing; fill it and run again"
            payload.update(_write_manager_summary(payload))
            return payload
        payload["steps"]["import_links"] = import_smartsheet_links(source_path=source, profiles=profiles)

    if mode in {0, 2}:
        payload["steps"]["verify_profiles"] = verify_registry_doc_profiles(profiles=profiles)

    if mode in {0, 3}:
        payload["steps"]["sync"] = _sync_profiles(
            profiles=profiles,
            sync_mode=sync_mode,
            recent_limit=recent_limit,
            verify_hours=verify_hours,
            include_invalid=include_invalid,
        )

    if mode == 4:
        payload["steps"]["document_inventory"] = export_document_inventory()

    payload.update(_write_manager_summary(payload))
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="企业微信智能表格统一主入口")
    parser.add_argument("--mode", type=int, choices=[0, 1, 2, 3, 4, 5], default=None)
    parser.add_argument("--profiles", default="COMPANY_A,COMPANY_B", help="逗号/分号分隔，例如 COMPANY_A,COMPANY_B")
    parser.add_argument("--source", default=str(MANUAL_LINKS_PATH), help="人工链接清单 xlsx/csv")
    parser.add_argument("--sync-mode", choices=["auto", "full", "recent", "verify"], default="auto")
    parser.add_argument("--recent-limit", type=int, default=50)
    parser.add_argument("--verify-hours", type=int, default=24)
    parser.add_argument("--include-invalid", action="store_true", help="追查历史失效 docid 时使用")
    parser.add_argument("--non-interactive", action="store_true", help="不弹出菜单；未传 --mode 时默认 mode=0")
    args = parser.parse_args()

    mode = args.mode
    if mode is None:
        mode = 0 if args.non_interactive else _ask_mode(0)

    result = run_manager(
        mode=mode,
        profiles=_split_profiles(args.profiles),
        source=Path(args.source),
        sync_mode=args.sync_mode,
        recent_limit=args.recent_limit,
        verify_hours=args.verify_hours,
        include_invalid=args.include_invalid,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
