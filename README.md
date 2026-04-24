# PeiFang PaiChan

This repository is now organized for direct GitHub cloning and local use.
The structure follows three main groups:

- WeCom smart-sheet sync and post-processing
- Feishu bitable sync and post-processing
- Other functional utility scripts

No root-level compatibility wrappers are required for normal use. The old thin redirect files were moved into `legacy/compat_wrappers_archive/` for reference only.

## Project Layout

### `apps/wecom_smartsheet_qiyeweixin/`

WeCom smart-sheet related entry scripts:

- `B00_wecom_verify_server_qiyeweixin.py`
- `B01_wecom_smartsheet_registry_qiyeweixin.py`
- `B02_wecom_smartsheet_sync_qiyeweixin.py`
- `B03_wecom_smartsheet_templates_qiyeweixin.py`
- `B04_wecom_smartsheet_read_qiyeweixin.py`

### `apps/schedule_paichan/`

Scheduling and post-processing scripts:

- `B05A_schedule_prepare_paichan.py`
- `B05B_schedule_build_frame_paichan.py`
- `B06_schedule_fill_cards_paichan.py`

The schedule pipeline can now generate:

- Excel output
- layout JSON
- HTML schedule pages for later website integration

### `apps/feishu_bitable_feishu/`

Feishu bitable related entry scripts:

- `F01_feishu_bitable_sync_feishu.py`
- `F02_feishu_dashboard_id_feishu.py`
- `F03_feishu_api_info_feishu.py`
- `F04_feishu_long_conn_feishu.py`

### `apps/feishu_local_bot_feishu/`

Standalone Feishu local bot subproject retained as its own app area.

### `tools/manufacturing_calc_gongju/`

Other manufacturing and calculation scripts were preserved and grouped here:

- `T010_extract_source_bom_goujianbili.py`
- `T020_matrix_juzhen.py`
- `T021_insert_structure_frame_zijianbiaozhun.py`
- `T030_purchase_cost_caigou.py`
- `T040_sales_profit_xiaoshou.py`

### `tools/misc_gongju/`

Other utility scripts and notes:

- `M10_message_sender_main.py`
- `M20_haier_ppt_gongju.py`
- `M30_color_standard_juxian.py`
- `M40_video_cut_jianji.py`
- `M50_text_notes_tici.txt`

### `peifang_core/`

Shared core logic for sync and rendering:

- `common.py`
- `wecom.py`
- `feishu.py`
- `schedule_web.py`

### `data/`

Local sync cache directory.

### `production_data_shengchan/`

Local production data directory. Real business data is not committed.

### `legacy/`

Archived experiment scripts and compatibility wrappers kept only for reference.

## Sync Strategy

### WeCom smart-sheet sync

- First run pulls full data and stores it locally
- Later runs fetch the latest 50 records after time sorting
- New records are merged into local cache
- Periodic full refresh is supported to verify local accuracy

Cache path:

- `data/wecom/smartsheet/<docid>/<sheetid>/`

### Feishu bitable sync

- First run pulls full data and stores it locally
- Later runs fetch the latest 50 records after time sorting
- New records are merged into local cache
- Periodic full refresh is supported to verify local accuracy

Cache path:

- `data/feishu/bitable/<app_token>/<table_id>/`

## Quick Start

1. Copy `.env.example` to `.env` and fill in credentials.
2. Review sample config files and examples.
3. Run the needed entry script from `apps/`.

Example commands:

```powershell
python apps/wecom_smartsheet_qiyeweixin/B02_wecom_smartsheet_sync_qiyeweixin.py --help
python apps/feishu_bitable_feishu/F01_feishu_bitable_sync_feishu.py --help
python apps/schedule_paichan/B05A_schedule_prepare_paichan.py
python apps/schedule_paichan/B05B_schedule_build_frame_paichan.py
python apps/schedule_paichan/B06_schedule_fill_cards_paichan.py
```

## Git Safety

These items are intentionally ignored:

- `.env`
- `smartsheet_registry.json`
- local sync data under `data/`
- runtime output under `output/`
- real business data under `production_data_shengchan/`

Safe examples are kept in:

- `examples/`
- `.env.example`
- `smartsheet_registry.example.json`
