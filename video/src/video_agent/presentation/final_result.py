from __future__ import annotations

import copy
import re


RESULT_MAP = {
    "失敗": "FAILURE",
    "成功": "SUCCESS",
    "regular 成功": "SUCCESS",
    "レギュラー成功": "SUCCESS",
    "FAILURE": "FAILURE",
    "SUCCESS": "SUCCESS",
}


def canonical_result(value: str | None) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    for key, canonical in RESULT_MAP.items():
        if key.lower() in text.lower():
            return canonical
    return text.upper()


def apply_final_result_overrides(lines: list[dict]) -> tuple[list[dict], list[dict]]:
    """Enrich overlays from explicit source facts without changing M2 input."""
    output, changes = [], []
    for source in lines:
        line = copy.deepcopy(source)
        overlay = line.get("overlay")
        text = str(line.get("display_text") or line.get("text") or "")
        luck = re.search(r"【幸運消費】.*?幸運を\s*(\d+)\s*消費.*?(?:regular|レギュラー)?\s*成功", text,
                         flags=re.IGNORECASE | re.DOTALL)
        if overlay and overlay.get("type") == "SKILL_CHECK":
            raw = canonical_result(overlay.get("raw_result") or overlay.get("result"))
            overlay["raw_result"] = raw
            overlay.setdefault("final_result", raw)
            overlay.setdefault("presentation_phase", "RAW_RESULT")
            if luck:
                amount = int(luck.group(1))
                overlay["final_result"] = "SUCCESS"
                overlay["modification"] = {"type": "LUCK_SPEND", "amount": amount}
                overlay["presentation_phase"] = "FINALIZED_RESULT"
                changes.append({
                    "script_line_id": line.get("script_line_id"),
                    "raw_result": raw,
                    "final_result": "SUCCESS",
                    "modification": {"type": "LUCK_SPEND", "amount": amount},
                    "grounding": "EXPLICIT_LUCK_SPEND_IN_SOURCE",
                })
        output.append(line)
    return output, changes


def final_result_mismatches(lines: list[dict]) -> list[dict]:
    mismatches = []
    for line in lines:
        overlay = line.get("overlay") or {}
        modification = overlay.get("modification") or {}
        if modification.get("type") == "LUCK_SPEND" and overlay.get("final_result") != "SUCCESS":
            mismatches.append({"script_line_id": line.get("script_line_id"),
                               "reason": "LUCK_SPEND_NOT_DISPLAYED_AS_SUCCESS"})
        if overlay.get("presentation_phase") == "FINALIZED_RESULT" and not overlay.get("final_result"):
            mismatches.append({"script_line_id": line.get("script_line_id"),
                               "reason": "FINALIZED_RESULT_MISSING_FINAL_RESULT"})
    return mismatches

