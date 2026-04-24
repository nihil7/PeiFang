import os
import re
import json
import argparse
import tempfile
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from typing import Any, Dict, List, Optional, Tuple

import requests
import pandas as pd
from dotenv import load_dotenv

# -----------------------------
# 0) 基础配置
# -----------------------------
load_dotenv()

FEISHU_API_BASE = os.getenv("FEISHU_API_BASE", "https://open.feishu.cn/open-apis")

APP_ID = os.getenv("APP_ID")
APP_SECRET = os.getenv("APP_SECRET")

# 你可以直接给 APP_TOKEN/TABLE_ID（如果你已经拿到了）
APP_TOKEN = os.getenv("APP_TOKEN")
TABLE_ID = os.getenv("TABLE_ID")

# 或者给 Wiki 入口（你现在就是这种）
WIKI_URL = os.getenv("WIKI_URL")
WIKI_NODE_TOKEN = os.getenv("WIKI_NODE_TOKEN")

SAVE_PATH = os.getenv("SAVE_PATH", "./生产数据")

# 默认筛选与字段（可通过参数覆盖/关闭）
DEFAULT_FIELD_NAMES = ["日期", "岗位", "实际产量", "拉条单价"]
DEFAULT_FILTER = {
    "conjunction": "and",
    "conditions": [{"field_name": "岗位", "operator": "eq", "value": "拉条"}]
}

TIMEOUT_TOKEN = 12
TIMEOUT_API = 20


# -----------------------------
# 1) 日志与工具函数
# -----------------------------
def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log(level: str, msg: str) -> None:
    print(f"[{ts()}] [{level}] {msg}")


def mask(s: Optional[str], keep: int = 4) -> str:
    if not s:
        return "(empty)"
    if len(s) <= keep * 2:
        return "*" * len(s)
    return f"{s[:keep]}***{s[-keep:]}"


def short_json(obj: Any, limit: int = 1200) -> str:
    try:
        text = json.dumps(obj, ensure_ascii=False)
    except Exception:
        text = str(obj)
    return text if len(text) <= limit else text[:limit] + "...(truncated)"


def require_env(name: str, value: Optional[str]) -> Tuple[bool, str]:
    if value is None or str(value).strip() == "":
        return False, f"{name} 缺失或为空"
    if any(ch.isspace() for ch in value):
        return False, f"{name} 含空格/换行，疑似复制错误"
    return True, f"{name} OK"


def check_save_path(path: Optional[str]) -> Tuple[bool, str]:
    if not path or path.strip() == "":
        return False, "SAVE_PATH 缺失或为空"
    p = os.path.abspath(path)
    try:
        os.makedirs(p, exist_ok=True)
    except Exception as e:
        return False, f"SAVE_PATH 无法创建目录：{p}；{e}"

    try:
        with tempfile.NamedTemporaryFile(dir=p, prefix="__feishu_write_test__", delete=True):
            pass
        return True, f"SAVE_PATH OK 可写：{p}"
    except Exception as e:
        return False, f"SAVE_PATH 不可写：{p}；{e}"


def request_json(method: str, url: str, headers: Dict[str, str], payload: Optional[Dict[str, Any]] = None,
                 params: Optional[Dict[str, Any]] = None,
                 timeout: int = TIMEOUT_API, debug: bool = False) -> Tuple[int, Dict[str, Any], Dict[str, Any]]:
    """
    返回：(http_status, response_json, meta)
    meta包含 log_id, url 等，便于定位
    """
    try:
        resp = requests.request(
            method=method,
            url=url,
            headers=headers,
            json=payload,
            params=params,
            timeout=timeout
        )
        status = resp.status_code
        log_id = resp.headers.get("x-tt-logid") or resp.headers.get("X-Tt-Logid") or resp.headers.get("X-Request-Id")

        try:
            data = resp.json()
        except Exception:
            data = {"_non_json_body": resp.text}

        meta = {"http_status": status, "log_id": log_id, "url": url}
        if debug:
            meta["raw_text"] = (resp.text[:2000] + "...(truncated)") if len(resp.text) > 2000 else resp.text

        return status, data, meta

    except requests.exceptions.RequestException as e:
        return 0, {"code": -1, "msg": f"requests异常：{e}"}, {"http_status": 0, "log_id": None, "url": url}


