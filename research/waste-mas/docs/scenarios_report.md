# Результаты тестовых сценариев

Пройдено **18 из 18** (100%).

| ID | Сценарий | Ожидание | Факт | Шаги | Вызовы | Макс. доля | Итог |
|---|---|---|---|---:|---:|---:|---|
| S01 | Типовой сценарий (демо) | status=approved, replans=0, min_selected=5, max_share_le=0.4, all_critical_served=True | approved: План утверждён проверяющим агентом | 6 | 23 | 22% | ✅ |
| S02 | Горизонт 2 дня через праздничный перенос | status=approved, min_selected=10, off_days_include=2026-10-26 | approved: План утверждён проверяющим агентом | 6 | 23 | 22% | ✅ |
| S03 | Качество прогноза: календарь лучше базовых методов | status=approved, mae_order=True, mae_model_le=1.5 | approved: План утверждён проверяющим агентом | 6 | 23 | 22% | ✅ |
| S04 | Нехватка рейсов → перепланирование | status=approved, replans_ge=1, deferred_nonempty=True, all_critical_served=True, max_share_le=0.4 | approved: План утверждён проверяющим агентом | 9 | 35 | 29% | ✅ |
| S05 | Невыполнимый план: критических больше, чем вмещает парк | status=rejected, exit_code=1, message_contains=fleet_limit | rejected: План не утверждён: fleet_limit | 9 | 35 | 29% | ✅ |
| S06 | Контейнер больше вместимости машины | status=error, exit_code=2, message_contains=вместимости | error: Объём контейнера больше вместимости машины; увеличьте --truck-capacity | 4 | 14 | 36% | ✅ |
| S07 | Некорректные данные: заполненность 150% | status=error, message_contains=Строка | error: Строка 6: заполненность вне диапазона 0..100% | 1 | 2 | 100% | ✅ |
| S08 | Файл телеметрии не найден | status=error, message_contains=не найден | error: Файл не найден: /tmp/sc2/S08/no_such_file.csv | 1 | 1 | 100% | ✅ |
| S09 | Дубликат измерения | status=error, message_contains=дубликат | error: Строка 4: дубликат контейнер/дата | 1 | 2 | 100% | ✅ |
| S10 | Неверный заголовок CSV | status=error, message_contains=Колонки | error: Колонки CSV должны быть: bin_id,district,latitude,longitude,capacity_m3,observed_on,fill_pct | 1 | 1 | 100% | ✅ |
| S11 | Разные последние даты у контейнеров | status=error, message_contains=последняя дата | error: У всех контейнеров должна быть общая последняя дата | 1 | 2 | 100% | ✅ |
| S12 | Лимит шагов (защита от зацикливания) | status=aborted, message_contains=лимит шагов | aborted: Превышен лимит шагов (3) | 3 | 11 | 45% | ✅ |
| S13 | Лимит времени | status=aborted, message_contains=времени | aborted: Превышен лимит времени 1e-06 с | 1 | 0 | 0% | ✅ |
| S14 | LLM формирует сводку | status=approved, summary_source=llm, llm_calls=1, max_share_le=0.4 | approved: План утверждён проверяющим агентом | 6 | 23 | 22% | ✅ |
| S15 | Защита от галлюцинаций LLM | status=approved, summary_source=template, guard_events=1 | approved: План утверждён проверяющим агентом | 6 | 24 | 21% | ✅ |
| S16 | LLM недоступна → повторы и запасной вариант | status=approved, summary_source=template, retries_ge=2 | approved: План утверждён проверяющим агентом | 6 | 24 | 21% | ✅ |
| S17 | Другой датасет (seed=7) | status=approved, max_share_le=0.4, all_critical_served=True | approved: План утверждён проверяющим агентом | 6 | 23 | 22% | ✅ |
| S18 | Низкий порог 60%: больше вывоза | status=approved, min_selected=15, max_share_le=0.4 | approved: План утверждён проверяющим агентом | 6 | 23 | 22% | ✅ |
