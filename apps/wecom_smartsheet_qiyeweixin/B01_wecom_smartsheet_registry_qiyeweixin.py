"""
程序简介：整理企业微信智能表格登记信息，生成本地 smartsheet_registry 供同步脚本选择表格。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

import json
import os
import sys
import time
import requests
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from peifang_core.common import get_profiled_env, load_dotenv_for_profile
from peifang_core.document_inventory import export_document_inventory

BASE = "https://qyapi.weixin.qq.com/cgi-bin"
ACTIVE_PROFILE = ""

# ==========================================================
# 0) 配置区（你只需要改这里）
# ==========================================================
MODE = 0  # 1 = 新建并存储；0 = 刷新 registry 里所有表的ID并打印变更

# MODE=1 时使用
DOC_NAME = "案例表4"
SHEET_TITLES = ["A", "B"]

# MODE=0 时可选：不填=自动刷新 registry 里全部 docid；填了=只刷新该 docid
TARGET_DOCID = ""

# 本地索引文件：给其它程序调用（docid / sheet_id 都在这里）
REGISTRY_PATH = "smartsheet_registry.json"

# 可选：是否顺手拉 records（默认关）
PULL_RECORDS = False
PULL_TOPN = 3

# 日志最多打印多少条“变更明细”（防止表太多刷屏）
MAX_CHANGE_LINES_PER_DOC = 50

TIMEOUT = 15
SLEEP_SECONDS = 0.2
UPDATE_ENV_TARGET_ON_CREATE = True
# ==========================================================


# =========================
# 1) 基础工具函数
# =========================
def must_env(key: str) -> str:
    """强制读取 .env（为空就报错）。"""
    v = get_profiled_env(key, namespace="WECOM", profile=ACTIVE_PROFILE)
    if not v:
        raise RuntimeError(f"Missing .env: {key}")
    return v


def now_str() -> str:
    """返回当前时间字符串（用于 registry 记录创建/同步时间）。"""
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def api_get(path: str, params: dict) -> dict:
    """封装企业微信 GET 请求。"""
    url = f"{BASE}{path}"
    r = requests.get(url, params=params, timeout=TIMEOUT)
    return r.json()


def api_post(path: str, params: dict, payload: dict) -> dict:
    """封装企业微信 POST 请求。"""
    url = f"{BASE}{path}"
    r = requests.post(url, params=params, json=payload, timeout=TIMEOUT)
    return r.json()


def short_id(s: str, keep: int = 10) -> str:
    """把超长 docid/sheet_id 简短显示（不影响存储）。"""
    if not s:
        return ""
    return s if len(s) <= keep else (s[:keep] + "...")


# =========================
# 2) Token / Doc / Sheet API
# =========================
def get_access_token(corpid: str, corpsecret: str) -> str:
    """获取 access_token（后续所有接口都需要）。"""
    data = api_get("/gettoken", {"corpid": corpid, "corpsecret": corpsecret})
    if data.get("errcode") != 0:
        raise RuntimeError(f"gettoken failed: {data}")
    return data["access_token"]


def create_smartsheet_doc(access_token: str, doc_name: str, admin_users: list[str]) -> dict:
    """新建智能表格（doc_type=10）。返回通常包含 docid、url（有时有）。"""
    payload = {"doc_type": 10, "doc_name": doc_name, "admin_users": admin_users}
    data = api_post("/wedoc/create_doc", {"access_token": access_token}, payload)
    if data.get("errcode") != 0:
        raise RuntimeError(f"create_doc failed: {data}")
    return data


def add_sheet(access_token: str, docid: str, title: str, index: int = 1) -> dict:
    """
    新增工作表。
    不依赖返回取 sheet_id（接口返回结构可能变化），我们会用 get_sheets 稳定获取。
    """
    payload = {"docid": docid, "properties": {"title": title, "index": index}}
    data = api_post("/wedoc/smartsheet/add_sheet", {"access_token": access_token}, payload)
    if data.get("errcode") != 0:
        raise RuntimeError(f"add_sheet failed: {data}")
    return data


def get_sheets(access_token: str, docid: str) -> list[dict]:
    """查询 docid 下全部工作表（稳定拿 sheet_id；云端新增/改名也能发现）。"""
    payload = {"docid": docid}
    data = api_post("/wedoc/smartsheet/get_sheet", {"access_token": access_token}, payload)
    if data.get("errcode") != 0:
        raise RuntimeError(f"get_sheet failed: {data}")

    # 兼容不同字段名
    sheets = data.get("sheets") or data.get("sheet_list") or data.get("data") or []
    if isinstance(sheets, dict):
        sheets = sheets.get("sheets") or sheets.get("sheet_list") or []
    if not isinstance(sheets, list):
        sheets = []
    return sheets


def normalize_sheet_item(s: dict) -> dict:
    """把原始 sheet 对象整理为统一格式，便于比对、落盘。"""
    props = s.get("properties") or {}
    sheet_id = s.get("sheet_id") or s.get("id") or ""
    title = props.get("title") or s.get("title") or ""
    index = props.get("index") if "index" in props else s.get("index", "")
    # 有些返回里可能带 is_visible/type 等信息，我们保留到 raw 里
    return {"sheet_id": sheet_id, "title": title, "index": index, "raw": s}


def get_records(access_token: str, docid: str, sheet_id: str) -> dict:
    """读取工作表记录（可选功能）。"""
    payload = {"docid": docid, "sheet_id": sheet_id}
    data = api_post("/wedoc/smartsheet/get_records", {"access_token": access_token}, payload)
    if data.get("errcode") != 0:
        raise RuntimeError(f"get_records failed: {data}")
    return data


# =========================
# 3) Registry：本地索引文件（给其它程序读）
# =========================
def load_registry(path: str) -> dict:
    """读取 registry（没有就返回空）。"""
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_registry(path: str, registry: dict) -> None:
    """写入 registry 到本地 JSON。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(registry, f, ensure_ascii=False, indent=2)


