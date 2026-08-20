import json

from artanimate.core.effects.documentation import (
    DOCUMENTATION_PATH,
    documentation_for,
    load_effect_documentation,
)


def test_effect_documentation_json_is_packaged_and_valid() -> None:
    payload = json.loads(DOCUMENTATION_PATH.read_text(encoding="utf-8"))
    documentation = load_effect_documentation()

    assert payload["schema_version"] == 1
    assert set(documentation) == {"sand", "wave"}
    assert documentation_for("sand").parameters[0].description
    assert documentation_for("wave").parameters[0].choices
