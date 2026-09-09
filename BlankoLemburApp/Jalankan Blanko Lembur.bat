@echo off
cd /d "%~dp0"

where pyw >nul 2>nul
if %errorlevel%==0 (
    start "" /b pyw -3 "%~dp0blanko_lembur.py"
    exit /b
)

where pythonw >nul 2>nul
if %errorlevel%==0 (
    start "" /b pythonw "%~dp0blanko_lembur.py"
    exit /b
)

echo Python tidak ditemukan.
echo Pastikan Python dan Tcl/Tk sudah terpasang, lalu coba lagi.
pause
