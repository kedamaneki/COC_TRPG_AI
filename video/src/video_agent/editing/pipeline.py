from __future__ import annotations

import json
import shutil
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from video_agent.common.io import read_json, stable_digest, write_json
from video_agent.editing.continuity import build_continuity_report
from video_agent.editing.editor import SceneEditCache, edit_scene
from video_agent.editing.protection import detect_protected_events
from video_agent.editing.segmenter import segment_events
from video_agent.rendering import M1Pipeline


PROMPT_VERSION = "replay_editor_prompt_v1"
CONTINUITY_PROMPT_VERSION = "continuity_qa_prompt_v1"


def estimate_line_duration(line: dict) -> float:
    if line["presentation_mode"] == "VOICED":
        return max(1.2, len(line.get("voice_text") or "") / 7.0 + 0.35)
    if line["presentation_mode"] in {"SUBTITLE_ONLY", "OVERLAY_ONLY"}:
        return max(2.0, min(6.0, len(line.get("display_text") or "") / 12.0 + 1.0))
    return 0.0


def part_candidates(scenes: list[dict], lines: list[dict]) -> list[dict]:
    durations = defaultdict(float)
    for line in lines:
        durations[line["scene_id"]] += estimate_line_duration(line)
    candidates, cumulative, last_boundary = [], 0.0, 0.0
    for scene in scenes:
        cumulative += durations[scene["scene_id"]]
        elapsed = cumulative - last_boundary
        preferred = scene["scene_type"] in {"TRAVEL", "COMBAT", "CLIMAX", "ENDING"} or scene["importance"] >= 0.7
        if elapsed >= 480 and preferred:
            candidates.append({"after_scene_id": scene["scene_id"], "estimated_sec": round(cumulative, 1),
                               "reason": "SCENE_COMPLETION_AND_MAJOR_TRANSITION"})
            last_boundary = cumulative
        elif elapsed >= 960:
            candidates.append({"after_scene_id": scene["scene_id"], "estimated_sec": round(cumulative, 1),
                               "reason": "SCENE_COMPLETION_RUNTIME_LIMIT"})
            last_boundary = cumulative
    return candidates


