"""
RealBeats - one player for audio AND video (Tkinter + pygame + OpenCV)

Open any file: audio plays with the RealBeats logo on screen (like VLC),
video plays on the same screen. No mode switching.

Install:
    pip install pygame mutagen opencv-python pillow imageio-ffmpeg

Custom logo: put an image called  logo.png  (or logo.jpg) next to this script
and it will be shown instead of the "RealBeats" text.

Shortcuts:
    Space play/pause   Left/Right seek (5s audio, 10s video)   Up/Down volume
    M mute   N/P next/previous   F fullscreen   L playlist   Ctrl+O open   Esc exit fullscreen

You can also run:  python realbeats.py somefile.mp4 song.mp3
"""
import os
import random
import shutil
import subprocess
import sys
import threading
import time
import tkinter as tk
import tkinter.font as tkfont
from tkinter import filedialog, messagebox, ttk

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

# Crisp rendering on high-DPI Windows screens (must happen before Tk starts)
if sys.platform == "win32":
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass

# ----------------------------------------------------------------------------
# Optional dependencies - the app degrades gracefully if they're missing
# ----------------------------------------------------------------------------
try:
    from mutagen import File as MutagenFile
    HAS_MUTAGEN = True
except ImportError:
    HAS_MUTAGEN = False

try:
    from PIL import Image, ImageTk
    HAS_PIL = True
except ImportError:
    HAS_PIL = False

try:
    import cv2
    HAS_CV2 = HAS_PIL
except ImportError:
    HAS_CV2 = False

try:
    import imageio_ffmpeg
except ImportError:
    imageio_ffmpeg = None


# ----------------------------------------------------------------------------
# Theme
# ----------------------------------------------------------------------------
BG = "#0E0E13"
STAGE = "#050507"
PANEL = "#17171F"
BAR = "#13131A"
CARD = "#22222C"
CARD_HOVER = "#2D2D3A"
ACCENT = "#FF8A1F"
ACCENT_HOVER = "#FFA24D"
ON_ACCENT = "#1A1008"
TEXT = "#F4F4F6"
DIM = "#8D8D99"
TROUGH = "#34343F"
SELECT = "#2E2118"

if sys.platform == "win32":
    FONT = "Segoe UI"
elif sys.platform == "darwin":
    FONT = "Helvetica Neue"
else:
    FONT = "Helvetica"

AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus")
VIDEO_EXTS = (".mp4", ".avi", ".mov", ".mkv", ".webm", ".m4v", ".wmv", ".flv", ".mpg", ".mpeg")
UI = 1.0  # UI scale factor, set once Tk exists


def s(n):
    """Scale a pixel size for the current display."""
    return int(round(n * UI))


def format_time(seconds):
    if seconds is None or seconds < 0 or seconds != seconds:
        seconds = 0
    m, sec = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h:d}:{m:02d}:{sec:02d}" if h else f"{m:d}:{sec:02d}"


