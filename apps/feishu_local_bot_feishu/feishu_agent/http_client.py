import json
import logging
import random
import time
from typing import Any, Dict, Optional

import requests


logger = logging.getLogger("feishu.http")


class FeishuHttpError(RuntimeError):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


class FeishuHttpClient:
    """
    轻量 HTTP 客户端：带少量重试与 backoff
    """
    def __init__(self, base_url: str = "https://open.feishu.cn/open-apis", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()

    def request(
        self,
        method: str,
        path: str,
        headers: Optional[Dict[str, str]] = None,
        params: Optional[Dict[str, Any]] = None,
        json_body: Optional[Dict[str, Any]] = None,
        max_retries: int = 5,
    ) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        headers = headers or {}
        params = params or {}

        for attempt in range(1, max_retries + 1):
            try:
                resp = self.session.request(
                    method=method.upper(),
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_body,
                    timeout=self.timeout,
                )

                if resp.status_code in (429, 500, 502, 503, 504):
                    raise FeishuHttpError(resp.status_code, f"HTTP {resp.status_code} 可重试错误")

                data = resp.json()
                return data

            except (requests.RequestException, json.JSONDecodeError, FeishuHttpError) as e:
                if attempt >= max_retries:
                    raise RuntimeError(f"请求失败（{method} {path}），最后错误：{e}") from e

                sleep_s = min(10.0, 0.6 * (2 ** (attempt - 1))) + random.random() * 0.3
                logger.warning("请求异常，将重试 %s/%s，sleep=%.2fs，错误=%s", attempt, max_retries, sleep_s, e)
                time.sleep(sleep_s)

        raise RuntimeError("不应到达这里")
