"""Constants for the Model Context Protocol Server integration."""

DOMAIN = "ws_mcp_server"
TITLE = "WebSocket Model Context Protocol Server"
# The Stateless API is no longer registered explicitly, but this name may still exist in the
# users config entry.
STATELESS_LLM_API = "stateless_assist"

# ---------------------------------------------------------------------------
# Music Assistant (MA) 直连配置默认值
# 这些值可在集成配置（config flow）中手动修改，存储于 config entry 的
# mass_url / mass_token / mass_queue_id / mass_player_id 字段。
#
# ⚠️ 安全提示：这里不要填写任何真实 token / 内网地址 / 实体 ID。
# 默认值留空，由用户在集成配置界面中填写自己的 MA 地址与 token。
# （之前版本曾把真实 token 硬编码在此处，已移除，请务必在 Music Assistant
#   中轮换/撤销该 long-lived token。）
# ---------------------------------------------------------------------------
MA_BASE_URL = ""          # 在集成配置中填写，例如 http://192.168.x.x:8095
MA_API_TOKEN = ""         # 在集成配置中填写（Music Assistant 设置里的 long-lived token）
MA_DEFAULT_QUEUE_ID = ""  # 留空将自动发现；也可在集成配置中填写
MA_DEFAULT_PLAYER_ID = "" # 留空将自动发现；也可在集成配置中填写

