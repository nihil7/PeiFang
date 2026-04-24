from __future__ import annotations

import hashlib
import json
import os
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"


def ensure_dir(path: Path | str) -> Path:
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_json(path: Path | str, default: Any = None) -> Any:
    p = Path(path)
    if not p.exists():
        return default
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def write_json(path: Path | str, data: Any) -> Path:
    p = Path(path)
    ensure_dir(p.parent)
    with p.open("w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    return p


def write_text(path: Path | str, text: str) -> Path:
    p = Path(path)
    ensure_dir(p.parent)
    p.write_text(text, encoding="utf-8")
    return p


def first_text_cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list) and value:
        first = value[0]
        if isinstance(first, dict):
            if "text" in first:
                return str(first.get("text", "")).strip()
            if "name" in first:
                return str(first.get("name", "")).strip()
        return str(first).strip()
    if isinstance(value, dict):
        for key in ("text", "name", "value"):
            if key in value:
                return str(value.get(key, "")).strip()
    return str(value).strip()


def normalize_record_payload(record: dict) -> dict:
    if "values" in record and isinstance(record["values"], dict):
        return record["values"]
    if "fields" in record and isinstance(record["fields"], dict):
        return record["fields"]
    return {}


def parse_loose_datetime(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        num = float(value)
        if num > 10_000_000_000:
            return num / 1000.0
        return num

    text = first_text_cell(value)
    if not text:
        return 0.0
    if text.isdigit():
        return parse_loose_datetime(int(text))

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
        "%Y/%m/%d %H:%M:%S",
        "%Y/%m/%d %H:%M",
        "%Y-%m-%d",
        "%Y/%m/%d",
    ):
        try:
            dt = datetime.strptime(text, fmt)
            return dt.replace(tzinfo=timezone.utc).timestamp()
        except ValueError:
            pass

    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.timestamp()
    except ValueError:
        return 0.0


def extract_sort_timestamp(record: dict, field_candidates: Iterable[str]) -> float:
    payload = normalize_record_payload(record)
    for key in (
        "update_time",
        "updated_at",
        "modified_time",
        "last_modified_time",
        "create_time",
        "created_at",
    ):
        if key in record:
            ts = parse_loose_datetime(record.get(key))
            if ts:
                return ts

    for field_name in field_candidates:
        if field_name in payload:
            ts = parse_loose_datetime(payload.get(field_name))
            if ts:
                return ts
    return 0.0


def stable_record_id(record: dict, preferred_keys: Iterable[str] = ("record_id", "id")) -> str:
    for key in preferred_keys:
        value = record.get(key)
        if value:
            return str(value)

    payload = normalize_record_payload(record)
    for key in ("record_id", "id"):
        value = payload.get(key)
        if value:
            return first_text_cell(value) or str(value)

    digest = hashlib.sha1(
        json.dumps(payload or record, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"synthetic_{digest[:16]}"


def merge_records(existing: list[dict], incoming: list[dict], field_candidates: Iterable[str]) -> dict:
    merged_map: dict[str, dict] = {}
    created = 0
    updated = 0

    for item in existing:
        rid = stable_record_id(item)
        normalized = dict(item)
        normalized["_record_id"] = rid
        normalized["_sort_ts"] = extract_sort_timestamp(normalized, field_candidates)
        merged_map[rid] = normalized

    for item in incoming:
        rid = stable_record_id(item)
        normalized = dict(item)
        normalized["_record_id"] = rid
        normalized["_sort_ts"] = extract_sort_timestamp(normalized, field_candidates)
        if rid in merged_map:
            updated += 1
        else:
            created += 1
        merged_map[rid] = normalized

    merged = sorted(
        merged_map.values(),
        key=lambda row: (float(row.get("_sort_ts", 0) or 0), str(row.get("_record_id", ""))),
        reverse=True,
    )
    return {
        "records": merged,
        "created": created,
        "updated": updated,
        "total": len(merged),
    }


def should_verify_full(state: dict, interval_hours: int) -> bool:
    if interval_hours <= 0:
        return False
    last = state.get("last_verify_at") or state.get("last_full_sync_at")
    if not last:
        return True
    try:
        then = datetime.fromisoformat(str(last))
    except ValueError:
        return True
    delta = datetime.now() - then
    return delta.total_seconds() >= interval_hours * 3600


def build_verify_report(local_records: list[dict], remote_records: list[dict], field_candidates: Iterable[str]) -> dict:
    local_ids = {stable_record_id(item) for item in local_records}
    remote_ids = {stable_record_id(item) for item in remote_records}
    missing_local = sorted(remote_ids - local_ids)
    stale_local = sorted(local_ids - remote_ids)
    return {
        "generated_at": now_iso(),
        "local_count": len(local_records),
        "remote_count": len(remote_records),
        "missing_local_count": len(missing_local),
        "stale_local_count": len(stale_local),
        "missing_local_sample": missing_local[:20],
        "stale_local_sample": stale_local[:20],
        "local_latest_sort_ts": max((extract_sort_timestamp(r, field_candidates) for r in local_records), default=0),
        "remote_latest_sort_ts": max((extract_sort_timestamp(r, field_candidates) for r in remote_records), default=0),
    }


def sort_records(records: list[dict], field_candidates: Iterable[str]) -> list[dict]:
    enriched = []
    for item in records:
        normalized = dict(item)
        normalized["_record_id"] = stable_record_id(item)
        normalized["_sort_ts"] = extract_sort_timestamp(item, field_candidates)
        enriched.append(normalized)
    return sorted(
        enriched,
        key=lambda row: (float(row.get("_sort_ts", 0) or 0), str(row.get("_record_id", ""))),
        reverse=True,
    )


def date_label(iso_date: str) -> str:
    dt = date.fromisoformat(iso_date)
    weekdays = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    return f"{dt.month}/{dt.day} {weekdays[dt.weekday()]}"
