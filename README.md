# 配方排产项目

这个仓库用于把企业微信智能表格、飞书多维表格中的生产任务同步到本地，再整理成排产任务、Excel 框架和可查看的排产结果。

项目说明统一放在各级 `README.md` 中；原来的 `A00_目录说明.txt` 已不再需要，避免同一份说明维护两遍。

## 日常只看这几个入口

| 场景 | 日常入口 |
|---|---|
| 企业微信标准同步 | `apps/wecom_smartsheet_qiyeweixin/B00A_wecom_smartsheet_manager_qiyeweixin.py --mode 0 --non-interactive` |
| 生成标准化排产任务 | `apps/schedule_paichan/B05A_schedule_prepare_paichan.py` |
| 生成排产网页看板 | `apps/schedule_paichan/B05B_schedule_build_frame_paichan.py` |

其他脚本主要用于单步排错、字段检查、飞书同步或 Excel 增强导出，日常不用逐个打开。

## 推荐日常命令

1. 复制 `.env.example` 为 `.env`，填写企业微信或飞书凭证。
2. 如需多公司配置，设置 `WECOM_ENV_PROFILE=COMPANY_A` 或 `COMPANY_B`，飞书可设置 `FEISHU_ENV_PROFILE`。
3. 先同步数据，再运行排产链路。

```powershell
python apps/wecom_smartsheet_qiyeweixin/B00A_wecom_smartsheet_manager_qiyeweixin.py --mode 0 --non-interactive
python apps/schedule_paichan/B05A_schedule_prepare_paichan.py
python apps/schedule_paichan/B05B_schedule_build_frame_paichan.py
```

本项目目前按本地电脑运行设计。通常跑到 `B05B` 即可，使用生成的网页看板作为主排产结果。`B06` 依赖 Windows Excel COM，只有需要可编辑 Excel 卡片时再运行。

日常打开最新结果时，优先看固定文件：

```text
output/latest/schedule_web.html
output/latest/document_inventory.xlsx
output/latest/wecom_two_company_sync_summary.json
```

企业微信完整同步后，人工核对原始表格数据可打开：

```text
output/latest/wecom_smartsheet_full.xlsx
```

带时间戳的历史输出会自动归档到 `output/archive/`，避免 `output/` 根目录越跑越乱。

## 同步问题优先检查

| 顺序 | 文件 | 看什么 |
|---|---|---|
| 1 | `data/wecom/manual_smartsheet_links.xlsx` | 新表链接是否已填写并启用 |
| 2 | `smartsheet_registry.json` | `docid`、`sheet_id`、`env_profile`、失效状态 |
| 3 | `data/wecom/smartsheet/<docid>/<sheet_id>/fields_latest.json` | 字段结构是否已同步 |
| 4 | `data/wecom/smartsheet/<docid>/<sheet_id>/records_merged_latest.json` | 记录是否已同步 |
| 5 | `output/latest/wecom_two_company_sync_summary.json` | 本次同步是否有错误 |
| 6 | `output/latest/document_inventory.xlsx` | 人工核对总览 |

## 目录地图

| 路径 | 用途 | 进一步阅读 |
|---|---|---|
| `apps/` | 可直接运行的业务入口，按平台和流程分组 | [apps/README.md](apps/README.md) |
| `peifang_core/` | 企业微信、飞书、排产渲染等可复用核心逻辑 | [peifang_core/README.md](peifang_core/README.md) |
| `tools/` | 不属于主同步链路的独立制造计算和杂项工具 | [tools/README.md](tools/README.md) |
| `data/` | 同步后的本地缓存和状态文件 | [data/README.md](data/README.md) |
| `output/` | 排产流程生成的 JSON、CSV、Excel、HTML 等输出 | [output/README.md](output/README.md) |
| `production_data_shengchan/` | 真实生产业务数据的本地放置区 | [production_data_shengchan/README.md](production_data_shengchan/README.md) |
| `examples/` | 可提交的样例输入和样例输出 | [examples/README.md](examples/README.md) |
| `legacy/` | 旧脚本、实验脚本和兼容包装归档 | [legacy/README.md](legacy/README.md) |

