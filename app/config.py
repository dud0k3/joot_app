from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


_EMPTY_VALUES = {"", "-", "none", "null", "replace_me", "your_token", "значение переменной"}


def clean_optional(value: str | None) -> str:
    value = (value or "").strip()
    if value.lower() in _EMPTY_VALUES:
        return ""
    return value


class Settings(BaseSettings):
    # Telegram / app
    bot_token: str = ""
    admin_ids: str = ""
    app_url: str = "http://localhost:8000"
    bot_mode: str = "polling"  # polling | off
    dev_mode: bool = False
    public_error_details: bool = False
    build_version: str = "joot-clean-production-2026-06-29-v7-joot8-ui-clean"
    support_username: str = ""
    telegram_initdata_max_age_seconds: int = 86400

    # Database
    database_url: str = "sqlite:////data/joot.db"

    # Provider
    vpn_provider: str = "stealthsurf"  # stealthsurf | demo

    # StealthSurf
    stealthsurf_api_base: str = "https://api.stealthsurf.net"
    stealthsurf_api_token: str = ""
    stealthsurf_cloud_server_id: int = 0
    stealthsurf_verify_ssl: bool = True
    stealthsurf_request_retries: int = 4
    stealthsurf_available_items_retries: int = 12

    # JOOT bundle creates 8 items in every StealthSurf custom subscription:
    # 7 regular configs + 1 Auto config. Set STEALTHSURF_USE_JOOT_BUNDLE=false
    # only if you want to fall back to STEALTHSURF_PROTOCOLS manually.
    stealthsurf_use_joot_bundle: bool = True
    stealthsurf_expected_config_count: int = 8
    stealthsurf_protocols: str = "vless,trojan,hysteria2,shadowsocks-2022"
    stealthsurf_device_limit: int = 3
    stealthsurf_subscription_title_prefix: str = "JOOT"
    stealthsurf_config_title_prefix: str = "JOOT"
    stealthsurf_use_custom_subscriptions: bool = True

    # StealthSurf subscription link mode
    # Use the normal console link like https://connect.stealthsurf.net/to/<token>.
    # Encrypted happ:// links are intentionally not used as subscription URLs.
    stealthsurf_subscription_public_base: str = "https://connect.stealthsurf.net/to"
    stealthsurf_allow_encrypted_link_fallback: bool = False

    # Xray extended options. Code applies them only to compatible protocols.
    stealthsurf_use_extended_settings: bool = True
    stealthsurf_block_bittorrent: bool = True
    stealthsurf_use_grpc: bool = True
    stealthsurf_grpc_multi_mode: bool = True
    stealthsurf_use_xhttp: bool = False
    stealthsurf_use_warp: bool = False
    stealthsurf_randomize_fingerprint: bool = True
    stealthsurf_pass_all_traffic_through_vpn: bool = False
    stealthsurf_enable_family_filter: bool = False
    stealthsurf_disable_reality: bool = False
    stealthsurf_disable_flow_reality: bool = False

    # Default subscription in JOOT DB
    default_subscription_days: int = 30
    default_subscription_traffic_gb: int = 0
    default_subscription_devices: int = 3

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def admins(self) -> set[int]:
        result: set[int] = set()
        for item in self.admin_ids.replace(";", ",").split(","):
            item = item.strip()
            if item.isdigit():
                result.add(int(item))
        return result

    @property
    def support_contact(self) -> str:
        return clean_optional(self.support_username).lstrip("@")

    @property
    def stealthsurf_protocol_list(self) -> list[str]:
        aliases = {
            "ss2022": "shadowsocks-2022",
            "shadowsocks2022": "shadowsocks-2022",
            "shadowocks-2022": "shadowsocks-2022",
            "hysteria": "hysteria2",
        }
        result: list[str] = []
        for item in self.stealthsurf_protocols.replace(";", ",").split(","):
            protocol = clean_optional(item).lower().strip()
            if not protocol:
                continue
            protocol = aliases.get(protocol, protocol)
            if protocol not in result:
                result.append(protocol)
        return result or ["vless"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
