"""
CoC 7版クイックスタート準拠のルール補助モジュール。
既存マネージャーから呼び出される共通ロジックを集約する。
"""
from __future__ import annotations

import random
from typing import Any, Dict, List, Optional, Tuple

# STR+SIZ → ダメージ・ボーナス / ビルド（クイックスタート p.9）
_DB_BLD_TABLE: List[Tuple[int, int, int, str]] = [
    (2, 64, -2, -2),
    (65, 84, -1, -1),
    (85, 124, 0, 0),
    (125, 164, 1, 1),   # +1D4
    (165, 204, 2, 2),   # +1D6
    (205, 10_000, 3, 3),
]


def compute_damage_bonus_and_build(str_val: int, siz_val: int) -> Dict[str, Any]:
    """STR+SIZ からダメージ・ボーナスとビルドを算出する。"""
    total = int(str_val or 0) + int(siz_val or 0)
    for low, high, db_die, build in _DB_BLD_TABLE:
        if low <= total <= high:
            if db_die <= 0:
                db_text = str(db_die)
            elif db_die == 1:
                db_text = "+1D4"
            elif db_die == 2:
                db_text = "+1D6"
            else:
                db_text = f"+{db_die}D4"
            return {"DB": db_text, "BLD": build, "STR_SIZ_sum": total}
    return {"DB": "+0", "BLD": 0, "STR_SIZ_sum": total}


def roll_luck_quickstart() -> int:
    """幸運 = 3D6 × 5（クイックスタート）。"""
    return sum(random.randint(1, 6) for _ in range(3)) * 5


def roll_dice_formula(formula: str) -> int:
    """'1D3', '2D6+1' 等を解釈してロール。"""
    import re

    text = str(formula or "").strip().upper()
    if not text:
        return 0
    total = 0
    for part in re.findall(r"([+-]?\d*D\d+|\d+)", text):
        part = part.strip()
        sign = 1
        if part.startswith("+"):
            part = part[1:]
        elif part.startswith("-"):
            sign = -1
            part = part[1:]
        if "D" in part:
            count_s, faces_s = part.split("D", 1)
            count = int(count_s) if count_s else 1
            faces = int(faces_s)
            total += sign * sum(random.randint(1, faces) for _ in range(count))
        else:
            total += sign * int(part)
    return total


