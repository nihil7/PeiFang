# B05A_prepare_data.py
# 功能：
# 1) 读取 output 下最新 records.raw.json（可选同时读取 fields.json）
# 2) 开始/结束日期：按北京时间解析毫秒（修复“差一天”）
# 3) 甘特图文本：拆成3行（只处理第1、第3个空格；第2个空格不动）
# 4) 计算长度：len1/len2/len3/max_len（按“视觉长度”加权：更贴近 Excel 字体实际占宽）
# 5) 输出：output/tasks_prepared_*.json + output/tasks_prepared_*.csv

import os
import re
import sys
import json
import math
import unicodedata
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

try:
    from zoneinfo import ZoneInfo
    BJ_TZ = ZoneInfo("Asia/Shanghai")
except Exception:
    BJ_TZ = timezone(timedelta(hours=8))


# =========================
# 配置区（只改这里）
# =========================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

AUTO_LATEST = True

# 若 AUTO_LATEST=False，就用你手动指定的文件
RECORDS_JSON = os.path.join(OUTPUT_DIR, "生产任务排期__排产·统计总台账__YYYYMMDD_HHMMSS.records.raw.json")
FIELDS_JSON  = os.path.join(OUTPUT_DIR, "生产任务排期__排产·统计总台账__YYYYMMDD_HHMMSS.fields.json")

# 字段名（按你现有表）
FIELD_MACHINE = "机台"
FIELD_TEXT    = "甘特图文本"
FIELD_STARTMS = "开始日期"
FIELD_ENDMS   = "结束日期"
FIELD_RGB     = "RGB"

# 如果 records 里没有 RGB，但有 “颜色选择=C1”，可以用 fields.json 做映射
ENABLE_COLOR_CHOICE_FALLBACK = True
FIELD_COLOR_CHOICE = "颜色选择"   # 例如 C1/C2...

# ====== 视觉长度权重（更“科学”）======
# 你的字体设定：
# - 字母/数字：微软雅黑 12号 加粗
# - 汉字：宋体 12号 加粗
#
# 说明：
# - Excel 列宽单位不是“字符数”，而是按默认字体折算；因此这里用加权近似“视觉占宽”
# - 这些权重是经验值：优先解决“列宽偏小导致二次自动换行”
VIS_W_CJK        = 2.2   # 汉字/全角（宋体12粗）：接近全角，更占宽
VIS_W_UPPER      = 1.35  # 英文大写（微软雅黑12粗）
VIS_W_LOWER      = 1.25  # 英文小写（微软雅黑12粗）
VIS_W_DIGIT      = 1.25  # 数字（微软雅黑12粗）
VIS_W_SPACE      = 0.60  # 空格
VIS_W_HYPHEN     = 0.85  # 连字符（- 及其变体）
VIS_W_PUNCT      = 1.00  # 半角标点
VIS_W_OTHER      = 1.10  # 其它字符（兜底）
# ======================================

PRINT_FIRST_N = 30
# =========================


def ensure_dir(p: str):
    os.makedirs(p, exist_ok=True)


def pick_latest(output_dir: str, suffix: str) -> Optional[str]:
    if not os.path.isdir(output_dir):
        return None
    files = [f for f in os.listdir(output_dir) if f.endswith(suffix)]
    if not files:
        return None
    files.sort(key=lambda fn: os.path.getmtime(os.path.join(output_dir, fn)), reverse=True)
    return os.path.join(output_dir, files[0])


def read_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def first_text_cell(v: Any) -> str:
    """
    兼容 smart-sheet 常见结构：
    - 纯字符串
    - [{"text":"xxx", ...}]
    """
    if v is None:
        return ""
    if isinstance(v, list) and v:
        if isinstance(v[0], dict) and "text" in v[0]:
            return str(v[0].get("text", "")).strip()
        if isinstance(v[0], dict) and "name" in v[0]:
            return str(v[0].get("name", "")).strip()
    if isinstance(v, str):
        return v.strip()
    return str(v).strip()


def clamp_rgb(r: int, g: int, b: int) -> Tuple[int, int, int]:
    return max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b))


def parse_rgb(s: Any) -> Optional[Tuple[int, int, int]]:
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None

    m = re.match(r"rgb\(\s*(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})\s*\)", s, re.I)
    if m:
        return clamp_rgb(*map(int, m.groups()))

    m = re.match(r"#?([0-9a-fA-F]{6})$", s)
    if m:
        h = m.group(1)
        return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)

    m = re.match(r"(\d{1,3})\s*,\s*(\d{1,3})\s*,\s*(\d{1,3})$", s)
    if m:
        return clamp_rgb(*map(int, m.groups()))

    return None


