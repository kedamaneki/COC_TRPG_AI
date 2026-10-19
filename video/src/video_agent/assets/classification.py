from __future__ import annotations

import hashlib
import json
import re
import wave
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable


CATEGORIES = {
    "背景素材": "BACKGROUND", "BGM素材": "BGM", "効果音素材": "SFX",
    "backgrounds": "BACKGROUND", "background": "BACKGROUND",
    "bgm": "BGM", "music": "BGM", "sfx": "SFX",
}
MEDIA_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".wav", ".mp3", ".ogg", ".m4a"}
EVIDENCE_SUFFIXES = {".txt", ".md", ".pdf", ".url", ".html", ".json"}
EVIDENCE_WORDS = ("readme", "license", "licence", "terms", "利用規約", "規約", "作者", "配布元")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def category_from_path(path: str | Path) -> str | None:
    parts = Path(path).parts
    for folder, category in CATEGORIES.items():
        if folder.casefold() in {part.casefold() for part in parts}:
            return category
    return None


def _name_text(path: str | Path) -> str:
    return Path(path).stem.casefold().replace("_", " ")


def _contains(text: str, *words: str) -> bool:
    return any(word.casefold() in text for word in words)


def _wav_duration(path: Path) -> float | None:
    if path.suffix.casefold() != ".wav":
        return None
    try:
        with wave.open(str(path), "rb") as wav:
            return round(wav.getnframes() / wav.getframerate(), 4)
    except (wave.Error, OSError, ZeroDivisionError):
        return None


