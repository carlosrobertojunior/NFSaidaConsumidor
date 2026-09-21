# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_data_files

datas = [
    ('nfce_mg/windows_store.ps1', 'nfce_mg'),
    ('README.md', '.'),
]
datas += collect_data_files('tzdata')
datas += collect_data_files('certifi')

a = Analysis(
    ['app.pyw'], pathex=[], binaries=[], datas=datas, hiddenimports=[],
    hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=['pytest', 'ruff'], noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='NFCeMG', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
)
