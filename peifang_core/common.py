"""
程序简介：提供项目根路径、JSON/文本读写、记录排序合并、时间处理，以及多公司环境变量配置档案读取。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"


def normalize_env_profile(profile: str | None) -> str:
    """把公司配置档案名整理成可用于环境变量名的格式。"""
    return re.sub(r"[^A-Za-z0-9]+", "_", (profile or "").strip()).strip("_").upper()


def get_env_profile(namespace: str | None = None) -> str:
    """读取当前启用的配置档案，平台专用配置优先于项目通用配置。"""
    namespace_key = f"{normalize_env_profile(namespace)}_ENV_PROFILE" if namespace else ""
    return (os.getenv(namespace_key) or os.getenv("PEIFANG_ENV_PROFILE") or "").strip()


def load_dotenv_for_profile(namespace: str | None = None) -> str:
    """
    读取 .env，并按配置档案追加读取公司专用 .env 文件。

    示例：
    - PEIFANG_ENV_PROFILE=haier 会读取 .env 和 .env.haier。
    - WECOM_ENV_PROFILE=haier 会额外读取 .env.wecom.haier。
    - 配置档案文件里可以继续使用 WECOM_CORP_ID 这类普通变量名。
    """
    from dotenv import load_dotenv

    load_dotenv(ROOT_DIR / ".env", override=False)
    profile = get_env_profile(namespace)
    if not profile:
        return ""

    profile_slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", profile.strip()).strip("_.-")
    load_dotenv(ROOT_DIR / f".env.{profile_slug}", override=True)
    if namespace:
        namespace_slug = re.sub(r"[^A-Za-z0-9_.-]+", "_", namespace.strip().lower()).strip("_.-")
        load_dotenv(ROOT_DIR / f".env.{namespace_slug}.{profile_slug}", override=True)
    return profile


def profiled_env_candidates(key: str, namespace: str | None = None, profile: str | None = None) -> list[str]:
    """生成一个配置项在当前公司档案下可能使用的环境变量名。"""
    normalized_profile = normalize_env_profile(profile)
    normalized_namespace = normalize_env_profile(namespace)
    normalized_key = normalize_env_profile(key)
    candidates: list[str] = []

    if normalized_profile:
        if normalized_namespace and normalized_key.startswith(f"{normalized_namespace}_"):
            rest = normalized_key[len(normalized_namespace) + 1 :]
            candidates.append(f"{normalized_namespace}_{normalized_profile}_{rest}")
        elif normalized_namespace:
            candidates.append(f"{normalized_namespace}_{normalized_profile}_{normalized_key}")

        if "_" in normalized_key:
            first, rest = normalized_key.split("_", 1)
            candidates.append(f"{first}_{normalized_profile}_{rest}")

        candidates.extend(
            [
                f"{normalized_key}_{normalized_profile}",
                f"{normalized_profile}_{normalized_key}",
            ]
        )

    candidates.append(normalized_key)
    return list(dict.fromkeys(candidates))


def get_profiled_env(
    key: str,
    namespace: str | None = None,
    profile: str | None = None,
    default: str = "",
    fallback_legacy: bool = True,
) -> str:
    """读取配置项：优先读取公司档案变量，最后回退到旧的单公司变量名。"""
    active_profile = profile if profile is not None else get_env_profile(namespace)
    candidates = profiled_env_candidates(key, namespace=namespace, profile=active_profile)
    if active_profile and not fallback_legacy:
        candidates = candidates[:-1]
    for name in candidates:
        value = os.getenv(name)
        if value is not None and str(value).strip() != "":
            return str(value).strip()
    return default


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

