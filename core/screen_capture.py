import mss
import mss.exception
import numpy as np
import time

class ScreenCapture:
    """屏幕截图工具类，使用 mss 实现高频低延迟截图"""
    
    def __init__(self):
        # 放弃全局单例，改为每个线程拥有自己独立的 mss 实例
        # 这样在线程销毁时，可以安全地释放对应的系统 GDI 句柄
        self.sct = mss.mss()
        
    def close(self):
        """显式释放 mss 占用的系统 GDI 句柄资源"""
        if hasattr(self, 'sct') and self.sct:
            self.sct.close()
            self.sct = None
            
    def capture_roi(self, left, top, width, height):
        """
        截取屏幕上指定 ROI 区域，并返回 numpy (OpenCV BGR格式)
        参数为屏幕绝对坐标
        """
        # 防止因窗口极度缩小导致计算出的 width/height <= 0
        # 增加更严格的尺寸校验：如果窗口被缩得太小（例如最小化时变成极小的图标），也拒绝截图
        if width <= 10 or height <= 10:
            return None

        monitor = {
            "top": int(top),
            "left": int(left),
            "width": int(width),
            "height": int(height)
        }
        
        try:
            sct_img = self.sct.grab(monitor)
            # mss 返回的是 BGRA，转换为 BGR
            img = np.array(sct_img)[:, :, :3]
            # mss grab 返回的 np.array 默认是只读的，如果要用 cv2 处理建议 copy
            return np.copy(img)
        except mss.exception.ScreenShotError as e:
            # 捕获 BitBlt 或 SelectObject 异常：这通常发生在游戏切换全屏、窗口被强制覆盖或系统资源短暂枯竭时
            print(f"[ScreenCapture] mss 截图异常 (系统绘图失败): {e}")
            # 极其重要：在发生底层绘图错误时，必须强制休眠一小段时间，
            # 否则死循环会瞬间产生成千上万个异常，导致整个 Python 进程崩溃
            time.sleep(0.1)
            return None
        except Exception as e:
            print(f"[ScreenCapture] 未知截图异常: {e}")
            time.sleep(0.1)
            return None
        
    def capture_relative(self, window_rect, rx, ry, rw, rh):
        """
        基于客户区窗口截取相对区域。
        例如 rx=0.5, ry=0.1, rw=0.2, rh=0.1 表示截取中心偏上的一块区域。
        window_rect: (left, top, width, height)
        """
        if not window_rect:
            return None
            
        w_left, w_top, w_width, w_height = window_rect
        
        abs_left = w_left + int(w_width * rx)
        abs_top = w_top + int(w_height * ry)
        abs_width = int(w_width * rw)
        abs_height = int(w_height * rh)
        
        return self.capture_roi(abs_left, abs_top, abs_width, abs_height)

    def close(self):
        """释放 mss 资源"""
        if self.sct:
            self.sct.close()
