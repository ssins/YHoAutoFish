from collections import defaultdict

from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, QTimer, Qt
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from gui.theme import (
    APP_COLORS,
    RARITY_META,
    RARITY_ORDER,
    add_shadow,
    combo_stylesheet,
    line_edit_stylesheet,
    panel_stylesheet,
    secondary_button_stylesheet,
    table_stylesheet,
)


class DashboardPanel(QFrame):
    def __init__(self, variant="elevated", parent=None):
        super().__init__(parent)
        self.setProperty("variant", variant)
        self.setStyleSheet(panel_stylesheet())
        add_shadow(self, blur=22, alpha=92, offset=(0, 8))


class StatCard(DashboardPanel):
    def __init__(self, title, accent, parent=None):
        super().__init__("elevated", parent)
        self.accent = accent

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(8)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text_dim']}; font-size: 13px; font-weight: 700;"
        )
        layout.addWidget(title_label)

        self.value_label = QLabel("--")
        self.value_label.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text']}; font-size: 29px; font-weight: 900;"
        )
        layout.addWidget(self.value_label)

        self.note_label = QLabel("")
        self.note_label.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text_soft']}; font-size: 12px;"
        )
        layout.addWidget(self.note_label)

        accent_bar = QFrame()
        accent_bar.setFixedHeight(4)
        accent_bar.setStyleSheet(
            f"background-color: {accent}; border: none; border-radius: 2px;"
        )
        layout.addWidget(accent_bar)

    def set_data(self, value, note=""):
        self.value_label.setText(value)
        self.note_label.setText(note)


class ChartModeButton(QPushButton):
    def __init__(self, text, mode, parent=None):
        super().__init__(text, parent)
        self.mode = mode
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setStyleSheet(secondary_button_stylesheet())


