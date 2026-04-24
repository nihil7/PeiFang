from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from dotenv import load_dotenv

from .common import (
    DATA_DIR,
    build_verify_report,
    ensure_dir,
    merge_records,
    now_iso,
    now_tag,
    read_json,
    should_verify_full,
    sort_records,
    stable_record_id,
    write_json,
)


FEISHU_API_BASE = "https://open.feishu.cn/open-apis"
SORT_FIELD_CANDIDATES = ["更新时间", "修改时间", "日期", "创建时间"]


class FeishuBitableClient:
    def __init__(self, app_id: str, app_secret: str, api_base: str = FEISHU_API_BASE, timeout: int = 20) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.api_base = api_base.rstrip("/")
        self.timeout = timeout
        self._tenant_token: str | None = None

    def tenant_token(self) -> str:
        if self._tenant_token:
            return self._tenant_token
        resp = requests.post(
            f"{self.api_base}/auth/v3/tenant_access_token/internal",
            json={"app_id": self.app_id, "app_secret": self.app_secret},
            timeout=self.timeout,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"tenant_access_token failed: {data}")
        self._tenant_token = str(data["tenant_access_token"])
        return self._tenant_token

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.tenant_token()}", "Content-Type": "application/json"}

    def resolve_app_token_from_wiki_node(self, wiki_node_token: str) -> str:
        resp = requests.get(
            f"{self.api_base}/wiki/v2/spaces/get_node",
            headers=self._headers(),
            params={"token": wiki_node_token},
            timeout=self.timeout,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"wiki get_node failed: {data}")
        node = (data.get("data") or {}).get("node") or (data.get("data") or {})
        obj_type = node.get("obj_type")
        obj_token = node.get("obj_token")
        if obj_type != "bitable" or not obj_token:
            raise RuntimeError(f"wiki node is not a direct bitable node: obj_type={obj_type}")
        return str(obj_token)

    def list_fields(self, app_token: str, table_id: str) -> list[dict[str, Any]]:
        resp = requests.get(
            f"{self.api_base}/bitable/v1/apps/{app_token}/tables/{table_id}/fields",
            headers=self._headers(),
            timeout=self.timeout,
        )
        data = resp.json()
        if data.get("code") != 0:
            raise RuntimeError(f"list_fields failed: {data}")
        return (data.get("data") or {}).get("items") or []

    def search_records(self, app_token: str, table_id: str, page_size: int = 500, max_pages: int = 100) -> list[dict[str, Any]]:
        page_token = None
        items: list[dict[str, Any]] = []
        for _ in range(max_pages):
            payload: dict[str, Any] = {"page_size": min(max(page_size, 1), 500)}
            if page_token:
                payload["page_token"] = page_token
            resp = requests.post(
                f"{self.api_base}/bitable/v1/apps/{app_token}/tables/{table_id}/records/search",
                headers=self._headers(),
                json=payload,
                timeout=self.timeout,
            )
            data = resp.json()
            if data.get("code") != 0:
                raise RuntimeError(f"search_records failed: {data}")
            block = data.get("data") or {}
            page_items = block.get("items") or []
            items.extend(page_items)
            if not block.get("has_more"):
                break
            page_token = block.get("page_token")
            if not page_token:
                break
        return items


def parse_wiki_url(wiki_url: str) -> tuple[str | None, str | None]:
    parsed = urlparse(wiki_url)
    qs = parse_qs(parsed.query)
    parts = [p for p in parsed.path.split("/") if p]
    node_token = parts[-1] if parts and "wiki" in parts else None
    table_id = qs.get("table", [None])[0]
    return node_token, table_id


def resolve_selection() -> dict[str, str]:
    load_dotenv()
    api_base = (os.getenv("FEISHU_API_BASE") or FEISHU_API_BASE).strip() or FEISHU_API_BASE
    app_id = (os.getenv("APP_ID") or os.getenv("FEISHU_APP_ID") or "").strip()
    app_secret = (os.getenv("APP_SECRET") or os.getenv("FEISHU_APP_SECRET") or "").strip()
    app_token = (os.getenv("APP_TOKEN") or "").strip()
    table_id = (os.getenv("TABLE_ID") or "").strip()
    wiki_url = (os.getenv("WIKI_URL") or "").strip()
    wiki_node_token = (os.getenv("WIKI_NODE_TOKEN") or "").strip()

    if not app_id or not app_secret:
        raise RuntimeError("缺少 APP_ID / APP_SECRET")

    if wiki_url:
        parsed_node, parsed_table = parse_wiki_url(wiki_url)
        wiki_node_token = wiki_node_token or parsed_node or ""
        table_id = table_id or parsed_table or ""

    client = FeishuBitableClient(app_id=app_id, app_secret=app_secret, api_base=api_base)
    if not app_token and wiki_node_token:
        app_token = client.resolve_app_token_from_wiki_node(wiki_node_token)
    if not app_token or not table_id:
        raise RuntimeError("无法解析 APP_TOKEN / TABLE_ID")

    return {
        "api_base": api_base,
        "app_id": app_id,
        "app_secret": app_secret,
        "app_token": app_token,
        "table_id": table_id,
    }