def editing_qa(events: list[dict], plans: list[dict], lines: list[dict], protected: dict[str, dict], continuity: dict) -> dict:
    event_ids = {event["event_id"] for event in events}
    plan_by_id = {plan["source_event_id"]: plan for plan in plans}
    failures, warnings, checks = [], [], []
    def check(name: str, ok: bool, detail=None):
        checks.append({"name": name, "status": "PASS" if ok else "FAIL", "detail": detail})
        if not ok:
            failures.append(name)
    check("all_events_accounted", set(plan_by_id) == event_ids, len(plan_by_id))
    unsupported = sorted({source for line in lines for source in line["source_event_ids"] if source.startswith("norm:") and source not in event_ids})
    check("unsupported_source_zero", not unsupported, unsupported)
    check("source_provenance_100_percent", all(line["source_event_ids"] for line in lines))
    hard_lost = sorted(event_id for event_id, item in protected.items()
                       if item["level"] == "HARD_PROTECTED" and plan_by_id[event_id]["content_decision"] == "CUT")
    check("protected_event_loss_zero", not hard_lost, hard_lost)
    event_by_id = {event["event_id"]: event for event in events}
    bad_system_voice = []
    for line in lines:
        if line["presentation_mode"] != "VOICED":
            continue
        sources = [event_by_id[source] for source in line["source_event_ids"] if source in event_by_id]
        if any(event["event_type"] in {"DICE_RESULT", "SKILL_CHECK", "SAN_LOSS", "SYSTEM_INTERNAL"}
               or (event.get("text") or "").startswith(("システム:", "[システム]")) for event in sources):
            bad_system_voice.append(line["script_line_id"])
    check("system_attribution_clean", not bad_system_voice, bad_system_voice)
    bad_speakers = []
    for line in lines:
        source_speakers = {event_by_id[source].get("speaker_id") or event_by_id[source].get("actor_id") or "system"
                           for source in line["source_event_ids"] if source in event_by_id}
        if source_speakers and line["speaker_id"] not in source_speakers:
            bad_speakers.append(line["script_line_id"])
    check("dialogue_attribution", not bad_speakers, bad_speakers)
    ungrounded = []
    for line in lines:
        if not line.get("display_text"):
            continue
        originals = [event_by_id[source].get("text") or "" for source in line["source_event_ids"] if source in event_by_id]
        if not any(line["display_text"] in original for original in originals):
            ungrounded.append(line["script_line_id"])
    check("ungrounded_generated_dialogue_zero", not ungrounded, ungrounded)
    check("continuity_major_errors_zero", continuity["status"] == "PASS", continuity)
    ending_ok = all(plan_by_id[event["event_id"]]["content_decision"] != "CUT" for event in events if event["event_type"] == "ENDING")
    combat_ok = all(plan_by_id[event["event_id"]]["content_decision"] != "CUT" for event in events if event["event_type"] in {"COMBAT_START", "COMBAT_END"})
    check("ending_preserved", ending_ok)
    check("combat_context_preserved", combat_ok)
    counts = Counter(plan["content_decision"] for plan in plans)
    cut_rate = counts["CUT"] / len(plans)
    if cut_rate > 0.8:
        warnings.append("OVER_COMPRESSION")
    if cut_rate < 0.05:
        warnings.append("UNDER_EDITING")
    self_name_remaining = sum(1 for line in lines if line["presentation_mode"] == "VOICED"
                              and line.get("display_text") and line.get("original_text") == line.get("display_text")
                              and "(PC" in line["display_text"][:30])
    if self_name_remaining:
        warnings.append("SELF_NAME_PREFIX_REMAINS")
    recent_text: dict[tuple[str, str], int] = {}
    repetition_pairs = []
    for index, line in enumerate(lines):
        normalized = "".join((line.get("display_text") or "").split())
        if len(normalized) < 20:
            continue
        key = (line["speaker_id"], normalized)
        if key in recent_text and index - recent_text[key] <= 10:
            repetition_pairs.append([lines[recent_text[key]]["script_line_id"], line["script_line_id"]])
        recent_text[key] = index
    if repetition_pairs:
        warnings.append("NEARBY_REPETITION_REMAINS")
    return {"status": "PASS" if not failures else "FAIL", "checks": checks, "warnings": warnings,
            "metrics": {"cut_rate": round(cut_rate, 4), "self_name_prefix_remaining": self_name_remaining,
                        "nearby_repetition_pairs": repetition_pairs}}


