# peifang_core 目录说明

`peifang_core/` 是共享核心包。入口脚本负责命令行和流程编排，核心目录负责可复用逻辑。

| 文件 | 功能 |
|---|---|
| `__init__.py` | 标记 `peifang_core` 为可导入包 |
| `common.py` | 项目路径、JSON/文本读写、记录排序合并、时间处理、多公司环境配置档案读取 |
| `wecom.py` | 企业微信智能表格 token、字段、记录同步和本地缓存 |
| `feishu.py` | 飞书多维表格标识解析、字段和记录同步、本地缓存 |
| `schedule_web.py` | 把排产任务和布局数据渲染成可查看的 HTML 页面 |

## 调用关系

| 入口 | 主要调用 |
|---|---|
| `apps/wecom_smartsheet_qiyeweixin/B02_wecom_smartsheet_sync_qiyeweixin.py` | `peifang_core.wecom.sync_smartsheet` |
| `apps/feishu_bitable_feishu/F01_feishu_bitable_sync_feishu.py` | `peifang_core.feishu.sync_bitable` |
| `apps/schedule_paichan/B05B_schedule_build_frame_paichan.py` | `peifang_core.schedule_web.render_schedule_html` |
| `apps/schedule_paichan/B06_schedule_fill_cards_paichan.py` | `peifang_core.schedule_web.render_schedule_html` |
