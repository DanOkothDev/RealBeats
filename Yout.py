import os
import random
import tempfile
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import pygame

# ----------------------------------------------------------------------------
# Optional dependencies — the app degrades gracefully if they're missing
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
    from moviepy.editor import VideoFileClip
    HAS_MOVIEPY = True
except ImportError:
    HAS_MOVIEPY = False


BG_DARK = "#1B1B1F"
BG_PANEL = "#232328"
BG_CONTROLS = "#17171B"
ACCENT = "#FF8800"
ACCENT_HOVER = "#FFA733"
TEXT_MAIN = "#F2F2F2"
TEXT_DIM = "#9A9AA2"
TROUGH = "#3A3A40"

AUDIO_EXTS = (".mp3", ".wav", ".ogg", ".flac")
VIDEO_EXTS = (".mp4", ".avi", ".mov", ".mkv", ".webm")


def format_time(seconds):
    if seconds is None or seconds < 0:
        seconds = 0
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:d}:{m:02d}:{s:02d}"
    return f"{m:d}:{s:02d}"


def make_icon_button(parent, text, command, size=16, fg=TEXT_MAIN):
    btn = tk.Button(
        parent,
        text=text,
        command=command,
        font=("Segoe UI Symbol", size),
        bg=BG_CONTROLS,
        fg=fg,
        activebackground=BG_CONTROLS,
        activeforeground=ACCENT,
        bd=0,
        highlightthickness=0,
        cursor="hand2",
        padx=8,
    )

    def on_enter(_):
        btn.configure(fg=ACCENT)

    def on_leave(_):
        btn.configure(fg=fg)

    btn.bind("<Enter>", on_enter)
    btn.bind("<Leave>", on_leave)
    return btn