class InsightChart(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "bar"
        self.distribution = {}
        self.trend_points = []
        self.total_count = 0
        self.setMinimumHeight(300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_mode(self, mode):
        self.mode = mode
        self.update()

    def set_data(self, distribution, trend_points):
        self.distribution = distribution or {}
        self.trend_points = trend_points or []
        self.total_count = sum(self.distribution.values())
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        rect = self.rect().adjusted(10, 10, -10, -10)
        shell_path = QPainterPath()
        shell_path.addRoundedRect(rect, 28, 28)

        background = QLinearGradient(rect.topLeft(), rect.bottomRight())
        background.setColorAt(0.0, QColor(20, 33, 51, 215))
        background.setColorAt(0.5, QColor(18, 31, 47, 228))
        background.setColorAt(1.0, QColor(10, 20, 33, 236))
        painter.fillPath(shell_path, background)

        glow = QLinearGradient(rect.topLeft(), rect.bottomLeft())
        glow.setColorAt(0.0, QColor(29, 208, 214, 32))
        glow.setColorAt(1.0, QColor(29, 208, 214, 0))
        painter.fillPath(shell_path, glow)

        painter.setPen(QPen(QColor(115, 146, 182, 36), 1))
        painter.drawPath(shell_path)

        if self.mode == "pie":
            self._draw_pie(painter, rect)
        elif self.mode == "line":
            self._draw_line(painter, rect)
        else:
            self._draw_bar(painter, rect)

    def _draw_empty(self, painter, rect, text):
        painter.setPen(QColor(APP_COLORS["text_soft"]))
        painter.setFont(QFont("Microsoft YaHei UI", 12))
        painter.drawText(rect, Qt.AlignCenter, text)

    def _distribution_items(self):
        total = sum(self.distribution.values())
        return [
            (rarity, self.distribution[rarity], total)
            for rarity in RARITY_ORDER
            if self.distribution.get(rarity, 0)
        ]

    def _draw_bar(self, painter, rect):
        items = self._distribution_items()
        if not items:
            self._draw_empty(painter, rect, "暂无捕获数据")
            return

        header_rect = QRectF(rect.left() + 16, rect.top() + 14, rect.width() - 32, 28)
        painter.setPen(QColor(APP_COLORS["text_dim"]))
        painter.setFont(QFont("Microsoft YaHei UI", 10))
        painter.drawText(header_rect, Qt.AlignLeft | Qt.AlignVCenter, "稀有度分布")
        painter.drawText(header_rect, Qt.AlignRight | Qt.AlignVCenter, f"总计 {self.total_count} 条")

        content_rect = rect.adjusted(18, 54, -18, -18)
        max_count = max(count for _, count, _ in items)
        row_height = max(48, int(content_rect.height() / max(1, len(items))))

        for index, (rarity, count, total) in enumerate(items):
            meta = RARITY_META[rarity]
            top = content_rect.top() + index * row_height + 6
            label_rect = QRectF(content_rect.left(), top, 84, 28)
            track_rect = QRectF(content_rect.left() + 86, top + 5, content_rect.width() - 184, 18)
            value_rect = QRectF(content_rect.right() - 90, top, 90, 28)

            label_path = QPainterPath()
            label_path.addRoundedRect(label_rect, 14, 14)
            painter.fillPath(label_path, QColor(255, 255, 255, 10))
            painter.setPen(QColor(meta["color"]))
            painter.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
            painter.drawText(label_rect, Qt.AlignCenter, meta["label"])

            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(255, 255, 255, 14))
            painter.drawRoundedRect(track_rect, 9, 9)

            fill_width = track_rect.width() * (count / max_count if max_count else 0)
            fill_rect = QRectF(track_rect.left(), track_rect.top(), max(22, fill_width), track_rect.height())
            gradient = QLinearGradient(fill_rect.topLeft(), fill_rect.topRight())
            gradient.setColorAt(0.0, QColor(meta["color"]))
            gradient.setColorAt(1.0, QColor(meta["glow"]))
            painter.setBrush(gradient)
            painter.drawRoundedRect(fill_rect, 9, 9)

            painter.setPen(QColor(APP_COLORS["text"]))
            painter.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
            painter.drawText(
                value_rect,
                Qt.AlignRight | Qt.AlignVCenter,
                f"{count} / {int(count / total * 100)}%",
            )

    def _draw_pie(self, painter, rect):
        items = self._distribution_items()
        if not items:
            self._draw_empty(painter, rect, "暂无捕获数据")
            return

        total = sum(count for _, count, _ in items)
        size = min(rect.width() * 0.46, rect.height() * 0.82)
        pie_rect = QRectF(rect.left() + 20, rect.center().y() - size / 2, size, size)

        painter.setPen(QPen(QColor(255, 255, 255, 10), 16))
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(pie_rect)

        start_angle = 90 * 16
        for rarity, count, _ in items:
            color = QColor(RARITY_META[rarity]["color"])
            pen = QPen(color, 18)
            pen.setCapStyle(Qt.RoundCap)
            painter.setPen(pen)
            span = -int((count / total) * 360 * 16)
            painter.drawArc(pie_rect, start_angle, span)
            start_angle += span

        inner_rect = pie_rect.adjusted(44, 44, -44, -44)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(10, 18, 29, 235))
        painter.drawEllipse(inner_rect)

        center_rect = inner_rect.adjusted(10, 10, -10, -10)
        label_rect = QRectF(center_rect.left(), center_rect.top() + 8, center_rect.width(), 18)
        value_rect = QRectF(center_rect.left(), center_rect.top() + 28, center_rect.width(), 32)

        painter.setPen(QColor(APP_COLORS["text_dim"]))
        painter.setFont(QFont("Microsoft YaHei UI", 9))
        painter.drawText(label_rect, Qt.AlignCenter, "累计捕获")
        painter.setPen(QColor(APP_COLORS["text"]))
        painter.setFont(QFont("Microsoft YaHei UI", 18, QFont.Bold))
        painter.drawText(value_rect, Qt.AlignCenter, str(total))

        legend_x = pie_rect.right() + 34
        for index, (rarity, count, _) in enumerate(items):
            top = rect.top() + 36 + index * 52
            badge_rect = QRectF(legend_x, top, rect.right() - legend_x - 12, 40)
            badge_path = QPainterPath()
            badge_path.addRoundedRect(badge_rect, 14, 14)
            painter.fillPath(badge_path, QColor(255, 255, 255, 8))

            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(RARITY_META[rarity]["color"]))
            painter.drawEllipse(QRectF(legend_x + 14, top + 11, 18, 18))

            painter.setPen(QColor(APP_COLORS["text"]))
            painter.setFont(QFont("Microsoft YaHei UI", 10, QFont.Bold))
            painter.drawText(
                QRectF(legend_x + 42, top + 4, 110, 16),
                Qt.AlignLeft | Qt.AlignVCenter,
                RARITY_META[rarity]["label"],
            )
            painter.setPen(QColor(APP_COLORS["text_dim"]))
            painter.setFont(QFont("Microsoft YaHei UI", 9))
            painter.drawText(
                QRectF(legend_x + 42, top + 19, 140, 14),
                Qt.AlignLeft | Qt.AlignVCenter,
                f"{count} 条 · {int(count / total * 100)}%",
            )

    def _draw_line(self, painter, rect):
        if not self.trend_points:
            self._draw_empty(painter, rect, "暂无趋势数据")
            return

        plot_rect = rect.adjusted(24, 26, -22, -36)
        painter.setPen(QPen(QColor(255, 255, 255, 14), 1))
        for index in range(5):
            y = plot_rect.top() + index * plot_rect.height() / 4
            painter.drawLine(plot_rect.left(), y, plot_rect.right(), y)

        max_value = max(value for _, value in self.trend_points) or 1
        x_step = plot_rect.width() / max(1, len(self.trend_points) - 1)
        points = []
        for index, (label, value) in enumerate(self.trend_points):
            x = plot_rect.left() + index * x_step
            y = plot_rect.bottom() - (value / max_value) * plot_rect.height()
            points.append((QPointF(x, y), label, value))

        path = QPainterPath(points[0][0])
        for index in range(1, len(points)):
            prev = points[index - 1][0]
            current = points[index][0]
            control_x = (prev.x() + current.x()) / 2
            path.cubicTo(QPointF(control_x, prev.y()), QPointF(control_x, current.y()), current)

        fill_path = QPainterPath(path)
        fill_path.lineTo(plot_rect.right(), plot_rect.bottom())
        fill_path.lineTo(plot_rect.left(), plot_rect.bottom())
        fill_path.closeSubpath()

        fill_gradient = QLinearGradient(plot_rect.topLeft(), plot_rect.bottomLeft())
        fill_gradient.setColorAt(0.0, QColor(29, 208, 214, 72))
        fill_gradient.setColorAt(1.0, QColor(29, 208, 214, 0))
        painter.fillPath(fill_path, fill_gradient)

        painter.setPen(QPen(QColor(APP_COLORS["accent_soft"]), 7))
        painter.setOpacity(0.18)
        painter.drawPath(path)
        painter.setOpacity(1.0)
        painter.setPen(QPen(QColor(APP_COLORS["accent"]), 3))
        painter.drawPath(path)

        for point, label, value in points:
            painter.setPen(Qt.NoPen)
            painter.setBrush(QColor(APP_COLORS["accent"]))
            painter.drawEllipse(point, 5, 5)
            painter.setBrush(QColor(255, 255, 255, 70))
            painter.drawEllipse(point, 9, 9)

            painter.setPen(QColor(APP_COLORS["text"]))
            painter.setFont(QFont("Microsoft YaHei UI", 9, QFont.Bold))
            painter.drawText(QRectF(point.x() - 18, point.y() - 26, 36, 16), Qt.AlignCenter, str(value))

            painter.setPen(QColor(APP_COLORS["text_dim"]))
            painter.setFont(QFont("Microsoft YaHei UI", 9))
            painter.drawText(
                QRectF(point.x() - 40, plot_rect.bottom() + 10, 80, 16),
                Qt.AlignCenter,
                label[5:] if len(label) >= 10 else label,
            )


