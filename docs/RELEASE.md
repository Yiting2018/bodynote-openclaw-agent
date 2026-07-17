# 发布检查

1. 运行全部测试，包括 Pillow/reportlab 渲染测试。
2. 渲染日报 PNG 和三类 PDF，检查中文、分页、重叠和裁切。
3. 在桌面和移动视口检查驾驶舱。
4. 运行 `maintenance migrate` 和备份恢复测试。
5. 运行 `privacy audit --project-root .`，确保没有 high finding。
6. 运行 `release build --project-root . --output dist`。
7. 检查 zip 中的 `RELEASE-MANIFEST.json`，确认无数据库、配置、报告、备份、缓存或密钥。
8. 安装 Skill 后检查 `status --json` 能力声明。
9. 经 owner 确认后安装 cron，并用 `openclaw cron show` 检查路由。
10. 分别在飞书和 QQ 私聊/群聊做一次 PNG/PDF 收件验证；QQ guild channel 验证文字降级。
