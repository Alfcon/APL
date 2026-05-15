from PyQt5.QtWidgets import QGraphicsRectItem
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPen, QBrush


class ComponentItem(QGraphicsRectItem):
    def __init__(self, comp_data, x, y, width=15.0, height=10.0, rotation=0.0):
        super().__init__(-width / 2, -height / 2, width, height)
        self.comp_data = comp_data
        self.setPos(x, y)
        self.setBrush(QBrush(QColor(60, 180, 90, 90)))
        pen = QPen(QColor(20, 100, 40))
        pen.setCosmetic(True)
        pen.setWidthF(1.2)
        self.setPen(pen)
        if rotation:
            self.setRotation(rotation)
        self.setToolTip(f"{comp_data['designator']}: {comp_data['description']}")
