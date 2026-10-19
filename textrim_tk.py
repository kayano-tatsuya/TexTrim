#!/usr/bin/env python3
"""
TexTrim (tkinter edition) - find oversized DDS textures in mod folders and downscale them.

Stdlib only. Uses Microsoft's texconv.exe (DirectXTex) for resizing so the original
compression format (BC7, BC5, ...) is preserved.

  GUI:  python textrim_tk.py
  CLI:  python textrim_tk.py "D:/Mods" --max 2048 [--dry-run]
"""

import argparse
import queue
import sys
import tempfile
import threading
from pathlib import Path

from textrim_core import (APP_NAME, app_dir, data_dir, default_backup_root, ensure_texconv,  # noqa: E402
                     human, restore_backups, run_mode, scan, shrink_one, startup_log)


# --------------------------------------------------------------------------- CLI

def run_cli(argv):
    ap = argparse.ArgumentParser(description=APP_NAME)
    ap.add_argument("root", type=Path)
    ap.add_argument("--max", type=int, default=2048)
    ap.add_argument("--exclude", default="", help="Comma-separated substrings to skip, e.g. normal,light")
    ap.add_argument("--backup", type=Path, default=None)
    ap.add_argument("--no-backup", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)

    root = a.root.resolve()
    if not root.is_dir():
        sys.exit(f"Not a folder: {root}")
    items = scan(root, a.max, a.exclude.split(","))
    if not items:
        print(f"Nothing above {a.max}px.")
        return
    for t in items:
        print(f"{t.rel}: {t.w}x{t.h} -> {t.new_w}x{t.new_h} ({human(t.size)} -> ~{human(t.est_new_size)})")
    if a.dry_run:
        print("\nDry run only.")
        return
    texconv = ensure_texconv()
    backup = None if a.no_backup else (a.backup or default_backup_root(root))
    saved = 0
    for t in items:
        try:
            b, af = shrink_one(t, texconv, backup, Path(tempfile.gettempdir()))
            saved += b - af
            print(f"OK   {t.rel}: {human(b)} -> {human(af)}")
        except Exception as e:  # noqa: BLE001
            print(f"FAIL {t.rel}: {e}")
    print(f"\nSaved about {human(saved)}.")


# --------------------------------------------------------------------------- GUI

