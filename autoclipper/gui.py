"""AutoClipper desktop app (tkinter)."""
from __future__ import annotations

import base64
import os
import queue
import subprocess
import sys
import tempfile
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, settings as cfg
from .drafts import PLATFORMS, build_draft
from .engine import FONTS, EngineError, Job, Result, make_clip, thumbnail
from . import updates
from .presets import PRESETS

try:
    from tkinterdnd2 import DND_FILES, DND_TEXT, TkinterDnD
    HAVE_DND = True
except Exception:  # drag and drop is optional
    HAVE_DND = False

WM_MODES = {"Off": "off", "Text": "text", "Logo": "logo", "Text + logo": "both"}
WM_MODES_REV = {v: k for k, v in WM_MODES.items()}
STYLES = {"Framed (zoomed)": "frame", "Full video over blur": "blur", "Fill screen (crop)": "crop"}
BROWSERS = ["", "firefox", "edge", "chrome", "brave", "opera", "vivaldi"]
ACCENT = "#2563eb"


class SettingsDialog(tk.Toplevel):
    def __init__(self, app: "App"):
        super().__init__(app.root)
        self.app = app
        self.title("Settings")
        self.resizable(False, False)
        self.transient(app.root)
        s = app.settings
        self.vars = {
            "out_dir": tk.StringVar(value=s.out_dir or str(s.output_path)),
            "hashtags": tk.StringVar(value=s.hashtags),
            "cookies_browser": tk.StringVar(value=s.cookies_browser),
            "cookies_file": tk.StringVar(value=s.cookies_file),
        }
        f = ttk.Frame(self, padding=14)
        f.pack()
        rows = [("Save clips to", "out_dir", "folder"), ("Default hashtags", "hashtags", None)]
        r = 0
        for label, key, browse in rows:
            ttk.Label(f, text=label).grid(row=r, column=0, sticky="w", pady=4)
            ttk.Entry(f, textvariable=self.vars[key], width=44).grid(row=r, column=1, padx=6)
            if browse:
                ttk.Button(f, text="Browse", command=lambda k=key, b=browse: self.pick(k, b)).grid(row=r, column=2)
            r += 1
        ttk.Separator(f).grid(row=r, columnspan=3, sticky="ew", pady=8)
        r += 1
        ttk.Label(f, text="Signed-in downloads (for private or adult-flagged posts)",
                  font=("", 10, "bold")).grid(row=r, columnspan=3, sticky="w")
        r += 1
        ttk.Label(f, text="Use cookies from browser").grid(row=r, column=0, sticky="w", pady=4)
        ttk.Combobox(f, textvariable=self.vars["cookies_browser"], values=BROWSERS, width=16,
                     state="readonly").grid(row=r, column=1, sticky="w", padx=6)
        r += 1
        ttk.Label(f, text="or a cookies.txt file").grid(row=r, column=0, sticky="w")
        ttk.Entry(f, textvariable=self.vars["cookies_file"], width=44).grid(row=r, column=1, padx=6)
        ttk.Button(f, text="Browse", command=lambda: self.pick("cookies_file", "file")).grid(row=r, column=2)
        r += 1
        ttk.Label(f, text="Chrome often can't be read on Windows. Firefox is the most reliable.\n"
                          "A cookies file is a login key to your account. Keep it private.",
                  foreground="#666").grid(row=r, columnspan=3, sticky="w", pady=6)
        r += 1
        ttk.Button(f, text="Save", command=self.save).grid(row=r, column=2, sticky="e")

    def pick(self, key, kind):
        if kind == "folder":
            p = filedialog.askdirectory()
        elif kind == "image":
            p = filedialog.askopenfilename(filetypes=[("Image", "*.png *.jpg *.jpeg"), ("All", "*.*")])
        else:
            p = filedialog.askopenfilename(filetypes=[("Text", "*.txt"), ("All", "*.*")])
        if p:
            self.vars[key].set(p)

    def save(self):
        s = self.app.settings
        s.out_dir = self.vars["out_dir"].get().strip()
        s.hashtags = self.vars["hashtags"].get().strip()
        s.cookies_browser = self.vars["cookies_browser"].get()
        s.cookies_file = self.vars["cookies_file"].get().strip()
        cfg.save(s)
        self.app.tags.set(s.hashtags)
        self.destroy()