def classify_background(path: str | Path) -> dict[str, Any]:
    text = _name_text(path)
    result: dict[str, Any] = {
        "environment_type": "UNKNOWN", "location_type": "UNKNOWN",
        "indoor_outdoor": "UNKNOWN", "time_of_day": "UNKNOWN", "mood": ["UNKNOWN"],
        "era_style": "UNKNOWN", "scenario_fit": ["UNKNOWN"], "visual_density": "UNKNOWN",
        "character_overlay_compatibility": "UNKNOWN", "semantic_tags": [], "suggested_use": [],
        "video_suitability": "UNKNOWN", "match_quality": "WEAK_MATCH",
        "classification_confidence": "LOW",
    }
    if _contains(text, "地下室", "basement", "cellar"):
        result.update(environment_type="BASEMENT", location_type="BASEMENT", indoor_outdoor="INDOOR",
                      mood=["DARK", "TENSE"], scenario_fit=["CORBITT_HOUSE", "COC_GENERAL"],
                      semantic_tags=["BASEMENT", "DARK_INTERIOR", "CORBITT_HOUSE"],
                      suggested_use=["basement", "horror_investigation"], match_quality="EXACT_MATCH",
                      video_suitability="GOOD", classification_confidence="HIGH")
    elif _contains(text, "紅魔館ロビー", "廊下", "hallway"):
        is_mansion = "紅魔館" in text
        result.update(environment_type="HALLWAY" if "廊下" in text else "HOUSE_INTERIOR",
                      location_type="HALLWAY" if "廊下" in text else "HALL",
                      indoor_outdoor="INDOOR", mood=["MYSTERIOUS" if is_mansion else "NEUTRAL"],
                      era_style="FANTASY" if is_mansion else "MODERN",
                      scenario_fit=["GENERIC_INVESTIGATION", "COC_GENERAL"],
                      semantic_tags=["OLD_HOUSE_INTERIOR" if is_mansion else "HALLWAY", "INTERIOR"],
                      suggested_use=["old_house_interior" if is_mansion else "investigation_hallway"],
                      match_quality="GOOD_MATCH", video_suitability="ACCEPTABLE",
                      classification_confidence="HIGH")
    elif _contains(text, "紅魔館"):
        result.update(environment_type="HOUSE_EXTERIOR", location_type="MANSION", indoor_outdoor="OUTDOOR",
                      mood=["MYSTERIOUS", "OLD"], era_style="FANTASY",
                      scenario_fit=["COC_GENERAL", "GENERIC_INVESTIGATION"],
                      semantic_tags=["OLD_HOUSE", "MANSION_EXTERIOR"], suggested_use=["old_house_exterior"],
                      match_quality="GOOD_MATCH", video_suitability="ACCEPTABLE", classification_confidence="HIGH")
    elif _contains(text, "和室", "床の間", "部屋", "物置", "オフィス", "喫茶店"):
        env = "OFFICE" if "オフィス" in text else "ROOM_GENERIC"
        loc = "STORAGE" if "物置" in text else "ROOM_GENERIC"
        mood = ["BRIGHT"] if _contains(text, "白い", "日中") else ["NEUTRAL"]
        result.update(environment_type=env, location_type=loc, indoor_outdoor="INDOOR", mood=mood,
                      era_style="TRADITIONAL_JAPANESE" if _contains(text, "和室", "床の間") else "MODERN",
                      scenario_fit=["GENERIC_INVESTIGATION"], semantic_tags=[env, "INTERIOR"],
                      suggested_use=["generic_interior"], match_quality="WEAK_MATCH",
                      video_suitability="ACCEPTABLE", classification_confidence="HIGH")
    elif _contains(text, "住宅街", "街中", "駅前"):
        night = "夜" in text
        result.update(environment_type="STREET", location_type="STREET", indoor_outdoor="OUTDOOR",
                      time_of_day="NIGHT" if night else "DAY", mood=["DARK" if night else "BRIGHT"],
                      era_style="MODERN", scenario_fit=["GENERIC_INVESTIGATION", "MODERN"],
                      semantic_tags=["STREET", "NIGHT" if night else "DAY"], suggested_use=["city_travel"],
                      match_quality="GOOD_MATCH", video_suitability="ACCEPTABLE", classification_confidence="HIGH")
    elif _contains(text, "森"):
        result.update(environment_type="FOREST", location_type="FOREST", indoor_outdoor="OUTDOOR",
                      mood=["MYSTERIOUS"], era_style="FANTASY", scenario_fit=["FANTASY"],
                      semantic_tags=["FOREST", "MYSTERIOUS"], suggested_use=["forest_exploration"],
                      video_suitability="ACCEPTABLE", classification_confidence="HIGH")
    elif _contains(text, "まがまがしい"):
        result.update(environment_type="DARK_INTERIOR", location_type="ABSTRACT", mood=["OMINOUS", "HORROR"],
                      scenario_fit=["COC_GENERAL"], semantic_tags=["HORROR", "OMINOUS", "DARK_INTERIOR"],
                      suggested_use=["horror_reveal"], video_suitability="ACCEPTABLE",
                      match_quality="GOOD_MATCH", classification_confidence="HIGH")
    elif _contains(text, "神社", "白玉楼"):
        result.update(environment_type="BUILDING_GENERIC", location_type="SHRINE_OR_FANTASY_BUILDING",
                      indoor_outdoor="OUTDOOR", mood=["CALM"], era_style="FANTASY",
                      scenario_fit=["FANTASY", "UNSUITABLE"], semantic_tags=["FANTASY_BUILDING"],
                      suggested_use=["fantasy_scene"], video_suitability="POOR", classification_confidence="HIGH")
    elif _contains(text, "黒板", "紙", "柄背景", "コルクボード", "カラーバー", "セリフ枠", "フレーム"):
        result.update(environment_type="UNKNOWN", location_type="GRAPHIC_OR_FRAME", mood=["NEUTRAL"],
                      scenario_fit=["UNSUITABLE"], semantic_tags=["GRAPHIC", "FRAME_OR_TEXTURE"],
                      suggested_use=["presentation_overlay"], video_suitability="POOR",
                      match_quality="UNSUITABLE", classification_confidence="HIGH")
    if result["location_type"] not in {"GRAPHIC_OR_FRAME", "UNKNOWN"}:
        result["character_overlay_compatibility"] = "ACCEPTABLE"
    elif result["location_type"] == "GRAPHIC_OR_FRAME":
        result["character_overlay_compatibility"] = "POOR"
    return result


