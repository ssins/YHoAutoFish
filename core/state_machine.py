import time
import threading
import queue
import cv2
import os

from core.window_manager import WindowManager
from core.screen_capture import ScreenCapture
from core.controller import Controller
from core.vision import VisionCore
from core.pid import PIDController

class StateMachine:
    STATE_IDLE = 0
    STATE_WAITING = 1
    STATE_FISHING = 2
    STATE_RESULT = 3
    STATE_FAILED = 4
    STATE_PAUSED = 5
    
    def __init__(self, log_queue=None, debug_queue=None, config=None):
        self.log_queue = log_queue
        self.debug_queue = debug_queue
        
        self.wm = WindowManager()
        # 将 ScreenCapture 的实例化推迟到 _run_loop 内部（即新线程内部），
        # 避免在主线程中创建 mss 实例却在子线程中调用/销毁，导致跨线程 GDI 句柄异常。
        self.sc = None 
        self.ctrl = Controller()
        self.vis = VisionCore()
        
        self.is_running = False
        self.current_state = self.STATE_IDLE
        self.fishing_start_time = 0
        self.fishing_timeout = 180 # 3分钟超时防卡死
        self.fish_count = 0
        
        # 实例化真正的 PID 控制器
        # Kp: 比例，影响追赶速度
        # Ki: 积分，消除长期偏差（设为极小）
        # Kd: 微分，物理刹车预测防过冲（异环这种带惯性的游戏，Kd需要比较大）
        self.pid = PIDController(kp=1.2, ki=0.01, kd=0.4, output_limits=(-100, 100))
        self.total_runtime = 0
        self.start_timestamp = 0
        
        # 参数配置 (后续可由 GUI 更新)
        self.config = config or {
            "t_hold": 15,       # 长按阈值像素
            "t_deadzone": 5,    # 死区像素
            "hotkey_start": 'f9',
            "hotkey_stop": 'f10',
            "debug_mode": True
        }
        
    def _log(self, msg):
        """线程安全的日志发送"""
        self.log_queue.put(msg)

    def start(self):
        """启动状态机"""
        if self.is_running: return
        self.is_running = True
        self.current_state = self.STATE_IDLE
        self.start_timestamp = time.time()
        self._log("钓鱼脚本启动中，正在寻找游戏窗口...")
        
        # 在独立线程运行主循环
        t = threading.Thread(target=self._run_loop, daemon=True)
        t.start()

    def stop(self):
        """停止状态机"""
        if not self.is_running: return
        self.is_running = False
        self.ctrl.release_all()
        # 释放系统绘图句柄，防止二次启动时抛出 BitBlt 和 SelectObject 异常
        if hasattr(self, 'sc') and self.sc:
            self.sc.close()
        self._log("钓鱼脚本已停止。")
        # 传递特定的控制指令给 GUI，让 GUI 恢复按钮状态
        self._log("CMD_STOP_UPDATE_GUI")

    def update_config(self, key, value):
        self.config[key] = value
        # 对于超时设置，直接同步到实例变量
        if key == "fishing_timeout":
            self.fishing_timeout = value

    def _run_loop(self):
        # 确保在当前线程中实例化 ScreenCapture
        self.sc = ScreenCapture()
        
        # 初始化与绑定窗口
        if not self.wm.find_window():
            self._log("错误: 未找到游戏进程 HTGame.exe。请确保游戏正在运行。")
            self.stop()
            return
            
        self._log("成功绑定游戏窗口。")
        self.wm.set_foreground()
        time.sleep(1) # 等待窗口置顶完成
        
        # ROI 定义 (相对于客户区宽高)
        # 缩小寻找 F 键的范围，只截取屏幕真正的右下角边缘，避免把中间的发光背景截进去
        ROI_F_BTN = (0.75, 0.75, 0.25, 0.25)
        self.roi_f_btn = ROI_F_BTN # 保存给其他状态使用
        
        # 恢复合理的高度范围，根据用户提供的精确比例进行定位：
        # 横向占比是30%到70% (X: 0.3, Width: 0.4)
        # 竖向占比是从5.56%到8.33% (Y: 0.0556, Height: 0.0277)
        ROI_FISHING_BAR = (0.3, 0.0556, 0.4, 0.0277) 
        
        ROI_CENTER_TEXT = (0.2, 0.2, 0.6, 0.5)
        
        # DEBUG 计数器，防止写爆硬盘
        debug_save_count = 0

        while self.is_running:
            # 1. 焦点保护机制
            if not self.wm.is_foreground():
                # 检查当前焦点是否是被我们自己的 Debug 窗口抢走了
                import win32gui
                fg_hwnd = win32gui.GetForegroundWindow()
                if win32gui.GetWindowText(fg_hwnd) == "Fishing Bar Tracker (Debug)":
                    # 如果是被 Debug 窗口抢走的，不要暂停按键，尝试切回去
                    self.wm.set_foreground()
                else:
                    self._log("警告: 游戏窗口失去焦点，暂停按键发送。")
                    self.ctrl.release_all()
                    time.sleep(1)
                    continue
                
            # 2. 获取实时窗口坐标 (防止窗口被拖动)
            rect = self.wm.get_client_rect()
            if not rect:
                self._log("获取窗口坐标失败，请不要最小化游戏。")
                time.sleep(1)
                continue
                
            # 3. 状态分发
            if self.current_state == self.STATE_IDLE:
                self._handle_idle(rect, ROI_F_BTN)
            elif self.current_state == self.STATE_WAITING:
                self._handle_waiting(rect, ROI_CENTER_TEXT)
            elif self.current_state == self.STATE_FISHING:
                self._handle_fishing(rect, ROI_FISHING_BAR)
            elif self.current_state == self.STATE_RESULT:
                self._handle_result(rect)
            elif self.current_state == self.STATE_FAILED:
                self._handle_failed()
                
            # 控制基础循环帧率
            time.sleep(0.01)
            
        self.sc.close()

    def _handle_idle(self, rect, roi):
        self._log("[待机] 正在检测右下角抛竿图标...")
        
        # 截取右下角 ROI
        btn_img = self.sc.capture_relative(rect, *roi)
        if btn_img is None: 
            time.sleep(1)
            return
            
        # DEBUG 计数器
        if not hasattr(self, '_debug_count'): self._debug_count = 0
        self._debug_count += 1
            
        # 找图匹配
        # 在待机状态下，利用 use_binary=True 强力二值化特征提取。
        # 它可以无视白天水面的高亮背景，只对比纯白色图标本身，使得匹配成功率大幅提升。
        # 此时阈值可以安全地设在 0.65 甚至更高，彻底防止将背景噪点当成 F 键。
        btn_path = os.path.join("assets", "F键图标.png")
        loc, conf = self.vis.find_template(btn_img, btn_path, threshold=0.60, use_edge=False, use_binary=True)
        
        if loc:
            self._log(f"[待机] 识别到 F 键图标 (置信度: {conf:.2f})，坐标: {loc}。准备抛竿。")
            self._log("[待机] > 正在向游戏发送 'F' 键点按指令 (150ms)...")
            self.ctrl.key_tap('F', duration=0.15)
            self._log("[待机] > 发送完成，等待 2 秒抛竿动画...")
            self.current_state = self.STATE_WAITING
            time.sleep(2) # 抛竿动画较长，防抖
        else:
            if self._debug_count % 10 == 0 and self._debug_count <= 30:
                cv2.imwrite("debug_f_btn_roi.png", btn_img)
                self._log(f"[排错] 抛竿图标匹配失败，最高置信度: {conf:.2f}。已保存当前截图至根目录 debug_f_btn_roi.png")
            time.sleep(0.5)

    def _handle_waiting(self, rect, roi):
        # 每隔一小段时间检测一次即可，不需要过高频率
        time.sleep(0.1) 
        
        text_img = self.sc.capture_relative(rect, *roi)
        if text_img is None: return
        
        # 每次重新抛竿后，重置 PID 控制器状态
        self.pid.reset()
        
        text_path = os.path.join("assets", "上钩文字.png")
        loc, conf = self.vis.find_template(text_img, text_path, threshold=0.7)
        
        if loc:
            self._log(f"[等待] 识别到上钩提示 (置信度: {conf:.2f})，迅速按F！")
            self.ctrl.key_tap('F')
            self.fishing_start_time = time.time()
            self.current_state = self.STATE_FISHING
            # 移除了硬编码的 1.5 秒 sleep，改为在 _handle_fishing 中动态等待耐力条出现，
            # 这样对于出现极快的稀有鱼可以做到零延迟响应。


    def _handle_fishing(self, rect, roi):
        # 记录进入溜鱼状态的时间，用于防卡死
        if getattr(self, '_fishing_start_time', 0) == 0:
            self._fishing_start_time = time.time()
            self._last_cursor_x = None # 记录上一帧的游标位置，用于预测速度
            self._seen_fishing_bar = False # 记录是否已经看到过耐力条
            
        elapsed = time.time() - self._fishing_start_time
        if elapsed > self.fishing_timeout:
            self._log("[防卡死] 溜鱼超时，强制结束当前回合。")
            self._fishing_start_time = 0
            self.current_state = self.STATE_RESULT
            return

        # 截取耐力条 ROI
        bar_img = self.sc.capture_relative(rect, *roi)
        if bar_img is None: return
        
        target_x, cursor_x, target_w, debug_img = self.vis.analyze_fishing_bar(bar_img)
        
        # 性能优化：限制 Debug 图像的发送频率（一秒最多 10 帧），防止撑爆队列导致主线程阻塞
        if self.config.get("debug_mode", True) and debug_img is not None:
            now = time.time()
            if getattr(self, '_last_debug_time', 0) == 0 or (now - self._last_debug_time) > 0.1:
                if self.debug_queue and self.debug_queue.qsize() < 2:
                    self.debug_queue.put(debug_img)
                self._last_debug_time = now

        # 判断是否结束 (无论是成功还是鱼儿溜走，耐力条都会消失)
        if target_x is None or cursor_x is None:
            if not getattr(self, '_seen_fishing_bar', False):
                # 还没看到过耐力条，说明还在播放上钩的过渡动画
                # 增加一个初始等待超时，比如 5 秒
                if time.time() - self._fishing_start_time > 5.0:
                    self._log("[溜鱼] 长时间未检测到耐力条，进入结果判定...")
                    self._fishing_start_time = 0
                    self.current_state = self.STATE_RESULT
                return

            # 引入容错：偶尔一帧没识别到不算结束，连续 1.5 秒没识别到才算结束
            if getattr(self, '_missing_start_time', 0) == 0:
                self._missing_start_time = time.time()
            elif time.time() - self._missing_start_time > 1.5:
                self._log("[溜鱼] 耐力条消失，停止溜鱼，进入结果判定...")
                self.ctrl.release_all()
                self._fishing_start_time = 0
                self._missing_start_time = 0
                self._last_cursor_x = None
                self._seen_fishing_bar = False
                self.current_state = self.STATE_RESULT
            return
        
        # 识别到了，重置丢失计时器，并标记已经看到过耐力条
        self._missing_start_time = 0
        self._seen_fishing_bar = True

        # === 核心追踪算法 (自适应非线性 PID 阻尼控制) ===
        # 计算偏差
        # diff > 0 说明游标偏左，目标在右，需要向右追赶
        # diff < 0 说明游标偏右，目标在左，需要向左追赶
        error = target_x - cursor_x
        abs_error = abs(error)
        
        # 动态死区：根据当前绿条的实际宽度计算绝对安全区 (比如绿条宽度的 25%)
        safe_zone = target_w * 0.25 if target_w else 10
        
        # 把偏差喂给真正的 PID 控制器，获取需要输出的“力”
        # PID 的输出是一个有正负的数值，代表要按下的方向和强度
        control_signal = self.pid.update(error)
        abs_signal = abs(control_signal)

        # 1. 如果游标稳稳在安全区内，松开所有按键，让其自然滑动
        if abs_error <= safe_zone:
            self.ctrl.release_all()
            return
            
        # 2. 如果游标偏离，但控制信号出现反向（说明速度太快，PID 的 D 预测到即将过冲，产生了刹车信号）
        if error > 0 and control_signal < -10:
            # 目标在右，本来该按 D，但信号说要向左刹车
            self.ctrl.release_all()
            self.ctrl.key_tap('A', duration=0.01) # 物理急刹
            return
        elif error < 0 and control_signal > 10:
            # 目标在左，本来该按 A，但信号说要向右刹车
            self.ctrl.release_all()
            self.ctrl.key_tap('D', duration=0.01)
            return

        # 3. 将 PID 强度映射为键盘的 PWM (脉宽调制) 点击时间
        # 信号越强，点按时间越长（甚至直接长按）
        t_hold_signal = 50 # 如果 PID 信号强度超过这个值，就视为需要长按
        
        # 信号强度转点击时长：0.005s 到 0.03s 的超高频微操
        tap_duration = max(0.005, min(0.03, abs_signal / t_hold_signal * 0.03))

        # 执行动作
        if control_signal > 0:
            # 需要向右 (按 D)
            self.ctrl.key_up('A')
            if abs_signal > t_hold_signal:
                self.ctrl.key_down('D')
            else:
                self.ctrl.key_tap('D', duration=tap_duration)
        elif control_signal < 0:
            # 需要向左 (按 A)
            self.ctrl.key_up('D')
            if abs_signal > t_hold_signal:
                self.ctrl.key_down('A')
            else:
                self.ctrl.key_tap('A', duration=tap_duration)

    def _handle_result(self, rect):
        self._log("[结算] 正在检测钓鱼结果...")
        
        # 如果既没有成功特征，也没有明显的F键，我们还需要检查是不是“鱼儿溜走了”
        # 鱼儿溜走了的特征：屏幕中央有一条黑色横幅，里面有白色文字
        roi_failed_text = (0.2, 0.45, 0.6, 0.1)
        
        max_attempts = 10 # 增加循环次数，但缩短每次的等待时间，实现更敏捷的响应
        failed_path = os.path.join("assets", "鱼儿溜走了.png")
        
        # 成功结算界面的最底部，有一行非常清晰的白色文字：“点击空白区域关闭”
        # 我们截取屏幕底部的这块区域，通过分析其亮度（是否存在大量白色像素）来判断是否处于成功界面
        roi_bottom_text = (0.3, 0.85, 0.4, 0.1)

        for attempt in range(max_attempts):
            # 1. 优先检测中央的“鱼儿溜走了”横幅 (唯一失败判定标准)
            failed_img = self.sc.capture_relative(rect, *roi_failed_text)
            if failed_img is not None:
                # 使用真实的资产图片进行特征匹配，彻底解决误判
                # 鱼儿溜走了是白底黑字，可以直接使用二值化来排除背景光照干扰
                loc_fail, conf_fail = self.vis.find_template(failed_img, failed_path, threshold=0.60, use_edge=False, use_binary=True)
                if loc_fail:
                    self._log(f"[结算] 识别到“鱼儿溜走了”横幅 (置信度: {conf_fail:.2f})！判定为钓鱼失败，已自动重置。")
                    self.current_state = self.STATE_IDLE
                    return

            # 2. 检测是否成功（底部出现了“点击空白区域关闭”之类的白色高亮文本）
            bottom_img = self.sc.capture_relative(rect, *roi_bottom_text)
            if bottom_img is not None:
                # 简单粗暴且高效的亮度检测：将图像转为灰度，统计亮度大于 200 的纯白像素数量
                gray = cv2.cvtColor(bottom_img, cv2.COLOR_BGR2GRAY)
                white_pixels = cv2.countNonZero(cv2.inRange(gray, 200, 255))
                
                # 如果底部有大量高亮文字，说明真的是成功结算界面了
                if white_pixels > 150:
                    self._log("[结算] 识别到结算文字特征，判定为钓鱼成功！")
                    self._log(f"[结算] 尝试 ESC 关闭结算界面 (尝试 {attempt+1}/{max_attempts})...")
                    
                    # 仅使用 ESC 关闭
                    self.ctrl.key_tap('esc', duration=0.15)
                    
                    time.sleep(2) # 每次操作后多等一会，给动画留足时间
                    self.fish_count += 1
                    self._log(f"[结算] 成功关闭结算界面。当前累计钓获: {self.fish_count} 条。等待抛竿...")
                    self.current_state = self.STATE_IDLE
                    return
                    
            # 如果既没有 F 键，也没有底部文字，说明可能还在播放动画，稍微等一下继续循环
            time.sleep(0.5)

        # 如果试了多次还是不行，就强行重置，避免脚本卡死在这个状态
        self._log("[警告] 结算超时，强制返回待机状态。")
        self.current_state = self.STATE_IDLE

    def _handle_failed(self):
        # 注意: 这里的“溜走了”如果用户提供了图片，建议也走 find_template
        # 目前暂时作为占位或使用超时跳出
        self._log("[失败/结束] 释放按键，等待复位。")
        self.ctrl.release_all()
        time.sleep(1.5)
        self.current_state = self.STATE_IDLE
