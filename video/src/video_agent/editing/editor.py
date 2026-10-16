from __future__ import annotations

import re
from pathlib import Path

from video_agent.common.io import read_json, stable_digest, write_json


TECHNICAL_MARKERS = (
    "session director", "progress director", "stall detector", "availability contract",
    "checkpoint", "system_forced", "llm", "再生成上限", "システム検証エラー",
    "アクション自動補正", "解釈ログ", "システム通知", "システム支援",
)
SYSTEM_MODES = {"DICE_RESULT", "SKILL_CHECK", "SAN_CHECK", "SAN_LOSS", "DAMAGE"}


def source_ids(event: dict) -> list[str]:
    return list(dict.fromkeys([event["event_id"], *(event.get("source_event_ids") or [])]))


def cleanup_text(event: dict, participant_names: dict[str, str]) -> tuple[str | None, str, list[str]]:
    text = event.get("text")
    if not text:
        return None, "VERBATIM", []
    speaker = event.get("speaker_id") or event.get("actor_id")
    name = participant_names.get(speaker)
    patterns = []
    if name:
        patterns.append((rf"^{re.escape(name)}(?:\(PC\d+\))?(?:\(PL\))?\s*[:：]\s*", "SELF_NAME_PREFIX"))
    if speaker == "kp":
        patterns.append((r"^KP\s*[:：]\s*", "SYSTEM_METADATA_REMOVED"))
    for pattern, reason in patterns:
        match = re.match(pattern, text)
        if match and match.end() < len(text):
            return text[match.end():].strip(), "TRIM_REDUNDANCY", [reason]
    return text, "VERBATIM", []


def overlay_for(event: dict) -> dict | None:
    dice = event.get("dice") or {}
    san = event.get("san") or {}
    combat = event.get("combat") or {}
    if dice.get("roll") is not None or dice.get("skill_name"):
        return {"type": "SKILL_CHECK", "skill": dice.get("skill_name"), "target": dice.get("target_value"),
                "roll": dice.get("roll"), "result": dice.get("result")}
    if event["event_type"] in {"SAN_CHECK", "SAN_LOSS"}:
        return {"type": "SAN", "before": san.get("san_before"), "after": san.get("san_after"),
                "loss": san.get("san_loss"), "result": san.get("result")}
    if event["event_type"].startswith("COMBAT") or event["event_type"] == "DAMAGE":
        return {"type": event["event_type"], "attacker": combat.get("attacker"), "target": combat.get("target"),
                "action": combat.get("action"), "damage": combat.get("damage")}
    if event.get("state_changes"):
        return {"type": "STATE_CHANGE", "changes": event["state_changes"]}
    if event["event_type"] in {"CLUE_FOUND", "LOCATION_CHANGE", "ITEM_GAINED", "ITEM_LOST"}:
        return {"type": event["event_type"], "location": (event.get("location") or {}).get("display_name")}
    return None


def _technical_text(event: dict) -> bool:
    text = (event.get("text") or "").lower()
    return event["event_type"] == "SYSTEM_INTERNAL" or any(marker in text for marker in TECHNICAL_MARKERS)


