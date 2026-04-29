"""
程序简介：直接读取指定企业微信智能表格内容，用于检查接口返回、字段和值结构。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

# read_top3.py
# 用途：读取企业微信智能表格（smartsheet）指定工作表的前 3 行（不新建表）
# 依赖：pip install requests python-dotenv
# .env 需要：
#   WECOM_ENV_PROFILE=COMPANY_A
#   WECOM_COMPANY_A_CORP_ID=...
#   WECOM_COMPANY_A_APP_SECRET=...
#   SMARTSHEET_COMPANY_A_ID=...          # docid
#   SMARTSHEET_COMPANY_A_SHEET_ID=...    # sheet_id

import os
import json
import sys
import requests
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)

from peifang_core.common import get_profiled_env, load_dotenv_for_profile

BASE = "https://qyapi.weixin.qq.com/cgi-bin"
ACTIVE_PROFILE = ""


def must_env(key: str) -> str:
    v = get_profiled_env(key, namespace="WECOM", profile=ACTIVE_PROFILE)
    if not v:
        raise RuntimeError(f"Missing .env: {key}")
    return v


def get_access_token(corpid: str, corpsecret: str) -> str:
    url = f"{BASE}/gettoken"
    r = requests.get(url, params={"corpid": corpid, "corpsecret": corpsecret}, timeout=15)
    data = r.json()
    if data.get("errcode") != 0:
        raise RuntimeError(f"gettoken failed: {data}")
    return data["access_token"]


def get_records(access_token: str, docid: str, sheet_id: str) -> dict:
    # wedoc 智能表格：查询记录
    url = f"{BASE}/wedoc/smartsheet/get_records"
    payload = {"docid": docid, "sheet_id": sheet_id}
    r = requests.post(url, params={"access_token": access_token}, json=payload, timeout=15)
    data = r.json()
    if data.get("errcode") != 0:
        raise RuntimeError(f"get_records failed: {data}")
    return data


def extract_top3(resp: dict):
    """
    不同返回可能 records 在不同字段里，这里做几个常见兜底
    """
    candidates = [
        resp.get("records"),
        (resp.get("data") or {}).get("records"),
        resp.get("record_list"),
        (resp.get("data") or {}).get("record_list"),
    ]
    for c in candidates:
        if isinstance(c, list):
            return c[:3]
    return []


def main():
    global ACTIVE_PROFILE
    ACTIVE_PROFILE = load_dotenv_for_profile("WECOM")

    corpid = must_env("WECOM_CORP_ID")
    secret = must_env("WECOM_APP_SECRET")
    docid = must_env("SMARTSHEET_ID")
    sheet_id = must_env("SMARTSHEET_SHEET_ID")

    token = get_access_token(corpid, secret)
    print("access_token OK")

    resp = get_records(token, docid, sheet_id)

    top3 = extract_top3(resp)
    print("\n=== top3 records ===")
    if not top3:
        print("未取到 records（可能表为空，或返回字段名不同）。下面打印原始返回，方便定位：")
        print(json.dumps(resp, ensure_ascii=False, indent=2))
        return

    print(json.dumps(top3, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
