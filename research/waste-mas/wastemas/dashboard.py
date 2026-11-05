"""Self-contained HTML dashboard (no CDN, no JavaScript, works offline)."""
from __future__ import annotations

import html

SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
STATUS = {"critical": "#d03b3b", "high": "#ec835a", "medium": "#fab219", "low": "#9a998f"}
CAT_RU = {"critical": "критический", "high": "высокий", "medium": "средний", "low": "низкий"}

CSS = """
.viz-root{color-scheme:light;--surface-1:#fcfcfb;--surface-2:#f3f2ee;--text-primary:#0b0b0b;
--text-secondary:#52514e;--grid:#e1e0d9;--axis:#c3c2b7;--border:rgba(11,11,11,.10);--accent:#2a78d6;--good:#006300;--bad:#d03b3b}
@media (prefers-color-scheme:dark){.viz-root{color-scheme:dark;--surface-1:#1a1a19;--surface-2:#232322;
--text-primary:#f0efec;--text-secondary:#c3c2b7;--grid:#2c2c2a;--axis:#383835;--border:rgba(255,255,255,.10);--accent:#3987e5;--good:#0ca30c;--bad:#e66767}}
*{box-sizing:border-box}body{margin:0;font:14px/1.5 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.viz-root{background:var(--surface-1);color:var(--text-primary);min-height:100vh;padding:28px clamp(16px,4vw,48px)}
h1{font-size:22px;margin:0 0 4px}h2{font-size:16px;margin:28px 0 10px}.muted{color:var(--text-secondary)}
.badge{display:inline-flex;gap:6px;align-items:center;padding:3px 10px;border-radius:999px;font-weight:600;border:1px solid var(--border)}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-top:18px}
.tile{background:var(--surface-2);border:1px solid var(--border);border-radius:10px;padding:12px 14px}
.tile .v{font-size:26px;font-weight:650;font-variant-numeric:tabular-nums}.tile .l{color:var(--text-secondary);font-size:12.5px}
.summary{background:var(--surface-2);border-left:3px solid var(--accent);padding:12px 16px;border-radius:6px;white-space:pre-line;margin-top:16px}
.grid2{display:grid;grid-template-columns:minmax(0,3fr) minmax(0,2fr);gap:24px}@media(max-width:900px){.grid2{grid-template-columns:1fr}}
.card{border:1px solid var(--border);border-radius:10px;padding:14px;background:var(--surface-1)}
table{border-collapse:collapse;width:100%;font-size:13px;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:5px 8px;border-bottom:1px solid var(--grid)}th{color:var(--text-secondary);font-weight:600}
td.n,th.n{text-align:right}.dot{display:inline-block;width:9px;height:9px;border-radius:50%;margin-right:6px;vertical-align:middle}
.legend{display:flex;flex-wrap:wrap;gap:14px;font-size:12.5px;color:var(--text-secondary);margin-top:8px}
.scroll{max-height:420px;overflow:auto}svg text{fill:var(--text-secondary);font-size:11px}
.mapbg{fill:var(--surface-2)}.gridl{stroke:var(--grid)}.ok{color:var(--good)}.bad{color:var(--bad)}
"""


def _e(v) -> str:
    return html.escape(str(v), quote=True)


