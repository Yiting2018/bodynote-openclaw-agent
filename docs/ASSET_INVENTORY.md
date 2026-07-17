# 现有资产盘点

## 可直接迁移或改造

| 来源 | 已有能力 | 新版本处理 |
| --- | --- | --- |
| `health-agent/app/acp_core` | 意图路由、时间解释、字段校验、安全处理 | 拆小后迁入 `workflows`，不直接复制 1800 行 orchestrator |
| `health-agent/app/db` | SQLite、健康事件、记忆、体检报告仓储 | 保留仓储思想，统一到新 schema 和单 owner 模型 |
| `health-agent/app/memory` | 长期记忆写入、检索、上下文压缩 | 第二阶段迁移，健康事实与对话记忆继续分开 |
| `health-agent/app/security` | 风险和策略检查 | 优先迁移，改为与渠道无关的健康安全层 |
| `health-agent/tests` | 打卡、问答、体检报告、安全测试 | 按新接口重写为回归测试，不复制旧测试数据库 |
| `bodynote-openclaw-skill V0.2/schema.sql` | 饮食、运动、体成分、周期、情绪、症状、报告等详细字段 | 作为领域字段参考，按迁移版本逐步规范化 |
| `V0.2/scripts/build_dashboard_data.py` | SQLite 到看板 JSON | 提取聚合逻辑，去掉旧目录和多用户绑定假设 |
| `V0.2/scripts/generate_delivery_reports.py` | HTML/JSON 月报与交付队列 | 拆分日报/周报/月报模型，增加 PNG/PDF 渲染 |
| `V0.2/web/index.html` | 本地看板原型 | 只借鉴交互和组件，不原样搬入发布版 |
| `V0.2/design` | 首页、月报、打卡卡片视觉参考 | 作为模板设计输入，重新实现移动端尺寸和色彩语义 |
| `bodynote-openclaw-skill` | 健康驾驶舱、洞察、报告、定时流程协议 | 已重新整理到新版本 `skill/bodynote/references` |

## 不迁移

- `.venv`、`__pycache__`、`.DS_Store`、构建产物。
- `.env`、飞书 App Secret、渠道本地配置。
- 所有 SQLite、备份数据库、真实记录、图片和生成报告。
- V0.1/V0.2 的演示用户、外部账号绑定和合并脚本。
- `health-agent` 中的飞书 WebSocket runner 和 IM gateway。
- 旧版直接依赖独立 AI Provider 的默认配置。
- 大型指南 PDF 和 RAG 索引；后续作为可选知识包处理。

## 迁移前缺口与本版结果

- 首次引导缺少补录和报告时间配置：已在 M2 补齐。
- 缺少统一健康分与置信度模型：已在 M3 分离实现。
- 日报、周报、月报没有独立数据模型：已在 M4-M5 分层实现。
- 移动端 PNG/PDF 自动渲染缺失：已在 M4 实现并完成视觉检查。
- Agent 调用契约和附件回传未落地：已在 M6 形成 OpenClaw 定时与交付闭环。
