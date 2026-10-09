# Архитектура и алгоритмы

`models.py` задаёт Reading, BinState, Trip, Config и Context.
`data.py` отвечает за проверку CSV и генерацию демонстрационного набора.
`agents.py` содержит пять агентов и оркестратор. `export.py` формирует отчёты,
`cli.py` отделяет пользовательский интерфейс от вычислений.

## Прогноз

Для дат t_i и заполненности y_i агент считает наклон МНК:

`b = max(0, sum((t_i-mean(t))*(y_i-mean(y))) / sum((t_i-mean(t))**2))`.

Время измеряется в днях от первой даты; пропуски между датами сохраняются.
Прогноз: `min(100, latest_fill + b * horizon_days)`.
Используется наклон линейной регрессии с привязкой прогноза к последнему наблюдению.
При двух агентах прогноз равен текущему заполнению.

## Решения и маршруты

Отбор: predicted_pct >= threshold. Critical >=95%; high >=threshold;
medium >=60% среди невыбранных; low <60% среди невыбранных.
Категория critical может обозначать очень высокую заполненность даже при пороге выше 95%.
Отбор всегда определяется `selected`, а не строкой категории.
Объём: capacity_m3 * predicted_pct / 100.
В каждом рейсе выбирается ближайший допустимый по остаточной вместимости контейнер.
Если ни один оставшийся контейнер не помещается, машина возвращается в депо,
разгружается и начинает следующий рейс. Начальная и конечная точки — депо.
Контейнер с объёмом больше вместимости машины приводит к понятной ошибке.
Дистанция рассчитывается формулой Haversine, радиус Земли 6371.0088 км.

## Проверка научного результата

Для каждого контейнера все даты кроме последней являются train.
Последняя дата — holdout. Прогноз строится на временной интервал до holdout.
MAE = mean(abs(prediction - actual)), единица — процентный пункт.
Persistence baseline предсказывает последнее значение train без роста.
Все индивидуальные ошибки сохраняются в report.json.
Это одна временная контрольная точка, а не полноценная внешняя валидация.

## Расширение

```python
from smart_waste.agents import AnalysisAgent, PriorityAgent, run_pipeline
from smart_waste.data import load_csv
from smart_waste.models import Context, Config
from pathlib import Path

class OverflowAlertAgent:
    name = "overflow_alert"

    def run(self, context: Context) -> None:
        """Attach an explainable alert count to the research result."""
        context.metrics["overflow_alerts"] = sum(
            state.predicted_pct >= 95 for state in context.states
        )

context = Context(load_csv(Path("data/astana_synthetic.csv")), Config())
run_pipeline(context, agents=[AnalysisAgent(), PriorityAgent(), OverflowAlertAgent()])
print(context.metrics)
```

Порядок custom agents должен соответствовать зависимостям: анализ до прогноза,
приоритеты до маршрутов. Оркестратор исполняет список и сохраняет trace.

