import json
import os
import random
import copy

from CoCRules import (
    compute_damage_bonus_and_build,
    compute_dodge_base,
    roll_luck_quickstart,
    skill_improvement_roll,
)

POOL_KEYS = frozenset({"SAN", "HP", "MP"})
MYTHOS_SKILL_MARKERS = ("クトゥルフ", "神話")

# マスター定義ファイル（pcs.json / npcs.json）へ書き戻してはならないセッション専用キー
SESSION_RUNTIME_KEYS = frozenset({
    "session_social",
    "session_skill_marks",
})


class CharacterManager:
    # CoC 7版の初期値ルールブック（主要なもの）
    BASE_SKILLS = {
        "回避": 0, "近接戦闘": 25, "投擲": 20, "射撃": 0,
        "応急手当": 30, "鍵開け": 1, "手さばき": 10, "聞き耳": 20, "隠密": 20, 
        "精神分析": 1, "追跡": 10, "登攀": 20, "図書館": 20, "目星": 25,
        "運転": 20, "機械修理": 10, "跳躍": 20, "ナビゲート": 10, "変装": 5,
        "言いくるめ": 5, "信用": 0, "説得": 10, "威圧": 15, "魅惑": 15, 
        "母国語": 0, "心理学": 10, "法律": 5, "歴史": 5
    }

    def __init__(self, pc_filepath="pcs.json", npc_filepath="npcs.json"):
        # 保存先を2つのファイルに分ける
        self.pc_filepath = pc_filepath
        self.npc_filepath = npc_filepath
        
        # メモリ上で統合される唯一のデータベース
        self.characters = {}
        # セッション参加中の PC ID 一覧（save/load で永続化）
        self.active_pcs = []
        self.load_data()
        if not self.active_pcs:
            self.active_pcs = self.list_pc_ids()

    def export_to_dict(self):
        """現在のキャラクター状態を辞書として返す（プール構造を正規化済み）。"""
        for char in self.characters.values():
            self.normalize_character_attributes(char)
        return {
            "characters": self.characters,
            "active_pcs": list(self.active_pcs or []),
        }

    def load_from_dict(self, data):
        """保存データからキャラクター状態を復元する。"""
        if "characters" in data:
            self.characters = data["characters"]
            for char_id, char in self.characters.items():
                self.normalize_character_attributes(char)
                if not char.get("profile", {}).get("is_npc", False):
                    self.initialize_derived_pools(char_id, fill_current=False)
        if "active_pcs" in data and data["active_pcs"]:
            self.set_active_pcs(data["active_pcs"])
        elif not self.active_pcs:
            self.active_pcs = self.list_pc_ids()
        # セーブ時点より後に追加された NPC 定義を補完（既存セッション状態は上書きしない）
        self.merge_missing_npcs_from_file()

    def merge_missing_npcs_from_file(self):
        """npcs.json にあるがメモリに無い NPC を追加する。"""
        npcs = self._load_json(self.npc_filepath)
        added = 0
        for cid, char in (npcs or {}).items():
            if cid in self.characters:
                continue
            if not (char.get("profile") or {}).get("is_npc", False):
                continue
            char = copy.deepcopy(char)
            for key in SESSION_RUNTIME_KEYS:
                char.pop(key, None)
            self.characters[cid] = char
            self.normalize_character_attributes(char)
            added += 1
        return added

    # ==========================================
    # プール型ステータス（SAN / HP / MP）current・max 分離
    # ==========================================
    @staticmethod
    def _coerce_int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _is_pool_dict(value):
        return isinstance(value, dict) and "current" in value

    def get_mythos_skill_points(self, char):
        """クトゥルフ神話技能の合計（SAN絶対上限 = 99 - この値）。"""
        if not char:
            return 0
        total = 0
        for name, value in (char.get("skills") or {}).items():
            if any(marker in str(name) for marker in MYTHOS_SKILL_MARKERS):
                total += self._coerce_int(value, 0)
        return total

    @staticmethod
    def _get_scalar_attribute(attrs, name, default=50):
        """STR/CON 等のスカラー能力値を取得（dict ラップにも対応）。"""
        val = (attrs or {}).get(name, default)
        if isinstance(val, dict):
            return CharacterManager._coerce_int(
                val.get("current", val.get("value")),
                default,
            )
        return CharacterManager._coerce_int(val, default)

    def compute_hp_max_from_attrs(self, attrs):
        """CoC7: 最大HP = (CON + SIZ) / 10（切り捨て）。"""
        con = self._get_scalar_attribute(attrs, "CON", 50)
        siz = self._get_scalar_attribute(attrs, "SIZ", 50)
        return max(1, (con + siz) // 10)

    def compute_mp_max_from_attrs(self, attrs):
        """CoC7: 最大MP = POW / 5（切り捨て）。"""
        pow_val = self._get_scalar_attribute(attrs, "POW", 50)
        return max(0, pow_val // 5)

    def apply_quickstart_derived_stats(self, char_id):
        """クイックスタート準拠の派生値（MOV/DB/BLD/HP/MP/SAN初期）を再計算。"""
        char = self.characters.get(char_id)
        if not char or char.get("profile", {}).get("is_npc", False):
            return
        attrs = char.setdefault("attributes", {})
        str_val = self._get_scalar_attribute(attrs, "STR", 50)
        siz_val = self._get_scalar_attribute(attrs, "SIZ", 50)
        pow_val = self._get_scalar_attribute(attrs, "POW", 50)
        derived = compute_damage_bonus_and_build(str_val, siz_val)
        attrs["DB"] = derived["DB"]
        attrs["BLD"] = derived["BLD"]
        attrs["MOV"] = attrs.get("MOV", 8) or 8

        self.initialize_derived_pools(char_id, fill_current=False)
        san_pool = self.get_stat_pool(char_id, "SAN")
        if san_pool.get("current", 0) <= 0:
            san_pool["current"] = pow_val
        san_pool["max"] = self.compute_san_absolute_max(char)
        if not san_pool.get("session_start"):
            san_pool["session_start"] = san_pool["current"]
        self._write_stat_pool(char_id, "SAN", san_pool)

        if not self.get_luck(char_id):
            attrs["LUCK"] = roll_luck_quickstart()
        self.save_data()

    def mark_skill_success(self, char_id, skill_name):
        """技能ロール成功時のチェックマーク（成功の報酬用）。"""
        if not skill_name:
            return
        char = self.characters.get(char_id)
        if not char:
            return
        marks = char.setdefault("session_skill_marks", [])
        if skill_name not in marks:
            marks.append(skill_name)

    def clear_skill_marks(self, char_id):
        char = self.characters.get(char_id)
        if char and "session_skill_marks" in char:
            char["session_skill_marks"] = []

    def get_skill_marks(self, char_id) -> list:
        char = self.characters.get(char_id)
        if not char:
            return []
        return list(char.get("session_skill_marks") or [])

    def apply_skill_improvement_rewards(self, char_id):
        """シナリオ終了時の技能成長ロール（クイックスタート）。"""
        char = self.characters.get(char_id)
        if not char:
            return []
        results = []
        skills = char.setdefault("skills", {})
        for skill_name in self.get_skill_marks(char_id):
            current = int(skills.get(skill_name, 0) or 0)
            if current <= 0:
                current = self.get_skill(char_id, skill_name)
            outcome = skill_improvement_roll(current)
            if outcome["improved"]:
                skills[skill_name] = outcome["new_value"]
            results.append({"skill": skill_name, **outcome})
        self.clear_skill_marks(char_id)
        self.save_data()
        return results

    def apply_mp_cost(self, char_id, amount):
        """
        MP消費。0を下回る分はHPから差し引く（クイックスタート）。
        戻り値: {mp_spent, hp_spent, new_mp, new_hp, overflow_to_hp}
        """
        amount = self._coerce_int(amount, 0)
        if amount <= 0:
            pool = self.get_stat_pool(char_id, "MP")
            return {
                "mp_spent": 0, "hp_spent": 0,
                "new_mp": pool["current"], "new_hp": self.get_stat_current(char_id, "HP"),
                "overflow_to_hp": 0,
            }
        pool = self.get_stat_pool(char_id, "MP")
        old_mp = pool["current"]
        if old_mp >= amount:
            pool["current"] = old_mp - amount
            self._write_stat_pool(char_id, "MP", pool)
            self.save_data()
            return {
                "mp_spent": amount, "hp_spent": 0,
                "new_mp": pool["current"], "new_hp": self.get_stat_current(char_id, "HP"),
                "overflow_to_hp": 0,
            }
        overflow = amount - old_mp
        pool["current"] = 0
        self._write_stat_pool(char_id, "MP", pool)
        old_hp, new_hp = self.apply_pool_damage(char_id, "HP", overflow)
        return {
            "mp_spent": old_mp, "hp_spent": overflow,
            "new_mp": 0, "new_hp": new_hp,
            "overflow_to_hp": overflow,
        }

    def compute_san_absolute_max(self, char):
        """正気度の理論上限（99 - クトゥルフ神話技能）。"""
        return max(0, 99 - self.get_mythos_skill_points(char))

    def initialize_derived_pools(self, char_id, *, fill_current=True):
        """HP/MP の max を能力値から算出し、SAN プールを正規化する。"""
        char = self.characters.get(char_id)
        if not char:
            return
        attrs = char.setdefault("attributes", {})
        self.normalize_character_attributes(char)

        hp_max = self.compute_hp_max_from_attrs(attrs)
        hp_pool = self.get_stat_pool(char_id, "HP")
        if not hp_pool.get("max"):
            hp_pool["max"] = hp_max
        if fill_current and hp_pool.get("current", 0) <= 0:
            hp_pool["current"] = hp_pool["max"]
        hp_pool["current"] = max(0, min(hp_pool["current"], hp_pool["max"]))
        self._write_stat_pool(char_id, "HP", hp_pool)

        mp_max = self.compute_mp_max_from_attrs(attrs)
        mp_pool = self.get_stat_pool(char_id, "MP")
        if not mp_pool.get("max"):
            mp_pool["max"] = mp_max
        if fill_current and mp_pool.get("current", 0) <= 0:
            mp_pool["current"] = mp_pool["max"]
        mp_pool["current"] = max(0, min(mp_pool["current"], mp_pool["max"]))
        self._write_stat_pool(char_id, "MP", mp_pool)

        san_pool = self.get_stat_pool(char_id, "SAN")
        san_pool["max"] = self.compute_san_absolute_max(char)
        if "session_start" not in san_pool or san_pool.get("session_start") is None:
            san_pool["session_start"] = san_pool.get("current", 50)
        san_pool["session_start"] = min(san_pool["session_start"], san_pool["max"])
        san_pool["current"] = max(0, min(san_pool["current"], san_pool["max"]))
        self._write_stat_pool(char_id, "SAN", san_pool)

    def normalize_character_attributes(self, char):
        """レガシー flat 値を current/max/session_start プールへ移行する。"""
        if not char:
            return
        attrs = char.setdefault("attributes", {})

        san_raw = attrs.get("SAN")
        if self._is_pool_dict(san_raw):
            current = self._coerce_int(san_raw.get("current"), 50)
            session_start = self._coerce_int(
                san_raw.get("session_start", san_raw.get("session_start_san")),
                current,
            )
        else:
            current = self._coerce_int(san_raw, 50)
            session_start = self._coerce_int(attrs.get("session_start_san"), current)

        san_max = self.compute_san_absolute_max(char)
        attrs["SAN"] = {
            "current": max(0, min(current, san_max)),
            "max": san_max,
            "session_start": max(0, min(session_start, san_max)),
            "session_start_san": max(0, min(session_start, san_max)),
        }
        attrs.pop("session_start_san", None)  # top-level legacy; pool内へ移動済み
        # 上で pool に session_start_san を入れ直す
        attrs["SAN"]["session_start_san"] = attrs["SAN"]["session_start"]

        hp_raw = attrs.get("HP")
        if self._is_pool_dict(hp_raw):
            hp_current = self._coerce_int(hp_raw.get("current"), 10)
            hp_max = self._coerce_int(hp_raw.get("max"), 0) or self.compute_hp_max_from_attrs(attrs)
        else:
            hp_current = self._coerce_int(hp_raw, 10)
            hp_max = self._coerce_int(attrs.get("MAX_HP"), 0) or self.compute_hp_max_from_attrs(attrs)
        attrs["HP"] = {
            "current": max(0, min(hp_current, hp_max)),
            "max": max(1, hp_max),
        }
        attrs.pop("MAX_HP", None)

        mp_raw = attrs.get("MP")
        if self._is_pool_dict(mp_raw):
            mp_current = self._coerce_int(mp_raw.get("current"), 10)
            mp_max = self._coerce_int(mp_raw.get("max"), 0) or self.compute_mp_max_from_attrs(attrs)
        else:
            mp_current = self._coerce_int(mp_raw, 10)
            mp_max = self._coerce_int(attrs.get("MAX_MP"), 0) or self.compute_mp_max_from_attrs(attrs)
        attrs["MP"] = {
            "current": max(0, min(mp_current, mp_max)),
            "max": max(0, mp_max),
        }
        attrs.pop("MAX_MP", None)
        char_id = self._find_char_id(char)
        if char_id:
            self.sync_dodge_base_skill(char_id)

    def _find_char_id(self, char):
        """キャラ dict から ID を逆引きする。"""
        if not char:
            return None
        for cid, c in self.characters.items():
            if c is char:
                return cid
        return None

    def get_dodge_base(self, char_id):
        """〈回避〉の基礎値（DEX÷2）。"""
        dex = self.get_attribute(char_id, "DEX") or 0
        return compute_dodge_base(dex)

    def sync_dodge_base_skill(self, char_id):
        """
        〈回避〉を DEX 由来の基礎値へ同期する。
        技能辞書に明示値がある場合（キャラ作成で割当済み）は上書きしない。
        skill_meta.回避_derived が True のときのみ DEX 変動に追従する。
        """
        char = self.characters.get(char_id)
        if not char or char.get("profile", {}).get("is_npc", False):
            return
        skills = char.setdefault("skills", {})
        meta = char.setdefault("skill_meta", {})
        dodge_base = self.get_dodge_base(char_id)

        if "回避" not in skills:
            skills["回避"] = dodge_base
            meta["回避_derived"] = True
        elif meta.get("回避_derived"):
            skills["回避"] = dodge_base

    def get_skill_tiers(self, char_id, skill_name):
        """技能のフル・ハード・イクストリーム値を返す。"""
        full = self.get_skill(char_id, skill_name)
        return {
            "full": full,
            "hard": full // 2,
            "extreme": full // 5,
        }

    def get_stat_pool(self, char_id, pool_key):
        """SAN/HP/MP のプール dict（current, max, SANは session_start / session_start_san）を返す。"""
        char = self.characters.get(char_id)
        if not char:
            return {"current": 0, "max": 0}
        self.normalize_character_attributes(char)
        pool = dict(char["attributes"].get(pool_key) or {})
        if pool_key == "SAN":
            if "session_start" not in pool:
                pool["session_start"] = pool.get("session_start_san", pool.get("current", 0))
            if "session_start_san" not in pool:
                pool["session_start_san"] = pool["session_start"]
            else:
                # 同期（どちらか欠落していた場合の保険）
                pool["session_start"] = pool.get("session_start", pool["session_start_san"])
                pool["session_start_san"] = pool.get("session_start_san", pool["session_start"])
            if "max" not in pool:
                pool["max"] = self.compute_san_absolute_max(char)
        elif pool_key == "HP" and not pool.get("max"):
            pool["max"] = self.compute_hp_max_from_attrs(char.get("attributes", {}))
        elif pool_key == "MP" and not pool.get("max"):
            pool["max"] = self.compute_mp_max_from_attrs(char.get("attributes", {}))
        pool.setdefault("current", 0)
        pool.setdefault("max", 0)
        return pool

    def get_session_start_san(self, char_id):
        """セッション開始時SAN（session_start_san）。"""
        pool = self.get_stat_pool(char_id, "SAN")
        return int(pool.get("session_start_san", pool.get("session_start", pool.get("current", 0))) or 0)

    def set_session_start_san(self, char_id, value=None):
        """session_start / session_start_san を指定値（省略時は現在SAN）に揃える。"""
        pool = self.get_stat_pool(char_id, "SAN")
        current = pool.get("current", 0)
        start = current if value is None else int(value)
        start = max(0, min(start, pool.get("max", start)))
        pool["session_start"] = start
        pool["session_start_san"] = start
        self._write_stat_pool(char_id, "SAN", pool)
        return start

    def get_stat_display(self, char_id):
        """UI 向けに SAN/HP/MP プールをまとめて返す。"""
        return {
            "SAN": self.get_stat_pool(char_id, "SAN"),
            "HP": self.get_stat_pool(char_id, "HP"),
            "MP": self.get_stat_pool(char_id, "MP"),
        }

    def get_stat_current(self, char_id, pool_key):
        return self.get_stat_pool(char_id, pool_key).get("current", 0)

    def get_stat_max(self, char_id, pool_key):
        return self.get_stat_pool(char_id, pool_key).get("max", 0)

    def get_san_recovery_limit(self, char_id):
        """SAN回復の上限 = min(理論max, セッション開始時SAN)。"""
        pool = self.get_stat_pool(char_id, "SAN")
        return min(pool.get("max", 99), pool.get("session_start", pool.get("current", 0)))

    def _write_stat_pool(self, char_id, pool_key, pool):
        char = self.characters.get(char_id)
        if not char:
            return
        attrs = char.setdefault("attributes", {})
        attrs[pool_key] = pool

    def set_stat_current(self, char_id, pool_key, value):
        pool = self.get_stat_pool(char_id, pool_key)
        ceiling = pool.get("max", value)
        pool["current"] = max(0, min(self._coerce_int(value, 0), ceiling))
        self._write_stat_pool(char_id, pool_key, pool)
        self.save_data()
        return pool["current"]

    def apply_pool_damage(self, char_id, pool_key, damage):
        """プールの current を減少（0未満にならない）。"""
        pool = self.get_stat_pool(char_id, pool_key)
        old = pool["current"]
        new = max(0, old - self._coerce_int(damage, 0))
        pool["current"] = new
        self._write_stat_pool(char_id, pool_key, pool)
        self.save_data()
        return old, new

    def recover_pool(self, char_id, pool_key, amount, *, limit=None):
        """プールの current を回復（limit を超えない）。"""
        pool = self.get_stat_pool(char_id, pool_key)
        if limit is None:
            if pool_key == "SAN":
                limit = min(pool.get("max", 0), pool.get("session_start", pool.get("current", 0)))
            else:
                limit = pool.get("max", 0)
        old = pool["current"]
        new = min(old + self._coerce_int(amount, 0), self._coerce_int(limit, old))
        pool["current"] = new
        self._write_stat_pool(char_id, pool_key, pool)
        self.save_data()
        return {"old": old, "new": new, "limit": limit, "recovered": new - old}

    def modify_pool(self, char_id, pool_key, amount, *, mode="damage"):
        """
        プール型ステータスを一括操作する。
        mode: damage | recover | set
        """
        amount = self._coerce_int(amount, 0)
        if mode == "damage":
            old, new = self.apply_pool_damage(char_id, pool_key, abs(amount))
            return {"old": old, "new": new, "delta": new - old}
        if mode == "recover":
            if pool_key == "SAN":
                limit = self.get_san_recovery_limit(char_id)
            else:
                limit = self.get_stat_max(char_id, pool_key)
            return self.recover_pool(char_id, pool_key, amount, limit=limit)
        if mode == "set":
            new = self.set_stat_current(char_id, pool_key, amount)
            return {"old": None, "new": new, "delta": None}
        raise ValueError(f"未知の mode: {mode}")

    def get_pc_baseline(self, char_id):
        """
        PC のシナリオ開始用固定初期値を返す。
        `baseline` ブロックを優先し、未定義時は POW / 能力値派生で補完する。
        """
        char = self.get_pc(char_id)
        if not char:
            return {}
        attrs = char.get("attributes") or {}
        baseline = char.get("baseline") or {}
        pow_val = self._coerce_int(attrs.get("POW"), 50)
        san_max = self.compute_san_absolute_max(char)
        hp_max = self.compute_hp_max_from_attrs(attrs)
        mp_max = self.compute_mp_max_from_attrs(attrs)

        san = baseline.get("SAN")
        if san is None:
            san = pow_val
        san = max(0, min(self._coerce_int(san, pow_val), san_max))

        luck = baseline.get("LUCK")
        if luck is None:
            luck = attrs.get("LUCK", attrs.get("LUK", attrs.get("幸運", 50)))
        luck = max(0, min(self._coerce_int(luck, 50), 99))

        hp = baseline.get("HP")
        hp = hp_max if hp is None else max(0, min(self._coerce_int(hp, hp_max), hp_max))

        mp = baseline.get("MP")
        mp = mp_max if mp is None else max(0, min(self._coerce_int(mp, mp_max), mp_max))

        return {
            "SAN": san,
            "LUCK": luck,
            "HP": hp,
            "MP": mp,
            "SAN_max": san_max,
            "HP_max": hp_max,
            "MP_max": mp_max,
        }

    def set_luck(self, char_id, value):
        """幸運値を設定する（シナリオ開始リセット用）。"""
        char = self.characters.get(char_id)
        if not char:
            return 0
        attrs = char.setdefault("attributes", {})
        luck_key = None
        for key in ("LUK", "幸運", "LUCK"):
            if key in attrs:
                luck_key = key
                break
        if luck_key is None:
            luck_key = "LUCK"
        attrs[luck_key] = max(0, min(self._coerce_int(value, 0), 99))
        return attrs[luck_key]

    def reset_pc_to_baseline(self, char_id, *, persist=False):
        """
        シナリオ開始用に PC を固定初期値へ強制復元する。
        SAN / 幸運 / HP / MP を baseline に戻し、発狂状態・技能チェックをクリアする。
        """
        char = self.get_pc(char_id)
        if not char:
            return None

        baseline = self.get_pc_baseline(char_id)
        self.normalize_character_attributes(char)
        self.apply_quickstart_derived_stats(char_id)

        san_pool = {
            "current": baseline["SAN"],
            "max": baseline["SAN_max"],
            "session_start": baseline["SAN"],
            "session_start_san": baseline["SAN"],
        }
        self._write_stat_pool(char_id, "SAN", san_pool)

        hp_pool = {
            "current": baseline["HP"],
            "max": baseline["HP_max"],
        }
        self._write_stat_pool(char_id, "HP", hp_pool)

        mp_pool = {
            "current": baseline["MP"],
            "max": baseline["MP_max"],
        }
        self._write_stat_pool(char_id, "MP", mp_pool)

        self.set_luck(char_id, baseline["LUCK"])

        # シナリオ横断で持ち越したくない一時状態
        char["states"] = []
        self.clear_skill_marks(char_id)

        if persist:
            self.save_data()
        return dict(baseline)

    def begin_session_stats(self, char_id):
        """シナリオ開始時: 固定 baseline へ復元し、session_start_san をその値で固定する。"""
        char = self.characters.get(char_id)
        if not char or char.get("profile", {}).get("is_npc", False):
            return
        self.reset_pc_to_baseline(char_id, persist=False)
        self.initialize_derived_pools(char_id, fill_current=False)
        # baseline 復元後の SAN をセッション開始値として再固定
        pool = self.get_stat_pool(char_id, "SAN")
        start = int(pool.get("current", 0) or 0)
        pool["session_start"] = start
        pool["session_start_san"] = start
        self._write_stat_pool(char_id, "SAN", pool)
        self.save_data()

    def reset_all_pcs_to_baseline(self, *, persist=True):
        """全 PC をシナリオ開始用 baseline へ復元する。"""
        results = {}
        for pc_id in self.list_pc_ids():
            results[pc_id] = self.reset_pc_to_baseline(pc_id, persist=False)
        if persist:
            self.save_data()
        return results

    def get_insanity_states(self, char_id):
        """キャラクターの構造化された発狂状態 dict の一覧を返す。"""
        char = self.characters.get(char_id)
        if not char:
            return []
        return [
            state for state in char.get("states", [])
            if isinstance(state, dict) and state.get("status") == "insane"
        ]

    def refresh_san_absolute_max(self, char_id):
        """神話技能変動後に SAN.max を再計算する。"""
        char = self.characters.get(char_id)
        if not char:
            return
        pool = self.get_stat_pool(char_id, "SAN")
        pool["max"] = self.compute_san_absolute_max(char)
        pool["current"] = min(pool["current"], pool["max"])
        pool["session_start"] = min(pool.get("session_start", pool["current"]), pool["max"])
        self._write_stat_pool(char_id, "SAN", pool)
        self.save_data()

    # ==========================================
    # データ読み込み・保存機能（ハイブリッド設計のコア）
    # ==========================================
    def load_data(self):
        """2つのファイルを読み込み、メモリ上で結合する（ディープコピー・セッション汚染除去）。"""
        pcs = self._load_json(self.pc_filepath)
        npcs = self._load_json(self.npc_filepath)

        merged = {}
        for source in (pcs, npcs):
            for char_id, char_data in (source or {}).items():
                # 定義ファイルはディープコピーしてからメモリ管理（参照共有による汚染防止）
                char = copy.deepcopy(char_data)
                # マスターに誤って残ったセッション状態はロード時に除去
                for key in SESSION_RUNTIME_KEYS:
                    char.pop(key, None)
                merged[char_id] = char

        self.characters.update(merged)

        for char_id, char in self.characters.items():
            self.normalize_character_attributes(char)
            if not char.get("profile", {}).get("is_npc", False):
                self.initialize_derived_pools(char_id, fill_current=False)

        print(f"[システム] PCデータ({len(pcs)}件) と NPCデータ({len(npcs)}件) をメモリに読み込みました。")

    # ==========================================
    # マルチPL: PC 一覧・参加管理
    # ==========================================
    def list_pc_ids(self):
        """pcs.json 由来の全 PC ID を返す（NPC 除外）。"""
        return [
            cid for cid, char in self.characters.items()
            if not char.get("profile", {}).get("is_npc", False)
        ]

    def list_npc_ids(self):
        """メモリ上の NPC ID 一覧。"""
        return [
            cid for cid, char in self.characters.items()
            if char.get("profile", {}).get("is_npc", False)
        ]

    def clear_session_social(self, char_id):
        """NPC のセッション限定社交状態を削除する。"""
        char = self.characters.get(char_id)
        if not char:
            return False
        if "session_social" in char:
            del char["session_social"]
            return True
        return False

    def cleanse_extraneous_npc_session_state(
        self,
        scenario_npc_ids=None,
        log_referenced_npc_ids=None,
        *,
        new_session=False,
    ):
        """
        シナリオ外・今セッション未登場 NPC の session_social をクレンジングする。

        - new_session=True: 全 NPC の session_social をクリア（新規ゲーム）
        - それ以外: シナリオ未定義 NPC、またはログ未登場のシナリオ内 NPC の
          session_social を削除（過去セッション残留対策）
        """
        scenario_ids = set(scenario_npc_ids or [])
        log_ids = set(log_referenced_npc_ids or [])
        cleared = []
        for cid in self.list_npc_ids():
            char = self.characters.get(cid) or {}
            if "session_social" not in char:
                continue
            if new_session:
                self.clear_session_social(cid)
                cleared.append(cid)
                continue
            if scenario_ids and cid not in scenario_ids:
                self.clear_session_social(cid)
                cleared.append(cid)
                continue
            if log_referenced_npc_ids is not None and cid not in log_ids:
                self.clear_session_social(cid)
                cleared.append(cid)
        return cleared

    def get_pc(self, char_id):
        """PC オブジェクトを返す。NPC または存在しない ID は None。"""
        char = self.characters.get(char_id)
        if not char or char.get("profile", {}).get("is_npc", False):
            return None
        return char

    def get_pc_name(self, char_id, default="探索者"):
        char = self.get_pc(char_id)
        if not char:
            return default
        return char.get("profile", {}).get("name", default)

    @staticmethod
    def get_pc_slot_label(pc_id):
        """pc_01 → PC1, pc_02 → PC2 などの表示用スロットラベル。"""
        pid = str(pc_id or "")
        if pid.startswith("pc_"):
            suffix = pid.split("_", 1)[-1]
            try:
                return f"PC{int(suffix)}"
            except ValueError:
                return suffix.upper()
        return pid

    def get_pc_log_prefix(self, pc_id, *, role="PC"):
        """ログ表示用プレフィックス（例: マクガフィン刑事(PC1)）。"""
        name = self.get_pc_name(pc_id, default=str(pc_id))
        slot = self.get_pc_slot_label(pc_id)
        if role == "PL":
            return f"{name}({slot})(PL)"
        return f"{name}({slot})"

    def set_active_pcs(self, pc_ids):
        """セッション参加 PC を設定する。"""
        valid = [str(pid) for pid in (pc_ids or []) if self.get_pc(pid)]
        if not valid:
            fallback = self.list_pc_ids()
            valid = fallback[:1] if fallback else []
        self.active_pcs = valid
        return list(self.active_pcs)

    @property
    def active_pc_list(self):
        """参加中 PC ID のコピー。"""
        if self.active_pcs:
            return list(self.active_pcs)
        return self.list_pc_ids()

    def is_pc_active(self, char_id):
        return str(char_id) in self.active_pc_list

    def is_pc_incapacitated(self, char_id, state_mgr=None):
        """意識不明・死亡なら True（探索/戦闘手番スキップ）。"""
        if state_mgr is not None and hasattr(state_mgr, "is_combat_participant_incapacitated"):
            return state_mgr.is_combat_participant_incapacitated(char_id)
        char = self.get_pc(char_id)
        if not char:
            return True
        states = char.get("states") or []
        state_labels = set()
        for s in states:
            if isinstance(s, dict):
                state_labels.add(str(s.get("label") or s.get("status") or ""))
            else:
                state_labels.add(str(s))
        if {"死亡", "意識不明", "排除"} & state_labels:
            return True
        if self.get_stat_current(char_id, "HP") <= 0:
            return True
        return False

    def get_top_skills(self, char_id, limit=8):
        """プロンプト注入用: 主要技能を (名前, 値) のリストで返す。"""
        char = self.get_pc(char_id)
        if not char:
            return []
        skills = char.get("skills") or {}
        ranked = []
        for name, val in skills.items():
            try:
                ranked.append((str(name), int(val)))
            except (TypeError, ValueError):
                continue
        ranked.sort(key=lambda x: x[1], reverse=True)
        return ranked[:limit]

    def build_character_sheet_summary(self, char_id):
        """LLM プロンプト用のキャラクターシート要約。"""
        char = self.get_pc(char_id)
        if not char:
            return ""
        profile = char.get("profile") or {}
        attrs = char.get("attributes") or {}
        name = profile.get("name", char_id)
        slot = self.get_pc_slot_label(char_id)
        occupation = profile.get("occupation", "")
        age = profile.get("age", "")
        memo = str(char.get("memo") or "").strip()
        personality = str(profile.get("personality") or profile.get("roleplay_notes") or "").strip()
        action_guide = str(profile.get("action_guide") or "").strip()
        notes = profile.get("roleplay_notes")
        if isinstance(notes, list):
            notes = " / ".join(str(n) for n in notes)
        notes = str(notes or "").strip()

        san = self.get_stat_display(char_id).get("SAN", {})
        hp = self.get_stat_display(char_id).get("HP", {})
        mp = self.get_stat_display(char_id).get("MP", {})
        luck = self.get_luck(char_id)

        skill_lines = [
            f"  - {sk}: {val}%" for sk, val in self.get_top_skills(char_id, limit=10)
        ]
        attr_keys = ("STR", "CON", "POW", "DEX", "APP", "SIZ", "INT", "EDU")
        attr_lines = []
        for key in attr_keys:
            val = self.get_attribute(char_id, key)
            if val is not None:
                attr_lines.append(f"{key}={val}")

        lines = [
            f"【操作キャラクター: {name} ({slot})】",
            f"ID: {char_id}",
        ]
        if occupation:
            lines.append(f"職業: {occupation}" + (f" / 年齢: {age}" if age else ""))
        if attr_lines:
            lines.append("能力値: " + ", ".join(attr_lines))
        lines.append(
            f"SAN {san.get('current', '?')}/{san.get('max', '?')} | "
            f"HP {hp.get('current', '?')}/{hp.get('max', '?')} | "
            f"MP {mp.get('current', '?')}/{mp.get('max', '?')} | 幸運 {luck}"
        )
        if skill_lines:
            lines.append("主要技能:\n" + "\n".join(skill_lines))
        if personality:
            lines.append(f"性格・口調: {personality}")
        if memo:
            lines.append(f"背景メモ: {memo}")
        if notes:
            lines.append(f"RP指針: {notes}")
        if action_guide:
            lines.append(f"推奨行動指針: {action_guide}")
        lines.append(
            f"※ あなたは【PC名: {name} / 職業: {occupation or '探索者'}】としてのみ発言・技能宣言すること。"
            "他 PC の名前・職業・口調と絶対に混同せず、代弁や操作も禁止。"
            "自己紹介では必ず自身の名前と職業を名乗ること。"
        )
        return "\n".join(lines)

    def _load_json(self, filepath):
        """内部用の読み込みヘルパー"""
        if os.path.exists(filepath):
            with open(filepath, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}

    @staticmethod
    def _strip_session_runtime_fields(char_data):
        """マスター定義へ書き戻す前にセッション専用フィールドを除去する。"""
        cleaned = copy.deepcopy(char_data)
        for key in SESSION_RUNTIME_KEYS:
            cleaned.pop(key, None)
        return cleaned

    def save_data(self):
        """
        メモリ上のデータを is_npc フラグで振り分けて保存する。
        session_social / session_skill_marks 等のセッション状態はマスターへ書き戻さない。
        （セッション進行はセーブデータ側で永続化する）
        """
        pcs_to_save = {}
        npcs_to_save = {}

        for char_id, char_data in self.characters.items():
            is_npc = char_data.get("profile", {}).get("is_npc", False)
            cleaned = self._strip_session_runtime_fields(char_data)
            if is_npc:
                npcs_to_save[char_id] = cleaned
            else:
                pcs_to_save[char_id] = cleaned

        self._save_json(self.pc_filepath, pcs_to_save)
        self._save_json(self.npc_filepath, npcs_to_save)
        print("[システム] データを PC用 と NPC用 のファイルに分割して保存しました（セッション状態は除外）。")

    def _save_json(self, filepath, data):
        """内部用の保存ヘルパー"""
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)

    # ==========================================
    # TRPGシステム機能（ダイス、ステータス生成）
    # ==========================================
    def roll_dice(self, num, sides):
        """NdMのダイスを振る"""
        return sum(random.randint(1, sides) for _ in range(num))

    def generate_7th_attribute(self, attr_name):
        """CoC7版のルールに従ってNPCのステータスをランダム生成する"""
        if attr_name in ["STR", "CON", "DEX", "APP", "POW"]:
            return self.roll_dice(3, 6) * 5
        elif attr_name in ["SIZ", "INT", "EDU"]:
            return (self.roll_dice(2, 6) + 6) * 5
        elif attr_name == "HP":
            return 10 # 暫定値
        else:
            return 50

    def get_attribute(self, char_id, attr_name):
        """能力値を取得（未設定のNPCならその場で生成）"""
        if attr_name in POOL_KEYS:
            return self.get_stat_current(char_id, attr_name)

        char = self.characters.get(char_id)
        if not char:
            return None
        
        if attr_name in char.get("attributes", {}):
            return char["attributes"][attr_name]
        
        # NPCの未設定ステータス遅延生成
        if char.get("profile", {}).get("is_npc", False):
            new_val = self.generate_7th_attribute(attr_name)
            if "attributes" not in char:
                char["attributes"] = {}
            char["attributes"][attr_name] = new_val
            self.save_data() # 生成したら即座に保存
            print(f"[KP裏処理] NPC '{char['profile']['name']}' の {attr_name} を【{new_val}】で生成しました。")
            return new_val
            
        return None

    def get_skill(self, char_id, skill_name):
        """技能値を取得（7版初期値ルール対応）"""
        char = self.characters.get(char_id)
        if not char:
            return 0

        if skill_name in char.get("skills", {}):
            return char["skills"][skill_name]

        if skill_name in self.BASE_SKILLS:
            if skill_name == "回避":
                return self.get_dodge_base(char_id)
            if skill_name == "母国語":
                edu = self.get_attribute(char_id, "EDU") or 0
                return edu
            return self.BASE_SKILLS[skill_name]

        return 0

    def get_luck(self, char_id):
        """現在の幸運値を取得（LUK / 幸運 / LUCK に対応）。"""
        char = self.characters.get(char_id)
        if not char:
            return 0
        attrs = char.get("attributes", {})
        for key in ("LUK", "幸運", "LUCK"):
            if key in attrs:
                return attrs[key]
        return 0

    def can_offer_luck_burn(self, char_id, margin, max_burn=10):
        """幸運消費の提案が可能か（差分上限・所持幸運の両方を満たすか）。"""
        if margin <= 0 or margin > max_burn:
            return False
        return self.get_luck(char_id) >= margin

    def spend_luck(self, char_id, amount, max_burn=10):
        """幸運を永久消費する。成功時 (True, 残り幸運)、不足時 (False, 現在幸運)。"""
        if amount <= 0:
            return True, self.get_luck(char_id)
        if amount > max_burn:
            return False, self.get_luck(char_id)

        char = self.characters.get(char_id)
        if not char:
            return False, 0

        attrs = char.setdefault("attributes", {})
        luck_key = None
        for key in ("LUK", "幸運", "LUCK"):
            if key in attrs:
                luck_key = key
                break
        if luck_key is None:
            luck_key = "LUK"
            attrs[luck_key] = 0

        current = attrs.get(luck_key, 0)
        if current < amount:
            return False, current

        attrs[luck_key] = current - amount
        self.save_data()
        return True, attrs[luck_key]