def rounded_rect(c, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def detect_kind(path):
    ext = os.path.splitext(path)[1].lower()
    if ext in VIDEO_EXTS:
        return "video"
    if ext in AUDIO_EXTS:
        return "audio"
    return None


# ----------------------------------------------------------------------------
# Custom widgets (drawn on Canvas so they look the same everywhere)
# ----------------------------------------------------------------------------
def draw_icon(c, name, size, color, frac=0.6):
    k = size * frac / 24
    o = size * (1 - frac) / 2
    lw = max(2, int(2 * k))

    def T(*pts):
        return [o + v * k for v in pts]

    if name == "play":
        c.create_polygon(T(8, 5, 8, 19, 19, 12), fill=color, outline=color,
                         width=max(1, int(k)), joinstyle="round")
    elif name == "pause":
        c.create_rectangle(*T(7, 5, 10.5, 19), fill=color, outline="")
        c.create_rectangle(*T(13.5, 5, 17, 19), fill=color, outline="")
    elif name == "prev":
        c.create_rectangle(*T(6, 5, 8.5, 19), fill=color, outline="")
        c.create_polygon(T(19, 5, 19, 19, 9.5, 12), fill=color, outline=color, joinstyle="round")
    elif name == "next":
        c.create_rectangle(*T(15.5, 5, 18, 19), fill=color, outline="")
        c.create_polygon(T(5, 5, 5, 19, 14.5, 12), fill=color, outline=color, joinstyle="round")
    elif name == "stop":
        c.create_rectangle(*T(7, 7, 17, 17), fill=color, outline="")
    elif name == "shuffle":
        shape = (5 * k, 6 * k, 3 * k)
        c.create_line(*T(3, 7, 8, 7, 15, 17, 19, 17), fill=color, width=lw,
                      arrow="last", arrowshape=shape, joinstyle="round")
        c.create_line(*T(3, 17, 8, 17, 15, 7, 19, 7), fill=color, width=lw,
                      arrow="last", arrowshape=shape, joinstyle="round")
    elif name in ("repeat", "repeat_one"):
        shape = (5 * k, 6 * k, 3 * k)
        c.create_line(*T(5, 11, 5, 8, 8, 6, 19, 6), fill=color, width=lw,
                      arrow="last", arrowshape=shape, joinstyle="round")
        c.create_line(*T(19, 13, 19, 16, 16, 18, 5, 18), fill=color, width=lw,
                      arrow="last", arrowshape=shape, joinstyle="round")
        if name == "repeat_one":
            c.create_text(*T(12, 12), text="1", fill=color,
                          font=(FONT, max(6, int(7 * k)), "bold"))
    elif name in ("volume", "mute"):
        c.create_polygon(T(4, 9, 8, 9, 13, 5, 13, 19, 8, 15, 4, 15), fill=color,
                         outline=color, joinstyle="round")
        if name == "volume":
            c.create_arc(*T(9, 8, 17, 16), start=-55, extent=110, style="arc",
                         outline=color, width=lw)
            c.create_arc(*T(5, 4, 21, 20), start=-55, extent=110, style="arc",
                         outline=color, width=lw)
        else:
            c.create_line(*T(16, 9.5, 21, 14.5), fill=color, width=lw, capstyle="round")
            c.create_line(*T(21, 9.5, 16, 14.5), fill=color, width=lw, capstyle="round")
    elif name == "expand":
        for pts in ((4, 9, 4, 4, 9, 4), (15, 4, 20, 4, 20, 9),
                    (20, 15, 20, 20, 15, 20), (9, 20, 4, 20, 4, 15)):
            c.create_line(*T(*pts), fill=color, width=lw, joinstyle="round", capstyle="round")
    elif name == "list":
        for y in (7, 12, 17):
            c.create_line(*T(4, y, 4.1, y), fill=color, width=lw + 1, capstyle="round")
        c.create_line(*T(8, 7, 20, 7), fill=color, width=lw, capstyle="round")
        c.create_line(*T(8, 12, 20, 12), fill=color, width=lw, capstyle="round")
        c.create_line(*T(8, 17, 16, 17), fill=color, width=lw, capstyle="round")


class IconButton(tk.Canvas):
    def __init__(self, parent, icon, command, size=40, color=TEXT, hover=ACCENT,
                 circle=None, circle_hover=None, icon_frac=0.6, bg=None):
        px = s(size)
        super().__init__(parent, width=px, height=px, bg=bg or parent["bg"],
                         highlightthickness=0, bd=0, cursor="hand2")
        self.size = px
        self.icon = icon
        self.command = command
        self.color = color
        self.hover_color = hover
        self.circle = circle
        self.circle_hover = circle_hover or circle
        self.icon_frac = icon_frac
        self._hover = False
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self._draw()

    def _click(self, e):
        if 0 <= e.x <= self.size and 0 <= e.y <= self.size and self.command:
            self.command()

    def _set_hover(self, v):
        self._hover = v
        self._draw()

    def set_icon(self, icon):
        if icon != self.icon:
            self.icon = icon
            self._draw()

    def set_color(self, color):
        self.color = color
        self._draw()

    def _draw(self):
        self.delete("all")
        sz = self.size
        if self.circle:
            fill = self.circle_hover if self._hover else self.circle
            self.create_oval(2, 2, sz - 2, sz - 2, fill=fill, outline="")
            col = self.color
        else:
            col = self.hover_color if self._hover else self.color
        draw_icon(self, self.icon, sz, col, self.icon_frac)


class PillButton(tk.Canvas):
    def __init__(self, parent, text, command, primary=False, bg=None):
        self.font = tkfont.Font(family=FONT, size=10, weight="bold")
        w = self.font.measure(text) + s(32)
        h = s(34)
        super().__init__(parent, width=w, height=h, bg=bg or parent["bg"],
                         highlightthickness=0, bd=0, cursor="hand2")
        self.w, self.h = w, h
        self.text = text
        self.command = command
        self.primary = primary
        self._hover = False
        self.bind("<Enter>", lambda e: self._set_hover(True))
        self.bind("<Leave>", lambda e: self._set_hover(False))
        self.bind("<ButtonRelease-1>", self._click)
        self._draw()

    def _click(self, e):
        if 0 <= e.x <= self.w and 0 <= e.y <= self.h:
            self.command()

    def _set_hover(self, v):
        self._hover = v
        self._draw()

    def _draw(self):
        self.delete("all")
        if self.primary:
            fill = ACCENT_HOVER if self._hover else ACCENT
            fg = ON_ACCENT
        else:
            fill = CARD_HOVER if self._hover else CARD
            fg = TEXT
        rounded_rect(self, 1, 1, self.w - 1, self.h - 1, self.h // 2, fill=fill, outline="")
        self.create_text(self.w // 2, self.h // 2, text=self.text, fill=fg, font=self.font)


class Slider(tk.Canvas):
    """Slim modern slider. Value is 0..1."""

    def __init__(self, parent, bg, width=None, on_drag=None, on_commit=None, value=0.0):
        kw = {"width": s(width)} if width else {}
        super().__init__(parent, height=s(20), bg=bg, highlightthickness=0, bd=0,
                         cursor="hand2", **kw)
        self.value = value
        self.dragging = False
        self.enabled = True
        self._hover = False
        self.on_drag = on_drag
        self.on_commit = on_commit
        self.bind("<Configure>", lambda e: self._draw())
        self.bind("<Enter>", lambda e: self._hov(True))
        self.bind("<Leave>", lambda e: self._hov(False))
        self.bind("<ButtonPress-1>", self._press)
        self.bind("<B1-Motion>", self._move)
        self.bind("<ButtonRelease-1>", self._release)

    def _hov(self, v):
        self._hover = v
        self._draw()

    def set(self, v):
        if self.dragging:
            return
        self.value = min(max(v, 0.0), 1.0)
        self._draw()

    def _x_to_val(self, x):
        pad = s(8)
        w = max(self.winfo_width() - 2 * pad, 1)
        return min(max((x - pad) / w, 0.0), 1.0)

    def _press(self, e):
        if not self.enabled:
            return
        self.dragging = True
        self.value = self._x_to_val(e.x)
        self._draw()
        if self.on_drag:
            self.on_drag(self.value)

    def _move(self, e):
        if not self.dragging:
            return
        self.value = self._x_to_val(e.x)
        self._draw()
        if self.on_drag:
            self.on_drag(self.value)

    def _release(self, e):
        if not self.dragging:
            return
        self.value = self._x_to_val(e.x)
        self.dragging = False
        self._draw()
        if self.on_commit:
            self.on_commit(self.value)

    def _draw(self):
        self.delete("all")
        w, h = self.winfo_width(), self.winfo_height()
        if w < 4:
            return
        pad, cy, tw = s(8), h // 2, s(4)
        x2 = pad + (w - 2 * pad) * self.value
        self.create_line(pad, cy, w - pad, cy, width=tw, fill=TROUGH, capstyle="round")
        if self.value > 0:
            self.create_line(pad, cy, x2, cy, width=tw, fill=ACCENT, capstyle="round")
        if (self._hover or self.dragging) and self.enabled:
            r = s(6)
            self.create_oval(x2 - r, cy - r, x2 + r, cy + r, fill="white", outline="")


# ----------------------------------------------------------------------------
# Live audio streaming for video (ffmpeg -> pygame mixer, starts instantly)
# ----------------------------------------------------------------------------
class AudioStream:
    """Pipes a video's audio from ffmpeg straight into the mixer in small chunks.

    No waiting for a full extraction: sound starts within a fraction of a second
    and seeking just restarts the stream at the new position.
    """

    CHUNK_SECONDS = 0.2

    def __init__(self, ffmpeg, path, start, get_volume):
        self.start = start
        self.start_wall = 0.0
        self.started = False
        self.failed = False
        self._stop = False
        self._get_volume = get_volume
        self._proc = None
        freq, _fmt, ch = pygame.mixer.get_init()
        self._frame = ch * 2
        self._chunk = int(freq * self.CHUNK_SECONDS) * self._frame
        self._cmd = [ffmpeg, "-v", "error", "-ss", f"{start:.3f}", "-i", path, "-vn",
                     "-ac", str(ch), "-ar", str(freq), "-f", "s16le", "-"]
        self.channel = pygame.mixer.Channel(0)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        try:
            self._proc = subprocess.Popen(
                self._cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except Exception:
            self.failed = True
            return
        if self._stop:
            self._kill()
            return
        pending = None
        while not self._stop:
            if pending is None:
                data = self._proc.stdout.read(self._chunk)
                data = data[:len(data) // self._frame * self._frame]
                if not data:
                    if not self.started:
                        self.failed = True  # no audio track / bad seek
                    break
                snd = pygame.mixer.Sound(buffer=data)
                snd.set_volume(self._get_volume())
                pending = snd
            if self._stop:
                break
            if not self.started:
                self.start_wall = time.perf_counter()
                self.channel.play(pending)
                self.started = True
                pending = None
            elif self.channel.get_queue() is None:
                self.channel.queue(pending)
                pending = None
            else:
                time.sleep(0.004)
        self._kill()

    def _kill(self):
        try:
            self._proc.kill()
        except Exception:
            pass

    def stop(self):
        self._stop = True
        self._kill()
        self._thread.join(timeout=0.5)
        try:
            self.channel.stop()
        except pygame.error:
            pass


# ----------------------------------------------------------------------------
# The player: one screen, audio or video decided by the file
# ----------------------------------------------------------------------------
class Player(tk.Frame):
    REPEAT_OFF, REPEAT_ONE, REPEAT_ALL = "off", "one", "all"

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        # library
        self.playlist = []          # dicts: path, title, duration, kind
        self.current_index = -1
        # engine state
        self.kind = None            # "audio" | "video" | None
        self.state = "idle"         # "idle" | "playing" | "paused"
        self.duration = 0.0
        self._clock_start = 0.0
        self._paused_pos = 0.0
        self._started_wall = 0.0
        # video
        self.cap = None
        self.fps = 25.0
        self._last_frame = -1
        self._job = None
        self._frame = None
        self._photo = None
        self._img_item = None
        self._ffmpeg = self._find_ffmpeg()
        self._astream = None
        self._awaiting_audio = False
        self._await_pos = 0.0
        self._await_since = 0.0
        self._video_path = None
        self._video_silent = False
        # options
        self.repeat_mode = self.REPEAT_OFF
        self.shuffle_on = False
        self._muted = False
        self._pre_mute = 0.7
        self._fs = False
        self._panel_visible = True
        self._was_panel = True
        self._click_job = None
        self._logo_font = None
        self._logo_photo = None
        self._logo_src = self._load_logo()
        pygame.mixer.music.set_volume(0.7)

        self._build()
        self._tick()

    # ---- UI ---------------------------------------------------------------
    def _load_logo(self):
        if not HAS_PIL:
            return None
        here = os.path.dirname(os.path.abspath(__file__))
        for name in ("logo.png", "logo.jpg", "logo.jpeg"):
            p = os.path.join(here, name)
            if os.path.exists(p):
                try:
                    return Image.open(p).convert("RGBA")
                except Exception:
                    pass
        return None

    def _build(self):
        # bottom bar first so it always keeps its space
        bar = tk.Frame(self, bg=BAR)
        bar.pack(side="bottom", fill="x")
        seek_row = tk.Frame(bar, bg=BAR)
        seek_row.pack(fill="x", padx=24, pady=(12, 0))
        self.elapsed_var = tk.StringVar(value="0:00")
        self.total_var = tk.StringVar(value="0:00")
        tk.Label(seek_row, textvariable=self.elapsed_var, fg=DIM, bg=BAR, width=6,
                 font=(FONT, 9)).pack(side="left")
        self.seek = Slider(seek_row, BAR, on_drag=self._seek_preview, on_commit=self._seek_commit)
        self.seek.pack(side="left", fill="x", expand=True, padx=4)
        tk.Label(seek_row, textvariable=self.total_var, fg=DIM, bg=BAR, width=6,
                 font=(FONT, 9)).pack(side="left")

        ctl = tk.Frame(bar, bg=BAR)
        ctl.pack(fill="x", padx=24, pady=(4, 12))
        ctl.columnconfigure(0, weight=1)
        ctl.columnconfigure(2, weight=1)

        left = tk.Frame(ctl, bg=BAR)
        left.grid(row=0, column=0, sticky="w")
        self.open_pill = PillButton(left, "Open  ▴", self._open_menu, primary=True, bg=BAR)
        self.open_pill.pack(side="left")
        IconButton(left, "stop", self.stop_media, size=36, color=DIM, bg=BAR).pack(side="left", padx=(10, 0))

        mid = tk.Frame(ctl, bg=BAR)
        mid.grid(row=0, column=1)
        self.shuffle_btn = IconButton(mid, "shuffle", self.toggle_shuffle, size=38, color=DIM, bg=BAR)
        self.shuffle_btn.pack(side="left", padx=6)
        IconButton(mid, "prev", self.play_previous, size=44, bg=BAR).pack(side="left", padx=6)
        self.play_btn = IconButton(mid, "play", self.toggle_play, size=56, color=ON_ACCENT,
                                   circle=ACCENT, circle_hover=ACCENT_HOVER, icon_frac=0.5, bg=BAR)
        self.play_btn.pack(side="left", padx=8)
        IconButton(mid, "next", lambda: self.play_next(), size=44, bg=BAR).pack(side="left", padx=6)
        self.repeat_btn = IconButton(mid, "repeat", self.cycle_repeat, size=38, color=DIM, bg=BAR)
        self.repeat_btn.pack(side="left", padx=6)

        right = tk.Frame(ctl, bg=BAR)
        right.grid(row=0, column=2, sticky="e")
        self.list_btn = IconButton(right, "list", self.toggle_panel, size=34, color=ACCENT, bg=BAR)
        self.list_btn.pack(side="left")
        IconButton(right, "expand", self.toggle_fullscreen, size=34, bg=BAR).pack(side="left", padx=(0, 8))
        self.mute_btn = IconButton(right, "volume", self.toggle_mute, size=34, bg=BAR)
        self.mute_btn.pack(side="left")
        self.volume = Slider(right, BAR, width=100, on_drag=self._on_volume, value=0.7)
        self.volume.pack(side="left")

        # body: playlist panel (right) + stage (left, expands)
        body = tk.Frame(self, bg=BG)
        body.pack(side="top", fill="both", expand=True)

        self.panel = tk.Frame(body, bg=PANEL, width=s(330))
        self.panel.pack(side="right", fill="y")
        self.panel.pack_propagate(False)
        head = tk.Frame(self.panel, bg=PANEL)
        head.pack(fill="x", padx=16, pady=(16, 8))
        self.queue_var = tk.StringVar(value="Playlist")
        tk.Label(head, textvariable=self.queue_var, font=(FONT, 11, "bold"), fg=TEXT,
                 bg=PANEL).pack(side="left")
        PillButton(head, "Clear", self.clear_playlist, bg=PANEL).pack(side="right", padx=(6, 0))
        PillButton(head, "Remove", self.remove_selected, bg=PANEL).pack(side="right")

        tree_wrap = tk.Frame(self.panel, bg=PANEL)
        tree_wrap.pack(fill="both", expand=True, padx=(10, 6), pady=(0, 10))
        self.tree = ttk.Treeview(tree_wrap, columns=("n", "title", "dur"), show="tree",
                                 style="RB.Treeview", selectmode="extended")
        self.tree.column("#0", width=0, stretch=False)
        self.tree.column("n", width=s(34), anchor="center", stretch=False)
        self.tree.column("title", anchor="w")
        self.tree.column("dur", width=s(56), anchor="e", stretch=False)
        self.tree["displaycolumns"] = ("n", "title", "dur")
        self.tree.tag_configure("playing", foreground=ACCENT)
        sb = ttk.Scrollbar(tree_wrap, orient="vertical", command=self.tree.yview,
                           style="RB.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y", padx=(4, 0))
        self.tree.bind("<Double-Button-1>", self._on_tree_double)
        self.tree.bind("<space>", lambda e: "break")
        self.empty_label = tk.Label(tree_wrap, text="Playlist is empty\nUse Open to add media",
                                    font=(FONT, 10), fg=DIM, bg=PANEL, justify="center")
        self.empty_label.place(relx=0.5, rely=0.45, anchor="center")

        self.canvas = tk.Canvas(body, bg=STAGE, highlightthickness=0, bd=0)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)
        self._body = body

    # ---- Stage (logo / video frames) --------------------------------------
    def _show_logo(self):
        """VLC-style idle/audio screen: big RealBeats logo in the middle."""
        c = self.canvas
        c.delete("all")
        self._img_item = None
        w, h = c.winfo_width(), c.winfo_height()
        if w < 20 or h < 20:
            return
        cy = h * 0.46
        if self._logo_src is not None:
            iw, ih = self._logo_src.size
            sc = min(w * 0.6 / iw, h * 0.42 / ih)
            nw, nh = max(1, int(iw * sc)), max(1, int(ih * sc))
            self._logo_photo = ImageTk.PhotoImage(self._logo_src.resize((nw, nh), Image.LANCZOS))
            c.create_image(w // 2, int(cy), image=self._logo_photo)
            ty = cy + nh / 2 + s(30)
        else:
            px = int(max(s(32), min(w / 7.5, h / 3.0, s(120))))
            self._logo_font = tkfont.Font(family=FONT, size=-px, weight="bold")
            w1 = self._logo_font.measure("Real")
            w2 = self._logo_font.measure("Beats")
            x0 = (w - w1 - w2) / 2
            c.create_text(x0, cy, text="Real", anchor="w", fill=TEXT, font=self._logo_font)
            c.create_text(x0 + w1, cy, text="Beats", anchor="w", fill=ACCENT, font=self._logo_font)
            ty = cy + px * 0.85
        if self.kind == "audio" and 0 <= self.current_index < len(self.playlist):
            caption = self.playlist[self.current_index]["title"]
        else:
            caption = "Open a file to start  ·  Ctrl+O"
        c.create_text(w // 2, ty, text=caption, fill=DIM, font=(FONT, 12),
                      width=int(w * 0.8), justify="center")

    def _on_resize(self, _e):
        if self.kind == "video" and self.cap is not None:
            self._render()
        else:
            self._show_logo()

    def _on_click(self, _e):
        if self._click_job:
            self.after_cancel(self._click_job)
        self._click_job = self.after(220, self._single_click)

    def _single_click(self):
        self._click_job = None
        self.toggle_play()

    def _on_double_click(self, _e):
        if self._click_job:
            self.after_cancel(self._click_job)
            self._click_job = None
        self.toggle_fullscreen()

    def _render(self, frame=None):
        if frame is not None:
            self._frame = frame
        if self._frame is None:
            return
        cw, ch = self.canvas.winfo_width(), self.canvas.winfo_height()
        if cw < 2 or ch < 2:
            return
        h, w = self._frame.shape[:2]
        scale = min(cw / w, ch / h)
        nw, nh = max(1, int(w * scale)), max(1, int(h * scale))
        img = cv2.resize(self._frame, (nw, nh),
                         interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        self._photo = ImageTk.PhotoImage(Image.fromarray(img))
        if self._img_item is None:
            self.canvas.delete("all")
            self._img_item = self.canvas.create_image(cw // 2, ch // 2, image=self._photo)
        else:
            self.canvas.coords(self._img_item, cw // 2, ch // 2)
            self.canvas.itemconfig(self._img_item, image=self._photo)

    # ---- Opening media ----------------------------------------------------
    def _open_menu(self):
        menu = tk.Menu(self, tearoff=0, bg=CARD, fg=TEXT, activebackground=ACCENT,
                       activeforeground=ON_ACCENT, bd=0, relief="flat", font=(FONT, 10))
        menu.add_command(label="  Open files…", command=self.open_files)
        menu.add_command(label="  Open folder…", command=self.open_folder)
        menu.update_idletasks()
        x = self.open_pill.winfo_rootx()
        y = self.open_pill.winfo_rooty() - menu.winfo_reqheight() - 4
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def open_files(self):
        a = " ".join("*" + e for e in AUDIO_EXTS)
        v = " ".join("*" + e for e in VIDEO_EXTS)
        files = filedialog.askopenfilenames(
            title="Open media",
            filetypes=[("Media files", f"{a} {v}"), ("Audio files", a),
                       ("Video files", v), ("All files", "*.*")])
        if files:
            self.open_paths(files)

    def open_folder(self):
        folder = filedialog.askdirectory(title="Open a folder of media")
        if not folder:
            return
        found = []
        for root, _d, files in os.walk(folder):
            for name in sorted(files):
                if detect_kind(name):
                    found.append(os.path.join(root, name))
        if found:
            self.open_paths(found)
        else:
            messagebox.showinfo("RealBeats", "No audio or video files found in that folder.")

    def open_paths(self, paths):
        first = len(self.playlist)
        for p in paths:
            self._add(p)
        self._refresh_tree()
        if len(self.playlist) > first:
            self.play_index(first)

    def _add(self, path):
        if not os.path.isfile(path):
            return
        kind = detect_kind(path)
        dur = 0.0
        if kind is None:  # unknown extension: sniff it
            dur = self._probe_video(path) if HAS_CV2 else 0.0
            kind = "video" if dur > 0 else "audio"
        elif kind == "video":
            dur = self._probe_video(path) if HAS_CV2 else 0.0
        if kind == "audio" or dur == 0:
            dur = dur or self._audio_duration(path)
        self.playlist.append({
            "path": path,
            "title": os.path.splitext(os.path.basename(path))[0],
            "duration": dur,
            "kind": kind,
        })

    @staticmethod
    def _audio_duration(path):
        if HAS_MUTAGEN:
            try:
                audio = MutagenFile(path)
                if audio and audio.info and audio.info.length:
                    return float(audio.info.length)
            except Exception:
                pass
        return 0.0

    @staticmethod
    def _probe_video(path):
        try:
            cap = cv2.VideoCapture(path)
            if not cap.isOpened():
                return 0.0
            fps = cap.get(cv2.CAP_PROP_FPS)
            frames = cap.get(cv2.CAP_PROP_FRAME_COUNT)
            cap.release()
            if fps and fps == fps and frames and frames > 0:
                return frames / fps
        except Exception:
            pass
        return 0.0

    # ---- Playlist ---------------------------------------------------------
    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, t in enumerate(self.playlist):
            current = i == self.current_index
            dur = format_time(t["duration"]) if t["duration"] else "--:--"
            self.tree.insert("", "end", iid=str(i),
                             values=("▶" if current else i + 1, t["title"], dur),
                             tags=("playing",) if current else ())
        n = len(self.playlist)
        self.queue_var.set(f"Playlist  ·  {n}" if n else "Playlist")
        if n:
            self.empty_label.place_forget()
        else:
            self.empty_label.place(relx=0.5, rely=0.45, anchor="center")

    def _on_tree_double(self, e):
        row = self.tree.identify_row(e.y)
        if row:
            self.play_index(int(row))

    def remove_selected(self):
        sel = sorted((int(i) for i in self.tree.selection()), reverse=True)
        if not sel:
            return
        cur_removed = self.current_index in sel
        shift = sum(1 for i in sel if i < self.current_index)
        for idx in sel:
            del self.playlist[idx]
        if cur_removed:
            self._reset_to_idle()
        else:
            self.current_index -= shift
        self._refresh_tree()

    def clear_playlist(self):
        self.playlist.clear()
        self._reset_to_idle()
        self._refresh_tree()

    def _reset_to_idle(self):
        self._halt()
        self.kind = None
        self.current_index = -1
        self.duration = 0.0
        self.seek.set(0)
        self.elapsed_var.set("0:00")
        self.total_var.set("0:00")
        self.play_btn.set_icon("play")
        self._set_title(None)
        self._show_logo()

    def toggle_panel(self):
        if self._panel_visible:
            self.panel.pack_forget()
        else:
            self.panel.pack(side="right", fill="y", before=self.canvas)
        self._panel_visible = not self._panel_visible
        self.list_btn.set_color(ACCENT if self._panel_visible else DIM)

    # ---- Core playback ----------------------------------------------------
    def _set_title(self, title):
        self.winfo_toplevel().title(f"{title}  -  RealBeats" if title else "RealBeats")

    def _pos(self):
        if self.state == "playing":
            if self._awaiting_audio:
                return self._await_pos
            return time.perf_counter() - self._clock_start
        return self._paused_pos

    def _mark_start(self):
        self._started_wall = time.perf_counter()

    def _halt(self):
        """Stop everything and release the current media."""
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        self.state = "idle"
        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.unload()
        except Exception:
            pass
        self._stop_video_audio()
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self._frame = None

    def play_index(self, index):
        if not (0 <= index < len(self.playlist)):
            return
        self._halt()
        item = self.playlist[index]
        self.current_index = index
        self.kind = item["kind"]
        ok = self._open_video(item) if self.kind == "video" else self._open_audio(item)
        if not ok:
            self.kind = None
            self.play_btn.set_icon("play")
            self._refresh_tree()
            self._show_logo()
            return

        self.state = "playing"
        self._paused_pos = 0.0
        self._clock_start = time.perf_counter()
        self._mark_start()
        self.seek.enabled = self.duration > 0
        self.seek.set(0)
        self.elapsed_var.set("0:00")
        self.total_var.set(format_time(self.duration) if self.duration else "--:--")
        self.play_btn.set_icon("pause")
        self._set_title(item["title"])
        self._refresh_tree()
        self.tree.see(str(index))
        if self.kind == "video":
            self._begin_video_audio(0.0)
            self._loop()
        else:
            self._show_logo()

    def _open_audio(self, item):
        try:
            pygame.mixer.music.load(item["path"])
            pygame.mixer.music.set_volume(self.volume.value)
            pygame.mixer.music.play()
        except pygame.error as e:
            messagebox.showerror("Playback error", f"Could not play:\n{item['path']}\n\n{e}")
            return False
        self.duration = item["duration"]
        return True

    def _open_video(self, item):
        if not HAS_CV2:
            messagebox.showwarning(
                "Missing dependency",
                "Video playback requires opencv-python and pillow.\n\n"
                "Install with:\npip install opencv-python pillow")
            return False
        cap = cv2.VideoCapture(item["path"])
        if not cap.isOpened():
            messagebox.showerror("Playback error", f"Could not open:\n{item['path']}")
            return False
        self.cap = cap
        fps = cap.get(cv2.CAP_PROP_FPS)
        self.fps = fps if fps and fps == fps and 1 <= fps <= 120 else 25.0
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.duration = frames / self.fps if frames > 0 else 0.0
        if self.duration:
            item["duration"] = self.duration
        self._img_item = None
        self._frame = None
        self.canvas.delete("all")
        self._video_path = item["path"]
        self._video_silent = False
        self._show_frame(0)
        return True

    def toggle_play(self):
        if self.current_index == -1 or self.kind is None:
            if self.playlist:
                sel = self.tree.selection()
                self.play_index(int(sel[0]) if sel else 0)
            else:
                self.open_files()
            return
        if self.state == "playing":
            self._pause()
        elif self.state == "paused":
            self._resume()
        else:
            self.play_index(self.current_index)

    def _pause(self):
        if self.state != "playing":
            return
        self._paused_pos = self._pos()
        self.state = "paused"
        if self.kind == "audio":
            pygame.mixer.music.pause()
        else:
            if self._job:
                self.after_cancel(self._job)
                self._job = None
            self._stop_video_audio()
        self.play_btn.set_icon("play")

    def _resume(self):
        if self.state != "paused":
            return
        if self.kind == "audio":
            pygame.mixer.music.unpause()
        else:
            if self.duration and self._paused_pos >= self.duration - 0.2:
                self._paused_pos = 0.0
                self._show_frame(0)
            self._begin_video_audio(self._paused_pos)
        self._clock_start = time.perf_counter() - self._paused_pos
        if self.kind == "video" and self._awaiting_audio:
            self._await_since = time.perf_counter()
        self._mark_start()
        self.state = "playing"
        self.play_btn.set_icon("pause")
        if self.kind == "video" and self._job is None:
            self._loop()

    def stop_media(self):
        if self.kind is None:
            return
        if self.kind == "audio":
            pygame.mixer.music.stop()
            self.state = "idle"
            self._paused_pos = 0.0
        else:
            self._pause()
            self._paused_pos = 0.0
            self._show_frame(0)
        self.play_btn.set_icon("play")
        self.seek.set(0)
        self.elapsed_var.set("0:00")

    def _on_end(self):
        if self.repeat_mode == self.REPEAT_ONE:
            self.play_index(self.current_index)
        else:
            self.play_next(auto=True)

    def play_next(self, auto=False):
        if not self.playlist:
            return
        if self.shuffle_on and len(self.playlist) > 1:
            nxt = random.choice([i for i in range(len(self.playlist)) if i != self.current_index])
        else:
            nxt = self.current_index + 1
            if nxt >= len(self.playlist):
                if self.repeat_mode == self.REPEAT_ALL or not auto:
                    nxt = 0
                else:
                    self.stop_media()
                    return
        self.play_index(nxt)

    def play_previous(self):
        if not self.playlist:
            return
        if self.current_index != -1 and self._pos() > 3:
            self.play_index(self.current_index)  # restart current first
            return
        self.play_index((self.current_index - 1) % len(self.playlist))

    def toggle_shuffle(self):
        self.shuffle_on = not self.shuffle_on
        self.shuffle_btn.set_color(ACCENT if self.shuffle_on else DIM)

    def cycle_repeat(self):
        order = [self.REPEAT_OFF, self.REPEAT_ALL, self.REPEAT_ONE]
        self.repeat_mode = order[(order.index(self.repeat_mode) + 1) % 3]
        self.repeat_btn.set_icon("repeat_one" if self.repeat_mode == self.REPEAT_ONE else "repeat")
        self.repeat_btn.set_color(DIM if self.repeat_mode == self.REPEAT_OFF else ACCENT)

    # ---- Video frames -----------------------------------------------------
    def _show_frame(self, idx):
        if self.cap is None:
            return
        idx = max(0, idx)
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ok, frame = self.cap.read()
        if ok:
            self._last_frame = idx
            self._render(frame)

    def _loop(self):
        """Clock-driven video loop on the main thread: no drift, no frame pile-up."""
        self._job = None
        if self.state != "playing" or self.cap is None or self.kind != "video":
            return
        if self._awaiting_audio:
            # hold the picture until the sound is really playing, then start both together
            st = self._astream
            now = time.perf_counter()
            if st is not None and st.started:
                self._clock_start = st.start_wall - st.start
                self._awaiting_audio = False
            elif st is None or st.failed or now - self._await_since > 4.0:
                if st is not None and st.failed and st.start < 1.0:
                    self._video_silent = True  # this video simply has no audio
                self._stop_video_audio()
                self._clock_start = now - self._await_pos
            else:
                self._job = self.after(4, self._loop)
                return
        pos = time.perf_counter() - self._clock_start
        if self.duration and pos >= self.duration:
            self._on_end()
            return

        target = int(pos * self.fps)
        if target > self._last_frame:
            gap = target - self._last_frame - 1
            if gap >= 24:  # far behind: jump
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, target)
            else:          # slightly behind: drop frames to catch up
                for _ in range(gap):
                    self.cap.grab()
            ok, frame = self.cap.read()
            if not ok:
                self._on_end()
                return
            self._last_frame = target
            self._render(frame)

        next_t = (self._last_frame + 1) / self.fps
        wait_ms = int((next_t - (time.perf_counter() - self._clock_start)) * 1000)
        self._job = self.after(min(max(wait_ms, 1), 15), self._loop)

    # ---- Video audio: streamed live from ffmpeg into the mixer ------------
    @staticmethod
    def _find_ffmpeg():
        exe = shutil.which("ffmpeg")
        if exe:
            return exe
        if imageio_ffmpeg is not None:
            try:
                return imageio_ffmpeg.get_ffmpeg_exe()
            except Exception:
                return None
        return None

    def _begin_video_audio(self, pos):
        """(Re)start the audio stream at `pos`; the video loop waits for it."""
        self._stop_video_audio()
        if not self._ffmpeg or self._video_silent or not self._video_path:
            self._clock_start = time.perf_counter() - pos  # silent video
            return
        self._astream = AudioStream(self._ffmpeg, self._video_path, pos,
                                    lambda: self.volume.value)
        self._awaiting_audio = True
        self._await_pos = pos
        self._await_since = time.perf_counter()

    def _stop_video_audio(self):
        self._awaiting_audio = False
        if self._astream is not None:
            self._astream.stop()
            self._astream = None

    # ---- Seeking / volume -------------------------------------------------
    def _seek_preview(self, frac):
        self.elapsed_var.set(format_time(frac * self.duration))

    def _seek_commit(self, frac):
        self._seek_to(frac * self.duration)

    def _seek_to(self, t):
        if self.kind is None or self.duration <= 0 or self.state == "idle":
            return
        t = min(max(t, 0), max(self.duration - 0.5, 0))
        if self.kind == "audio":
            try:
                pygame.mixer.music.play(start=t)
                pygame.mixer.music.set_volume(self.volume.value)
                if self.state == "paused":
                    pygame.mixer.music.pause()
            except pygame.error:
                return
        else:
            self._show_frame(int(t * self.fps))
            if self.state == "playing":
                self._begin_video_audio(t)
        self._paused_pos = t
        self._clock_start = time.perf_counter() - t
        self._mark_start()
        self.seek.set(t / self.duration)
        self.elapsed_var.set(format_time(t))

    def seek_relative(self, direction=1):
        step = 5 if self.kind == "audio" else 10
        self._seek_to(self._pos() + direction * step)

    def _on_volume(self, v):
        pygame.mixer.music.set_volume(v)
        self._muted = v == 0
        self.mute_btn.set_icon("mute" if v == 0 else "volume")

    def toggle_mute(self):
        if self._muted:
            self.volume.value = self._pre_mute or 0.7
        else:
            self._pre_mute = self.volume.value
            self.volume.value = 0
        self.volume._draw()
        self._on_volume(self.volume.value)

    def change_volume(self, delta):
        self.volume.value = min(max(self.volume.value + delta, 0.0), 1.0)
        self.volume._draw()
        self._on_volume(self.volume.value)

    # ---- Fullscreen -------------------------------------------------------
    def toggle_fullscreen(self, force=None):
        want = (not self._fs) if force is None else force
        if want == self._fs:
            return
        self._fs = want
        self.winfo_toplevel().attributes("-fullscreen", want)
        if want:
            self._was_panel = self._panel_visible
            if self._panel_visible:
                self.toggle_panel()
        elif self._was_panel and not self._panel_visible:
            self.toggle_panel()

    # ---- Clock tick (UI + end-of-audio detection) -------------------------
    def _tick(self):
        if self.state == "playing":
            pos = self._pos()
            if not self.seek.dragging:
                self.elapsed_var.set(format_time(pos))
                if self.duration > 0:
                    self.seek.set(pos / self.duration)
            if (self.kind == "audio" and time.perf_counter() - self._started_wall > 0.6
                    and not pygame.mixer.music.get_busy()):
                self._on_end()
        self.after(200, self._tick)

    def shutdown(self):
        self._halt()


# ----------------------------------------------------------------------------
# App shell
# ----------------------------------------------------------------------------
class RealBeatsApp:
    def __init__(self):
        global UI
        try:
            pygame.mixer.init(44100, -16, 2, 1024, allowedchanges=0)
        except TypeError:
            pygame.mixer.init(44100, -16, 2, 1024)

        self.root = tk.Tk()
        try:
            UI = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            UI = 1.0
        self.root.title("RealBeats")
        self.root.geometry(f"{s(1100)}x{s(680)}")
        self.root.minsize(s(820), s(520))
        self.root.configure(bg=BG)
        self._style()

        self.player = Player(self.root)
        self.player.pack(fill="both", expand=True)

        r, p = self.root, self.player
        r.bind("<space>", lambda e: p.toggle_play())
        r.bind("<Left>", lambda e: p.seek_relative(-1))
        r.bind("<Right>", lambda e: p.seek_relative(1))
        r.bind("<Up>", lambda e: p.change_volume(0.05))
        r.bind("<Down>", lambda e: p.change_volume(-0.05))
        r.bind("<m>", lambda e: p.toggle_mute())
        r.bind("<n>", lambda e: p.play_next())
        r.bind("<p>", lambda e: p.play_previous())
        r.bind("<f>", lambda e: p.toggle_fullscreen())
        r.bind("<l>", lambda e: p.toggle_panel())
        r.bind("<Escape>", lambda e: p.toggle_fullscreen(False))
        r.bind("<Control-o>", lambda e: p.open_files())
        r.protocol("WM_DELETE_WINDOW", self._on_close)

        self._dark_title_bar()
        args = [a for a in sys.argv[1:] if os.path.isfile(a)]
        if args:
            self.root.after(300, lambda: p.open_paths(args))

    def _style(self):
        st = ttk.Style()
        try:
            st.theme_use("clam")
        except tk.TclError:
            pass
        st.configure("RB.Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                     rowheight=s(34), borderwidth=0, font=(FONT, 10))
        st.map("RB.Treeview", background=[("selected", SELECT)], foreground=[("selected", TEXT)])
        st.layout("RB.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        st.layout("RB.Vertical.TScrollbar", [("Vertical.Scrollbar.trough", {
            "sticky": "ns",
            "children": [("Vertical.Scrollbar.thumb", {"expand": "1", "sticky": "nswe"})]})])
        st.configure("RB.Vertical.TScrollbar", background=TROUGH, troughcolor=PANEL,
                     bordercolor=PANEL, lightcolor=TROUGH, darkcolor=TROUGH, width=s(10))
        st.map("RB.Vertical.TScrollbar", background=[("active", DIM)])

    def _dark_title_bar(self):
        if sys.platform != "win32":
            return
        try:
            import ctypes
            self.root.update()
            hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id())
            val = ctypes.c_int(1)
            for attr in (20, 19):
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
        except Exception:
            pass

    def _on_close(self):
        try:
            self.player.shutdown()
        except Exception:
            pass
        try:
            pygame.mixer.quit()
        except Exception:
            pass
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    RealBeatsApp().run()