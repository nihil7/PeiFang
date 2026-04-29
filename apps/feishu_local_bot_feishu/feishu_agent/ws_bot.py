"""
程序简介：处理飞书 WebSocket 事件、消息解析和可选自动回复。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

import json
import logging
from pathlib import Path
from typing import Optional

from .config import Settings
from .im_api import FeishuIM
from .service import sync_chat_history
from .storage import JsonlWriter, StateStore

logger = logging.getLogger("feishu.ws")


def _safe_text_from_content(content: dict) -> str:
    # content 可能是 {"text": "..."} 或更复杂结构
    if not isinstance(content, dict):
        return str(content)
    if "text" in content and isinstance(content["text"], str):
        return content["text"]
    # 尽量把内容压成一行字符串
    try:
        return json.dumps(content, ensure_ascii=False)
    except Exception:
        return str(content)


def start_ws_bot(
    *,
    settings: Settings,
    im: FeishuIM,
    state_store: StateStore,
) -> None:
    """
    使用官方 SDK 的长连接（WebSocket）接收事件：
    - 订阅“接收消息 v2.0”（im.message.receive_v1）后，可以实时收到消息事件
    - 你关机/程序退出期间不会收到事件；所以本函数可选：启动前补拉一次历史增量
    """
    try:
        import lark_oapi as lark  # pip install lark-oapi
    except Exception as e:  # pragma: no cover
        raise RuntimeError("缺少依赖 lark-oapi，请先 pip install -r requirements.txt") from e

    # 事件落地：data/events/p2_im_message_receive_v1.jsonl
    writer: Optional[JsonlWriter] = None
    if settings.ws_dump_events:
        data_dir = Path(settings.data_dir)
        evt_dir = data_dir / "events"
        writer = JsonlWriter(evt_dir / "p2_im_message_receive_v1.jsonl")

    # 启动前补拉：避免“你离线期间的 @机器人 消息”丢失
    if settings.ws_sync_on_start and settings.target_chat_ids:
        for chat_id in settings.target_chat_ids:
            try:
                res = sync_chat_history(chat_id=chat_id, settings=settings, im=im, state_store=state_store, full=False)
                logger.info(
                    "pre-sync ok: chat=%s saved=%s last_time=%s",
                    chat_id,
                    res.saved,
                    res.last_synced_time,
                )
            except Exception:
                logger.exception("pre-sync failed: chat=%s", chat_id)

    def do_p2_im_message_receive_v1(data):  # noqa: ANN001
        """
        回调：接收消息事件
        data 类型：lark.im.v1.P2ImMessageReceiveV1（SDK 对象）
        """
        try:
            payload = json.loads(lark.JSON.marshal(data))
            norm = FeishuIM.normalize_event(payload)

            if writer is not None:
                writer.append(norm)

            if settings.ws_auto_reply:
                msg_id = norm.get("message_id")
                if msg_id:
                    text = _safe_text_from_content(norm.get("content") or {})
                    reply = (settings.ws_reply_prefix + text).strip()
                    if len(reply) > settings.ws_reply_max_chars:
                        reply = reply[: settings.ws_reply_max_chars]
                    resp = im.reply_text(msg_id, reply)
                    if resp.get("code") != 0:
                        logger.warning("reply failed: code=%s msg=%s", resp.get("code"), resp.get("msg"))
        except Exception:
            logger.exception("handle ws event failed")

    handler = (
        lark.EventDispatcherHandler.builder("", "")
        .register_p2_im_message_receive_v1(do_p2_im_message_receive_v1)
        .build()
    )

    # 这里不需要你自己搭公网回调；只要程序在本地跑着，连接就会维持
    client = lark.ws.Client(settings.app_id, settings.app_secret, event_handler=handler)
    logger.info("ws client starting...")
    client.start()
