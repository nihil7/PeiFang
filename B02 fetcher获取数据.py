# fetcher.py
# 作用：
# - 从 smartsheet_registry.json 读取已刷新 docid / sheet_id
# - 同时拉取：表头(字段列表) + 记录(records)
# - 打印：字段清单 + 前N条记录预览
# - 保存：fields.json + records.raw.json + preview.txt

# ====== 配置区（你只要改这里）======
REGISTRY_PATH = "smartsheet_registry.json"

# 推荐：用名字选择（更像人）
SELECT_DOC_NAME = "生产任务排期"
SELECT_SHEET_TITLE = "排产·统计总台账"

# 也支持：直接用ID选择（优先级更高，作为兜底）
SELECT_DOCID = ""
SELECT_SHEET_ID = ""

FETCH_FIRST_N = 50

# 打印控制（避免刷屏/超长）
MAX_CELL_TEXT_LEN = 120     # 单元格文本最多显示多少字符（打印用）
MAX_LINE_LEN = 600          # 每行拼接后最多显示多少字符（打印用）
PRINT_SAVE_DIR = "output"

# 是否把“字段ID”也一并打印出来（便于你后续做映射/调试）
PRINT_FIELD_ID = True

TIMEOUT = 15
# ====== 配置区结束 ======

import os
import json
import requests
from datetime import datetime
from dotenv import load_dotenv

BASE = "https://qyapi.weixin.qq.com/cgi-bin"


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _now_str() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _must_env(key: str) -> str:
    v = (os.getenv(key) or "").strip()
    if not v:
        raise RuntimeError(f"fetcher.py 缺少必要的 .env 配置：{key}")
    return v


def _truncate(s: str, max_len: int) -> str:
    s = "" if s is None else str(s)
    if max_len <= 0:
        return s
    return s if len(s) <= max_len else (s[:max_len] + "…")


def _safe_name(s: str, max_len: int = 40) -> str:
    s = (s or "").strip()
    s = s.replace("/", "_").replace("\\", "_").replace(":", "_").replace("*", "_").replace("?", "_") \
         .replace('"', "_").replace("<", "_").replace(">", "_").replace("|", "_")
    return s[:max_len] if len(s) > max_len else s


def _load_registry(path: str) -> dict:
    if not os.path.exists(path):
        raise RuntimeError(f"找不到 registry 文件：{os.path.abspath(path)}")
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def _resolve_doc(reg: dict) -> tuple[str, dict]:
    docs = reg.get("docs") or {}
    if not docs:
        raise RuntimeError("registry 里没有 docs：请先运行你的刷新脚本（MODE=0）或创建脚本（MODE=1）。")

    if SELECT_DOCID.strip():
        docid = SELECT_DOCID.strip()
        if docid not in docs:
            raise RuntimeError(f"registry 中找不到该 docid：{docid}")
        return docid, docs[docid]

    target_name = (SELECT_DOC_NAME or "").strip()
    if not target_name:
        raise RuntimeError("未配置 SELECT_DOCID，也未配置 SELECT_DOC_NAME")

    for docid, entry in docs.items():
        if (entry.get("doc_name") or "").strip() == target_name:
            return docid, entry

    names = [((e.get("doc_name") or "").strip() or "(未命名)") for e in docs.values()]
    raise RuntimeError(f"registry 中找不到 doc_name={target_name}。可选 doc_name：{names}")


def _resolve_sheet(doc_entry: dict) -> tuple[str, dict]:
    sheets = doc_entry.get("sheets") or {}
    if not sheets:
        raise RuntimeError("该 docid 在 registry 中没有 sheets：请先运行刷新脚本同步 sheet_id。")

    if SELECT_SHEET_ID.strip():
        sid = SELECT_SHEET_ID.strip()
        if sid not in sheets:
            raise RuntimeError(f"registry 中找不到该 sheet_id：{sid}")
        return sid, sheets[sid]

    target_title = (SELECT_SHEET_TITLE or "").strip()
    if not target_title:
        raise RuntimeError("未配置 SELECT_SHEET_ID，也未配置 SELECT_SHEET_TITLE")

    for sid, info in sheets.items():
        if (info.get("title") or "").strip() == target_title:
            return sid, info

    titles = [((s.get("title") or "").strip() or "(无标题)") for s in sheets.values()]
    raise RuntimeError(f"找不到 sheet_title={target_title}。可选 sheet_title：{titles}")


