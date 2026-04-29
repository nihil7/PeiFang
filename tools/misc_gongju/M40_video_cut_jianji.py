"""
程序简介：执行本地视频剪辑或裁切相关处理。
主要逻辑：读取所需配置或输入数据，执行本文件负责的处理步骤，并把结果写入本地文件或输出到命令行。
配置说明：涉及企微或飞书凭证时，优先读取 PEIFANG_ENV_PROFILE、WECOM_ENV_PROFILE、FEISHU_ENV_PROFILE 选择公司配置档案；未设置时兼容原来的 .env 变量。
"""

# -*- coding: utf-8 -*-
import json
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

# ================================
# 配置（集中）
# ================================
DEFAULT_FFMPEG_PATH = r"C:\ffmpeg\bin\ffmpeg.exe"
DEFAULT_FFPROBE_PATH = r"C:\ffmpeg\bin\ffprobe.exe"

SEG_NAME_PATTERN = "{stem}_part{idx:03d}{suffix}"
DEFAULT_SUFFIX = ".mp4"

# 1 MB = 1,000,000 bytes
BYTES_PER_MB = 1_000_000

# 为了降低“估算值”和“实际值”的偏差导致超限，预留安全余量
HEADROOM_MB = 20.0

EPS = 0.001
MIN_SEGMENT_SEC = 0.2

FASTSTART_SUFFIXES = {".mp4", ".m4v", ".mov"}


# ================================
# 数据结构
# ================================
@dataclass
class MediaInfo:
    path: Path
    duration: float
    file_size: int
    format_name: str
    bitrate: float
    suffix: str
    has_video: bool


@dataclass
class PlanItem:
    idx: int
    start: float
    end: float
    expected_size: int
    file_name: str


# ================================
# 基础工具
# ================================
def run_cmd(cmd):
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace"
    )


def format_mb(num_bytes: int) -> str:
    return f"{num_bytes / BYTES_PER_MB:.2f} MB"


def format_seconds(sec: float) -> str:
    sec = max(0.0, float(sec))
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec - h * 3600 - m * 60
    return f"{h:02d}:{m:02d}:{s:06.3f}"


def unique_sorted_floats(values, eps=EPS):
    vals = sorted(float(v) for v in values if v is not None)
    out = []
    for v in vals:
        if not out or abs(v - out[-1]) > eps:
            out.append(v)
    return out


def resolve_tool_path(user_input: str, tool_name: str) -> str:
    """
    支持三种方式：
    1. 直接填 exe 完整路径
    2. 填 bin 目录路径（自动补 exe）
    3. 留空则自动走系统 PATH
    """
    txt = (user_input or "").strip().strip('"')

    if txt:
        p = Path(txt)

        if p.exists() and p.is_dir():
            p = p / f"{tool_name}.exe"

        if not p.exists() and p.suffix == "":
            p_exe = Path(str(p) + ".exe")
            if p_exe.exists():
                p = p_exe

        if not p.exists():
            raise RuntimeError(f"{tool_name} 路径不存在：\n{txt}")
        if p.is_dir():
            raise RuntimeError(f"{tool_name} 路径不能是文件夹：\n{txt}")

        return str(p)

    found = shutil.which(tool_name)
    if found:
        return found

    raise RuntimeError(
        f"找不到 {tool_name}。\n"
        f"请在界面中填写 {tool_name}.exe 的完整路径，或先安装 FFmpeg 并加入 PATH。"
    )


def ensure_tools(ffmpeg_input: str, ffprobe_input: str):
    ffmpeg_bin = resolve_tool_path(ffmpeg_input, "ffmpeg")
    ffprobe_bin = resolve_tool_path(ffprobe_input, "ffprobe")
    return ffmpeg_bin, ffprobe_bin


