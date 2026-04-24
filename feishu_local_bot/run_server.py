import asyncio
from pathlib import Path
from typing import Optional

import uvicorn
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse

from feishu_agent.config import load_settings
from feishu_agent.utils import setup_logging
from feishu_agent.http_client import FeishuHttpClient
from feishu_agent.auth import TokenManager
from feishu_agent.im_api import FeishuIM
from feishu_agent.storage import StateStore
from feishu_agent.service import sync_chat_history, SyncResult


settings = load_settings()
setup_logging(settings.log_level)

data_dir = Path(settings.data_dir)
data_dir.mkdir(parents=True, exist_ok=True)

state_store = StateStore(data_dir / "state.json")
state_store.load()

client = FeishuHttpClient()
token_mgr = TokenManager(client, settings.app_id, settings.app_secret)
im = FeishuIM(client, token_mgr)

app = FastAPI(title="Feishu Local Bot - Stage1")

_lock = asyncio.Lock()


def _default_chat_ids():
    if settings.target_chat_ids:
        return settings.target_chat_ids
    return []


def _result_to_dict(r: SyncResult):
    return {
        "chat_id": r.chat_id,
        "start_time": r.start_time,
        "end_time": r.end_time,
        "fetched": r.fetched,
        "saved": r.saved,
        "last_synced_time": r.last_synced_time,
        "last_synced_message_id": r.last_synced_message_id,
    }


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/chats")
def chats():
    items_all = []
    page_token = None
    page_size = min(settings.page_size, 50)

    while True:
        resp = im.list_chats(page_size=page_size, page_token=page_token)
        if resp.get("code") != 0:
            return JSONResponse(status_code=500, content={"error": resp})

        data = resp.get("data") or {}
        items = data.get("items") or []
        items_all.extend(items)

        page_token = data.get("page_token")
        if not data.get("has_more"):
            break

    # 同时写文件，便于你在本地查看
    out_path = data_dir / "chats.json"
    out_path.write_text(__import__("json").dumps(items_all, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"count": len(items_all), "items": items_all[:200], "saved_to": str(out_path)}


@app.post("/sync")
async def sync(
    chat_id: Optional[str] = Query(default=None),
    full: int = Query(default=0, description="1=从起点重拉（仍追加保存）"),
):
    """
    触发一次同步：
    - chat_id 不传：同步 .env 中 FEISHU_TARGET_CHAT_IDS
    - chat_id 传：只同步该群
    """
    async with _lock:
        targets = [chat_id] if chat_id else _default_chat_ids()
        if not targets:
            return JSONResponse(
                status_code=400,
                content={"error": "未指定 chat_id：请传 ?chat_id= 或在 .env 里设置 FEISHU_TARGET_CHAT_IDS"},
            )

        results = []
        for cid in targets:
            # sync_chat_history 是阻塞 I/O，用线程跑
            r = await asyncio.to_thread(
                sync_chat_history,
                chat_id=cid,
                settings=settings,
                im=im,
                state_store=state_store,
                full=bool(full),
            )
            results.append(_result_to_dict(r))

        return {"ok": True, "results": results}


async def _poll_loop():
    if settings.poll_interval_seconds <= 0:
        return

    while True:
        try:
            async with _lock:
                targets = _default_chat_ids()
                for cid in targets:
                    await asyncio.to_thread(
                        sync_chat_history,
                        chat_id=cid,
                        settings=settings,
                        im=im,
                        state_store=state_store,
                        full=False,
                    )
        except Exception as e:
            # 这里不抛出，避免后台任务退出
            import logging
            logging.getLogger("feishu.server").exception("poll loop error: %s", e)

        await asyncio.sleep(settings.poll_interval_seconds)


@app.on_event("startup")
async def _startup():
    # 启动轮询（如果启用）
    if settings.poll_interval_seconds > 0:
        asyncio.create_task(_poll_loop())


def main():
    uvicorn.run(app, host=settings.server_host, port=settings.server_port, log_level="info")


if __name__ == "__main__":
    main()
