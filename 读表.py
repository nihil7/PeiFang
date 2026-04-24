# read_top3.py
# 用途：读取企业微信智能表格（smartsheet）指定工作表的前 3 行（不新建表）
# 依赖：pip install requests python-dotenv
# .env 需要：
#   WECOM_CORP_ID=...
#   WECOM_APP_SECRET=...
#   SMARTSHEET_ID=...          # docid
#   SMARTSHEET_SHEET_ID=...    # sheet_id

import os
import json
import requests
from dotenv import load_dotenv

BASE = "https://qyapi.weixin.qq.com/cgi-bin"


def must_env(key: str) -> str:
    v = (os.getenv(key) or "").strip()
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
    load_dotenv()

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
