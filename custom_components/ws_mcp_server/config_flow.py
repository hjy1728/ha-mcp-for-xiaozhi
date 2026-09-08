import voluptuous as vol
from typing import Any
import logging
import httpx
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_LLM_HASS_API
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import llm,selector
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    TextSelector
)

from homeassistant.config_entries import ConfigEntry
from .session import SessionManager

from .const import DOMAIN, MA_BASE_URL, MA_API_TOKEN, MA_DEFAULT_QUEUE_ID, MA_DEFAULT_PLAYER_ID

CONF_CLIENT_ENDPOINT = "client_endpoint"
CONF_MODE = "control_mode"
CONF_MASS_URL = "mass_url"
CONF_MASS_TOKEN = "mass_token"
CONF_MASS_QUEUE_ID = "mass_queue_id"
CONF_MASS_PLAYER_ID = "mass_player_id"
MORE_INFO_URL = "https://www.home-assistant.io/integrations/mcp_server/#configuration"
DEFAULT_NAME = "WebSocket MCP Server"
_LOGGER = logging.getLogger(__name__)



class WsMCPServerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for MCP Server."""
    VERSION = 1
    SUPPORT_MULTIPLE_ENTRIES = True  # 添加这行来支持多实例

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 1: Music Assistant 连接配置 + 连通性测试。"""
        errors: dict[str, str] = {}
        description = None
        if user_input is not None:
            url = (user_input.get(CONF_MASS_URL) or "").strip()
            token = (user_input.get(CONF_MASS_TOKEN) or "").strip()
            if url and token:
                ok, msg = await self._async_test_ma_connection(url, token)
                if ok:
                    self._ma_input = dict(user_input)
                    return await self.async_step_finish()
                # 测试失败：留在当前步并提示失败原因
                description = f"❌ 连通失败：{msg}"
            else:
                # 未同时填写 MA 地址与 Token，跳过测试直接进入下一步
                self._ma_input = dict(user_input)
                return await self.async_step_finish()
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_MASS_URL,
                        default=MA_BASE_URL,
                        description={"suggested_value": MA_BASE_URL},
                    ): selector.TextSelector(),
                    vol.Optional(
                        CONF_MASS_TOKEN,
                        default=MA_API_TOKEN,
                        description={"suggested_value": MA_API_TOKEN},
                    ): selector.TextSelector(),
                    vol.Optional(
                        CONF_MASS_QUEUE_ID,
                        default=MA_DEFAULT_QUEUE_ID,
                        description={"suggested_value": MA_DEFAULT_QUEUE_ID},
                    ): selector.TextSelector(),
                    vol.Optional(
                        CONF_MASS_PLAYER_ID,
                        default=MA_DEFAULT_PLAYER_ID,
                        description={"suggested_value": MA_DEFAULT_PLAYER_ID},
                    ): selector.TextSelector(),
                }
            ),
            description_placeholders={"more_info_url": MORE_INFO_URL},
            description=description,
            errors=errors,
        )

    async def async_step_finish(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Step 2: Home Assistant 接入点 + LLM API（预填 MA 配置）。"""
        errors: dict[str, str] = {}
        ma_input = getattr(self, "_ma_input", {}) or {}
        llm_apis = {api.id: api.name for api in llm.async_get_apis(self.hass)}
        if user_input is not None:
            await self.async_set_unique_id(
                f"{user_input[CONF_LLM_HASS_API]}_{user_input[CONF_CLIENT_ENDPOINT]}"
            )
            self._abort_if_unique_id_configured()

            if not user_input[CONF_LLM_HASS_API]:
                errors[CONF_LLM_HASS_API] = "llm_api_required"
            else:
                merged = {**ma_input, **user_input}
                return self.async_create_entry(
                    title=", ".join(
                        llm_apis[api_id] for api_id in user_input[CONF_LLM_HASS_API]
                    ),
                    data=merged,
                )

        return self.async_show_form(
            step_id="finish",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_CLIENT_ENDPOINT): selector.TextSelector(),
                    vol.Optional(
                        CONF_LLM_HASS_API,
                        default=[llm.LLM_API_ASSIST],
                    ): SelectSelector(
                        SelectSelectorConfig(
                            options=[
                                SelectOptionDict(
                                    label=name,
                                    value=llm_api_id,
                                )
                                for llm_api_id, name in llm_apis.items()
                            ],
                            multiple=True,
                        )
                    ),
                }
            ),
            description_placeholders={"more_info_url": MORE_INFO_URL},
            errors=errors,
        )

    async def _async_test_ma_connection(self, url: str, token: str) -> tuple[bool, str]:
        """测试 Music Assistant 连通性与鉴权，返回 (成功, 提示信息)。"""
        base = url.rstrip("/")
        headers = {"Content-Type": "application/json"}
        if token:
            t = token.strip()
            if not t.lower().startswith("bearer "):
                t = f"Bearer {t}"
            headers["Authorization"] = t
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{base}/api",
                    json={"command": "player_queues/all", "args": {}},
                    headers=headers,
                )
            if resp.status_code in (401, 403):
                return False, "鉴权失败：token 不正确或无权限"
            if resp.status_code >= 500:
                return False, f"MA 服务器内部错误（HTTP {resp.status_code}）"
            resp.raise_for_status()
            return True, "连通成功"
        except httpx.HTTPStatusError:
            return False, "MA 返回错误，请检查地址与参数"
        except httpx.RequestError as err:
            return False, f"无法连接 MA 服务：{err}"
        except Exception as err:  # noqa: BLE001
            return False, f"连接测试异常：{err}"

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow editing the MA connection on an already-loaded entry."""
        entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        errors: dict[str, str] = {}
        description = None
        if user_input is not None:
            url = (user_input.get(CONF_MASS_URL) or "").strip()
            token = (user_input.get(CONF_MASS_TOKEN) or "").strip()
            if url and token:
                ok, msg = await self._async_test_ma_connection(url, token)
                if not ok:
                    description = f"❌ 连通失败：{msg}"
                    cur = {**entry.data, **user_input}
                    return self.async_show_form(
                        step_id="reconfigure",
                        data_schema=vol.Schema(
                            {
                                vol.Optional(
                                    CONF_MASS_URL,
                                    default=cur.get(CONF_MASS_URL, MA_BASE_URL),
                                ): selector.TextSelector(),
                                vol.Optional(
                                    CONF_MASS_TOKEN,
                                    default=cur.get(CONF_MASS_TOKEN, MA_API_TOKEN),
                                ): selector.TextSelector(),
                                vol.Optional(
                                    CONF_MASS_QUEUE_ID,
                                    default=cur.get(CONF_MASS_QUEUE_ID, MA_DEFAULT_QUEUE_ID),
                                ): selector.TextSelector(),
                                vol.Optional(
                                    CONF_MASS_PLAYER_ID,
                                    default=cur.get(CONF_MASS_PLAYER_ID, MA_DEFAULT_PLAYER_ID),
                                ): selector.TextSelector(),
                            }
                        ),
                        description=description,
                        errors=errors,
                    )
            new_data = {**entry.data, **user_input}
            return self.async_update_reload_and_abort(
                entry, data=new_data, reload_even_if_entry_is_unchanged=False
            )

        cur = entry.data
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        CONF_MASS_URL,
                        default=cur.get(CONF_MASS_URL, MA_BASE_URL),
                    ): selector.TextSelector(),
                    vol.Optional(
                        CONF_MASS_TOKEN,
                        default=cur.get(CONF_MASS_TOKEN, MA_API_TOKEN),
                    ): selector.TextSelector(),
                    vol.Optional(
                        CONF_MASS_QUEUE_ID,
                        default=cur.get(CONF_MASS_QUEUE_ID, MA_DEFAULT_QUEUE_ID),
                    ): selector.TextSelector(),
                    vol.Optional(
                        CONF_MASS_PLAYER_ID,
                        default=cur.get(CONF_MASS_PLAYER_ID, MA_DEFAULT_PLAYER_ID),
                    ): selector.TextSelector(),
                }
            ),
            errors=errors,
        )

