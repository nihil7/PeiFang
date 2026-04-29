"""
程序简介：封装飞书群聊、消息列表、图片等 IM 开放接口调用。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

import json
import logging
from typing import Any, Dict, Optional

from .auth import TokenManager
from .http_client import FeishuHttpClient
from .normalize import parse_body_content
from .utils import safe_int


logger = logging.getLogger("feishu.im")


class FeishuIM:
    def __init__(self, client: FeishuHttpClient, token_mgr: TokenManager):
        self.client = client
        self.token_mgr = token_mgr

    def _auth_headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token_mgr.get()}"}

    # --------------------
    # 群 / 消息查询
    # --------------------
    def list_chats(self, page_size: int = 50, page_token: Optional[str] = None) -> Dict[str, Any]:
        params: Dict[str, Any] = {"page_size": page_size}
        if page_token:
            params["page_token"] = page_token
        return self.client.request("GET", "/im/v1/chats", headers=self._auth_headers(), params=params)

    def list_messages(
        self,
        chat_id: str,
        start_time: Optional[int] = None,  # unix seconds
        end_time: Optional[int] = None,  # unix seconds
        page_size: int = 50,
        page_token: Optional[str] = None,
        sort_type: str = "ByCreateTimeAsc",
    ) -> Dict[str, Any]:
        params: Dict[str, Any] = {
            "container_id_type": "chat",
            "container_id": chat_id,
            "page_size": page_size,
            "sort_type": sort_type,
        }
        if start_time is not None:
            params["start_time"] = start_time
        if end_time is not None:
            params["end_time"] = end_time
        if page_token:
            params["page_token"] = page_token

        return self.client.request("GET", "/im/v1/messages", headers=self._auth_headers(), params=params)

    # --------------------
    # 发送 / 回复
    # --------------------
    def send_text_to_chat(self, chat_id: str, text: str) -> Dict[str, Any]:
        """
        给群（chat_id）发送一条文本消息。
        参考：发送消息 POST /im/v1/messages（receive_id_type=chat_id）
        """
        params = {"receive_id_type": "chat_id"}
        body = {
            "receive_id": chat_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        return self.client.request("POST", "/im/v1/messages", headers=self._auth_headers(), params=params, json=body)

    def reply_text(self, message_id: str, text: str) -> Dict[str, Any]:
        """
        回复指定消息（更适合“群里 @机器人”的场景）。
        参考：回复消息 POST /im/v1/messages/{message_id}/reply
        """
        body = {
            "msg_type": "text",
            "content": json.dumps({"text": text}, ensure_ascii=False),
        }
        path = f"/im/v1/messages/{message_id}/reply"
        return self.client.request("POST", path, headers=self._auth_headers(), json=body)

    # --------------------
    # 归一化（历史拉取 / 事件）
    # --------------------
    @staticmethod
    def normalize_message(item: Dict[str, Any]) -> Dict[str, Any]:
        """将 messages 接口返回的 item 归一化，便于落地 JSONL。"""
        body = item.get("body") or {}
        content_raw = body.get("content")
        content_norm = parse_body_content(content_raw)

        create_time_ms = safe_int(item.get("create_time"), 0)
        update_time_ms = safe_int(item.get("update_time"), 0)

        return {
            "message_id": item.get("message_id"),
            "chat_id": item.get("chat_id"),
            "chat_type": item.get("chat_type"),
            "msg_type": item.get("msg_type") or item.get("message_type"),
            "create_time_ms": create_time_ms,
            "create_time_s": int(create_time_ms / 1000) if create_time_ms else 0,
            "update_time_ms": update_time_ms,
            "deleted": bool(item.get("deleted")),
            "updated": bool(item.get("updated")),
            "sender": item.get("sender"),
            "mentions": item.get("mentions") or [],
            "content": content_norm,
            "raw": item,
        }

    @staticmethod
    def normalize_event(event_payload: Dict[str, Any]) -> Dict[str, Any]:
        """将接收消息事件（im.message.receive_v1）的 event 结构归一化，便于落地 JSONL。"""
        evt = (event_payload.get("event") or event_payload.get("data", {}).get("event") or {})
        msg = evt.get("message") or {}
        sender = evt.get("sender") or {}

        content_norm = parse_body_content(msg.get("content"))

        create_time_ms = safe_int(msg.get("create_time"), 0)

        return {
            "message_id": msg.get("message_id"),
            "chat_id": msg.get("chat_id"),
            "chat_type": msg.get("chat_type"),
            "msg_type": msg.get("message_type"),
            "create_time_ms": create_time_ms,
            "create_time_s": int(create_time_ms / 1000) if create_time_ms else 0,
            "deleted": False,
            "updated": False,
            "sender": sender,
            "mentions": msg.get("mentions") or [],
            "content": content_norm,
            "raw": event_payload,
        }
