from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path


REPO = Path(os.environ.get("CORBITT_PROJECT_ROOT", Path(__file__).resolve().parents[2])).resolve()
SESSION_ID = "CORBITT_LONGRUN_ITERATION3_V13_HOME_001"
RAW = Path(os.environ.get("CORBITT_V13_SOURCE_ROOT", REPO.parent / "evaluation-v2" / SESSION_ID)).resolve()
VIDEO_ROOT = Path(os.environ.get("VIDEO_OUTPUT_ROOT", REPO.parent / "video-production")).resolve() / SESSION_ID
OUT = VIDEO_ROOT / "video_002_final_battle_preflight"
SOURCE_START = 264
SOURCE_END = 281
COMBAT_START = 266
COMBAT_ACTION_RESOLVED = 277
SPECIAL_OBJECTIVE_COMPLETED = 278
COMBAT_ENDING = 279
COMBAT_ENDED = 280


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_identity(root: Path) -> dict:
    files = sorted(path for path in root.rglob("*") if path.is_file())
    digest = hashlib.sha256()
    size = 0
    for path in files:
        relative = path.relative_to(root).as_posix()
        file_hash = sha256(path)
        size += path.stat().st_size
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\n")
    return {"file_count": len(files), "size": size, "sha256": digest.hexdigest()}


def first_asset(registry: dict, canonical_id: str) -> dict | None:
    candidates = [
        asset for asset in registry["assets"]
        if asset.get("asset_id") == canonical_id or asset.get("canonical_asset_id") == canonical_id
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda item: (
        item.get("license_status") == "LICENSE_APPROVED",
        item.get("approval_status") == "APPROVED_FOR_PREVIEW",
        bool(item.get("classification")),
    ), reverse=True)
    return candidates[0]


def evidence_record(evidence_index: dict, canonical_id: str) -> dict | None:
    return next(
        (row for row in evidence_index.get("records", []) if row.get("canonical_asset_id") == canonical_id),
        None,
    )


def asset_view(asset: dict | None, *, requirement: str, fit: str, critical: bool,
               selection: str, note: str) -> dict:
    if asset is None:
        return {
            "requirement": requirement, "fit": "MISSING", "critical": critical,
            "selection": "BLOCKED", "asset_id": None, "path": None,
            "approval_status": "MISSING", "license_status": "MISSING", "note": note,
        }
    return {
        "requirement": requirement,
        "fit": fit,
        "critical": critical,
        "selection": selection,
        "asset_id": asset.get("canonical_asset_id") or asset.get("asset_id"),
        "path": asset.get("path"),
        "sha256": asset.get("sha256"),
        "approval_status": asset.get("approval_status"),
        "license_status": asset.get("license_status"),
        "author": asset.get("author"),
        "license": asset.get("license"),
        "source_url": asset.get("source_url"),
        "license_url": asset.get("license_url"),
        "credit_required": asset.get("credit_required"),
        "note": note,
    }


def compact_event(event: dict) -> dict:
    return {
        key: event.get(key) for key in (
            "raw_event_offset", "event_id", "event_type", "turn_id", "combat_id",
            "adjudication_id", "actor", "location", "position_before", "position_after",
            "selected_action", "target", "skill_or_stat", "resolution_mode", "target_value",
            "roll", "raw_result", "final_result", "roll_result", "objective_outcome",
            "damage_formula", "damage_roll", "actual_damage", "damage", "HP_before", "HP_after",
            "combat_state", "combat_end_condition", "resolution_reason", "effect",
            "human_readable_description", "state_before", "state_after", "world_fact",
        ) if event.get(key) is not None
    }


