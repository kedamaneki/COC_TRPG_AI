import copy
import re

from video_agent import SCHEMA_VERSION
from video_agent.schemas.models import empty_event


COMBAT_TYPE_MAP = {
    "COMBAT_STARTED": "COMBAT_START",
    "COMBAT_ENDED": "COMBAT_END",
    "COMBAT_ENDING": "ENDING",
    "COMBAT_ACTION_SELECTED": "COMBAT_ACTION",
    "COMBAT_ACTION_RESOLVED": "COMBAT_ACTION",
    "COMBAT_ACTION_REJECTED": "COMBAT_ACTION",
    "COMBAT_ROUND_STARTED": "COMBAT_ACTION",
}

LIFECYCLE_TYPES = {
    "LOCATION_CHANGE", "MOVEMENT", "STATE_TRANSITION",
    "COMBAT_STARTED", "COMBAT_ENDING", "COMBAT_ENDED",
}

RESULT_CANONICAL = {
    0: "FUMBLE", 1: "FAILURE", 2: "REGULAR_SUCCESS",
    3: "HARD_SUCCESS", 4: "EXTREME_SUCCESS", 5: "CRITICAL_SUCCESS",
    "失敗": "FAILURE", "レギュラー成功": "REGULAR_SUCCESS",
    "ハード成功": "HARD_SUCCESS", "イクストリーム成功": "EXTREME_SUCCESS",
    "決定的成功": "CRITICAL_SUCCESS", "クリティカル": "CRITICAL_SUCCESS",
    "致命的失敗": "FUMBLE", "ファンブル": "FUMBLE",
    "成功": "REGULAR_SUCCESS",
}