# -----------------------------
# 2) 解析 Wiki URL / Token
# -----------------------------
def parse_wiki_url(wiki_url: str) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    """
    从类似：
    https://xxx.feishu.cn/wiki/TefUwY... ?table=tbl6...&view=...
    解析出：(wiki_node_token, table_id, view_id)
    """
    u = urlparse(wiki_url)
    m = re.search(r"/wiki/([^/?]+)", u.path)
    wiki_node_token = m.group(1) if m else None

    qs = parse_qs(u.query)
    table_id = qs.get("table", [None])[0]
    view_id = qs.get("view", [None])[0]
    return wiki_node_token, table_id, view_id


# -----------------------------
# 3) 飞书 API：token + wiki 反查 + bitable 操作
# -----------------------------
def get_tenant_access_token(debug: bool = False) -> Optional[str]:
    url = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
    headers = {"Content-Type": "application/json"}
    payload = {"app_id": APP_ID, "app_secret": APP_SECRET}

    log("STEP", "获取 tenant_access_token ...")
    status, res, meta = request_json("POST", url, headers, payload, timeout=TIMEOUT_TOKEN, debug=debug)

    if status == 0:
        log("ERR", f"Token 请求失败（网络/超时）。{res.get('msg')}")
        return None

    if res.get("code") == 0:
        token = res.get("tenant_access_token")
        expires_in = res.get("expire") or res.get("expires_in")  # 兼容不同字段名
        log("OK", f"Token 获取成功，expires_in={expires_in}，log_id={meta.get('log_id')}")
        return token

    log("ERR", f"Token 获取失败：code={res.get('code')} msg={res.get('msg')} log_id={meta.get('log_id')}")
    if debug:
        log("DBG", f"响应：{short_json(res)}")
    return None


def resolve_app_token_from_wiki_node(tenant_access_token: str, wiki_node_token: str, debug: bool = False) -> Optional[str]:
    """
    用 wiki get_node 把 wiki node token 转成实际对象 token。
    当 obj_type == 'bitable' 时，obj_token 一般就是可用于 bitable 的 app_token。
    """
    url = f"{FEISHU_API_BASE}/wiki/v2/spaces/get_node"
    headers = {"Authorization": f"Bearer {tenant_access_token}"}
    params = {"token": wiki_node_token}

    log("STEP", f"通过 Wiki node 反查 Base token：node_token={mask(wiki_node_token)} ...")
    status, res, meta = request_json("GET", url, headers, payload=None, params=params, timeout=TIMEOUT_API, debug=debug)

    if status == 0:
        log("ERR", "get_node 请求失败（网络/超时）")
        return None

    if res.get("code") != 0:
        log("ERR", f"get_node 失败：code={res.get('code')} msg={res.get('msg')} log_id={meta.get('log_id')}")
        if debug:
            log("DBG", f"响应：{short_json(res)}")
        return None

    data = res.get("data", {}) or {}
    node = data.get("node") or data  # 兼容字段层级
    obj_type = node.get("obj_type")
    obj_token = node.get("obj_token")

    log("INFO", f"get_node 返回：obj_type={obj_type} obj_token={mask(obj_token)}")

    if obj_type == "bitable" and obj_token:
        log("OK", "已从 Wiki node 解析到 Base app_token（obj_token）")
        return obj_token

    # 如果不是 bitable，通常说明 wiki 节点指向 doc/docx，bitable 是嵌入在文档里
    log("ERR", f"该 Wiki 节点不是直接指向多维表格（obj_type={obj_type}）。"
               f"如果这是文档里嵌入的表格，需要换成真正的 Base 链接/或手动提供 APP_TOKEN。")
    return None


def list_fields(token: str, app_token: str, table_id: str, debug: bool = False) -> List[Dict[str, Any]]:
    url = f"{FEISHU_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/fields"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    log("STEP", "读取字段列表（校验 APP_TOKEN/TABLE_ID 是否正确）...")
    status, res, meta = request_json("GET", url, headers, payload=None, timeout=TIMEOUT_API, debug=debug)

    if status == 0:
        log("ERR", "字段列表请求失败（网络/超时）")
        return []

    if res.get("code") != 0:
        log("ERR", f"字段列表失败：code={res.get('code')} msg={res.get('msg')} log_id={meta.get('log_id')}")
        if debug:
            log("DBG", f"响应：{short_json(res)}")
        return []

    items = res.get("data", {}).get("items", []) or []
    log("OK", f"字段列表读取成功，共 {len(items)} 个字段（log_id={meta.get('log_id')}）")

    preview = []
    for it in items[:25]:
        preview.append(f"{it.get('field_name')}({it.get('type')})")
    log("INFO", "字段预览(前25)：" + " | ".join(preview) if preview else "字段预览为空")

    return items


