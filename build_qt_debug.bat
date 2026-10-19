@echo off
setlocal
cd /d "%~dp0"
set PY=python
where python >nul 2>&1 || set PY=py

echo [1/4] Checking Python...
%PY% --version || (echo ERROR: Python not found on PATH. Install from python.org and tick "Add to PATH". & goto :fail)

echo [2/4] Installing PySide6 + PyInstaller...
%PY% -m pip install --upgrade PySide6-Essentials pyinstaller || goto :fail
%PY% -c "import PySide6.QtWidgets" || (echo ERROR: PySide6 failed to import. Python 3.12 is the safest version. & goto :fail)

echo [3/4] Getting texconv.exe...
if not exist texconv.exe curl -L -o texconv.exe https://github.com/microsoft/DirectXTex/releases/latest/download/texconv.exe || goto :fail
for %%A in (texconv.exe) do if %%~zA LSS 100000 (echo ERROR: texconv.exe looks invalid, delete it and retry. & goto :fail)

echo [4/4] Building...
%PY% -m PyInstaller --noconfirm --clean --onefile --console --name TexTrim_debug --add-binary "texconv.exe;." --exclude-module PySide6.QtNetwork --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick --exclude-module PySide6.QtQuickWidgets --exclude-module PySide6.QtOpenGL --exclude-module PySide6.QtOpenGLWidgets --exclude-module PySide6.QtSql --exclude-module PySide6.QtSvg --exclude-module PySide6.QtSvgWidgets --exclude-module PySide6.QtPrintSupport --exclude-module PySide6.QtTest --exclude-module PySide6.QtDBus --exclude-module PySide6.QtXml --exclude-module PySide6.QtConcurrent --exclude-module PySide6.QtWebEngineCore --exclude-module PySide6.QtPdf textrim_qt.py || goto :fail

echo.
for %%A in (dist\TexTrim_debug.exe) do echo SUCCESS: dist\TexTrim_debug.exe  (%%~zA bytes)
if not defined CI pause
exit /b 0

:fail
echo.
echo BUILD FAILED - read the messages above.
if not defined CI pause
exit /b 1