class MusicPlayer(tk.Frame):
    REPEAT_OFF, REPEAT_ONE, REPEAT_ALL = "off", "one", "all"

    def __init__(self, parent):
        super().__init__(parent, bg=BG_DARK)

        self.playlist = []          # list of filepaths
        self.current_index = -1
        self.is_playing = False
        self.is_paused = False
        self.track_length = 0.0
        self.start_offset = 0.0     # seconds already played before current play() call
        self.play_started_at = None
        self.user_dragging_seek = False
        self.repeat_mode = self.REPEAT_OFF
        self.shuffle_on = False

        self._build_ui()
        self._tick()

  
    def _build_ui(self):
        
        header = tk.Frame(self, bg=BG_DARK)
        header.pack(fill="x", padx=20, pady=(18, 6))

        tk.Label(
            header, text="🎵  RealBeats", font=("Helvetica", 20, "bold"),
            fg=ACCENT, bg=BG_DARK,
        ).pack(anchor="w")

        self.now_playing_var = tk.StringVar(value="No track loaded")
        tk.Label(
            header, textvariable=self.now_playing_var, font=("Helvetica", 12),
            fg=TEXT_MAIN, bg=BG_DARK,
        ).pack(anchor="w", pady=(4, 0))

        
        body = tk.Frame(self, bg=BG_DARK)
        body.pack(fill="both", expand=True, padx=20, pady=6)

        # Playlist panel
        list_frame = tk.Frame(body, bg=BG_PANEL)
        list_frame.pack(side="left", fill="both", expand=True)

        list_header = tk.Frame(list_frame, bg=BG_PANEL)
        list_header.pack(fill="x", padx=10, pady=(10, 4))
        tk.Label(
            list_header, text="Playlist", font=("Helvetica", 11, "bold"),
            fg=TEXT_MAIN, bg=BG_PANEL,
        ).pack(side="left")

        list_body = tk.Frame(list_frame, bg=BG_PANEL)
        list_body.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        scrollbar = tk.Scrollbar(list_body)
        scrollbar.pack(side="right", fill="y")

        self.listbox = tk.Listbox(
            list_body,
            bg=BG_CONTROLS, fg=TEXT_MAIN, selectbackground=ACCENT,
            selectforeground="black", bd=0, highlightthickness=0,
            activestyle="none", font=("Helvetica", 10),
            yscrollcommand=scrollbar.set,
        )
        self.listbox.pack(side="left", fill="both", expand=True)
        scrollbar.config(command=self.listbox.yview)
        self.listbox.bind("<Double-Button-1>", self._on_double_click)

        # Playlist management buttons
        pl_btns = tk.Frame(list_frame, bg=BG_PANEL)
        pl_btns.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(
            pl_btns, text="＋ Files", command=self.add_files, bg=BG_CONTROLS,
            fg=TEXT_MAIN, bd=0, activebackground=ACCENT, activeforeground="black",
            cursor="hand2",
        ).pack(side="left", padx=(0, 6))
        tk.Button(
            pl_btns, text="＋ Folder", command=self.add_folder, bg=BG_CONTROLS,
            fg=TEXT_MAIN, bd=0, activebackground=ACCENT, activeforeground="black",
            cursor="hand2",
        ).pack(side="left", padx=(0, 6))
        tk.Button(
            pl_btns, text="－ Remove", command=self.remove_selected, bg=BG_CONTROLS,
            fg=TEXT_MAIN, bd=0, activebackground=ACCENT, activeforeground="black",
            cursor="hand2",
        ).pack(side="left", padx=(0, 6))
        tk.Button(
            pl_btns, text="Clear", command=self.clear_playlist, bg=BG_CONTROLS,
            fg=TEXT_MAIN, bd=0, activebackground=ACCENT, activeforeground="black",
            cursor="hand2",
        ).pack(side="left")

       
        seek_frame = tk.Frame(self, bg=BG_DARK)
        seek_frame.pack(fill="x", padx=20, pady=(6, 0))

        self.elapsed_var = tk.StringVar(value="0:00")
        self.total_var = tk.StringVar(value="0:00")

        tk.Label(seek_frame, textvariable=self.elapsed_var, fg=TEXT_DIM,
                 bg=BG_DARK, width=6, font=("Helvetica", 9)).pack(side="left")

        self.seek_var = tk.DoubleVar(value=0)
        self.seek_scale = tk.Scale(
            seek_frame, from_=0, to=1000, orient="horizontal", variable=self.seek_var,
            showvalue=False, bg=BG_DARK, fg=ACCENT, troughcolor=TROUGH,
            highlightthickness=0, bd=0, sliderrelief="flat",
            activebackground=ACCENT,
        )
        self.seek_scale.pack(side="left", fill="x", expand=True, padx=8)
        self.seek_scale.bind("<ButtonPress-1>", lambda e: self._set_dragging(True))
        self.seek_scale.bind("<ButtonRelease-1>", self._on_seek_release)

        tk.Label(seek_frame, textvariable=self.total_var, fg=TEXT_DIM,
                 bg=BG_DARK, width=6, font=("Helvetica", 9)).pack(side="left")

        
        controls = tk.Frame(self, bg=BG_CONTROLS)
        controls.pack(fill="x", padx=0, pady=(10, 0))

        inner = tk.Frame(controls, bg=BG_CONTROLS)
        inner.pack(pady=12)

        self.shuffle_btn = make_icon_button(inner, "🔀", self.toggle_shuffle, fg=TEXT_DIM)
        self.shuffle_btn.grid(row=0, column=0, padx=8)
        make_icon_button(inner, "⏮", self.play_previous).grid(row=0, column=1, padx=8)
        self.play_pause_btn = make_icon_button(inner, "▶", self.toggle_play, size=22, fg=ACCENT)
        self.play_pause_btn.grid(row=0, column=2, padx=8)
        make_icon_button(inner, "⏹", self.stop_music).grid(row=0, column=3, padx=8)
        make_icon_button(inner, "⏭", self.play_next).grid(row=0, column=4, padx=8)
        self.repeat_btn = make_icon_button(inner, "🔁", self.cycle_repeat, fg=TEXT_DIM)
        self.repeat_btn.grid(row=0, column=5, padx=8)

        # Volume
        vol_frame = tk.Frame(controls, bg=BG_CONTROLS)
        vol_frame.pack(pady=(0, 12))
        self.mute_btn = make_icon_button(vol_frame, "🔊", self.toggle_mute, size=14)
        self.mute_btn.pack(side="left")
        self.volume_var = tk.DoubleVar(value=70)
        self.volume_scale = tk.Scale(
            vol_frame, from_=0, to=100, orient="horizontal", variable=self.volume_var,
            showvalue=False, length=140, bg=BG_CONTROLS, fg=ACCENT, troughcolor=TROUGH,
            highlightthickness=0, bd=0, command=self._on_volume_change,
        )
        self.volume_scale.pack(side="left", padx=6)
        pygame.mixer.music.set_volume(self.volume_var.get() / 100)
        self._muted = False
        self._pre_mute_volume = 70

    
    def add_files(self):
        files = filedialog.askopenfilenames(
            title="Add music files",
            filetypes=[("Audio files", "*.mp3 *.wav *.ogg *.flac"), ("All files", "*.*")],
        )
        for f in files:
            self._add_to_playlist(f)

    def add_folder(self):
        folder = filedialog.askdirectory(title="Add a folder of music")
        if not folder:
            return
        for root, _dirs, files in os.walk(folder):
            for name in sorted(files):
                if name.lower().endswith(AUDIO_EXTS):
                    self._add_to_playlist(os.path.join(root, name))

    def _add_to_playlist(self, path):
        self.playlist.append(path)
        self.listbox.insert("end", os.path.basename(path))

    def remove_selected(self):
        sel = list(self.listbox.curselection())
        for idx in reversed(sel):
            self.listbox.delete(idx)
            del self.playlist[idx]
            if idx == self.current_index:
                self.stop_music()
                self.current_index = -1
            elif idx < self.current_index:
                self.current_index -= 1

    def clear_playlist(self):
        self.stop_music()
        self.playlist.clear()
        self.listbox.delete(0, "end")
        self.current_index = -1
        self.now_playing_var.set("No track loaded")

    def _on_double_click(self, _event):
        sel = self.listbox.curselection()
        if sel:
            self.play_index(sel[0])

    
    def play_index(self, index):
        if not (0 <= index < len(self.playlist)):
            return
        path = self.playlist[index]
        try:
            pygame.mixer.music.load(path)
        except pygame.error as e:
            messagebox.showerror("Playback error", f"Could not load:\n{path}\n\n{e}")
            return

        self.current_index = index
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(index)
        self.listbox.see(index)

        self.track_length = self._get_duration(path)
        self.total_var.set(format_time(self.track_length))
        self.now_playing_var.set(f"♪  {os.path.basename(path)}")

        pygame.mixer.music.play()
        self.start_offset = 0.0
        self.play_started_at = time.time()
        self.is_playing = True
        self.is_paused = False
        self.play_pause_btn.configure(text="⏸")

    def _get_duration(self, path):
        if HAS_MUTAGEN:
            try:
                audio = MutagenFile(path)
                if audio and audio.info and audio.info.length:
                    return float(audio.info.length)
            except Exception:
                pass
        return 0.0

    def toggle_play(self):
        if self.current_index == -1:
            if self.playlist:
                self.play_index(0)
            return
        if self.is_playing and not self.is_paused:
            pygame.mixer.music.pause()
            self.is_paused = True
            self.play_pause_btn.configure(text="▶")
        elif self.is_paused:
            pygame.mixer.music.unpause()
            self.is_paused = False
            self.play_started_at = time.time()
            self.play_pause_btn.configure(text="⏸")
        else:
            self.play_index(self.current_index)

    def stop_music(self):
        pygame.mixer.music.stop()
        self.is_playing = False
        self.is_paused = False
        self.play_pause_btn.configure(text="▶")
        self.seek_var.set(0)
        self.elapsed_var.set("0:00")

    def play_next(self, auto=False):
        if not self.playlist:
            return
        if self.shuffle_on:
            next_index = random.randrange(len(self.playlist))
        else:
            next_index = self.current_index + 1
            if next_index >= len(self.playlist):
                if self.repeat_mode == self.REPEAT_ALL:
                    next_index = 0
                else:
                    self.stop_music()
                    return
        self.play_index(next_index)

    def play_previous(self):
        if not self.playlist:
            return
        prev_index = self.current_index - 1
        if prev_index < 0:
            prev_index = len(self.playlist) - 1
        self.play_index(prev_index)

    def toggle_shuffle(self):
        self.shuffle_on = not self.shuffle_on
        self.shuffle_btn.configure(fg=ACCENT if self.shuffle_on else TEXT_DIM)

    def cycle_repeat(self):
        order = [self.REPEAT_OFF, self.REPEAT_ONE, self.REPEAT_ALL]
        self.repeat_mode = order[(order.index(self.repeat_mode) + 1) % len(order)]
        symbol = {self.REPEAT_OFF: "🔁", self.REPEAT_ONE: "🔂", self.REPEAT_ALL: "🔁"}
        color = TEXT_DIM if self.repeat_mode == self.REPEAT_OFF else ACCENT
        self.repeat_btn.configure(text=symbol[self.repeat_mode], fg=color)

    def toggle_mute(self):
        if self._muted:
            self.volume_var.set(self._pre_mute_volume)
            self._muted = False
            self.mute_btn.configure(text="🔊")
        else:
            self._pre_mute_volume = self.volume_var.get()
            self.volume_var.set(0)
            self._muted = True
            self.mute_btn.configure(text="🔇")
        self._on_volume_change(None)

    def _on_volume_change(self, _value):
        vol = self.volume_var.get() / 100
        pygame.mixer.music.set_volume(vol)
        self.mute_btn.configure(text="🔇" if vol == 0 else "🔊")

    
    def _set_dragging(self, dragging):
        self.user_dragging_seek = dragging

    def _on_seek_release(self, _event):
        if self.track_length <= 0 or self.current_index == -1:
            self.user_dragging_seek = False
            return
        fraction = self.seek_var.get() / 1000
        target = fraction * self.track_length
        try:
            pygame.mixer.music.play(start=target)
            self.start_offset = target
            self.play_started_at = time.time()
            self.is_playing = True
            self.is_paused = False
            self.play_pause_btn.configure(text="⏸")
        except pygame.error:
            pass
        self.user_dragging_seek = False

    
    def _tick(self):
        if self.is_playing and not self.is_paused and not self.user_dragging_seek:
            elapsed = self.start_offset + (time.time() - self.play_started_at)
            if self.track_length > 0:
                if elapsed >= self.track_length and not pygame.mixer.music.get_busy():
                    # Track ended
                    if self.repeat_mode == self.REPEAT_ONE:
                        self.play_index(self.current_index)
                    else:
                        self.play_next(auto=True)
                else:
                    self.seek_var.set(min(elapsed / self.track_length, 1) * 1000)
                    self.elapsed_var.set(format_time(elapsed))
            else:
                # Unknown duration — still show elapsed time, detect end via get_busy
                self.elapsed_var.set(format_time(elapsed))
                if not pygame.mixer.music.get_busy():
                    if self.repeat_mode == self.REPEAT_ONE:
                        self.play_index(self.current_index)
                    else:
                        self.play_next(auto=True)
        self.after(250, self._tick)



