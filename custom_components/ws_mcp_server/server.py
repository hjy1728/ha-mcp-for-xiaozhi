"""The Model Context Protocol Server implementation.

The Model Context Protocol python sdk defines a Server API that provides the
MCP message handling logic and error handling. The server implementation provided
here is independent of the lower level transport protocol.

See https://modelcontextprotocol.io/docs/concepts/architecture#implementation-example
"""

from collections.abc import Callable, Sequence
import json
import logging
from typing import Any

from mcp import types
from mcp.server import Server
import voluptuous as vol
from voluptuous_openapi import convert

try:
    from voluptuous_openapi import _Unsupported
except ImportError:  # 不同版本可能不导出该类名
    _Unsupported = None  # type: ignore[assignment]

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import llm

import httpx
import re

from .const import STATELESS_LLM_API, MA_BASE_URL, MA_API_TOKEN, MA_DEFAULT_QUEUE_ID, MA_DEFAULT_PLAYER_ID

_LOGGER = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Music Assistant (MASS) integration
# MA 2.x 只有一个命令端点：POST {base}/api，body 为
# {"command": "<命令名>", "args": {<参数>}}，鉴权：Authorization: Bearer <token>。
# 绕过 HA conversation，规避 MCP 上下文 bug。
# 四项配置（mass_url / mass_token / mass_queue_id / mass_player_id）来自
# config entry，未配置时回退到 const.py 中的默认值。
# 命令名与参数以你 NAS 上的 /api-docs（Commands Reference）为准。
# ---------------------------------------------------------------------------


def _get_ma_config(ma_config: dict | None) -> dict:
    """Build effective MA config from config entry, falling back to defaults."""
    cfg = ma_config or {}
    return {
        "base_url": cfg.get("mass_url") or MA_BASE_URL,
        "token": cfg.get("mass_token") or MA_API_TOKEN,
        "queue_id": cfg.get("mass_queue_id") or MA_DEFAULT_QUEUE_ID,
        "player_id": cfg.get("mass_player_id") or MA_DEFAULT_PLAYER_ID,
    }


class MAError(Exception):
    """Music Assistant 命令执行失败时的自定义异常。"""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


async def _call_ma(cfg: dict, command: str, args: dict | None) -> Any:
    """Call a Music Assistant command via its single HTTP endpoint.

    MA 2.x 仅暴露一个命令端点：POST {base}/api，body 为
    {"command": "<命令名>", "args": {<参数>}}，鉴权：Authorization: Bearer <token>。
    命令名以 /api-docs 的 Commands Reference 为准（如 players/cmd/volume_set）。
    """
    url = f"{cfg['base_url'].rstrip('/')}/api"
    headers = {"Content-Type": "application/json"}
    token = (cfg.get("token") or "").strip()
    if token and not token.lower().startswith("bearer "):
        token = f"Bearer {token}"
    if token:
        headers["Authorization"] = token
    payload = {
        "command": command,
        "args": args or {},
    }
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as err:
        status = err.response.status_code
        body = (err.response.text or "").strip()
        if status in (401, 403):
            msg = (
                "Music Assistant 鉴权失败，请检查集成配置里的 "
                "MA API Token 是否正确（需 long-lived token）。"
            )
        elif status == 500:
            msg = (
                "Music Assistant 执行命令失败（500）。通常是目标播放器"
                "离线或无法启动播放，请在 MA 中确认该播放器可用，"
                "或在集成配置里指定正确的队列/播放器 ID。"
            )
        else:
            msg = f"Music Assistant 返回错误 {status}：{body or '无详细信息'}"
        raise MAError(msg, status) from err
    except httpx.RequestError as err:
        raise MAError(
            f"无法连接 Music Assistant（{cfg.get('base_url')}），"
            f"请检查地址与网络：{err}"
        ) from err
    if isinstance(data, dict) and "result" in data:
        return data["result"]
    return data


