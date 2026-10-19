@echo off
setlocal
cd /d "%~dp0"
set OUT=diagnose_tk.txt
echo ===== SYSTEM ===== > %OUT%
ver >> %OUT% 2>&1
echo. >> %OUT%
echo ===== PYTHON ===== >> %OUT%
where python >> %OUT% 2>&1
python --version >> %OUT% 2>&1
py --version >> %OUT% 2>&1
python -c "import sys;print(sys.executable)" >> %OUT% 2>&1
python -c "import tkinter;print('tkinter', tkinter.TkVersion)" >> %OUT% 2>&1
python -m PyInstaller --version >> %OUT% 2>&1
echo. >> %OUT%
echo ===== FILES ===== >> %OUT%
dir /b texconv.exe dist >> %OUT% 2>&1
echo. >> %OUT%
echo ===== RUN SCRIPT DIRECTLY (close the window to continue) ===== >> %OUT%
python textrim_tk.py >> %OUT% 2>&1
echo exit code: %errorlevel% >> %OUT%
echo. >> %OUT%
if exist dist\TexTrim_tk_debug.exe (
  echo ===== RUN DEBUG EXE ^(close the window to continue^) ===== >> %OUT%
  dist\TexTrim_tk_debug.exe >> %OUT% 2>&1
  echo exit code: %errorlevel% >> %OUT%
)
echo. >> %OUT%
echo ===== textrim_startup.log ===== >> %OUT%
type textrim_startup.log >> %OUT% 2>&1
type dist\textrim_startup.log >> %OUT% 2>&1
echo. >> %OUT%
echo ===== crash.log ===== >> %OUT%
type crash.log >> %OUT% 2>&1
type dist\crash.log >> %OUT% 2>&1
type "%LOCALAPPDATA%\TexTrim\crash.log" >> %OUT% 2>&1
type %OUT%
echo.
echo Saved to %CD%\%OUT% - paste its contents back to me.
pause
