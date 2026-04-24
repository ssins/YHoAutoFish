import sys, os
sys.path.append(os.getcwd())

print("Testing imports...")
try:
    import cv2
    print("cv2 OK")
except Exception as e: print(e)

try:
    from PySide6.QtWidgets import QApplication
    print("PySide6 OK")
except Exception as e: print(e)

try:
    from core.window_manager import WindowManager
    print("WM OK")
except Exception as e: print(e)

try:
    from core.screen_capture import ScreenCapture
    print("SC OK")
except Exception as e: print(e)

try:
    from core.vision import VisionCore
    print("Vis OK")
except Exception as e: print(e)

try:
    from gui.app import AppWindow
    print("AppWindow OK")
except Exception as e: print(e)

print("Done")