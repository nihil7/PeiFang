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
