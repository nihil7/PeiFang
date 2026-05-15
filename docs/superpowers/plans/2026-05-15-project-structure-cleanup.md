# Project Structure Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the repository easier to operate by documenting the daily sync flow, clarifying core troubleshooting files, and moving local root-level clutter into the right local data/archive folders without refactoring the working scripts.

**Architecture:** Keep the current `apps/`, `peifang_core/`, `data/`, `output/`, `examples/`, `production_data_shengchan/`, and `legacy/` layout. Update operator-facing docs first, then move only untracked local files that should not appear as root-level daily files. Verify with git status, doc inspection, and existing lightweight tests.

**Tech Stack:** Markdown docs, PowerShell file moves, Python scripts, pytest.

---

## File Structure

### Files To Modify

| Path | Responsibility |
|---|---|
| `README.md` | Top-level daily operator guide, simplified commands, core troubleshooting map |
| `apps/README.md` | App entry point summary; distinguish daily, advanced, and optional entries |
| `apps/wecom_smartsheet_qiyeweixin/README.md` | Keep current strong WeCom flow; add short troubleshooting order and daily-only command block if needed |
| `apps/schedule_paichan/README.md` | Keep B05A/B05B as the normal schedule flow and mark B06 optional |
| `data/README.md` | Clarify that `data/` is cache/runtime state and normally hidden from daily attention |
| `output/README.md` | Clarify that daily users inspect only `output/latest/`, not `output/archive/` |
| `production_data_shengchan/README.md` | Clarify root-level real business files should move here |

### Local Files To Move

These are not tracked by git, so moving them changes the working folder but will not produce committed source changes:

| Current Path | Target Path | Reason |
|---|---|---|
| `生产任务排期_提取任务.csv` | `production_data_shengchan/生产任务排期_提取任务.csv` | Looks like real or manual production data |
| `generated_env.txt` | `legacy/local_runtime_archive/generated_env.txt` | Old generated helper, not a daily root config |
| `.env.backup_20260429_104845` | `legacy/local_runtime_archive/.env.backup_20260429_104845` | Local credential backup, should not sit in root |

### Files Not To Modify

| Path | Reason |
|---|---|
| `.env` | Contains local credentials |
| `smartsheet_registry.json` | Core local sync state; keep in root but ignored |
| `data/wecom/smartsheet/**` | Runtime cache; do not restructure in this cleanup |
| `output/latest/**` | Current generated outputs; do not alter in this cleanup |
| `output/archive/**` | Historical outputs; do not alter except through existing cleanup scripts |
| `peifang_core/**` | No code refactor in conservative cleanup |
| `apps/**/*.py` | No script behavior changes in conservative cleanup |

---

### Task 1: Update The Top-Level Operator Guide

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Read the current README**

Run:

```powershell
Get-Content -Path README.md -Encoding UTF8
```

Expected: Shows current project intro, quick entry table, run order, directory map, data flow, sync strategy, and safety notes.

- [ ] **Step 2: Replace the top daily workflow sections**

Modify `README.md` so the opening sections clearly say:

````markdown
## 日常只看这几个入口

| 场景 | 日常入口 |
|---|---|
| 企业微信标准同步 | `apps/wecom_smartsheet_qiyeweixin/B00A_wecom_smartsheet_manager_qiyeweixin.py --mode 0 --non-interactive` |
| 生成标准化排产任务 | `apps/schedule_paichan/B05A_schedule_prepare_paichan.py` |
| 生成排产网页看板 | `apps/schedule_paichan/B05B_schedule_build_frame_paichan.py` |

## 推荐日常命令

```powershell
python apps/wecom_smartsheet_qiyeweixin/B00A_wecom_smartsheet_manager_qiyeweixin.py --mode 0 --non-interactive
python apps/schedule_paichan/B05A_schedule_prepare_paichan.py
python apps/schedule_paichan/B05B_schedule_build_frame_paichan.py
```

生成后优先查看：

```text
output/latest/schedule_web.html
output/latest/document_inventory.xlsx
output/latest/wecom_two_company_sync_summary.json
```
````

Keep the existing directory map, multi-company config, and commit safety sections. Remove or demote `B02_wecom_smartsheet_sync_qiyeweixin.py` from daily use because `B00A` is now the recommended standard workflow.

