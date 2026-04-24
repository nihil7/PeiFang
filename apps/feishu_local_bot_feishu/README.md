# Feishu 本地机器人：历史拉取 + HTTP 触发 +（可选）长连接实时收发

你现在要验证：**能读取群历史消息，并保存到本地**。  
本项目提供三种入口（可同时用）：

1) **手动刷新（CLI）**：你主动运行脚本拉取历史/增量消息  
2) **挂载路由（HTTP Server）**：启动本地服务后，通过 `http://127.0.0.1:8000/sync` 触发同步；也支持定时自动拉取（轮询）  
3) **长连接（WebSocket SDK）**：程序在线时实时接收“@机器人”的群消息，并可自动回复（用于你验证链路）

> 关键点：长连接只负责“在线实时事件”。你关机/程序退出期间的消息 **不会自动补发**。  
> 所以本项目在 `run_ws_bot.py` 启动前，默认会先跑一次“历史增量补拉”（可在 .env 里关掉）。

---

## 1) 安装依赖

建议 Python 3.10+：

```bash
pip install -r requirements.txt
```

---

## 2) 配置 .env

复制示例并填写：

- 将 `.env.example` 复制为 `.env`
- 填写 `FEISHU_APP_ID / FEISHU_APP_SECRET`

---

## 3) 飞书后台必须满足的条件（否则会报错）

- 应用需要开启“机器人能力”
- 机器人必须在目标群里
- **要拉取群消息历史**：需要权限（消息读取相关权限；若只给“@机器人消息”权限，就只能拿到 @ 相关）

---

## 4) 先拿 chat_id（群 ID）

```bash
python run_list_chats.py
```

结果会写入：`data/chats.json`  
控制台也会打印前 20 条（群名 + chat_id）。

---

## 5) 方式 A：手动刷新（CLI 拉历史）

### 拉取单个群（推荐先这样验证）

```bash
python run_history_sync.py --chat-id oc_xxxxx
```

### 或者在 .env 里设置默认群（逗号分隔）

`FEISHU_TARGET_CHAT_IDS=oc_xxx,oc_yyy`

然后直接运行：

```bash
python run_history_sync.py
```

输出：
- `data/messages/<chat_id>.jsonl`（一行一条消息）
- `data/state.json`（保存 last_synced_time，用于增量）

---

## 6) 方式 B：挂载路由（HTTP Server 触发同步）

启动服务：

```bash
python run_server.py
```

常用接口：

- 健康检查：`GET /health`
- 列群：`GET /chats`
- 触发同步：
  - `POST /sync` （不带参数则同步 .env 里配置的群）
  - `POST /sync?chat_id=oc_xxx&full=0`

---

## 7) 自动拉取（轮询）

在 `.env` 里设置：

- `FEISHU_POLL_INTERVAL_SECONDS=60`（每 60 秒自动拉一次增量）

然后用 `run_server.py` 启动服务即可。

---

## 8) 方式 C：长连接（WebSocket SDK）实时收消息 + 自动回复（可选）

启动长连接：

```bash
python run_ws_bot.py
```

落地文件：

- `data/events/p2_im_message_receive_v1.jsonl`（每条接收事件一行）

自动回复开关（在 `.env`）：

- `FEISHU_WS_AUTO_REPLY=1`（开）/ `0`（关）
- `FEISHU_WS_REPLY_PREFIX=收到：`

### 控制台提示“应用未建立长连接”怎么办？

这是飞书后台在你选择“使用长连接接收事件”时的校验提示：  
你还没跑 `run_ws_bot.py` 建立连接，所以它认为“未建立长连接”。  
先把程序跑起来，再回到控制台保存事件订阅即可。

---

## 9) 下一步（你确认历史拉取 + 长连接收发 OK 之后再做）
- 对接多维表格（bitable）读取与回传
- 处理数据（你自定义逻辑）
- 把结果发回群聊 / 写回多维表格
