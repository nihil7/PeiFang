# B06_填充卡片.py
# 作用：读取 layout.json + 框架xlsx -> 用 Excel COM 插入“圆角矩形Shape（可编辑）”
# 特性：
# - 文本支持 1/2/3 行（layout line1/line2/line3 或 text_raw/text）
# - Anchor 覆盖单元格范围 + Card 内留白 + Group，拖动列宽能联动
# - AutoSize/BoundHeight 计算高度 -> 自动抬高行高 -> 重对齐
# - 新增：两行卡片高度微调，解决“2行只显示1行”的裁切（3行不影响）
# - 新增：行高/列宽“校准值”，用于不同电脑/Office/DPI/缩放下的观感一致
# 依赖：pip install pywin32

import os
import sys
import json
import re
from typing import Optional, Tuple, Dict, List
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from peifang_core.common import ROOT_DIR
from peifang_core.schedule_web import render_schedule_html

# =========================
# 配置区（只改这里）
# =========================

# 项目根目录（当前脚本所在目录）
BASE_DIR = str(ROOT_DIR)

# 输出目录（layout/json、框架xlsx都在这里）
OUTPUT_DIR = os.path.join(BASE_DIR, "output")

# 是否自动选用 output 里“最新”的 layout/json 和 框架xlsx
AUTO_LATEST = True

# 手动指定 layout.json 路径（AUTO_LATEST=False 时生效）
LAYOUT_JSON = os.path.join(OUTPUT_DIR, "排产_layout_YYYYMMDD_HHMMSS.json")

# 手动指定 框架xlsx 路径（AUTO_LATEST=False 时生效）
FRAME_XLSX = os.path.join(OUTPUT_DIR, "排产_框架_YYYYMMDD_HHMMSS.xlsx")

# —— 卡片与单元格边缘距离（外边距，像素）——
# 卡片距离单元格左右边缘的距离（越大，卡片越“缩进”）
CARD_MARGIN_X_PX = 8

# 卡片距离单元格上下边缘的距离（越大，卡片越“缩进”）
CARD_MARGIN_Y_PX = 4

# —— 卡片内部文字留白（内边距，像素）——
# 文字距离卡片左边缘的留白
TEXT_PAD_L_PX = 10

# 文字距离卡片右边缘的留白
TEXT_PAD_R_PX = 10

# 文字距离卡片上边缘的留白
TEXT_PAD_T_PX = 8

# 文字距离卡片下边缘的留白
TEXT_PAD_B_PX = 8

# —— 卡片圆角/边框 ——
# 圆角比例（Excel 的 RoundedRectangle 调整值：一般 0.15~0.35）
SHAPE_RADIUS = 0.22

# 边框颜色（RGB）
BORDER_RGB = (203, 213, 225)  # #CBD5E1

# 边框粗细（pt）
BORDER_WEIGHT = 1.1

# —— 阴影 ——
# 是否启用阴影（卡片“悬浮感”）
ENABLE_SHADOW = True

# 阴影透明度（0~1；越大越淡，越不明显）
SHADOW_TRANSPARENCY = 0.9

# 阴影模糊（越大越柔和；0~2 很硬，4~8 较自然）
SHADOW_BLUR = 1

# 阴影水平偏移（正=向右，负=向左）
SHADOW_OFFSET_X = 0

# 阴影垂直偏移（正=向下，负=向上）
SHADOW_OFFSET_Y = 1

# —— 填充 ——
# 当 layout 里没有 rgb 时：True=卡片透明，仅保留边框；False=保持默认填充
FILL_TRANSPARENT_IF_NO_RGB = True

# —— 字体/颜色固定（每行固定样式）——
# 字体名（尽量用中文 Office 更稳定的字体名）
FONT_NAME = "微软雅黑"

# 第1行字号
LINE1_SIZE = 12
# 第1行是否加粗
LINE1_BOLD = True
# 第1行颜色（RGB）
LINE1_COLOR = (17, 24, 39)  # #111827

# 第2行字号
LINE2_SIZE = 11
# 第2行是否加粗
LINE2_BOLD = True
# 第2行颜色（RGB）
LINE2_COLOR = (37, 99, 235)  # #2563EB

# 第3行字号
LINE3_SIZE = 10
# 第3行是否加粗
LINE3_BOLD = True
# 第3行颜色（RGB）——固定红色（不判断内容）
LINE3_COLOR = (220, 38, 38)  # #DC2626

