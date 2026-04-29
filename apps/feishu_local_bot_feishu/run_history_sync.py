"""
程序简介：按配置拉取指定飞书群聊历史消息，并保存到本地数据目录。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

import argparse
from pathlib import Path
from typing import List, Optional

from feishu_agent.config import load_settings
from feishu_agent.utils import setup_logging
from feishu_agent.http_client import FeishuHttpClient
from feishu_agent.auth import TokenManager
from feishu_agent.im_api import FeishuIM
from feishu_agent.storage import StateStore
from feishu_agent.service import sync_chat_history


def _pick_chat_ids(cli_chat_id: Optional[str], env_chat_ids: Optional[List[str]]) -> List[str]:
    if cli_chat_id:
        return [cli_chat_id]
    if env_chat_ids:
        return env_chat_ids
    raise RuntimeError("未指定 chat_id：请用 --chat-id 或在 .env 里设置 FEISHU_TARGET_CHAT_IDS")


def main():
    ap = argparse.ArgumentParser(description="拉取指定群历史消息并保存为 JSONL（支持增量）")
    ap.add_argument("--chat-id", default="", help="目标群 chat_id（优先于 .env）")
    ap.add_argument("--full", action="store_true", help="忽略增量状态，从起点时间重新拉取（仍会追加保存）")
    args = ap.parse_args()

    settings = load_settings()
    setup_logging(settings.log_level)

    data_dir = Path(settings.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    state_store = StateStore(data_dir / "state.json")
    state_store.load()

    client = FeishuHttpClient()
    token_mgr = TokenManager(client, settings.app_id, settings.app_secret)
    im = FeishuIM(client, token_mgr)

    chat_ids = _pick_chat_ids(args.chat_id.strip() or None, settings.target_chat_ids)

    for chat_id in chat_ids:
        chat_id = chat_id.strip()
        if not chat_id:
            continue
        r = sync_chat_history(chat_id=chat_id, settings=settings, im=im, state_store=state_store, full=args.full)
        print(f"[{r.chat_id}] fetched={r.fetched} saved={r.saved} last_synced_time={r.last_synced_time}")

    print("Done.")


if __name__ == "__main__":
    main()

