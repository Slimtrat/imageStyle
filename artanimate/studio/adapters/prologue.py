from __future__ import annotations

from ..prologue import (
    PROLOGUE_CAPABILITY_ID,
    PROLOGUE_RENDERER_ID,
    PrologueSettings,
    render_prologue_frame,
)
from ..semantic import (
    FrozenJsonObject,
    RenderFrame,
    RenderRequest,
    RendererDescriptor,
    RendererEvaluation,
)
from ..sources import validate_frame_index


class PreparedPrologueRender:
    def __init__(self, request: RenderRequest, settings: PrologueSettings) -> None:
        self.request = request
        self.settings = settings.validate()
        self.width = request.constraints.width
        self.height = request.constraints.height
        self.fps = request.constraints.fps
        self.frame_count = request.invocation.duration_frames
        self.closed = False

    def frame_at(self, frame_index: int) -> RenderFrame:
        if self.closed:
            raise RuntimeError("Ce rendu de prologue est fermé")
        local = validate_frame_index(frame_index, self.frame_count)
        return RenderFrame(
            image=render_prologue_frame(
                self.settings,
                self.width,
                self.height,
                local,
                self.frame_count,
            ),
            blend_mode="normal",
            metadata=FrozenJsonObject(
                {
                    "capability_id": PROLOGUE_CAPABILITY_ID,
                    "progress": 0.0
                    if self.frame_count == 1
                    else local / (self.frame_count - 1),
                },
                where="prologue.frame",
            ),
        )

    def close(self) -> None:
        self.closed = True


class LocalPrologueRenderer:
    descriptor = RendererDescriptor(
        PROLOGUE_RENDERER_ID,
        "Prologue typographique local",
        (PROLOGUE_CAPABILITY_ID,),
        version="1",
        deterministic=True,
        offline=True,
        priority=200,
    )

    def evaluate(self, request: RenderRequest) -> RendererEvaluation:
        try:
            PrologueSettings.from_mapping(
                request.invocation.parameters.to_dict().get("settings")
            )
        except (TypeError, ValueError) as exc:
            return RendererEvaluation(False, reasons=(str(exc),))
        return RendererEvaluation(True, score=200)

    def prepare(self, request: RenderRequest) -> PreparedPrologueRender:
        evaluation = self.evaluate(request)
        if not evaluation.compatible:
            raise ValueError("Prologue impossible : " + "; ".join(evaluation.reasons))
        return PreparedPrologueRender(
            request,
            PrologueSettings.from_mapping(
                request.invocation.parameters.to_dict().get("settings")
            ),
        )