# —— 自动撑高 lane 行（RowHeight）——
# 是否自动根据文本高度抬高行高
AUTO_ROW_HEIGHT = True

# 最小行高（pt）——行高再小也不低于它
MIN_ROW_HEIGHT = 40

# 最大行高（pt）——行高再大也不超过它（避免极端拉高）
MAX_ROW_HEIGHT = 260

# —— 两行卡片高度微调 ——
# 是否对“2行文本”额外加高，解决偶发“2行只显示1行”裁切
TWO_LINE_HEIGHT_FIX = True

# 2行文本额外加高的像素（不够就加到 10/12）
TWO_LINE_EXTRA_PX = 4

# 通用保险垫像素（避免偶发裁切；对所有卡片都生效）
HEIGHT_SAFETY_PAD_PX = 4

# —— 校准值：适配不同电脑/Office/DPI/缩放（核心新增）——
# BoundHeight 缩放因子（>1 更保守，更不容易裁切；<1 更紧凑）
BOUNDH_SCALE = 1.1

# BoundHeight 额外偏移（pt；正数抬高、负数压低）
HEIGHT_CALIB_PT = 5.0

# 卡片宽度校准（pt；正数让卡片略窄、更早换行；负数让卡片略宽、更晚换行）
WIDTH_CALIB_PT = 0.0

# —— 清理旧卡片 ——
# 是否删除上一次生成的卡片（用 AlternativeText 标记）
CLEAR_OLD_SHAPES = True

# 旧卡片标记前缀（AlternativeText 以这个开头的 Shape 会被删除）
SHAPE_TAG_PREFIX = "TASKCARD::"
# =========================


def pick_latest(prefix: str, ext: str) -> Optional[str]:
    """在 OUTPUT_DIR 中选择最新的 prefix+*+ext 文件（按修改时间）"""
    files = [f for f in os.listdir(OUTPUT_DIR) if f.startswith(prefix) and f.endswith(ext)]
    if not files:
        return None
    files.sort(key=lambda fn: os.path.getmtime(os.path.join(OUTPUT_DIR, fn)), reverse=True)
    return os.path.join(OUTPUT_DIR, files[0])


def px_to_pt(px: float) -> float:
    """像素转 pt：Excel/COM 更习惯用 points（这里按 96dpi 近似：1px≈0.75pt）"""
    return px * 0.75


def rgb_to_ole(rgb: Tuple[int, int, int]) -> int:
    """RGB -> OLE 颜色（BGR 顺序）"""
    r, g, b = rgb
    return (b << 16) | (g << 8) | r


def clamp(v: float, lo: float, hi: float) -> float:
    """数值夹逼到 [lo, hi]"""
    return max(lo, min(hi, v))


def format_3lines(text: str) -> str:
    """
    把 raw 文本尽量拆成 1~3 行：
    - >=4段：行1=0，行2=1+2，行3=3...
    - 3段：1/2/3
    - 2段：1/2
    - 1段：1
    """
    tokens = re.split(r"\s+", (text or "").strip())
    tokens = [t for t in tokens if t]
    if len(tokens) >= 4:
        line1 = tokens[0]
        line2 = f"{tokens[1]} {tokens[2]}"
        line3 = " ".join(tokens[3:])
        return f"{line1}\n{line2}\n{line3}".strip()
    if len(tokens) == 3:
        return f"{tokens[0]}\n{tokens[1]}\n{tokens[2]}".strip()
    if len(tokens) == 2:
        return f"{tokens[0]}\n{tokens[1]}".strip()
    return (tokens[0] if tokens else "").strip()


def get_item_text(it: dict) -> str:
    """
    layout 文本兼容三种情况：
    1) 新版 layout：line1/line2/line3
    2) 新版 layout：text_raw
    3) 旧版 layout：text
    """
    l1 = str(it.get("line1", "") or "")
    l2 = str(it.get("line2", "") or "")
    l3 = str(it.get("line3", "") or "")

    if (l1 + l2 + l3).strip():
        return "\n".join([l1, l2, l3]).strip()

    raw = str(it.get("text", "") or it.get("text_raw", "") or "")
    return format_3lines(raw)


def split_lines_keep_max3(text: str) -> Tuple[str, str, str]:
    """把文本拆成最多三行（第3行允许合并剩余多行）"""
    lines = (text or "").splitlines()
    lines = [l.strip() for l in lines if l is not None and str(l).strip() != ""]
    if len(lines) >= 3:
        return lines[0], lines[1], "\n".join(lines[2:]).strip()
    if len(lines) == 2:
        return lines[0], lines[1], ""
    if len(lines) == 1:
        return lines[0], "", ""
    return "", "", ""