- [ ] **Step 3: Add a core troubleshooting section**

Add this section before or after the data flow section:

```markdown
## 同步问题优先检查

| 顺序 | 文件 | 看什么 |
|---|---|---|
| 1 | `data/wecom/manual_smartsheet_links.xlsx` | 新表链接是否已填写并启用 |
| 2 | `smartsheet_registry.json` | `docid`、`sheet_id`、`env_profile`、失效状态 |
| 3 | `data/wecom/smartsheet/<docid>/<sheet_id>/fields_latest.json` | 字段结构是否已同步 |
| 4 | `data/wecom/smartsheet/<docid>/<sheet_id>/records_merged_latest.json` | 记录是否已同步 |
| 5 | `output/latest/wecom_two_company_sync_summary.json` | 本次同步是否有错误 |
| 6 | `output/latest/document_inventory.xlsx` | 人工核对总览 |
```

- [ ] **Step 4: Inspect the rendered markdown text**

Run:

```powershell
Get-Content -Path README.md -Encoding UTF8 -TotalCount 180
```

Expected: The first screen shows the simplified daily workflow before advanced details.

- [ ] **Step 5: Commit top-level README update**

Run:

```powershell
git add README.md
git commit -m "Clarify daily sync workflow in README"
```

Expected: Commit succeeds and only `README.md` is included.

---

### Task 2: Tighten App README Visibility

**Files:**
- Modify: `apps/README.md`
- Modify: `apps/wecom_smartsheet_qiyeweixin/README.md`
- Modify: `apps/schedule_paichan/README.md`

- [ ] **Step 1: Read current app docs**

Run:

```powershell
Get-Content -Path apps\README.md -Encoding UTF8
Get-Content -Path apps\wecom_smartsheet_qiyeweixin\README.md -Encoding UTF8 -TotalCount 220
Get-Content -Path apps\schedule_paichan\README.md -Encoding UTF8
```

Expected: Confirms WeCom README already has `B00A` as daily entry and schedule README already has `B05A -> B05B`.

- [ ] **Step 2: Update `apps/README.md` summary**

Change the scenario table so it uses these daily entries:

```markdown
| 场景 | 日常入口 |
|---|---|
| 企业微信标准同步 | `wecom_smartsheet_qiyeweixin/B00A_wecom_smartsheet_manager_qiyeweixin.py --mode 0 --non-interactive` |
| 企业微信双公司同步排错 | `wecom_smartsheet_qiyeweixin/B02A_wecom_smartsheet_sync_two_companies_qiyeweixin.py` |
| 飞书多维表格同步 | `feishu_bitable_feishu/F01_feishu_bitable_sync_feishu.py` |
| 生成排产结果 | 依次运行 `schedule_paichan/B05A`、`schedule_paichan/B05B` |
| 填充 Excel 排产卡片 | `schedule_paichan/B06`，仅 Windows + Excel 需要 |
```

Add one short sentence after the table:

```markdown
其他拆分脚本主要用于单步排错、字段检查或兼容旧流程，日常不用逐个打开。
```

- [ ] **Step 3: Add WeCom troubleshooting order if missing**

In `apps/wecom_smartsheet_qiyeweixin/README.md`, add this compact section after the recommended data flow:

```markdown
## 同步排错顺序

1. `data/wecom/manual_smartsheet_links.xlsx`：确认链接是否填写、是否启用。
2. `smartsheet_registry.json`：确认 `docid`、`sheet_id`、`env_profile` 是否正确。
3. `output/latest/wecom_smartsheet_profile_verification.xlsx`：确认归属公司验证结果。
4. `data/wecom/smartsheet/<docid>/<sheet_id>/records_merged_latest.json`：确认记录缓存是否刷新。
5. `output/latest/wecom_two_company_sync_summary.json`：确认最近一次同步摘要和错误码。
6. `output/latest/document_inventory.xlsx`：用表格方式核对所有登记表和缓存表状态。
```

- [ ] **Step 4: Add schedule core outputs if missing**

In `apps/schedule_paichan/README.md`, add this compact section after common commands:

