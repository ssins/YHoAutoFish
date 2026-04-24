import os

from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QImage, QPixmap


class ImageCache(QObject):
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        super().__init__()
        self.vram_cache = {}

    def _load_pixmap(self, path, name):
        if name in self.vram_cache:
            return self.vram_cache[name]

        if not path or not os.path.exists(path):
            self.vram_cache[name] = QPixmap()
            return self.vram_cache[name]

        image = QImage(path)
        if image.isNull():
            self.vram_cache[name] = QPixmap()
            return self.vram_cache[name]

        image = image.scaled(220, 220, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pixmap = QPixmap.fromImage(image)
        self.vram_cache[name] = pixmap
        return pixmap

    def request_image(self, path, name, _rarity, callback):
        callback(name, self._load_pixmap(path, name))

    def preload_many(self, fish_entries):
        for name, data in fish_entries:
            self._load_pixmap(data.get("image_path", ""), name)