async def _resolve_ids(cfg: dict) -> dict:
    """Auto-discover queue/player ids when not configured.

    优先选择「在线(available)」播放器对应的队列，跳过离线播放器；
    若无法从在线列表中确定，则退回到首个队列。最终选定的队列会写日志。
    """
    if not cfg["queue_id"]:
        available_ids: set[str] = set()
        try:
            players = await _call_ma(cfg, "players/all", {})
            if isinstance(players, list):
                available_ids = {
                    p.get("player_id") for p in players if p.get("available")
                }
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("MA discover players failed: %s", err)

        try:
            queues = await _call_ma(cfg, "player_queues/all", {})
            if isinstance(queues, list) and queues:
                chosen = None
                for q in queues:
                    qid = q.get("queue_id") or q.get("id")
                    if qid in available_ids:
                        chosen = qid
                        break
                if not chosen:
                    chosen = (
                        queues[0].get("queue_id") or queues[0].get("id")
                    )
                cfg["queue_id"] = chosen
                _LOGGER.info("MA auto-discovered queue_id=%s", cfg["queue_id"])
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("MA discover via player_queues/all failed: %s", err)
    if not cfg["player_id"] and cfg["queue_id"]:
        cfg["player_id"] = cfg["queue_id"]
    return cfg


_MEDIA_KEY = {
    "track": "tracks",
    "album": "albums",
    "artist": "artists",
    "playlist": "playlists",
    "radio": "radio",
}


def _txt(text: str) -> types.TextContent:
    return types.TextContent(type="text", text=text)


async def _handle_ma_tool(name: str, arguments: dict, ma_config: dict | None):
    """Dispatch a Music Assistant tool call and return MCP text content."""
    cfg = _get_ma_config(ma_config)
    qid = pid = None
    try:
        cfg = await _resolve_ids(cfg)
        qid = cfg["queue_id"]
        pid = cfg["player_id"]

        if name == "ma_play":
            query = re.sub(
                r"[\U0001F000-\U0001FAFF\u2600-\u27BF\u2190-\u21FF\u2B00-\u2BFF]",
                "",
                (arguments.get("query") or "").strip(),
            )
            media_type = arguments.get("media_type", "track")
            limit = int(arguments.get("limit", 5))
            if not query:
                return [_txt("缺少搜索关键词 query。")]
            search = await _call_ma(
                cfg,
                "music/search",
                {"search_query": query, "media_types": [media_type], "limit": limit},
            )
            key = _MEDIA_KEY.get(media_type, "tracks")
            items = (search or {}).get(key) or []
            if not items:
                return [_txt(f"未找到与「{query}」相关的{media_type}。")]
            item = items[0]
            uri = item.get("uri")
            title = item.get("name") or item.get("title") or query
            await _call_ma(
                cfg,
                "player_queues/play_media",
                {"queue_id": qid, "media": uri},
            )
            return [_txt(f"正在播放：{title}（{media_type}）")]

        if name == "ma_control":
            command = arguments.get("command")
            if command == "seek":
                pos = int(arguments.get("position", 0))
                await _call_ma(
                    cfg, "player_queues/seek",
                    {"queue_id": qid, "position": pos},
                )
                return [_txt(f"已跳转到 {pos} 秒。")]
            mapping = {
                "play": "player_queues/play",
                "pause": "player_queues/pause",
                "stop": "player_queues/stop",
                "next": "player_queues/next",
                "previous": "player_queues/previous",
            }
            labels = {
                "play": "继续播放", "pause": "暂停", "stop": "停止",
                "next": "下一曲", "previous": "上一曲",
            }
            ma_cmd = mapping.get(command)
            if not ma_cmd:
                return [_txt(f"未知控制指令：{command}")]
            await _call_ma(cfg, ma_cmd, {"queue_id": qid})
            return [_txt(f"已执行：{labels.get(command, command)}。")]

        if name == "ma_volume":
            vol = int(max(0, min(100, float(arguments.get("volume", 0)))))
            if not pid:
                return [_txt("未配置 MA player_id，无法设置音量。")]
            await _call_ma(
                cfg, "players/cmd/volume_set",
                {"player_id": pid, "volume_level": vol},
            )
            return [_txt(f"音量已设置为 {vol}%。")]

        if name == "ma_repeat":
            mode = arguments.get("mode", "off")
            await _call_ma(
                cfg, "player_queues/repeat",
                {"queue_id": qid, "repeat_mode": mode},
            )
            return [_txt(f"循环模式已设置为：{mode}。")]

        if name == "ma_shuffle":
            enabled = bool(arguments.get("enabled", False))
            await _call_ma(
                cfg, "player_queues/shuffle",
                {"queue_id": qid, "shuffle_enabled": enabled},
            )
            return [_txt(f"随机播放已{'开启' if enabled else '关闭'}。")]

        if name == "ma_status":
            if not qid:
                return [_txt("未配置且未自动发现 MA queue_id。")]
            items = await _call_ma(
                cfg, "player_queues/items",
                {"queue_id": qid, "limit": 3, "offset": 0},
            )
            text = json.dumps(items, ensure_ascii=False)
            return [_txt(f"当前播放队列：{text[:1500]}")]

        return [_txt(f"未知 MA 工具：{name}")]
    except MAError as err:
        target = pid or qid
        suffix = f"（目标播放器：{target}）" if target else ""
        _LOGGER.error("MA tool %s failed: %s", name, err)
        return [_txt(err.message + suffix)]
    except Exception as err:  # noqa: BLE001
        _LOGGER.error("MA tool %s failed: %s", name, err)
        return [_txt(f"操作失败：{err}")]


