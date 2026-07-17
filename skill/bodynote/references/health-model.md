# Health Model

Read this reference when structuring health records or generating scores, confidence, insights, and actions.

## Event Types

- `blood_pressure`: systolic, diastolic, and optional heart rate.
- `blood_glucose`: mmol/L value and fasting/postprandial context.
- `meal`: meal type, foods, calories, protein, fat, carbs, sodium, fiber.
- `exercise`: activity, duration, calories, heart rate, body parts, sets, reps, volume.
- `body`: weight, body fat, muscle, waist, and body-composition metrics.
- `sleep`: duration, quality, bedtime, wake time, and recovery signals.
- `mood`: label, intensity, time scope, and optional attribution.
- `symptom`: symptom, body part, severity, duration, and red-flag fields.
- `menstrual_cycle`: dates, flow, symptoms, phase hint, and confidence.
- `medical_report`: date, type, indicators, findings, and action candidates.

Keep raw source files local. Preserve the original text and confidence beside derived fields.

## Score and Confidence

Calculate two separate values:

- `health_score`: current state based on available evidence.
- `confidence`: completeness and reliability of the evidence.

Use four health modules:

| Module | Initial weight |
| --- | ---: |
| Movement | 25 |
| Nutrition | 25 |
| Body state | 20 |
| Recovery, mood, and cycle | 15 |

Normalize the health score across modules with available evidence. Do not award or remove points for an unavailable or inapplicable module; reduce confidence instead. Keep the owner's goal visible in the result without pretending that free-text goal adherence can always be scored precisely.

Map status as an initial display convention:

- Green: 80-100.
- Yellow: 60-79.
- Red: below 60 or a rule-based safety concern.

Do not let a score hide urgent symptom handling.

## Missing Data

Missing information should produce:

- Lower confidence.
- A specific supplement request.
- A visible note in the report.

Missing information should not automatically produce a red state unless the missing field is required for safe handling.

## Insight Cards

Generate at most three daily cards. Supported types:

- `completion`, `gap`, `risk`, `explanation`, `trend`, `correlation`, `suggestion`, `achievement`.

Each card should include type, severity, title, explanation, evidence, confidence, and one next action. Prefer associations such as "可能相关" and "值得继续观察" over causal claims.

## Evidence Thresholds

- Do not infer fat or muscle change from one day.
- Flag training imbalance only after a repeated pattern.
- Keep menstrual-cycle insights low confidence until at least two cycles are recorded.
- Link medical indicators to lifestyle only when timing and evidence align.
- Treat subjective fatigue as one signal alongside sleep, training, food, stress, and cycle context.

Weekly output uses a seven-day trend, movement structure, meal timing pattern, recovery pattern, and body-change summary. Monthly output requires at least eight record days for trend language; otherwise return `evidence_level: summary_only`.
