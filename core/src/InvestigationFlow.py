"""Generic investigation adjudication and attempt-right tracking.

This module deliberately knows nothing about a particular scenario.  The
scenario describes the legal skills and no-roll cases; this layer records who
has tried which legal approach under which circumstances.
"""
from __future__ import annotations

import copy
from EventIdentity import append_unified_event
import hashlib
import json
import uuid


INVESTIGATION_ACTIONS = frozenset({"search", "inspect", "read", "listen", "spot"})

AVAILABLE = "AVAILABLE"
SUCCEEDED = "SUCCEEDED"
FAILED = "FAILED"
PUSH_AVAILABLE = "PUSH_AVAILABLE"
EXHAUSTED = "EXHAUSTED"
RESET_BY_CONTEXT_CHANGE = "RESET_BY_CONTEXT_CHANGE"

NO_ROLL_REQUIRED = "NO_ROLL_REQUIRED"
ROLL_WITH_PRIMARY_SKILL = "ROLL_WITH_PRIMARY_SKILL"
ROLL_WITH_PROPOSED_SKILL = "ROLL_WITH_PROPOSED_SKILL"
ROLL_WITH_ALTERNATIVE_SKILL = "ROLL_WITH_ALTERNATIVE_SKILL"
REJECT_SKILL_PROPOSAL = "REJECT_SKILL_PROPOSAL"
ACTION_NOT_POSSIBLE = "ACTION_NOT_POSSIBLE"

INVESTIGATION_EVENT_TYPES = frozenset({
    "INVESTIGATION_DECLARED", "SKILL_PROPOSED", "SKILL_APPROVED",
    "SKILL_REJECTED", "ROLL_NOT_REQUIRED", "INVESTIGATION_ROLLED",
    "INVESTIGATION_FAILED", "INVESTIGATION_SUCCEEDED", "ATTEMPT_EXHAUSTED",
    "PUSH_DECLARED", "INFORMATION_SHARED", "KP_RESCUE_ROUTE_CREATED",
    "INVESTIGATION_TARGET_EXHAUSTED",
})


def ensure_investigation_state(state):
    """Return a normalized, save-safe investigation runtime dictionary."""
    if not isinstance(state, dict):
        raise TypeError("state must be a dict")
    flow = state.setdefault("investigation_flow", {})
    if not isinstance(flow, dict):
        flow = state["investigation_flow"] = {}
    flow.setdefault("attempts", {})
    flow.setdefault("target_context_revisions", {})
    flow.setdefault("rejected_skills", {})
    flow.setdefault("target_status", {})
    flow.setdefault("rescue_routes", [])
    return flow


def _object_info(scenario_mgr, location, target):
    if not scenario_mgr or not target:
        return {}
    try:
        return scenario_mgr.get_object_info(location, target) or {}
    except TypeError:
        return scenario_mgr.get_object_info(target) or {}


