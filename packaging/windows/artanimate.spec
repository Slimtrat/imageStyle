from pathlib import Path

from PyInstaller.utils.hooks import collect_all


WINDOWS_DIR = Path(SPECPATH).resolve()
PROJECT_ROOT = WINDOWS_DIR.parents[1]

imageio_datas, imageio_binaries, imageio_hiddenimports = collect_all("imageio_ffmpeg")
branding_datas = [
    (
        str(
            PROJECT_ROOT
            / "artanimate"
            / "assets"
            / "branding"
            / "artanimate-harlequin-logo.png"
        ),
        "artanimate/assets/branding",
    )
]
documentation_datas = [
    (
        str(PROJECT_ROOT / "artanimate" / "assets" / "docs" / "effects.fr.json"),
        "artanimate/assets/docs",
    )
]

analysis = Analysis(
    [str(WINDOWS_DIR / "launcher.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=imageio_binaries,
    datas=branding_datas + documentation_datas + imageio_datas,
    hiddenimports=imageio_hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name="ArtAnimate",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(WINDOWS_DIR / "artanimate.ico"),
    version=str(WINDOWS_DIR / "version_info.txt"),
)