def classify_bgm(path: str | Path) -> dict[str, Any]:
    text = _name_text(path)
    result: dict[str, Any] = {
        "mood": ["UNKNOWN"], "intensity": "UNKNOWN", "tempo_class": "UNKNOWN",
        "loop_suitability": "UNKNOWN", "scene_role": ["GENERIC_BACKGROUND"], "horror_fit": "UNKNOWN",
        "dialogue_compatibility": "UNKNOWN", "semantic_tags": [], "suggested_use": [],
        "video_suitability": "UNKNOWN", "match_quality": "WEAK_MATCH", "classification_confidence": "LOW",
    }
    if _contains(text, "tension", "horror", "snaps in the dark", "light fades", "piercing shadow", "monster"):
        result.update(mood=["TENSION", "DARK", "OMINOUS"], intensity="MEDIUM", tempo_class="SLOW",
                      loop_suitability="GOOD" if _contains(text, "loop", "snaps in the dark") else "UNKNOWN",
                      scene_role=["TENSION_BUILD", "INVESTIGATION"], horror_fit="GOOD",
                      dialogue_compatibility="GOOD", semantic_tags=["TENSION", "TENSION_BUILD", "HORROR", "INVESTIGATION"],
                      suggested_use=["tension", "horror_investigation"], video_suitability="GOOD",
                      match_quality="EXACT_MATCH", classification_confidence="HIGH")
    elif _contains(text, "日常", "昼下がり", "休み時間"):
        result.update(mood=["CALM", "LIGHT"], intensity="LOW", tempo_class="MEDIUM",
                      scene_role=["EXPLORATION", "GENERIC_BACKGROUND"], horror_fit="POOR",
                      dialogue_compatibility="GOOD", semantic_tags=["CALM_EXPLORATION", "LIGHT"],
                      suggested_use=["calm_exploration", "roleplay"], video_suitability="GOOD",
                      match_quality="GOOD_MATCH", classification_confidence="HIGH")
    elif _contains(text, "大慌て", "騒がしく", "暴れん坊", "みｗな"):
        result.update(mood=["COMEDIC"], intensity="HIGH", tempo_class="FAST",
                      scene_role=["COMBAT" if "騒がしく" in text else "GENERIC_BACKGROUND"], horror_fit="POOR",
                      dialogue_compatibility="POOR", semantic_tags=["COMEDIC", "HIGH_INTENSITY"],
                      suggested_use=["comedy_or_panic"], video_suitability="ACCEPTABLE",
                      match_quality="WEAK_MATCH", classification_confidence="HIGH")
    elif _contains(text, "moment", "recollections", "回想"):
        result.update(mood=["MYSTERIOUS", "SAD"], intensity="LOW", tempo_class="SLOW",
                      scene_role=["INVESTIGATION", "AFTERMATH"], horror_fit="ACCEPTABLE",
                      dialogue_compatibility="GOOD", semantic_tags=["INVESTIGATION", "REFLECTION"],
                      suggested_use=["investigation", "aftermath"], video_suitability="ACCEPTABLE",
                      match_quality="GOOD_MATCH", classification_confidence="MEDIUM")
    elif _contains(text, "ジングル", "コロンビア"):
        result.update(mood=["BREAKTHROUGH"], intensity="MEDIUM", tempo_class="SHORT_STINGER",
                      loop_suitability="POOR", scene_role=["BREAKTHROUGH"], horror_fit="POOR",
                      dialogue_compatibility="ACCEPTABLE", semantic_tags=["BREAKTHROUGH", "STINGER"],
                      suggested_use=["success_reveal"], video_suitability="ACCEPTABLE",
                      match_quality="GOOD_MATCH", classification_confidence="HIGH")
    return result


