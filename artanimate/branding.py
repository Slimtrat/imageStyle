from __future__ import annotations

from pathlib import Path


BRANDING_DIR = Path(__file__).resolve().parent / "assets" / "branding"
LOGO_PATH = BRANDING_DIR / "artanimate-harlequin-logo.png"


def require_logo_path() -> Path:
    """Return the packaged logo path, failing clearly if packaging omitted it."""
    if not LOGO_PATH.is_file():
        raise FileNotFoundError(f"Logo ArtAnimate introuvable : {LOGO_PATH}")
    return LOGO_PATH
