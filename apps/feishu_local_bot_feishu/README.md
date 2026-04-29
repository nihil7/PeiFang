# 飞书本地机器人

这个子项目用于读取飞书群消息历史、保存本地消息数据，也可以启动 HTTP 服务或 WebSocket 机器人处理实时事件。

## 入口脚本

| 文件 | 功能 | 常见用途 |
|---|---|---|
| `run_list_chats.py` | 列出机器人可见的飞书群聊 | 获取 `chat_id` 和确认机器人可见范围 |
| `run_history_sync.py` | 拉取指定飞书群聊历史消息并保存到本地 | 手动刷新历史消息或补拉增量 |
| `run_server.py` | 启动本地 HTTP 服务，通过接口触发同步和健康检查 | 本地调试、外部系统触发同步 |
| `run_ws_bot.py` | 启动飞书 WebSocket 机器人，接收实时事件并可选回复 | 验证实时事件链路 |

## 核心包

更细的模块说明见 [feishu_agent/README.md](feishu_agent/README.md)。

| 路径 | 功能 |
|---|---|
| `feishu_agent/config.py` | 读取运行配置，支持默认变量和多公司配置档案变量 |
| `feishu_agent/auth.py` | 管理 `tenant_access_token` 获取和复用 |
| `feishu_agent/http_client.py` | 封装飞书 HTTP 请求、超时和响应处理 |
| `feishu_agent/im_api.py` | 封装群聊、消息列表、图片和回复等 IM 接口 |
| `feishu_agent/service.py` | 组织消息拉取、增量状态更新和本地保存流程 |
| `feishu_agent/storage.py` | 负责状态文件、消息文件和本地数据目录读写 |
| `feishu_agent/assets.py` | 下载消息图片资源并维护本地缓存路径 |
| `feishu_agent/normalize.py` | 把飞书消息转换为稳定的本地保存结构 |
| `feishu_agent/ws_bot.py` | 处理 WebSocket 事件、消息解析和可选自动回复 |
| `feishu_agent/utils.py` | 日志、时间和安全转换等小工具 |

## 快速使用

安装依赖：

```powershell
pip install -r apps/feishu_local_bot_feishu/requirements.txt
```

复制 `.env.example` 为 `.env`，填写 `FEISHU_APP_ID` 和 `FEISHU_APP_SECRET`。如果要拉群历史消息，飞书后台需要给应用开通相应消息读取权限，且机器人必须在目标群里。

先列出群聊：

```powershell
python apps/feishu_local_bot_feishu/run_list_chats.py
```

再拉取指定群：

```powershell
python apps/feishu_local_bot_feishu/run_history_sync.py --chat-id oc_xxxxx
```

启动 HTTP 服务：

```powershell
python apps/feishu_local_bot_feishu/run_server.py
```

常用接口：

| 接口 | 功能 |
|---|---|
| `GET /health` | 健康检查 |
| `GET /chats` | 列出可见群聊 |
| `POST /sync` | 同步 `.env` 中配置的群 |
| `POST /sync?chat_id=oc_xxx&full=0` | 同步指定群 |

启动 WebSocket 机器人：

```powershell
python apps/feishu_local_bot_feishu/run_ws_bot.py
```

## 本地数据

| 路径 | 内容 |
|---|---|
| `data/chats.json` | 群聊列表缓存 |
| `data/messages/` | 拉取到的消息文件 |
| `data/events/` | WebSocket 或 HTTP 事件落盘 |
| `data/images/` | 消息图片本地缓存 |

长连接只负责程序在线期间的实时事件；程序退出或电脑关机期间的消息，需要通过历史同步补拉。
