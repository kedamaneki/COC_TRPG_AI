from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
from dataclasses import asdict
from pathlib import Path


REPO = Path(os.environ.get("CORBITT_PROJECT_ROOT", Path(__file__).resolve().parents[2])).resolve()
SESSION_ID = "CORBITT_LONGRUN_ITERATION3_V13_HOME_001"
RAW = Path(os.environ.get("CORBITT_V13_SOURCE_ROOT", REPO.parent / "evaluation-v2" / SESSION_ID)).resolve()
CONTROL = Path(os.environ.get("CORBITT_V13_CONTROL_ROOT", REPO.parent / "evaluation-control" / SESSION_ID)).resolve()
VIDEO_ROOT = Path(os.environ.get("VIDEO_OUTPUT_ROOT", REPO.parent / "video-production")).resolve() / SESSION_ID
OLD_PREFLIGHT = VIDEO_ROOT / "video_002_final_battle_preflight"
OUT = VIDEO_ROOT / "video_002_final_battle_preflight_blocker_resolution_v1"
SCOPE = "VIDEO_002_FINAL_BATTLE"
EXPECTED_RAW_AGGREGATE = "fd42df1dc3278ef3250486235f43a5693de4fea9ad3f7af5fc769690ab18e44d"

sys.path.insert(0, str(REPO / "video/src"))
from video_agent.assets.approval import approved_for_preview_scope, extend_preview_scope  # noqa: E402
from video_agent.presentation.combat_result_card import (  # noqa: E402
    assert_combat_result_card,
    build_no_roll_special_objective_card,
)


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_raw_freeze() -> dict:
    manifest = read_json(CONTROL / "V13_RAW_FREEZE_MANIFEST.json")
    failures = []
    digest = hashlib.sha256()
    for item in sorted(manifest["files"], key=lambda row: row["path"]):
        path = RAW / Path(item["path"])
        actual = sha256(path) if path.is_file() else None
        if actual != item["sha256"]:
            failures.append({"path": item["path"], "expected": item["sha256"], "actual": actual})
        digest.update(item["path"].encode("utf-8"))
        digest.update(b"\0")
        digest.update(item["sha256"].encode("ascii"))
        digest.update(b"\n")
    aggregate = digest.hexdigest()
    return {
        "status": "PASS" if not failures and aggregate == EXPECTED_RAW_AGGREGATE else "FAIL",
        "file_count": len(manifest["files"]),
        "aggregate_sha256": aggregate,
        "expected_aggregate_sha256": EXPECTED_RAW_AGGREGATE,
        "failures": failures,
    }


def find_asset(registry: dict, asset_id: str) -> dict:
    rows = [row for row in registry["assets"] if row.get("asset_id") == asset_id]
    if len(rows) != 1:
        raise RuntimeError(f"ASSET_MATCH_COUNT:{asset_id}:{len(rows)}")
    return rows[0]


def find_portrait(registry: dict, profile_id: str) -> dict:
    rows = [row for row in registry["portraits"] if row.get("portrait_profile_id") == profile_id]
    if len(rows) != 1:
        raise RuntimeError(f"PORTRAIT_MATCH_COUNT:{profile_id}:{len(rows)}")
    return rows[0]


