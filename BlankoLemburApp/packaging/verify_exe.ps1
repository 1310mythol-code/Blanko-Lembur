<#
Run from an interactive Windows desktop after the one-file build completes:
  powershell -NoProfile -ExecutionPolicy Bypass -File .\verify_exe.ps1 -ExePath C:\path\BlankoLembur.exe

Only the EXE is copied into the test application's directory. All generated
data, extraction files, reports and automation scripts stay in a unique folder
inside the workspace. The EXE is not modified. Synthetic data is used only in
the isolated LOCALAPPDATA directory. The test briefly opens application windows
and uses normal Win32 mouse/keyboard input to save a DOCX. Do not operate the
test windows while it runs. Python is needed by this developer test driver,
not by the distributed EXE. This is not a substitute for a separate clean VM.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ExePath,
    [string]$AutomationPython = 'C:\Users\user\AppData\Local\Python\pythoncore-3.14-64\python.exe'
)

$ErrorActionPreference = 'Stop'
$resolvedExe = (Resolve-Path -LiteralPath $ExePath).Path
if ([IO.Path]::GetExtension($resolvedExe) -ne '.exe') { throw 'ExePath must name an EXE.' }
if (-not (Test-Path -LiteralPath $AutomationPython -PathType Leaf)) { throw 'The test automation Python runtime was not found.' }
$verificationWorkspace = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..'))
$verificationRoot = [IO.Path]::GetFullPath((Join-Path $verificationWorkspace ('.packaging-verification\run-' + [Guid]::NewGuid().ToString('N'))))
if (-not $verificationRoot.StartsWith($verificationWorkspace.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Test folder must remain inside the workspace.' }
New-Item -ItemType Directory -Path $verificationRoot | Out-Null
$driverPath = Join-Path $verificationRoot 'verify_driver.py'
$driverSource = @'
from __future__ import annotations
import ctypes as C
from ctypes import wintypes as W
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET
import zipfile

source = Path(sys.argv[1]).resolve()
root = Path(sys.argv[2]).resolve()
app_dir = root / 'application'
app_dir.mkdir()
exe = app_dir / source.name
shutil.copy2(source, exe)
local = root / 'localappdata'
temp = root / 'temp'
local.mkdir()
temp.mkdir()
data = local / 'BlankoLemburOtomatis'
output = root / 'Smoke Test - Blanko Lembur.docx'
monthly_output = root / 'Smoke Test - Rekap Bulanan.docx'
report = {'exe': str(exe), 'sha256': hashlib.sha256(exe.read_bytes()).hexdigest(),
          'scratch': str(root), 'checks': [], 'modules': [], 'success': False}

user32 = C.WinDLL('user32', use_last_error=True)
kernel32 = C.WinDLL('kernel32', use_last_error=True)
try:
    user32.SetProcessDPIAware()
except AttributeError:
    pass
ULONG_PTR = W.WPARAM
WNDENUMPROC = C.WINFUNCTYPE(W.BOOL, W.HWND, W.LPARAM)

class PROCESSENTRY32W(C.Structure):
    _fields_ = [('dwSize', W.DWORD), ('cntUsage', W.DWORD), ('th32ProcessID', W.DWORD),
                ('th32DefaultHeapID', ULONG_PTR), ('th32ModuleID', W.DWORD),
                ('cntThreads', W.DWORD), ('th32ParentProcessID', W.DWORD),
                ('pcPriClassBase', W.LONG), ('dwFlags', W.DWORD), ('szExeFile', W.WCHAR * 260)]

class MODULEENTRY32W(C.Structure):
    _fields_ = [('dwSize', W.DWORD), ('th32ModuleID', W.DWORD), ('th32ProcessID', W.DWORD),
                ('GlblcntUsage', W.DWORD), ('ProccntUsage', W.DWORD), ('modBaseAddr', C.c_void_p),
                ('modBaseSize', W.DWORD), ('hModule', W.HMODULE),
                ('szModule', W.WCHAR * 256), ('szExePath', W.WCHAR * 260)]

class KEYBDINPUT(C.Structure):
    _fields_ = [('wVk', W.WORD), ('wScan', W.WORD), ('dwFlags', W.DWORD),
                ('time', W.DWORD), ('dwExtraInfo', ULONG_PTR)]

class MOUSEINPUT(C.Structure):
    _fields_ = [('dx', W.LONG), ('dy', W.LONG), ('mouseData', W.DWORD),
                ('dwFlags', W.DWORD), ('time', W.DWORD), ('dwExtraInfo', ULONG_PTR)]

class INPUTUNION(C.Union):
    _fields_ = [('ki', KEYBDINPUT), ('mi', MOUSEINPUT)]

class INPUT(C.Structure):
    _anonymous_ = ('u',)
    _fields_ = [('type', W.DWORD), ('u', INPUTUNION)]

kernel32.CreateToolhelp32Snapshot.argtypes = [W.DWORD, W.DWORD]
kernel32.CreateToolhelp32Snapshot.restype = W.HANDLE
kernel32.Process32FirstW.argtypes = [W.HANDLE, C.POINTER(PROCESSENTRY32W)]
kernel32.Process32NextW.argtypes = [W.HANDLE, C.POINTER(PROCESSENTRY32W)]
kernel32.Module32FirstW.argtypes = [W.HANDLE, C.POINTER(MODULEENTRY32W)]
kernel32.Module32NextW.argtypes = [W.HANDLE, C.POINTER(MODULEENTRY32W)]
kernel32.CloseHandle.argtypes = [W.HANDLE]
kernel32.OpenProcess.argtypes = [W.DWORD, W.BOOL, W.DWORD]
kernel32.OpenProcess.restype = W.HANDLE
kernel32.TerminateProcess.argtypes = [W.HANDLE, W.UINT]
user32.EnumWindows.argtypes = [WNDENUMPROC, W.LPARAM]
user32.EnumChildWindows.argtypes = [W.HWND, WNDENUMPROC, W.LPARAM]
user32.GetWindowThreadProcessId.argtypes = [W.HWND, C.POINTER(W.DWORD)]
user32.GetWindowTextW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
user32.GetClassNameW.argtypes = [W.HWND, W.LPWSTR, C.c_int]
user32.IsWindowVisible.argtypes = [W.HWND]
user32.GetForegroundWindow.restype = W.HWND
user32.SetForegroundWindow.argtypes = [W.HWND]
user32.ShowWindow.argtypes = [W.HWND, C.c_int]
user32.GetClientRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
user32.GetWindowRect.argtypes = [W.HWND, C.POINTER(W.RECT)]
user32.ClientToScreen.argtypes = [W.HWND, C.POINTER(W.POINT)]
user32.WindowFromPoint.argtypes = [W.POINT]
user32.WindowFromPoint.restype = W.HWND
user32.PostMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
user32.SetWindowTextW.argtypes = [W.HWND, W.LPCWSTR]
user32.SendMessageW.argtypes = [W.HWND, W.UINT, W.WPARAM, W.LPARAM]
user32.SendMessageW.restype = W.LPARAM
user32.GetDlgCtrlID.argtypes = [W.HWND]
user32.SendInput.argtypes = [W.UINT, C.POINTER(INPUT), C.c_int]
user32.SendInput.restype = W.UINT

def screenshot(hwnd, name):
    """Capture only the test window, for diagnosing desktop/DPI differences."""
    gdi32 = C.WinDLL('gdi32', use_last_error=True)
    user32.GetWindowDC.argtypes = [W.HWND]
    user32.GetWindowDC.restype = W.HDC
    user32.ReleaseDC.argtypes = [W.HWND, W.HDC]
    gdi32.CreateCompatibleDC.argtypes = [W.HDC]
    gdi32.CreateCompatibleDC.restype = W.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [W.HDC, C.c_int, C.c_int]
    gdi32.CreateCompatibleBitmap.restype = W.HBITMAP
    gdi32.SelectObject.argtypes = [W.HDC, W.HANDLE]
    gdi32.SelectObject.restype = W.HANDLE
    gdi32.BitBlt.argtypes = [W.HDC, C.c_int, C.c_int, C.c_int, C.c_int, W.HDC, C.c_int, C.c_int, W.DWORD]
    gdi32.GetDIBits.argtypes = [W.HDC, W.HBITMAP, W.UINT, W.UINT, C.c_void_p, C.c_void_p, W.UINT]
    gdi32.DeleteObject.argtypes = [W.HANDLE]
    gdi32.DeleteDC.argtypes = [W.HDC]
    rect = W.RECT()
    user32.GetWindowRect(hwnd, C.byref(rect))
    width, height = rect.right - rect.left, rect.bottom - rect.top
    dc = user32.GetWindowDC(hwnd)
    memory = gdi32.CreateCompatibleDC(dc)
    bitmap = gdi32.CreateCompatibleBitmap(dc, width, height)
    old = gdi32.SelectObject(memory, bitmap)
    try:
        gdi32.BitBlt(memory, 0, 0, width, height, dc, 0, 0, 0x00CC0020)
        gdi32.SelectObject(memory, old)
        size = width * height * 4
        info = C.create_string_buffer(struct.pack('<IiiHHIIiiII', 40, width, height, 1, 32, 0, size, 0, 0, 0, 0))
        pixels = C.create_string_buffer(size)
        if gdi32.GetDIBits(memory, bitmap, 0, height, pixels, info, 0):
            (root / name).write_bytes(struct.pack('<2sIHHI', b'BM', 54 + size, 0, 0, 54) + info.raw[:40] + pixels.raw)
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory)
        user32.ReleaseDC(hwnd, dc)

def wait_for(fn, label, timeout=20):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        result = fn()
        if result:
            return result
        time.sleep(0.15)
    raise RuntimeError('Timed out: ' + label)

def process_map():
    snapshot = kernel32.CreateToolhelp32Snapshot(2, 0)
    if snapshot == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    result = {}
    entry = PROCESSENTRY32W()
    entry.dwSize = C.sizeof(entry)
    try:
        ok = kernel32.Process32FirstW(snapshot, C.byref(entry))
        while ok:
            result[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile)
            ok = kernel32.Process32NextW(snapshot, C.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return result

def descendants(parent):
    items = process_map()
    result = {parent}
    while True:
        added = {pid for pid, (ppid, _) in items.items() if ppid in result} - result
        if not added:
            return result
        result |= added

def owner(hwnd):
    pid = W.DWORD()
    user32.GetWindowThreadProcessId(hwnd, C.byref(pid))
    return pid.value

def window_text(hwnd):
    buf = C.create_unicode_buffer(2048)
    user32.GetWindowTextW(hwnd, buf, len(buf))
    return buf.value

def control_text(hwnd):
    buf = C.create_unicode_buffer(2048)
    user32.SendMessageW(hwnd, 0x000D, len(buf), C.addressof(buf))
    return buf.value

def windows(pids, title=None, parent=None, visible_only=True):
    result = []
    @WNDENUMPROC
    def visit(hwnd, _):
        if owner(hwnd) in pids and (not visible_only or user32.IsWindowVisible(hwnd)):
            text = window_text(hwnd)
            if title is None or title in text:
                result.append(hwnd)
        return True
    if parent is None:
        user32.EnumWindows(visit, 0)
    else:
        user32.EnumChildWindows(parent, visit, 0)
    return result

def module_paths(pid):
    snapshot = kernel32.CreateToolhelp32Snapshot(0x08 | 0x10, pid)
    if snapshot == C.c_void_p(-1).value:
        raise C.WinError(C.get_last_error())
    entry = MODULEENTRY32W()
    entry.dwSize = C.sizeof(entry)
    result = []
    try:
        ok = kernel32.Module32FirstW(snapshot, C.byref(entry))
        while ok:
            result.append(entry.szExePath)
            ok = kernel32.Module32NextW(snapshot, C.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)
    return result

def assert_bundled_modules(hwnd):
    paths = module_paths(owner(hwnd))
    report['modules'] = paths
    required = [p for p in paths if re.match(r'^(python\d+(?:t)?\.dll|_tkinter\.pyd|tcl\d+.*\.dll|tk\d+.*\.dll)$', Path(p).name, re.I)]
    names = [Path(p).name.lower() for p in required]
    for prefix in ('python', '_tkinter', 'tcl', 'tk'):
        if not any(name.startswith(prefix) for name in names):
            raise AssertionError('Missing loaded runtime module: ' + prefix)
    for path in required:
        if not Path(path).resolve().is_relative_to(temp):
            raise AssertionError('Runtime module loaded outside isolated extraction directory: ' + path)
    report['checks'].append('Python, Tkinter, Tcl and Tk DLLs loaded from isolated one-file extraction')

environment = os.environ.copy()
for key in list(environment):
    if key.upper().startswith(('PYTHON', '_PYI', 'PYINSTALLER')) or key.upper() in ('TCL_LIBRARY', 'TK_LIBRARY'):
        environment.pop(key)
environment.update(LOCALAPPDATA=str(local), TEMP=str(temp), TMP=str(temp),
                   PATH=os.pathsep.join((str(Path(os.environ['SystemRoot']) / 'System32'), os.environ['SystemRoot'])))
report['isolated_environment'] = {key: environment[key] for key in ('LOCALAPPDATA', 'TEMP', 'TMP', 'PATH')}
active = None
pids = set()

def launch():
    global active, pids
    startup = subprocess.STARTUPINFO()
    startup.dwFlags = subprocess.STARTF_USESHOWWINDOW
    startup.wShowWindow = 0
    active = subprocess.Popen([str(exe)], cwd=app_dir, env=environment, startupinfo=startup)
    def main_window():
        global pids
        pids = descendants(active.pid)
        matches = windows(pids, 'Blanko Lembur Otomatis', visible_only=False)
        return matches[0] if matches else None
    hwnd = wait_for(main_window, 'application main window', timeout=45)
    user32.ShowWindow(hwnd, 9)
    time.sleep(0.5)
    print('Launched test application: ' + str({'parent_pid': active.pid, 'pids': sorted(pids), 'hwnd': hwnd}), flush=True)
    return hwnd

def close():
    global active, pids
    if active is None:
        return
    pids |= descendants(active.pid)
    for hwnd in windows(pids):
        user32.PostMessageW(hwnd, 0x0010, 0, 0)
    try:
        active.wait(timeout=10)
    except subprocess.TimeoutExpired:
        # The PIDs are restricted to this invocation and its own descendants.
        for pid in pids:
            handle = kernel32.OpenProcess(1, False, pid)
            if handle:
                kernel32.TerminateProcess(handle, 1)
                kernel32.CloseHandle(handle)
        active.wait(timeout=10)
        raise RuntimeError('Application did not close normally')
    finally:
        active = None
        pids = set()

def foreground(hwnd):
    if owner(hwnd) not in pids:
        raise RuntimeError('Refusing input to a window outside the test application')
    user32.ShowWindow(hwnd, 9)
    user32.SetForegroundWindow(hwnd)
    wait_for(lambda: user32.GetForegroundWindow() == hwnd, 'test window foreground', timeout=5)

def click(hwnd, x, y):
    foreground(hwnd)
    point = W.POINT(round(x), round(y))
    user32.ClientToScreen(hwnd, C.byref(point))
    target = user32.WindowFromPoint(point)
    if owner(target) not in pids:
        raise RuntimeError('Refusing to click outside the test application')
    user32.SetCursorPos(point.x, point.y)
    user32.mouse_event(2, 0, 0, 0, 0)
    user32.mouse_event(4, 0, 0, 0, 0)
    time.sleep(0.35)

def client_size(hwnd):
    rect = W.RECT()
    user32.GetClientRect(hwnd, C.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top

def key(hwnd, vk):
    foreground(hwnd)
    seq = (INPUT * 2)(INPUT(type=1, ki=KEYBDINPUT(wVk=vk)),
                      INPUT(type=1, ki=KEYBDINPUT(wVk=vk, dwFlags=2)))
    if user32.SendInput(2, seq, C.sizeof(INPUT)) != 2:
        raise C.WinError(C.get_last_error())

def save_from_gui(hwnd):
    foreground(hwnd)
    screenshot(hwnd, 'before-preview.bmp')
    width, height = client_size(hwnd)
    print('Main client size: ' + str((width, height)), flush=True)
    click(hwnd, width * 0.83, height - 108)
    preview = wait_for(lambda: next(iter(windows(pids, 'Preview Word - September 2026')), None), 'Word preview')
    foreground(preview)
    screenshot(preview, 'word-preview.bmp')
    width, height = client_size(preview)
    click(preview, width - 120, height - 40)
    dialog = wait_for(lambda: next(iter(windows(pids, 'Simpan Word Blanko Lembur')), None), 'Word save dialog')
    complete_save(dialog, output, 'Blanko Lembur - September 2026', 'Word siap dicetak')
    report['checks'].append('Actual daily preview and Save As generated DOCX')

def complete_save(dialog, target_path, initial_name, success_title):
    foreground(dialog)
    screenshot(dialog, 'save-dialog.bmp')
    report['save_controls'] = []
    for child in windows(pids, parent=dialog):
        cls = C.create_unicode_buffer(128)
        user32.GetClassNameW(child, cls, len(cls))
        if cls.value == 'Edit':
            report['save_controls'].append({'hwnd':child, 'class':cls.value,
                'id':user32.GetDlgCtrlID(child), 'text':control_text(child)})
    def filename_edit():
        for child in windows(pids, parent=dialog):
            cls = C.create_unicode_buffer(128)
            user32.GetClassNameW(child, cls, len(cls))
            if cls.value == 'Edit' and control_text(child).startswith(initial_name):
                return child
        return None
    edit = wait_for(filename_edit, 'native filename edit control')
    # Native Save As keeps its own filename state; send actual typing so its
    # change notification runs, instead of only replacing the control text.
    edit_rect = W.RECT()
    user32.GetWindowRect(edit, C.byref(edit_rect))
    origin = W.POINT(0, 0)
    user32.ClientToScreen(dialog, C.byref(origin))
    click(dialog, edit_rect.left - origin.x + 15, edit_rect.top - origin.y + 10)
    select_all = (INPUT * 4)(
        INPUT(type=1, ki=KEYBDINPUT(wVk=0x11)),
        INPUT(type=1, ki=KEYBDINPUT(wVk=0x41)),
        INPUT(type=1, ki=KEYBDINPUT(wVk=0x41, dwFlags=2)),
        INPUT(type=1, ki=KEYBDINPUT(wVk=0x11, dwFlags=2)))
    if user32.SendInput(4, select_all, C.sizeof(INPUT)) != 4:
        raise C.WinError(C.get_last_error())
    for char in str(target_path):
        typed = (INPUT * 2)(INPUT(type=1, ki=KEYBDINPUT(wScan=ord(char), dwFlags=4)),
                            INPUT(type=1, ki=KEYBDINPUT(wScan=ord(char), dwFlags=6)))
        if user32.SendInput(2, typed, C.sizeof(INPUT)) != 2:
            raise C.WinError(C.get_last_error())
        time.sleep(0.01)
    wait_for(lambda: control_text(edit) == str(target_path), 'complete output filename', timeout=8)
    screenshot(dialog, 'save-dialog-typed.bmp')
    report['typed_filename'] = control_text(edit)
    if control_text(edit) != str(target_path):
        raise AssertionError('Unexpected typed filename: ' + control_text(edit))
    time.sleep(0.25)
    key(dialog, 0x0D)
    wait_for(lambda: target_path.exists(), 'generated DOCX')
    success = wait_for(lambda: next(iter(windows(pids, success_title)), None), 'Word success message')
    key(success, 0x0D)
    report['checks'].append(success_title + ': native Save As succeeded')

def save_monthly_from_gui(hwnd):
    width, height = client_size(hwnd)
    click(hwnd, width * 0.83, height - 64)
    dialog = wait_for(lambda: next(iter(windows(pids, 'Simpan Rekap Lembur Bulanan')), None), 'Monthly save dialog')
    complete_save(dialog, monthly_output, 'Rekap Lembur Bulan September 2026', 'Rekap bulanan selesai')

def write_csv(filename, fields, rows):
    with (data / filename).open('w', encoding='utf-8-sig', newline='') as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter=';', lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)

def data_hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(data.glob('*.csv'))}

def seed():
    write_csv('profil.csv', ['nama', 'nip', 'unit_kerja', 'bulan'],
              [dict(nama='Pegawai Uji EXE', nip='123456789012345678', unit_kerja='Unit Verifikasi EXE', bulan='September 2026')])
    write_csv('pejabat.csv', ['nama_manager', 'nip_manager', 'nama_asmen', 'nip_asmen', 'manager_unit_override', 'asmen_unit_override'],
              [dict(nama_manager='Manajer Uji EXE', nip_manager='', nama_asmen='Asmen Uji EXE', nip_asmen='', manager_unit_override='Pelayanan Khusus', asmen_unit_override='')])
    fields = ['blanko_id', 'urutan', 'tanggal', 'jam_mulai', 'jam_selesai', 'pekerjaan', 'kuantitas', 'keterangan']
    rows = [dict(blanko_id=f'2026-09-0{day}', urutan='1', tanggal=f'2026-09-0{day}',
                 jam_mulai='16:00', jam_selesai='20:00', pekerjaan=f'Pekerjaan Uji EXE {day}',
                 kuantitas=str(day), keterangan=f'Catatan Uji {day}') for day in (1, 2)]
    rows.insert(1, dict(rows[0], urutan='2', pekerjaan='Pekerjaan Tambahan EXE', kuantitas='3'))
    write_csv('lembur_records.csv', fields, rows)

def verify_docx():
    with zipfile.ZipFile(output) as archive:
        if archive.testzip() is not None:
            raise AssertionError('DOCX ZIP integrity failed')
        document = ET.fromstring(archive.read('word/document.xml'))
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        text = '\n'.join(node.text or '' for node in document.findall('.//w:t', ns))
        for expected in ('Pegawai Uji EXE', '123456789012345678', 'Unit Verifikasi EXE',
                         'Manajer Uji EXE', 'Asmen Uji EXE', 'Pekerjaan Uji EXE 1',
                         'Pekerjaan Uji EXE 2', '1 September 2026', '2 September 2026',
                         'Manajer Pelayanan Khusus', 'Asisten Manajer Unit Verifikasi EXE'):
            if expected not in text:
                raise AssertionError('Missing generated document text: ' + expected)
        breaks = [node for node in document.findall('.//w:br', ns) if node.get('{'+ns['w']+'}type') == 'page']
        if len(breaks) != 1:
            raise AssertionError('Two records should generate exactly one separating page break')
        tables = document.findall('.//w:body/w:tbl', ns)
        for signature_table in (tables[2], tables[5]):
            nip_cells = signature_table.findall('w:tr', ns)[6].findall('w:tc', ns)
            for cell in (nip_cells[0], nip_cells[2]):
                if ''.join(node.text or '' for node in cell.findall('.//w:t', ns)).strip():
                    raise AssertionError('Empty official NIP must produce a blank signature line')
        report['checks'].append('Blank official NIPs export without NIP labels; manager uses manual role; assistant follows Unit Kerja')
    report['docx'] = str(output)
    report['checks'].append('DOCX ZIP and XML valid; both dates, employee and officials present; one page break')

def verify_monthly_docx():
    with zipfile.ZipFile(monthly_output) as archive:
        assert archive.testzip() is None
        ns = {'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
        doc = ET.fromstring(archive.read('word/document.xml'))
        tables = doc.findall('.//w:body/w:tbl', ns)
        text = '\n'.join(n.text or '' for n in doc.findall('.//w:t', ns))
        for expected in ('SEPTEMBER 2026', 'Pegawai Uji EXE', 'Manajer Pelayanan Khusus', 'Asisten Manajer Unit Verifikasi EXE'):
            assert expected in text, expected
        rows = tables[1].findall('w:tr', ns)
        values = [[''.join(n.text or '' for n in cell.findall('.//w:t', ns)) for cell in row.findall('w:tc', ns)] for row in rows[1:]]
        assert values[:3] == [
            ['1', '01/09/2026', 'Pekerjaan Uji EXE 1', '1', '16.00-20.00'],
            ['2', '01/09/2026', 'Pekerjaan Tambahan EXE', '3', '16.00-20.00'],
            ['3', '02/09/2026', 'Pekerjaan Uji EXE 2', '2', '16.00-20.00']
        ], values[:3]
        assert all(not value.strip() for row in values[3:] for value in row)
        assert not doc.findall('.//w:highlight', ns)
    report['monthly_docx'] = str(monthly_output)
    report['checks'].append('Monthly button exports separate Word; date/time repeat per job; unused rows blank; no highlights')

try:
    main = launch()
    wait_for(lambda: all((data / filename).exists() for filename in ('profil.csv', 'pejabat.csv', 'lembur_records.csv')), 'first-run data files')
    assert_bundled_modules(main)
    close()
    report['checks'].append('Clean first launch initialized its own isolated data and closed normally')
    seed()
    before = data_hashes()
    main = launch()
    save_from_gui(main)
    verify_docx()
    save_monthly_from_gui(main)
    verify_monthly_docx()
    close()
    main = launch()
    close()
    if data_hashes() != before:
        raise AssertionError('Stored synthetic data changed after restart')
    report['checks'].append('Profile, officials and overtime CSV data persisted through two subsequent launches')
    if sorted(p.name for p in app_dir.iterdir()) != [exe.name]:
        raise AssertionError('Application created companion files beside the EXE')
    report['checks'].append('Application directory still contains exactly one EXE and no companion files')
    report['success'] = True
except Exception:
    report['error'] = traceback.format_exc()
    report['remaining_windows'] = [{'hwnd': h, 'title': window_text(h), 'pid': owner(h)} for h in windows(pids)]
    report['active_process_exit'] = active.poll() if active else None
finally:
    try:
        close()
    except Exception:
        report['cleanup_error'] = traceback.format_exc()
        report['success'] = False
    (root / 'verification.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))
sys.exit(0 if report['success'] else 1)
'@
[IO.File]::WriteAllText($driverPath, $driverSource, [Text.UTF8Encoding]::new($false))
Write-Output ('Verification artifacts: ' + $verificationRoot)
& $AutomationPython $driverPath $resolvedExe $verificationRoot
if ($LASTEXITCODE -ne 0) { throw ('EXE verification failed. Inspect ' + (Join-Path $verificationRoot 'verification.json')) }
