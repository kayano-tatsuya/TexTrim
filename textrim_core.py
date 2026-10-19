"""
textrim_core.py - shared logic for TexTrim (no GUI imports).

Scans folders for oversized DDS textures and downscales them with texconv.exe.
"""

import os
import shutil
import struct
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

APP_NAME = "TexTrim"
TEXCONV_URL = "https://github.com/microsoft/DirectXTex/releases/latest/download/texconv.exe"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def startup_log(msg: str):
    """Append a line to textrim_startup.log next to the exe (falls back to temp). Never raises."""
    import time
    for folder in (exe_dir(), Path(tempfile.gettempdir())):
        try:
            with open(folder / "textrim_startup.log", "a", encoding="utf-8") as f:
                f.write(f"{time.strftime('%H:%M:%S')} {msg}\n")
            return
        except OSError:
            continue


# --------------------------------------------------------------------------- core

@dataclass
class Tex:
    path: Path
    rel: Path
    w: int
    h: int
    mips: int
    new_w: int
    new_h: int
    new_mips: int
    size: int

    @property
    def est_new_size(self) -> int:
        # Block-compressed formats (BC1-BC7) are fixed bits per pixel, so size scales with pixel count.
        # (Don't derive this from mip counts: many textures have a single mip level.)
        old_px = max(self.w * self.h, 1)
        return max(int(self.size * (self.new_w * self.new_h) / old_px), 1)


def exe_dir() -> Path:
    """Folder containing the program the user launched (where logs should go)."""
    if getattr(sys, "frozen", False):  # PyInstaller
        return Path(sys.executable).parent
    if "__compiled__" in globals():  # Nuitka (onefile: argv[0] is the original exe, not the temp copy)
        return Path(sys.argv[0]).resolve().parent
    return Path(__file__).resolve().parent


def bundle_dir() -> Path:
    """Folder holding data files bundled into the program (e.g. texconv.exe)."""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass) if meipass else Path(__file__).resolve().parent


app_dir = exe_dir  # backwards-compatible name


def run_mode() -> str:
    """How the program is running, for logs: pyinstaller / nuitka / script."""
    if getattr(sys, "frozen", False):
        return "pyinstaller"
    return "nuitka" if "__compiled__" in globals() else "script"


def data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    d = base / "TexTrim"
    old = base / "ZZTextureShrinker"  # pre-rename folder: carry over cached texconv + settings
    if not d.exists() and old.is_dir():
        try:
            old.rename(d)
        except OSError:
            pass
    d.mkdir(parents=True, exist_ok=True)
    return d


def find_texconv():
    candidates = [bundle_dir() / "texconv.exe", exe_dir() / "texconv.exe", data_dir() / "texconv.exe"]
    for c in candidates:
        if c.is_file():
            return c
    found = shutil.which("texconv") or shutil.which("texconv.exe")
    return Path(found) if found else None


def ensure_texconv(log=print) -> Path:
    found = find_texconv()
    if found:
        return found
    dest = data_dir() / "texconv.exe"
    log("texconv.exe not found, downloading from Microsoft's DirectXTex releases...")
    with urllib.request.urlopen(TEXCONV_URL, timeout=60) as r, open(dest, "wb") as f:
        shutil.copyfileobj(r, f)
    log(f"Downloaded to {dest}")
    return dest


def read_dds_info(path: Path):
    """Return (width, height, mip_count) from the DDS header, or None."""
    try:
        with open(path, "rb") as f:
            head = f.read(32)
    except OSError:
        return None
    if len(head) < 32 or head[:4] != b"DDS ":
        return None
    _size, _flags, height, width, _pitch, _depth, mips = struct.unpack("<7I", head[4:32])
    return width, height, max(mips, 1)


def target_size(w: int, h: int, max_side: int):
    """Halve until longest side <= max_side (keeps aspect and multiples of 4)."""
    n = 0
    while max(w, h) > max_side and min(w, h) > 4:
        w = max(w // 2, 4)
        h = max(h // 2, 4)
        n += 1
    return w, h, n


def scan(root: Path, max_side: int, excludes=(), should_stop=lambda: False):
    results = []
    excludes = [e.lower() for e in excludes if e]
    for p in root.rglob("*"):
        if should_stop():
            break
        if p.suffix.lower() != ".dds" or not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(e in str(rel).lower() for e in excludes):
            continue
        info = read_dds_info(p)
        if not info:
            continue
        w, h, mips = info
        nw, nh, halvings = target_size(w, h, max_side)
        if halvings == 0:
            continue
        results.append(Tex(p, rel, w, h, mips, nw, nh, max(mips - halvings, 1), p.stat().st_size))
    results.sort(key=lambda t: t.size, reverse=True)
    return results


def default_backup_root(root: Path) -> Path:
    return root.with_name(root.name + "_texture_backup")


def shrink_one(tex: Tex, texconv: Path, backup_root, tmp_root: Path):
    """Resize one texture in place. Returns (bytes_before, bytes_after)."""
    before = tex.path.stat().st_size
    with tempfile.TemporaryDirectory(dir=tmp_root) as tmp:
        cmd = [str(texconv), "-nologo", "-y", "-w", str(tex.new_w), "-h", str(tex.new_h),
               "-m", str(tex.new_mips), "-o", tmp, str(tex.path)]
        res = subprocess.run(cmd, capture_output=True, text=True, creationflags=NO_WINDOW)
        out = Path(tmp) / tex.path.name
        if res.returncode != 0 or not out.is_file():
            raise RuntimeError((res.stdout or res.stderr or "texconv failed").strip())
        if backup_root is not None:
            dest = Path(backup_root) / tex.rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():  # never overwrite an existing backup
                shutil.copy2(tex.path, dest)
        shutil.move(str(out), str(tex.path))
    return before, tex.path.stat().st_size


def restore_backups(root: Path, backup_root: Path, log=print) -> int:
    count = 0
    for p in backup_root.rglob("*.dds"):
        dest = root / p.relative_to(backup_root)
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, dest)
        count += 1
        log(f"Restored {p.relative_to(backup_root)}")
    return count


def human(n) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"
