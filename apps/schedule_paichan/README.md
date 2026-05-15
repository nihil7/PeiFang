# 排产流程入口

这个目录保存排产主流程入口。若部署到 Linux 服务器，推荐把 `B05A -> B05B` 作为主链路，直接生成 `layout.json` 和自适应 HTML 排产看板；`B06` 仅作为 Windows + Excel 环境下的可选增强导出。

| 顺序 | 文件 | 输入 | 输出 | 功能 |
|---|---|---|---|---|
| 1 | `B05A_schedule_prepare_paichan.py` | `output/` 中最新旧格式记录；若没有，则自动读取 `data/wecom/smartsheet/` 下最新同步缓存 | `tasks_prepared_*.json`、`tasks_prepared_*.csv` | 解析机台、日期、甘特图文本和颜色，生成标准化排产任务 |
| 2 | `B05B_schedule_build_frame_paichan.py` | 最新 `tasks_prepared_*.json` | 排产框架 Excel、`layout.json`、自适应 HTML 看板 | 生成日期、机台、lane、排产布局和网页看板 |
| 3 | `B06_schedule_fill_cards_paichan.py` | `layout.json` 和框架 Excel | 填充后的 Excel、布局 JSON 或 HTML | Windows 可选步骤：用 Excel COM 把任务卡片填入 Excel |

## 常用命令

```powershell
python apps/schedule_paichan/B05A_schedule_prepare_paichan.py
python apps/schedule_paichan/B05B_schedule_build_frame_paichan.py
```

生成后优先查看固定入口：

```text
output/latest/schedule_web.html
```

## 排产核心输出

| 文件 | 用途 |
|---|---|
| `output/latest/tasks_prepared.json` | B05A 生成的标准化任务，是排产问题的第一检查点 |
| `output/latest/tasks_prepared.csv` | 方便人工查看的任务表 |
| `output/latest/排产_layout.json` | B05B 生成的布局数据 |
| `output/latest/schedule_web.html` | 日常查看的网页排产看板 |

## 注意

- `B06` 使用 Excel COM 和 `pywin32` 插入可编辑形状，通常需要 Windows + 本机 Office。
- Linux 服务器环境下通常不用 `B06`，直接使用 `B05B` 输出的 `schedule_web_*.html`。
- `B05A` 会优先兼容旧的 `output/*.records.raw.json`；没有旧格式文件时，会使用企业微信同步后的 `data/wecom/smartsheet/**/records_merged_latest.json`。
- `B05B` 和 `B06` 默认从 `output/` 中选择最新 `tasks_prepared_*.json` 和最新布局文件；如果要固定输入文件，需要改对应脚本配置区。
- HTML 渲染能力来自 `peifang_core/schedule_web.py`，当前生成的是自适应网页看板：桌面横向排产网格，小屏自动切换列表视图，并支持机台筛选。
- 每次生成会同步更新 `output/latest/`，并把时间戳历史文件移动到 `output/archive/`；默认每类保留最近 10 个，可用 `PEIFANG_OUTPUT_KEEP` 调整。
