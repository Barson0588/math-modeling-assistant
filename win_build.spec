# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for Math Modeling Assistant — Windows .exe build."""

import sys
from pathlib import Path

block_cipher = None

# Project root
ROOT = Path(SPECPATH).resolve()

# Data files
datas = [
    (str(ROOT / "templates"), "templates"),
    (str(ROOT / "static"), "static"),
]

hiddenimports = [
    "flask",
    "flask.cli",
    "flask.json",
    "flask.sessions",
    "jinja2",
    "jinja2.ext",
    "markupsafe",
    "openai",
    "dotenv",
    "src",
    "src.prompts",
    "src.llm_client",
    "src.models_data",
    "src.problems_data",
    "src.guide_data",
    "src.scholar",
]

a = Analysis(
    [str(ROOT / "launcher_win.pyw")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "tkinter",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "PIL",
        "cv2",
        "test",
        "unittest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="MathModelingAssistant",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,   # Hide console window
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="MathModelingAssistant",
)
