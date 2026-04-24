from __future__ import annotations

import html
from pathlib import Path

from .common import date_label, write_text


def render_schedule_html(layout_payload: dict, out_path: str | Path) -> Path:
    dates = layout_payload.get("dates") or []
    items = layout_payload.get("items") or []
    machines = layout_payload.get("machines") or []

    today = None
    for iso in dates:
        if iso == layout_payload.get("today"):
            today = iso

    date_headers = "\n".join(
        f'<div class="date-cell{" today" if iso == today else ""}"><span>{html.escape(date_label(iso))}</span></div>'
        for iso in dates
    )

    machine_sections: list[str] = []
    for machine in machines:
        machine_items = [item for item in items if item.get("machine") == machine]
        lanes = sorted({int(item.get("lane", 0) or 0) for item in machine_items}) or [0]
        lane_markup = []
        for lane in lanes:
            lane_cards = []
            for item in sorted(
                [entry for entry in machine_items if int(entry.get("lane", 0) or 0) == lane],
                key=lambda row: (int(row.get("col_start", 0)), int(row.get("col_end", 0))),
            ):
                start = max(1, int(item.get("col_start", 2)) - 1)
                span = max(1, int(item.get("col_end", start)) - int(item.get("col_start", start)) + 1)
                rgb = item.get("rgb") or [243, 244, 246]
                bg = f"rgb({rgb[0]}, {rgb[1]}, {rgb[2]})"
                lines = [item.get("line1") or "", item.get("line2") or "", item.get("line3") or ""]
                lines_html = "".join(f"<div>{html.escape(text)}</div>" for text in lines if text)
                lane_cards.append(
                    f"""
                    <article class="task-card" style="grid-column:{start} / span {span}; background:{bg};">
                      <div class="task-lines">{lines_html or html.escape(str(item.get('text_raw') or ''))}</div>
                      <footer>{html.escape(str(item.get('start_date') or ''))} - {html.escape(str(item.get('end_date') or ''))}</footer>
                    </article>
                    """
                )
            lane_markup.append(
                f"""
                <div class="lane-grid" style="grid-template-columns: repeat({max(1, len(dates))}, minmax(120px, 1fr));">
                  {''.join(lane_cards)}
                </div>
                """
            )

        machine_sections.append(
            f"""
            <section class="machine-section">
              <div class="machine-title">{html.escape(str(machine))}</div>
              <div class="machine-lanes">
                {''.join(lane_markup)}
              </div>
            </section>
            """
        )

    title = html.escape(str(layout_payload.get("title") or "排产看板"))
    generated_at = html.escape(str(layout_payload.get("generated_at") or ""))
    body = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      --bg: #f4f7fb;
      --panel: rgba(255,255,255,0.84);
      --text: #122033;
      --muted: #5d6b82;
      --line: #dbe4ef;
      --accent: #0f7bff;
      --shadow: 0 18px 40px rgba(25, 45, 72, 0.10);
      --radius: 18px;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Microsoft YaHei", "PingFang SC", sans-serif;
      color: var(--text);
      background:
        radial-gradient(circle at top left, rgba(15,123,255,0.16), transparent 30%),
        radial-gradient(circle at top right, rgba(36,99,235,0.10), transparent 24%),
        linear-gradient(180deg, #eef4fb 0%, var(--bg) 100%);
    }}
    .page {{
      max-width: 1600px;
      margin: 0 auto;
      padding: 24px;
    }}
    .hero {{
      background: var(--panel);
      backdrop-filter: blur(10px);
      border: 1px solid rgba(255,255,255,0.7);
      border-radius: 28px;
      box-shadow: var(--shadow);
      padding: 24px 28px;
      margin-bottom: 20px;
    }}
    .hero h1 {{
      margin: 0;
      font-size: 30px;
    }}
    .hero p {{
      margin: 8px 0 0;
      color: var(--muted);
    }}
    .date-strip {{
      display: grid;
      gap: 8px;
      grid-template-columns: 220px repeat({max(1, len(dates))}, minmax(120px, 1fr));
      margin-bottom: 14px;
      position: sticky;
      top: 0;
      z-index: 10;
      padding-top: 8px;
      background: linear-gradient(180deg, rgba(244,247,251,0.96), rgba(244,247,251,0.75));
      backdrop-filter: blur(10px);
    }}
    .date-cell, .date-label {{
      min-height: 56px;
      display: flex;
      align-items: center;
      justify-content: center;
      border-radius: 14px;
      background: rgba(255,255,255,0.88);
      border: 1px solid var(--line);
      font-weight: 700;
    }}
    .date-cell.today {{
      color: var(--accent);
      border-color: rgba(15,123,255,0.35);
      box-shadow: inset 0 -3px 0 rgba(15,123,255,0.45);
    }}
    .machine-section {{
      display: grid;
      grid-template-columns: 220px minmax(0, 1fr);
      gap: 8px;
      align-items: start;
      margin-bottom: 12px;
    }}
    .machine-title {{
      position: sticky;
      left: 0;
      top: 76px;
      min-height: 92px;
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 16px;
      background: rgba(248,250,252,0.92);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      font-weight: 700;
      box-shadow: var(--shadow);
    }}
    .machine-lanes {{
      display: grid;
      gap: 8px;
    }}
    .lane-grid {{
      display: grid;
      gap: 8px;
      padding: 10px;
      border-radius: var(--radius);
      background: rgba(255,255,255,0.66);
      border: 1px solid rgba(219,228,239,0.8);
      min-height: 84px;
      box-shadow: inset 0 1px 0 rgba(255,255,255,0.7);
    }}
    .task-card {{
      border-radius: 16px;
      padding: 12px 14px;
      border: 1px solid rgba(17,24,39,0.08);
      box-shadow: 0 10px 22px rgba(15, 23, 42, 0.08);
      overflow: hidden;
      min-height: 64px;
    }}
    .task-lines {{
      font-weight: 700;
      line-height: 1.35;
      color: #111827;
    }}
    .task-lines div:nth-child(2) {{
      color: #2563eb;
      font-size: 0.95em;
    }}
    .task-lines div:nth-child(3) {{
      color: #dc2626;
      font-size: 0.9em;
    }}
    .task-card footer {{
      margin-top: 8px;
      color: rgba(17,24,39,0.66);
      font-size: 12px;
    }}
    @media (max-width: 900px) {{
      .page {{ padding: 12px; }}
      .date-strip, .machine-section {{
        grid-template-columns: 1fr;
      }}
      .machine-title {{
        position: static;
        min-height: auto;
      }}
      .lane-grid {{
        overflow-x: auto;
      }}
      .task-card {{
        min-width: 180px;
      }}
    }}
  </style>
</head>
<body>
  <main class="page">
    <section class="hero">
      <h1>{title}</h1>
      <p>生成时间：{generated_at}</p>
    </section>
    <section class="date-strip">
      <div class="date-label">机台 / 日期</div>
      {date_headers}
    </section>
    {''.join(machine_sections)}
  </main>
</body>
</html>
"""
    return write_text(out_path, body)
