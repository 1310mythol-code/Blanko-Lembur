"""Verify the one-file distribution; requires the build environment only."""
import hashlib
import json
import sys
from pathlib import Path

import pefile
from PyInstaller.archive.readers import CArchiveReader


def verify(executable: Path) -> dict:
    archive = CArchiveReader(str(executable))
    entries = set(archive.toc)
    required = {
        'blanko_lembur', 'blanko_template.docx', 'REKAP LEMBUR BULAN.docx', 'PYZ.pyz',
        '_tkinter.pyd', 'VCRUNTIME140.dll', 'zlib1.dll',
        '_tcl_data\\init.tcl', '_tk_data\\tk.tcl', '_tk_data\\ttk\\ttk.tcl',
    }
    assert required <= entries, f'Missing embedded files: {required - entries}'
    assert any(n.startswith('python3') and n.endswith('.dll') for n in entries)
    assert any(n.startswith('tcl') and n.endswith('.dll') for n in entries)
    assert any(n.startswith('tk') and n.endswith('.dll') for n in entries)
    assert not any(n.endswith('.csv') for n in entries), 'User CSV must stay separate from application code'
    modules = set(archive.open_embedded_archive('PYZ.pyz').toc)
    required_modules = {'core', 'recap', 'app_metadata', 'updater',
                        'cryptography.hazmat.primitives.asymmetric.ed25519',
                        'tkinter', 'tkinter.ttk', 'tkinter.filedialog',
                        'tkinter.messagebox', 'zipfile', 'xml.dom.minidom', 'csv'}
    assert required_modules <= modules, f'Missing modules: {required_modules - modules}'
    template = Path(__file__).resolve().parents[1] / 'blanko_template.docx'
    assert archive.extract('blanko_template.docx') == template.read_bytes()
    assert archive.extract('REKAP LEMBUR BULAN.docx') == (template.parent / 'REKAP LEMBUR BULAN.docx').read_bytes()

    pe = pefile.PE(str(executable))
    assert pe.FILE_HEADER.Machine == 0x8664, 'Expected Windows x64'
    assert pe.OPTIONAL_HEADER.Subsystem == 2, 'Expected GUI application without console'

    windows_libraries = {
        'kernel32.dll', 'user32.dll', 'gdi32.dll', 'advapi32.dll', 'shell32.dll',
        'ole32.dll', 'oleaut32.dll', 'comdlg32.dll', 'comctl32.dll', 'imm32.dll',
        'version.dll', 'ws2_32.dll', 'iphlpapi.dll', 'rpcrt4.dll', 'crypt32.dll',
        'bcrypt.dll', 'netapi32.dll', 'userenv.dll', 'msvcrt.dll', 'ntdll.dll',
        'ncrypt.dll', 'bcryptprimitives.dll', 'propsys.dll',
    }
    bundled_libraries = {n.lower() for n in entries if n.lower().endswith(('.dll', '.pyd'))}
    binaries = [(executable.name, pe)] + [
        (name, pefile.PE(data=archive.extract(name)))
        for name in entries if name.lower().endswith(('.dll', '.pyd'))
    ]
    missing_dependencies = []
    for name, binary in binaries:
        for imported in getattr(binary, 'DIRECTORY_ENTRY_IMPORT', []):
            dependency = imported.dll.decode('ascii').lower()
            if not (dependency in bundled_libraries or dependency in windows_libraries
                    or dependency.startswith(('api-ms-win-', 'ext-ms-win-'))):
                missing_dependencies.append((name, dependency))
    assert not missing_dependencies, missing_dependencies

    return {'status': 'PASS', 'executable': executable.name,
            'size_bytes': executable.stat().st_size,
            'sha256': hashlib.sha256(executable.read_bytes()).hexdigest(),
            'platform': 'Windows x64', 'console_window': False,
            'template_matches_source': True, 'python_and_tk_embedded': True,
            'non_system_dll_dependencies_bundled': True, 'user_csv_embedded': False}


if __name__ == '__main__':
    print(json.dumps(verify(Path(sys.argv[1]).resolve()), indent=2))
