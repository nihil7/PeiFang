# 制造计算工具

这个目录保存制造计算相关的独立脚本，通常按编号顺序处理。

| 文件 | 功能 |
|---|---|
| `T010_extract_source_bom_goujianbili.py` | 从原始数据提取 BOM 或构件比例，生成后续矩阵处理输入 |
| `T020_matrix_juzhen.py` | 基于提取结果构建或整理矩阵数据 |
| `T021_insert_structure_frame_zijianbiaozhun.py` | 插入结构框架和子件标准名称，规范生产计算表 |
| `T030_purchase_cost_caigou.py` | 计算采购价格和成本，输出可核对结果 |
| `T040_sales_profit_xiaoshou.py` | 基于成本和销售价格计算利润 |

## 使用建议

这些脚本更像独立工具箱，不是主排产链路的必经步骤。运行前先打开脚本顶部配置区，确认输入文件、输出文件和字段名。
