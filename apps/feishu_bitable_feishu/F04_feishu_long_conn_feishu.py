"""
程序简介：运行飞书长连接实验，用于验证实时消息或事件接入链路。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

import requests
import json
import time
import threading
from dotenv import load_dotenv
import os

# -------------------------- 从.env读取配置 --------------------------
load_dotenv()
APP_ID = os.getenv("FEISHU_APP_ID")
APP_SECRET = os.getenv("FEISHU_APP_SECRET")

if not APP_ID or not APP_SECRET:
    raise ValueError("❌ .env文件中FEISHU_APP_ID或FEISHU_APP_SECRET未配置！")
# ------------------------------------------------------------------------

# 飞书官方接口域名
FEISHU_API_DOMAIN = "https://open.feishu.cn"


# 1. 获取app_access_token（飞书鉴权核心）
def get_app_access_token():
    url = f"{FEISHU_API_DOMAIN}/open-apis/auth/v3/app_access_token/internal"
    data = {
        "app_id": APP_ID,
        "app_secret": APP_SECRET
    }
    try:
        resp = requests.post(url, json=data, timeout=10)
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") == 0:
            return result["app_access_token"], result["expire"]
        else:
            print(f"❌ 获取token失败：{result}")
            return None, 0
    except Exception as e:
        print(f"❌ 获取token异常：{e}")
        return None, 0


# 2. 解析@消息事件
def parse_at_message(event_data):
    """解析飞书推送的@消息事件，提取关键信息"""
    try:
        # 事件核心数据
        event = event_data.get("event", {})
        msg = event.get("message", {})
        sender = event.get("sender", {})

        # 仅处理群文本@消息
        if msg.get("message_type") == "text" and msg.get("chat_type") == "group":
            # 解析消息内容（JSON字符串转字典）
            content = json.loads(msg.get("content", "{}"))
            text = content.get("text", "")

            # 提取关键信息
            msg_info = {
                "发送人昵称": sender.get("sender_name", "未知"),
                "发送人OpenID": sender.get("sender_id", {}).get("open_id", "未知"),
                "群ID": msg.get("chat_id", "未知"),
                "消息内容": text,
                "消息ID": msg.get("message_id", "未知"),
                "发送时间": event.get("create_time", "未知")
            }

            print("=" * 50)
            print("✅ 收到群@消息：")
            for k, v in msg_info.items():
                print(f"  {k}：{v}")
            print("=" * 50)
    except Exception as e:
        print(f"❌ 解析消息失败：{e}")


# 3. 启动长连接监听消息（适配最新接口）
def start_long_polling():
    """手动实现飞书长连接，轮询获取消息事件"""
    token, expire = get_app_access_token()
    if not token:
        print("❌ 鉴权失败，无法启动长连接")
        return

    # token过期时间（提前300秒刷新）
    token_expire_time = time.time() + expire - 300
    # 修正：飞书最新长连接接口路径
    url = f"{FEISHU_API_DOMAIN}/open-apis/event/v1/longpoll"

    print("✅ 飞书长连接已启动，等待接收@消息...")
    print("🔍 群内@机器人即可触发消息推送（按Ctrl+C停止）")

    while True:
        # 检查token是否过期，过期则刷新
        if time.time() > token_expire_time:
            print("🔄 token即将过期，刷新中...")
            new_token, new_expire = get_app_access_token()
            if new_token:
                token = new_token
                token_expire_time = time.time() + new_expire - 300
            else:
                print("❌ token刷新失败，重试中...")
                time.sleep(5)
                continue

        # 长轮询请求（飞书官方推荐timeout=30秒）
        try:
            # 修正：最新接口的参数格式（用JSON POST请求，而非GET）
            data = {
                "token": token,
                "timeout": 30  # 长轮询超时时间，单位秒
            }
            resp = requests.post(url, json=data, timeout=35)
            resp.raise_for_status()
            result = resp.json()

            # 处理推送的事件
            if result.get("code") == 0:
                events = result.get("data", {}).get("events", [])
                for event in events:
                    # 仅处理@消息事件
                    if event.get("type") == "im.message.receive_v1":
                        parse_at_message(event)
            else:
                print(f"❌ 长轮询返回错误：{result}")

        except requests.exceptions.ReadTimeout:
            # 长轮询超时是正常现象，继续轮询即可
            continue
        except Exception as e:
            print(f"❌ 长轮询异常：{e}")
            print(f"🔍 异常详情：{resp.text if 'resp' in locals() else '无响应'}")
            time.sleep(5)  # 异常时休眠5秒重试


if __name__ == "__main__":
    print(f"🔍 已从.env加载App ID：{APP_ID[:6]}****（已脱敏）")

    # 线程启动长连接
    conn_thread = threading.Thread(target=start_long_polling)
    conn_thread.daemon = True
    conn_thread.start()

    # 保持主程序运行
    try:
        while True:
            input("")
    except KeyboardInterrupt:
        print("\n❌ 飞书长连接已停止")