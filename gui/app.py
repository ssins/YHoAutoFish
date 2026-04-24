import json
import os
import queue
from collections import deque

import keyboard
from PySide6.QtCore import QPoint, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QFont, QMouseEvent, QPainter, QPainterPath, QPen, QLinearGradient, QColor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QScrollArea,
    QSlider,
    QStackedWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from core.state_machine import StateMachine
from gui.encyclopedia import EncyclopediaWidget
from gui.fishing_record import FishingRecordWidget
from gui.theme import (
    APP_COLORS,
    add_shadow,
    line_edit_stylesheet,
    panel_stylesheet,
    primary_button_stylesheet,
    rounded_pixmap,
    scroll_area_stylesheet,
    secondary_button_stylesheet,
    text_edit_stylesheet,
)

CONFIG_FILE = "config.json"


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
    def __init__(self, text, hover_color, parent=None):
        super().__init__(text, parent)
        self.hover_color = hover_color
        self.setFixedSize(42, 32)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFont(QFont("Microsoft YaHei UI", 11, QFont.Bold))
        self.setStyleSheet(
            f"""
            QPushButton {{
                background-color: rgba(255, 255, 255, 0.04);
                color: {APP_COLORS['text_dim']};
                border: 1px solid rgba(111, 145, 182, 0.18);
                outline: none;
                border-radius: 16px;
            }}
            QPushButton:hover {{
                background-color: {hover_color};
                color: {APP_COLORS['text']};
            }}
            """
        )


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

        title = QLabel("异环自动钓鱼")
        title.setStyleSheet(f"background: transparent; border: none; color: {APP_COLORS['text']}; font-size: 14px; font-weight: 900;")
        layout.addWidget(title)
        layout.addStretch()

        self.btn_min = TitleButton("—", "rgba(90, 129, 166, 0.22)")
        self.btn_max = TitleButton("□", "rgba(90, 129, 166, 0.22)")
        self.btn_close = TitleButton("×", "rgba(255, 102, 126, 0.36)")

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
        self.btn_max.setText("❐" if self.window_ref.isMaximized() else "□")


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


class AppWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("异环自动钓鱼")
        self.resize(1420, 920)
        self.setMinimumSize(1200, 760)
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Window)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        self.config = {
            "hotkey_start": "alt+9",
            "hotkey_stop": "alt+0",
            "hold_threshold": 25,
            "deadzone_threshold": 10,
            "fishing_timeout": 180,
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

        self.init_ui()
        self._sync_runtime_preferences()
        self.bind_hotkeys()

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.process_queue)
        self.timer.start(60)

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
            self.bind_hotkeys()
        except Exception as exc:
            self.write_log(f"[配置] 保存失败: {exc}")

    def _sync_runtime_preferences(self):
        self.config["log_line_limit"] = int(self.config.get("log_line_limit", 320))
        self.log_deque = deque(self.log_deque, maxlen=self.config["log_line_limit"])
        if hasattr(self, "hotkey_label"):
            self.hotkey_label.setText(
                f"开始热键 {self.config['hotkey_start']}  |  停止热键 {self.config['hotkey_stop']}"
            )
        if hasattr(self, "log_textbox"):
            self.log_textbox.setText("\n".join(self.log_deque))

    def _normalize_hotkey(self, text):
        return (text or "").strip().lower().replace(" ", "")

    def _validate_hotkey(self, hotkey):
        if not hotkey:
            return False
        try:
            keyboard.parse_hotkey_combinations(hotkey)
            return True
        except Exception:
            return False

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
        self.page_encyclopedia = EncyclopediaWidget(self.sm.record_mgr)
        self.page_log = self._build_log_page()
        self.page_settings = self._build_settings_page()

        self.stack.addWidget(self.page_record)
        self.stack.addWidget(self.page_encyclopedia)
        self.stack.addWidget(self.page_log)
        self.stack.addWidget(self.page_settings)
        self.switch_page(0, self.nav_record)

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

    def show_usage_agreement(self):
        self.agreement_dialog = UsageAgreementDialog(self)
        dialog = self.agreement_dialog
        dialog.finished.connect(self._handle_agreement_result)
        dialog.move(self.geometry().center() - dialog.rect().center())
        dialog.open()

    def _handle_agreement_result(self, result):
        if result != QDialog.Accepted:
            self.close()

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

        logo_frame = QFrame()
        logo_frame.setFixedHeight(174)
        logo_frame.setStyleSheet(
            """
            QFrame {
                background-color: rgba(17, 31, 48, 0.78);
                border: 1px solid rgba(94, 132, 170, 0.20);
                border-radius: 30px;
            }
            """
        )
        add_shadow(logo_frame, blur=22, alpha=90, offset=(0, 8))
        logo_layout = QVBoxLayout(logo_frame)
        logo_layout.setContentsMargins(12, 12, 12, 12)

        logo_label = QLabel()
        logo_label.setAlignment(Qt.AlignCenter)
        logo_label.setStyleSheet("background: transparent; border: none;")
        if os.path.exists("logo.jpg"):
            logo_label.setPixmap(rounded_pixmap("logo.jpg", 246, 150, 28, keep_full=True))
        logo_layout.addWidget(logo_label)
        layout.addWidget(logo_frame)

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

        self.hotkey_label = QLabel(f"开始热键 {self.config['hotkey_start']}  |  停止热键 {self.config['hotkey_stop']}")
        self.hotkey_label.setWordWrap(True)
        self.hotkey_label.setStyleSheet(f"background: transparent; border: none; color: {APP_COLORS['text_soft']}; font-size: 12px;")
        control_layout.addWidget(self.hotkey_label)

        self.btn_start = QPushButton("开始钓鱼")
        self.btn_start.setFocusPolicy(Qt.NoFocus)
        self.btn_start.setStyleSheet(primary_button_stylesheet())
        self.btn_start.clicked.connect(self.start_bot)
        control_layout.addWidget(self.btn_start)

        self.btn_stop = QPushButton("停止运行")
        self.btn_stop.setFocusPolicy(Qt.NoFocus)
        self.btn_stop.setStyleSheet(secondary_button_stylesheet())
        self.btn_stop.setEnabled(False)
        self.btn_stop.clicked.connect(self.stop_bot)
        control_layout.addWidget(self.btn_stop)
        layout.addWidget(control_panel)

        layout.addStretch()

        author_panel = QFrame()
        author_panel.setStyleSheet(
            """
            QFrame {
                background-color: rgba(18, 29, 44, 0.52);
                border: 1px solid rgba(111, 145, 182, 0.14);
                border-radius: 20px;
            }
            """
        )
        author_layout = QVBoxLayout(author_panel)
        author_layout.setContentsMargins(14, 12, 14, 12)
        author_layout.setSpacing(6)

        author = QLabel("作者：FADEDTUMI")
        author.setStyleSheet(f"background: transparent; border: none; color: {APP_COLORS['text_dim']}; font-size: 12px; font-weight: 700;")
        author_layout.addWidget(author)

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
        author_layout.addWidget(github, 0, Qt.AlignLeft)
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

        self.log_textbox = QTextEdit()
        self.log_textbox.setReadOnly(True)
        self.log_textbox.setStyleSheet(text_edit_stylesheet())
        self.log_textbox.append("--- 异环自动钓鱼初始化完成 ---\n请确保游戏窗口处于可操作状态。")
        layout.addWidget(self.log_textbox, 1)
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

        subtitle = QLabel("调整热键、运行保护和日志展示等常用选项。")
        subtitle.setProperty("role", "subtle")
        content_layout.addWidget(subtitle)

        self._build_hotkey_block(content_layout)
        self.slider_hold = self._settings_block(
            content_layout,
            "跟鱼力度",
            "数值越大，跟鱼时按键会更积极；如出现跟随过猛或过慢，可在此调整。",
            self.config.get("hold_threshold", 25),
            10,
            50,
            "hold_threshold",
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

    def _build_hotkey_block(self, parent_layout):
        block = self._settings_panel()
        layout = QVBoxLayout(block)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        title = QLabel("快捷控制")
        title.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text']}; font-size: 16px; font-weight: 800;"
        )
        layout.addWidget(title)

        note = QLabel("设置用于快速开始或停止钓鱼的快捷键，格式示例：alt+9、ctrl+shift+s。")
        note.setWordWrap(True)
        note.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text_dim']}; font-size: 12px;"
        )
        layout.addWidget(note)

        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)

        start_label = QLabel("启动热键")
        start_label.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text']}; font-size: 13px; font-weight: 700;"
        )
        grid.addWidget(start_label, 0, 0)

        self.input_hotkey_start = QLineEdit(self.config.get("hotkey_start", "alt+9"))
        self.input_hotkey_start.setPlaceholderText("例如 alt+9")
        self.input_hotkey_start.setStyleSheet(line_edit_stylesheet())
        grid.addWidget(self.input_hotkey_start, 0, 1)

        stop_label = QLabel("停止热键")
        stop_label.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text']}; font-size: 13px; font-weight: 700;"
        )
        grid.addWidget(stop_label, 1, 0)

        self.input_hotkey_stop = QLineEdit(self.config.get("hotkey_stop", "alt+0"))
        self.input_hotkey_stop.setPlaceholderText("例如 alt+0")
        self.input_hotkey_stop.setStyleSheet(line_edit_stylesheet())
        grid.addWidget(self.input_hotkey_stop, 1, 1)

        layout.addLayout(grid)
        parent_layout.addWidget(block)

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

        slider = QSlider(Qt.Horizontal)
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
        hotkey_start = self._normalize_hotkey(self.input_hotkey_start.text())
        hotkey_stop = self._normalize_hotkey(self.input_hotkey_stop.text())

        if not self._validate_hotkey(hotkey_start):
            self.write_log("[配置] 启动热键格式无效，请使用类似 alt+9 或 ctrl+shift+s 的写法。")
            return
        if not self._validate_hotkey(hotkey_stop):
            self.write_log("[配置] 停止热键格式无效，请使用类似 alt+0 或 ctrl+shift+x 的写法。")
            return
        if hotkey_start == hotkey_stop:
            self.write_log("[配置] 启动热键与停止热键不能设置成相同组合。")
            return

        self.config["hotkey_start"] = hotkey_start
        self.config["hotkey_stop"] = hotkey_stop
        self.sm.update_config("t_hold", self.config.get("hold_threshold", 25))
        self.sm.update_config("fishing_timeout", self.config.get("fishing_timeout", 180))
        self.save_config()

    def switch_page(self, index, button):
        for nav in [self.nav_record, self.nav_encyclopedia, self.nav_log, self.nav_settings]:
            nav.setChecked(False)
        button.setChecked(True)
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

        try:
            while True:
                self.debug_queue.get_nowait()
        except queue.Empty:
            pass

    def bind_hotkeys(self):
        try:
            keyboard.unhook_all()
            keyboard.add_hotkey(self.config["hotkey_start"], self.start_bot_from_hotkey, suppress=True)
            keyboard.add_hotkey(self.config["hotkey_stop"], self.stop_bot_from_hotkey, suppress=True)
        except Exception as exc:
            print(f"Hotkey bind error: {exc}")

    def start_bot_from_hotkey(self):
        if not self.sm.is_running:
            QTimer.singleShot(0, self.start_bot)

    def stop_bot_from_hotkey(self):
        if self.sm.is_running:
            QTimer.singleShot(0, self.stop_bot)

    def start_bot(self):
        if self.sm.is_running:
            return

        self.sm.update_config("t_hold", self.config.get("hold_threshold", 25))
        self.sm.update_config("fishing_timeout", self.config.get("fishing_timeout", 180))
        self.sm.update_config("debug_mode", self.config.get("debug_mode", False))

        self.btn_start.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.status_chip.set_status("运行中", "running")
        if self.config.get("auto_switch_to_log", True):
            self.switch_page(2, self.nav_log)
        self.write_log(">>> 启动自动钓鱼。")
        self.sm.start()

    def stop_bot(self):
        if not self.sm.is_running:
            return
        self.sm.stop()
        self.write_log(">>> 已发送停止指令。")
        self.update_ui_on_stop()

    def update_ui_on_stop(self):
        self.btn_start.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.status_chip.set_status("已停止", "stopped")
        self.page_record.refresh_data()
        self.page_encyclopedia.refresh_data()