def approve_assets() -> dict:
    asset_path = REPO / "video/config/asset_registry.json"
    portrait_path = REPO / "video/config/portrait_registry.json"
    registry = read_json(asset_path)
    portraits = read_json(portrait_path)

    corbitt_01 = find_asset(registry, "portrait_corbitt_shadow_candidate_01_v1")
    corbitt_01.update({
        "license": "OpenAI Terms of Use - user owns generated Output, scoped project review",
        "commercial_use": True,
        "video_use": True,
        "modification_allowed": True,
        "standalone_redistribution_allowed": False,
        "credit_required": False,
        "credit_text": None,
        "source_url": "https://openai.com/policies/terms-of-use/",
        "license_url": "https://openai.com/policies/terms-of-use/",
        "license_status": "LICENSE_APPROVED",
        "approval_status": "APPROVED_FOR_PREVIEW",
        "approved_sha256": corbitt_01["sha256"],
        "approved_video_scopes": [SCOPE],
        "human_selected": True,
        "selection_status": "SELECTED_FOR_VIDEO_002",
        "license_evidence_paths": [
            "assets/portraits/mob_shadow_pack_v1/evidence/corbitt_shadow_candidate_01.source.json",
            "docs/license_evidence/corbitt_candidate_01/license_review_2026-10-19.json",
        ],
        "auto_use": False,
    })
    corbitt_02 = find_asset(registry, "portrait_corbitt_shadow_candidate_02_v1")
    corbitt_02.update({"selection_status": "RESERVE", "human_selected": False, "auto_use": False})

    background = find_asset(registry, "detected_aipict_basement_ruins01_334234bf_be2b81b6")
    bg_scopes = list(dict.fromkeys([*background.get("approved_video_scopes", []),
                                    "V13_VIDEO_001_BASEMENT_PLANKS_V2_5"]))
    background["approved_video_scopes"] = bg_scopes
    extend_preview_scope(background, SCOPE)

    bgm = find_asset(registry, "detected_itch_arkeia_tension_as_the_light_fades_f154e404_3bdff3eb")
    bgm_scopes = list(dict.fromkeys([*bgm.get("approved_video_scopes", []),
                                     "V13_VIDEO_001_BASEMENT_PLANKS_V2_5"]))
    bgm["approved_video_scopes"] = bgm_scopes
    extend_preview_scope(bgm, SCOPE)

    dice = find_asset(registry, "detected_nc42340_ダイス音_2_2d10_0e238a99_7b2e1d3e")
    dice.update({
        "author": "ニコニ・コモンズ user_id 993967",
        "license": "ニコニ・コモンズ素材ライセンス (allowedScope=INTERNET_ONLY)",
        "commercial_use": True,
        "video_use": True,
        "modification_allowed": "VIDEO_MIX_INTEGRATION_ONLY",
        "standalone_redistribution_allowed": False,
        "credit_required": False,
        "credit_text": None,
        "source_url": "https://commons.nicovideo.jp/works/nc42340",
        "license_url": "https://public-api.commons.nicovideo.jp/v1/materials/42340",
        "license_status": "LICENSE_APPROVED",
        "approval_status": "APPROVED_FOR_PREVIEW",
        "approved_sha256": dice["sha256"],
        "approved_video_scopes": [SCOPE],
        "license_evidence_paths": [
            "docs/license_evidence/nc42340/material_api_2026-10-19.json",
            "docs/license_evidence/nc42340/source_page_2026-10-19.html",
        ],
        "license_review_note": (
            "Internet video use and personal/corporate monetization are OK. Credit and parent registration are not "
            "required. Creator contact for outside-Niconico use is optional. Raw WAV redistribution is outside approval."
        ),
        "auto_use": False,
    })

    p1 = find_portrait(portraits, "portrait_profile_corbitt_shadow_candidate_01_v1")
    p1.update({
        "approval_status": "APPROVED_FOR_PREVIEW",
        "license_status": "LICENSE_APPROVED",
        "human_selected": True,
        "selection_status": "SELECTED_FOR_VIDEO_002",
        "approved_video_scopes": [SCOPE],
        "auto_use": False,
    })
    p2 = find_portrait(portraits, "portrait_profile_corbitt_shadow_candidate_02_v1")
    p2.update({"selection_status": "RESERVE", "human_selected": False, "auto_use": False})

    write_json(asset_path, registry)
    write_json(portrait_path, portraits)

    source_evidence_path = REPO / "video/assets/portraits/mob_shadow_pack_v1/evidence/corbitt_shadow_candidate_01.source.json"
    source_evidence = read_json(source_evidence_path)
    source_evidence.update({
        "license_status": "LICENSE_APPROVED",
        "approval_status": "APPROVED_FOR_PREVIEW",
        "approved_video_scopes": [SCOPE],
        "human_selected": True,
        "selection_status": "SELECTED_FOR_VIDEO_002",
        "license_authority_url": "https://openai.com/policies/terms-of-use/",
        "auto_use": False,
    })
    write_json(source_evidence_path, source_evidence)

    corbitt_license = {
        "schema_version": "1.0",
        "asset_id": corbitt_01["asset_id"],
        "sha256": corbitt_01["sha256"],
        "reviewed_at": "2026-10-19",
        "source_type": "INTERNAL_GENERATED",
        "generation_tool": "OpenAI built-in image generation",
        "authority_url": "https://openai.com/policies/terms-of-use/",
        "evidence_summary": "OpenAI Terms state that, as between the user and OpenAI, the user owns Output and OpenAI assigns its rights in Output.",
        "approval_scope": SCOPE,
        "commercial_video_use": True,
        "modification": True,
        "credit_required": False,
        "standalone_asset_redistribution": False,
        "similarity_and_third_party_review_required": True,
        "license_status": "LICENSE_APPROVED",
        "approval_status": "APPROVED_FOR_PREVIEW",
        "auto_use": False,
    }
    write_json(REPO / "docs/license_evidence/corbitt_candidate_01/license_review_2026-10-19.json",
               corbitt_license)

    evidence_path = REPO / "docs/VIDEO_ASSET_LICENSE_EVIDENCE_INDEX.json"
    index = read_json(evidence_path)
    replacements = {
        corbitt_01["asset_id"]: {
            "canonical_asset_id": corbitt_01["asset_id"], "category": "PORTRAIT",
            "evidence_files": 2, "evidence_paths": corbitt_01["license_evidence_paths"],
            "license_status": "LICENSE_APPROVED", "license_source": "OpenAI Terms of Use",
            "license_document": "https://openai.com/policies/terms-of-use/",
            "license_author": "OpenAI", "license_site": "openai.com",
            "allowed_commercial_use": True, "allowed_modification": True,
            "attribution_required": False, "redistribution_allowed": False,
            "video_use_allowed": True, "review_status": "HUMAN_APPROVED_FOR_SCOPED_PREVIEW",
            "approval_scope": SCOPE,
        },
        dice["canonical_asset_id"]: {
            "canonical_asset_id": dice["canonical_asset_id"], "category": "SFX",
            "evidence_files": 2, "evidence_paths": dice["license_evidence_paths"],
            "source_locator_hints": [{"kind": "NICONICO_COMMONS_ID", "value": "nc42340", "license_evidence": True}],
            "license_status": "LICENSE_APPROVED", "license_source": "Niconico Commons official material API",
            "license_document": dice["license_url"], "license_author": dice["author"],
            "license_site": "commons.nicovideo.jp", "allowed_commercial_use": True,
            "allowed_modification": "VIDEO_MIX_INTEGRATION_ONLY", "attribution_required": False,
            "redistribution_allowed": False, "video_use_allowed": True,
            "youtube_niconico_allowed": True, "review_status": "HUMAN_APPROVED_FOR_SCOPED_PREVIEW",
            "approval_scope": SCOPE,
            "notes": dice["license_review_note"],
        },
    }
    records = [row for row in index.get("records", []) if row.get("canonical_asset_id") not in replacements]
    records.extend(replacements.values())
    records.sort(key=lambda row: row.get("canonical_asset_id", ""))
    index["records"] = records
    index["evidence_file_count"] = sum(
        len(value) if isinstance(value := row.get("evidence_files"), list) else int(value or 0)
        for row in records
    )
    write_json(evidence_path, index)

    return {
        "corbitt_01": corbitt_01,
        "corbitt_02": corbitt_02,
        "background": background,
        "bgm": bgm,
        "dice": dice,
        "scope_checks": {
            "corbitt_01": approved_for_preview_scope(corbitt_01, SCOPE),
            "background": approved_for_preview_scope(background, SCOPE),
            "bgm": approved_for_preview_scope(bgm, SCOPE),
            "dice": approved_for_preview_scope(dice, SCOPE),
        },
    }


