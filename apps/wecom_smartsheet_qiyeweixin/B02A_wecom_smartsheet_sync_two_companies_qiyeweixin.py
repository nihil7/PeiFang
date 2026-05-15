"""
Stable two-company WeCom smartsheet sync entrypoint.

This script is the daily-use wrapper around B02:
- syncs COMPANY_A and COMPANY_B without editing .env;
- skips docids already confirmed invalid/no-access by default;
- writes a compact run summary to output/latest/wecom_two_company_sync_summary.json.
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

from peifang_core.common import now_iso, now_tag, write_json
from peifang_core.output_manager import archive_outputs, publish_latest
from peifang_core.wecom import sync_all_smartsheets


OUTPUT_DIR = PROJECT_ROOT / "output"


def _split_profiles(text: str) -> list[str]:
    profiles = [
        item.strip()
        for part in str(text or "").split(";")
        for item in part.split(",")
        if item.strip()
    ]
    return profiles or ["COMPANY_A", "COMPANY_B"]


def _compact_profile_summary(summary: dict[str, Any]) -> dict[str, Any]:
    errors = summary.get("errors") or []
    error_counts: dict[str, int] = {}
    errcodes: dict[str, int] = {}
    from_ips: dict[str, int] = {}
    for item in errors:
        stage = str(item.get("stage") or "unknown")
        error_counts[stage] = error_counts.get(stage, 0) + 1
        error_text = str(item.get("error") or "")
        for errcode in re.findall(r"errcode['\"]?:\s*(\d+)", error_text):
            errcodes[errcode] = errcodes.get(errcode, 0) + 1
        for from_ip in re.findall(r"from ip:\s*([0-9.]+)", error_text):
            from_ips[from_ip] = from_ips.get(from_ip, 0) + 1

    return {
        "env_profile": summary.get("env_profile") or "",
        "app_count": summary.get("app_count", 0),
        "candidate_doc_count": summary.get("candidate_doc_count", 0),
        "wedrive_discovered_doc_count": summary.get("wedrive_discovered_doc_count", 0),
        "synced_sheet_count": summary.get("synced_sheet_count", 0),
        "error_count": summary.get("error_count", 0),
        "error_counts": error_counts,
        "errcodes": errcodes,
        "from_ips": from_ips,
        "document_inventory": summary.get("document_inventory") or {},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="稳定同步 A/B 两家公司企业微信智能表格数据")
    parser.add_argument("--profiles", default="COMPANY_A,COMPANY_B", help="逗号/分号分隔，例如 COMPANY_A,COMPANY_B")
    parser.add_argument("--mode", choices=["auto", "full", "recent", "verify"], default="auto")
    parser.add_argument("--recent-limit", type=int, default=50)
    parser.add_argument("--verify-hours", type=int, default=24)
    parser.add_argument("--include-invalid", action="store_true", help="追查历史失效 docid 时使用")
    args = parser.parse_args()

    profiles = _split_profiles(args.profiles)
    results = []
    for profile in profiles:
        os.environ["WECOM_ENV_PROFILE"] = profile
        result = sync_all_smartsheets(
            mode=args.mode,
            recent_limit=args.recent_limit,
            verify_interval_hours=args.verify_hours,
            include_invalid_docids=args.include_invalid,
        )
        results.append(result)

    compact = [_compact_profile_summary(item) for item in results]
    payload = {
        "generated_at": now_iso(),
        "mode": args.mode,
        "profiles": profiles,
        "include_invalid": bool(args.include_invalid),
        "profile_count": len(results),
        "total_synced_sheet_count": sum(int(item.get("synced_sheet_count") or 0) for item in results),
        "total_error_count": sum(int(item.get("error_count") or 0) for item in results),
        "profiles_summary": compact,
        "results": results,
    }

    out_path = OUTPUT_DIR / f"wecom_two_company_sync_summary_{now_tag()}.json"
    write_json(out_path, payload)
    latest = publish_latest({"wecom_two_company_sync_summary.json": out_path}, OUTPUT_DIR)
    archive = archive_outputs({"wecom_two_company_sync_summary.json": out_path}, OUTPUT_DIR)

    payload["latest_summary_path"] = latest.get("wecom_two_company_sync_summary.json", "")
    payload["archive_summary_path"] = archive.get("wecom_two_company_sync_summary.json", "")
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
