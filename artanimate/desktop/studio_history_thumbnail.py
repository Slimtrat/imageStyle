from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QImage

from ..studio.model import AssetKind, MediaAsset
from ..studio.video import VideoClipSettings, VideoFrameSource, inspect_video


logger = logging.getLogger(__name__)


def representative_video_thumbnail(
    output: str | Path,
    frame_count: int,
) -> QImage | None:
    """Decode the middle frame through the client source used by Studio media."""

    try:
        path = Path(output).resolve(strict=True)
        inspection = inspect_video(path)
        asset = MediaAsset(
            "history-thumbnail",
            AssetKind.VIDEO,
            str(path),
            width=inspection.width,
            height=inspection.height,
            metadata={
                "native_frame_count": inspection.native_frame_count,
                "native_fps": inspection.native_fps,
            },
        )
        source = VideoFrameSource(
            asset,
            path,
            int(round(inspection.native_fps)),
            VideoClipSettings(),
            max_cache_frames=1,
        )
        try:
            index = min(max(0, int(frame_count) // 2), source.frame_count - 1)
            frame = source.frame_at(index)
            return QImage(
                frame.data,
                frame.shape[1],
                frame.shape[0],
                frame.strides[0],
                QImage.Format.Format_RGB888,
            ).copy()
        finally:
            source.close()
    except (IndexError, OSError, RuntimeError, TypeError, ValueError):
        logger.exception("Vignette représentative impossible : %s", output)
        return None
