# apps 目录说明

`apps/` 放可直接运行的入口脚本。日常操作优先从这里启动，而不是直接调用 `peifang_core/` 中的底层函数。

| 子目录 | 功能 |
|---|---|
| `wecom_smartsheet_qiyeweixin/` | 企业微信智能表格接入、登记、同步和读取 |
| `feishu_bitable_feishu/` | 飞书多维表格同步、资源 ID 查询和长连接实验 |
| `schedule_paichan/` | 排产三步流程：准备任务、生成框架、填充卡片 |
| `feishu_local_bot_feishu/` | 飞书本地机器人，负责群消息历史拉取、HTTP 触发和实时事件 |

## 使用建议

| 场景 | 日常入口 |
|---|---|
| 企业微信标准同步 | `wecom_smartsheet_qiyeweixin/B00A_wecom_smartsheet_manager_qiyeweixin.py --mode 0 --non-interactive` |
| 企业微信双公司同步排错 | `wecom_smartsheet_qiyeweixin/B02A_wecom_smartsheet_sync_two_companies_qiyeweixin.py` |
| 飞书多维表格同步 | `feishu_bitable_feishu/F01_feishu_bitable_sync_feishu.py` |
| 生成排产结果 | 依次运行 `schedule_paichan/B05A`、`schedule_paichan/B05B` |
| 填充 Excel 排产卡片 | `schedule_paichan/B06`，仅 Windows + Excel 需要 |
| 保存飞书群历史消息 | `feishu_local_bot_feishu/run_history_sync.py` |

其他拆分脚本主要用于单步排错、字段检查或兼容旧流程，日常不用逐个打开。

## 子目录文档

- [企业微信智能表格入口](wecom_smartsheet_qiyeweixin/README.md)
- [飞书多维表格入口](feishu_bitable_feishu/README.md)
- [排产流程入口](schedule_paichan/README.md)
- [飞书本地机器人](feishu_local_bot_feishu/README.md)
