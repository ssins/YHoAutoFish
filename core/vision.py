import cv2
import numpy as np

class VisionCore:
    def __init__(self):
        # 初始化默认的HSV阈值，后续可由GUI配置传入覆盖
        self.hsv_config = {
            "green": {"min": [40, 50, 50], "max": [80, 255, 255]},
            "yellow": {"min": [15, 100, 100], "max": [35, 255, 255]}
        }
        
    def update_hsv_config(self, color_name, min_val, max_val):
        """用于GUI动态调节HSV参数"""
        if color_name in self.hsv_config:
            self.hsv_config[color_name]["min"] = min_val
            self.hsv_config[color_name]["max"] = max_val

    def find_template(self, screen_img, template_path, threshold=0.75, use_edge=False, use_binary=False):
        """
        在屏幕截图中寻找模板图片 (支持中文路径)
        use_edge: 是否使用 Canny 边缘检测匹配（排除光照干扰）
        use_binary: 是否使用二值化提取高亮特征匹配（适用于白天水面强光下的纯白 UI 图标）
        返回 (x, y) 坐标，如果没有找到返回 (None, None)
        """
        try:
            # 避免使用 cv2.imread 读取中文路径报错，使用 numpy fromfile
            template = cv2.imdecode(np.fromfile(template_path, dtype=np.uint8), -1)
            
            if template is None:
                print(f"[Vision] 无法解析图片数据: {template_path}")
                return None, 0.0

            # 统一转为灰度图
            screen_gray = cv2.cvtColor(screen_img, cv2.COLOR_BGR2GRAY)
            
            # 如果模板有 alpha 通道（透明背景），我们可以提取它的 mask，但通常为了简单直接用灰度
            if len(template.shape) == 3 and template.shape[2] == 4:
                # 把透明背景变成黑色
                alpha_channel = template[:, :, 3]
                rgb_channels = template[:, :, :3]
                # 创建一个白色或黑色背景
                background = np.zeros_like(rgb_channels, dtype=np.uint8)
                alpha_factor = alpha_channel[:, :, np.newaxis] / 255.0
                template_bgr = (rgb_channels * alpha_factor + background * (1 - alpha_factor)).astype(np.uint8)
                template_gray = cv2.cvtColor(template_bgr, cv2.COLOR_BGR2GRAY)
            else:
                template_gray = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY)

            # 强力防干扰：二值化处理
            # 只提取图像中最亮的部分（纯白色的字母和边框），把所有灰色、蓝色的水面全部变成纯黑
            if use_binary:
                # 像素值大于 200 的变成 255（纯白），其他的变成 0（纯黑）
                _, screen_gray = cv2.threshold(screen_gray, 200, 255, cv2.THRESH_BINARY)
                _, template_gray = cv2.threshold(template_gray, 200, 255, cv2.THRESH_BINARY)

            if use_edge and not use_binary:
                screen_gray = cv2.Canny(screen_gray, 50, 150)
                template_gray = cv2.Canny(template_gray, 50, 150)
            
            best_match = None
            best_val = -1
            best_loc = None
            best_scale = 1.0
            
            # 多尺度匹配 (Multi-scale Template Matching)
            # 因为游戏分辨率不同，截到的F键大小可能和我们存的图片大小不一样
            # 从 0.5 倍到 1.5 倍，每次缩放 10% 去匹配
            for scale in np.linspace(0.5, 1.5, 11)[::-1]:
                # 缩放模板
                width = int(template_gray.shape[1] * scale)
                height = int(template_gray.shape[0] * scale)
                
                # 如果缩放后的模板比截图还要大，就跳过
                if width > screen_gray.shape[1] or height > screen_gray.shape[0]:
                    continue
                    
                resized_template = cv2.resize(template_gray, (width, height))
                
                # 进行匹配
                res = cv2.matchTemplate(screen_gray, resized_template, cv2.TM_CCOEFF_NORMED)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
                
                if max_val > best_val:
                    best_val = max_val
                    best_loc = max_loc
                    best_scale = scale
                    best_match = resized_template

            if best_val >= threshold and best_match is not None:
                h, w = best_match.shape[:2]
                center_x = best_loc[0] + w // 2
                center_y = best_loc[1] + h // 2
                return (center_x, center_y), best_val
                
            return None, best_val
        except Exception as e:
            print(f"[Vision] Template matching error: {e}")
            return None, 0.0

    def analyze_fishing_bar(self, roi_img):
        """
        [极简防抖重构版]
        解析上方耐力条区域，提取绿条(目标)和黄条(游标)的中心X坐标。
        抛弃了不可靠的 HSV 颜色空间，直接通过灰度和亮度阈值定位高亮的游标。
        """
        if roi_img is None or roi_img.size == 0:
            return None, None, roi_img
            
        # ==========================================
        # 根据主程序的精确 ROI 截取，这里不再需要进行二次裁剪或涂黑处理
        # 直接使用 roi_img 进行 HSV 分析
        # ==========================================
        
        debug_img = roi_img.copy()
        
        # 1. 提取黄色游标 (高亮 + 黄色特征)
        # 将图像转换为 HSV 图，提取黄色范围
        hsv = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)
        
        # 精准黄色 HSV 范围 (H: 20-40, S: 100-255, V: 200-255)
        lower_yellow = np.array([20, 100, 200])
        upper_yellow = np.array([40, 255, 255])
        cursor_mask = cv2.inRange(hsv, lower_yellow, upper_yellow)
        
        # 2. 提取绿色目标区域 (中等亮度绿条)
        # 恢复对绿色色相的限制，防止提取到蓝天或白云，同时放宽饱和度
        # H: 40(偏黄绿) 到 90(偏青绿)
        lower_green = np.array([40, 40, 60])
        upper_green = np.array([90, 255, 255])
        target_mask = cv2.inRange(hsv, lower_green, upper_green)
        
        # 对于绿条，不进行极其严格的形态学限制，因为它可能因为半透明被截断
        target_info = self._get_center_x(target_mask, is_vertical=False, strict_shape=False, return_width=True)
        cursor_info = self._get_center_x(cursor_mask, is_vertical=True, strict_shape=True, return_width=True)
        
        target_x, target_w = target_info if target_info else (None, None)
        cursor_x, cursor_w = cursor_info if cursor_info else (None, None)
        
        # 在 Debug 图像上画线
        if target_x is not None:
            # 画出绿条的中心线和宽度范围
            cv2.line(debug_img, (target_x, 0), (target_x, debug_img.shape[0]), (0, 255, 0), 2)
            cv2.rectangle(debug_img, (target_x - target_w//2, 0), (target_x + target_w//2, debug_img.shape[0]), (0, 100, 0), 1)
        if cursor_x is not None:
            cv2.line(debug_img, (cursor_x, 0), (cursor_x, debug_img.shape[0]), (0, 255, 255), 2)
            
        return target_x, cursor_x, target_w, debug_img

    def _get_center_x(self, mask, is_vertical=False, strict_shape=True, return_width=False):
        """从二值化掩码中找到最大的合法轮廓，并返回中心X坐标 (以及可选的宽度)"""
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours: return None
        
        # 按照面积从大到小排序，只取最大的那个，防止被背景的小噪点干扰
        contours = sorted(contours, key=cv2.contourArea, reverse=True)
        
        for cnt in contours:
            x, y, w, h = cv2.boundingRect(cnt)
            area = w * h
            
            # 忽略过小的噪点
            if area < 5: 
                continue
                
            if strict_shape:
                # 宽容的形态学过滤：
                # 黄色游标 (is_vertical=True) 应该是竖着的，高大于宽，放宽要求
                if is_vertical and w > h * 1.8: 
                    continue
                    
                # 绿色目标条 (is_vertical=False) 应该是横着的，宽大于高
                if not is_vertical and h > w * 1.8:
                    continue
                
            if return_width:
                return x + w // 2, w
            return x + w // 2
            
        return None
