# 企业微信智能表格入口

这个目录保存企业微信智能表格相关的可运行脚本，主要用于回调校验、表格登记、数据同步和接口结构检查。

| 文件 | 功能 | 常见用途 |
|---|---|---|
| `B00_wecom_verify_server_qiyeweixin.py` | 启动企业微信回调校验服务，用配置中的 token 和 AESKey 验证服务器回调 | 配置企微接收消息服务器 URL 时验证链路 |
| `B01_wecom_smartsheet_registry_qiyeweixin.py` | 整理企业微信智能表格登记信息，生成本地 `smartsheet_registry.json` | 新增或刷新智能表格登记信息 |
| `B02_wecom_smartsheet_sync_qiyeweixin.py` | 默认 `full` 完整同步字段、记录和状态到 `data/`，也支持 `auto`、`recent`、`verify` | 日常同步企业微信表格数据 |
| `B03_wecom_smartsheet_templates_qiyeweixin.py` | 读取字段和样例数据，辅助生成排产模板或调试字段结构 | 调整表字段、模板或排产字段映射前检查结构 |
| `B04_wecom_smartsheet_read_qiyeweixin.py` | 直接读取指定智能表格内容 | 排查接口返回、字段和值结构 |

## 常用命令

```powershell
python apps/wecom_smartsheet_qiyeweixin/B02_wecom_smartsheet_sync_qiyeweixin.py
python apps/wecom_smartsheet_qiyeweixin/B02_wecom_smartsheet_sync_qiyeweixin.py --mode full
python apps/wecom_smartsheet_qiyeweixin/B02_wecom_smartsheet_sync_qiyeweixin.py --mode auto
python apps/wecom_smartsheet_qiyeweixin/B02_wecom_smartsheet_sync_qiyeweixin.py --mode recent --recent-limit 50
python apps/wecom_smartsheet_qiyeweixin/B02_wecom_smartsheet_sync_qiyeweixin.py --mode verify
```

不带参数运行时会完整拉取目标智能表格。同步结果摘要中的 `is_full_fetch=true` 表示本次已取完整数据。

完整同步成功后，会额外生成便于人工核对的完整表格：

```text
output/latest/wecom_smartsheet_full.xlsx
output/latest/wecom_smartsheet_full.csv
```

## 多公司切换

在 `.env` 里用 `WECOM_ENV_PROFILE` 选择当前企业微信公司：

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
```

切换到另一家公司时，只改：

```dotenv
WECOM_ENV_PROFILE=COMPANY_B
```

脚本会优先读取带公司名的变量；如果没设置公司档案，仍兼容旧的 `WECOM_CORP_ID`、`WECOM_APP_SECRET`、`WEDOC_DOCID`、`SMARTSHEET_ID` 等变量。

## 企业可信 IP

截图里的“企业可信 IP”配置的是调用企业微信接口的服务器公网出口 IP，不是域名验证。你的服务器在美国、域名无法备案时，日常拉取智能表格数据可以走这条路：把阿里云服务器的固定公网 IPv4、EIP 或 NAT 网关出口 IP 填进去。

在 Linux 服务器上查看公网出口 IP：

```bash
curl -4 https://api.ipify.org
```

如果服务器有 EIP，填 EIP；如果通过 NAT 网关出网，填 NAT 网关绑定的 EIP；如果后面用了代理或负载均衡，填最终访问 `qyapi.weixin.qq.com` 的出口 IP。多个 IP 用英文分号 `;` 分隔。

`B00_wecom_verify_server_qiyeweixin.py` 只用于“接收消息服务器 URL”回调校验，需要一个能被企业微信访问到的 HTTP/HTTPS 地址；它不能替代“企业可信 IP”。设置可信 IP 后，直接在服务器运行 `B02_wecom_smartsheet_sync_qiyeweixin.py` 测试即可。

## 相关核心模块

- `peifang_core/wecom.py`：企业微信 token、字段、记录同步和本地缓存逻辑。
- `peifang_core/common.py`：路径、JSON 读写、记录合并和多公司环境配置。
