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
    kind: str = "dds"      # "dds" or "tga"
    bpp: int = 0           # TGA only: bytes per pixel texconv will write
    rle: bool = False      # TGA only: original was RLE-compressed (texconv always writes uncompressed)

    @property
    def est_new_size(self) -> int:
        if self.kind == "tga":
            # texconv's TGA writer is always uncompressed: 18-byte header + raw pixels.
            return 18 + self.new_w * self.new_h * max(self.bpp, 1)
        # Block-compressed formats (BC1-BC7) are fixed bits per pixel, so size scales with pixel count.
        # (Don't derive this from mip counts: many textures have a single mip level.)
        old_px = max(self.w * self.h, 1)
        return max(int(self.size * (self.new_w * self.new_h) / old_px), 1)

    @property
    def grows(self) -> bool:
        """True when shrinking would make the file bigger on disk (RLE-compressed TGA sources)."""
        return self.kind == "tga" and self.est_new_size >= self.size


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


def read_tga_info(path: Path):
    """Return (width, height, bytes_per_pixel_out, rle) from a TGA header, or None if it doesn't look like TGA.

    TGA has no magic number, so the 18-byte header is sanity-checked instead.
    """
    try:
        with open(path, "rb") as f:
            hdr = f.read(18)
    except OSError:
        return None
    if len(hdr) < 18:
        return None
    cmap_type, img_type = hdr[1], hdr[2]
    cmap_bits = hdr[7]
    width, height = struct.unpack("<2H", hdr[12:16])
    depth = hdr[16]
    if img_type not in (1, 2, 3, 9, 10, 11) or cmap_type not in (0, 1):
        return None
    if width == 0 or height == 0 or depth not in (8, 15, 16, 24, 32):
        return None
    if img_type in (1, 9) and (cmap_type != 1 or cmap_bits not in (15, 16, 24, 32)):
        return None
    rle = img_type >= 9
    if img_type in (3, 11):                    # greyscale
        bpp = 1 if depth == 8 else 2
    elif img_type in (1, 9):                   # palettized: texconv expands to truecolor
        bpp = 4 if cmap_bits == 32 else 3
    else:                                      # truecolor
        bpp = {15: 2, 16: 2, 24: 3, 32: 4}[depth]
    return width, height, bpp, rle


def target_size(w: int, h: int, max_side: int):
    """Halve until longest side <= max_side (keeps aspect and multiples of 4)."""
    n = 0
    while max(w, h) > max_side and min(w, h) > 4:
        w = max(w // 2, 4)
        h = max(h // 2, 4)
        n += 1
    return w, h, n


def scan(root: Path, max_side: int, excludes=(), should_stop=lambda: False, include_tga=False):
    results = []
    excludes = [e.lower() for e in excludes if e]
    for p in root.rglob("*"):
        if should_stop():
            break
        suffix = p.suffix.lower()
        if suffix not in (".dds", ".tga") or (suffix == ".tga" and not include_tga) or not p.is_file():
            continue
        rel = p.relative_to(root)
        if any(e in str(rel).lower() for e in excludes):
            continue
        if suffix == ".dds":
            info = read_dds_info(p)
            if not info:
                continue
            w, h, mips = info
            nw, nh, halvings = target_size(w, h, max_side)
            if halvings:
                results.append(Tex(p, rel, w, h, mips, nw, nh, max(mips - halvings, 1), p.stat().st_size))
        else:
            info = read_tga_info(p)
            if not info:
                continue
            w, h, bpp, rle = info
            nw, nh, halvings = target_size(w, h, max_side)
            if halvings:
                results.append(Tex(p, rel, w, h, 1, nw, nh, 1, p.stat().st_size, "tga", bpp, rle))
    results.sort(key=lambda t: t.size, reverse=True)
    return results


def default_backup_root(root: Path) -> Path:
    return root.with_name(root.name + "_texture_backup")


class Cancelled(Exception):
    """Raised by shrink_one when the user cancels while texconv is running."""


# texconv "-bc" flags: q = minimal compression (BC7 uses only mode 6), x = exhaustive. See the texconv wiki.
QUALITY_FLAGS = {"fast": ["-bc", "q"], "balanced": [], "best": ["-bc", "x"]}
_NO_BC_FLAGS = set()  # texconv builds that rejected -bc (older versions), so we stop trying


def _run_texconv(cmd, cancel):
    """Run texconv, killing it if `cancel` is set. Returns (returncode, message)."""
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            creationflags=NO_WINDOW)
    while True:
        try:
            out, err = proc.communicate(timeout=0.25)
            return proc.returncode, (out or err or "texconv failed").strip()
        except subprocess.TimeoutExpired:
            if cancel is not None and cancel.is_set():
                proc.kill()
                proc.communicate()
                raise Cancelled() from None


def shrink_one(tex: Tex, texconv: Path, backup_root, tmp_root: Path, cancel=None,
               quality="balanced", log=None):
    """Resize one texture in place. Returns (bytes_before, bytes_after).

    quality: "fast", "balanced" (default, texconv's own default) or "best" (BC6H/BC7 encoding effort).
    If `cancel` (a threading.Event) is set while texconv is running, texconv is killed, the original
    file is left untouched, and Cancelled is raised.
    """
    before = tex.path.stat().st_size
    is_tga = tex.kind == "tga"
    flags = [] if (is_tga or str(texconv) in _NO_BC_FLAGS) else QUALITY_FLAGS.get(quality, [])
    with tempfile.TemporaryDirectory(dir=tmp_root, ignore_cleanup_errors=True) as tmp:
        base = [str(texconv), "-nologo", "-y", "-w", str(tex.new_w), "-h", str(tex.new_h)]
        # texconv writes DDS unless told otherwise; -m (mip count) only applies to DDS output.
        base += ["-ft", "tga"] if is_tga else ["-m", str(tex.new_mips)]
        tail = ["-o", tmp, str(tex.path)]
        outfile = Path(tmp) / f"{tex.path.stem}.{tex.kind}"
        rc, msg = _run_texconv(base + flags + tail, cancel)
        if (rc != 0 or not outfile.is_file()) and flags:
            # Older texconv builds don't know -bc. Retry plainly; if that works, remember and tell the user.
            rc, msg = _run_texconv(base + tail, cancel)
            if rc == 0 and outfile.is_file():
                _NO_BC_FLAGS.add(str(texconv))
                if log:
                    log("NOTE This texconv doesn't support the encoding option, so the default was used. "
                        "Delete texconv.exe and let TexTrim download the latest one.")
        if rc != 0 or not outfile.is_file():
            raise RuntimeError(msg)
        if backup_root is not None:
            dest = Path(backup_root) / tex.rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if not dest.exists():  # never overwrite an existing backup
                shutil.copy2(tex.path, dest)
        shutil.move(str(outfile), str(tex.path))
    return before, tex.path.stat().st_size


def restore_backups(root: Path, backup_root: Path, log=print) -> int:
    count = 0
    for p in backup_root.rglob("*"):
        if p.suffix.lower() not in (".dds", ".tga") or not p.is_file():
            continue
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