def _map(bundle: dict) -> str:
    fc = {f["bin_id"]: f for f in bundle["forecasts"]}
    cat = {d["bin_id"]: d["category"] for d in bundle["decisions"]}
    depot = bundle["plan"]["depot"]
    lats = [f["latitude"] for f in fc.values()] + [depot[0]]
    lons = [f["longitude"] for f in fc.values()] + [depot[1]]
    w, h, pad = 640, 420, 28
    la0, la1, lo0, lo1 = min(lats), max(lats), min(lons), max(lons)
    sx = lambda lo: pad + (lo - lo0) / ((lo1 - lo0) or 1) * (w - 2 * pad)
    sy = lambda la: h - pad - (la - la0) / ((la1 - la0) or 1) * (h - 2 * pad)
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Карта контейнеров и рейсов">',
             f'<rect class="mapbg" x="0" y="0" width="{w}" height="{h}" rx="8"/>']
    for i in range(1, 4):
        parts.append(f'<line class="gridl" x1="{w*i/4}" y1="0" x2="{w*i/4}" y2="{h}"/>'
                     f'<line class="gridl" x1="0" y1="{h*i/4}" x2="{w}" y2="{h*i/4}"/>')
    for t in bundle["plan"]["trips"]:
        color = SERIES[(t["trip_id"] - 1) % len(SERIES)]
        pts = [depot] + [(fc[b]["latitude"], fc[b]["longitude"]) for b in t["bin_ids"]] + [depot]
        path = " ".join(f"{sx(lo):.1f},{sy(la):.1f}" for la, lo in pts)
        parts.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="2" '
                     f'stroke-linejoin="round" opacity=".9"><title>Рейс {t["trip_id"]} · машина {t["truck"]} · '
                     f'{t["distance_km"]} км · {t["load_m3"]:.2f} м³</title></polyline>')
        if t["bin_ids"]:
            f0 = fc[t["bin_ids"][0]]
            parts.append(f'<text x="{sx(f0["longitude"])+7:.1f}" y="{sy(f0["latitude"])-7:.1f}" '
                         f'style="font-weight:700">Р{t["trip_id"]}</text>')
    for b, f in fc.items():
        c = cat[b]
        r = 6 if c in ("critical", "high") else 4
        parts.append(f'<circle cx="{sx(f["longitude"]):.1f}" cy="{sy(f["latitude"]):.1f}" r="{r}" '
                     f'fill="{STATUS[c]}" stroke="var(--surface-1)" stroke-width="2"><title>{_e(b)} · '
                     f'{_e(f["district"])} · сейчас {f["fill_pct"]}% → прогноз {f["predicted_pct"]}% · '
                     f'{CAT_RU[c]}</title></circle>')
    parts.append(f'<rect x="{sx(depot[1])-7:.1f}" y="{sy(depot[0])-7:.1f}" width="14" height="14" rx="2" '
                 f'fill="var(--text-primary)"><title>Депо</title></rect>'
                 f'<text x="{sx(depot[1])+10:.1f}" y="{sy(depot[0])+4:.1f}">депо</text></svg>')
    legend = "".join(f'<span><span class="dot" style="background:{STATUS[k]}"></span>{v}</span>'
                     for k, v in CAT_RU.items())
    legend += "".join(f'<span><span class="dot" style="background:{SERIES[(t["trip_id"]-1) % 8]};border-radius:2px">'
                      f'</span>Рейс {t["trip_id"]}</span>' for t in bundle["plan"]["trips"])
    return "".join(parts) + f'<div class="legend">{legend}</div>'


def _load_chart(load: dict) -> str:
    agents = load["agents"]
    if not agents:
        return "<p class='muted'>Нет данных</p>"
    w, row, left, right = 460, 30, 90, 60
    h = row * len(agents) + 30
    scale = lambda s: left + s / 0.5 * (w - left - right)
    parts = [f'<svg viewBox="0 0 {w} {h}" width="100%" role="img" aria-label="Доля вызовов по агентам">']
    for i, (name, a) in enumerate(agents.items()):
        y = 10 + i * row
        parts.append(f'<text x="{left-8}" y="{y+14}" text-anchor="end">{_e(name)}</text>'
                     f'<rect x="{left}" y="{y+3}" width="{max(2, scale(a["share"])-left):.1f}" height="16" rx="4" '
                     f'fill="#2a78d6"><title>{_e(name)}: {a["total_calls"]} вызовов, {a["share"]:.1%}</title></rect>'
                     f'<text x="{scale(a["share"])+6:.1f}" y="{y+15}">{a["share"]:.0%}</text>')
    x40 = scale(0.40)
    parts.append(f'<line x1="{x40:.1f}" y1="4" x2="{x40:.1f}" y2="{h-18}" stroke="#d03b3b" stroke-dasharray="4 3"/>'
                 f'<text x="{x40:.1f}" y="{h-4}" text-anchor="middle">лимит 40%</text></svg>')
    return "".join(parts)


