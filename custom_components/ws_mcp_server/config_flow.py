import voluptuous as vol
from typing import Any
import logging
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
        """Handle the initial step."""
        errors: dict[str, str] = {}
        _LOGGER.debug("mcp  LLM APIs available: %s",  llm.async_get_apis(self.hass))
        
        llm_apis = {api.id: api.name for api in llm.async_get_apis(self.hass)}
        #llm_apis = {api.id: api.name for api in await llm.async_get_apis(self.hass)}
        if user_input is not None:
            # 为每个配置创建唯一标识
            title = f"{user_input[CONF_LLM_HASS_API]}"
            
            # 验证配置是否重复
            await self.async_set_unique_id(f"{user_input[CONF_LLM_HASS_API]}_{user_input[CONF_CLIENT_ENDPOINT]}")
            self._abort_if_unique_id_configured()

            if not user_input[CONF_LLM_HASS_API]:
                errors[CONF_LLM_HASS_API] = "llm_api_required"
            else:
                return self.async_create_entry(
                    title=", ".join(
                        llm_apis[api_id] for api_id in user_input[CONF_LLM_HASS_API]
                    ),
                    data=user_input,
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    #vol.Required(CONF_CLIENT_ENDPOINT): TextSelector(),
                    vol.Required(CONF_CLIENT_ENDPOINT): selector.TextSelector(),
                    vol.Optional(
                        CONF_LLM_HASS_API,          # llm_hass_api
                        default=[llm.LLM_API_ASSIST], # assist
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
                    # ---- Music Assistant 直连配置（可选，留空则使用默认值）----
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
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Allow editing the MA connection on an already-loaded entry."""
        entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )
        errors: dict[str, str] = {}
        if user_input is not None:
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

