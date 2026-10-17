import importlib.util
from pathlib import Path

from video_agent.normalizer import normalize_session


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "v11_formal_auditor", ROOT / "tools" / "audit_longrun_formal_v2.py",
)
auditor = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(auditor)


def source(unified, session):
    return {
        "root": "v11_fixture",
        "source_files": [],
        "result": {"session_id": "V11_PATCHED_FIXTURE", "scenario_file": "fixture.json"},
        "scenarios": [{"scenario_meta": {"title": "fixture"}, "locations": {}}],
        "pcs": {"pc_01": {"profile": {"name": "探索者"}}},
        "npcs": {},
        "unified_events": unified,
        "session_events": session,
    }


def test_patched_session_roll_lifecycle_and_identifier_have_zero_formal_blockers():
    evidence = {
        "adjudication_id": "adj_v11",
        "resolution_mode": "ROLL",
        "actor": "pc_01",
        "target": "wall_planks",
        "skill_or_stat": "STR",
        "canonical_identifier": "STR",
        "target_value": 55,
        "roll": 38,
        "raw_result": "REGULAR_SUCCESS",
        "final_result": "REGULAR_SUCCESS",
        "modifier": {"type": "NONE"},
    }
    unified = [
        {"event_id": "u_roll", "event_type": "INVESTIGATION_ROLLED", **evidence},
        {
            "event_id": "u_end", "event_type": "COMBAT_ENDED",
            "combat_id": "combat_v11", "cause_adjudication_id": "adj_v11",
        },
    ]
    session = [
        {
            "channel": "IC", "location": "basement",
            "text": "システム: 【技能:STR】CC(1d100<=55) ＞ 出目:38 ＞ レギュラー成功",
            "meta": {
                "event_id": "s_roll", "actor_id": "pc_01", "target": "wall_planks",
                "roll_type": "skill", **{k: v for k, v in evidence.items() if k != "actor"},
            },
        },
        {
            "channel": "IC", "location": "basement",
            "text": "システム: 【戦闘終了】戦闘が終結した。",
            "meta": {
                "event_id": "s_end", "actor_id": "pc_01", "action_id": "combat_end",
                "roll_type": "combat_lifecycle", "cause_adjudication_id": "adj_v11",
            },
        },
    ]
    normalized_doc = normalize_session(source(unified, session))
    normalized = normalized_doc["events"]

    assert auditor.audit_roll_contract(unified, normalized, "fixture") == []
    assert auditor.audit_lifecycle_contract(unified, normalized, "fixture") == []
    assert auditor.audit_normalizer_warnings(normalized_doc, "fixture") == []
    assert not [
        warning for warning in normalized_doc["metadata"]["conversion_warnings"]
        if warning.get("code") == "NORMALIZATION_SOURCE_CONTRADICTION"
    ]
    roll_events = [event for event in normalized if event.get("adjudication_id") == "adj_v11"]
    assert roll_events
    assert all((event.get("dice") or {}).get("skill_name") == "STR" for event in roll_events)
