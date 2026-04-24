from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import requests
from dotenv import load_dotenv

from .common import (
    DATA_DIR,
    build_verify_report,
    ensure_dir,
    first_text_cell,
    merge_records,
    now_iso,
    now_tag,
    read_json,
    should_verify_full,
    sort_records,
    stable_record_id,
    write_json,
    write_text,
)


BASE = "https://qyapi.weixin.qq.com/cgi-bin"
REGISTRY_PATH = Path("smartsheet_registry.json")
SORT_FIELD_CANDIDATES = ["更新时间", "修改时间", "最后更新时间", "开始日期", "日期"]


class WeComSmartsheetClient:
    def __init__(self, corpid: str, secret: str, timeout: int = 15) -> None:
        self.corpid = corpid
        self.secret = secret
        self.timeout = timeout
        self._token: str | None = None

    def access_token(self) -> str:
        if self._token:
            return self._token
        resp = requests.get(
            f"{BASE}/gettoken",
            params={"corpid": self.corpid, "corpsecret": self.secret},
            timeout=self.timeout,
        )
        data = resp.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"gettoken failed: {data}")
        self._token = str(data["access_token"])
        return self._token

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        resp = requests.post(
            f"{BASE}{path}",
            params={"access_token": self.access_token()},
            json=payload,
            timeout=self.timeout,
        )
        data = resp.json()
        if data.get("errcode") != 0:
            raise RuntimeError(f"{path} failed: {data}")
        return data

    def get_fields(self, docid: str, sheet_id: str) -> dict[str, Any]:
        return self._post("/wedoc/smartsheet/get_fields", {"docid": docid, "sheet_id": sheet_id})

    def get_records(self, docid: str, sheet_id: str) -> dict[str, Any]:
        return self._post("/wedoc/smartsheet/get_records", {"docid": docid, "sheet_id": sheet_id})


def resolve_selection(registry_path: Path = REGISTRY_PATH) -> dict[str, str]:
    registry = read_json(registry_path, default={}) or {}
    docs = registry.get("docs") or {}

    docid = (os.getenv("WEDOC_DOCID") or os.getenv("SMARTSHEET_ID") or "").strip()
    sheet_id = (os.getenv("WEDOC_SHEET_ID") or os.getenv("SMARTSHEET_SHEET_ID") or "").strip()
    doc_name = ""
    sheet_title = ""

    if docid and docid in docs:
        doc_entry = docs[docid]
    else:
        target_doc_name = (os.getenv("WEDOC_DOC_NAME") or "生产任务排期").strip()
        doc_entry = None
        for item in docs.values():
            if (item.get("doc_name") or "").strip() == target_doc_name:
                doc_entry = item
                break
        if doc_entry:
            docid = str(doc_entry.get("docid") or "")

    if not docid or not doc_entry:
        raise RuntimeError("无法从 .env 或 smartsheet_registry.json 解析目标 docid")

    doc_name = str(doc_entry.get("doc_name") or docid)
    sheets = doc_entry.get("sheets") or {}

    if sheet_id and sheet_id in sheets:
        sheet_entry = sheets[sheet_id]
    else:
        target_sheet_title = (os.getenv("WEDOC_SHEET_TITLE") or "排产·统计总台账").strip()
        sheet_entry = None
        for item in sheets.values():
            if (item.get("title") or "").strip() == target_sheet_title:
                sheet_entry = item
                break
        if sheet_entry:
            sheet_id = str(sheet_entry.get("sheet_id") or "")

    if not sheet_id or not sheet_entry:
        raise RuntimeError("无法从 .env 或 smartsheet_registry.json 解析目标 sheet_id")

    sheet_title = str(sheet_entry.get("title") or sheet_id)
    return {
        "docid": docid,
        "sheet_id": sheet_id,
        "doc_name": doc_name,
        "sheet_title": sheet_title,
    }


def build_storage_paths(docid: str, sheet_id: str) -> dict[str, Path]:
    base_dir = ensure_dir(DATA_DIR / "wecom" / "smartsheet" / docid / sheet_id)
    return {
        "base_dir": base_dir,
        "fields_latest": base_dir / "fields_latest.json",
        "full_latest": base_dir / "records_full_latest.json",
        "recent_latest": base_dir / "records_recent_latest.json",
        "merged_latest": base_dir / "records_merged_latest.json",
        "preview_latest": base_dir / "preview_latest.txt",
        "state": base_dir / "sync_state.json",
        "verify_latest": base_dir / "verify_latest.json",
        "history_dir": ensure_dir(base_dir / "history"),
    }


def parse_fields(fields_data: dict[str, Any]) -> list[dict[str, Any]]:
    fields = fields_data.get("fields") or fields_data.get("field_list") or fields_data.get("data") or []
    if isinstance(fields, dict):
        fields = fields.get("fields") or fields.get("field_list") or []
    out = []
    for field in fields:
        if not isinstance(field, dict):
            continue
        out.append(
            {
                "field_id": field.get("field_id") or field.get("id") or "",
                "title": field.get("title") or field.get("name") or "",
                "type": field.get("type") or field.get("field_type") or "",
                "raw": field,
            }
        )
    return out