def classify_sfx(path: str | Path, duration_seconds: float | None = None) -> dict[str, Any]:
    text = _name_text(path)
    result: dict[str, Any] = {
        "sfx_family": "UNKNOWN", "action_semantic": "UNKNOWN", "intensity": "UNKNOWN",
        "duration_class": "UNKNOWN", "loopable": False, "scene_role": ["UNKNOWN"],
        "semantic_tags": [], "suggested_use": [], "video_suitability": "UNKNOWN",
        "match_quality": "WEAK_MATCH", "classification_confidence": "LOW",
    }
    rules = [
        (("ダイス", "dice"), "DICE", "dice_roll", "MEDIUM", "dice_result"),
        (("折れ", "割れ", "壊れ", "破壊", "wood break", "branch break", "snap crunch"), "WOOD", "wood_break", "HIGH", "object_break"),
        (("きし", "軋", "木材", "板", "木が", "木の", "wood creak"), "WOOD", "wood_creak", "LOW", "object_interaction"),
        (("ドア", "扉"), "DOOR", "door_interaction", "MEDIUM", "location_transition"),
        (("足音", "歩く", "走る"), "FOOTSTEP", "footstep", "LOW", "movement"),
        (("不正解", "しょげる", "失敗", "ずっこけ"), "FAILURE", "failure_feedback", "MEDIUM", "result_feedback"),
        (("正解", "レベルアップ", "ファンファーレ", "きらーん", "キラッ", "ひらめく"), "SUCCESS", "success_feedback", "MEDIUM", "result_feedback"),
        (("スイッチ", "早押し", "ピコッ", "決定", "確認"), "UI", "ui_confirm", "LOW", "ui"),
        (("キャンセル", "中止"), "UI", "ui_cancel", "LOW", "ui"),
        (("紙", "ページ", "タイプライター"), "PAPER", "paper_or_text", "LOW", "investigation"),
        (("爆発", "ドーン", "バーン", "衝撃", "打つ", "グサッ", "噛みつく", "げんこつ"), "IMPACT", "impact_heavy", "HIGH", "combat_or_impact"),
        (("鈴", "鐘", "チャイム", "チーン", "チリン"), "METAL", "bell_or_chime", "MEDIUM", "attention"),
        (("不安", "ショック", "恐怖", "ホラー", "寒いギャグで突風"), "HORROR", "ominous_stinger", "MEDIUM", "horror_reveal"),
        (("ジャンプ", "逃げる", "落下", "動作", "座る", "ブレーキ"), "MOVEMENT", "movement", "MEDIUM", "movement"),
        (("触る", "スポッ", "ペタッ", "ニュッ"), "OBJECT_INTERACTION", "object_interaction", "LOW", "object_interaction"),
        (("シーン切り替え", "タイトル表示", "回想", "データ解析"), "UI", "scene_transition", "MEDIUM", "transition"),
    ]
    for words, family, action, intensity, role in rules:
        if _contains(text, *words):
            result.update(sfx_family=family, action_semantic=action, intensity=intensity,
                          scene_role=[role], semantic_tags=[action, family], suggested_use=[action],
                          video_suitability="GOOD" if action in {"dice_roll", "wood_creak", "wood_break", "success_feedback", "failure_feedback", "footstep", "door_interaction", "ominous_stinger"} else "ACCEPTABLE",
                          match_quality="EXACT_MATCH" if action in {"dice_roll", "wood_creak", "wood_break", "success_feedback", "failure_feedback"} else "GOOD_MATCH",
                          classification_confidence="HIGH")
            break
    if duration_seconds is not None:
        result["duration_seconds"] = duration_seconds
        result["duration_class"] = "SHORT" if duration_seconds <= 2 else "MEDIUM" if duration_seconds <= 10 else "LONG"
    return result


def classify_asset(asset: dict[str, Any]) -> dict[str, Any]:
    path = Path(asset["path"])
    category = category_from_path(path)
    if category == "BACKGROUND":
        classification = classify_background(path)
    elif category == "BGM":
        classification = classify_bgm(path)
    elif category == "SFX":
        classification = classify_sfx(path, _wav_duration(path))
    else:
        raise ValueError(f"out-of-scope asset: {path}")
    return {"asset_id": asset["asset_id"], "category": category, **classification}