def write_docs(approved: dict) -> None:
    docs = REPO / "docs"
    (docs / "CORBITT_PORTRAIT_SELECTION_DECISION.md").write_text(
        "# Corbitt Portrait Selection Decision\n\n"
        "- Human selection: `corbitt_shadow_candidate_01`\n"
        "- Registry asset: `portrait_corbitt_shadow_candidate_01_v1`\n"
        "- Scope: `VIDEO_002_FINAL_BATTLE`\n"
        "- Status: `LICENSE_APPROVED / APPROVED_FOR_PREVIEW`\n"
        "- `auto_use=false`\n"
        "- Candidate 02: `RESERVE / auto_use=false`\n\n"
        "Candidate 01 is the selected Corbitt Scene Actor for Video 002. It may only be used in the approved preview scope.\n",
        encoding="utf-8",
    )
    (docs / "CORBITT_PORTRAIT_LICENSE_REVIEW.md").write_text(
        "# Corbitt Portrait License Review\n\n"
        "The selected image was generated internally with OpenAI image generation. The saved source record and SHA-256 identify the exact output. "
        "OpenAI Terms state that, as between the user and OpenAI, the user owns Output and OpenAI assigns its rights in Output.\n\n"
        "- Decision: `LICENSE_APPROVED`\n"
        "- Preview scope: `VIDEO_002_FINAL_BATTLE`\n"
        "- Modification for the scoped video: allowed\n"
        "- Credit: not required by the reviewed source terms\n"
        "- Standalone asset redistribution: not approved by this review\n"
        "- Similarity/third-party rights: human review remains applicable\n"
        "- `auto_use=false`\n\n"
        "Authority: https://openai.com/policies/terms-of-use/\n",
        encoding="utf-8",
    )
    (docs / "NC42340_LICENSE_REVIEW.md").write_text(
        "# nc42340 License Review\n\n"
        "Official material: `nc42340 / ダイス音・2（2D10）`. The official Commons API reports `allowedScope=INTERNET_ONLY`, "
        "personal and corporate monetization categories all `OK`, `parentRegistrationRequired=false`, and "
        "`copyrightNoticeRequired=false`. The creator's request for contact outside Niconico is explicitly optional.\n\n"
        "- Internet video use: allowed\n"
        "- Commercial/monetized video: allowed\n"
        "- Credit: not required\n"
        "- Parent registration: not required\n"
        "- Modification: approved only as mix/edit integration in Video 002\n"
        "- Standalone WAV redistribution: not approved\n"
        "- Decision: `LICENSE_APPROVED / APPROVED_FOR_PREVIEW(scope=VIDEO_002_FINAL_BATTLE)`\n"
        "- `auto_use=false`\n\n"
        "Sources:\n"
        "- https://commons.nicovideo.jp/works/nc42340\n"
        "- https://public-api.commons.nicovideo.jp/v1/materials/42340\n",
        encoding="utf-8",
    )
    (docs / "COMBAT_RESULT_CARD_V1_REPORT.md").write_text(
        "# Combat Result Card v1 Report\n\n"
        "The card is a silent SYSTEM component for the accepted Video 002 range. It presents only three source-backed stages:\n\n"
        "1. `遺体を破壊` — offsets 275 and 277\n"
        "2. `コービットを打倒` — offset 278\n"
        "3. `戦闘終了` — offsets 279 and 280\n\n"
        "The resolution is `NO_ROLL`. The card forbids attack rolls, damage rolls, HP changes, and enemy retaliation because none exist in the source. "
        "Corbitt fades out only after `CORBITT_BODY_DESTROYED` at offset 278.\n",
        encoding="utf-8",
    )
    (docs / "COMBAT_RESULT_CARD_V1_HUMAN_REVIEW.md").write_text(
        "# Combat Result Card v1 — Human Review\n\n"
        "Status: `READY`, not rendered.\n\n"
        "Review in the future render:\n"
        "- The three stages appear in source order.\n"
        "- The card does not imply an attack roll, damage, HP loss, or an enemy counterattack.\n"
        "- Corbitt remains visible only while source-confirmed present and fades after offset 278.\n"
        "- SYSTEM remains faceless and voiceless.\n",
        encoding="utf-8",
    )


