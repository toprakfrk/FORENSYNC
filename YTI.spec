# -*- mode: python ; coding: utf-8 -*-
# ForenSync Imager — Windows exe build spec
#
# KULLANIM (proje kök dizininde, yti_fixed/ içinde, venv aktifken):
#   pyinstaller YTI.spec
#
# Bu dosyayı yti_fixed/ klasörünün İÇİNE koyun (main.py ile aynı yere).

import sys
from PyInstaller.utils.hooks import collect_submodules

block_cipher = None

# resources/win altındaki tüm dll + exe dosyalarını exe'nin yanına gömüyoruz
# (ewfacquire.exe, ewfinfo.exe, ewfverify.exe, ewfexport.exe, libewf.dll, zlib.dll)
added_binaries = [
    (r'resources\win\*.dll', 'resources/win'),
    (r'resources\win\*.exe', 'resources/win'),
]

added_datas = [
    # Gerekirse ek statik dosyalar (ikon, lisans metni vs.) buraya eklenebilir.
]

hiddenimports = []
hiddenimports += collect_submodules('PyQt6')

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=added_binaries,
    datas=added_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='YildizlarTakimiImajer',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # False = kara ekran açılmaz, direkt GUI açılır
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=r'resources\win\app_icon.ico',  # yoksa bu satırı silin
)
