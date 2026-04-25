import json
import os
import queue
import time
import ctypes
from ctypes import wintypes
from collections import deque

from PySide6.QtCore import QPoint, Qt, QThread, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QImage, QMouseEvent, QPainter, QPainterPath, QPen, QLinearGradient, QColor, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.paths import ensure_writable_file, resource_path
from core.state_machine import StateMachine
from gui.encyclopedia import EncyclopediaWidget
from gui.fishing_record import FishingRecordWidget
from gui.theme import (
    APP_COLORS,
    add_shadow,
    panel_stylesheet,
    primary_button_stylesheet,
    scroll_area_stylesheet,
    secondary_button_stylesheet,
    text_edit_stylesheet,
)

CONFIG_FILE = ensure_writable_file("config.json")


class BackdropFrame(QFrame):
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        rect = self.rect()
        path = QPainterPath()
        path.addRoundedRect(rect.adjusted(0, 0, -1, -1), 32, 32)
        painter.fillPath(path, QColor(APP_COLORS["bg_alt"]))

        glow1 = QLinearGradient(rect.topLeft(), rect.bottomRight())
        glow1.setColorAt(0.0, QColor(17, 199, 214, 62))
        glow1.setColorAt(0.55, QColor(8, 18, 30, 0))
        glow1.setColorAt(1.0, QColor(17, 199, 214, 0))
        painter.fillPath(path, glow1)

        glow2 = QLinearGradient(rect.topRight(), rect.bottomLeft())
        glow2.setColorAt(0.0, QColor(120, 170, 255, 28))
        glow2.setColorAt(0.4, QColor(10, 18, 28, 0))
        glow2.setColorAt(1.0, QColor(10, 18, 28, 0))
        painter.fillPath(path, glow2)

        painter.setPen(QPen(QColor(74, 107, 141, 72), 1))
        painter.drawPath(path)
        super().paintEvent(event)


class NavButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedHeight(52)
        self.setFont(QFont("Microsoft YaHei UI", 11, QFont.DemiBold))
        self.setStyleSheet(
            f"""
            QPushButton {{
                text-align: left;
                padding-left: 18px;
                color: {APP_COLORS['text_dim']};
                border: 1px solid transparent;
                outline: none;
                border-radius: 18px;
                background-color: transparent;
            }}
            QPushButton:hover {{
                color: {APP_COLORS['text']};
                background-color: rgba(255, 255, 255, 0.04);
            }}
            QPushButton:checked {{
                color: {APP_COLORS['accent_soft']};
                background-color: rgba(29, 208, 214, 0.14);
                border: 1px solid rgba(29, 208, 214, 0.36);
            }}
            """
        )


class TitleButton(QPushButton):
    def __init__(self, kind, hover_color, parent=None):
        super().__init__("", parent)
        self.kind = kind
        self.hover_color = hover_color
        self.setFixedSize(46, 34)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover, True)
        self.setStyleSheet("QPushButton { background: transparent; border: none; outline: none; }")

    def set_kind(self, kind):
        if self.kind != kind:
            self.kind = kind
            self.update()

    def enterEvent(self, event):
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(3, 4, -3, -4)
        if self.isDown():
            bg = QColor(255, 255, 255, 38)
        elif self.underMouse():
            bg = QColor(self.hover_color)
        else:
            bg = QColor(255, 255, 255, 0)
        painter.setPen(Qt.NoPen)
        painter.setBrush(bg)
        painter.drawRoundedRect(rect, 11, 11)

        icon_color = QColor(APP_COLORS["text"])
        if self.kind == "close" and self.underMouse():
            icon_color = QColor(255, 255, 255)
        elif not self.underMouse():
            icon_color = QColor(APP_COLORS["text_dim"])

        pen = QPen(icon_color, 1.35)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)

        cx = self.width() / 2
        cy = self.height() / 2
        if self.kind == "min":
            painter.drawLine(int(cx - 5), int(cy + 1), int(cx + 5), int(cy + 1))
        elif self.kind == "max":
            painter.drawRect(int(cx - 5), int(cy - 5), 10, 10)
        elif self.kind == "restore":
            painter.drawRect(int(cx - 6), int(cy - 2), 8, 8)
            painter.drawRect(int(cx - 2), int(cy - 6), 8, 8)
        elif self.kind == "close":
            painter.drawLine(int(cx - 5), int(cy - 5), int(cx + 5), int(cy + 5))
            painter.drawLine(int(cx + 5), int(cy - 5), int(cx - 5), int(cy + 5))


