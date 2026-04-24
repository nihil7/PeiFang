import os
from pathlib import Path

import requests
from dotenv import load_dotenv

# ===== 写死你的测试数据（只改这里）=====
BASE = "https://open.feishu.cn/open-apis"
MESSAGE_ID = "om_x100b58e9f539d8acb2623f55f111e88"
FILE_KEY = "img_v3_02uf_962835a3-166d-469f-9336-4d496ec99f8g"  # 你消息里的 image_key
OUT_DIR = r".\data\images"
# =====================================


def guess_ext(content_type: str) -> str:
    ct = (content_type or "").lower()
    if "png" in ct:
        return ".png"
    if "jpeg" in ct or "jpg" in ct:
        return ".jpg"
    if "gif" in ct:
        return ".gif"
    if "webp" in ct:
        return ".webp"
    return ".bin"


def get_tenant_token(app_id: str, app_secret: str) -> str:
    url = f"{BASE}/auth/v3/tenant_access_token/internal"
    r = requests.post(url, json={"app_id": app_id, "app_secret": app_secret}, timeout=20)
    r.raise_for_status()
    j = r.json()
    if j.get("code") != 0:
        raise RuntimeError(f"token error: code={j.get('code')} msg={j.get('msg')}")
    return j["tenant_access_token"]


def main():
    load_dotenv()
    app_id = os.getenv("FEISHU_APP_ID", "").strip()
    app_secret = os.getenv("FEISHU_APP_SECRET", "").strip()
    if not app_id or not app_secret:
        raise SystemExit("Missing FEISHU_APP_ID / FEISHU_APP_SECRET in .env")

    token = get_tenant_token(app_id, app_secret)
    headers = {"Authorization": f"Bearer {token}"}

    out_dir = Path(OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)

    # ✅ 直接用“获取消息中的资源文件”接口下载图片
    url = f"{BASE}/im/v1/messages/{MESSAGE_ID}/resources/{FILE_KEY}"
    r = requests.get(url, headers=headers, params={"type": "image"}, timeout=60)

    if r.status_code == 200:
        ext = guess_ext(r.headers.get("Content-Type", ""))
        path = out_dir / f"{FILE_KEY}{ext}"
        path.write_bytes(r.content)
        print(f"[OK] saved -> {path}")
        return

    # 尽量解析出 code/msg
    code = None
    msg = None
    try:
        j = r.json()
        code = j.get("code")
        msg = j.get("msg")
    except Exception:
        pass

    print(f"[FAIL] http={r.status_code} code={code} msg={msg}")
    print(f"       url={url}?type=image")


if __name__ == "__main__":
    main()
