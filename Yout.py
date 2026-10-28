"""
RealBeats - a modern audio & video player (Tkinter + pygame + OpenCV)

Install:
    pip install pygame mutagen opencv-python pillow imageio-ffmpeg

(imageio-ffmpeg bundles ffmpeg, which is used to pull the audio track out of
videos so you get sound in sync. If you already have ffmpeg on PATH that works too.)

Shortcuts:
    Space  play / pause        Left / Right  seek -/+ (5s music, 10s video)
    M      mute                N / P         next / previous track
    F      fullscreen video    Esc           leave fullscreen
"""
import math
import os
import random
import shutil
import subprocess
import sys
import tempfile
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
    import cv2
    from PIL import Image, ImageTk
    HAS_CV2 = True
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
SIDEBAR = "#13131A"
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

AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".flac")
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


def lerp_color(c1, c2, t):
    a = [int(c1[i:i + 2], 16) for i in (1, 3, 5)]
    b = [int(c2[i:i + 2], 16) for i in (1, 3, 5)]
    return "#%02x%02x%02x" % tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def rounded_rect(c, x1, y1, x2, y2, r, **kw):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


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


class Visualizer(tk.Canvas):
    """Little animated equaliser shown while music plays."""

    def __init__(self, parent, width, height, bg, bars=28):
        super().__init__(parent, width=s(width), height=s(height), bg=bg,
                         highlightthickness=0, bd=0)
        self.n = bars
        self.levels = [0.08] * bars
        self.phase = [random.uniform(0, 6.28) for _ in range(bars)]
        self.speed = [random.uniform(2.0, 5.0) for _ in range(bars)]
        self.colors = [lerp_color(ACCENT, "#FF4D6D", i / max(bars - 1, 1)) for i in range(bars)]
        self.active = False
        self.t = 0.0
        self._anim()

    def _anim(self):
        self.t += 0.06
        w, h = self.winfo_width(), self.winfo_height()
        self.delete("all")
        if w > 10:
            step = w / self.n
            lw = max(2, step * 0.55)
            for i in range(self.n):
                if self.active:
                    wave = 0.5 + 0.5 * math.sin(self.t * self.speed[i] + self.phase[i])
                    target = 0.15 + 0.85 * wave * random.uniform(0.7, 1.0)
                else:
                    target = 0.06
                self.levels[i] += (target - self.levels[i]) * 0.35
                bh = max(lw, self.levels[i] * h)
                x = step * (i + 0.5)
                self.create_line(x, h / 2 - bh / 2, x, h / 2 + bh / 2, width=lw,
                                 fill=self.colors[i], capstyle="round")
        self.after(45, self._anim)


