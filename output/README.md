# output 目录说明

`output/` 保存同步和排产流程生成的输出文件。这里通常包含 JSON、CSV、Excel、HTML 等运行产物。

## 固定最新结果

排产脚本会自动维护 `output/latest/`，日常查看优先打开这里：

| 文件 | 说明 |
|---|---|
| `latest/tasks_prepared.json` | 最新标准化排产任务 |
| `latest/tasks_prepared.csv` | 最新标准化排产任务表格 |
| `latest/wecom_smartsheet_full.xlsx` | 最新企业微信智能表格完整导出，方便人工比对 |
| `latest/wecom_smartsheet_full.csv` | 最新企业微信智能表格完整 CSV 导出 |
| `latest/排产_layout.json` | 最新网页/Excel 共用布局 |
| `latest/schedule_web.html` | 最新自适应网页排产看板 |
| `latest/排产_框架.xlsx` | 最新 Excel 排产框架或填充结果 |

## 历史归档

带时间戳的历史文件会自动移动到 `output/archive/`，默认每类保留最近 10 个。可通过环境变量调整：

```dotenv
PEIFANG_OUTPUT_KEEP=10
```

清理只针对 `archive/` 里的时间戳运行产物，不清理 `README.md`、`A00_目录说明.txt` 和 `latest/`。

## 常见输出

| 文件类型 | 来源 | 用途 |
|---|---|---|
| `*.fields.json` | 企业微信或飞书同步 | 保存字段结构 |
| `*.records.raw.json` | 企业微信或飞书同步 | 保存接口返回的原始记录 |
| `wecom_smartsheet_full_*.xlsx` | 企业微信完整同步 | 按字段展开后的完整表格，方便人工比对 |
| `wecom_smartsheet_full_*.csv` | 企业微信完整同步 | 按字段展开后的完整 CSV |
| `tasks_prepared_*.json` | `B05A_schedule_prepare_paichan.py` | 标准化排产任务 |
| `tasks_prepared_*.csv` | `B05A_schedule_prepare_paichan.py` | 便于人工核对的任务表 |
| `layout*.json` | `B05B` 或 `B06` | 排产布局数据 |
| `*.xlsx` | `B05B` 或 `B06` | 排产框架或填充后的 Excel |
| `*.html` | 排产渲染逻辑 | 浏览器可查看的排产结果 |

## 提交建议

真实业务输出不要提交。需要保留示例时，放到 `examples/output/` 并脱敏。
