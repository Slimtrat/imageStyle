from __future__ import annotations

from collections.abc import Callable
from threading import Event
from time import monotonic
from typing import Any

from PySide6.QtCore import QCoreApplication, QEventLoop, QThread, QTimer, Qt
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from ..core.video import RenderCancelled
from .preview import frame_to_qimage
from .studio3d import Studio3DPanel
from .studio3d_export import capture_requires_retry, qimage_to_rgb
from .studio3d_renderer import PreparedStudio3DRender


def _event_pause(milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(max(0, int(milliseconds)), loop.quit)
    loop.exec()


def capture_with_retry(
    grab: Callable[[], QImage],
    *,
    cancelled: Event | None = None,
    max_retries: int = 5,
    wait_for_scene: Callable[[], None] | None = None,
) -> QImage:
    """Capture one valid GPU frame with bounded retries and cancellation."""
    if max_retries < 0:
        raise ValueError("Le nombre de retries 3D ne peut pas être négatif")
    wait = wait_for_scene or (lambda: _event_pause(36))
    for attempt in range(max_retries + 1):
        if cancelled is not None and cancelled.is_set():
            raise RenderCancelled("Capture Studio 3D annulée")
        image = grab()
        try:
            invalid = capture_requires_retry(qimage_to_rgb(image))
        except (TypeError, ValueError):
            invalid = True
        if not invalid:
            return image
        if attempt < max_retries:
            wait()
    raise RuntimeError(
        f"Le moteur 3D a produit {max_retries + 1} captures vides consécutives"
    )


class StandaloneStudio3DCapture:
    """Own an off-screen 3D surface; never reuses the visible Studio workspace."""

    def __init__(
        self,
        width: int,
        height: int,
        *,
        panel_factory: Callable[[], Studio3DPanel] = Studio3DPanel,
        ready_timeout_ms: int = 5000,
    ) -> None:
        if width <= 0 or height <= 0:
            raise ValueError("Les dimensions de capture 3D doivent être positives")
        application = QApplication.instance()
        if application is None:
            raise RuntimeError("Une QApplication est requise pour la capture Studio 3D")
        if QThread.currentThread() is not application.thread():
            raise RuntimeError("La surface Studio 3D doit être créée sur le thread UI")
        self.width = int(width)
        self.height = int(height)
        self.ready_timeout_ms = int(ready_timeout_ms)
        self.panel = panel_factory()
        self.panel.setAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen, True)
        self.panel.resize(max(760, self.width + 360), max(560, self.height))
        self.panel.show()
        self.panel.activate()
        self._prepared_identity: int | None = None
        self.closed = False

    def _ensure_ui_thread(self) -> None:
        application = QApplication.instance()
        if application is None or QThread.currentThread() is not application.thread():
            raise RuntimeError("La capture Studio 3D doit s’exécuter sur le thread UI")

    def _ensure_ready(self) -> None:
        deadline = monotonic() + max(0, self.ready_timeout_ms) / 1000
        while not self.panel.is_ready() and monotonic() < deadline:
            QCoreApplication.processEvents()
            _event_pause(10)
        if not self.panel.is_ready():
            details = "; ".join(self.panel.scene_errors) or "délai de chargement dépassé"
            raise RuntimeError("Surface Studio 3D indisponible : " + details)

    def _prepare_scene(self, prepared: PreparedStudio3DRender) -> None:
        identity = id(prepared)
        if self._prepared_identity == identity:
            return
        config = prepared.source.renderer.config
        initial = prepared.state_at(0)
        self.panel.set_scene_data(prepared.scene_data)
        self.panel.set_effect(
            config.effect,
            config.rgb_mode,
            initial.settings.direction,
            initial.settings.wave,
        )
        self._prepared_identity = identity

    def capture_at(
        self,
        prepared: PreparedStudio3DRender,
        frame_index: int,
        *,
        cancelled: Event | None = None,
        max_retries: int = 5,
    ) -> QImage:
        if self.closed:
            raise RuntimeError("La surface de capture Studio 3D est fermée")
        self._ensure_ui_thread()
        self._ensure_ready()
        self._prepare_scene(prepared)
        packet = prepared.frame_at(frame_index)
        state = prepared.state_at(frame_index)
        self.panel.set_frame(
            frame_to_qimage(packet.image),
            state.frame_index,
            state.frame_count,
            state.effect_progress,
        )
        self.panel.apply_scene_state(state)
        QCoreApplication.processEvents()
        return capture_with_retry(
            lambda: self.panel.capture_frame(self.width, self.height),
            cancelled=cancelled,
            max_retries=max_retries,
        )

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.panel.close()
        self.panel.deleteLater()
        QCoreApplication.processEvents()

    def __enter__(self) -> "StandaloneStudio3DCapture":
        if self.closed:
            raise RuntimeError("La surface de capture Studio 3D est fermée")
        return self

    def __exit__(self, *_args: Any) -> None:
        self.close()
