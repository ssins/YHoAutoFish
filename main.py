import sys
import os

# Ensure modules can be found
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QIcon
from core.paths import resource_path
from gui.app import AppWindow

if __name__ == '__main__':
    print("Starting app...", flush=True)
    app = QApplication(sys.argv)
    
    app.setApplicationName("FishingBot")
    app.setWindowIcon(QIcon(resource_path("logo.jpg")))
    
    print("Creating AppWindow...", flush=True)
    window = AppWindow()
    print("Showing AppWindow...", flush=True)
    window.show()
    
    sys.exit(app.exec())
