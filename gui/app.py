import customtkinter as ctk
import threading
import queue
import time
import webbrowser
import json
import os
import cv2  # 添加 OpenCV 引用以在主线程显示 Debug 窗口
import win32gui
from collections import deque
import keyboard

from core.state_machine import StateMachine

# GUI 主题设置
ctk.set_appearance_mode("System")  # 支持 System, Dark, Light
ctk.set_default_color_theme("blue")  

CONFIG_FILE = "config.json"

class App(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("异环自动钓鱼")
        self.geometry("650x550")
        
        # 默认配置
        self.config = {
            "hotkey_start": "ctrl+f9",
            "hotkey_stop": "ctrl+f10",
            "hold_threshold": 25,
            "deadzone_threshold": 10,
            "fishing_timeout": 180,
            "debug_mode": False
        }
        self.load_config()
        
        # UI 安全线程通信队列
        self.log_queue = queue.Queue()
        self.debug_queue = queue.Queue()
        self.log_deque = deque(maxlen=200) 
        
        # 核心业务对象
        self.sm = StateMachine(log_queue=self.log_queue, debug_queue=self.debug_queue)
        
        # 布局配置
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # ============ 左侧边栏 ============
        self.sidebar_frame = ctk.CTkFrame(self, width=160, corner_radius=0)
        self.sidebar_frame.grid(row=0, column=0, sticky="nsew")
        self.sidebar_frame.grid_rowconfigure(5, weight=1)

        self.logo_label = ctk.CTkLabel(self.sidebar_frame, text="异环自动钓鱼", font=ctk.CTkFont(size=20, weight="bold"))
        self.logo_label.grid(row=0, column=0, padx=20, pady=(20, 20))

        self.btn_start = ctk.CTkButton(self.sidebar_frame, text=f"启动 ({self.config['hotkey_start']})", command=self.start_bot, fg_color="green", hover_color="darkgreen")
        self.btn_start.grid(row=1, column=0, padx=20, pady=10)

        self.btn_stop = ctk.CTkButton(self.sidebar_frame, text=f"停止 ({self.config['hotkey_stop']})", command=self.stop_bot, fg_color="red", hover_color="darkred", state="disabled")
        self.btn_stop.grid(row=2, column=0, padx=20, pady=10)

        # 状态指示灯
        self.status_label = ctk.CTkLabel(self.sidebar_frame, text="● 待机中", text_color="gray")
        self.status_label.grid(row=3, column=0, padx=20, pady=10)
        
        # 作者信息与超链接
        self.author_label = ctk.CTkLabel(self.sidebar_frame, text="By FADEDTUMI\nOpen Source", text_color="gray", font=ctk.CTkFont(size=12))
        self.author_label.grid(row=6, column=0, padx=20, pady=(10, 0))
        
        self.github_btn = ctk.CTkButton(self.sidebar_frame, text="GitHub 主页", command=self.open_github, fg_color="transparent", border_width=1, text_color=("gray10", "#DCE4EE"))
        self.github_btn.grid(row=7, column=0, padx=20, pady=(5, 20))

        # ============ 右侧主面板 (TabView) ============
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")
        self.tabview.add("主控面板")
        self.tabview.add("高级设置")
        
        self.tabview.tab("主控面板").grid_columnconfigure(0, weight=1)
        self.tabview.tab("主控面板").grid_rowconfigure(0, weight=1)
        
        self.tabview.tab("高级设置").grid_columnconfigure((0, 1), weight=1)

        # ---- Tab: 主控面板 ----
        # 日志输出框
        self.log_textbox = ctk.CTkTextbox(self.tabview.tab("主控面板"), corner_radius=10)
        self.log_textbox.grid(row=0, column=0, padx=10, pady=10, sticky="nsew")
        self.log_textbox.insert("0.0", "--- 异环自动钓鱼初始化完毕 ---\n请确保游戏正在运行，并处于初始钓鱼界面。\n请在“高级设置”中配置快捷键与参数。\n")
        self.log_textbox.configure(state="disabled")

        # ---- Tab: 高级设置 ----
        self.recording_target = None  # 记录当前正在录制哪个快捷键: 'start' 或 'stop'

        # 快捷键设置区
        self.lbl_hotkey_start = ctk.CTkLabel(self.tabview.tab("高级设置"), text="启动快捷键:")
        self.lbl_hotkey_start.grid(row=0, column=0, padx=10, pady=15, sticky="w")
        
        self.btn_record_start = ctk.CTkButton(self.tabview.tab("高级设置"), text=self.config["hotkey_start"], command=lambda: self.start_recording("start"))
        self.btn_record_start.grid(row=0, column=1, padx=10, pady=15, sticky="ew")
        
        self.lbl_hotkey_stop = ctk.CTkLabel(self.tabview.tab("高级设置"), text="停止快捷键:")
        self.lbl_hotkey_stop.grid(row=1, column=0, padx=10, pady=15, sticky="w")
        
        self.btn_record_stop = ctk.CTkButton(self.tabview.tab("高级设置"), text=self.config["hotkey_stop"], command=lambda: self.start_recording("stop"))
        self.btn_record_stop.grid(row=1, column=1, padx=10, pady=15, sticky="ew")

        # 控制阈值区
        self.lbl_hold = ctk.CTkLabel(self.tabview.tab("高级设置"), text="长按追赶阈值 (Hold):")
        self.lbl_hold.grid(row=2, column=0, padx=10, pady=10, sticky="w")
        
        self.slider_hold = ctk.CTkSlider(self.tabview.tab("高级设置"), from_=10, to=50, number_of_steps=40, command=self._update_hold_label)
        self.slider_hold.grid(row=2, column=1, padx=10, pady=10, sticky="ew")
        self.slider_hold.set(self.config.get("hold_threshold", 25))
        
        self.lbl_hold_val = ctk.CTkLabel(self.tabview.tab("高级设置"), text=f"{int(self.slider_hold.get())}")
        self.lbl_hold_val.grid(row=2, column=2, padx=10, pady=10, sticky="w")

        self.lbl_timeout = ctk.CTkLabel(self.tabview.tab("高级设置"), text="防卡死超时(秒):")
        self.lbl_timeout.grid(row=3, column=0, padx=10, pady=10, sticky="w")
        
        self.slider_timeout = ctk.CTkSlider(self.tabview.tab("高级设置"), from_=60, to=300, number_of_steps=240, command=self._update_timeout_label)
        self.slider_timeout.grid(row=3, column=1, padx=10, pady=10, sticky="ew")
        self.slider_timeout.set(self.config.get("fishing_timeout", 180))
        
        self.lbl_timeout_val = ctk.CTkLabel(self.tabview.tab("高级设置"), text=f"{int(self.slider_timeout.get())}")
        self.lbl_timeout_val.grid(row=3, column=2, padx=10, pady=10, sticky="w")
        
        # Debug 开关
        self.switch_debug = ctk.CTkSwitch(self.tabview.tab("高级设置"), text="开启 Debug 视觉窗口 (诊断用)")
        self.switch_debug.grid(row=4, column=0, columnspan=2, padx=10, pady=15, sticky="w")
        if self.config.get("debug_mode", False):
            self.switch_debug.select()
        else:
            self.switch_debug.deselect()
        
        # 保存设置按钮
        self.btn_save_config = ctk.CTkButton(self.tabview.tab("高级设置"), text="应用并保存设置", command=self.save_and_apply_config)
        self.btn_save_config.grid(row=5, column=0, columnspan=2, padx=10, pady=30, sticky="ew")

        # 启动定时更新 UI 的循环
        self.after(100, self.process_queue)
        
        # 绑定初始热键
        self.bind_hotkeys()

    def load_config(self):
        """读取本地配置文件"""
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    saved_config = json.load(f)
                    self.config.update(saved_config)
            except Exception as e:
                print(f"配置文件加载失败: {e}")

    def save_and_apply_config(self):
        """保存设置并应用"""
        # 从按钮的文本上获取最新快捷键 (如果在录制中，先取消录制)
        if self.recording_target:
            self.cancel_recording()
            
        self.config["hotkey_start"] = self.btn_record_start.cget("text")
        self.config["hotkey_stop"] = self.btn_record_stop.cget("text")
        self.config["hold_threshold"] = int(self.slider_hold.get())
        self.config["fishing_timeout"] = int(self.slider_timeout.get())
        self.config["debug_mode"] = bool(self.switch_debug.get())
        
        # 更新左侧面板的主按钮文本
        self.btn_start.configure(text=f"启动 ({self.config['hotkey_start']})")
        self.btn_stop.configure(text=f"停止 ({self.config['hotkey_stop']})")
        
        # 重新绑定快捷键
        self.bind_hotkeys()
        
        # 持久化到文件
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=4)
            self.write_log(">>> 设置已保存并应用！")
            self.tabview.set("主控面板") # 保存后自动切回主页
        except Exception as e:
            self.write_log(f"配置保存失败: {e}")

    def _update_hold_label(self, value):
        """实时更新 Hold 阈值显示"""
        if hasattr(self, 'lbl_hold_val'):
            self.lbl_hold_val.configure(text=f"{int(value)}")

    def _update_timeout_label(self, value):
        """实时更新防卡死超时显示"""
        if hasattr(self, 'lbl_timeout_val'):
            self.lbl_timeout_val.configure(text=f"{int(value)}")

    def open_github(self):
        webbrowser.open("https://github.com/FADEDTUMI")

    def start_recording(self, target):
        """进入快捷键录制模式"""
        # 如果已经在录制其他键，先还原
        if self.recording_target:
            self.cancel_recording()
            
        self.recording_target = target
        
        if target == "start":
            self.btn_record_start.configure(text="正在录制... 请按下按键", fg_color="orange")
        else:
            self.btn_record_stop.configure(text="正在录制... 请按下按键", fg_color="orange")
            
        # 启动一个后台线程来拦截按键
        t = threading.Thread(target=self._record_thread_func, daemon=True)
        t.start()
        
    def cancel_recording(self):
        """取消录制模式，恢复原来的文本"""
        if self.recording_target == "start":
            self.btn_record_start.configure(text=self.config["hotkey_start"], fg_color=["#3B8ED0", "#1F6AA5"])
        elif self.recording_target == "stop":
            self.btn_record_stop.configure(text=self.config["hotkey_stop"], fg_color=["#3B8ED0", "#1F6AA5"])
        self.recording_target = None
        
    def _record_thread_func(self):
        """在后台线程中读取键盘组合键"""
        try:
            # 读取一个完整的按键组合
            hotkey = keyboard.read_hotkey(suppress=False)
            
            # 将结果发送回主线程更新 UI
            self.after(0, self._finish_recording, hotkey)
        except Exception as e:
            print(f"录制错误: {e}")
            self.after(0, self.cancel_recording)
            
    def _finish_recording(self, hotkey_str):
        """录制完成，更新 UI 文本"""
        if not self.recording_target: return
        
        # 简单过滤一些无效的录制 (比如只按了 ctrl)
        if hotkey_str in ["ctrl", "shift", "alt", "windows"]:
            self.cancel_recording()
            self.write_log("请录制包含字母或功能键的完整组合键！")
            return
            
        if self.recording_target == "start":
            self.btn_record_start.configure(text=hotkey_str, fg_color=["#3B8ED0", "#1F6AA5"])
        else:
            self.btn_record_stop.configure(text=hotkey_str, fg_color=["#3B8ED0", "#1F6AA5"])
            
        self.recording_target = None

    def bind_hotkeys(self):
        """重新绑定全局热键"""
        try:
            keyboard.unhook_all()
        except Exception:
            pass
            
        try:
            keyboard.add_hotkey(self.config["hotkey_start"], self.start_bot_from_hotkey, suppress=True)
            keyboard.add_hotkey(self.config["hotkey_stop"], self.stop_bot_from_hotkey, suppress=True)
            self.write_log(f"已绑定全局快捷键 - 启动: {self.config['hotkey_start']} | 停止: {self.config['hotkey_stop']}")
        except Exception as e:
            self.write_log(f"快捷键绑定失败: {e}。请检查输入格式 (如 ctrl+shift+a)。")

    def start_bot_from_hotkey(self):
        if not self.sm.is_running:
            self.after(0, self.start_bot)

    def stop_bot_from_hotkey(self):
        if self.sm.is_running:
            self.after(0, self.stop_bot)

    def write_log(self, msg):
        if msg == "CMD_STOP_UPDATE_GUI":
            self.update_ui_on_stop()
            return
            
        time_str = time.strftime("[%H:%M:%S] ")
        full_msg = time_str + msg + "\n"
        self.log_deque.append(full_msg)
        
        self.log_textbox.configure(state="normal")
        self.log_textbox.delete("0.0", "end")
        self.log_textbox.insert("0.0", "".join(self.log_deque))
        self.log_textbox.see("end")
        self.log_textbox.configure(state="disabled")

    def process_queue(self):
        # 处理日志
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.write_log(msg)
        except queue.Empty:
            pass
            
        # 处理 Debug 图像 (只有在主线程 imshow 才不会卡死)
        try:
            while True:
                img = self.debug_queue.get_nowait()
                
                # 如果窗口不存在，先创建一个不抢焦点的窗口
                if not getattr(self, '_debug_window_created', False):
                    cv2.namedWindow("Fishing Bar Tracker (Debug)", cv2.WINDOW_GUI_NORMAL | cv2.WINDOW_AUTOSIZE)
                    self._debug_window_created = True
                    
                cv2.imshow("Fishing Bar Tracker (Debug)", img)
                cv2.waitKey(1)
                
                # 如果此时前台窗口变成了 Debug 窗口，强制把焦点还给游戏
                fg_hwnd = win32gui.GetForegroundWindow()
                if win32gui.GetWindowText(fg_hwnd) == "Fishing Bar Tracker (Debug)":
                    if self.sm and self.sm.wm and self.sm.wm.hwnd:
                        try:
                            self.sm.wm.set_foreground()
                        except Exception:
                            pass
        except queue.Empty:
            pass
            
        # 如果程序停止了，关闭 OpenCV 窗口
        if not self.sm.is_running:
            try:
                cv2.destroyWindow("Fishing Bar Tracker (Debug)")
            except Exception:
                pass
                
        self.after(50, self.process_queue)

    def start_bot(self):
        if self.sm.is_running: return
        
        # 从配置中拿最新的参数同步给后台
        self.sm.update_config("t_hold", self.config.get("hold_threshold", 25))
        self.sm.update_config("fishing_timeout", self.config.get("fishing_timeout", 180))
        self.sm.update_config("debug_mode", self.config.get("debug_mode", False))
        
        # 禁用设置组件 (防误触)
        self.btn_save_config.configure(state="disabled")
        
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        self.status_label.configure(text="● 运行中", text_color="green")
        
        # 启动时强制切回主控面板看日志
        self.tabview.set("主控面板")
        
        self.write_log(">>> 启动自动钓鱼...")
        self.sm.start()

    def stop_bot(self):
        if not self.sm.is_running: return
        self.sm.stop()
        self.write_log(">>> 已手动发送停止指令。")
        self.update_ui_on_stop()
        
    def update_ui_on_stop(self):
        """恢复UI组件状态"""
        self.btn_save_config.configure(state="normal")
        
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")
        self.status_label.configure(text="● 已停止", text_color="red")
