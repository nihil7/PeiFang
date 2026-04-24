import logging
import time
from dataclasses import dataclass
from typing import Optional

from .http_client import FeishuHttpClient


logger = logging.getLogger("feishu.auth")


@dataclass
class Token:
    value: str
    expire_at: float  # epoch seconds


class TokenManager:
    """
    tenant_access_token（自建应用）
    POST /auth/v3/tenant_access_token/internal
    """
    def __init__(self, client: FeishuHttpClient, app_id: str, app_secret: str):
        self.client = client
        self.app_id = app_id
        self.app_secret = app_secret
        self._token: Optional[Token] = None

    def get(self) -> str:
        now = time.time()
        if self._token and (self._token.expire_at - now) > 60:
            return self._token.value

        payload = {"app_id": self.app_id, "app_secret": self.app_secret}
        data = self.client.request("POST", "/auth/v3/tenant_access_token/internal", json_body=payload)

        if data.get("code") != 0:
            raise RuntimeError(f"获取 tenant_access_token 失败：code={data.get('code')} msg={data.get('msg')}")

        token = data.get("tenant_access_token")
        expire = int(data.get("expire", 0))
        if not token or expire <= 0:
            raise RuntimeError(f"获取 tenant_access_token 返回异常：{data}")

        self._token = Token(value=token, expire_at=now + expire)
        logger.info("tenant_access_token 已刷新（有效期 %ss）", expire)
        return token