def _api_get(path: str, params: dict) -> dict:
    url = f"{BASE}{path}"
    r = requests.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _api_post(path: str, params: dict, payload: dict) -> dict:
    url = f"{BASE}{path}"
    r = requests.post(url, params=params, json=payload, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()


def _get_access_token(corpid: str, secret: str) -> str:
    data = _api_get("/gettoken", {"corpid": corpid, "corpsecret": secret})
    if data.get("errcode") != 0:
        raise RuntimeError(f"获取 access_token 失败：{data}")
    return data["access_token"]


def _get_fields(access_token: str, docid: str, sheet_id: str) -> dict:
    """
    查询字段（表头）接口：
    企业微信智能表格存在“查询字段”这一类能力，常见路径为 /wedoc/smartsheet/get_fields。
    若你环境返回字段名不同，本函数会尽量兼容解析。
    参考开发实践中“查询字段”的文档/说明：:contentReference[oaicite:1]{index=1}
    """
    payload = {"docid": docid, "sheet_id": sheet_id}
    data = _api_post("/wedoc/smartsheet/get_fields", {"access_token": access_token}, payload)
    if data.get("errcode") != 0:
        raise RuntimeError(f"get_fields 失败：{data}")
    return data


def _get_records(access_token: str, docid: str, sheet_id: str) -> dict:
    payload = {"docid": docid, "sheet_id": sheet_id}
    data = _api_post("/wedoc/smartsheet/get_records", {"access_token": access_token}, payload)
    if data.get("errcode") != 0:
        raise RuntimeError(f"get_records 失败：{data}")
    return data


def _cell_to_text(v) -> str:
    """
    单元格 values 常见结构是 list[dict]：比如 [{'type':'text','text':'xxx'}]
    这里做尽量可读的兜底。
    """
    if v is None:
        return ""
    if isinstance(v, list) and v:
        first = v[0]
        if isinstance(first, dict):
            if "text" in first:
                return str(first["text"])
            # 兜底：把 dict 压成 json 字符串
            return json.dumps(first, ensure_ascii=False)
        return str(first)
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def _parse_fields(fields_data: dict) -> list[dict]:
    """
    兼容解析字段列表：
    预期字段列表可能在 fields / field_list / data 等位置
    每个字段常见包含：field_id / id / title / name / type
    """
    fields = fields_data.get("fields") or fields_data.get("field_list") or fields_data.get("data") or []
    if isinstance(fields, dict):
        fields = fields.get("fields") or fields.get("field_list") or []
    if not isinstance(fields, list):
        fields = []

    out = []
    for f in fields:
        if not isinstance(f, dict):
            continue
        fid = f.get("field_id") or f.get("id") or ""
        title = f.get("title") or f.get("name") or ""
        ftype = f.get("type") or f.get("field_type") or ""
        out.append({"field_id": fid, "title": title, "type": ftype, "raw": f})
    return out


def _build_field_maps(fields: list[dict]) -> tuple[dict, dict]:
    """
    返回：
    - id_to_title: field_id -> title
    - id_to_type:  field_id -> type
    """
    id_to_title = {}
    id_to_type = {}
    for f in fields:
        fid = (f.get("field_id") or "").strip()
        if not fid:
            continue
        id_to_title[fid] = (f.get("title") or "").strip() or fid
        id_to_type[fid] = (f.get("type") or "").strip()
    return id_to_title, id_to_type


def build_message() -> str:
    """
    入口：
    1) .env: corpid/secret
    2) registry: docid/sheet_id
    3) get_fields + get_records
    4) 打印并保存
    5) return 可发送文本（如你后续要接 sender.py）
    """
    load_dotenv()

    corpid = _must_env("WECOM_CORP_ID")
    secret = _must_env("WECOM_APP_SECRET")

    reg = _load_registry(REGISTRY_PATH)
    docid, doc_entry = _resolve_doc(reg)
    sheet_id, sheet_entry = _resolve_sheet(doc_entry)

    doc_name = (doc_entry.get("doc_name") or "").strip() or "(未命名文档)"
    sheet_title = (sheet_entry.get("title") or "").strip() or "(无标题工作表)"

    access_token = _get_access_token(corpid, secret)

    # 1) 表头 / 字段
    fields_data = _get_fields(access_token, docid, sheet_id)
    fields = _parse_fields(fields_data)
    id_to_title, id_to_type = _build_field_maps(fields)

    # 2) 数据
    rec_data = _get_records(access_token, docid, sheet_id)
    records = rec_data.get("records", []) or []
    head = records[: min(FETCH_FIRST_N, len(records))]

    # 3) 打印：字段清单
    print("========== 智能表格拉取结果 ==========")
    print(f"doc_name: {doc_name}")
    print(f"docid: {docid}")
    print(f"sheet_title: {sheet_title}")
    print(f"sheet_id: {sheet_id}")
    print(f"fields_count: {len(fields)}")
    print(f"records_total: {len(records)}")
    print(f"print_first_n: {len(head)}")
    print("--------------------------------------")

    print("【表头/字段列表】")
    if fields:
        for i, f in enumerate(fields, start=1):
            fid = f.get("field_id", "")
            title = f.get("title", "")
            ftype = f.get("type", "")
            if PRINT_FIELD_ID:
                print(f"  {i}. {title} (type={ftype}) [field_id={fid}]")
            else:
                print(f"  {i}. {title} (type={ftype})")
    else:
        print("  （未解析到字段列表：可能接口返回结构不同，或该表没有字段权限）")

    print("--------------------------------------")
    print(f"【前 {len(head)} 条记录预览】")

    # 4) 打印：前 N 行（用列名）
    lines = []
    for i, row in enumerate(head, start=1):
        values = row.get("values", {}) or {}
        parts = []
        for k, v in values.items():
            col = id_to_title.get(k, k)  # 优先翻译成列名
            txt = _truncate(_cell_to_text(v), MAX_CELL_TEXT_LEN)
            parts.append(f"{col}={txt}")

        line = f"{i}. " + (" | ".join(parts) if parts else "（该行无可读字段）")
        line = _truncate(line, MAX_LINE_LEN)
        lines.append(line)

    preview_text = "\n".join(lines) if lines else "（当前没有记录）"
    print(preview_text)
    print("======================================")

    # 5) 保存
    os.makedirs(PRINT_SAVE_DIR, exist_ok=True)
    tag = _now_tag()

    base = f"{_safe_name(doc_name)}__{_safe_name(sheet_title)}__{tag}"

    fields_path = os.path.join(PRINT_SAVE_DIR, base + ".fields.json")
    raw_records_path = os.path.join(PRINT_SAVE_DIR, base + ".records.raw.json")
    preview_path = os.path.join(PRINT_SAVE_DIR, base + ".preview.txt")

    fields_out = {
        "generated_at": _now_str(),
        "doc_name": doc_name,
        "docid": docid,
        "sheet_title": sheet_title,
        "sheet_id": sheet_id,
        "fields_count": len(fields),
        "fields": fields,
    }

    records_out = {
        "generated_at": _now_str(),
        "doc_name": doc_name,
        "docid": docid,
        "sheet_title": sheet_title,
        "sheet_id": sheet_id,
        "fetch_first_n": FETCH_FIRST_N,
        "records_total": len(records),
        "records": head,  # 原始结构（不截断），后续处理最稳
    }

    with open(fields_path, "w", encoding="utf-8") as f:
        json.dump(fields_out, f, ensure_ascii=False, indent=2)

    with open(raw_records_path, "w", encoding="utf-8") as f:
        json.dump(records_out, f, ensure_ascii=False, indent=2)

    with open(preview_path, "w", encoding="utf-8") as f:
        f.write(preview_text)

    print("\n[已保存]")
    print("fields_json:", os.path.abspath(fields_path))
    print("records_raw_json:", os.path.abspath(raw_records_path))
    print("preview_txt:", os.path.abspath(preview_path))

    # 6) 返回“可发送消息文本”（如果你后面还想接 sender.py）
    final_message = f"智能表格数据预览\n前{len(head)}条\n{preview_text}"
    return final_message


if __name__ == "__main__":
    msg = build_message()
    print("\n[build_message 返回的发送文本长度] =", len(msg))