def canonicalize_assets(assets: Iterable[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, str]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for asset in assets:
        groups[asset["sha256"]].append(asset)
    canonical_records, asset_to_canonical = [], {}
    for digest, members in sorted(groups.items()):
        ordered = sorted(members, key=lambda item: (item["path"].casefold(), item["asset_id"]))
        canonical = ordered[0]
        for member in ordered:
            asset_to_canonical[member["asset_id"]] = canonical["asset_id"]
        canonical_records.append({
            "canonical_asset_id": canonical["asset_id"], "sha256": digest,
            "canonical_path": canonical["path"],
            "duplicate_asset_ids": [item["asset_id"] for item in ordered[1:]],
            "duplicate_paths": [item["path"] for item in ordered[1:]],
            "review_count": 1,
        })
    return canonical_records, asset_to_canonical


def _evidence_candidates(asset_root: Path, category: str | None = None) -> list[Path]:
    category_folder = next((name for name, value in CATEGORIES.items() if value == category), None)
    folders = [asset_root] + ([asset_root / category_folder] if category_folder else [])
    found: dict[str, Path] = {}
    for folder in folders:
        if not folder.exists():
            continue
        for item in folder.iterdir():
            if not item.is_file():
                continue
            lowered = item.name.casefold()
            if item.suffix.casefold() in EVIDENCE_SUFFIXES and (
                item.suffix.casefold() == ".url" or any(word.casefold() in lowered for word in EVIDENCE_WORDS)
            ):
                found[str(item.resolve()).casefold()] = item.resolve()
    return [found[key] for key in sorted(found)]


def _sidecar_evidence(asset_path: Path) -> list[Path]:
    """Return acquisition evidence stored beside one externally acquired asset."""
    candidates = [
        asset_path.with_name(asset_path.name + ".source.json"),
        asset_path.with_name(asset_path.name + ".license.txt"),
        asset_path.with_name(asset_path.name + ".source.html"),
        asset_path.with_name(asset_path.name + ".license.html"),
    ]
    return [path.resolve() for path in candidates if path.is_file()]


def _external_license_record(canonical: dict[str, Any], category: str) -> dict[str, Any] | None:
    asset_path = Path(canonical["canonical_path"])
    sidecars = _sidecar_evidence(asset_path)
    source_json = next((path for path in sidecars if path.name.endswith(".source.json")), None)
    if source_json is None:
        return None
    metadata = json.loads(source_json.read_text(encoding="utf-8-sig"))
    evidence_items = [{"path": str(path), "sha256": sha256_file(path), "size": path.stat().st_size} for path in sidecars]
    return {
        "canonical_asset_id": canonical["canonical_asset_id"], "category": category,
        "evidence_files": evidence_items, "evidence_paths": [item["path"] for item in evidence_items],
        "source_locator_hints": [{"kind": "PRIMARY_SOURCE_URL", "value": metadata.get("source_url"), "license_evidence": True}],
        "extracted_notes": ["Acquisition metadata and contemporaneous source/license snapshots are stored beside the asset."],
        "license_status": "LICENSE_REVIEW_REQUIRED", "license_source": metadata.get("license_name", "UNKNOWN"),
        "license_document": metadata.get("license_url", "UNKNOWN"), "license_author": metadata.get("creator", "UNKNOWN"),
        "license_site": metadata.get("source_site", "UNKNOWN"),
        "allowed_commercial_use": metadata.get("commercial_use"),
        "allowed_modification": metadata.get("modification_allowed"),
        "attribution_required": metadata.get("attribution_required"),
        "redistribution_allowed": metadata.get("redistribution_allowed"),
        "video_use_allowed": metadata.get("video_use"), "youtube_niconico_allowed": metadata.get("video_use"),
        "credit_text": metadata.get("credit_text"), "source_url": metadata.get("source_url"),
        "downloaded_at": metadata.get("downloaded_at"), "generation_origin": metadata.get("generation_origin", "UNKNOWN"),
        "license_review_recommendation": metadata.get("license_review_recommendation", "UNRESOLVED"),
        "notes": metadata.get("terms_summary", "Human license review is required."),
        "review_status": "HUMAN_REVIEW_REQUIRED",
    }


def build_license_evidence(canonical_records: list[dict[str, Any]], classifications: dict[str, dict[str, Any]], asset_root: Path) -> dict[str, Any]:
    evidence_by_category = {
        category: [{"path": str(path), "sha256": sha256_file(path), "size": path.stat().st_size}
                   for path in _evidence_candidates(asset_root, category)]
        for category in ("BACKGROUND", "BGM", "SFX")
    }
    records = []
    for canonical in canonical_records:
        aid = canonical["canonical_asset_id"]
        category = classifications[aid]["category"]
        external = _external_license_record(canonical, category)
        if external is not None:
            records.append(external)
            continue
        evidence_items = evidence_by_category[category]
        file_name = Path(canonical["canonical_path"]).name
        nc = re.search(r"(?i)\bnc(\d+)", file_name)
        records.append({
            "canonical_asset_id": aid, "category": category,
            "evidence_files": evidence_items, "evidence_paths": [item["path"] for item in evidence_items],
            "source_locator_hints": ([{"kind": "NICONICO_COMMONS_ID_FROM_FILENAME", "value": f"nc{nc.group(1)}", "license_evidence": False}] if nc else []),
            "extracted_notes": (["Local evidence documents require human interpretation."] if evidence_items else ["No local license evidence document was found near the selected asset folders."]),
            "license_status": "LICENSE_REVIEW_REQUIRED", "license_source": "UNKNOWN",
            "license_document": "UNKNOWN", "license_author": "UNKNOWN", "license_site": "UNKNOWN",
            "allowed_commercial_use": None, "allowed_modification": None, "attribution_required": None,
            "redistribution_allowed": None, "video_use_allowed": None, "youtube_niconico_allowed": None,
            "notes": "Filename identifiers are source-locator hints only and do not approve a license.",
            "review_status": "HUMAN_REVIEW_REQUIRED",
        })
    unique_evidence = {item["path"]: item for items in evidence_by_category.values() for item in items}
    return {"schema_version": "1.0", "evidence_scope": str(asset_root), "evidence_file_count": len(unique_evidence), "records": records}


def build_semantic_index(classifications: list[dict[str, Any]], registry: dict[str, Any]) -> dict[str, Any]:
    assets_by_id = {item["asset_id"]: item for item in registry["assets"]}
    buckets: dict[str, dict[str, list[str]]] = {"background": defaultdict(list), "bgm": defaultdict(list), "sfx": defaultdict(list)}
    eligible: dict[str, dict[str, list[str]]] = {"background": defaultdict(list), "bgm": defaultdict(list), "sfx": defaultdict(list)}
    for record in classifications:
        category = record["category"].casefold()
        semantics = list(record.get("semantic_tags", []))
        if record["category"] == "BACKGROUND": semantics += [record.get("environment_type"), record.get("location_type")]
        elif record["category"] == "BGM": semantics += list(record.get("mood", [])) + list(record.get("scene_role", []))
        else: semantics += [record.get("sfx_family"), record.get("action_semantic")]
        asset = assets_by_id[record["asset_id"]]
        is_eligible = asset.get("license_status") == "LICENSE_APPROVED" and asset.get("approval_status") == "APPROVED_FOR_PREVIEW" and asset.get("auto_use") is True
        unique_semantics: dict[str, str] = {}
        for value in semantics:
            if value and value != "UNKNOWN":
                unique_semantics.setdefault(str(value).casefold(), str(value))
        for semantic in sorted(unique_semantics.values(), key=str.casefold):
            buckets[category][semantic].append(record["asset_id"])
            if is_eligible:
                eligible[category][semantic].append(record["asset_id"])
    all_classified = {cat: {key: sorted(value) for key, value in sorted(data.items())} for cat, data in buckets.items()}
    auto_eligible = {cat: {key: sorted(value) for key, value in sorted(data.items())} for cat, data in eligible.items()}
    return {
        "schema_version": "1.0", "selection_policy": "Planner automatic selection requires LICENSE_APPROVED + APPROVED_FOR_PREVIEW + auto_use=true.",
        "background": all_classified["background"], "bgm": all_classified["bgm"], "sfx": all_classified["sfx"],
        "all_classified": all_classified,
        "planner_auto_eligible": auto_eligible,
    }


def semantic_lookup(index: dict[str, Any], category: str, semantic: str, *, automatic: bool = True) -> list[str]:
    branch = "planner_auto_eligible" if automatic else "all_classified"
    return list(index.get(branch, {}).get(category.casefold(), {}).get(semantic, []))


def invalidate_changed_hash(asset: dict[str, Any], new_sha256: str) -> dict[str, Any]:
    updated = dict(asset)
    if asset.get("sha256") != new_sha256:
        updated.update(sha256=new_sha256, license_status="LICENSE_REVIEW_REQUIRED", approval_status="NOT_APPROVED",
                       auto_use=False, change_status="CHANGED_ASSET_REQUIRES_REVIEW")
    return updated


def _priority(record: dict[str, Any]) -> tuple[str, list[str]]:
    tags = set(record.get("semantic_tags", [])) | {record.get("environment_type"), record.get("location_type"), record.get("action_semantic")}
    tags |= set(record.get("mood", [])) | set(record.get("scene_role", []))
    p0 = {"BASEMENT", "OLD_HOUSE", "OLD_HOUSE_INTERIOR", "wood_creak", "wood_break", "success_feedback", "failure_feedback", "INVESTIGATION", "TENSION", "TENSION_BUILD"}
    hits = sorted(str(value) for value in tags & p0 if value)
    if hits:
        return "P0", hits
    if record.get("classification_confidence") == "LOW" or record.get("video_suitability") == "GOOD":
        return "P1", ["LOW_CONFIDENCE" if record.get("classification_confidence") == "LOW" else "GENERAL_TRPG_UTILITY"]
    return "P2", ["FUTURE_USE"]


def build_review_queue(classifications: list[dict[str, Any]], canonicals: dict[str, dict[str, Any]], evidence_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    queue = []
    for record in classifications:
        if record["asset_id"] != record["canonical_asset_id"]:
            continue
        priority, reasons = _priority(record)
        canonical = canonicals[record["canonical_asset_id"]]
        evidence = evidence_by_id[record["canonical_asset_id"]]
        queue.append({
            "priority": priority, "canonical_asset_id": record["canonical_asset_id"], "category": record["category"],
            "file": canonical["canonical_path"], "semantic_tags": record.get("semantic_tags", []),
            "classification_confidence": record["classification_confidence"], "match_quality": record["match_quality"],
            "duplicate_count": len(canonical["duplicate_asset_ids"]), "priority_reasons": reasons,
            "license_evidence_found": bool(evidence["evidence_files"]), "license_status": "LICENSE_REVIEW_REQUIRED",
            "approval_status": "NOT_APPROVED", "auto_use": False,
        })
    queue.sort(key=lambda item: ({"P0": 0, "P1": 1, "P2": 2}[item["priority"]], item["category"], item["file"].casefold()))
    required = ["basement background", "old house interior", "wood_creak", "wood_break", "success_feedback", "failure_feedback", "investigation BGM", "tension BGM"]
    present = {(item["category"], semantic) for item in queue for semantic in item["semantic_tags"]}
    checks = {
        "basement background": ("BACKGROUND", "BASEMENT"),
        "old house interior": ("BACKGROUND", "OLD_HOUSE_INTERIOR"),
        "wood_creak": ("SFX", "wood_creak"),
        "wood_break": ("SFX", "wood_break"),
        "success_feedback": ("SFX", "success_feedback"),
        "failure_feedback": ("SFX", "failure_feedback"),
        "investigation BGM": ("BGM", "INVESTIGATION"),
        "tension BGM": ("BGM", "TENSION"),
    }
    unresolved = [name for name in required if checks[name] not in present]
    return {"schema_version": "1.0", "duplicate_aware": True, "items": queue,
            "required_p0_review_topics": required, "p0_topics_without_named_candidate": unresolved}


def run_classification(registry_path: Path, asset_root: Path) -> dict[str, Any]:
    registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    historical_folders = {"背景素材", "BGM素材", "効果音素材"}
    selected = [item for item in registry["assets"]
                if category_from_path(item.get("path", "")) in {"BACKGROUND", "BGM", "SFX"}
                and historical_folders.intersection(Path(item.get("path", "")).parts)
                and str(item.get("path", "")).casefold().startswith(str(asset_root).casefold())]
    expected = Counter(category_from_path(item["path"]) for item in selected)
    if expected != Counter({"BACKGROUND": 30, "BGM": 30, "SFX": 137}):
        raise ValueError(f"selected counts differ from contract: {dict(expected)}")
    canonical_records, asset_to_canonical = canonicalize_assets(selected)
    classified = []
    for asset in selected:
        record = classify_asset(asset)
        record["canonical_asset_id"] = asset_to_canonical[asset["asset_id"]]
        classified.append(record)
        asset["canonical_asset_id"] = record["canonical_asset_id"]
        asset["classification_status"] = "CLASSIFIED_V1"
        asset["classification"] = {key: value for key, value in record.items() if key not in {"asset_id", "canonical_asset_id", "category"}}
        asset["asset_category"] = record["category"]
        asset["auto_use"] = False
    evidence = build_license_evidence(canonical_records, {item["asset_id"]: item for item in classified}, asset_root)
    semantic = build_semantic_index(classified, registry)
    canonical_by_id = {item["canonical_asset_id"]: item for item in canonical_records}
    evidence_by_id = {item["canonical_asset_id"]: item for item in evidence["records"]}
    queue = build_review_queue(classified, canonical_by_id, evidence_by_id)
    stats = Counter(item["classification_confidence"] for item in classified)
    matches = Counter(item["match_quality"] for item in classified)
    return {"registry": registry, "selected": selected, "classifications": sorted(classified, key=lambda item: item["asset_id"]),
            "canonical_records": canonical_records, "semantic_index": semantic, "license_evidence": evidence,
            "review_queue": queue, "counts": dict(expected), "confidence": dict(stats), "match_quality": dict(matches)}


def run_external_classification(registry_path: Path, external_root: Path) -> dict[str, Any]:
    """Classify only media acquired under an isolated external-asset root.

    This deliberately leaves the historical 30/30/137 contract in
    ``run_classification`` unchanged.
    """
    registry = json.loads(registry_path.read_text(encoding="utf-8-sig"))
    root = external_root.resolve()
    selected = []
    for item in registry["assets"]:
        raw_path = item.get("path")
        if not raw_path:
            continue
        path = Path(raw_path)
        try:
            path.resolve().relative_to(root)
        except (ValueError, OSError):
            continue
        if path.suffix.casefold() not in MEDIA_SUFFIXES or category_from_path(path) not in {"BACKGROUND", "BGM", "SFX"}:
            continue
        selected.append(item)
    if not selected:
        raise ValueError(f"no external media assets found under {external_root}")
    counts = Counter(category_from_path(item["path"]) for item in selected)
    canonical_records, asset_to_canonical = canonicalize_assets(selected)
    classified = []
    for asset in selected:
        record = classify_asset(asset)
        record["canonical_asset_id"] = asset_to_canonical[asset["asset_id"]]
        classified.append(record)
        asset["canonical_asset_id"] = record["canonical_asset_id"]
        asset["classification_status"] = "CLASSIFIED_EXTERNAL_V1"
        asset["classification"] = {key: value for key, value in record.items() if key not in {"asset_id", "canonical_asset_id", "category"}}
        asset["asset_category"] = record["category"]
        asset["auto_use"] = False
        asset["approval_status"] = "NOT_APPROVED"
        asset["license_status"] = "LICENSE_REVIEW_REQUIRED"
    evidence = build_license_evidence(canonical_records, {item["asset_id"]: item for item in classified}, external_root)
    semantic = build_semantic_index(classified, registry)
    queue = build_review_queue(
        classified,
        {item["canonical_asset_id"]: item for item in canonical_records},
        {item["canonical_asset_id"]: item for item in evidence["records"]},
    )
    stats = Counter(item["classification_confidence"] for item in classified)
    matches = Counter(item["match_quality"] for item in classified)
    return {"registry": registry, "selected": selected, "classifications": sorted(classified, key=lambda item: item["asset_id"]),
            "canonical_records": canonical_records, "semantic_index": semantic, "license_evidence": evidence,
            "review_queue": queue, "counts": dict(counts), "confidence": dict(stats), "match_quality": dict(matches)}
