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


# ---------------------------------------------------------------------------
# タスク4: 判定失敗後の選択肢（Pending Decision）ルール
# ---------------------------------------------------------------------------

DECISION_OPTION_ACCEPT = "accept"
DECISION_OPTION_SPEND_LUCK = "spend_luck"
DECISION_OPTION_PUSH = "push"
DECISION_OPTION_DODGE = "dodge"
DECISION_OPTION_FIGHT_BACK = "fight_back"
DECISION_OPTION_ACCEPT_HIT = "accept_hit"

PENDING_DECISION_POST_ROLL_FAILURE = "POST_ROLL_FAILURE"
PENDING_DECISION_COMBAT_DEFENSE = "COMBAT_DEFENSE"
PENDING_DECISION_SHOOT_DEFENSE = "SHOOT_DEFENSE"

UNPUSHABLE_SKILL_NAMES = frozenset({
    "正気度", "SAN", "幸運", "LUCK", "LUK",
    "格闘", "近接戦闘", "射撃", "火器", "回避", "投擲",
})
COMBAT_SKILL_NAME_KEYWORDS = (
    "戦闘", "射撃", "火器", "格闘", "回避", "刀剣", "拳銃", "ライフル", "ショットガン",
)
DEFAULT_LUCK_BURN_MAX = 10


def is_push_allowed(
    *,
    skill_name: str = "",
    action_id: str = "",
    in_combat: bool = False,
    already_pushed: bool = False,
    roll_type: str = "",
) -> bool:
    """
    プッシュロール可否（CoC7）。
    不可: 戦闘中 / 既プッシュ / SAN / 幸運 / 戦闘技能 / 技能名なし。
    """
    if in_combat or already_pushed:
        return False
    action = str(action_id or "").lower().strip()
    rtype = str(roll_type or "").lower().strip()
    if action in ("san_check", "wait", "push_roll") or rtype in ("san_check", "luck", "opposed_str"):
        return False
    skill = str(skill_name or "").strip()
    if not skill:
        return False
    if skill in UNPUSHABLE_SKILL_NAMES:
        return False
    if any(kw in skill for kw in COMBAT_SKILL_NAME_KEYWORDS):
        return False
    return True


def is_luck_spend_allowed(
    *,
    is_fumble: bool = False,
    action_id: str = "",
    roll_type: str = "",
    already_pushed: bool = False,
    margin: int = 0,
    current_luck: int = 0,
    max_burn: int = DEFAULT_LUCK_BURN_MAX,
) -> bool:
    """
    失敗後の幸運消費可否。
    不可: ファンブル / SAN / 幸運ロール / プッシュ後ロール / 差分超過・幸運不足。
    """
    if is_fumble:
        return False
    action = str(action_id or "").lower().strip()
    rtype = str(roll_type or "").lower().strip()
    if action in ("san_check", "push_roll") or rtype in ("san_check", "luck"):
        return False
    if already_pushed:
        return False
    margin = int(margin or 0)
    if margin <= 0 or margin > int(max_burn or DEFAULT_LUCK_BURN_MAX):
        return False
    if int(current_luck or 0) < margin:
        return False
    return True


def build_post_roll_failure_legal_options(
    *,
    skill_name: str = "",
    action_id: str = "",
    roll_type: str = "",
    in_combat: bool = False,
    already_pushed: bool = False,
    is_fumble: bool = False,
    margin: int = 0,
    current_luck: int = 0,
    max_burn: int = DEFAULT_LUCK_BURN_MAX,
    allow_push: Optional[bool] = None,
) -> Dict[str, Any]:
    """
    判定失敗後に提示可能な選択肢を算出する。
    常に accept を含み、条件を満たせば spend_luck / push を追加する。
    """
    reasons: Dict[str, str] = {}
    options: List[str] = [DECISION_OPTION_ACCEPT]

    push_ok = is_push_allowed(
        skill_name=skill_name,
        action_id=action_id,
        in_combat=in_combat,
        already_pushed=already_pushed,
        roll_type=roll_type,
    )
    if allow_push is False:
        push_ok = False
        reasons["push"] = "シナリオ／呼び出し側でプッシュ禁止"
    elif not push_ok:
        if in_combat:
            reasons["push"] = "戦闘ロールはプッシュ不可"
        elif already_pushed:
            reasons["push"] = "既にプッシュ済み"
        elif str(action_id or "").lower() in ("san_check",) or str(roll_type or "").lower() == "san_check":
            reasons["push"] = "SANチェックはプッシュ不可"
        elif str(action_id or "").lower() == "push_roll":
            reasons["push"] = "プッシュロール自体は再プッシュ不可"
        else:
            reasons["push"] = "技能／行動種別によりプッシュ不可"

    luck_ok = is_luck_spend_allowed(
        is_fumble=is_fumble,
        action_id=action_id,
        roll_type=roll_type,
        already_pushed=already_pushed,
        margin=margin,
        current_luck=current_luck,
        max_burn=max_burn,
    )
    if not luck_ok:
        if is_fumble:
            reasons["spend_luck"] = "ファンブルには幸運消費不可"
        elif already_pushed:
            reasons["spend_luck"] = "プッシュ後ロールには幸運消費不可"
        elif str(action_id or "").lower() in ("san_check", "push_roll") or str(roll_type or "").lower() in ("san_check", "luck"):
            reasons["spend_luck"] = "SAN／幸運／プッシュロールには幸運消費不可"
        elif int(margin or 0) <= 0:
            reasons["spend_luck"] = "成功に必要な差分がない"
        elif int(margin or 0) > int(max_burn or DEFAULT_LUCK_BURN_MAX):
            reasons["spend_luck"] = f"差分が上限（{max_burn}）を超える"
        else:
            reasons["spend_luck"] = "幸運が不足している"

    luck_cost = int(margin or 0) if luck_ok else None
    if luck_ok:
        options.append(DECISION_OPTION_SPEND_LUCK)
    if push_ok:
        options.append(DECISION_OPTION_PUSH)

    return {
        "legal_options": options,
        "luck_cost": luck_cost,
        "push_allowed": push_ok,
        "luck_allowed": luck_ok,
        "reasons": reasons,
    }


def build_combat_defense_legal_options(*, is_shoot: bool = False) -> List[str]:
    """戦闘防衛の合法選択肢。射撃は応戦不可。"""
    if is_shoot:
        return [DECISION_OPTION_DODGE, DECISION_OPTION_ACCEPT_HIT]
    return [DECISION_OPTION_DODGE, DECISION_OPTION_FIGHT_BACK]
