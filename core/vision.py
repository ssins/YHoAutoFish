import cv2
import numpy as np
import os

class VisionCore:
    def __init__(self):
        # 初始化默认的HSV阈值，后续可由GUI配置传入覆盖
        self.hsv_config = {
            "green": {"min": [40, 50, 50], "max": [80, 255, 255]},
            "yellow": {"min": [15, 100, 100], "max": [35, 255, 255]}
        }
        self._template_cache = {}
        self._processed_template_cache = {}
        
    def update_hsv_config(self, color_name, min_val, max_val):
        """用于GUI动态调节HSV参数"""
        if color_name in self.hsv_config:
            self.hsv_config[color_name]["min"] = min_val
            self.hsv_config[color_name]["max"] = max_val

    def _read_template(self, template_path):
        path = os.fspath(template_path)
        if path in self._template_cache:
            return self._template_cache[path]

        if not os.path.exists(path):
            self._template_cache[path] = None
            return None

        template = cv2.imdecode(np.fromfile(path, dtype=np.uint8), -1)
        self._template_cache[path] = template
        return template

    def _to_gray(self, image):
        if image is None:
            return None
        if len(image.shape) == 2:
            return image.copy()
        if len(image.shape) == 3 and image.shape[2] == 4:
            alpha_channel = image[:, :, 3]
            rgb_channels = image[:, :, :3]
            background = np.zeros_like(rgb_channels, dtype=np.uint8)
            alpha_factor = alpha_channel[:, :, np.newaxis] / 255.0
            bgr = (rgb_channels * alpha_factor + background * (1 - alpha_factor)).astype(np.uint8)
            return cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    def _prepare_for_match(self, image, use_edge=False, use_binary=False, binary_threshold=200):
        gray = self._to_gray(image)
        if gray is None:
            return None
        if use_binary:
            _, gray = cv2.threshold(gray, binary_threshold, 255, cv2.THRESH_BINARY)
        elif use_edge:
            gray = cv2.Canny(gray, 50, 150)
        return gray

    def _template_for_match(self, template_path, use_edge=False, use_binary=False, binary_threshold=200):
        path = os.fspath(template_path)
        cache_key = (path, bool(use_edge), bool(use_binary), int(binary_threshold))
        if cache_key in self._processed_template_cache:
            return self._processed_template_cache[cache_key]

        template = self._read_template(path)
        if template is None:
            print(f"[Vision] 无法解析图片数据: {path}")
            self._processed_template_cache[cache_key] = None
            return None

        prepared = self._prepare_for_match(template, use_edge=use_edge, use_binary=use_binary, binary_threshold=binary_threshold)
        self._processed_template_cache[cache_key] = prepared
        return prepared

    def _template_mask_for_match(
        self,
        template_path,
        use_edge=False,
        use_binary=False,
        binary_threshold=200,
        mask_threshold=8,
    ):
        path = os.fspath(template_path)
        cache_key = ("mask", path, bool(use_edge), bool(use_binary), int(binary_threshold), int(mask_threshold))
        if cache_key in self._processed_template_cache:
            return self._processed_template_cache[cache_key]

        template = self._read_template(path)
        if template is None:
            self._processed_template_cache[cache_key] = None
            return None

        if len(template.shape) == 3 and template.shape[2] == 4:
            mask = cv2.inRange(template[:, :, 3], 12, 255)
        else:
            gray = self._to_gray(template)
            if gray is None:
                self._processed_template_cache[cache_key] = None
                return None
            if use_edge:
                mask = cv2.Canny(gray, 50, 150)
                mask = cv2.dilate(mask, np.ones((3, 3), np.uint8), iterations=1)
            elif use_binary:
                threshold = max(1, min(245, int(binary_threshold) - 25))
                _, mask = cv2.threshold(gray, threshold, 255, cv2.THRESH_BINARY)
            else:
                border = np.concatenate([gray[0, :], gray[-1, :], gray[:, 0], gray[:, -1]])
                background = int(np.median(border))
                diff = cv2.absdiff(gray, np.full_like(gray, background))
                _, mask = cv2.threshold(diff, int(mask_threshold), 255, cv2.THRESH_BINARY)
                if cv2.countNonZero(mask) < 5:
                    _, mask = cv2.threshold(gray, 35, 255, cv2.THRESH_BINARY)

        if cv2.countNonZero(mask) < 5:
            mask = None
        self._processed_template_cache[cache_key] = mask
        return mask

    def _build_scales(self, scale_range=None, scale_steps=11):
        if scale_range is None:
            low, high = 0.5, 1.5
        else:
            low, high = float(scale_range[0]), float(scale_range[1])
        if low > high:
            low, high = high, low
        low = max(0.20, low)
        high = max(low, min(4.00, high))
        steps = max(1, int(scale_steps))
        if steps == 1 or abs(high - low) < 0.001:
            return [low]
        scales = list(np.linspace(high, low, steps))
        if low <= 1.0 <= high and all(abs(scale - 1.0) > 0.015 for scale in scales):
            scales.append(1.0)
            scales.sort(reverse=True)
        return scales

    def find_template(
        self,
        screen_img,
        template_path,
        threshold=0.75,
        use_edge=False,
        use_binary=False,
        scale_range=None,
        scale_steps=11,
        binary_threshold=200,
        use_mask=False,
        mask_threshold=8,
    ):
        """
        在屏幕截图中寻找模板图片 (支持中文路径)
        use_edge: 是否使用 Canny 边缘检测匹配（排除光照干扰）
        use_binary: 是否使用二值化提取高亮特征匹配（适用于白天水面强光下的纯白 UI 图标）
        返回 (x, y) 坐标，如果没有找到返回 (None, None)
        """
        try:
            screen_gray = self._prepare_for_match(
                screen_img,
                use_edge=use_edge,
                use_binary=use_binary,
                binary_threshold=binary_threshold,
            )
            template_gray = self._template_for_match(
                template_path,
                use_edge=use_edge,
                use_binary=use_binary,
                binary_threshold=binary_threshold,
            )
            template_mask = None
            if use_mask:
                template_mask = self._template_mask_for_match(
                    template_path,
                    use_edge=use_edge,
                    use_binary=use_binary,
                    binary_threshold=binary_threshold,
                    mask_threshold=mask_threshold,
                )

            if screen_gray is None or template_gray is None:
                return None, 0.0
            if use_binary and cv2.countNonZero(screen_gray) < 5:
                return None, 0.0
            
            best_match = None
            best_val = -1
            best_loc = None
            
            for scale in self._build_scales(scale_range=scale_range, scale_steps=scale_steps):
                # 缩放模板
                width = int(template_gray.shape[1] * scale)
                height = int(template_gray.shape[0] * scale)
                
                # 如果缩放后的模板比截图还要大，就跳过
                if width < 4 or height < 4 or width > screen_gray.shape[1] or height > screen_gray.shape[0]:
                    continue

                interpolation = cv2.INTER_NEAREST if use_binary else (cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR)
                resized_template = cv2.resize(template_gray, (width, height), interpolation=interpolation)
                if use_binary:
                    _, resized_template = cv2.threshold(resized_template, 127, 255, cv2.THRESH_BINARY)
                    if cv2.countNonZero(resized_template) < 5:
                        continue
                if float(np.std(resized_template)) < 1.0:
                    continue

                resized_mask = None
                match_method = cv2.TM_CCOEFF_NORMED
                if template_mask is not None:
                    resized_mask = cv2.resize(template_mask, (width, height), interpolation=cv2.INTER_NEAREST)
                    _, resized_mask = cv2.threshold(resized_mask, 1, 255, cv2.THRESH_BINARY)
                    if cv2.countNonZero(resized_mask) >= 5:
                        match_method = cv2.TM_CCORR_NORMED
                    else:
                        resized_mask = None
                
                # 进行匹配
                if resized_mask is not None:
                    res = cv2.matchTemplate(screen_gray, resized_template, match_method, mask=resized_mask)
                else:
                    res = cv2.matchTemplate(screen_gray, resized_template, match_method)
                res = np.nan_to_num(res, nan=-1.0, posinf=-1.0, neginf=-1.0)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
                max_val = max(-1.0, min(1.0, float(max_val)))
                
                if max_val > best_val:
                    best_val = max_val
                    best_loc = max_loc
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

    def find_best_template(self, screen_img, template_paths, threshold=0.75, **kwargs):
        """在多个模板中返回置信度最高的匹配。"""
        best_loc = None
        best_conf = -1.0
        best_path = None

        for template_path in template_paths or []:
            loc, conf = self.find_template(screen_img, template_path, threshold=threshold, **kwargs)
            if conf > best_conf:
                best_loc = loc
                best_conf = conf
                best_path = template_path

        if best_loc is not None and best_conf >= threshold:
            return best_loc, best_conf, best_path
        return None, best_conf, best_path

    def find_best_template_multi_strategy(self, screen_img, template_paths, strategies, threshold=0.75, **base_kwargs):
        """使用多种预处理策略匹配模板，返回最可靠的命中。"""
        best_raw = (None, -1.0, None, "")
        best_pass = (None, -1.0, None, "", -999.0)

        for strategy in strategies or ():
            params = dict(base_kwargs)
            params.update({k: v for k, v in strategy.items() if k not in {"name", "threshold"}})
            local_threshold = float(strategy.get("threshold", threshold))
            loc, conf, matched_path = self.find_best_template(
                screen_img,
                template_paths,
                threshold=local_threshold,
                **params,
            )
            strategy_name = strategy.get("name", "")
            if conf > best_raw[1]:
                best_raw = (loc, conf, matched_path, strategy_name)
            if loc is not None and conf >= local_threshold:
                margin = conf - local_threshold
                if margin > best_pass[4]:
                    best_pass = (loc, conf, matched_path, strategy_name, margin)

        if best_pass[0] is not None:
            return best_pass[0], best_pass[1], best_pass[2], best_pass[3]
        return None, best_raw[1], best_raw[2], best_raw[3]

    def analyze_fishing_bar(
        self,
        roi_img,
        cursor_template_paths=None,
        cursor_scale_range=None,
        cursor_scale_steps=5,
    ):
        """
        解析上方耐力条区域。
        先定位黄色游标所在的 HUD 水平带，再只在同一带内寻找横向绿色目标条，
        避免树林、水草等大面积绿色背景参与目标中心计算。
        """
        if roi_img is None or roi_img.size == 0:
            return None, None, None, roi_img, 0.0

        debug_img = roi_img.copy()
        roi_h, roi_w = roi_img.shape[:2]
        hsv = cv2.cvtColor(roi_img, cv2.COLOR_BGR2HSV)

        yellow_cfg = self.hsv_config.get("yellow", {})
        lower_yellow = np.array(yellow_cfg.get("min", [15, 80, 130]), dtype=np.uint8)
        upper_yellow = np.array(yellow_cfg.get("max", [45, 255, 255]), dtype=np.uint8)
        lower_yellow = np.minimum(lower_yellow, np.array([15, 80, 130], dtype=np.uint8))
        upper_yellow = np.maximum(upper_yellow, np.array([45, 255, 255], dtype=np.uint8))
        cursor_mask = cv2.inRange(hsv, lower_yellow, upper_yellow)

        green_cfg = self.hsv_config.get("green", {})
        lower_green = np.array(green_cfg.get("min", [35, 45, 45]), dtype=np.uint8)
        upper_green = np.array(green_cfg.get("max", [95, 255, 255]), dtype=np.uint8)
        lower_green = np.maximum(lower_green, np.array([35, 45, 70], dtype=np.uint8))
        upper_green = np.maximum(upper_green, np.array([95, 255, 255], dtype=np.uint8))
        target_mask = cv2.inRange(hsv, lower_green, upper_green)

        green_probe_mask = target_mask.copy()
        probe_values = hsv[:, :, 2][green_probe_mask > 0]
        if probe_values.size:
            probe_v_floor = max(int(lower_green[2]), min(155, int(np.percentile(probe_values, 65)) + 6))
            refined_probe = green_probe_mask.copy()
            refined_probe[hsv[:, :, 2] < probe_v_floor] = 0
            if cv2.countNonZero(refined_probe) >= max(8, int(roi_w * roi_h * 0.0004)):
                green_probe_mask = refined_probe
        green_probe_mask = cv2.morphologyEx(green_probe_mask, cv2.MORPH_CLOSE, np.ones((3, max(7, int(roi_w * 0.025))), np.uint8))
        green_probe_mask = cv2.morphologyEx(green_probe_mask, cv2.MORPH_OPEN, np.ones((2, 3), np.uint8))
        green_candidates = self._collect_green_bar_candidates(green_probe_mask, roi_w, roi_h)

        cursor_kernel = np.ones((3, 3), np.uint8)
        cursor_mask = cv2.morphologyEx(cursor_mask, cv2.MORPH_OPEN, cursor_kernel)
        cursor_mask = cv2.morphologyEx(cursor_mask, cv2.MORPH_CLOSE, cursor_kernel)

        cursor_candidates = self._collect_cursor_components(cursor_mask, roi_w, roi_h)
        cursor = self._select_cursor_candidate(cursor_candidates, green_candidates, roi_w, roi_h)
        needs_template = cursor is None or cursor.get("confidence", 0.0) < 0.55 or cursor.get("score", 0.0) < 0.58
        if cursor_template_paths and needs_template:
            template_cursor = self._cursor_template_candidate(
                roi_img,
                cursor_template_paths or (),
                roi_w,
                roi_h,
                cursor_scale_range,
                cursor_scale_steps,
            )
            if template_cursor is not None:
                cursor_candidates.append(template_cursor)
                cursor = self._select_cursor_candidate(cursor_candidates, green_candidates, roi_w, roi_h)
        if cursor is None:
            cv2.putText(debug_img, "cursor missing", (4, max(12, roi_h - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (0, 0, 255), 1)
            return None, None, None, debug_img, 0.0

        band_half = max(6, int(cursor["h"] * 0.85), int(roi_h * 0.22))
        band_y1 = max(0, int(cursor["cy"]) - band_half)
        band_y2 = min(roi_h, int(cursor["cy"]) + band_half + 1)

        band_mask = np.zeros_like(target_mask)
        band_mask[band_y1:band_y2, :] = target_mask[band_y1:band_y2, :]
        relaxed_band_mask = band_mask.copy()
        band_values = hsv[band_y1:band_y2, :, 2][band_mask[band_y1:band_y2, :] > 0]
        if band_values.size:
            adaptive_v_floor = max(int(lower_green[2]), min(155, int(np.percentile(band_values, 65)) + 6))
            refined_band_mask = band_mask.copy()
            refined_band_mask[hsv[:, :, 2] < adaptive_v_floor] = 0
            if cv2.countNonZero(refined_band_mask[band_y1:band_y2, :]) >= max(8, int(roi_w * roi_h * 0.0004)):
                band_mask = refined_band_mask
        close_w = max(7, int(roi_w * 0.035))
        band_mask = cv2.morphologyEx(band_mask, cv2.MORPH_CLOSE, np.ones((3, close_w), np.uint8))
        band_mask = cv2.morphologyEx(band_mask, cv2.MORPH_OPEN, np.ones((2, 3), np.uint8))

        target = self._select_green_bar_component(band_mask, roi_w, roi_h, band_y1, band_y2, cursor)
        if target is None:
            relaxed_close_w = max(5, int(roi_w * 0.025))
            relaxed_band_mask = cv2.morphologyEx(relaxed_band_mask, cv2.MORPH_CLOSE, np.ones((3, relaxed_close_w), np.uint8))
            relaxed_band_mask = cv2.morphologyEx(relaxed_band_mask, cv2.MORPH_OPEN, np.ones((2, 3), np.uint8))
            target = self._select_green_bar_component(
                relaxed_band_mask,
                roi_w,
                roi_h,
                band_y1,
                band_y2,
                cursor,
                relaxed=True,
            )
        if target is None:
            target = self._select_green_candidate_near_cursor(green_candidates, cursor, roi_w, roi_h)

        cursor_x = int(cursor["cx"])
        target_x = int(target["cx"]) if target else None
        target_w = int(target["w"]) if target else None
        confidence = 0.0
        if target:
            confidence = min(0.98, cursor["confidence"] * 0.42 + target["confidence"] * 0.58)

        cv2.rectangle(debug_img, (0, band_y1), (roi_w - 1, max(band_y1, band_y2 - 1)), (255, 120, 0), 1)
        cv2.rectangle(
            debug_img,
            (int(cursor["x"]), int(cursor["y"])),
            (int(cursor["x"] + cursor["w"]), int(cursor["y"] + cursor["h"])),
            (0, 255, 255),
            1,
        )
        cv2.line(debug_img, (cursor_x, 0), (cursor_x, roi_h), (0, 255, 255), 2)
        if target:
            cv2.rectangle(
                debug_img,
                (int(target["x"]), int(target["y"])),
                (int(target["x"] + target["w"]), int(target["y"] + target["h"])),
                (0, 180, 0),
                1,
            )
            cv2.line(debug_img, (target_x, 0), (target_x, roi_h), (0, 255, 0), 2)
        source = cursor.get("source", "color")
        cv2.putText(debug_img, f"conf {confidence:.2f} {source}", (4, max(12, roi_h - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (255, 255, 255), 1)

        return target_x, cursor_x, target_w, debug_img, confidence

    def _cursor_template_candidate(self, roi_img, cursor_template_paths, roi_w, roi_h, scale_range=None, scale_steps=5):
        if not cursor_template_paths:
            return None

        strategies = (
            {"name": "cursor-gray-mask", "threshold": 0.66, "use_mask": True, "mask_threshold": 5},
            {"name": "cursor-binary-mask", "threshold": 0.60, "use_binary": True, "binary_threshold": 150, "use_mask": True},
            {"name": "cursor-edge", "threshold": 0.52, "use_edge": True},
        )
        loc, conf, matched_path, strategy = self.find_best_template_multi_strategy(
            roi_img,
            cursor_template_paths,
            strategies,
            threshold=0.60,
            scale_range=scale_range or (0.70, 1.55),
            scale_steps=max(3, int(scale_steps)),
        )
        if loc is None:
            return None

        template = self._read_template(matched_path)
        if template is not None:
            template_h, template_w = template.shape[:2]
        else:
            template_h, template_w = max(6, int(roi_h * 0.45)), max(3, int(roi_h * 0.16))
        h = max(int(template_h), int(roi_h * 0.35))
        h = min(max(4, h), roi_h)
        w = max(int(template_w), int(h * 0.28), 3)
        w = min(max(3, w), max(4, int(roi_w * 0.12)))
        cx, cy = float(loc[0]), float(loc[1])
        x = int(round(cx - w / 2))
        y = int(round(cy - h / 2))
        x = max(0, min(roi_w - w, x))
        y = max(0, min(roi_h - h, y))
        return {
            "x": x,
            "y": y,
            "w": int(w),
            "h": int(h),
            "area": int(w * h),
            "cx": cx,
            "cy": cy,
            "confidence": max(0.0, min(0.98, float(conf))),
            "score": max(0.0, min(0.98, float(conf))),
            "source": "template",
            "strategy": strategy,
        }

    def _collect_cursor_components(self, mask, roi_w, roi_h):
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        candidates = []
        min_area = max(6, int(roi_w * roi_h * 0.00025))

        for index in range(1, count):
            x, y, w, h, area = stats[index]
            if area < min_area or h < max(4, int(roi_h * 0.16)):
                continue
            if w > max(12, int(h * 0.44)):
                continue
            aspect = h / max(w, 1)
            if aspect < 1.05:
                continue
            cx, cy = centroids[index]
            vertical_score = min(1.0, aspect / 3.0)
            height_score = min(1.0, h / max(1, roi_h * 0.55))
            area_score = min(1.0, area / max(1, roi_w * roi_h * 0.012))
            center_score = 1.0 - min(1.0, abs(cy - roi_h * 0.5) / max(1.0, roi_h * 0.65))
            confidence = max(0.0, min(0.98, vertical_score * 0.34 + height_score * 0.30 + area_score * 0.20 + center_score * 0.16))
            score = confidence + area_score * 0.15
            candidates.append({
                "x": int(x),
                "y": int(y),
                "w": int(w),
                "h": int(h),
                "area": int(area),
                "cx": float(cx),
                "cy": float(cy),
                "confidence": confidence,
                "score": score,
                "source": "color",
            })
        return candidates

    def _collect_green_bar_candidates(self, mask, roi_w, roi_h):
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        candidates = []
        min_width = max(10, int(roi_w * 0.030))
        min_area = max(8, int(roi_w * roi_h * 0.00035))
        max_height = max(5, int(roi_h * 0.58))

        for index in range(1, count):
            x, y, w, h, area = stats[index]
            if area < min_area or w < min_width or h < 2 or h > max_height:
                continue
            aspect = w / max(1, h)
            if aspect < 2.0:
                continue
            fill_ratio = area / max(1, w * h)
            if fill_ratio < 0.12:
                continue
            cx, cy = centroids[index]
            edge_penalty = 0.12 if (x <= 1 or x + w >= roi_w - 1) else 0.0
            score = min(1.0, aspect / 8.0) * 0.35 + min(1.0, w / max(1.0, roi_w * 0.18)) * 0.35
            score += min(1.0, fill_ratio / 0.55) * 0.20
            score += (1.0 - min(1.0, abs(cy - roi_h * 0.5) / max(1.0, roi_h * 0.55))) * 0.10
            score = max(0.0, score - edge_penalty)
            candidates.append({
                "x": int(x),
                "y": int(y),
                "w": int(w),
                "h": int(h),
                "area": int(area),
                "cx": float(cx),
                "cy": float(cy),
                "confidence": max(0.0, min(0.98, score)),
                "score": score,
            })
        return sorted(candidates, key=lambda item: item["score"], reverse=True)[:6]

    def _select_cursor_candidate(self, candidates, green_candidates, roi_w, roi_h):
        best = None
        for candidate in candidates:
            cx = float(candidate["cx"])
            cy = float(candidate["cy"])
            h = max(1, int(candidate["h"]))
            w = max(1, int(candidate["w"]))
            edge_distance = min(cx, max(0.0, roi_w - 1 - cx))
            edge_score = min(1.0, edge_distance / max(1.0, roi_w * 0.055))
            if candidate.get("source") != "template" and green_candidates and edge_score < 0.75:
                continue
            center_score = 1.0 - min(1.0, abs(cy - roi_h * 0.5) / max(1.0, roi_h * 0.62))
            slender_score = min(1.0, (h / max(w, 1)) / 3.2)
            band_score = 0.50
            if green_candidates:
                green_scores = []
                for green in green_candidates:
                    y_score = 1.0 - min(1.0, abs(cy - green["cy"]) / max(2.0, roi_h * 0.16, h * 0.9))
                    expected_h = max(4.0, green["h"] * 2.8)
                    height_score = 1.0 - min(1.0, abs(h - expected_h) / max(3.0, expected_h * 1.10))
                    green_scores.append(y_score * 0.72 + height_score * 0.28)
                band_score = max(0.0, max(green_scores))
                if band_score < 0.18 and candidate.get("source") != "template":
                    continue

            template_bonus = 0.18 if candidate.get("source") == "template" else 0.0
            confidence = float(candidate.get("confidence", 0.0))
            score = confidence * 0.42 + band_score * 0.24 + center_score * 0.12 + slender_score * 0.12 + edge_score * 0.10 + template_bonus
            if candidate.get("source") == "template" and confidence >= 0.78:
                score += 0.06
            candidate["score"] = max(0.0, min(1.20, score))
            candidate["confidence"] = max(0.0, min(0.98, confidence * 0.70 + band_score * 0.20 + edge_score * 0.10))
            if best is None or candidate["score"] > best["score"]:
                best = candidate

        return best

    def _select_green_bar_component(self, mask, roi_w, roi_h, band_y1, band_y2, cursor, relaxed=False):
        count, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        best = None
        band_h = max(1, band_y2 - band_y1)
        min_width = max(8 if relaxed else 12, int(roi_w * (0.026 if relaxed else 0.035)))
        min_area = max(7 if relaxed else 10, int(roi_w * roi_h * (0.00030 if relaxed else 0.00045)))
        max_height = max(6, int(min(roi_h * (0.72 if relaxed else 0.62), band_h * (1.05 if relaxed else 0.92))))

        for index in range(1, count):
            x, y, w, h, area = stats[index]
            if area < min_area or w < min_width or h < 2 or h > max_height:
                continue
            aspect = w / max(h, 1)
            if aspect < (1.65 if relaxed else 2.2):
                continue
            fill_ratio = area / max(1, w * h)
            if fill_ratio < (0.10 if relaxed else 0.16):
                continue
            cx, cy = centroids[index]
            y_delta = abs(cy - cursor["cy"])
            if y_delta > max(cursor["h"] * (1.25 if relaxed else 0.95), roi_h * (0.36 if relaxed else 0.28)):
                continue
            if w > roi_w * 0.95 and h > roi_h * 0.42:
                continue

            edge_touch_penalty = 0.0
            if x <= 1 or (x + w) >= roi_w - 1:
                edge_touch_penalty += 0.12
            if y <= band_y1 + 1 or (y + h) >= band_y2 - 1:
                edge_touch_penalty += 0.10

            aspect_score = min(1.0, aspect / 8.0)
            width_score = min(1.0, w / max(1.0, roi_w * 0.18))
            fill_score = min(1.0, fill_ratio / 0.55)
            y_score = 1.0 - min(1.0, y_delta / max(1.0, band_h * 0.65))
            height_score = 1.0 - min(1.0, abs(h - max(3.0, cursor["h"] * 0.32)) / max(3.0, cursor["h"]))
            confidence = aspect_score * 0.24 + width_score * 0.24 + fill_score * 0.20 + y_score * 0.24 + height_score * 0.08
            confidence = max(0.0, min(0.98, confidence - edge_touch_penalty))
            score = confidence + width_score * 0.10 + y_score * 0.08

            if best is None or score > best["score"]:
                best = {
                    "x": int(x),
                    "y": int(y),
                    "w": int(w),
                    "h": int(h),
                    "area": int(area),
                    "cx": float(cx),
                    "cy": float(cy),
                    "confidence": confidence,
                    "score": score,
                }
        return best

    def _select_green_candidate_near_cursor(self, candidates, cursor, roi_w, roi_h):
        best = None
        for candidate in candidates or []:
            y_delta = abs(float(candidate["cy"]) - float(cursor["cy"]))
            if y_delta > max(float(cursor["h"]) * 1.35, roi_h * 0.38):
                continue
            if candidate["w"] > roi_w * 0.92 and candidate["h"] > roi_h * 0.38:
                continue
            width_score = min(1.0, candidate["w"] / max(1.0, roi_w * 0.16))
            y_score = 1.0 - min(1.0, y_delta / max(1.0, roi_h * 0.38))
            base_conf = float(candidate.get("confidence", 0.0))
            score = base_conf * 0.55 + width_score * 0.25 + y_score * 0.20
            if best is None or score > best["score"]:
                best = dict(candidate)
                best["score"] = score
                best["confidence"] = max(0.0, min(0.88, base_conf * 0.70 + y_score * 0.18 + width_score * 0.12))
        return best

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