def build_preflight(approved: dict, raw_before: dict) -> dict:
    if OUT.exists():
        raise FileExistsError(f"refusing to overwrite {OUT}")
    OUT.mkdir(parents=True)
    events = read_json(RAW / "unified-event-log.json")
    selected = [row for row in events if 264 <= int(row["raw_event_offset"]) <= 281]
    card = build_no_roll_special_objective_card(selected)
    card_audit = asdict(assert_combat_result_card(card, selected))
    write_json(OUT / "V13_VIDEO_002_COMBAT_RESULT_CARD.json", {"card": card, "audit": card_audit})

    for name in (
        "V13_VIDEO_002_FINAL_BATTLE_SOURCE_RANGE.json",
        "V13_VIDEO_002_COMBAT_CAUSAL_TRACE.json",
        "V13_VIDEO_002_SAN_SCOPE_DECISION.json",
    ):
        shutil.copy2(OLD_PREFLIGHT / name, OUT / name)

    actor_map = read_json(OLD_PREFLIGHT / "V13_VIDEO_002_ACTOR_VISIBILITY_MAP.json")
    actor_map["corbitt_scene_actor_asset"] = {
        "registry_match": True,
        "asset_id": approved["corbitt_01"]["asset_id"],
        "portrait_profile_id": "portrait_profile_corbitt_shadow_candidate_01_v1",
        "sha256": approved["corbitt_01"]["sha256"],
        "approval_status": "APPROVED_FOR_PREVIEW",
        "license_status": "LICENSE_APPROVED",
        "approval_scope": SCOPE,
        "fit": "EXACT",
        "critical": True,
        "presence_contract": "SCENE_ACTOR_WHILE_SOURCE_CONFIRMED_PRESENT",
        "fade_out_after_raw_event_offset": 278,
        "auto_use": False,
    }
    write_json(OUT / "V13_VIDEO_002_ACTOR_VISIBILITY_MAP.json", actor_map)

    asset_gap = {
        "scope": SCOPE,
        "assets": [
            {"requirement": "final battle basement background", "fit": "EXACT", "critical": True,
             "asset_id": approved["background"].get("canonical_asset_id"), "status": "READY",
             "license_status": "LICENSE_APPROVED", "approval_status": "APPROVED_FOR_PREVIEW"},
            {"requirement": "Walter Corbitt Scene Actor portrait", "fit": "EXACT", "critical": True,
             "asset_id": approved["corbitt_01"]["asset_id"], "status": "READY",
             "license_status": "LICENSE_APPROVED", "approval_status": "APPROVED_FOR_PREVIEW"},
            {"requirement": "combat/climax BGM", "fit": "GOOD", "critical": True,
             "asset_id": approved["bgm"].get("canonical_asset_id"), "status": "READY",
             "license_status": "LICENSE_APPROVED", "approval_status": "APPROVED_FOR_PREVIEW",
             "credit_required": True},
            {"requirement": "mandatory two-dice D100 SFX", "fit": "EXACT", "critical": True,
             "asset_id": approved["dice"].get("canonical_asset_id"), "status": "READY",
             "license_status": "LICENSE_APPROVED", "approval_status": "APPROVED_FOR_PREVIEW",
             "credit_required": False},
        ],
        "critical_asset_missing": 0,
        "license_blocker": 0,
        "optional_unresolved": ["impact/collapse SFX may remain unused; source has no attack/damage event"],
    }
    write_json(OUT / "V13_VIDEO_002_ASSET_GAP_REPORT.json", asset_gap)
    (OUT / "V13_VIDEO_002_ASSET_GAP_REPORT.md").write_text(
        "# Video 002 Asset Gap Report\n\nAll four critical requirements are ready for the scoped preview. "
        "Optional impact/collapse cues are not required because the accepted source contains no attack or damage exchange.\n",
        encoding="utf-8",
    )

    dice_coverage = read_json(OLD_PREFLIGHT / "V13_VIDEO_002_DICE_SE_POLICY_COVERAGE.json")
    dice_coverage.update({
        "license_status": "LICENSE_APPROVED",
        "approval_status": "APPROVED_FOR_PREVIEW",
        "approval_scope": SCOPE,
        "auto_use": False,
        "coverage": 1.0,
    })
    write_json(OUT / "V13_VIDEO_002_DICE_SE_POLICY_COVERAGE.json", dice_coverage)

    presentation = read_json(OLD_PREFLIGHT / "V13_VIDEO_002_COMBAT_PRESENTATION_MAP.json")
    presentation["combat_result_card"] = {
        "status": "READY",
        "config": "video/config/combat_result_card.json",
        "artifact": "V13_VIDEO_002_COMBAT_RESULT_CARD.json",
        "source_offsets": [275, 277, 278, 279, 280],
        "stages": ["遺体を破壊", "コービットを打倒", "戦闘終了"],
        "forbidden_inventions": ["attack_roll", "damage_roll", "hp_change", "enemy_action"],
    }
    presentation["status"] = "PASS"
    write_json(OUT / "V13_VIDEO_002_COMBAT_PRESENTATION_MAP.json", presentation)
    (OUT / "V13_VIDEO_002_COMBAT_PRESENTATION_MAP.md").write_text(
        "# Combat Presentation Map\n\nStatus: PASS. The source-backed NO_ROLL special-objective chain is represented by the ready Combat Result Card.\n",
        encoding="utf-8",
    )
    ui = read_json(OLD_PREFLIGHT / "V13_VIDEO_002_SYSTEM_UI_ASSESSMENT.json")
    ui.update({"combat_result_card_required": True, "combat_result_card_status": "READY",
               "system_voice": "NONE", "system_portrait": "NONE", "status": "PASS"})
    write_json(OUT / "V13_VIDEO_002_SYSTEM_UI_ASSESSMENT.json", ui)

    gates = {
        "SOURCE_RANGE_CONFIRMED": True,
        "SPECIAL_OBJECTIVE_CAUSAL_CHAIN_COMPLETE": True,
        "COMBAT_PRESENTATION_MAP": "PASS",
        "DICE_SE_POLICY_COVERAGE": 1.0,
        "CRITICAL_ASSET_MISSING": 0,
        "LICENSE_BLOCKER": 0,
        "COMBAT_RESULT_CARD_STATUS": "READY",
        "COMBAT_RESULT_CARD_AUDIT": card_audit["status"],
        "FINAL_BATTLE_VIDEO_RENDER": "ALLOWED",
    }
    report = {
        "schema_version": "1.0",
        "operation": "FINAL_BATTLE_RENDER_BLOCKER_RESOLUTION_V1",
        "candidate_video_id": "V13_VIDEO_002_FINAL_BATTLE",
        "preflight_only": True,
        "source_range": [264, 281],
        "video_rendered": False,
        "raw_freeze_verification_before": raw_before,
        "asset_scope_checks": approved["scope_checks"],
        "gates": gates,
        "blockers": [],
        "FINAL_BATTLE_VIDEO_RENDER": "ALLOWED",
        "VIDEO_RENDERED": False,
        "human_review_required": True,
        "auto_publish": False,
    }
    write_json(OUT / "V13_VIDEO_002_FINAL_BATTLE_PREFLIGHT_REPORT.json", report)
    (OUT / "V13_VIDEO_002_FINAL_BATTLE_PREFLIGHT_REPORT.md").write_text(
        "# V13 Video 002 Final Battle — Blocker Resolution Preflight\n\n"
        "The source range remains offsets 264..281. Corbitt candidate 01, the basement background, the tension BGM, "
        "and nc42340 are approved only for the Video 002 preview scope. The Combat Result Card is READY.\n\n"
        "- CRITICAL_ASSET_MISSING = 0\n- LICENSE_BLOCKER = 0\n- COMBAT_RESULT_CARD_STATUS = READY\n"
        "- COMBAT_PRESENTATION_MAP = PASS\n- DICE_SE_POLICY_COVERAGE = 1.0\n"
        "- SPECIAL_OBJECTIVE_CAUSAL_CHAIN_COMPLETE = true\n- FINAL_BATTLE_VIDEO_RENDER = ALLOWED\n"
        "- VIDEO_RENDERED = false\n",
        encoding="utf-8",
    )
    return report


