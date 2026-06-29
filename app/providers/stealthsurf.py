import asyncio
import json
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime

import httpx

from ..config import get_settings
from .base import BaseVpnProvider, VpnAccess

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigSpec:
    title: str
    protocol: str
    role: str = "regular"
    use_grpc: bool | None = None
    use_xhttp: bool | None = None
    disable_flow_reality: bool | None = None
    use_loopbacks: bool = False


JOOT_BUNDLE_CONFIGS: tuple[ConfigSpec, ...] = (
    # 1 Auto + 7 regular configs. Names are intentionally short and clean in Happ/Hiddify.
    ConfigSpec("JOOT Auto", "vless", role="auto", use_grpc=True, use_loopbacks=True),
    ConfigSpec("JOOT VLESS", "vless", use_grpc=True),
    ConfigSpec("JOOT VLESS Backup", "vless", use_grpc=False),
    ConfigSpec("JOOT Trojan", "trojan"),
    ConfigSpec("JOOT Trojan Backup", "trojan"),
    ConfigSpec("JOOT Hysteria", "hysteria2"),
    ConfigSpec("JOOT Shadowsocks", "shadowsocks-2022"),
    ConfigSpec("JOOT Direct", "vless", use_grpc=False, disable_flow_reality=True),
)


class StealthSurfApiError(RuntimeError):
    def __init__(self, action: str, status_code: int, message: str, error_code: int | None = None, payload: dict | None = None) -> None:
        self.action = action
        self.status_code = status_code
        self.error_code = error_code
        self.payload = payload or {}
        suffix = f" errorCode={error_code}" if error_code is not None else ""
        super().__init__(f"StealthSurf {status_code} during {action}{suffix}: {message}")


