from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def first_index(events: list[dict[str, Any]], predicate) -> int | None:
    return next((index for index, event in enumerate(events) if predicate(event)), None)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--core-run", type=Path, required=True)
    parser.add_argument("--normalized", type=Path, required=True)
    parser.add_argument("--legacy-project", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    run = args.core_run
    result = read_json(run / "result.json")
    session = read_json(run / "session-log.json")
    unified = read_json(run / "unified-event-log.json")
    normalized = read_json(args.normalized)
    final_state = read_json(run / "checkpoints" / "cycle_000033" / "state.json")
    legacy = read_json(args.legacy_project / "normalized_session.json")
    legacy_audit = read_json(args.legacy_project / "adjudication_evidence_report.json")
    legacy_gaps = read_json(args.legacy_project / "adjudication_gap_report.json")

    # Preserve the exact evaluated inputs beside the Core logs.
    shutil.copy2(args.normalized, run / "normalized_session.json")
    shutil.copy2(run / "runtime_data" / "pcs.json", run / "pcs.json")

    event_counts = Counter(event.get("event_type") for event in normalized["events"])
    unified_event_counts = Counter(event.get("event_type") for event in unified)
    warnings = normalized.get("metadata", {}).get("conversion_warnings", [])
    warning_fields = Counter(warning.get("field") for warning in warnings)

    traceable = sum(bool(event.get("source_event_ids")) for event in normalized["events"])
    traceability = traceable / len(normalized["events"]) if normalized["events"] else 1.0

    actual_resolution_types = {"INVESTIGATION_ROLLED", "COMBAT_ACTION_RESOLVED"}
    unified_roll_resolutions = [
        event
        for event in unified
        if event.get("event_type") in actual_resolution_types and event.get("resolution_mode") == "ROLL"
    ]
    unified_incomplete_rolls = [
        event
        for event in unified_roll_resolutions
        if any(event.get(field) in (None, "") for field in ("target_value", "roll", "raw_result", "final_result"))
    ]

    session_rolls = []
    for index, event in enumerate(session):
        meta = event.get("meta") or {}
        if meta.get("resolution_mode") == "ROLL" and meta.get("adjudication_id"):
            session_rolls.append((index, event, meta))
    session_incomplete_rolls = [
        (index, event, meta)
        for index, event, meta in session_rolls
        if any(meta.get(field) in (None, "") for field in ("target_value", "roll", "raw_result", "final_result"))
    ]
    incomplete_adjudications = sorted({meta["adjudication_id"] for _, _, meta in session_incomplete_rolls})

    luck_events = []
    for index, event in enumerate(session):
        meta = event.get("meta") or {}
        modifier = meta.get("modifier") or {}
        if modifier.get("type") == "LUCK_SPEND":
            luck_events.append(
                {
                    "session_index": index,
                    "adjudication_id": meta.get("adjudication_id"),
                    "target": meta.get("target"),
                    "target_value": meta.get("target_value"),
                    "roll": meta.get("roll"),
                    "raw_result": meta.get("raw_result"),
                    "final_result": meta.get("final_result"),
                    "modifier": modifier,
                }
            )

    normalized_san = [event for event in normalized["events"] if event.get("san") is not None]
    actual_san = []
    for index, event in enumerate(session):
        meta = event.get("meta") or {}
        if meta.get("roll_type") == "san" or meta.get("san_roll") is not None:
            actual_san.append({"session_index": index, "meta": meta})
    fake_san = [
        {
            "event_id": event.get("event_id"),
            "event_type": event.get("event_type"),
            "adjudication_id": event.get("adjudication_id"),
            "san": event.get("san"),
            "source_stream": event.get("metadata", {}).get("source_stream"),
            "source_index": event.get("metadata", {}).get("source_index"),
        }
        for event in normalized_san
        if not event.get("san", {}).get("roll") and not event.get("san", {}).get("result")
    ]

    combats: dict[str, dict[str, Any]] = {}
    for index, event in enumerate(unified):
        combat_id = event.get("combat_id")
        if not combat_id:
            continue
        record = combats.setdefault(combat_id, {"start": None, "end": None, "actions": [], "events": []})
        record["events"].append({"index": index, "event_id": event.get("event_id"), "event_type": event.get("event_type")})
        if event.get("event_type") == "COMBAT_STARTED":
            record["start"] = event.get("event_id")
            record["participants"] = event.get("participants")
            record["trigger_event_id"] = event.get("trigger_event_id")
        elif event.get("event_type") == "COMBAT_ACTION_RESOLVED":
            record["actions"].append(
                {
                    "event_id": event.get("event_id"),
                    "adjudication_id": event.get("adjudication_id"),
                    "resolution_mode": event.get("resolution_mode"),
                    "target_value": event.get("target_value"),
                    "roll": event.get("roll"),
                    "raw_result": event.get("raw_result"),
                    "final_result": event.get("final_result"),
                    "damage_formula": event.get("damage_formula"),
                    "damage_roll": event.get("damage_roll"),
                    "actual_damage": event.get("actual_damage"),
                    "hp_before": event.get("HP_before"),
                    "hp_after": event.get("HP_after"),
                }
            )
        elif event.get("event_type") == "COMBAT_ENDED":
            record["end"] = event.get("event_id")
    dangling_combats = [combat_id for combat_id, combat in combats.items() if not combat["start"] or not combat["end"]]

    legacy_traceability = read_json(args.legacy_project / "provenance_report.json").get("source_traceability_rate")
    legacy_hash = sha256(args.legacy_project / "normalized_session.json")

    findings = [
        {
            "finding_id": "rolled_check_incomplete",
            "classification": "SOURCE_LOGGING_GAP",
            "root_cause": "LOGGING_GAP",
            "severity": "CRITICAL",
            "count": len(incomplete_adjudications),
            "detail": "resolution_mode=ROLL の9判定で target_value / roll / raw_result のいずれかが構造値として欠落する。対抗STRは本文に双方の出目があるがmeta/Unifiedへ記録されず、INVESTIGATION_ROLLEDでも2件がnullのまま。",
            "adjudication_ids": incomplete_adjudications,
            "unified_incomplete_event_ids": [event.get("event_id") for event in unified_incomplete_rolls],
            "recommended_fix_layer": ["TRPG Core", "Unified Event Logging"],
        },
        {
            "finding_id": "wall_board_narrative_state_contradiction",
            "classification": "SOURCE_CONTRADICTION",
            "root_cause": "STATE_CONTRADICTION",
            "severity": "CRITICAL",
            "count": 1,
            "detail": "session[180-181] は板を破壊して通路を開けたと断定するが、同一判定のstate_afterは basement_planks_examined=true のみで broken=false。後の別判定 session[439] で初めて broken が false→true になる。",
            "evidence": {"session_indices": [180, 181, 439], "adjudication_ids": ["adj_13a48cc9fd3a46338d8d30f02fe52852", "adj_1ff0fac2aa3e467bb7cbc55ae6dff52d"]},
            "recommended_fix_layer": ["Scenario Data", "TRPG Core"],
        },
        {
            "finding_id": "basement_door_narrative_state_contradiction",
            "classification": "SOURCE_CONTRADICTION",
            "root_cause": "STATE_CONTRADICTION",
            "severity": "CRITICAL",
            "count": 1,
            "detail": "session[161] は『扉はまだ閉ざされている』と『地下室への扉を開けた』を同時に出力し、state_afterは examined=true のみ。session[164]/[247] でも閉鎖と開放が同時表示され、実際の unlocked false→true はsession[167]の別判定。",
            "evidence": {"session_indices": [161, 164, 167, 247], "adjudication_ids": ["adj_d5341ff2dbd24fd8879db6a03670d638", "adj_c9bddd0f441b440193eb54ad452daca8"]},
            "recommended_fix_layer": ["Scenario Data", "TRPG Core"],
        },
        {
            "finding_id": "required_san_payload_not_executed",
            "classification": "SOURCE_GAMEPLAY_GAP",
            "root_cause": "CORE_GAMEPLAY_BUG",
            "severity": "CRITICAL",
            "count": 1,
            "detail": "シナリオの living_room_clutter 成功payloadには force_san_check(0/1D3) があるが、session[154]の成功後にSAN判定が生成されない。実runのSAN判定は0件で、単一式/状態整合性を長編運用で検証できなかった。",
            "evidence": {"session_index": 154, "trigger_event_id": "corbitt_ground_floor__living_room_clutter__success", "actual_san_check_count": len(actual_san)},
            "recommended_fix_layer": ["Scenario Runtime", "TRPG Core"],
        },
        {
            "finding_id": "normalization_source_contradictions",
            "classification": "NORMALIZATION_GAP",
            "root_cause": "NORMALIZATION_GAP",
            "severity": "MAJOR",
            "count": len(warnings),
            "detail": "Normalizerが22件のNORMALIZATION_SOURCE_CONTRADICTIONを出力。16件は数値result_levelと文字列成功度の未正規化比較、2件はLuck適用前後を矛盾扱い、1件は戦闘結果taxonomy、3件は戦闘状態のSANフィールド誤解釈。",
            "fields": dict(warning_fields),
            "recommended_fix_layer": ["Video Production Agent Normalizer"],
        },
        {
            "finding_id": "combat_state_misnormalized_as_san",
            "classification": "NORMALIZATION_GAP",
            "root_cause": "NORMALIZATION_GAP",
            "severity": "MAJOR",
            "count": len(fake_san),
            "detail": "実SAN判定は0件だが、Normalizerは戦闘イベントのSAN_before/SAN_after状態スナップショットを7件のSAN証拠として生成した。うちknife combatでは55と0が同一adjudicationで衝突する。",
            "evidence": fake_san,
            "recommended_fix_layer": ["Unified Event Schema", "Video Production Agent Normalizer"],
        },
        {
            "finding_id": "luck_transition_misclassified_as_contradiction",
            "classification": "NORMALIZATION_GAP",
            "root_cause": "NORMALIZATION_GAP",
            "severity": "MAJOR",
            "count": 2,
            "detail": "2件のLuck消費はsourceではroll/target/raw failure/spend/before/after/final successを保持するが、Normalizerは適用前FAILUREと適用後SUCCESSをsource contradictionとして扱う。",
            "evidence": luck_events,
            "recommended_fix_layer": ["Video Production Agent Normalizer"],
        },
        {
            "finding_id": "knife_object_state_inconsistent",
            "classification": "SOURCE_CONTRADICTION",
            "root_cause": "STATE_CONTRADICTION",
            "severity": "MAJOR",
            "count": 1,
            "detail": "session[197]は has_corbitt_knife=false の時点で『持っているナイフ』と『床に放置』を同時に描写。戦闘後にダガーが消滅した描写があるが、最終flag has_corbitt_knife=true のまま。",
            "evidence": {"session_indices": [197, 424, 434], "final_has_corbitt_knife": result.get("final_flags", {}).get("has_corbitt_knife")},
            "recommended_fix_layer": ["TRPG Core", "Scenario Runtime", "KP Context"],
        },
        {
            "finding_id": "final_battle_adjudication_link_missing",
            "classification": "SOURCE_LOGGING_GAP",
            "root_cause": "LOGGING_GAP",
            "severity": "MAJOR",
            "count": 1,
            "detail": "最終戦のSession eventはworld_factとadjudication_idを持つが、同じtransactionのUnified COMBAT_ACTION_SELECTED/RESOLVEDはadjudication_idが空。NO_ROLLのautomatic_result/resolution_reasonもUnified側にない。",
            "evidence": {"session_index": 475, "session_adjudication_id": "adj_e1cafc0922d745c8aea2f9e580102aba", "unified_event_ids": ["combat_event_000365", "combat_event_000367"]},
            "recommended_fix_layer": ["Unified Event Logging"],
        },
        {
            "finding_id": "final_battle_narrative_embellishment",
            "classification": "SOURCE_NARRATIVE_GAP",
            "root_cause": "LOGGING_GAP",
            "severity": "MINOR",
            "count": 1,
            "detail": "構造factはCORBITT_BODY_DESTROYEDでstateとも一致する一方、session[475]本文は『渾身の一撃、あるいは浄化の儀式』というsource factにない代替描写を追加する。human_readable_description自体は事実ベース。",
            "evidence": {"session_index": 475, "world_fact": "CORBITT_BODY_DESTROYED"},
            "recommended_fix_layer": ["Narrative Logging"],
        },
    ]

    severity_summary = Counter(finding["severity"] for finding in findings)
    classification_summary = Counter(finding["classification"] for finding in findings)
    critical_count = severity_summary["CRITICAL"]
    major_count = severity_summary["MAJOR"]

    gate = {
        "scenario_completed": bool(result.get("completed") and result.get("phase") == "clear"),
        "human_intervention_zero": result.get("human_interventions") == 0,
        "goal_completion_synchronized": bool(result.get("completed") and result.get("final_flags", {}).get("corbitt_defeated")),
        "critical_finding_zero": critical_count == 0,
        "source_contradiction_zero": classification_summary["SOURCE_CONTRADICTION"] == 0,
        "normalization_gap_zero": classification_summary["NORMALIZATION_GAP"] == 0,
        "rolled_check_incomplete_zero": len(incomplete_adjudications) == 0,
        "combat_without_termination_zero": len(dangling_combats) == 0,
        "normalization_source_contradiction_zero": len(warnings) == 0,
        "legacy_text_parse_zero": not any(
            event.get("san", {}).get("derived_from_legacy_text")
            for event in normalized["events"]
            if event.get("san")
        ),
        "traceability_one": traceability == 1.0,
    }
    passed = all(gate.values())
    evaluation_result = "PASS" if passed else "NEEDS_ITERATION"
    video_eligible = passed and critical_count == 0 and major_count == 0

    run_identity = {
        "session_id": result["session_id"],
        "core_version": {"git_commit": None, "working_tree_status": "NOT_A_GIT_WORKTREE"},
        "model_api": {
            "provider": "Ollama OpenAI-compatible local endpoint",
            "base_url": "http://localhost:11434/v1",
            "models": {"PL": "qwen2.5:14b", "KP": "qwen2.5:14b", "Judge": "qwen2.5:14b"},
            "temperature": "runtime default/configured",
            "seed": 2101,
            "context_limit": "model/runtime default",
            "retry_policy": "existing runtime policy",
            "timeout_seconds": 120,
            "max_tokens_per_call": 2048,
            "paid_api": False,
            "estimated_external_api_cost": 0,
        },
        "hashes": {
            "scenario_sha256": sha256(run / "runtime_data" / "datasets" / "corbitt_house.json"),
            "pcs_sha256": sha256(run / "runtime_data" / "pcs.json"),
            "normalized_session_sha256": sha256(args.normalized),
            "legacy_normalized_session_sha256": legacy_hash,
        },
        "recorded_preflight_hashes": {
            "scenario_sha256": "621e6a996f31a802132ed37b14a4005fa12049eaee225a353f8c7a11837610d6",
            "pc_sha256": "8b04641837d36786b541e2c3bbccead7b4ff025135b18765383c6e446861215e",
            "npc_sha256": "3c795e6098f97ae8e6240b9ed2412428ab332c91c30a1cb45b846d2f4628377c",
        },
    }
    write_json(run / "run_identity.json", run_identity)

    metrics = {
        "session_id": result["session_id"],
        "completion": {"completed": result["completed"], "phase": result["phase"], "pause_reason": result["pause_reason"]},
        "turns": result["turns"],
        "cycles": result["cycles"],
        "elapsed_seconds": result["elapsed_seconds"],
        "actions": sum(result.get("action_origins", {}).values()),
        "action_origins": result.get("action_origins"),
        "location_changes_normalized": event_counts["LOCATION_CHANGE"],
        "skill_checks_normalized": event_counts["SKILL_CHECK"],
        "dice_results_normalized": event_counts["DICE_RESULT"],
        "actual_san_checks": len(actual_san),
        "normalized_san_records": len(normalized_san),
        "luck_spends": len(luck_events),
        "combat_count": len(combats),
        "combat_actions_resolved": sum(len(combat["actions"]) for combat in combats.values()),
        "forced_actions": result["system_forced"],
        "guided_actions": result["system_guided"],
        "human_interventions": result["human_interventions"],
        "stagnation_recoveries": result["system_forced"],
        "maximum_stagnation": result["max_stagnation"],
        "repeated_actions": result["repeated_investigation"],
        "rejected_actions_unified": unified_event_counts["ACTION_BLOCKED"] + unified_event_counts["COMBAT_ACTION_REJECTED"],
        "goal_transitions": len(final_state["evaluator_state"].get("completed_objectives", [])),
        "resume_count": result.get("resume_count"),
        "segment_merge": result.get("segment_merge"),
    }
    write_json(run / "longrun_metrics.json", metrics)

    comparison = {
        "legacy_session": "corbitt_clear_001",
        "new_session": result["session_id"],
        "legacy": {
            "normalized_events": len(legacy["events"]),
            "completed": legacy.get("metadata", {}).get("completed"),
            "traceability": legacy_traceability,
            "skill_checks": legacy_audit["skill_check_summary"]["normalized_skill_check_records"],
            "combat_without_termination": 1,
            "critical_findings": legacy_gaps["severity_summary"]["CRITICAL"],
            "major_findings": legacy_gaps["severity_summary"]["MAJOR"],
            "known_wall_contradiction": True,
            "knife_combat_complete": False,
        },
        "new": {
            "normalized_events": len(normalized["events"]),
            "completed": result["completed"],
            "turns": result["turns"],
            "cycles": result["cycles"],
            "human_interventions": result["human_interventions"],
            "forced_actions": result["system_forced"],
            "traceability": traceability,
            "combat_without_termination": len(dangling_combats),
            "critical_findings": critical_count,
            "major_findings": major_count,
            "normalization_source_contradictions": len(warnings),
            "rolled_check_incomplete": len(incomplete_adjudications),
            "legacy_text_parse": 0,
            "known_wall_contradiction_recurred": True,
            "knife_combat_complete": not dangling_combats and any("7987" in combat_id for combat_id in combats),
        },
        "assessment": "Combat lifecycle and autonomous completion improved, but evidence completeness and narrative/state consistency did not meet the formal gate.",
    }
    write_json(run / "comparison_with_legacy.json", comparison)

    audit = {
        "audit": "LONG_AUTONOMOUS_RUN_EVIDENCE_AUDIT",
        "status": "PASS" if passed else "GAPS_FOUND",
        "long_autonomous_reevaluation": evaluation_result,
        "video_source_eligible": video_eligible,
        "scope": {
            "session_id": result["session_id"],
            "session_events": len(session),
            "unified_events": len(unified),
            "normalized_events": len(normalized["events"]),
        },
        "gate": gate,
        "summary": {
            "critical_findings": critical_count,
            "major_findings": major_count,
            "minor_findings": severity_summary["MINOR"],
            "source_contradictions": classification_summary["SOURCE_CONTRADICTION"],
            "source_gameplay_gaps": classification_summary["SOURCE_GAMEPLAY_GAP"],
            "source_logging_gaps": classification_summary["SOURCE_LOGGING_GAP"],
            "normalization_gaps": classification_summary["NORMALIZATION_GAP"],
            "normalization_source_contradictions": len(warnings),
            "rolled_check_incomplete": len(incomplete_adjudications),
            "unified_resolution_rolls": len(unified_roll_resolutions),
            "unified_resolution_rolls_incomplete": len(unified_incomplete_rolls),
            "combat_without_termination": len(dangling_combats),
            "legacy_text_parse": 0,
            "traceability": traceability,
        },
        "skill_check_integrity": {
            "session_structured_roll_records": len(session_rolls),
            "incomplete_adjudication_ids": incomplete_adjudications,
            "unified_resolution_records": len(unified_roll_resolutions),
            "unified_incomplete_event_ids": [event.get("event_id") for event in unified_incomplete_rolls],
        },
        "san_integrity": {"actual_checks": actual_san, "normalized_records": len(normalized_san), "misclassified_records": fake_san},
        "luck_integrity": luck_events,
        "combat_integrity": {"combats": combats, "dangling_combat_ids": dangling_combats},
        "normalizer": {"warning_count": len(warnings), "warning_fields": dict(warning_fields), "warnings": warnings, "traceability": traceability},
        "findings": findings,
    }
    write_json(run / "adjudication_evidence_report.json", audit)

    report = f"""# Long Autonomous Run Re-evaluation Report

## Result

- `LONG_AUTONOMOUS_REEVALUATION = {evaluation_result}`
- `VIDEO_SOURCE_ELIGIBLE = {str(video_eligible).lower()}`
- Gameplayは完走したが、正式PASS条件の証拠完全性とNarrative/State整合性を満たさない。
- CRITICAL {critical_count}件、MAJOR {major_count}件、MINOR {severity_summary['MINOR']}件。

## Run Identity

- Session: `{result['session_id']}`
- Seed: `{result['seed']}`
- Core: Git worktreeではないためcommit固定値なし。run開始時のruntime dataとhashを保存。
- Resume: {result.get('resume_count')}回。20 cycle地点のcheckpointから継続し、segment mergeは `{result.get('segment_merge', {}).get('status')}`。

## Model / API Configuration

- Provider: local Ollama OpenAI-compatible endpoint (`http://localhost:11434/v1`)
- PL / KP / Judge: `qwen2.5:14b`
- Timeout: 120秒、max_tokens: 2048
- 有料外部API: 不使用。外部API費用: 0。

## Scenario / PC Identity

- Runtime scenario SHA-256: `{run_identity['hashes']['scenario_sha256']}`
- Runtime PCs SHA-256: `{run_identity['hashes']['pcs_sha256']}`
- Preflight scenario hash: `{run_identity['recorded_preflight_hashes']['scenario_sha256']}`
- Preflight PC hash: `{run_identity['recorded_preflight_hashes']['pc_sha256']}`
- Preflight NPC hash: `{run_identity['recorded_preflight_hashes']['npc_sha256']}`

## Completion Result

- completed=true / phase=clear / ending=game_clear
- 33 cycles、99 turns、経過 {result['elapsed_seconds']:.3f}秒。
- 最終地点は `corbitt_basement_room2`。`corbitt_defeated=true`。

## Human Intervention

- human_intervention = 0（合格）
- system forced = {result['system_forced']}、system guided = {result['system_guided']}。
- system forcedは正式機能として記録され、完走判定とは分離した。

## Action / Progress Statistics

- actions = {metrics['actions']} ({json.dumps(metrics['action_origins'], ensure_ascii=False)})
- location changes(normalized) = {metrics['location_changes_normalized']}
- skill checks(normalized) = {metrics['skill_checks_normalized']}
- dice results(normalized) = {metrics['dice_results_normalized']}
- rejected actions = {metrics['rejected_actions_unified']}
- maximum stagnation = {metrics['maximum_stagnation']}
- combats = {metrics['combat_count']}、resolved combat actions = {metrics['combat_actions_resolved']}

## Adjudication Integrity

- FAIL。ROLL契約欠落は9 adjudication。
- Unifiedの実resolution ROLLは{len(unified_roll_resolutions)}件、そのうち`INVESTIGATION_ROLLED` 2件がtarget/roll/raw result欠落。
- 対抗STRは本文に双方の出目があるが、meta/Unifiedではrollとtargetがnullであり、構造契約を満たさない。

## Skill Check Integrity

- `rolled_check_incomplete = {len(incomplete_adjudications)}`（必須値0に不合格）。
- 主な対象: `corbitt_house`, `wall_planks`, `basement_door`, `basement_planks`, `rotting_floorboards`。

## SAN Integrity

- FAIL。実際に構造化されたSAN判定は0件。
- `living_room_clutter`成功payloadの`force_san_check(0/1D3)`が実行されていない。
- Normalizerは戦闘状態のSAN snapshotをSAN判定と誤認し、7件の不完全なSANレコードを生成した。
- このrunではSAN単一式と`after = before - loss`を実運用検証できない。

## Luck Integrity

- Sourceでは2件ともoriginal roll/target/raw failure/Luck before-after/final successを保持。
- 71 vs 65、Luck 6、45→39、final REGULAR_SUCCESS。
- 39 vs 32、Luck 7、39→32、final HARD_SUCCESS。
- Normalizerは適用前FAILUREと適用後SUCCESSを2件のsource contradictionとして誤分類したため、Normalizer gateはFAIL。

## Combat Integrity

- 2 combatとも`COMBAT_STARTED`→action→`COMBAT_ENDED`へ到達。
- `COMBAT_WITHOUT_TERMINATION = {len(dangling_combats)}`（合格）。
- ナイフ戦闘はattack 26/55、defense 99、damage 4、HP 1→0を保持。
- 最終戦はSPECIAL_OBJECTIVEのNO_ROLL解決を維持したが、Unified側のadjudication_idが空でSession側と結合できない。

## Wall Board Result

- FAIL。session[180-181]で破壊成功を描写するが、authoritative stateは`basement_planks_examined=true`だけで`broken=false`。
- session[189]の別STR対抗は失敗。session[439]のさらに別判定で初めて`basement_planks_broken: false→true`。
- `NARRATIVE_STATE_CONTRADICTION != 0`。

## Basement Door Result

- FAIL。session[161]内で「まだ閉ざされている」と「扉を開けた」が併存し、stateはexaminedだけ更新。
- session[164]/[247]でも閉鎖/開放の矛盾文を反復。実際のunlockはsession[167]の別判定。

## Knife Encounter Result

- Combat lifecycle自体は改善し、開始・攻防・damage・HP変化・終了を記録。
- ただし戦闘イベントのSAN状態フィールドがNormalizerでSAN checkに誤変換される。

## Knife State / Rediscovery Result

- FAIL。session[197]はflag=false時に「持っているナイフ」と「床に放置」を同時に描写。
- session[424]で初めて`has_corbitt_knife: false→true`。session[434]でダガー消滅を描写するが最終flagはtrueのまま。

## Final Battle Result

- `SPECIAL_OBJECTIVE_COMPLETED / CORBITT_BODY_DESTROYED`と`corbitt_defeated: false→true`は一致。
- Session側の事実ベースhuman_readable_descriptionも存在。
- Unified combat actionにはadjudication_idが伝播せず、NO_ROLL理由も欠落。
- 表示本文の「渾身の一撃、あるいは浄化の儀式」はsource factにない選択肢を加えている。

## Narrative / State Consistency

- FAIL。壁板、地下室扉、ナイフ所持/消滅で矛盾を確認。
- Core evaluatorの`inconsistency_count=0`はこれらを検出できていない。

## Goal Completion Sync

- PASS。`completed=true`, `phase=clear`, `pause_reason=game_clear`, `corbitt_defeated=true`が一致。

## Logging Integrity

- FAIL。9件のROLL判定で構造数値が欠落。
- 最終戦のSession/Unified adjudication linkも欠落。
- 時系列近接での推測補完は行わず、欠落として保持した。

## Normalizer Result

- Import/schema validationはPASS、events={len(normalized['events'])}、traceability={traceability:.1f}。
- `legacy_text_parse = 0`。
- `NORMALIZATION_SOURCE_CONTRADICTION = {len(warnings)}` のため正式gateはFAIL。
- 内訳: {json.dumps(dict(warning_fields), ensure_ascii=False)}。

## Evidence Audit

- `SOURCE_CONTRADICTION = {classification_summary['SOURCE_CONTRADICTION']}`
- `SOURCE_GAMEPLAY_GAP = {classification_summary['SOURCE_GAMEPLAY_GAP']}`
- `SOURCE_LOGGING_GAP = {classification_summary['SOURCE_LOGGING_GAP']}`
- `NORMALIZATION_GAP = {classification_summary['NORMALIZATION_GAP']}`
- `COMBAT_WITHOUT_TERMINATION = {len(dangling_combats)}`
- `rolled_check_incomplete = {len(incomplete_adjudications)}`
- `NORMALIZATION_SOURCE_CONTRADICTION = {len(warnings)}`
- `legacy_text_parse = 0`
- `traceability = {traceability:.1f}`

## Legacy Run Comparison

- 旧run: combat termination欠落1、CRITICAL 2、MAJOR 4、壁板矛盾あり。
- 新run: 自律完走・human 0・2戦闘完結は改善。
- 壁板矛盾は再発し、地下室扉/ナイフ状態の矛盾、ROLL証拠欠落、Normalizer矛盾22件が残る。

## Test / Validation Results

- Preflight Core: 545 PASS。
- Preflight Video Agent: 160 PASS。
- Normalizer import/schema validation: PASS。
- Segment merge: PASS、duplicate event 0、issues 0。
- 長編Evidence gate: FAIL。単体テスト合格と長時間自由運用の契約維持が一致しなかった。

## Cost / API Usage

- ローカルOllamaのみ。外部有料API費用0。

## Remaining Issues

1. シナリオのexamine clueとstate mutationを分離し、未開放時に開放済み本文を返さない。
2. opposed STRを含む全ROLLでactor/target双方の閾値と出目を構造化し、Unifiedへ同一adjudication_idで出す。
3. success payload内`force_san_check`を実行し、完全なSAN tupleを記録する。
4. Normalizerで成功度表現をcanonical化し、Luckのphase transitionを矛盾扱いしない。
5. 戦闘participant stateのSAN snapshotとSAN adjudicationをschema上で分離する。
6. knifeのowned/available/destroyed状態を明示し、消滅後にowned=trueを残さない。
7. final battleのadjudication_idをUnified combat lifecycleへ伝播する。

## Video Source Eligibility

- `VIDEO_SOURCE_ELIGIBLE = {str(video_eligible).lower()}`
- CRITICAL/MAJOR gapが残るため、正式Video Production Agent projectへは投入しない。今回のNormalizer処理は監査用stagingに限定した。
- M3状態は継続: `M3 PRESENTATION_NEEDS_ITERATION`, `M3 ASSET_INPUT_REQUIRED`, `M3 LICENSE_REVIEW_REQUIRED`, `HUMAN_REVIEW_REQUIRED`。
"""
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")

    print(json.dumps({"result": evaluation_result, "video_source_eligible": video_eligible, "gate": gate, "summary": audit["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
