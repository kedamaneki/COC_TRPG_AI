"""
CoC 第7版準拠のダイスエンジン。
成功度は SuccessLevel（0–5）で表現し、難易度（regular/hard/extreme）を目標値に反映する。
"""
from __future__ import annotations

import random
import re
from enum import IntEnum
from typing import Any, Dict, Optional, Tuple, Union

from CoCRules import (
    compare_success_levels,
    resolve_firearm_defense_outcome,
    resolve_melee_defense_outcome,
)


class SuccessLevel(IntEnum):
    """第7版向け成功度。シナリオの success_level 比較はこの値を使う。"""

    FUMBLE = 0
    FAILURE = 1
    REGULAR_SUCCESS = 2
    HARD_SUCCESS = 3
    EXTREME_SUCCESS = 4
    CRITICAL = 5


SUCCESS_LEVEL_LABELS = {
    SuccessLevel.FUMBLE: "致命的失敗 (ファンブル)",
    SuccessLevel.FAILURE: "失敗",
    SuccessLevel.REGULAR_SUCCESS: "レギュラー成功",
    SuccessLevel.HARD_SUCCESS: "ハード成功",
    SuccessLevel.EXTREME_SUCCESS: "イクストリーム成功",
    SuccessLevel.CRITICAL: "決定的成功 (クリティカル)",
}

DIFFICULTY_ALIASES = {
    "regular": "regular",
    "normal": "regular",
    "通常": "regular",
    "reg": "regular",
    "hard": "hard",
    "困難": "hard",
    "harder": "hard",
    "extreme": "extreme",
    "極限": "extreme",
    "イクストリーム": "extreme",
    "ext": "extreme",
}

DIFFICULTY_MIN_LEVEL = {
    "regular": SuccessLevel.REGULAR_SUCCESS,
    "hard": SuccessLevel.HARD_SUCCESS,
    "extreme": SuccessLevel.EXTREME_SUCCESS,
}


def normalize_difficulty(value: Optional[str], default: str = "regular") -> str:
    """シナリオJSONの難易度表記を regular/hard/extreme に正規化する。"""
    key = str(value or default).strip().lower()
    # 日本語はそのまま照合するため lower していない別名も見る
    raw = str(value or default).strip()
    if raw in DIFFICULTY_ALIASES:
        return DIFFICULTY_ALIASES[raw]
    if key in DIFFICULTY_ALIASES:
        return DIFFICULTY_ALIASES[key]
    return default


def difficulty_target_value(skill_value: int, difficulty: str = "regular") -> int:
    """難易度に応じた目標値（端数切り捨て）。"""
    skill_value = max(0, int(skill_value or 0))
    difficulty = normalize_difficulty(difficulty)
    if difficulty == "extreme":
        return skill_value // 5
    if difficulty == "hard":
        return skill_value // 2
    return skill_value


def is_success_level(level: Union[int, SuccessLevel]) -> bool:
    return int(level) >= int(SuccessLevel.REGULAR_SUCCESS)


def is_failure_level(level: Union[int, SuccessLevel]) -> bool:
    return int(level) <= int(SuccessLevel.FAILURE)


def min_level_for_difficulty(difficulty: str = "regular") -> SuccessLevel:
    return DIFFICULTY_MIN_LEVEL[normalize_difficulty(difficulty)]


def luck_points_needed(roll: int, target_value: int) -> int:
    """
    目標成功出目に届くために必要な幸運ポイント（不足分）。
    出目が既に目標以下なら 0（消費不要）。
    """
    return max(0, int(roll) - int(target_value))