MA_TOOL_DEFS = [
    types.Tool(
        name="ma_play",
        description=(
            "在 Music Assistant 中按关键词搜索并播放音乐。"
            "支持歌曲(track)/专辑(album)/歌单(playlist)/艺人(artist)/电台(radio)。"
            "当用户说'播放xxx的xxx'、'来首xxx'时使用。query 不要包含 emoji。"
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词，例如'周杰伦 晴天'"},
                "media_type": {
                    "type": "string",
                    "enum": ["track", "album", "playlist", "artist", "radio"],
                    "description": "媒体类型，默认 track",
                    "default": "track",
                },
                "limit": {"type": "integer", "description": "搜索返回数量，默认5", "default": 5},
            },
            "required": ["query"],
        },
    ),
    types.Tool(
        name="ma_control",
        description="Music Assistant 播放器传输控制：播放/暂停/停止/下一曲/上一曲/跳转进度(seek)。",
        inputSchema={
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": ["play", "pause", "stop", "next", "previous", "seek"],
                    "description": "控制指令",
                },
                "position": {"type": "integer", "description": "仅 command=seek 时有效，目标秒数", "default": 0},
            },
            "required": ["command"],
        },
    ),
    types.Tool(
        name="ma_volume",
        description="设置 Music Assistant 播放器音量(0-100)。",
        inputSchema={
            "type": "object",
            "properties": {
                "volume": {"type": "integer", "description": "音量 0-100", "default": 50},
            },
            "required": ["volume"],
        },
    ),
    types.Tool(
        name="ma_repeat",
        description="设置 Music Assistant 循环模式：off 关闭 / all 列表循环 / one 单曲循环。",
        inputSchema={
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["off", "all", "one"],
                    "description": "循环模式，默认 off",
                    "default": "off",
                },
            },
            "required": ["mode"],
        },
    ),
    types.Tool(
        name="ma_shuffle",
        description="开关 Music Assistant 随机播放。",
        inputSchema={
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean", "description": "true 开启 / false 关闭", "default": False},
            },
            "required": ["enabled"],
        },
    ),
    types.Tool(
        name="ma_status",
        description="获取 Music Assistant 当前播放队列与状态。",
        inputSchema={"type": "object", "properties": {}},
    ),
]
MA_TOOL_NAMES = {t.name for t in MA_TOOL_DEFS}


def _sanitize_schema(node: Any) -> Any:
    """递归把 voluptuous_openapi 的 _Unsupported 节点替换为宽松 schema。

    HA 2026.9 起，部分工具（脚本/某些 intent）的参数 schema 会包含
    _Unsupported 类型，直接序列化会抛 '_Unsupported' object is not subscriptable。
    这里把这类节点降级为 {}（任意值均可），保住其余正常字段。
    """
    if _Unsupported is not None and isinstance(node, _Unsupported):
        return {}
    if isinstance(node, dict):
        return {k: _sanitize_schema(v) for k, v in node.items()}
    if isinstance(node, list):
        return [_sanitize_schema(v) for v in node]
    return node


