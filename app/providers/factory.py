from ..config import get_settings
from .base import BaseVpnProvider
from .demo import DemoProvider
from .stealthsurf import StealthSurfProvider


def get_vpn_provider() -> BaseVpnProvider:
    provider = get_settings().vpn_provider.lower().replace("-", "").replace("_", "")
    if provider in {"stealthsurf", "stealsurf", "stealth"}:
        return StealthSurfProvider()
    return DemoProvider()
