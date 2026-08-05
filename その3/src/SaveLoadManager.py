import json
import os
from datetime import datetime


class SaveLoadManager:
    """複数スロット対応のセーブ/ロード管理。"""

    SAVE_PREFIX = "save_"
    LEGACY_FILENAME = "trpg_save_data.json"
    AUTOSAVE_SLOT_ID = "autosave"
    DEFAULT_MANUAL_SLOTS = ("slot_1", "slot_2", "slot_3")

    def __init__(self, save_dir=None):
        self.save_dir = save_dir or os.path.dirname(os.path.abspath(__file__))

    def _filepath(self, slot_id):
        if slot_id == "legacy":
            return os.path.join(self.save_dir, self.LEGACY_FILENAME)
        return os.path.join(self.save_dir, f"{self.SAVE_PREFIX}{slot_id}.json")

    def save_game(self, slot_id, data):
        """指定スロットにセーブデータをJSON保存する。"""
        filepath = self._filepath(slot_id)
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return True
        except OSError as e:
            print(f"[SaveLoadManager] 保存エラー ({slot_id}): {e}")
            return False

    def load_game(self, slot_id):
        """指定スロットのセーブデータを辞書として返す。存在しない場合は None。"""
        filepath = self._filepath(slot_id)
        if not os.path.exists(filepath):
            return None
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            print(f"[SaveLoadManager] 読込エラー ({slot_id}): {e}")
            return None

    def slot_exists(self, slot_id):
        return os.path.exists(self._filepath(slot_id))

    def get_available_slots(self):
        """存在するセーブスロットのメタ情報一覧を返す（更新日時降順）。"""
        slots = []

        if os.path.isdir(self.save_dir):
            for fname in os.listdir(self.save_dir):
                if fname.startswith(self.SAVE_PREFIX) and fname.endswith(".json"):
                    slot_id = fname[len(self.SAVE_PREFIX) : -len(".json")]
                    filepath = os.path.join(self.save_dir, fname)
                    meta = self._build_slot_meta(slot_id, filepath)
                    if meta:
                        slots.append(meta)

        legacy_path = os.path.join(self.save_dir, self.LEGACY_FILENAME)
        if os.path.exists(legacy_path):
            meta = self._build_slot_meta("legacy", legacy_path)
            if meta:
                meta["is_legacy"] = True
                slots.append(meta)

        slots.sort(key=lambda x: x.get("modified_timestamp", 0), reverse=True)
        return slots

    def _build_slot_meta(self, slot_id, filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
        return self._meta_from_save_data(data, slot_id, filepath)

    @staticmethod
    def _meta_from_save_data(data, slot_id, filepath):
        app_state = data.get("app_state", {})
        char_name = app_state.get("char_name")
        if not char_name:
            pl_id = app_state.get("pl_id", "new_investigator")
            characters = data.get("character_manager", {}).get("characters", {})
            char_name = characters.get(pl_id, {}).get("profile", {}).get("name", "不明")

        mtime = os.path.getmtime(filepath)
        scenario_file = data.get("scenario_file") or app_state.get("scenario_file", "")
        return {
            "slot_id": slot_id,
            "filename": os.path.basename(filepath),
            "modified_at": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "modified_timestamp": mtime,
            "char_name": char_name,
            "current_loc": app_state.get("current_loc", ""),
            "scenario_file": scenario_file,
            "is_autosave": slot_id == SaveLoadManager.AUTOSAVE_SLOT_ID,
            "is_legacy": False,
        }
