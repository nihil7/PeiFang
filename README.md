# 配方排产项目

这个仓库保留脚本代码，但不会上传真实密钥、生产数据、业务 CSV，或本地运行生成的注册表与输出文件。

## 仓库里保留什么

- Python 脚本与子项目源码
- 可提交的配置样例
- 最小示例数据，方便理解输入输出结构
- 空目录占位，方便本地继续运行和让 Codex 识别目录用途

## 不会上传什么

- `.env` 和任何子目录下的 `.env`
- `smartsheet_registry.json`
- `生产数据/` 里的真实导出文件
- `output/` 下的运行结果
- 根目录真实业务核对 CSV

## 首次使用

1. 安装依赖

```bash
pip install -r requirements.txt
```

2. 复制环境变量模板

```bash
copy .env.example .env
```

3. 按你的企业微信/飞书配置填写 `.env`

4. 如果要跑企业微信智能表格脚本，先复制注册表样例

```bash
copy smartsheet_registry.example.json smartsheet_registry.json
```

5. 如果你只是想离线理解数据结构，把 `examples/output/` 里的样例复制到本地 `output/` 后再运行后续脚本

## 推荐流程

### 企业微信智能表格流程

1. `B01 新建智能表.py`
作用：创建或刷新智能表格，并在本地生成 `smartsheet_registry.json`

2. `B02 fetcher获取数据.py`
作用：根据 `smartsheet_registry.json` 拉取字段和记录，保存到 `output/`

3. `B05A_prepare_data.py`
作用：把 `output/*.records.raw.json` 处理成排产任务 JSON/CSV

4. `B05B_build_frame.py`
作用：根据 prepared 数据生成排产框架 Excel 和 layout JSON

5. `B06_填充卡片.py`
作用：基于 layout 和框架 Excel 插入卡片图形

### 飞书相关脚本

`飞书/` 和 `feishu_local_bot/` 是单独的飞书方向工具。`feishu_local_bot/` 已自带自己的 `.env.example` 和说明文档。

## 样例文件

- `smartsheet_registry.example.json`
示例版智能表格注册表，展示 `docid / sheet_id / sheets` 结构

- `examples/output/生产任务排期__排产·统计总台账__sample.fields.json`
示例字段结构

- `examples/output/生产任务排期__排产·统计总台账__sample.records.raw.json`
示例原始记录结构

- `examples/output/tasks_prepared_sample.json`
示例 prepared 数据结构

- `examples/生产任务排期_提取任务.sample.csv`
示例核对 CSV

## 本地目录约定

- `生产数据/`
真实导出数据目录，不进仓库；仓库里只保留占位说明文件

- `output/`
运行产物目录，不进仓库

## 给 Codex 的约定

- 需要真实运行企业微信相关脚本时，默认读取本地 `.env` 与 `smartsheet_registry.json`
- 需要理解数据结构、补脚本或改文档时，优先读取 `examples/` 中的样例文件
- 不要把 `生产数据/`、`output/`、真实 `.env`、真实 `smartsheet_registry.json` 提交到 Git
