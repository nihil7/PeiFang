"""
程序简介：解析飞书多维表格、数据表、视图等 API 关键参数，便于复制到环境变量。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

import os
import re
import json
from urllib.parse import urlparse, parse_qs

import requests
from dotenv import load_dotenv

load_dotenv()

FEISHU_API_BASE = os.getenv("FEISHU_API_BASE", "https://open.feishu.cn/open-apis")
APP_ID = os.getenv("APP_ID")
APP_SECRET = os.getenv("APP_SECRET")


def mask(s: str, keep: int = 4) -> str:
    if not s:
        return "(empty)"
    if len(s) <= keep * 2:
        return "*" * len(s)
    return f"{s[:keep]}***{s[-keep:]}"


def request_json(method: str, url: str, headers=None, params=None, payload=None, timeout=15):
    headers = headers or {}
    resp = requests.request(method, url, headers=headers, params=params, json=payload, timeout=timeout)
    log_id = resp.headers.get("x-tt-logid") or resp.headers.get("X-Tt-Logid") or resp.headers.get("X-Request-Id")
    try:
        data = resp.json()
    except Exception:
        data = {"_non_json_body": resp.text}
    return resp.status_code, data, log_id


def get_tenant_access_token() -> str:
    if not APP_ID or not APP_SECRET:
        raise RuntimeError("缺少 APP_ID / APP_SECRET（请在同目录 .env 里配置）")

    url = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
    payload = {"app_id": APP_ID, "app_secret": APP_SECRET}
    status, data, log_id = request_json(
        "POST", url,
        headers={"Content-Type": "application/json"},
        payload=payload,
        timeout=12
    )

    if status != 200:
        raise RuntimeError(f"获取 tenant_access_token 失败：HTTP {status} log_id={log_id} body={data}")

    if data.get("code") != 0:
        raise RuntimeError(f"获取 tenant_access_token 失败：code={data.get('code')} msg={data.get('msg')} log_id={log_id}")

    token = data.get("tenant_access_token")
    if not token:
        raise RuntimeError(f"tenant_access_token 为空：log_id={log_id} body={data}")

    return token


def parse_link(link: str):
    """
    解析：
    - wiki_node_token: /wiki/<token>
    - base_token: /base/<token>（如果未来你拿到 base 链接也支持）
    - table_id: ?table=tbl...
    - view_id: ?view=...
    """
    u = urlparse(link.strip())
    qs = parse_qs(u.query)

    table_id = qs.get("table", [None])[0]
    view_id = qs.get("view", [None])[0]

    wiki_node_token = None
    m = re.search(r"/wiki/([^/?]+)", u.path)
    if m:
        wiki_node_token = m.group(1)

    base_token = None
    m2 = re.search(r"/base/([^/?]+)", u.path)
    if m2:
        base_token = m2.group(1)

    return {
        "domain": u.netloc,
        "wiki_node_token": wiki_node_token,
        "base_token": base_token,
        "table_id": table_id,
        "view_id": view_id,
        "raw_path": u.path,
        "raw_query": u.query,
    }


def resolve_bitable_app_token_from_wiki(tenant_token: str, wiki_node_token: str) -> str:
    url = f"{FEISHU_API_BASE}/wiki/v2/spaces/get_node"
    headers = {"Authorization": f"Bearer {tenant_token}"}
    params = {"token": wiki_node_token}

    status, data, log_id = request_json("GET", url, headers=headers, params=params, timeout=15)

    if status != 200:
        raise RuntimeError(f"get_node 失败：HTTP {status} log_id={log_id} body={data}")

    if data.get("code") != 0:
        raise RuntimeError(f"get_node 失败：code={data.get('code')} msg={data.get('msg')} log_id={log_id}")

    node = (data.get("data") or {}).get("node") or (data.get("data") or {})
    obj_type = node.get("obj_type")
    obj_token = node.get("obj_token")

    if obj_type != "bitable" or not obj_token:
        raise RuntimeError(
            f"该 wiki 节点不是直接指向多维表格 Base：obj_type={obj_type} obj_token={obj_token}\n"
            f"（如果是文档里嵌入表格，需要换 Base 链接或手动提供 APP_TOKEN）"
        )

    return obj_token


def build_env_block(parsed: dict, bitable_app_token: str | None, original_link: str) -> str:
    lines = []
    lines.append("# ====== Feishu Bitable env (auto generated) ======")
    lines.append(f"FEISHU_API_BASE={FEISHU_API_BASE}")
    lines.append(f"APP_ID={APP_ID or ''}")
    lines.append(f"APP_SECRET={APP_SECRET or ''}")

    # 原始链接保存一下，方便追溯
    lines.append(f"WIKI_URL={original_link.strip()}")

    if parsed.get("wiki_node_token"):
        lines.append(f"WIKI_NODE_TOKEN={parsed['wiki_node_token']}")

    if bitable_app_token:
        lines.append(f"APP_TOKEN={bitable_app_token}")

    if parsed.get("table_id"):
        lines.append(f"TABLE_ID={parsed['table_id']}")
    if parsed.get("view_id"):
        lines.append(f"VIEW_ID={parsed['view_id']}")

    # 默认保存路径，你按需修改
    lines.append("SAVE_PATH=./生产数据")
    lines.append("# ================================================")
    return "\n".join(lines) + "\n"


def main():
    print("===== 飞书环境变量生成器 =====")
    print("1) 请直接粘贴飞书链接（支持 /wiki/ 链接），然后回车")
    link = input("链接：").strip()

    if not link:
        print("❌ 你没有粘贴链接，程序结束")
        return

    parsed = parse_link(link)

    # 基础校验
    if not parsed.get("wiki_node_token") and not parsed.get("base_token"):
        print("❌ 解析失败：链接里没找到 /wiki/<token> 或 /base/<token>")
        print("你粘贴的链接是：", link)
        return

    if not parsed.get("table_id"):
        print("⚠️ 警告：链接里没看到 table=tbl...，后续不会生成 TABLE_ID")
        print("（如果你要调用具体表的 records/search，一般需要 TABLE_ID）")

    # 获取 tenant token
    tenant_token = get_tenant_access_token()
    print(f"✅ tenant_access_token 获取成功：{mask(tenant_token)}")

    # 得到 bitable app_token
    bitable_app_token = None
    if parsed.get("wiki_node_token"):
        bitable_app_token = resolve_bitable_app_token_from_wiki(tenant_token, parsed["wiki_node_token"])
        print(f"✅ 解析得到 APP_TOKEN（Base token）：{mask(bitable_app_token)}")
    elif parsed.get("base_token"):
        bitable_app_token = parsed["base_token"]
        print(f"✅ 从 base 链接直接得到 APP_TOKEN：{mask(bitable_app_token)}")

    env_block = build_env_block(parsed, bitable_app_token, link)

    print("\n===== 可直接复制到 .env 的内容如下 =====\n")
    print(env_block)

    # 同时保存到本地文件，避免你复制丢失
    out_file = "generated_env.txt"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(env_block)

    print(f"✅ 已保存到本地文件：{out_file}（同目录）")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print("❌ 运行失败：", str(e))
        print("提示：如果报权限/NOTEXIST，请把错误全文贴出来（含 code/msg/log_id），我能直接定位原因。")
