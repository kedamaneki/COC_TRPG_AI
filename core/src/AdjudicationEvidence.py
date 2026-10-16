"""Canonical, fail-closed evidence contract for authoritative adjudications."""
from __future__ import annotations

import copy


ROLL = "ROLL"
NO_ROLL = "NO_ROLL"
NONE_MODIFIER = {"type": "NONE"}


class EvidenceContractError(ValueError):
    pass


def _present(value):
    return value is not None and (not isinstance(value, str) or bool(value.strip()))


def normalize_modifier(value):
    if value in (None, "", []):
        return copy.deepcopy(NONE_MODIFIER)
    if not isinstance(value, dict) or not _present(value.get("type")):
        raise EvidenceContractError("modifier evidence requires an explicit type")
    return copy.deepcopy(value)


def validate_evidence(payload):
    mode = str((payload or {}).get("resolution_mode") or "").upper()
    common = ["adjudication_id", "resolution_mode"]
    if mode == ROLL:
        required = common + [
            "skill_or_stat", "target_value", "roll", "raw_result", "final_result", "modifier",
        ]
    elif mode == NO_ROLL:
        required = common + ["resolution_reason", "final_result"]
    else:
        raise EvidenceContractError(f"unsupported resolution_mode: {mode or '<missing>'}")
    missing = [name for name in required if not _present((payload or {}).get(name))]
    if missing:
        raise EvidenceContractError(f"incomplete {mode} evidence: {', '.join(missing)}")
    if mode == ROLL:
        normalize_modifier(payload.get("modifier"))
    return True


def roll_evidence(*, adjudication_id, skill_or_stat, target_value, roll,
                  raw_result, final_result, modifier=None, base_target=None,
                  effect_result=None, objective_outcome=None, **extra):
    result = {
        "adjudication_id": adjudication_id,
        "resolution_mode": ROLL,
        "skill_or_stat": skill_or_stat,
        "base_target": target_value if base_target is None else base_target,
        "final_target": target_value,
        "target_value": target_value,
        "roll": roll,
        "raw_result": raw_result,
        "final_result": final_result,
        "roll_result": final_result,
        "modifier": normalize_modifier(modifier),
    }
    if effect_result is not None:
        result["effect_result"] = effect_result
    if objective_outcome is not None:
        result["objective_outcome"] = objective_outcome
    result.update(extra)
    validate_evidence(result)
    return result


def no_roll_evidence(*, adjudication_id, reason, final_outcome,
                     effect_result=None, objective_outcome=None, **extra):
    result = {
        "adjudication_id": adjudication_id,
        "resolution_mode": NO_ROLL,
        "resolution_reason": reason,
        "final_result": final_outcome,
        "automatic_result": final_outcome,
        "skill_or_stat": extra.pop("skill_or_stat", ""),
        "target_value": None,
        "roll": None,
        "raw_result": None,
        "modifier": None,
    }
    if effect_result is not None:
        result["effect_result"] = effect_result
    if objective_outcome is not None:
        result["objective_outcome"] = objective_outcome
    result.update(extra)
    validate_evidence(result)
    return result