# ================================
# 媒体探测
# ================================
def probe_media(input_path: Path, ffprobe_bin: str) -> MediaInfo:
    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-show_format",
        "-show_streams",
        "-of", "json",
        str(input_path)
    ]
    r = run_cmd(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 探测失败：\n{r.stderr.strip()}")

    data = json.loads(r.stdout or "{}")
    fmt = data.get("format", {})
    streams = data.get("streams", [])

    duration = float(fmt.get("duration", 0.0) or 0.0)
    file_size = int(fmt.get("size", 0) or 0)
    format_name = str(fmt.get("format_name", "") or "")
    bitrate = float(fmt.get("bit_rate", 0.0) or 0.0)
    has_video = any(s.get("codec_type") == "video" for s in streams)

    if duration <= 0:
        raise RuntimeError("无法读取视频总时长。")
    if file_size <= 0:
        raise RuntimeError("无法读取文件大小。")
    if not has_video:
        raise RuntimeError("文件中没有检测到视频流。")

    suffix = input_path.suffix.lower().strip() or DEFAULT_SUFFIX

    return MediaInfo(
        path=input_path,
        duration=duration,
        file_size=file_size,
        format_name=format_name,
        bitrate=bitrate if bitrate > 0 else (file_size * 8 / duration),
        suffix=suffix,
        has_video=has_video
    )


def get_keyframes(input_path: Path, duration: float, ffprobe_bin: str):
    """
    读取视频主轨关键帧时间点。
    """
    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-select_streams", "v:0",
        "-skip_frame", "nokey",
        "-show_frames",
        "-show_entries", "frame=best_effort_timestamp_time,pkt_pts_time",
        "-of", "json",
        str(input_path)
    ]
    r = run_cmd(cmd)
    if r.returncode != 0:
        raise RuntimeError(f"读取关键帧失败：\n{r.stderr.strip()}")

    data = json.loads(r.stdout or "{}")
    frames = data.get("frames", [])

    times = [0.0]
    for fr in frames:
        t = fr.get("best_effort_timestamp_time", None)
        if t in (None, "", "N/A"):
            t = fr.get("pkt_pts_time", None)
        if t not in (None, "", "N/A"):
            try:
                tv = float(t)
                if 0.0 <= tv <= duration + 1:
                    times.append(tv)
            except Exception:
                pass

    times.append(duration)
    times = unique_sorted_floats(times)

    if len(times) < 2:
        raise RuntimeError("没有读到可用的关键帧信息，无法做可靠的纯无损独立分段。")

    return times


# ================================
# 快速估算逻辑（分析阶段）
# ================================
def estimate_segment_size_fast(media: MediaInfo, start: float, end: float) -> int:
    """
    按整文件时长比例快速估算片段大小。
    优点：极快，不会反复临时切文件。
    缺点：是估算值，不是实测值。
    """
    seg_dur = max(0.0, end - start)
    if seg_dur <= 0 or media.duration <= 0:
        return 0

    ratio = seg_dur / media.duration
    est = int(media.file_size * ratio)

    # 给一点封装开销余量
    est += 512 * 1024
    return est


def pick_candidates_after(keyframes, start: float):
    return [t for t in keyframes if t > start + MIN_SEGMENT_SEC]


def choose_best_end(
    media: MediaInfo,
    start: float,
    duration: float,
    keyframes,
    working_cap_bytes: int,
    log_func=None
):
    """
    在 start 之后的关键帧里寻找最大的 end，
    使得 [start, end] 的估算大小 <= working_cap_bytes。
    """
    candidates = pick_candidates_after(keyframes, start)

    if not candidates:
        end = duration
        size = estimate_segment_size_fast(media, start, end)
        if size > working_cap_bytes:
            raise RuntimeError("最后一段估算仍超过上限，请把最大大小再调低一点。")
        return end, size

    full_end = duration
    full_size = estimate_segment_size_fast(media, start, full_end)
    if full_size <= working_cap_bytes:
        return full_end, full_size

    cache = {}

    def get_size_by_time(end_time: float):
        key = round(end_time, 6)
        if key not in cache:
            if log_func:
                log_func(f"估算片段大小：{format_seconds(start)} -> {format_seconds(end_time)}")
            cache[key] = estimate_segment_size_fast(media, start, end_time)
        return cache[key]

    first_end = candidates[0]
    first_size = get_size_by_time(first_end)
    if first_size > working_cap_bytes:
        raise RuntimeError(
            "单个关键帧间隔对应的最短片段估算都超过了上限。\n"
            "请把最大大小调大，或者改为重编码切分。"
        )

    lo = 0
    hi = len(candidates) - 1
    best_end = first_end
    best_size = first_size

    while lo <= hi:
        mid = (lo + hi) // 2
        end_time = candidates[mid]
        seg_size = get_size_by_time(end_time)

        if seg_size <= working_cap_bytes:
            best_end = end_time
            best_size = seg_size
            lo = mid + 1
        else:
            hi = mid - 1

    return best_end, best_size


