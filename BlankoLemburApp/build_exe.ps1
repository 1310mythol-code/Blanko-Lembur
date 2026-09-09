param([string]$Python = 'python', [string]$OutputDirectory = '')

$ErrorActionPreference = 'Stop'
$appDir = $PSScriptRoot
$workspace = Split-Path -Parent $appDir
if (-not $OutputDirectory) { $OutputDirectory = $workspace }
$OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
$buildDir = Join-Path $appDir '.build'
$buildPython = Join-Path $buildDir 'venv\Scripts\python.exe'

# Build dependencies are local to the project, never needed on the target PC.
if (-not (Test-Path -LiteralPath $buildPython)) {
    & $Python -m venv (Join-Path $buildDir 'venv')
    if ($LASTEXITCODE -ne 0) { throw 'Gagal membuat lingkungan build Python.' }
}
& $buildPython -m pip install --disable-pip-version-check 'pyinstaller==6.22.2' 'cryptography==50.0.1'
if ($LASTEXITCODE -ne 0) { throw 'Gagal memasang PyInstaller.' }

& $buildPython -c 'import tkinter; root = tkinter.Tk(); root.withdraw(); root.update_idletasks(); root.destroy()'
if ($LASTEXITCODE -ne 0) { throw 'Tcl/Tk tidak dapat digunakan. Periksa instalasi Python atau izin lingkungan build.' }

$env:PYINSTALLER_CONFIG_DIR = Join-Path $buildDir 'cache'
& $buildPython -m PyInstaller --noconfirm --clean --onefile --windowed --noupx `
    --name 'Blanko Lembur Otomatis' `
    --add-data ((Join-Path $appDir 'blanko_template.docx') + ':.') `
    --add-data ((Join-Path $appDir 'REKAP LEMBUR BULAN.docx') + ':.') `
    --distpath $OutputDirectory --workpath (Join-Path $buildDir 'work') `
    --specpath $buildDir (Join-Path $appDir 'blanko_lembur.py')
if ($LASTEXITCODE -ne 0) { throw 'Pembuatan EXE gagal.' }

& $buildPython (Join-Path $appDir 'packaging\verify_bundle.py') (Join-Path $OutputDirectory 'Blanko Lembur Otomatis.exe')
if ($LASTEXITCODE -ne 0) { throw 'Pemeriksaan isi EXE gagal.' }

Write-Host "Selesai. Cukup salin satu file: $(Join-Path $OutputDirectory 'Blanko Lembur Otomatis.exe')"
