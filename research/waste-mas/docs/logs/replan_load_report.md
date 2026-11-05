# Распределение нагрузки — прогон replan

Статус: **approved**. Всего вызовов инструментов и LLM: **35**. Максимальная доля агента: **28.6%** (лимит 40%) — ✅ соблюдён

| Агент | Вызовов агента | Инструменты | LLM | Всего | Доля |
|---|---:|---:|---:|---:|---:|
| data | 1 | 3 | 0 | 3 | 8.6% |
| forecast | 1 | 5 | 0 | 5 | 14.3% |
| priority | 2 | 6 | 0 | 6 | 17.1% |
| report | 1 | 3 | 0 | 3 | 8.6% |
| route | 2 | 10 | 0 | 10 | 28.6% |
| verifier | 2 | 8 | 0 | 8 | 22.9% |

Оркестратор не вызывает инструментов: только планирует и рассылает задачи.

Трасса: data.ingest → forecast.forecast → priority.prioritize → route.plan_routes → verifier.verify → priority.defer → route.plan_routes → verifier.verify → report.report