def _canonical_result(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return "REGULAR_SUCCESS" if value else "FAILURE"
    if isinstance(value, int) or (isinstance(value, str) and value.strip().isdigit()):
        return RESULT_CANONICAL.get(int(value), str(value))
    token = str(value).strip()
    upper = token.upper().replace(" ", "_")
    if upper in {"FUMBLE", "FAILURE", "REGULAR_SUCCESS", "HARD_SUCCESS",
                 "EXTREME_SUCCESS", "CRITICAL_SUCCESS", "ACTOR_WINS",
                 "OPPONENT_WINS", "HIT", "MISS"}:
        return upper
    for label, canonical in RESULT_CANONICAL.items():
        if isinstance(label, str) and label in token:
            return canonical
    return upper


def _locations(scenarios):
    result = {}
    for scenario in scenarios:
        for location_id, item in (scenario.get("locations") or {}).items():
            result[str(location_id)] = (item or {}).get("name")
    return result


def _scenario_info(source):
    chosen = next(
        (x for x in source["scenarios"] if (x.get("scenario_meta") or {}).get("title")),
        {},
    )
    meta = chosen.get("scenario_meta") or {}
    return {
        "scenario_id": source["result"].get("scenario_file") or "UNKNOWN",
        "scenario_title": meta.get("title"),
        "source": "trpg_evaluation_v2",
        "version": meta.get("version"),
    }


def _participants(source):
    items = [
        {"participant_id": "kp", "display_name": "KP", "role": "KP", "character_id": "kp", "source_actor_id": None},
        {"participant_id": "system", "display_name": "システム", "role": "SYSTEM", "character_id": "system", "source_actor_id": None},
    ]
    for role, group in (("PC", source.get("pcs") or {}), ("NPC", source.get("npcs") or {})):
        for actor_id in sorted(group):
            data = group[actor_id] or {}
            items.append({
                "participant_id": str(actor_id),
                "display_name": (data.get("profile") or {}).get("name") or str(actor_id),
                "role": role,
                "character_id": str(actor_id),
                "source_actor_id": str(actor_id),
            })
    return items


def _location(location_id, names):
    location_id = str(location_id) if location_id not in (None, "") else None
    return {"location_id": location_id, "display_name": names.get(location_id)}


def _explicit_bool(record, name, text):
    if name in record and isinstance(record[name], bool):
        return record[name]
    token = name.lower()
    if token == "critical" and ("クリティカル" in text or "critical" in text.lower()):
        return True
    if token == "fumble" and ("ファンブル" in text or "fumble" in text.lower()):
        return True
    return None


def _dice(record, text=""):
    roll = record.get("roll")
    base_target = record.get("base_target")
    final_target = record.get("final_target", record.get("target_value"))
    target = final_target
    skill = (
        record.get("skill") or record.get("skill_name")
        or record.get("skill_or_stat") or record.get("kp_selected_skill")
        or record.get("proposed_skill")
    )
    match = re.search(r"CC\(1d100<=([0-9]+)\).*?出目:([0-9]+).*?＞\s*([^\r\n]+)", text, re.S)
    if match:
        target = int(match.group(1))
        roll = int(match.group(2))
        result = match.group(3).strip()
        skill_match = re.search(r"【技能:([^】]+)】", text)
        skill = skill or (skill_match.group(1) if skill_match else None)
    else:
        result = record.get("result")
    result = _canonical_result(result)
    raw_result = _canonical_result(record.get("raw_result") or result)
    event_type = str(record.get("event_type") or "").upper()
    recorded_final = _canonical_result(record.get("final_result") or result)
    roll_result = _canonical_result(record.get("roll_result") or recorded_final)
    effect_result = record.get("effect_result")
    objective_outcome = record.get("objective_outcome")
    success_grades = {
        "FAILURE", "FUMBLE", "REGULAR_SUCCESS", "HARD_SUCCESS",
        "EXTREME_SUCCESS", "CRITICAL_SUCCESS", "SUCCESS",
    }
    if event_type == "COMBAT_ACTION_RESOLVED" and str(record.get("resolution_mode") or "").upper() == "ROLL":
        if recorded_final not in success_grades:
            effect_result = effect_result or recorded_final
            roll_result = _canonical_result(record.get("raw_result") or record.get("result_level"))
    if event_type == "SPECIAL_OBJECTIVE_COMPLETED":
        objective_outcome = objective_outcome or record.get("final_result") or "SPECIAL_OBJECTIVE_COMPLETED"
    final_result = roll_result
    if "【幸運消費】" in text and "成功に書き換えた" in text:
        raw_result = "FAILURE"
        final_match = re.search(r"幸運を\s*\d+\s*消費し、\s*([A-Za-z_]+|[^\s]+)\s*成功", text)
        token = (final_match.group(1) if final_match else "regular").upper()
        final_result = {
            "REGULAR": "REGULAR_SUCCESS", "レギュラー": "REGULAR_SUCCESS",
            "HARD": "HARD_SUCCESS", "ハード": "HARD_SUCCESS",
            "EXTREME": "EXTREME_SUCCESS", "イクストリーム": "EXTREME_SUCCESS",
        }.get(token, "REGULAR_SUCCESS")
        roll_result = final_result
    resolution_mode = str(record.get("resolution_mode") or "").upper() or None
    structured_roll = resolution_mode == "ROLL" or bool(record.get("adjudication_evidence"))
    legacy_text_roll = match is not None and bool(text)
    if not structured_roll and not legacy_text_roll and resolution_mode != "NO_ROLL":
        return None
    if roll is None and target is None and not skill and resolution_mode != "NO_ROLL":
        return None
    return {
        "skill_name": skill or None,
        "base_target": base_target,
        "final_target": final_target,
        "target_value": target,
        "roll": roll,
        "result": result,
        "resolution_mode": resolution_mode or ("ROLL" if roll is not None else None),
        "resolution_reason": record.get("resolution_reason") or record.get("reason_code") or record.get("reason"),
        "result_level": _canonical_result(record.get("result_level")),
        "raw_result": raw_result,
        "final_result": final_result,
        "roll_result": roll_result,
        "modifier": (
            record.get("modifier") if record.get("modifier") is not None
            else ({"type": "NONE"} if (resolution_mode or ("ROLL" if roll is not None else None)) == "ROLL" else None)
        ),
        "effect_result": effect_result,
        "objective_outcome": objective_outcome,
        "automatic_result": record.get("automatic_result"),
        "critical": _explicit_bool(record, "critical", text),
        "fumble": _explicit_bool(record, "fumble", text),
    }


def _san(record, text=""):
    structured = record.get("san") if isinstance(record.get("san"), dict) else {}
    event_type = str(record.get("event_type") or "").upper()
    roll_type = str(record.get("roll_type") or "").lower()
    explicit_san = bool(structured) and str(structured.get("kind") or "ADJUDICATION").upper() != "SNAPSHOT"
    explicit_san = explicit_san or "SAN_CHECK" in event_type or "SAN_RESULT" in event_type
    explicit_san = explicit_san or roll_type in {"san", "san_check"} or "【SANチェック】" in text
    if not explicit_san:
        return None
    before = structured.get("before", record.get("SAN_before"))
    after = structured.get("after", record.get("SAN_after"))
    loss = structured.get("loss", record.get("san_loss"))
    roll = structured.get("roll", record.get("san_roll"))
    result = _canonical_result(structured.get("result", record.get("san_result")))
    target = structured.get("target", before)
    source = "STRUCTURED" if structured or any(
        value is not None for value in (before, after, loss, roll, result)
    ) else None
    derived = False
    if source is None and text:
        match = re.search(
            r"【SANチェック】1d100\s*[＞>]\s*(\d+)\s*[＞>]\s*(成功|失敗)"
            r"（現在値[:：]\s*(\d+)）[^\r\n]*?正気度が\s*(\d+)\s*減少",
            text,
        )
        if match:
            roll = int(match.group(1))
            result = "SUCCESS" if match.group(2) == "成功" else "FAILURE"
            before = target = int(match.group(3))
            loss = int(match.group(4))
            after = before - loss
            source = "LEGACY_TEXT_PARSE"
            derived = True
    if source is None:
        return None
    return {
        "san_before": before,
        "san_after": after,
        "san_loss": loss if loss is not None else (
            before - after if isinstance(before, (int, float)) and isinstance(after, (int, float)) else None
        ),
        "before": before,
        "target": target,
        "roll": roll,
        "result": result,
        "loss": loss,
        "after": after,
        "success_loss_formula": structured.get("success_loss_formula"),
        "failure_loss_formula": structured.get("failure_loss_formula"),
        "resolved_loss_formula": structured.get("resolved_loss_formula"),
        "trigger_event_id": structured.get("trigger_event_id"),
        "normalization_source": source,
        "derived_from_legacy_text": derived,
    }


def _modifier(record, text=""):
    value = record.get("modifier") or record.get("luck_modifier")
    if isinstance(value, dict):
        return dict(value)
    match = re.search(
        r"【幸運消費】[^\r\n]*?幸運を\s*(\d+)\s*消費し、\s*([A-Za-z_]+|[^\s]+)\s*成功に書き換えた"
        r"（残り幸運[:：]\s*(\d+)）",
        text,
    )
    if not match:
        return None
    amount, after = int(match.group(1)), int(match.group(3))
    return {
        "type": "LUCK_SPEND", "amount": amount,
        "resource_before": after + amount, "resource_after": after,
        "normalization_source": "LEGACY_TEXT_PARSE",
        "derived_from_legacy_text": True,
    }


def _combat(record):
    if not record.get("combat_id") and not str(record.get("event_type") or "").startswith("COMBAT_"):
        return None
    return {
        "combat_id": record.get("combat_id"),
        "attacker": record.get("actor"),
        "target": record.get("target"),
        "action": record.get("selected_action"),
        "roll": record.get("roll"),
        "damage": record.get("damage"),
        "hp_before": record.get("HP_before"),
        "hp_after": record.get("HP_after"),
    }


def _unified_type(record):
    source_type = str(record.get("event_type") or "")
    if source_type == "MOVE_ACTION_RESOLVED":
        return "MOVE_ACTION_RESOLVED"
    if source_type in {"LOCATION_CHANGE", "MOVEMENT"}:
        return "LOCATION_CHANGE"
    if source_type == "STATE_TRANSITION":
        return "SYSTEM_INTERNAL"
    if source_type in COMBAT_TYPE_MAP:
        return COMBAT_TYPE_MAP[source_type]
    if source_type == "INVESTIGATION_ROLLED":
        return "SKILL_CHECK"
    if source_type == "INVESTIGATION_SUCCEEDED" and (
        record.get("knowledge_gained") or record.get("information_gained")
    ):
        return "CLUE_FOUND"
    if source_type.startswith(("INVESTIGATION_", "SKILL_")):
        return "SCENARIO_EVENT"
    if source_type:
        return "SYSTEM_INTERNAL"
    before = record.get("state_before") or {}
    after = record.get("state_after") or {}
    if record.get("selected_action") == "move" or before.get("location") != after.get("location"):
        return "LOCATION_CHANGE"
    if record.get("dice_used") or record.get("roll") is not None:
        return "SKILL_CHECK"
    if record.get("selected_action"):
        return "ACTION_DECLARATION"
    return "UNKNOWN"


def _normalize_unified(record, index, names):
    source_id = str(record.get("event_id") or f"unified_event:{index:06d}")
    event = empty_event(f"norm:unified:{index:06d}", [source_id], index)
    actor = record.get("actor")
    event.update({
        "turn": record.get("turn_id") or record.get("session_turn_after"),
        "scene_id": record.get("scene_id") or record.get("scene"),
        "location": _location(record.get("location"), names),
        "speaker_id": str(actor) if actor else None,
        "actor_id": str(actor) if actor else None,
        "adjudication_id": record.get("adjudication_id"),
        "cause_adjudication_id": record.get("cause_adjudication_id"),
        "lifecycle_relation_id": record.get("lifecycle_relation_id"),
        "interaction_id": record.get("interaction_id"),
        "event_type": _unified_type(record),
        "text": record.get("text"),
        "action": {
            "action_id": record.get("selected_action"),
            "target": record.get("target"),
            "origin": record.get("action_origin"),
        } if record.get("selected_action") else None,
        "dice": _dice(record),
        "modifier": _modifier(record),
        "san": _san(record, str(record.get("text") or "")),
        "combat": _combat(record),
        "state_changes": record.get("flags_changed") or {},
        "metadata": {"source_stream": "unified_event_log", "source_index": index, "source_payload": record},
    })
    return event


def _speaker_from_text(text, meta, name_to_id):
    for key in ("pc_id", "actor_id", "decision_owner_id"):
        if meta.get(key):
            return str(meta[key])
    if re.match(r"^KP(?:\([^)]*\))?:", text):
        return "kp"
    if text.startswith(("システム:", "[システム]", "【システム")):
        return "system"
    prefix = text.split(":", 1)[0].strip()
    prefix = re.sub(r"\(PC\d+\)(?:\(PL\))?$", "", prefix).strip()
    return name_to_id.get(prefix)


def _session_type(text, meta, speaker):
    if "悪霊の家の呪いは解かれた" in text or "【エンディング】" in text:
        return "ENDING"
    if "【戦闘開始】" in text:
        return "COMBAT_START"
    if "【戦闘終了】" in text:
        return "COMBAT_END"
    if "【移動】" in text:
        return "LOCATION_CHANGE"
    if "SAN" in text and ("減少" in text or "喪失" in text):
        return "SAN_LOSS"
    if "ダメージ" in text or meta.get("damage") is not None:
        return "DAMAGE"
    roll_type = str(meta.get("roll_type") or "")
    if roll_type in {"skill", "san", "combat"} or "CC(" in text:
        return "SAN_CHECK" if roll_type == "san" else "DICE_RESULT"
    if meta.get("action_id") and speaker not in {"system", "kp"}:
        return "ACTION_DECLARATION"
    if speaker == "kp":
        return "KP_DESCRIPTION"
    if speaker == "system" or str(meta.get("channel") or "") == "OOC":
        return "SYSTEM_INTERNAL"
    if speaker:
        return "DIALOGUE"
    return "UNKNOWN"


def _normalize_session_event(record, index, base_order, names, name_to_id):
    meta = dict(record.get("meta") or {})
    source_id = str(meta.get("event_id") or f"session_log:{index:06d}")
    event = empty_event(f"norm:session:{index:06d}", [source_id], base_order + index)
    text = str(record.get("text") or "")
    speaker = _speaker_from_text(text, meta, name_to_id)
    event.update({
        "turn": meta.get("turn_id"),
        "scene_id": meta.get("scene_id"),
        "location": _location(record.get("location"), names),
        "speaker_id": speaker,
        "actor_id": str(meta.get("actor_id")) if meta.get("actor_id") else None,
        "adjudication_id": meta.get("adjudication_id"),
        "cause_adjudication_id": meta.get("cause_adjudication_id"),
        "lifecycle_relation_id": meta.get("lifecycle_relation_id"),
        "interaction_id": meta.get("interaction_id"),
        "event_type": _session_type(text, meta, speaker),
        "text": text,
        "action": {
            "action_id": meta.get("action_id"), "target": meta.get("target"),
            "origin": meta.get("action_origin"),
        } if meta.get("action_id") else None,
        "dice": _dice(meta, text),
        "modifier": _modifier(meta, text),
        "san": _san(meta, text),
        "combat": _combat(meta),
        "state_changes": meta.get("flags_changed") or {},
        "metadata": {
            "source_stream": "session_log", "source_index": index,
            "channel": record.get("channel"), "secret_to": record.get("secret_to"),
            "source_payload": record,
        },
    })
    return event


def _separate_location_lifecycle(event):
    """Split a legacy mixed movement row without inventing evidence."""
    if event.get("event_type") != "LOCATION_CHANGE":
        return [event]
    dice = event.get("dice") or {}
    mode = str(dice.get("resolution_mode") or "").upper()
    adjudication_id = event.get("adjudication_id")
    if mode not in {"ROLL", "NO_ROLL"}:
        event["adjudication_id"] = None
        event["dice"] = None
        event["modifier"] = None
        return [event]

    reason = dice.get("resolution_reason") or dice.get("reason_code") or dice.get("reason")
    outcome = dice.get("final_result") or dice.get("automatic_result")
    complete = bool(adjudication_id) and (
        mode == "ROLL" or (reason not in (None, "") and outcome not in (None, ""))
    )
    if not complete:
        # Keep invalid evidence visible so the formal detector rejects it.
        return [event]

    adjudication = copy.deepcopy(event)
    adjudication["event_id"] = f"{event['event_id']}:adjudication"
    adjudication["event_type"] = "MOVE_ACTION_RESOLVED"
    adjudication["metadata"]["normalized_role"] = "movement_adjudication"

    lifecycle = copy.deepcopy(event)
    lifecycle["adjudication_id"] = None
    lifecycle["dice"] = None
    lifecycle["modifier"] = None
    lifecycle["metadata"]["normalized_role"] = "location_lifecycle"
    lifecycle["metadata"]["cause_adjudication_id"] = str(adjudication_id)
    lifecycle["cause_adjudication_id"] = str(adjudication_id)
    return [adjudication, lifecycle]


def _dedupe_simple_moves(events):
    """Pair lifecycle authority/display records by explicit identity first."""
    def simple(event):
        payload = event['metadata']['source_payload']
        meta = payload.get('meta', payload)
        return (event.get('event_type') == 'LOCATION_CHANGE'
                and not event.get('cause_adjudication_id')
                and not event.get('adjudication_id')
                and not meta.get('resolution_mode')
                and not event.get('dice'))

    def value(event, key):
        payload = event['metadata']['source_payload']
        return (payload.get('meta') or payload).get(key)

    def compatible(u, s):
        up, sp = u['metadata']['source_payload'], s['metadata']['source_payload']
        sm = sp.get('meta') or {}
        before = (up.get('state_before') or {}).get('location')
        after = (up.get('state_after') or {}).get('location')
        if (up.get('event_type') != 'LOCATION_CHANGE' or up.get('selected_action') != 'move'
                or sm.get('action_id') != 'move' or sm.get('roll_type') != 'none'
                or not before or not after or before == after
                or before != up.get('location') or before != sp.get('location')
                or after != up.get('target') or after != sm.get('target')):
            return False
        if sm.get('actor_id') and sm['actor_id'] != up.get('actor'):
            return False
        if not up.get('event_id') or up.get('raw_event_offset') is None:
            return False
        return True

    unified = [e for e in events if simple(e) and e['metadata']['source_stream'] == 'unified_event_log']
    session = [e for e in events if simple(e) and e['metadata']['source_stream'] == 'session_log']
    # Inferred legacy rows are not authoritative lifecycle records.
    if any(e['metadata']['source_payload'].get('event_type') != 'LOCATION_CHANGE' for e in unified):
        return events

    pairs = []
    used_u, used_s = set(), set()

    def pair_by_unique_key(key, method):
        um, sm = {}, {}
        for index, row in enumerate(unified):
            if index in used_u or (key == 'transaction_id' and value(row, 'lifecycle_relation_id')):
                continue
            token = str(value(row, key) or '')
            if token:
                if token in um:
                    raise ValueError(f'DEDUP_AMBIGUOUS: duplicate Unified {key}')
                um[token] = index
        for index, row in enumerate(session):
            if index in used_s or (key == 'transaction_id' and value(row, 'lifecycle_relation_id')):
                continue
            token = str(value(row, key) or '')
            if token:
                if token in sm:
                    raise ValueError(f'DEDUP_AMBIGUOUS: duplicate Session {key}')
                sm[token] = index
        for token in sorted(set(um) & set(sm), key=lambda item: um[item]):
            ui, si = um[token], sm[token]
            if ui in used_u or si in used_s:
                raise ValueError(f'DEDUP_AMBIGUOUS: overlapping {key} relation')
            if not compatible(unified[ui], session[si]):
                raise ValueError(f'DEDUP_RELATION_CONTRADICTION: {key}={token}')
            pairs.append((unified[ui], session[si], method))
            used_u.add(ui)
            used_s.add(si)

    # Producer relation is authoritative.
    pair_by_unique_key('lifecycle_relation_id', 'lifecycle_relation_id')

    # Historical structured Simple Move streams are accepted only as a full,
    # ordered bijection.  One bad/missing row disables the whole legacy merge.
    remaining_u = [(i, row) for i, row in enumerate(unified) if i not in used_u]
    remaining_s = [(i, row) for i, row in enumerate(session) if i not in used_s]
    if remaining_u or remaining_s:
        if sum(not value(row, 'transaction_id') for _, row in remaining_u) > 1 or sum(
            not value(row, 'transaction_id') for _, row in remaining_s
        ) > 1:
            raise ValueError('DEDUP_AMBIGUOUS: multiple unkeyed simple moves')
        if len(remaining_u) != len(remaining_s):
            return events
        u_transactions = [str(value(row, 'transaction_id') or '') for _, row in remaining_u]
        s_transactions = [str(value(row, 'transaction_id') or '') for _, row in remaining_s]
        for transactions in (u_transactions, s_transactions):
            explicit = [token for token in transactions if token]
            if len(explicit) != len(set(explicit)):
                raise ValueError('DEDUP_DUPLICATE_TRANSACTION_ID: simple move correspondence is not unique')
            if transactions.count('') > 1:
                raise ValueError('DEDUP_AMBIGUOUS: multiple unkeyed simple moves')
        legacy_pairs = []
        for (ui, u), (si, s), ut, st in zip(
            remaining_u, remaining_s, u_transactions, s_transactions,
        ):
            if ut != st or not compatible(u, s):
                return events
            if not ut and u['metadata']['source_payload'].get('forced_action') is not True:
                return events
            legacy_pairs.append((u, s, 'transaction_id' if ut else 'narrow_forced_transition_compatibility'))
        # Do not accept a stream consisting only of an unkeyed heuristic pair.
        if legacy_pairs and not any(u_transactions):
            return events
        pairs.extend(legacy_pairs)

    removed = set()
    for u, s, method in pairs:
        u['source_event_ids'] = list(dict.fromkeys(u['source_event_ids'] + s['source_event_ids']))
        u['metadata']['simple_move_relation'] = {
            'method': method, 'authority_event_id': u['metadata']['source_payload']['event_id'],
            'display_source_event_ids': list(s['source_event_ids']),
            'display_source_payload': copy.deepcopy(s['metadata']['source_payload']),
        }
        removed.add(id(s))
    return [e for e in events if id(e) not in removed]


def _dedupe_movement_pairs(events):
    """Coalesce Unified/Session counterparts while retaining every source id."""
    result = []
    positions = {}
    for event in events:
        event_type = event.get("event_type")
        cause = event.get("cause_adjudication_id") or (event.get("metadata") or {}).get("cause_adjudication_id")
        aid = event.get("adjudication_id")
        key = None
        if event_type == "MOVE_ACTION_RESOLVED" and aid:
            key = (event_type, str(aid))
        elif event_type == "LOCATION_CHANGE" and cause:
            key = (event_type, str(cause))
        if key is None or key not in positions:
            if key is not None:
                positions[key] = len(result)
            result.append(event)
            continue
        current = result[positions[key]]
        current_stream = (current.get("metadata") or {}).get("source_stream")
        new_stream = (event.get("metadata") or {}).get("source_stream")
        preferred, other = (
            (event, current)
            if new_stream == "unified_event_log" and current_stream != "unified_event_log"
            else (current, event)
        )
        preferred["source_event_ids"] = list(dict.fromkeys(
            list(preferred.get("source_event_ids") or [])
            + list(other.get("source_event_ids") or [])
        ))
        result[positions[key]] = preferred
    return result


def _merge_adjudications(events, warnings):
    """Propagate unambiguous structured evidence by explicit adjudication id."""
    groups = {}
    for event in events:
        aid = event.get("adjudication_id")
        if aid:
            mode = str((event.get("dice") or {}).get("resolution_mode") or "UNSPECIFIED")
            groups.setdefault((str(aid), mode), []).append(event)
    for (aid, mode), rows in groups.items():
        for section in ("dice", "san", "modifier"):
            authoritative_keys = set()
            keys = set()
            for row in rows:
                if isinstance(row.get(section), dict):
                    keys.update(row[section])
            merged = {}
            for key in keys:
                values = []
                for row in rows:
                    value = (row.get(section) or {}).get(key) if isinstance(row.get(section), dict) else None
                    if value is not None and value not in values:
                        values.append(value)
                if len(values) == 1:
                    merged[key] = values[0]
                elif len(values) > 1:
                    if section == "dice" and key == "modifier":
                        substantive = [
                            value for value in values
                            if not (isinstance(value, dict) and value.get("type") == "NONE")
                        ]
                        if len(substantive) == 1:
                            merged[key] = substantive[0]
                            continue
                    # Structured unified evidence outranks legacy text parsing.
                    # Conflicts within the same source tier still fail loudly.
                    structured_values = []
                    for row in rows:
                        if (row.get("metadata") or {}).get("source_stream") != "unified_event_log":
                            continue
                        value = (row.get(section) or {}).get(key) if isinstance(row.get(section), dict) else None
                        if value is not None and value not in structured_values:
                            structured_values.append(value)
                    if len(structured_values) == 1:
                        merged[key] = structured_values[0]
                        authoritative_keys.add(key)
                        continue
                    # Luck rows are later phases of the same adjudication.  The
                    # post-modifier final result supersedes the raw roll phase.
                    if section == "dice" and key in {"final_result", "roll_result"}:
                        post_modifier = [
                            (row.get("dice") or {}).get(key)
                            for row in rows
                            if isinstance(row.get("modifier"), dict)
                            and (row.get("dice") or {}).get(key) is not None
                        ]
                        post_modifier = list(dict.fromkeys(post_modifier))
                        if len(post_modifier) == 1:
                            merged[key] = post_modifier[0]
                            continue
                    # result and result_level express the same success grade in
                    # different source schemas; canonicalization removes merely
                    # textual disagreements before this comparison.
                    if section == "dice" and key in {"result", "result_level"}:
                        canonical = list(dict.fromkeys(_canonical_result(v) for v in values))
                        if len(canonical) == 1:
                            merged[key] = canonical[0]
                            continue
                    warning = {
                        "code": "NORMALIZATION_SOURCE_CONTRADICTION",
                        "adjudication_id": aid,
                        "field": f"{section}.{key}",
                        "values": values,
                    }
                    if warning not in warnings:
                        warnings.append(warning)
            if not merged:
                continue
            for row in rows:
                current = dict(row.get(section) or {})
                for key, value in merged.items():
                    if key in authoritative_keys or (section == "dice" and key in {"final_result", "roll_result"}):
                        current[key] = value
                    else:
                        current.setdefault(key, value)
                row[section] = current
    # Declaration rows intentionally carry no resolution mode.  Once exactly
    # one authoritative phase exists, copy its evidence for downstream viewers
    # without pretending the declaration itself was another adjudication.
    by_aid = {}
    for event in events:
        if event.get("adjudication_id"):
            by_aid.setdefault(str(event["adjudication_id"]), []).append(event)
    for rows in by_aid.values():
        explicit = [row for row in rows if str((row.get("dice") or {}).get("resolution_mode") or "") in {"ROLL", "NO_ROLL"}]
        modes = {str((row.get("dice") or {}).get("resolution_mode")) for row in explicit}
        if len(modes) != 1:
            continue
        source = max(explicit, key=lambda row: len([v for v in (row.get("dice") or {}).values() if v is not None]), default=None)
        if source is None:
            continue
        for row in rows:
            if row.get("dice") is None:
                row["dice"] = copy.deepcopy(source.get("dice"))


def normalize_session(source):
    participants = _participants(source)
    name_to_id = {x["display_name"]: x["participant_id"] for x in participants}
    names = _locations(source["scenarios"])
    unified = []
    for i, record in enumerate(source["unified_events"]):
        unified.extend(_separate_location_lifecycle(_normalize_unified(record, i, names)))
    session = []
    for i, record in enumerate(source["session_events"]):
        session.extend(_separate_location_lifecycle(
            _normalize_session_event(record, i, len(unified), names, name_to_id)
        ))
    warnings = []
    for event in session:
        if event["speaker_id"] is None and event["event_type"] in {"DIALOGUE", "UNKNOWN"}:
            event["metadata"].setdefault("validation_warnings", []).append("UNKNOWN_SPEAKER")
            warnings.append({"code": "UNKNOWN_SPEAKER", "event_id": event["event_id"]})
        if "【SANチェック】" in str(event.get("text") or "") and event.get("san") is None:
            event["metadata"].setdefault("validation_warnings", []).append("SAN_PARSE_FAILED")
            warnings.append({"code": "SAN_PARSE_FAILED", "event_id": event["event_id"]})
    events = _dedupe_movement_pairs(_dedupe_simple_moves(unified + session))
    _merge_adjudications(events, warnings)
    expected_source_ids = [
        str(record.get("event_id") or f"unified_event:{i:06d}")
        for i, record in enumerate(source["unified_events"])
    ] + [
        str((record.get("meta") or {}).get("event_id") or f"session_log:{i:06d}")
        for i, record in enumerate(source["session_events"])
    ]
    result = source["result"]
    return {
        "schema_version": SCHEMA_VERSION,
        "session_id": result.get("session_id") or "UNKNOWN",
        "scenario": _scenario_info(source),
        "participants": participants,
        "events": events,
        "metadata": {
            "source_kind": "trpg_evaluation_v2",
            "seed": result.get("seed"),
            "completed": result.get("completed"),
            "phase": result.get("phase"),
            "turns": result.get("turns"),
            "cycles": result.get("cycles"),
            "conversion_warnings": warnings,
        },
        "provenance": {
            "source_root": source["root"],
            "source_files": source["source_files"],
            "source_event_count": len(expected_source_ids),
            "source_event_ids": expected_source_ids,
            "source_stream_counts": {
                "unified_event_log": len(source["unified_events"]),
                "session_log": len(source["session_events"]),
            },
        },
    }
