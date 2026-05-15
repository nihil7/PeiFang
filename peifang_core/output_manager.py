"""
排产输出管理：维护 output/latest 固定入口，把时间戳运行产物归档到 output/archive。
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Mapping


DEFAULT_KEEP_HISTORY = 10
HISTORY_PATTERNS = [
    "tasks_prepared_*.json",
    "tasks_prepared_*.csv",
    "排产_框架_*.xlsx",
    "排产_layout_*.json",
    "schedule_web_*.html",
    "wecom_smartsheet_full_*.csv",
    "wecom_smartsheet_full_*.xlsx",
    "document_inventory_*.csv",
    "document_inventory_*.xlsx",
    "wecom_two_company_sync_summary_*.json",
    "wecom_smartsheet_link_inventory_*.csv",
    "wecom_smartsheet_link_inventory_*.xlsx",
    "wecom_smartsheet_profile_verification_*.csv",
    "wecom_smartsheet_profile_verification_*.xlsx",
    "wecom_smartsheet_manager_summary_*.json",
]


def output_keep_history(default: int = DEFAULT_KEEP_HISTORY) -> int:
    raw = (os.getenv("PEIFANG_OUTPUT_KEEP") or "").strip()
    if not raw:
        return default
    try:
        return max(1, int(raw))
    except ValueError:
        return default


def publish_latest(files: Mapping[str, str | Path], output_dir: str | Path) -> dict[str, str]:
    latest_dir = Path(output_dir) / "latest"
    latest_dir.mkdir(parents=True, exist_ok=True)

    published: dict[str, str] = {}
    for latest_name, source in files.items():
        src = Path(source)
        if not src.exists() or not src.is_file():
            continue
        dst = latest_dir / latest_name
        if src.resolve() == dst.resolve():
            published[latest_name] = str(dst)
            continue
        try:
            shutil.copy2(src, dst)
            published[latest_name] = str(dst)
        except OSError:
            if dst.exists():
                published[latest_name] = str(dst)
    return published


def archive_outputs(files: Mapping[str, str | Path], output_dir: str | Path) -> dict[str, str]:
    output_path = Path(output_dir)
    archive_dir = Path(output_dir) / "archive"
    latest_dir = output_path / "latest"
    archive_dir.mkdir(parents=True, exist_ok=True)

    archived: dict[str, str] = {}
    for label, source in files.items():
        src = Path(source)
        if not src.exists() or not src.is_file() or src.parent == archive_dir:
            continue
        if src.parent == latest_dir:
            continue
        dst = archive_dir / src.name
        if dst.exists():
            dst.unlink()
        shutil.move(str(src), str(dst))
        archived[label] = str(dst)
    return archived


def cleanup_output_history(output_dir: str | Path, keep: int | None = None) -> list[str]:
    output_path = Path(output_dir)
    if not output_path.exists():
        return []
    archive_path = output_path / "archive"
    archive_path.mkdir(parents=True, exist_ok=True)

    for pattern in HISTORY_PATTERNS:
        for root_file in output_path.glob(pattern):
            if not root_file.is_file() or root_file.name.startswith("~$"):
                continue
            dst = archive_path / root_file.name
            try:
                if dst.exists():
                    dst.unlink()
                shutil.move(str(root_file), str(dst))
            except OSError:
                continue

    keep_count = output_keep_history() if keep is None else max(1, keep)
    removed: list[str] = []

    for pattern in HISTORY_PATTERNS:
        files = [
            path
            for path in archive_path.glob(pattern)
            if path.is_file() and not path.name.startswith("~$")
        ]
        files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
        for old_path in files[keep_count:]:
            try:
                old_path.unlink()
                removed.append(str(old_path))
            except OSError:
                continue

    return removed