def ensure_doc_entry(
    registry: dict,
    docid: str,
    admin_userid: str,
    doc_name: str = "",
    url: str = "",
    env_profile: str = "",
) -> None:
    """确保 registry 里存在 docid 条目（MODE=0 也能同步）。"""
    docs = registry.setdefault("docs", {})
    if docid not in docs:
        docs[docid] = {
            "docid": docid,
            "doc_name": doc_name,
            "url": url,
            "admin_userid": admin_userid,
            "env_profile": env_profile,
            "created_at": now_str() if doc_name else "",
            "last_sync_at": "",
            "sheets": {}
        }
    else:
        # 不覆盖已有信息，只补空
        if doc_name and not docs[docid].get("doc_name"):
            docs[docid]["doc_name"] = doc_name
        if url and not docs[docid].get("url"):
            docs[docid]["url"] = url
        if admin_userid and not docs[docid].get("admin_userid"):
            docs[docid]["admin_userid"] = admin_userid
        if env_profile and not docs[docid].get("env_profile"):
            docs[docid]["env_profile"] = env_profile


def update_env_value(lines: list[str], key: str, value: str) -> list[str]:
    """更新 .env 中的单个变量；不存在则追加。"""
    found = False
    updated: list[str] = []
    for line in lines:
        if line.strip().startswith("#") or "=" not in line:
            updated.append(line)
            continue
        old_key = line.split("=", 1)[0].strip()
        if old_key == key:
            updated.append(f"{key}={value}")
            found = True
        else:
            updated.append(line)
    if not found:
        updated.append(f"{key}={value}")
    return updated


def write_profile_target_to_env(profile: str, docid: str, sheet_id: str, sheet_title: str) -> None:
    """把新建表格的目标 docid/sheet_id 写回当前公司配置，方便 B02 直接同步。"""
    if not UPDATE_ENV_TARGET_ON_CREATE or not profile:
        return

    normalized_profile = "".join(ch if ch.isalnum() else "_" for ch in profile.upper()).strip("_")
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    lines = env_path.read_text(encoding="utf-8").splitlines()
    replacements = {
        f"WEDOC_{normalized_profile}_DOCID": docid,
        f"WEDOC_{normalized_profile}_SHEET_ID": sheet_id,
        f"WEDOC_{normalized_profile}_DOC_NAME": DOC_NAME,
        f"WEDOC_{normalized_profile}_SHEET_TITLE": sheet_title,
        f"SMARTSHEET_{normalized_profile}_ID": docid,
        f"SMARTSHEET_{normalized_profile}_SHEET_ID": sheet_id,
    }
    for key, value in replacements.items():
        lines = update_env_value(lines, key, value)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n=== .env 已更新当前公司目标表格：WECOM_ENV_PROFILE={profile} ===")
    print(f"doc_name={DOC_NAME} | sheet_title={sheet_title}")