# ================================
# 正式切段
# ================================
def build_output_name(stem: str, idx: int, suffix: str) -> str:
    return SEG_NAME_PATTERN.format(stem=stem, idx=idx, suffix=suffix)


def build_ffmpeg_cut_cmd(ffmpeg_bin: str, input_path: Path, start: float, end: float, output_path: Path):
    """
    说明：
    1. 不重编码：-c copy
    2. 起点按关键帧规划，保证每段可独立播放的成功率
    3. reset_timestamps + avoid_negative_ts 让每段时间轴更干净
    4. mp4/mov/m4v 加 faststart，便于云端/在线播放
    """
    duration = max(0.0, end - start)
    if duration <= 0:
        raise RuntimeError("切段时长必须大于 0。")

    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-ss", f"{start:.6f}",
        "-i", str(input_path),
        "-t", f"{duration:.6f}",
        "-map", "0",
        "-map_metadata", "0",
        "-c", "copy",
        "-reset_timestamps", "1",
        "-avoid_negative_ts", "make_zero",
    ]

    if output_path.suffix.lower() in FASTSTART_SUFFIXES:
        cmd += ["-movflags", "+faststart"]

    cmd.append(str(output_path))
    return cmd


def create_segment_file(ffmpeg_bin: str, input_path: Path, start: float, end: float, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_ffmpeg_cut_cmd(ffmpeg_bin, input_path, start, end, output_path)
    r = run_cmd(cmd)

    if r.returncode != 0:
        raise RuntimeError(
            f"ffmpeg 切段失败：\n"
            f"输出：{output_path.name}\n"
            f"错误：{r.stderr.strip()}"
        )

    if not output_path.exists():
        raise RuntimeError(f"切段完成后未找到输出文件：{output_path}")

    return output_path.stat().st_size


def verify_playable(ffprobe_bin: str, output_path: Path):
    """
    基础校验：能被 ffprobe 正常读取到时长。
    """
    cmd = [
        ffprobe_bin,
        "-v", "error",
        "-show_entries", "format=duration",
        "-of", "default=nokey=1:noprint_wrappers=1",
        str(output_path)
    ]
    r = run_cmd(cmd)

    if r.returncode != 0:
        raise RuntimeError(f"输出文件不可探测：{output_path.name}")

    txt = (r.stdout or "").strip()
    try:
        dur = float(txt)
    except Exception:
        dur = 0.0

    if dur <= 0:
        raise RuntimeError(f"输出文件时长异常，可能不可独立播放：{output_path.name}")


def perform_split(
    media: MediaInfo,
    plan,
    output_dir: Path,
    max_size_mb: float,
    ffmpeg_bin: str,
    ffprobe_bin: str,
    log_func=None
):
    output_dir.mkdir(parents=True, exist_ok=True)
    cap_bytes = int(max_size_mb * BYTES_PER_MB)

    results = []
    for item in plan:
        out_path = output_dir / item.file_name

        if log_func:
            log_func(f"正式输出：{item.file_name}")

        actual_size = create_segment_file(
            ffmpeg_bin=ffmpeg_bin,
            input_path=media.path,
            start=item.start,
            end=item.end,
            output_path=out_path
        )

        verify_playable(ffprobe_bin, out_path)

        if actual_size > cap_bytes:
            raise RuntimeError(
                f"输出文件超过限制：{item.file_name}\n"
                f"实际大小：{format_mb(actual_size)}\n"
                f"上限：{max_size_mb:.2f} MB\n"
                f"建议把界面中的最大大小再调低一点，比如减少 10~30MB。"
            )

        results.append((out_path, actual_size))

        if log_func:
            log_func(f"完成：{item.file_name} | {format_mb(actual_size)}")

    return results


# ================================
# 分割规划
# ================================
def make_plan(
    media: MediaInfo,
    max_size_mb: float,
    ffprobe_bin: str,
    log_func=None
):
    if max_size_mb <= 1:
        raise RuntimeError("最大大小必须大于 1 MB。")

    cap_bytes = int(max_size_mb * BYTES_PER_MB)
    headroom_bytes = int(HEADROOM_MB * BYTES_PER_MB)
    working_cap_bytes = max(1, cap_bytes - headroom_bytes)

    if log_func:
        log_func(f"读取关键帧信息：{media.path.name}")

    keyframes = get_keyframes(media.path, media.duration, ffprobe_bin)

    if log_func:
        log_func(f"关键帧数量：{len(keyframes)}")
        log_func(f"目标上限：{max_size_mb:.2f} MB，内部工作上限：{working_cap_bytes / BYTES_PER_MB:.2f} MB")

    plan = []
    start = 0.0
    idx = 1
    stem = media.path.stem
    suffix = media.suffix or DEFAULT_SUFFIX

    while start < media.duration - EPS:
        if log_func:
            log_func(f"规划第 {idx} 段：起点 {format_seconds(start)}")

        end, est_size = choose_best_end(
            media=media,
            start=start,
            duration=media.duration,
            keyframes=keyframes,
            working_cap_bytes=working_cap_bytes,
            log_func=log_func
        )

        if end <= start + EPS:
            raise RuntimeError("规划失败：切点没有向前推进。")

        file_name = build_output_name(stem, idx, suffix)
        plan.append(
            PlanItem(
                idx=idx,
                start=start,
                end=end,
                expected_size=est_size,
                file_name=file_name
            )
        )

        start = end
        idx += 1

        if idx > 9999:
            raise RuntimeError("分段数量异常过多，已停止。")

    return plan


# ================================
# GUI
# ================================
class App:
    def __init__(self, root):
        self.root = root
        self.root.title("视频无损分割（按最大大小，快速预估版）")
        self.root.geometry("1120x780")

        self.media = None
        self.plan = None
        self.worker_running = False

        self.ffmpeg_var = tk.StringVar(value=DEFAULT_FFMPEG_PATH)
        self.ffprobe_var = tk.StringVar(value=DEFAULT_FFPROBE_PATH)
        self.video_var = tk.StringVar()
        self.outdir_var = tk.StringVar()
        self.max_mb_var = tk.StringVar(value="900")

        self.last_ffmpeg_bin = None
        self.last_ffprobe_bin = None

        self.build_ui()

    def build_ui(self):
        frm = ttk.Frame(self.root, padding=12)
        frm.pack(fill="both", expand=True)

        # ffmpeg 路径
        row0 = ttk.Frame(frm)
        row0.pack(fill="x", pady=4)
        ttk.Label(row0, text="ffmpeg 路径：", width=12).pack(side="left")
        ttk.Entry(row0, textvariable=self.ffmpeg_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row0, text="选择 ffmpeg.exe", command=self.choose_ffmpeg).pack(side="left")

        # ffprobe 路径
        row00 = ttk.Frame(frm)
        row00.pack(fill="x", pady=4)
        ttk.Label(row00, text="ffprobe 路径：", width=12).pack(side="left")
        ttk.Entry(row00, textvariable=self.ffprobe_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row00, text="选择 ffprobe.exe", command=self.choose_ffprobe).pack(side="left")

        ttk.Label(
            frm,
            text="可直接输入 exe 路径；也可留空让程序自动使用系统 PATH。",
            justify="left"
        ).pack(anchor="w", pady=(2, 8))

        # 选择视频
        row1 = ttk.Frame(frm)
        row1.pack(fill="x", pady=4)
        ttk.Label(row1, text="视频文件：", width=12).pack(side="left")
        ttk.Entry(row1, textvariable=self.video_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row1, text="选择文件", command=self.choose_video).pack(side="left")

        # 输出目录
        row2 = ttk.Frame(frm)
        row2.pack(fill="x", pady=4)
        ttk.Label(row2, text="输出目录：", width=12).pack(side="left")
        ttk.Entry(row2, textvariable=self.outdir_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(row2, text="选择目录", command=self.choose_outdir).pack(side="left")

        # 最大大小
        row3 = ttk.Frame(frm)
        row3.pack(fill="x", pady=4)
        ttk.Label(row3, text="每段最大大小：", width=12).pack(side="left")
        ttk.Entry(row3, textvariable=self.max_mb_var, width=18).pack(side="left", padx=4)
        ttk.Label(row3, text="MB（十进制，1MB=1,000,000字节）").pack(side="left")

        # 说明
        hint = (
            "说明：\n"
            "1. 分析阶段为快速估算，不再反复临时切文件，所以会快很多。\n"
            "2. 正式分割仍使用无损 copy，并校验每段是否能独立探测播放。\n"
            "3. 纯无损分割会受关键帧限制，所以切点不会完全任意。\n"
            "4. 如果云端上限很死，比如 900MB，建议界面里填 880 或 890 更稳。"
        )
        ttk.Label(frm, text=hint, justify="left").pack(anchor="w", pady=(8, 8))

        # 按钮
        row4 = ttk.Frame(frm)
        row4.pack(fill="x", pady=6)
        self.btn_probe = ttk.Button(row4, text="分析并预估", command=self.on_analyze)
        self.btn_probe.pack(side="left", padx=(0, 6))

        self.btn_split = ttk.Button(row4, text="开始正式分割", command=self.on_split)
        self.btn_split.pack(side="left", padx=(0, 6))

        self.btn_clear = ttk.Button(row4, text="清空日志", command=self.clear_log)
        self.btn_clear.pack(side="left")

        # 预估表格
        ttk.Label(frm, text="预估分段结果（快速估算）：").pack(anchor="w", pady=(12, 4))
        cols = ("idx", "name", "start", "end", "size")
        self.tree = ttk.Treeview(frm, columns=cols, show="headings", height=12)
        self.tree.heading("idx", text="序号")
        self.tree.heading("name", text="文件名")
        self.tree.heading("start", text="开始时间")
        self.tree.heading("end", text="结束时间")
        self.tree.heading("size", text="预计大小")
        self.tree.column("idx", width=70, anchor="center")
        self.tree.column("name", width=470)
        self.tree.column("start", width=140, anchor="center")
        self.tree.column("end", width=140, anchor="center")
        self.tree.column("size", width=140, anchor="center")
        self.tree.pack(fill="both", expand=False)

        # 日志
        ttk.Label(frm, text="运行日志：").pack(anchor="w", pady=(12, 4))
        self.txt = tk.Text(frm, height=16, wrap="word")
        self.txt.pack(fill="both", expand=True)

    def _append_log(self, msg: str):
        self.txt.insert("end", msg.rstrip() + "\n")
        self.txt.see("end")

    def log(self, msg: str):
        self.root.after(0, lambda m=msg: self._append_log(m))

    def clear_log(self):
        self.txt.delete("1.0", "end")

    def choose_ffmpeg(self):
        p = filedialog.askopenfilename(
            title="选择 ffmpeg.exe",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")]
        )
        if p:
            self.ffmpeg_var.set(p)

    def choose_ffprobe(self):
        p = filedialog.askopenfilename(
            title="选择 ffprobe.exe",
            filetypes=[("Executable", "*.exe"), ("All files", "*.*")]
        )
        if p:
            self.ffprobe_var.set(p)

    def choose_video(self):
        p = filedialog.askopenfilename(
            title="选择视频文件",
            filetypes=[
                ("Video files", "*.mp4 *.mkv *.mov *.ts *.avi *.m4v *.flv *.webm *.mpg *.mpeg"),
                ("All files", "*.*")
            ]
        )
        if not p:
            return

        self.video_var.set(p)
        ip = Path(p)
        default_out = ip.parent / f"{ip.stem}_splits"
        self.outdir_var.set(str(default_out))

    def choose_outdir(self):
        p = filedialog.askdirectory(title="选择输出目录")
        if p:
            self.outdir_var.set(p)

    def set_busy(self, busy: bool):
        self.worker_running = busy
        state = "disabled" if busy else "normal"
        self.btn_probe.config(state=state)
        self.btn_split.config(state=state)
        self.btn_clear.config(state=state)

    def validate_inputs(self):
        ffmpeg_input = self.ffmpeg_var.get().strip()
        ffprobe_input = self.ffprobe_var.get().strip()

        video_path = Path(self.video_var.get().strip())
        if not self.video_var.get().strip():
            raise RuntimeError("请先选择视频文件。")
        if not video_path.exists():
            raise RuntimeError("视频文件不存在。")

        outdir = Path(self.outdir_var.get().strip())
        if not self.outdir_var.get().strip():
            raise RuntimeError("请指定输出目录。")

        try:
            max_size_mb = float(self.max_mb_var.get().strip())
        except Exception:
            raise RuntimeError("最大大小必须是数字。")

        if max_size_mb <= 1:
            raise RuntimeError("最大大小必须大于 1 MB。")

        return ffmpeg_input, ffprobe_input, video_path, outdir, max_size_mb

    def fill_plan_table(self, plan):
        for item in self.tree.get_children():
            self.tree.delete(item)

        for x in plan:
            self.tree.insert(
                "",
                "end",
                values=(
                    x.idx,
                    x.file_name,
                    format_seconds(x.start),
                    format_seconds(x.end),
                    format_mb(x.expected_size),
                )
            )

    def run_in_thread(self, target):
        if self.worker_running:
            return

        self.set_busy(True)

        def wrapper():
            try:
                target()
            except Exception as e:
                err_msg = str(e)
                self.root.after(0, lambda msg=err_msg: messagebox.showerror("错误", msg))
            finally:
                self.root.after(0, lambda: self.set_busy(False))

        threading.Thread(target=wrapper, daemon=True).start()

    def on_analyze(self):
        def task():
            ffmpeg_input, ffprobe_input, video_path, outdir, max_size_mb = self.validate_inputs()
            ffmpeg_bin, ffprobe_bin = ensure_tools(ffmpeg_input, ffprobe_input)

            self.last_ffmpeg_bin = ffmpeg_bin
            self.last_ffprobe_bin = ffprobe_bin

            self.root.after(0, self.clear_log)
            self.log("开始分析……")
            self.log(f"ffmpeg：{ffmpeg_bin}")
            self.log(f"ffprobe：{ffprobe_bin}")

            media = probe_media(video_path, ffprobe_bin)
            self.media = media

            self.log(f"文件：{media.path.name}")
            self.log(f"大小：{format_mb(media.file_size)}")
            self.log(f"时长：{format_seconds(media.duration)}")
            self.log(f"容器：{media.format_name or '未知'}")
            self.log(f"平均码率：{media.bitrate / 1_000_000:.3f} Mbps")

            plan = make_plan(
                media=media,
                max_size_mb=max_size_mb,
                ffprobe_bin=ffprobe_bin,
                log_func=self.log
            )
            self.plan = plan

            self.root.after(0, lambda: self.fill_plan_table(plan))

            total_preview = sum(x.expected_size for x in plan)
            self.log("——")
            self.log(f"预估完成：共 {len(plan)} 段")
            self.log(f"预估总大小：{format_mb(total_preview)}")
            self.log(f"输出目录：{outdir}")

        self.run_in_thread(task)

    def on_split(self):
        def task():
            ffmpeg_input, ffprobe_input, video_path, outdir, max_size_mb = self.validate_inputs()
            ffmpeg_bin, ffprobe_bin = ensure_tools(ffmpeg_input, ffprobe_input)

            need_rebuild_plan = (
                self.media is None
                or self.plan is None
                or self.media.path != video_path
                or self.last_ffmpeg_bin != ffmpeg_bin
                or self.last_ffprobe_bin != ffprobe_bin
            )

            if need_rebuild_plan:
                self.log("未发现可用预估方案，先自动分析……")
                media = probe_media(video_path, ffprobe_bin)
                self.media = media
                self.last_ffmpeg_bin = ffmpeg_bin
                self.last_ffprobe_bin = ffprobe_bin

                plan = make_plan(
                    media=media,
                    max_size_mb=max_size_mb,
                    ffprobe_bin=ffprobe_bin,
                    log_func=self.log
                )
                self.plan = plan
                self.root.after(0, lambda: self.fill_plan_table(plan))

            self.log("开始正式分割……")

            results = perform_split(
                media=self.media,
                plan=self.plan,
                output_dir=outdir,
                max_size_mb=max_size_mb,
                ffmpeg_bin=ffmpeg_bin,
                ffprobe_bin=ffprobe_bin,
                log_func=self.log
            )

            self.log("——")
            self.log("全部完成：")
            for p, sz in results:
                self.log(f"{p.name} | {format_mb(sz)}")

            self.root.after(
                0,
                lambda: messagebox.showinfo("完成", f"分割完成，共输出 {len(results)} 个文件。")
            )

        self.run_in_thread(task)


def main():
    root = tk.Tk()
    try:
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
    except Exception:
        pass

    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()