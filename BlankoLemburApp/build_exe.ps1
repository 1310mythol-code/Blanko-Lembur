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

$pythonRoot = (& $buildPython -c 'import sys; print(sys.base_prefix)').Trim()
$tclData = Join-Path $pythonRoot 'tcl\tcl8.6'
$tkData = Join-Path $pythonRoot 'tcl\tk8.6'
$tkinterBinary = Join-Path $pythonRoot 'DLLs\_tkinter.pyd'
$tclBinary = Join-Path $pythonRoot 'DLLs\tcl86t.dll'
$tkBinary = Join-Path $pythonRoot 'DLLs\tk86t.dll'
$zlibBinary = Join-Path $pythonRoot 'DLLs\zlib1.dll'
$runtimeHook = Join-Path $buildDir 'venv\Lib\site-packages\PyInstaller\hooks\rthooks\pyi_rth__tkinter.py'
$customHooks = Join-Path $appDir 'packaging\pyinstaller_hooks'
foreach ($path in @($tclData, $tkData, $tkinterBinary, $tclBinary, $tkBinary, $zlibBinary, $runtimeHook, $customHooks)) {
    if (-not (Test-Path -LiteralPath $path)) { throw "Komponen Tkinter tidak ditemukan: $path" }
}

# Some Python installations have all Tcl/Tk runtime files but cannot open a
# local Tk window during the build. Bundle those verified files explicitly.
& $buildPython -c 'import _tkinter'
if ($LASTEXITCODE -ne 0) { throw 'Modul _tkinter tidak dapat dimuat.' }

$env:PYINSTALLER_CONFIG_DIR = Join-Path $buildDir 'cache'
& $buildPython -m PyInstaller --noconfirm --clean --onefile --windowed --noupx `
    --name 'Blanko Lembur Otomatis' `
    --additional-hooks-dir $customHooks `
    --runtime-hook $runtimeHook `
    --add-data ((Join-Path $appDir 'blanko_template.docx') + ':.') `
    --add-data ((Join-Path $appDir 'REKAP LEMBUR BULAN.docx') + ':.') `
    --add-data ($tclData + ':_tcl_data') `
    --add-data ($tkData + ':_tk_data') `
    --add-binary ($tkinterBinary + ':.') `
    --add-binary ($tclBinary + ':.') `
    --add-binary ($tkBinary + ':.') `
    --add-binary ($zlibBinary + ':.') `
    --distpath $OutputDirectory --workpath (Join-Path $buildDir 'work') `
    --specpath $buildDir (Join-Path $appDir 'blanko_lembur.py')
if ($LASTEXITCODE -ne 0) { throw 'Pembuatan EXE gagal.' }

& $buildPython (Join-Path $appDir 'packaging\verify_bundle.py') (Join-Path $OutputDirectory 'Blanko Lembur Otomatis.exe')
if ($LASTEXITCODE -ne 0) { throw 'Pemeriksaan isi EXE gagal.' }

Write-Host "Selesai. Cukup salin satu file: $(Join-Path $OutputDirectory 'Blanko Lembur Otomatis.exe')"