def search_records_paginated(
    token: str,
    app_token: str,
    table_id: str,
    field_names: List[str],
    filter_obj: Optional[Dict[str, Any]],
    page_size: int = 500,
    max_pages: int = 100,
    debug: bool = False
) -> pd.DataFrame:
    url = f"{FEISHU_API_BASE}/bitable/v1/apps/{app_token}/tables/{table_id}/records/search"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    page_token = None
    all_rows: List[Dict[str, Any]] = []
    page = 0

    while True:
        page += 1
        payload: Dict[str, Any] = {
            "page_size": min(max(page_size, 1), 500),
            "field_names": field_names,
        }
        if filter_obj:
            payload["filter"] = filter_obj
        if page_token:
            payload["page_token"] = page_token

        log("STEP", f"查询记录：第 {page} 页（page_token={'YES' if page_token else 'NO'}）...")
        status, res, meta = request_json("POST", url, headers, payload=payload, timeout=TIMEOUT_API, debug=debug)

        if status == 0:
            log("ERR", f"查询失败（网络/超时），停在第 {page} 页")
            break

        if res.get("code") != 0:
            log("ERR", f"查询失败：code={res.get('code')} msg={res.get('msg')} log_id={meta.get('log_id')}")
            if debug:
                log("DBG", f"请求：{short_json(payload)}")
                log("DBG", f"响应：{short_json(res)}")
            break

        data = res.get("data", {}) or {}
        items = data.get("items", []) or []
        has_more = bool(data.get("has_more"))
        page_token = data.get("page_token")

        for rec in items:
            all_rows.append(rec.get("fields", {}) or {})

        log("OK", f"第 {page} 页：返回 {len(items)} 条；累计 {len(all_rows)} 条；has_more={has_more}")

        if not has_more:
            break
        if page >= max_pages:
            log("WARN", f"达到 max_pages={max_pages}，停止分页（累计 {len(all_rows)} 条）")
            break
        if not page_token:
            log("WARN", "has_more=True 但未返回 page_token，停止分页（建议开启 --debug 查看响应）")
            break

    df = pd.DataFrame(all_rows)
    if field_names:
        df = df.reindex(columns=field_names)
    return df


def save_data_to_excel(df: pd.DataFrame, out_dir: str, prefix: str = "拉条生产数据") -> Optional[str]:
    ok, msg = check_save_path(out_dir)
    if not ok:
        log("ERR", msg)
        return None

    today = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_name = f"{prefix}_{today}.xlsx"
    file_path = os.path.join(os.path.abspath(out_dir), file_name)

    try:
        df.to_excel(file_path, index=False, engine="openpyxl")
        log("OK", f"已保存 Excel：{file_path}（行数={len(df)} 列数={len(df.columns)}）")
        return file_path
    except Exception as e:
        log("ERR", f"保存 Excel 失败：{e}")
        return None


# -----------------------------
# 4) 环境变量校验 + 主流程
# -----------------------------
def validate_env() -> bool:
    log("STEP", "开始校验环境变量（缺失/空值/空格）...")

    ok_all = True

    for name, val in [("APP_ID", APP_ID), ("APP_SECRET", APP_SECRET), ("SAVE_PATH", SAVE_PATH)]:
        ok, msg = require_env(name, val)
        if not ok:
            ok_all = False
            log("ERR", msg)
        else:
            show = val if name == "SAVE_PATH" else mask(val)
            log("OK", f"{name}={show}")

    # 至少要提供一种入口：APP_TOKEN+TABLE_ID 或 WIKI_URL/WIKI_NODE_TOKEN
    have_direct = bool(APP_TOKEN and TABLE_ID)
    have_wiki = bool(WIKI_URL or WIKI_NODE_TOKEN)

    if not have_direct and not have_wiki:
        ok_all = False
        log("ERR", "缺少入口参数：请提供 (APP_TOKEN + TABLE_ID) 或 (WIKI_URL / WIKI_NODE_TOKEN)")
    else:
        if APP_TOKEN:
            log("OK", f"APP_TOKEN={mask(APP_TOKEN)}")
        if TABLE_ID:
            log("OK", f"TABLE_ID={mask(TABLE_ID)}")
        if WIKI_URL:
            log("OK", f"WIKI_URL={WIKI_URL}")
        if WIKI_NODE_TOKEN:
            log("OK", f"WIKI_NODE_TOKEN={mask(WIKI_NODE_TOKEN)}")

    ok_path, msg_path = check_save_path(SAVE_PATH)
    if ok_path:
        log("OK", msg_path)
    else:
        ok_all = False
        log("ERR", msg_path)

    return ok_all