def context_version(state, scenario_mgr, location, target):
    """Build a stable version that changes only for relevant circumstances."""
    flow = ensure_investigation_state(state)
    key = f"{location}|{target}"
    revision = int((flow.get("target_context_revisions") or {}).get(key, 0) or 0)
    obj = _object_info(scenario_mgr, location, target)
    flags = getattr(scenario_mgr, "flags", {}) or {}
    watched = obj.get("retry_context_flags") or obj.get("context_flags") or []
    if isinstance(watched, str):
        watched = [watched]
    flag_values = [(str(name), copy.deepcopy(flags.get(str(name)))) for name in watched]
    raw = {
        "location": str(location or ""),
        "phase": str(getattr(scenario_mgr, "current_phase", "") or ""),
        "revision": revision,
        "object_version": obj.get("context_version", 0),
        "flags": flag_values,
    }
    digest = hashlib.sha1(
        json.dumps(raw, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:12]
    return f"{location}:{target}:{digest}"


def advance_context(state, location, target, *, reason="situation_changed"):
    """Explicitly reopen attempts after a real tool/evidence/environment change."""
    flow = ensure_investigation_state(state)
    key = f"{location}|{target}"
    versions = flow["target_context_revisions"]
    versions[key] = int(versions.get(key, 0) or 0) + 1
    for attempt in flow["attempts"].values():
        if attempt.get("location") == location and attempt.get("target_id") == target:
            if attempt.get("attempt_status") in {FAILED, EXHAUSTED, PUSH_AVAILABLE}:
                attempt["reset_reason"] = str(reason or "situation_changed")
                attempt["attempt_status"] = RESET_BY_CONTEXT_CHANGE
    flow["target_status"].pop(key, None)
    return versions[key]


def _attempt_key(actor_id, target_id, skill_id, version):
    return "|".join(str(x or "") for x in (actor_id, target_id, skill_id, version))


def get_attempt_right(state, actor_id, target_id, skill_id, version):
    flow = ensure_investigation_state(state)
    record = flow["attempts"].get(_attempt_key(actor_id, target_id, skill_id, version))
    if not record:
        return AVAILABLE
    return str(record.get("attempt_status") or AVAILABLE)


def check_attempt_right(state, actor_id, target_id, skill_id, version, *, is_push=False):
    status = get_attempt_right(state, actor_id, target_id, skill_id, version)
    if is_push:
        allowed = status == PUSH_AVAILABLE
    else:
        allowed = status in {AVAILABLE, RESET_BY_CONTEXT_CHANGE}
    return {
        "allowed": allowed,
        "status": status,
        "reason": "" if allowed else (
            "このPCは同じ対象・技能・状況で既に判定済みです。"
            "プッシュ、別PC、別アプローチ、状況変化、または別対象を選んでください。"
        ),
    }


def adjudicate_investigation(
    scenario_mgr, action_id, target, *, proposed_skill="", proposal_reason="",
    location="", kp_selected_skill="", kp_no_roll=False, kp_action_possible=True,
):
    """Resolve scenario-first skill selection while retaining KP discretion."""
    action_id = str(action_id or "").lower()
    proposed = str(proposed_skill or "").strip()
    reason = str(proposal_reason or "").strip()
    if action_id not in INVESTIGATION_ACTIONS or not target or not kp_action_possible:
        return {
            "adjudication": ACTION_NOT_POSSIBLE, "roll_required": False,
            "selected_skill": "", "primary_skill": "", "allowed_skills": [],
            "proposed_skill": proposed, "proposal_reason": reason,
            "alternative_skill_requested": bool(proposed),
            "alternative_skill_approved": False,
        }

    required = scenario_mgr.get_required_check(action_id, target, location)
    if kp_no_roll or (required and required.get("type") == "no_roll"):
        return {
            "adjudication": NO_ROLL_REQUIRED, "roll_required": False,
            "selected_skill": "", "primary_skill": "", "allowed_skills": [],
            "proposed_skill": proposed, "proposal_reason": reason,
            "alternative_skill_requested": bool(proposed),
            "alternative_skill_approved": False, "required_check": required,
        }

    resolved = scenario_mgr.resolve_investigation_skill(
        action_id, target, proposed_skill=proposed, loc_id=location,
        required_check=required,
    )
    allowed = list(resolved.get("allowed_skills") or [])
    primary = allowed[0] if allowed else str(resolved.get("skill_name") or "")
    selected = str(resolved.get("skill_name") or primary)
    kp_skill = str(kp_selected_skill or "").strip()
    if kp_skill:
        # A KP alternative must either be scenario-listed or carry an explicit
        # reason.  This prevents blind skill-list enumeration.
        if kp_skill in allowed or reason:
            selected = kp_skill
            adjudication = (
                ROLL_WITH_PRIMARY_SKILL if kp_skill == primary else ROLL_WITH_ALTERNATIVE_SKILL
            )
            approved = kp_skill != primary
        else:
            adjudication = REJECT_SKILL_PROPOSAL
            selected = primary
            approved = False
    elif proposed and proposed in allowed:
        selected = proposed
        adjudication = (
            ROLL_WITH_PRIMARY_SKILL if proposed == primary else ROLL_WITH_PROPOSED_SKILL
        )
        approved = proposed != primary
    elif proposed:
        adjudication = REJECT_SKILL_PROPOSAL
        selected = primary
        approved = False
    else:
        adjudication = ROLL_WITH_PRIMARY_SKILL
        selected = primary
        approved = False

    check = dict(resolved.get("required_check") or {})
    if check.get("type") == "skill":
        check["skill_name"] = selected
    return {
        "adjudication": adjudication,
        "roll_required": True,
        "selected_skill": selected,
        "primary_skill": primary,
        "allowed_skills": allowed,
        "proposed_skill": proposed,
        "proposal_reason": reason,
        "alternative_skill_requested": bool(proposed and proposed != primary),
        "alternative_skill_approved": approved,
        "required_check": check or required,
    }


def prepare_investigation(
    state, scenario_mgr, *, actor_id, action_id, target, location,
    proposed_skill="", proposal_reason="", kp_selected_skill="",
    kp_no_roll=False, is_push=False,
):
    adjudication = adjudicate_investigation(
        scenario_mgr, action_id, target, proposed_skill=proposed_skill,
        proposal_reason=proposal_reason, location=location,
        kp_selected_skill=kp_selected_skill, kp_no_roll=kp_no_roll,
    )
    version = context_version(state, scenario_mgr, location, target)
    skill = adjudication.get("selected_skill") or "__NO_ROLL__"
    right = check_attempt_right(
        state, actor_id, target, skill, version, is_push=is_push,
    )
    investigation_id = uuid.uuid4().hex
    return {
        "investigation_id": investigation_id,
        "actor_id": str(actor_id or ""),
        "action_id": str(action_id or ""),
        "target_id": str(target or ""),
        "location": str(location or ""),
        "context_version": version,
        "skill_id": skill,
        "attempt_right_before": right["status"],
        "attempt_allowed": right["allowed"],
        "attempt_block_reason": right["reason"],
        "retry_type": "PUSH" if is_push else "NORMAL",
        **adjudication,
    }


RESOLUTION_EVENTS = frozenset({
    "ROLL_NOT_REQUIRED", "INVESTIGATION_ROLLED", "INVESTIGATION_FAILED",
    "INVESTIGATION_SUCCEEDED",
})


def _event_base(ctx, *, include_evidence=False):
    row = {
        "investigation_id": ctx.get("investigation_id", ""),
        "transaction_id": ctx.get("transaction_id", ""),
        "adjudication_id": ctx.get("adjudication_id", ""),
        "parent_adjudication_id": ctx.get("parent_adjudication_id"),
        "interaction_id": ctx.get("interaction_id", ""),
        "actor": ctx.get("actor_id", ""),
        "target": ctx.get("target_id", ""),
        "action_intent": ctx.get("action_intent", ""),
        "proposed_skill": ctx.get("proposed_skill", ""),
        "kp_selected_skill": ctx.get("selected_skill", ""),
        "adjudication": ctx.get("adjudication", ""),
        "roll_required": bool(ctx.get("roll_required")),
        "state_before": copy.deepcopy(ctx.get("state_before") or {}),
        "state_after": copy.deepcopy(ctx.get("state_after") or {}),
        "cause_event_ids": list(ctx.get("cause_event_ids") or []),
        "result_event_ids": list(ctx.get("result_event_ids") or []),
        "attempt_right_before": ctx.get("attempt_right_before", AVAILABLE),
        "attempt_right_after": ctx.get("attempt_right_after", ""),
        "result": ctx.get("result"),
        "information_gained": list(ctx.get("information_gained") or []),
        "information_shared": list(ctx.get("information_shared") or []),
        "alternative_skill_requested": bool(ctx.get("alternative_skill_requested")),
        "alternative_skill_approved": bool(ctx.get("alternative_skill_approved")),
        "retry_type": ctx.get("retry_type", "NORMAL"),
        "push_used": ctx.get("retry_type") == "PUSH",
        "rescue_route_used": bool(ctx.get("rescue_route_used")),
        "target_exhausted": bool(ctx.get("target_exhausted")),
        "context_version": ctx.get("context_version", ""),
    }
    if include_evidence:
        from AdjudicationEvidence import normalize_modifier, validate_evidence
        if not ctx.get("resolution_mode") and not ctx.get("adjudication_id"):
            row["evidence_contract_status"] = "LEGACY_INCOMPLETE"
            return row
        evidence = {
            key: copy.deepcopy(ctx.get(key)) for key in (
                "resolution_mode", "skill_or_stat", "base_target", "final_target",
                "target_value", "roll", "result_level", "raw_result", "modifier",
                "final_result", "automatic_result", "resolution_reason", "roll_result",
                "effect_result", "objective_outcome",
            ) if key in ctx
        }
        evidence["adjudication_id"] = ctx.get("adjudication_id")
        evidence.setdefault("skill_or_stat", ctx.get("skill_or_stat") or ctx.get("skill_id"))
        if str(evidence.get("resolution_mode") or "").upper() == "ROLL":
            evidence["modifier"] = normalize_modifier(evidence.get("modifier"))
        validate_evidence(evidence)
        row.update(evidence)
    return row


def append_investigation_event(state, event_type, ctx, **extra):
    if event_type not in INVESTIGATION_EVENT_TYPES:
        raise ValueError(f"unknown investigation event type: {event_type}")
    unified = state.setdefault("unified_event_log", [])
    row = {
        "turn_id": len(unified) + 1,
        "event_type": event_type,
        "location": ctx.get("location", ""),
        **_event_base(ctx, include_evidence=event_type in RESOLUTION_EVENTS),
        **extra,
    }
    return append_unified_event(state, row)


def _information_from_result(result):
    gained = []
    for grant in result.get("knowledge_grants") or []:
        if isinstance(grant, dict) and grant.get("knowledge_id"):
            gained.append(str(grant["knowledge_id"]))
    if result.get("confirmed_fact") and not gained:
        gained.append(str(result["confirmed_fact"])[:400])
    partial = result.get("failure_information") or result.get("partial_information")
    if partial:
        gained.append(str(partial)[:400])
    return gained


def target_is_exhausted(state, ctx, active_pc_ids):
    if ctx.get("attempt_right_after") == SUCCEEDED:
        return True
    flow = ensure_investigation_state(state)
    target = ctx.get("target_id")
    version = ctx.get("context_version")
    skills = list(ctx.get("allowed_skills") or [ctx.get("skill_id")])
    for pc_id in active_pc_ids or [ctx.get("actor_id")]:
        for skill in skills:
            status = get_attempt_right(state, pc_id, target, skill, version)
            if status in {AVAILABLE, RESET_BY_CONTEXT_CHANGE, PUSH_AVAILABLE}:
                return False
    return True


def finalize_investigation(state, result, action, *, active_pc_ids=None):
    """Record a committed investigation result and emit structured events."""
    ctx = dict(result.get("investigation") or {})
    if not ctx:
        return None
    ctx["action_intent"] = str(
        action.get("action_intent") or action.get("dialogue") or action.get("message") or ""
    )
    adjudication = result.get("adjudication") or {}
    for key in (
        "adjudication_id", "parent_adjudication_id", "interaction_id",
        "resolution_mode", "skill_or_stat", "target_value", "roll",
        "result_level", "raw_result", "modifier", "final_result",
        "automatic_result",
        "state_before", "state_after", "cause_event_ids", "result_event_ids",
    ):
        if key in adjudication:
            ctx[key] = copy.deepcopy(adjudication.get(key))
        elif key in result:
            ctx[key] = copy.deepcopy(result.get(key))
    ctx["transaction_id"] = str(
        result.get("transaction_id") or action.get("transaction_id") or ""
    )
    append_investigation_event(state, "INVESTIGATION_DECLARED", ctx)
    if ctx.get("proposed_skill"):
        append_investigation_event(state, "SKILL_PROPOSED", ctx)
        append_investigation_event(
            state,
            "SKILL_REJECTED" if ctx.get("adjudication") == REJECT_SKILL_PROPOSAL else "SKILL_APPROVED",
            ctx,
        )
        if ctx.get("adjudication") == REJECT_SKILL_PROPOSAL:
            flow = ensure_investigation_state(state)
            reject_key = "|".join((
                str(ctx.get("actor_id") or ""), str(ctx.get("target_id") or ""),
                str(ctx.get("context_version") or ""),
            ))
            rejected = flow["rejected_skills"].setdefault(reject_key, [])
            proposed = str(ctx.get("proposed_skill") or "")
            if proposed and proposed not in rejected:
                rejected.append(proposed)
    if not ctx.get("attempt_allowed"):
        ctx["attempt_right_after"] = ctx.get("attempt_right_before", EXHAUSTED)
        ctx["result"] = "BLOCKED"
        append_investigation_event(state, "ATTEMPT_EXHAUSTED", ctx)
        result["investigation"] = ctx
        return ctx

    status = int(result.get("success_level") or result.get("status") or 0)
    blocked = bool(result.get("blocked"))
    if not ctx.get("roll_required"):
        after = SUCCEEDED if not blocked else EXHAUSTED
        event_type = "ROLL_NOT_REQUIRED"
    elif status >= 2 and not blocked:
        after = SUCCEEDED
        event_type = "INVESTIGATION_SUCCEEDED"
    else:
        pending_push = result.get("pending_push_roll") or (
            result.get("pending_luck_burn")
            if (result.get("pending_luck_burn") or {}).get("allow_push", True)
            else None
        )
        after = PUSH_AVAILABLE if pending_push and ctx.get("retry_type") != "PUSH" else EXHAUSTED
        event_type = "INVESTIGATION_FAILED"

    ctx["attempt_right_after"] = after
    ctx["result"] = status
    ctx["information_gained"] = _information_from_result(result)
    flow = ensure_investigation_state(state)
    key = _attempt_key(ctx.get("actor_id"), ctx.get("target_id"), ctx.get("skill_id"), ctx.get("context_version"))
    flow["attempts"][key] = {
        "actor_id": ctx.get("actor_id"), "target_id": ctx.get("target_id"),
        "skill_id": ctx.get("skill_id"), "location": ctx.get("location"),
        "context_version": ctx.get("context_version"), "attempt_status": after,
        "investigation_id": ctx.get("investigation_id"), "retry_type": ctx.get("retry_type"),
    }
    if ctx.get("retry_type") == "PUSH":
        append_investigation_event(state, "PUSH_DECLARED", ctx)
    if ctx.get("roll_required"):
        append_investigation_event(state, "INVESTIGATION_ROLLED", ctx)
    append_investigation_event(state, event_type, ctx)
    if after == EXHAUSTED:
        append_investigation_event(state, "ATTEMPT_EXHAUSTED", ctx)

    ctx["target_exhausted"] = target_is_exhausted(state, ctx, active_pc_ids or [])
    target_key = f"{ctx.get('location')}|{ctx.get('target_id')}"
    flow["target_status"][target_key] = "EXHAUSTED" if ctx["target_exhausted"] else "AVAILABLE"
    if ctx["target_exhausted"]:
        append_investigation_event(state, "INVESTIGATION_TARGET_EXHAUSTED", ctx)
    result["investigation"] = ctx
    return ctx


def share_information(
    state, char_mgr, *, from_pc, to_pcs, knowledge_ids, physical=False,
    secret=False, summary_by_id=None, location="",
):
    """Transfer character knowledge; PL knowledge is intentionally untouched."""
    if secret:
        return []
    summary_by_id = summary_by_id or {}
    shared = []
    known = set(char_mgr.get_known_knowledge_ids(from_pc) or [])
    for kid in knowledge_ids or []:
        kid = str(kid or "").strip()
        if not kid or kid not in known:
            continue
        for recipient in to_pcs or []:
            if recipient == from_pc:
                continue
            if char_mgr.grant_knowledge(
                recipient, kid, summary=summary_by_id.get(kid, ""),
                mark_investigated=bool(physical),
            ):
                shared.append({"knowledge_id": kid, "from": from_pc, "to": recipient, "physical": bool(physical)})
    if shared:
        ctx = {
            "investigation_id": uuid.uuid4().hex, "actor_id": from_pc,
            "target_id": "", "location": location, "information_shared": shared,
            "roll_required": False,
        }
        append_investigation_event(state, "INFORMATION_SHARED", ctx)
    return shared


def create_rescue_route(state, *, target, location, route, kp_stance="STANDARD"):
    """Record a new opportunity, never an unconditional clue grant."""
    flow = ensure_investigation_state(state)
    item = {
        "route_id": uuid.uuid4().hex, "target": str(target or ""),
        "location": str(location or ""), "route": copy.deepcopy(route),
        "kp_stance": str(kp_stance or "STANDARD").upper(),
    }
    flow["rescue_routes"].append(item)
    ctx = {
        "investigation_id": item["route_id"], "actor_id": "KP",
        "target_id": target, "location": location, "rescue_route_used": True,
        "roll_required": False,
    }
    append_investigation_event(state, "KP_RESCUE_ROUTE_CREATED", ctx, rescue_route=item)
    return item


def filter_investigation_candidates(state, candidates, *, actor_id, scenario_mgr, location):
    """Remove illegal repeats without removing options that remain for other PCs."""
    output = []
    for candidate in candidates or []:
        item = dict(candidate)
        target = str(item.get("target") or "")
        skill = str(item.get("skill") or "")
        version = context_version(state, scenario_mgr, location, target)
        status = get_attempt_right(state, actor_id, target, skill, version)
        if status in {SUCCEEDED, FAILED, EXHAUSTED, PUSH_AVAILABLE}:
            continue
        flow = ensure_investigation_state(state)
        rejected = flow["rejected_skills"].get(f"{actor_id}|{target}|{version}", [])
        if skill and skill in rejected:
            continue
        output.append(item)
    return output


def build_attempt_rights_prompt(state, *, actor_id, scenario_mgr, location):
    """Compact prompt block that discourages retries and blind skill spam."""
    flow = ensure_investigation_state(state)
    rows = []
    for record in flow["attempts"].values():
        if record.get("actor_id") != actor_id or record.get("location") != location:
            continue
        if record.get("attempt_status") not in {FAILED, EXHAUSTED, PUSH_AVAILABLE, SUCCEEDED}:
            continue
        rows.append(
            f"- {record.get('target_id')} / 〈{record.get('skill_id')}〉: {record.get('attempt_status')}"
        )
    if not rows:
        return ""
    return (
        "【調査試行権（システム確定）】\n" + "\n".join(rows[-10:]) +
        "\n同じPC・対象・技能・状況で通常再判定しない。"
        "PUSH_AVAILABLEはプッシュだけ可。別PCの試行権は別管理。\n"
    )