# ----------------------------------------------------------------------------
# Music
# ----------------------------------------------------------------------------
class MusicView(tk.Frame):
    REPEAT_OFF, REPEAT_ONE, REPEAT_ALL = "off", "one", "all"

    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.playlist = []  # dicts: path, title, duration
        self.current_index = -1
        self.is_playing = False
        self.is_paused = False
        self.track_length = 0.0
        self.start_offset = 0.0
        self.play_started_at = 0.0
        self.repeat_mode = self.REPEAT_OFF
        self.shuffle_on = False
        self._muted = False
        self._pre_mute = 0.7
        self.on_start = None  # hook so video can pause when music starts
        pygame.mixer.music.set_volume(0.7)
        self._build()
        self._tick()

    # ---- UI ---------------------------------------------------------------
    def _build(self):
        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=28, pady=(24, 10))
        left = tk.Frame(top, bg=BG)
        left.pack(side="left", fill="x", expand=True)
        self.title_var = tk.StringVar(value="Nothing playing")
        self.sub_var = tk.StringVar(value="Add some music to get started")
        tk.Label(left, textvariable=self.title_var, font=(FONT, 20, "bold"), fg=TEXT,
                 bg=BG, anchor="w").pack(fill="x")
        tk.Label(left, textvariable=self.sub_var, font=(FONT, 10), fg=DIM,
                 bg=BG, anchor="w").pack(fill="x", pady=(2, 0))
        self.viz = Visualizer(top, 220, 56, BG)
        self.viz.pack(side="right", padx=(16, 0))

        card = tk.Frame(self, bg=PANEL)
        card.pack(fill="both", expand=True, padx=28, pady=(0, 14))

        head = tk.Frame(card, bg=PANEL)
        head.pack(fill="x", padx=16, pady=(14, 8))
        self.queue_var = tk.StringVar(value="Queue")
        tk.Label(head, textvariable=self.queue_var, font=(FONT, 11, "bold"), fg=TEXT,
                 bg=PANEL).pack(side="left")
        for text, cmd, primary in (("Clear", self.clear_playlist, False),
                                   ("Remove", self.remove_selected, False),
                                   ("Add folder", self.add_folder, False),
                                   ("Add files", self.add_files, True)):
            PillButton(head, text, cmd, primary=primary, bg=PANEL).pack(side="right", padx=(8, 0))

        body = tk.Frame(card, bg=PANEL)
        body.pack(fill="both", expand=True, padx=(16, 8), pady=(0, 12))
        self.tree = ttk.Treeview(body, columns=("n", "title", "dur"), show="headings",
                                 style="RB.Treeview", selectmode="extended")
        self.tree.heading("n", text="#")
        self.tree.heading("title", text="TITLE", anchor="w")
        self.tree.heading("dur", text="TIME", anchor="e")
        self.tree.column("n", width=s(46), anchor="center", stretch=False)
        self.tree.column("title", anchor="w")
        self.tree.column("dur", width=s(80), anchor="e", stretch=False)
        self.tree.tag_configure("playing", foreground=ACCENT)
        sb = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview,
                           style="RB.Vertical.TScrollbar")
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y", padx=(6, 0))
        self.tree.bind("<Double-Button-1>", self._on_double_click)
        self.tree.bind("<space>", lambda e: "break")

        self.empty_label = tk.Label(
            body, text="Your queue is empty\nAdd files or a folder to begin",
            font=(FONT, 11), fg=DIM, bg=PANEL, justify="center")
        self.empty_label.place(relx=0.5, rely=0.5, anchor="center")

        # Player bar
        bar = tk.Frame(self, bg=BAR)
        bar.pack(fill="x", side="bottom")
        seek_row = tk.Frame(bar, bg=BAR)
        seek_row.pack(fill="x", padx=28, pady=(14, 0))
        self.elapsed_var = tk.StringVar(value="0:00")
        self.total_var = tk.StringVar(value="0:00")
        tk.Label(seek_row, textvariable=self.elapsed_var, fg=DIM, bg=BAR, width=6,
                 font=(FONT, 9)).pack(side="left")
        self.seek = Slider(seek_row, BAR, on_drag=self._seek_preview, on_commit=self._seek_commit)
        self.seek.pack(side="left", fill="x", expand=True, padx=4)
        tk.Label(seek_row, textvariable=self.total_var, fg=DIM, bg=BAR, width=6,
                 font=(FONT, 9)).pack(side="left")

        ctl = tk.Frame(bar, bg=BAR)
        ctl.pack(fill="x", padx=28, pady=(6, 14))
        ctl.columnconfigure(0, weight=1)
        ctl.columnconfigure(2, weight=1)

        IconButton(ctl, "stop", self.stop_music, size=36, color=DIM, bg=BAR).grid(
            row=0, column=0, sticky="w")

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

        vol = tk.Frame(ctl, bg=BAR)
        vol.grid(row=0, column=2, sticky="e")
        self.mute_btn = IconButton(vol, "volume", self.toggle_mute, size=34, bg=BAR)
        self.mute_btn.pack(side="left")
        self.volume = Slider(vol, BAR, width=110, on_drag=self._on_volume, value=0.7)
        self.volume.pack(side="left")

    # ---- Playlist ---------------------------------------------------------
    def add_files(self):
        files = filedialog.askopenfilenames(
            title="Add music files",
            filetypes=[("Audio files", "*.mp3 *.wav *.ogg *.flac"), ("All files", "*.*")])
        for f in files:
            self._add(f)
        self._refresh_tree()

    def add_folder(self):
        folder = filedialog.askdirectory(title="Add a folder of music")
        if not folder:
            return
        for root, _d, files in os.walk(folder):
            for name in sorted(files):
                if name.lower().endswith(AUDIO_EXTS):
                    self._add(os.path.join(root, name))
        self._refresh_tree()

    def _add(self, path):
        self.playlist.append({
            "path": path,
            "title": os.path.splitext(os.path.basename(path))[0],
            "duration": self._get_duration(path),
        })

    def _get_duration(self, path):
        if HAS_MUTAGEN:
            try:
                audio = MutagenFile(path)
                if audio and audio.info and audio.info.length:
                    return float(audio.info.length)
            except Exception:
                pass
        return 0.0

    def _refresh_tree(self):
        self.tree.delete(*self.tree.get_children())
        for i, t in enumerate(self.playlist):
            current = i == self.current_index
            dur = format_time(t["duration"]) if t["duration"] else "--:--"
            self.tree.insert("", "end", iid=str(i),
                             values=("▶" if current else i + 1, t["title"], dur),
                             tags=("playing",) if current else ())
        n = len(self.playlist)
        self.queue_var.set(f"Queue  ·  {n} track{'s' if n != 1 else ''}" if n else "Queue")
        if n:
            self.empty_label.place_forget()
        else:
            self.empty_label.place(relx=0.5, rely=0.5, anchor="center")

    def remove_selected(self):
        sel = sorted((int(i) for i in self.tree.selection()), reverse=True)
        if not sel:
            return
        cur_removed = self.current_index in sel
        shift = sum(1 for i in sel if i < self.current_index)
        for idx in sel:
            del self.playlist[idx]
        if cur_removed:
            self.stop_music()
            self.current_index = -1
            self._update_now_playing()
        else:
            self.current_index -= shift
        self._refresh_tree()

    def clear_playlist(self):
        self.stop_music()
        self.playlist.clear()
        self.current_index = -1
        self._update_now_playing()
        self._refresh_tree()

    def _on_double_click(self, e):
        row = self.tree.identify_row(e.y)
        if row:
            self.play_index(int(row))

    def _update_now_playing(self):
        if 0 <= self.current_index < len(self.playlist):
            self.title_var.set(self.playlist[self.current_index]["title"])
            self.sub_var.set(f"Track {self.current_index + 1} of {len(self.playlist)}")
        else:
            self.title_var.set("Nothing playing")
            self.sub_var.set("Add some music to get started")
            self.total_var.set("0:00")

    # ---- Playback ---------------------------------------------------------
    def _position(self):
        if self.is_playing and not self.is_paused:
            return self.start_offset + (time.perf_counter() - self.play_started_at)
        return self.start_offset

    def play_index(self, index):
        if not (0 <= index < len(self.playlist)):
            return
        if self.on_start:
            self.on_start()
        track = self.playlist[index]
        try:
            pygame.mixer.music.load(track["path"])
            pygame.mixer.music.set_volume(self.volume.value)
            pygame.mixer.music.play()
        except pygame.error as e:
            messagebox.showerror("Playback error", f"Could not play:\n{track['path']}\n\n{e}")
            return

        self.current_index = index
        self.track_length = track["duration"]
        self.start_offset = 0.0
        self.play_started_at = time.perf_counter()
        self.is_playing = True
        self.is_paused = False
        self.seek.enabled = self.track_length > 0
        self.seek.set(0)
        self.total_var.set(format_time(self.track_length) if self.track_length else "--:--")
        self.play_btn.set_icon("pause")
        self.viz.active = True
        self._update_now_playing()
        self._refresh_tree()
        self.tree.see(str(index))

    def toggle_play(self):
        if self.current_index == -1:
            if self.playlist:
                sel = self.tree.selection()
                self.play_index(int(sel[0]) if sel else 0)
            return
        if self.is_playing and not self.is_paused:
            self.start_offset = self._position()
            pygame.mixer.music.pause()
            self.is_paused = True
            self.play_btn.set_icon("play")
            self.viz.active = False
        elif self.is_paused:
            if self.on_start:
                self.on_start()
            pygame.mixer.music.unpause()
            self.is_paused = False
            self.play_started_at = time.perf_counter()
            self.play_btn.set_icon("pause")
            self.viz.active = True
        else:
            self.play_index(self.current_index)

    def stop_music(self):
        pygame.mixer.music.stop()
        self.is_playing = False
        self.is_paused = False
        self.start_offset = 0.0
        self.play_btn.set_icon("play")
        self.viz.active = False
        self.seek.set(0)
        self.elapsed_var.set("0:00")

    def pause_for_other(self):
        """Called when video starts: stop music so the mixer is free."""
        if self.is_playing:
            self.stop_music()

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
                    self.stop_music()
                    return
        self.play_index(nxt)

    def play_previous(self):
        if not self.playlist:
            return
        if self._position() > 3 and self.current_index != -1:
            self.play_index(self.current_index)  # restart current track first
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

    # ---- Volume / seeking -------------------------------------------------
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

    def _seek_preview(self, frac):
        self.elapsed_var.set(format_time(frac * self.track_length))

    def _seek_commit(self, frac):
        self._seek_to(frac * self.track_length)

    def _seek_to(self, target):
        if self.track_length <= 0 or not self.is_playing:
            return
        target = min(max(target, 0), max(self.track_length - 0.5, 0))
        try:
            pygame.mixer.music.play(start=target)
            pygame.mixer.music.set_volume(self.volume.value)
            if self.is_paused:
                pygame.mixer.music.pause()
        except pygame.error:
            return
        self.start_offset = target
        self.play_started_at = time.perf_counter()
        self.seek.set(target / self.track_length)
        self.elapsed_var.set(format_time(target))

    def seek_relative(self, delta):
        self._seek_to(self._position() + delta)

    # ---- Clock ------------------------------------------------------------
    def _tick(self):
        if self.is_playing and not self.is_paused:
            pos = self._position()
            if not self.seek.dragging:
                self.elapsed_var.set(format_time(pos))
                if self.track_length > 0:
                    self.seek.set(pos / self.track_length)
            # track finished?
            if time.perf_counter() - self.play_started_at > 0.6 and not pygame.mixer.music.get_busy():
                if self.repeat_mode == self.REPEAT_ONE:
                    self.play_index(self.current_index)
                else:
                    self.play_next(auto=True)
        self.after(200, self._tick)


