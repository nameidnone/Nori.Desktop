"""Build script for Nori Desktop Pet - Compiles C++ extensions and prepares for Nuitka packaging."""

from __future__ import annotations

import os
import sys
import subprocess
import shutil
from pathlib import Path
from typing import Optional

# Project root
ROOT_DIR = Path(__file__).parent.absolute()
CPP_EXT_DIR = ROOT_DIR / "cpp_ext"
BUILD_DIR = ROOT_DIR / "build" / "cpp"
SRC_DIR = ROOT_DIR / "src"


def check_requirements() -> bool:
    """Check if build requirements are installed."""
    requirements = {
        "cmake": "CMake >= 3.28",
        "python": "Python >= 3.12",
    }
    
    missing = []
    
    # Check CMake
    try:
        result = subprocess.run(
            ["cmake", "--version"],
            capture_output=True,
            text=True,
            check=False
        )
        if result.returncode != 0:
            missing.append("cmake")
    except FileNotFoundError:
        missing.append("cmake")
    
    # Check Python version
    if sys.version_info < (3, 12):
        missing.append(f"python>=3.12 (current: {sys.version_info.major}.{sys.version_info.minor})")
    
    if missing:
        print("❌ Missing build requirements:")
        for req in missing:
            print(f"   - {req}")
        return False
    
    print("✅ Build requirements satisfied")
    return True


def build_cpp_extension(build_type: str = "Release") -> bool:
    """
    Build C++ extension using CMake.
    
    Args:
        build_type: CMake build type (Release/Debug)
    
    Returns:
        True if build succeeded
    """
    print(f"\n🔨 Building C++ extension ({build_type})...")
    
    # Create build directory
    BUILD_DIR.mkdir(parents=True, exist_ok=True)
    
    # Configure with CMake
    print("   Configuring CMake...")
    configure_cmd = [
        "cmake",
        "-S", str(CPP_EXT_DIR),
        "-B", str(BUILD_DIR),
        f"-DCMAKE_BUILD_TYPE={build_type}",
        "-DPYTHON_EXECUTABLE=" + sys.executable,
    ]
    
    # Platform-specific options
    if sys.platform == "win32":
        configure_cmd.extend(["-A", "x64"])
    elif sys.platform == "darwin":
        configure_cmd.extend([
            "-DCMAKE_OSX_ARCHITECTURES=arm64;x86_64",
            "-DCMAKE_MACOSX_RPATH=ON",
        ])
    
    result = subprocess.run(configure_cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"❌ CMake configuration failed:\n{result.stderr}")
        return False
    
    # Build
    print("   Compiling...")
    build_cmd = [
        "cmake",
        "--build", str(BUILD_DIR),
        "--config", build_type,
        "-j", str(os.cpu_count()),
    ]
    
    result = subprocess.run(build_cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"❌ Build failed:\n{result.stderr}")
        return False
    
    # Copy extension to source directory
    print("   Installing extension...")
    ext_name = "nori_core_ext"
    
    if sys.platform == "win32":
        src_ext = BUILD_DIR / f"{ext_name}.pyd"
        dst_ext = SRC_DIR / "nori_core" / "_ext" / f"{ext_name}.pyd"
    elif sys.platform == "darwin":
        src_ext = BUILD_DIR / f"{ext_name}.so"
        dst_ext = SRC_DIR / "nori_core" / "_ext" / f"{ext_name}.so"
    else:  # Linux
        src_ext = BUILD_DIR / f"{ext_name}.so"
        dst_ext = SRC_DIR / "nori_core" / "_ext" / f"{ext_name}.so"
    
    if src_ext.exists():
        dst_ext.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src_ext, dst_ext)
        print(f"✅ Extension copied to {dst_ext}")
    else:
        print(f"⚠️  Extension not found at {src_ext}")
        # Search for it
        for f in BUILD_DIR.rglob(f"{ext_name}.*"):
            print(f"   Found: {f}")
        return False
    
    return True


def run_nuitka(onefile: bool = True) -> bool:
    """
    Compile Python code to native binary using Nuitka.
    
    Args:
        onefile: Create single executable
    
    Returns:
        True if compilation succeeded
    """
    print("\n📦 Running Nuitka compilation...")
    
    nuitka_cmd = [
        sys.executable, "-m", "nuitka",
        "--module-name=nori_desktop",
        "--include-package=nori_core",
        "--include-package=nori_desktop",
        "--standalone",
    ]
    
    if onefile:
        nuitka_cmd.extend([
            "--onefile",
            "--windows-disable-console" if sys.platform == "win32" else "",
        ])
    
    nuitka_cmd.extend([
        "--enable-plugin=pyqt6",
        "--output-dir=dist",
        "--assume-yes-for-downloads",
        "--python-flag=-O",
        SRC_DIR / "nori_desktop" / "__main__.py",
    ])
    
    # Remove empty strings
    nuitka_cmd = [arg for arg in nuitka_cmd if arg]
    
    print(f"   Command: {' '.join(nuitka_cmd)}")
    
    result = subprocess.run(nuitka_cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"❌ Nuitka compilation failed:\n{result.stderr}")
        return False
    
    print("✅ Nuitka compilation successful")
    return True


def main():
    """Main build entry point."""
    print("=" * 60)
    print("Nori Desktop Pet - Build Script")
    print("=" * 60)
    
    # Change to project root
    os.chdir(ROOT_DIR)
    
    # Check requirements
    if not check_requirements():
        sys.exit(1)
    
    # Build C++ extension
    build_type = os.environ.get("BUILD_TYPE", "Release")
    if not build_cpp_extension(build_type):
        print("\n⚠️  C++ extension build failed, continuing with Python-only build...")
    
    # Run Nuitka (optional, can be disabled)
    if os.environ.get("SKIP_NUITKA", "").lower() != "1":
        if not run_nuitka(onefile=True):
            print("\n⚠️  Nuitka compilation failed")
            sys.exit(1)
    
    print("\n" + "=" * 60)
    print("✅ Build completed successfully!")
    print("=" * 60)


if __name__ == "__main__":
    main()
