# Project Structure And Sync Design

## Goal

Use a conservative cleanup: keep the current working scripts and module layout, but make the project easier to inspect by clarifying which files are daily entry points, which files are core state, which files are generated, and where real business data should live.

This design avoids large code rewrites. It focuses on file placement, visible workflow, and a repeatable checklist for confirming sync problems.

## Current Shape

The project already has a useful layered structure:

| Path | Role |
|---|---|
| `apps/` | Runnable business entry scripts |
| `peifang_core/` | Shared sync, parsing, output, and rendering logic |
| `data/` | Local sync cache and runtime state |
| `output/` | Generated reports, dashboards, spreadsheets, and summaries |
| `examples/` | Desensitized sample inputs and outputs that can be committed |
| `production_data_shengchan/` | Local real production data and manual business files |
| `legacy/` | Old wrappers, experiments, and compatibility scripts |
| `docs/` | Design notes and operator documentation |

The main problem is not the directory structure itself. The problem is that too many runtime and support files look equally important from the root and from `output/`, so the operator has to guess what matters.

## Design Principles

1. Keep daily operation simple: one WeCom sync entry, two schedule generation entries.
2. Keep real data local: do not commit real cache, production CSV/XLSX files, registry state, or generated output.
3. Keep `output/latest/` as the human-facing latest result area.
4. Keep `output/archive/` as historical run artifacts that are normally not inspected.
5. Keep `smartsheet_registry.json` in the root as the local registry center, but document it as local state, not source code.
6. Do not delete old scripts during this cleanup. Reclassify them as advanced or legacy entries first.

## Recommended Root Directory

Daily-visible root files should be limited to:

| File | Keep? | Reason |
|---|---:|---|
| `README.md` | Yes | Main operator guide |
| `requirements.txt` | Yes | Python dependencies |
| `.env.example` | Yes | Safe credential template |
| `smartsheet_registry.example.json` | Yes | Safe registry example |
| `smartsheet_registry.json` | Local only | Core registry state, ignored by git |
| `.env` | Local only | Credentials, ignored by git |

Files that should not stay as root-level daily files:

| File | Recommended Location | Reason |
|---|---|---|
| `生产任务排期_提取任务.csv` | `production_data_shengchan/` if real, `examples/` if desensitized | It is business data or sample input, not project structure |
| `generated_env.txt` | `legacy/` or remove after confirmation | Looks like an old generated helper, not a daily config source |
| root generated JSON/CSV/XLSX/HTML files | `output/latest/` or `output/archive/` | Generated output should not compete with source files |

## Daily Entry Points

Daily operators should primarily use these scripts:

| Purpose | Script |
|---|---|
| Standard WeCom sync workflow | `apps/wecom_smartsheet_qiyeweixin/B00A_wecom_smartsheet_manager_qiyeweixin.py` |
| Direct two-company WeCom sync | `apps/wecom_smartsheet_qiyeweixin/B02A_wecom_smartsheet_sync_two_companies_qiyeweixin.py` |
| Prepare standardized schedule tasks | `apps/schedule_paichan/B05A_schedule_prepare_paichan.py` |
| Build schedule layout and web dashboard | `apps/schedule_paichan/B05B_schedule_build_frame_paichan.py` |

Recommended normal run:

```powershell
python apps/wecom_smartsheet_qiyeweixin/B00A_wecom_smartsheet_manager_qiyeweixin.py --mode 0 --non-interactive
python apps/schedule_paichan/B05A_schedule_prepare_paichan.py
python apps/schedule_paichan/B05B_schedule_build_frame_paichan.py
```

## Advanced Entry Points

These files should remain available, but should be documented as single-step troubleshooting or compatibility tools:

| Script | Classification |
|---|---|
| `B01A_wecom_smartsheet_import_links_qiyeweixin.py` | Import manual links only |
| `B01B_wecom_smartsheet_verify_profiles_qiyeweixin.py` | Verify and correct company ownership only |
| `B02_wecom_smartsheet_sync_qiyeweixin.py` | Low-level single-profile sync |
| `B03_wecom_smartsheet_templates_qiyeweixin.py` | Field/template inspection |
| `B04_wecom_smartsheet_read_qiyeweixin.py` | Direct API read/debug |
| `B06_schedule_fill_cards_paichan.py` | Optional Windows Excel COM export |

## Core Files For Sync Troubleshooting

When sync looks wrong, inspect files in this order:

