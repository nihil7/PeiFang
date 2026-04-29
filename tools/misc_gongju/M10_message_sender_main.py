"""
程序简介：读取企微 webhook 等配置，向指定群机器人发送本地消息。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

# ====== 配置区（你只要改这里）======
MANUAL_MODE = False  # True=手动消息；False=自动消息（由 fetcher.py 提供）

# 手动消息（可按群不同）
MANUAL_MSG_GROUP1 = "群1测试：PyCharm 一键发送成功 ✅"
MANUAL_MSG_GROUP2 = "群2测试：这是另一条测试消息 ✅"

# 自动模式下：是否在本地打印将要发送的消息（预览用）
PRINT_AUTO_MESSAGE = True

# 调试开关：True=只打印不发送；False=真正发送
DRY_RUN = False
# ====== 配置区结束 ======

import os
import requests
from dotenv import load_dotenv

import fetcher  # 自动模式会用到：fetcher.build_message()


def send_text(webhook_url: str, content: str) -> str | None:
    """
    发送一条文本消息到群机器人 webhook。
    成功返回 None；失败返回错误字符串（用于打印排错）。
    """
    payload = {"msgtype": "text", "text": {"content": content}}
    try:
        r = requests.post(webhook_url, json=payload, timeout=10)
        r.raise_for_status()
        data = r.json()
    except Exception as e:
        return f"HTTP/JSON 异常：{e}"

    if data.get("errcode") != 0:
        return f"企业微信返回失败：errcode={data.get('errcode')}, errmsg={data.get('errmsg')}"
    return None


def main():
    """
    主流程：
    1) 读取 .env 的 webhook
    2) 根据 MANUAL_MODE 选择消息来源（手动/自动）
    3) 逐群发送（或 DRY_RUN 只打印）
    """
    load_dotenv()  # 读取项目根目录 .env

    group1_webhook = (os.getenv("GROUP1_WEBHOOK") or "").strip()
    group2_webhook = (os.getenv("GROUP2_WEBHOOK") or "").strip()
    if not group1_webhook or not group2_webhook:
        raise RuntimeError("缺少 .env 配置：GROUP1_WEBHOOK / GROUP2_WEBHOOK")

    # 目标群列表（这里固定两个群，最简）
    targets = [
        {"name": "群1", "webhook": group1_webhook},
        {"name": "群2", "webhook": group2_webhook},
    ]

    # 选择消息来源
    if MANUAL_MODE:
        # 每个群的消息都在配置区写好，不做运行时输入
        messages = {
            "群1": MANUAL_MSG_GROUP1,
            "群2": MANUAL_MSG_GROUP2,
        }
    else:
        # 自动消息：由 fetcher.py 负责生成/读取，并可在本地打印
        auto_msg = fetcher.build_message()
        if PRINT_AUTO_MESSAGE:
            print(f"[AUTO] 将发送的消息预览：{auto_msg[:200]}{'...' if len(auto_msg) > 200 else ''}")
        messages = {"群1": auto_msg, "群2": auto_msg}

    # 发送
    ok, fail = 0, 0
    for t in targets:
        name = t["name"]
        webhook = t["webhook"]
        msg = (messages.get(name) or "").strip()

        if not msg:
            print(f"[SKIP] {name}：消息为空，跳过")
            continue

        if DRY_RUN:
            print(f"[DRY_RUN] {name} => {msg[:200]}{'...' if len(msg) > 200 else ''}")
            ok += 1
            continue

        err = send_text(webhook, msg)
        if err is None:
            print(f"[OK] {name} 已发送")
            ok += 1
        else:
            print(f"[FAIL] {name}：{err}")
            fail += 1

    print(f"[DONE] 成功 {ok}，失败 {fail}")


if __name__ == "__main__":
    main()