class FishingRecordWidget(QWidget):
    def __init__(self, record_mgr):
        super().__init__()
        self.record_mgr = record_mgr
        self.current_chart_mode = "bar"
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.setInterval(100)
        self.refresh_timer.timeout.connect(self.refresh_data)
        self.init_ui()
        self.refresh_data()

    def init_ui(self):
        self.setStyleSheet(panel_stylesheet())
        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 24)
        layout.setSpacing(18)

        header = QHBoxLayout()
        header.setSpacing(12)

        title_col = QVBoxLayout()
        title_col.setSpacing(5)

        title = QLabel("钓鱼记录")
        title.setProperty("role", "headline")
        title_col.addWidget(title)

        subtitle = QLabel("默认首页展示自动钓鱼成果，支持查询、分类筛选和多图表切换。")
        subtitle.setProperty("role", "subtle")
        title_col.addWidget(subtitle)
        header.addLayout(title_col, 1)

        badge = QLabel("记录视图")
        badge.setProperty("role", "accent-chip")
        header.addWidget(badge, 0, Qt.AlignTop)
        layout.addLayout(header)

        self._build_stats(layout)
        self._build_filter_bar(layout)
        self._build_content(layout)

    def _build_stats(self, parent_layout):
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(14)

        self.card_total = StatCard("累计钓起", APP_COLORS["accent"])
        self.card_runtime = StatCard("运行时长", "#58C7FF")
        self.card_success = StatCard("成功率", APP_COLORS["success"])
        self.card_weight = StatCard("最大重量", APP_COLORS["warning"])
        self.card_empty = StatCard("连续空竿", APP_COLORS["danger"])
        self.card_unlocked = StatCard("已解锁图鉴", "#B677FF")

        cards = [
            self.card_total,
            self.card_runtime,
            self.card_success,
            self.card_weight,
            self.card_empty,
            self.card_unlocked,
        ]
        for index, card in enumerate(cards):
            grid.addWidget(card, 0, index)
        parent_layout.addLayout(grid)

    def _build_filter_bar(self, parent_layout):
        panel = DashboardPanel()
        row = QHBoxLayout(panel)
        row.setContentsMargins(18, 16, 18, 16)
        row.setSpacing(12)

        label = QLabel("记录检索")
        label.setProperty("role", "section")
        row.addWidget(label)

        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText("输入鱼名快速查询")
        self.search_edit.setStyleSheet(line_edit_stylesheet())
        self.search_edit.textChanged.connect(self._schedule_refresh)
        row.addWidget(self.search_edit, 1)

        self.rarity_combo = QComboBox()
        self.rarity_combo.addItems(["全部稀有度"] + RARITY_ORDER)
        self.rarity_combo.setStyleSheet(combo_stylesheet())
        self.rarity_combo.currentIndexChanged.connect(self.refresh_data)
        row.addWidget(self.rarity_combo)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems(["按时间倒序", "按重量倒序", "按重量正序"])
        self.sort_combo.setStyleSheet(combo_stylesheet())
        self.sort_combo.currentIndexChanged.connect(self.refresh_data)
        row.addWidget(self.sort_combo)

        self.reset_btn = QPushButton("重置筛选")
        self.reset_btn.setFocusPolicy(Qt.NoFocus)
        self.reset_btn.setStyleSheet(secondary_button_stylesheet())
        self.reset_btn.clicked.connect(self._reset_filters)
        row.addWidget(self.reset_btn)

        parent_layout.addWidget(panel)

    def _build_content(self, parent_layout):
        row = QHBoxLayout()
        row.setSpacing(18)

        chart_panel = DashboardPanel()
        chart_layout = QVBoxLayout(chart_panel)
        chart_layout.setContentsMargins(18, 18, 18, 18)
        chart_layout.setSpacing(14)

        chart_header = QHBoxLayout()
        chart_title = QLabel("数据图表")
        chart_title.setProperty("role", "section")
        chart_header.addWidget(chart_title)
        chart_header.addStretch()

        self.chart_buttons = []
        for text, mode in [("柱状图", "bar"), ("扇形图", "pie"), ("折线图", "line")]:
            btn = ChartModeButton(text, mode)
            btn.clicked.connect(self._change_chart_mode)
            self.chart_buttons.append(btn)
            chart_header.addWidget(btn)
        self.chart_buttons[0].setChecked(True)
        chart_layout.addLayout(chart_header)

        self.chart_body = QFrame()
        self.chart_body.setProperty("variant", "soft")
        self.chart_body.setStyleSheet(panel_stylesheet())
        chart_body_layout = QVBoxLayout(self.chart_body)
        chart_body_layout.setContentsMargins(14, 14, 14, 14)
        chart_body_layout.setSpacing(0)

        self.chart = InsightChart()
        chart_body_layout.addWidget(self.chart)
        chart_layout.addWidget(self.chart_body, 1)
        row.addWidget(chart_panel, 4)

        list_panel = DashboardPanel()
        list_layout = QVBoxLayout(list_panel)
        list_layout.setContentsMargins(18, 18, 18, 18)
        list_layout.setSpacing(14)

        list_header = QHBoxLayout()
        list_title = QLabel("捕获记录")
        list_title.setProperty("role", "section")
        list_header.addWidget(list_title)
        list_header.addStretch()

        self.result_chip = QLabel("0 条记录")
        self.result_chip.setStyleSheet(
            f"""
            QLabel {{
                background-color: rgba(255, 255, 255, 0.04);
                color: {APP_COLORS['text_dim']};
                border: 1px solid rgba(111, 145, 182, 0.18);
                border-radius: 16px;
                padding: 8px 14px;
                font-size: 12px;
                font-weight: 700;
            }}
            """
        )
        list_header.addWidget(self.result_chip)
        list_layout.addLayout(list_header)

        self.record_body = QFrame()
        self.record_body.setProperty("variant", "soft")
        self.record_body.setStyleSheet(panel_stylesheet())
        record_body_layout = QVBoxLayout(self.record_body)
        record_body_layout.setContentsMargins(12, 12, 12, 12)
        record_body_layout.setSpacing(8)

        self.record_table = QTableWidget(0, 4)
        self.record_table.setHorizontalHeaderLabels(["时间", "鱼种", "稀有度", "重量"])
        self.record_table.setAlternatingRowColors(True)
        self.record_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.record_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.record_table.setFocusPolicy(Qt.NoFocus)
        self.record_table.setShowGrid(False)
        self.record_table.setWordWrap(False)
        self.record_table.verticalHeader().setVisible(False)
        self.record_table.verticalHeader().setDefaultSectionSize(42)
        self.record_table.horizontalHeader().setStretchLastSection(True)
        self.record_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.record_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.record_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.record_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.record_table.setStyleSheet(table_stylesheet())
        record_body_layout.addWidget(self.record_table, 1)

        self.empty_tip = QLabel("当前筛选条件下暂无记录")
        self.empty_tip.setAlignment(Qt.AlignCenter)
        self.empty_tip.setStyleSheet(
            f"background: transparent; border: none; color: {APP_COLORS['text_soft']}; font-size: 13px;"
        )
        record_body_layout.addWidget(self.empty_tip, 1)

        list_layout.addWidget(self.record_body, 1)
        row.addWidget(list_panel, 5)

        parent_layout.addLayout(row, 1)

    def _schedule_refresh(self):
        self.refresh_timer.start()

    def _change_chart_mode(self):
        sender = self.sender()
        if not isinstance(sender, ChartModeButton):
            return
        self.current_chart_mode = sender.mode
        for button in self.chart_buttons:
            button.setChecked(button is sender)
        self.chart.set_mode(self.current_chart_mode)

    def _reset_filters(self):
        blockers = [
            QSignalBlocker(self.search_edit),
            QSignalBlocker(self.rarity_combo),
            QSignalBlocker(self.sort_combo),
        ]
        self.search_edit.clear()
        self.rarity_combo.setCurrentIndex(0)
        self.sort_combo.setCurrentIndex(0)
        del blockers
        self.refresh_data()

    def _populate_table(self, history):
        self.record_table.setUpdatesEnabled(False)
        self.record_table.clearContents()
        self.record_table.setRowCount(len(history))

        for row, record in enumerate(history):
            rarity = record.get("rarity", "未知稀有度")
            rarity_meta = RARITY_META.get(rarity, {"label": "未知", "color": APP_COLORS["text"]})
            values = [
                record.get("time", ""),
                record.get("fish_name", "未知鱼种"),
                rarity_meta["label"],
                f"{record.get('weight', 0)} g",
            ]
            for col, value in enumerate(values):
                item = QTableWidgetItem(value)
                if col == 0:
                    item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                else:
                    item.setTextAlignment(Qt.AlignCenter)
                item.setForeground(
                    QColor(rarity_meta["color"] if col == 2 else APP_COLORS["text"])
                )
                self.record_table.setItem(row, col, item)

        self.record_table.setUpdatesEnabled(True)

    def refresh_data(self):
        stats = self.record_mgr.get_stats()
        encyclopedia = self.record_mgr.get_encyclopedia()

        keyword = self.search_edit.text().strip()
        rarity = self.rarity_combo.currentText()
        history = self.record_mgr.query_history(keyword=keyword, rarity=rarity)

        sort_mode = self.sort_combo.currentText()
        if sort_mode == "按重量倒序":
            history.sort(key=lambda item: item.get("weight", 0), reverse=True)
        elif sort_mode == "按重量正序":
            history.sort(key=lambda item: item.get("weight", 0))
        else:
            history.sort(key=lambda item: item.get("time", ""), reverse=True)

        total_caught = stats.get("total_caught", 0)
        total_attempts = stats.get("total_attempts", 0)
        runtime = stats.get("total_time_seconds", 0)
        success_rate = (total_caught / total_attempts * 100) if total_attempts else 0
        max_weight = max((data.get("max_weight", 0) for data in encyclopedia.values()), default=0)
        unlocked = sum(1 for data in encyclopedia.values() if data.get("caught_count", 0) > 0)

        self.card_total.set_data(str(total_caught), f"检索结果 {len(history)} 条")
        self.card_runtime.set_data(f"{runtime // 3600}h {(runtime % 3600) // 60}m", "累计运行")
        self.card_success.set_data(f"{success_rate:.1f}%", f"总尝试 {total_attempts} 次")
        self.card_weight.set_data(f"{max_weight} g", "历史最大值")
        self.card_empty.set_data(str(stats.get("consecutive_empty", 0)), "空竿连续计数")
        self.card_unlocked.set_data(f"{unlocked}/{len(encyclopedia)}", "图鉴收集进度")

        distribution = self.record_mgr.get_rarity_distribution(history)
        trend_source = defaultdict(int)
        for record in history:
            trend_source[record.get("time", "")[:10]] += 1
        trend_points = [(day, trend_source[day]) for day in sorted(trend_source.keys())[-7:]]

        self.chart.set_data(distribution, trend_points)
        self.chart.set_mode(self.current_chart_mode)

        self._populate_table(history)

        has_records = len(history) > 0
        self.record_table.setVisible(has_records)
        self.empty_tip.setVisible(not has_records)
        self.result_chip.setText(f"{len(history)} 条记录")
