import argparse
import json
from pathlib import Path

from feishu_agent.config import load_settings
from feishu_agent.utils import setup_logging
from feishu_agent.http_client import FeishuHttpClient
from feishu_agent.auth import TokenManager
from feishu_agent.im_api import FeishuIM


def main():
    ap = argparse.ArgumentParser(description="列出机器人所在群（chat_id）并保存到 data/chats.json")
    args = ap.parse_args()

    settings = load_settings()
    setup_logging(settings.log_level)

    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    client = FeishuHttpClient()
    token_mgr = TokenManager(client, settings.app_id, settings.app_secret)
    im = FeishuIM(client, token_mgr)

    items_all = []
    page_token = None
    page_size = min(settings.page_size, 50)

    while True:
        resp = im.list_chats(page_size=page_size, page_token=page_token)

        if resp.get("code") != 0:
            raise RuntimeError(f"拉取群列表失败：code={resp.get('code')} msg={resp.get('msg')}")

        data = resp.get("data") or {}
        items = data.get("items") or []
        items_all.extend(items)

        page_token = data.get("page_token")
        if not data.get("has_more"):
            break

    out_path = data_dir / "chats.json"
    out_path.write_text(json.dumps(items_all, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"共获取 {len(items_all)} 个群，已保存：{out_path}")
    for x in items_all[:20]:
        print(f"- {x.get('name')} | {x.get('chat_id')}")


if __name__ == "__main__":
    main()