def compute_dodge_base(dex: int) -> int:
    """〈回避〉の基礎値 = DEX÷2（端数切り捨て）。クイックスタート p.12。"""
    return max(0, int(dex or 0) // 2)


def compare_success_levels(attacker_level: int, defender_level: int) -> str:
    """対抗ロールの勝敗。同格は防御側勝利。"""
    if attacker_level > defender_level:
        return "attacker"
    return "defender"


def resolve_melee_defense_outcome(
    attacker_level: int,
    defender_level: int,
    defense_mode: str,
) -> str:
    """
    近接攻撃に対する回避／応戦の勝敗（CoC7 クイックスタート）。

    Returns:
        "miss"         … 双方とも失敗以下（どちらも未命中）
        "dodged"       … 回避成功（ダメージなし）
        "counter"      … 応戦成功（防御側が攻撃側にダメージ）
        "hit_attacker" … 攻撃命中（攻撃側が防御側にダメージ）
    """
    mode = str(defense_mode or "dodge").strip().lower()
    if mode in ("fight_back", "fighting_back", "応戦", "fightback"):
        mode = "fight_back"
    else:
        mode = "dodge"

    a = int(attacker_level or 0)
    d = int(defender_level or 0)

    # 双方失敗（成功度1以下）→ どちらの攻撃も当たらない
    if a <= 1 and d <= 1:
        return "miss"

    if mode == "dodge":
        # 防御側成功度 >= 攻撃側 → 回避成功
        if d >= a:
            return "dodged"
        return "hit_attacker"

    # 応戦: 防御側成功度 > 攻撃側 → カウンター、それ以外（同値含む）は攻撃命中
    if d > a:
        return "counter"
    return "hit_attacker"


def is_firearm_fight_back_allowed() -> bool:
    """銃器射撃に対する【応戦】は不可（クイックスタート）。"""
    return False


def resolve_firearm_defense_outcome(
    attacker_level: int,
    defender_level: int,
    defense_mode: str,
) -> str:
    """
    銃器射撃に対する回避／甘受の勝敗（CoC7 クイックスタート）。

    Returns:
        "not_allowed"  … 【応戦】が選択された（ガード）
        "miss"         … 射撃失敗（甘受時の失敗、または双方失敗）
        "dodged"       … 回避成功（射撃ミス）
        "hit_attacker" … 射撃命中
    """
    mode = str(defense_mode or "dodge").strip().lower()
    if mode in ("fight_back", "fighting_back", "応戦", "fightback", "counter", "反撃"):
        return "not_allowed"
    if mode in (
        "accept", "take", "take_it", "none", "no_dodge",
        "甘受", "甘んじて", "甘んじて受ける", "受け入れる", "受け止める",
    ):
        mode = "accept"
    else:
        mode = "dodge"

    a = int(attacker_level or 0)
    d = int(defender_level or 0)

    if mode == "accept":
        # 対抗なし。射撃側がレギュラー成功以上なら命中
        if a >= 2:
            return "hit_attacker"
        return "miss"

    # 回避対抗: 射撃側 ＞ 回避側 → 命中、それ以外（同値含む）は回避成功
    if a <= 1 and d <= 1:
        return "miss"
    if a > d:
        return "hit_attacker"
    return "dodged"


def max_dice_formula_value(formula: str) -> int:
    """ダイス式の理論最大値（例: 1D10→10, 2D6+1→13）。"""
    import re

    text = str(formula or "").strip().upper()
    if not text:
        return 0
    total = 0
    for part in re.findall(r"([+-]?\d*D\d+|\d+)", text):
        part = part.strip()
        sign = 1
        if part.startswith("+"):
            part = part[1:]
        elif part.startswith("-"):
            sign = -1
            part = part[1:]
        if "D" in part:
            count_s, faces_s = part.split("D", 1)
            count = int(count_s) if count_s else 1
            faces = int(faces_s)
            total += sign * (count * faces)
        else:
            total += sign * int(part)
    return max(0, total)


def compute_firearm_damage(
    weapon_dice: str,
    *,
    is_impale: bool = False,
) -> Tuple[int, str]:
    """
    銃器ダメージ算出。
    通常命中: 武器ダイスのみ（DB 非適用）。
    貫通（インペール）: 武器最大ダメージ＋通常ダイスロール（例: 1D10 → 10+1D10）。
    """
    dice_str = str(weapon_dice or "1D10").strip() or "1D10"
    if is_impale:
        max_base = max_dice_formula_value(dice_str)
        extra = roll_dice_formula(dice_str)
        total = max(0, max_base + extra)
        detail = f"貫通(インペール) {dice_str}最大{max_base}+{dice_str}→{extra} = {total}"
        return total, detail
    base = roll_dice_formula(dice_str)
    return max(0, base), f"{dice_str}→{base}"


def compute_melee_damage(
    weapon_dice: str,
    *,
    damage_bonus_dice: str = "",
    is_extreme: bool = False,
    is_blunt: bool = False,
) -> Tuple[int, str]:
    """
    近接ダメージ算出（簡易版）。
    イクストリーム成功時: 鈍器は最大+DB最大、貫通は最大+DB+追加ダイス。
    """
    base = roll_dice_formula(weapon_dice)
    log_parts = [f"{weapon_dice}→{base}"]
    bonus = 0
    if damage_bonus_dice:
        if damage_bonus_dice.startswith("+") or "D" in damage_bonus_dice.upper():
            bonus = roll_dice_formula(damage_bonus_dice.lstrip("+"))
        else:
            try:
                bonus = int(damage_bonus_dice)
            except ValueError:
                bonus = 0
        if bonus:
            log_parts.append(f"DB→{bonus}")

    if is_extreme:
        import re
        m = re.match(r"(\d*)D(\d+)", weapon_dice.upper())
        if m:
            count = int(m.group(1) or 1)
            faces = int(m.group(2))
            max_base = count * faces
            if is_blunt:
                total = max_base + max(bonus, 0)
                log_parts.append("イクストリーム(鈍器最大)")
                return max(0, total), " + ".join(log_parts)
            extra = roll_dice_formula(weapon_dice)
            total = max_base + max(bonus, 0) + extra
            log_parts.append(f"イクストリーム(貫通+{extra})")
            return max(0, total), " + ".join(log_parts)
    total = max(0, base + bonus)
    return total, " + ".join(log_parts)


def skill_improvement_roll(current_value: int) -> Dict[str, Any]:
    """成功の報酬: 1D100 > 現在値なら 1D10 上昇。"""
    roll = random.randint(1, 100)
    if roll > current_value:
        gain = random.randint(1, 10)
        return {
            "improved": True,
            "roll": roll,
            "gain": gain,
            "new_value": min(99, current_value + gain),
        }
    return {"improved": False, "roll": roll, "gain": 0, "new_value": current_value}