def build_preview(records: list[dict[str, Any]], fields: list[dict[str, Any]], limit: int = 10) -> str:
    id_to_title = {str(item.get("field_id") or ""): str(item.get("title") or "") for item in fields}
    lines = []
    for idx, record in enumerate(records[:limit], start=1):
        values = record.get("values") or {}
        pieces = []
        for key, value in values.items():
            title = id_to_title.get(str(key), str(key))
            pieces.append(f"{title}={first_text_cell(value)}")
        rid = stable_record_id(record)
        lines.append(f"{idx:02d}. [{rid}] " + " | ".join(pieces[:8]))
    return "\n".join(lines)


def sync_smartsheet(
    mode: str = "auto",
    recent_limit: int = 50,
    verify_interval_hours: int = 24,
    registry_path: Path = REGISTRY_PATH,
) -> dict[str, Any]:
    load_dotenv()
    corpid = (os.getenv("WECOM_CORP_ID") or "").strip()
    secret = (os.getenv("WECOM_APP_SECRET") or "").strip()
    if not corpid or not secret:
        raise RuntimeError("缺少 WECOM_CORP_ID / WECOM_APP_SECRET")

    selection = resolve_selection(registry_path)
    client = WeComSmartsheetClient(corpid=corpid, secret=secret)
    paths = build_storage_paths(selection["docid"], selection["sheet_id"])
    state = read_json(paths["state"], default={}) or {}

    effective_mode = mode
    if mode == "auto":
        if not paths["merged_latest"].exists():
            effective_mode = "full"
        elif should_verify_full(state, verify_interval_hours):
            effective_mode = "verify"
        else:
            effective_mode = "recent"

    fields_raw = client.get_fields(selection["docid"], selection["sheet_id"])
    fields = parse_fields(fields_raw)
    write_json(paths["fields_latest"], fields_raw)

    remote_raw = client.get_records(selection["docid"], selection["sheet_id"])
    remote_records = remote_raw.get("records") or []
    remote_sorted = sort_records(remote_records, SORT_FIELD_CANDIDATES)
    recent_records = remote_sorted[: max(1, recent_limit)]
    existing_merged = (read_json(paths["merged_latest"], default={}) or {}).get("records") or []

    summary: dict[str, Any] = {
        "docid": selection["docid"],
        "sheet_id": selection["sheet_id"],
        "doc_name": selection["doc_name"],
        "sheet_title": selection["sheet_title"],
        "effective_mode": effective_mode,
        "remote_count": len(remote_sorted),
        "recent_limit": recent_limit,
        "generated_at": now_iso(),
        "storage_dir": str(paths["base_dir"]),
    }

    if effective_mode in {"full", "verify"}:
        merged_payload = {
            "generated_at": now_iso(),
            "doc_name": selection["doc_name"],
            "sheet_title": selection["sheet_title"],
            "records": remote_sorted,
        }
        write_json(paths["full_latest"], {"generated_at": now_iso(), "records": remote_sorted, "raw": remote_raw})
        write_json(paths["merged_latest"], merged_payload)
        state["last_full_sync_at"] = now_iso()
        if effective_mode == "verify":
            report = build_verify_report(existing_merged, remote_sorted, SORT_FIELD_CANDIDATES)
            write_json(paths["verify_latest"], report)
            state["last_verify_at"] = now_iso()
            summary["verify_report"] = report
        summary["merged_total"] = len(remote_sorted)
        summary["created"] = len(remote_sorted)
        summary["updated"] = 0
    else:
        write_json(paths["recent_latest"], {"generated_at": now_iso(), "records": recent_records})
        merged = merge_records(existing_merged, recent_records, SORT_FIELD_CANDIDATES)
        write_json(
            paths["merged_latest"],
            {
                "generated_at": now_iso(),
                "doc_name": selection["doc_name"],
                "sheet_title": selection["sheet_title"],
                "records": merged["records"],
            },
        )
        state["last_incremental_sync_at"] = now_iso()
        summary["merged_total"] = merged["total"]
        summary["created"] = merged["created"]
        summary["updated"] = merged["updated"]

    preview = build_preview(remote_sorted, fields)
    write_text(paths["preview_latest"], preview)
    write_text(paths["history_dir"] / f"preview_{now_tag()}.txt", preview)

    state["last_remote_count"] = len(remote_sorted)
    state["last_effective_mode"] = effective_mode
    state["last_recent_limit"] = recent_limit
    state["last_run_at"] = now_iso()
    state["strategy_note"] = "WeCom current implementation fetches current records and then applies local sort/merge."
    write_json(paths["state"], state)

    summary["preview_path"] = str(paths["preview_latest"])
    summary["merged_path"] = str(paths["merged_latest"])
    summary["fields_path"] = str(paths["fields_latest"])
    summary["state_path"] = str(paths["state"])
    return summary