def _format_tool(
    tool: llm.Tool, custom_serializer: Callable[[Any], Any] | None
) -> types.Tool:
    """Format tool specification."""
    try:
        input_schema = convert(tool.parameters, custom_serializer=custom_serializer)
    except Exception as err:  # 单个工具转换失败不应拖垮整个 tools/list
        _LOGGER.warning(
            "MCP: 转换工具 %s 的参数 schema 失败，已降级为空参数: %s",
            tool.name,
            err,
        )
        input_schema = {}
    # convert 可能整体返回 _Unsupported（整段 schema 不被支持）
    if not isinstance(input_schema, dict):
        _LOGGER.warning(
            "MCP: 工具 %s 的参数 schema 不受支持(_Unsupported)，已降级为空参数",
            tool.name,
        )
        input_schema = {}
    input_schema = _sanitize_schema(input_schema)
    return types.Tool(
        name=tool.name,
        description=tool.description or "",
        inputSchema={
            "type": "object",
            "properties": input_schema.get("properties", {}),
            "required": input_schema.get("required", []),
        },
    )


async def create_server(
    hass: HomeAssistant,
    llm_api_id: str | list[str],
    llm_context: llm.LLMContext,
    ma_config: dict | None = None,
) -> Server:
    """Create a new Model Context Protocol Server.

    A Model Context Protocol Server object is associated with a single session.
    The MCP SDK handles the details of the protocol.
    """
    #_LOGGER.error("mcp create server, llm_api_id:%s , llm_context:%s)",llm_api_id ,llm_context)
    #_LOGGER.error("mcp create server, STATELESS_LLM_API:%s )",STATELESS_LLM_API)
    #_LOGGER.error("mcp create server, llm.LLM_API_ASSIST:%s )",llm.LLM_API_ASSIST)
    if llm_api_id == STATELESS_LLM_API:
        llm_api_id = llm.LLM_API_ASSIST

    server = Server("home-assistant")
    #server = Server[Any]("home-assistant")

    async def get_api_instance() -> llm.APIInstance:
        """Get the LLM API selected."""
        # Backwards compatibility with old MCP Server config
        return await llm.async_get_api(hass, llm_api_id, llm_context)

    @server.list_prompts()  # type: ignore[no-untyped-call, misc]
    async def handle_list_prompts() -> list[types.Prompt]:
        llm_api = await get_api_instance()
        return [
            types.Prompt(
                name=llm_api.api.name,
                description=f"Default prompt for Home Assistant {llm_api.api.name} API",
            )
        ]

    @server.get_prompt()  # type: ignore[no-untyped-call, misc]
    async def handle_get_prompt(
        name: str, arguments: dict[str, str] | None
    ) -> types.GetPromptResult:
        llm_api = await get_api_instance()
        if name != llm_api.api.name:
            raise ValueError(f"Unknown prompt: {name}")

        return types.GetPromptResult(
            description=f"Default prompt for Home Assistant {llm_api.api.name} API",
            messages=[
                types.PromptMessage(
                    role="assistant",
                    content=types.TextContent(
                        type="text",
                        text=llm_api.api_prompt,
                    ),
                )
            ],
        )

    @server.list_tools()  # type: ignore[no-untyped-call, misc]
    async def list_tools() -> list[types.Tool]:
        """List available time tools."""
        llm_api = await get_api_instance()
        _LOGGER.debug("mcp list tools:%s )",llm_api.tools)
        tools = [_format_tool(tool, llm_api.custom_serializer) for tool in llm_api.tools]
        # 仅在配置了 MA token 时挂载 Music Assistant 工具
        if MA_API_TOKEN or (ma_config or {}).get("mass_token"):
            tools += MA_TOOL_DEFS
        return tools

    @server.call_tool()  # type: ignore[no-untyped-call, misc]
    async def call_tool(name: str, arguments: dict) -> Sequence[types.TextContent]:
        """Handle calling tools."""
        # Music Assistant 工具优先路由，不走 HA assist 管道
        if name in MA_TOOL_NAMES:
            return await _handle_ma_tool(name, arguments, ma_config)
        llm_api = await get_api_instance()
        tool_input = llm.ToolInput(tool_name=name, tool_args=arguments)
        _LOGGER.debug("Tool call: %s(%s)", tool_input.tool_name, tool_input.tool_args)

        try:
            tool_response = await llm_api.async_call_tool(tool_input)
        except (HomeAssistantError, vol.Invalid) as e:
            raise HomeAssistantError(f"Error calling tool: {e}") from e
        return [
            types.TextContent(
                type="text",
                text=json.dumps(tool_response),
            )
        ]

    return server