### 1. Manual Discovery Source

```text
data/wecom/manual_smartsheet_links.xlsx
```

Use this to confirm whether a target smart sheet link has been entered and enabled. If a new sheet never appears in the registry, start here.

### 2. Registry Center

```text
smartsheet_registry.json
```

Use this to confirm:

- `docid`
- `sheet_id`
- sheet title
- owning `env_profile`
- access or invalid status
- last seen or sync metadata

This file is local operational state. It should be ignored by git, but it is a core file for troubleshooting.

### 3. Local Cache

```text
data/wecom/smartsheet/<docid>/<sheet_id>/
```

Important files inside each sheet cache:

| File | Meaning |
|---|---|
| `fields_latest.json` | Latest field structure |
| `records_merged_latest.json` | Latest merged records |
| sync state files | Last sync time, mode, paging, or verification state when present |

If `registry` is correct but output is wrong, inspect the matching cache folder next.

### 4. Latest Human-Check Outputs

```text
output/latest/document_inventory.xlsx
output/latest/wecom_two_company_sync_summary.json
output/latest/wecom_smartsheet_full.xlsx
output/latest/tasks_prepared.json
output/latest/schedule_web.html
```

Use `output/latest/` for daily confirmation. Avoid browsing `output/archive/` unless comparing history.

## Sync Flow

The intended WeCom flow is:

```text
data/wecom/manual_smartsheet_links.xlsx
  -> import links and discover docid / sheet_id
  -> smartsheet_registry.json
  -> verify COMPANY_A / COMPANY_B ownership
  -> sync fields and records
  -> data/wecom/smartsheet/<docid>/<sheet_id>/
  -> output/latest sync summaries and check spreadsheets
```

The intended schedule flow is:

```text
data/wecom/smartsheet/**/records_merged_latest.json
  -> B05A prepares normalized tasks
  -> output/latest/tasks_prepared.json
  -> B05B builds layout and dashboard
  -> output/latest/排产_layout.json
  -> output/latest/schedule_web.html
```

## Troubleshooting Checklist

Use this order when a sync result looks wrong:

1. Check whether the smart sheet link exists and is enabled in `data/wecom/manual_smartsheet_links.xlsx`.
2. Check whether the `docid` and `sheet_id` exist in `smartsheet_registry.json`.
3. Check whether `env_profile` points to the correct company.
4. Run the profile verification step if ownership looks wrong.
5. Check the matching `data/wecom/smartsheet/<docid>/<sheet_id>/fields_latest.json`.
6. Check the matching `records_merged_latest.json`.
7. Check `output/latest/wecom_two_company_sync_summary.json` for errors.
8. Check `output/latest/document_inventory.xlsx` for a human-readable overview.
9. If schedule output is wrong, check `output/latest/tasks_prepared.json`.
10. If web output is wrong, check `output/latest/schedule_web.html` and `output/latest/排产_layout.json`.

## File Visibility Rules

Files that should be visible for daily work:

- `README.md`
- `docs/`
- `apps/wecom_smartsheet_qiyeweixin/B00A...`
- `apps/schedule_paichan/B05A...`
- `apps/schedule_paichan/B05B...`
- `output/latest/`
- `smartsheet_registry.json` when troubleshooting
- `data/wecom/manual_smartsheet_links.xlsx` when adding or checking links

Files that should usually be hidden from operator attention:

- `output/archive/`
- `data/wecom/smartsheet/**` except during troubleshooting
- `legacy/`
- `__pycache__/`
- old compatibility wrappers
- timestamped generated files

## Implementation Scope

The conservative cleanup should do only these changes:

1. Add or update docs that define the daily workflow and core files.
2. Move root-level business data files to the correct data directory after confirming whether they are real or sample data.
3. Move or remove obsolete helper files only after confirming they are no longer used.
4. Update README files so daily operators see the simplified workflow first.
5. Keep existing scripts and module imports working.
6. Avoid large code refactors until the file layout and operator workflow are stable.

## Acceptance Criteria

The cleanup is successful when:

1. A daily operator can identify the three normal commands without reading all scripts.
2. A troubleshooting operator can identify the core registry, cache, and latest output files.
3. Root-level files are limited to source, config examples, docs, and clearly local state.
4. Real production files are under `production_data_shengchan/`.
5. Desensitized examples are under `examples/`.
6. Generated output is under `output/latest/` or `output/archive/`.
7. Existing sync and schedule commands still work.