def run_gui():
    startup_log("run_gui: importing tkinter")
    import json
    import tkinter as tk
    import tkinter.font as tkfont
    from tkinter import filedialog, messagebox, ttk
    startup_log(f"run_gui: tkinter OK (Tk {tk.TkVersion})")

    # Sharp text on high-DPI Windows displays (must happen before the window exists).
    if sys.platform == "win32":
        try:
            import ctypes
            try:
                ctypes.windll.shcore.SetProcessDpiAwareness(1)
            except Exception:  # noqa: BLE001
                ctypes.windll.user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass

    C = dict(
        bg="#111318", card="#1a1d24", card2="#232733", line="#2c313d", text="#e8eaf0",
        muted="#8a91a3", accent="#7c6cff", accent_hov="#9285ff", accent_dim="#37316b",
        sel="#2f2a63", stripe="#1e222a", ok="#3ddc97", bad="#ff6b6b",
    )
    settings_path = data_dir() / "settings.json"

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(APP_NAME)
            self.configure(bg=C["bg"])
            self.sc = max(self.winfo_fpixels("1i") / 96.0, 1.0)
            self.geometry(f"{self.S(1000)}x{self.S(780)}")
            self.minsize(self.S(840), self.S(620))

            self.q = queue.Queue()
            self.items = {}
            self.busy = False
            self.log_visible = False

            saved = self._load_settings()
            self.root_var = tk.StringVar(value=saved.get("root", ""))
            self.max_var = tk.StringVar(value=str(saved.get("max", 2048)))
            self.exclude_var = tk.StringVar(value=saved.get("exclude", ""))
            self.backup_var = tk.BooleanVar(value=saved.get("backup", True))
            self.found_var = tk.StringVar(value="0")
            self.savings_var = tk.StringVar(value="-")
            self.selected_var = tk.StringVar(value="0")
            self.status_var = tk.StringVar(value="Choose your mods folder and press Scan.")

            self._fonts()
            self._style()
            self._build()
            self.max_var.trace_add("write", lambda *_: self._sync_presets())
            self._sync_presets()
            self._refresh_primary()
            self._set_busy(False)
            self._dark_titlebar()
            self.protocol("WM_DELETE_WINDOW", self._close)
            self.after(100, self._poll)

        # ---------------------------------------------------------------- setup
        def S(self, v):
            return int(v * self.sc)

        def _fonts(self):
            fams = set(tkfont.families(self))
            fam = next((f for f in ("Segoe UI Variable Text", "Segoe UI", "Inter", "SF Pro Text",
                                    "Helvetica Neue", "DejaVu Sans") if f in fams),
                       tkfont.nametofont("TkDefaultFont").actual("family"))
            mono = next((f for f in ("Cascadia Mono", "Consolas", "DejaVu Sans Mono", "Courier New")
                         if f in fams), "TkFixedFont")
            self.f_base = tkfont.Font(family=fam, size=10)
            self.f_bold = tkfont.Font(family=fam, size=10, weight="bold")
            self.f_small = tkfont.Font(family=fam, size=9)
            self.f_small_b = tkfont.Font(family=fam, size=8, weight="bold")
            self.f_title = tkfont.Font(family=fam, size=20, weight="bold")
            self.f_stat = tkfont.Font(family=fam, size=17, weight="bold")
            self.f_mono = tkfont.Font(family=mono, size=9)

        def _style(self):
            st = ttk.Style(self)
            st.theme_use("clam")
            S = self.S

            def flat(name, bg, fg, hover=None, dim_bg=None, dim_fg=None, border=None, padding=(14, 8), font=None, width=0):
                border = border or bg
                st.configure(name, background=bg, foreground=fg, bordercolor=border, lightcolor=bg,
                             darkcolor=bg, relief="flat", borderwidth=1, focuscolor=bg, width=width,
                             padding=(S(padding[0]), S(padding[1])), font=font or self.f_base)
                hover = hover or bg
                st.map(name,
                       background=[("disabled", dim_bg or bg), ("active", hover)],
                       lightcolor=[("disabled", dim_bg or bg), ("active", hover)],
                       darkcolor=[("disabled", dim_bg or bg), ("active", hover)],
                       bordercolor=[("disabled", dim_bg or border), ("active", hover if border == bg else border)],
                       foreground=[("disabled", dim_fg or C["muted"])])

            st.configure(".", background=C["bg"], foreground=C["text"], fieldbackground=C["card2"],
                         font=self.f_base, bordercolor=C["line"], troughcolor=C["card2"], focuscolor=C["bg"])
            st.configure("TFrame", background=C["bg"])
            st.configure("TLabel", background=C["bg"], foreground=C["text"])
            st.configure("Muted.TLabel", foreground=C["muted"], font=self.f_small)
            st.configure("Title.TLabel", font=self.f_title)
            st.configure("Field.TLabel", background=C["card"], foreground=C["muted"], font=self.f_small)
            st.configure("Hint.TLabel", background=C["card"], foreground=C["muted"], font=self.f_small)
            st.configure("Stat.TLabel", background=C["card"], foreground=C["muted"], font=self.f_small_b)
            st.configure("StatNum.TLabel", background=C["card"], foreground=C["text"], font=self.f_stat)
            st.configure("Card.TFrame", background=C["card"])

            flat("TButton", C["card2"], C["text"], hover=C["line"], dim_bg=C["card"], border=C["line"])
            flat("Accent.TButton", C["accent"], "#ffffff", hover=C["accent_hov"], dim_bg=C["accent_dim"],
                 dim_fg="#9a95c9", font=self.f_bold)
            flat("Ghost.TButton", C["bg"], C["muted"], hover=C["card2"], dim_bg=C["bg"], border=C["line"])
            flat("Seg.TButton", C["card2"], C["muted"], hover=C["line"], border=C["line"], padding=(8, 6), width=6)
            flat("SegOn.TButton", C["accent_dim"], "#ffffff", hover=C["accent_dim"], border=C["accent"],
                 padding=(8, 6), font=self.f_bold, width=6)

            st.configure("TEntry", fieldbackground=C["card2"], foreground=C["text"], insertcolor=C["text"],
                         bordercolor=C["line"], lightcolor=C["card2"], darkcolor=C["card2"],
                         padding=(S(8), S(6)))
            st.map("TEntry", bordercolor=[("focus", C["accent"])], lightcolor=[("focus", C["card2"])])

            st.configure("Card.TCheckbutton", background=C["card"], foreground=C["text"], focuscolor=C["card"],
                         indicatorbackground=C["card2"], indicatorforeground="#ffffff",
                         indicatormargin=(0, 0, S(8), 0))
            st.map("Card.TCheckbutton",
                   background=[("active", C["card"])],
                   indicatorbackground=[("selected", C["accent"]), ("active", C["line"])])

            st.configure("Treeview", background=C["card"], fieldbackground=C["card"], foreground=C["text"],
                         rowheight=S(30), borderwidth=0, bordercolor=C["card"], lightcolor=C["card"],
                         darkcolor=C["card"], font=self.f_base)
            st.map("Treeview", background=[("selected", C["sel"])], foreground=[("selected", "#ffffff")])
            st.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
            st.configure("Treeview.Heading", background=C["card2"], foreground=C["muted"], relief="flat",
                         padding=(S(10), S(8)), font=self.f_small_b, bordercolor=C["card2"],
                         lightcolor=C["card2"], darkcolor=C["card2"])
            st.map("Treeview.Heading", background=[("active", C["line"])])

            st.configure("Vertical.TScrollbar", background=C["card2"], troughcolor=C["card"],
                         bordercolor=C["card"], lightcolor=C["card2"], darkcolor=C["card2"],
                         arrowcolor=C["muted"], relief="flat", gripcount=0)
            st.map("Vertical.TScrollbar", background=[("active", C["line"])])

            st.configure("Horizontal.TProgressbar", background=C["accent"], troughcolor=C["card2"],
                         bordercolor=C["bg"], lightcolor=C["accent"], darkcolor=C["accent"],
                         thickness=S(6))

        def _dark_titlebar(self):
            if sys.platform != "win32":
                return
            try:
                import ctypes
                self.update_idletasks()
                hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
                val = ctypes.c_int(1)
                for attr in (20, 19):
                    if ctypes.windll.dwmapi.DwmSetWindowAttribute(
                            hwnd, attr, ctypes.byref(val), ctypes.sizeof(val)) == 0:
                        break
            except Exception:  # noqa: BLE001
                pass

        # ---------------------------------------------------------------- layout
        def _card(self, parent, **kw):
            return tk.Frame(parent, bg=C["card"], highlightbackground=C["line"], highlightthickness=1, **kw)

        def _build(self):
            S = self.S
            outer = ttk.Frame(self)
            outer.pack(fill="both", expand=True, padx=S(22), pady=(S(18), S(14)))

            # header
            head = ttk.Frame(outer)
            head.pack(fill="x", pady=(0, S(14)))
            ttk.Label(head, text="TexTrim", style="Title.TLabel").pack(anchor="w")
            ttk.Label(head, text="Find oversized .dds textures in your mods and downscale them. "
                                 "Originals are backed up first.", style="Muted.TLabel").pack(anchor="w", pady=(2, 0))

            # settings card
            box = self._card(outer)
            box.pack(fill="x")
            g = ttk.Frame(box, style="Card.TFrame")
            g.pack(fill="x", padx=S(16), pady=S(14))
            g.columnconfigure(1, weight=1)
            lab = {"sticky": "w", "pady": S(6), "padx": (0, S(16))}

            ttk.Label(g, text="Mods folder", style="Field.TLabel").grid(row=0, column=0, **lab)
            ttk.Entry(g, textvariable=self.root_var).grid(row=0, column=1, sticky="ew", pady=S(6))
            ttk.Button(g, text="Browse", command=self._browse).grid(row=0, column=2, padx=(S(8), 0), pady=S(6))

            ttk.Label(g, text="Max texture side", style="Field.TLabel").grid(row=1, column=0, **lab)
            seg = ttk.Frame(g, style="Card.TFrame")
            seg.grid(row=1, column=1, sticky="w", pady=S(6))
            self.preset_btns = {}
            for v in (512, 1024, 2048, 4096):
                b = ttk.Button(seg, text=str(v), style="Seg.TButton",
                               command=lambda v=v: self.max_var.set(str(v)))
                b.pack(side="left", padx=(0, S(4)))
                self.preset_btns[v] = b
            ttk.Entry(seg, textvariable=self.max_var, width=6).pack(side="left", padx=(S(10), S(6)))
            ttk.Label(seg, text="px  (custom)", style="Hint.TLabel").pack(side="left")

            ttk.Label(g, text="Skip paths containing", style="Field.TLabel").grid(row=2, column=0, **lab)
            ttk.Entry(g, textvariable=self.exclude_var).grid(row=2, column=1, sticky="ew", pady=S(6))
            ttk.Label(g, text="comma-separated, e.g. normal,light", style="Hint.TLabel").grid(
                row=2, column=2, sticky="w", padx=(S(10), 0))

            ttk.Checkbutton(g, text="Back up originals before changing them (recommended)",
                            variable=self.backup_var, style="Card.TCheckbutton").grid(
                row=3, column=1, columnspan=2, sticky="w", pady=(S(8), 0))

            # stat tiles
            stats = ttk.Frame(outer)
            stats.pack(fill="x", pady=(S(12), S(12)))
            for col, (label, var) in enumerate((("Over the limit", self.found_var),
                                                ("Potential savings", self.savings_var),
                                                ("Selected", self.selected_var))):
                stats.columnconfigure(col, weight=1, uniform="stat")
                t = self._card(stats)
                t.grid(row=0, column=col, sticky="ew", padx=(0 if col == 0 else S(10), 0))
                ttk.Label(t, text=label.upper(), style="Stat.TLabel").pack(anchor="w", padx=S(14), pady=(S(10), 0))
                ttk.Label(t, textvariable=var, style="StatNum.TLabel").pack(anchor="w", padx=S(14), pady=(0, S(10)))

            # action bar (packed before the table so it never gets pushed off-screen)
            bottom = ttk.Frame(outer)
            bottom.pack(side="bottom", fill="x")
            self.log_holder = ttk.Frame(bottom)
            self.log_holder.pack(side="bottom", fill="x")
            self.log_frame = tk.Frame(self.log_holder, bg=C["card2"], highlightbackground=C["line"], highlightthickness=1)
            self.log = tk.Text(self.log_frame, height=7, state="disabled", bg=C["card2"], fg=C["muted"],
                               relief="flat", font=self.f_mono, padx=S(10), pady=S(8), wrap="word",
                               highlightthickness=0, insertbackground=C["text"])
            self.log.pack(fill="both", expand=True)
            self.log.tag_configure("fail", foreground=C["bad"])
            self.log.tag_configure("ok", foreground=C["ok"])

            status_row = ttk.Frame(bottom)
            status_row.pack(side="bottom", fill="x", pady=(S(6), 0))
            pwrap = tk.Frame(bottom, height=S(6), bg=C["card2"])
            pwrap.pack(side="bottom", fill="x", pady=(S(10), 0))
            pwrap.pack_propagate(False)
            self.progress = ttk.Progressbar(pwrap, mode="determinate")
            self.progress.pack(fill="both", expand=True)
            ttk.Label(status_row, textvariable=self.status_var, style="Muted.TLabel").pack(side="left")
            self.log_btn = ttk.Button(status_row, text="Show log", style="Ghost.TButton",
                                      command=self._toggle_log, padding=(S(8), S(2)))
            self.log_btn.pack(side="right")

            actions = ttk.Frame(bottom)
            actions.pack(side="bottom", fill="x", pady=(S(12), 0))
            self.btn_scan = ttk.Button(actions, text="Scan", command=self._scan)
            self.btn_sel = ttk.Button(actions, text="Shrink selected", command=lambda: self._shrink(True))
            self.btn_all = ttk.Button(actions, text="Shrink all listed", command=lambda: self._shrink(False))
            self.btn_restore = ttk.Button(actions, text="Restore backups", style="Ghost.TButton",
                                          command=self._restore)
            for b in (self.btn_scan, self.btn_sel, self.btn_all):
                b.pack(side="left", padx=(0, S(8)))
            self.btn_restore.pack(side="right")

            # results table
            tcard = self._card(outer)
            tcard.pack(fill="both", expand=True)
            cols = ("file", "cur", "new", "size", "after")
            self.tree = ttk.Treeview(tcard, columns=cols, show="headings", selectmode="extended")
            spec = (("file", "FILE", 380, "w", True), ("cur", "CURRENT", 100, "center", False),
                    ("new", "NEW", 100, "center", False), ("size", "SIZE", 100, "e", False),
                    ("after", "AFTER (EST.)", 130, "e", False))
            for c, t, w, a, stretch in spec:
                self.tree.heading(c, text=t, anchor="w" if c == "file" else a)
                self.tree.column(c, width=S(w), anchor=a, stretch=stretch, minwidth=S(70))
            sb = ttk.Scrollbar(tcard, orient="vertical", command=self.tree.yview)
            self.tree.configure(yscrollcommand=sb.set)
            self.tree.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")
            self.tree.tag_configure("odd", background=C["card"])
            self.tree.tag_configure("even", background=C["stripe"])
            self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())
            self.tree.bind("<Control-a>", lambda e: (self.tree.selection_set(self.tree.get_children()), "break")[1])
            self.empty = tk.Label(tcard, text="No results yet\nChoose your mods folder and press Scan",
                                  bg=C["card"], fg=C["muted"], font=self.f_base, justify="center")
            self.empty.place(relx=0.5, rely=0.55, anchor="center")

        # ---------------------------------------------------------------- helpers
        def _load_settings(self):
            try:
                return json.loads(settings_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return {}

        def _save_settings(self):
            try:
                settings_path.write_text(json.dumps({
                    "root": self.root_var.get(), "max": self.max_var.get(),
                    "exclude": self.exclude_var.get(), "backup": bool(self.backup_var.get()),
                }), encoding="utf-8")
            except OSError:
                pass

        def _close(self):
            self._save_settings()
            self.destroy()

        def _sync_presets(self):
            cur = self.max_var.get().strip()
            for v, b in self.preset_btns.items():
                b.configure(style="SegOn.TButton" if cur == str(v) else "Seg.TButton")

        def _refresh_primary(self):
            has = bool(self.items)
            self.btn_scan.configure(style="TButton" if has else "Accent.TButton")
            self.btn_all.configure(style="Accent.TButton" if has else "TButton")

        def _toggle_log(self, force=None):
            show = (not self.log_visible) if force is None else force
            if show == self.log_visible:
                return
            self.log_visible = show
            if show:
                self.log_frame.pack(fill="x", pady=(self.S(8), 0))
            else:
                self.log_frame.pack_forget()
            self.log_btn.configure(text="Hide log" if show else "Show log")

        def _browse(self):
            d = filedialog.askdirectory(initialdir=self.root_var.get() or None)
            if d:
                self.root_var.set(d)

        def _log(self, msg):
            self.log.configure(state="normal")
            tag = "fail" if msg.startswith("FAIL") else ("ok" if msg.startswith("OK") else None)
            self.log.insert("end", msg + "\n", tag)
            self.log.see("end")
            self.log.configure(state="disabled")
            if tag == "fail":
                self._toggle_log(True)

        def _set_busy(self, busy):
            self.busy = busy
            has = bool(self.items)
            self.btn_scan.state(["disabled"] if busy else ["!disabled"])
            self.btn_restore.state(["disabled"] if busy else ["!disabled"])
            for b in (self.btn_sel, self.btn_all):
                b.state(["disabled"] if (busy or not has) else ["!disabled"])

        def _get_root(self):
            p = Path(self.root_var.get().strip())
            if not self.root_var.get().strip() or not p.is_dir():
                messagebox.showerror(APP_NAME, "Choose a valid mods folder first.")
                return None
            return p.resolve()

        def _max(self):
            try:
                v = int(self.max_var.get())
                if v < 8:
                    raise ValueError
                return v
            except ValueError:
                messagebox.showerror(APP_NAME, "Max side must be a number like 2048.")
                return None

        def _on_select(self):
            sel = [self.items[i] for i in self.tree.selection() if i in self.items]
            if sel:
                self.selected_var.set(f"{len(sel)}  \u00b7  ~{human(sum(t.size - t.est_new_size for t in sel))}")
            else:
                self.selected_var.set("0")

        def _show_empty(self, text):
            self.empty.configure(text=text)
            self.empty.place(relx=0.5, rely=0.55, anchor="center")

        # ---------------------------------------------------------------- actions
        def _scan(self):
            root, mx = self._get_root(), self._max()
            if not root or not mx:
                return
            self._save_settings()
            excludes = [e.strip() for e in self.exclude_var.get().split(",")]
            self.tree.delete(*self.tree.get_children())
            self.items.clear()
            self.found_var.set("...")
            self.savings_var.set("...")
            self.selected_var.set("0")
            self.status_var.set("Scanning...")
            self._show_empty("Scanning...")
            self.progress.configure(mode="indeterminate")
            self.progress.start(15)
            self._set_busy(True)

            def work():
                try:
                    self.q.put(("scan_done", scan(root, mx, excludes), mx))
                except Exception as e:  # noqa: BLE001
                    self.q.put(("error", str(e)))
            threading.Thread(target=work, daemon=True).start()

        def _shrink(self, selected_only):
            root = self._get_root()
            if not root:
                return
            iids = self.tree.selection() if selected_only else self.tree.get_children()
            todo = [self.items[i] for i in iids if i in self.items]
            if not todo:
                messagebox.showinfo(APP_NAME, "Nothing to shrink. Scan first (and select rows if needed).")
                return
            backup = default_backup_root(root) if self.backup_var.get() else None
            if backup is None and not messagebox.askyesno(
                    APP_NAME, "Backups are off. Originals will be overwritten permanently. Continue?"):
                return
            self._save_settings()
            self._set_busy(True)
            self.status_var.set(f"Shrinking {len(todo)} texture(s)...")
            self.progress.configure(mode="determinate", maximum=len(todo), value=0)

            def work():
                try:
                    texconv = ensure_texconv(lambda m: self.q.put(("log", m)))
                except Exception as e:  # noqa: BLE001
                    self.q.put(("error", f"Could not get texconv.exe: {e}"))
                    return
                saved = 0
                for i, t in enumerate(todo, 1):
                    try:
                        b, a = shrink_one(t, texconv, backup, Path(tempfile.gettempdir()))
                        saved += b - a
                        self.q.put(("log", f"OK   {t.rel}: {human(b)} -> {human(a)}"))
                    except Exception as e:  # noqa: BLE001
                        self.q.put(("log", f"FAIL {t.rel}: {e}"))
                    self.q.put(("progress", i, len(todo)))
                self.q.put(("shrink_done", saved, backup))
            threading.Thread(target=work, daemon=True).start()

        def _restore(self):
            root = self._get_root()
            if not root:
                return
            backup = default_backup_root(root)
            if not backup.is_dir():
                messagebox.showinfo(APP_NAME, f"No backup folder found at:\n{backup}")
                return
            if not messagebox.askyesno(APP_NAME, f"Copy all backed-up textures from\n{backup}\n"
                                                 "back into the mods folder?"):
                return
            n = restore_backups(root, backup, self._log)
            self.status_var.set(f"Restored {n} texture(s) from backup.")

        # ---------------------------------------------------------------- queue pump
        def _poll(self):
            try:
                while True:
                    msg = self.q.get_nowait()
                    kind = msg[0]
                    if kind == "log":
                        self._log(msg[1])
                    elif kind == "progress":
                        self.progress.configure(value=msg[1])
                        self.status_var.set(f"{msg[1]} / {msg[2]} done")
                    elif kind == "scan_done":
                        results, mx = msg[1], msg[2]
                        self.progress.stop()
                        self.progress.configure(mode="determinate", value=0)
                        total = 0
                        for n, t in enumerate(results):
                            iid = str(n)
                            self.items[iid] = t
                            total += t.size - t.est_new_size
                            self.tree.insert("", "end", iid=iid, tags=("even" if n % 2 else "odd",), values=(
                                str(t.rel), f"{t.w}\u00d7{t.h}", f"{t.new_w}\u00d7{t.new_h}",
                                human(t.size), human(t.est_new_size)))
                        self.found_var.set(str(len(results)))
                        self.savings_var.set(f"~{human(total)}" if results else "-")
                        if results:
                            self.empty.place_forget()
                            self.status_var.set(f"{len(results)} texture(s) larger than {mx}px. "
                                                "Select rows or shrink everything.")
                        else:
                            self._show_empty(f"Nothing larger than {mx}px.\nYou're already under the limit.")
                            self.status_var.set("Scan complete.")
                        self._refresh_primary()
                        self._set_busy(False)
                    elif kind == "shrink_done":
                        self.progress.configure(value=0)
                        self.status_var.set(f"Done. Saved about {human(msg[1])}.")
                        if msg[2]:
                            self._log(f"Originals backed up to: {msg[2]}")
                        self.tree.delete(*self.tree.get_children())
                        self.items.clear()
                        self.found_var.set("0")
                        self.savings_var.set("-")
                        self.selected_var.set("0")
                        self._show_empty(f"Done. Saved about {human(msg[1])}.\nScan again to check for more.")
                        self._refresh_primary()
                        self._set_busy(False)
                    elif kind == "error":
                        self.progress.stop()
                        self.progress.configure(mode="determinate", value=0)
                        self.status_var.set("Something went wrong.")
                        self._show_empty("Something went wrong.")
                        self._set_busy(False)
                        messagebox.showerror(APP_NAME, msg[1])
            except queue.Empty:
                pass
            self.after(100, self._poll)

    app = App()
    startup_log("run_gui: window created, entering mainloop")
    app.mainloop()
    startup_log("run_gui: mainloop exited normally")


def report_crash():
    """Write the traceback to a log file and show it, since windowed builds have no console."""
    import traceback
    text = traceback.format_exc()
    startup_log("CRASH:\n" + text)
    where = ""
    for folder in (app_dir(), data_dir()):
        try:
            log_path = folder / "crash.log"
            log_path.write_text(text, encoding="utf-8")
            where = f"\n\n(Saved to {log_path})"
            break
        except OSError:
            continue
    try:
        import tkinter as tk
        from tkinter import messagebox
        r = tk.Tk()
        r.withdraw()
        messagebox.showerror(APP_NAME + " crashed", text[-1500:] + where)
        r.destroy()
    except Exception:  # noqa: BLE001
        sys.stderr and sys.stderr.write(text)


if __name__ == "__main__":
    startup_log(f"start: python {sys.version.split()[0]}, mode={run_mode()}, argv={sys.argv[1:]}")
    try:
        if len(sys.argv) > 1:
            run_cli(sys.argv[1:])
        else:
            run_gui()
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001
        report_crash()
        sys.exit(1)
