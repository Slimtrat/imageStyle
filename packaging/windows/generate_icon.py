from __future__ import annotations

from pathlib import Path

from PIL import Image


WINDOWS_ICON_SIZES = tuple(
    (size, size) for size in (16, 20, 24, 32, 40, 48, 64, 128, 256)
)


def main() -> None:
    windows_dir = Path(__file__).resolve().parent
    project_root = windows_dir.parents[1]
    source = (
        project_root
        / "artanimate"
        / "assets"
        / "branding"
        / "artanimate-harlequin-logo.png"
    )
    destination = windows_dir / "artanimate.ico"

    with Image.open(source) as image:
        square = image.convert("RGBA")
        if square.width != square.height:
            raise ValueError(f"Le logo doit être carré : {source}")
        square.save(destination, format="ICO", sizes=WINDOWS_ICON_SIZES)

    print(f"Icône Windows créée : {destination}")


if __name__ == "__main__":
    main()
