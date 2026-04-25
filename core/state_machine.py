import time
import threading
import queue
import cv2
import numpy as np
import os
import re
from PIL import Image, ImageDraw, ImageFont

from core.window_manager import WindowManager
from core.screen_capture import ScreenCapture
from core.controller import Controller
from core.vision import VisionCore
from core.pid import PIDController
from core.record_manager import RecordManager
from core.paths import resource_path

CnOcr = None

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
        self.sc = None 
        self.ctrl = Controller()
        self.vis = VisionCore()
        self.record_mgr = RecordManager()
        self.ocr = {}
        self.ocr_available = True
        self._ocr_import_checked = False
        self._fish_matcher_refs = None
        self._weight_digit_templates = None
        self._last_name_ocr_candidates = []
        self._last_weight_ocr_candidates = []
        self._last_weight_corrections = []
        
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
            "debug_mode": True,
            "cast_animation_delay": 2,
            "settlement_close_delay": 2,
            "bar_missing_timeout": 2,
        }
        
    def _log(self, msg):
        """线程安全的日志发送"""
        if self.log_queue is not None:
            self.log_queue.put(msg)
        else:
            print(msg)

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
        self._log("[系统] 收到停止指令。")
        self.is_running = False
        
        # 记录本次运行时长
        if self.start_timestamp > 0:
            duration = int(time.time() - self.start_timestamp)
            self.total_runtime += duration
            self.record_mgr.add_runtime(duration)
            
        self.ctrl.release_all()
        # 释放系统绘图句柄，防止二次启动时抛出 BitBlt 和 SelectObject 异常
        if hasattr(self, 'sc') and self.sc:
            self.sc.close()
        self._log("钓鱼脚本已停止。")
        # 通知 UI 更新
        if self.log_queue:
            self.log_queue.put("CMD_STOP_UPDATE_GUI")

    def update_config(self, key, value):
        self.config[key] = value
        # 对于超时设置，直接同步到实例变量
        if key == "fishing_timeout":
            self.fishing_timeout = value

    def prepare_recognition_modules(self):
        """预热结算识别所需的 OCR 模块，避免首次上鱼时才加载导致卡顿。"""
        name_ocr = self._ensure_ocr("name")
        weight_ocr = self._ensure_ocr("weight")
        # 图像兜底匹配同样需要首次构建特征，放在初始化阶段完成。
        self._load_fish_matcher_refs()
        return name_ocr is not None and weight_ocr is not None

    def _ensure_ocr(self, mode="general"):
        global CnOcr
        if CnOcr is None and not self._ocr_import_checked:
            self._ocr_import_checked = True
            try:
                from cnocr import CnOcr as LoadedCnOcr
                CnOcr = LoadedCnOcr
            except Exception as exc:
                self.ocr_available = False
                self._log(f"[识别] OCR 模块加载失败，请确认已安装 cnocr 与 onnxruntime: {exc}")
                return None
        if CnOcr is None:
            self.ocr_available = False
            return None
        if not self.ocr_available:
            return None
        if mode not in self.ocr:
            try:
                if mode == "name":
                    self._log("[系统] 正在初始化鱼名 OCR 识别模块...")
                    self.ocr[mode] = CnOcr(det_model_name="naive_det")
                elif mode == "weight":
                    self._log("[系统] 正在初始化重量 OCR 识别模块...")
                    self.ocr[mode] = CnOcr(det_model_name="naive_det", cand_alphabet="0123456789gG克")
                else:
                    self._log("[系统] 正在初始化 OCR 单行识别模块...")
                    self.ocr[mode] = CnOcr(det_model_name="naive_det")
            except Exception as exc:
                self.ocr_available = False
                self._log(f"[识别] OCR 模块初始化失败，已切换到本地图像识别兜底方案: {exc}")
                self.ocr.pop(mode, None)
        return self.ocr.get(mode)

    def _collect_ocr_candidates(self, image, mode="general"):
        ocr = self._ensure_ocr(mode)
        if ocr is None or image is None or image.size == 0:
            return []

        candidates = []
        try:
            result = ocr.ocr_for_single_line(image)
        except Exception as exc:
            self._log(f"[识别] OCR 执行失败: {exc}")
            return []

        if isinstance(result, dict):
            cleaned = (result.get("text") or "").strip()
            if cleaned:
                candidates.append((cleaned, float(result.get("score") or 0.0)))
        elif result:
            cleaned = str(result).strip()
            if cleaned:
                candidates.append((cleaned, 0.0))

        if mode in {"name", "weight"}:
            candidates.sort(key=lambda item: item[1], reverse=True)
            return candidates

        if getattr(ocr, "det_model", None) is not None:
            try:
                results = ocr.ocr(image)
            except Exception:
                results = []
            for item in results or []:
                text = item.get("text", "") if isinstance(item, dict) else str(item)
                score = item.get("score", 0.0) if isinstance(item, dict) else 0.0
                cleaned = (text or "").strip()
                if cleaned:
                    candidates.append((cleaned, float(score or 0.0)))

        candidates.sort(key=lambda item: item[1], reverse=True)
        return candidates

    def _collect_ocr_texts(self, image):
        return [text for text, _ in self._collect_ocr_candidates(image)]

    def _crop_name_text_region(self, image):
        if image is None or image.size == 0:
            return image

        # 结算鱼名是白色描边字，背景常有高亮光效；优先只框选中心标题行的低饱和高亮文字。
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (0, 0, 150), (179, 80, 255))
        mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)), iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        height, width = image.shape[:2]
        boxes = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w * h < 20 or h < max(6, int(height * 0.10)) or w < 4:
                continue
            if w > width * 0.45 or h > height * 0.75:
                continue
            boxes.append((x, y, w, h))

        if not boxes:
            return image

        center_x = width / 2
        center_y = height / 2
        boxes.sort(key=lambda item: abs((item[0] + item[2] / 2) - center_x) + abs((item[1] + item[3] / 2) - center_y) * 0.55)
        row_y = boxes[0][1] + boxes[0][3] / 2
        row_boxes = [
            box for box in boxes
            if abs((box[1] + box[3] / 2) - row_y) < max(18, int(height * 0.20))
        ]

        x1 = min(x for x, _, _, _ in row_boxes)
        y1 = min(y for _, y, _, _ in row_boxes)
        x2 = max(x + w for x, _, w, _ in row_boxes)
        y2 = max(y + h for _, y, _, h in row_boxes)

        pad_x = max(8, int((x2 - x1) * 0.18))
        pad_y = max(6, int((y2 - y1) * 0.40))
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(width, x2 + pad_x)
        y2 = min(height, y2 + pad_y)

        if x2 <= x1 or y2 <= y1:
            return image
        if (x2 - x1) * (y2 - y1) > width * height * 0.72:
            return image
        return image[y1:y2, x1:x2]

    def _crop_weight_digits_region(self, image):
        if image is None or image.size == 0:
            return image

        # 重量数字比单位 g 更高更粗；先按亮色主体分割，再只保留数字高度等级的连通区域。
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        mask = cv2.inRange(hsv, (0, 0, 135), (179, 115, 255))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)), iterations=1)
        mask = cv2.dilate(mask, cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2)), iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        height, width = image.shape[:2]
        boxes = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w * h < 18 or h < max(12, int(height * 0.24)) or w < 4:
                continue
            if w > width * 0.40 or h > height * 0.92:
                continue
            boxes.append((x, y, w, h))

        if not boxes:
            return image

        max_height = max(h for _, _, _, h in boxes)
        top_y = min(y for _, y, _, h in boxes if h >= max_height * 0.70)
        digit_boxes = [
            box for box in boxes
            if box[3] >= max_height * 0.68 and box[1] <= top_y + max(8, int(max_height * 0.24))
        ]
        if not digit_boxes:
            return image

        x1 = min(x for x, _, _, _ in digit_boxes)
        y1 = min(y for _, y, _, _ in digit_boxes)
        x2 = max(x + w for x, _, w, _ in digit_boxes)
        y2 = max(y + h for _, y, _, h in digit_boxes)

        pad_x = max(4, int((x2 - x1) * 0.08))
        pad_y = max(4, int((y2 - y1) * 0.18))
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(width, x2 + pad_x)
        y2 = min(height, y2 + pad_y)

        if x2 <= x1 or y2 <= y1:
            return image
        return image[y1:y2, x1:x2]

    def _crop_text_region(self, image, mode):
        if image is None or image.size == 0:
            return image

        if mode == "name":
            return self._crop_name_text_region(image)
        if mode == "weight":
            return self._crop_weight_digits_region(image)

        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        threshold = 115 if mode == "name" else 135
        mask = cv2.inRange(gray, threshold, 255)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        height, width = gray.shape[:2]
        min_area = max(12, int(width * height * 0.0007))
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w * h < min_area or h < max(6, int(height * 0.10)):
                continue
            boxes.append((x, y, w, h))

        if not boxes:
            return image

        x1 = min(x for x, _, _, _ in boxes)
        y1 = min(y for _, y, _, _ in boxes)
        x2 = max(x + w for x, _, w, _ in boxes)
        y2 = max(y + h for _, y, _, h in boxes)

        pad_x = max(8, int((x2 - x1) * 0.16))
        pad_y = max(5, int((y2 - y1) * 0.28))
        x1 = max(0, x1 - pad_x)
        y1 = max(0, y1 - pad_y)
        x2 = min(width, x2 + pad_x)
        y2 = min(height, y2 + pad_y)

        if x2 <= x1 or y2 <= y1:
            return image
        if (x2 - x1) * (y2 - y1) > width * height * 0.88:
            return image
        return image[y1:y2, x1:x2]

    def _build_ocr_variants(self, image, mode):
        if image is None or image.size == 0:
            return []

        variants = []
        sources = [image]
        cropped = self._crop_text_region(image, mode)
        if cropped is not image and cropped is not None and cropped.size > 0:
            sources.insert(0, cropped)

        scales = (2.0, 3.0, 4.0) if mode == "name" else (2.0,)
        for source in sources:
            for scale in scales:
                enlarged = cv2.resize(source, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
                gray = cv2.cvtColor(enlarged, cv2.COLOR_BGR2GRAY)

                variants.append(enlarged)

                if mode == "name":
                    _, binary = cv2.threshold(gray, 150, 255, cv2.THRESH_BINARY)
                    variants.append(cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR))
                    continue

                denoised = cv2.GaussianBlur(gray, (3, 3), 0)
                _, binary = cv2.threshold(denoised, 165, 255, cv2.THRESH_BINARY)
                inverted = cv2.bitwise_not(binary)
                variants.append(cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR))
                variants.append(cv2.cvtColor(inverted, cv2.COLOR_GRAY2BGR))

        return variants

    def _parse_weight_text(self, text):
        raw_text = str(text or "").strip()
        if not raw_text:
            return 0

        normalized = raw_text.translate(str.maketrans({
            "O": "0",
            "o": "0",
            "〇": "0",
            "I": "1",
            "l": "1",
            "|": "1",
            "S": "5",
            "s": "5",
            "B": "8",
        }))
        compact = re.sub(r"\s+", "", normalized)

        explicit_match = re.search(r"(\d{1,5})(?:[gG克])", compact)
        if explicit_match:
            value = int(explicit_match.group(1))
            return value if 0 < value < 50000 else 0

        if not re.fullmatch(r"\d{1,6}", compact):
            loose_match = re.search(r"(\d{1,6})", compact)
            if not loose_match:
                return 0
            compact = loose_match.group(1)

        value = int(compact)
        return value if 0 < value < 50000 else 0

    def _extract_weight_value(self, texts):
        for text in texts:
            value = self._parse_weight_text(text)
            if value > 0:
                return value
        return 0

    def _is_plausible_name(self, text):
        cleaned = re.sub(r"\s+", "", text or "")
        if len(cleaned) < 2:
            return False
        banned = ["点击空白区域关闭", "获得钓鱼经验", "等级", "LEVEL", "RESULT", "MASTER"]
        return not any(token in cleaned for token in banned)

    def _read_roi_text(self, rect, rois, mode):
        best_text = ""
        weight_candidates = []
        known_fishes = self.record_mgr.get_encyclopedia() if mode == "name" else {}
        name_candidates = []

        for roi in rois:
            image = self.sc.capture_relative(rect, *roi)
            if image is None:
                continue
            for variant in self._build_ocr_variants(image, mode):
                candidates = self._collect_ocr_candidates(variant, mode)
                if not candidates:
                    continue
                if mode == "weight":
                    for text, score in candidates:
                        self._last_weight_ocr_candidates.append((text, score))
                        if score < 0.12:
                            continue
                        value = self._parse_weight_text(text)
                        if value <= 0:
                            continue
                        digit_count = len(str(value))
                        compact = re.sub(r"\s+", "", str(text or "").translate(str.maketrans({
                            "O": "0",
                            "o": "0",
                            "〇": "0",
                            "I": "1",
                            "l": "1",
                            "|": "1",
                            "S": "5",
                            "s": "5",
                            "B": "8",
                        })))
                        has_unit = 1 if re.search(r"\d{1,5}(?:[gG克])", compact) else 0
                        weight_candidates.append((value, float(score or 0.0), has_unit, digit_count, text))
                else:
                    for text, score in candidates:
                        if mode == "name":
                            self._last_name_ocr_candidates.append((text, score))
                            name_candidates.append((text, score))
                            if score >= 0.88:
                                resolved, resolved_score, _ = self.record_mgr.resolve_fish_name_candidates([(text, score)])
                                if resolved in known_fishes and resolved_score >= 1.0:
                                    return resolved, 0
                        if score < 0.16:
                            continue
                        if len(text) > len(best_text):
                            best_text = text

        if mode == "weight":
            if not weight_candidates:
                return "", 0

            explicit_candidates = [item for item in weight_candidates if item[2]]
            pure_candidates = [item for item in weight_candidates if not item[2]]
            explicit_best_score = max((item[1] for item in explicit_candidates), default=-1.0)
            pure_best_score = max((item[1] for item in pure_candidates), default=-1.0)

            if explicit_candidates and explicit_best_score >= pure_best_score - 0.18:
                pool = explicit_candidates
            else:
                pool = weight_candidates

            best_score = max(item[1] for item in pool)
            near_best = [item for item in pool if item[1] >= max(0.12, best_score - 0.08)]
            near_best.sort(key=lambda item: (min(item[3], 5), item[1]), reverse=True)
            return "", near_best[0][0]
        resolved, score, raw_text = self.record_mgr.resolve_fish_name_candidates(name_candidates)
        if resolved in known_fishes:
            if raw_text and raw_text != resolved:
                self._log(f"[识别] 鱼名 OCR 已按图鉴词典修正: {raw_text} -> {resolved} ({score:.2f})")
            return resolved, 0
        return "", 0

    def _load_fish_matcher_refs(self):
        if self._fish_matcher_refs is not None:
            return self._fish_matcher_refs

        refs = []
        orb = cv2.ORB_create(nfeatures=300)
        encyclopedia = self.record_mgr.get_encyclopedia()
        for name, data in encyclopedia.items():
            image_path = data.get("image_path", "")
            if not image_path or not os.path.exists(image_path):
                continue
            try:
                image = cv2.imdecode(np.fromfile(image_path, dtype=np.uint8), cv2.IMREAD_UNCHANGED)
            except Exception:
                continue
            if image is None:
                continue
            if len(image.shape) == 3 and image.shape[2] == 4:
                image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)

            h, w = image.shape[:2]
            crop = image[int(h * 0.12):int(h * 0.82), int(w * 0.12):int(w * 0.88)]
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            _, descriptors = orb.detectAndCompute(gray, None)
            if descriptors is None:
                continue
            refs.append((name, descriptors))

        self._fish_matcher_refs = refs
        return refs

    def _match_fish_by_image(self, rect, rois):
        refs = self._load_fish_matcher_refs()
        if not refs:
            return ""

        orb = cv2.ORB_create(nfeatures=350)
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
        best_name = ""
        best_score = 0
        second_score = 0

        for roi in rois:
            image = self.sc.capture_relative(rect, *roi)
            if image is None or image.size == 0:
                continue
            h, w = image.shape[:2]
            crop = image[int(h * 0.12):int(h * 0.88), int(w * 0.12):int(w * 0.88)]
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            _, query_desc = orb.detectAndCompute(gray, None)
            if query_desc is None:
                continue

            for name, ref_desc in refs:
                matches = matcher.knnMatch(query_desc, ref_desc, k=2)
                good_matches = [
                    m for pair in matches if len(pair) == 2 for m, n in [pair] if m.distance < 0.72 * n.distance
                ]
                score = len(good_matches)
                if score > best_score:
                    second_score = best_score
                    best_score = score
                    best_name = name
                elif score > second_score:
                    second_score = score

        if best_score >= 28 and best_score >= int(second_score * 1.4):
            return best_name
        return ""

    def _build_weight_digit_templates(self):
        if self._weight_digit_templates is not None:
            return self._weight_digit_templates

        font_candidates = [
            r"C:\Windows\Fonts\arialbd.ttf",
            r"C:\Windows\Fonts\bahnschrift.ttf",
            r"C:\Windows\Fonts\segoeuib.ttf",
            r"C:\Windows\Fonts\impact.ttf",
        ]
        templates = {digit: [] for digit in "0123456789"}

        for font_path in font_candidates:
            if not os.path.exists(font_path):
                continue
            try:
                font = ImageFont.truetype(font_path, 92)
            except Exception:
                continue

            for digit in "0123456789":
                canvas = Image.new("L", (120, 140), 0)
                drawer = ImageDraw.Draw(canvas)
                bbox = drawer.textbbox((0, 0), digit, font=font, stroke_width=7)
                text_x = (120 - (bbox[2] - bbox[0])) // 2 - bbox[0]
                text_y = (140 - (bbox[3] - bbox[1])) // 2 - bbox[1]
                drawer.text(
                    (text_x, text_y),
                    digit,
                    font=font,
                    fill=255,
                    stroke_width=7,
                    stroke_fill=0,
                )
                arr = np.array(canvas)
                _, binary = cv2.threshold(arr, 110, 255, cv2.THRESH_BINARY)
                coords = cv2.findNonZero(binary)
                if coords is None:
                    continue
                x, y, w, h = cv2.boundingRect(coords)
                crop = binary[y:y + h, x:x + w]
                crop = cv2.resize(crop, (52, 84), interpolation=cv2.INTER_AREA)
                templates[digit].append(crop)

        self._weight_digit_templates = templates
        return templates

    def _classify_digit_image(self, image):
        templates = self._build_weight_digit_templates()
        if image is None or image.size == 0:
            return "", -1.0

        resized = cv2.resize(image, (52, 84), interpolation=cv2.INTER_AREA)
        best_digit = ""
        best_score = -1.0
        for digit, variants in templates.items():
            for template in variants:
                score = cv2.matchTemplate(resized, template, cv2.TM_CCOEFF_NORMED)[0][0]
                if score > best_score:
                    best_score = score
                    best_digit = digit
        return best_digit, best_score

    def _read_weight_by_template(self, rect, rois):
        for roi in rois:
            image = self.sc.capture_relative(rect, *roi)
            if image is None or image.size == 0:
                continue
            digit_image = self._crop_weight_digits_region(image)
            value = self._extract_weight_from_image_by_template(
                digit_image if digit_image is not None and digit_image.size > 0 else image
            )
            if value > 0:
                return value
        return 0

    def _extract_weight_from_image_by_template(self, image):
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        _, binary = cv2.threshold(gray, 175, 255, cv2.THRESH_BINARY)
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
        binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=1)

        contours, _ = cv2.findContours(binary, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        boxes = []
        h, w = binary.shape[:2]
        for cnt in contours:
            x, y, cw, ch = cv2.boundingRect(cnt)
            if ch < h * 0.38 or cw < 8 or cw > w * 0.28:
                continue
            if y > h * 0.78:
                continue
            boxes.append((x, y, cw, ch))

        if not boxes:
            return 0

        boxes.sort(key=lambda item: item[0])
        top_y = min(box[1] for box in boxes)
        max_height = max(box[3] for box in boxes)
        digits = []
        for x, y, cw, ch in boxes:
            if y > top_y + max_height * 0.12:
                continue
            pad = 4
            crop = binary[max(0, y - pad):min(h, y + ch + pad), max(0, x - pad):min(w, x + cw + pad)]
            digit, score = self._classify_digit_image(crop)
            if digit and score >= 0.18:
                digits.append(digit)

        if not digits:
            return 0

        try:
            return int("".join(digits))
        except ValueError:
            return 0

    def _format_name_ocr_candidates(self):
        unique = []
        seen = set()
        for text, score in sorted(self._last_name_ocr_candidates, key=lambda item: item[1], reverse=True):
            cleaned = str(text or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            unique.append(f"{cleaned}({score:.2f})")
            if len(unique) >= 8:
                break
        return "、".join(unique)

    def _format_weight_ocr_candidates(self):
        unique = []
        seen = set()
        for text, score in sorted(self._last_weight_ocr_candidates, key=lambda item: item[1], reverse=True):
            cleaned = str(text or "").strip()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            unique.append(f"{cleaned}({score:.2f})")
            if len(unique) >= 6:
                break
        return "、".join(unique)

    def _save_unknown_settlement_debug(self, rect, name_rois):
        if not self.config.get("debug_mode", False) or self.sc is None:
            return
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        full_image = self.sc.capture_relative(rect, 0, 0, 1, 1)
        if full_image is not None and full_image.size > 0:
            path = f"debug_settlement_unknown_{timestamp}.png"
            cv2.imwrite(path, full_image)
            self._log(f"[排错] 已保存未知鱼类结算截图: {path}")
        for index, roi in enumerate(name_rois, start=1):
            roi_image = self.sc.capture_relative(rect, *roi)
            if roi_image is not None and roi_image.size > 0:
                path = f"debug_settlement_unknown_name_roi_{timestamp}_{index}.png"
                cv2.imwrite(path, roi_image)

    def _read_settlement_info(self, rect):
        fish_name = ""
        weight_g = 0
        self._last_name_ocr_candidates = []
        self._last_weight_ocr_candidates = []
        self._last_weight_corrections = []

        name_rois = [
            (0.30, 0.14, 0.40, 0.12),
            (0.26, 0.12, 0.48, 0.15),
            (0.34, 0.16, 0.32, 0.10),
            (0.28, 0.18, 0.44, 0.11),
            (0.24, 0.10, 0.52, 0.20),
        ]
        fish_image_rois = [
            (0.33, 0.24, 0.34, 0.34),
            (0.30, 0.22, 0.40, 0.38),
            (0.36, 0.26, 0.28, 0.30),
        ]
        weight_rois = [
            (0.33, 0.62, 0.34, 0.14),
            (0.30, 0.60, 0.40, 0.16),
            (0.36, 0.64, 0.28, 0.12),
        ]
        sample_offsets = [0.28, 0.46, 0.68, 0.92, 1.18]

        elapsed = 0.0
        for target_offset in sample_offsets:
            sleep_for = max(0.0, target_offset - elapsed)
            if sleep_for > 0:
                time.sleep(sleep_for)
            elapsed = target_offset

            if not fish_name:
                candidate_name, _ = self._read_roi_text(rect, name_rois, "name")
                if candidate_name:
                    fish_name = candidate_name

            if weight_g <= 0:
                _, candidate_weight = self._read_roi_text(rect, weight_rois, "weight")
                if candidate_weight > 0:
                    weight_g = candidate_weight

            if weight_g <= 0:
                candidate_weight = self._read_weight_by_template(rect, weight_rois)
                if candidate_weight > 0:
                    weight_g = candidate_weight

            if fish_name and weight_g > 0:
                break

        if not fish_name and not self.ocr_available:
            candidate_name = self._match_fish_by_image(rect, fish_image_rois)
            if candidate_name:
                fish_name = candidate_name

        if fish_name:
            self._log(f"[识别] 结算鱼名识别结果: {fish_name}")
        else:
            candidates = self._format_name_ocr_candidates()
            if candidates:
                self._log(f"[识别] 鱼名 OCR 候选未命中图鉴: {candidates}")
            self._save_unknown_settlement_debug(rect, name_rois)
            fish_name = "未知鱼类"
            self._log("[识别] 未能稳定识别到鱼名，已按未知鱼类记录。")

        if weight_g > 0:
            if self._last_weight_corrections:
                raw_text, corrected = self._last_weight_corrections[-1]
                self._log(f"[识别] 重量 OCR 候选疑似把单位 g 识别为数字，已修正: {raw_text} -> {corrected} g")
            self._log(f"[识别] 结算重量识别结果: {weight_g} g")
        else:
            candidates = self._format_weight_ocr_candidates()
            if candidates:
                self._log(f"[识别] 重量 OCR 候选未能稳定解析: {candidates}")
            self._log("[识别] 未能稳定识别到重量，已按 0 g 记录。")

        return fish_name, weight_g

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
        btn_path = resource_path("assets", "F键图标.png")
        loc, conf = self.vis.find_template(btn_img, btn_path, threshold=0.60, use_edge=False, use_binary=True)
        
        if loc:
            self._log(f"[待机] 识别到 F 键图标 (置信度: {conf:.2f})，坐标: {loc}。准备抛竿。")
            self._log("[待机] > 正在向游戏发送 'F' 键点按指令 (150ms)...")
            self.ctrl.key_tap('F', duration=0.15)
            cast_delay = max(1, min(int(self.config.get("cast_animation_delay", 2)), 5))
            self._log(f"[待机] > 发送完成，等待 {cast_delay} 秒抛竿动画...")
            self.current_state = self.STATE_WAITING
            time.sleep(cast_delay) # 抛竿动画较长，防抖
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
        
        text_path = resource_path("assets", "上钩文字.png")
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
            self._last_target_time = 0 # 每次抛竿重置测速时间戳
            self._target_velocity = 0  # 每次抛竿重置测速历史
            
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
            # 安全保护：如果丢失目标，立刻释放所有按键，防止游标因为惯性飞出界
            self.ctrl.release_all()
            
            if not getattr(self, '_seen_fishing_bar', False):
                # 还没看到过耐力条，说明还在播放上钩的过渡动画
                # 增加一个初始等待超时，比如 5 秒
                if time.time() - self._fishing_start_time > 5.0:
                    self._log("[溜鱼] 长时间未检测到耐力条，进入结果判定...")
                    self._fishing_start_time = 0
                    self.current_state = self.STATE_RESULT
                return

            # 引入容错：偶尔一帧没识别到不算结束，连续丢失超过用户设定才算结束
            if getattr(self, '_missing_start_time', 0) == 0:
                self._missing_start_time = time.time()
            missing_timeout = max(1, min(int(self.config.get("bar_missing_timeout", 2)), 5))
            if time.time() - self._missing_start_time > missing_timeout:
                self._log("[溜鱼] 耐力条消失，停止溜鱼，进入结果判定...")
                self.ctrl.release_all()
                self._fishing_start_time = 0
                self._missing_start_time = 0
                self._last_cursor_x = None
                self._seen_fishing_bar = False
                self._last_target_time = 0  # 重置测速时间戳
                self._target_velocity = 0   # 重置速度历史
                self.current_state = self.STATE_RESULT
            return
        
        # 识别到了，重置丢失计时器，并标记已经看到过耐力条
        self._missing_start_time = 0
        self._seen_fishing_bar = True

        # === 核心追踪算法 (自适应非线性 PID + 前馈控制) ===
        error = target_x - cursor_x
        abs_error = abs(error)
        
        # 计算目标移动速度 (前馈预测)
        now = time.time()
        if getattr(self, '_last_target_time', 0) == 0:
            self._last_target_x = target_x
            self._last_target_time = now
            target_velocity = 0
        else:
            dt = now - self._last_target_time
            if dt > 0.001:
                # 简单低通滤波平滑速度，防止图像抖动导致速度突变
                raw_velocity = (target_x - self._last_target_x) / dt
                old_velocity = getattr(self, '_target_velocity', 0)
                target_velocity = old_velocity * 0.6 + raw_velocity * 0.4
            else:
                target_velocity = getattr(self, '_target_velocity', 0)
                
            self._last_target_x = target_x
            self._last_target_time = now
            self._target_velocity = target_velocity
            
        # 动态安全区：根据绿条宽度计算 (比如绿条宽度的 20%)
        safe_zone = target_w * 0.20 if target_w else 10
        
        # PID 控制器计算基础偏差修正力
        control_signal = self.pid.update(error)
        
        # 引入前馈控制 (Feed-Forward)
        # 目标移动得越快，我们需要提前施加的同向“力”就越大
        ff_gain = 0.15 # 前馈增益系数
        total_signal = control_signal + target_velocity * ff_gain

        # --- 纯非阻塞高频按键控制 ---
        # 动态阈值：
        # 如果游标在安全区内且目标没有高速移动，我们提高触发阈值，释放按键让游标自然滑动，避免左右鬼畜抽搐
        # 如果游标偏离或者目标正在高速逃离，我们降低阈值，要求立即按键追赶
        is_safe = (abs_error <= safe_zone) and (abs(target_velocity) < 80)
        hold_threshold = max(6, min(int(self.config.get("t_hold", 15)), 60))
        deadzone_threshold = max(1, min(int(self.config.get("t_deadzone", 5)), 30))
        threshold = hold_threshold if is_safe else deadzone_threshold

        # 直接根据总信号方向进行按键映射，废弃阻塞线程的 key_tap(sleep)
        if total_signal > threshold:
            # 信号强力向右，需要按 D (同时松开 A 防止冲突)
            self.ctrl.key_up('A')
            self.ctrl.key_down('D')
        elif total_signal < -threshold:
            # 信号强力向左，需要按 A (同时松开 D 防止冲突)
            self.ctrl.key_up('D')
            self.ctrl.key_down('A')
        else:
            # 信号较小，处于完美跟随状态或需要刹车滑行，释放按键
            self.ctrl.release_all()

    def _handle_result(self, rect):
        self._log("[结算] 正在检测钓鱼结果...")
        
        # 如果既没有成功特征，也没有明显的F键，我们还需要检查是不是“鱼儿溜走了”
        # 鱼儿溜走了的特征：屏幕中央有一条黑色横幅，里面有白色文字
        roi_failed_text = (0.2, 0.45, 0.6, 0.1)
        
        max_attempts = 10 # 增加循环次数，但缩短每次的等待时间，实现更敏捷的响应
        failed_path = resource_path("assets", "鱼儿溜走了.png")
        
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
                    self._log("[结算] 识别到结算文字特征，判定为钓鱼成功！正在识别鱼类信息...")

                    fish_name, weight_g = self._read_settlement_info(rect)
                    self.record_mgr.add_catch(fish_name, weight_g)
                    
                    self._log(f"[结算] 捕获: {fish_name}, 重量: {weight_g}g。尝试 ESC 关闭结算界面 (尝试 {attempt+1}/{max_attempts})...")
                    
                    # 仅使用 ESC 关闭
                    self.ctrl.key_tap('esc', duration=0.15)
                    
                    close_delay = max(1, min(int(self.config.get("settlement_close_delay", 2)), 5))
                    time.sleep(close_delay) # 每次操作后多等一会，给动画留足时间
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
