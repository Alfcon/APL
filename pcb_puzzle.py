import sys
import math
import re
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QPushButton, QListWidget,
                             QTextEdit, QGraphicsView, QGraphicsScene,
                             QFileDialog, QMessageBox, QListWidgetItem,
                             QGraphicsEllipseItem, QGraphicsLineItem,
                             QGraphicsRectItem, QGraphicsSimpleTextItem,
                             QGraphicsItem, QGraphicsPixmapItem, QComboBox)

PREFIX_LABELS = {
    'R': 'Resistors', 'C': 'Capacitors', 'L': 'Inductors',
    'D': 'Diodes', 'Q': 'Transistors',
    'IC': 'ICs', 'U': 'ICs',
    'J': 'Connectors', 'P': 'Connectors',
    'TP': 'Test Points', 'GND': 'Ground Points',
    'Y': 'Crystals', 'X': 'Crystals',
    'S': 'Switches', 'SW': 'Switches',
    'F': 'Fuses', 'FB': 'Ferrite Beads',
    'M': 'Mounting Holes', 'H': 'Mounting Holes',
    'LED': 'LEDs',
}


def designator_prefix(designator):
    m = re.match(r'^[A-Za-z]+', designator)
    return m.group(0).upper() if m else designator.upper()


def designator_sort_key(designator):
    return [int(t) if t.isdigit() else t.lower()
            for t in re.split(r'(\d+)', designator)]
from PyQt5.QtCore import Qt, QMimeData, QPointF, QTimer, QSize
from PyQt5.QtGui import (QDrag, QPixmap, QPainter, QColor, QPen, QBrush, QFont,
                         QTransform, QIcon)
from utils.parser import PCBParser
from pcb_components import ComponentItem