```markdown
## 排产核心输出

| 文件 | 用途 |
|---|---|
| `output/latest/tasks_prepared.json` | B05A 生成的标准化任务，是排产问题的第一检查点 |
| `output/latest/tasks_prepared.csv` | 方便人工查看的任务表 |
| `output/latest/排产_layout.json` | B05B 生成的布局数据 |
| `output/latest/schedule_web.html` | 日常查看的网页排产看板 |
```

- [ ] **Step 5: Inspect app docs**

Run:

```powershell
Get-Content -Path apps\README.md -Encoding UTF8
Get-Content -Path apps\wecom_smartsheet_qiyeweixin\README.md -Encoding UTF8 -TotalCount 120
Get-Content -Path apps\schedule_paichan\README.md -Encoding UTF8
```

Expected: Daily entries appear before advanced entries; B06 is clearly optional.

- [ ] **Step 6: Commit app README updates**

Run:

```powershell
git add apps\README.md apps\wecom_smartsheet_qiyeweixin\README.md apps\schedule_paichan\README.md
git commit -m "Clarify app entry points and sync troubleshooting"
```

Expected: Commit succeeds and only these README files are included.

---

### Task 3: Clarify Runtime Data Directories

**Files:**
- Modify: `data/README.md`
- Modify: `output/README.md`
- Modify: `production_data_shengchan/README.md`

- [ ] **Step 1: Read current runtime docs**

Run:

```powershell
Get-Content -Path data\README.md -Encoding UTF8
Get-Content -Path output\README.md -Encoding UTF8
Get-Content -Path production_data_shengchan\README.md -Encoding UTF8
```

Expected: Confirms each directory already has a purpose but can be made more operator-focused.

- [ ] **Step 2: Update `data/README.md` with cache rules**

Add this near the top:

````markdown
## 日常可见性

这里是程序缓存和状态区，日常不需要逐层打开。只有同步异常时才检查：

```text
data/wecom/manual_smartsheet_links.xlsx
data/wecom/smartsheet/<docid>/<sheet_id>/fields_latest.json
data/wecom/smartsheet/<docid>/<sheet_id>/records_merged_latest.json
```

不要手工改 `data/wecom/smartsheet/**` 下的缓存文件；需要新增表格时，优先维护 `manual_smartsheet_links.xlsx`，再运行企业微信标准同步入口。
````

- [ ] **Step 3: Update `output/README.md` with latest-first rules**

Add this near the top:

````markdown
## 日常只看 latest

日常确认结果时优先打开：

```text
output/latest/schedule_web.html
output/latest/document_inventory.xlsx
output/latest/wecom_two_company_sync_summary.json
output/latest/tasks_prepared.json
```

`output/archive/` 只用于追溯历史版本，不作为日常入口。带时间戳的文件如果出现在 `output/` 根目录，应由现有输出清理逻辑归档到 `output/archive/`。
````

- [ ] **Step 4: Update `production_data_shengchan/README.md` with root-file rule**

Add this near the top:

````markdown
## 根目录业务文件归位

真实生产 CSV、XLSX、人工导出的业务资料不要放在项目根目录。根目录出现这类文件时，优先移动到本目录，并保留原文件名，方便回溯来源。

示例：

```text
生产任务排期_提取任务.csv
```
````

- [ ] **Step 5: Inspect runtime docs**

Run:

```powershell
Get-Content -Path data\README.md -Encoding UTF8 -TotalCount 120
Get-Content -Path output\README.md -Encoding UTF8 -TotalCount 140
Get-Content -Path production_data_shengchan\README.md -Encoding UTF8 -TotalCount 120
```

Expected: Each README now tells the operator when to look there and when to ignore it.

- [ ] **Step 6: Commit runtime README updates**

Run:

```powershell
git add data\README.md output\README.md production_data_shengchan\README.md
git commit -m "Document runtime data visibility rules"
```

Expected: Commit succeeds and only these README files are included.

---

### Task 4: Move Local Root-Level Runtime Files

**Files:**
- Move locally: `生产任务排期_提取任务.csv`
- Move locally: `generated_env.txt`
- Move locally: `.env.backup_20260429_104845`
- Create local directory if missing: `legacy/local_runtime_archive/`

- [ ] **Step 1: Confirm target files are untracked**

Run:

```powershell
git ls-files -- generated_env.txt "生产任务排期_提取任务.csv" .env.backup_20260429_104845
```