class VideoPlayer(tk.Frame):
    def __init__(self, parent):
        super().__init__(parent, bg=BG_DARK)
        self.cap = None
        self.video_path = None
        self.fps = 25
        self.frame_count = 0
        self.duration = 0.0
        self.is_playing = False
        self.current_frame_index = 0
        self.user_dragging_seek = False
        self._play_thread = None
        self._stop_thread = False
        self._photo_image = None

        # Optional synced audio (via moviepy -> temp wav -> pygame Sound)
        self._audio_channel = None
        self._audio_sound = None
        self._audio_offset = 0.0
        self._temp_audio_file = None

        self._build_ui()

    def _build_ui(self):
        header = tk.Frame(self, bg=BG_DARK)
        header.pack(fill="x", padx=20, pady=(18, 6))
        tk.Label(
            header, text="🎬  RealBeats Video", font=("Helvetica", 20, "bold"),
            fg=ACCENT, bg=BG_DARK,
        ).pack(anchor="w")

        self.status_var = tk.StringVar(
            value="No video loaded" if HAS_CV2 else
            "Video playback needs: pip install opencv-python pillow"
        )
        tk.Label(
            header, textvariable=self.status_var, font=("Helvetica", 11),
            fg=TEXT_MAIN, bg=BG_DARK,
        ).pack(anchor="w", pady=(4, 0))

        # Video canvas
        canvas_frame = tk.Frame(self, bg="black")
        canvas_frame.pack(fill="both", expand=True, padx=20, pady=6)
        self.canvas = tk.Canvas(canvas_frame, bg="black", highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)

        # Seek bar
        seek_frame = tk.Frame(self, bg=BG_DARK)
        seek_frame.pack(fill="x", padx=20, pady=(6, 0))
        self.elapsed_var = tk.StringVar(value="0:00")
        self.total_var = tk.StringVar(value="0:00")
        tk.Label(seek_frame, textvariable=self.elapsed_var, fg=TEXT_DIM,
                 bg=BG_DARK, width=6, font=("Helvetica", 9)).pack(side="left")
        self.seek_var = tk.DoubleVar(value=0)
        self.seek_scale = tk.Scale(
            seek_frame, from_=0, to=1000, orient="horizontal", variable=self.seek_var,
            showvalue=False, bg=BG_DARK, fg=ACCENT, troughcolor=TROUGH,
            highlightthickness=0, bd=0, activebackground=ACCENT,
        )
        self.seek_scale.pack(side="left", fill="x", expand=True, padx=8)
        self.seek_scale.bind("<ButtonPress-1>", lambda e: setattr(self, "user_dragging_seek", True))
        self.seek_scale.bind("<ButtonRelease-1>", self._on_seek_release)
        tk.Label(seek_frame, textvariable=self.total_var, fg=TEXT_DIM,
                 bg=BG_DARK, width=6, font=("Helvetica", 9)).pack(side="left")

        # Controls
        controls = tk.Frame(self, bg=BG_CONTROLS)
        controls.pack(fill="x", pady=(10, 0))
        inner = tk.Frame(controls, bg=BG_CONTROLS)
        inner.pack(pady=12)

        make_icon_button(inner, "📂", self.open_video).grid(row=0, column=0, padx=8)
        self.play_pause_btn = make_icon_button(inner, "▶", self.toggle_play, size=22, fg=ACCENT)
        self.play_pause_btn.grid(row=0, column=1, padx=8)
        make_icon_button(inner, "⏹", self.stop_video).grid(row=0, column=2, padx=8)

        vol_frame = tk.Frame(controls, bg=BG_CONTROLS)
        vol_frame.pack(pady=(0, 12))
        tk.Label(vol_frame, text="🔊", bg=BG_CONTROLS, fg=TEXT_MAIN).pack(side="left")
        self.volume_var = tk.DoubleVar(value=70)
        tk.Scale(
            vol_frame, from_=0, to=100, orient="horizontal", variable=self.volume_var,
            showvalue=False, length=140, bg=BG_CONTROLS, fg=ACCENT, troughcolor=TROUGH,
            highlightthickness=0, bd=0, command=self._on_volume_change,
        ).pack(side="left", padx=6)

        if not HAS_MOVIEPY:
            tk.Label(
                controls,
                text="(Optional) install 'moviepy' + ffmpeg for synced audio",
                bg=BG_CONTROLS, fg=TEXT_DIM, font=("Helvetica", 8),
            ).pack(pady=(0, 8))

  
    def open_video(self):
        if not HAS_CV2:
            messagebox.showwarning(
                "Missing dependency",
                "Video playback requires opencv-python and pillow.\n\n"
                "Install with:\npip install opencv-python pillow",
            )
            return
        path = filedialog.askopenfilename(
            title="Open a video",
            filetypes=[("Video files", "*.mp4 *.avi *.mov *.mkv *.webm"), ("All files", "*.*")],
        )
        if not path:
            return
        self.stop_video()
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened():
            messagebox.showerror("Playback error", f"Could not open:\n{path}")
            self.cap = None
            return

        self.video_path = path
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 25
        self.frame_count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.duration = self.frame_count / self.fps if self.fps else 0
        self.total_var.set(format_time(self.duration))
        self.status_var.set(f"▶  {os.path.basename(path)}")
        self.current_frame_index = 0

        self._prepare_audio(path)
        self._show_frame_at(0)

    def _prepare_audio(self, path):
        self._audio_sound = None
        if not HAS_MOVIEPY:
            return

        def extract():
            try:
                clip = VideoFileClip(path)
                if clip.audio is None:
                    return
                tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                tmp.close()
                clip.audio.write_audiofile(tmp.name, logger=None)
                self._temp_audio_file = tmp.name
                self._audio_sound = pygame.mixer.Sound(tmp.name)
                clip.close()
            except Exception:
                self._audio_sound = None

        threading.Thread(target=extract, daemon=True).start()

   
    def toggle_play(self):
        if self.cap is None:
            self.open_video()
            return
        if self.is_playing:
            self._pause()
        else:
            self._play()

    def _play(self):
        if self.cap is None:
            return
        self.is_playing = True
        self.play_pause_btn.configure(text="⏸")
        self._stop_thread = False

        if self._audio_sound is not None:
            start_sec = self.current_frame_index / self.fps if self.fps else 0
            try:
                self._audio_channel = self._audio_sound.play()
                self._audio_channel.set_volume(self.volume_var.get() / 100)
            except Exception:
                self._audio_channel = None

        self._play_thread = threading.Thread(target=self._playback_loop, daemon=True)
        self._play_thread.start()

    def _pause(self):
        self.is_playing = False
        self._stop_thread = True
        self.play_pause_btn.configure(text="▶")
        if self._audio_channel is not None:
            self._audio_channel.stop()
            self._audio_channel = None

    def stop_video(self):
        self.is_playing = False
        self._stop_thread = True
        if self._audio_channel is not None:
            self._audio_channel.stop()
            self._audio_channel = None
        if self.cap is not None:
            self.current_frame_index = 0
            self._show_frame_at(0)
        self.play_pause_btn.configure(text="▶")
        self.seek_var.set(0)
        self.elapsed_var.set("0:00")

    def _playback_loop(self):
        delay = 1.0 / self.fps if self.fps else 0.04
        while not self._stop_thread and self.cap is not None:
            ok, frame = self.cap.read()
            if not ok:
                self.after(0, self.stop_video)
                break
            self.current_frame_index += 1
            self.after(0, self._render_frame, frame)
            if not self.user_dragging_seek and self.duration > 0:
                elapsed = self.current_frame_index / self.fps
                self.after(0, self._update_seek_ui, elapsed)
            time.sleep(delay)

    def _update_seek_ui(self, elapsed):
        self.seek_var.set(min(elapsed / self.duration, 1) * 1000)
        self.elapsed_var.set(format_time(elapsed))

    def _show_frame_at(self, frame_index):
        if self.cap is None:
            return
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_index)
        ok, frame = self.cap.read()
        if ok:
            self._render_frame(frame)

    def _render_frame(self, frame):
        frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        img = Image.fromarray(frame_rgb)

        cw = max(self.canvas.winfo_width(), 1)
        ch = max(self.canvas.winfo_height(), 1)
        img.thumbnail((cw, ch), Image.LANCZOS)

        self._photo_image = ImageTk.PhotoImage(img)
        self.canvas.delete("all")
        self.canvas.create_image(cw // 2, ch // 2, image=self._photo_image, anchor="center")

    def _on_seek_release(self, _event):
        if self.cap is None or self.duration <= 0:
            self.user_dragging_seek = False
            return
        fraction = self.seek_var.get() / 1000
        target_frame = int(fraction * self.frame_count)
        self.current_frame_index = target_frame
        self._show_frame_at(target_frame)
        if self._audio_channel is not None:
            self._audio_channel.stop()
            self._audio_channel = None
        if self.is_playing:
            self._pause()
            self._play()
        self.user_dragging_seek = False

    def _on_volume_change(self, _value):
        if self._audio_channel is not None:
            self._audio_channel.set_volume(self.volume_var.get() / 100)



class RealBeatsApp:
    def __init__(self):
        pygame.init()
        pygame.mixer.init()

        self.root = tk.Tk()
        self.root.title("RealBeats")
        self.root.geometry("760x560")
        self.root.minsize(620, 480)
        self.root.configure(bg=BG_DARK)

        self._configure_style()
        self._build_menu()

        notebook = ttk.Notebook(self.root, style="RealBeats.TNotebook")
        notebook.pack(fill="both", expand=True)

        self.music_player = MusicPlayer(notebook)
        notebook.add(self.music_player, text="  🎵  Music  ")

        self.video_player = VideoPlayer(notebook)
        notebook.add(self.video_player, text="  🎬  Video  ")

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _configure_style(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(
            "RealBeats.TNotebook", background=BG_DARK, borderwidth=0,
        )
        style.configure(
            "RealBeats.TNotebook.Tab", background=BG_CONTROLS, foreground=TEXT_DIM,
            padding=(14, 8), font=("Helvetica", 10, "bold"), borderwidth=0,
        )
        style.map(
            "RealBeats.TNotebook.Tab",
            background=[("selected", BG_DARK)],
            foreground=[("selected", ACCENT)],
        )

    def _build_menu(self):
        menubar = tk.Menu(self.root)

        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Add Music Files…", command=lambda: self.music_player.add_files())
        file_menu.add_command(label="Add Music Folder…", command=lambda: self.music_player.add_folder())
        file_menu.add_command(label="Open Video…", command=lambda: self.video_player.open_video())
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self._on_close)
        menubar.add_cascade(label="File", menu=file_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="About", command=self._show_about)
        menubar.add_cascade(label="Help", menu=help_menu)

        self.root.config(menu=menubar)

    def _show_about(self):
        messagebox.showinfo(
            "About RealBeats",
            "RealBeats\nA lightweight VLC-style audio & video player.\n\n"
            "Built with Python, Tkinter, pygame and OpenCV.",
        )

    def _on_close(self):
        try:
            self.video_player.stop_video()
            if self.video_player._temp_audio_file and os.path.exists(self.video_player._temp_audio_file):
                os.remove(self.video_player._temp_audio_file)
        except Exception:
            pass
        pygame.mixer.quit()
        pygame.quit()
        self.root.destroy()

    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    RealBeatsApp().run()