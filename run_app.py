import sys
import os

# Ensure modules can be found
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication
from gui.app import AppWindow

if __name__ == '__main__':
    print("Starting app...")
    app = QApplication(sys.argv)
    
    app.setApplicationName("FishingBot")
    
    window = AppWindow()
    window.show()
    
    try:
        sys.exit(app.exec())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if hasattr(window, 'sm'):
            window.sm.stop()
        os._exit(0)
