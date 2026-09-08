## ha-mcp-for-xiaozhi+mass


- [English](README.en.md)
- [中文](README.md)




<p align="center">
  <img src="https://raw.githubusercontent.com/c1pher-cn/brands/refs/heads/master/custom_integrations/ws_mcp_server/icon.png" alt="Alt Text" align="center">
</p>  

<p align="center"> 
Homeassistant MCP server for 小智AI，直连小智AI官方服务器。
</p>


[![Open your Home Assistant instance and open a repository inside the Home Assistant Community Store.](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=hjy1728&repository=ha-mcp-for-xiaozhi&category=integration)

### 项目说明

本项目 **Fork 自** [c1pher-cn/ha-mcp-for-xiaozhi](https://github.com/c1pher-cn/ha-mcp-for-xiaozhi)，并在其基础上做了如下主要修改：

- **新增 Music Assistant 直连播放支持**：直接调用 Music Assistant 的 `/api` 命令端点，让小智 AI 可以点歌 / 控播 / 调音量，**绕过 Home Assistant 的 conversation 管道**，规避 MCP 上下文相关的 bug，并避免与内置音乐控制逻辑冲突。

> 安装时请使用本 Fork 仓库地址：`https://github.com/hjy1728/ha-mcp-for-xiaozhi.git`

### 插件能力介绍
#### 1.HomeAssistant自身作为mcp server 以websocket协议直接对接虾哥服务器，无需中转
#### 2.在一个实体里同时选择多个API组（HomeAssistant自带控制API、用户自己配置的MCPServer）并将它们一起代理给小智
#### 3.支持同时配置多个实体
#### 4.新增 Music Assistant 直连播放支持（绕过 HA conversation 管道，直接点歌/控播/调音量）

---
