"""
程序简介：把排产任务和布局数据渲染成可查看的 HTML 页面，供后续网页集成或人工核对。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

from __future__ import annotations

import html
from pathlib import Path

from .common import date_label, write_text


def _esc(value: object) -> str:
    return html.escape(str(value or ""))


def _rgb_css(value: object) -> str:
    if isinstance(value, list) and len(value) >= 3:
        try:
            r, g, b = [max(0, min(255, int(x))) for x in value[:3]]
            return f"rgb({r}, {g}, {b})"
        except Exception:
            pass
    return "#f1f5f9"


def _date_mmdd(iso: object) -> str:
    text = str(iso or "")
    if len(text) >= 10:
        return text[5:10]
    return text


def _card_lines(item: dict) -> list[str]:
    lines = [str(item.get("line1") or ""), str(item.get("line2") or ""), str(item.get("line3") or "")]
    lines = [line.strip() for line in lines if line and line.strip()]
    if lines:
        return lines
    raw = str(item.get("text_raw") or "").strip()
    return [raw] if raw else ["未命名任务"]


def _item_detail_text(item: dict) -> str:
    parts = [
        f"机台：{item.get('machine') or ''}",
        f"日期：{item.get('start_date') or ''} - {item.get('end_date') or ''}",
        f"任务：{item.get('text_raw') or ''}",
        f"记录：{item.get('task_id') or ''}",
    ]
    return "\n".join(parts)


def render_schedule_html(layout_payload: dict, out_path: str | Path) -> Path:
    dates = layout_payload.get("dates") or []
    items = layout_payload.get("items") or []
    machines = layout_payload.get("machines") or []
    today = str(layout_payload.get("today") or "")

    machine_options = "\n".join(
        f'<option value="{_esc(machine)}">{_esc(machine)}</option>' for machine in machines
    )

    date_headers = "\n".join(
        f"""
        <div class="date-cell{' today' if iso == today else ''}">
          <span class="date-main">{_esc(_date_mmdd(iso))}</span>
          <span class="date-sub">{_esc(date_label(iso))}</span>
        </div>
        """
        for iso in dates
    )

    machine_sections: list[str] = []
    list_sections: list[str] = []

    for machine in machines:
        machine_items = [item for item in items if item.get("machine") == machine]
        lanes = sorted({int(item.get("lane", 0) or 0) for item in machine_items}) or [0]
        lane_markup: list[str] = []

        for lane in lanes:
            lane_cards: list[str] = []
            lane_items = [entry for entry in machine_items if int(entry.get("lane", 0) or 0) == lane]
            for item in sorted(lane_items, key=lambda row: (int(row.get("col_start", 0)), int(row.get("col_end", 0)))):
                start = max(1, int(item.get("col_start", 2)) - 1)
                span = max(1, int(item.get("col_end", start)) - int(item.get("col_start", start)) + 1)
                lines = _card_lines(item)
                lines_html = "".join(f"<div>{_esc(line)}</div>" for line in lines)
                detail = _esc(_item_detail_text(item))
                label = _esc(f"{item.get('start_date') or ''} - {item.get('end_date') or ''}")
                lane_cards.append(
                    f"""
                    <article
                      class="task-card"
                      style="grid-column:{start} / span {span}; background:{_rgb_css(item.get('rgb'))};"
                      title="{detail}">
                      <div class="task-lines">{lines_html}</div>
                      <footer>{label}</footer>
                    </article>
                    """
                )

            lane_markup.append(
                f"""
                <div class="lane-grid" aria-label="{_esc(machine)} lane {lane + 1}">
                  {''.join(lane_cards)}
                </div>
                """
            )

        machine_sections.append(
            f"""
            <section class="machine-section" data-machine="{_esc(machine)}">
              <div class="machine-title">{_esc(machine)}</div>
              <div class="machine-lanes">{''.join(lane_markup)}</div>
            </section>
            """
        )

        list_cards: list[str] = []
        for item in sorted(machine_items, key=lambda row: (str(row.get("start_date") or ""), int(row.get("lane", 0) or 0))):
            lines = _card_lines(item)
            line_html = "".join(f"<div>{_esc(line)}</div>" for line in lines)
            list_cards.append(
                f"""
                <article class="list-card" style="border-left-color:{_rgb_css(item.get('rgb'))};" title="{_esc(_item_detail_text(item))}">
                  <time>{_esc(_date_mmdd(item.get('start_date')))} - {_esc(_date_mmdd(item.get('end_date')))}</time>
                  <div class="list-lines">{line_html}</div>
                </article>
                """
            )

        list_sections.append(
            f"""
            <section class="list-machine" data-machine="{_esc(machine)}">
              <h2>{_esc(machine)}</h2>
              <div class="list-cards">{''.join(list_cards) if list_cards else '<p class="empty">暂无任务</p>'}</div>
            </section>
            """
        )

    title = _esc(layout_payload.get("title") or "排产看板")
    generated_at = _esc(layout_payload.get("generated_at") or "")
    win_start = _esc(layout_payload.get("win_start") or "")
    win_end = _esc(layout_payload.get("win_end") or "")
    day_count = max(1, len(dates))
    task_count = len(items)
    machine_count = len(machines)

    body = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{title}</title>
  <style>
    :root {{
      --bg: #f6f8fb;
      --surface: #ffffff;
      --surface-soft: #f8fafc;
      --text: #172033;
      --muted: #667085;
      --line: #d8e0ea;
      --line-strong: #b9c5d4;
      --accent: #0f766e;
      --today: #fff7d6;
      --machine-width: 112px;
      --day-width: 164px;
      --lane-height: 78px;
      --radius: 8px;
    }}
    * {{ box-sizing: border-box; }}
    html {{ color-scheme: light; }}
    body {{
      margin: 0;
      font-family: "Microsoft YaHei", "PingFang SC", "Segoe UI", sans-serif;
      color: var(--text);
      background: var(--bg);
    }}
    .page {{
      min-height: 100vh;
      padding: 18px;
    }}
    .topbar {{
      display: flex;
      align-items: end;
      justify-content: space-between;
      gap: 16px;
      margin: 0 0 14px;
    }}
    .title-block h1 {{
      margin: 0;
      font-size: 22px;
      line-height: 1.2;
      letter-spacing: 0;
    }}
    .meta {{
      margin-top: 6px;
      color: var(--muted);
      font-size: 13px;
    }}
    .toolbar {{
      display: flex;
      align-items: center;
      gap: 8px;
      flex-wrap: wrap;
      justify-content: flex-end;
    }}
    .toolbar select,
    .toolbar button {{
      height: 34px;
      border: 1px solid var(--line);
      background: var(--surface);
      color: var(--text);
      border-radius: 7px;
      padding: 0 10px;
      font: inherit;
      font-size: 13px;
    }}
    .toolbar button {{
      cursor: pointer;
    }}
    .toolbar button.active {{
      border-color: var(--accent);
      background: #e7f5f2;
      color: #075e57;
      font-weight: 700;
    }}
    .summary {{
      display: grid;
      grid-template-columns: repeat(3, minmax(0, 1fr));
      gap: 10px;
      margin-bottom: 14px;
    }}
    .summary-item {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 10px 12px;
    }}
    .summary-item span {{
      display: block;
      color: var(--muted);
      font-size: 12px;
    }}
    .summary-item strong {{
      display: block;
      margin-top: 4px;
      font-size: 18px;
    }}
    .board-shell {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      overflow: hidden;
    }}
    .board-scroll {{
      overflow: auto;
      max-height: calc(100vh - 170px);
      overscroll-behavior: contain;
    }}
    .timeline {{
      --day-count: {day_count};
      min-width: calc(var(--machine-width) + var(--day-count) * var(--day-width));
      width: max-content;
      background:
        linear-gradient(90deg, transparent var(--machine-width), rgba(216,224,234,0.65) var(--machine-width), transparent calc(var(--machine-width) + 1px));
    }}
    .date-strip {{
      position: sticky;
      top: 0;
      z-index: 20;
      display: grid;
      grid-template-columns: var(--machine-width) repeat({day_count}, var(--day-width));
      border-bottom: 1px solid var(--line-strong);
      background: var(--surface);
    }}
    .corner-cell,
    .date-cell {{
      min-height: 52px;
      border-right: 1px solid var(--line);
      display: flex;
      align-items: center;
      justify-content: center;
      text-align: center;
      padding: 8px;
      font-weight: 700;
    }}
    .corner-cell {{
      position: sticky;
      left: 0;
      z-index: 30;
      background: var(--surface-soft);
    }}
    .date-cell {{
      flex-direction: column;
      gap: 2px;
      background: var(--surface);
    }}
    .date-cell.today {{
      background: var(--today);
      color: #7a4f00;
    }}
    .date-main {{
      font-size: 15px;
    }}
    .date-sub {{
      color: var(--muted);
      font-size: 11px;
      font-weight: 600;
    }}
    .machine-section {{
      display: grid;
      grid-template-columns: var(--machine-width) 1fr;
      border-bottom: 1px solid var(--line-strong);
    }}
    .machine-section:last-child {{
      border-bottom: 0;
    }}
    .machine-title {{
      position: sticky;
      left: 0;
      z-index: 10;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: var(--lane-height);
      padding: 8px;
      background: var(--surface-soft);
      border-right: 1px solid var(--line-strong);
      font-weight: 700;
      text-align: center;
    }}
    .machine-lanes {{
      display: grid;
    }}
    .lane-grid {{
      display: grid;
      grid-template-columns: repeat({day_count}, var(--day-width));
      min-height: var(--lane-height);
      border-bottom: 1px solid var(--line);
      background-image: linear-gradient(90deg, transparent calc(var(--day-width) - 1px), var(--line) calc(var(--day-width) - 1px), var(--line) var(--day-width));
      background-size: var(--day-width) 100%;
    }}
    .lane-grid:last-child {{
      border-bottom: 0;
    }}
    .task-card {{
      min-height: 58px;
      margin: 8px 6px;
      padding: 8px 10px;
      border: 1px solid rgba(23,32,51,0.14);
      border-radius: 7px;
      overflow: hidden;
      align-self: stretch;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      box-shadow: 0 1px 2px rgba(16,24,40,0.08);
    }}
    .task-lines {{
      color: #111827;
      font-weight: 700;
      line-height: 1.25;
      font-size: 13px;
    }}
    .task-lines div {{
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .task-lines div:nth-child(2) {{
      color: #155e75;
    }}
    .task-lines div:nth-child(3) {{
      color: #9f1239;
      font-size: 12px;
    }}
    .task-card footer {{
      margin-top: 5px;
      color: rgba(17,24,39,0.62);
      font-size: 11px;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }}
    .list-view {{
      display: none;
      margin-top: 14px;
    }}
    .list-machine {{
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      margin-bottom: 10px;
      overflow: hidden;
    }}
    .list-machine h2 {{
      margin: 0;
      padding: 10px 12px;
      background: var(--surface-soft);
      border-bottom: 1px solid var(--line);
      font-size: 15px;
    }}
    .list-cards {{
      display: grid;
      gap: 8px;
      padding: 10px;
    }}
    .list-card {{
      border: 1px solid var(--line);
      border-left: 6px solid #cbd5e1;
      border-radius: 7px;
      padding: 9px 10px;
      background: #fff;
    }}
    .list-card time {{
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 4px;
    }}
    .list-lines {{
      font-weight: 700;
      line-height: 1.35;
      font-size: 14px;
    }}
    .empty {{
      margin: 0;
      color: var(--muted);
      font-size: 13px;
    }}
    .page.list-mode .board-shell {{
      display: none;
    }}
    .page.list-mode .list-view {{
      display: block;
    }}
    .page.board-mode .board-shell {{
      display: block;
    }}
    .page.board-mode .list-view {{
      display: none;
    }}
    [hidden] {{
      display: none !important;
    }}
    @media (min-width: 1500px) {{
      :root {{
        --day-width: 184px;
        --lane-height: 84px;
      }}
    }}
    @media (max-width: 1100px) {{
      :root {{
        --day-width: 150px;
        --machine-width: 96px;
      }}
      .summary {{
        grid-template-columns: repeat(3, minmax(120px, 1fr));
        overflow-x: auto;
      }}
    }}
    @media (max-width: 760px) {{
      .page {{
        padding: 12px;
      }}
      .topbar {{
        align-items: stretch;
        flex-direction: column;
      }}
      .toolbar {{
        justify-content: flex-start;
      }}
      .summary {{
        grid-template-columns: 1fr;
      }}
      .board-shell {{
        display: none;
      }}
      .list-view {{
        display: block;
      }}
      .page.board-mode .board-shell {{
        display: block;
      }}
      .page.board-mode .list-view {{
        display: none;
      }}
      .board-scroll {{
        max-height: 68vh;
      }}
      .title-block h1 {{
        font-size: 20px;
      }}
    }}
  </style>
</head>
<body>
  <main class="page board-mode" id="page">
    <header class="topbar">
      <div class="title-block">
        <h1>{title}</h1>
        <div class="meta">窗口：{win_start} 至 {win_end}；生成时间：{generated_at}</div>
      </div>
      <div class="toolbar" aria-label="看板工具">
        <select id="machineFilter" aria-label="机台筛选">
          <option value="">全部机台</option>
          {machine_options}
        </select>
        <button type="button" id="boardBtn" class="active">看板</button>
        <button type="button" id="listBtn">列表</button>
      </div>
    </header>

    <section class="summary" aria-label="排产概览">
      <div class="summary-item"><span>机台</span><strong>{machine_count}</strong></div>
      <div class="summary-item"><span>任务</span><strong>{task_count}</strong></div>
      <div class="summary-item"><span>日期</span><strong>{day_count}</strong></div>
    </section>

    <section class="board-shell" aria-label="排产看板">
      <div class="board-scroll">
        <div class="timeline">
          <section class="date-strip">
            <div class="corner-cell">机台 / 日期</div>
            {date_headers}
          </section>
          {''.join(machine_sections)}
        </div>
      </div>
    </section>

    <section class="list-view" aria-label="排产列表">
      {''.join(list_sections)}
    </section>
  </main>
  <script>
    const page = document.getElementById('page');
    const boardBtn = document.getElementById('boardBtn');
    const listBtn = document.getElementById('listBtn');
    const machineFilter = document.getElementById('machineFilter');

    function setMode(mode) {{
      page.classList.toggle('board-mode', mode === 'board');
      page.classList.toggle('list-mode', mode === 'list');
      boardBtn.classList.toggle('active', mode === 'board');
      listBtn.classList.toggle('active', mode === 'list');
    }}

    function applyMachineFilter() {{
      const selected = machineFilter.value;
      document.querySelectorAll('[data-machine]').forEach((section) => {{
        section.hidden = Boolean(selected) && section.dataset.machine !== selected;
      }});
    }}

    boardBtn.addEventListener('click', () => setMode('board'));
    listBtn.addEventListener('click', () => setMode('list'));
    machineFilter.addEventListener('change', applyMachineFilter);

    if (window.matchMedia('(max-width: 760px)').matches) {{
      setMode('list');
    }}
  </script>
</body>
</html>
"""
    return write_text(out_path, body)