def ms_to_date_bj(ms: Any):
    if ms is None or ms == "":
        return None
    ms_int = int(ms)
    dt_utc = datetime.fromtimestamp(ms_int / 1000, tz=timezone.utc)
    dt_bj = dt_utc.astimezone(BJ_TZ)
    return dt_bj.date()


def split_3_lines(text: str) -> Tuple[str, str, str]:
    """
    只处理第1个和第3个空格：
    - 找到第1个空格：在这里换行
    - 找到第3个空格：在这里换行
    - 第2个空格不动（如果没有第3个空格，就不做第二次换行）
    说明：
    - “空格”指普通空格 ' '；其它空白（\t 等）先归一成空格再处理
    """
    s = (text or "").replace("\t", " ").strip()
    if not s:
        return "", "", ""

    space_pos = [i for i, ch in enumerate(s) if ch == " "]
    if len(space_pos) == 0:
        return s, "", ""

    p1 = space_pos[0]
    line1 = s[:p1].strip()
    rest = s[p1 + 1:]  # 第1个空格之后（保留其余空格结构）

    if len(space_pos) < 3:
        return line1, rest.strip(), ""

    p3 = space_pos[2]
    line2 = s[p1 + 1:p3].strip()   # 包含第2个空格（原样保留）
    line3 = s[p3 + 1:].strip()

    return line1, line2, line3


_HYPHENS = {"-", "‐", "-", "‒", "–", "—", "―"}
def _is_cjk_or_fullwidth(ch: str) -> bool:
    # W/F：宽/全角，基本覆盖汉字、全角标点等
    return unicodedata.east_asian_width(ch) in ("W", "F")


def visual_len(s: str) -> int:
    """
    视觉长度（加权），返回 int（向上取整）：
    - 汉字/全角：VIS_W_CJK
    - 英文：按大小写
    - 数字：VIS_W_DIGIT
    - 空格/连字符/标点：独立权重
    """
    if not s:
        return 0

    total = 0.0
    for ch in s:
        if ch == " ":
            total += VIS_W_SPACE
            continue
        if ch in _HYPHENS:
            total += VIS_W_HYPHEN
            continue

        if _is_cjk_or_fullwidth(ch):
            total += VIS_W_CJK
            continue

        # 半角范围：英文/数字/标点
        o = ord(ch)
        if 48 <= o <= 57:  # 0-9
            total += VIS_W_DIGIT
        elif 65 <= o <= 90:  # A-Z
            total += VIS_W_UPPER
        elif 97 <= o <= 122:  # a-z
            total += VIS_W_LOWER
        else:
            cat = unicodedata.category(ch)
            # P*: punctuation; S*: symbol
            if cat and (cat[0] == "P" or cat[0] == "S"):
                total += VIS_W_PUNCT
            else:
                total += VIS_W_OTHER

    return int(math.ceil(total))


def build_color_choice_map(fields_doc: dict) -> Dict[str, Tuple[int, int, int]]:
    """
    尝试从 fields.json 建立：颜色选择(如C1) -> RGB
    尽力解析常见结构。
    """
    out: Dict[str, Tuple[int, int, int]] = {}

    fields = fields_doc.get("fields")
    if not isinstance(fields, list):
        if isinstance(fields_doc, list):
            fields = fields_doc
        else:
            fields = []

    def pick_options(field: dict) -> List[dict]:
        for path in [
            ("property", "options"),
            ("options",),
            ("config", "options"),
            ("meta", "options"),
        ]:
            cur = field
            ok = True
            for k in path:
                if isinstance(cur, dict) and k in cur:
                    cur = cur[k]
                else:
                    ok = False
                    break
            if ok and isinstance(cur, list):
                return cur
        return []

    target_fields = []
    for f in fields:
        name = str(f.get("name", "")).strip()
        if FIELD_COLOR_CHOICE in name:
            target_fields.append(f)

    if not target_fields:
        return out

    f0 = target_fields[0]
    options = pick_options(f0)

    for opt in options:
        key = str(opt.get("key") or opt.get("value") or opt.get("name") or opt.get("text") or "").strip()
        if not key:
            continue

        color_raw = opt.get("rgb") or opt.get("color") or opt.get("hex") or opt.get("backgroundColor") or opt.get("bgColor")
        rgb = parse_rgb(color_raw)
        if rgb:
            out[key] = rgb

    return out


def _cut(s: str, limit: int = 120) -> str:
    s = s or ""
    return s if len(s) <= limit else (s[:limit] + "...")