def mark_profile_access(registry: dict, docid: str, profile: str, status: str, error: str = "") -> None:
    """记录某个公司 profile 是否能访问该 doc，避免下次反复扫无效 docid。"""
    if not profile:
        return
    doc = (registry.get("docs") or {}).get(docid)
    if not doc:
        return
    access = doc.setdefault("profile_access", {})
    access[profile] = {
        "status": status,
        "checked_at": now_str(),
        "error": error,
    }


def is_invalid_docid_error(error: str) -> bool:
    return "301085" in error or "invalid docid" in error.lower()


def hydrate_profile_access_from_errors(registry: dict, profile: str) -> None:
    """把上一次中断前已保存的 invalid docid 错误转成 profile 访问状态。"""
    if not profile:
        return
    for item in registry.get("sync_errors") or []:
        docid = str(item.get("docid") or "")
        error = str(item.get("error") or "")
        if docid and is_invalid_docid_error(error):
            mark_profile_access(registry, docid, profile, "invalid_docid", error)


def should_skip_for_profile(registry: dict, docid: str, profile: str) -> bool:
    if not profile:
        return False
    doc = (registry.get("docs") or {}).get(docid) or {}
    access = (doc.get("profile_access") or {}).get(profile) or {}
    return access.get("status") in {"invalid_docid", "no_access"}


def looks_like_docid(value: str) -> bool:
    text = str(value or "").strip()
    return text.startswith("dc") and len(text) > 20


def profile_target_docids(profile: str) -> list[str]:
    """读取当前 profile 在 .env 中显式配置的目标 docid。"""
    targets = [
        get_profiled_env("WEDOC_DOCID", namespace="WECOM", profile=profile, fallback_legacy=not bool(profile)),
        get_profiled_env("SMARTSHEET_ID", namespace="WECOM", profile=profile, fallback_legacy=not bool(profile)),
    ]
    return list(dict.fromkeys(docid for docid in targets if looks_like_docid(docid)))


def doc_matches_active_profile(registry: dict, docid: str, profile: str) -> bool:
    """有 profile 时只自动刷新归属于该 profile 的 doc。"""
    if not profile:
        return True
    doc = (registry.get("docs") or {}).get(docid) or {}
    return str(doc.get("env_profile") or "").strip() == profile


def build_sheet_map_from_registry(registry_doc: dict) -> dict:
    """
    从 registry 里提取旧的 sheet 状态，用于对比：
    old_map[sheet_id] = {"title":..., "index":..., "missing":...}
    """
    old = {}
    sheets = (registry_doc.get("sheets") or {})
    for sid, info in sheets.items():
        old[sid] = {
            "title": info.get("title", ""),
            "index": info.get("index", ""),
            "missing": bool(info.get("missing", False)),
        }
    return old


def build_sheet_map_from_cloud(sheet_items: list[dict]) -> dict:
    """
    从云端返回的 sheets 构造新 map：
    new_map[sheet_id] = {"title":..., "index":..., "raw":...}
    """
    new = {}
    for s in sheet_items:
        ns = normalize_sheet_item(s)
        sid = ns["sheet_id"]
        if not sid:
            continue
        new[sid] = ns
    return new