def render_dashboard(bundle: dict, load: dict) -> str:
    f, v = bundle["facts"], bundle["verdict"]
    ok = v["approved"]
    mae = v["backtest"]["mae_pp"]
    badge = (f'<span class="badge ok">✔ План утверждён</span>' if ok else
             f'<span class="badge bad">✖ План не утверждён: {_e(f["violations"])}</span>')
    fc = {x["bin_id"]: x for x in bundle["forecasts"]}
    trip_of = {b: t["trip_id"] for t in bundle["plan"]["trips"] for b in t["bin_ids"]}
    rows = "".join(
        f'<tr><td>{_e(d["bin_id"])}</td><td>{_e(fc[d["bin_id"]]["district"])}</td>'
        f'<td class="n">{d["fill_pct"]:.1f}</td><td class="n">{d["predicted_pct"]:.1f}</td>'
        f'<td><span class="dot" style="background:{STATUS[d["category"]]}"></span>{CAT_RU[d["category"]]}</td>'
        f'<td>{"перенос" if d["deferred"] else "да" if d["selected"] else "—"}</td>'
        f'<td class="n">{trip_of.get(d["bin_id"], "")}</td><td>{_e(d["reason"])}</td></tr>'
        for d in bundle["decisions"])
    trips = "".join(f'<tr><td>Р{t["trip_id"]}</td><td>{t["truck"]}</td><td class="n">{len(t["bin_ids"])}</td>'
                    f'<td class="n">{t["load_m3"]:.2f}</td><td class="n">{t["distance_km"]:.2f}</td>'
                    f'<td>{_e(" → ".join(t["bin_ids"]))}</td></tr>' for t in bundle["plan"]["trips"])
    viol = "".join(f"<li>{_e(x['code'])}: {_e({k: val for k, val in x.items() if k != 'code'})}</li>"
                   for x in v["violations"]) or "<li>нарушений нет</li>"
    warn = "".join(f"<li>{_e(w)}</li>" for w in v.get("warnings", []))
    mae_rows = "".join(f'<tr><td>{_e(k)}</td><td class="n">{"—" if val is None else f"{val:.3f}"}</td></tr>'
                       for k, val in mae.items())
    cfg = bundle["config"]
    off = ", ".join(f["off_days_in_horizon"]) or "нет"
    src = {"llm": "LLM", "template": "шаблон"}[bundle["summary_source"]]
    note = f'<p class="muted">{_e(bundle["summary_note"])}</p>' if bundle.get("summary_note") else ""
    return f"""<!doctype html><html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Waste MAS — план вывоза</title>
<style>{CSS}</style></head><body><div class="viz-root">
<h1>План вывоза ТБО — Астана, {_e(f["target_date"])}</h1>
<div class="muted">Прогон {_e(bundle["run_id"])} · порог {cfg["threshold_pct"]}% · горизонт {cfg["horizon_days"]} дн. ·
{cfg["trucks"]} маш. × {cfg["trips_per_truck"]} рейса × {cfg["truck_capacity_m3"]} м³ · нерабочие дни в горизонте: {_e(off)}</div>
<p>{badge}</p>
<div class="tiles">
<div class="tile"><div class="v">{f["bins_selected"]} / {f["bins_total"]}</div><div class="l">контейнеров к вывозу</div></div>
<div class="tile"><div class="v">{f["trips"]} / {cfg["trucks"]*cfg["trips_per_truck"]}</div><div class="l">рейсов / доступно</div></div>
<div class="tile"><div class="v">{f["distance_km"]}</div><div class="l">км по прямой (после 2-opt)</div></div>
<div class="tile"><div class="v">{f["volume_m3"]}</div><div class="l">м³ к вывозу</div></div>
<div class="tile"><div class="v">{"—" if mae["calendar_model"] is None else f'{mae["calendar_model"]:.2f}'}</div>
<div class="l">MAE прогноза, п.п. (наивный: {"—" if mae["persistence"] is None else f'{mae["persistence"]:.2f}'})</div></div>
</div>
<div class="summary"><b>Сводка ({src}).</b>
{_e(bundle["summary"])}</div>{note}
<div class="grid2"><div><h2>Карта рейсов</h2><div class="card">{_map(bundle)}</div></div>
<div><h2>Нагрузка на агентов</h2><div class="card">{_load_chart(load)}
<p class="muted">Вызовов инструментов и LLM на момент формирования отчёта: {load["total_calls"]} (без финальной записи файлов; итог — load_report.md). Максимум {load["max_share"]:.1%} при лимите 40%.</p></div>
<h2>Проверяющий агент</h2><div class="card"><ul>{viol}</ul>{f"<ul>{warn}</ul>" if warn else ""}
<table><tr><th>Метод (контрольная дата {_e(v["backtest"]["holdout_date"])})</th><th class="n">MAE, п.п.</th></tr>{mae_rows}</table></div></div></div>
<h2>Рейсы</h2><div class="card"><table><tr><th>Рейс</th><th>Машина</th><th class="n">Конт.</th><th class="n">м³</th>
<th class="n">км</th><th>Порядок объезда</th></tr>{trips or '<tr><td colspan="6">Нет рейсов</td></tr>'}</table></div>
<h2>Решения по контейнерам</h2><div class="card scroll"><table><tr><th>ID</th><th>Район</th><th class="n">Сейчас, %</th>
<th class="n">Прогноз, %</th><th>Категория</th><th>Вывоз</th><th class="n">Рейс</th><th>Причина</th></tr>{rows}</table></div>
<h2>Трасса агентов</h2><p class="muted">{_e(" → ".join(bundle["trace"]))}</p>
<p class="muted">Данные синтетические, расстояния по прямой. Не является измерением акимата.</p>
</div></body></html>"""
