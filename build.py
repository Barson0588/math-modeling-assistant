#!/usr/bin/env python3
"""One-command build script for Math Modeling Assistant desktop app.

Usage:
    python build.py           # Build for current platform
    python build.py --clean   # Clean previous builds first

Output:
    dist/MathModelingAssistant.exe     (Windows)
    dist/MathModelingAssistant.app     (macOS)
"""

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP_NAME = "MathModelingAssistant"
DIST = ROOT / "dist"
BUILD = ROOT / "build"


def clean():
    """Remove previous build artifacts."""
    for d in [BUILD, DIST]:
        if d.exists():
            shutil.rmtree(d)
            print(f"  Cleaned {d.name}/")
    for spec in ROOT.glob("*.spec"):
        pass  # Keep spec files


def build_windows():
    """Build Windows .exe using PyInstaller."""
    spec = ROOT / "win_build.spec"
    if not spec.exists():
        print(f"ERROR: {spec} not found")
        sys.exit(1)
    print("[1/2] Running PyInstaller for Windows...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
         "--distpath", str(DIST), "--workpath", str(BUILD), str(spec)],
        cwd=str(ROOT), capture_output=False,
    )
    if result.returncode != 0:
        print("ERROR: PyInstaller build failed")
        sys.exit(1)

    exe = DIST / APP_NAME / f"{APP_NAME}.exe"
    if exe.exists():
        size_mb = exe.stat().st_size / (1024 * 1024)
        print(f"  OK {exe.relative_to(ROOT)} ({size_mb:.1f} MB)")
    else:
        print("WARNING: .exe not found at expected path")


def build_macos():
    """Build macOS .app using PyInstaller."""
    spec = ROOT / "mac_build.spec"
    if not spec.exists():
        print(f"ERROR: {spec} not found")
        sys.exit(1)
    print("[1/2] Running PyInstaller for macOS...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "--clean", "--noconfirm",
         "--distpath", str(DIST), "--workpath", str(BUILD), str(spec)],
        cwd=str(ROOT), capture_output=False,
    )
    if result.returncode != 0:
        print("ERROR: PyInstaller build failed")
        sys.exit(1)

    app = DIST / f"{APP_NAME}.app"
    if app.exists():
        print(f"  OK {app.relative_to(ROOT)}")
    else:
        print("WARNING: .app not found at expected path")


def main():
    system = platform.system()
    print(f"=== MMA Desktop Builder ({system}) ===")
    print()

    if "--clean" in sys.argv:
        clean()

    # Ensure PyInstaller is available
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    if system == "Windows":
        build_windows()
    elif system == "Darwin":
        build_macos()
    else:
        print(f"Unsupported platform: {system}")
        print("This build script supports Windows and macOS only.")
        sys.exit(1)

    print()
    print("=== Done ===")
    out = DIST / APP_NAME if system == "Windows" else DIST / f"{APP_NAME}.app"
    print(f"Output: {out}")
    print("To distribute: zip the output folder and share.")


if __name__ == "__main__":
    main()