def sync_sheets_to_registry_with_diff(registry: dict, docid: str, cloud_sheets: list[dict]) -> dict:
    """
    同步并返回“变更明细”：
    - added: 新增工作表
    - changed: 同一个 sheet_id 下 title/index 等变化
    - missing: registry 有但云端本次没返回（可能权限/隐藏/删除/移动，谨慎描述）
    """
    doc = registry["docs"][docid]
    old_map = build_sheet_map_from_registry(doc)
    new_map = build_sheet_map_from_cloud(cloud_sheets)

    old_ids = set(old_map.keys())
    new_ids = set(new_map.keys())

    added_ids = sorted(list(new_ids - old_ids))
    missing_ids = sorted(list(old_ids - new_ids))
    common_ids = sorted(list(old_ids & new_ids))

    # 生成变更清单
    added = []
    changed = []
    missing = []

    # 1) 新增
    for sid in added_ids:
        added.append({
            "sheet_id": sid,
            "title": new_map[sid].get("title", ""),
            "index": new_map[sid].get("index", "")
        })

    # 2) 共同存在：对比 title/index
    for sid in common_ids:
        o = old_map.get(sid, {})
        n = new_map.get(sid, {})
        old_title = o.get("title", "")
        new_title = n.get("title", "")
        old_index = o.get("index", "")
        new_index = n.get("index", "")

        diff_fields = {}
        if old_title != new_title:
            diff_fields["title"] = (old_title, new_title)
        if old_index != new_index:
            diff_fields["index"] = (old_index, new_index)

        # 如果之前标记 missing，但这次云端回来了，也算一种“状态变化”
        was_missing = bool(o.get("missing", False))
        if was_missing:
            diff_fields["missing_cleared"] = (True, False)

        if diff_fields:
            changed.append({"sheet_id": sid, "diff": diff_fields})

    # 3) 云端未返回
    for sid in missing_ids:
        o = old_map.get(sid, {})
        missing.append({
            "sheet_id": sid,
            "title": o.get("title", ""),
            "index": o.get("index", "")
        })

    # ====== 把 new_map 写回 registry（并标记 missing）======
    sheets_store = doc.setdefault("sheets", {})

    # 云端返回的都更新/新增
    for sid, ns in new_map.items():
        if sid not in sheets_store:
            sheets_store[sid] = {
                "sheet_id": sid,
                "title": ns.get("title", ""),
                "index": ns.get("index", ""),
                "first_seen_at": now_str(),
                "last_seen_at": now_str(),
                "missing": False,
                "missing_since": "",
                "raw": ns.get("raw", {}),
            }
        else:
            sheets_store[sid]["title"] = ns.get("title", "")
            sheets_store[sid]["index"] = ns.get("index", "")
            sheets_store[sid]["last_seen_at"] = now_str()
            sheets_store[sid]["raw"] = ns.get("raw", {})
            # 之前 missing 的清掉
            sheets_store[sid]["missing"] = False
            sheets_store[sid]["missing_since"] = ""

    # 未返回的：不删除，只标记 missing（避免误判）
    for sid in missing_ids:
        if sid in sheets_store:
            sheets_store[sid]["missing"] = True
            if not sheets_store[sid].get("missing_since"):
                sheets_store[sid]["missing_since"] = now_str()

    doc["last_sync_at"] = now_str()

    # 汇总统计：把 changed 再细分一下（更人类）
    renamed = 0
    reindexed = 0
    restored = 0
    for c in changed:
        d = c["diff"]
        if "title" in d:
            renamed += 1
        if "index" in d:
            reindexed += 1
        if "missing_cleared" in d:
            restored += 1

    return {
        "total": len(sheets_store),
        "added": added,
        "changed": changed,
        "missing": missing,
        "counts": {
            "added": len(added),
            "changed": len(changed),
            "missing": len(missing),
            "renamed": renamed,
            "reindexed": reindexed,
            "restored": restored
        }
    }


def print_diff_log(i: int, n: int, docid: str, doc_name: str, diff: dict) -> None:
    """按“人类可读”方式打印本次刷新变更。"""
    c = diff["counts"]
    print(f"[{i}/{n}] OK docid={docid} name={doc_name} sheets_total={diff['total']} "
          f"+{c['added']} ~{c['changed']} -{c['missing']} (rename={c['renamed']} index={c['reindexed']})")

    lines = []
    # 新增
    for a in diff["added"]:
        sid = a["sheet_id"]
        lines.append(f"  + 新增 [{short_id(sid)}] {a.get('title','')} (index={a.get('index','')})")

    # 变更（合并同一 sheet_id 的变化）
    for ch in diff["changed"]:
        sid = ch["sheet_id"]
        d = ch["diff"]
        parts = []
        if "title" in d:
            old_t, new_t = d["title"]
            parts.append(f"改名：{old_t} -> {new_t}")
        if "index" in d:
            old_i, new_i = d["index"]
            parts.append(f"顺序：{old_i} -> {new_i}")
        if "missing_cleared" in d:
            parts.append("状态：已恢复可见")
        if parts:
            lines.append(f"  ~ 变更 [{short_id(sid)}] " + "；".join(parts))

    # 未返回（谨慎措辞）
    for m in diff["missing"]:
        sid = m["sheet_id"]
        lines.append(f"  - 未在云端列表中 [{short_id(sid)}] {m.get('title','')} (last_index={m.get('index','')})")

    if not lines:
        print("  = 无变化（仅更新同步时间/原始信息）")
        return

    # 控制打印条数，避免刷屏
    if len(lines) > MAX_CHANGE_LINES_PER_DOC:
        show = lines[:MAX_CHANGE_LINES_PER_DOC]
        for x in show:
            print(x)
        print(f"  ... 其余 {len(lines) - MAX_CHANGE_LINES_PER_DOC} 条变更已省略（可调 MAX_CHANGE_LINES_PER_DOC）")
    else:
        for x in lines:
            print(x)


