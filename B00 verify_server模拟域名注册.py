# verify_server.py
# 用途：通过企业微信“接收消息服务器URL”的 openapi 回调校验（GET）+ POST 解密并打印明文 XML
# 原理：
# - GET：校验 msg_signature + 解密 echostr + 返回明文
# - POST：解密加密 XML，打印 decrypted_xml，提取常见字段（DocId/SheetId 等）

import os
from flask import Flask, request, make_response
from dotenv import load_dotenv
from wechatpy.enterprise.crypto import WeChatCrypto
from wechatpy.exceptions import InvalidSignatureException
import xml.etree.ElementTree as ET

app = Flask(__name__)

# ====== 配置区：从 .env 读取（你只要改 .env）======
load_dotenv()
CORP_ID = (os.getenv("WECOM_CORP_ID") or "").strip()
TOKEN = (os.getenv("WECOM_CALLBACK_TOKEN") or "").strip()
AES_KEY = (os.getenv("WECOM_CALLBACK_AESKEY") or "").strip()
# ====== 配置区结束 ======

if not (CORP_ID and TOKEN and AES_KEY):
    raise RuntimeError("缺少 .env 配置：WECOM_CORP_ID / WECOM_CALLBACK_TOKEN / WECOM_CALLBACK_AESKEY")

# 注意：用“位置参数”最稳（不同版本关键字参数可能不一致）
crypto = WeChatCrypto(TOKEN, AES_KEY, CORP_ID)


def parse_xml_to_dict(xml_text: str) -> dict:
    """
    把明文 XML 转成 dict，便于快速找字段（DocId/SheetId/Event等）
    """
    result = {}
    try:
        root = ET.fromstring(xml_text)
        for child in list(root):
            # child.text 可能为 None
            result[child.tag] = (child.text or "").strip()
    except Exception:
        # 解析失败就返回空 dict；仍然可以直接看 decrypted_xml 原文
        return {}
    return result


@app.route("/wecom", methods=["GET", "POST"])
def wecom_callback():
    msg_signature = request.args.get("msg_signature", "")
    timestamp = request.args.get("timestamp", "")
    nonce = request.args.get("nonce", "")

    # ===== GET：回调地址校验 =====
    if request.method == "GET":
        echostr = request.args.get("echostr", "")
        try:
            plain = crypto.check_signature(msg_signature, timestamp, nonce, echostr)
            return plain  # 必须返回明文
        except InvalidSignatureException:
            return make_response("invalid signature", 403)
        except Exception as e:
            app.logger.exception("wecom GET verify error")
            return make_response(f"error: {e}", 500)

    # ===== POST：事件/消息推送（加密 XML）=====
    try:
        xml_data = request.data  # bytes
        decrypted_xml = crypto.decrypt_message(xml_data, msg_signature, timestamp, nonce)

        # 1) 直接打印完整明文（最可靠，避免日志截断）
        print("\n========== WECOM decrypted_xml (BEGIN) ==========")
        print(decrypted_xml)
        print("========== WECOM decrypted_xml (END) ==========\n")

        # 2) 解析常见字段，方便你定位 DocId/SheetId
        d = parse_xml_to_dict(decrypted_xml)
        if d:
            keys_of_interest = [
                "ToUserName", "FromUserName", "CreateTime",
                "MsgType", "Event",
                "DocId", "SheetId", "TableId", "FileId",
                "AgentID", "ChangeType", "UserID",
            ]
            picked = {k: d.get(k, "") for k in keys_of_interest if d.get(k, "")}
            if picked:
                print("==== picked fields ====")
                for k, v in picked.items():
                    print(f"{k}: {v}")
                print("=======================\n")

        # 企业微信事件回调通常返回纯文本 "success"
        return "success"

    except InvalidSignatureException:
        return make_response("invalid signature", 403)
    except Exception as e:
        app.logger.exception("wecom POST decrypt error")
        return make_response(f"error: {e}", 500)


if __name__ == "__main__":
    # 本地服务继续开 8000，cloudflared 转发它 cloudflared tunnel --url http://127.0.0.1:8000
    app.run(host="0.0.0.0", port=8000)
