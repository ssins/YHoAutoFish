import json
import os
import random
import time
from collections import defaultdict


class RecordManager:
    DEFAULT_STATS = {
        "total_caught": 0,
        "total_time_seconds": 0,
        "total_attempts": 0,
        "consecutive_empty": 0,
    }

    def __init__(self, record_file="records.json", encyclopedia_dir="异环鱼类图鉴资源"):
        self.record_file = record_file
        self.encyclopedia_dir = encyclopedia_dir
        self._query_cache = {}
        self._cache_version = 0
        self.records = {
            "stats": dict(self.DEFAULT_STATS),
            "encyclopedia": {},
            "history": [],
        }
        self.load_records()
        self._sync_encyclopedia_images()

    def _touch_cache(self):
        self._cache_version += 1
        self._query_cache.clear()

    def load_records(self):
        if not os.path.exists(self.record_file):
            return

        try:
            with open(self.record_file, "r", encoding="utf-8") as file:
                data = json.load(file)
        except Exception as exc:
            print(f"Failed to load records: {exc}")
            return

        self.records["stats"].update(data.get("stats", {}))
        self.records["history"] = data.get("history", [])
        self.records["encyclopedia"] = data.get("encyclopedia", {})
        self._touch_cache()

    def save_records(self):
        try:
            with open(self.record_file, "w", encoding="utf-8") as file:
                json.dump(self.records, file, ensure_ascii=False, indent=4)
        except Exception as exc:
            print(f"Failed to save records: {exc}")

    def _decode_mojibake(self, text):
        if not isinstance(text, str) or not text:
            return text

        candidates = [text]
        for codec in ("gbk", "gb18030", "utf-8"):
            try:
                repaired = text.encode(codec, errors="ignore").decode("utf-8", errors="ignore").strip()
                if repaired and repaired not in candidates:
                    candidates.append(repaired)
            except Exception:
                continue
        return candidates

    def _canonical_name_candidates(self, name, image_path=""):
        candidates = set()
        if name:
            for item in self._decode_mojibake(name):
                if item:
                    candidates.add(item)
        if image_path:
            basename = os.path.splitext(os.path.basename(image_path))[0]
            for item in self._decode_mojibake(basename):
                if item:
                    candidates.add(item)
        return candidates

    def _scan_resource_catalog(self):
        catalog = {}
        if not os.path.isdir(self.encyclopedia_dir):
            return catalog

        for rarity_dir in os.listdir(self.encyclopedia_dir):
            rarity_path = os.path.join(self.encyclopedia_dir, rarity_dir)
            if not os.path.isdir(rarity_path):
                continue
            for filename in os.listdir(rarity_path):
                if not filename.lower().endswith(".png"):
                    continue
                fish_name = os.path.splitext(filename)[0]
                catalog[fish_name] = {
                    "caught_count": 0,
                    "max_weight": 0,
                    "rarity": rarity_dir,
                    "image_path": os.path.join(rarity_path, filename),
                    "first_caught_at": "",
                    "last_caught_at": "",
                }
        return catalog

    def _sync_encyclopedia_images(self):
        catalog = self._scan_resource_catalog()
        if not catalog:
            return

        old_encyclopedia = self.records.get("encyclopedia", {})
        remapped = {}

        for fish_name, base_data in catalog.items():
            merged = dict(base_data)
            for old_name, old_data in old_encyclopedia.items():
                candidates = self._canonical_name_candidates(old_name, old_data.get("image_path", ""))
                if fish_name in candidates:
                    merged["caught_count"] = max(0, int(old_data.get("caught_count", 0)))
                    merged["max_weight"] = max(0, int(old_data.get("max_weight", 0)))
                    merged["first_caught_at"] = old_data.get("first_caught_at", "")
                    merged["last_caught_at"] = old_data.get("last_caught_at", "")
                    break
            remapped[fish_name] = merged

        for old_name, old_data in old_encyclopedia.items():
            if any(old_name == name or old_name in self._canonical_name_candidates(name, info.get("image_path", "")) for name, info in remapped.items()):
                continue
            repaired_names = [candidate for candidate in self._canonical_name_candidates(old_name, old_data.get("image_path", "")) if candidate not in remapped]
            fallback_name = repaired_names[0] if repaired_names else old_name
            remapped[fallback_name] = {
                "caught_count": max(0, int(old_data.get("caught_count", 0))),
                "max_weight": max(0, int(old_data.get("max_weight", 0))),
                "rarity": old_data.get("rarity", "未知稀有度"),
                "image_path": old_data.get("image_path", ""),
                "first_caught_at": old_data.get("first_caught_at", ""),
                "last_caught_at": old_data.get("last_caught_at", ""),
            }

        repaired_history = []
        for record in self.records.get("history", []):
            fixed = dict(record)
            name_candidates = self._canonical_name_candidates(record.get("fish_name", ""), record.get("image_path", ""))
            matched_name = next((name for name in remapped if name in name_candidates), None)
            if matched_name:
                fixed["fish_name"] = matched_name
                fixed["rarity"] = remapped[matched_name]["rarity"]
                fixed["image_path"] = remapped[matched_name]["image_path"]
            repaired_history.append(fixed)

        self.records["encyclopedia"] = remapped
        self.records["history"] = repaired_history
        self._touch_cache()
        self.save_records()

    def generate_sample_records(self):
        encyclopedia = {}
        for name, data in self._scan_resource_catalog().items():
            encyclopedia[name] = {
                "caught_count": 0,
                "max_weight": 0,
                "rarity": data.get("rarity", "未知稀有度"),
                "image_path": data.get("image_path", ""),
                "first_caught_at": "",
                "last_caught_at": "",
            }

        fish_names = list(encyclopedia.keys())
        history = []
        randomizer = random.Random(20260424)
        rarity_weight = {
            "绿色稀有度": (25, 280),
            "蓝色稀有度": (40, 420),
            "紫色稀有度": (60, 560),
            "金色稀有度": (80, 760),
            "废品": (5, 60),
            "未知稀有度": (15, 160),
        }

        selected = []
        for rarity in ["绿色稀有度", "蓝色稀有度", "紫色稀有度", "金色稀有度", "废品"]:
            same_rarity = [name for name, data in encyclopedia.items() if data.get("rarity") == rarity]
            randomizer.shuffle(same_rarity)
            selected.extend(same_rarity[: min(len(same_rarity), 8 if rarity != "废品" else 2)])

        selected = selected[:34] if len(selected) > 34 else selected

        for index in range(132):
            fish_name = selected[index % len(selected)]
            fish_data = encyclopedia[fish_name]
            rarity = fish_data["rarity"]
            weight_range = rarity_weight.get(rarity, (15, 160))
            weight = randomizer.randint(*weight_range)

            day = 1 + (index % 18)
            hour = 8 + (index * 3) % 12
            minute = (index * 7) % 60
            timestamp = f"2026-04-{day:02d} {hour:02d}:{minute:02d}:00"

            fish_data["caught_count"] += 1
            fish_data["max_weight"] = max(fish_data["max_weight"], weight)
            if not fish_data["first_caught_at"]:
                fish_data["first_caught_at"] = timestamp
            fish_data["last_caught_at"] = timestamp

            history.append(
                {
                    "time": timestamp,
                    "fish_name": fish_name,
                    "weight": weight,
                    "rarity": rarity,
                    "image_path": fish_data["image_path"],
                }
            )

        stats = {
            "total_caught": len(history),
            "total_time_seconds": 6 * 3600 + 42 * 60,
            "total_attempts": len(history) + 19,
            "consecutive_empty": 2,
        }

        return {
            "stats": stats,
            "encyclopedia": encyclopedia,
            "history": history,
        }

    def add_empty_catch(self):
        self.records["stats"]["total_attempts"] += 1
        self.records["stats"]["consecutive_empty"] += 1
        self._touch_cache()
        self.save_records()

    def add_catch(self, fish_name, weight_g, rarity=None):
        self.records["stats"]["total_caught"] += 1
        self.records["stats"]["total_attempts"] += 1
        self.records["stats"]["consecutive_empty"] = 0

        canonical_name = fish_name
        if fish_name not in self.records["encyclopedia"]:
            for name in self.records["encyclopedia"]:
                if fish_name in self._canonical_name_candidates(name, self.records["encyclopedia"][name].get("image_path", "")):
                    canonical_name = name
                    break

        if canonical_name not in self.records["encyclopedia"]:
            self.records["encyclopedia"][canonical_name] = {
                "caught_count": 0,
                "max_weight": 0,
                "rarity": rarity or "未知稀有度",
                "image_path": "",
                "first_caught_at": "",
                "last_caught_at": "",
            }

        fish_data = self.records["encyclopedia"][canonical_name]
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        fish_data["caught_count"] += 1
        fish_data["max_weight"] = max(int(weight_g or 0), int(fish_data.get("max_weight", 0)))
        if not fish_data.get("first_caught_at"):
            fish_data["first_caught_at"] = timestamp
        fish_data["last_caught_at"] = timestamp

        self.records["history"].append(
            {
                "time": timestamp,
                "fish_name": canonical_name,
                "weight": int(weight_g or 0),
                "rarity": fish_data.get("rarity", rarity or "未知稀有度"),
                "image_path": fish_data.get("image_path", ""),
            }
        )

        if len(self.records["history"]) > 1000:
            self.records["history"] = self.records["history"][-1000:]

        self._touch_cache()
        self.save_records()

    def add_runtime(self, duration_seconds):
        self.records["stats"]["total_time_seconds"] += max(0, int(duration_seconds))
        self._touch_cache()
        self.save_records()

    def get_stats(self):
        return dict(self.records["stats"])

    def get_history(self):
        return list(self.records["history"])

    def get_encyclopedia(self):
        return dict(self.records["encyclopedia"])

    def get_all_fishes_by_rarity(self):
        grouped = defaultdict(dict)
        for name, data in self.records["encyclopedia"].items():
            grouped[data.get("rarity", "未知稀有度")][name] = data
        return dict(grouped)

    def query_history(self, keyword="", rarity="全部稀有度"):
        keyword = (keyword or "").strip().lower()
        cache_key = (self._cache_version, keyword, rarity)
        if cache_key in self._query_cache:
            return list(self._query_cache[cache_key])

        results = []
        for record in self.records["history"]:
            if keyword and keyword not in record.get("fish_name", "").lower():
                continue
            if rarity and rarity != "全部稀有度" and record.get("rarity") != rarity:
                continue
            results.append(record)
        self._query_cache[cache_key] = list(results)
        return list(results)

    def get_rarity_distribution(self, history=None):
        source = history if history is not None else self.records["history"]
        distribution = defaultdict(int)
        for record in source:
            distribution[record.get("rarity", "未知稀有度")] += 1
        return dict(distribution)

    def get_daily_trend(self, days=7):
        points = defaultdict(int)
        for record in self.records["history"]:
            day = record.get("time", "")[:10]
            if day:
                points[day] += 1
        days = max(1, int(days))
        ordered_days = sorted(points.keys())[-days:]
        return [(day, points[day]) for day in ordered_days]

    def get_summary(self):
        encyclopedia = self.records["encyclopedia"]
        history = self.records["history"]
        stats = self.records["stats"]

        unlocked_count = sum(1 for data in encyclopedia.values() if data.get("caught_count", 0) > 0)
        total_species = len(encyclopedia)
        max_weight = max((int(data.get("max_weight", 0)) for data in encyclopedia.values()), default=0)
        rarest_count = self.get_rarity_distribution(history).get("金色稀有度", 0)
        success_rate = 0.0
        if stats.get("total_attempts", 0) > 0:
            success_rate = stats.get("total_caught", 0) / stats["total_attempts"] * 100

        return {
            "total_species": total_species,
            "unlocked_species": unlocked_count,
            "max_weight": max_weight,
            "gold_caught": rarest_count,
            "success_rate": success_rate,
        }
