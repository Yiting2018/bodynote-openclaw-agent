# Owner Reference Guides

Use this workflow when the owner uploads a guide, textbook excerpt, public guideline,
or personal training note and asks BodyNote to use it in future analysis.

1. Confirm the owner wants this source included and may lawfully use the supplied copy.
2. Read only the owner-selected source through OpenClaw.
3. Extract concise structured notes: title, source type, version, scope, rules, and citations.
4. Show the extracted card to the owner and obtain confirmation before saving it.
5. Store the card with `bodynote-agent reference add --input ... --json`.
6. Keep the original document outside BodyNote unless the owner explicitly manages it elsewhere.

Example card:

```json
{
  "title": "个人抗阻训练参考",
  "source_type": "user_note",
  "version": "2026-07",
  "scope": ["strength", "recovery"],
  "rules": [
    {"topic": "progression", "note": "结合个人恢复状态逐步调整训练量"}
  ],
  "citations": [
    {"label": "用户整理的训练原则", "section": "渐进与恢复"}
  ],
  "enabled": true
}
```

Guide cards can enrich explanations and owner-selected goal analysis. They cannot
override red-flag handling, invent missing data, diagnose conditions, prescribe
treatment, or convert a short association into a causal conclusion. Cite the guide
title and the stored citation label when its rule materially affects an explanation.
