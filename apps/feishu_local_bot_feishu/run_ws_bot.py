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
