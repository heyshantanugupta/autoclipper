"""AutoClipper desktop app (tkinter)."""
from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__, settings as cfg
from .drafts import PLATFORMS, build_draft
from .engine import EngineError, Job, Result, make_clip

try:
    from tkinterdnd2 import DND_FILES, DND_TEXT, TkinterDnD
    HAVE_DND = True
except Exception:  # drag and drop is optional
    HAVE_DND = False

STYLES = {"Framed (zoomed, blurred sides)": "frame", "Full video over blur": "blur", "Fill screen (crop)": "crop"}
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
            "watermark": tk.StringVar(value=s.watermark),
            "hashtags": tk.StringVar(value=s.hashtags),
            "cookies_browser": tk.StringVar(value=s.cookies_browser),
            "cookies_file": tk.StringVar(value=s.cookies_file),
        }
        f = ttk.Frame(self, padding=14)
        f.pack()
        rows = [("Save clips to", "out_dir", "folder"), ("Watermark (text or logo image)", "watermark", "image"),
                ("Default hashtags", "hashtags", None)]
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
                  font=("", 9, "bold")).grid(row=r, columnspan=3, sticky="w")
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
        s.watermark = self.vars["watermark"].get().strip()
        s.hashtags = self.vars["hashtags"].get().strip()
        s.cookies_browser = self.vars["cookies_browser"].get()
        s.cookies_file = self.vars["cookies_file"].get().strip()
        cfg.save(s)
        self.app.tags.set(s.hashtags)
        self.app.wm.set(bool(s.watermark))
        self.destroy()


class App:
    def __init__(self):
        self.root = TkinterDnD.Tk() if HAVE_DND else tk.Tk()
        self.root.title(f"AutoClipper {__version__}")
        self.root.geometry("820x900")
        self.root.minsize(760, 760)
        ttk.Style(self.root).theme_use("clam")
        self.settings = cfg.load()
        self.q: queue.Queue = queue.Queue()
        self.result: Result | None = None
        self.platform: str | None = None
        self.build()
        self.root.after(100, self.poll)

    # ---------- layout ----------
    def build(self):
        root = self.root
        top = tk.Frame(root, bg=ACCENT)
        top.pack(fill="x")
        tk.Label(top, text="AutoClipper", bg=ACCENT, fg="white", font=("", 16, "bold")).pack(side="left", padx=14, pady=10)
        tk.Label(top, text="link or video in, ready-to-post short out", bg=ACCENT, fg="#dbe7ff").pack(side="left")
        ttk.Button(top, text="Settings", command=lambda: SettingsDialog(self)).pack(side="right", padx=12)

        body = ttk.Frame(root, padding=(14, 8))
        body.pack(fill="both", expand=True)

        # 1 source
        box = ttk.LabelFrame(body, text="1  Video", padding=8)
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
        box = ttk.LabelFrame(body, text="2  Clip length", padding=8)
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
        box = ttk.LabelFrame(body, text="3  Format", padding=8)
        box.pack(fill="x", pady=4)
        self.aspect = tk.StringVar(value="Short (9:16)")
        ttk.Combobox(box, textvariable=self.aspect, state="readonly", width=18,
                     values=["Short (9:16)", "Widescreen (16:9)"]).pack(side="left")
        self.style = tk.StringVar(value=list(STYLES)[0])
        ttk.Combobox(box, textvariable=self.style, state="readonly", width=30,
                     values=list(STYLES)).pack(side="left", padx=8)
        self.enhance = tk.BooleanVar(value=True)
        ttk.Checkbutton(box, text="Enhance colors", variable=self.enhance).pack(side="left")
        self.wm = tk.BooleanVar(value=bool(self.settings.watermark))
        ttk.Checkbutton(box, text="Watermark", variable=self.wm).pack(side="left", padx=8)

        # 4 text
        box = ttk.LabelFrame(body, text="4  Caption and credit", padding=8)
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
                            font=("", 11, "bold"), relief="flat", pady=8, activebackground="#1d4ed8",
                            activeforeground="white")
        self.go.pack(fill="x", pady=(8, 4))
        self.bar = ttk.Progressbar(body, mode="indeterminate")
        self.bar.pack(fill="x")
        self.status = tk.StringVar(value="Ready.")
        ttk.Label(body, textvariable=self.status, wraplength=760, justify="left").pack(anchor="w", pady=4)

        # 5 drafts
        box = ttk.LabelFrame(body, text="5  Post draft: pick where you're posting", padding=8)
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
        tr = ttk.Frame(box)
        tr.pack(fill="x", pady=(8, 2))
        ttk.Label(tr, text="Title").pack(side="left")
        self.draft_title = tk.StringVar()
        ttk.Entry(tr, textvariable=self.draft_title).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(tr, text="Copy", command=lambda: self.copy(self.draft_title.get())).pack(side="left")
        self.draft = tk.Text(box, height=8, wrap="word")
        self.draft.pack(fill="both", expand=True, pady=4)
        bf = ttk.Frame(box)
        bf.pack(fill="x")
        ttk.Button(bf, text="Copy description", command=lambda: self.copy(self.draft.get("1.0", "end").strip())).pack(side="left")
        ttk.Button(bf, text="Open upload page", command=self.open_upload).pack(side="left", padx=6)

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
        job = Job(
            source=self.source.get(), out_dir=s.output_path, mode=self.mode.get(),
            seconds=self.secs.get(), start=self.start.get(), end=self.end.get(),
            aspect="16:9" if wide else "9:16", style=STYLES[self.style.get()],
            enhance=self.enhance.get(), watermark=s.watermark if self.wm.get() else "",
            caption=self.caption.get(), show_caption=self.show_cap.get(),
            credit=self.credit.get(), cookies_browser=s.cookies_browser, cookies_file=s.cookies_file)
        if not job.source.strip():
            messagebox.showinfo("AutoClipper", "Paste a link or choose a video first.")
            return
        if job.mode == "trim" and not (job.start.strip() and job.end.strip()):
            messagebox.showinfo("AutoClipper", "Enter a start and an end time.")
            return
        self.result = None
        self.go.configure(state="disabled")
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
                else:
                    self.bar.stop()
                    self.go.configure(state="normal")
                    if kind == "ok":
                        self.result = val
                        self.status.set(f"Done: {val.path.name}. Pick a platform below for your post draft.")
                    else:
                        self.status.set(val)
                        messagebox.showwarning("AutoClipper", val)
        except queue.Empty:
            pass
        self.root.after(100, self.poll)

    # ---------- drafts ----------
    def show_draft(self, platform: str):
        self.platform = platform
        credit = self.result.credit_name if self.result else self.credit.get()
        title, body = build_draft(platform, self.caption.get(), credit, self.tags.get())
        self.draft_title.set(title)
        self.draft.delete("1.0", "end")
        self.draft.insert("1.0", body)
        self.copy(body)
        self.status.set(f"{platform} draft copied. Paste it into the description box.")

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
