import random
from enum import IntEnum

from CoCRules import roll_dice_formula

# 症状ラベル（日本語）から内部 type へのマッピング
_INSANITY_SYMPTOM_TYPE_MAP = (
    ("パニック", "panic"),
    ("恐怖症", "phobia"),
    ("幻覚", "hallucination"),
    ("妄想", "delusion"),
    ("偏執", "paranoia"),
    ("強迫", "obsession"),
    ("殺人", "homicidal"),
    ("自殺", "suicidal"),
    ("多弁", "mania"),
    ("ヒステリー", "hysteria"),
    ("混迷", "confusion"),
    ("健忘", "amnesia"),
    ("フェティッシュ", "fetish"),
    ("食欲", "voracious"),
)


class InterventionLevel(IntEnum):
    """膠着時のシステム介入強度。"""

    NONE = 0
    LIGHT = 1
    STANDARD = 2
    FORCE = 3


INTERVENTION_LEVEL_ALIASES = {
    "none": InterventionLevel.NONE,
    "なし": InterventionLevel.NONE,
    "0": InterventionLevel.NONE,
    "light": InterventionLevel.LIGHT,
    "控えめ": InterventionLevel.LIGHT,
    "1": InterventionLevel.LIGHT,
    "standard": InterventionLevel.STANDARD,
    "通常": InterventionLevel.STANDARD,
    "標準": InterventionLevel.STANDARD,
    "2": InterventionLevel.STANDARD,
    "force": InterventionLevel.FORCE,
    "積極的": InterventionLevel.FORCE,
    "強制": InterventionLevel.FORCE,
    "3": InterventionLevel.FORCE,
}

KP_STYLE_TO_INTERVENTION = {
    "classic": InterventionLevel.NONE,
    "クラシック": InterventionLevel.NONE,
    "collaborative": InterventionLevel.LIGHT,
    "協調": InterventionLevel.LIGHT,
    "helpful": InterventionLevel.STANDARD,
    "ヘルプフル": InterventionLevel.STANDARD,
    "directive": InterventionLevel.FORCE,
    "積極誘導": InterventionLevel.FORCE,
}

INTERVENTION_LEVEL_LABELS = {
    InterventionLevel.NONE: "なし",
    InterventionLevel.LIGHT: "控えめ",
    InterventionLevel.STANDARD: "標準",
    InterventionLevel.FORCE: "積極的",
}


def normalize_intervention_level(value, default=InterventionLevel.STANDARD):
    """文字列 / 数値 / Enum を InterventionLevel に正規化する。"""
    if isinstance(value, InterventionLevel):
        return value
    if value is None or value == "":
        return InterventionLevel(default)
    if isinstance(value, (int, float)):
        try:
            return InterventionLevel(int(value))
        except ValueError:
            return InterventionLevel(default)
    key = str(value).strip().lower()
    raw = str(value).strip()
    if raw in INTERVENTION_LEVEL_ALIASES:
        return INTERVENTION_LEVEL_ALIASES[raw]
    if key in INTERVENTION_LEVEL_ALIASES:
        return INTERVENTION_LEVEL_ALIASES[key]
    return InterventionLevel(default)


def intervention_level_from_kp_style(style, default=InterventionLevel.LIGHT):
    """KPプレイスタイルから介入レベルへマッピングする。"""
    if style is None or style == "":
        return InterventionLevel(default)
    raw = str(style).strip()
    key = raw.lower()
    if raw in KP_STYLE_TO_INTERVENTION:
        return KP_STYLE_TO_INTERVENTION[raw]
    if key in KP_STYLE_TO_INTERVENTION:
        return KP_STYLE_TO_INTERVENTION[key]
    return InterventionLevel(default)


def resolve_effective_intervention_level(scenario_level, kp_level):
    """シナリオ既定とKP設定の論理和（より強い側）を返す。"""
    a = normalize_intervention_level(scenario_level, InterventionLevel.NONE)
    b = normalize_intervention_level(kp_level, InterventionLevel.NONE)
    return InterventionLevel(max(int(a), int(b)))


def _symptom_label_to_type(label):
    """狂気症状の日本語ラベルから内部 type スラッグを推定する。"""
    for keyword, insanity_type in _INSANITY_SYMPTOM_TYPE_MAP:
        if keyword in str(label or ""):
            return insanity_type
    return "madness"


