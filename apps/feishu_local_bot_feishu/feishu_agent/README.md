# feishu_agent 包说明

`feishu_agent/` 是飞书本地机器人的核心包。上一级的 `run_*.py` 文件负责命令行入口，这里负责配置、鉴权、接口、同步、存储和实时事件处理。

| 文件 | 功能 |
|---|---|
| `__init__.py` | 标记 `feishu_agent` 为可导入包 |
| `config.py` | 读取飞书机器人运行配置，支持默认变量和多公司配置档案变量 |
| `auth.py` | 管理 `tenant_access_token` 的获取、缓存和复用 |
| `http_client.py` | 封装飞书 HTTP 请求、超时和响应处理 |
| `im_api.py` | 封装群聊列表、消息列表、图片下载、消息回复等 IM API |
| `service.py` | 组织消息拉取、增量状态更新和本地保存流程 |
| `storage.py` | 负责状态文件、消息文件和本地数据目录读写 |
| `assets.py` | 处理消息图片下载和本地缓存路径 |
| `normalize.py` | 把飞书接口返回的消息转换为稳定的本地保存结构 |
| `ws_bot.py` | 处理 WebSocket 事件、消息解析和可选自动回复 |
| `utils.py` | 日志、时间和安全类型转换等复用小工具 |
| `download_image_test.py` | 用指定 `image_key` 验证飞书图片下载接口和本地保存逻辑 |

## 调用关系

| 入口 | 主要调用 |
|---|---|
| `../run_list_chats.py` | `config`、`auth`、`im_api` |
| `../run_history_sync.py` | `config`、`service`、`storage`、`im_api` |
| `../run_server.py` | `service`、`storage`、HTTP 路由 |
| `../run_ws_bot.py` | `ws_bot`、`service`、`storage` |
