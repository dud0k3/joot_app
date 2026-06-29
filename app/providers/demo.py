import secrets
from datetime import datetime

from .base import BaseVpnProvider, VpnAccess


class DemoProvider(BaseVpnProvider):
    async def create_or_extend(self, username: str, expires_at: datetime, traffic_gb: int, devices: int | None = None) -> VpnAccess:
        token = secrets.token_urlsafe(32)
        return VpnAccess(
            username=username,
            access_url=f"https://demo.joot/sub/{token}#{username}",
            provider="demo",
            external_subscription_id=token,
            external_config_ids=[],
        )

    async def get_subscription_link(self, subscription_id: str) -> str:
        return f"https://demo.joot/sub/{subscription_id}"

    async def reset_subscription_link(self, subscription_id: str) -> str:
        token = secrets.token_urlsafe(32)
        return f"https://demo.joot/sub/{token}"
