from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from PIL import Image

from artanimate.studio.model import ClipKind, StudioProject
from artanimate.studio.render_session import StudioRenderSession


def test_canonical_2d_session_executes_the_semantic_render_plan(tmp_path: Path) -> None:
    artwork = tmp_path / "artwork.png"
    Image.new("RGB", (96, 64), (210, 48, 88)).save(artwork)
    project = StudioProject.new(artwork, duration_seconds=2)

    with StudioRenderSession(
        project,
        artwork,
        output_width=90,
        output_height=160,
    ) as session:
        assert session.execution_mode == "semantic"
        prepared = session.prepared_plan
        frame = session.frame_at(0)
        assert frame.shape == (160, 90, 3)

    assert prepared is not None
    assert prepared.closed
    assert session.prepared_plan is None


def test_unmigrated_3d_capability_keeps_the_legacy_path_temporarily(tmp_path: Path) -> None:
    artwork = tmp_path / "artwork.png"
    Image.new("RGB", (96, 64), (40, 130, 220)).save(artwork)
    project = StudioProject.new(artwork, duration_seconds=2)
    artwork_track = project.tracks[0]
    three_d = replace(artwork_track.clips[0], kind=ClipKind.ARTWORK_3D)
    project = replace(
        project,
        tracks=(replace(artwork_track, clips=(three_d,)), *project.tracks[1:]),
    ).validate()

    with StudioRenderSession(
        project,
        artwork,
        output_width=90,
        output_height=160,
    ) as session:
        assert session.execution_mode == "legacy"
        assert session.prepared_plan is None
        assert session.frame_at(0).shape == (160, 90, 3)
