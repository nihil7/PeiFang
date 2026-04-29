"""
程序简介：启动飞书 WebSocket 机器人，接收实时事件并按配置落盘或回复。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

import logging
from pathlib import Path

from feishu_agent.auth import TokenManager
from feishu_agent.config import load_settings
from feishu_agent.http_client import FeishuHttpClient
from feishu_agent.im_api import FeishuIM
from feishu_agent.storage import StateStore
from feishu_agent.ws_bot import start_ws_bot


def main() -> None:
    settings = load_settings()

    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    http = FeishuHttpClient()
    # ✅ TokenManager 参数名是 client，不是 http
    token_mgr = TokenManager(client=http, app_id=settings.app_id, app_secret=settings.app_secret)

    im = FeishuIM(client=http, token_mgr=token_mgr)

    # ✅ StateStore 需要传 state.json 的完整路径（不是目录）
    state_store = StateStore(Path(settings.data_dir) / "state.json")
    state_store.load()

    start_ws_bot(settings=settings, im=im, state_store=state_store)


if __name__ == "__main__":
    main()

