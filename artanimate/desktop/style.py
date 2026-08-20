APP_STYLESHEET = """
QWidget {
    color: #172033;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog, QWidget#appRoot {
    background: #f4f6fa;
}
QLabel#brand {
    color: #172033;
    font-size: 25px;
    font-weight: 700;
}
QLabel#versionBadge {
    color: #4050c2;
    background: #eef0ff;
    border: 1px solid #d8dcff;
    border-radius: 6px;
    padding: 2px 7px;
    font-size: 10px;
    font-weight: 800;
}
QLabel#tagline, QLabel#muted, QLabel#pathText {
    color: #6b7280;
}
QLabel#dialogTitle {
    color: #172033;
    font-size: 22px;
    font-weight: 750;
}
QLabel#sectionTitle {
    color: #172033;
    font-size: 15px;
    font-weight: 650;
}
QFrame#card, QFrame#previewCard, QFrame#progressCard, QFrame#historyPanel {
    background: #ffffff;
    border: 1px solid #dfe4ec;
    border-radius: 14px;
}
QFrame#dropZone {
    background: #fafbfe;
    border: 2px dashed #c8d0dc;
    border-radius: 13px;
}
QFrame#dropZone:hover {
    background: #f5f7ff;
    border-color: #6775e8;
}
QFrame#dropZone[ready="true"] {
    background: #f2fbf6;
    border-color: #65b383;
}
QFrame#dropZone[invalid="true"] {
    background: #fff4f4;
    border-color: #d85d69;
}
QCommandLinkButton#settingsCard {
    color: #172033;
    background: #f8f9fd;
    border: 1px solid #d9dfea;
    border-radius: 11px;
    padding: 8px 11px;
    text-align: left;
    font-weight: 700;
}
QCommandLinkButton#settingsCard:hover {
    color: #4050c2;
    background: #eef0ff;
    border-color: #aeb7f0;
}
QCommandLinkButton#settingsCard:focus {
    border: 2px solid #6775e8;
}
QPushButton {
    background: #eef1f6;
    border: 1px solid #d8dee8;
    border-radius: 8px;
    padding: 8px 14px;
    font-weight: 600;
}
QPushButton:hover {
    background: #e4e9f1;
}
QPushButton:disabled {
    color: #9da5b3;
    background: #f1f3f6;
}
QPushButton#primaryButton {
    color: #ffffff;
    background: #5262d9;
    border: 1px solid #5262d9;
    padding: 11px 20px;
}
QPushButton#primaryButton:hover {
    background: #4352c5;
}
QPushButton#dangerButton {
    color: #a43b45;
    background: #fff4f4;
    border-color: #f0c9cc;
}
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {
    background: #ffffff;
    border: 1px solid #ccd3df;
    border-radius: 7px;
    min-height: 32px;
    padding: 0 8px;
}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {
    border: 2px solid #6775e8;
}
QComboBox::drop-down {
    border: none;
    width: 24px;
}
QProgressBar {
    background: #e8ebf1;
    border: none;
    border-radius: 6px;
    height: 12px;
    text-align: center;
}
QProgressBar::chunk {
    background: #5969df;
    border-radius: 6px;
}
QScrollArea {
    border: none;
    background: transparent;
}
QScrollArea#settingsScroll, QWidget#settingsViewport,
QWidget#settingsContent, QStackedWidget#effectModeStack,
QWidget#effectModePage {
    color: #172033;
    background-color: #f4f6fa;
}
QLabel#parameterHelp {
    color: #4e5870;
    background-color: transparent;
    padding: 0 0 7px 0;
}
QFrame#sequenceCard {
    background: #f8f9fd;
    border: 1px solid #dfe4ec;
    border-radius: 11px;
}
QLabel#helperText {
    color: #4e5870;
    background: #eef1f8;
    border-radius: 8px;
    padding: 8px 10px;
}
QLabel#sliderValue {
    color: #4050c2;
    background: #eef0ff;
    border: 1px solid #d8dcff;
    border-radius: 6px;
    padding: 3px 6px;
    font-weight: 700;
}
QLabel#rangeLabel {
    color: #8a92a1;
    font-size: 10px;
}
QSlider::groove:horizontal {
    height: 6px;
    background: #dfe4ec;
    border-radius: 3px;
}
QSlider::sub-page:horizontal {
    background: #6372e5;
    border-radius: 3px;
}
QSlider::handle:horizontal {
    width: 16px;
    height: 16px;
    margin: -5px 0;
    background: #ffffff;
    border: 2px solid #5262d9;
    border-radius: 8px;
}
QSlider::handle:horizontal:hover {
    background: #eef0ff;
}
QTabWidget::pane {
    border: 1px solid #dfe4ec;
    border-radius: 12px;
    background: #f7f8fb;
}
QTabBar::tab {
    background: #e8ebf2;
    border: 1px solid #d6dce7;
    padding: 9px 20px;
    margin-right: 4px;
    border-top-left-radius: 8px;
    border-top-right-radius: 8px;
    font-weight: 650;
}
QTabBar::tab:selected {
    color: #4352c5;
    background: #ffffff;
}
QLabel#previewBadge {
    color: #5262d9;
    background: #eef0ff;
    border-radius: 7px;
    padding: 4px 7px;
    font-size: 11px;
}
QFrame#historyCard {
    background: #f9faff;
    border: 1px solid #dfe4ec;
    border-radius: 10px;
}
QLabel#historyThumbnail {
    color: #8a92a1;
    background: #171b25;
    border-radius: 7px;
}
QLabel#historyTitle {
    font-weight: 700;
}
QLabel#historyMetadata {
    color: #737c8e;
    font-size: 10px;
}
QLabel#historyEmpty {
    color: #8a92a1;
    background: #f7f8fb;
    border: 1px dashed #cbd2de;
    border-radius: 9px;
    padding: 10px;
}
QPushButton#compactButton {
    padding: 3px 7px;
    font-size: 11px;
}
QToolButton#historyMenuButton {
    min-width: 28px;
    min-height: 24px;
    background: #eef1f6;
    border: 1px solid #d8dee8;
    border-radius: 7px;
    font-size: 18px;
    font-weight: 700;
}
QMenuBar {
    background: #ffffff;
    border-bottom: 1px solid #dfe4ec;
    padding: 3px;
}
QMenuBar::item {
    padding: 6px 10px;
    border-radius: 6px;
}
QMenuBar::item:selected, QMenu::item:selected {
    background: #eef0ff;
    color: #4050c2;
}
QMenu {
    background: #ffffff;
    border: 1px solid #d8dee8;
    padding: 5px;
}
QMenu::item {
    padding: 7px 24px 7px 10px;
}
QWidget#studio3DPage {
    background: #f7f8fb;
}
QLabel#studioTitle {
    color: #172033;
    font-size: 23px;
    font-weight: 750;
}
QLabel#studioLiveBadge {
    color: #eafff2;
    background: #23865b;
    border-radius: 9px;
    padding: 6px 11px;
    font-size: 10px;
    font-weight: 800;
}
QFrame#studioControls {
    background: #ffffff;
    border: 1px solid #dfe4ec;
    border-radius: 13px;
}
QLabel#studioStatus {
    color: #4e5870;
    background: #f4f6fa;
    border-radius: 8px;
    padding: 9px;
}
QToolTip {
    color: #ffffff;
    background: #20283a;
    border: none;
    padding: 5px;
}
"""