def main():
    ensure_dir(OUTPUT_DIR)

    records_path = RECORDS_JSON
    fields_path = FIELDS_JSON

    if AUTO_LATEST:
        lp = pick_latest(OUTPUT_DIR, ".records.raw.json")
        if lp:
            records_path = lp
        fp = pick_latest(OUTPUT_DIR, ".fields.json")
        if fp:
            fields_path = fp

    if not os.path.exists(records_path):
        raise FileNotFoundError(f"records 文件不存在：{records_path}")

    records_doc = read_json(records_path)

    # 颜色选择映射（可选）
    color_map: Dict[str, Tuple[int, int, int]] = {}
    if ENABLE_COLOR_CHOICE_FALLBACK and os.path.exists(fields_path):
        try:
            fields_doc = read_json(fields_path)
            color_map = build_color_choice_map(fields_doc)
        except Exception:
            color_map = {}

    tasks: List[dict] = []
    recs = records_doc.get("records", [])
    if not isinstance(recs, list):
        raise ValueError("records.raw.json 结构异常：records 不是列表")

    for rec in recs:
        vals = rec.get("values", {}) or {}
        machine = first_text_cell(vals.get(FIELD_MACHINE))
        text_raw = first_text_cell(vals.get(FIELD_TEXT))

        s_ms = vals.get(FIELD_STARTMS)
        e_ms = vals.get(FIELD_ENDMS)
        if s_ms in (None, "") or e_ms in (None, ""):
            continue

        try:
            s_ms = int(s_ms)
            e_ms = int(e_ms)
        except Exception:
            continue

        # 北京日期
        s_date = ms_to_date_bj(s_ms)
        e_date = ms_to_date_bj(e_ms)
        if not machine or not text_raw or not s_date or not e_date:
            continue

        if e_ms < s_ms:
            s_ms, e_ms = e_ms, s_ms
            s_date, e_date = e_date, s_date

        # RGB：优先取 RGB 字段；否则尝试颜色选择映射
        rgb = parse_rgb(first_text_cell(vals.get(FIELD_RGB)))
        if rgb is None and ENABLE_COLOR_CHOICE_FALLBACK:
            choice = first_text_cell(vals.get(FIELD_COLOR_CHOICE))
            if choice and choice in color_map:
                rgb = color_map[choice]

        l1, l2, l3 = split_3_lines(text_raw)

        # ====== 关键改动：视觉长度 ======
        len1, len2, len3 = visual_len(l1), visual_len(l2), visual_len(l3)
        max_len = max(len1, len2, len3)
        # ============================

        rid = str(rec.get("record_id", "")).strip()
        task_id = rid if rid else f"{machine}_{s_ms}_{e_ms}_{abs(hash(text_raw))}"

        span_days = (e_date - s_date).days + 1

        tasks.append({
            "task_id": task_id,
            "record_id": rid,
            "machine": machine,
            "start_ms": s_ms,
            "end_ms": e_ms,
            "start_date": s_date.isoformat(),
            "end_date": e_date.isoformat(),
            "span_days_inclusive": span_days,

            "text_raw": text_raw,
            "line1": l1,
            "line2": l2,
            "line3": l3,
            "len1": len1,
            "len2": len2,
            "len3": len3,
            "max_len": max_len,

            "rgb": None if rgb is None else [rgb[0], rgb[1], rgb[2]],
            "color_choice": first_text_cell(vals.get(FIELD_COLOR_CHOICE)) if ENABLE_COLOR_CHOICE_FALLBACK else "",
        })

    if not tasks:
        raise RuntimeError("未抽取到任务：请确认 records.raw.json 中包含 机台/开始日期/结束日期/甘特图文本")

    # 输出
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_json = os.path.join(OUTPUT_DIR, f"tasks_prepared_{ts}.json")
    out_csv = os.path.join(OUTPUT_DIR, f"tasks_prepared_{ts}.csv")

    payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "records_source": os.path.basename(records_path),
        "fields_source": os.path.basename(fields_path) if os.path.exists(fields_path) else "",
        "task_count": len(tasks),
        "min_date": min(t["start_date"] for t in tasks),
        "max_date": max(t["end_date"] for t in tasks),
        "tasks": tasks,
    }
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

    # CSV 方便人工核对
    import pandas as pd
    df = pd.DataFrame(tasks)
    df.to_csv(out_csv, index=False, encoding="utf-8-sig")

    # 打印预览（少量，避免过长）
    print(f"OK: prepared_json={out_json}")
    print(f"OK: prepared_csv ={out_csv}")
    print(f"tasks={len(tasks)} | date_range={payload['min_date']} ~ {payload['max_date']}")
    head = sorted(tasks, key=lambda x: (x["machine"], x["start_ms"], x["end_ms"]))[:PRINT_FIRST_N]
    for i, t in enumerate(head, 1):
        rgb_s = "" if t["rgb"] is None else ",".join(map(str, t["rgb"]))
        msg = f"{i:02d} | {t['machine']} | {t['start_date']}~{t['end_date']}({t['span_days_inclusive']}天) | max_len={t['max_len']} | RGB={rgb_s or '空'} | {t['line1']} / {t['line2']} / {t['line3']}"
        print(_cut(msg, 200))


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
