"""Portable JSON, CSV and self-contained HTML scientific outputs."""
import csv
import hashlib
import html
import json
from dataclasses import asdict
from pathlib import Path

from . import __version__
from .models import Context


def export_results(context: Context, out: Path, source: Path) -> dict:
    """Write reproducible outputs; no clocks, CDN, JavaScript or network calls."""
    out.mkdir(parents=True, exist_ok=True)
    report = {"version": __version__, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "data_notice": "Dataset provenance must be checked; bundled demo data is synthetic.",
              "distance_notice": "Straight-line distances, not road routes.",
              "config": asdict(context.config), "agents": context.trace,
              "metrics": context.metrics,
              "containers": [asdict(s) | {"as_of": s.as_of.isoformat(), "load_m3": s.load_m3}
                             for s in context.states],
              "trips": [asdict(t) for t in context.trips]}
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2,
                                                allow_nan=False) + "\n", encoding="utf-8")
    fields = ("bin_id", "district", "fill_pct", "predicted_pct", "priority", "selected", "load_m3")
    with (out / "priorities.csv").open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in report["containers"]:
            # Prevent spreadsheet formula interpretation for imported labels.
            safe = dict(row)
            for key in ("bin_id", "district"):
                if safe[key].startswith(("=", "+", "-", "@")):
                    safe[key] = "'" + safe[key]
            writer.writerow(safe)
    (out / "dashboard.html").write_text(render_html(report), encoding="utf-8")
    return report


def render_html(report: dict) -> str:
    """Render accessible tables and proportional fill bars in offline HTML."""
    escape = html.escape
    rows, bars = [], []
    for row in report["containers"]:
        bin_id, district = escape(row["bin_id"]), escape(row["district"])
        rows.append(f'<tr><td>{bin_id}</td><td>{district}</td><td>{row["fill_pct"]:.1f}%</td>'
                    f'<td>{row["predicted_pct"]:.1f}%</td><td>{escape(row["priority"])}</td>'
                    f'<td>{"Да" if row["selected"] else "Нет"}</td></tr>')
        bars.append(f'<div class="bar-row"><span>{bin_id}</span><div class="track">'
                    f'<div class="fill" style="width:{row["fill_pct"]:.2f}%"></div>'
                    f'<div class="forecast" style="width:{row["predicted_pct"]:.2f}%"></div></div>'
                    f'<span>{row["predicted_pct"]:.1f}%</span></div>')
    trips = "".join(f'<tr><td>{t["trip_id"]}</td><td>{escape(" → ".join(t["bin_ids"]))}</td>'
                    f'<td>{t["load_m3"]:.2f}</td><td>{t["distance_km"]:.2f}</td></tr>'
                    for t in report["trips"])
    metrics = report["metrics"]
    mae = metrics.get("forecast_mae_pp")
    evaluation = (f'Прогноз MAE: {mae:.3f} п.п. · Базовый прогноз: '
                  f'{metrics["persistence_mae_pp"]:.3f} п.п. · Контейнеров: {metrics["holdout_n"]}'
                  if mae is not None else "Режим 2 агентов: прогноз, маршруты и оценка отключены.")
    return f'''<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Smart Waste Astana — результаты эксперимента</title><style>
:root{{font-family:system-ui,sans-serif;color:#173c34;background:#f1f5f2}}body{{margin:0}}
main{{max-width:1120px;margin:auto;padding:40px 24px}}h1{{font-size:36px;margin:10px 0}}h2{{margin-top:0}}
.tag{{text-transform:uppercase;letter-spacing:2px;font-size:12px}}.muted{{color:#557069}}
.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin:28px 0}}
.card,section{{background:white;border:1px solid #dbe5df;border-radius:16px;padding:22px}}
.card strong{{display:block;font-size:32px;margin:10px 0}}section{{margin:18px 0}}
.notice{{border-left:4px solid #dbad42;background:#fff8e4;padding:16px;border-radius:8px}}
.scroll{{overflow-x:auto}}table{{border-collapse:collapse;width:100%;font-size:14px}}
th,td{{text-align:left;padding:12px;border-bottom:1px solid #e5ede8}}th{{background:#f1f5f2}}
.chart{{display:grid;grid-template-columns:1fr 1fr;gap:8px 28px}}.bar-row{{display:grid;grid-template-columns:76px 1fr 52px;gap:8px;align-items:center;font-size:12px}}
.track{{height:16px;background:#edf3ef;position:relative;border-radius:4px;overflow:hidden}}
.fill{{height:10px;position:absolute;z-index:2;background:#276a52;top:3px}}.forecast{{height:16px;background:#c4dfd2}}
@media(max-width:700px){{.cards{{grid-template-columns:1fr 1fr}}.chart{{grid-template-columns:1fr}}h1{{font-size:28px}}}}
</style></head><body><main><div class="tag">Research module · Assignment 3</div>
<h1>Smart Waste Astana</h1><p class="muted">Воспроизводимый анализ заполненности и планирование вывоза</p>
<div class="notice">Демонстрационный CSV содержит <strong>синтетические данные</strong>. Точки и депо вымышлены.
Расстояния рассчитываются по прямой и не являются дорожными маршрутами.</div>
<div class="cards"><div class="card">Контейнеров<strong>{metrics["bins_total"]}</strong></div>
<div class="card">К вывозу<strong>{metrics["bins_selected"]}</strong></div>
<div class="card">Рейсов<strong>{metrics["trips_total"]}</strong></div>
<div class="card">По прямой, км<strong>{metrics.get("route_distance_km", 0):.1f}</strong></div></div>
<section><h2>Заполненность и прогноз</h2><p class="muted">Тёмная полоса — наблюдение; светлая — прогноз.
Горизонт {report["config"]["horizon_days"]:g} дн.; порог вывоза {report["config"]["threshold_pct"]:g}%.</p>
<div class="chart">{"".join(bars)}</div></section>
<section><h2>Приоритеты вывоза</h2><div class="scroll"><table><thead><tr><th>Контейнер</th><th>Район</th>
<th>Сейчас</th><th>Прогноз</th><th>Приоритет</th><th>К вывозу</th></tr></thead><tbody>{"".join(rows)}</tbody></table></div></section>
<section><h2>Рейсы с возвратом в депо</h2><div class="scroll"><table><thead><tr><th>Рейс</th><th>Порядок посещения</th>
<th>Объём, м³</th><th>Длина, км</th></tr></thead><tbody>{trips}</tbody></table></div></section>
<section><h2>Проверка прогноза на последней дате</h2><p>{evaluation}</p>
<p class="muted">Последняя дата исключена из обучения. Метрики описывают только переданный набор данных.</p></section>
<p class="muted">Агенты: {escape(" → ".join(report["agents"]))} · Версия {escape(report["version"])}<br>
SHA256 входного CSV: {escape(report["source_sha256"])}</p></main></body></html>'''

