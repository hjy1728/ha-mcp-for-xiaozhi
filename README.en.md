## ha-mcp-for-xiaozhi+mass
- [English](README.en.md)
- [中文](README.md)


[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hjy1728&repository=ha-mcp-for-xiaozhi&category=integration)

<p align="center">
  <img src="https://raw.githubusercontent.com/c1pher-cn/brands/refs/heads/master/custom_integrations/ws_mcp_server/icon.png" alt="Alt Text" align="center">
</p>  

<p align="center"> 
Homeassistant MCP server for XiaoZhi AI，directly connect to Xiaozhi AI official server.
</p>



### About This Fork

This project is **forked from** [c1pher-cn/ha-mcp-for-xiaozhi](https://github.com/c1pher-cn/ha-mcp-for-xiaozhi), with the following main changes:

- **New: direct Music Assistant playback support**: calls Music Assistant's `/api` command endpoint directly so XiaoZhi AI can search / play / control / adjust volume, **bypassing Home Assistant's conversation pipeline** to avoid the MCP-context bug and conflicts with the built-in music control logic.

> When installing, use this fork's repository URL: `https://github.com/hjy1728/ha-mcp-for-xiaozhi.git`

### Capabilities
#### 1.HomeAssistant itself acts as an MCP server and connects directly to the XiaoZhi server via the websocket protocol without the need for a proxy.
#### 2.Select multiple API groups (HomeAssistant's build in Intent APIs and user-configured MCPServer) in one entity and proxy them to Xiaozhi
#### 3.Support configuring multiple entities at the same time
#### 4.New: direct Music Assistant playback support (bypasses the HA conversation pipeline for direct play/control/volume)

---
