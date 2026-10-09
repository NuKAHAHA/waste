# Проверка реализации

Дата: 9 октября 2026 года.

## Локально

- `python -m unittest discover -s tests -v`: 30 тестов, OK.
- `python -m compileall -q smart_waste tests`: OK.
- `python main.py demo`: 24 контейнера, 8 выбрано, 2 рейса.
- `python tools/build_release.py`: автономный ZIP создан.
- `python tools/check_release.py`: тесты и демо из распакованного ZIP прошли.

Проверяемые свойства: holdout без утечки, известный линейный прогноз, интервалы дат,
возврат в депо, ограничения объёма, обслуживание ровно один раз, валидация данных,
побайтная воспроизводимость и безопасный экспорт подписей.

## GitHub Actions

Подтверждённый run: https://github.com/NuKAHAHA/waste/actions/runs/37919752690
Статус: success.

| Job | Результат |
| --- | --- |
| Ubuntu / Python 3.11 | success |
| Ubuntu / Python 3.13 | success |
| Windows / Python 3.12 | success |
| Deliver | success; ZIP и результаты доступны в artifact |

Pull request: https://github.com/NuKAHAHA/waste/pull/1 — merged.

CI выполнялся в реальном GitHub Actions, а не только проверялся как YAML.
Workflow Smart Waste Release повторяет тесты и публикует ZIP при добавлении VERSION
в main или ручном запуске. Отдельная доставка через Actions artifact проверена.
Релизы: https://github.com/NuKAHAHA/waste/releases

## Формат аналитического отчёта

DOCX задаёт Times New Roman, 12 pt, интервал 1.5 и выравнивание основного текста по ширине.
PDF экспортирован с метрически совместимым Liberation Serif, поскольку Times New Roman
отсутствует в среде экспорта. Для строгого требования к названию шрифта открыть DOCX
в Microsoft Word на Windows с Times New Roman и экспортировать в PDF.

