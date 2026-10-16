"""Audit the offline post-fix acceptance session without inventing evidence."""
from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / "projects" / "corbitt_adjudication_fix_001"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def main():
    normalized = load(PROJECT / "normalized_session.json")
    events = normalized["events"]
    warnings = normalized["metadata"].get("conversion_warnings") or []

    rolled = [e for e in events if (e.get("dice") or {}).get("resolution_mode") == "ROLL"]
    incomplete_rolls = [
        e["event_id"] for e in rolled
        if any((e.get("dice") or {}).get(k) is None
               for k in ("target_value", "roll", "raw_result", "final_result"))
    ]
    san_rows = [e for e in events if e.get("san")]
    incomplete_san = [
        e["event_id"] for e in san_rows
        if any(e["san"].get(k) is None for k in ("before", "target", "roll", "result", "loss", "after"))
    ]
    luck_rows = [e for e in events if (e.get("modifier") or {}).get("type") == "LUCK_SPEND"]
    incomplete_luck = [
        e["event_id"] for e in luck_rows
        if any((e.get("modifier") or {}).get(k) is None
               for k in ("amount", "resource_before", "resource_after"))
        or any((e.get("dice") or {}).get(k) is None
               for k in ("roll", "target_value", "raw_result", "final_result"))
    ]

    wall = [e for e in events if (e.get("action") or {}).get("target") == "basement_planks"
            or (e.get("metadata", {}).get("source_payload") or {}).get("target") == "basement_planks"]
    wall_state_ok = any(
        (e.get("metadata", {}).get("source_payload") or {}).get("state_before", {}).get("basement_planks_broken") is False
        and (e.get("metadata", {}).get("source_payload") or {}).get("state_after", {}).get("basement_planks_broken") is True
        for e in wall
    )
    wall_text_ok = any("板を破壊" in str(e.get("text") or "") for e in events)

    knife = [e for e in events if (e.get("combat") or {}).get("combat_id") == "combat_knife_001"]
    knife_types = {e.get("event_type") for e in knife}
    combat_resolved = [e for e in knife if e.get("event_type") == "COMBAT_ACTION"]
    combat_evidence_ok = any(
        (e.get("dice") or {}).get("roll") is not None
        and (e.get("combat") or {}).get("hp_after") == 0
        for e in combat_resolved
    )
    combat_terminated = "COMBAT_START" in knife_types and "COMBAT_END" in knife_types

    contradiction_warnings = [
        w for w in warnings if w.get("code") == "NORMALIZATION_SOURCE_CONTRADICTION"
    ]
    legacy_fallbacks = sum(
        1 for e in events
        if (e.get("san") or {}).get("normalization_source") == "LEGACY_TEXT_PARSE"
        or (e.get("modifier") or {}).get("normalization_source") == "LEGACY_TEXT_PARSE"
    )
    critical = []
    if not wall_state_ok or not wall_text_ok:
        critical.append("SOURCE_CONTRADICTION")
    if not combat_terminated or not combat_evidence_ok:
        critical.append("SOURCE_GAMEPLAY_GAP")
    if incomplete_rolls or incomplete_san or incomplete_luck or contradiction_warnings:
        critical.append("NORMALIZATION_GAP")

    report = {
        "session_id": normalized["session_id"],
        "acceptance_session_kind": "OFFLINE_DETERMINISTIC_CONTRACT_SESSION",
        "source_contradiction_count": 0 if wall_state_ok and wall_text_ok else 1,
        "normalization_gap_count": len(incomplete_rolls) + len(incomplete_san) + len(incomplete_luck),
        "combat_without_termination_count": 0 if combat_terminated else 1,
        "normalization_source_contradiction_count": len(contradiction_warnings),
        "rolled_check_count": len(rolled),
        "rolled_check_incomplete_count": len(incomplete_rolls),
        "san_complete": bool(san_rows) and not incomplete_san,
        "luck_complete": bool(luck_rows) and not incomplete_luck,
        "wall_narrative_state_consistent": wall_state_ok and wall_text_ok,
        "knife_combat_lifecycle_complete": combat_terminated and combat_evidence_ok,
        "final_battle_special_objective_preserved": any(
            (e.get("metadata", {}).get("source_payload") or {}).get("final_result")
            == "SPECIAL_OBJECTIVE_COMPLETED" for e in events
        ),
        "legacy_text_parse_count": legacy_fallbacks,
        "critical_findings": critical,
        "result": "PASS" if not critical else "FAIL",
        "details": {
            "incomplete_roll_event_ids": incomplete_rolls,
            "incomplete_san_event_ids": incomplete_san,
            "incomplete_luck_event_ids": incomplete_luck,
            "normalization_contradictions": contradiction_warnings,
        },
    }
    (PROJECT / "adjudication_recovery_audit.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
