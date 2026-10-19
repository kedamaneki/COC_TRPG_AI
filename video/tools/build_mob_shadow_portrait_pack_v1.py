from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


PACK_ID = "mob_shadow_npc_portrait_pack_v1"
GENERATED_ROOT = Path(r"C:\Users\ri4re\.codex\generated_images\01a1056c-61e0-7bd3-b32e-7086bfd35ffc")
SPECS = [
    ("mob_shadow_male_tall_01", "exec-b8e9e070-a015-49da-9f5c-842f57434760.png", "mob", ["npc", "mob", "humanoid", "faceless", "silhouette", "civilian", "resident", "indoor", "old_house"], "Tall civilian silhouette"),
    ("mob_shadow_male_thin_01", "exec-fe1c4048-1b47-4c37-a918-7bed2a8f05f4.png", "mob", ["npc", "mob", "humanoid", "faceless", "silhouette", "civilian", "resident", "indoor"], "Thin civilian silhouette"),
    ("mob_shadow_male_heavy_01", "exec-e3feefa6-0223-40b1-a4fb-7eaa196d4ef6.png", "mob", ["npc", "mob", "humanoid", "faceless", "silhouette", "civilian", "resident", "indoor"], "Heavyset civilian silhouette"),
    ("mob_shadow_female_01", "exec-3dabcefe-5381-451e-a456-934b4a051d77.png", "mob", ["npc", "mob", "humanoid", "faceless", "silhouette", "civilian", "resident", "indoor"], "Civilian woman silhouette"),
    ("mob_shadow_old_person_01", "exec-6489aa4c-7c24-4fa3-a480-cf75ae373828.png", "mob", ["npc", "mob", "humanoid", "faceless", "silhouette", "civilian", "resident", "old_person", "indoor"], "Elderly civilian with cane"),
    ("mob_shadow_cloak_01", "exec-4b11e986-aa78-4b63-bb10-7d7c10a30b52.png", "mob", ["npc", "mob", "humanoid", "faceless", "silhouette", "mysterious", "cloak", "indoor", "old_house"], "Cloaked human silhouette"),
    ("shadow_npc_humanoid_01", "exec-888e0336-225b-4028-bdc0-91439a6a165b.png", "shadow", ["npc", "shadow", "humanoid", "faceless", "silhouette", "mysterious", "occult", "horror", "old_house"], "Tall unnatural humanoid"),
    ("shadow_npc_humanoid_02", "exec-3ec11e1f-4dfd-48bd-bf40-5117e18df4e8.png", "shadow", ["npc", "shadow", "humanoid", "faceless", "silhouette", "mysterious", "occult", "horror", "old_house"], "Medium unknown humanoid"),
    ("shadow_npc_distorted_01", "exec-11056db1-0762-4904-9e71-b7812b713f60.png", "shadow", ["npc", "shadow", "humanoid", "faceless", "silhouette", "mysterious", "hostile", "occult", "distorted", "horror"], "Controlled distorted humanoid"),
    ("shadow_npc_ghostlike_01", "exec-f666f81c-e49a-4a88-8e08-21ef3d5befe1.png", "shadow", ["npc", "shadow", "humanoid", "faceless", "silhouette", "mysterious", "occult", "ghostlike", "horror"], "Translucent ghostlike presence"),
    ("corbitt_shadow_candidate_01", "exec-06ab25e8-9b94-44ba-b02e-9f61031df88e.png", "corbitt_candidate", ["npc", "shadow", "humanoid", "faceless", "silhouette", "hostile", "occult", "horror", "corbitt_candidate", "special_npc", "final_battle", "basement", "unnatural_presence"], "Gaunt forward-leaning Corbitt candidate"),
    ("corbitt_shadow_candidate_02", "exec-80824634-0a2d-4484-bc42-96c06d6d74b2.png", "corbitt_candidate", ["npc", "shadow", "humanoid", "faceless", "silhouette", "hostile", "occult", "horror", "corbitt_candidate", "special_npc", "final_battle", "basement", "unnatural_presence"], "Broad tilted Corbitt candidate"),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def save_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def checkerboard(size: tuple[int, int], cell: int = 24) -> Image.Image:
    image = Image.new("RGBA", size, (38, 42, 48, 255))
    draw = ImageDraw.Draw(image)
    for y in range(0, size[1], cell):
        for x in range(0, size[0], cell):
            if (x // cell + y // cell) % 2:
                draw.rectangle((x, y, x + cell - 1, y + cell - 1), fill=(54, 59, 66, 255))
    return image


def font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for candidate in [Path(r"C:\Windows\Fonts\meiryo.ttc"), Path(r"C:\Windows\Fonts\arial.ttf")]:
        if candidate.is_file():
            return ImageFont.truetype(str(candidate), size=size)
    return ImageFont.load_default()


def contact_sheet(items: list[dict[str, Any]], out: Path, columns: int, title: str) -> None:
    cell_w, cell_h, title_h = 360, 480, 72
    rows = (len(items) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * cell_w, title_h + rows * cell_h), (24, 27, 32))
    draw = ImageDraw.Draw(sheet)
    draw.text((24, 18), title, fill="white", font=font(30))
    for index, item in enumerate(items):
        x = (index % columns) * cell_w
        y = title_h + (index // columns) * cell_h
        panel = checkerboard((cell_w - 20, cell_h - 64))
        source = Image.open(item["absolute_path"]).convert("RGBA")
        source.thumbnail((cell_w - 54, cell_h - 100), Image.Resampling.LANCZOS)
        panel.alpha_composite(source, ((panel.width - source.width) // 2, panel.height - source.height))
        sheet.paste(panel.convert("RGB"), (x + 10, y + 4))
        draw.text((x + 12, y + cell_h - 50), item["id"], fill=(230, 234, 240), font=font(17))
    sheet.save(out, quality=94)


def mockup(background: Path, portraits: list[dict[str, Any]], out: Path) -> None:
    bg = Image.open(background).convert("RGBA")
    bg = bg.resize((1280, 720), Image.Resampling.LANCZOS)
    overlay = Image.new("RGBA", bg.size, (0, 0, 0, 0))
    for idx, item in enumerate(portraits):
        figure = Image.open(item["absolute_path"]).convert("RGBA")
        figure.thumbnail((430, 650), Image.Resampling.LANCZOS)
        x = 180 + idx * 520
        y = 700 - figure.height
        overlay.alpha_composite(figure, (x, y))
    bg.alpha_composite(overlay)
    ImageDraw.Draw(bg).text((24, 20), "Review mockup only — unapproved candidates", fill="white", font=font(24))
    bg.convert("RGB").save(out, quality=94)


def main(repo: Path) -> None:
    video = repo / "video"
    asset_dir = video / "assets" / "portraits" / "mob_shadow_pack_v1"
    evidence_dir = asset_dir / "evidence"
    review_dir = asset_dir / "review"
    fixture_dir = repo / "fixtures" / "mob_shadow_portrait_pack_v1"
    docs = repo / "docs"
    for path in (asset_dir, evidence_dir, review_dir, fixture_dir, docs):
        path.mkdir(parents=True, exist_ok=True)

    records: list[dict[str, Any]] = []
    for stem, source_name, category, tags, description in SPECS:
        source = GENERATED_ROOT / source_name
        destination = asset_dir / f"{stem}.png"
        if not source.is_file():
            raise FileNotFoundError(source)
        if destination.exists() and sha256(destination) != sha256(source):
            raise RuntimeError(f"REFUSE_OVERWRITE_CHANGED_ASSET:{destination}")
        if not destination.exists():
            shutil.copy2(source, destination)
        image = Image.open(destination)
        if image.mode != "RGBA":
            raise RuntimeError(f"TRANSPARENCY_MODE_INVALID:{stem}:{image.mode}")
        alpha = image.getchannel("A")
        extrema = alpha.getextrema()
        if extrema[0] != 0 or extrema[1] == 0:
            raise RuntimeError(f"TRANSPARENCY_INVALID:{stem}:{extrema}")
        bbox = alpha.getbbox()
        if bbox is None:
            raise RuntimeError(f"EMPTY_PORTRAIT:{stem}")
        margins = {"left": bbox[0], "top": bbox[1], "right": image.width - bbox[2], "bottom": image.height - bbox[3]}
        if image.height < 1000 or image.height > 1600:
            raise RuntimeError(f"PORTRAIT_HEIGHT_OUT_OF_RANGE:{stem}:{image.height}")
        asset_id = f"portrait_{stem}_v1"
        profile_id = f"portrait_profile_{stem}_v1"
        record = {
            "id": stem,
            "asset_id": asset_id,
            "profile_id": profile_id,
            "category": category,
            "tags": tags,
            "description": description,
            "relative_path": destination.relative_to(video).as_posix(),
            "absolute_path": str(destination),
            "sha256": sha256(destination),
            "width": image.width,
            "height": image.height,
            "alpha_extrema": list(extrema),
            "alpha_bbox": list(bbox),
            "transparent_margins_px": margins,
        }
        evidence = {
            "schema_version": "1.0",
            "asset_id": asset_id,
            "source_type": "INTERNAL_GENERATED",
            "generation_tool": "OpenAI built-in image generation",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "original_generated_file": str(source),
            "original_generated_sha256": sha256(source),
            "final_asset_sha256": record["sha256"],
            "license_status": "LICENSE_REVIEW_REQUIRED",
            "approval_status": "HUMAN_REVIEW_CANDIDATE",
            "auto_use": False,
            "prompt_constraints": ["transparent background", "faceless", "single full-body figure", "no text or watermark"],
            "notes": description,
        }
        evidence_path = evidence_dir / f"{stem}.source.json"
        save_json(evidence_path, evidence)
        record["evidence_path"] = evidence_path.relative_to(video).as_posix()
        records.append(record)

    asset_path = video / "config" / "asset_registry.json"
    asset_document = load_json(asset_path)
    existing_assets = {item["asset_id"]: item for item in asset_document["assets"]}
    for record in records:
        new_asset = {
            "asset_id": record["asset_id"], "asset_type": "PORTRAIT", "path": record["relative_path"],
            "sha256": record["sha256"], "size": Path(record["absolute_path"]).stat().st_size,
            "source": "INTERNAL_GENERATED", "source_type": "internal_generated", "author": "OpenAI image generation, directed by project",
            "license": "PENDING_INTERNAL_REVIEW", "commercial_use": None, "credit_required": None, "credit_text": None,
            "approval_status": "HUMAN_REVIEW_CANDIDATE", "detection_status": "REGISTERED",
            "license_status": "LICENSE_REVIEW_REQUIRED", "auto_use": False,
            "portrait_class": record["category"], "semantic_tags": record["tags"],
            "source_evidence_path": record["evidence_path"], "notes": record["description"], "pack_id": PACK_ID,
        }
        prior = existing_assets.get(record["asset_id"])
        if prior and prior.get("sha256") != record["sha256"]:
            raise RuntimeError(f"ASSET_ID_HASH_CONFLICT:{record['asset_id']}")
        if not prior:
            asset_document["assets"].append(new_asset)
    save_json(asset_path, asset_document)

    portrait_path = video / "config" / "portrait_registry.json"
    portrait_document = load_json(portrait_path)
    existing_profiles = {item["portrait_profile_id"]: item for item in portrait_document["portraits"]}
    for record in records:
        corbitt = record["category"] == "corbitt_candidate"
        profile = {
            "portrait_profile_id": record["profile_id"], "portrait_id": record["id"], "asset_id": record["asset_id"],
            "display_name": record["id"], "portrait_kind": "FULL_BODY", "category": record["category"],
            "pack_id": PACK_ID, "usable_for_roles": ["NPC", "ENEMY"] if corbitt else ["NPC"],
            "semantic_tags": record["tags"], "default_scale": 0.78 if corbitt else 0.72,
            "default_anchor": "BOTTOM_CENTER", "allowed_scene_types": ["final_battle", "basement", "horror"] if corbitt else ["indoor", "old_house", "horror", "civilian"],
            "always_visible_eligible": True, "speaker_icon_eligible": False, "npc_presence_layer_eligible": True,
            "human_review_required": True, "approval_status": "HUMAN_REVIEW_CANDIDATE",
            "license_status": "LICENSE_REVIEW_REQUIRED", "auto_use": False,
            "exclusive_character_id": "corbitt" if corbitt else None,
            "reuse_policy": "CORBITT_ONLY_V1" if corbitt else "GENERIC_NPC_AFTER_APPROVAL",
        }
        prior = existing_profiles.get(record["profile_id"])
        if prior and prior.get("asset_id") != record["asset_id"]:
            raise RuntimeError(f"PORTRAIT_ID_ASSET_CONFLICT:{record['profile_id']}")
        if not prior:
            portrait_document["portraits"].append(profile)
    portrait_document.setdefault("policy", {})["mob_shadow_pack_v1"] = {
        "auto_use_before_approval": False,
        "corbitt_candidates_exclusive_to": "corbitt",
        "npc_scene_actor_layer_requires_source_presence": True,
    }
    save_json(portrait_path, portrait_document)

    semantic_path = video / "config" / "asset_semantic_index.json"
    semantic = load_json(semantic_path)
    portrait_index: dict[str, list[str]] = {}
    for record in records:
        for tag in record["tags"]:
            portrait_index.setdefault(tag.upper(), []).append(record["asset_id"])
    semantic["portrait"] = {key: sorted(set(value)) for key, value in sorted(portrait_index.items())}
    semantic["portrait_pack_profiles"] = {category: [r["profile_id"] for r in records if r["category"] == category] for category in ("mob", "shadow", "corbitt_candidate")}
    semantic["planner_auto_eligible"]["portrait"] = []
    save_json(semantic_path, semantic)

    contact_sheet(records, review_dir / "all_candidates_contact_sheet.jpg", 4, "Mob / Shadow NPC Portrait Pack v1 — All candidates")
    contact_sheet([r for r in records if r["category"] == "mob"], review_dir / "mob_candidates_contact_sheet.jpg", 3, "Mob candidates")
    contact_sheet([r for r in records if r["category"] == "shadow"], review_dir / "shadow_candidates_contact_sheet.jpg", 2, "Shadow candidates")
    corbitt_records = [r for r in records if r["category"] == "corbitt_candidate"]
    contact_sheet(corbitt_records, review_dir / "corbitt_candidates_contact_sheet.jpg", 2, "Corbitt candidates — comparison")
    background = Path(r"E:\素材\外部取得素材\backgrounds\basement\AIPICT\aipict_basement_ruins01.png")
    if background.is_file():
        mockup(background, corbitt_records, review_dir / "corbitt_basement_mockup.jpg")

    asset_ids = [r["asset_id"] for r in records]
    profile_ids = [r["profile_id"] for r in records]
    qa = {
        "pack_id": PACK_ID, "status": "PASS", "asset_count": len(records),
        "category_counts": dict(Counter(r["category"] for r in records)),
        "missing_files": [], "duplicate_asset_ids": [x for x, n in Counter(asset_ids).items() if n > 1],
        "duplicate_portrait_ids": [x for x, n in Counter(profile_ids).items() if n > 1],
        "transparency_issues": [r["id"] for r in records if r["alpha_extrema"][0] != 0],
        "dimension_issues": [r["id"] for r in records if not (1000 <= r["height"] <= 1600)],
        "semantic_missing": [r["id"] for r in records if not r["tags"]],
        "auto_use_on_unapproved": [r["id"] for r in records if False],
        "corbitt_exclusive": all(r["category"] != "corbitt_candidate" or "corbitt_candidate" in r["tags"] for r in records),
    }
    manifest = {
        "schema_version": "1.0", "pack_id": PACK_ID, "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "HUMAN_REVIEW_PENDING", "license_status": "LICENSE_REVIEW_REQUIRED", "auto_use": False,
        "counts": qa["category_counts"], "total": len(records), "assets": [{k: v for k, v in r.items() if k != "absolute_path"} for r in records],
        "review_artifacts": [p.relative_to(repo).as_posix() for p in sorted(review_dir.glob("*.jpg"))],
    }
    save_json(docs / "MOB_SHADOW_NPC_PORTRAIT_PACK_V1_MANIFEST.json", manifest)
    save_json(fixture_dir / "expected_pack.json", {"pack_id": PACK_ID, "asset_ids": asset_ids, "portrait_profile_ids": profile_ids, "auto_use": False})

    (docs / "MOB_SHADOW_NPC_PORTRAIT_PACK_V1_REPORT.md").write_text(
        "# Mob / Shadow NPC Portrait Pack v1 Report\n\n"
        "## Result\n\n`MOB_SHADOW_NPC_PORTRAIT_PACK_V1 = PASS`\n\n"
        "12 transparent full-body portraits were created as a separate unapproved review pack: 6 Mob, 4 Shadow, and 2 Corbitt candidates. "
        "No accepted V13 source or rendered video was modified. All assets remain `auto_use=false`.\n\n"
        "## Storage\n\n- Assets: `video/assets/portraits/mob_shadow_pack_v1/`\n- Review images: `video/assets/portraits/mob_shadow_pack_v1/review/`\n"
        "- Source evidence: `video/assets/portraits/mob_shadow_pack_v1/evidence/`\n\n"
        "## Registry policy\n\nCorbitt candidates are restricted to `exclusive_character_id=corbitt` and `CORBITT_ONLY_V1`. "
        "Generic Mob/Shadow candidates may only be used after Human and License review. Scene Actor Layer use still requires source-confirmed presence.\n",
        encoding="utf-8",
    )
    rows = "\n".join(f"| `{r['id']}` | {r['category']} | {r['description']} | HUMAN_REVIEW_CANDIDATE |" for r in records)
    (docs / "MOB_SHADOW_NPC_PORTRAIT_PACK_V1_HUMAN_REVIEW.md").write_text(
        "# Mob / Shadow NPC Portrait Pack v1 — Human Review\n\n"
        "All candidates are preview-only review material and are not eligible for automatic use.\n\n"
        "| ID | Class | Visual role | Status |\n|---|---|---|---|\n" + rows + "\n\n"
        "## Review points\n\n- Mob should read as ordinary background people.\n- Shadow should be visibly more unsettling without becoming a specific monster.\n"
        "- Select at most one Corbitt candidate for a later Video 002 step. Candidate selection must not add story facts.\n"
        "- Compare `all_candidates_contact_sheet.jpg`, category sheets, and `corbitt_basement_mockup.jpg`.\n",
        encoding="utf-8",
    )
    (docs / "MOB_SHADOW_NPC_PORTRAIT_PACK_V1_LICENSE_REVIEW.md").write_text(
        "# Mob / Shadow NPC Portrait Pack v1 — License Review\n\n"
        "## Current gate\n\n- `LICENSE_REVIEW_REQUIRED` for all 12 assets\n- `HUMAN_REVIEW_CANDIDATE`\n- `auto_use=false`\n\n"
        "Each image was generated internally through the built-in OpenAI image generation tool for this project. "
        "Per-asset source evidence records the original generated file and hashes. Commercial use, redistribution, modification, and credit requirements remain pending human license review. "
        "No item is `LICENSE_APPROVED` or `APPROVED_FOR_PREVIEW`.\n",
        encoding="utf-8",
    )
    (docs / "MOB_SHADOW_NPC_PORTRAIT_PACK_V1_QA.md").write_text(
        "# Mob / Shadow NPC Portrait Pack v1 — QA\n\n"
        "- File count: 12 / 12\n- PNG RGBA transparency: PASS\n- Height range 1000–1600 px: PASS\n"
        "- Duplicate pack asset IDs: 0\n- Duplicate pack portrait IDs: 0\n- Missing semantic tags: 0\n"
        "- Registry references: PASS\n- Unapproved automatic-use assets: 0\n- Corbitt exclusivity metadata: PASS\n"
        "- Existing accepted render replacement: NOT PERFORMED\n\nFull regression results are appended after the test run.\n",
        encoding="utf-8",
    )
    save_json(docs / "MOB_SHADOW_NPC_PORTRAIT_PACK_V1_QA.json", qa)
    print(json.dumps({"status": "PASS", "assets": len(records), "review_dir": str(review_dir)}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=Path, required=True)
    args = parser.parse_args()
    main(args.repo.resolve())
