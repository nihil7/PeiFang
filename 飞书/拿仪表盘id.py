import os
import requests
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()

FEISHU_API_BASE = os.getenv("FEISHU_API_BASE", "https://open.feishu.cn/open-apis")
APP_ID = os.getenv("APP_ID")
APP_SECRET = os.getenv("APP_SECRET")
APP_TOKEN = os.getenv("APP_TOKEN")  # 你已经有：SyLY...

def ts():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

def log(level, msg):
    print(f"[{ts()}] [{level}] {msg}")

def request_json(method, url, headers=None, payload=None, params=None, timeout=15):
    headers = headers or {}
    r = requests.request(method, url, headers=headers, json=payload, params=params, timeout=timeout)
    log_id = r.headers.get("x-tt-logid") or r.headers.get("X-Tt-Logid") or r.headers.get("X-Request-Id")
    try:
        data = r.json()
    except Exception:
        data = {"_non_json_body": r.text}
    return r.status_code, data, log_id

def get_tenant_access_token():
    url = f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal"
    payload = {"app_id": APP_ID, "app_secret": APP_SECRET}
    status, data, log_id = request_json("POST", url, headers={"Content-Type":"application/json"}, payload=payload, timeout=12)
    if status != 200 or data.get("code") != 0:
        raise RuntimeError(f"token失败 HTTP={status} code={data.get('code')} msg={data.get('msg')} log_id={log_id}")
    return data["tenant_access_token"]

def main():
    if not (APP_ID and APP_SECRET and APP_TOKEN):
        log("ERR", "请检查 .env：需要 APP_ID/APP_SECRET/APP_TOKEN")
        return

    token = get_tenant_access_token()
    url = f"{FEISHU_API_BASE}/bitable/v1/apps/{APP_TOKEN}/dashboards"
    status, data, log_id = request_json("GET", url, headers={"Authorization": f"Bearer {token}"}, timeout=15)

    if status != 200 or data.get("code") != 0:
        log("ERR", f"获取仪表盘失败 HTTP={status} code={data.get('code')} msg={data.get('msg')} log_id={log_id}")
        return

    items = (data.get("data") or {}).get("items") or []
    log("OK", f"仪表盘数量：{len(items)}（log_id={log_id}）")

    if not items:
        log("WARN", "当前 Base 没有仪表盘，或应用无权限看到仪表盘")
        return

    print("\n===== Dashboards =====")
    for i, it in enumerate(items, 1):
        dashboard_id = it.get("dashboard_id") or it.get("id")
        name = it.get("name") or it.get("title")
        print(f"{i}. {name} | dashboard_id={dashboard_id}")

if __name__ == "__main__":
    main()