Expected: No output. If any path appears, stop and adjust the plan because the file move needs to be committed or explicitly skipped.

- [ ] **Step 2: Create the local archive directory**

Run:

```powershell
New-Item -ItemType Directory -Force -Path legacy\local_runtime_archive
```

Expected: Directory exists. This directory is for local-only root clutter and should not require committing sensitive files.

- [ ] **Step 3: Move the production CSV if present**

Run:

```powershell
if (Test-Path -LiteralPath "生产任务排期_提取任务.csv") {
  Move-Item -LiteralPath "生产任务排期_提取任务.csv" -Destination "production_data_shengchan\生产任务排期_提取任务.csv"
}
```

Expected: The CSV no longer appears in the root and appears under `production_data_shengchan/`.

- [ ] **Step 4: Move old generated environment helper if present**

Run:

```powershell
if (Test-Path -LiteralPath "generated_env.txt") {
  Move-Item -LiteralPath "generated_env.txt" -Destination "legacy\local_runtime_archive\generated_env.txt"
}
```

Expected: `generated_env.txt` no longer appears in the root and appears under `legacy/local_runtime_archive/`.

- [ ] **Step 5: Move old env backup if present**

Run:

```powershell
if (Test-Path -LiteralPath ".env.backup_20260429_104845") {
  Move-Item -LiteralPath ".env.backup_20260429_104845" -Destination "legacy\local_runtime_archive\.env.backup_20260429_104845"
}
```

Expected: `.env.backup_20260429_104845` no longer appears in the root and appears under `legacy/local_runtime_archive/`.

- [ ] **Step 6: Inspect root files**

Run:

```powershell
Get-ChildItem -Force -File | Select-Object Name,Length,LastWriteTime
```

Expected: Root still has `.env`, `.env.example`, `.gitignore`, `README.md`, `requirements.txt`, `smartsheet_registry.example.json`, and local `smartsheet_registry.json`, but no longer has `生产任务排期_提取任务.csv`, `generated_env.txt`, or `.env.backup_20260429_104845`.

- [ ] **Step 7: Confirm git did not pick up local data moves**

Run:

```powershell
git status --short
```

Expected: No new tracked production CSV or local env backup is staged. If `legacy/local_runtime_archive/` appears only because it contains ignored files, leave it uncommitted.

---

### Task 5: Verify The Conservative Cleanup

**Files:**
- Verify docs and existing tests

- [ ] **Step 1: Run lightweight tests**

Run:

```powershell
python -m pytest tests/test_wecom_manual_links.py -q
```

Expected: Test passes. If pytest is unavailable, run:

```powershell
C:\Python\python.exe -m pytest tests/test_wecom_manual_links.py -q
```

Expected: Test passes.

- [ ] **Step 2: Verify key scripts still show help or import cleanly**

Run:

```powershell
python apps/wecom_smartsheet_qiyeweixin/B00A_wecom_smartsheet_manager_qiyeweixin.py --help
python apps/wecom_smartsheet_qiyeweixin/B02A_wecom_smartsheet_sync_two_companies_qiyeweixin.py --help
python apps/schedule_paichan/B05A_schedule_prepare_paichan.py --help
python apps/schedule_paichan/B05B_schedule_build_frame_paichan.py --help
```

Expected: If a script does not implement `--help`, it may print its normal startup text or error on missing runtime data. Do not run network sync during this verification. The goal is to catch syntax/import breakage after doc-only changes and local moves.

- [ ] **Step 3: Inspect final git status**

Run:

```powershell
git status --short
```

Expected: Only unrelated pre-existing worktree changes remain, or the README/doc commits are cleanly recorded. No real production data or credentials should be staged.

- [ ] **Step 4: Summarize final operator view**

Prepare the final response with:

```text
Updated docs:
- README.md
- apps/README.md
- apps/wecom_smartsheet_qiyeweixin/README.md
- apps/schedule_paichan/README.md
- data/README.md
- output/README.md
- production_data_shengchan/README.md

Moved local files:
- 生产任务排期_提取任务.csv -> production_data_shengchan/
- generated_env.txt -> legacy/local_runtime_archive/
- .env.backup_20260429_104845 -> legacy/local_runtime_archive/

Verification:
- pytest command result
- git status summary
```
