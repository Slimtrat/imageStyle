from __future__ import annotations

import sys

import pytest


@pytest.fixture(autouse=True)
def close_orphaned_studio_panels():
    """Keep Qt proxy jobs scoped to the test that created their Studio panel."""
    yield
    studio_module = sys.modules.get("artanimate.desktop.studio")
    widgets_module = sys.modules.get("PySide6.QtWidgets")
    if studio_module is None or widgets_module is None:
        return
    application = widgets_module.QApplication.instance()
    if application is None:
        return
    panel_type = studio_module.StudioPanel
    panels = [
        widget
        for widget in application.allWidgets()
        if isinstance(widget, panel_type)
    ]
    for panel in panels:
        panel.close()
    application.processEvents()
