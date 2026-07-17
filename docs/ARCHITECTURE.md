# 架构边界

## 产品定义

BodyNote 是被 OpenClaw 调用的本地健康工作流，不是独立聊天应用，也不管理飞书、QQ 等渠道连接。

```text
飞书 / QQ / 其他渠道
        |
        v
OpenClaw
- pairing / allowlist
- session.dmScope
- session.identityLinks
- 定时触发和消息交付
        |
        v
BodyNote Skill
- 判断何时调用
- 规定数据、安全和输出流程
        |
        v
BodyNote Agent
- SQLite 健康记录
- 查漏补缺
- 健康分、置信度和洞察
- HTML / PNG / PDF 报告
- 备份、迁移和隐私审计
```

## 单用户原则

- 一套 BodyNote 运行目录只对应一个健康主体，固定标识为 `owner`。
- 飞书和 QQ 的跨渠道身份关联由 OpenClaw 完成。
- BodyNote 不保存外部账号、渠道密钥或联系人白名单。
- 其他人需要独立的 OpenClaw Agent/workspace 和独立 `BODYNOTE_HOME`。

## 数据边界

仓库只保存代码、模板、规则和测试夹具。真实运行数据放在 `BODYNOTE_HOME`，默认是 `~/.bodynote`：

```text
~/.bodynote/
├── config.toml
├── data/bodynote.sqlite3
├── reports/
└── logs/
```

报告生成时只读取当前运行目录中的单一 owner 档案。默认不开放局域网访问，不自动向第三方渠道发送文件。

发送附件时，可将允许发送的 PNG/PDF/HTML 副本暂存到 OpenClaw Agent 工作区的 `.bodynote-delivery`。原数据库、`report.json`、manifest 和原始记录目录不进入发送清单。

## AI 边界

- 核心记录、评分、缺失判断、安全升级和报告数据模型必须可以确定性运行。
- OpenClaw 负责自然语言交互和渠道能力。
- 可选模型只用于非关键字段提取、自然语言解释和文案润色。
- 模型不可覆盖确定性安全规则，不可补造缺失健康数据。

## 报告边界

- 日报回答今天怎样、为什么、明天做什么。
- 周报回答七日结构、模式和可持续性。
- 月报回答身体变化、目标进展、证据等级和下月核心行动。
- 三种报告共用规范化事件，但各自拥有独立数据模型和版式。
