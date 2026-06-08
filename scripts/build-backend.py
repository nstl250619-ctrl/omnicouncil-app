#!/usr/bin/env python3
"""Build OmniCouncil backend with PyInstaller for bundling with Tauri."""
import subprocess
import sys
import shutil
from pathlib import Path

ROOT = Path(__file__).parent.parent
BACKEND = ROOT / "backend"
TAURI_RESOURCES = ROOT / "src-tauri" / "resources"
DIST_OUTPUT = BACKEND / "dist" / "omnicouncil-backend"

def build():
    print("=== Building OmniCouncil Backend ===")

    # Clean previous builds
    for d in [BACKEND / "dist", BACKEND / "build"]:
        if d.exists():
            shutil.rmtree(d)
            print(f"Cleaned {d}")

    # Install dependencies
    print("Installing Python dependencies...")
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "-r", str(BACKEND / "requirements.txt"), "pyinstaller", "-q"],
        check=True,
    )
    # Install engine packages (required by main.py imports)
    # Core first — all other engine packages depend on it
    core_dir = BACKEND / "packages" / "omnicounci1l-core"
    if (core_dir / "pyproject.toml").exists():
        print(f"  Installing engine package: {core_dir.name}")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", str(core_dir), "-q"],
            check=True,
        )
    for pkg_dir in sorted((BACKEND / "packages").iterdir()):
        if not (pkg_dir / "pyproject.toml").exists() or pkg_dir.name == "omnicounci1l-core":
            continue
        print(f"  Installing engine package: {pkg_dir.name}")
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", str(pkg_dir), "-q"],
            check=True,
        )
    print("Engine packages installed.")

    # Run PyInstaller
    print("Running PyInstaller...")
    subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(BACKEND / "build.spec"),
         "--distpath", str(BACKEND / "dist"),
         "--workpath", str(BACKEND / "build"),
         "--noconfirm"],
        check=True,
        cwd=str(BACKEND),
    )

    # Copy to Tauri resources
    if TAURI_RESOURCES.exists():
        shutil.rmtree(TAURI_RESOURCES)
    TAURI_RESOURCES.mkdir(parents=True)

    dest = TAURI_RESOURCES / "backend"
    shutil.copytree(DIST_OUTPUT, dest)
    print(f"Copied backend to {dest}")

    # Verify
    exe_name = "omnicouncil-backend.exe" if sys.platform == "win32" else "omnicouncil-backend"
    exe_path = dest / exe_name
    if exe_path.exists():
        size_mb = exe_path.stat().st_size / 1024 / 1024
        print(f"[OK] Backend built: {exe_path} ({size_mb:.1f}MB)")
    else:
        print(f"[WARN] Backend executable not found at {exe_path}")
        # List what's in the dist directory
        for f in dest.iterdir():
            print(f"  {f.name}")

    print("=== Build Complete ===")

if __name__ == "__main__":
    build()
