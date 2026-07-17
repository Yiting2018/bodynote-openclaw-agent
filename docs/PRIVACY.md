# 隐私模型

## 数据所有权

一套 `BODYNOTE_HOME` 只对应一个 owner。OpenClaw 负责配对、allowlist、会话范围和跨渠道身份绑定；BodyNote 不保存飞书、QQ 账号映射或渠道密钥。

## 本地文件

- 运行目录和报告目录权限为 owner-only。
- SQLite、配置和备份文件权限为 `0600`。
- 报告默认不启动网络服务。
- 备份包含健康数据，清单中标记为 sensitive，不包含报告文件。

## 附件交付

报告生成结果提供结构化 `attachments` 数组。OpenClaw 只能发送其中列出的 PNG、PDF 或 HTML。开启 workspace-only 文件限制时，通过 `--delivery-dir .bodynote-delivery` 暂存副本。

飞书支持图片和文件。QQ 私聊及群聊支持本地富媒体；QQ guild channel 不支持本地文件上传，因此降级为文字摘要，不为此开放公网报告地址。

## 发布阻断

`privacy audit` 会检查运行权限、网络与第三方交付配置，以及项目中的数据库、密钥、运行配置和生成报告。存在 high finding 时，`release build` 拒绝打包。