class GameStateManager:
    def __init__(self, character_manager):
        # CharacterManagerを内部で保持してデータを操作する
        self.char_mgr = character_manager
        
        # 戦闘用の状態管理
        self.in_combat = False
        self.round_number = 0
        self.turn_order = []  # DEX順に並んだキャラクターIDのリスト
        self.combat_turn_queue = []  # turn_order と同内容（DEXイニシアチブ）
        self.current_turn_index = 0
        self.pending_combat_defense = None  # 攻防保留（回避／応戦待ち）
        
        # 進行状態管理
        self.current_scene_id = "scene_001"
        self.turn_count = 0
        self.flags = {}

        # 膠着検知トラッカー
        self.stagnation_tracker = {
            "location": None,
            "progress_signature": None,
            "repeat_key": None,
            "streak": 0,
            "intervened_at_streak": 0,
            "last_reason": "",
        }

    def export_to_dict(self):
        """現在の状態を辞書化して返す"""
        return {
            # 進行状態
            "current_scene_id": self.current_scene_id,
            "turn_count": self.turn_count,
            "flags": self.flags,
            
            # 戦闘状態（追加）
            "in_combat": self.in_combat,
            "round_number": self.round_number,
            "turn_order": self.turn_order,
            "combat_turn_queue": list(self.combat_turn_queue or self.turn_order or []),
            "current_turn_index": self.current_turn_index,
            "pending_combat_defense": self.pending_combat_defense,
            "stagnation_tracker": dict(self.stagnation_tracker),
        }

    def load_from_dict(self, data):
        """辞書データから状態を復元する"""
        # 進行状態
        self.current_scene_id = data.get("current_scene_id", "scene_001")
        self.turn_count = data.get("turn_count", 0)
        self.flags = data.get("flags", {})
        
        # 戦闘状態（追加）
        self.in_combat = data.get("in_combat", False)
        self.round_number = data.get("round_number", 0)
        self.turn_order = data.get("turn_order", [])
        self.combat_turn_queue = data.get("combat_turn_queue") or list(self.turn_order or [])
        self.current_turn_index = data.get("current_turn_index", 0)
        self.pending_combat_defense = data.get("pending_combat_defense")
        tracker = data.get("stagnation_tracker")
        if isinstance(tracker, dict):
            self.stagnation_tracker.update(tracker)
        
    # ==========================================
    # 状態・狂気管理システム (GameStateManager クラス内)
    # ==========================================
    @staticmethod
    def _is_pc_character(char):
        """NPC ではなくプレイヤーキャラクターかどうか。"""
        return not char.get("profile", {}).get("is_npc", False)

    @staticmethod
    def get_insanity_states(char):
        """キャラクターの states から発狂状態 dict の一覧を取得する。"""
        if not char:
            return []
        return [
            state for state in char.get("states", [])
            if isinstance(state, dict) and state.get("status") == "insane"
        ]

    @staticmethod
    def get_insanity_state(char):
        """後方互換: 先頭の発狂状態 dict を返す。"""
        states = GameStateManager.get_insanity_states(char)
        return states[0] if states else None

    def get_insanity_state_for(self, char_id):
        """指定キャラクターIDの発狂状態一覧を返す。"""
        char = self.char_mgr.characters.get(char_id)
        return self.get_insanity_states(char)

    def _set_pc_insanity_state(
        self, char, *, insanity_type, category, duration, label,
        kind=None, bout_pending=False, realtime_madness=False, summary_madness=False,
    ):
        """PC のみに構造化された発狂状態を保存する（カテゴリごとに複数保持可能）。"""
        if not char or not self._is_pc_character(char):
            return

        states = char.setdefault("states", [])
        if category == "permanent":
            states[:] = [
                s for s in states
                if not (isinstance(s, dict) and s.get("status") == "insane")
            ]
        else:
            states[:] = [
                s for s in states
                if not (
                    isinstance(s, dict)
                    and s.get("status") == "insane"
                    and s.get("category") == category
                )
            ]
        entry = {
            "status": "insane",
            "type": insanity_type,
            "category": category,
            "duration": duration,
            "label": label,
            "kind": kind or (
                "temporary_insanity" if category == "temporary"
                else "indefinite_insanity" if category == "indefinite"
                else "permanent_insanity"
            ),
            "bout_pending": bool(bout_pending),
            "realtime_madness": bool(realtime_madness),
            "summary_madness": bool(summary_madness),
        }
        states.append(entry)
        self.char_mgr.save_data()

    def apply_san_damage(
        self, char_id, damage, *,
        force_temporary_insanity=False,
        insanity_label=None,
        insanity_duration=None,
        dice_engine=None,
        char_name=None,
        event_log=None,
    ):
        """
        SAN減少と第7版準拠の狂気判定。

        - 一時的狂気: 1回で 5点以上減少したとき INT ロール成功で発症
          （成功=理解して発狂 / 失敗=現実逃避で回避）
        - 不定の狂気: session_start_san から 20% 以上失ったとき（INTロール不要）
        """
        from DiceEngine import DiceEngine, SuccessLevel, is_success_level

        char = self.char_mgr.characters.get(char_id)
        if not char:
            return {"status": "error"}

        self.char_mgr.normalize_character_attributes(char)
        san_pool = self.char_mgr.get_stat_pool(char_id, "SAN")
        session_start_san = self.char_mgr.get_session_start_san(char_id)

        attrs = char.setdefault("attributes", {})
        intel = attrs.get("INT", 50)
        if isinstance(intel, dict):
            intel = intel.get("current", 50)
        int_val = self.char_mgr._coerce_int(intel, 50)

        old_san, new_san = self.char_mgr.apply_pool_damage(char_id, "SAN", damage)
        lost_san = max(0, old_san - new_san)

        states = char.setdefault("states", [])
        insanity_events = []
        madness_instruction = ""
        display_name = char_name or char.get("profile", {}).get("name", char_id)
        engine = dice_engine or DiceEngine()

        def _append_log(message):
            insanity_events.append(message)
            if event_log is not None:
                event_log.append({
                    "channel": "OOC",
                    "location": "all",
                    "secret_to": None,
                    "text": f"システム: {message}",
                })

        # 【3】永久的発狂
        if new_san == 0:
            permanent_label = "永久的発狂"
            if permanent_label not in states:
                states.append(permanent_label)
            _append_log("【永久的発狂】SAN値が0になりました。探索者は完全に正気を失いました。")
            madness_instruction = (
                "【システム指示】探索者のSAN値が0になりました。"
                "回復不能な狂気に陥り、ゲームオーバーとなったことを絶望的に描写してください。"
            )
            self._set_pc_insanity_state(
                char,
                insanity_type="permanent",
                category="permanent",
                duration=0,
                label=permanent_label,
                kind="permanent_insanity",
            )
        else:
            # 【1】一時的狂気（1回で5点以上 + INTロール成功）
            if lost_san >= 5:
                bouts = [
                    "気絶あるいは金切り声の発作",
                    "パニック状態で逃げ出す",
                    "肉体的なヒステリーあるいは感情の噴出",
                    "早口でぶつぶつ言う意味不明の会話あるいは多弁症",
                    "その場から動けなくなるほどの恐怖症",
                    "殺人癖あるいは自殺癖",
                    "幻覚あるいは妄想",
                    "周囲の者の動作や発言を反復する",
                    "異常食欲",
                    "混迷",
                ]
                if force_temporary_insanity:
                    duration = (
                        self.char_mgr._coerce_int(insanity_duration, 0)
                        if insanity_duration is not None
                        else random.randint(1, 10) + 4
                    )
                    bout_symptom = str(insanity_label).strip() if insanity_label else random.choice(bouts)
                    _append_log(
                        "【一時的狂気・強制発症】シナリオ効果により、"
                        "INTロールを経ずに一時的狂気が発症した。"
                    )
                    _append_log(f"【一時的狂気】症状：『{bout_symptom}』 ({duration}ラウンド継続)")
                    madness_instruction = (
                        f"【重要指示】探索者は一時的狂気に陥りました。症状は『{bout_symptom}』です。"
                        "この異常な行動を強制的に描写に組み込んでください。"
                    )
                    self._set_pc_insanity_state(
                        char,
                        insanity_type=_symptom_label_to_type(bout_symptom),
                        category="temporary",
                        duration=duration,
                        label=bout_symptom,
                        kind="temporary_insanity",
                        bout_pending=True,
                        realtime_madness=True,
                        summary_madness=False,
                    )
                else:
                    int_roll = engine.execute_int_roll(display_name, int_val)
                    int_ok = is_success_level(int_roll.get("success_level", SuccessLevel.FAILURE))
                    roll_val = int_roll.get("roll", "?")
                    if int_ok:
                        duration = random.randint(1, 10) + 4
                        bout_symptom = random.choice(bouts)
                        _append_log(
                            f"【INTロール】1d100={roll_val} ≦ INT{int_val} ＞ 成功。"
                            "事態を完全に理解してしまい、一時的狂気に陥った！"
                        )
                        _append_log(
                            f"【一時的狂気】症状：『{bout_symptom}』 ({duration}ラウンド継続)"
                            " / 潜伏期・リアルタイム狂気フラグ=ON"
                        )
                        madness_instruction = (
                            f"【重要指示】探索者は一時的狂気に陥りました。症状は『{bout_symptom}』です。"
                            "この異常な行動を強制的に描写に組み込んでください。"
                        )
                        self._set_pc_insanity_state(
                            char,
                            insanity_type=_symptom_label_to_type(bout_symptom),
                            category="temporary",
                            duration=duration,
                            label=bout_symptom,
                            kind="temporary_insanity",
                            bout_pending=True,
                            realtime_madness=True,
                            summary_madness=False,
                        )
                    else:
                        _append_log(
                            f"【INTロール】1d100={roll_val} ≦ INT{int_val} ＞ 失敗。"
                            "現実逃避に成功し、一時的狂気を免れた。"
                        )

            # 【2】不定の狂気（セッション開始SANの20%以上を喪失、未発症時のみ）
            threshold = session_start_san * 0.2
            already_indefinite = any(
                (isinstance(s, dict) and s.get("status") == "insane" and s.get("category") == "indefinite")
                or s == "不定の発狂"
                or (isinstance(s, dict) and s.get("kind") == "indefinite_insanity")
                for s in states
            )
            if (
                session_start_san > 0
                and (session_start_san - new_san) >= threshold
                and not already_indefinite
            ):
                indefinite_label = "不定の発狂"
                if indefinite_label not in states:
                    states.append(indefinite_label)
                bouts_indefinite = [
                    "健忘症", "激しい恐怖症", "幻覚", "奇妙な性的嗜好", "フェティッシュ",
                    "制御不能のチック、震え。会話や文章での人との交流が不可能になる",
                    "心因性視覚障害、心因性難聴、単数あるいは四肢の機能障害",
                    "短時間の心因反応", "一時的偏執狂", "強迫観念にとりつかれた行動",
                ]
                bout_symptom = random.choice(bouts_indefinite)
                duration_months = random.randint(1, 6)
                _append_log(
                    f"【不定の狂気】セッション開始SAN({session_start_san})から20%以上を喪失"
                    f"（現在{new_san}）。症状：『{bout_symptom}』 ({duration_months}ヶ月継続）"
                )
                madness_instruction = (
                    f"{madness_instruction}\n【重要指示】探索者は不定の狂気（重篤なトラウマ）を発症しました。"
                    f"症状は『{bout_symptom}』です。"
                ).strip()
                self._set_pc_insanity_state(
                    char,
                    insanity_type=_symptom_label_to_type(bout_symptom),
                    category="indefinite",
                    duration=duration_months,
                    label=bout_symptom,
                    kind="indefinite_insanity",
                )

        return {
            "old_san": old_san,
            "new_san": new_san,
            "damage": damage,
            "lost_san": lost_san,
            "events": insanity_events,
            "madness_instruction": madness_instruction.strip(),
        }

    def recover_san(self, char_id, amount):
        """SAN回復（上限 = min(max, session_start) を超えない）。"""
        if not self.char_mgr.characters.get(char_id):
            return {"status": "error"}
        return self._recover_pool_result(
            char_id, "SAN",
            self.char_mgr.modify_pool(char_id, "SAN", amount, mode="recover"),
        )

    def recover_hp(self, char_id, amount):
        """HP回復（max を超えない）。"""
        if not self.char_mgr.characters.get(char_id):
            return {"status": "error"}
        return self._recover_pool_result(
            char_id, "HP",
            self.char_mgr.modify_pool(char_id, "HP", amount, mode="recover"),
            key_prefix="hp",
        )

    def recover_mp(self, char_id, amount):
        """MP回復（max を超えない）。"""
        if not self.char_mgr.characters.get(char_id):
            return {"status": "error"}
        return self._recover_pool_result(
            char_id, "MP",
            self.char_mgr.modify_pool(char_id, "MP", amount, mode="recover"),
            key_prefix="mp",
        )

    @staticmethod
    def _recover_pool_result(char_id, pool_key, result, key_prefix=None):
        prefix = (key_prefix or pool_key.lower()).lower()
        return {
            "status": "success",
            f"old_{prefix}": result["old"],
            f"new_{prefix}": result["new"],
            "recovered": result["recovered"],
            "recovery_limit": result["limit"],
        }

    def reset_session_san(self):
        """ゲーム内で1時間が経過した時の処理（不定の狂気リセット用）"""
        for char_id, char in self.char_mgr.characters.items():
            if "SAN" not in char.get("attributes", {}):
                continue
            self.char_mgr.set_session_start_san(char_id)
        self.char_mgr.save_data()
        print("[システム] 1時間が経過しました。不定の発狂の基準値をリセットしました。")

    def reset_day(self):
        """ゲーム内での1日が経過した時の処理（不定の狂気の基準値をリセット）"""
        for char_id, char in self.char_mgr.characters.items():
            if "SAN" not in char.get("attributes", {}):
                continue
            current = self.char_mgr.get_stat_current(char_id, "SAN")
            attrs = char.setdefault("attributes", {})
            attrs["start_of_day_san"] = current
        self.char_mgr.save_data()
        print("[システム] 1日が経過しました。SAN値の減少記録をリセットしました。")

    # ==========================================
    # 戦闘・ラウンド管理システム
    # ==========================================
    def _melee_skill_value(self, char_id):
        """近接戦闘関連技能の最良値（後方互換）。"""
        return self._combat_skill_value(char_id, include_melee=True, include_firearms=False)

    def _combat_skill_value(self, char_id, *, include_melee=True, include_firearms=True):
        """
        イニシアチブ同値タイブレーク用の戦闘関連技能の最良値。
        〈近接戦闘〉／〈射撃〉など関連技能の高い方を採用する。
        """
        char = self.char_mgr.characters.get(char_id) or {}
        skills = char.get("skills") or {}
        best = 0
        for key, val in skills.items():
            k = str(key)
            kl = k.lower()
            is_melee = (
                "近接" in k or "格闘" in k
                or "Fighting" in k or "fighting" in kl
            )
            is_firearm = (
                "射撃" in k or "火器" in k
                or "拳銃" in k or "ライフル" in k or "ショットガン" in k
                or "firearm" in kl or "handgun" in kl or "rifle" in kl
            )
            if (include_melee and is_melee) or (include_firearms and is_firearm):
                try:
                    best = max(best, int(val))
                except (TypeError, ValueError):
                    continue
        fallbacks = []
        if include_melee:
            fallbacks.extend(("近接戦闘（格闘）", "近接戦闘", "格闘", "Fighting (Brawl)"))
        if include_firearms:
            fallbacks.extend(("射撃（拳銃）", "射撃", "火器", "Firearms (Handgun)"))
        for fallback in fallbacks:
            try:
                best = max(best, int(self.char_mgr.get_skill(char_id, fallback) or 0))
            except (TypeError, ValueError):
                continue
        return int(best)

    def start_combat(self, participant_ids):
        """
        戦闘参加者のIDリストを受け取り、DEX降順でイニシアチブ順を決定して戦闘を開始する。
        DEX同値 → 近接／射撃など関連戦闘技能が高い方 → それでも同値なら 1d100 で決定。
        """
        unique_ids = []
        seen = set()
        for pid in participant_ids or []:
            cid = str(pid or "").strip()
            if cid and cid not in seen and cid in self.char_mgr.characters:
                seen.add(cid)
                unique_ids.append(cid)

        ranking = []
        for cid in unique_ids:
            dex = int(self.char_mgr.get_attribute(cid, "DEX") or 0)
            combat_skill = self._combat_skill_value(cid)
            tie_break = random.randint(1, 100)
            ranking.append((dex, combat_skill, tie_break, cid))

        ranking.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
        self.turn_order = [cid for _, _, _, cid in ranking]
        self.combat_turn_queue = list(self.turn_order)
        self.in_combat = True
        self.round_number = 1
        self.current_turn_index = 0
        self.pending_combat_defense = None
        self._advance_to_capable_actor(reset_search=True)

        order_names = []
        for dex, combat_skill, tb, cid in ranking:
            name = self.char_mgr.characters[cid]["profile"]["name"]
            order_names.append(f"{name}(DEX{dex}/戦闘技能{combat_skill})")
        print(f"[システム] 戦闘開始！ 行動順: {' -> '.join(order_names)}")
        return self.turn_order

    def is_combat_participant_incapacitated(self, char_id):
        """意識不明・死亡・排除済みなら True（手番スキップ）。"""
        char = self.char_mgr.characters.get(char_id)
        if not char:
            return True
        states = char.get("states") or []
        state_labels = set()
        for s in states:
            if isinstance(s, dict):
                state_labels.add(str(s.get("label") or s.get("status") or ""))
            else:
                state_labels.add(str(s))
        if "死亡" in state_labels or "意識不明" in state_labels or "排除" in state_labels:
            return True
        flags = char.get("flags")
        if isinstance(flags, dict) and (flags.get("dead") or flags.get("unconscious")):
            return True
        if isinstance(flags, (list, set)) and ({"死亡", "意識不明", "排除"} & set(flags)):
            return True
        if self.char_mgr.get_stat_current(char_id, "HP") <= 0:
            return True
        return False

    def _advance_to_capable_actor(self, *, reset_search=False):
        """行動可能な次の手番キャラを current_turn_index に合わせる。"""
        if not self.in_combat or not self.turn_order:
            return None
        n = len(self.turn_order)
        start = 0 if reset_search else int(self.current_turn_index)
        for offset in range(n):
            idx = (start + offset) % n
            cid = self.turn_order[idx]
            if not self.is_combat_participant_incapacitated(cid):
                self.current_turn_index = idx
                return cid
        return None

    def get_current_actor(self):
        """現在行動すべきキャラクターのIDを返す"""
        if not self.in_combat or not self.turn_order:
            return None
        if self.current_turn_index >= len(self.turn_order):
            return None
        return self.turn_order[self.current_turn_index]

    def get_combat_turn_queue(self):
        return list(self.combat_turn_queue or self.turn_order or [])

    def next_turn(self):
        """次のキャラクターのターンへ移行。全員終われば次のラウンドへ。行動不能はスキップ。"""
        if not self.in_combat or not self.turn_order:
            return None

        next_idx = int(self.current_turn_index) + 1
        if next_idx >= len(self.turn_order):
            return self._begin_new_combat_round()

        self.current_turn_index = next_idx
        actor = self._advance_to_capable_actor(reset_search=False)
        if actor is None:
            return self._begin_new_combat_round()

        next_actor_name = self.char_mgr.characters[actor]["profile"]["name"]
        print(f"[システム] {next_actor_name} のターンです。")
        return actor

    def _begin_new_combat_round(self):
        """ラウンド終了処理（一時的狂気・瀕死判定）の後、次ラウンド先頭へ。"""
        self.current_turn_index = 0
        self.round_number = int(self.round_number or 0) + 1
        print(f"\n[システム] --- 第{self.round_number}ラウンド 開始 ---")
        round_logs = []
        for cid in self.turn_order:
            resolved = self.tick_temporary_insanity_rounds(cid)
            for label in resolved:
                round_logs.append(
                    f"{self.char_mgr.characters[cid]['profile']['name']}: {label}から回復"
                )
            dying = self.tick_dying_state(cid)
            if dying.get("status") == "dead":
                name = self.char_mgr.characters[cid]["profile"]["name"]
                round_logs.append(
                    f"{name}は瀕死状態のCONロール失敗（{dying.get('roll')} vs {dying.get('target')}）により死亡"
                )
        if round_logs:
            for msg in round_logs:
                print(f"[戦闘] {msg}")

        actor = self._advance_to_capable_actor(reset_search=True)
        if actor:
            next_actor_name = self.char_mgr.characters[actor]["profile"]["name"]
            print(f"[システム] {next_actor_name} のターンです。")
        return actor

    def end_combat(self):
        """戦闘を終了する"""
        self.in_combat = False
        self.turn_order = []
        self.combat_turn_queue = []
        self.round_number = 0
        self.current_turn_index = 0
        self.pending_combat_defense = None
        print("[システム] 戦闘が終了しました。")

    def set_pending_combat_defense(self, payload):
        self.pending_combat_defense = dict(payload or {})

    def clear_pending_combat_defense(self):
        self.pending_combat_defense = None

    def get_pending_combat_defense(self):
        return self.pending_combat_defense

    def choose_npc_defense_mode(self, defender_id, *, attack_type="melee"):
        """
        NPC/モンスターの防衛選択。
        近接: 回避／応戦。射撃: 回避／甘受（応戦不可）。
        """
        if str(attack_type or "melee").lower() in ("shoot", "firearm", "ranged", "gun", "射撃"):
            return self.choose_npc_shoot_defense_mode(defender_id)

        char = self.char_mgr.characters.get(defender_id) or {}
        cp = char.get("combat_profile") or {}
        preferred = str(cp.get("preferred_defense") or cp.get("defense_mode") or "").strip().lower()
        if preferred in ("fight_back", "fighting_back", "応戦", "fightback"):
            return "fight_back"
        if preferred in ("dodge", "回避", "evade"):
            return "dodge"

        aggression = cp.get("aggression", cp.get("aggressiveness"))
        try:
            if aggression is not None and int(aggression) >= 50:
                return "fight_back"
        except (TypeError, ValueError):
            pass

        profile = char.get("profile") or {}
        if profile.get("monster") or profile.get("undead"):
            return "fight_back"

        notes = " ".join(str(n) for n in (char.get("roleplay_notes") or []))
        memo = str(char.get("memo") or "")
        if any(k in notes or k in memo for k in ("好戦", "悪意", "攻撃的", "興奮")):
            return "fight_back"

        hp = self.char_mgr.get_stat_current(defender_id, "HP")
        max_hp = self.char_mgr.get_stat_max(defender_id, "HP") or 1
        if hp <= max_hp // 3:
            return "dodge"
        return "fight_back"

    def choose_npc_shoot_defense_mode(self, defender_id):
        """射撃に対する NPC 防衛: dodge / accept のみ（応戦は選ばない）。"""
        char = self.char_mgr.characters.get(defender_id) or {}
        cp = char.get("combat_profile") or {}
        preferred = str(
            cp.get("preferred_shoot_defense")
            or cp.get("preferred_defense")
            or cp.get("defense_mode")
            or ""
        ).strip().lower()
        if preferred in (
            "accept", "take", "take_it", "none", "no_dodge",
            "甘受", "甘んじて", "甘んじて受ける",
        ):
            return "accept"
        if preferred in ("dodge", "回避", "evade"):
            return "dodge"
        # 好戦的でも射撃には応戦不可 → 甘受に倒しがち
        try:
            aggression = cp.get("aggression", cp.get("aggressiveness"))
            if aggression is not None and int(aggression) >= 70:
                return "accept"
        except (TypeError, ValueError):
            pass
        dodge_val = int(self.char_mgr.get_skill(defender_id, "回避") or 0)
        if dodge_val >= 30:
            return "dodge"
        return "accept"

    @staticmethod
    def _weapon_skill_is_firearm(skill_name):
        skill = str(skill_name or "")
        sl = skill.lower()
        return any(
            k in skill for k in ("射撃", "火器", "拳銃", "ライフル", "ショットガン")
        ) or any(k in sl for k in ("firearm", "handgun", "rifle", "shotgun", "gun"))

    @staticmethod
    def _weapon_skill_is_melee(skill_name):
        skill = str(skill_name or "")
        sl = skill.lower()
        return any(
            k in skill for k in ("近接", "格闘")
        ) or "fighting" in sl or not skill

    def get_default_melee_weapon(self, char_id):
        """キャラクターのデフォルト近接武器を返す。"""
        char = self.char_mgr.characters.get(char_id) or {}
        weapons = char.get("weapons") or []
        if isinstance(weapons, list):
            for w in weapons:
                if not isinstance(w, dict):
                    continue
                skill = str(w.get("skill") or "")
                if self._weapon_skill_is_melee(skill) and not self._weapon_skill_is_firearm(skill):
                    return dict(w)
            if weapons and isinstance(weapons[0], dict):
                w0 = weapons[0]
                if not self._weapon_skill_is_firearm(w0.get("skill")):
                    return dict(w0)
        return {
            "name": "素手",
            "skill": "近接戦闘（格闘）",
            "damage": "1D3",
            "apply_damage_bonus": True,
        }

    def get_default_firearm_weapon(self, char_id):
        """キャラクターのデフォルト銃器を返す。"""
        char = self.char_mgr.characters.get(char_id) or {}
        weapons = char.get("weapons") or []
        if isinstance(weapons, list):
            for w in weapons:
                if not isinstance(w, dict):
                    continue
                if self._weapon_skill_is_firearm(w.get("skill")) or w.get("type") in (
                    "firearm", "gun", "ranged", "射撃",
                ):
                    return dict(w)
        return {
            "name": "拳銃",
            "skill": "射撃（拳銃）",
            "damage": "1D10",
            "apply_damage_bonus": False,
            "type": "firearm",
        }

    def is_point_blank_shot(
        self,
        attacker_id,
        defender_id,
        *,
        current_loc="",
        scenario_mgr=None,
        weapon=None,
    ):
        """
        ゼロ距離（至近）射撃か。
        同一ロケーション、または weapon/scenario の明示設定に基づく。
        """
        weapon = weapon or {}
        range_raw = str(weapon.get("range") or weapon.get("distance") or "").strip().lower()
        if weapon.get("point_blank") is False:
            return False
        if range_raw in ("long", "extreme", "medium", "遠距離", "中距離", "長距離"):
            return False
        if weapon.get("point_blank") is True or range_raw in (
            "point_blank", "point-blank", "pb", "ゼロ距離", "至近", "近接距離",
        ):
            return True

        if scenario_mgr is not None:
            loc_id = current_loc or getattr(scenario_mgr, "location", None) or ""
            loc_info = {}
            if hasattr(scenario_mgr, "get_location_info") and loc_id:
                loc_info = scenario_mgr.get_location_info(loc_id) or {}
            if loc_info.get("point_blank_range") or loc_info.get("close_quarters"):
                return True
            # 参加者ロケーション既定: 戦闘中の同一ロケーションは至近
            if loc_id:
                return True
            meta = getattr(scenario_mgr, "scenario_data", None) or {}
            if isinstance(meta, dict):
                sm = meta.get("scenario_meta") or {}
                if sm.get("default_point_blank") is False:
                    return False
        # 戦闘中でロケーション情報が無い場合も同一交戦とみなしゼロ距離
        return bool(self.in_combat)

    def resolve_weapon_damage_amount(
        self, attacker_id, weapon=None, *, is_extreme=False, is_firearm=False,
    ):
        """武器ダメージをロールして総ダメージを返す（近接は DB 可、銃器は貫通ルール）。"""
        from CoCRules import compute_firearm_damage, compute_melee_damage

        if is_firearm:
            weapon = weapon or self.get_default_firearm_weapon(attacker_id)
            dice_str = str(weapon.get("damage") or weapon.get("dmg") or "1D10")
            total, detail = compute_firearm_damage(dice_str, is_impale=bool(is_extreme))
            return {
                "damage": int(total),
                "detail": detail,
                "weapon": weapon,
                "dice": dice_str,
                "db": "",
                "impale": bool(is_extreme),
            }

        weapon = weapon or self.get_default_melee_weapon(attacker_id)
        dice_str = str(weapon.get("damage") or weapon.get("dmg") or "1D3")
        add_db = bool(weapon.get("apply_damage_bonus", weapon.get("db", weapon.get("add_db", True))))
        db_expr = ""
        if add_db:
            char = self.char_mgr.characters.get(attacker_id) or {}
            attrs = char.get("attributes") or {}
            db_expr = str(attrs.get("DB") or attrs.get("db") or "0")
        total, detail = compute_melee_damage(
            dice_str,
            damage_bonus_dice=db_expr if add_db else "",
            is_extreme=is_extreme,
        )
        return {
            "damage": int(total),
            "detail": detail,
            "weapon": weapon,
            "dice": dice_str,
            "db": db_expr,
            "impale": False,
        }

    def _apply_hit_with_armor(
        self,
        attacker_id,
        defender_id,
        *,
        weapon=None,
        is_extreme=False,
        is_firearm=False,
        dice_engine=None,
    ):
        """命中ダメージ算出・装甲減算・物理ダメージ適用の共通処理。"""
        rolled = self.resolve_weapon_damage_amount(
            attacker_id, weapon=weapon, is_extreme=is_extreme, is_firearm=is_firearm,
        )
        raw = int(rolled["damage"])
        defender = self.char_mgr.characters.get(defender_id) or {}
        cp = defender.get("combat_profile") or {}
        armor = int(cp.get("armor_points") or 0)
        mitigated = 0
        if armor > 0:
            mitigated = min(armor, raw)
            cp["armor_points"] = max(0, armor - mitigated)
            defender["combat_profile"] = cp
            self.char_mgr.save_data()
        final_dmg = max(0, raw - mitigated)
        result = self.apply_physical_damage(
            defender_id, final_dmg, dice_engine=dice_engine,
        )
        result["rolled_damage"] = raw
        result["armor_mitigated"] = mitigated
        result["damage_detail"] = rolled["detail"]
        result["weapon_name"] = (rolled.get("weapon") or {}).get("name") or rolled.get("dice")
        result["impale"] = bool(rolled.get("impale"))
        return result

    def apply_melee_hit(
        self,
        attacker_id,
        defender_id,
        *,
        weapon=None,
        is_extreme=False,
        dice_engine=None,
    ):
        """近接命中ダメージを算出し、装甲減算のうえ apply_physical_damage する。"""
        return self._apply_hit_with_armor(
            attacker_id, defender_id,
            weapon=weapon, is_extreme=is_extreme, is_firearm=False, dice_engine=dice_engine,
        )

    def apply_firearm_hit(
        self,
        attacker_id,
        defender_id,
        *,
        weapon=None,
        is_impale=False,
        dice_engine=None,
    ):
        """
        銃器命中ダメージ。イクストリーム／クリティカル時は貫通（インペール）:
        武器最大ダメージ＋通常ダイス。DB は適用しない。
        """
        return self._apply_hit_with_armor(
            attacker_id, defender_id,
            weapon=weapon, is_extreme=is_impale, is_firearm=True, dice_engine=dice_engine,
        )

    def tick_temporary_insanity_rounds(self, char_id):
        """一時的狂気の残ラウンドを1減らし、0で解除する。"""
        char = self.char_mgr.characters.get(char_id)
        if not char:
            return []
        resolved = []
        states = char.get("states", [])
        kept = []
        for state in states:
            if isinstance(state, dict) and state.get("status") == "insane":
                if state.get("category") == "temporary":
                    duration = int(state.get("duration", 0) or 0) - 1
                    if duration <= 0:
                        resolved.append(state.get("label", "一時的狂気"))
                        continue
                    state = dict(state)
                    state["duration"] = duration
                kept.append(state)
            else:
                kept.append(state)
        char["states"] = kept
        if resolved:
            self.char_mgr.save_data()
        return resolved

    def resolve_major_wound_con_check(self, target_id, dice_engine=None):
        """重傷時のCONロール。失敗で意識喪失。"""
        char = self.char_mgr.characters.get(target_id)
        if not char:
            return {"status": "error"}
        con = self.char_mgr.get_attribute(target_id, "CON") or 0
        roll = random.randint(1, 100)
        success = roll <= con
        if not success:
            states = char.setdefault("states", [])
            if "意識不明" not in states:
                states.append("意識不明")
        return {
            "status": "success",
            "roll": roll,
            "target": con,
            "passed": success,
            "unconscious": not success,
        }

    def process_first_aid(self, target_id, *, within_hour=True):
        """〈応急手当〉成功時: HP+1、意識回復。"""
        char = self.char_mgr.characters.get(target_id)
        if not char:
            return {"status": "error"}
        if not within_hour:
            return {"status": "error", "message": "応急手当は負傷後1時間以内"}
        result = self.char_mgr.recover_pool(
            target_id, "HP", 1, limit=self.char_mgr.get_stat_max(target_id, "HP"),
        )
        states = char.get("states", [])
        char["states"] = [s for s in states if s != "意識不明"]
        self.char_mgr.save_data()
        return {
            "status": "success",
            "recovered_hp": result["recovered"],
            "new_hp": result["new"],
            "revived": True,
        }

    def process_medicine(self, target_id, dice_engine=None):
        """〈医学〉成功時: HP+1D3（応急手当に加算）。"""
        char = self.char_mgr.characters.get(target_id)
        if not char:
            return {"status": "error"}
        heal = roll_dice_formula("1D3")
        hp_max = self.char_mgr.get_stat_max(target_id, "HP")
        result = self.char_mgr.recover_pool(target_id, "HP", heal, limit=hp_max)
        return {
            "status": "success",
            "recovered_hp": result["recovered"],
            "new_hp": result["new"],
            "rolled": heal,
        }

    def tick_dying_state(self, target_id):
        """瀕死状態: ラウンド終了時CONロール。失敗で死亡。"""
        char = self.char_mgr.characters.get(target_id)
        if not char:
            return {"status": "skip"}
        if self.char_mgr.get_stat_current(target_id, "HP") > 0:
            char.setdefault("flags", {})
            if isinstance(char.get("flags"), dict):
                char["flags"].pop("dying", None)
            return {"status": "recovered"}
        states = char.setdefault("states", [])
        if "瀕死" not in states and "重傷" not in states:
            return {"status": "skip"}
        con = self.char_mgr.get_attribute(target_id, "CON") or 0
        roll = random.randint(1, 100)
        if roll > con:
            states.append("死亡")
            return {"status": "dead", "roll": roll, "target": con}
        return {"status": "stable", "roll": roll, "target": con}

    def apply_push_failure_penalty(
        self,
        target_id,
        dice_engine=None,
        char_name="",
        *,
        include_hp=False,
    ):
        """
        プッシュロール失敗時の「恐ろしい結果」。
        - 正気度 1D3 喪失（狂気判定あり）
        - 状況悪化フラグ付与
        - include_hp=True のとき追加で HP 1D3
        """
        display_name = char_name or (
            (self.char_mgr.characters.get(target_id) or {}).get("profile", {}) or {}
        ).get("name", target_id)

        if dice_engine is not None and hasattr(dice_engine, "roll_dice_str"):
            san_loss = int(dice_engine.roll_dice_str("1d3") or 1)
        else:
            san_loss = random.randint(1, 3)

        san_result = self.apply_san_damage(
            target_id, san_loss, dice_engine=dice_engine, char_name=display_name,
        ) or {}

        self.flags["push_failure_dire_outcome"] = True
        self.flags["last_push_failure"] = {
            "target_id": target_id,
            "san_loss": san_loss,
        }

        log_parts = [
            f"【プッシュロール失敗・恐ろしい結果】{display_name} の正気度が {san_loss} 減少した。"
            "状況が急激に悪化した。",
        ]
        events = list(san_result.get("events") or [])
        hp_loss = 0

        if include_hp:
            if dice_engine is not None and hasattr(dice_engine, "roll_dice_str"):
                hp_loss = int(dice_engine.roll_dice_str("1d3") or 1)
            else:
                hp_loss = random.randint(1, 3)
            dmg = self.apply_physical_damage(target_id, hp_loss, dice_engine=dice_engine) or {}
            log_parts.append(f"【肉体的危険】耐久力が {hp_loss} 減少した（現在HP: {dmg.get('new_hp', '?')}）。")
            events.extend(dmg.get("events") or [])
            self.flags["last_push_failure"]["hp_loss"] = hp_loss

        kp_instruction = (
            "【プッシュロール失敗・恐ろしい結果・KP確定指示】"
            "探索者の再挑戦は惨敗に終わった。"
            "単なる失敗ではなく、取り返しのつかない悪化（怪我・発見の遅れ・追跡者の接近・証拠の損壊など）を容赦なく描写せよ。"
            "プレイヤーがリスクを負ったことが明確に伝わること。"
        )
        if san_result.get("madness_instruction"):
            kp_instruction = f"{kp_instruction}\n{san_result['madness_instruction']}"

        return {
            "status": "applied",
            "san_loss": san_loss,
            "hp_loss": hp_loss,
            "events": events,
            "log": "\n".join(log_parts),
            "madness_instruction": san_result.get("madness_instruction", ""),
            "kp_instruction": kp_instruction,
            "dire_outcome": True,
        }

    def apply_mp_cost(self, target_id, amount):
        """MP消費（枯渇分はHPへ）。"""
        return self.char_mgr.apply_mp_cost(target_id, amount)

    def apply_physical_damage(self, target_id, damage, *, dice_engine=None):
        """
        物理ダメージを適用し、第7版の「重傷・死亡」ルールに従ってイベントを発火する。
        - HP<=0 → 意識不明（戦闘キューからスキップ）
        - 一撃で最大HP以上、またはすでに瀕死でダメージを受けた場合 → 死亡
        """
        char = self.char_mgr.characters.get(target_id)
        if not char:
            return {"status": "error", "message": "キャラクターが見つかりません。"}

        attrs = char.setdefault("attributes", {})

        current_hp = self.char_mgr.get_stat_current(target_id, "HP")
        max_hp = self.char_mgr.get_stat_max(target_id, "HP")
        states = char.setdefault("states", [])
        was_dying = "瀕死" in states or "意識不明" in states or current_hp <= 0

        old_hp, new_hp = self.char_mgr.apply_pool_damage(target_id, "HP", damage)

        # ==========================================
        # ★ イベント（割り込み命令）の生成 ★
        # ==========================================
        system_events = [] # AIに叩き込む命令のリスト
        char_name = char["profile"]["name"]
        unconscious = False
        dead = False

        # 1. 即死判定（最大HP以上のダメージを一度に受けた場合）
        #    またはすでに瀕死／意識不明の状態で追加ダメージを受けた場合 → 死亡
        if damage >= max_hp or (was_dying and damage > 0):
            dead = True
            if "死亡" not in states:
                states.append("死亡")
            if "排除" not in states:
                states.append("排除")
            system_events.append({
                "type": "FATAL_WOUND",
                "priority": "HIGH",
                "instruction": (
                    f"【システム割り込み】{char_name}は"
                    + (
                        f"一度に最大HP以上のダメージ({damage}点)を受け、即死しました。"
                        if damage >= max_hp
                        else f"瀕死のところへ追加ダメージ({damage}点)を受け、死亡しました。"
                    )
                    + "KPは無残な死の情景を描写してください。"
                ),
            })
            self.char_mgr.save_data()
            return {
                "status": "success",
                "target": char_name,
                "old_hp": old_hp,
                "new_hp": new_hp,
                "damage": damage,
                "unconscious": False,
                "dead": True,
                "events": system_events,
            }

        has_major_wound = "重傷" in states

        # 2. HP=0: 重傷あり→瀕死、なければ意識不明のみ（クイックスタート）
        if new_hp == 0:
            unconscious = True
            if damage >= (max_hp / 2) or has_major_wound or "重傷" in states:
                if "瀕死" not in states:
                    states.append("瀕死")
                if "意識不明" not in states:
                    states.append("意識不明")
                system_events.append({
                    "type": "DEATH_DOOR",
                    "priority": "HIGH",
                    "instruction": (
                        f"【システム割り込み】{char_name}は瀕死状態です（意識不明・戦闘行動不能）。"
                        "各ラウンド終了時にCONロールが必要。〈応急手当〉成功で延命可能。"
                    ),
                })
            else:
                if "意識不明" not in states:
                    states.append("意識不明")
                system_events.append({
                    "type": "UNCONSCIOUS",
                    "priority": "HIGH",
                    "instruction": (
                        f"【システム割り込み】{char_name}はHP0で意識不明（戦闘行動不能）。"
                        "重傷でないため死亡には至らない。〈応急手当〉で1HP回復可能。"
                    ),
                })

        # 3. 重傷判定（一度に最大HPの半分以上）
        elif damage >= (max_hp / 2):
            if "重傷" not in states:
                states.append("重傷")
            con_result = self.resolve_major_wound_con_check(target_id, dice_engine)
            unconscious_note = ""
            if con_result.get("unconscious"):
                unconscious = True
                unconscious_note = " CONロール失敗により意識を失った。"
            system_events.append({
                "type": "MAJOR_WOUND",
                "priority": "HIGH",
                "instruction": (
                    f"【システム割り込み】{char_name}は重傷を負った。{unconscious_note}"
                    f"（CONロール: {con_result.get('roll')} vs {con_result.get('target')}）"
                ),
            })

        self.char_mgr.save_data()
        return {
            "status": "success",
            "target": char_name,
            "old_hp": old_hp,
            "new_hp": new_hp,
            "damage": damage,
            "unconscious": unconscious,
            "dead": dead,
            "events": system_events # 発火したイベントをメインループに返す
        }

    def apply_mp_damage(self, target_id, damage):
        """MPダメージ（超過分はHPへ転送）。"""
        return self.apply_mp_cost(target_id, damage)

    def take_damage(self, target_id, damage, *, pool_key="HP"):
        """物理/精神ダメージの統一エントリ（HP または MP）。"""
        if pool_key == "HP":
            return self.apply_physical_damage(target_id, damage)
        if pool_key == "MP":
            return self.apply_mp_damage(target_id, damage)
        if pool_key == "SAN":
            return self.apply_san_damage(target_id, damage)
        return {"status": "error", "message": f"未対応のプール: {pool_key}"}

    # ==========================================
    # 膠着（スタック）検知
    # ==========================================
    @staticmethod
    def _progress_signature(flags):
        """進行を表すフラグ署名（ON フラグ + 調査済み対象）。"""
        flags = flags or {}
        on_flags = sorted(
            key for key, value in flags.items()
            if key != "investigated_targets" and value is True
        )
        investigated = flags.get("investigated_targets") or []
        if isinstance(investigated, (list, tuple, set)):
            investigated_sig = tuple(sorted(str(x) for x in investigated))
        else:
            investigated_sig = (str(investigated),)
        return (tuple(on_flags), investigated_sig)

    @staticmethod
    def _repeat_key_from_action(pl_action=None, system_result=None):
        """同一調査・同一技能の繰り返し検知用キー。"""
        action = ""
        target = ""
        skill = ""
        if isinstance(system_result, dict):
            action = str(system_result.get("action_id") or "").lower()
            target = str(system_result.get("target") or "")
            if system_result.get("blocked") or system_result.get("roll_type") == "blocked":
                return ("blocked", action, target)
        if isinstance(pl_action, dict):
            action = action or str(pl_action.get("action") or "").lower()
            target = target or str(pl_action.get("target") or "")
            skill = str(pl_action.get("skill") or "")
        if action in ("wait", "none", "", "chat"):
            return ("chat",)
        if action == "push_roll":
            return ("push_roll", target, skill)
        if skill:
            return ("skill", skill, target)
        return ("action", action, target)

    def reset_stagnation_tracker(self, location_id=None, flags=None):
        """膠着カウンタをリセットする。"""
        self.stagnation_tracker = {
            "location": location_id,
            "progress_signature": self._progress_signature(flags) if flags is not None else None,
            "repeat_key": None,
            "streak": 0,
            "intervened_at_streak": 0,
            "last_reason": "",
        }
        return self.stagnation_tracker

    def detect_stagnation(
        self,
        all_events_log=None,
        *,
        location_id,
        flags,
        max_stagnation_turns=6,
        last_pl_action=None,
        last_system_result=None,
        chat_only=False,
        made_progress=None,
    ):
        """
        タイムライン状況から膠着を検知し、ストリークを更新する。

        条件（連続 max_stagnation_turns ターン、既定 6）:
          - 位置が変わっていない
          - 新たなフラグが ON になっていない
          - 同一オブジェクト／同一技能の失敗、または会話のみで未進行
        """
        max_turns = max(1, int(max_stagnation_turns or 6))
        tracker = self.stagnation_tracker
        progress_sig = self._progress_signature(flags)
        location_id = str(location_id or "")

        location_changed = (
            tracker.get("location") is not None
            and tracker.get("location") != location_id
        )
        flags_progressed = (
            tracker.get("progress_signature") is not None
            and tracker.get("progress_signature") != progress_sig
        )

        if made_progress is None and isinstance(last_system_result, dict):
            made_progress = bool(
                last_system_result.get("location_changed")
                or last_system_result.get("stagnation_progress")
            )

        if location_changed or flags_progressed or made_progress:
            self.reset_stagnation_tracker(location_id, flags)
            tracker = self.stagnation_tracker
            return {
                "is_stagnant": False,
                "streak": 0,
                "max_stagnation_turns": max_turns,
                "reason": "progress_or_moved",
                "needs_intervention": False,
                "repeat_key": None,
                "location_id": location_id,
            }

        if tracker.get("location") is None:
            tracker["location"] = location_id
            tracker["progress_signature"] = progress_sig

        stagnating = False
        reason = ""
        repeat_key = self._repeat_key_from_action(last_pl_action, last_system_result)

        if chat_only or repeat_key == ("chat",):
            stagnating = True
            reason = "chat_only"
            repeat_key = ("chat",)
        elif isinstance(last_system_result, dict):
            blocked = bool(
                last_system_result.get("blocked")
                or last_system_result.get("roll_type") == "blocked"
            )
            status = last_system_result.get("status", 0)
            is_fail = blocked or (isinstance(status, int) and status <= 1)
            log = str(last_system_result.get("log") or "")
            empty_find = "特になにも見つからなかった" in log
            if is_fail or empty_find:
                prev_key = tracker.get("repeat_key")
                if prev_key in (None, repeat_key):
                    stagnating = True
                    reason = "repeat_fail" if prev_key == repeat_key else "fail_start"
                else:
                    # 別対象・別技能へ切替 → ストリークを1から再開
                    tracker["repeat_key"] = repeat_key
                    tracker["streak"] = 1
                    tracker["last_reason"] = "signature_switch"
                    tracker["intervened_at_streak"] = 0
                    return {
                        "is_stagnant": False,
                        "streak": 1,
                        "max_stagnation_turns": max_turns,
                        "reason": "signature_switch",
                        "needs_intervention": False,
                        "repeat_key": repeat_key,
                        "location_id": location_id,
                    }

        # ログ末尾の会話往復のみ（システム結果無し）も膠着寄与
        if not stagnating and all_events_log is not None and last_system_result is None:
            recent = list(all_events_log or [])[-6:]
            has_system = any(
                str((e or {}).get("text") or "").startswith("システム:")
                for e in recent
            )
            has_pl = any(
                "(PL):" in str((e or {}).get("text") or "")
                or "(PC):" in str((e or {}).get("text") or "")
                for e in recent
            )
            if has_pl and not has_system:
                stagnating = True
                reason = "conversation_loop"
                repeat_key = ("chat",)

        if stagnating:
            tracker["location"] = location_id
            tracker["progress_signature"] = progress_sig
            tracker["repeat_key"] = repeat_key
            tracker["streak"] = int(tracker.get("streak") or 0) + 1
            tracker["last_reason"] = reason
        else:
            # 判定対象外のターンではストリーク維持（位置・フラグのみ更新）
            tracker["location"] = location_id
            tracker["progress_signature"] = progress_sig

        streak = int(tracker.get("streak") or 0)
        is_stagnant = streak >= max_turns
        intervened_at = int(tracker.get("intervened_at_streak") or 0)
        needs_intervention = is_stagnant and streak > intervened_at

        return {
            "is_stagnant": is_stagnant,
            "streak": streak,
            "max_stagnation_turns": max_turns,
            "reason": tracker.get("last_reason") or reason,
            "needs_intervention": needs_intervention,
            "repeat_key": tracker.get("repeat_key"),
            "location_id": location_id,
        }

    def mark_stagnation_intervened(self):
        """今回のストリークに対する介入を実行済みにする。"""
        streak = int(self.stagnation_tracker.get("streak") or 0)
        self.stagnation_tracker["intervened_at_streak"] = streak
        return streak

    def export_to_dict(self):
        """現在のゲーム状態を辞書で返す"""
        return {
            "current_scene_id": self.current_scene_id,
            "turn_count": self.turn_count,
            "flags": self.flags,
            "in_combat": self.in_combat,
            "round_number": self.round_number,
            "turn_order": self.turn_order,
            "current_turn_index": self.current_turn_index,
            "stagnation_tracker": dict(self.stagnation_tracker),
        }

    def load_from_dict(self, data):
        """保存データからゲーム状態を復元する"""
        self.current_scene_id = data.get("current_scene_id", "scene_001")
        self.turn_count = data.get("turn_count", 0)
        self.flags = data.get("flags", {})
        self.in_combat = data.get("in_combat", False)
        self.round_number = data.get("round_number", 0)
        self.turn_order = data.get("turn_order", [])
        self.current_turn_index = data.get("current_turn_index", 0)
        tracker = data.get("stagnation_tracker")
        if isinstance(tracker, dict):
            self.stagnation_tracker = {
                "location": None,
                "progress_signature": None,
                "repeat_key": None,
                "streak": 0,
                "intervened_at_streak": 0,
                "last_reason": "",
            }
            self.stagnation_tracker.update(tracker)