def set_font_all_props(font_obj, name: str):
    """
    让中文也强制走指定字体：
    Office 有时只设置 Name 会导致中文仍用宋体/等线等 fallback。
    """
    for prop in ("Name", "NameFarEast", "NameAscii", "NameOther", "NameComplexScript"):
        try:
            setattr(font_obj, prop, name)
        except Exception:
            pass


def set_shadow(shape, msoTrue):
    """按配置给 shape 设置阴影"""
    if not ENABLE_SHADOW:
        return
    try:
        shape.Shadow.Visible = msoTrue
        shape.Shadow.Transparency = SHADOW_TRANSPARENCY
        shape.Shadow.Blur = SHADOW_BLUR
        shape.Shadow.OffsetX = SHADOW_OFFSET_X
        shape.Shadow.OffsetY = SHADOW_OFFSET_Y
    except Exception:
        pass


def apply_text_styles(card, tf2, line1: str, line2: str, line3: str, msoTrue, msoFillSolid):
    """
    固定三行层级（不判断内容）：
    - 行1：12 加粗 #111827
    - 行2：11 加粗 #2563EB
    - 行3：10 加粗 #DC2626（固定红色）
    颜色用 TextFrame2 + TextFrame 双保险，避免 Excel 把颜色变浅/变白。
    """
    parts = []
    if line1:
        parts.append(line1)
    if line2:
        parts.append(line2)
    if line3:
        parts.append(line3)
    full = "\n".join(parts).strip()

    tr2 = tf2.TextRange
    tr2.Text = full

    # 先统一字体（含中文 FarEast）
    try:
        set_font_all_props(tr2.Font, FONT_NAME)
    except Exception:
        pass

    # 强制：字体填充为 Solid + 不透明（避免发白）
    try:
        tr2.Font.Fill.Visible = msoTrue
        tr2.Font.Fill.Solid()
        tr2.Font.Fill.Transparency = 0.0
    except Exception:
        pass

    # 兜底 TextFrame（老接口）—— Excel 上色最稳
    tf1 = None
    try:
        tf1 = card.TextFrame
        tf1.Characters().Text = full
    except Exception:
        tf1 = None

    def set_seg(start_1based: int, length: int, size: int, bold: bool, color_rgb: Tuple[int, int, int]):
        if length <= 0:
            return
        ole = rgb_to_ole(color_rgb)

        # --- TextFrame2 上色 ---
        try:
            seg2 = tr2.Characters(start_1based, length)
            set_font_all_props(seg2.Font, FONT_NAME)
            seg2.Font.Size = size
            seg2.Font.Bold = bold

            seg2.Font.Fill.Visible = msoTrue
            try:
                seg2.Font.Fill.Solid()
            except Exception:
                pass
            seg2.Font.Fill.Transparency = 0.0
            seg2.Font.Fill.ForeColor.RGB = ole
        except Exception:
            pass

        # --- TextFrame（老接口）兜底上色 ---
        if tf1 is not None:
            try:
                seg1 = tf1.Characters(start_1based, length)
                seg1.Font.Name = FONT_NAME
                seg1.Font.Size = size
                seg1.Font.Bold = bold
                seg1.Font.Color = ole
            except Exception:
                pass

    pos = 1
    if line1:
        set_seg(pos, len(line1), LINE1_SIZE, LINE1_BOLD, LINE1_COLOR)
        pos += len(line1) + 1

    if line2:
        set_seg(pos, len(line2), LINE2_SIZE, LINE2_BOLD, LINE2_COLOR)
        pos += len(line2) + 1

    if line3:
        set_seg(pos, len(line3), LINE3_SIZE, LINE3_BOLD, LINE3_COLOR)


