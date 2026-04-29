"""
程序简介：列出机器人可见的飞书群聊，帮助确认 chat_id 和同步范围。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

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