class DiceEngine:
    def __init__(self):
        pass

    # ==========================================
    # 第7版 B/Pダイス対応のロール処理
    # ==========================================
    def roll_1d100_with_bp(self, bonus_dice=0, penalty_dice=0):
        """
        10の位を複数個振り、B/Pルールに従って1d100の結果を返す
        """
        net_bonus = bonus_dice - penalty_dice
        units_die = random.randint(0, 9)
        tens_dice_count = 1 + abs(net_bonus)
        tens_rolls = [random.randint(0, 9) for _ in range(tens_dice_count)]

        if net_bonus > 0:
            chosen_tens = min(tens_rolls)
        elif net_bonus < 0:
            chosen_tens = max(tens_rolls)
        else:
            chosen_tens = tens_rolls[0]

        final_result = chosen_tens * 10 + units_die
        if final_result == 0:
            final_result = 100

        return final_result, tens_rolls, units_die, net_bonus

    # ==========================================
    # 第7版 ファンブル / 成功度 / 難易度
    # ==========================================
    def is_fumble(self, skill_value: int, roll_result: int) -> bool:
        """
        7版ファンブル:
        - 技能値 < 50: 出目 96–100
        - 技能値 >= 50: 出目 100 のみ
        """
        skill_value = int(skill_value or 0)
        roll_result = int(roll_result or 0)
        if skill_value < 50:
            return 96 <= roll_result <= 100
        return roll_result == 100

    def achieved_success_quality(self, skill_value: int, roll_result: int) -> SuccessLevel:
        """
        出目が技能のフル閾値に対して到達した最大成功度（難易度未適用の品質）。
        出目1はクリティカル。ファンブル/失敗はここでは扱わない。
        """
        skill_value = max(0, int(skill_value or 0))
        roll_result = int(roll_result or 0)
        if roll_result == 1:
            return SuccessLevel.CRITICAL
        if roll_result <= skill_value // 5:
            return SuccessLevel.EXTREME_SUCCESS
        if roll_result <= skill_value // 2:
            return SuccessLevel.HARD_SUCCESS
        if roll_result <= skill_value:
            return SuccessLevel.REGULAR_SUCCESS
        return SuccessLevel.FAILURE

    def evaluate_roll(
        self,
        skill_value: int,
        roll_result: int,
        required_difficulty: str = "regular",
    ) -> Dict[str, Any]:
        """
        出目を難易度付きで評価し、SuccessLevel と表示文言を返す。

        判定順:
        1. 出目1 → CRITICAL
        2. ファンブル条件 → FUMBLE
        3. 出目 > 難易度目標値 → FAILURE
        4. それ以外は到達した成功品質が required_difficulty 以上ならその品質、未満なら FAILURE
        """
        skill_value = max(0, int(skill_value or 0))
        roll_result = int(roll_result or 0)
        difficulty = normalize_difficulty(required_difficulty)
        target = difficulty_target_value(skill_value, difficulty)
        required_min = min_level_for_difficulty(difficulty)

        if roll_result == 1:
            level = SuccessLevel.CRITICAL
        elif self.is_fumble(skill_value, roll_result):
            level = SuccessLevel.FUMBLE
        elif roll_result > target:
            level = SuccessLevel.FAILURE
        else:
            quality = self.achieved_success_quality(skill_value, roll_result)
            if int(quality) >= int(required_min):
                level = quality
            else:
                level = SuccessLevel.FAILURE

        result_text = SUCCESS_LEVEL_LABELS[level]
        return {
            "success_level": int(level),
            "level": level,
            "result": result_text,
            "required_difficulty": difficulty,
            "target_value": target,
            "is_fumble": level == SuccessLevel.FUMBLE,
            "is_failure": is_failure_level(level),
            "is_success": is_success_level(level),
        }

    def evaluate_7th_edition_custom(self, skill_value, roll_result, required_difficulty="regular"):
        """後方互換: 評価文言のみ返す。"""
        return self.evaluate_roll(skill_value, roll_result, required_difficulty)["result"]

    def _result_to_success_level(self, result_text, skill_value=None, roll_result=None, required_difficulty="regular"):
        """文言からの逆引き（可能な場合は数値評価を優先）。"""
        if skill_value is not None and roll_result is not None:
            return self.evaluate_roll(skill_value, roll_result, required_difficulty)["success_level"]
        text = str(result_text or "")
        for level, label in SUCCESS_LEVEL_LABELS.items():
            if label == text:
                return int(level)
        if "ファンブル" in text or "致命的" in text:
            return int(SuccessLevel.FUMBLE)
        if "クリティカル" in text or "決定的" in text:
            return int(SuccessLevel.CRITICAL)
        if "イクストリーム" in text:
            return int(SuccessLevel.EXTREME_SUCCESS)
        if "ハード" in text:
            return int(SuccessLevel.HARD_SUCCESS)
        if "レギュラー" in text or "幸運消費" in text or "幸運成功" in text:
            return int(SuccessLevel.REGULAR_SUCCESS)
        return int(SuccessLevel.FAILURE)

    def _build_skill_roll_result(
        self,
        char_name,
        skill_name,
        skill_value,
        modifier=0,
        bonus_dice=0,
        penalty_dice=0,
        is_push=False,
        required_difficulty="regular",
    ):
        effective_skill = skill_value + modifier
        difficulty = normalize_difficulty(required_difficulty)
        roll, tens_rolls, units_die, net_bonus = self.roll_1d100_with_bp(bonus_dice, penalty_dice)
        evaluated = self.evaluate_roll(effective_skill, roll, difficulty)
        result_text = evaluated["result"]
        success_level = evaluated["success_level"]
        target_value = evaluated["target_value"]

        is_fumble = evaluated["is_fumble"]
        is_failure = evaluated["is_failure"]
        # 失敗・ファンブルとも幸運消費の対象（目標成功度の出目閾値との差分）
        failure_margin = luck_points_needed(roll, target_value) if is_failure else 0
        is_push_fail = is_push and is_failure

        bp_log = ""
        if net_bonus > 0:
            bp_log = f" [ボーナス{net_bonus}個: 10の位{tuple(tens_rolls)} -> 採用{min(tens_rolls)}]"
        elif net_bonus < 0:
            bp_log = f" [ペナルティ{abs(net_bonus)}個: 10の位{tuple(tens_rolls)} -> 採用{max(tens_rolls)}]"

        skill_display = f"{skill_value}"
        if modifier > 0:
            skill_display += f"+{modifier}={effective_skill}"
        elif modifier < 0:
            skill_display += f"{modifier}={effective_skill}"

        diff_note = ""
        if difficulty != "regular":
            diff_note = f" 難易度:{difficulty}(目標<={target_value})"

        roll_label = "プッシュロール" if is_push else "技能"
        log_text = (
            f"CC(1d100<={skill_display}){diff_note}{bp_log} ＞ 出目:{roll} ＞ {result_text}"
        )
        if is_push_fail:
            log_text += " ＞ 【プッシュロール失敗】"

        return {
            "status": "success",
            "roll": roll,
            "result": result_text,
            "log": f"{char_name} : 【{roll_label}:{skill_name}】{log_text}",
            "effective_skill": effective_skill,
            "failure_margin": failure_margin,
            "is_fumble": is_fumble,
            "is_failure": is_failure,
            "is_push_fail": is_push_fail,
            "success_level": success_level,
            "required_difficulty": difficulty,
            "target_value": target_value,
        }

    def execute_skill_roll(
        self,
        char_name,
        skill_name,
        skill_value,
        modifier=0,
        bonus_dice=0,
        penalty_dice=0,
        required_difficulty="regular",
    ):
        if skill_value <= 0:
            return {
                "status": "error",
                "message": f"{char_name} は {skill_name} を持っていません（または0です）。",
            }

        return self._build_skill_roll_result(
            char_name,
            skill_name,
            skill_value,
            modifier,
            bonus_dice,
            penalty_dice,
            is_push=False,
            required_difficulty=required_difficulty,
        )

    def execute_push_roll(
        self,
        char_name,
        skill_name,
        skill_value,
        modifier=0,
        bonus_dice=0,
        penalty_dice=0,
        required_difficulty="regular",
    ):
        """プッシュロール。失敗時は is_push_fail=True。"""
        if skill_value <= 0:
            return {
                "status": "error",
                "message": f"{char_name} は {skill_name} をプッシュできません（技能0）。",
            }

        return self._build_skill_roll_result(
            char_name,
            skill_name,
            skill_value,
            modifier,
            bonus_dice,
            penalty_dice,
            is_push=True,
            required_difficulty=required_difficulty,
        )

    def calculate_luck_points_needed(
        self,
        roll,
        skill_value,
        required_difficulty="regular",
        modifier=0,
    ):
        """技能値・難易度から、失敗を目標成功度まで届けるのに必要な幸運ポイントを算出する。"""
        effective = int(skill_value or 0) + int(modifier or 0)
        target = difficulty_target_value(effective, required_difficulty)
        return luck_points_needed(roll, target)

    def _roll_to_success_level(self, value, roll, required_difficulty="regular"):
        evaluated = self.evaluate_roll(value, roll, required_difficulty)
        return evaluated["success_level"], evaluated["result"]

    def execute_opposed_str_roll(
        self,
        char_name,
        char_str,
        opponent_name,
        opponent_str,
        penalty_dice=0,
        bonus_dice=0,
        required_difficulty="regular",
    ):
        """CoC7版 STR 対抗判定。成功段階の高い方が勝利（同格は防御側＝対象の勝ち）。"""
        difficulty = normalize_difficulty(required_difficulty)
        pc_roll, pc_tens, _, pc_bp = self.roll_1d100_with_bp(bonus_dice, penalty_dice)
        opp_roll, opp_tens, _, _ = self.roll_1d100_with_bp(0, 0)

        # 対抗では「品質」比較のため双方はフル技能閾値（regular）で段階を出し、
        # その後 PC 側が required_difficulty を満たすかも別途見る。
        pc_level, pc_result = self._roll_to_success_level(char_str, pc_roll, "regular")
        opp_level, opp_result = self._roll_to_success_level(opponent_str, opp_roll, "regular")

        if pc_level > opp_level:
            winner = "pc"
        elif opp_level > pc_level:
            winner = "opponent"
        else:
            winner = "opponent"

        # 難易度ハード以上が要求される対抗では、PCが勝利しても要求段階未満なら敗北扱い
        if winner == "pc" and pc_level < int(min_level_for_difficulty(difficulty)):
            winner = "opponent"
            pc_result = f"{pc_result}（要求難易度 {difficulty} 未達）"

        bp_note = ""
        if pc_bp < 0:
            bp_note = f" [ペナルティ{abs(pc_bp)}個: 10の位{tuple(pc_tens)}]"

        log_text = (
            f"【STR対抗】{char_name}(STR{char_str}) vs {opponent_name}(STR{opponent_str})"
            f"{bp_note} 難易度:{difficulty}\n"
            f"  PL: 1d100={pc_roll} → {pc_result}\n"
            f"  対象: 1d100={opp_roll} → {opp_result}\n"
            f"  結果: {'PLの勝利' if winner == 'pc' else 'PLの敗北'}"
        )

        return {
            "status": "success",
            "success_level": pc_level if winner == "pc" else int(SuccessLevel.FAILURE),
            "pc_roll": pc_roll,
            "opp_roll": opp_roll,
            "pc_level": pc_level,
            "opp_level": opp_level,
            "winner": winner,
            "log": log_text,
            "required_difficulty": difficulty,
        }

    def execute_luck_roll(self, char_name, luck_value):
        """〈幸運〉ロール: 1d100 <= 現在幸運で成功。"""
        luck_value = int(luck_value or 0)
        roll, tens_rolls, units_die, net_bonus = self.roll_1d100_with_bp(0, 0)
        success = roll <= luck_value
        result_text = "幸運成功" if success else "幸運失敗"
        log_text = (
            f"{char_name} : 【幸運】CC(1d100<={luck_value}) ＞ 出目:{roll} ＞ {result_text}"
        )
        return {
            "status": "success",
            "roll": roll,
            "success": success,
            "result": result_text,
            "log": log_text,
            "success_level": (
                int(SuccessLevel.REGULAR_SUCCESS) if success else int(SuccessLevel.FAILURE)
            ),
        }

    def execute_int_roll(self, char_name, int_value, required_difficulty="regular"):
        """知能（INT）ロール。一時的狂気判定などで使用。"""
        return self.execute_skill_roll(
            char_name,
            "INT",
            int(int_value or 0),
            required_difficulty=required_difficulty,
        )

    def execute_opposed_skill_roll(
        self,
        attacker_name,
        attacker_skill,
        attacker_value,
        defender_name,
        defender_skill,
        defender_value,
        *,
        attacker_bonus=0,
        attacker_penalty=0,
        defender_bonus=0,
        defender_penalty=0,
        required_difficulty="regular",
    ):
        """任意技能の対抗ロール。"""
        difficulty = normalize_difficulty(required_difficulty)
        a_roll, _, _, _ = self.roll_1d100_with_bp(attacker_bonus, attacker_penalty)
        d_roll, _, _, _ = self.roll_1d100_with_bp(defender_bonus, defender_penalty)
        a_level, a_result = self._roll_to_success_level(attacker_value, a_roll, "regular")
        d_level, d_result = self._roll_to_success_level(defender_value, d_roll, "regular")
        winner = compare_success_levels(a_level, d_level)
        if winner == "attacker" and a_level < int(min_level_for_difficulty(difficulty)):
            winner = "defender"
            a_result = f"{a_result}（要求難易度 {difficulty} 未達）"

        log_text = (
            f"【対抗】{attacker_name}〈{attacker_skill}〉({attacker_value}) vs "
            f"{defender_name}〈{defender_skill}〉({defender_value}) 難易度:{difficulty}\n"
            f"  攻: 1d100={a_roll} → {a_result}\n"
            f"  守: 1d100={d_roll} → {d_result}\n"
            f"  結果: {'攻撃側勝利' if winner == 'attacker' else '防御側勝利'}"
        )
        return {
            "status": "success",
            "winner": winner,
            "attacker_level": a_level,
            "defender_level": d_level,
            "success_level": (
                a_level if winner == "attacker" else int(SuccessLevel.FAILURE)
            ),
            "log": log_text,
            "required_difficulty": difficulty,
        }

    def execute_melee_opposed_roll(
        self,
        attacker_name,
        attacker_skill,
        attacker_value,
        defender_name,
        defender_skill,
        defender_value,
        *,
        defense_mode="dodge",
        attacker_bonus=0,
        attacker_penalty=0,
        defender_bonus=0,
        defender_penalty=0,
    ):
        """
        近接戦闘の攻防対抗ロール（回避／応戦）。
        成功度比較は resolve_melee_defense_outcome に従う。
        """
        mode = str(defense_mode or "dodge").strip().lower()
        if mode in ("fight_back", "fighting_back", "応戦", "fightback"):
            mode = "fight_back"
            mode_label = "応戦"
        else:
            mode = "dodge"
            mode_label = "回避"

        a_roll, _, _, _ = self.roll_1d100_with_bp(attacker_bonus, attacker_penalty)
        d_roll, _, _, _ = self.roll_1d100_with_bp(defender_bonus, defender_penalty)
        a_level, a_result = self._roll_to_success_level(attacker_value, a_roll, "regular")
        d_level, d_result = self._roll_to_success_level(defender_value, d_roll, "regular")
        outcome = resolve_melee_defense_outcome(a_level, d_level, mode)

        outcome_labels = {
            "miss": "双方失敗（未命中）",
            "dodged": "回避成功",
            "counter": "応戦成功（カウンター）",
            "hit_attacker": "攻撃命中",
        }
        log_text = (
            f"【近接対抗・{mode_label}】{attacker_name}〈{attacker_skill}〉({attacker_value}) vs "
            f"{defender_name}〈{defender_skill}〉({defender_value})\n"
            f"  攻: 1d100={a_roll} → {a_result}\n"
            f"  守: 1d100={d_roll} → {d_result}\n"
            f"  判定: {outcome_labels.get(outcome, outcome)}"
        )
        return {
            "status": "success",
            "outcome": outcome,
            "defense_mode": mode,
            "attacker_level": a_level,
            "defender_level": d_level,
            "attacker_roll": a_roll,
            "defender_roll": d_roll,
            "log": log_text,
        }

    def execute_firearm_attack_roll(
        self,
        attacker_name,
        attacker_skill,
        attacker_value,
        defender_name,
        defender_skill,
        defender_value,
        *,
        defense_mode="dodge",
        attacker_bonus=0,
        attacker_penalty=0,
        defender_bonus=0,
        defender_penalty=0,
    ):
        """
        銃器射撃の解決ロール（回避対抗または甘受）。
        【応戦】は不可。outcome が not_allowed のときはロール未実行。
        """
        mode_raw = str(defense_mode or "dodge").strip().lower()
        if mode_raw in ("fight_back", "fighting_back", "応戦", "fightback", "counter", "反撃"):
            return {
                "status": "error",
                "outcome": "not_allowed",
                "defense_mode": "fight_back",
                "attacker_level": 0,
                "defender_level": 0,
                "attacker_roll": 0,
                "defender_roll": 0,
                "log": "【射撃】銃撃に対して【応戦】は選択できません。【回避】か【甘んじて受ける】を選んでください。",
            }

        if mode_raw in (
            "accept", "take", "take_it", "none", "no_dodge",
            "甘受", "甘んじて", "甘んじて受ける", "受け入れる", "受け止める",
        ):
            mode = "accept"
            mode_label = "甘んじて受ける"
        else:
            mode = "dodge"
            mode_label = "回避"

        a_roll, _, _, _ = self.roll_1d100_with_bp(attacker_bonus, attacker_penalty)
        a_level, a_result = self._roll_to_success_level(attacker_value, a_roll, "regular")

        if mode == "accept":
            outcome = resolve_firearm_defense_outcome(a_level, 0, "accept")
            log_text = (
                f"【射撃・{mode_label}】{attacker_name}〈{attacker_skill}〉({attacker_value})"
                f"（ボーナス{attacker_bonus}/ペナルティ{attacker_penalty}）\n"
                f"  射撃: 1d100={a_roll} → {a_result}\n"
                f"  判定: {'射撃命中' if outcome == 'hit_attacker' else '射撃失敗'}"
            )
            return {
                "status": "success",
                "outcome": outcome,
                "defense_mode": mode,
                "attacker_level": a_level,
                "defender_level": 0,
                "attacker_roll": a_roll,
                "defender_roll": 0,
                "log": log_text,
            }

        d_roll, _, _, _ = self.roll_1d100_with_bp(defender_bonus, defender_penalty)
        d_level, d_result = self._roll_to_success_level(defender_value, d_roll, "regular")
        outcome = resolve_firearm_defense_outcome(a_level, d_level, "dodge")
        outcome_labels = {
            "miss": "双方失敗（未命中）",
            "dodged": "回避成功（射撃ミス）",
            "hit_attacker": "射撃命中",
        }
        log_text = (
            f"【射撃対抗・{mode_label}】{attacker_name}〈{attacker_skill}〉({attacker_value}) vs "
            f"{defender_name}〈{defender_skill}〉({defender_value})"
            f"（射撃ボーナス{attacker_bonus}）\n"
            f"  射: 1d100={a_roll} → {a_result}\n"
            f"  守: 1d100={d_roll} → {d_result}\n"
            f"  判定: {outcome_labels.get(outcome, outcome)}"
        )
        return {
            "status": "success",
            "outcome": outcome,
            "defense_mode": mode,
            "attacker_level": a_level,
            "defender_level": d_level,
            "attacker_roll": a_roll,
            "defender_roll": d_roll,
            "log": log_text,
        }

    def roll_dice_str(self, dice_str):
        """'1d3'や'1D6'、'0'などの文字列を受け取り、ダイスを振って整数を返す"""
        dice_str = str(dice_str).lower().strip()

        match = re.match(r"(\d+)d(\d+)", dice_str)
        if match:
            count = int(match.group(1))
            faces = int(match.group(2))
            total = sum(random.randint(1, faces) for _ in range(count))
            return total

        try:
            return int(dice_str)
        except ValueError:
            return 0