class M2Pipeline:
    def __init__(self, root: Path, project: Path):
        self.root = Path(root)
        self.project = Path(project)
        self.normalized_path = self.project / "normalized_session.json"
        self.session = read_json(self.normalized_path)
        self.events = self.session["events"]
        self.participant_names = {item["participant_id"]: item["display_name"] for item in self.session["participants"]}
        self.config = read_json(self.root / "config" / "editing_m2.json")
        self.state_path = self.project / "m2_project_state.json"

    def _state(self, status: str, completed: list[str]):
        write_json(self.state_path, {"status": status, "completed_steps": completed})

    def run(self) -> dict:
        protected, dependencies = detect_protected_events(self.events)
        protected_doc = {"schema_version": "0.1", "events": list(protected.values()), "dependencies": dependencies}
        write_json(self.project / "protected_events.json", protected_doc)
        scenes = segment_events(self.events, protected)
        self._state("SCENES_READY", ["protected", "scenes"])

        event_index = {event["event_id"]: event for event in self.events}
        cache = SceneEditCache(self.root / "cache" / "m2_scenes", PROMPT_VERSION)
        all_plans, all_lines, reused, generated = [], [], 0, 0
        for scene in scenes:
            scene_events = [event_index[event_id] for event_id in scene["source_event_ids"]]
            key = cache.key(scene, scene_events, self.config)
            payload = cache.load(scene, key)
            if payload is None:
                payload = edit_scene(scene, scene_events, protected, self.participant_names)
                cache.save(scene, key, payload)
                generated += 1
            else:
                reused += 1
            all_plans.extend(payload["plans"])
            all_lines.extend(payload["lines"])

        metadata = {
            "provider": "local", "model": "deterministic_rule_editor_v1", "prompt_version": PROMPT_VERSION,
            "temperature": 0, "generated_timestamp": datetime.now(timezone.utc).isoformat(),
            "normalized_input_sha256": stable_digest(self.session), "scene_cache_reused": reused,
            "scene_cache_generated": generated,
        }
        edit_plan = {"schema_version": "0.1", "metadata": metadata, "events": all_plans}
        edited_script = {"schema_version": "0.1", "metadata": metadata, "lines": all_lines}
        write_json(self.project / "edit_plan.json", edit_plan)
        write_json(self.project / "edited_script.json", edited_script)
        self._state("EDIT_PLAN_READY", ["protected", "scenes", "edit_plan"])
        self._state("SCRIPT_READY", ["protected", "scenes", "edit_plan", "script"])

        plan_by_id = {plan["source_event_id"]: plan for plan in all_plans}
        continuity = build_continuity_report(self.events, plan_by_id, dependencies, protected)
        continuity["metadata"] = {"provider": "local", "model": "deterministic_continuity_v1",
                                  "prompt_version": CONTINUITY_PROMPT_VERSION}
        write_json(self.project / "continuity_report.json", continuity)
        self._state("CONTINUITY_CHECKED", ["protected", "scenes", "edit_plan", "script", "continuity"])

        qa = editing_qa(self.events, all_plans, all_lines, protected, continuity)
        write_json(self.project / "editing_qa_report.json", qa)
        scene_doc = {"schema_version": "0.1", "scenes": scenes, "part_boundary_candidates": part_candidates(scenes, all_lines)}
        write_json(self.project / "scene_plan.json", scene_doc)
        if qa["status"] == "PASS":
            self._state("QA_PASSED", ["protected", "scenes", "edit_plan", "script", "continuity", "qa"])
        self._write_review(all_plans, all_lines, protected, qa, scenes)
        self._render_previews(all_lines)
        self._state("COMPLETED" if qa["status"] == "PASS" else "QA_FAILED",
                    ["protected", "scenes", "edit_plan", "script", "continuity", "qa", "review", "preview"])
        return {"status": qa["status"], "scenes": len(scenes), "lines": len(all_lines),
                "events": len(all_plans), "review": str(self.project / "review")}

    def _write_review(self, plans, lines, protected, qa, scenes):
        review = self.project / "review"
        review.mkdir(exist_ok=True)
        for decision, filename in (("KEEP", "keep_list.json"), ("COMPRESS", "compress_list.json"), ("CUT", "cut_list.json")):
            write_json(review / filename, [plan for plan in plans if plan["content_decision"] == decision])
        changes = [line for line in lines if line["text_treatment"] not in {"VERBATIM", "NONE"}]
        write_json(review / "text_changes.json", changes)
        write_json(review / "protected_events.json", read_json(self.project / "protected_events.json"))
        write_json(review / "continuity_report.json", read_json(self.project / "continuity_report.json"))
        decision_counts = Counter(plan["content_decision"] for plan in plans)
        mode_counts = Counter(line["presentation_mode"] for line in lines)
        self_cleanup = sum("SELF_NAME_PREFIX" in line["change_reasons"] for line in lines)
        hard = [event_id for event_id, item in protected.items() if item["level"] == "HARD_PROTECTED"]
        hard_kept = sum(next(plan for plan in plans if plan["source_event_id"] == event_id)["content_decision"] != "CUT" for event_id in hard)
        runtime = sum(estimate_line_duration(line) for line in lines)
        summary = f"""# M2 Edit Summary

- source events: {len(plans)}
- scenes: {len(scenes)}
- KEEP: {decision_counts['KEEP']}
- COMPRESS: {decision_counts['COMPRESS']}
- CUT: {decision_counts['CUT']}
- VOICED: {mode_counts['VOICED']}
- SUBTITLE_ONLY: {mode_counts['SUBTITLE_ONLY']}
- OVERLAY_ONLY: {mode_counts['OVERLAY_ONLY']}
- self-name cleanup: {self_cleanup}
- protected event preservation: {hard_kept}/{len(hard)} ({(hard_kept / len(hard) * 100 if hard else 100):.1f}%)
- estimated runtime: {runtime / 60:.1f} min
- editing QA: {qa['status']}
"""
        (review / "edit_summary.md").write_text(summary, encoding="utf-8")

    def _render_previews(self, all_lines):
        review = self.project / "review"
        before = self.root / "projects" / "m1_real_session" / "output" / "m1_real_session.mp4"
        shutil.copyfile(before, review / "preview_before.mp4")
        target_ids = {"norm:session:000161", "norm:session:000162", "norm:session:000165",
                      "norm:session:000166", "norm:session:000167", "norm:session:000169"}
        selected = [line for line in all_lines if target_ids.intersection(line["source_event_ids"])]
        preview = self.root / "projects" / "m2_preview_after"
        preview.mkdir(parents=True, exist_ok=True)
        chars = read_json(self.root / "projects" / "m1_real_session" / "characters.json")
        chars.append({"character_id": "system", "display_name": "SYSTEM", "role": "SYSTEM",
                      "voice_profile_id": None, "subtitle_profile_id": "subtitle_kp", "portrait_asset_id": None})
        write_json(preview / "characters.json", chars)
        profile_for = {"pc_01": ("m1_aq_f1", "subtitle_reimu", "m1_portrait_aquestalk"),
                       "pc_02": ("m1_vv_pc2", "subtitle_marisa", "m1_portrait_voicevox"),
                       "kp": ("m1_vv_kp", "subtitle_kp", None), "system": (None, "subtitle_kp", None)}
        fixture_lines = []
        for line in selected:
            profile, subtitle, portrait = profile_for.get(line["speaker_id"], profile_for["system"])
            dice = None
            if line.get("overlay") and line["overlay"].get("type") == "SKILL_CHECK":
                overlay = line["overlay"]
                dice = {"skill_name": overlay.get("skill"), "target_value": overlay.get("target"),
                        "roll": overlay.get("roll"), "result": overlay.get("result")}
            voice_text = line.get("voice_text")
            if line["speaker_id"] == "pc_01" and line["presentation_mode"] == "VOICED":
                voice_text = "ちらんしたかぐやにもつを、てがかりのかのーせーをさぐってみる。"
            fixture_lines.append({
                "source_event_ids": line["source_event_ids"], "speaker_id": line["speaker_id"],
                "text": line.get("display_text") or "", "voice_text": voice_text,
                "voice_profile_id": profile, "subtitle_profile_id": subtitle, "portrait_asset_id": portrait,
                "event_type": line["event_type"], "dice": dice, "presentation_mode": line["presentation_mode"],
                "fixed_duration_sec": 3.0,
            })
        write_json(preview / "project.json", {"fixture_type": "synthetic", "background_asset_id": "m1_background_fallback",
                                               "lines": fixture_lines})
        renderer = M1Pipeline(self.root, preview)
        script = renderer.prepare_script()
        audio = renderer.render_voices(script)
        timeline = renderer.build_timeline(script, audio)
        output = renderer.render_video(timeline)
        shutil.copyfile(output, review / "preview_after.mp4")