def edit_scene(scene: dict, events: list[dict], protected: dict[str, dict], participant_names: dict[str, str]) -> dict:
    plans, lines, plan_by_id = [], [], {}
    recent: dict[tuple[str, str], tuple[int, dict, dict]] = {}
    for position, event in enumerate(events):
        event_id = event["event_id"]
        protection = protected[event_id]
        original = event.get("text")
        edited, treatment, reasons = cleanup_text(event, participant_names)
        plan = {
            "source_event_id": event_id, "scene_id": scene["scene_id"], "protection_level": protection["level"],
            "content_decision": "KEEP", "presentation_mode": "VOICED", "text_treatment": treatment,
            "original_text": original, "edited_text": edited, "change_reasons": reasons,
            "output_script_line_id": None, "compress_into": None, "confidence": 1.0,
        }

        if _technical_text(event) and protection["level"] == "NORMAL":
            plan.update(content_decision="CUT", presentation_mode="NONE", text_treatment="NONE", edited_text=None,
                        change_reasons=["TECHNICAL_LOG"])
        elif event["event_type"] in SYSTEM_MODES:
            plan.update(presentation_mode="OVERLAY_ONLY", text_treatment="VERBATIM",
                        change_reasons=["SYSTEM_PRESENTATION_SEPARATION"])
        elif event["event_type"] in {"COMBAT_START", "COMBAT_END", "ENDING"}:
            plan.update(presentation_mode="SUBTITLE_ONLY" if original else "OVERLAY_ONLY",
                        change_reasons=["SYSTEM_PRESENTATION_SEPARATION"])
        elif event["event_type"] in {"LOCATION_CHANGE"}:
            plan.update(presentation_mode="SUBTITLE_ONLY" if original else "OVERLAY_ONLY")
        elif not original:
            if protection["level"] in {"HARD_PROTECTED", "SOFT_PROTECTED"}:
                plan.update(presentation_mode="OVERLAY_ONLY", text_treatment="VERBATIM")
            else:
                plan.update(content_decision="CUT", presentation_mode="NONE", text_treatment="NONE", edited_text=None,
                            change_reasons=["NON_VIEWER_TELEMETRY"])
        elif (original.startswith("システム:") or original.startswith("[システム]")) and plan["presentation_mode"] == "VOICED":
            plan.update(presentation_mode="SUBTITLE_ONLY", text_treatment="LIGHT_NORMALIZE",
                        change_reasons=["SYSTEM_METADATA_REMOVED"])

        if plan["content_decision"] != "CUT" and edited:
            key = (event.get("speaker_id") or "", re.sub(r"\s+", "", edited))
            prior = recent.get(key)
            if prior and position - prior[0] <= 10 and protection["level"] == "NORMAL":
                prior_plan, prior_line = prior[1], prior[2]
                plan.update(content_decision="COMPRESS", presentation_mode=prior_plan["presentation_mode"],
                            text_treatment="COMPRESSED", edited_text=prior_line["display_text"],
                            compress_into=prior_line["script_line_id"], output_script_line_id=prior_line["script_line_id"],
                            change_reasons=["DUPLICATE_PHRASE", "COMPRESSION"])
                prior_plan["content_decision"] = "COMPRESS"
                prior_plan["text_treatment"] = "COMPRESSED"
                prior_line["content_decision"] = "COMPRESS"
                prior_line["text_treatment"] = "COMPRESSED"
                prior_line["source_event_ids"].extend(value for value in source_ids(event) if value not in prior_line["source_event_ids"])
            else:
                line_id = f"{scene['scene_id']}_script_{len(lines) + 1:03d}"
                line = {
                    "script_line_id": line_id, "scene_id": scene["scene_id"], "source_event_ids": source_ids(event),
                    "speaker_id": event.get("speaker_id") or event.get("actor_id") or "system",
                    "event_type": event["event_type"], "content_decision": plan["content_decision"],
                    "presentation_mode": plan["presentation_mode"], "text_treatment": plan["text_treatment"],
                    "original_text": original, "display_text": edited,
                    "voice_text": edited if plan["presentation_mode"] == "VOICED" else None,
                    "overlay": overlay_for(event), "change_reasons": plan["change_reasons"],
                }
                lines.append(line)
                plan["output_script_line_id"] = line_id
                recent[key] = (position, plan, line)
        elif plan["content_decision"] != "CUT":
            line_id = f"{scene['scene_id']}_script_{len(lines) + 1:03d}"
            line = {
                "script_line_id": line_id, "scene_id": scene["scene_id"], "source_event_ids": source_ids(event),
                "speaker_id": event.get("speaker_id") or event.get("actor_id") or "system",
                "event_type": event["event_type"], "content_decision": plan["content_decision"],
                "presentation_mode": plan["presentation_mode"], "text_treatment": plan["text_treatment"],
                "original_text": original, "display_text": None, "voice_text": None,
                "overlay": overlay_for(event), "change_reasons": plan["change_reasons"],
            }
            lines.append(line)
            plan["output_script_line_id"] = line_id
        plans.append(plan)
        plan_by_id[event_id] = plan
    return {"plans": plans, "lines": lines}


class SceneEditCache:
    def __init__(self, directory: Path, prompt_version: str):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.prompt_version = prompt_version

    def key(self, scene: dict, events: list[dict], config: dict) -> str:
        return stable_digest({"scene": scene, "events": events, "config": config, "prompt_version": self.prompt_version})

    def load(self, scene: dict, key: str) -> dict | None:
        path = self.directory / f"{scene['scene_id']}.json"
        if not path.exists():
            return None
        value = read_json(path)
        return value["payload"] if value.get("cache_key") == key else None

    def save(self, scene: dict, key: str, payload: dict) -> None:
        write_json(self.directory / f"{scene['scene_id']}.json", {"cache_key": key, "payload": payload})
