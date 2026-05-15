"""
Build a local guide table for all fetched Feishu and WeCom documents.

The inventory is meant for two uses:
- humans can confirm which documents/sheets have been registered or cached;
- AI assistants can locate the exact local JSON cache before writing code.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pandas as pd

from .common import DATA_DIR, ROOT_DIR, now_iso, now_tag, read_json
from .output_manager import archive_outputs, cleanup_output_history, publish_latest


OUTPUT_DIR = ROOT_DIR / "output"
REGISTRY_PATH = ROOT_DIR / "smartsheet_registry.json"


def _count_items(payload: Any, keys: tuple[str, ...]) -> int:
    if not isinstance(payload, dict):
        return 0
    for key in keys:
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
        if isinstance(value, dict):
            nested = _count_items(value, keys)
            if nested:
                return nested
    return 0


def _records_count(path: Path) -> int:
    payload = read_json(path, default={}) or {}
    return _count_items(payload, ("records", "items"))


def _fields_count(path: Path) -> int:
    payload = read_json(path, default={}) or {}
    return _count_items(payload, ("fields", "field_list", "items", "data"))


def _json_value(path: Path, key: str, default: str = "") -> str:
    payload = read_json(path, default={}) or {}
    value = payload.get(key) if isinstance(payload, dict) else None
    return str(value if value not in (None, "") else default)


def _mtime(path: Path) -> str:
    if not path.exists():
        return ""
    return pd.Timestamp(path.stat().st_mtime, unit="s").strftime("%Y-%m-%d %H:%M:%S")


def _has(path: Path) -> str:
    return "yes" if path.exists() else "no"


def _path_text(path: Path) -> str:
    return str(path) if path.exists() else ""


def _raw_meta(raw: dict[str, Any], *keys: str) -> str:
    if not isinstance(raw, dict):
        return ""
    containers = [raw, raw.get("properties") if isinstance(raw.get("properties"), dict) else {}]
    for container in containers:
        for key in keys:
            value = container.get(key)
            if value not in (None, ""):
                return str(value)
    return ""


def _latest_profile_access(profile_access: dict[str, Any]) -> dict[str, str]:
    status = str(profile_access.get("status") or "")
    error = str(profile_access.get("error") or "")
    checked_at = str(profile_access.get("checked_at") or "")
    apps = profile_access.get("apps") if isinstance(profile_access, dict) else None
    if isinstance(apps, dict):
        latest_app = None
        for app_access in apps.values():
            if not isinstance(app_access, dict):
                continue
            app_checked_at = str(app_access.get("checked_at") or "")
            if latest_app is None or app_checked_at >= str(latest_app.get("checked_at") or ""):
                latest_app = app_access
        if latest_app:
            status = str(latest_app.get("status") or status)
            error = str(latest_app.get("error") or error)
            checked_at = str(latest_app.get("checked_at") or checked_at)
    if status == "error" and ("301085" in error or "invalid docid" in error.lower()):
        status = "invalid_docid"
    return {"status": status, "error": error, "checked_at": checked_at}


def _wecom_registry_rows(registry_path: Path) -> list[dict[str, Any]]:
    registry = read_json(registry_path, default={}) or {}
    rows: list[dict[str, Any]] = []
    for docid, doc in (registry.get("docs") or {}).items():
        sheets = doc.get("sheets") or {}
        if not sheets:
            sheets = {"": {}}
        for sheet_id, sheet in sheets.items():
            account_profile = doc.get("env_profile") or ""
            profile_access = (doc.get("profile_access") or {}).get(account_profile) or {}
            latest_access = _latest_profile_access(profile_access)
            access_status = latest_access.get("status") or ""
            row_status = access_status or ("missing" if sheet.get("missing") else "active")
            cache_dir = DATA_DIR / "wecom" / "smartsheet" / str(docid) / str(sheet_id)
            merged = cache_dir / "records_merged_latest.json"
            fields = cache_dir / "fields_latest.json"
            state = cache_dir / "sync_state.json"
            rows.append(
                {
                    "platform": "wecom",
                    "account_profile": account_profile or _json_value(state, "env_profile"),
                    "company_name": doc.get("company_name") or "",
                    "document_name": doc.get("doc_name") or "",
                    "sheet_name": sheet.get("title") or "",
                    "document_id": docid,
                    "sheet_or_table_id": sheet_id,
                    "source": "registry+cache" if cache_dir.exists() else "registry",
                    "status": row_status,
                    "access_error": latest_access.get("error") or "",
                    "creator_name": _raw_meta(sheet.get("raw") or {}, "creator_name", "creator", "create_user_name", "owner_name"),
                    "creator_userid": _raw_meta(sheet.get("raw") or {}, "creator_userid", "creator_user_id", "create_userid", "owner_userid"),
                    "created_at": _raw_meta(sheet.get("raw") or {}, "create_time", "created_at", "ctime"),
                    "updater_name": _raw_meta(sheet.get("raw") or {}, "updater_name", "modifier_name", "update_user_name"),
                    "updated_at": _raw_meta(sheet.get("raw") or {}, "update_time", "updated_at", "mtime"),
                    "manual_tab": doc.get("manual_tab") or "",
                    "manual_view_id": doc.get("manual_view_id") or "",
                    "manual_remark": doc.get("manual_remark") or "",
                    "record_count": _records_count(merged),
                    "field_count": _fields_count(fields),
                    "last_registry_sync_at": doc.get("last_sync_at") or "",
                    "last_cache_run_at": _json_value(state, "last_run_at"),
                    "cache_updated_at": _mtime(merged),
                    "doc_url": doc.get("url") or "",
                    "cache_dir": _path_text(cache_dir),
                    "records_path": _path_text(merged),
                    "fields_path": _path_text(fields),
                    "state_path": _path_text(state),
                    "has_records": _has(merged),
                    "has_fields": _has(fields),
                    "ai_locator": (
                        f"platform=wecom docid={docid} sheet_id={sheet_id} "
                        f"records={merged} fields={fields}"
                    ),
                }
            )
    return rows


def _wecom_cache_rows(existing_keys: set[tuple[str, str]]) -> list[dict[str, Any]]:
    root = DATA_DIR / "wecom" / "smartsheet"
    rows: list[dict[str, Any]] = []
    if not root.exists():
        return rows
    for doc_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        for sheet_dir in sorted(path for path in doc_dir.iterdir() if path.is_dir()):
            key = (doc_dir.name, sheet_dir.name)
            if key in existing_keys:
                continue
            merged = sheet_dir / "records_merged_latest.json"
            fields = sheet_dir / "fields_latest.json"
            state = sheet_dir / "sync_state.json"
            rows.append(
                {
                    "platform": "wecom",
                    "account_profile": _json_value(state, "env_profile"),
                    "document_name": _json_value(merged, "doc_name"),
                    "sheet_name": _json_value(merged, "sheet_title"),
                    "document_id": doc_dir.name,
                    "sheet_or_table_id": sheet_dir.name,
                    "source": "cache",
                    "status": "cached_only",
                    "access_error": "",
                    "record_count": _records_count(merged),
                    "field_count": _fields_count(fields),
                    "last_registry_sync_at": "",
                    "last_cache_run_at": _json_value(state, "last_run_at"),
                    "cache_updated_at": _mtime(merged),
                    "doc_url": "",
                    "cache_dir": str(sheet_dir),
                    "records_path": _path_text(merged),
                    "fields_path": _path_text(fields),
                    "state_path": _path_text(state),
                    "has_records": _has(merged),
                    "has_fields": _has(fields),
                    "ai_locator": (
                        f"platform=wecom docid={doc_dir.name} sheet_id={sheet_dir.name} "
                        f"records={merged} fields={fields}"
                    ),
                }
            )
    return rows


def _feishu_rows() -> list[dict[str, Any]]:
    root = DATA_DIR / "feishu" / "bitable"
    rows: list[dict[str, Any]] = []
    if not root.exists():
        return rows
    for app_dir in sorted(path for path in root.iterdir() if path.is_dir()):
        for table_dir in sorted(path for path in app_dir.iterdir() if path.is_dir()):
            merged = table_dir / "records_merged_latest.json"
            fields = table_dir / "fields_latest.json"
            state = table_dir / "sync_state.json"
            rows.append(
                {
                    "platform": "feishu",
                    "account_profile": _json_value(state, "env_profile"),
                    "document_name": _json_value(state, "app_name"),
                    "sheet_name": _json_value(state, "table_name"),
                    "document_id": app_dir.name,
                    "sheet_or_table_id": table_dir.name,
                    "source": "cache",
                    "status": "cached",
                    "access_error": "",
                    "record_count": _records_count(merged),
                    "field_count": _fields_count(fields),
                    "last_registry_sync_at": "",
                    "last_cache_run_at": _json_value(state, "last_run_at"),
                    "cache_updated_at": _mtime(merged),
                    "doc_url": _json_value(state, "wiki_url"),
                    "cache_dir": str(table_dir),
                    "records_path": _path_text(merged),
                    "fields_path": _path_text(fields),
                    "state_path": _path_text(state),
                    "has_records": _has(merged),
                    "has_fields": _has(fields),
                    "ai_locator": (
                        f"platform=feishu app_token={app_dir.name} table_id={table_dir.name} "
                        f"records={merged} fields={fields}"
                    ),
                }
            )
    return rows


def build_document_inventory(registry_path: Path = REGISTRY_PATH) -> list[dict[str, Any]]:
    rows = _wecom_registry_rows(registry_path)
    wecom_keys = {
        (str(row["document_id"]), str(row["sheet_or_table_id"]))
        for row in rows
        if row.get("platform") == "wecom"
    }
    rows.extend(_wecom_cache_rows(wecom_keys))
    rows.extend(_feishu_rows())
    rows.sort(
        key=lambda row: (
            str(row.get("platform") or ""),
            str(row.get("account_profile") or ""),
            str(row.get("document_name") or ""),
            str(row.get("sheet_name") or ""),
            str(row.get("document_id") or ""),
            str(row.get("sheet_or_table_id") or ""),
        )
    )
    return rows


def export_document_inventory(registry_path: Path = REGISTRY_PATH) -> dict[str, str]:
    generated_at = now_iso()
    rows = build_document_inventory(registry_path)
    tag = now_tag()
    out_csv = OUTPUT_DIR / f"document_inventory_{tag}.csv"
    out_xlsx = OUTPUT_DIR / f"document_inventory_{tag}.xlsx"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(
            columns=[
                "platform",
                "account_profile",
                "document_name",
                "sheet_name",
                "document_id",
                "sheet_or_table_id",
                "source",
                "status",
                "record_count",
                "field_count",
                "records_path",
                "fields_path",
                "ai_locator",
            ]
        )
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="documents")
        pd.DataFrame(
            [
                {"key": "generated_at", "value": generated_at},
                {"key": "row_count", "value": len(rows)},
                {"key": "purpose", "value": "Document/cache guide for human review and AI code navigation."},
            ]
        ).to_excel(writer, index=False, sheet_name="guide")

    latest = publish_latest(
        {
            "document_inventory.csv": out_csv,
            "document_inventory.xlsx": out_xlsx,
        },
        OUTPUT_DIR,
    )
    archived = archive_outputs(
        {
            "document_inventory.csv": out_csv,
            "document_inventory.xlsx": out_xlsx,
        },
        OUTPUT_DIR,
    )
    cleanup_output_history(OUTPUT_DIR)
    return {
        "csv_path": str(out_csv),
        "xlsx_path": str(out_xlsx),
        "latest_csv_path": latest.get("document_inventory.csv", ""),
        "latest_xlsx_path": latest.get("document_inventory.xlsx", ""),
        "archive_csv_path": archived.get("document_inventory.csv", ""),
        "archive_xlsx_path": archived.get("document_inventory.xlsx", ""),
        "row_count": str(len(rows)),
    }
