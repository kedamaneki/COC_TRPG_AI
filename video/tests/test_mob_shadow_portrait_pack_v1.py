import json
from pathlib import Path

import pytest

from video_agent.assets.portrait_pack import (
    PortraitPackError,
    assert_registry_ids_unique,
    load_portrait_pack,
    scene_actor_layer_eligible,
    semantic_portrait_lookup,
)


ROOT = Path(__file__).resolve().parents[1]
PACK_ID = "mob_shadow_npc_portrait_pack_v1"


@pytest.fixture(scope="module")
def profiles():
    return load_portrait_pack(
        ROOT / "config" / "portrait_registry.json",
        ROOT / "config" / "asset_registry.json",
        pack_id=PACK_ID,
    )


def test_pack_loads_all_twelve_registered_portraits(profiles):
    assert len(profiles) == 12
    assert {p["category"] for p in profiles} == {"mob", "shadow", "corbitt_candidate"}
    assert all((ROOT / p["asset"]["path"]).is_file() for p in profiles)


def test_pack_assets_are_never_automatic_and_only_selected_corbitt_is_scoped(profiles):
    assert semantic_portrait_lookup(profiles, "faceless", automatic=True) == []
    for profile in profiles:
        asset = profile["asset"]
        if asset["asset_id"] == "portrait_corbitt_shadow_candidate_01_v1":
            assert asset["approval_status"] == "APPROVED_FOR_PREVIEW"
            assert asset["license_status"] == "LICENSE_APPROVED"
            assert asset["approved_video_scopes"] == ["VIDEO_002_FINAL_BATTLE"]
        else:
            assert asset["approval_status"] in {"NOT_APPROVED", "HUMAN_REVIEW_CANDIDATE"}
            assert asset["license_status"] == "LICENSE_REVIEW_REQUIRED"
        assert profile["asset"]["auto_use"] is False


def test_semantic_lookup_and_corbitt_exclusivity(profiles):
    mob = semantic_portrait_lookup(profiles, "mob", "civilian")
    corbitt = semantic_portrait_lookup(profiles, "corbitt_candidate", "final_battle")
    assert len(mob) >= 5
    assert len(corbitt) == 2
    assert all(p["exclusive_character_id"] == "corbitt" for p in corbitt)
    assert all("corbitt_candidate" not in p.get("usable_for_roles", []) for p in mob)


def test_scene_actor_layer_eligibility(profiles):
    corbitt = semantic_portrait_lookup(profiles, "corbitt_candidate")[0]
    mob = semantic_portrait_lookup(profiles, "mob")[0]
    assert scene_actor_layer_eligible(corbitt, "final_battle")
    assert not scene_actor_layer_eligible(corbitt, "ordinary_civilian")
    assert scene_actor_layer_eligible(mob, "indoor")
    assert all(p["speaker_icon_eligible"] is False for p in profiles)


def test_duplicate_registry_ids_fail_closed():
    document = {"portraits": [{"portrait_profile_id": "same"}, {"portrait_profile_id": "same"}]}
    with pytest.raises(PortraitPackError, match="DUPLICATE_PORTRAIT_PROFILE_ID"):
        assert_registry_ids_unique(document, "portrait_profile_id", "portraits")


def test_registry_has_no_duplicate_asset_or_portrait_ids():
    portraits = json.loads((ROOT / "config" / "portrait_registry.json").read_text(encoding="utf-8-sig"))
    assets = json.loads((ROOT / "config" / "asset_registry.json").read_text(encoding="utf-8-sig"))
    assert_registry_ids_unique(portraits, "portrait_profile_id", "portraits")
    assert_registry_ids_unique(assets, "asset_id", "assets")