# ----------------------------------------------------------------------------
# Video
# ----------------------------------------------------------------------------
class VideoView(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG)
        self.cap = None
        self.fps = 25.0
        self.frame_count = 0
        self.duration = 0.0
        self.playing = False
        self._paused_pos = 0.0
        self._clock_start = 0.0
        self._last_frame = -1
        self._job = None
        self._frame = None
        self._photo = None
        self._img_item = None
        self._last_ui = 0.0
        self._click_job = None
        self._audio_file = None
        self._audio_started = False
        self._audio_token = 0
        self._temp_files = []
        self._muted = False
        self._pre_mute = 0.7
        self.on_start = None
        self.on_fullscreen = None
        self._build()

    def _build(self):
        self.header = tk.Frame(self, bg=BG)
        self.header.pack(fill="x", padx=28, pady=(24, 10))
        self.title_var = tk.StringVar(value="Video")
        self.sub_var = tk.StringVar(
            value="Open a video to start watching" if HAS_CV2
            else "Video needs:  pip install opencv-python pillow")
        tk.Label(self.header, textvariable=self.title_var, font=(FONT, 20, "bold"), fg=TEXT,
                 bg=BG, anchor="w").pack(fill="x")
        tk.Label(self.header, textvariable=self.sub_var, font=(FONT, 10), fg=DIM, bg=BG,
                 anchor="w").pack(fill="x", pady=(2, 0))

        self.stage = tk.Frame(self, bg="black")
        self.stage.pack(fill="both", expand=True, padx=28, pady=(0, 14))
        self.canvas = tk.Canvas(self.stage, bg="black", highlightthickness=0, bd=0)
        self.canvas.pack(fill="both", expand=True)
        self.canvas.bind("<Configure>", self._on_resize)
        self.canvas.bind("<Button-1>", self._on_click)
        self.canvas.bind("<Double-Button-1>", self._on_double_click)

        bar = tk.Frame(self, bg=BAR)
        bar.pack(fill="x", side="bottom")
        seek_row = tk.Frame(bar, bg=BAR)
        seek_row.pack(fill="x", padx=28, pady=(14, 0))
        self.elapsed_var = tk.StringVar(value="0:00")
        self.total_var = tk.StringVar(value="0:00")
        tk.Label(seek_row, textvariable=self.elapsed_var, fg=DIM, bg=BAR, width=6,
                 font=(FONT, 9)).pack(side="left")
        self.seek = Slider(seek_row, BAR, on_drag=self._seek_preview, on_commit=self._seek_commit)
        self.seek.pack(side="left", fill="x", expand=True, padx=4)
        tk.Label(seek_row, textvariable=self.total_var, fg=DIM, bg=BAR, width=6,
                 font=(FONT, 9)).pack(side="left")

        ctl = tk.Frame(bar, bg=BAR)
        ctl.pack(fill="x", padx=28, pady=(6, 14))
        ctl.columnconfigure(0, weight=1)
        ctl.columnconfigure(2, weight=1)

        left = tk.Frame(ctl, bg=BAR)
        left.grid(row=0, column=0, sticky="w")
        PillButton(left, "Open video", self.open_video, primary=True, bg=BAR).pack(side="left")
        IconButton(left, "stop", self.stop_video, size=36, color=DIM, bg=BAR).pack(side="left", padx=(10, 0))

        mid = tk.Frame(ctl, bg=BAR)
        mid.grid(row=0, column=1)
        PillButton(mid, "−10s", lambda: self.seek_relative(-10), bg=BAR).pack(side="left", padx=8)
        self.play_btn = IconButton(mid, "play", self.toggle_play, size=56, color=ON_ACCENT,
                                   circle=ACCENT, circle_hover=ACCENT_HOVER, icon_frac=0.5, bg=BAR)
        self.play_btn.pack(side="left", padx=8)
        PillButton(mid, "+10s", lambda: self.seek_relative(10), bg=BAR).pack(side="left", padx=8)

        right = tk.Frame(ctl, bg=BAR)
        right.grid(row=0, column=2, sticky="e")
        IconButton(right, "expand", lambda: self.on_fullscreen and self.on_fullscreen(),
                   size=34, bg=BAR).pack(side="left", padx=(0, 6))
        self.mute_btn = IconButton(right, "volume", self.toggle_mute, size=34, bg=BAR)
        self.mute_btn.pack(side="left")
        self.volume = Slider(right, BAR, width=110, on_drag=self._on_volume, value=0.7)
        self.volume.pack(side="left")

        self._draw_placeholder()

    def set_chrome_visible(self, visible):
        """Hide the header in fullscreen."""
        if visible:
            self.header.pack(fill="x", padx=28, pady=(24, 10), before=self.stage)
        else:
            self.header.pack_forget()

    # ---- Canvas -----------------------------------------------------------
    def _draw_placeholder(self):
        self.canvas.delete("all")
        self._img_item = None
        w, h = self.canvas.winfo_width(), self.canvas.winfo_height()
        if w < 2:
            w, h = s(600), s(300)
        self.canvas.create_text(w // 2, h // 2 - s(12), text="No video loaded",
                                fill="#55555F", font=(FONT, 18, "bold"))
        self.canvas.create_text(w // 2, h // 2 + s(18), text="Click here or press “Open video”",
                                fill="#44444E", font=(FONT, 11))

    def _on_resize(self, _e):
        if self.cap is None:
            self._draw_placeholder()
        elif not self.playing:
            self._render()

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
        if self.on_fullscreen:
            self.on_fullscreen()

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

    # ---- Open / close -----------------------------------------------------
    def open_video(self, path=None):
        if not HAS_CV2:
            messagebox.showwarning(
                "Missing dependency",
                "Video playback requires opencv-python and pillow.\n\n"
                "Install with:\npip install opencv-python pillow")
            return
        path = path or filedialog.askopenfilename(
            title="Open a video",
            filetypes=[("Video files", "*.mp4 *.avi *.mov *.mkv *.webm *.m4v *.wmv"),
                       ("All files", "*.*")])
        if not path:
            return
        self._close()
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            messagebox.showerror("Playback error", f"Could not open:\n{path}")
            return
        self.cap = cap
        fps = cap.get(cv2.CAP_PROP_FPS)
        self.fps = fps if fps and fps == fps and 1 <= fps <= 120 else 25.0
        self.frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        self.duration = self.frame_count / self.fps if self.frame_count > 0 else 0.0
        self.seek.enabled = self.duration > 0
        self.total_var.set(format_time(self.duration) if self.duration else "--:--")
        self.title_var.set(os.path.splitext(os.path.basename(path))[0])
        self._paused_pos = 0.0
        self._last_frame = -1
        self._img_item = None
        self.canvas.delete("all")
        self._show_frame(0)
        self._prepare_audio(path)
        self.toggle_play()  # auto-play on open

    def _close(self):
        self.playing = False
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        self._stop_audio()
        self._audio_token += 1
        self._audio_file = None
        if self.cap is not None:
            self.cap.release()
            self.cap = None
        self._frame = None
        self.play_btn.set_icon("play")
        self.seek.set(0)
        self.elapsed_var.set("0:00")
        self.cleanup_temp()

    def cleanup_temp(self):
        for f in self._temp_files:
            try:
                os.remove(f)
            except OSError:
                pass
        self._temp_files = []

    # ---- Audio (extracted with ffmpeg, played via pygame) -----------------
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

    def _prepare_audio(self, path):
        self._audio_token += 1
        token = self._audio_token
        self._audio_file = None
        self._audio_started = False
        ffmpeg = self._find_ffmpeg()
        if not ffmpeg:
            self.sub_var.set("Playing without sound - install ffmpeg:  pip install imageio-ffmpeg")
            return
        self.sub_var.set("Preparing audio…")
        result = {"done": False, "file": None}

        def work():
            flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            for ext, codec in ((".mp3", ["-c:a", "libmp3lame", "-q:a", "4"]),
                               (".wav", ["-c:a", "pcm_s16le"])):
                tmp = tempfile.NamedTemporaryFile(suffix=ext, delete=False)
                tmp.close()
                cmd = [ffmpeg, "-y", "-v", "error", "-i", path, "-vn", "-ac", "2",
                       "-ar", "44100", *codec, tmp.name]
                try:
                    r = subprocess.run(cmd, capture_output=True, creationflags=flags)
                    if r.returncode == 0 and os.path.getsize(tmp.name) > 1000:
                        result["file"] = tmp.name
                        break
                except Exception:
                    pass
                try:
                    os.remove(tmp.name)
                except OSError:
                    pass
            result["done"] = True

        threading.Thread(target=work, daemon=True).start()
        self._poll_audio(token, result)

    def _poll_audio(self, token, result):
        if token != self._audio_token:
            if result["file"]:
                try:
                    os.remove(result["file"])
                except OSError:
                    pass
            return
        if not result["done"]:
            self.after(250, self._poll_audio, token, result)
            return
        if result["file"]:
            self._audio_file = result["file"]
            self._temp_files.append(result["file"])
            self.sub_var.set("Ready")
        else:
            self.sub_var.set("No audio track found (playing silent)")

    def _start_audio(self, pos):
        self._audio_started = True  # don't retry in a loop even if it fails
        try:
            pygame.mixer.music.load(self._audio_file)
            pygame.mixer.music.set_volume(self.volume.value)
            pygame.mixer.music.play(start=pos)
        except pygame.error:
            self._audio_file = None

    def _stop_audio(self):
        self._audio_started = False
        try:
            pygame.mixer.music.stop()
        except pygame.error:
            pass

    def pause_for_other(self):
        if self.playing:
            self._pause()

    # ---- Transport --------------------------------------------------------
    def _pos(self):
        if self.playing:
            return time.perf_counter() - self._clock_start
        return self._paused_pos

    def toggle_play(self):
        if self.cap is None:
            self.open_video()
            return
        if self.playing:
            self._pause()
        else:
            self._play()

    def _play(self):
        if self.cap is None:
            return
        if self.on_start:
            self.on_start()
        if self.duration and self._paused_pos >= self.duration - 0.2:
            self._paused_pos = 0.0
            self._show_frame(0)
        self._clock_start = time.perf_counter() - self._paused_pos
        self.playing = True
        self._audio_started = False
        self.play_btn.set_icon("pause")
        if self._job is None:
            self._loop()

    def _pause(self):
        if self.playing:
            self._paused_pos = self._pos()
        self.playing = False
        if self._job:
            self.after_cancel(self._job)
            self._job = None
        self._stop_audio()
        self.play_btn.set_icon("play")

    def stop_video(self):
        if self.cap is None:
            return
        self._pause()
        self._paused_pos = 0.0
        self._show_frame(0)
        self.seek.set(0)
        self.elapsed_var.set("0:00")

    def _ended(self):
        self._pause()
        self._paused_pos = 0.0
        self._show_frame(0)
        self.seek.set(0)
        self.elapsed_var.set("0:00")

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
        """Main-thread playback loop, clock-driven so video never drifts or piles up."""
        self._job = None
        if not self.playing or self.cap is None:
            return
        pos = time.perf_counter() - self._clock_start
        if self.duration and pos >= self.duration:
            self._ended()
            return
        if self._audio_file and not self._audio_started:
            self._start_audio(pos)

        target = int(pos * self.fps)
        if target > self._last_frame:
            gap = target - self._last_frame - 1
            if gap >= 24:  # way behind: jump instead of decoding everything
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, target)
            else:
                for _ in range(gap):  # slightly behind: drop frames to catch up
                    self.cap.grab()
            ok, frame = self.cap.read()
            if not ok:
                self._ended()
                return
            self._last_frame = target
            self._render(frame)

        now = time.perf_counter()
        if now - self._last_ui > 0.2 and not self.seek.dragging:
            self._last_ui = now
            self.elapsed_var.set(format_time(pos))
            if self.duration:
                self.seek.set(pos / self.duration)

        next_t = (self._last_frame + 1) / self.fps
        wait_ms = int((next_t - (time.perf_counter() - self._clock_start)) * 1000)
        self._job = self.after(min(max(wait_ms, 1), 15), self._loop)

    # ---- Seek / volume ----------------------------------------------------
    def _seek_preview(self, frac):
        self.elapsed_var.set(format_time(frac * self.duration))

    def _seek_commit(self, frac):
        self._seek_to(frac * self.duration)

    def _seek_to(self, t):
        if self.cap is None or self.duration <= 0:
            return
        t = min(max(t, 0), self.duration - 0.1)
        self._paused_pos = t
        self._show_frame(int(t * self.fps))
        if self.playing:
            self._clock_start = time.perf_counter() - t
            self._stop_audio()  # loop restarts it at the new position
        self.seek.set(t / self.duration)
        self.elapsed_var.set(format_time(t))

    def seek_relative(self, delta):
        if self.cap is not None:
            self._seek_to(self._pos() + delta)

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


