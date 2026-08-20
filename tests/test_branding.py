from PIL import Image

from artanimate.branding import LOGO_PATH, require_logo_path


def test_harlequin_logo_is_a_packaged_square_asset() -> None:
    assert require_logo_path() == LOGO_PATH
    with Image.open(LOGO_PATH) as logo:
        assert logo.format == "PNG"
        assert logo.width == logo.height
        assert logo.width >= 512
        assert logo.mode in {"RGB", "RGBA"}