class StealthSurfProvider(BaseVpnProvider):
    """Production StealthSurf provider.

    Flow:
    1. check private cloud server;
    2. create configs on cloud server;
    3. resolve available custom-subscription items;
    4. create custom subscription with non-empty items;
    5. set device limit and display settings;
    6. return the normal console subscription URL, for example:
       https://connect.stealthsurf.net/to/<token>

    Important: encrypted happ:// links are not subscription URLs for manual import.
    Telegram/Happ users need the public connect.stealthsurf.net link.
    """

    def __init__(self) -> None:
        self.settings = get_settings()
        self.base = self.settings.stealthsurf_api_base.rstrip("/") or "https://api.stealthsurf.net"
        self.server_id = int(self.settings.stealthsurf_cloud_server_id or 0)

    def _require_config(self) -> None:
        if not self.settings.stealthsurf_api_token:
            raise RuntimeError("STEALTHSURF_API_TOKEN is not configured")
        if not self.server_id:
            raise RuntimeError("STEALTHSURF_CLOUD_SERVER_ID is not configured")

    def _client(self) -> httpx.AsyncClient:
        client = httpx.AsyncClient(
            base_url=self.base,
            timeout=45,
            verify=self.settings.stealthsurf_verify_ssl,
            follow_redirects=True,
        )
        client.headers.update({
            "Authorization": f"Bearer {self.settings.stealthsurf_api_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        })
        return client

    @staticmethod
    def _short_username(username: str) -> str:
        value = username.removeprefix("tg_") if username.startswith("tg_") else username
        value = "".join(ch for ch in value if ch.isalnum())
        return value[:18] or secrets.token_hex(4)

    @staticmethod
    def _extract_error(payload: object, fallback: str) -> tuple[str, int | None]:
        if isinstance(payload, dict):
            raw_code = payload.get("errorCode")
            error_code = int(raw_code) if str(raw_code).isdigit() else None
            message = str(payload.get("message") or payload.get("error") or fallback)
            return message, error_code
        return fallback, None

    async def _request(
        self,
        client: httpx.AsyncClient,
        method: str,
        path: str,
        *,
        json_payload: dict | None = None,
        action: str = "request",
        retries: int | None = None,
    ):
        retries = int(retries if retries is not None else self.settings.stealthsurf_request_retries)
        retries = max(1, min(retries, 8))
        last_error: Exception | None = None

        for attempt in range(1, retries + 1):
            response = await client.request(method, path, json=json_payload)
            text = response.text.strip()
            try:
                payload = response.json() if text else {}
            except json.JSONDecodeError as error:
                raise RuntimeError(f"StealthSurf returned non-json during {action}: {text[:240]}") from error

            failed = response.status_code >= 400 or (isinstance(payload, dict) and payload.get("status") is False)
            if not failed:
                if isinstance(payload, dict) and "data" in payload:
                    return payload["data"]
                return payload

            message, error_code = self._extract_error(payload, response.reason_phrase or "bad request")
            err = StealthSurfApiError(action, response.status_code, message, error_code, payload if isinstance(payload, dict) else {})
            last_error = err

            # 429 = rate limit, 88 = parallel config creation in StealthSurf.
            if attempt < retries and (response.status_code == 429 or error_code == 88):
                await asyncio.sleep(min(1.5 * attempt, 8.0))
                continue
            raise err

        if last_error:
            raise last_error
        raise RuntimeError(f"StealthSurf request failed during {action}")

    async def _ensure_server_online(self, client: httpx.AsyncClient) -> None:
        servers = await self._request(client, "GET", "/cloud-servers", action="list cloud servers")
        if not isinstance(servers, list):
            return
        for server in servers:
            if isinstance(server, dict) and int(server.get("id") or 0) == self.server_id:
                status = str(server.get("status") or "")
                if status != "active":
                    raise RuntimeError(f"StealthSurf server {self.server_id} status is {status or 'unknown'}")
                if server.get("is_online") is False:
                    raise RuntimeError(f"StealthSurf server {self.server_id} is offline")
                return
        raise RuntimeError(f"StealthSurf server {self.server_id} not found for this API key")

    def _config_specs(self) -> list[ConfigSpec]:
        if self.settings.stealthsurf_use_joot_bundle:
            prefix = (self.settings.stealthsurf_config_title_prefix or "JOOT").strip()[:20] or "JOOT"
            result: list[ConfigSpec] = []
            for spec in JOOT_BUNDLE_CONFIGS:
                title = spec.title
                if prefix != "JOOT" and title.startswith("JOOT"):
                    title = title.replace("JOOT", prefix, 1)
                result.append(ConfigSpec(
                    title=title,
                    protocol=spec.protocol,
                    role=spec.role,
                    use_grpc=spec.use_grpc,
                    use_xhttp=spec.use_xhttp,
                    disable_flow_reality=spec.disable_flow_reality,
                    use_loopbacks=spec.use_loopbacks,
                ))
            return result

        specs: list[ConfigSpec] = []
        prefix = (self.settings.stealthsurf_config_title_prefix or "JOOT").strip()[:20] or "JOOT"
        for protocol in self.settings.stealthsurf_protocol_list:
            proto_title = protocol.replace("shadowsocks-2022", "Shadowsocks").replace("hysteria2", "Hysteria")
            specs.append(ConfigSpec(f"{prefix} {proto_title.upper()}", protocol))
        return specs

    @staticmethod
    def _config_title(spec: ConfigSpec) -> str:
        return spec.title[:64]

    def _config_payload(self, spec: ConfigSpec) -> dict:
        protocol = spec.protocol.lower().strip()
        payload: dict = {"protocol": protocol, "title": self._config_title(spec)}

        if spec.use_loopbacks:
            # StealthSurf docs describe use_loopbacks as failover/overflow to the next
            # balancer group. We use it for the Auto config where API accepts it.
            payload["use_loopbacks"] = True

        if protocol in {"vless", "vless-2410"}:
            payload["use_extended_settings"] = bool(self.settings.stealthsurf_use_extended_settings)
            if self.settings.stealthsurf_block_bittorrent:
                payload["block_bittorrent"] = True
            if self.settings.stealthsurf_use_warp:
                payload["use_warp"] = True
            if self.settings.stealthsurf_randomize_fingerprint:
                payload["randomize_fingerprint"] = True
            if self.settings.stealthsurf_pass_all_traffic_through_vpn:
                payload["pass_all_traffic_through_vpn"] = True
            if self.settings.stealthsurf_enable_family_filter:
                payload["enable_family_filter"] = True
            if self.settings.stealthsurf_disable_reality:
                payload["disable_reality"] = True

            use_xhttp = self.settings.stealthsurf_use_xhttp if spec.use_xhttp is None else spec.use_xhttp
            use_grpc = self.settings.stealthsurf_use_grpc if spec.use_grpc is None else spec.use_grpc
            disable_flow = self.settings.stealthsurf_disable_flow_reality if spec.disable_flow_reality is None else spec.disable_flow_reality

            # use_grpc, use_xhttp and disable_flow_reality are mutually incompatible.
            if use_xhttp:
                payload["use_xhttp"] = True
            elif use_grpc and not disable_flow:
                payload["use_grpc"] = True
                if self.settings.stealthsurf_grpc_multi_mode:
                    payload["grpc_multi_mode"] = True
            elif disable_flow:
                payload["disable_flow_reality"] = True
            return payload

        if protocol in {"trojan", "trojan-2901"}:
            if self.settings.stealthsurf_randomize_fingerprint:
                payload["randomize_fingerprint"] = True
            return payload

        return payload

    async def _create_config(self, client: httpx.AsyncClient, username: str, spec: ConfigSpec) -> dict:
        payload = self._config_payload(spec)
        try:
            data = await self._request(
                client,
                "POST",
                f"/cloud-servers/{self.server_id}/configs",
                json_payload=payload,
                action=f"create {spec.title} config",
                retries=max(2, self.settings.stealthsurf_request_retries),
            )
        except StealthSurfApiError:
            # Some cloud-server endpoints may not accept use_loopbacks. Keep the
            # Auto config title, retry once with a conservative VLESS payload.
            if spec.role == "auto" and payload.get("use_loopbacks"):
                payload.pop("use_loopbacks", None)
                data = await self._request(
                    client,
                    "POST",
                    f"/cloud-servers/{self.server_id}/configs",
                    json_payload=payload,
                    action=f"create {spec.title} config without loopbacks",
                    retries=max(2, self.settings.stealthsurf_request_retries),
                )
            else:
                raise
        if not isinstance(data, dict) or not data.get("id"):
            raise RuntimeError(f"StealthSurf returned invalid config response for {spec.title}")
        return data

    async def _available_subscription_configs(self, client: httpx.AsyncClient) -> list[dict]:
        data = await self._request(
            client,
            "GET",
            "/profile/custom-subscriptions/available-items",
            action="list custom subscription available items",
            retries=3,
        )
        if isinstance(data, dict):
            configs = data.get("configs") or data.get("items") or []
            return [item for item in configs if isinstance(item, dict)]
        return []

    def _item_from_available(self, item: dict) -> dict | None:
        source = str(item.get("source") or item.get("item_type") or "")
        if source not in {"user_config", "cloud_server_config"}:
            return None
        if source == "cloud_server_config" and item.get("cloud_server_id") is not None:
            if int(item.get("cloud_server_id") or 0) != self.server_id:
                return None
        raw_id = item.get("id") or item.get("item_reference_id")
        if not str(raw_id).isdigit():
            return None
        return {"item_type": source, "item_reference_id": int(raw_id)}

    async def _resolve_subscription_items(self, client: httpx.AsyncClient, configs: list[dict]) -> list[dict]:
        expected = []
        for config in configs:
            if str(config.get("id", "")).isdigit():
                expected.append({
                    "id": int(config["id"]),
                    "title": str(config.get("title") or ""),
                    "protocol": str(config.get("protocol") or ""),
                })
        if not expected:
            raise RuntimeError("No created StealthSurf configs to add into custom subscription")

        last_available: list[dict] = []
        retries = max(6, min(self.settings.stealthsurf_available_items_retries, 20))
        for attempt in range(1, retries + 1):
            available = await self._available_subscription_configs(client)
            last_available = available
            by_id: dict[int, dict] = {}
            by_title: dict[str, dict] = {}

            for item in available:
                normalized = self._item_from_available(item)
                if not normalized:
                    continue
                raw_id = int(item.get("id") or item.get("item_reference_id") or 0)
                by_id[raw_id] = item
                title = str(item.get("title") or "")
                if title:
                    by_title[title] = item

            resolved: list[dict] = []
            used: set[tuple[str, int]] = set()
            missing = []
            for config in expected:
                item = by_id.get(config["id"]) or by_title.get(config["title"])
                normalized = self._item_from_available(item) if item else None
                if not normalized:
                    missing.append(config)
                    continue
                key = (normalized["item_type"], normalized["item_reference_id"])
                if key not in used:
                    used.add(key)
                    resolved.append(normalized)

            if not missing and len(resolved) == len(expected):
                return resolved
            await asyncio.sleep(min(1.0 + attempt * 0.7, 4.0))

        sample = [
            {"id": i.get("id"), "title": i.get("title"), "source": i.get("source"), "cloud_server_id": i.get("cloud_server_id")}
            for i in last_available[:20]
        ]
        raise RuntimeError(
            "Created configs are not available for custom subscription. "
            f"created={json.dumps(expected, ensure_ascii=False)[:700]}; "
            f"available_sample={json.dumps(sample, ensure_ascii=False)[:900]}"
        )

    async def _create_custom_subscription(self, client: httpx.AsyncClient, username: str, items: list[dict]) -> dict:
        if not items:
            raise RuntimeError("Cannot create StealthSurf subscription without items")
        prefix = (self.settings.stealthsurf_subscription_title_prefix or "JOOT").strip()[:32]
        title = f"{prefix}-{self._short_username(username)}"[:64]
        data = await self._request(
            client,
            "POST",
            "/profile/custom-subscriptions",
            json_payload={"title": title, "items": items},
            action="create custom subscription",
            retries=3,
        )
        if isinstance(data, dict) and data.get("id"):
            return data
        raise RuntimeError("StealthSurf returned invalid custom subscription response")

    async def _set_subscription_items(self, client: httpx.AsyncClient, subscription_id: str | int, items: list[dict]) -> dict:
        data = await self._request(
            client,
            "PUT",
            f"/profile/custom-subscriptions/{subscription_id}/items",
            json_payload={"items": items},
            action="set custom subscription items",
            retries=3,
        )
        return data if isinstance(data, dict) else {}

    async def _get_custom_subscription(self, client: httpx.AsyncClient, subscription_id: str | int) -> dict:
        data = await self._request(client, "GET", f"/profile/custom-subscriptions/{subscription_id}", action="get custom subscription")
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _subscription_items_valid(detail: dict, expected_count: int) -> bool:
        items = detail.get("items") if isinstance(detail, dict) else None
        if not isinstance(items, list) or len(items) < expected_count:
            return False
        return all(item.get("is_valid") is not False for item in items if isinstance(item, dict))

    async def _set_device_limit(self, client: httpx.AsyncClient, subscription_id: str | int, devices: int) -> None:
        devices = max(0, min(int(devices or 0), 100))
        await self._request(
            client,
            "PATCH",
            f"/profile/custom-subscriptions/{subscription_id}/devices/settings",
            json_payload={"block_unknown_devices": False, "device_limit": devices},
            action="set custom subscription device limit",
            retries=3,
        )

    async def _set_display_settings(self, client: httpx.AsyncClient, subscription_id: str | int) -> None:
        app_url = (self.settings.app_url or "").strip().rstrip("/")
        payload: dict = {"profile_title": "JOOT VPN", "profile_update_interval": 12}
        if app_url.startswith("https://"):
            payload["profile_web_page_url"] = app_url
        if self.settings.support_contact:
            payload["support_url"] = f"https://t.me/{self.settings.support_contact}"
        try:
            await self._request(
                client,
                "PATCH",
                f"/profile/custom-subscriptions/{subscription_id}/display/settings",
                json_payload=payload,
                action="set custom subscription display settings",
                retries=2,
            )
        except Exception as error:
            logger.info("StealthSurf display settings skipped: %s", error)

    @staticmethod
    def _iter_payload_strings(payload: object):
        if isinstance(payload, str):
            yield "", payload
            return
        if isinstance(payload, dict):
            for key, value in payload.items():
                if isinstance(value, str):
                    yield str(key), value
                elif isinstance(value, (dict, list, tuple)):
                    yield from StealthSurfProvider._iter_payload_strings(value)
            return
        if isinstance(payload, (list, tuple)):
            for value in payload:
                yield from StealthSurfProvider._iter_payload_strings(value)

    @staticmethod
    def _is_http_url(value: str) -> bool:
        return value.lower().startswith(("https://", "http://"))

    @staticmethod
    def _is_stealthsurf_connect_url(value: str) -> bool:
        lowered = value.lower().strip()
        return lowered.startswith(("https://connect.stealthsurf.net/to/", "http://connect.stealthsurf.net/to/"))

    def _public_link_from_token(self, token: str) -> str | None:
        token = str(token or "").strip().strip("/")
        if not token or token.isdigit() or len(token) < 8:
            return None
        if "://" in token or "/" in token or " " in token:
            return None
        base = (self.settings.stealthsurf_subscription_public_base or "https://connect.stealthsurf.net/to").strip().rstrip("/")
        return f"{base}/{token}"

    def _plain_subscription_link_from_payload(self, payload: object) -> str | None:
        """Extract normal StealthSurf console link from API payload.

        The web console shows links like:
        https://connect.stealthsurf.net/to/<token>

        Do not use encrypted happ://crypt5/... values here: they are deep links,
        not stable subscription URLs for manual import from the bot.
        """
        if isinstance(payload, str):
            value = payload.strip()
            return value if self._is_stealthsurf_connect_url(value) else None

        if not isinstance(payload, dict):
            return None

        preferred_url_keys = {
            "subscription_link", "subscriptionlink", "subscription_url", "subscriptionurl",
            "connect_link", "connectlink", "connect_url", "connecturl",
            "public_link", "publiclink", "public_url", "publicurl",
            "share_link", "sharelink", "share_url", "shareurl",
            "url", "link", "access_url", "accessurl",
        }
        token_keys = {
            "key", "token", "hash", "slug", "secret", "uuid",
            "subscription_key", "subscriptionkey", "subscription_token", "subscriptiontoken",
            "connect_key", "connectkey", "connect_token", "connecttoken",
            "link_key", "linkkey", "url_key", "urlkey",
        }

        # First priority: exact StealthSurf public link anywhere in payload.
        for _, value in self._iter_payload_strings(payload):
            value = value.strip()
            if self._is_stealthsurf_connect_url(value):
                return value

        # Second priority: known URL/link fields with regular http(s) URL.
        for key, value in self._iter_payload_strings(payload):
            normalized_key = key.replace("_", "").replace("-", "").lower()
            value = value.strip()
            if normalized_key in preferred_url_keys and self._is_http_url(value):
                return value

        # Third priority: known token/key fields. Build console URL from token.
        for key, value in self._iter_payload_strings(payload):
            normalized_key = key.replace("_", "").replace("-", "").lower()
            if normalized_key in token_keys:
                link = self._public_link_from_token(value)
                if link:
                    return link

        return None

    async def _encrypted_subscription_link(self, client: httpx.AsyncClient, subscription_id: str | int) -> str | None:
        data = await self._request(
            client,
            "GET",
            f"/profile/custom-subscriptions/{subscription_id}/encrypted-subscription-link",
            action="get encrypted subscription link",
            retries=2,
        )
        if isinstance(data, str) and data.strip():
            return data.strip()
        if isinstance(data, dict):
            for key in ("encrypted_subscription_link", "encryptedSubscriptionLink", "link", "url"):
                value = data.get(key)
                if value:
                    return str(value).strip()
        return None

    async def _subscription_link(self, client: httpx.AsyncClient, subscription_id: str | int) -> str:
        detail = await self._get_custom_subscription(client, subscription_id)
        link = self._plain_subscription_link_from_payload(detail)
        if link:
            return link

        # Some StealthSurf responses include the link only in list endpoint.
        try:
            subscriptions = await self._request(client, "GET", "/profile/custom-subscriptions", action="list custom subscriptions", retries=2)
            if isinstance(subscriptions, list):
                for item in subscriptions:
                    if isinstance(item, dict) and str(item.get("id")) == str(subscription_id):
                        link = self._plain_subscription_link_from_payload(item)
                        if link:
                            return link
            elif isinstance(subscriptions, dict):
                items = subscriptions.get("items") or subscriptions.get("subscriptions") or subscriptions.get("data") or []
                if isinstance(items, list):
                    for item in items:
                        if isinstance(item, dict) and str(item.get("id")) == str(subscription_id):
                            link = self._plain_subscription_link_from_payload(item)
                            if link:
                                return link
                link = self._plain_subscription_link_from_payload(subscriptions)
                if link:
                    return link
        except Exception as error:
            logger.info("StealthSurf custom subscription list link lookup skipped: %s", error)

        if self.settings.stealthsurf_allow_encrypted_link_fallback:
            encrypted = await self._encrypted_subscription_link(client, subscription_id)
            if encrypted:
                return encrypted

        sample = json.dumps(detail, ensure_ascii=False)[:1200] if detail else "empty detail"
        raise RuntimeError(
            "StealthSurf did not return a normal subscription URL. "
            "Expected https://connect.stealthsurf.net/to/<token>. "
            f"subscription_id={subscription_id}; detail_sample={sample}"
        )

    async def _delete_config_silent(self, client: httpx.AsyncClient, config_id: int) -> None:
        try:
            await self._request(client, "DELETE", f"/cloud-servers/{self.server_id}/configs/{config_id}", action=f"delete config {config_id}", retries=2)
        except Exception as error:
            logger.info("StealthSurf config cleanup skipped for %s: %s", config_id, error)

    async def _delete_custom_subscription_silent(self, client: httpx.AsyncClient, subscription_id: str | int | None) -> None:
        if not subscription_id:
            return
        try:
            await self._request(client, "DELETE", f"/profile/custom-subscriptions/{subscription_id}", action="delete custom subscription", retries=2)
        except Exception as error:
            logger.info("StealthSurf subscription cleanup skipped for %s: %s", subscription_id, error)

    @staticmethod
    def _direct_access_url(configs: list[dict]) -> str:
        return "\n".join(str(item.get("connection_url") or "").strip() for item in configs if item.get("connection_url"))

    async def _make_subscription_for_configs(self, client: httpx.AsyncClient, username: str, configs: list[dict], devices: int | None) -> VpnAccess:
        items = await self._resolve_subscription_items(client, configs)
        custom_subscription = await self._create_custom_subscription(client, username, items)
        subscription_id = custom_subscription["id"]

        if not self._subscription_items_valid(custom_subscription, len(items)):
            await asyncio.sleep(0.8)
            custom_subscription = await self._set_subscription_items(client, subscription_id, items)
        if not self._subscription_items_valid(custom_subscription, len(items)):
            await asyncio.sleep(0.8)
            custom_subscription = await self._get_custom_subscription(client, subscription_id)
        if not self._subscription_items_valid(custom_subscription, len(items)):
            raise RuntimeError("StealthSurf custom subscription was created, but items are not valid")

        await asyncio.sleep(0.4)
        await self._set_device_limit(client, subscription_id, int(devices or self.settings.stealthsurf_device_limit or 3))
        await self._set_display_settings(client, subscription_id)
        await asyncio.sleep(0.6)
        link = await self._subscription_link(client, subscription_id)

        return VpnAccess(
            username=username,
            access_url=link,
            provider="stealthsurf",
            external_subscription_id=str(subscription_id),
            external_config_ids=[int(config["id"]) for config in configs if str(config.get("id", "")).isdigit()],
        )

    async def create_or_extend(self, username: str, expires_at: datetime, traffic_gb: int, devices: int | None = None) -> VpnAccess:
        self._require_config()
        async with self._client() as client:
            await self._ensure_server_online(client)
            specs = self._config_specs()
            configs: list[dict] = []
            custom_subscription_id: str | int | None = None
            try:
                for index, spec in enumerate(specs):
                    if index:
                        await asyncio.sleep(1.2)  # StealthSurf: POST /configs is limited to 1 req/sec.
                    configs.append(await self._create_config(client, username, spec))

                if not self.settings.stealthsurf_use_custom_subscriptions:
                    return VpnAccess(
                        username=username,
                        access_url=self._direct_access_url(configs),
                        provider="stealthsurf",
                        external_config_ids=[int(config["id"]) for config in configs if str(config.get("id", "")).isdigit()],
                    )

                vpn = await self._make_subscription_for_configs(client, username, configs, devices)
                custom_subscription_id = vpn.external_subscription_id
                return vpn
            except Exception:
                await self._delete_custom_subscription_silent(client, custom_subscription_id)
                for config in configs:
                    if config.get("id"):
                        await self._delete_config_silent(client, int(config["id"]))
                        await asyncio.sleep(1.05)
                raise

    async def get_subscription_link(self, subscription_id: str) -> str:
        if not subscription_id:
            raise RuntimeError("StealthSurf external_subscription_id is empty")
        self._require_config()
        async with self._client() as client:
            return await self._subscription_link(client, subscription_id)

    async def reset_subscription_link(self, subscription_id: str) -> str:
        if not subscription_id:
            raise RuntimeError("StealthSurf external_subscription_id is empty")
        self._require_config()
        async with self._client() as client:
            await self._request(client, "POST", f"/profile/custom-subscriptions/{subscription_id}/reset-key", action="reset custom subscription key", retries=2)
            await asyncio.sleep(0.8)
            return await self._subscription_link(client, subscription_id)
