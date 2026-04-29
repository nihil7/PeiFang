"""
程序简介：保留历史流程或实验逻辑，仅供追溯参考，主流程优先使用 apps 或 tools 下的新入口。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

from runpy import run_path


if __name__ == "__main__":
    run_path("apps/feishu_bitable_feishu/feishu_scripts_feishu/拿仪表盘id.py", run_name="__main__")