def main():
    try:
        import win32com.client  # type: ignore
    except Exception:
        print("ERROR: 缺少 pywin32，请先 pip install pywin32")
        sys.exit(1)

    layout_path = LAYOUT_JSON
    frame_path = FRAME_XLSX

    # 自动选择最新文件
    if AUTO_LATEST:
        lp = pick_latest("排产_layout_", ".json")
        xp = pick_latest("排产_框架_", ".xlsx")
        if lp:
            layout_path = lp
        if xp:
            frame_path = xp

    if not os.path.exists(layout_path):
        print(f"ERROR: layout.json 不存在：{layout_path}")
        sys.exit(1)
    if not os.path.exists(frame_path):
        print(f"ERROR: 框架xlsx 不存在：{frame_path}")
        sys.exit(1)

    with open(layout_path, "r", encoding="utf-8") as f:
        layout = json.load(f)
    layout["today"] = datetime.now().date().isoformat()
    html_path = os.path.join(
        OUTPUT_DIR,
        os.path.basename(layout_path).replace("排产_layout_", "schedule_web_").replace(".json", ".html"),
    )
    render_schedule_html(layout, html_path)

    items = layout.get("items", [])
    if not items:
        print("ERROR: layout items 为空")
        sys.exit(1)

    # Office 常量（COM）
    msoShapeRoundedRectangle = 5
    msoTrue = -1
    xlMoveAndSize = 1
    msoAutoSizeNone = 0
    msoAutoSizeShapeToFitText = 1
    msoFillSolid = 1

    # px -> pt（Excel 用 points）
    mx = px_to_pt(CARD_MARGIN_X_PX)
    my = px_to_pt(CARD_MARGIN_Y_PX)

    padL = px_to_pt(TEXT_PAD_L_PX)
    padR = px_to_pt(TEXT_PAD_R_PX)
    padT = px_to_pt(TEXT_PAD_T_PX)
    padB = px_to_pt(TEXT_PAD_B_PX)

    two_line_extra_pt = px_to_pt(TWO_LINE_EXTRA_PX)
    safety_pad_pt = px_to_pt(HEIGHT_SAFETY_PAD_PX)

    excel = win32com.client.Dispatch("Excel.Application")
    excel.Visible = False
    excel.DisplayAlerts = False

    wb = excel.Workbooks.Open(os.path.abspath(frame_path))
    ws = wb.Worksheets("排产")

    # 清理旧卡片
    if CLEAR_OLD_SHAPES:
        for i in range(ws.Shapes.Count, 0, -1):
            shp = ws.Shapes.Item(i)
            try:
                alt = str(shp.AlternativeText or "")
            except Exception:
                alt = ""
            if alt.startswith(SHAPE_TAG_PREFIX):
                shp.Delete()

    border_ole = rgb_to_ole(BORDER_RGB)

    created_pairs: List[dict] = []
    row_need_height: Dict[int, float] = {}

    # 第1遍：创建 Anchor + Card，同时估算需要的行高
    for it in items:
        row = int(it["row"])
        c1 = int(it["col_start"])
        c2 = int(it["col_end"])
        text = get_item_text(it)

        rgb_list = it.get("rgb", None)
        rgb = None
        if isinstance(rgb_list, list) and len(rgb_list) == 3:
            rgb = (int(rgb_list[0]), int(rgb_list[1]), int(rgb_list[2]))

        rng = ws.Range(ws.Cells(row, c1), ws.Cells(row, c2))

        # Anchor：覆盖整个单元格范围（用于 group 联动）
        a_left, a_top = rng.Left, rng.Top
        a_w, a_h = max(10, rng.Width), max(10, rng.Height)

        anchor = ws.Shapes.AddShape(msoShapeRoundedRectangle, a_left, a_top, a_w, a_h)
        anchor.Placement = xlMoveAndSize
        anchor.Line.Visible = msoTrue
        anchor.Line.Transparency = 1.0
        anchor.Fill.Visible = msoTrue
        anchor.Fill.Transparency = 1.0

        # Card：在 Anchor 内缩进（外边距），并应用“宽度校准”
        c_left = a_left + mx
        c_top = a_top + my
        c_w = max(10, a_w - 2 * mx - float(WIDTH_CALIB_PT))   # ✅ 宽度校准点（pt）
        c_h = max(10, a_h - 2 * my)

        card = ws.Shapes.AddShape(msoShapeRoundedRectangle, c_left, c_top, c_w, c_h)
        card.Placement = xlMoveAndSize

        # 圆角
        try:
            card.Adjustments[1] = SHAPE_RADIUS
        except Exception:
            pass

        # 边框
        card.Line.Visible = msoTrue
        card.Line.ForeColor.RGB = border_ole
        card.Line.Weight = BORDER_WEIGHT

        # 阴影
        set_shadow(card, msoTrue)

        # 填充
        if rgb is None and FILL_TRANSPARENT_IF_NO_RGB:
            card.Fill.Visible = msoTrue
            card.Fill.Transparency = 1.0
        else:
            card.Fill.Visible = msoTrue
            card.Fill.Transparency = 0.0
            if rgb is not None:
                card.Fill.ForeColor.RGB = rgb_to_ole(rgb)

        # 文本框（TextFrame2）
        tf = card.TextFrame2
        tf.WordWrap = msoTrue
        tf.MarginLeft = padL
        tf.MarginRight = padR
        tf.MarginTop = padT
        tf.MarginBottom = padB

        # 三行拆分并固定样式
        l1, l2, l3 = split_lines_keep_max3(text)
        apply_text_styles(card, tf, l1, l2, l3, msoTrue, msoFillSolid)

        # 自动算高度（并记下需要的 RowHeight）
        if AUTO_ROW_HEIGHT:
            try:
                tf.AutoSize = msoAutoSizeShapeToFitText
            except Exception:
                pass

            # BoundHeight（更稳定）
            bound_h = 0.0
            try:
                bound_h = float(tf.TextRange.BoundHeight)
            except Exception:
                bound_h = 0.0

            # 行数判断（仅对 2 行加高）
            try:
                line_count = len([x for x in (tf.TextRange.Text or "").splitlines() if x.strip() != ""])
            except Exception:
                line_count = len([x for x in (text or "").splitlines() if x.strip() != ""])

            extra = safety_pad_pt
            if TWO_LINE_HEIGHT_FIX and line_count == 2:
                extra += two_line_extra_pt

            # ✅ 高度校准（先 scale 再 offset）
            bound_eff = bound_h * float(BOUNDH_SCALE) + float(HEIGHT_CALIB_PT)

            need_by_bound = bound_eff + float(tf.MarginTop) + float(tf.MarginBottom) + extra
            try:
                need_by_shape = float(card.Height)
            except Exception:
                need_by_shape = 0.0

            need_card_h = max(need_by_bound, need_by_shape)
            need_row_h = need_card_h + 2 * my
            need_row_h = clamp(need_row_h, MIN_ROW_HEIGHT, MAX_ROW_HEIGHT)

            row_need_height[row] = max(row_need_height.get(row, 0.0), need_row_h)

        created_pairs.append({
            "row": row, "c1": c1, "c2": c2,
            "anchor": anchor, "card": card,
            "task_id": str(it.get("task_id", "")),
        })

    # 第2步：统一抬高行高（只抬高不降低）
    if AUTO_ROW_HEIGHT and row_need_height:
        for row, need_h in row_need_height.items():
            try:
                cur = float(ws.Rows(row).RowHeight)
            except Exception:
                cur = 0.0
            if need_h > cur:
                ws.Rows(row).RowHeight = need_h

    # 第3步：重对齐（行高变了、列宽可能不同）+ 组（Group）
    for obj in created_pairs:
        row, c1, c2 = obj["row"], obj["c1"], obj["c2"]
        anchor, card = obj["anchor"], obj["card"]
        task_id = obj["task_id"]

        rng = ws.Range(ws.Cells(row, c1), ws.Cells(row, c2))

        # Anchor 重对齐
        a_left, a_top = rng.Left, rng.Top
        a_w, a_h = max(10, rng.Width), max(10, rng.Height)
        anchor.Left, anchor.Top, anchor.Width, anchor.Height = a_left, a_top, a_w, a_h

        # Card 重对齐（同样应用宽度校准）
        c_left = a_left + mx
        c_top = a_top + my
        c_w = max(10, a_w - 2 * mx - float(WIDTH_CALIB_PT))   # ✅ 宽度校准点（pt）
        c_h = max(10, a_h - 2 * my)
        card.Left, card.Top, card.Width, card.Height = c_left, c_top, c_w, c_h

        # 关闭 AutoSize，避免后续拖动乱跳
        try:
            card.TextFrame2.AutoSize = 0
        except Exception:
            pass

        # Group：保证拖动列宽/行高时形状跟随
        try:
            grp = ws.Shapes.Range([anchor.Name, card.Name]).Group()
            grp.Placement = xlMoveAndSize
            grp.AlternativeText = SHAPE_TAG_PREFIX + task_id
        except Exception:
            anchor.AlternativeText = SHAPE_TAG_PREFIX + task_id
            card.AlternativeText = SHAPE_TAG_PREFIX + task_id

    wb.Save()
    wb.Close(SaveChanges=True)
    excel.Quit()

    print(f"OK: 已填充卡片并保存：{frame_path}")
    print(f"layout: {layout_path}")
    print(f"web: {html_path}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
