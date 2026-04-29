"""
程序简介：保留历史流程或实验逻辑，仅供追溯参考，主流程优先使用 apps 或 tools 下的新入口。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

# B03 制作甘特图.py
# 生成“机台×日期排程（日历式）”：日期为列、同日任务同格堆叠、跨天分段但视觉连续、可拖动调列宽/行高
# 数据源：output 目录下的 *.fields.json + *.records.raw.json（可自动选最新一组）
#
# ✅ 支持开始/结束日期为“毫秒时间戳”（如 1768320000000）
# ✅ 同机台同一天多个任务：按更早 start_ms 排在更上面
# ✅ 同一个机台只显示一行（不出现多行/泳道）
# ✅ 机台行上下边框加粗，方便区分机台
# ✅ 跨天任务视觉连续：覆盖 td padding 和列分割线（不再断开）
# ✅ RGB 为空：透明底色仅边框；RGB 有值：填充底色
# ✅ 表头日期居中；竖向分割线更清晰
# ✅ 允许拖动调整列宽/行高，刷新保持（localStorage）

import os
import re
import sys
import json
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional, List, Dict, Any


# =========================
# 配置区（只改这里）
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# 1) 输入：不想每次改时间戳就用 AUTO_LATEST=True
AUTO_LATEST = True
FIELDS_JSON = os.path.join(OUTPUT_DIR, "生产任务排期__排产·统计总台账__20260114_230447.fields.json")
RECORDS_JSON = os.path.join(OUTPUT_DIR, "生产任务排期__排产·统计总台账__20260114_230447.records.raw.json")

# 2) 输出：必须放 output
OUTPUT_HTML = os.path.join(OUTPUT_DIR, "生产任务排期_日历排产_可调列宽_同日同格_跨天连续.html")
OUTPUT_TASKS_JSON = os.path.join(OUTPUT_DIR, "生产任务排期_提取任务_用于核对.json")

TITLE = "机台×日期排程（日历式）"

# 3) 机台排序/显示策略
MACHINE_ORDER: List[str] = ["35机", "4#65机", "1#机", "2#机"]  # 默认顺序
INCLUDE_OTHER_MACHINES = False   # False=只显示 MACHINE_ORDER；True=后面追加其它机台
HIDE_EMPTY_MACHINES = True       # True=时间范围内没任务的机台自动隐藏
HIDE_MACHINES: List[str] = []    # 永久隐藏黑名单：例 ["1#机"]

# 4) 日期范围（三选一）
#    - "THIS_WEEK": 本周（周一~周日）
#    - "ROLLING": 从过去 PAST_DAYS 到未来 FUTURE_DAYS（含今天）
#    - "CUSTOM": 自定义 START_DATE / END_DATE（任意一个为空=无边界）
DATE_PRESET = "THIS_WEEK"
PAST_DAYS = 3
FUTURE_DAYS = 14

START_DATE = None   # "2026-01-05" 或 None
END_DATE = None     # "2026-01-20" 或 None

# 无边界时的安全上限：最多生成多少天列（避免列数过大导致页面卡）
MAX_DAYS = 31


# =========================
# 工具函数
# =========================
def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)


def html_escape(x: Any) -> str:
    if x is None:
        return ""
    x = str(x)
    return (
        x.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
    )


def clamp_rgb(r: int, g: int, b: int) -> Tuple[int, int, int]:
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    return r, g, b


def parse_rgb(s: Any) -> Optional[Tuple[int, int, int]]:
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None

    m = re.match(r"rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)", s, re.I)
    if m:
        r, g, b = map(int, m.groups())
        return clamp_rgb(r, g, b)

    m = re.match(r"#?([0-9a-fA-F]{6})$", s)
    if m:
        hexv = m.group(1)
        r = int(hexv[0:2], 16)
        g = int(hexv[2:4], 16)
        b = int(hexv[4:6], 16)
        return r, g, b

    m = re.match(r"(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})$", s)
    if m:
        r, g, b = map(int, m.groups())
        return clamp_rgb(r, g, b)

    return None


def best_text_color(bg: Tuple[int, int, int]) -> str:
    r, g, b = bg
    luminance = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return "#FFFFFF" if luminance < 140 else "#111111"


def ms_to_date(ms: Any):
    # 毫秒时间戳 -> date（按 UTC 解释，避免本地时区导致日期偏移）
    if ms is None or ms == "":
        return None
    try:
        ms_int = int(ms)
    except Exception:
        return None
    dt = datetime.fromtimestamp(ms_int / 1000, tz=timezone.utc)
    return dt.date()


def first_text_cell(v: Any) -> str:
    # 文本字段常见结构：[{ "text": "...", "type":"text"}]
    if v is None:
        return ""
    if isinstance(v, list) and v:
        if isinstance(v[0], dict) and "text" in v[0]:
            return str(v[0].get("text", "")).strip()
    if isinstance(v, str):
        return v.strip()
    return ""


def weekday_cn(d):
    names = ["一", "二", "三", "四", "五", "六", "日"]
    return f"周{names[d.weekday()]}"


def pick_latest_pair(output_dir: str) -> Tuple[str, str]:
    files = os.listdir(output_dir)
    fields = [f for f in files if f.endswith(".fields.json")]
    if not fields:
        raise FileNotFoundError(f"在 {output_dir} 找不到 *.fields.json")

    fields.sort(key=lambda fn: os.path.getmtime(os.path.join(output_dir, fn)), reverse=True)
    latest_fields = fields[0]
    prefix = latest_fields[:-len(".fields.json")]
    latest_records = prefix + ".records.raw.json"
    latest_records_path = os.path.join(output_dir, latest_records)
    latest_fields_path = os.path.join(output_dir, latest_fields)

    if not os.path.exists(latest_records_path):
        records = [f for f in files if f.endswith(".records.raw.json")]
        if not records:
            raise FileNotFoundError(f"在 {output_dir} 找不到 *.records.raw.json")
        records.sort(key=lambda fn: os.path.getmtime(os.path.join(output_dir, fn)), reverse=True)
        latest_records_path = os.path.join(output_dir, records[0])

    return latest_fields_path, latest_records_path


def load_machine_order_from_fields(fields_doc: dict) -> List[str]:
    for fld in fields_doc.get("fields", []):
        raw = fld.get("raw", {})
        if raw.get("field_title") == "机台":
            opts = raw.get("property_single_select", {}).get("options", [])
            return [o.get("text") for o in opts if o.get("text")]
    return []


def extract_tasks(records_doc: dict) -> List[dict]:
    """
    严格按你指定字段：
    - 开始日期（ms）
    - 结束日期（ms）
    - 甘特图文本（text）
    - RGB（可为空）
    - 机台（single_select text）
    """
    tasks = []
    for rec in records_doc.get("records", []):
        vals = rec.get("values", {}) or {}

        machine = ""
        mv = vals.get("机台")
        if isinstance(mv, list) and mv and isinstance(mv[0], dict):
            machine = str(mv[0].get("text", "")).strip()

        text = first_text_cell(vals.get("甘特图文本"))
        rgb_str = first_text_cell(vals.get("RGB"))
        rgb_tuple = parse_rgb(rgb_str)  # None：透明底色，仅边框

        start_ms_raw = vals.get("开始日期")
        end_ms_raw = vals.get("结束日期")
        if start_ms_raw in (None, "") or end_ms_raw in (None, ""):
            continue

        try:
            start_ms = int(start_ms_raw)
            end_ms = int(end_ms_raw)
        except Exception:
            continue

        s = ms_to_date(start_ms)
        e = ms_to_date(end_ms)
        if not machine or not text or not s or not e:
            continue

        if end_ms < start_ms:
            start_ms, end_ms = end_ms, start_ms
            s, e = e, s

        tasks.append({
            "record_id": rec.get("record_id", ""),
            "machine": machine,
            "start": s,
            "end": e,
            "start_ms": start_ms,
            "end_ms": end_ms,
            "text": text,
            "rgb": rgb_tuple,
        })
    return tasks


def parse_ymd(x: Optional[str]):
    if not x:
        return None
    return datetime.strptime(x, "%Y-%m-%d").date()


def compute_window(tasks_all: List[dict]):
    today = datetime.now().date()
    data_min = min(t["start"] for t in tasks_all)
    data_max = max(t["end"] for t in tasks_all)

    if DATE_PRESET == "THIS_WEEK":
        start = today - timedelta(days=today.weekday())
        end = start + timedelta(days=6)
        return start, end

    if DATE_PRESET == "ROLLING":
        start = today - timedelta(days=PAST_DAYS)
        end = today + timedelta(days=FUTURE_DAYS)
        return start, end

    if DATE_PRESET == "CUSTOM":
        s_in = parse_ymd(START_DATE)
        e_in = parse_ymd(END_DATE)

        if s_in and e_in:
            start, end = s_in, e_in
            if (end - start).days + 1 > MAX_DAYS:
                end = start + timedelta(days=MAX_DAYS - 1)
            return start, end

        if s_in and (e_in is None):
            start = s_in
            end = min(data_max, start + timedelta(days=MAX_DAYS - 1))
            return start, end

        if (s_in is None) and e_in:
            end = e_in
            start = max(data_min, end - timedelta(days=MAX_DAYS - 1))
            return start, end

        start = data_min
        end = min(data_max, start + timedelta(days=MAX_DAYS - 1))
        return start, end

    raise ValueError("DATE_PRESET 只支持 THIS_WEEK / ROLLING / CUSTOM")


def build_dates(start, end) -> List[Any]:
    dates = []
    d = start
    while d <= end:
        dates.append(d)
        d += timedelta(days=1)
    return dates


def filter_tasks_by_window(tasks: List[dict], start, end) -> List[dict]:
    out = []
    for t in tasks:
        if t["end"] < start or t["start"] > end:
            continue
        out.append(t)
    return out


def build_machine_list(tasks_in_window: List[dict], fields_order: List[str]) -> List[str]:
    machines_in_data = sorted({t["machine"] for t in tasks_in_window})

    if MACHINE_ORDER:
        base = [m for m in MACHINE_ORDER if m not in HIDE_MACHINES]
        if INCLUDE_OTHER_MACHINES:
            base += [m for m in machines_in_data if m not in base and m not in HIDE_MACHINES]
        machines = base
    elif fields_order:
        machines = [m for m in fields_order if m not in HIDE_MACHINES]
        if INCLUDE_OTHER_MACHINES:
            machines += [m for m in machines_in_data if m not in machines and m not in HIDE_MACHINES]
    else:
        machines = [m for m in machines_in_data if m not in HIDE_MACHINES]

    if HIDE_EMPTY_MACHINES:
        has_task = {t["machine"] for t in tasks_in_window}
        machines = [m for m in machines if m in has_task]

    return machines


def split_task_to_day_segments(t: dict, win_start, win_end) -> List[dict]:
    s = max(t["start"], win_start)
    e = min(t["end"], win_end)
    if e < s:
        return []

    days = []
    d = s
    while d <= e:
        days.append(d)
        d += timedelta(days=1)

    segs = []
    for i, day in enumerate(days):
        if len(days) == 1:
            pos = "single"
        elif i == 0:
            pos = "start"
        elif i == len(days) - 1:
            pos = "end"
        else:
            pos = "mid"

        segs.append({
            "day": day,
            "pos": pos,
            "text": t["text"],
            "rgb": t["rgb"],
            "orig_start_ms": t["start_ms"],
            "orig_end_ms": t["end_ms"],
        })
    return segs


def render_html(dates: List[Any], machines: List[str], cell_map: Dict[Tuple[str, Any], List[dict]]) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    date_keys = [d.isoformat() for d in dates]

    colgroup_cols = ["<col class='col-machine'>"]
    for dk in date_keys:
        colgroup_cols.append(f"<col class='col-date' data-date='{dk}'>")
    colgroup_html = "<colgroup>" + "".join(colgroup_cols) + "</colgroup>"

    css = """
    :root{
      --grid-border:#dcdcdc;
      --grid-border-strong:#b0b0b0;
      --header-bg:#fafafa;
      --machine-bg:#f7f7f7;
      --text:#111;
      --muted:#666;

      --machine-col-w: 160px;
      --date-col-w: 150px;
      --cell-pad: 10px;
      --col-sep: 2px; /* 列分割线宽度（与 td border-right 一致） */
    }

    body{font-family:"Segoe UI","Microsoft YaHei",Arial,sans-serif;margin:18px;color:var(--text);}
    .topbar{display:flex;align-items:flex-end;justify-content:space-between;gap:12px;}
    h1{font-size:18px;margin:0;}
    .meta{font-size:12px;color:var(--muted);}

    .wrap{margin-top:12px;overflow:auto;border:1px solid var(--grid-border);border-radius:10px;}
    table{border-collapse:separate;border-spacing:0;min-width:1200px;width:100%;table-layout:fixed;}

    col.col-machine{width:var(--machine-col-w);}
    col.col-date{width:var(--date-col-w);}

    thead th{
      position:sticky;top:0;z-index:3;
      background:var(--header-bg);
      border-bottom:2px solid var(--grid-border-strong);
      font-weight:700;font-size:12px;
      padding:10px 10px;
      text-align:center;                 /* 日期行居中 */
      white-space:nowrap;
    }

    th.machine-col{
      position:sticky; left:0; z-index:4;
      background:var(--header-bg);
      border-right:2px solid var(--grid-border-strong);
      text-align:center;
    }

    /* 每机台一行：上下边框加粗 */
    tbody tr[data-machine] th,
    tbody tr[data-machine] td{
      border-top:2px solid var(--grid-border-strong);
      border-bottom:2px solid var(--grid-border-strong);
    }

    tbody th{
      position:sticky;left:0;z-index:2;
      background:var(--machine-bg);
      border-right:2px solid var(--grid-border-strong);
      padding:10px 10px;
      font-size:13px;
      text-align:left;
      white-space:nowrap;
      vertical-align:top;
    }

    td{
      border-right: var(--col-sep) solid var(--grid-border-strong);   /* 竖向分割线更清晰 */
      padding: var(--cell-pad);
      background:#fff;
      vertical-align:top;
      overflow:visible;
    }
    td:last-child, thead th:last-child{border-right:none;}

    .dayline{
      display:flex;
      flex-direction:column;
      align-items:center;
      gap:4px;
    }
    .daynum{font-size:14px;font-weight:800;}
    .weekday{font-size:12px;color:var(--muted);}

    /* 同日多任务同格堆叠 */
    .stack{
      display:flex;
      flex-direction:column;
      gap:8px;
    }

    .task{
      border:1px solid rgba(0,0,0,0.22);
      border-radius:12px;
      padding:8px 10px;
      font-weight:800;
      font-size:13px;
      line-height:1.25;

      white-space:normal;
      word-break:break-word;
      overflow:visible;

      box-shadow: inset 0 1px 0 rgba(255,255,255,0.35);

      /* ✅ 关键：让任务能盖住列分割线，避免跨天断开 */
      position: relative;
      z-index: 2;
    }
    .task.nofill{ background:transparent; }

    /* ✅ 跨天“视觉连续”：吃掉 td padding + 覆盖列分割线，并去掉连接处边框 */
    .pos-start{
      border-top-right-radius:0; border-bottom-right-radius:0;
      margin-right: calc(-1 * (var(--cell-pad) + var(--col-sep)));
      border-right: none;
    }
    .pos-mid{
      border-radius:0;
      margin-left:  calc(-1 * (var(--cell-pad) + var(--col-sep)));
      margin-right: calc(-1 * (var(--cell-pad) + var(--col-sep)));
      border-left: none;
      border-right: none;
    }
    .pos-end{
      border-top-left-radius:0; border-bottom-left-radius:0;
      margin-left: calc(-1 * (var(--cell-pad) + var(--col-sep)));
      border-left: none;
    }

    .empty{
      color:#bbb;
      font-size:12px;
    }

    /* 列宽拖拽把手 */
    .col-resizer{
      position:absolute;
      top:0; right:-6px;
      width:12px;
      height:100%;
      cursor:col-resize;
      z-index:10;
    }
    .thbox{ position:relative; }

    /* 行高拖拽把手（设置最小高度；内容仍可撑开） */
    .row-resizer{
      position:absolute;
      left:0; right:0; bottom:-6px;
      height:12px;
      cursor:row-resize;
      z-index:10;
    }
    .rowbox{ position:relative; }
    """

    js = r"""
    (function(){
      const KEY_PREFIX = "sched_v1_";
      function save(key, val){ localStorage.setItem(KEY_PREFIX + key, String(val)); }
      function load(key){ return localStorage.getItem(KEY_PREFIX + key); }

      function restoreColWidths(){
        document.querySelectorAll("col.col-date[data-date]").forEach(col=>{
          const dk = col.getAttribute("data-date");
          const w = load("colw_" + dk);
          if(w){ col.style.width = w + "px"; }
        });
        const mw = load("colw_machine");
        if(mw){
          const mcol = document.querySelector("col.col-machine");
          if(mcol) mcol.style.width = mw + "px";
        }
      }

      function restoreRowHeights(){
        document.querySelectorAll("tr[data-machine]").forEach(tr=>{
          const m = tr.getAttribute("data-machine");
          const h = load("rowh_" + m);
          if(h){
            tr.querySelectorAll("td,th").forEach(cell=>{
              cell.style.minHeight = h + "px";
            });
          }
        });
      }

      function bindColResizers(){
        document.querySelectorAll("th[data-date]").forEach(th=>{
          const dk = th.getAttribute("data-date");
          const col = document.querySelector("col.col-date[data-date='"+dk+"']");
          if(!col) return;

          const handle = th.querySelector(".col-resizer");
          if(!handle) return;

          handle.addEventListener("mousedown", (ev)=>{
            ev.preventDefault();
            const startX = ev.clientX;
            const startW = col.getBoundingClientRect().width;

            function onMove(e){
              const dx = e.clientX - startX;
              const w = Math.max(80, Math.round(startW + dx));
              col.style.width = w + "px";
            }
            function onUp(){
              document.removeEventListener("mousemove", onMove);
              document.removeEventListener("mouseup", onUp);
              const w = Math.round(col.getBoundingClientRect().width);
              save("colw_" + dk, w);
            }
            document.addEventListener("mousemove", onMove);
            document.addEventListener("mouseup", onUp);
          });
        });

        const mcol = document.querySelector("col.col-machine");
        const mth = document.querySelector("th.machine-col");
        if(mcol && mth){
          const handle = mth.querySelector(".col-resizer");
          if(handle){
            handle.addEventListener("mousedown", (ev)=>{
              ev.preventDefault();
              const startX = ev.clientX;
              const startW = mcol.getBoundingClientRect().width;

              function onMove(e){
                const dx = e.clientX - startX;
                const w = Math.max(120, Math.round(startW + dx));
                mcol.style.width = w + "px";
              }
              function onUp(){
                document.removeEventListener("mousemove", onMove);
                document.removeEventListener("mouseup", onUp);
                const w = Math.round(mcol.getBoundingClientRect().width);
                save("colw_machine", w);
              }
              document.addEventListener("mousemove", onMove);
              document.addEventListener("mouseup", onUp);
            });
          }
        }
      }

      function bindRowResizers(){
        document.querySelectorAll("tr[data-machine] th.rowhead").forEach(th=>{
          const tr = th.closest("tr");
          const m = tr.getAttribute("data-machine");
          const handle = th.querySelector(".row-resizer");
          if(!handle) return;

          handle.addEventListener("mousedown", (ev)=>{
            ev.preventDefault();
            const startY = ev.clientY;
            const startH = tr.getBoundingClientRect().height;

            function onMove(e){
              const dy = e.clientY - startY;
              const h = Math.max(40, Math.round(startH + dy));
              tr.querySelectorAll("td,th").forEach(cell=>{
                cell.style.minHeight = h + "px";
              });
            }
            function onUp(){
              document.removeEventListener("mousemove", onMove);
              document.removeEventListener("mouseup", onUp);
              const h = Math.round(tr.getBoundingClientRect().height);
              save("rowh_" + m, h);
            }
            document.addEventListener("mousemove", onMove);
            document.addEventListener("mouseup", onUp);
          });
        });
      }

      document.addEventListener("DOMContentLoaded", ()=>{
        restoreColWidths();
        restoreRowHeights();
        bindColResizers();
        bindRowResizers();
      });
    })();
    """

    parts = []
    parts.append(f"<!doctype html><html lang='zh-CN'><head><meta charset='utf-8'>"
                 f"<meta name='viewport' content='width=device-width, initial-scale=1'>"
                 f"<title>{html_escape(TITLE)}</title><style>{css}</style></head><body>")

    parts.append(f"<div class='topbar'><h1>{html_escape(TITLE)}</h1>"
                 f"<div class='meta'>生成时间：{now} · 数据源：Bitable JSON</div></div>")

    parts.append("<div class='wrap'>")
    parts.append("<table>")
    parts.append(colgroup_html)

    parts.append("<thead><tr>")
    parts.append("<th class='machine-col'><div class='thbox'>机台<span class='col-resizer'></span></div></th>")
    for d in dates:
        dk = d.isoformat()
        parts.append(
            f"<th data-date='{dk}'>"
            f"<div class='thbox'>"
            f"<div class='dayline'><div class='daynum'>{d.month}/{d.day}</div><div class='weekday'>{weekday_cn(d)}</div></div>"
            f"<span class='col-resizer'></span>"
            f"</div>"
            f"</th>"
        )
    parts.append("</tr></thead>")

    parts.append("<tbody>")
    for m in machines:
        parts.append(f"<tr data-machine='{html_escape(m)}'>")
        parts.append(
            f"<th class='rowhead'>"
            f"<div class='rowbox'>{html_escape(m)}"
            f"<span class='row-resizer'></span>"
            f"</div>"
            f"</th>"
        )

        for d in dates:
            segs = cell_map.get((m, d), [])
            parts.append("<td>")
            if segs:
                parts.append("<div class='stack'>")
                for seg in segs:
                    rgb = seg["rgb"]
                    pos = seg["pos"]  # single/start/mid/end
                    cls = "task"
                    if pos != "single":
                        cls += f" pos-{pos}"

                    if rgb is None:
                        bg_css = "transparent"
                        tc = "#111111"
                        cls += " nofill"
                    else:
                        bg_css = f"rgb({rgb[0]},{rgb[1]},{rgb[2]})"
                        tc = best_text_color(rgb)

                    parts.append(
                        f"<div class='{cls}' style='background:{bg_css};color:{tc};'>"
                        f"{html_escape(seg['text'])}"
                        f"</div>"
                    )
                parts.append("</div>")
            else:
                parts.append("<div class='empty'>—</div>")
            parts.append("</td>")

        parts.append("</tr>")
    parts.append("</tbody>")

    parts.append("</table>")
    parts.append("</div>")

    parts.append(f"<script>{js}</script>")
    parts.append("</body></html>")
    return "".join(parts)


def main():
    ensure_dir(OUTPUT_DIR)

    fields_path = FIELDS_JSON
    records_path = RECORDS_JSON
    if AUTO_LATEST:
        fields_path, records_path = pick_latest_pair(OUTPUT_DIR)

    if not os.path.exists(fields_path):
        raise FileNotFoundError(fields_path)
    if not os.path.exists(records_path):
        raise FileNotFoundError(records_path)

    with open(fields_path, "r", encoding="utf-8") as f:
        fields_doc = json.load(f)
    with open(records_path, "r", encoding="utf-8") as f:
        records_doc = json.load(f)

    fields_order = load_machine_order_from_fields(fields_doc)

    tasks_all = extract_tasks(records_doc)
    if not tasks_all:
        raise RuntimeError("没有抽取到任务：请检查 records.raw.json 是否包含 机台/开始日期/结束日期/甘特图文本")

    win_start, win_end = compute_window(tasks_all)
    dates = build_dates(win_start, win_end)

    tasks_in_win = filter_tasks_by_window(tasks_all, win_start, win_end)

    dump = []
    for t in tasks_in_win:
        dump.append({
            "machine": t["machine"],
            "start_date": t["start"].isoformat(),
            "end_date": t["end"].isoformat(),
            "start_ms": t["start_ms"],
            "end_ms": t["end_ms"],
            "text": t["text"],
            "rgb": None if t["rgb"] is None else [t["rgb"][0], t["rgb"][1], t["rgb"][2]],
        })
    with open(OUTPUT_TASKS_JSON, "w", encoding="utf-8") as f:
        json.dump(dump, f, ensure_ascii=False, indent=2)

    machines = build_machine_list(tasks_in_win, fields_order)
    if not machines:
        raise RuntimeError("窗口内没有任何机台任务：请调整 DATE_PRESET 或日期范围")

    machines_set = set(machines)

    cell_map: Dict[Tuple[str, Any], List[dict]] = {(m, d): [] for m in machines for d in dates}
    for t in tasks_in_win:
        if t["machine"] not in machines_set:
            continue
        segs = split_task_to_day_segments(t, win_start, win_end)
        for seg in segs:
            key = (t["machine"], seg["day"])
            if key in cell_map:
                cell_map[key].append(seg)

    # 同一格内排序：更早 start_ms 在上面
    for key, segs in cell_map.items():
        segs.sort(key=lambda x: (x["orig_start_ms"], x["orig_end_ms"], x["text"]))

    html = render_html(dates, machines, cell_map)
    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"OK: {OUTPUT_HTML}")
    print(f"Used: {os.path.basename(fields_path)} + {os.path.basename(records_path)}")
    print(f"Window: {win_start} ~ {win_end} ({len(dates)} days), Machines: {len(machines)}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)

