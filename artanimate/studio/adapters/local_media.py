from __future__ import annotations

from pathlib import Path

from ..media import StillClipSettings, StillImageSource
from ..model import AssetKind, StudioProject
from ..semantic import (
    FrozenJsonObject,
    RendererDescriptor,
    RendererEvaluation,
    RenderFrame,
    RenderRequest,
)
from ..source_registry import ArtworkSourceRegistry
from ..sources import validate_frame_index, validate_timed_frame
from ..video import VideoClipSettings, VideoFrameSource


class _PreparedLocalMedia:
    def __init__(self, source: StillImageSource | VideoFrameSource, request: RenderRequest) -> None:
        self.source = source
        self.width = source.width
        self.height = source.height
        self.fps = source.fps
        self.frame_count = request.invocation.duration_frames
        self.source_in_frame = int(request.invocation.parameters["source_in_frame"])
        self.closed = False

    def frame_at(self, frame_index: int) -> RenderFrame:
        if self.closed:
            raise RuntimeError("Ce rendu de média local est fermé")
        local = validate_frame_index(frame_index, self.frame_count)
        image = validate_timed_frame(
            self.source,
            self.source.frame_at(self.source_in_frame + local),
        )
        return RenderFrame(
            image=image,
            metadata=FrozenJsonObject({
                "asset_id": self.source.asset_id,
                "diagnostic": self.source.diagnostic,
                "diagnostic_message": self.source.diagnostic_message,
            }),
        )

    def close(self) -> None:
        self.closed = True


class LocalMediaCapabilityRenderer:
    descriptor = RendererDescriptor(
        "local.media",
        "Média local référencé",
        ("media.present",),
        supports_alpha=True,
        priority=100,
    )

    def __init__(
        self,
        project: StudioProject,
        artwork_path: str | Path,
        sources: ArtworkSourceRegistry,
        *,
        resource_base: str | Path | None = None,
    ) -> None:
        self.project = project
        self.sources = sources
        self.resource_base = (
            Path(resource_base)
            if resource_base is not None
            else Path(artwork_path).resolve(strict=False).parent
        )

    def _asset(self, request: RenderRequest):
        asset_id = str(request.invocation.parameters["asset_id"])
        try:
            return next(asset for asset in self.project.assets if asset.asset_id == asset_id)
        except StopIteration as exc:
            raise KeyError(f"Asset local introuvable : {asset_id}") from exc

    def evaluate(self, request: RenderRequest) -> RendererEvaluation:
        try:
            asset = self._asset(request)
        except KeyError as exc:
            return RendererEvaluation(False, reasons=(str(exc),))
        if asset.kind not in {AssetKind.IMAGE, AssetKind.VIDEO}:
            return RendererEvaluation(False, reasons=("type de média visuel incompatible",))
        return RendererEvaluation(True, 100)

    def prepare(self, request: RenderRequest) -> _PreparedLocalMedia:
        asset = self._asset(request)
        path = Path(asset.path)
        if not path.is_absolute():
            path = self.resource_base / path
        path = path.resolve(strict=False)
        if not path.is_file():
            source = StillImageSource.missing(
                asset,
                path,
                self.project.settings.fps,
                request.constraints.width,
                request.constraints.height,
                f"Média manquant : {path.name}",
            )
        elif asset.kind == AssetKind.IMAGE:
            settings = StillClipSettings.from_mapping(
                request.invocation.parameters.to_dict().get("settings")
            )
            try:
                source = self.sources.still_image(
                    asset,
                    path,
                    settings,
                    self.project.settings.fps,
                )
            except (OSError, ValueError) as exc:
                source = StillImageSource.missing(
                    asset,
                    path,
                    self.project.settings.fps,
                    request.constraints.width,
                    request.constraints.height,
                    f"Média illisible : {exc}",
                )
        else:
            settings = VideoClipSettings.from_mapping(
                request.invocation.parameters.to_dict().get("settings")
            )
            try:
                source = self.sources.video(
                    asset,
                    path,
                    settings,
                    self.project.settings.fps,
                )
            except (OSError, ValueError) as exc:
                source = StillImageSource.missing(
                    asset,
                    path,
                    self.project.settings.fps,
                    request.constraints.width,
                    request.constraints.height,
                    f"Vidéo illisible : {exc}",
                )
        return _PreparedLocalMedia(source, request)