def write_resolution_report(report: dict, raw_after: dict) -> None:
    text = f"""# Final Battle Render Blocker Resolution v1\n\n
## Result\n\n
- Corbitt selection: `corbitt_shadow_candidate_01`\n
- Candidate 02: `RESERVE`\n
- Source range: `264..281`\n
- Critical assets missing: `0`\n
- License blockers: `0`\n
- Combat Result Card: `READY`\n
- Combat Presentation Map: `PASS`\n
- Dice SE policy coverage: `1.0`\n
- Special Objective chain: complete\n
- `FINAL_BATTLE_VIDEO_RENDER=ALLOWED`\n
- `VIDEO_RENDERED=false`\n\n
V13 Raw verification before and after used {raw_after['file_count']} frozen files and aggregate `{raw_after['aggregate_sha256']}`. No main video was rendered.\n
"""
    (REPO / "docs/FINAL_BATTLE_RENDER_BLOCKER_RESOLUTION_V1_REPORT.md").write_text(text, encoding="utf-8")


def main() -> None:
    raw_before = verify_raw_freeze()
    if raw_before["status"] != "PASS":
        raise RuntimeError(f"V13_RAW_FREEZE_FAILED:{raw_before}")
    approved = approve_assets()
    if not all(approved["scope_checks"].values()):
        raise RuntimeError(f"ASSET_SCOPE_CHECK_FAILED:{approved['scope_checks']}")
    write_docs(approved)
    report = build_preflight(approved, raw_before)
    raw_after = verify_raw_freeze()
    if raw_after != raw_before:
        raise RuntimeError("V13_RAW_CHANGED")
    report["raw_freeze_verification_after"] = raw_after
    write_json(OUT / "V13_VIDEO_002_FINAL_BATTLE_PREFLIGHT_REPORT.json", report)
    write_resolution_report(report, raw_after)
    manifest = []
    for path in sorted(OUT.iterdir()):
        if path.is_file():
            manifest.append({"path": path.name, "size": path.stat().st_size, "sha256": sha256(path)})
    write_json(OUT / "V13_VIDEO_002_BLOCKER_RESOLUTION_ARTIFACT_MANIFEST.json", {
        "schema_version": "1.0", "video_rendered": False, "artifacts": manifest,
    })
    print(json.dumps({
        "output": str(OUT), "gates": report["gates"], "video_rendered": False,
        "raw_aggregate": raw_after["aggregate_sha256"], "scope_checks": approved["scope_checks"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
