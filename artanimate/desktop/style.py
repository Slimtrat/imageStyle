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
QLabel#tagline, QLabel#muted, QLabel#pathText {
    color: #6b7280;
}
QLabel#sectionTitle {
    color: #172033;
    font-size: 15px;
    font-weight: 650;
}
QFrame#card, QFrame#previewCard, QFrame#progressCard {
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
QToolTip {
    color: #ffffff;
    background: #20283a;
    border: none;
    padding: 5px;
}
"""
