# legacy 目录说明

`legacy/` 保存旧版入口、兼容包装和实验脚本。这里主要用于追溯历史逻辑，不建议作为新功能入口。

| 子目录 | 功能 |
|---|---|
| `compat_wrappers_archive/` | 旧文件名、旧路径和兼容包装归档 |
| `wecom_experiments_qiyeweixin/` | 企业微信相关实验脚本 |

## 使用建议

- 新流程优先看 `apps/` 和 `peifang_core/`。
- 需要理解历史算法或旧文件命名时，再进入这里查看。
- 如果发现这里的脚本仍在长期使用，建议迁移到 `apps/` 或 `tools/` 后再补文档。
