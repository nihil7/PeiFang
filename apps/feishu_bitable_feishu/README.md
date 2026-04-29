# 飞书多维表格入口

这个目录保存飞书多维表格相关的可运行脚本，主要用于同步多维表格、查询资源标识和验证长连接链路。

| 文件 | 功能 | 常见用途 |
|---|---|---|
| `F01_feishu_bitable_sync_feishu.py` | 按 `auto`、`full`、`recent` 或 `verify` 模式同步字段、记录和状态到 `data/` | 日常同步飞书多维表格数据 |
| `F02_feishu_dashboard_id_feishu.py` | 查询飞书仪表盘或相关资源标识 | 配置联调时确认 dashboard id |
| `F03_feishu_api_info_feishu.py` | 解析多维表格、数据表、视图等 API 关键参数 | 获取 app token、table id、view id 等配置值 |
| `F04_feishu_long_conn_feishu.py` | 运行飞书长连接实验 | 验证实时消息或事件接入链路 |

## 常用命令

```powershell
python apps/feishu_bitable_feishu/F01_feishu_bitable_sync_feishu.py --mode auto
python apps/feishu_bitable_feishu/F01_feishu_bitable_sync_feishu.py --mode full
python apps/feishu_bitable_feishu/F01_feishu_bitable_sync_feishu.py --mode recent --recent-limit 50
python apps/feishu_bitable_feishu/F01_feishu_bitable_sync_feishu.py --mode verify
```

## 相关核心模块

- `peifang_core/feishu.py`：飞书多维表格字段、记录同步和本地缓存逻辑。
- `peifang_core/common.py`：路径、JSON 读写、记录合并和多公司环境配置。
