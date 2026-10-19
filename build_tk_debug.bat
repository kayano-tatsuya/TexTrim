@echo off
setlocal
cd /d "%~dp0"
set PY=python
where python >nul 2>&1 || set PY=py

echo [1/4] Checking Python...
%PY% --version || (echo ERROR: Python not found on PATH. Install from python.org and tick "Add to PATH". & goto :fail)
%PY% -c "import tkinter" || (echo ERROR: this Python has no tkinter. Reinstall Python and keep "tcl/tk and IDLE" ticked. & goto :fail)

echo [2/4] Installing PyInstaller...
%PY% -m pip install --upgrade pyinstaller || goto :fail

echo [3/4] Getting texconv.exe...
if not exist texconv.exe curl -L -o texconv.exe https://github.com/microsoft/DirectXTex/releases/latest/download/texconv.exe || goto :fail
for %%A in (texconv.exe) do if %%~zA LSS 100000 (echo ERROR: texconv.exe looks invalid, delete it and retry. & goto :fail)

echo [4/4] Building...
%PY% -m PyInstaller --noconfirm --clean --onefile --console --name TexTrim_tk_debug --add-binary "texconv.exe;." textrim_tk.py || goto :fail

echo.
for %%A in (dist\TexTrim_tk_debug.exe) do echo SUCCESS: dist\TexTrim_tk_debug.exe  (%%~zA bytes)
if not defined CI pause
exit /b 0

:fail
echo.
echo BUILD FAILED - read the messages above.
if not defined CI pause
exit /b 1
