"""V17PRE production-path smoke: RecentAction schema + counters + progress wiring.

Session: CORBITT_NDM_SCHEMA_SMOKE_V17PRE_001 (not formal V17 Full-Long).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / "core" / "src"
sys.path.insert(0, str(CORE))

from ProgressDirectorV2 import StallDetectorV2
from ndm_integration import enrich_pc_action_with_ndm, ensure_ndm_runtime
from reasoning.error_class import NDMRuntimeContractViolation
from reasoning.progress_events import emit_progress_from_director_delta, progress_events_for_ndm
from reasoning.recent_action import RECENT_ACTION_SCHEMA_VERSION, normalize_recent_actions
from reasoning.runtime import DECISION_SOURCE_NDM, set_active_runtime

SMOKE_SESSION = "CORBITT_NDM_SCHEMA_SMOKE_V17PRE_001"


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else REPO / "docs"
    out.mkdir(parents=True, exist_ok=True)

    state = {
        "director_v2": {"stall": {}, "goal": {"candidate_next_actions": []}},
        "ndm_runtime": {},
        "current_loc": "introduction",
    }
    rt = ensure_ndm_runtime(state, required=True, enabled=True, implementation_commit="v17pre")
    set_active_runtime(rt)

    # StallDetector canonical write → NDM read
    stall = StallDetectorV2.update(
        state["director_v2"].get("stall") or {},
        action="talk",
        target="steven_knott",
        location_before="introduction",
        location_after="introduction",
        progress_delta=1,
    )
    state["director_v2"]["stall"] = stall
    recent = normalize_recent_actions(stall.get("recent_actions") or [])
    schema_ok = all(r.schema_version == RECENT_ACTION_SCHEMA_VERSION for r in recent)

    emit_progress_from_director_delta(
        state,
        progress={
            "progress_delta": 2,
            "location_changed": False,
            "knowledge_gained": True,
            "flags_changed": True,
            "requirements_completed": [],
            "progress_reason": ["knowledge"],
        },
        actor_id="pc_01",
    )

    selected = enrich_pc_action_with_ndm(
        state,
        {"action": "search", "target": "knott_letter", "reason": "read letter", "candidate_id": "pl_proposal"},
        actor_id="pc_01",
    )

    rates_positive = rt.telemetry.rates()
    positive_violation_count = int(rt.telemetry.RUNTIME_CONTRACT_VIOLATION_COUNT)

    # Negative: malformed recent must BLOCK (separate probe; must not poison positive gates)
    neg_blocked = False
    try:
        rt.decide(
            state,
            actor_id="pc_01",
            candidates=[{"action": "wait", "target": "", "reason": "x", "candidate_id": "c1"}],
            recent_actions=[["bad"]],
        )
    except NDMRuntimeContractViolation:
        neg_blocked = True

    list_get_hits = sum(
        1
        for e in rt.telemetry.events
        if "list" in str(e).lower() and "has no attribute 'get'" in str(e).lower()
    )

    report = {
        "session_id": SMOKE_SESSION,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "RECENT_ACTION_SCHEMA_CONSISTENT": schema_ok,
        "RECENT_ACTION_SCHEMA_VERSION": RECENT_ACTION_SCHEMA_VERSION,
        "NDM_DECISION_COMMIT_COUNT": rt.telemetry.NDM_DECISION_COMMIT_COUNT,
        "SAFE_LEGACY_DECISION_COMMIT_COUNT": rt.telemetry.SAFE_LEGACY_DECISION_COMMIT_COUNT,
        "UNSAFE_LEGACY_DECISION_COMMIT_COUNT": rt.telemetry.UNSAFE_LEGACY_DECISION_COMMIT_COUNT,
        "RUNTIME_CONTRACT_VIOLATION_COUNT_POSITIVE_PATH": positive_violation_count,
        "RUNTIME_CONTRACT_VIOLATION_COUNT": positive_violation_count,
        "SAFE_FALLBACK_FAILURE_COUNT": rt.telemetry.SAFE_FALLBACK_FAILURE_COUNT,
        "PROGRESS_EVENT_COUNT": len(progress_events_for_ndm(state)),
        "MEANINGFUL_PROGRESS_RATE": rates_positive.get("MEANINGFUL_PROGRESS_RATE"),
        "SELF_RECOVERY_RATE": rates_positive.get("SELF_RECOVERY_RATE"),
        "UNEXPLAINED_ACTION_RATE": rates_positive.get("UNEXPLAINED_ACTION_RATE"),
        "UNRESOLVED_LEAD_ABANDON_RATE": rates_positive.get("UNRESOLVED_LEAD_ABANDON_RATE"),
        "NDM_DECISION_CAUSAL_COVERAGE": rates_positive.get("NDM_DECISION_CAUSAL_COVERAGE"),
        "SELECTED_ACTION_DECISION_SOURCE": selected.get("decision_source"),
        "LIST_GET_ATTRIBUTE_ERROR_COUNT": list_get_hits,
        "NEGATIVE_MALFORMED_BLOCK": neg_blocked,
        "rates": rates_positive,
    }
    hard = (
        schema_ok
        and report["NDM_DECISION_COMMIT_COUNT"] > 0
        and report["UNSAFE_LEGACY_DECISION_COMMIT_COUNT"] == 0
        and report["RUNTIME_CONTRACT_VIOLATION_COUNT_POSITIVE_PATH"] == 0
        and report["SAFE_FALLBACK_FAILURE_COUNT"] == 0
        and report["PROGRESS_EVENT_COUNT"] > 0
        and report["MEANINGFUL_PROGRESS_RATE"] is not None
        and report["SELF_RECOVERY_RATE"] is not None
        and report["NDM_DECISION_CAUSAL_COVERAGE"] is not None
        and selected.get("decision_source") == DECISION_SOURCE_NDM
        and list_get_hits == 0
        and neg_blocked
    )
    report["PRODUCTION_SMOKE"] = "PASS" if hard else "FAIL"
    report["CONTRACT_VIOLATION_FAIL_CLOSED"] = "PASS" if neg_blocked else "FAIL"
    (out / "V17_PRODUCTION_SMOKE_REPORT.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if hard else 2


if __name__ == "__main__":
    raise SystemExit(main())
