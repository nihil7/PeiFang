"""
程序简介：封装企业微信智能表格同步逻辑，按当前公司配置获取 token、字段、记录，并写入本地缓存。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

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
from .document_inventory import export_document_inventory
from .output_manager import archive_outputs, cleanup_output_history, publish_latest


BASE = "https://qyapi.weixin.qq.com/cgi-bin"
REGISTRY_PATH = Path("smartsheet_registry.json")
SORT_FIELD_CANDIDATES = ["更新时间", "修改时间", "最后更新时间", "开始日期", "日期"]
NETWORK_RETRIES = 3
RETRY_SLEEP_SECONDS = 1.5
OUTPUT_DIR = ROOT_DIR / "output"
MANUAL_LINKS_PATH = DATA_DIR / "wecom" / "manual_smartsheet_links.xlsx"
ENV_LIST_SEPARATORS = (";", ",", "\n")
MAX_NUMBERED_ENV_ITEMS = 20
SENSITIVE_URL_PARAMS = {
    "access_token",
    "authcode",
    "code",
    "corpsecret",
    "scode",
    "sid",
    "skey",
    "ticket",
    "token",
    "wedrive_sid",
    "wedrive_skey",
    "wedrive_ticket",
    "wwmng_authcode",
}


class WeComSmartsheetClient:
    def __init__(self, corpid: str, secret: str, timeout: int = 15, use_system_proxy: bool = False) -> None:
        self.corpid = corpid
        self.secret = secret
        self.timeout = timeout
        self._token: str | None = None
        self.session = requests.Session()
        self.session.trust_env = use_system_proxy

    @staticmethod
    def _redact_url(url: str) -> str:
        parts = urlsplit(url)
        query = []
        for key, value in parse_qsl(parts.query, keep_blank_values=True):
            if key.lower() in {"corpsecret", "access_token"}:
                query.append((key, "***"))
            else:
                query.append((key, value))
        return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))

    def _request_json(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        last_error: Exception | None = None
        for attempt in range(1, NETWORK_RETRIES + 1):
            try:
                resp = self.session.request(method, url, timeout=self.timeout, **kwargs)
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
            f" 请求地址：{self._redact_url(url)}"
            f" 原始错误类型：{type(last_error).__name__ if last_error else 'unknown'}"
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

    def get_sheets(self, docid: str) -> list[dict[str, Any]]:
        data = self._post("/wedoc/smartsheet/get_sheet", {"docid": docid})
        sheets = data.get("sheets") or data.get("sheet_list") or data.get("data") or []
        if isinstance(sheets, dict):
            sheets = sheets.get("sheets") or sheets.get("sheet_list") or []
        return sheets if isinstance(sheets, list) else []

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

    def list_wedrive_files(
        self,
        spaceid: str,
        fatherid: str = "",
        recursive: bool = True,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        start: int | str = 0
        parent = fatherid or spaceid
        items: list[dict[str, Any]] = []
        seen_folders: set[str] = set()

        while True:
            payload: dict[str, Any] = {
                "spaceid": spaceid,
                "fatherid": parent,
                "sort_type": 1,
                "start": start,
                "limit": limit,
            }
            data = self._post("/wedrive/file_list", payload)
            raw_items = ((data.get("file_list") or {}).get("item") or data.get("item") or [])
            if isinstance(raw_items, list):
                items.extend(item for item in raw_items if isinstance(item, dict))

            if not data.get("has_more"):
                break
            next_start = data.get("next_start")
            if next_start in (None, "", start):
                break
            start = next_start

        if not recursive:
            return items

        for item in list(items):
            fileid = str(item.get("fileid") or "")
            if not fileid or fileid in seen_folders:
                continue
            file_type = str(item.get("file_type") or "").lower()
            file_name = str(item.get("file_name") or "")
            looks_like_folder = file_type in {"folder", "directory", "dir", "1"} or (
                not _looks_like_docid(fileid)
                and not str(item.get("url") or "")
                and not file_name.lower().endswith((".doc", ".docx", ".xls", ".xlsx", ".pdf", ".txt"))
            )
            if looks_like_folder:
                seen_folders.add(fileid)
                try:
                    items.extend(self.list_wedrive_files(spaceid, fatherid=fileid, recursive=True, limit=limit))
                except RuntimeError:
                    continue
        return items


def _split_env_list(value: str) -> list[str]:
    text = str(value or "")
    for sep in ENV_LIST_SEPARATORS[1:]:
        text = text.replace(sep, ENV_LIST_SEPARATORS[0])
    return [item.strip() for item in text.split(ENV_LIST_SEPARATORS[0]) if item.strip()]


def _profiled_env_values(key: str, namespace: str, profile: str, fallback_legacy: bool = True) -> list[str]:
    from .common import profiled_env_candidates

    values: list[str] = []
    candidates = profiled_env_candidates(key, namespace=namespace, profile=profile)
    if profile and not fallback_legacy:
        candidates = candidates[:-1]
    for candidate in candidates:
        keys = [candidate, f"{candidate}S"]
        for index in range(1, MAX_NUMBERED_ENV_ITEMS + 1):
            keys.extend((f"{candidate}_{index}", f"{candidate}{index}"))
        for env_key in keys:
            values.extend(_split_env_list(os.getenv(env_key, "")))
    return list(dict.fromkeys(values))


def _looks_like_docid(value: str) -> bool:
    text = str(value or "").strip()
    return (text.startswith("dc") or text.startswith("s3_") or text.startswith("s2_")) and len(text) > 20


def _sanitize_url(url: str) -> str:
    parts = urlsplit(str(url or "").strip())
    if not parts.scheme or not parts.netloc:
        return str(url or "").strip()
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in SENSITIVE_URL_PARAMS
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def parse_smartsheet_link(url: str) -> dict[str, str]:
    text = str(url or "").strip()
    parts = urlsplit(text)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    path_parts = [part for part in parts.path.split("/") if part]
    docid = ""
    for index, part in enumerate(path_parts):
        if part == "smartsheet" and index + 1 < len(path_parts):
            docid = path_parts[index + 1]
            break
    if not docid:
        for part in reversed(path_parts):
            if _looks_like_docid(part):
                docid = part
                break
    return {
        "docid": docid,
        "tab": query.get("tab", ""),
        "viewId": query.get("viewId", "") or query.get("viewid", ""),
        "safe_url": _sanitize_url(text),
        "host": parts.netloc,
        "path": parts.path,
    }


def _normalize_sheet_item(item: dict[str, Any]) -> dict[str, Any]:
    props = item.get("properties") or {}
    sheet_id = str(item.get("sheet_id") or item.get("id") or "")
    title = str(props.get("title") or item.get("title") or "")
    index = props.get("index") if "index" in props else item.get("index", "")
    return {"sheet_id": sheet_id, "title": title, "index": index, "raw": item}


def _ensure_registry_doc(
    registry: dict[str, Any],
    docid: str,
    profile: str,
    doc_name: str = "",
    url: str = "",
    app_label: str = "",
    source: str = "",
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    docs = registry.setdefault("docs", {})
    doc = docs.setdefault(
        docid,
        {
            "docid": docid,
            "doc_name": doc_name,
            "url": url,
            "admin_userid": "",
            "env_profile": profile,
            "created_at": "",
            "last_sync_at": "",
            "sheets": {},
        },
    )
    if doc_name and not doc.get("doc_name"):
        doc["doc_name"] = doc_name
    if url and not doc.get("url"):
        doc["url"] = url
    if profile and not doc.get("env_profile"):
        doc["env_profile"] = profile
    if app_label:
        doc["last_app_label"] = app_label
    if source:
        doc["discovery_source"] = source
    if raw:
        doc["raw"] = raw
    return doc


def _mark_registry_access(
    registry: dict[str, Any],
    docid: str,
    profile: str,
    app_label: str,
    status: str,
    error: str = "",
) -> None:
    doc = (registry.get("docs") or {}).get(docid)
    if not doc or not profile:
        return
    if status == "error" and ("301085" in error or "invalid docid" in error.lower()):
        status = "invalid_docid"
    access = doc.setdefault("profile_access", {})
    profile_access = access.setdefault(profile, {})
    if isinstance(profile_access, dict) and any(k in profile_access for k in ("status", "checked_at", "error")):
        old_status = profile_access.get("status") or ""
        old_error = profile_access.get("error") or ""
        old_checked_at = profile_access.get("checked_at") or ""
        profile_access = {
            "status": old_status,
            "checked_at": old_checked_at,
            "error": old_error,
            "apps": {},
        }
        access[profile] = profile_access
    profile_access["status"] = status
    profile_access["checked_at"] = now_iso()
    profile_access["error"] = error
    apps = profile_access.setdefault("apps", {})
    apps[app_label or "default"] = {"status": status, "checked_at": now_iso(), "error": error}


def _sync_registry_sheets(registry: dict[str, Any], docid: str, sheets: list[dict[str, Any]]) -> None:
    doc = registry["docs"][docid]
    store = doc.setdefault("sheets", {})
    seen: set[str] = set()
    for item in sheets:
        sheet = _normalize_sheet_item(item)
        sheet_id = sheet["sheet_id"]
        if not sheet_id:
            continue
        seen.add(sheet_id)
        existing = store.setdefault(
            sheet_id,
            {
                "sheet_id": sheet_id,
                "title": sheet["title"],
                "index": sheet["index"],
                "first_seen_at": now_iso(),
                "last_seen_at": "",
                "missing": False,
                "missing_since": "",
                "raw": {},
            },
        )
        existing["title"] = sheet["title"]
        existing["index"] = sheet["index"]
        existing["last_seen_at"] = now_iso()
        existing["missing"] = False
        existing["missing_since"] = ""
        existing["raw"] = sheet["raw"]
    for sheet_id, sheet in store.items():
        if sheet_id not in seen:
            sheet["missing"] = True
            if not sheet.get("missing_since"):
                sheet["missing_since"] = now_iso()
    doc["last_sync_at"] = now_iso()


def _env_target_docids(profile: str) -> list[str]:
    values: list[str] = []
    for key in ("WEDOC_DOCID", "SMARTSHEET_ID"):
        values.extend(_profiled_env_values(key, "WECOM", profile, fallback_legacy=not bool(profile)))
    return list(dict.fromkeys(value for value in values if _looks_like_docid(value)))


def _discover_wedrive_docids(client: WeComSmartsheetClient, profile: str) -> list[dict[str, Any]]:
    spaceids = _profiled_env_values("WEDRIVE_SPACEIDS", "WECOM", profile, fallback_legacy=not bool(profile))
    discovered: dict[str, dict[str, Any]] = {}
    for spaceid in spaceids:
        for item in client.list_wedrive_files(spaceid):
            fileid = str(item.get("fileid") or "")
            if not _looks_like_docid(fileid):
                continue
            discovered[fileid] = {
                "docid": fileid,
                "doc_name": str(item.get("file_name") or ""),
                "url": str(item.get("url") or ""),
                "source": f"wedrive:{spaceid}",
                "raw": item,
            }
    return list(discovered.values())


def resolve_selection(registry_path: Path = REGISTRY_PATH, profile: str | None = None) -> dict[str, str]:
    registry = read_json(registry_path, default={}) or {}
    docs = registry.get("docs") or {}
    profile = profile if profile is not None else get_env_profile("WECOM")
    strict_profile = bool(profile)

    docid = get_profiled_env(
        "WEDOC_DOCID", namespace="WECOM", profile=profile, fallback_legacy=not strict_profile
    ) or get_profiled_env(
        "SMARTSHEET_ID", namespace="WECOM", profile=profile, fallback_legacy=not strict_profile
    )
    sheet_id = get_profiled_env(
        "WEDOC_SHEET_ID", namespace="WECOM", profile=profile, fallback_legacy=not strict_profile
    ) or get_profiled_env(
        "SMARTSHEET_SHEET_ID", namespace="WECOM", profile=profile, fallback_legacy=not strict_profile
    )
    doc_name = ""
    sheet_title = ""

    if docid and docid in docs:
        doc_entry = docs[docid]
    else:
        target_doc_name = get_profiled_env(
            "WEDOC_DOC_NAME",
            namespace="WECOM",
            profile=profile,
            default="生产任务排期",
            fallback_legacy=not strict_profile,
        )
        doc_entry = None
        candidates = list(docs.values())
        if strict_profile:
            profile_docs = [item for item in candidates if str(item.get("env_profile") or "").strip() == profile]
            if profile_docs:
                candidates = profile_docs
        for item in candidates:
            if (item.get("doc_name") or "").strip() == target_doc_name:
                doc_entry = item
                break
        if not doc_entry and strict_profile:
            profile_docs = [item for item in docs.values() if str(item.get("env_profile") or "").strip() == profile]
            if len(profile_docs) == 1:
                doc_entry = profile_docs[0]
        if doc_entry:
            docid = str(doc_entry.get("docid") or "")

    if not docid or not doc_entry:
        if strict_profile:
            raise RuntimeError(
                f"当前 WECOM_ENV_PROFILE={profile}，但未找到该公司的目标 docid。"
                "请先运行 B01 新建/登记智能表格，或在 .env 中填写 "
                f"WEDOC_{profile}_DOCID / SMARTSHEET_{profile}_ID。"
            )
        raise RuntimeError("无法从 .env 或 smartsheet_registry.json 解析目标 docid")

    doc_name = str(doc_entry.get("doc_name") or docid)
    sheets = doc_entry.get("sheets") or {}

    if sheet_id and sheet_id in sheets:
        sheet_entry = sheets[sheet_id]
    else:
        target_sheet_title = get_profiled_env(
            "WEDOC_SHEET_TITLE",
            namespace="WECOM",
            profile=profile,
            default="排产·统计总台账",
            fallback_legacy=not strict_profile,
        )
        sheet_entry = None
        for item in sheets.values():
            if (item.get("title") or "").strip() == target_sheet_title:
                sheet_entry = item
                break
        if not sheet_entry and strict_profile and len(sheets) == 1:
            sheet_entry = next(iter(sheets.values()))
        if sheet_entry:
            sheet_id = str(sheet_entry.get("sheet_id") or "")

    if not sheet_id or not sheet_entry:
        if strict_profile:
            raise RuntimeError(
                f"当前 WECOM_ENV_PROFILE={profile}，已找到 docid，但未找到目标 sheet_id。"
                "请在 .env 中填写 "
                f"WEDOC_{profile}_SHEET_ID / SMARTSHEET_{profile}_SHEET_ID，"
                "或设置 WEDOC_COMPANY_B_SHEET_TITLE 为实际工作表名称。"
            )
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


def _sync_selection(
    client: WeComSmartsheetClient,
    selection: dict[str, str],
    profile: str,
    mode: str,
    recent_limit: int,
    verify_interval_hours: int,
    export_table: bool = True,
) -> dict[str, Any]:
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
        if export_table:
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
    state["env_profile"] = profile or ""
    state["strategy_note"] = "WeCom fetches remote records and then applies local sort/merge."
    write_json(paths["state"], state)

    summary["preview_path"] = str(paths["preview_latest"])
    summary["merged_path"] = str(paths["merged_latest"])
    summary["fields_path"] = str(paths["fields_latest"])
    summary["state_path"] = str(paths["state"])
    return summary


def sync_smartsheet(
    mode: str = "auto",
    recent_limit: int = 50,
    verify_interval_hours: int = 24,
    registry_path: Path = REGISTRY_PATH,
) -> dict[str, Any]:
    profile = load_dotenv_for_profile("WECOM")
    corpid = get_profiled_env("WECOM_CORP_ID", namespace="WECOM", profile=profile)
    secret = get_profiled_env("WECOM_APP_SECRET", namespace="WECOM", profile=profile)
    use_system_proxy = get_profiled_env(
        "WECOM_USE_SYSTEM_PROXY", namespace="WECOM", profile=profile, default=""
    ).lower() in {"1", "true", "yes", "on"}
    if not corpid or not secret:
        raise RuntimeError("缺少 WECOM_CORP_ID / WECOM_APP_SECRET")

    selection = resolve_selection(registry_path, profile=profile)
    client = WeComSmartsheetClient(corpid=corpid, secret=secret, use_system_proxy=use_system_proxy)
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
    state["env_profile"] = profile or ""
    state["strategy_note"] = "WeCom current implementation fetches current records and then applies local sort/merge."
    write_json(paths["state"], state)

    summary["preview_path"] = str(paths["preview_latest"])
    summary["merged_path"] = str(paths["merged_latest"])
    summary["fields_path"] = str(paths["fields_latest"])
    summary["state_path"] = str(paths["state"])
    summary["document_inventory"] = export_document_inventory(registry_path)
    return summary


def _wecom_app_credentials(profile: str) -> list[dict[str, str]]:
    corpid = get_profiled_env("WECOM_CORP_ID", namespace="WECOM", profile=profile)
    secrets = _profiled_env_values("WECOM_APP_SECRET", "WECOM", profile, fallback_legacy=not bool(profile))
    if not secrets:
        secret = get_profiled_env("WECOM_APP_SECRET", namespace="WECOM", profile=profile)
        if secret:
            secrets = [secret]
    return [
        {"corpid": corpid, "secret": secret, "app_label": "default" if index == 1 else f"app_{index}"}
        for index, secret in enumerate(secrets, start=1)
        if corpid and secret
    ]


def _profile_access_status(doc: dict[str, Any], profile: str) -> str:
    profile_access = (doc.get("profile_access") or {}).get(profile) or {}
    status = str(profile_access.get("status") or "")
    error = str(profile_access.get("error") or "")
    apps = profile_access.get("apps") if isinstance(profile_access, dict) else None
    if not status and isinstance(apps, dict):
        latest_app: dict[str, Any] | None = None
        for app_access in apps.values():
            if not isinstance(app_access, dict):
                continue
            if latest_app is None or str(app_access.get("checked_at") or "") >= str(
                latest_app.get("checked_at") or ""
            ):
                latest_app = app_access
        if latest_app:
            status = str(latest_app.get("status") or "")
            error = str(latest_app.get("error") or error)
    if status == "error" and ("301085" in error or "invalid docid" in error.lower()):
        return "invalid_docid"
    return status


def _hydrate_invalid_docids_from_sync_errors(registry: dict[str, Any], profile: str) -> None:
    if not profile:
        return
    docs = registry.get("docs") or {}
    for item in registry.get("sync_errors") or []:
        docid = str(item.get("docid") or "")
        error = str(item.get("error") or "")
        doc = docs.get(docid)
        if not doc or str(doc.get("env_profile") or "").strip() != profile:
            continue
        if "301085" in error or "invalid docid" in error.lower():
            _mark_registry_access(registry, docid, profile, str(item.get("app_label") or "default"), "invalid_docid", error)


def _registry_candidate_docs(
    registry: dict[str, Any],
    profile: str,
    include_invalid_docids: bool = False,
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for docid, doc in (registry.get("docs") or {}).items():
        if profile and str(doc.get("env_profile") or "").strip() != profile:
            continue
        if not include_invalid_docids and _profile_access_status(doc, profile) in {"invalid_docid", "no_access"}:
            continue
        if _looks_like_docid(str(docid)):
            candidates[str(docid)] = {
                "docid": str(docid),
                "doc_name": str(doc.get("doc_name") or ""),
                "url": str(doc.get("url") or ""),
                "source": "registry",
                "raw": {},
            }
    for docid in _env_target_docids(profile):
        candidates.setdefault(docid, {"docid": docid, "doc_name": "", "url": "", "source": "env", "raw": {}})
    return list(candidates.values())


def _selection_from_registry_doc(docid: str, doc: dict[str, Any], sheet_id: str, sheet: dict[str, Any]) -> dict[str, str]:
    return {
        "docid": docid,
        "sheet_id": sheet_id,
        "doc_name": str(doc.get("doc_name") or docid),
        "sheet_title": str(sheet.get("title") or sheet_id),
    }


def _read_manual_link_rows(source_path: Path) -> list[dict[str, Any]]:
    if not source_path.exists():
        return []
    suffix = source_path.suffix.lower()
    if suffix in {".xlsx", ".xls"}:
        df = pd.read_excel(source_path)
    else:
        df = pd.read_csv(source_path)
    df = df.fillna("")
    return [dict(row) for row in df.to_dict(orient="records")]


def _truthy_enabled(value: Any) -> bool:
    text = str(value if value is not None else "").strip().lower()
    return text not in {"0", "false", "no", "n", "off", "停用", "否"}


def _row_value(row: dict[str, Any], *keys: str) -> str:
    lowered = {str(key).strip().lower(): value for key, value in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value not in (None, ""):
            return str(value).strip()
    return ""


def _metadata_from_raw(raw: dict[str, Any], *keys: str) -> str:
    containers = [raw, raw.get("properties") if isinstance(raw.get("properties"), dict) else {}]
    for container in containers:
        for key in keys:
            value = container.get(key)
            if value not in (None, ""):
                return _maybe_datetime_text(str(value))
    return ""


def _manual_link_review_row(
    source_row: int,
    profile: str,
    company_name: str,
    doc_name: str,
    parsed: dict[str, str],
    status: str,
    app_label: str = "",
    sheet: dict[str, Any] | None = None,
    error: str = "",
    remark: str = "",
) -> dict[str, Any]:
    raw = sheet.get("raw") if isinstance(sheet, dict) and isinstance(sheet.get("raw"), dict) else {}
    return {
        "source_row": source_row,
        "account_profile": profile,
        "company_name": company_name,
        "document_name": doc_name,
        "document_id": parsed.get("docid", ""),
        "sheet_name": (sheet or {}).get("title", ""),
        "sheet_or_table_id": (sheet or {}).get("sheet_id", ""),
        "sheet_index": (sheet or {}).get("index", ""),
        "status": status,
        "app_label": app_label,
        "creator_name": _metadata_from_raw(raw, "creator_name", "creator", "create_user_name", "owner_name"),
        "creator_userid": _metadata_from_raw(raw, "creator_userid", "creator_user_id", "create_userid", "owner_userid"),
        "created_at": _metadata_from_raw(raw, "create_time", "created_at", "ctime"),
        "updater_name": _metadata_from_raw(raw, "updater_name", "modifier_name", "update_user_name"),
        "updated_at": _metadata_from_raw(raw, "update_time", "updated_at", "mtime"),
        "tab": parsed.get("tab", ""),
        "viewId": parsed.get("viewId", ""),
        "safe_url": parsed.get("safe_url", ""),
        "access_error": error,
        "remark": remark,
    }


def create_manual_smartsheet_link_template(path: Path = MANUAL_LINKS_PATH) -> Path:
    ensure_dir(path.parent)
    df = pd.DataFrame(
        [
            {
                "company_profile": "COMPANY_A",
                "company_name": "四川和裕达新材料有限公司",
                "doc_name": "示例智能表格",
                "url": "https://doc.weixin.qq.com/smartsheet/s3_xxx?tab=xxx&viewId=xxx",
                "enabled": "yes",
                "remark": "把可访问的智能表格链接粘贴到这里",
            },
            {
                "company_profile": "COMPANY_B",
                "company_name": "四川和裕泰新材料有限公司",
                "doc_name": "示例智能表格",
                "url": "https://doc.weixin.qq.com/smartsheet/s3_xxx?tab=xxx&viewId=xxx",
                "enabled": "yes",
                "remark": "",
            },
        ]
    )
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="links")
        pd.DataFrame(
            [
                {"column": "company_profile", "description": "COMPANY_A 或 COMPANY_B，对应 .env 中的企业微信配置档案"},
                {"column": "company_name", "description": "公司名称，只用于核对表展示"},
                {"column": "doc_name", "description": "人工备注的文档名称，可用来纠正云端名称不清晰的问题"},
                {"column": "url", "description": "企业微信智能表格访问链接；脚本会自动移除 scode/token 等敏感参数"},
                {"column": "enabled", "description": "yes/true/1 表示启用；no/false/0/否 表示跳过"},
                {"column": "remark", "description": "备注"},
            ]
        ).to_excel(writer, index=False, sheet_name="guide")
    return path


def _export_manual_link_inventory(rows: list[dict[str, Any]], output_dir: Path) -> dict[str, str]:
    tag = now_tag()
    ensure_dir(output_dir)
    out_csv = output_dir / f"wecom_smartsheet_link_inventory_{tag}.csv"
    out_xlsx = output_dir / f"wecom_smartsheet_link_inventory_{tag}.xlsx"
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(
            columns=[
                "source_row",
                "account_profile",
                "company_name",
                "document_name",
                "document_id",
                "sheet_name",
                "sheet_or_table_id",
                "status",
                "creator_name",
                "creator_userid",
                "created_at",
                "updated_at",
                "safe_url",
                "access_error",
            ]
        )
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="links")
        pd.DataFrame(
            [
                {"key": "generated_at", "value": now_iso()},
                {"key": "row_count", "value": len(rows)},
                {"key": "purpose", "value": "Manual WeCom smartsheet link import review table."},
            ]
        ).to_excel(writer, index=False, sheet_name="guide")
    latest = publish_latest(
        {
            "wecom_smartsheet_link_inventory.csv": out_csv,
            "wecom_smartsheet_link_inventory.xlsx": out_xlsx,
        },
        output_dir,
    )
    archived = archive_outputs(
        {
            "wecom_smartsheet_link_inventory.csv": out_csv,
            "wecom_smartsheet_link_inventory.xlsx": out_xlsx,
        },
        output_dir,
    )
    cleanup_output_history(output_dir)
    return {
        "csv_path": str(out_csv),
        "xlsx_path": str(out_xlsx),
        "latest_csv_path": latest.get("wecom_smartsheet_link_inventory.csv", ""),
        "latest_xlsx_path": latest.get("wecom_smartsheet_link_inventory.xlsx", ""),
        "archive_csv_path": archived.get("wecom_smartsheet_link_inventory.csv", ""),
        "archive_xlsx_path": archived.get("wecom_smartsheet_link_inventory.xlsx", ""),
    }


def import_smartsheet_links(
    source_path: Path = MANUAL_LINKS_PATH,
    registry_path: Path = REGISTRY_PATH,
    output_dir: Path = OUTPUT_DIR,
    profiles: list[str] | None = None,
    client_factory: Callable[[str, dict[str, str]], Any] | None = None,
    credentials_provider: Callable[[str], list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    load_dotenv_for_profile("WECOM")
    source_path = Path(source_path)
    registry_path = Path(registry_path)
    output_dir = Path(output_dir)
    registry = read_json(registry_path, default={}) or {}
    source_rows = _read_manual_link_rows(source_path)
    selected_profiles = {profile.strip() for profile in profiles or [] if profile.strip()}
    review_rows: list[dict[str, Any]] = []
    ok_docids: set[str] = set()
    imported_docids: set[str] = set()
    errors: list[dict[str, str]] = []

    credentials_provider = credentials_provider or _wecom_app_credentials

    def make_client(profile: str, credential: dict[str, str]) -> Any:
        if client_factory:
            return client_factory(profile, credential)
        use_system_proxy = get_profiled_env(
            "WECOM_USE_SYSTEM_PROXY", namespace="WECOM", profile=profile, default=""
        ).lower() in {"1", "true", "yes", "on"}
        return WeComSmartsheetClient(
            corpid=credential["corpid"],
            secret=credential["secret"],
            use_system_proxy=use_system_proxy,
        )

    for source_index, row in enumerate(source_rows, start=2):
        if not _truthy_enabled(_row_value(row, "enabled", "启用")):
            continue
        profile = _row_value(row, "company_profile", "account_profile", "env_profile", "profile", "公司配置")
        if selected_profiles and profile not in selected_profiles:
            continue
        company_name = _row_value(row, "company_name", "公司名称")
        doc_name = _row_value(row, "doc_name", "document_name", "文档名称", "名称")
        url = _row_value(row, "url", "link", "链接", "文档链接")
        remark = _row_value(row, "remark", "备注")
        parsed = parse_smartsheet_link(url)
        docid = parsed.get("docid", "")
        if not _looks_like_docid(docid):
            review_rows.append(
                _manual_link_review_row(source_index, profile, company_name, doc_name, parsed, "invalid_link", error="无法从链接解析智能表格文档ID", remark=remark)
            )
            continue

        imported_docids.add(docid)
        doc = _ensure_registry_doc(
            registry,
            docid,
            profile=profile,
            doc_name=doc_name,
            url=parsed["safe_url"],
            source="manual_link",
            raw={},
        )
        doc["company_name"] = company_name or doc.get("company_name", "")
        doc["manual_tab"] = parsed.get("tab", "")
        doc["manual_view_id"] = parsed.get("viewId", "")
        doc["manual_remark"] = remark
        doc["url"] = parsed["safe_url"]

        credentials = credentials_provider(profile)
        if not credentials:
            error = "缺少该 company_profile 对应的 WECOM_CORP_ID / WECOM_APP_SECRET"
            _mark_registry_access(registry, docid, profile, "default", "no_credentials", error)
            review_rows.append(
                _manual_link_review_row(source_index, profile, company_name, doc_name, parsed, "no_credentials", error=error, remark=remark)
            )
            errors.append({"docid": docid, "profile": profile, "stage": "credentials", "error": error})
            continue

        doc_ok = False
        last_error = ""
        for credential in credentials:
            app_label = credential.get("app_label") or "default"
            try:
                client = make_client(profile, credential)
                cloud_sheets = client.get_sheets(docid)
                _sync_registry_sheets(registry, docid, cloud_sheets)
                _mark_registry_access(registry, docid, profile, app_label, "ok")
                ok_docids.add(docid)
                doc_ok = True
                stored_doc = (registry.get("docs") or {}).get(docid) or {}
                for sheet_id, sheet in (stored_doc.get("sheets") or {}).items():
                    if sheet.get("missing"):
                        continue
                    review_rows.append(
                        _manual_link_review_row(
                            source_index,
                            profile,
                            company_name,
                            doc_name or str(stored_doc.get("doc_name") or ""),
                            parsed,
                            "ok",
                            app_label=app_label,
                            sheet=sheet,
                            remark=remark,
                        )
                    )
                break
            except Exception as exc:
                last_error = str(exc)
                _mark_registry_access(registry, docid, profile, app_label, "error", last_error)
                errors.append({"docid": docid, "profile": profile, "app_label": app_label, "stage": "get_sheets", "error": last_error})
        if not doc_ok:
            review_rows.append(
                _manual_link_review_row(source_index, profile, company_name, doc_name, parsed, "error", error=last_error, remark=remark)
            )

    write_json(registry_path, registry)
    exported = _export_manual_link_inventory(review_rows, output_dir)
    document_inventory = export_document_inventory(registry_path)
    return {
        "source_path": str(source_path),
        "registry_path": str(registry_path),
        "imported_doc_count": len(imported_docids),
        "ok_doc_count": len(ok_docids),
        "row_count": len(review_rows),
        "error_count": len(errors),
        "errors": errors,
        "latest_csv_path": exported.get("latest_csv_path", ""),
        "latest_xlsx_path": exported.get("latest_xlsx_path", ""),
        "document_inventory": document_inventory,
    }


def _export_profile_verification(rows: list[dict[str, Any]], output_dir: Path) -> dict[str, str]:
    tag = now_tag()
    ensure_dir(output_dir)
    out_csv = output_dir / f"wecom_smartsheet_profile_verification_{tag}.csv"
    out_xlsx = output_dir / f"wecom_smartsheet_profile_verification_{tag}.xlsx"
    df = pd.DataFrame(rows)
    if df.empty:
        df = pd.DataFrame(
            columns=[
                "document_id",
                "document_name",
                "old_profile",
                "new_profile",
                "status",
                "valid_profiles",
                "checked_profiles",
                "sheet_count",
                "access_errors",
                "doc_url",
            ]
        )
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")
    with pd.ExcelWriter(out_xlsx, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="profile_check")
        pd.DataFrame(
            [
                {"key": "generated_at", "value": now_iso()},
                {"key": "row_count", "value": len(rows)},
                {"key": "purpose", "value": "Verify and correct WeCom smartsheet company profile ownership."},
            ]
        ).to_excel(writer, index=False, sheet_name="guide")
    latest = publish_latest(
        {
            "wecom_smartsheet_profile_verification.csv": out_csv,
            "wecom_smartsheet_profile_verification.xlsx": out_xlsx,
        },
        output_dir,
    )
    archived = archive_outputs(
        {
            "wecom_smartsheet_profile_verification.csv": out_csv,
            "wecom_smartsheet_profile_verification.xlsx": out_xlsx,
        },
        output_dir,
    )
    cleanup_output_history(output_dir)
    return {
        "csv_path": str(out_csv),
        "xlsx_path": str(out_xlsx),
        "latest_csv_path": latest.get("wecom_smartsheet_profile_verification.csv", ""),
        "latest_xlsx_path": latest.get("wecom_smartsheet_profile_verification.xlsx", ""),
        "archive_csv_path": archived.get("wecom_smartsheet_profile_verification.csv", ""),
        "archive_xlsx_path": archived.get("wecom_smartsheet_profile_verification.xlsx", ""),
    }


def verify_registry_doc_profiles(
    profiles: list[str],
    registry_path: Path = REGISTRY_PATH,
    output_dir: Path = OUTPUT_DIR,
    client_factory: Callable[[str, dict[str, str]], Any] | None = None,
    credentials_provider: Callable[[str], list[dict[str, str]]] | None = None,
) -> dict[str, Any]:
    load_dotenv_for_profile("WECOM")
    registry_path = Path(registry_path)
    output_dir = Path(output_dir)
    registry = read_json(registry_path, default={}) or {}
    profiles = [profile.strip() for profile in profiles if profile.strip()]
    credentials_provider = credentials_provider or _wecom_app_credentials
    rows: list[dict[str, Any]] = []
    corrected_count = 0
    ok_docids: set[str] = set()
    errors: list[dict[str, str]] = []

    def make_client(profile: str, credential: dict[str, str]) -> Any:
        if client_factory:
            return client_factory(profile, credential)
        use_system_proxy = get_profiled_env(
            "WECOM_USE_SYSTEM_PROXY", namespace="WECOM", profile=profile, default=""
        ).lower() in {"1", "true", "yes", "on"}
        return WeComSmartsheetClient(
            corpid=credential["corpid"],
            secret=credential["secret"],
            use_system_proxy=use_system_proxy,
        )

    for docid, doc in list((registry.get("docs") or {}).items()):
        if not _looks_like_docid(str(docid)):
            continue
        old_profile = str(doc.get("env_profile") or "")
        valid_profiles: list[str] = []
        checked_profiles: list[str] = []
        profile_errors: list[str] = []
        best_sheets: list[dict[str, Any]] = []
        best_app_label = ""

        for profile in profiles:
            credentials = credentials_provider(profile)
            if not credentials:
                checked_profiles.append(profile)
                message = "no_credentials"
                _mark_registry_access(registry, str(docid), profile, "default", "no_credentials", message)
                profile_errors.append(f"{profile}: {message}")
                continue
            for credential in credentials:
                checked_profiles.append(profile)
                app_label = credential.get("app_label") or "default"
                try:
                    sheets = make_client(profile, credential).get_sheets(str(docid))
                    valid_profiles.append(profile)
                    _mark_registry_access(registry, str(docid), profile, app_label, "ok")
                    if not best_sheets:
                        best_sheets = sheets
                        best_app_label = app_label
                    break
                except Exception as exc:
                    error_text = str(exc)
                    _mark_registry_access(registry, str(docid), profile, app_label, "error", error_text)
                    profile_errors.append(f"{profile}/{app_label}: {error_text}")
                    errors.append({"docid": str(docid), "profile": profile, "app_label": app_label, "error": error_text})

        valid_profiles = list(dict.fromkeys(valid_profiles))
        new_profile = old_profile
        status = "no_access"
        if valid_profiles:
            ok_docids.add(str(docid))
            status = "ok"
            if old_profile in valid_profiles:
                new_profile = old_profile
            elif len(valid_profiles) == 1:
                new_profile = valid_profiles[0]
                status = "corrected"
            else:
                new_profile = valid_profiles[0]
                status = "corrected_multi_access"
            if new_profile != old_profile:
                corrected_count += 1
                doc["env_profile"] = new_profile
            if best_sheets:
                _sync_registry_sheets(registry, str(docid), best_sheets)
                if best_app_label:
                    doc["last_app_label"] = best_app_label
        else:
            doc["profile_verify_status"] = "no_access"

        doc["profile_verified_at"] = now_iso()
        doc["profile_verify_valid_profiles"] = valid_profiles
        doc["profile_verify_errors"] = profile_errors[-10:]
        rows.append(
            {
                "document_id": str(docid),
                "document_name": doc.get("doc_name") or "",
                "old_profile": old_profile,
                "new_profile": new_profile,
                "status": status,
                "valid_profiles": ";".join(valid_profiles),
                "checked_profiles": ";".join(list(dict.fromkeys(checked_profiles))),
                "sheet_count": len((doc.get("sheets") or {})),
                "access_errors": " | ".join(profile_errors[-5:]),
                "doc_url": doc.get("url") or "",
            }
        )

    write_json(registry_path, registry)
    exported = _export_profile_verification(rows, output_dir)
    inventory = export_document_inventory(registry_path)
    return {
        "registry_path": str(registry_path),
        "checked_doc_count": len(rows),
        "ok_doc_count": len(ok_docids),
        "corrected_count": corrected_count,
        "error_count": len(errors),
        "errors": errors[-50:],
        "latest_csv_path": exported.get("latest_csv_path", ""),
        "latest_xlsx_path": exported.get("latest_xlsx_path", ""),
        "document_inventory": inventory,
    }


def sync_all_smartsheets(
    mode: str = "auto",
    recent_limit: int = 50,
    verify_interval_hours: int = 24,
    registry_path: Path = REGISTRY_PATH,
    include_invalid_docids: bool = False,
) -> dict[str, Any]:
    profile = load_dotenv_for_profile("WECOM")
    credentials = _wecom_app_credentials(profile)
    use_system_proxy = get_profiled_env(
        "WECOM_USE_SYSTEM_PROXY", namespace="WECOM", profile=profile, default=""
    ).lower() in {"1", "true", "yes", "on"}
    if not credentials:
        raise RuntimeError("缂哄皯 WECOM_CORP_ID / WECOM_APP_SECRET")

    registry = read_json(registry_path, default={}) or {}
    _hydrate_invalid_docids_from_sync_errors(registry, profile)
    candidates = _registry_candidate_docs(
        registry,
        profile,
        include_invalid_docids=include_invalid_docids,
    )
    synced: list[dict[str, Any]] = []
    synced_keys: set[tuple[str, str]] = set()
    errors: list[dict[str, str]] = []
    discovered_count = 0

    for credential in credentials:
        app_label = credential["app_label"]
        client = WeComSmartsheetClient(
            corpid=credential["corpid"],
            secret=credential["secret"],
            use_system_proxy=use_system_proxy,
        )
        app_candidates = list(candidates)
        try:
            discovered = _discover_wedrive_docids(client, profile)
            discovered_count += len(discovered)
            known = {item["docid"] for item in app_candidates}
            for item in discovered:
                if item["docid"] not in known:
                    app_candidates.append(item)
                    candidates.append(item)
                    known.add(item["docid"])
        except Exception as exc:
            errors.append({"app_label": app_label, "stage": "discover_wedrive", "error": str(exc)})

        for item in app_candidates:
            docid = str(item.get("docid") or "")
            if not _looks_like_docid(docid):
                continue
            try:
                _ensure_registry_doc(
                    registry,
                    docid,
                    profile=profile,
                    doc_name=str(item.get("doc_name") or ""),
                    url=str(item.get("url") or ""),
                    app_label=app_label,
                    source=str(item.get("source") or ""),
                    raw=item.get("raw") if isinstance(item.get("raw"), dict) else None,
                )
                cloud_sheets = client.get_sheets(docid)
                _sync_registry_sheets(registry, docid, cloud_sheets)
                _mark_registry_access(registry, docid, profile, app_label, "ok")
                write_json(registry_path, registry)
            except Exception as exc:
                _mark_registry_access(registry, docid, profile, app_label, "error", str(exc))
                errors.append({"app_label": app_label, "docid": docid, "stage": "get_sheets", "error": str(exc)})
                continue

            doc = (registry.get("docs") or {}).get(docid) or {}
            for sheet_id, sheet in (doc.get("sheets") or {}).items():
                if sheet.get("missing"):
                    continue
                sync_key = (docid, str(sheet_id))
                if sync_key in synced_keys:
                    continue
                try:
                    selection = _selection_from_registry_doc(docid, doc, str(sheet_id), sheet)
                    summary = _sync_selection(
                        client=client,
                        selection=selection,
                        profile=profile,
                        mode=mode,
                        recent_limit=recent_limit,
                        verify_interval_hours=verify_interval_hours,
                        export_table=False,
                    )
                    summary["app_label"] = app_label
                    synced.append(summary)
                    synced_keys.add(sync_key)
                except Exception as exc:
                    errors.append(
                        {
                            "app_label": app_label,
                            "docid": docid,
                            "sheet_id": str(sheet_id),
                            "stage": "sync_sheet",
                            "error": str(exc),
                        }
                    )

    if errors:
        registry.setdefault("sync_errors", [])
        registry["sync_errors"] = [{"time": now_iso(), **item} for item in errors][-200:]
        write_json(registry_path, registry)

    inventory = export_document_inventory(registry_path)
    return {
        "env_profile": profile or "",
        "app_count": len(credentials),
        "candidate_doc_count": len({item["docid"] for item in candidates}),
        "wedrive_discovered_doc_count": discovered_count,
        "synced_sheet_count": len(synced),
        "error_count": len(errors),
        "synced": synced,
        "errors": errors,
        "document_inventory": inventory,
    }