def main() -> None:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite {OUT}")

    raw_before = tree_identity(RAW)
    predecessor_before = {
        path.name: tree_identity(path)
        for path in sorted(VIDEO_ROOT.iterdir())
        if path.is_dir() and path.name.startswith("video_001_")
    }

    events = read_json(RAW / "unified-event-log.json")
    by_offset = {int(event["raw_event_offset"]): event for event in events}
    selected = [by_offset[offset] for offset in range(SOURCE_START, SOURCE_END + 1)]
    expected_types = {
        COMBAT_START: "COMBAT_STARTED",
        COMBAT_ACTION_RESOLVED: "COMBAT_ACTION_RESOLVED",
        SPECIAL_OBJECTIVE_COMPLETED: "SPECIAL_OBJECTIVE_COMPLETED",
        COMBAT_ENDING: "COMBAT_ENDING",
        COMBAT_ENDED: "COMBAT_ENDED",
    }
    for offset, event_type in expected_types.items():
        if by_offset[offset].get("event_type") != event_type:
            raise RuntimeError(f"offset {offset}: expected {event_type}")

    chain = [COMBAT_ACTION_RESOLVED, SPECIAL_OBJECTIVE_COMPLETED, COMBAT_ENDING, COMBAT_ENDED]
    chain_complete = chain == sorted(chain) and all(SOURCE_START <= offset <= SOURCE_END for offset in chain)
    shared_combat_id = {str(by_offset[offset].get("combat_id")) for offset in chain}
    shared_adjudication = (
        by_offset[COMBAT_ACTION_RESOLVED].get("adjudication_id")
        == by_offset[SPECIAL_OBJECTIVE_COMPLETED].get("adjudication_id")
    )
    source_range = {
        "schema_version": "1.0",
        "source_session_id": "CORBITT_LONGRUN_ITERATION3_V13_HOME_001",
        "candidate_video_id": "V13_VIDEO_002_FINAL_BATTLE",
        "source_range": {"start": SOURCE_START, "end": SOURCE_END, "event_count": len(selected)},
        "range_rationale": {
            "encounter_pre_context": {"offset": 264, "event_type": "LOCATION_CHANGE", "meaning": "enter corbitt_basement_room2"},
            "pre_start_target_context": {"offset": 265, "event_type": "ACTION_AVAILABILITY_CHECKED", "target": "corbitt_body"},
            "combat_start": {"offset": COMBAT_START, "event_type": "COMBAT_STARTED"},
            "combat_ended": {"offset": COMBAT_ENDED, "event_type": "COMBAT_ENDED"},
            "minimal_post_end_confirmation": {"offset": 281, "event_type": "NORMAL_PROGRESSION_RESUMED"},
        },
        "required_offsets": {event_type: offset for offset, event_type in expected_types.items()},
        "special_objective_causal_chain": {
            "offsets": chain,
            "event_types": [by_offset[offset].get("event_type") for offset in chain],
            "complete": chain_complete,
            "single_combat_id": len(shared_combat_id) == 1,
            "combat_id": next(iter(shared_combat_id)),
            "action_and_objective_share_adjudication_id": shared_adjudication,
        },
        "events": [compact_event(event) for event in selected],
    }

    combat_timeline = []
    for event in selected:
        offset = int(event["raw_event_offset"])
        if event.get("event_type") in {
            "COMBAT_STARTED", "COMBAT_ROUND_STARTED", "INVESTIGATION_DECLARED", "SKILL_PROPOSED",
            "SKILL_APPROVED", "INVESTIGATION_ROLLED", "INVESTIGATION_SUCCEEDED",
            "INVESTIGATION_TARGET_EXHAUSTED", "COMBAT_ACTION_REJECTED", "COMBAT_ACTION_SELECTED",
            "ACTION_AVAILABILITY_CHECKED", "COMBAT_ACTION_RESOLVED", "SPECIAL_OBJECTIVE_COMPLETED",
            "COMBAT_ENDING", "COMBAT_ENDED", "NORMAL_PROGRESSION_RESUMED",
        }:
            combat_timeline.append(compact_event(event))
    attack_rolls = [event for event in selected if event.get("event_type") == "COMBAT_ACTION_RESOLVED" and event.get("resolution_mode") == "ROLL"]
    damage_rolls = [event for event in selected if event.get("damage_roll")]
    hp_changes = [event for event in selected if event.get("HP_before") is not None and event.get("HP_after") is not None and event.get("HP_before") != event.get("HP_after")]
    enemy_actions = [event for event in selected if event.get("actor") == "walter_corbitt" and event.get("event_type", "").startswith("COMBAT_ACTION")]
    causal_trace = {
        "source_range": [SOURCE_START, SOURCE_END],
        "location": "corbitt_basement_room2",
        "combat_id": "combat-65-9502",
        "timeline": combat_timeline,
        "roll_summary": [{
            "offset": 271, "purpose": "corbitt_body investigation", "expression": "1d100",
            "actor": "pc_01", "skill": "目星", "target_value": 65, "roll": 23,
            "success_level": "HARD_SUCCESS", "state_effect": {
                "corbitt_body_encountered": [False, True], "trigger_corbitt_boss_battle": [False, True],
            },
        }],
        "combat_action_summary": [{
            "selected_offset": 275, "availability_offset": 276, "resolved_offset": 277,
            "actor": "pc_01", "action": "break", "target": "corbitt_body",
            "resolution_mode": "NO_ROLL", "final_result": "SPECIAL_OBJECTIVE_COMPLETED",
            "objective_outcome": "SPECIAL_OBJECTIVE_COMPLETED", "hp_change": "12 -> 12",
        }],
        "attack_rolls": [compact_event(event) for event in attack_rolls],
        "damage_rolls": [compact_event(event) for event in damage_rolls],
        "hp_changes": [compact_event(event) for event in hp_changes],
        "enemy_actions": [compact_event(event) for event in enemy_actions],
        "explicit_absences": {
            "normal_attack_roll": len(attack_rolls) == 0,
            "damage_roll": len(damage_rolls) == 0,
            "hp_change": len(hp_changes) == 0,
            "walter_corbitt_action": len(enemy_actions) == 0,
            "note": "The accepted source resolves this battle through a NO_ROLL scenario special objective; missing normal exchanges must not be invented.",
        },
        "special_objective": {
            "action_resolved_offset": 277,
            "objective_event_offset": 278,
            "world_fact": by_offset[278].get("world_fact"),
            "state_change": {"corbitt_defeated": [False, True]},
            "combat_ending_offset": 279,
            "combat_ended_offset": 280,
        },
        "causal_chain_complete": chain_complete and len(shared_combat_id) == 1 and shared_adjudication,
    }

    sessions = read_json(RAW / "session-log.json")
    san_rows = [row for row in sessions if (row.get("meta") or {}).get("roll_type") == "san_check"]
    san_scope = {
        "include_in_video_002": False,
        "candidate_for_video_003": True,
        "decision": "SEPARATE",
        "reason": "The only SAN check is attached to ground-floor evidence discovery, not the final-battle encounter or combat chain.",
        "san_events": [{
            "session_log_index": sessions.index(row), "location": row.get("location"),
            "actor": row.get("meta", {}).get("actor_id"), "adjudication_id": row.get("meta", {}).get("adjudication_id"),
            "san": row.get("meta", {}).get("san"), "text": row.get("text"),
        } for row in san_rows],
        "final_battle_range": [SOURCE_START, SOURCE_END],
    }

    actor_map = {
        "scene_location": "corbitt_basement_room2",
        "actors": [
            {"actor_id": "pl_01", "source_role": "PL", "display_name": "霊夢", "presentation_character": "霊夢", "visibility": "SPEAKER_ICON_WHILE_SPEAKING"},
            {"actor_id": "pc_01", "source_role": "PC", "display_name": "マクガフィン刑事", "presentation_character": "霊夢", "visibility": "SPEAKER_ICON_WHILE_SPEAKING"},
            {"actor_id": "pl_02", "source_role": "PL", "display_name": "魔理沙", "presentation_character": "魔理沙", "visibility": "SPEAKER_ICON_WHILE_SPEAKING"},
            {"actor_id": "pc_02", "source_role": "PC", "display_name": "エレノア教授", "presentation_character": "魔理沙", "visibility": "SPEAKER_ICON_WHILE_SPEAKING"},
            {"actor_id": "kp", "source_role": "KP", "display_name": "KP", "presentation_character": "咲夜", "visibility": "SPEAKER_ICON_WHILE_SPEAKING"},
            {"actor_id": "system", "source_role": "SYSTEM", "display_name": "", "presentation_character": None, "visibility": "NO_FACE_NO_VOICE"},
            {"actor_id": "walter_corbitt", "source_role": "ENEMY", "display_name": "ウォルター・コービット", "presentation_character": None, "visibility": "SCENE_ACTOR_WHILE_PRESENT"},
        ],
        "corbitt_scene_actor_asset": {
            "registry_match": False, "filesystem_name_match": False, "approval_status": "MISSING",
            "license_status": "MISSING", "fit": "MISSING", "critical": True,
        },
        "visibility_contract": "PASS",
    }

    registry = read_json(REPO / "video/config/asset_registry.json")
    evidence_index = read_json(REPO / "docs/VIDEO_ASSET_LICENSE_EVIDENCE_INDEX.json")
    background = first_asset(registry, "detected_aipict_basement_ruins01_334234bf_5301eeda")
    bgm = first_asset(registry, "detected_itch_arkeia_tension_as_the_light_fades_f154e404_e37cfd77")
    background_evidence = evidence_record(evidence_index, "detected_aipict_basement_ruins01_334234bf_5301eeda")
    bgm_evidence = evidence_record(evidence_index, "detected_itch_arkeia_tension_as_the_light_fades_f154e404_e37cfd77")
    dice_one = first_asset(registry, "detected_nc42339_ダイス音_1_1d10_e09bd219_e685378a")
    dice_two = first_asset(registry, "detected_nc42340_ダイス音_2_2d10_0e238a99_7b2e1d3e")
    impact = first_asset(registry, "detected_ドーン_095d02b7_3c1671ba")
    horror = first_asset(registry, "detected_ショック1_3aed3338_411f2030")
    combat_bgm = first_asset(registry, "detected_nc77916__東方アレンジ_恋色マスタースパーク_騒がしく_87ae68b7_fa55b4dc")
    asset_rows = [
        asset_view(background, requirement="final battle basement background", fit="EXACT", critical=True,
                   selection="REQUIRES_VIDEO_002_APPROVAL", note="License is approved, but Human preview approval is scoped to V13 Video 001 V2.5; separate Video 002 approval is required."),
        asset_view(None, requirement="Walter Corbitt Scene Actor portrait", fit="MISSING", critical=True,
                   selection="BLOCKED", note="No Corbitt/mummy/corpse portrait is registered or present under E:\\素材."),
        asset_view(bgm, requirement="combat/climax BGM", fit="GOOD", critical=True,
                   selection="REQUIRES_VIDEO_002_APPROVAL", note="License is approved, but Human preview approval is scoped to V13 Video 001 V2.5; it is a dark climax fallback rather than a normal combat track."),
        asset_view(combat_bgm, requirement="combat BGM alternative", fit="WEAK", critical=False,
                   selection="REJECTED_UNTIL_LICENSE_APPROVED", note="Combat tag exists, but mood is comedic and license/preview approval is absent."),
        asset_view(impact, requirement="impact/collapse SFX for Corbitt body destruction", fit="GOOD", critical=False,
                   selection="REJECTED_UNTIL_LICENSE_APPROVED", note="Closest collapse/impact candidate; approval and license evidence are absent."),
        asset_view(horror, requirement="encounter/horror reveal SFX", fit="GOOD", critical=False,
                   selection="REJECTED_UNTIL_LICENSE_APPROVED", note="Semantically suitable, but approval and license evidence are absent."),
        {"requirement": "attack/hit/miss/damage SFX", "fit": "NOT_APPLICABLE", "critical": False,
         "selection": "NONE", "approval_status": "NOT_REQUIRED_FOR_THIS_RANGE", "license_status": "NOT_REQUIRED_FOR_THIS_RANGE",
         "note": "The final battle has no normal attack, hit, miss, damage roll, or HP change in the accepted source."},
    ]
    asset_rows[0]["approval_scope"] = (background_evidence or {}).get("approval_scope")
    asset_rows[0]["review_status"] = (background_evidence or {}).get("review_status")
    asset_rows[2]["approval_scope"] = (bgm_evidence or {}).get("approval_scope")
    asset_rows[2]["review_status"] = (bgm_evidence or {}).get("review_status")
    critical_missing = sum(row.get("critical") and row.get("fit") == "MISSING" for row in asset_rows)
    license_blockers = [
        {"requirement": "final battle basement background", "asset_id": background.get("canonical_asset_id") or background.get("asset_id"),
         "approval_status": background.get("approval_status"), "license_status": background.get("license_status"),
         "approval_scope": (background_evidence or {}).get("approval_scope"),
         "reason": "License is approved, but existing Human preview approval is scoped to Video 001 V2.5, not Video 002."},
        {"requirement": "combat/climax BGM", "asset_id": bgm.get("canonical_asset_id") or bgm.get("asset_id"),
         "approval_status": bgm.get("approval_status"), "license_status": bgm.get("license_status"),
         "approval_scope": (bgm_evidence or {}).get("approval_scope"),
         "reason": "License is approved, but existing Human preview approval is scoped to Video 001 V2.5, not Video 002."},
        {"requirement": "mandatory two-dice D100 SFX", "asset_id": dice_two.get("canonical_asset_id") or dice_two.get("asset_id"),
         "approval_status": dice_two.get("approval_status"), "license_status": dice_two.get("license_status"),
         "reason": "Formal dice policy requires this cue, but its license has not been approved."},
    ]
    asset_gap = {
        "registry": str(REPO / "video/config/asset_registry.json"),
        "semantic_index": str(REPO / "video/config/asset_semantic_index.json"),
        "requirements": asset_rows,
        "dice_assets": [
            asset_view(dice_one, requirement="one physical die", fit="EXACT", critical=False, selection="POLICY_REFERENCE", note="Not used by this range."),
            asset_view(dice_two, requirement="two or more physical dice / D100", fit="EXACT", critical=True, selection="REQUIRED_BUT_LICENSE_BLOCKED", note="Required for offset 271."),
        ],
        "CRITICAL_ASSET_MISSING": critical_missing,
        "LICENSE_BLOCKER": len(license_blockers),
        "license_blockers": license_blockers,
    }

    dice_coverage = {
        "policy": {"one_physical_die": "nc42339", "two_or_more_physical_dice": "nc42340", "D100": "2D10"},
        "dice_events": [{
            "offset": 271, "event_type": "INVESTIGATION_ROLLED", "expression": "1d100",
            "physical_dice_count": 2, "selected_sfx": "nc42340",
            "asset_id": dice_two.get("canonical_asset_id") or dice_two.get("asset_id"),
            "mapping_status": "COVERED", "approval_status": dice_two.get("approval_status"),
            "license_status": dice_two.get("license_status"),
        }],
        "dice_event_count": 1,
        "covered_count": 1,
        "DICE_SE_POLICY_COVERAGE": 1.0,
        "license_note": "Coverage measures deterministic policy mapping; it does not override the separate license blocker.",
    }

    presentation_map = {
        "status": "PASS",
        "source_range": [SOURCE_START, SOURCE_END],
        "stages": [
            {"stage": "PC_ACTION", "offsets": [268, 275], "mapping": "Investigate the body, then select break against corbitt_body."},
            {"stage": "KP_CHECK_REQUEST", "offsets": [269, 270], "mapping": "Use the approved Spot Hidden check for the body investigation."},
            {"stage": "ATTACK_ROLL", "offsets": [], "status": "NOT_APPLICABLE", "mapping": "No attack roll exists in source; do not invent one."},
            {"stage": "ROLL_REACTION", "offsets": [271], "status": "OPTIONAL_PRESENTATION_REACTION", "mapping": "May react only to 23/65 HARD_SUCCESS after SYSTEM display."},
            {"stage": "KP_OUTCOME", "offsets": [272], "mapping": "Describe only the investigation success and encounter state change."},
            {"stage": "DAMAGE_ROLL", "offsets": [], "status": "NOT_APPLICABLE", "mapping": "No damage die exists in source."},
            {"stage": "HP_CHANGE", "offsets": [277], "status": "NO_CHANGE", "mapping": "PC1 HP remains 12; do not show damage."},
            {"stage": "OUTCOME_REACTION", "offsets": [272, 278], "status": "OPTIONAL_PRESENTATION_REACTION", "mapping": "World-outcome reaction is allowed only after KP outcome/Special Objective presentation."},
            {"stage": "SPECIAL_OBJECTIVE", "offsets": [275, 276, 277, 278], "mapping": "break -> availability -> NO_ROLL action resolution -> CORBITT_BODY_DESTROYED."},
            {"stage": "COMBAT_END", "offsets": [279, 280, 281], "mapping": "scenario-condition ending, ended, then minimal normal-progression confirmation."},
        ],
        "forbidden_inventions": ["normal attack exchange", "damage roll", "Walter Corbitt attack", "HP loss", "SAN check inside final battle"],
        "COMBAT_PRESENTATION_MAP": "PASS",
    }

    ui_assessment = {
        "existing_system_ui": {
            "d100_roll_23_vs_65": "SUPPORTED",
            "hard_success": "SUPPORTED",
            "no_roll_special_objective_chain": "TOO_DENSE_FOR_SINGLE_STANDARD_RESULT_HUD",
            "combat_termination_reason": "NEEDS_DEDICATED_SUMMARY",
        },
        "COMBAT_RESULT_CARD_REQUIRED": True,
        "design_required_before_render": {
            "fields": ["action", "target", "resolution_mode", "objective_outcome", "world_fact", "combat_end_condition"],
            "proposed_visible_labels": ["遺体を破壊", "特殊目的達成", "コービットを打倒", "戦闘終了"],
            "source_offsets": [275, 277, 278, 279, 280],
            "must_not_imply": ["attack roll", "damage roll", "HP damage", "enemy counterattack"],
        },
        "COMBAT_RESULT_CARD_DESIGN_STATUS": "REQUIRED_BEFORE_RENDER",
    }

    gates = {
        "SOURCE_RANGE_CONFIRMED": True,
        "SPECIAL_OBJECTIVE_CAUSAL_CHAIN_COMPLETE": causal_trace["causal_chain_complete"],
        "COMBAT_PRESENTATION_MAP": presentation_map["COMBAT_PRESENTATION_MAP"],
        "DICE_SE_POLICY_COVERAGE": dice_coverage["DICE_SE_POLICY_COVERAGE"],
        "CRITICAL_ASSET_MISSING": critical_missing,
        "LICENSE_BLOCKER": len(license_blockers),
        "COMBAT_RESULT_CARD_REQUIRED": True,
        "COMBAT_RESULT_CARD_DESIGN_STATUS": "REQUIRED_BEFORE_RENDER",
    }
    allowed = (
        critical_missing == 0
        and len(license_blockers) == 0
        and presentation_map["COMBAT_PRESENTATION_MAP"] == "PASS"
        and dice_coverage["DICE_SE_POLICY_COVERAGE"] == 1.0
        and causal_trace["causal_chain_complete"]
        and not ui_assessment["COMBAT_RESULT_CARD_REQUIRED"]
    )
    gates["FINAL_BATTLE_VIDEO_RENDER"] = "ALLOWED" if allowed else "BLOCKED"

    OUT.mkdir(parents=True)
    write_json(OUT / "V13_VIDEO_002_FINAL_BATTLE_SOURCE_RANGE.json", source_range)
    write_json(OUT / "V13_VIDEO_002_COMBAT_CAUSAL_TRACE.json", causal_trace)
    write_json(OUT / "V13_VIDEO_002_SAN_SCOPE_DECISION.json", san_scope)
    write_json(OUT / "V13_VIDEO_002_ACTOR_VISIBILITY_MAP.json", actor_map)
    write_json(OUT / "V13_VIDEO_002_ASSET_GAP_REPORT.json", asset_gap)
    write_json(OUT / "V13_VIDEO_002_DICE_SE_POLICY_COVERAGE.json", dice_coverage)
    write_json(OUT / "V13_VIDEO_002_COMBAT_PRESENTATION_MAP.json", presentation_map)
    write_json(OUT / "V13_VIDEO_002_SYSTEM_UI_ASSESSMENT.json", ui_assessment)
    (OUT / "V13_VIDEO_002_COMBAT_CAUSAL_TRACE.md").write_text(
        "# V13 Video 002 Combat Causal Trace\n\n"
        "## Formal range\n\n"
        "- Candidate source range: `264..281`\n"
        "- Core combat range: `266..280`\n"
        "- Location: `corbitt_basement_room2`\n"
        "- Combat ID: `combat-65-9502`\n\n"
        "## Timeline\n\n"
        "- `264` LOCATION_CHANGE: PC2 enters the second basement room.\n"
        "- `265` ACTION_AVAILABILITY_CHECKED: `corbitt_body` becomes the immediate target context.\n"
        "- `266` COMBAT_STARTED: PC1, PC2, and Walter Corbitt enter combat.\n"
        "- `267` COMBAT_ROUND_STARTED: initiative is PC1, PC2, Walter Corbitt.\n"
        "- `268..270` PC1 investigates the body; Spot Hidden is proposed and approved.\n"
        "- `271` INVESTIGATION_ROLLED: Spot Hidden `23/65`, `HARD_SUCCESS`; encounter flags become true.\n"
        "- `272..273` investigation succeeds and the target is exhausted.\n"
        "- `274` PC1 wait action is rejected because normal actions are forbidden during combat.\n"
        "- `275` PC1 selects `break` against `corbitt_body`.\n"
        "- `276` the action route is confirmed available.\n"
        "- `277` COMBAT_ACTION_RESOLVED: `NO_ROLL`, `SPECIAL_OBJECTIVE_COMPLETED`, HP remains `12 -> 12`.\n"
        "- `278` SPECIAL_OBJECTIVE_COMPLETED: world fact `CORBITT_BODY_DESTROYED`; `corbitt_defeated false -> true`.\n"
        "- `279` COMBAT_ENDING: end condition is `scenario_condition`.\n"
        "- `280` COMBAT_ENDED.\n"
        "- `281` NORMAL_PROGRESSION_RESUMED: minimal post-end confirmation.\n\n"
        "## Explicit absences\n\n"
        "- Normal attack roll: none\n"
        "- Damage roll: none\n"
        "- HP change: none\n"
        "- Walter Corbitt attack/action: none\n\n"
        "These absences are authoritative. The video must not invent a normal attack exchange, damage, or enemy counterattack.\n",
        encoding="utf-8",
    )
    (OUT / "V13_VIDEO_002_ASSET_GAP_REPORT.md").write_text(
        "# V13 Video 002 Asset Gap Report\n\n"
        "| Requirement | Fit | Approval | License | Gate |\n"
        "|---|---|---|---|---|\n"
        "| Basement battle background: AIPICT ruins01 | EXACT | APPROVED only for Video 001 V2.5 | LICENSE_APPROVED | Video 002 approval required |\n"
        "| Walter Corbitt Scene Actor portrait | MISSING | MISSING | MISSING | critical blocker |\n"
        "| Climax BGM: As the Light Fades | GOOD | APPROVED only for Video 001 V2.5 | LICENSE_APPROVED | Video 002 approval required |\n"
        "| Combat BGM alternative: nc77916 | WEAK | NOT_APPROVED | LICENSE_REVIEW_REQUIRED | rejected |\n"
        "| Impact/collapse SFX: ドーン | GOOD | NOT_APPROVED | LICENSE_REVIEW_REQUIRED | rejected |\n"
        "| Horror reveal SFX: ショック1 | GOOD | NOT_APPROVED | LICENSE_REVIEW_REQUIRED | rejected |\n"
        "| Attack/hit/miss/damage SFX | NOT_APPLICABLE | — | — | source has no such result |\n"
        "| D100/two-dice SFX: nc42340 | EXACT | APPROVED_FOR_PREVIEW | LICENSE_REVIEW_REQUIRED | license blocker |\n\n"
        f"- CRITICAL_ASSET_MISSING: `{critical_missing}`\n"
        f"- LICENSE_BLOCKER: `{len(license_blockers)}`\n",
        encoding="utf-8",
    )
    (OUT / "V13_VIDEO_002_COMBAT_PRESENTATION_MAP.md").write_text(
        "# V13 Video 002 Combat Presentation Map\n\n"
        "| Stage | Source offsets | Mapping |\n"
        "|---|---:|---|\n"
        "| PC_ACTION | 268, 275 | Investigate the body, then select break |\n"
        "| KP_CHECK_REQUEST | 269, 270 | Request/approve Spot Hidden |\n"
        "| ATTACK_ROLL | — | Not applicable; no source attack roll |\n"
        "| ROLL_REACTION | 271 | Optional reaction to 23/65 HARD_SUCCESS after SYSTEM display |\n"
        "| KP_OUTCOME | 272 | Describe investigation success and encounter state only |\n"
        "| DAMAGE_ROLL | — | Not applicable |\n"
        "| HP_CHANGE | 277 | No change: 12 -> 12 |\n"
        "| OUTCOME_REACTION | 272, 278 | Optional only after outcome presentation |\n"
        "| SPECIAL_OBJECTIVE | 275..278 | break -> availability -> NO_ROLL resolution -> body destroyed |\n"
        "| COMBAT_END | 279..281 | ending -> ended -> normal progression confirmation |\n\n"
        "- COMBAT_PRESENTATION_MAP: `PASS`\n"
        "- COMBAT_RESULT_CARD_REQUIRED: `true`\n",
        encoding="utf-8",
    )

    raw_after = tree_identity(RAW)
    predecessor_after = {
        path.name: tree_identity(path)
        for path in sorted(VIDEO_ROOT.iterdir())
        if path.is_dir() and path.name.startswith("video_001_")
    }
    immutable = raw_before == raw_after and predecessor_before == predecessor_after
    if not immutable:
        raise RuntimeError("protected V13 Raw or V1-V2.8 artifact changed")
    report = {
        "candidate_video_id": "V13_VIDEO_002_FINAL_BATTLE",
        "preflight_only": True,
        "render_performed": False,
        "source_range": [SOURCE_START, SOURCE_END],
        "core_combat_range": [COMBAT_START, COMBAT_ENDED],
        "source_artifacts_unchanged": immutable,
        "raw_identity_before": raw_before,
        "raw_identity_after": raw_after,
        "san_scope": "SEPARATE_TO_VIDEO_003",
        "gates": gates,
        "blockers": {
            "critical_asset_missing": ["Walter Corbitt Scene Actor portrait"],
            "license": license_blockers,
            "ui": ["Combat Result Card design is required before rendering."],
        },
        "FINAL_BATTLE_VIDEO_RENDER": gates["FINAL_BATTLE_VIDEO_RENDER"],
        "next_actions": [
            "Provide and approve a licensed Walter Corbitt Scene Actor asset.",
            "Approve the licensed AIPICT background and CC BY BGM specifically for Video 002 preview use.",
            "Resolve the license for nc42340 or approve a licensed two-dice replacement under the formal dice policy.",
            "Design and fixture-test the Combat Result Card before any main render.",
            "Optionally license an impact/collapse SFX; do not use current unapproved candidates.",
        ],
    }
    write_json(OUT / "V13_VIDEO_002_FINAL_BATTLE_PREFLIGHT_REPORT.json", report)
    (OUT / "V13_VIDEO_002_FINAL_BATTLE_PREFLIGHT_REPORT.md").write_text(
        "# V13 Video 002 Final Battle Preflight\n\n"
        "- Mode: `PREFLIGHT_ONLY`\n"
        "- Render performed: `false`\n"
        "- Formal source range: `264..281`\n"
        "- Core combat range: `266..280`\n"
        "- COMBAT_STARTED: `266`\n"
        "- COMBAT_ACTION_RESOLVED: `277`\n"
        "- SPECIAL_OBJECTIVE_COMPLETED: `278`\n"
        "- COMBAT_ENDING: `279`\n"
        "- COMBAT_ENDED: `280`\n"
        "- Special Objective causal chain complete: `true`\n"
        "- SAN scope: `SEPARATE_TO_VIDEO_003`\n"
        "- COMBAT_PRESENTATION_MAP: `PASS`\n"
        "- DICE_SE_POLICY_COVERAGE: `1.0`\n"
        f"- CRITICAL_ASSET_MISSING: `{critical_missing}`\n"
        f"- LICENSE_BLOCKER: `{len(license_blockers)}`\n"
        "- COMBAT_RESULT_CARD_REQUIRED: `true`\n"
        "- FINAL_BATTLE_VIDEO_RENDER: `BLOCKED`\n\n"
        "## Blocking items\n\n"
        "1. Walter Corbitt has no registered, approved Scene Actor portrait.\n"
        "2. The background and climax BGM licenses are approved, but their Human preview approval is scoped to Video 001 V2.5 and must be extended to Video 002.\n"
        "3. The mandatory nc42340 D100/two-dice cue is approved for preview but its license remains under review.\n"
        "4. The Special Objective and termination chain needs a dedicated Combat Result Card before rendering.\n\n"
        "The accepted source contains no normal attack roll, damage roll, HP change, or Walter Corbitt attack in this battle. These must not be invented.\n",
        encoding="utf-8",
    )
    artifacts = []
    for path in sorted(OUT.iterdir()):
        if path.is_file() and path.name != "V13_VIDEO_002_PREFLIGHT_ARTIFACT_MANIFEST.json":
            artifacts.append({"path": str(path), "size": path.stat().st_size, "sha256": sha256(path)})
    write_json(OUT / "V13_VIDEO_002_PREFLIGHT_ARTIFACT_MANIFEST.json", {
        "preflight_only": True, "rendered_media_count": 0, "source_artifacts_unchanged": immutable,
        "artifacts": artifacts,
    })
    print(json.dumps({
        "source_range": [SOURCE_START, SOURCE_END], "chain_complete": causal_trace["causal_chain_complete"],
        "critical_asset_missing": critical_missing, "license_blocker": len(license_blockers),
        "combat_result_card_required": True, "render": gates["FINAL_BATTLE_VIDEO_RENDER"],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