class LogoImageCard(QFrame):
    def __init__(self, image_path=None, parent=None):
        super().__init__(parent)
        self.image_path = image_path or resource_path("logo.jpg")
        self.source_pixmap = QPixmap(self.image_path) if os.path.exists(self.image_path) else QPixmap()
        self.setFixedSize(254, 146)
        self.setStyleSheet("QFrame { background: transparent; border: none; }")

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)

        rect = self.rect().adjusted(0, 0, -1, -1)
        path = QPainterPath()
        path.addRoundedRect(rect, 28, 28)

        if not self.source_pixmap.isNull():
            scaled = self.source_pixmap.scaled(
                self.size(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            x = int((self.width() - scaled.width()) / 2)
            y = int((self.height() - scaled.height()) / 2)
            painter.setClipPath(path)
            painter.drawPixmap(x, y, scaled)
            painter.setClipping(False)
        else:
            fallback = QLinearGradient(rect.topLeft(), rect.bottomRight())
            fallback.setColorAt(0.0, QColor(29, 208, 214, 190))
            fallback.setColorAt(1.0, QColor(10, 45, 66, 220))
            painter.fillPath(path, fallback)

        sheen = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        sheen.setColorAt(0.0, QColor(255, 255, 255, 32))
        sheen.setColorAt(0.45, QColor(255, 255, 255, 0))
        sheen.setColorAt(1.0, QColor(0, 0, 0, 28))
        painter.fillPath(path, sheen)

        painter.setPen(QPen(QColor(136, 230, 238, 72), 1))
        painter.drawPath(path)


class TitleBrand(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("QFrame { background: transparent; border: none; }")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(9)

        mark = QFrame()
        mark.setFixedSize(5, 24)
        mark.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        mark.setStyleSheet(
            f"""
            QFrame {{
                background-color: {APP_COLORS['accent_soft']};
                border: none;
                border-radius: 2px;
            }}
            """
        )
        layout.addWidget(mark, 0, Qt.AlignVCenter)

        title = QLabel(
            "<span style='color:#63E4E4;'>异环</span>"
            "<span style='color:#F3F8FF;'>自动钓鱼</span>"
        )
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        title.setStyleSheet(
            """
            QLabel {
                background: transparent;
                border: none;
                font-family: 'Microsoft YaHei UI';
                font-size: 15px;
                font-weight: 900;
            }
            """
        )
        layout.addWidget(title, 0, Qt.AlignVCenter)

        tag = QLabel("YHo AutoFish")
        tag.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        tag.setStyleSheet(
            f"""
            QLabel {{
                background-color: rgba(29, 208, 214, 0.08);
                border: 1px solid rgba(99, 228, 228, 0.22);
                border-radius: 11px;
                color: {APP_COLORS['text_soft']};
                font-size: 10px;
                font-weight: 800;
                padding: 3px 8px;
            }}
            """
        )
        layout.addWidget(tag, 0, Qt.AlignVCenter)


class CustomTitleBar(QFrame):
    def __init__(self, window, parent=None):
        super().__init__(parent)
        self.window_ref = window
        self.drag_pos = QPoint()
        self.dragging = False
        self.setFixedHeight(56)
        self.setStyleSheet(
            """
            QFrame {
                background-color: rgba(15, 27, 43, 0.86);
                border-top-left-radius: 32px;
                border-top-right-radius: 32px;
                border: 1px solid rgba(74, 107, 141, 0.22);
                border-bottom: none;
            }
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 14, 10)
        layout.setSpacing(10)

        title = TitleBrand()
        layout.addWidget(title)
        layout.addStretch()

        self.btn_min = TitleButton("min", "rgba(90, 129, 166, 0.22)")
        self.btn_max = TitleButton("max", "rgba(90, 129, 166, 0.22)")
        self.btn_close = TitleButton("close", "rgba(255, 102, 126, 0.58)")

        self.btn_min.clicked.connect(self.window_ref.showMinimized)
        self.btn_max.clicked.connect(self.window_ref.toggle_maximize_restore)
        self.btn_close.clicked.connect(self.window_ref.close)

        layout.addWidget(self.btn_min)
        layout.addWidget(self.btn_max)
        layout.addWidget(self.btn_close)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.window_ref.toggle_maximize_restore()
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.dragging = True
            self.drag_pos = event.globalPosition().toPoint() - self.window_ref.frameGeometry().topLeft()
            event.accept()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        if self.dragging and not self.window_ref.isMaximized():
            self.window_ref.move(event.globalPosition().toPoint() - self.drag_pos)
            event.accept()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self.dragging = False
        super().mouseReleaseEvent(event)

    def sync_state(self):
        self.btn_max.set_kind("restore" if self.window_ref.isMaximized() else "max")


class StatusChip(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignCenter)
        self.setFixedHeight(36)
        self.set_status("待机中", "idle")

    def set_status(self, text, tone="idle"):
        color = {
            "idle": APP_COLORS["text_dim"],
            "running": APP_COLORS["accent_soft"],
            "stopped": APP_COLORS["danger"],
        }.get(tone, APP_COLORS["text_dim"])
        self.setText(text)
        self.setStyleSheet(
            f"""
            QLabel {{
                background-color: rgba(255, 255, 255, 0.04);
                border: 1px solid rgba(111, 145, 182, 0.18);
                border-radius: 18px;
                color: {color};
                padding: 0 12px;
                font-size: 12px;
                font-weight: 800;
            }}
            """
        )


class NoWheelSlider(QSlider):
    def wheelEvent(self, event):
        event.ignore()


class RecognitionInitWorker(QThread):
    completed = Signal(bool, str)

    def __init__(self, state_machine, parent=None):
        super().__init__(parent)
        self.state_machine = state_machine

    def run(self):
        try:
            ok = self.state_machine.prepare_recognition_modules()
            if ok:
                self.completed.emit(True, "识别模块初始化完成，可以开始钓鱼。")
            else:
                self.completed.emit(False, "识别模块初始化失败，请检查 cnocr 与 onnxruntime 环境。")
        except Exception as exc:
            self.completed.emit(False, f"识别模块初始化失败: {exc}")


class PolicyDialog(QDialog):
    def __init__(self, title, subtitle, html, parent=None):
        super().__init__(parent)
        self.setModal(True)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(760, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(0)

        shell = QFrame()
        shell.setStyleSheet(
            f"""
            QFrame {{
                background-color: rgba(11, 22, 36, 0.97);
                border: 1px solid rgba(89, 125, 164, 0.28);
                border-radius: 30px;
            }}
            """
        )
        add_shadow(shell, blur=34, alpha=120, offset=(0, 14))
        root.addWidget(shell)

        layout = QVBoxLayout(shell)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(16)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text']}; font-size: 30px; font-weight: 900;"
        )
        layout.addWidget(title_label)

        subtitle_label = QLabel(subtitle)
        subtitle_label.setWordWrap(True)
        subtitle_label.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text_dim']}; font-size: 13px;"
        )
        layout.addWidget(subtitle_label)

        body = QTextEdit()
        body.setReadOnly(True)
        body.setFocusPolicy(Qt.NoFocus)
        body.setStyleSheet(text_edit_stylesheet())
        body.setHtml(html)
        layout.addWidget(body, 1)

        close_btn = QPushButton("已阅读，关闭")
        close_btn.setFocusPolicy(Qt.NoFocus)
        close_btn.setStyleSheet(primary_button_stylesheet())
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn, 0, Qt.AlignRight)


class ToastPopup(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet(
            f"""
            QFrame {{
                background-color: rgba(9, 20, 34, 0.94);
                border: 1px solid rgba(99, 228, 228, 0.36);
                border-radius: 18px;
            }}
            QLabel {{
                background: transparent;
                border: none;
                color: {APP_COLORS['text']};
                font-size: 13px;
                font-weight: 800;
            }}
            """
        )
        add_shadow(self, blur=24, alpha=110, offset=(0, 8))
        layout = QHBoxLayout(self)
        layout.setContentsMargins(18, 12, 18, 12)
        layout.setSpacing(8)
        self.label = QLabel("")
        layout.addWidget(self.label)
        self.hide_timer = QTimer(self)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self.hide)
        self.hide()

    def show_message(self, text, tone="info"):
        color = {
            "success": APP_COLORS["success"],
            "warning": APP_COLORS["warning"],
            "danger": APP_COLORS["danger"],
        }.get(tone, APP_COLORS["accent_soft"])
        self.label.setText(f"<span style='color:{color};'>●</span> {text}")
        self.adjustSize()
        self.reposition()
        self.raise_()
        self.show()
        self.hide_timer.start(2200)

    def reposition(self):
        parent = self.parentWidget()
        if parent:
            x = parent.width() - self.width() - 34
            y = 78
            self.move(max(24, x), y)


class FloatingControlWindow(QFrame):
    _EVENT_OBJECT_LOCATIONCHANGE = 0x800B
    _OBJID_WINDOW = 0
    _WINEVENT_OUTOFCONTEXT = 0x0000
    _WINEVENT_SKIPOWNPROCESS = 0x0002
    _SWP_NOSIZE = 0x0001
    _SWP_NOZORDER = 0x0004
    _SWP_NOACTIVATE = 0x0010
    _SWP_ASYNCWINDOWPOS = 0x4000
    _WinEventProc = ctypes.WINFUNCTYPE(
        None,
        wintypes.HANDLE,
        wintypes.DWORD,
        wintypes.HWND,
        wintypes.LONG,
        wintypes.LONG,
        wintypes.DWORD,
        wintypes.DWORD,
    )

    def __init__(self, app_window):
        super().__init__(None)
        self.app_window = app_window
        self._last_window_find = 0.0
        self._last_target_pos = None
        self._event_hook = None
        self._event_callback = None
        self._pending_hook_update = False
        self.setWindowTitle("异环自动钓鱼悬浮控制")
        self.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setFocusPolicy(Qt.NoFocus)

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(0)

        self.shell = QFrame()
        self.shell.setStyleSheet(
            """
            QFrame {
                background-color: rgba(10, 20, 34, 0.92);
                border: 1px solid rgba(103, 234, 236, 0.28);
                border-radius: 22px;
            }
            """
        )
        add_shadow(self.shell, blur=28, alpha=120, offset=(0, 10))
        root.addWidget(self.shell)

        layout = QVBoxLayout(self.shell)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(11)

        header = QHBoxLayout()
        title = QLabel("钓鱼悬浮窗")
        title.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text']}; font-size: 14px; font-weight: 900;"
        )
        header.addWidget(title)
        header.addStretch()

        self.close_btn = QPushButton("×")
        self.close_btn.setFixedSize(30, 30)
        self.close_btn.setFocusPolicy(Qt.NoFocus)
        self.close_btn.setCursor(Qt.PointingHandCursor)
        self.close_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.05);
                color: {APP_COLORS['text_dim']};
                border: 1px solid rgba(111, 145, 182, 0.18);
                border-radius: 15px;
                font-size: 16px;
                font-weight: 900;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 102, 126, 0.24);
                color: {APP_COLORS['text']};
            }}
            """
        )
        self.close_btn.clicked.connect(self.hide)
        header.addWidget(self.close_btn)
        layout.addLayout(header)

        self.status_label = QLabel()
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFixedHeight(34)
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.setSpacing(8)

        self.start_btn = QPushButton("▶ 开始")
        self.start_btn.setFixedHeight(42)
        self.start_btn.setFocusPolicy(Qt.NoFocus)
        self.start_btn.setCursor(Qt.PointingHandCursor)
        self.start_btn.clicked.connect(self.app_window.handle_primary_action)
        actions.addWidget(self.start_btn)

        self.stop_btn = QPushButton("■ 停止")
        self.stop_btn.setFixedHeight(42)
        self.stop_btn.setFocusPolicy(Qt.NoFocus)
        self.stop_btn.setCursor(Qt.PointingHandCursor)
        self.stop_btn.clicked.connect(self.app_window.stop_bot)
        actions.addWidget(self.stop_btn)
        layout.addLayout(actions)

        self.debug_panel = QFrame()
        self.debug_panel.setProperty("variant", "soft")
        self.debug_panel.setStyleSheet(panel_stylesheet())
        self.debug_panel.setMinimumHeight(198)
        debug_layout = QVBoxLayout(self.debug_panel)
        debug_layout.setContentsMargins(12, 12, 12, 12)
        debug_layout.setSpacing(10)

        debug_title = QLabel("调试溜鱼视图")
        debug_title.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['accent_soft']}; font-size: 12px; font-weight: 800;"
        )
        debug_layout.addWidget(debug_title)

        self.debug_preview = QLabel("等待画面...")
        self.debug_preview.setAlignment(Qt.AlignCenter)
        self.debug_preview.setFixedSize(236, 118)
        self.debug_preview.setStyleSheet(
            """
            background-color: rgba(5, 12, 20, 0.78);
            border: 1px solid rgba(87, 119, 153, 0.18);
            border-radius: 16px;
            color: #9AB0CA;
            font-size: 12px;
            font-weight: 700;
            """
        )
        debug_layout.addWidget(self.debug_preview)
        layout.addWidget(self.debug_panel)

        self.position_timer = QTimer(self)
        self.position_timer.setTimerType(Qt.PreciseTimer)
        self.position_timer.timeout.connect(self.position_near_game)
        self.position_timer.start(16)
        self.refresh_state()

    def refresh_state(self):
        running = self.app_window.sm.is_running
        modules_ready = self.app_window.modules_ready
        modules_initializing = self.app_window.modules_initializing
        status_text = "运行中" if running else "待机中"
        status_color = APP_COLORS["accent_soft"] if running else APP_COLORS["text_dim"]
        dot_color = APP_COLORS["success"] if running else APP_COLORS["warning"]
        self.status_label.setText(f"<span style='color:{dot_color};'>●</span> {status_text}")
        self.status_label.setStyleSheet(
            f"""
            QLabel {{
                background-color: rgba(255, 255, 255, 0.05);
                border: 1px solid rgba(111, 145, 182, 0.18);
                border-radius: 16px;
                color: {status_color};
                font-size: 12px;
                font-weight: 900;
            }}
            """
        )
        if modules_initializing:
            self.start_btn.setText(self.app_window.init_button_text("▶ 初始化"))
        elif modules_ready:
            self.start_btn.setText("▶ 开始")
        else:
            self.start_btn.setText("▶ 初始化")
        self.start_btn.setEnabled(not running and not modules_initializing)
        self.stop_btn.setEnabled(running)
        self.start_btn.setStyleSheet(primary_button_stylesheet())
        self.stop_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: rgba(255, 82, 117, 0.16);
                color: {APP_COLORS['danger']};
                border: 1px solid rgba(255, 82, 117, 0.34);
                border-radius: 18px;
                min-height: 40px;
                padding: 0 14px;
                font-size: 13px;
                font-weight: 900;
            }}
            QPushButton:hover {{
                background-color: rgba(255, 82, 117, 0.26);
                color: {APP_COLORS['text']};
            }}
            QPushButton:disabled {{
                background-color: rgba(255, 255, 255, 0.035);
                color: {APP_COLORS['text_soft']};
                border: 1px solid rgba(111, 145, 182, 0.12);
            }}
            """
        )
        self.refresh_debug_visibility()

    def refresh_debug_visibility(self):
        debug_enabled = bool(self.app_window.config.get("debug_mode", False))
        self.debug_panel.setVisible(debug_enabled)
        self.setFixedSize(304, 404 if debug_enabled else 176)
        self.adjustSize()

    def _ensure_event_hook(self):
        if self._event_hook:
            return
        hwnd = self.app_window.sm.wm.hwnd
        if not hwnd:
            return

        def _callback(_hook, event, hwnd_event, id_object, _id_child, _event_thread, _event_time):
            if event != self._EVENT_OBJECT_LOCATIONCHANGE:
                return
            if int(hwnd_event) != int(self.app_window.sm.wm.hwnd or 0):
                return
            if id_object != self._OBJID_WINDOW:
                return
            if self._pending_hook_update:
                return
            self._pending_hook_update = True
            QTimer.singleShot(0, self._position_from_hook)

        self._event_callback = self._WinEventProc(_callback)
        user32 = ctypes.windll.user32
        try:
            user32.SetWinEventHook.restype = wintypes.HANDLE
            user32.SetWinEventHook.argtypes = [
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.HANDLE,
                self._WinEventProc,
                wintypes.DWORD,
                wintypes.DWORD,
                wintypes.DWORD,
            ]
            user32.UnhookWinEvent.argtypes = [wintypes.HANDLE]
        except Exception:
            pass
        self._event_hook = user32.SetWinEventHook(
            self._EVENT_OBJECT_LOCATIONCHANGE,
            self._EVENT_OBJECT_LOCATIONCHANGE,
            0,
            self._event_callback,
            0,
            0,
            self._WINEVENT_OUTOFCONTEXT | self._WINEVENT_SKIPOWNPROCESS,
        )

    def _release_event_hook(self):
        if self._event_hook:
            try:
                ctypes.windll.user32.UnhookWinEvent(self._event_hook)
            except Exception:
                pass
        self._event_hook = None
        self._event_callback = None
        self._pending_hook_update = False

    def _position_from_hook(self):
        self._pending_hook_update = False
        self.position_near_game()

    def _move_to_target(self, target):
        if self._last_target_pos == target:
            return
        self._last_target_pos = target
        if self.pos() == target:
            return
        try:
            ctypes.windll.user32.SetWindowPos(
                int(self.winId()),
                0,
                target.x(),
                target.y(),
                0,
                0,
                self._SWP_NOSIZE | self._SWP_NOZORDER | self._SWP_NOACTIVATE | self._SWP_ASYNCWINDOWPOS,
            )
        except Exception:
            self.move(target)

    def position_near_game(self):
        if not self.isVisible():
            return

        rect = self.app_window.sm.wm.get_client_rect()
        now = time.monotonic()
        if rect is None and now - self._last_window_find > 1.2:
            self._last_window_find = now
            self.app_window.sm.wm.find_window()
            rect = self.app_window.sm.wm.get_client_rect()

        if rect:
            self._ensure_event_hook()
            left, top, _width, _height = rect
            target = QPoint(left + 16, top + 16)
        else:
            window_rect = self.app_window.geometry()
            target = QPoint(window_rect.left() + 34, window_rect.top() + 86)

        self._move_to_target(target)

    def showEvent(self, event):
        super().showEvent(event)
        self.refresh_state()
        self.position_near_game()

    def set_debug_frame(self, frame):
        if frame is None or not self.app_window.config.get("debug_mode", False):
            return
        rgb_frame = frame[:, :, ::-1].copy()
        height, width, channel = rgb_frame.shape
        image = QImage(rgb_frame.data, width, height, channel * width, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(image).scaled(
            self.debug_preview.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.debug_preview.setPixmap(pixmap)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._release_event_hook()
        if hasattr(self.app_window, "float_toggle_btn"):
            self.app_window.float_toggle_btn.setText("悬浮窗")

    def closeEvent(self, event):
        self._release_event_hook()
        super().closeEvent(event)


class UsageAgreementDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.seconds_left = 3
        self._allow_reject = False

        self.setModal(True)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(860, 660)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(0)

        shell = QFrame()
        shell.setStyleSheet(
            f"""
            QFrame {{
                background-color: rgba(11, 22, 36, 0.96);
                border: 1px solid rgba(89, 125, 164, 0.26);
                border-radius: 30px;
            }}
            """
        )
        add_shadow(shell, blur=34, alpha=120, offset=(0, 14))
        root.addWidget(shell)

        layout = QVBoxLayout(shell)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        header = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(6)

        title = QLabel("使用协议")
        title.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text']}; font-size: 32px; font-weight: 900;"
        )
        title_col.addWidget(title)

        subtitle = QLabel("请先阅读以下说明，再决定是否继续使用本程序。")
        subtitle.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text_dim']}; font-size: 13px;"
        )
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)

        badge = QLabel("启动前确认")
        badge.setProperty("role", "accent-chip")
        badge.setStyleSheet(
            f"""
            QLabel {{
                background-color: rgba(22, 209, 214, 0.12);
                color: {APP_COLORS['accent_soft']};
                border: 1px solid rgba(22, 209, 214, 0.28);
                border-radius: 15px;
                padding: 7px 14px;
                font-size: 12px;
                font-weight: 800;
            }}
            """
        )
        header.addWidget(badge, 0, Qt.AlignTop)
        layout.addLayout(header)

        agreement_box = QTextEdit()
        agreement_box.setReadOnly(True)
        agreement_box.setFocusPolicy(Qt.NoFocus)
        agreement_box.setStyleSheet(text_edit_stylesheet())
        agreement_box.setHtml(
            """
            <div style="font-family:'Microsoft YaHei UI'; line-height:1.65;">
              <p style="margin:0 0 12px 0; color:#F3F8FF; font-size:14px;">
                在继续使用本程序前，请你确认已经完整阅读并理解以下条款。点击“同意协议并开始”即视为你自愿接受全部内容。
              </p>
              <p style="margin:10px 0 6px 0; color:#FFFFFF; font-size:15px; font-weight:700;">1. 用途说明</p>
              <p style="margin:0 0 10px 0; color:#9AB0CA; font-size:13px;">
                本程序仅用于图像识别、自动化控制流程学习与个人技术研究，不提供任何官方授权。请勿用于商业牟利、批量传播、代练代刷或其他破坏游戏公平性的用途。若你仅为测试或学习，请在下载、复制或接触本程序后的 24 小时内自行删除全部文件与副本。
              </p>
              <p style="margin:10px 0 6px 0; color:#FFFFFF; font-size:15px; font-weight:700;">2. 实现逻辑说明</p>
              <p style="margin:0 0 10px 0; color:#9AB0CA; font-size:13px;">
                本程序当前采用屏幕截图、模板识别、窗口前台控制和键盘按键模拟等方式工作，用于识别钓鱼界面并触发对应操作。程序设计目标是不直接访问游戏内存、不注入 DLL、不加载驱动，也不修改游戏资源文件。
              </p>
              <p style="margin:10px 0 6px 0; color:#FFFFFF; font-size:15px; font-weight:700;">3. 风险提示</p>
              <p style="margin:0 0 10px 0; color:#9AB0CA; font-size:13px;">
                即使本程序未主动访问游戏内存，也不能保证不会被游戏、平台或安全系统识别为异常自动化行为。使用本程序可能导致包括但不限于警告、限制、收益回收、临时封禁、永久封禁、账号异常、设备环境标记等风险。该类风险始终由使用者自行判断并承担。
              </p>
              <p style="margin:10px 0 6px 0; color:#FFFFFF; font-size:15px; font-weight:700;">4. 法律与协议责任</p>
              <p style="margin:0 0 10px 0; color:#9AB0CA; font-size:13px;">
                你应自行确认所在地区法律法规、平台规则、游戏用户协议及社区规范是否允许此类工具存在或使用。若因安装、传播、改造、二次分发或实际运行本程序而引发任何法律纠纷、平台处罚、账号损失、设备损害或第三方索赔，责任均由实际使用者承担。
              </p>
              <p style="margin:10px 0 6px 0; color:#FFFFFF; font-size:15px; font-weight:700;">5. 使用者承诺</p>
              <p style="margin:0 0 10px 0; color:#9AB0CA; font-size:13px;">
                你承诺仅在知情、自愿、可承担后果的前提下使用本程序；不会将其包装为收费产品、不会冒充官方工具、不会将其用于任何违法违规或侵害他人权益的行为；若你不同意本协议中的任一条款，请立即退出程序并停止使用。
              </p>
            </div>
            """
        )
        layout.addWidget(agreement_box, 1)

        footer = QHBoxLayout()
        footer.setSpacing(12)

        self.countdown_label = QLabel("请阅读协议后继续")
        self.countdown_label.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text_soft']}; font-size: 12px;"
        )
        footer.addWidget(self.countdown_label, 1, Qt.AlignVCenter)

        self.exit_button = QPushButton("退出程序")
        self.exit_button.setFocusPolicy(Qt.NoFocus)
        self.exit_button.setStyleSheet(secondary_button_stylesheet())
        self.exit_button.clicked.connect(self._reject_dialog)
        footer.addWidget(self.exit_button)

        self.accept_button = QPushButton()
        self.accept_button.setFocusPolicy(Qt.NoFocus)
        self.accept_button.setEnabled(False)
        self.accept_button.setStyleSheet(primary_button_stylesheet())
        self.accept_button.clicked.connect(self.accept)
        footer.addWidget(self.accept_button)
        layout.addLayout(footer)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(1000)
        self._update_accept_text()

    def _update_accept_text(self):
        if self.seconds_left > 0:
            self.accept_button.setText(f"同意协议并开始（{self.seconds_left}s）")
            self.countdown_label.setText("请先阅读风险说明，按钮将在倒计时结束后启用。")
        else:
            self.accept_button.setText("同意协议并开始")
            self.countdown_label.setText("点击按钮即表示你已阅读并同意以上全部内容。")

    def _tick(self):
        self.seconds_left -= 1
        if self.seconds_left <= 0:
            self.seconds_left = 0
            self.timer.stop()
            self.accept_button.setEnabled(True)
        self._update_accept_text()

    def _reject_dialog(self):
        self._allow_reject = True
        super().reject()

    def reject(self):
        if self._allow_reject:
            super().reject()


class OpenSourceWarningDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._allow_reject = False

        self.setModal(True)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.resize(820, 520)

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(0)

        shell = QFrame()
        shell.setStyleSheet(
            """
            QFrame {
                background-color: rgba(17, 21, 30, 0.98);
                border: 1px solid rgba(255, 112, 112, 0.32);
                border-radius: 30px;
            }
            """
        )
        add_shadow(shell, blur=34, alpha=140, offset=(0, 14))
        root.addWidget(shell)

        layout = QVBoxLayout(shell)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        title = QLabel("严正提醒")
        title.setStyleSheet(
            "background: transparent; border: none; color: #FFFFFF; font-size: 32px; font-weight: 900;"
        )
        layout.addWidget(title)

        warning_chip = QLabel("本程序开源免费发布")
        warning_chip.setStyleSheet(
            """
            QLabel {
                background-color: rgba(255, 102, 126, 0.14);
                color: #FF99A7;
                border: 1px solid rgba(255, 102, 126, 0.36);
                border-radius: 15px;
                padding: 7px 14px;
                font-size: 12px;
                font-weight: 900;
            }
            """
        )
        layout.addWidget(warning_chip, 0, Qt.AlignLeft)

        content = QTextEdit()
        content.setReadOnly(True)
        content.setFocusPolicy(Qt.NoFocus)
        content.setStyleSheet(text_edit_stylesheet())
        content.setHtml(
            """
            <div style="font-family:'Microsoft YaHei UI'; line-height:1.7;">
              <p style="margin:0 0 12px 0; color:#FFFFFF; font-size:15px; font-weight:800;">
                本程序为开源项目，永久免费发布。
              </p>
              <p style="margin:0 0 12px 0; color:#FFB4BC; font-size:14px; font-weight:700;">
                任何通过付费渠道、卡密渠道、代下渠道、网盘贩卖、二手转卖、打包收费等方式向你提供本程序的行为，均属于非法传播或恶意牟利。
              </p>
              <p style="margin:0 0 10px 0; color:#9AB0CA; font-size:13px;">
                如果你是付费获得本程序，请立即停止继续向对方付款，并尽快申请退款、投诉或维权。你的权益已经受到侵害，出售者并不具备合法收费授权。
              </p>
              <p style="margin:0 0 10px 0; color:#9AB0CA; font-size:13px;">
                请仅从下方开源地址获取最新版本，避免下载被二次打包、植入风险代码或篡改内容的文件：
              </p>
              <p style="margin:6px 0 0 0; color:#67EAEC; font-size:13px; font-weight:800;">
                https://github.com/FADEDTUMI/YHoAutoFish
              </p>
            </div>
            """
        )
        layout.addWidget(content, 1)

        footer = QHBoxLayout()
        footer.setSpacing(12)

        link_button = QPushButton("打开开源地址")
        link_button.setFocusPolicy(Qt.NoFocus)
        link_button.setStyleSheet(secondary_button_stylesheet())
        link_button.clicked.connect(
            lambda: QDesktopServices.openUrl(QUrl("https://github.com/FADEDTUMI/YHoAutoFish"))
        )
        footer.addWidget(link_button)

        footer.addStretch()

        exit_button = QPushButton("退出程序")
        exit_button.setFocusPolicy(Qt.NoFocus)
        exit_button.setStyleSheet(secondary_button_stylesheet())
        exit_button.clicked.connect(self._reject_dialog)
        footer.addWidget(exit_button)

        accept_button = QPushButton("我已知晓，继续使用")
        accept_button.setFocusPolicy(Qt.NoFocus)
        accept_button.setStyleSheet(primary_button_stylesheet())
        accept_button.clicked.connect(self.accept)
        footer.addWidget(accept_button)

        layout.addLayout(footer)

    def _reject_dialog(self):
        self._allow_reject = True
        super().reject()

    def reject(self):
        if self._allow_reject:
            super().reject()


class AppWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("异环自动钓鱼")
        self.resize(1420, 920)
        self.setMinimumSize(1200, 760)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.config = {
            "hold_threshold": 25,
            "deadzone_threshold": 10,
            "fishing_timeout": 180,
            "cast_animation_delay": 2,
            "settlement_close_delay": 2,
            "bar_missing_timeout": 2,
            "log_line_limit": 320,
            "auto_switch_to_log": True,
            "debug_mode": False,
        }
        self.load_config()

        self.log_queue = queue.Queue()
        self.debug_queue = queue.Queue()
        self.log_deque = deque(maxlen=int(self.config.get("log_line_limit", 320)))
        self.sm = StateMachine(log_queue=self.log_queue, debug_queue=self.debug_queue)
        self._agreement_shown = False
        self.floating_window = None
        self.modules_ready = False
        self.modules_initializing = False
        self.init_animation_step = 0
        self.ocr_init_worker = None

        self.init_ui()
        self._sync_runtime_preferences()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_queue)
        self.timer.start(60)

        self.init_animation_timer = QTimer(self)
        self.init_animation_timer.timeout.connect(self._tick_init_animation)

    def load_config(self):
        if not os.path.exists(CONFIG_FILE):
            return
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as file:
                self.config.update(json.load(file))
        except Exception as exc:
            print(f"Config load error: {exc}")

    def save_config(self):
        try:
            with open(CONFIG_FILE, "w", encoding="utf-8") as file:
                json.dump(self.config, file, ensure_ascii=False, indent=4)
            self._sync_runtime_preferences()
            self.write_log("[配置] 高级设置已保存。")
            return True
        except Exception as exc:
            self.write_log(f"[配置] 保存失败: {exc}")
            return False

    def _sync_runtime_preferences(self):
        self.config["log_line_limit"] = int(self.config.get("log_line_limit", 320))
        self.log_deque = deque(self.log_deque, maxlen=self.config["log_line_limit"])
        if hasattr(self, "log_textbox"):
            self.log_textbox.setText("\n".join(self.log_deque))
        self._apply_state_machine_config()
        self._refresh_debug_view_state()
        if self.floating_window is not None:
            self.floating_window.refresh_state()

    def _apply_state_machine_config(self):
        self.sm.update_config("t_hold", self.config.get("hold_threshold", 25))
        self.sm.update_config("t_deadzone", self.config.get("deadzone_threshold", 10))
        self.sm.update_config("fishing_timeout", self.config.get("fishing_timeout", 180))
        self.sm.update_config("cast_animation_delay", self.config.get("cast_animation_delay", 2))
        self.sm.update_config("settlement_close_delay", self.config.get("settlement_close_delay", 2))
        self.sm.update_config("bar_missing_timeout", self.config.get("bar_missing_timeout", 2))
        self.sm.update_config("debug_mode", self.config.get("debug_mode", False))

    def _refresh_debug_view_state(self):
        if not hasattr(self, "debug_preview"):
            return

        if self.config.get("debug_mode", False):
            self.debug_state_label.setText("调试溜鱼视图已开启")
            if self.debug_preview.pixmap() is None:
                self.debug_preview.setText("等待溜鱼画面...")
            self.debug_help_label.setText("开始钓鱼后将实时显示识别到的绿条、黄条与中心位置。")
        else:
            self.debug_state_label.setText("调试溜鱼视图未开启")
            self.debug_preview.clear()
            self.debug_preview.setText("当前未开启")
            self.debug_help_label.setText("如需反馈识别问题，请在高级设置中开启调试溜鱼视图后再复现问题。")

    def _set_debug_frame(self, frame):
        if not hasattr(self, "debug_preview"):
            return
        if frame is None or not self.config.get("debug_mode", False):
            return

        rgb_frame = frame[:, :, ::-1].copy()
        height, width, channel = rgb_frame.shape
        image = QImage(rgb_frame.data, width, height, channel * width, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(image).scaled(
            self.debug_preview.size(),
            Qt.KeepAspectRatio,
            Qt.SmoothTransformation,
        )
        self.debug_preview.setPixmap(pixmap)
        if self.floating_window is not None and self.floating_window.isVisible():
            self.floating_window.set_debug_frame(frame)

    def init_ui(self):
        central = QWidget()
        central.setStyleSheet("background: transparent;")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(0)

        self.shell = BackdropFrame()
        shell_layout = QVBoxLayout(self.shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)
        root.addWidget(self.shell)

        self.title_bar = CustomTitleBar(self)
        shell_layout.addWidget(self.title_bar)

        content = QWidget()
        content.setStyleSheet(
            """
            QWidget {
                background: transparent;
                border-bottom-left-radius: 32px;
                border-bottom-right-radius: 32px;
            }
            """
        )
        content_layout = QHBoxLayout(content)
        content_layout.setContentsMargins(18, 18, 18, 18)
        content_layout.setSpacing(18)
        shell_layout.addWidget(content, 1)

        self.sidebar = self._build_sidebar()
        content_layout.addWidget(self.sidebar)

        self.stack = QStackedWidget()
        self.stack.setStyleSheet("QStackedWidget { background: transparent; }")
        content_layout.addWidget(self.stack, 1)

        self.page_record = FishingRecordWidget(self.sm.record_mgr)
        self.page_encyclopedia = None
        self.page_encyclopedia_placeholder = QWidget()
        self.page_encyclopedia_placeholder.setStyleSheet("background: transparent;")
        self.page_log = self._build_log_page()
        self.page_settings = self._build_settings_page()

        self.stack.addWidget(self.page_record)
        self.stack.addWidget(self.page_encyclopedia_placeholder)
        self.stack.addWidget(self.page_log)
        self.stack.addWidget(self.page_settings)
        self.switch_page(0, self.nav_record)

        self.toast = ToastPopup(self)
        self.update_primary_buttons()

    def _ensure_encyclopedia_page(self):
        if self.page_encyclopedia is not None:
            return self.page_encyclopedia

        page = EncyclopediaWidget(self.sm.record_mgr)
        placeholder_index = self.stack.indexOf(self.page_encyclopedia_placeholder)
        if placeholder_index < 0:
            placeholder_index = 1
        self.stack.removeWidget(self.page_encyclopedia_placeholder)
        self.page_encyclopedia_placeholder.deleteLater()
        self.stack.insertWidget(placeholder_index, page)
        self.page_encyclopedia = page
        return page

    def toggle_maximize_restore(self):
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        if hasattr(self, "title_bar"):
            self.title_bar.sync_state()

    def changeEvent(self, event):
        super().changeEvent(event)
        if hasattr(self, "title_bar"):
            self.title_bar.sync_state()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._agreement_shown:
            self._agreement_shown = True
            QTimer.singleShot(120, self.show_usage_agreement)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "toast") and self.toast.isVisible():
            self.toast.reposition()

    def closeEvent(self, event):
        if self.floating_window is not None:
            self.floating_window.close()
        super().closeEvent(event)

    def show_usage_agreement(self):
        self.agreement_dialog = UsageAgreementDialog(self)
        dialog = self.agreement_dialog
        dialog.finished.connect(self._handle_agreement_result)
        dialog.move(self.geometry().center() - dialog.rect().center())
        dialog.open()

    def _handle_agreement_result(self, result):
        if result != QDialog.Accepted:
            self.close()
            return
        self.show_open_source_warning()

    def show_open_source_warning(self):
        self.source_warning_dialog = OpenSourceWarningDialog(self)
        dialog = self.source_warning_dialog
        dialog.finished.connect(self._handle_source_warning_result)
        dialog.move(self.geometry().center() - dialog.rect().center())
        dialog.open()

    def _handle_source_warning_result(self, result):
        if result != QDialog.Accepted:
            self.close()

    def show_toast(self, text, tone="info"):
        if hasattr(self, "toast"):
            self.toast.show_message(text, tone)

    def init_button_text(self, prefix="初始化模块"):
        dots = "." * ((self.init_animation_step % 3) + 1)
        return f"{prefix}{dots}"

    def update_primary_buttons(self):
        running = self.sm.is_running
        if self.modules_initializing:
            self.btn_start.setText(self.init_button_text("初始化模块"))
            self.btn_start.setEnabled(False)
        elif self.modules_ready:
            self.btn_start.setText("开始钓鱼")
            self.btn_start.setEnabled(not running)
        else:
            self.btn_start.setText("初始化模块")
            self.btn_start.setEnabled(not running)
        self.btn_stop.setEnabled(running)
        if self.floating_window is not None:
            self.floating_window.refresh_state()

    def _tick_init_animation(self):
        self.init_animation_step += 1
        self.update_primary_buttons()

    def handle_primary_action(self):
        if self.sm.is_running:
            return
        if not self.modules_ready:
            self.start_module_initialization()
            return
        self.start_bot()

    def start_module_initialization(self):
        if self.modules_ready:
            self.update_primary_buttons()
            return
        if self.modules_initializing:
            return
        self.modules_initializing = True
        self.init_animation_step = 0
        self.init_animation_timer.start(360)
        self.update_primary_buttons()
        self.write_log("[系统] 开始初始化鱼名与重量 OCR 识别模块...")
        self.show_toast("正在初始化识别模块", "info")

        self.ocr_init_worker = RecognitionInitWorker(self.sm, self)
        self.ocr_init_worker.completed.connect(self._handle_module_init_result)
        self.ocr_init_worker.finished.connect(self.ocr_init_worker.deleteLater)
        self.ocr_init_worker.start()

    def _handle_module_init_result(self, ok, message):
        self.init_animation_timer.stop()
        self.modules_initializing = False
        self.modules_ready = bool(ok)
        self.update_primary_buttons()
        self.write_log(f"[系统] {message}")
        self.show_toast(message, "success" if ok else "danger")
        self.ocr_init_worker = None

    def show_usage_policy(self):
        html = """
        <div style="font-family:'Microsoft YaHei UI'; line-height:1.72;">
          <p style="color:#F3F8FF; font-size:14px; font-weight:800;">使用范围</p>
          <p style="color:#9AB0CA; font-size:13px;">本程序仅用于图像识别、自动化控制流程学习与个人技术研究。请勿用于商业牟利、代练代刷、批量传播或破坏游戏公平性的用途。</p>
          <p style="color:#F3F8FF; font-size:14px; font-weight:800;">实现方式</p>
          <p style="color:#9AB0CA; font-size:13px;">程序通过屏幕截图、模板识别、OCR 与键盘模拟完成自动钓鱼流程，不主动读取或修改游戏内存，不注入 DLL，不修改游戏资源文件。</p>
          <p style="color:#F3F8FF; font-size:14px; font-weight:800;">风险说明</p>
          <p style="color:#9AB0CA; font-size:13px;">即使未访问游戏内存，自动化行为仍可能被平台风控识别。由此产生的警告、限制、封禁、账号异常或其他损失，均由使用者自行承担。</p>
          <p style="color:#F3F8FF; font-size:14px; font-weight:800;">学习声明</p>
          <p style="color:#9AB0CA; font-size:13px;">如仅为测试或学习，请在下载、复制或接触本程序后的 24 小时内自行删除全部文件与副本。</p>
        </div>
        """
        dialog = PolicyDialog("用户协议", "查看程序使用范围、实现方式与风险提示。", html, self)
        dialog.move(self.geometry().center() - dialog.rect().center())
        dialog.exec()

    def show_anti_infringement_policy(self):
        html = """
        <div style="font-family:'Microsoft YaHei UI'; line-height:1.72;">
          <p style="color:#FFB4BC; font-size:15px; font-weight:900;">本程序开源免费发布，任何付费出售、卡密售卖、网盘倒卖、二次打包收费均不是作者授权行为。</p>
          <p style="color:#9AB0CA; font-size:13px;">如果你从付费渠道获得本程序，说明你的权益可能已经受到侵犯。请停止继续付款，尽快申请退款、投诉或维权。</p>
          <p style="color:#F3F8FF; font-size:14px; font-weight:800;">唯一建议来源</p>
          <p style="color:#67EAEC; font-size:13px; font-weight:800;">https://github.com/FADEDTUMI/YHoAutoFish</p>
          <p style="color:#9AB0CA; font-size:13px;">从非开源渠道下载的文件可能被植入风险代码、篡改配置或夹带无关内容。请优先从开源仓库获取并核对项目说明。</p>
        </div>
        """
        dialog = PolicyDialog("反侵权协议", "提醒用户识别非法付费传播，保护自己的下载与使用权益。", html, self)
        dialog.move(self.geometry().center() - dialog.rect().center())
        dialog.exec()

    def toggle_floating_window(self):
        if self.floating_window is None:
            self.floating_window = FloatingControlWindow(self)

        if self.floating_window.isVisible():
            self.floating_window.hide()
            self.float_toggle_btn.setText("悬浮窗")
            return

        self.floating_window.refresh_state()
        self.floating_window.show()
        self.floating_window.raise_()
        self.floating_window.position_near_game()
        self.float_toggle_btn.setText("隐藏")

    def _build_sidebar(self):
        panel = QFrame()
        panel.setFixedWidth(294)
        panel.setStyleSheet(
            """
            QFrame {
                background-color: rgba(10, 20, 35, 0.70);
                border: 1px solid rgba(62, 92, 123, 0.22);
                border-radius: 32px;
            }
            """
        )
        add_shadow(panel, blur=34, alpha=110, offset=(0, 12))

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)

        logo_card = LogoImageCard()
        add_shadow(logo_card, blur=24, alpha=96, offset=(0, 10))
        layout.addWidget(logo_card, 0, Qt.AlignHCenter)

        nav_panel = QFrame()
        nav_panel.setStyleSheet(
            """
            QFrame {
                background-color: rgba(18, 29, 44, 0.58);
                border: 1px solid rgba(111, 145, 182, 0.14);
                border-radius: 26px;
            }
            """
        )
        nav_layout = QVBoxLayout(nav_panel)
        nav_layout.setContentsMargins(12, 12, 12, 12)
        nav_layout.setSpacing(8)

        self.nav_record = NavButton("钓鱼记录")
        self.nav_encyclopedia = NavButton("图鉴记录")
        self.nav_log = NavButton("运行日志")
        self.nav_settings = NavButton("高级设置")

        self.nav_record.clicked.connect(lambda: self.switch_page(0, self.nav_record))
        self.nav_encyclopedia.clicked.connect(lambda: self.switch_page(1, self.nav_encyclopedia))
        self.nav_log.clicked.connect(lambda: self.switch_page(2, self.nav_log))
        self.nav_settings.clicked.connect(lambda: self.switch_page(3, self.nav_settings))

        for button in [self.nav_record, self.nav_encyclopedia, self.nav_log, self.nav_settings]:
            nav_layout.addWidget(button)
        layout.addWidget(nav_panel)

        control_panel = QFrame()
        control_panel.setMinimumHeight(238)
        control_panel.setStyleSheet(
            """
            QFrame {
                background-color: rgba(18, 29, 44, 0.66);
                border: 1px solid rgba(111, 145, 182, 0.16);
                border-radius: 26px;
            }
            """
        )
        control_layout = QVBoxLayout(control_panel)
        control_layout.setContentsMargins(18, 18, 18, 18)
        control_layout.setSpacing(12)

        status_title = QLabel("运行状态")
        status_title.setStyleSheet(f"background: transparent; border: none; color: {APP_COLORS['text']}; font-size: 16px; font-weight: 800;")
        control_layout.addWidget(status_title)

        self.status_chip = StatusChip()
        control_layout.addWidget(self.status_chip)

        control_hint = QLabel("可在主程序或游戏内悬浮窗控制开始与停止。")
        control_hint.setWordWrap(True)
        control_hint.setStyleSheet(f"background: transparent; border: none; color: {APP_COLORS['text_soft']}; font-size: 12px;")
        control_layout.addWidget(control_hint)

        self.btn_start = QPushButton("开始钓鱼")
        self.btn_start.setMinimumHeight(44)
        self.btn_start.setFocusPolicy(Qt.NoFocus)
        self.btn_start.setStyleSheet(primary_button_stylesheet())
        self.btn_start.clicked.connect(self.handle_primary_action)
        control_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("停止运行")
        self.btn_stop.setMinimumHeight(42)
        self.btn_stop.setFocusPolicy(Qt.NoFocus)
        self.btn_stop.setStyleSheet(secondary_button_stylesheet())
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_bot)
        control_layout.addWidget(self.btn_stop)
        layout.addWidget(control_panel)

        layout.addStretch()

        author_panel = QFrame()
        author_panel.setMinimumHeight(96)
        author_panel.setStyleSheet(
            """
            QFrame {
                background-color: rgba(18, 29, 44, 0.52);
                border: 1px solid rgba(111, 145, 182, 0.14);
                border-radius: 20px;
            }
            """
        )
        author_layout = QHBoxLayout(author_panel)
        author_layout.setContentsMargins(12, 12, 12, 12)
        author_layout.setSpacing(8)

        author_text_col = QVBoxLayout()
        author_text_col.setSpacing(5)
        author_text_col.setContentsMargins(0, 0, 0, 0)

        author = QLabel("作者：FADEDTUMI")
        author.setStyleSheet(f"background: transparent; border: none; color: {APP_COLORS['text_dim']}; font-size: 12px; font-weight: 700;")
        author_text_col.addWidget(author)

        author_note = QLabel("开源免费 · 学习研究用途")
        author_note.setStyleSheet(f"background: transparent; border: none; color: {APP_COLORS['text_soft']}; font-size: 11px;")
        author_text_col.addWidget(author_note)

        link_row = QHBoxLayout()
        link_row.setSpacing(4)

        github = QPushButton("GitHub")
        github.setCursor(Qt.PointingHandCursor)
        github.setFocusPolicy(Qt.NoFocus)
        github.setStyleSheet(
            f"""
            QPushButton {{
                background: transparent;
                color: {APP_COLORS['accent_soft']};
                border: none;
                text-align: left;
                padding: 0;
                font-size: 12px;
                font-weight: 800;
            }}
            QPushButton:hover {{
                color: {APP_COLORS['text']};
            }}
            """
        )
        github.clicked.connect(lambda: QDesktopServices.openUrl(QUrl("https://github.com/FADEDTUMI")))
        github.setFixedWidth(50)
        link_row.addWidget(github, 0, Qt.AlignLeft)

        agreement = QPushButton("用户协议")
        agreement.setCursor(Qt.PointingHandCursor)
        agreement.setFocusPolicy(Qt.NoFocus)
        agreement.setStyleSheet(github.styleSheet())
        agreement.setFixedWidth(52)
        agreement.clicked.connect(self.show_usage_policy)
        link_row.addWidget(agreement, 0, Qt.AlignLeft)

        anti_abuse = QPushButton("反侵权")
        anti_abuse.setCursor(Qt.PointingHandCursor)
        anti_abuse.setFocusPolicy(Qt.NoFocus)
        anti_abuse.setStyleSheet(github.styleSheet())
        anti_abuse.setFixedWidth(42)
        anti_abuse.clicked.connect(self.show_anti_infringement_policy)
        link_row.addWidget(anti_abuse, 0, Qt.AlignLeft)
        link_row.addStretch()
        author_text_col.addLayout(link_row)
        author_layout.addLayout(author_text_col, 1)

        self.float_toggle_btn = QPushButton("悬浮窗")
        self.float_toggle_btn.setFixedSize(62, 56)
        self.float_toggle_btn.setCursor(Qt.PointingHandCursor)
        self.float_toggle_btn.setFocusPolicy(Qt.NoFocus)
        self.float_toggle_btn.setStyleSheet(
            f"""
            QPushButton {{
                background-color: rgba(22, 209, 214, 0.10);
                color: {APP_COLORS['accent_soft']};
                border: 1px solid rgba(22, 209, 214, 0.34);
                border-radius: 18px;
                font-size: 12px;
                font-weight: 900;
            }}
            QPushButton:hover {{
                background-color: rgba(22, 209, 214, 0.20);
                color: {APP_COLORS['text']};
            }}
            """
        )
        self.float_toggle_btn.clicked.connect(self.toggle_floating_window)
        author_layout.addWidget(self.float_toggle_btn, 0, Qt.AlignRight | Qt.AlignVCenter)
        layout.addWidget(author_panel)
        return panel

    def _build_log_page(self):
        page = QFrame()
        page.setProperty("variant", "elevated")
        page.setStyleSheet(panel_stylesheet())

        layout = QVBoxLayout(page)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        title = QLabel("运行日志")
        title.setProperty("role", "headline")
        layout.addWidget(title)

        subtitle = QLabel("查看自动钓鱼的实时状态、异常提示与关键步骤输出。")
        subtitle.setProperty("role", "subtle")
        layout.addWidget(subtitle)

        content_row = QHBoxLayout()
        content_row.setSpacing(18)

        self.log_textbox = QTextEdit()
        self.log_textbox.setReadOnly(True)
        self.log_textbox.setStyleSheet(text_edit_stylesheet())
        self.log_textbox.append("--- 异环自动钓鱼初始化完成 ---\n请确保游戏窗口处于可操作状态。")
        content_row.addWidget(self.log_textbox, 5)

        debug_panel = QFrame()
        debug_panel.setProperty("variant", "soft")
        debug_panel.setStyleSheet(panel_stylesheet())
        add_shadow(debug_panel, blur=20, alpha=85, offset=(0, 8))
        debug_panel.setFixedWidth(340)

        debug_layout = QVBoxLayout(debug_panel)
        debug_layout.setContentsMargins(16, 16, 16, 16)
        debug_layout.setSpacing(10)

        debug_title = QLabel("调试溜鱼视图")
        debug_title.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text']}; font-size: 16px; font-weight: 800;"
        )
        debug_layout.addWidget(debug_title)

        debug_note = QLabel("用于回看溜鱼阶段识别到的绿条、黄条位置，方便定位识别问题。")
        debug_note.setWordWrap(True)
        debug_note.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text_dim']}; font-size: 12px;"
        )
        debug_layout.addWidget(debug_note)

        self.debug_state_label = QLabel()
        self.debug_state_label.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['accent_soft']}; font-size: 12px; font-weight: 700;"
        )
        debug_layout.addWidget(self.debug_state_label)

        self.debug_preview = QLabel()
        self.debug_preview.setAlignment(Qt.AlignCenter)
        self.debug_preview.setMinimumSize(300, 118)
        self.debug_preview.setStyleSheet(
            """
            background-color: rgba(8, 15, 24, 0.78);
            border: 1px solid rgba(87, 119, 153, 0.18);
            border-radius: 18px;
            """
        )
        debug_layout.addWidget(self.debug_preview)

        self.debug_help_label = QLabel()
        self.debug_help_label.setWordWrap(True)
        self.debug_help_label.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text_soft']}; font-size: 12px;"
        )
        debug_layout.addWidget(self.debug_help_label)
        debug_layout.addStretch()

        content_row.addWidget(debug_panel, 2)
        layout.addLayout(content_row, 1)
        self._refresh_debug_view_state()
        return page

    def _build_settings_page(self):
        container = QScrollArea()
        container.setWidgetResizable(True)
        container.setStyleSheet(scroll_area_stylesheet())
        container.viewport().setStyleSheet("background: transparent;")
        container.viewport().setAutoFillBackground(False)

        page = QWidget()
        page.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        content = QFrame()
        content.setProperty("variant", "elevated")
        content.setStyleSheet(panel_stylesheet())
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(28, 24, 28, 28)
        content_layout.setSpacing(18)

        title = QLabel("高级设置")
        title.setProperty("role", "headline")
        content_layout.addWidget(title)

        subtitle = QLabel("调整自动钓鱼运行保护、日志展示、调试视图等常用选项。")
        subtitle.setProperty("role", "subtle")
        content_layout.addWidget(subtitle)

        self.slider_hold = self._settings_block(
            content_layout,
            "跟鱼力度",
            "数值越大，跟鱼时按键会更积极；如出现跟随过猛或过慢，可在此调整。",
            self.config.get("hold_threshold", 25),
            10,
            50,
            "hold_threshold",
        )
        self.slider_deadzone = self._settings_block(
            content_layout,
            "跟鱼死区",
            "数值越小，鱼漂偏离时越快按键追赶；过低可能导致左右频繁抖动。",
            self.config.get("deadzone_threshold", 10),
            2,
            20,
            "deadzone_threshold",
        )
        self.slider_timeout = self._settings_block(
            content_layout,
            "防卡死超时",
            "单次钓鱼等待超过该时长时自动重置，避免界面停在异常状态。",
            self.config.get("fishing_timeout", 180),
            60,
            300,
            "fishing_timeout",
        )
        self.slider_bar_missing = self._settings_block(
            content_layout,
            "耐力条丢失容忍",
            "耐力条短暂识别不到时等待的秒数；画面抖动或帧率低可适当调大。",
            self.config.get("bar_missing_timeout", 2),
            1,
            5,
            "bar_missing_timeout",
        )
        self.slider_cast_delay = self._settings_block(
            content_layout,
            "抛竿动画等待",
            "按下抛竿键后等待动画完成的秒数；机器或网络较慢时可适当调大。",
            self.config.get("cast_animation_delay", 2),
            1,
            5,
            "cast_animation_delay",
        )
        self.slider_close_delay = self._settings_block(
            content_layout,
            "结算关闭等待",
            "捕获后按 ESC 关闭结算界面，再等待回到可抛竿状态的秒数。",
            self.config.get("settlement_close_delay", 2),
            1,
            5,
            "settlement_close_delay",
        )
        self.slider_log_limit = self._settings_block(
            content_layout,
            "日志保留条数",
            "控制运行日志页保留的最近输出数量，数值越大可回看更多记录。",
            self.config.get("log_line_limit", 320),
            120,
            800,
            "log_line_limit",
        )
        self.auto_log_button = self._settings_toggle_block(
            content_layout,
            "启动后跳转运行日志",
            "开启后，点击开始钓鱼会自动切换到运行日志页，方便观察实时状态。",
            self.config.get("auto_switch_to_log", True),
            "auto_switch_to_log",
        )
        self.debug_view_button = self._settings_toggle_block(
            content_layout,
            "调试溜鱼视图",
            "开启后，运行日志页会显示溜鱼阶段的实时识别画面，便于排查识别异常与反馈问题。",
            self.config.get("debug_mode", False),
            "debug_mode",
        )

        save_btn = QPushButton("保存并应用设置")
        save_btn.setFocusPolicy(Qt.NoFocus)
        save_btn.setStyleSheet(primary_button_stylesheet())
        save_btn.clicked.connect(self._save_settings)
        content_layout.addWidget(save_btn)
        content_layout.addStretch()

        layout.addWidget(content)
        container.setWidget(page)
        return container

    def _settings_panel(self):
        block = QFrame()
        block.setProperty("variant", "soft")
        block.setStyleSheet(panel_stylesheet())
        add_shadow(block, blur=20, alpha=85, offset=(0, 8))
        return block

    def _settings_block(self, parent_layout, title, note, value, minimum, maximum, key):
        block = self._settings_panel()

        layout = QVBoxLayout(block)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(10)

        top = QHBoxLayout()
        title_label = QLabel(title)
        title_label.setStyleSheet(f"background: transparent; border: none; color: {APP_COLORS['text']}; font-size: 16px; font-weight: 800;")
        top.addWidget(title_label)
        top.addStretch()

        value_label = QLabel(str(int(value)))
        value_label.setStyleSheet(
            f"""
            QLabel {{
                color: {APP_COLORS['accent_soft']};
                background-color: rgba(29, 208, 214, 0.10);
                border: 1px solid rgba(29, 208, 214, 0.22);
                border-radius: 14px;
                padding: 6px 10px;
                font-size: 18px;
                font-weight: 900;
            }}
            """
        )
        top.addWidget(value_label)
        layout.addLayout(top)

        note_label = QLabel(note)
        note_label.setStyleSheet(f"background: transparent; border: none; color: {APP_COLORS['text_dim']}; font-size: 12px;")
        layout.addWidget(note_label)

        slider = NoWheelSlider(Qt.Horizontal)
        slider.setRange(minimum, maximum)
        slider.setValue(int(value))
        slider.setFocusPolicy(Qt.NoFocus)
        slider.setStyleSheet(
            f"""
            QSlider::groove:horizontal {{
                background-color: rgba(255, 255, 255, 0.08);
                border-radius: 5px;
                height: 10px;
            }}
            QSlider::sub-page:horizontal {{
                background-color: rgba(29, 208, 214, 0.82);
                border-radius: 5px;
                height: 10px;
            }}
            QSlider::handle:horizontal {{
                background-color: #B8FFFF;
                border: 2px solid rgba(29, 208, 214, 0.92);
                width: 16px;
                margin: -4px 0;
                border-radius: 8px;
            }}
            """
        )
        slider.valueChanged.connect(lambda new_value, label=value_label, config_key=key: self._update_slider_value(label, config_key, new_value))
        layout.addWidget(slider)
        parent_layout.addWidget(block)
        return slider

    def _settings_toggle_block(self, parent_layout, title, note, checked, key):
        block = self._settings_panel()
        layout = QHBoxLayout(block)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(14)

        text_col = QVBoxLayout()
        text_col.setSpacing(6)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text']}; font-size: 16px; font-weight: 800;"
        )
        text_col.addWidget(title_label)

        note_label = QLabel(note)
        note_label.setWordWrap(True)
        note_label.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text_dim']}; font-size: 12px;"
        )
        text_col.addWidget(note_label)
        layout.addLayout(text_col, 1)

        button = QPushButton()
        button.setCheckable(True)
        button.setFocusPolicy(Qt.NoFocus)
        button.setChecked(bool(checked))
        button.setStyleSheet(secondary_button_stylesheet())
        button.toggled.connect(
            lambda is_checked, cfg_key=key, btn=button: self._update_toggle_value(btn, cfg_key, is_checked)
        )
        self._update_toggle_value(button, key, bool(checked))
        layout.addWidget(button)

        parent_layout.addWidget(block)
        return button

    def _update_slider_value(self, label, key, value):
        label.setText(str(int(value)))
        self.config[key] = int(value)

    def _update_toggle_value(self, button, key, checked):
        self.config[key] = bool(checked)
        button.setText("已开启" if checked else "已关闭")

    def _save_settings(self):
        self._apply_state_machine_config()
        if self.save_config():
            self.show_toast("高级设置已保存并应用", "success")
        else:
            self.show_toast("设置保存失败，请查看运行日志", "danger")

    def switch_page(self, index, button):
        for nav in [self.nav_record, self.nav_encyclopedia, self.nav_log, self.nav_settings]:
            nav.setChecked(False)
        button.setChecked(True)
        if index == 1:
            self._ensure_encyclopedia_page()
        self.stack.setCurrentIndex(index)
        if index == 0:
            self.page_record.refresh_data()
        elif index == 1:
            self.page_encyclopedia.refresh_data()

    def write_log(self, msg):
        if msg == "CMD_STOP_UPDATE_GUI":
            self.update_ui_on_stop()
            return

        import time

        line = f"[{time.strftime('%H:%M:%S')}] {msg}"
        self.log_deque.append(line)
        self.log_textbox.setText("\n".join(self.log_deque))
        self.log_textbox.verticalScrollBar().setValue(self.log_textbox.verticalScrollBar().maximum())

    def process_queue(self):
        try:
            while True:
                self.write_log(self.log_queue.get_nowait())
        except queue.Empty:
            pass

        latest_debug_frame = None
        try:
            while True:
                latest_debug_frame = self.debug_queue.get_nowait()
        except queue.Empty:
            pass
        if latest_debug_frame is not None:
            self._set_debug_frame(latest_debug_frame)

    def start_bot(self):
        if self.sm.is_running:
            return
        if not self.modules_ready:
            self.start_module_initialization()
            return

        self._apply_state_machine_config()

        self.status_chip.set_status("运行中", "running")
        if self.config.get("auto_switch_to_log", True):
            self.switch_page(2, self.nav_log)
        self.write_log(">>> 启动自动钓鱼。")
        self.sm.start()
        self.update_primary_buttons()
        self.show_toast("自动钓鱼已启动", "success")

    def stop_bot(self):
        if not self.sm.is_running:
            self.show_toast("当前未在运行", "warning")
            return
        self.sm.stop()
        self.write_log(">>> 已发送停止指令。")
        self.update_ui_on_stop()
        self.show_toast("停止指令已发送", "warning")

    def update_ui_on_stop(self):
        self.status_chip.set_status("已停止", "stopped")
        self.update_primary_buttons()
        if hasattr(self, "debug_preview") and not self.config.get("debug_mode", False):
            self._refresh_debug_view_state()
        self.page_record.refresh_data()
        if self.page_encyclopedia is not None:
            self.page_encyclopedia.refresh_data()
