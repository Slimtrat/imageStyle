from pathlib import Path

from PIL import Image
import pytest

from artanimate.studio.model import StudioProject, TrackKind
from artanimate.studio.timeline import add_track, set_track_state, track_by_id


def project(tmp_path: Path) -> StudioProject:
    artwork = tmp_path / "art.png"
    Image.new("RGB", (100, 160), "white").save(artwork)
    return StudioProject.new(artwork)


def test_multiple_tracks_can_be_added_at_explicit_z_positions(tmp_path: Path) -> None:
    source = project(tmp_path)
    updated, video = add_track(source, TrackKind.VIDEO, name="Réel", index=1)
    updated, effects = add_track(updated, TrackKind.EFFECT)
    updated, audio = add_track(updated, TrackKind.AUDIO)

    assert [track.track_id for track in updated.tracks][1] == video.track_id
    assert sum(track.kind == TrackKind.VIDEO for track in updated.tracks) == 2
    assert sum(track.kind == TrackKind.EFFECT for track in updated.tracks) == 2
    assert sum(track.kind == TrackKind.AUDIO for track in updated.tracks) == 2
    assert track_by_id(updated, effects.track_id)[1].kind == TrackKind.EFFECT
    assert track_by_id(updated, audio.track_id)[1].kind == TrackKind.AUDIO


def test_track_states_are_immutable_validated_updates(tmp_path: Path) -> None:
    source = project(tmp_path)
    updated = set_track_state(
        source,
        "video-main",
        muted=True,
        locked=True,
        hidden=True,
    )

    original = track_by_id(source, "video-main")[1]
    changed = track_by_id(updated, "video-main")[1]
    assert not original.muted and not original.locked and not original.hidden
    assert changed.muted and changed.locked and changed.hidden
    with pytest.raises(KeyError, match="introuvable"):
        set_track_state(updated, "missing", muted=True)