class App:
    def __init__(self):
        self.root = TkinterDnD.Tk() if HAVE_DND else tk.Tk()
        self.root.title(f"AutoClipper {__version__}")
        self.root.geometry("900x985")
        try:
            from .engine import ASSETS
            self._icon = tk.PhotoImage(file=str(ASSETS / "icon.png"))
            self.root.iconphoto(True, self._icon)
            if sys.platform == "win32":
                self.root.iconbitmap(str(ASSETS / "icon.ico"))
        except Exception:
            pass
        self.root.minsize(760, 760)
        ttk.Style(self.root).theme_use("clam")
        self.settings = cfg.load()
        self.q: queue.Queue = queue.Queue()
        self.result: Result | None = None
        self.platform: str | None = None
        self.build()
        self.hook_steps()
        self.root.after(100, self.poll)
        threading.Thread(target=self.check_updates, daemon=True).start()

    # ---------- layout ----------
    def sect(self, parent, n: int, title: str):
        lbl = ttk.Label(parent, text=f"{n}  {title}")
        self.steps[n] = (lbl, title)
        return ttk.LabelFrame(parent, labelwidget=lbl, padding=8)

    def set_step(self, n: int, done: bool):
        lbl, title = self.steps[n]
        if done:
            lbl.configure(text=f"\u2713  {title}", foreground="#15803d", font=("", 10, "bold"))
        else:
            lbl.configure(text=f"{n}  {title}", foreground="", font="TkDefaultFont")

    def refresh_steps(self, *_):
        src = bool(self.source.get().strip())
        wm = WM_MODES[self.wm_mode.get()]
        need_text = wm in ("text", "both") and not self.wm_text.get().strip()
        need_logo = wm in ("logo", "both") and not self.wm_logo.get().strip()
        trim_bad = self.mode.get() == "trim" and not (self.start.get().strip() and self.end.get().strip())
        self.set_step(1, src)
        self.set_step(2, src and not trim_bad)
        self.set_step(3, src and not need_text and not need_logo)
        self.set_step(4, src and bool(self.caption.get().strip()))
        self.set_step(5, self.result is not None)

    def build(self):
        self.steps = {}
        root = self.root
        top = self.top = tk.Frame(root, bg=ACCENT)
        top.pack(fill="x")
        try:
            from PIL import Image
            import io
            from .engine import ASSETS
            im = Image.open(ASSETS / "icon.png").convert("RGBA").resize((26, 26), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "PNG")
            self._logo = tk.PhotoImage(data=base64.b64encode(buf.getvalue()))
            tk.Label(top, image=self._logo, bg=ACCENT).pack(side="left", padx=(14, 0), pady=10)
        except Exception:
            pass
        tk.Label(top, text="AutoClipper", bg=ACCENT, fg="white", font=("", 16, "bold")).pack(side="left", padx=(8, 14), pady=10)
        tk.Label(top, text="link or video in, ready-to-post short out", bg=ACCENT, fg="#dbe7ff").pack(side="left")
        ttk.Button(top, text="Settings", command=lambda: SettingsDialog(self)).pack(side="right", padx=12)

        foot = ttk.Frame(root, padding=(14, 4))
        foot.pack(side="bottom", fill="x")
        ttk.Separator(root).pack(side="bottom", fill="x")
        ttk.Label(foot, text=f"Made by Shantanu Gupta   v{__version__}", foreground="#666").pack(side="left")
        lic = ttk.Label(foot, text="MIT License", foreground="#2563eb", cursor="hand2")
        lic.pack(side="right")
        lic.bind("<Button-1>", lambda _e: webbrowser.open("https://github.com/heyshantanugupta/autoclipper/blob/main/LICENSE"))

        body = ttk.Frame(root, padding=(14, 8))
        body.pack(fill="both", expand=True)

        # 1 source
        box = self.sect(body, 1, "Video")
        box.pack(fill="x", pady=4)
        row = ttk.Frame(box)
        row.pack(fill="x")
        self.source = tk.StringVar()
        self.src_entry = ttk.Entry(row, textvariable=self.source)
        self.src_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Paste link", command=self.paste).pack(side="left", padx=4)
        ttk.Button(row, text="Choose file", command=self.browse).pack(side="left")
        hint = ("Paste a link from YouTube, X, TikTok, Instagram, Twitch, Reddit... or drop a video here"
                if HAVE_DND else "Paste a link from YouTube, X, TikTok, Instagram, Twitch, Reddit... or choose a file")
        self.drop = tk.Label(box, text=hint, relief="groove", height=3, bg="#f3f6fb", fg="#445")
        self.drop.pack(fill="x", pady=(6, 0))
        if HAVE_DND:
            for w in (self.drop, self.src_entry):
                w.drop_target_register(DND_FILES, DND_TEXT)
                w.dnd_bind("<<Drop>>", self.on_drop)

        # 2 length
        box = self.sect(body, 2, "Clip length")
        box.pack(fill="x", pady=4)
        self.mode = tk.StringVar(value="whole")
        self.secs = tk.IntVar(value=59)
        g = ttk.Frame(box)
        g.pack(fill="x")
        ttk.Radiobutton(g, text="From the start, up to", variable=self.mode, value="whole").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(g, from_=5, to=180, width=5, textvariable=self.secs).grid(row=0, column=1, padx=4)
        ttk.Label(g, text="seconds (max 180)").grid(row=0, column=2, sticky="w")
        self.start, self.end = tk.StringVar(), tk.StringVar()
        ttk.Radiobutton(g, text="Pick a section: from", variable=self.mode, value="trim").grid(row=1, column=0, sticky="w", pady=3)
        ttk.Entry(g, width=8, textvariable=self.start).grid(row=1, column=1, padx=4)
        ttk.Label(g, text="to").grid(row=1, column=2)
        ttk.Entry(g, width=8, textvariable=self.end).grid(row=1, column=3, padx=4)
        ttk.Label(g, text="like 0:53 and 1:46").grid(row=1, column=4, sticky="w")
        ttk.Radiobutton(g, text="Auto-pick the loudest moment (uses the length above)", variable=self.mode,
                        value="auto").grid(row=2, column=0, columnspan=5, sticky="w")

        # 3 format
        box = self.sect(body, 3, "Format")
        box.pack(fill="x", pady=4)
        row1 = ttk.Frame(box)
        row1.pack(fill="x")
        self.preset = tk.StringVar(value="Custom")
        pre = ttk.Combobox(row1, textvariable=self.preset, state="readonly", width=14, values=list(PRESETS))
        pre.pack(side="left", padx=(0, 8))
        pre.bind("<<ComboboxSelected>>", self.apply_preset)
        self.aspect = tk.StringVar(value="Short (9:16)")
        ttk.Combobox(row1, textvariable=self.aspect, state="readonly", width=15,
                     values=["Short (9:16)", "Widescreen (16:9)"]).pack(side="left")
        self.style = tk.StringVar(value=list(STYLES)[0])
        ttk.Combobox(row1, textvariable=self.style, state="readonly", width=24,
                     values=list(STYLES)).pack(side="left", padx=8)
        self.enhance = tk.BooleanVar(value=True)
        ttk.Checkbutton(row1, text="Enhance colors", variable=self.enhance).pack(side="left")

        row2 = ttk.Frame(box)
        row2.pack(fill="x", pady=(8, 0))
        st = self.settings
        ttk.Label(row2, text="Watermark").pack(side="left")
        self.wm_mode = tk.StringVar(value=WM_MODES_REV.get(st.watermark_mode, "Off"))
        mode = ttk.Combobox(row2, textvariable=self.wm_mode, state="readonly", width=12, values=list(WM_MODES))
        mode.pack(side="left", padx=6)
        self.wm_text = tk.StringVar(value=st.watermark_text)
        self.wm_text_e = ttk.Entry(row2, textvariable=self.wm_text, width=16)
        self.wm_text_e.pack(side="left")
        self.wm_font = tk.StringVar(value=FONTS.get(st.watermark_font, FONTS["clean"])[0])
        self.wm_font_c = ttk.Combobox(row2, textvariable=self.wm_font, state="readonly", width=8,
                                      values=[v[0] for v in FONTS.values()])
        self.wm_font_c.pack(side="left", padx=6)
        self.wm_logo = tk.StringVar(value=st.watermark_logo)
        self.wm_logo_e = ttk.Entry(row2, textvariable=self.wm_logo, width=18)
        self.wm_logo_e.pack(side="left")
        self.wm_logo_b = ttk.Button(row2, text="Logo...", command=self.pick_logo)
        self.wm_logo_b.pack(side="left", padx=6)
        mode.bind("<<ComboboxSelected>>", lambda _e: self.update_wm_fields())
        self.update_wm_fields()

        # 4 text
        box = self.sect(body, 4, "Caption and credit")
        box.pack(fill="x", pady=4)
        box.columnconfigure(1, weight=1)
        self.caption, self.credit = tk.StringVar(), tk.StringVar()
        self.tags = tk.StringVar(value=self.settings.hashtags)
        self.show_cap = tk.BooleanVar(value=True)
        ttk.Label(box, text="Caption").grid(row=0, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.caption).grid(row=0, column=1, sticky="ew", padx=6, pady=2)
        ttk.Checkbutton(box, text="Show on video", variable=self.show_cap).grid(row=0, column=2)
        ttk.Label(box, text="Credit").grid(row=1, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.credit).grid(row=1, column=1, sticky="ew", padx=6, pady=2)
        ttk.Label(box, text="blank = none, type auto = use the uploader").grid(row=1, column=2, sticky="w")
        ttk.Label(box, text="Hashtags").grid(row=2, column=0, sticky="w")
        ttk.Entry(box, textvariable=self.tags).grid(row=2, column=1, sticky="ew", padx=6, pady=2)

        self.go = tk.Button(body, text="Make clip", command=self.start_job, bg=ACCENT, fg="white",
                            font=("", 11, "bold"), relief="flat", pady=10, bd=0, activebackground="#1e40af",
                            activeforeground="white", disabledforeground="#c7d2fe", cursor="hand2")
        self.go.pack(fill="x", pady=(8, 4))
        self._go_fade = None
        self.go.bind("<Enter>", lambda _e: self.fade_go("#1d4ed8"))
        self.go.bind("<Leave>", lambda _e: self.fade_go(ACCENT))
        self.go.bind("<ButtonPress-1>", lambda _e: self.fade_go("#1e40af", steps=2))
        self.go.bind("<ButtonRelease-1>", lambda _e: self.fade_go("#1d4ed8", steps=2))
        self.bar = ttk.Progressbar(body, mode="indeterminate")
        self.bar.pack(fill="x")
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(body, textvariable=self.status, wraplength=840, justify="left").pack(anchor="w", pady=4)

        # 5 drafts
        box = self.sect(body, 5, "Post draft: pick where you're posting")
        box.pack(fill="both", expand=True, pady=4)
        pf = ttk.Frame(box)
        pf.pack(fill="x")
        self.pbtns = {}
        for name in PLATFORMS:
            b = ttk.Button(pf, text=name, command=lambda n=name: self.show_draft(n))
            b.pack(side="left", padx=(0, 6))
            self.pbtns[name] = b
        ttk.Button(pf, text="Show clip in folder", command=self.open_folder).pack(side="right")
        ttk.Button(pf, text="Play clip", command=self.play).pack(side="right", padx=6)
        mid = ttk.Frame(box)
        mid.pack(fill="both", expand=True, pady=(8, 0))
        self.thumb = tk.Label(mid, text="Preview\nappears here", width=18, bg="#eef1f6", fg="#667")
        self.thumb.pack(side="left", fill="y", padx=(0, 10))
        right = ttk.Frame(mid)
        right.pack(side="left", fill="both", expand=True)
        tr = self.title_row = ttk.Frame(right)
        ttk.Label(tr, text="Title").pack(side="left")
        self.draft_title = tk.StringVar()
        ttk.Entry(tr, textvariable=self.draft_title).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(tr, text="Copy", command=lambda: self.copy(self.draft_title.get())).pack(side="left")
        self.draft = tk.Text(right, height=8, wrap="word")
        self.draft.pack(fill="both", expand=True, pady=4)
        self.draft_widget = self.draft
        bf = ttk.Frame(right)
        bf.pack(fill="x")
        ttk.Button(bf, text="Copy description", command=lambda: self.copy(self.draft.get("1.0", "end").strip())).pack(side="left")
        ttk.Button(bf, text="Open upload page", command=self.open_upload).pack(side="left", padx=6)

    def fade_go(self, target: str, steps: int = 6):
        """Smoothly change the Make clip button colour (hover animation)."""
        if self.go.cget("state") == "disabled":
            self.go.configure(bg=ACCENT)
            return
        if self._go_fade:
            self.root.after_cancel(self._go_fade)
        def rgb(h):
            return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))
        start, end = rgb(self.go.cget("bg")), rgb(target)
        def step(i=1):
            c = tuple(round(a + (b - a) * i / steps) for a, b in zip(start, end))
            self.go.configure(bg="#%02x%02x%02x" % c)
            self._go_fade = self.root.after(18, step, i + 1) if i < steps else None
        step()

    def hook_steps(self):
        for v in (self.source, self.mode, self.start, self.end, self.wm_mode, self.wm_text, self.wm_logo, self.caption):
            v.trace_add("write", self.refresh_steps)
        self.refresh_steps()

    def update_wm_fields(self):
        mode = WM_MODES[self.wm_mode.get()]
        use_text, use_logo = mode in ("text", "both"), mode in ("logo", "both")
        self.wm_text_e.configure(state="normal" if use_text else "disabled")
        self.wm_font_c.configure(state="readonly" if use_text else "disabled")
        self.wm_logo_e.configure(state="normal" if use_logo else "disabled")
        self.wm_logo_b.configure(state="normal" if use_logo else "disabled")

    def pick_logo(self):
        p = filedialog.askopenfilename(filetypes=[("Image", "*.png *.jpg *.jpeg"), ("All", "*.*")])
        if p:
            self.wm_logo.set(p)

    def watermark_args(self):
        mode = WM_MODES[self.wm_mode.get()]
        key = next((k for k, v in FONTS.items() if v[0] == self.wm_font.get()), "clean")
        text = self.wm_text.get().strip() if mode in ("text", "both") else ""
        logo = self.wm_logo.get().strip() if mode in ("logo", "both") else ""
        return mode, text, logo, key

    def apply_preset(self, _=None):
        p = PRESETS.get(self.preset.get())
        if p:
            self.aspect.set("Short (9:16)" if p[0] == "9:16" else "Widescreen (16:9)")
            self.secs.set(p[1])

    # ---------- input helpers ----------
    def browse(self):
        p = filedialog.askopenfilename(filetypes=[("Video", "*.mp4 *.mov *.mkv *.webm *.avi"), ("All", "*.*")])
        if p:
            self.source.set(p)

    def paste(self):
        try:
            self.source.set(self.root.clipboard_get().strip())
        except tk.TclError:
            pass

    def on_drop(self, e):
        items = self.root.tk.splitlist(e.data)
        if items:
            self.source.set(items[0].strip())

    def copy(self, text: str):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status.set("Copied.")

    # ---------- making the clip ----------
    def start_job(self):
        s = self.settings
        wide = self.aspect.get().startswith("Wide")
        wmode, wtext, wlogo, wfont = self.watermark_args()
        if wmode in ("text", "both") and not wtext:
            messagebox.showinfo("AutoClipper", "Type the watermark text, or set Watermark to Off.")
            return
        if wmode in ("logo", "both") and not wlogo:
            messagebox.showinfo("AutoClipper", "Choose a logo image, or set Watermark to Off.")
            return
        s.watermark_mode, s.watermark_text, s.watermark_logo, s.watermark_font = wmode, self.wm_text.get().strip(), self.wm_logo.get().strip(), wfont
        cfg.save(s)
        job = Job(
            source=self.source.get(), out_dir=s.output_path, mode=self.mode.get(),
            seconds=self.secs.get(), start=self.start.get(), end=self.end.get(),
            aspect="16:9" if wide else "9:16", style=STYLES[self.style.get()],
            enhance=self.enhance.get(), watermark_text=wtext, watermark_logo=wlogo, watermark_font=wfont,
            caption=self.caption.get(), show_caption=self.show_cap.get(),
            credit=self.credit.get(), cookies_browser=s.cookies_browser, cookies_file=s.cookies_file)
        if not job.source.strip():
            messagebox.showinfo("AutoClipper", "Paste a link or choose a video first.")
            return
        if job.mode == "trim" and not (job.start.strip() and job.end.strip()):
            messagebox.showinfo("AutoClipper", "Enter a start and an end time.")
            return
        self.result = None
        self.refresh_steps()
        self.go.configure(state="disabled", text="Making your clip...")
        self.bar.start(12)
        self.status.set("Working...")
        threading.Thread(target=self.work, args=(job,), daemon=True).start()

    def work(self, job: Job):
        try:
            res = make_clip(job, log=lambda m: self.q.put(("log", m)))
            self.q.put(("ok", res))
        except EngineError as ex:
            self.q.put(("err", str(ex)))
        except Exception as ex:  # unexpected
            self.q.put(("err", f"Something went wrong: {ex}"))

    def poll(self):
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "log":
                    self.status.set(val)
                elif kind == "update":
                    self.show_update(val)
                elif kind == "updprog":
                    val[0].configure(text=f"Downloading the update... {val[1]}")
                elif kind == "updready":
                    try:
                        updates.install_and_restart(val)
                        self.root.destroy()
                        os._exit(0)
                    except Exception:
                        webbrowser.open(updates.direct_url(self._latest))
                elif kind == "updfail":
                    msg, btn, later, err = val
                    msg.configure(text="The update could not be installed. Starting the download in your browser instead.")
                    webbrowser.open(updates.direct_url(self._latest))
                    later.configure(state="normal")
                else:
                    self.bar.stop()
                    self.go.configure(state="normal", text="Make clip", bg=ACCENT)
                    if kind == "ok":
                        self.result = val
                        self.refresh_steps()
                        self.show_thumb(val.path)
                        self.status.set(f"Done: {val.path.name}. Pick a platform below for your post draft.")
                    else:
                        self.status.set(val)
                        messagebox.showwarning("AutoClipper", val)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    def check_updates(self):
        latest = updates.latest_version()
        if latest and updates.is_newer(latest, __version__):
            self.q.put(("update", latest))

    def show_update(self, latest: str):
        bg = "#fff4cc"
        bar = tk.Frame(self.root, bg=bg)
        msg = tk.Label(bar, text=f"A new version of AutoClipper is available (v{latest}).", bg=bg, fg="#5a4500")
        msg.pack(side="left", padx=14, pady=6)
        auto = updates.can_self_update()
        btn = ttk.Button(bar, text="Update now" if auto else "Download")
        btn.pack(side="left")
        later = ttk.Button(bar, text="Later", command=bar.destroy)
        later.pack(side="left", padx=6)
        btn.configure(command=lambda: self.start_update(latest, bar, msg, btn, later) if auto
                      else webbrowser.open(updates.direct_url(latest)))
        bar.pack(fill="x", after=self.top)

    def start_update(self, latest, bar, msg, btn, later):
        self._latest = latest
        name = updates.asset_name(latest)
        dest = Path(tempfile.gettempdir()) / name
        btn.configure(state="disabled")
        later.configure(state="disabled")
        msg.configure(text="Downloading the update... 0%")

        def work():
            try:
                updates.download(updates.asset_url(latest, name), dest,
                                 lambda f: self.q.put(("updprog", (msg, f"{int(f * 100)}%"))))
                self.q.put(("updready", dest))
            except Exception as ex:
                self.q.put(("updfail", (msg, btn, later, str(ex))))
        threading.Thread(target=work, daemon=True).start()

    def show_thumb(self, path: Path):
        png = thumbnail(path)
        if png:
            self._img = tk.PhotoImage(data=base64.b64encode(png))
            self.thumb.configure(image=self._img, text="", width=self._img.width())

    # ---------- drafts ----------
    def show_draft(self, platform: str):
        self.platform = platform
        credit = self.result.credit_name if self.result else self.credit.get()
        title, body = build_draft(platform, self.caption.get(), credit, self.tags.get())
        self.draft_title.set(title)
        if title:
            self.title_row.pack(fill="x", pady=(0, 2), before=self.draft)
        else:
            self.title_row.pack_forget()
        self.draft.delete("1.0", "end")
        self.draft.insert("1.0", body)
        self.copy(body)
        where = "title and description" if title else "caption box"
        self.status.set(f"{platform} draft copied. Paste it into the {where}.")

    def open_upload(self):
        if self.platform:
            webbrowser.open(PLATFORMS[self.platform])

    def open_folder(self):
        if not self.result:
            return
        if os.name == "nt":
            subprocess.Popen(["explorer", "/select,", str(self.result.path)])
        else:
            webbrowser.open(self.result.path.parent.as_uri())

    def play(self):
        if not self.result:
            return
        if os.name == "nt":
            os.startfile(str(self.result.path))  # type: ignore[attr-defined]
        else:
            webbrowser.open(self.result.path.as_uri())


def main():
    App().root.mainloop()


if __name__ == "__main__":
    main()
