"""Source-bound result cards for combat resolved without normal attack exchanges."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence


class CombatResultCardError(ValueError):
    """Raised when a result card would invent or obscure combat evidence."""


@dataclass(frozen=True)
class CombatResultCardAudit:
    status: str
    source_traceability: float
    invented_attack_roll: int
    invented_damage_roll: int
    invented_hp_change: int
    invented_enemy_action: int
    causal_order_mismatch: int


REQUIRED_SEQUENCE = (
    "COMBAT_ACTION_SELECTED",
    "COMBAT_ACTION_RESOLVED",
    "SPECIAL_OBJECTIVE_COMPLETED",
    "COMBAT_ENDING",
    "COMBAT_ENDED",
)

FORBIDDEN_FACT_KEYS = {
    "attack_roll",
    "attack_target",
    "damage_roll",
    "damage_formula",
    "actual_damage",
    "hp_change",
    "enemy_action",
    "enemy_attack",
    "enemy_retaliation",
}


def _event_view(event: Mapping) -> dict:
    return {
        "raw_event_offset": int(event["raw_event_offset"]),
        "event_id": str(event["event_id"]),
        "event_type": str(event["event_type"]),
        "adjudication_id": event.get("adjudication_id") or None,
    }


def build_no_roll_special_objective_card(events: Iterable[Mapping]) -> dict:
    """Build the three-stage Video 002 card from authoritative source events.

    The function requires the complete selected -> resolved -> objective -> ending ->
    ended chain.  It does not infer attack, damage, HP loss, or enemy actions.
    """

    rows = sorted((dict(event) for event in events), key=lambda row: int(row["raw_event_offset"]))
    by_type = {row.get("event_type"): row for row in rows}
    missing = [event_type for event_type in REQUIRED_SEQUENCE if event_type not in by_type]
    if missing:
        raise CombatResultCardError("SPECIAL_OBJECTIVE_CHAIN_INCOMPLETE:" + ",".join(missing))

    sequence = [int(by_type[event_type]["raw_event_offset"]) for event_type in REQUIRED_SEQUENCE]
    if sequence != sorted(sequence):
        raise CombatResultCardError("SPECIAL_OBJECTIVE_CAUSAL_ORDER_MISMATCH")

    selected = by_type["COMBAT_ACTION_SELECTED"]
    resolved = by_type["COMBAT_ACTION_RESOLVED"]
    objective = by_type["SPECIAL_OBJECTIVE_COMPLETED"]
    ending = by_type["COMBAT_ENDING"]
    ended = by_type["COMBAT_ENDED"]
    if selected.get("selected_action") != "break" or selected.get("target") != "corbitt_body":
        raise CombatResultCardError("UNSUPPORTED_SPECIAL_OBJECTIVE_ACTION")
    if resolved.get("resolution_mode") != "NO_ROLL":
        raise CombatResultCardError("SPECIAL_OBJECTIVE_MUST_BE_NO_ROLL")
    if resolved.get("objective_outcome") != "SPECIAL_OBJECTIVE_COMPLETED":
        raise CombatResultCardError("SPECIAL_OBJECTIVE_OUTCOME_MISSING")
    world_fact = objective.get("world_fact") or {}
    if world_fact.get("fact") != "CORBITT_BODY_DESTROYED":
        raise CombatResultCardError("CORBITT_BODY_DESTROYED_EVIDENCE_MISSING")
    if ended.get("combat_state") != "ENDED":
        raise CombatResultCardError("COMBAT_ENDED_STATE_MISSING")

    source_events = [_event_view(by_type[event_type]) for event_type in REQUIRED_SEQUENCE]
    return {
        "schema_version": "1.0",
        "card_type": "COMBAT_RESULT_CARD",
        "presentation_role": "SYSTEM",
        "voice": "NONE",
        "portrait": "NONE",
        "source_event_ids": [row["event_id"] for row in source_events],
        "source_raw_event_offsets": [row["raw_event_offset"] for row in source_events],
        "source_events": source_events,
        "resolution_mode": "NO_ROLL",
        "stages": [
            {
                "stage": "ACTION",
                "label": "遺体を破壊",
                "source_event_ids": [str(selected["event_id"]), str(resolved["event_id"])],
                "source_raw_event_offsets": [int(selected["raw_event_offset"]), int(resolved["raw_event_offset"])],
            },
            {
                "stage": "OBJECTIVE",
                "label": "コービットを打倒",
                "source_event_ids": [str(objective["event_id"])],
                "source_raw_event_offsets": [int(objective["raw_event_offset"])],
            },
            {
                "stage": "COMBAT_END",
                "label": "戦闘終了",
                "source_event_ids": [str(ending["event_id"]), str(ended["event_id"])],
                "source_raw_event_offsets": [int(ending["raw_event_offset"]), int(ended["raw_event_offset"])],
            },
        ],
        "scene_actor_transition": {
            "actor_id": "walter_corbitt",
            "visible_while_source_present": True,
            "fade_out_after_raw_event_offset": int(objective["raw_event_offset"]),
            "fade_style": "NATURAL_SHORT_FADE",
        },
        "explicit_absences": {
            "attack_roll": True,
            "damage_roll": True,
            "hp_change": True,
            "enemy_action": True,
        },
    }


def audit_combat_result_card(card: Mapping, source_events: Sequence[Mapping]) -> CombatResultCardAudit:
    source_by_id = {str(row.get("event_id")): row for row in source_events if row.get("event_id")}
    cited = [str(value) for value in card.get("source_event_ids", [])]
    traceability = 1.0 if cited and all(event_id in source_by_id for event_id in cited) else 0.0
    serialized = str(card).lower()
    invented = {
        "attack_roll": int(any(key in card for key in ("attack_roll", "attack_target")) or "attack roll" in serialized),
        "damage_roll": int(any(key in card for key in ("damage_roll", "damage_formula", "actual_damage"))),
        "hp_change": int("hp_change" in card or "hp_before" in serialized or "hp_after" in serialized),
        "enemy_action": int(any(key in card for key in ("enemy_action", "enemy_attack", "enemy_retaliation"))),
    }
    offsets = [int(value) for value in card.get("source_raw_event_offsets", [])]
    order_mismatch = int(offsets != sorted(offsets))
    status = "PASS" if traceability == 1.0 and not any(invented.values()) and not order_mismatch else "FAIL"
    return CombatResultCardAudit(
        status=status,
        source_traceability=traceability,
        invented_attack_roll=invented["attack_roll"],
        invented_damage_roll=invented["damage_roll"],
        invented_hp_change=invented["hp_change"],
        invented_enemy_action=invented["enemy_action"],
        causal_order_mismatch=order_mismatch,
    )


def assert_combat_result_card(card: Mapping, source_events: Sequence[Mapping]) -> CombatResultCardAudit:
    audit = audit_combat_result_card(card, source_events)
    if audit.status != "PASS":
        raise CombatResultCardError(f"COMBAT_RESULT_CARD_AUDIT_FAILED:{audit}")
    return audit
