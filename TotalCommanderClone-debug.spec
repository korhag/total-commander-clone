# -*- mode: python ; coding: utf-8 -*-
# Console build for one-shot diagnosis (stderr visible). Run:
#   py -3 -m PyInstaller --noconfirm --clean --distpath dist_build TotalCommanderClone-debug.spec
import os


# ------------------------------------------------------------
# Bundle 7-Zip when it is installed on the build machine.
# SEVENZIP_DIR overrides the default Program Files location.
# ------------------------------------------------------------
def _bundled_sevenzip():
    folders = []
    env_dir = os.environ.get("SEVENZIP_DIR", "")
    if env_dir:
        folders.append(env_dir)
    for key in ("ProgramFiles", "ProgramFiles(x86)"):
        root = os.environ.get(key)
        if root:
            folders.append(os.path.join(root, "7-Zip"))
    for folder in folders:
        exe = os.path.join(folder, "7z.exe")
        dll = os.path.join(folder, "7z.dll")
        if os.path.isfile(exe) and os.path.isfile(dll):
            bundled = [(exe, "7zip"), (dll, "7zip")]
            license_path = os.path.join(folder, "License.txt")
            if os.path.isfile(license_path):
                bundled.append((license_path, "7zip"))
            return bundled
    return []


sevenzip_binaries = _bundled_sevenzip()


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=sevenzip_binaries,
    datas=[('file-explorer.ico', '.'), ('icons', 'icons')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='TotalCommanderClone-debug',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['file-explorer.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='TotalCommanderClone-debug',
)