## 数据流

```text
企业微信智能表格 / 飞书多维表格
        -> 同步脚本
        -> data/ 本地缓存
        -> B05A 标准化任务
        -> output/ 标准任务、布局和结果文件
        -> B05B 自适应 HTML 看板和布局
        -> B06 Excel 排产结果（Windows 可选）
```

## 同步策略

| 平台 | 入口 | 缓存路径 | 策略 |
|---|---|---|---|
| 企业微信智能表格 | `apps/wecom_smartsheet_qiyeweixin/B00A_wecom_smartsheet_manager_qiyeweixin.py --mode 0 --non-interactive` | `data/wecom/smartsheet/<docid>/<sheetid>/` | 导入人工链接；验证公司归属；同步双公司；刷新 latest |
| 飞书多维表格 | `apps/feishu_bitable_feishu/F01_feishu_bitable_sync_feishu.py` | `data/feishu/bitable/<app_token>/<table_id>/` | 首次全量；后续可取最近记录合并；定期全量校验 |

## 多公司环境配置

项目支持多个企业微信或多个飞书公司的配置。未设置配置档案时，继续读取原来的单公司变量；设置配置档案后，会优先读取对应公司的变量或专用环境文件。

常用选择变量：

| 变量 | 用途 |
|---|---|
| `PEIFANG_ENV_PROFILE` | 企业微信和飞书共用同一个配置档案 |
| `WECOM_ENV_PROFILE` | 只选择企业微信配置档案 |
| `FEISHU_ENV_PROFILE` | 只选择飞书配置档案 |

同一个 `.env` 中可以写带档案名的变量：

```dotenv
WECOM_ENV_PROFILE=COMPANY_A
WECOM_COMPANY_A_CORP_ID=wwxxxxxxxxxxxxxxxx
WECOM_COMPANY_A_ADMIN_USERID=your_admin_userid
WECOM_COMPANY_A_APP_SECRET=replace-me
WECOM_COMPANY_A_CALLBACK_TOKEN=replace-me
WECOM_COMPANY_A_CALLBACK_AESKEY=replace-me
WEDOC_COMPANY_A_DOCID=sample_docid_a
WEDOC_COMPANY_A_SHEET_ID=sample_sheet_id_a
SMARTSHEET_COMPANY_A_ID=sample_docid_a
SMARTSHEET_COMPANY_A_SHEET_ID=sample_sheet_id_a

WECOM_COMPANY_B_CORP_ID=wwyyyyyyyyyyyyyyyy
WECOM_COMPANY_B_ADMIN_USERID=your_admin_userid
WECOM_COMPANY_B_APP_SECRET=replace-me
WEDOC_COMPANY_B_DOCID=sample_docid_b
WEDOC_COMPANY_B_SHEET_ID=sample_sheet_id_b

FEISHU_ENV_PROFILE=COMPANY_B
FEISHU_COMPANY_B_APP_ID=cli_xxxxxxxxxxxxxxxx
FEISHU_COMPANY_B_APP_SECRET=replace-me
FEISHU_COMPANY_B_APP_TOKEN=bascnxxxxxxxxxxxxxxxx
FEISHU_COMPANY_B_TABLE_ID=tblxxxxxxxxxxxxxxxx
```

也可以为不同公司单独放本地文件，例如 `.env.company_a`、`.env.wecom.company_a`、`.env.feishu.company_b`。这些文件里可以继续使用普通变量名，例如 `WECOM_CORP_ID`、`FEISHU_APP_ID`、`APP_TOKEN`。

## 提交安全

真实凭证、真实业务数据、运行缓存和输出文件不应提交。可提交的安全示例保留在 `.env.example`、`examples/` 和 `smartsheet_registry.example.json`。
