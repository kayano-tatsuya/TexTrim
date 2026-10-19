@echo off
setlocal
cd /d "%~dp0"
set PY=python
where python >nul 2>&1 || set PY=py

echo [1/4] Checking Python...
%PY% --version || (echo ERROR: Python not found on PATH. Install from python.org and tick "Add to PATH". & goto :fail)

echo [2/4] Installing PySide6 + Nuitka...
%PY% -m pip install --upgrade PySide6-Essentials nuitka ordered-set zstandard || goto :fail
%PY% -c "import PySide6.QtWidgets" || (echo ERROR: PySide6 failed to import. Python 3.12 is the safest version. & goto :fail)

echo [3/4] Getting texconv.exe...
if not exist texconv.exe curl -L -o texconv.exe https://github.com/microsoft/DirectXTex/releases/latest/download/texconv.exe || goto :fail
for %%A in (texconv.exe) do if %%~zA LSS 100000 (echo ERROR: texconv.exe looks invalid, delete it and retry. & goto :fail)

echo [4/4] Compiling with Nuitka (first build takes several minutes; it may download a C compiler)...
%PY% -m nuitka --onefile --enable-plugin=pyside6 --windows-console-mode=disable ^
  --assume-yes-for-downloads ^
  --include-data-files=texconv.exe=texconv.exe ^
  --noinclude-qt-plugins=tls,printsupport,iconengines ^
  --output-dir=dist_nuitka --output-filename=TexTrim.exe ^
  --product-name="TexTrim" --file-description="TexTrim texture optimizer" ^
  --product-version=1.0.0.0 --file-version=1.0.0.0 ^
  textrim_qt.py || goto :fail

echo.
for %%A in (dist_nuitka\TexTrim.exe) do echo SUCCESS: dist_nuitka\TexTrim.exe  (%%~zA bytes)
if not defined CI pause
exit /b 0

:fail
echo.
echo BUILD FAILED - read the messages above.
if not defined CI pause
exit /b 1