def maybe_pull_records(token: str, registry: dict, docid: str) -> None:
    """可选：拉 records（默认关闭）。"""
    if not PULL_RECORDS:
        return

    sheets_map = (registry.get("docs") or {}).get(docid, {}).get("sheets") or {}
    print(f"\n=== pull records for docid={short_id(docid, 16)} ===")
    for sid, info in sheets_map.items():
        if info.get("missing"):
            continue  # missing 的不拉
        rec = get_records(token, docid, sid)
        rows = rec.get("records") or []
        topn = rows[:PULL_TOPN]
        print(f"[{info.get('title','')}] count={len(rows)} top{PULL_TOPN}={json.dumps(topn, ensure_ascii=False)}")
        time.sleep(SLEEP_SECONDS)


# =========================
# 4) 两种模式
# =========================
def run_mode_create(token: str, admin_userid: str) -> str:
    """MODE=1：新建 doc + 新建 sheets + 同步并落盘。"""
    doc = create_smartsheet_doc(token, DOC_NAME, [admin_userid])
    docid = doc["docid"]
    url = doc.get("url", "")

    print("\n=== create_doc OK ===")
    print("docid:", docid)
    if url:
        print("url:", url)

    for i, title in enumerate(SHEET_TITLES, start=1):
        resp = add_sheet(token, docid, title, index=i)
        print(f"add_sheet: {title} => errcode={resp.get('errcode')} errmsg={resp.get('errmsg','')}")

    registry = load_registry(REGISTRY_PATH)
    ensure_doc_entry(registry, docid, admin_userid, doc_name=DOC_NAME, url=url, env_profile=ACTIVE_PROFILE)

    cloud_sheets = get_sheets(token, docid)
    diff = sync_sheets_to_registry_with_diff(registry, docid, cloud_sheets)
    save_registry(REGISTRY_PATH, registry)
    inventory = export_document_inventory(Path(REGISTRY_PATH))

    sheet_id_for_env = ""
    sheet_title_for_env = ""
    normalized_sheets = [normalize_sheet_item(item) for item in cloud_sheets]
    for title in SHEET_TITLES:
        for item in normalized_sheets:
            if item.get("title") == title:
                sheet_id_for_env = str(item.get("sheet_id") or "")
                sheet_title_for_env = str(item.get("title") or "")
                break
        if sheet_id_for_env:
            break
    if not sheet_id_for_env and normalized_sheets:
        sheet_id_for_env = str(normalized_sheets[0].get("sheet_id") or "")
        sheet_title_for_env = str(normalized_sheets[0].get("title") or "")
    write_profile_target_to_env(ACTIVE_PROFILE, docid, sheet_id_for_env, sheet_title_for_env)

    print("\n=== registry saved ===")
    print("registry_path:", os.path.abspath(REGISTRY_PATH))
    print("document_inventory:", inventory.get("latest_xlsx_path", ""))
    print_diff_log(1, 1, docid, DOC_NAME, diff)

    maybe_pull_records(token, registry, docid)
    return docid