def main():
    parser = argparse.ArgumentParser(description="Feishu 多维表格导出（支持从 Wiki 反查 APP_TOKEN）")
    parser.add_argument("--debug", action="store_true", help="输出更多 debug 信息（含响应截断）")
    parser.add_argument("--list-fields-only", action="store_true", help="仅列字段，验证 APP_TOKEN/TABLE_ID 是否正确")
    parser.add_argument("--no-filter", action="store_true", help="不加筛选条件（用于排查筛选不生效）")
    parser.add_argument("--page-size", type=int, default=500, help="每页条数（<=500）")
    parser.add_argument("--max-pages", type=int, default=50, help="最大翻页页数")
    parser.add_argument("--fields", type=str, default=",".join(DEFAULT_FIELD_NAMES), help="逗号分隔字段名列表")
    parser.add_argument("--out-prefix", type=str, default="生产数据导出", help="导出文件名前缀")
    args = parser.parse_args()

    log("INFO", "===== 飞书多维表格同步开始 =====")

    if not validate_env():
        log("ERR", "环境变量校验未通过：请先修正 .env 后再运行")
        return

    # 1) token
    token = get_tenant_access_token(debug=args.debug)
    if not token:
        log("ERR", "Token 获取失败，终止")
        return

    # 2) 确定 app_token/table_id
    app_token = APP_TOKEN
    table_id = TABLE_ID

    # 如果给了 WIKI_URL，就从中解析 node_token/table_id
    node_token = WIKI_NODE_TOKEN
    if WIKI_URL:
        n, t, _v = parse_wiki_url(WIKI_URL)
        if n and not node_token:
            node_token = n
        if t and not table_id:
            table_id = t
        log("INFO", f"从 WIKI_URL 解析：node_token={mask(node_token)} table_id={mask(table_id)}")

    # 如果没 app_token，但有 node_token，就用 get_node 反查
    if not app_token and node_token:
        app_token = resolve_app_token_from_wiki_node(token, node_token, debug=args.debug)

    if not app_token:
        log("ERR", "无法获得 APP_TOKEN（Base token）。请确认：")
        log("ERR", "1) 该 Wiki 节点是否“直接指向多维表格 Base”（不是文档里嵌入）")
        log("ERR", "2) 应用是否有 Wiki/知识库读取权限，并且对该节点有协作权限")
        log("ERR", "3) 或者你手动把真正的 APP_TOKEN 写入 .env")
        return

    if not table_id:
        log("ERR", "无法获得 TABLE_ID。请确认：")
        log("ERR", "1) 你的 WIKI_URL 是否带 ?table=tblxxxx")
        log("ERR", "2) 或者手动把 TABLE_ID=tblxxxx 写入 .env")
        return

    log("OK", f"最终使用：APP_TOKEN={mask(app_token)} TABLE_ID={mask(table_id)}")

    # 3) 列字段校验
    fields_meta = list_fields(token, app_token, table_id, debug=args.debug)
    if not fields_meta:
        log("ERR", "字段列表为空或失败：一般是 APP_TOKEN/TABLE_ID 不匹配或权限不够")
        log("ERR", "建议：在多维表格里把“你的应用/机器人”加为协作者（至少可查看）")
        return

    if args.list_fields_only:
        log("OK", "list-fields-only 完成：未查询记录/未导出 Excel")
        return

    # 4) 查询记录
    field_names = [x.strip() for x in args.fields.split(",") if x.strip()]
    filter_obj = None if args.no_filter else DEFAULT_FILTER
    if args.no_filter:
        log("WARN", "已开启 --no-filter：本次不加筛选条件（用于排查筛选条件/字段类型问题）")
    else:
        log("INFO", f"使用筛选：{short_json(filter_obj)}")

    df = search_records_paginated(
        token=token,
        app_token=app_token,
        table_id=table_id,
        field_names=field_names,
        filter_obj=filter_obj,
        page_size=args.page_size,
        max_pages=args.max_pages,
        debug=args.debug
    )

    if df.empty:
        log("WARN", "查询结果为空。建议：先用 --no-filter 验证是否能取到任何记录；再核对字段名/筛选值")
        return

    # 5) 保存
    save_data_to_excel(df, SAVE_PATH, prefix=args.out_prefix)
    log("INFO", "===== 飞书多维表格同步完成 =====")


if __name__ == "__main__":
    main()