# ----------------------------------------------------------------------------
# App shell
# ----------------------------------------------------------------------------
class NavItem(tk.Frame):
    def __init__(self, parent, text, command):
        super().__init__(parent, bg=SIDEBAR, cursor="hand2")
        self.command = command
        self.bar = tk.Frame(self, bg=SIDEBAR, width=3)
        self.bar.pack(side="left", fill="y")
        self.label = tk.Label(self, text=text, font=(FONT, 11, "bold"), fg=DIM, bg=SIDEBAR,
                              anchor="w", padx=18, pady=12, cursor="hand2")
        self.label.pack(side="left", fill="x", expand=True)
        self.active = False
        for w in (self, self.label):
            w.bind("<Button-1>", lambda e: self.command())
            w.bind("<Enter>", lambda e: self._paint(True))
            w.bind("<Leave>", lambda e: self._paint(False))

    def set_active(self, v):
        self.active = v
        self._paint(False)

    def _paint(self, hover):
        bg = CARD if (self.active or hover) else SIDEBAR
        self.configure(bg=bg)
        self.label.configure(bg=bg, fg=ACCENT if self.active else (TEXT if hover else DIM))
        self.bar.configure(bg=ACCENT if self.active else bg)


class RealBeatsApp:
    def __init__(self):
        global UI
        pygame.mixer.init()

        self.root = tk.Tk()
        try:
            UI = max(1.0, self.root.winfo_fpixels("1i") / 96.0)
        except tk.TclError:
            UI = 1.0
        self.root.title("RealBeats")
        self.root.geometry(f"{s(1040)}x{s(680)}")
        self.root.minsize(s(860), s(580))
        self.root.configure(bg=BG)
        self._fullscreen = False

        self._style()

        self.sidebar = tk.Frame(self.root, bg=SIDEBAR, width=s(190))
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)
        logo = tk.Frame(self.sidebar, bg=SIDEBAR)
        logo.pack(fill="x", padx=18, pady=(26, 28))
        tk.Label(logo, text="Real", font=(FONT, 16, "bold"), fg=TEXT, bg=SIDEBAR).pack(side="left")
        tk.Label(logo, text="Beats", font=(FONT, 16, "bold"), fg=ACCENT, bg=SIDEBAR).pack(side="left")

        self.content = tk.Frame(self.root, bg=BG)
        self.content.pack(side="left", fill="both", expand=True)

        self.music = MusicView(self.content)
        self.video = VideoView(self.content)
        self.music.on_start = self.video.pause_for_other
        self.video.on_start = self.music.pause_for_other
        self.video.on_fullscreen = self.toggle_fullscreen

        self.nav = {
            "music": NavItem(self.sidebar, "Music", lambda: self.show("music")),
            "video": NavItem(self.sidebar, "Video", lambda: self.show("video")),
        }
        for item in self.nav.values():
            item.pack(fill="x", pady=1)

        tk.Label(self.sidebar, text="Space  play / pause\n← →  seek\nM  mute    F  fullscreen",
                 font=(FONT, 8), fg="#5A5A66", bg=SIDEBAR, justify="left").pack(
            side="bottom", anchor="w", padx=18, pady=18)

        self.views = {"music": self.music, "video": self.video}
        self.active = "music"
        self.show("music")

        r = self.root
        r.bind("<space>", lambda e: self._view().toggle_play())
        r.bind("<Left>", lambda e: self._view().seek_relative(-self._step()))
        r.bind("<Right>", lambda e: self._view().seek_relative(self._step()))
        r.bind("<m>", lambda e: self._view().toggle_mute())
        r.bind("<n>", lambda e: self.music.play_next() if self.active == "music" else None)
        r.bind("<p>", lambda e: self.music.play_previous() if self.active == "music" else None)
        r.bind("<f>", lambda e: self.toggle_fullscreen() if self.active == "video" else None)
        r.bind("<Escape>", lambda e: self.toggle_fullscreen(False))
        r.protocol("WM_DELETE_WINDOW", self._on_close)

        self._dark_title_bar()

    def _view(self):
        return self.views[self.active]

    def _step(self):
        return 5 if self.active == "music" else 10

    def show(self, name):
        self.active = name
        for key, view in self.views.items():
            view.pack_forget()
            self.nav[key].set_active(key == name)
        self.views[name].pack(fill="both", expand=True)

    def toggle_fullscreen(self, force=None):
        want = (not self._fullscreen) if force is None else force
        if want == self._fullscreen or (want and self.active != "video"):
            return
        self._fullscreen = want
        self.root.attributes("-fullscreen", want)
        if want:
            self.sidebar.pack_forget()
        else:
            self.sidebar.pack(side="left", fill="y", before=self.content)
        self.video.set_chrome_visible(not want)

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
        st.configure("RB.Treeview.Heading", background=PANEL, foreground=DIM, relief="flat",
                     font=(FONT, 8, "bold"), borderwidth=0, padding=(6, 6))
        st.map("RB.Treeview.Heading", background=[("active", PANEL)])
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
            self.video._close()
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