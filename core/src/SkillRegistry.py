"""Canonical identifiers used by authoritative ROLL producers.

The scenario vocabulary contains both CoC skills and characteristics such as
STR. Keeping that distinction here prevents a characteristic from silently
falling through CharacterManager.get_skill() as an undefined zero value.
"""

from __future__ import annotations

from collections.abc import Mapping


ATTRIBUTE_IDS = frozenset({"STR", "CON", "DEX", "APP", "POW", "SIZ", "INT", "EDU"})

# Only aliases already used interchangeably by the combat runtime belong here.
# Free-form LLM proposals remain subject to the scenario's allowed-skill list.
SKILL_ALIASES = {
    "近接戦闘（格闘）": "近接戦闘",
    "格闘": "近接戦闘",
    "Fighting (Brawl)": "近接戦闘",
}


def canonical_roll_identifier(name: str) -> dict:
    requested = str(name or "").strip()
    upper = requested.upper()
    if upper in ATTRIBUTE_IDS:
        return {
            "requested": requested,
            "canonical": upper,
            "kind": "ATTRIBUTE",
            "alias_used": requested != upper,
        }
    canonical = SKILL_ALIASES.get(requested, requested)
    return {
        "requested": requested,
        "canonical": canonical,
        "kind": "SKILL",
        "alias_used": canonical != requested,
    }


def resolve_roll_target(char_mgr, char_id: str, name: str) -> dict:
    identity = canonical_roll_identifier(name)
    canonical = identity["canonical"]
    if not canonical:
        return {**identity, "defined": False, "legal_zero": False, "value": None}

    if identity["kind"] == "ATTRIBUTE":
        value = char_mgr.get_attribute(char_id, canonical)
        defined = value is not None
    else:
        char = (getattr(char_mgr, "characters", {}) or {}).get(char_id) or {}
        explicit = char.get("skills") or {}
        base = getattr(char_mgr, "BASE_SKILLS", {}) or {}
        if not isinstance(base, Mapping):
            base = {}
        value = char_mgr.get_skill(char_id, canonical)
        # Test doubles and adapters may expose only get_skill().  A positive
        # value is still authoritative; zero needs an explicit registry entry
        # so an undefined name is never confused with a legal zero default.
        defined = canonical in explicit or canonical in base or bool(value and int(value) > 0)
        if not defined:
            value = None

    try:
        value = int(value) if value is not None else None
    except (TypeError, ValueError):
        value = None
        defined = False
    return {
        **identity,
        "defined": bool(defined),
        "legal_zero": bool(defined and value == 0),
        "value": value,
    }
