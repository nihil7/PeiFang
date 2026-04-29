"""
程序简介：封装企业微信智能表格同步逻辑，按当前公司配置获取 token、字段、记录，并写入本地缓存。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from requests import RequestException

from .common import (
    DATA_DIR,
    ROOT_DIR,
    build_verify_report,
    ensure_dir,
    first_text_cell,
    get_env_profile,
    get_profiled_env,
    load_dotenv_for_profile,
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
from .output_manager import archive_outputs, cleanup_output_history, publish_latest


BASE = "https://qyapi.weixin.qq.com/cgi-bin"
REGISTRY_PATH = Path("smartsheet_registry.json")
SORT_FIELD_CANDIDATES = ["更新时间", "修改时间", "最后更新时间", "开始日期", "日期"]
NETWORK_RETRIES = 3
RETRY_SLEEP_SECONDS = 1.5
OUTPUT_DIR = ROOT_DIR / "output"


class WeComSmartsheetClient:
    def __init__(self, corpid: str, secret: str, timeout: int = 15) -> None:
        self.corpid = corpid
        self.secret = secret
        self.timeout = timeout
        self._token: str | None = None

    def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, NETWORK_RETRIES + 1):
            try:
                resp = requests.request(method, url, timeout=self.timeout, **kwargs)
                resp.raise_for_status()
                return resp.json()
            except RequestException as exc:
                last_error = exc
                if attempt < NETWORK_RETRIES:
                    time.sleep(RETRY_SLEEP_SECONDS * attempt)
                    continue
            except ValueError as exc:
                raise RuntimeError(f"企业微信接口返回不是 JSON：{url}") from exc

        raise RuntimeError(
            "企业微信接口连接失败，可能是网络、代理或远端临时断开。"
            "本次同步未完成，未更新本地数据。请稍后重试同步。"
            f" 原始错误：{last_error}"
        ) from last_error

    def access_token(self) -> str:
        if self._token:
            return self._token
        data = self._request_json(
            "GET",
            f"{BASE}/gettoken",
            params={"corpid": self.corpid, "corpsecret": self.secret},
        )
        if data.get("errcode") != 0:
            raise RuntimeError(f"gettoken failed: {data}")
        self._token = str(data["access_token"])
        return self._token

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        data = self._request_json(
            "POST",
            f"{BASE}{path}",
            params={"access_token": self.access_token()},
            json=payload,
        )
        if data.get("errcode") != 0:
            raise RuntimeError(f"{path} failed: {data}")
        return data

    def get_fields(self, docid: str, sheet_id: str) -> dict[str, Any]:
        return self._post("/wedoc/smartsheet/get_fields", {"docid": docid, "sheet_id": sheet_id})

    def get_records(self, docid: str, sheet_id: str) -> dict[str, Any]:
        payload: dict[str, Any] = {"docid": docid, "sheet_id": sheet_id}
        first_page = self._post("/wedoc/smartsheet/get_records", payload)
        records = list(first_page.get("records") or [])
        page_count = 1
        next_cursor = first_page.get("next")

        while first_page.get("has_more") and next_cursor not in (None, ""):
            page_payload = {**payload, "next": next_cursor}
            page = self._post("/wedoc/smartsheet/get_records", page_payload)
            records.extend(page.get("records") or [])
            page_count += 1
            first_page["has_more"] = page.get("has_more")
            next_cursor = page.get("next")
            first_page["next"] = next_cursor

        merged = dict(first_page)
        merged["records"] = records
        merged["fetched_count"] = len(records)
        merged["page_count"] = page_count
        return merged


def resolve_selection(registry_path: Path = REGISTRY_PATH, profile: str | None = None) -> dict[str, str]:
    registry = read_json(registry_path, default={}) or {}
    docs = registry.get("docs") or {}
    profile = profile if profile is not None else get_env_profile("WECOM")

    docid = get_profiled_env("WEDOC_DOCID", namespace="WECOM", profile=profile) or get_profiled_env(
        "SMARTSHEET_ID", namespace="WECOM", profile=profile
    )
    sheet_id = get_profiled_env("WEDOC_SHEET_ID", namespace="WECOM", profile=profile) or get_profiled_env(
        "SMARTSHEET_SHEET_ID", namespace="WECOM", profile=profile
    )
    doc_name = ""
    sheet_title = ""

    if docid and docid in docs:
        doc_entry = docs[docid]
    else:
        target_doc_name = get_profiled_env("WEDOC_DOC_NAME", namespace="WECOM", profile=profile, default="生产任务排期")
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
        target_sheet_title = get_profiled_env(
            "WEDOC_SHEET_TITLE", namespace="WECOM", profile=profile, default="排产·统计总台账"
        )
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


def _field_title(field: dict[str, Any]) -> str:
    return str(field.get("field_title") or field.get("title") or field.get("name") or field.get("field_id") or "").strip()


def _field_id(field: dict[str, Any]) -> str:
    return str(field.get("field_id") or field.get("id") or "").strip()


def _flatten_cell(value: Any) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, list):
        pieces = []
        for item in value:
            text = first_text_cell(item)
            if text:
                pieces.append(text)
        return "、".join(pieces)
    if isinstance(value, dict):
        return first_text_cell(value)
    return str(value).strip()


def _maybe_datetime_text(value: str) -> str:
    if not value or not value.isdigit():
        return value
    try:
        number = int(value)
    except ValueError:
        return value
    if number < 10_000_000_000:
        return value
    try:
        return datetime.fromtimestamp(number / 1000).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return value


def export_records_table(
    records: list[dict[str, Any]],
    fields_raw: dict[str, Any],
    doc_name: str,
    sheet_title: str,
    generated_at: str,
) -> dict[str, str]:
    fields = fields_raw.get("fields") or []
    field_pairs = [(_field_id(field), _field_title(field)) for field in fields if _field_title(field)]
    seen_titles: set[str] = set()
    rows: list[dict[str, Any]] = []

    for index, record in enumerate(records, start=1):
        values = record.get("values") or {}
        row: dict[str, Any] = {
            "_序号": index,
            "_record_id": record.get("record_id") or record.get("_record_id") or "",
            "_create_time": _maybe_datetime_text(str(record.get("create_time") or "")),
            "_update_time": _maybe_datetime_text(str(record.get("update_time") or "")),
            "_creator_name": record.get("creator_name") or "",
            "_updater_name": record.get("updater_name") or "",
        }
        for field_id, title in field_pairs:
            raw_value = values.get(title)
            if raw_value is None and field_id:
                raw_value = values.get(field_id)
            row[title] = _maybe_datetime_text(_flatten_cell(raw_value))
            seen_titles.add(title)
        for key in values:
            if key not in seen_titles and key not in row:
                row[str(key)] = _maybe_datetime_text(_flatten_cell(values.get(key)))
        rows.append(row)

    tag = now_tag()
    safe_prefix = "wecom_smartsheet_full"
    out_csv = OUTPUT_DIR / f"{safe_prefix}_{tag}.csv"
    out_xlsx = OUTPUT_DIR / f"{safe_prefix}_{tag}.xlsx"
    df = pd.DataFrame(rows)
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="完整表格")
        meta = pd.DataFrame(
            [
                {"项目": "文档", "值": doc_name},
                {"项目": "表格", "值": sheet_title},
                {"项目": "生成时间", "值": generated_at},
                {"项目": "记录数", "值": len(records)},
            ]
        )
        meta.to_excel(writer, index=False, sheet_name="导出说明")

    latest = publish_latest(
        {
            "wecom_smartsheet_full.csv": out_csv,
            "wecom_smartsheet_full.xlsx": out_xlsx,
        },
        OUTPUT_DIR,
    )
    archived = archive_outputs(
        {
            "wecom_smartsheet_full.csv": out_csv,
            "wecom_smartsheet_full.xlsx": out_xlsx,
        },
        OUTPUT_DIR,
    )
    cleanup_output_history(OUTPUT_DIR)
    return {
        "csv_path": str(out_csv),
        "xlsx_path": str(out_xlsx),
        "latest_csv_path": latest.get("wecom_smartsheet_full.csv", ""),
        "latest_xlsx_path": latest.get("wecom_smartsheet_full.xlsx", ""),
        "archive_csv_path": archived.get("wecom_smartsheet_full.csv", ""),
        "archive_xlsx_path": archived.get("wecom_smartsheet_full.xlsx", ""),
    }


def sync_smartsheet(
    mode: str = "auto",
    recent_limit: int = 50,
    verify_interval_hours: int = 24,
    registry_path: Path = REGISTRY_PATH,
) -> dict[str, Any]:
    profile = load_dotenv_for_profile("WECOM")
    corpid = get_profiled_env("WECOM_CORP_ID", namespace="WECOM", profile=profile)
    secret = get_profiled_env("WECOM_APP_SECRET", namespace="WECOM", profile=profile)
    if not corpid or not secret:
        raise RuntimeError("缺少 WECOM_CORP_ID / WECOM_APP_SECRET")

    selection = resolve_selection(registry_path, profile=profile)
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
        "remote_total": remote_raw.get("total", len(remote_sorted)),
        "remote_has_more": bool(remote_raw.get("has_more")),
        "remote_page_count": int(remote_raw.get("page_count") or 1),
        "is_full_fetch": (not remote_raw.get("has_more"))
        and len(remote_sorted) >= int(remote_raw.get("total") or len(remote_sorted)),
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
        summary["table_export"] = export_records_table(
            remote_sorted,
            fields_raw,
            selection["doc_name"],
            selection["sheet_title"],
            summary["generated_at"],
        )
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