def build_storage_paths(app_token: str, table_id: str) -> dict[str, Path]:
    base_dir = ensure_dir(DATA_DIR / "feishu" / "bitable" / app_token / table_id)
    return {
        "base_dir": base_dir,
        "fields_latest": base_dir / "fields_latest.json",
        "full_latest": base_dir / "records_full_latest.json",
        "recent_latest": base_dir / "records_recent_latest.json",
        "merged_latest": base_dir / "records_merged_latest.json",
        "state": base_dir / "sync_state.json",
        "verify_latest": base_dir / "verify_latest.json",
        "history_dir": ensure_dir(base_dir / "history"),
    }


def normalize_record(record: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(record)
    fields = normalized.get("fields") or {}
    normalized["fields"] = fields
    normalized["_record_id"] = stable_record_id(normalized, preferred_keys=("record_id", "recordId", "id"))
    return normalized


def sync_bitable(mode: str = "auto", recent_limit: int = 50, verify_interval_hours: int = 24) -> dict[str, Any]:
    selection = resolve_selection()
    client = FeishuBitableClient(
        app_id=selection["app_id"],
        app_secret=selection["app_secret"],
        api_base=selection["api_base"],
    )
    paths = build_storage_paths(selection["app_token"], selection["table_id"])
    state = read_json(paths["state"], default={}) or {}

    effective_mode = mode
    if mode == "auto":
        if not paths["merged_latest"].exists():
            effective_mode = "full"
        elif should_verify_full(state, verify_interval_hours):
            effective_mode = "verify"
        else:
            effective_mode = "recent"

    fields = client.list_fields(selection["app_token"], selection["table_id"])
    write_json(paths["fields_latest"], {"generated_at": now_iso(), "items": fields})

    remote_items = [normalize_record(item) for item in client.search_records(selection["app_token"], selection["table_id"])]
    remote_sorted = sort_records(remote_items, SORT_FIELD_CANDIDATES)
    recent_items = remote_sorted[: max(1, recent_limit)]
    existing = (read_json(paths["merged_latest"], default={}) or {}).get("records") or []

    summary: dict[str, Any] = {
        "app_token": selection["app_token"],
        "table_id": selection["table_id"],
        "generated_at": now_iso(),
        "effective_mode": effective_mode,
        "remote_count": len(remote_sorted),
        "recent_limit": recent_limit,
        "storage_dir": str(paths["base_dir"]),
    }

    if effective_mode in {"full", "verify"}:
        write_json(paths["full_latest"], {"generated_at": now_iso(), "records": remote_sorted})
        write_json(paths["merged_latest"], {"generated_at": now_iso(), "records": remote_sorted})
        state["last_full_sync_at"] = now_iso()
        if effective_mode == "verify":
            report = build_verify_report(existing, remote_sorted, SORT_FIELD_CANDIDATES)
            write_json(paths["verify_latest"], report)
            state["last_verify_at"] = now_iso()
            summary["verify_report"] = report
        summary["merged_total"] = len(remote_sorted)
        summary["created"] = len(remote_sorted)
        summary["updated"] = 0
    else:
        write_json(paths["recent_latest"], {"generated_at": now_iso(), "records": recent_items})
        merged = merge_records(existing, recent_items, SORT_FIELD_CANDIDATES)
        write_json(paths["merged_latest"], {"generated_at": now_iso(), "records": merged["records"]})
        state["last_incremental_sync_at"] = now_iso()
        summary["merged_total"] = merged["total"]
        summary["created"] = merged["created"]
        summary["updated"] = merged["updated"]

    state["last_remote_count"] = len(remote_sorted)
    state["last_effective_mode"] = effective_mode
    state["last_recent_limit"] = recent_limit
    state["last_run_at"] = now_iso()
    state["strategy_note"] = "Feishu current implementation fetches records, sorts locally, and merges recent items by record_id."
    write_json(paths["state"], state)
    write_json(paths["history_dir"] / f"summary_{now_tag()}.json", summary)

    summary["fields_path"] = str(paths["fields_latest"])
    summary["merged_path"] = str(paths["merged_latest"])
    summary["state_path"] = str(paths["state"])
    return summary
