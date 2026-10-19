# TexTrim

Texture optimizer for game mods. Finds oversized `.dds` textures in your mod folders and downscales
them, keeping each file's original compression format (BC7, BC5, ...). Works with mods for any game that
uses DDS textures (the XXMI family: Zenless Zone Zero, Genshin, Honkai: Star Rail, Wuthering Waves, ...).
Microsoft's `texconv` is bundled into the exe.

## Two front ends, one core (`textrim_core.py`)

| | PySide6 (recommended) | tkinter (lightweight fallback) |
|---|---|---|
| Script | `textrim_qt.py` | `textrim_tk.py` |
| Build | `build_qt.bat` -> `dist\TexTrim.exe` | `build_tk.bat` -> `dist\TexTrim_tk.exe` |
| Nuitka build (smaller) | `build_qt_nuitka.bat` -> `dist_nuitka\TexTrim.exe` | - |
| Console debug build | `build_qt_debug.bat` | `build_tk_debug.bat` |
| Diagnostics | `diagnose_qt.bat` | `diagnose_tk.bat` |

## Features (PySide6)
- Drag and drop a mods folder onto the window; it scans right away.
- Sortable columns, live filter box, per-row checkboxes, Check all / Uncheck all (visible rows).
- Right-click a row: Show in folder / Skip this mod from now on / Remove from list.
- Shrink only what is checked. Failures stay listed; successes leave the list. Cancel any time.
- Backups go to `<folder>_texture_backup`; "Restore backups" copies them back.
- Remembers your folder, size, skip list and window size.

## Build (Windows)
1. Install Python 3.12 (tick "Add to PATH").
2. Run `build_qt.bat` (or `build_qt_nuitka.bat`). It installs the dependencies, downloads texconv,
   and prints the exe path and size.

## Notes
- Halves dimensions until the longest side <= your max (keeps aspect ratio and multiples of 4).
- The savings estimate assumes block-compressed formats, where size scales with pixel count.
- Test on one mod first; some mods expect specific sizes (normal/light maps especially).
- Problems: a dialog shows the error and it is saved to `crash.log`; `textrim_startup.log` shows how far
  startup got. Run `diagnose_qt.bat` and send `diagnose_qt.txt` if you need help.
- CLI (no GUI): `python textrim_tk.py "D:/Mods" --max 2048 --dry-run`
- Upgrading from the old "ZZ Texture Shrinker": settings migrate automatically, and existing
  `_texture_backup` folders keep working.
