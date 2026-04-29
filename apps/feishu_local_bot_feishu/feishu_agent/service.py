"""
程序简介：组织消息拉取、增量状态更新和本地保存流程。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import Settings
from .im_api import FeishuIM
from .storage import JsonlWriter, StateStore, State
from .utils import calc_start_time_from_days

from .assets import enrich_message_with_local_images


@dataclass
class SyncResult:
    chat_id: str
    start_time: int
    end_time: Optional[int]
    fetched: int
    saved: int
    last_synced_time: int
    last_synced_message_id: Optional[str]


def sync_chat_history(
    *,
    chat_id: str,
    settings: Settings,
    im: FeishuIM,
    state_store: StateStore,
    full: bool = False,
) -> SyncResult:
    """
    拉取某个 chat_id 的历史消息，并写入 JSONL。
    - 增量基于 state.json 的 last_synced_time（unix seconds）
    - full=True：忽略增量状态，从起点重新拉取（仍追加保存，不会清空文件）
    """

    data_dir = Path(settings.data_dir)
    msg_dir = data_dir / "messages"
    writer = JsonlWriter(msg_dir / f"{chat_id}.jsonl")

    prev_state = state_store.get_chat_state(chat_id)

    forced_start_time: Optional[int] = None
    if settings.history_start_time is not None:
        forced_start_time = settings.history_start_time
    elif settings.history_start_days is not None:
        forced_start_time = calc_start_time_from_days(settings.history_start_days)

    start_time = forced_start_time if forced_start_time is not None else prev_state.last_synced_time
    if full:
        start_time = forced_start_time if forced_start_time is not None else 0

    end_time = settings.history_end_time or None

    page_token: Optional[str] = None
    has_more = True

    newest_time_s = prev_state.last_synced_time
    newest_msg_id = prev_state.last_synced_message_id

    fetched = 0
    saved = 0

    download_images = bool(getattr(settings, "download_images", False))
    images_skip_existing = bool(getattr(settings, "images_skip_existing", True))

    while has_more:
        resp = im.list_messages(
            chat_id=chat_id,
            start_time=start_time if start_time else None,
            end_time=end_time,
            page_size=settings.page_size,
            page_token=page_token,
            sort_type="ByCreateTimeAsc",
        )

        if resp.get("code") != 0:
            raise RuntimeError(f"[{chat_id}] 拉取消息失败：code={resp.get('code')} msg={resp.get('msg')}")

        data = resp.get("data") or {}
        items = data.get("items") or []
        fetched += len(items)

        for item in items:
            norm = im.normalize_message(item)
            ct_s = int(norm.get("create_time_s") or 0)

            # 增量：过滤掉 <= 上次水位 的消息（你如果想“边界也处理”，可把 <= 改成 <）
            if (not full) and ct_s <= prev_state.last_synced_time:
                continue

            # ✅ 自动下载卡片/富文本里引用的图片（image_key）
            norm = enrich_message_with_local_images(
                norm,
                im,
                data_dir=data_dir,
                enable=download_images,
                skip_existing=images_skip_existing,
            )

            writer.append(norm)
            saved += 1

            if ct_s >= newest_time_s:
                newest_time_s = ct_s
                newest_msg_id = norm.get("message_id")

        has_more = bool(data.get("has_more"))
        page_token = data.get("page_token")

    new_state = State(last_synced_time=newest_time_s, last_synced_message_id=newest_msg_id)
    state_store.set_chat_state(chat_id, new_state)
    state_store.save()

    return SyncResult(
        chat_id=chat_id,
        start_time=start_time,
        end_time=end_time,
        fetched=fetched,
        saved=saved,
        last_synced_time=new_state.last_synced_time,
        last_synced_message_id=new_state.last_synced_message_id,
    )