def run_mode_sync_all(token: str, admin_userid: str) -> None:
    """
    MODE=0：自动刷新 registry 里所有 docid。
    可选：如果配置了 TARGET_DOCID，则只刷新那个 docid。
    """
    registry = load_registry(REGISTRY_PATH)
    hydrate_profile_access_from_errors(registry, ACTIVE_PROFILE)
    docs = registry.get("docs") or {}

    if TARGET_DOCID.strip():
        docids = [TARGET_DOCID.strip()]
        ensure_doc_entry(registry, docids[0], admin_userid, env_profile=ACTIVE_PROFILE)
    else:
        env_target_docids = profile_target_docids(ACTIVE_PROFILE)
        docids = [
            docid
            for docid in docs.keys()
            if doc_matches_active_profile(registry, docid, ACTIVE_PROFILE)
            and not should_skip_for_profile(registry, docid, ACTIVE_PROFILE)
        ]
        for docid in env_target_docids:
            ensure_doc_entry(registry, docid, admin_userid, env_profile=ACTIVE_PROFILE)
            if docid not in docids:
                docids.append(docid)
        if env_target_docids:
            save_registry(REGISTRY_PATH, registry)

    if not docids:
        raise RuntimeError(
            f"MODE=0 需要先有可刷新的 docid。\n"
            f"当前 {REGISTRY_PATH} 里没有 docs。\n"
            f"解决：先 MODE=1 创建一次，或手动把 docid 写入 registry 后再运行 MODE=0。"
        )

    print("=== sync start ===")
    print("registry_path:", os.path.abspath(REGISTRY_PATH))
    print("doc_count:", len(docids))
    print("env_target_doc_count:", len(profile_target_docids(ACTIVE_PROFILE)))
    skipped_count = len(docs) - len(docids) if not TARGET_DOCID.strip() else 0
    if skipped_count:
        print("skipped_invalid_for_profile:", skipped_count)

    errors = []
    for idx, docid in enumerate(docids, start=1):
        try:
            ensure_doc_entry(registry, docid, admin_userid, env_profile=ACTIVE_PROFILE)
            cloud_sheets = get_sheets(token, docid)
            mark_profile_access(registry, docid, ACTIVE_PROFILE, "ok")
            diff = sync_sheets_to_registry_with_diff(registry, docid, cloud_sheets)
            save_registry(REGISTRY_PATH, registry)

            doc_name = (registry["docs"][docid].get("doc_name") or "").strip()
            if not doc_name:
                doc_name = "(未命名/未知)"

            print_diff_log(idx, len(docids), docid, doc_name, diff)
            maybe_pull_records(token, registry, docid)
            time.sleep(SLEEP_SECONDS)

        except Exception as e:
            error_text = str(e)
            if is_invalid_docid_error(error_text):
                mark_profile_access(registry, docid, ACTIVE_PROFILE, "invalid_docid", error_text)
                save_registry(REGISTRY_PATH, registry)
            errors.append({"docid": docid, "error": error_text})
            print(f"[{idx}/{len(docids)}] FAIL docid={docid} error={e}")

    if errors:
        registry.setdefault("sync_errors", [])
        registry["sync_errors"] = [{"time": now_str(), **x} for x in errors][-200:]
        save_registry(REGISTRY_PATH, registry)
        inventory = export_document_inventory(Path(REGISTRY_PATH))
        print("\n=== sync finished with errors ===")
        print("document_inventory:", inventory.get("latest_xlsx_path", ""))
        print(json.dumps(errors, ensure_ascii=False, indent=2))
    else:
        inventory = export_document_inventory(Path(REGISTRY_PATH))
        print("\n=== sync finished: all OK ===")
        print("document_inventory:", inventory.get("latest_xlsx_path", ""))


# =========================
# 5) 主入口
# =========================
def main():
    global ACTIVE_PROFILE
    ACTIVE_PROFILE = load_dotenv_for_profile("WECOM")
    corpid = must_env("WECOM_CORP_ID")
    secret = must_env("WECOM_APP_SECRET")
    admin_userid = must_env("ADMIN_USERID")

    token = get_access_token(corpid, secret)
    print("access_token OK")
    print("MODE:", MODE)

    if MODE == 1:
        new_docid = run_mode_create(token, admin_userid)
        print("\n创建完成，新 docid：", new_docid)
        print("以后刷新：把 MODE 改成 0 直接运行（会自动刷 registry 里所有表）。")

    elif MODE == 0:
        run_mode_sync_all(token, admin_userid)

    else:
        raise RuntimeError("MODE 只能是 0 或 1")


if __name__ == "__main__":
    main()

