"""Dice-expression based sound-effect selection for video presentation."""

from __future__ import annotations

import re
from dataclasses import dataclass


class DiceExpressionError(ValueError):
    """Raised when a dice expression cannot be safely interpreted."""


@dataclass(frozen=True)
class DiceSfxSelection:
    expression: str
    physical_dice_count: int
    asset_id: str


_TERM = re.compile(r"(?<![A-Z0-9_])(\d*)D(\d+)(?![A-Z0-9_])", re.IGNORECASE)


def physical_dice_count(expression: str) -> int:
    """Return dice rolled simultaneously; percentile dice count as two d10s."""
    normalized = str(expression or "").strip().upper().replace(" ", "")
    if not normalized:
        raise DiceExpressionError("DICE_EXPRESSION_MISSING")
    matches = list(_TERM.finditer(normalized))
    if not matches:
        raise DiceExpressionError(f"DICE_EXPRESSION_UNSUPPORTED:{expression}")
    count = 0
    for match in matches:
        quantity = int(match.group(1) or "1")
        sides = int(match.group(2))
        if quantity < 1 or sides < 2:
            raise DiceExpressionError(f"DICE_EXPRESSION_INVALID:{expression}")
        count += 2 * quantity if sides == 100 else quantity
    return count


def select_dice_sfx(expression: str, *, single_asset_id: str, multi_asset_id: str) -> DiceSfxSelection:
    count = physical_dice_count(expression)
    return DiceSfxSelection(expression=expression, physical_dice_count=count,
                            asset_id=single_asset_id if count == 1 else multi_asset_id)
