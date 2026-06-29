from dataclasses import dataclass
from datetime import datetime


@dataclass(slots=True)
class VpnAccess:
    username: str
    access_url: str
    provider: str
    external_subscription_id: str | None = None
    external_config_ids: list[int] | None = None


class BaseVpnProvider:
    async def create_or_extend(self, username: str, expires_at: datetime, traffic_gb: int, devices: int | None = None) -> VpnAccess:
        raise NotImplementedError

    async def get_subscription_link(self, subscription_id: str) -> str:
        raise NotImplementedError

    async def reset_subscription_link(self, subscription_id: str) -> str:
        raise NotImplementedError