class DraggableListWidget(QListWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return

        comp_data = item.data(Qt.UserRole)

        drag = QDrag(self)
        mime_data = QMimeData()
        mime_data.setText(comp_data['designator'])
        drag.setMimeData(mime_data)

        pixmap = QPixmap(50, 20)
        pixmap.fill(Qt.lightGray)
        painter = QPainter(pixmap)
        painter.drawText(pixmap.rect(), Qt.AlignCenter, comp_data['designator'])
        painter.end()

        drag.setPixmap(pixmap)
        drag.setHotSpot(pixmap.rect().center())

        result = drag.exec_(Qt.MoveAction)

        if result == Qt.MoveAction:
            self.takeItem(self.row(item))


class BoardScene(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSceneRect(0, 0, 800, 600)
        self.drop_zones = {}


class BoardView(QGraphicsView):
    MIN_SCALE = 0.2
    MAX_SCALE = 40.0

    def __init__(self, scene, main_window):
        super().__init__(scene)
        self.setAcceptDrops(True)
        self.main_window = main_window
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.AnchorUnderMouse)
        self.setDragMode(QGraphicsView.NoDrag)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            return
        factor = 1.25 if delta > 0 else 1 / 1.25
        new_scale = self.transform().m11() * factor
        if new_scale < self.MIN_SCALE or new_scale > self.MAX_SCALE:
            return
        self.scale(factor, factor)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        if event.mimeData().hasText():
            designator = event.mimeData().text()
            drop_pos = self.mapToScene(event.pos())

            success = self.main_window.handle_component_drop(designator, drop_pos)

            if success:
                event.acceptProposedAction()
            else:
                event.ignore()
        else:
            event.ignore()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PCB Assembly Puzzle")
        self.setGeometry(100, 100, 1200, 800)

        self.parser = PCBParser()
        self.score = 0
        self.attempts = {}
        self.flash_timers = {}
        self.placed_designators = set()
        self.component_thumbnails = {}  # designator -> QPixmap (per-component STEP render)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        main_layout = QHBoxLayout()
        central_widget.setLayout(main_layout)

        left_panel = QVBoxLayout()
        left_panel_widget = QWidget()
        left_panel_widget.setLayout(left_panel)
        left_panel_widget.setFixedWidth(300)

        self.btn_load = QPushButton("Load Altium ZIP or CSV")
        self.btn_load.clicked.connect(self.load_zip)
        left_panel.addWidget(self.btn_load)

        self.btn_load_outline = QPushButton("Load Board Outline")
        self.btn_load_outline.clicked.connect(self.load_outline)
        left_panel.addWidget(self.btn_load_outline)

        self.btn_load_step = QPushButton("Load 3D Model (STEP)")
        self.btn_load_step.clicked.connect(self.load_step)
        left_panel.addWidget(self.btn_load_step)

        self.lbl_list = QLabel("Unplaced Components:")
        left_panel.addWidget(self.lbl_list)

        self.cmb_category = QComboBox()
        self.cmb_category.currentIndexChanged.connect(self._apply_category_filter)
        left_panel.addWidget(self.cmb_category)

        self.comp_list = DraggableListWidget()
        self.comp_list.setIconSize(QSize(44, 44))
        self.comp_list.itemClicked.connect(self.display_component_info)
        left_panel.addWidget(self.comp_list)

        self.btn_hint = QPushButton("Hint: Show Selected Position")
        self.btn_hint.clicked.connect(self.show_hint)
        left_panel.addWidget(self.btn_hint)

        self.lbl_desc = QLabel("Component Information:")
        left_panel.addWidget(self.lbl_desc)

        self.lbl_comp_image = QLabel()
        self.lbl_comp_image.setAlignment(Qt.AlignCenter)
        self.lbl_comp_image.setFixedHeight(160)
        self.lbl_comp_image.setStyleSheet("background: #2b2b2b; border: 1px solid #555;")
        left_panel.addWidget(self.lbl_comp_image)

        self.text_desc = QTextEdit()
        self.text_desc.setReadOnly(True)
        left_panel.addWidget(self.text_desc)

        right_panel = QVBoxLayout()

        top_bar = QHBoxLayout()
        self.lbl_score = QLabel("Score: 0")
        self.lbl_score.setStyleSheet("font-size: 24px; font-weight: bold;")
        self.lbl_score.setAlignment(Qt.AlignCenter)
        top_bar.addWidget(self.lbl_score, 1)

        self.btn_zoom_in = QPushButton("+")
        self.btn_zoom_in.setFixedWidth(36)
        self.btn_zoom_in.clicked.connect(lambda: self.zoom_by(1.25))
        top_bar.addWidget(self.btn_zoom_in)

        self.btn_zoom_out = QPushButton("-")
        self.btn_zoom_out.setFixedWidth(36)
        self.btn_zoom_out.clicked.connect(lambda: self.zoom_by(1 / 1.25))
        top_bar.addWidget(self.btn_zoom_out)

        self.btn_fit = QPushButton("Fit Board")
        self.btn_fit.clicked.connect(self.fit_board)
        top_bar.addWidget(self.btn_fit)

        self.btn_reset = QPushButton("Reset")
        self.btn_reset.clicked.connect(self.reset_placements)
        top_bar.addWidget(self.btn_reset)

        right_panel.addLayout(top_bar)

        self.scene = BoardScene(self)
        self.view = BoardView(self.scene, self)
        self.view.setRenderHint(QPainter.Antialiasing)
        right_panel.addWidget(self.view)

        main_layout.addWidget(left_panel_widget)
        main_layout.addLayout(right_panel)

    def load_zip(self):
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getOpenFileName(self, "Select Altium ZIP or CSV",
                                                    "",
                                                    "Altium files (*.zip *.csv);;ZIP Files (*.zip);;CSV Files (*.csv)",
                                                    options=options)

        if not file_path:
            return

        lower = file_path.lower()
        if lower.endswith('.zip'):
            if not self.parser.extract_zip(file_path):
                QMessageBox.critical(self, "Error", "Failed to extract ZIP file.")
                return
            ok = self.parser.parse_files()
        elif lower.endswith('.csv'):
            ok = self.parser.parse_file(file_path)
        else:
            QMessageBox.critical(self, "Error", "Unsupported file type.")
            return

        if ok:
            self.populate_component_list()
            QMessageBox.information(self, "Success", "Project loaded successfully.")
        else:
            QMessageBox.warning(self, "Warning", "No component data found.")

    def load_outline(self):
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select Board Outline (Gerber ZIP or single file)",
            "",
            "Gerber files (*.zip *.gm1 *.gko *.gml *.gbr)",
            options=options,
        )
        if not file_path:
            return

        lower = file_path.lower()
        if lower.endswith('.zip'):
            ok = self.parser.load_outline_zip(file_path)
        else:
            ok = self.parser.load_outline_file(file_path)

        if not ok:
            QMessageBox.warning(self, "Warning", "Could not load board outline.")
            return

        self.populate_component_list()
        QMessageBox.information(
            self, "Success",
            f"Loaded {len(self.parser.board_outline)} outline segments.",
        )

    def load_step(self):
        options = QFileDialog.Options()
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select 3D Model (STEP)",
            "",
            "STEP files (*.step *.stp *.STEP *.STP)",
            options=options,
        )
        if not file_path:
            return

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            ok = self.parser.render_step_image(file_path, self.parser.components)
        finally:
            QApplication.restoreOverrideCursor()

        if not ok:
            QMessageBox.warning(
                self, "3D Model",
                "Could not render the STEP file.\n\n"
                "This needs a Python environment with pythonocc-core "
                "(conda env 'adcs-step' or the $ADCS_STEP_PYTHON interpreter).\n"
                "See the console for details.",
            )
            return

        self.populate_component_list()
        QMessageBox.information(
            self, "Success",
            f"Loaded component images for {len(self.component_thumbnails)} components.",
        )

    def _stop_all_hints(self):
        for state in list(self.flash_timers.values()):
            state['timer'].stop()
        self.flash_timers = {}

    def reset_placements(self):
        if not self.parser.components:
            return
        self._stop_all_hints()
        self.populate_component_list()

    def populate_component_list(self):
        self._stop_all_hints()
        self.comp_list.clear()
        self.scene.clear()
        self.score = 0
        self.attempts = {}
        self.placed_designators = set()
        self.update_score()
        self._build_component_thumbnails()
        self._build_category_filter()

        self.scale_factor = 5.0

        board_image = None
        board_bbox = None
        if self.parser.board_image_path and self.parser.board_image_bbox_mm:
            board_image = self.parser.board_image_path
            board_bbox = self.parser.board_image_bbox_mm

        xs = [c['x'] for c in self.parser.components]
        ys = [c['y'] for c in self.parser.components]
        for (x1, y1), (x2, y2) in self.parser.board_outline:
            xs.extend([x1, x2])
            ys.extend([y1, y2])
        if board_bbox:
            xs.extend([board_bbox[0], board_bbox[2]])
            ys.extend([board_bbox[1], board_bbox[3]])

        max_x = max(xs + [0])
        max_y = max(ys + [0])
        self.max_y = max_y

        scene_width = (max_x + 20) * self.scale_factor
        scene_height = (max_y + 20) * self.scale_factor
        self.scene.setSceneRect(0, 0, scene_width, scene_height)

        if board_image:
            pixmap = QPixmap(board_image)
            if not pixmap.isNull():
                pix_item = QGraphicsPixmapItem(pixmap)
                pix_item.setTransformationMode(Qt.SmoothTransformation)
                pix_item.setZValue(-2)
                min_x_mm, min_y_mm, max_x_mm, max_y_mm = board_bbox
                scene_w = (max_x_mm - min_x_mm) * self.scale_factor
                scene_h = (max_y_mm - min_y_mm) * self.scale_factor
                sx = scene_w / pixmap.width() if pixmap.width() else 1.0
                sy = scene_h / pixmap.height() if pixmap.height() else 1.0
                pix_item.setTransform(QTransform().scale(sx, sy))
                pix_item.setPos(min_x_mm * self.scale_factor,
                                (max_y - max_y_mm) * self.scale_factor)
                self.scene.addItem(pix_item)
        else:
            outline_pen = QPen(QColor(50, 100, 200), 2)
            for (x1, y1), (x2, y2) in self.parser.board_outline:
                line = QGraphicsLineItem(
                    x1 * self.scale_factor,
                    (max_y - y1) * self.scale_factor,
                    x2 * self.scale_factor,
                    (max_y - y2) * self.scale_factor,
                )
                line.setPen(outline_pen)
                line.setZValue(-1)
                self.scene.addItem(line)

        marker_pen = QPen(QColor(120, 120, 120))
        marker_pen.setWidth(1)
        label_font = QFont()
        label_font.setPointSize(7)
        label_color = QColor(80, 80, 80)
        marker_radius = 4  # in screen pixels (markers ignore view transform)

        self.scene.drop_zones = {}
        for comp in self.parser.components:
            tx = comp['x'] * self.scale_factor
            ty = (max_y - comp['y']) * self.scale_factor

            marker = QGraphicsEllipseItem(
                -marker_radius, -marker_radius,
                marker_radius * 2, marker_radius * 2,
            )
            marker.setPen(marker_pen)
            marker.setBrush(QBrush(Qt.NoBrush))
            marker.setPos(tx, ty)
            marker.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
            marker.setZValue(-0.5)
            marker.setToolTip(f"{comp['designator']}: {comp['description']}")
            self.scene.addItem(marker)

            label = QGraphicsSimpleTextItem(comp['designator'])
            label.setBrush(label_color)
            label.setFont(label_font)
            label.setPos(tx, ty)
            label.setFlag(QGraphicsItem.ItemIgnoresTransformations, True)
            label.setZValue(-0.5)
            self.scene.addItem(label)

            self.scene.drop_zones[comp['designator']] = {
                'x': tx,
                'y': ty,
                'data': comp,
                'marker': marker,
                'label': label,
            }

        self._apply_category_filter()
        self.fit_board()

    def _build_component_thumbnails(self):
        """Load the per-component PNGs rendered from the STEP file, if any."""
        self.component_thumbnails = {}
        for designator, path in self.parser.step_thumbnails.items():
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self.component_thumbnails[designator] = pixmap

    def _build_category_filter(self):
        self.cmb_category.blockSignals(True)
        self.cmb_category.clear()
        counts = {}
        for comp in self.parser.components:
            prefix = designator_prefix(comp['designator'])
            counts[prefix] = counts.get(prefix, 0) + 1
        self.cmb_category.addItem(f"All ({len(self.parser.components)})", None)
        for prefix in sorted(counts.keys()):
            name = PREFIX_LABELS.get(prefix)
            display = f"{prefix} – {name} ({counts[prefix]})" if name else f"{prefix} ({counts[prefix]})"
            self.cmb_category.addItem(display, prefix)
        self.cmb_category.blockSignals(False)

    def _apply_category_filter(self):
        if not self.parser.components:
            self.comp_list.clear()
            return
        prefix = self.cmb_category.currentData()
        self.comp_list.clear()
        ordered = sorted(self.parser.components,
                         key=lambda c: designator_sort_key(c['designator']))
        for comp in ordered:
            des = comp['designator']
            if des in self.placed_designators:
                continue
            if prefix is not None and designator_prefix(des) != prefix:
                continue
            item = QListWidgetItem(des)
            item.setData(Qt.UserRole, comp)
            thumb = self.component_thumbnails.get(des)
            if thumb is not None:
                item.setIcon(QIcon(thumb))
            self.comp_list.addItem(item)

    def handle_component_drop(self, designator, drop_pos):
        if designator not in self.scene.drop_zones:
            return False

        target = self.scene.drop_zones[designator]
        target_x = target['x']
        target_y = target['y']

        dist = math.hypot(drop_pos.x() - target_x, drop_pos.y() - target_y)

        TOLERANCE = 30.0

        if dist <= TOLERANCE:
            self.score += 1
            self.update_score()
            self.placed_designators.add(designator)

            if target.get('marker') is not None:
                self.scene.removeItem(target['marker'])
                target['marker'] = None
            if target.get('label') is not None:
                self.scene.removeItem(target['label'])
                target['label'] = None

            data = target['data']
            comp_item = ComponentItem(
                data,
                target_x, target_y,
                width=data.get('width_mm', 3.0) * self.scale_factor,
                height=data.get('height_mm', 2.0) * self.scale_factor,
                rotation=data.get('rotation', 0.0),
            )
            self.scene.addItem(comp_item)

            return True
        else:
            if designator not in self.attempts:
                self.attempts[designator] = 0
            self.attempts[designator] += 1

            if self.attempts[designator] >= 3:
                self.score -= 1
                self.update_score()
                self.trigger_hint_flash(designator, target_x, target_y)

            QMessageBox.warning(self, "Incorrect", f"Incorrect placement for {designator}.")
            return False

    def update_score(self):
        self.lbl_score.setText(f"Score: {self.score}")

    def fit_board(self):
        rect = self.scene.sceneRect()
        if rect.isEmpty():
            return
        self.view.resetTransform()
        self.view.fitInView(rect, Qt.KeepAspectRatio)

    def zoom_by(self, factor):
        current = self.view.transform().m11() * factor
        if current < BoardView.MIN_SCALE or current > BoardView.MAX_SCALE:
            return
        self.view.scale(factor, factor)

    def trigger_hint_flash(self, designator, x, y):
        indicator = QGraphicsEllipseItem(0, 0, 40, 40)
        indicator.setPos(x - 20, y - 20)
        indicator.setBrush(QBrush(Qt.NoBrush))
        indicator.setPen(QPen(Qt.red, 3))
        self.scene.addItem(indicator)

        timer = QTimer(self)
        self.flash_timers[designator] = {'timer': timer, 'item': indicator, 'count': 0}

        def toggle_visibility():
            state = self.flash_timers[designator]
            state['count'] += 1
            state['item'].setVisible(not state['item'].isVisible())

            if state['count'] > 10:
                state['timer'].stop()
                self.scene.removeItem(state['item'])
                del self.flash_timers[designator]

        timer.timeout.connect(toggle_visibility)
        timer.start(300)

    def show_hint(self):
        item = self.comp_list.currentItem()
        if item is None:
            return
        designator = item.text()
        if designator not in self.scene.drop_zones:
            return
        if designator in self.flash_timers:
            return
        target = self.scene.drop_zones[designator]
        self.view.centerOn(target['x'], target['y'])
        self.trigger_hint_flash(designator, target['x'], target['y'])

    def display_component_info(self, item):
        comp = item.data(Qt.UserRole)
        info = f"<b>Designator:</b> {comp['designator']}<br>"
        info += f"<b>Description:</b> {comp['description']}<br>"
        info += f"<b>Target X:</b> {comp['x']} mm<br>"
        info += f"<b>Target Y:</b> {comp['y']} mm<br>"
        self.text_desc.setHtml(info)

        thumb = self.component_thumbnails.get(comp['designator'])
        if thumb is not None and not thumb.isNull():
            scaled = thumb.scaled(self.lbl_comp_image.width(),
                                  self.lbl_comp_image.height(),
                                  Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.lbl_comp_image.setPixmap(scaled)
        else:
            self.lbl_comp_image.clear()
            self.lbl_comp_image.setText("Load a STEP model\nfor component images")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())
