"""
程序简介：把飞书接口返回的消息转换为稳定的本地保存结构。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

import json
from typing import Any, Dict, Optional


def parse_body_content(raw: Optional[str]) -> Dict[str, Any]:
    """
    body.content 可能是：
    - JSON 字符串：{"text":"..."} / {"zh_cn": {...}}
    - 简化格式：text:xxxx
    这里尽量解析，失败就只保留 raw。
    """
    if not raw:
        return {"raw": raw, "parsed": None}

    s = str(raw).strip()

    if s.startswith("text:"):
        return {"raw": raw, "parsed": {"text": s[len("text:"):]}}

    try:
        parsed = json.loads(s)
        return {"raw": raw, "parsed": parsed}
    except Exception:
        return {"raw": raw, "parsed": None}

