from __future__ import annotations

import importlib.util
import json
from pathlib import Path


REPO = Path(r"F:\制作物\その3\corbitt-trpg-system")
VIDEO = REPO / "video"
BASE = Path(r"F:\制作物\その3\video-production\CORBITT_LONGRUN_ITERATION3_V13_HOME_001")
V26 = BASE / "video_001_basement_planks_v2_6"
OUT = BASE / "video_001_basement_planks_v2_6_alt_dialogue_frame_prototype"
RT = Path(r"C:\Users\ri4re\Documents\Codex\V13_VIDEO_001_V2_6_ALT_FRAME_RENDER_WORKSPACE")
FRAME = Path(r"E:\素材\背景素材\nc131976_SF風シンプルセリフ枠(半透明).png")

spec = importlib.util.spec_from_file_location("v26_builder", VIDEO / "tools/build_v13_video_001_v2_6.py")
v26 = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(v26)


def main() -> None:
    if not FRAME.exists() or not V26.exists():
        raise FileNotFoundError({"frame": str(FRAME), "v2_6": str(V26)})
    v26_before = v26.v25.v23.snapshot(V26)
    v26.OUT = OUT
    v26.RT = RT
    v26.PROJ = RT / "project"
    original_render = v26.render_dialogue

    def render_with_candidate(pipe, timeline, gains, assets):
        candidate_assets = dict(assets)
        candidate_assets["dialogue_frame_user"] = FRAME
        return original_render(pipe, timeline, gains, candidate_assets)

    v26.render_dialogue = render_with_candidate
    v26.main()
    if v26_before != v26.v25.v23.snapshot(V26):
        raise RuntimeError("V2_6_HISTORICAL_ARTIFACT_CHANGED")
    report = {
        "prototype_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_6_ALT_DIALOGUE_FRAME_PROTOTYPE",
        "base_video_id": "V13_VIDEO_001_BASEMENT_PLANKS_V2_6",
        "change_scope": "DIALOGUE_FRAME_ONLY",
        "dialogue_frame": {
            "path": str(FRAME),
            "sha256": v26.v25.v23.sha(FRAME),
            "dimensions": [1280, 250],
            "mode": "RGBA",
            "registry_asset_id": "detected_nc131976_sf風シンプルセリフ枠_半透明_6c3f3538_669813da",
            "approval_status": "NOT_APPROVED",
            "license_status": "LICENSE_REVIEW_REQUIRED",
            "auto_use": False,
            "use_scope": "USER_REQUESTED_LOCAL_PROTOTYPE_ONLY",
        },
        "base_v2_6_unchanged": True,
        "human_review": "REQUIRED",
        "auto_publish": "prohibited",
    }
    report_path = OUT / "V13_VIDEO_001_V2_6_ALT_DIALOGUE_FRAME_PROTOTYPE_REPORT.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest_path = OUT / "V13_VIDEO_001_V2_6_ARTIFACT_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "prototype_only": True,
        "prototype_id": report["prototype_id"],
        "dialogue_frame_candidate": report["dialogue_frame"],
        "base_v2_6_unchanged": True,
        "license_review_required": True,
        "auto_publish": "prohibited",
    })
    manifest["artifacts"].append({"path": str(report_path), "size": report_path.stat().st_size,
                                  "sha256": v26.v25.v23.sha(report_path)})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"prototype": report["prototype_id"], "output": str(OUT),
                      "base_v2_6_unchanged": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
