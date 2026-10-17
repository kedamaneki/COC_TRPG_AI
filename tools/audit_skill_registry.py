"""Cross-audit scenario and decision skill vocabulary against Core ROLL producers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from unittest import mock


REPO = Path(__file__).resolve().parents[1]
CORE = REPO / "core" / "src"
if str(CORE) not in sys.path:
    sys.path.insert(0, str(CORE))

from CharacterManager import CharacterManager  # noqa: E402
from AdjudicationEvidence import roll_evidence, validate_evidence  # noqa: E402
from DiceEngine import DiceEngine, SuccessLevel  # noqa: E402
from SkillRegistry import SKILL_ALIASES, resolve_roll_target  # noqa: E402


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def scenario_skill_refs(scenario):
    refs = []
    for location_id, location in (scenario.get("locations") or {}).items():
        for object_id, obj in (location.get("objects") or {}).items():
            raw = obj.get("required_skill")
            if raw is None:
                raw = obj.get("required_skills")
            if raw is None:
                continue
            names = [raw] if isinstance(raw, str) else list(raw)
            for name in names:
                if str(name or "").strip():
                    refs.append({
                        "source": "SCENARIO_REQUIRED_SKILL",
                        "location": location_id,
                        "target": object_id,
                        "name": str(name).strip(),
                        "authoritative": True,
                    })
    return refs


def decision_skill_refs(path):
    refs = []
    path = Path(path)
    if not path.exists():
        return refs
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        action = row.get("chosen_action") or {}
        name = str(action.get("skill") or "").strip()
        if name:
            refs.append({
                "source": "DECISION_PROPOSAL",
                "line": line_no,
                "action": action.get("action"),
                "target": action.get("target"),
                "name": name,
                # Proposals are adjudicated against the scenario list. They
                # are inventory data, not authoritative Dice input.
                "authoritative": False,
            })
    return refs


class _AuditCharacters:
    BASE_SKILLS = CharacterManager.BASE_SKILLS

    def __init__(self, characters):
        self.characters = characters

    def get_attribute(self, char_id, name):
        value = (self.characters.get(char_id) or {}).get("attributes", {}).get(name)
        if isinstance(value, dict):
            value = value.get("current", value.get("value"))
        return value

    def get_skill(self, char_id, name):
        char = self.characters.get(char_id) or {}
        if name in (char.get("skills") or {}):
            return char["skills"][name]
        if name == "回避":
            dex = self.get_attribute(char_id, "DEX") or 0
            return int(dex) // 2
        if name == "母国語":
            return self.get_attribute(char_id, "EDU") or 0
        return self.BASE_SKILLS.get(name, 0)


def audit(*, scenario_path, pcs_path, decision_cases_path=None):
    scenario = _load(scenario_path)
    pcs = _load(pcs_path)
    chars = _AuditCharacters(pcs)
    refs = scenario_skill_refs(scenario)
    decision_refs = decision_skill_refs(decision_cases_path) if decision_cases_path else []

    unresolved = []
    dice_unsupported = []
    contract_failures = []
    resolved_rows = []
    for ref in refs:
        per_actor = []
        for actor_id in sorted(pcs):
            target = resolve_roll_target(chars, actor_id, ref["name"])
            per_actor.append({"actor_id": actor_id, **target})
            if not target["defined"]:
                unresolved.append({**ref, "actor_id": actor_id})
                continue
            if target["value"] is None or target["value"] < 0:
                dice_unsupported.append({**ref, "actor_id": actor_id, **target})
                continue
            with mock.patch("DiceEngine.random.randint", side_effect=[5, 5]):
                result = DiceEngine().execute_skill_roll(
                    actor_id, target["canonical"], target["value"],
                    allow_zero=target["legal_zero"],
                )
            missing = [
                key for key in ("target_value", "roll", "success_level")
                if result.get(key) is None
            ]
            if result.get("status") == "error" or missing:
                contract_failures.append({
                    **ref, "actor_id": actor_id, "missing": missing,
                    "dice_status": result.get("status"),
                })
                continue
            result_name = SuccessLevel(int(result["success_level"])).name
            try:
                evidence = roll_evidence(
                    adjudication_id=f"audit_scenario_{actor_id}_{len(resolved_rows):04d}",
                    skill_or_stat=target["canonical"],
                    target_value=result["target_value"],
                    roll=result["roll"],
                    raw_result=result_name,
                    final_result=result_name,
                )
                validate_evidence(evidence)
            except Exception as exc:  # the audit reports the contract boundary
                contract_failures.append({
                    "source": ref["source"], "name": ref["name"],
                    "actor_id": actor_id, "evidence_error": str(exc),
                })
        resolved_rows.append({**ref, "actors": per_actor})

    # Exercise the complete registered ROLL vocabulary, not only the subset
    # currently referenced by this scenario.  This catches the next scenario
    # selecting a legal base skill before a long run reaches that branch.
    registry_rows = []
    registry_identifiers = sorted(set(CharacterManager.BASE_SKILLS) | {
        "STR", "CON", "DEX", "APP", "POW", "SIZ", "INT", "EDU",
    })
    for name in registry_identifiers:
        per_actor = []
        for actor_id in sorted(pcs):
            target = resolve_roll_target(chars, actor_id, name)
            row = {"actor_id": actor_id, **target}
            per_actor.append(row)
            if not target["defined"] or target["value"] is None or target["value"] < 0:
                dice_unsupported.append({
                    "source": "ROLLABLE_REGISTRY", "name": name,
                    "actor_id": actor_id, **target,
                })
                continue
            with mock.patch("DiceEngine.random.randint", side_effect=[5, 5]):
                result = DiceEngine().execute_skill_roll(
                    actor_id, target["canonical"], target["value"],
                    allow_zero=target["legal_zero"],
                )
            missing = [
                key for key in ("target_value", "roll", "success_level")
                if result.get(key) is None
            ]
            if result.get("status") == "error" or missing:
                contract_failures.append({
                    "source": "ROLLABLE_REGISTRY", "name": name,
                    "actor_id": actor_id, "missing": missing,
                    "dice_status": result.get("status"),
                })
                continue
            result_name = SuccessLevel(int(result["success_level"])).name
            try:
                evidence = roll_evidence(
                    adjudication_id=f"audit_registry_{actor_id}_{len(registry_rows):04d}",
                    skill_or_stat=target["canonical"],
                    target_value=result["target_value"],
                    roll=result["roll"],
                    raw_result=result_name,
                    final_result=result_name,
                )
                validate_evidence(evidence)
            except Exception as exc:
                contract_failures.append({
                    "source": "ROLLABLE_REGISTRY", "name": name,
                    "actor_id": actor_id, "evidence_error": str(exc),
                })
        registry_rows.append({"name": name, "actors": per_actor})

    invalid_defaults = []
    for name, value in CharacterManager.BASE_SKILLS.items():
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            invalid_defaults.append({"name": name, "value": value})

    alias_targets = {}
    for alias, canonical in SKILL_ALIASES.items():
        alias_targets.setdefault(alias, set()).add(canonical)
    ambiguous = [
        {"alias": alias, "targets": sorted(targets)}
        for alias, targets in alias_targets.items() if len(targets) != 1
    ]

    metrics = {
        "scenario_skill_unresolved": len(unresolved),
        "skill_alias_ambiguous": len(ambiguous),
        "dice_unsupported_skill": len(dice_unsupported),
        "invalid_skill_default": len(invalid_defaults),
        "rollable_skill_contract_failure": len(contract_failures),
    }
    return {
        "status": "PASS" if not any(metrics.values()) else "FAIL",
        "metrics": metrics,
        "scenario_references": resolved_rows,
        "rollable_registry": registry_rows,
        "decision_proposals": decision_refs,
        "decision_proposal_policy": "ENGINE_ADJUDICATES_AGAINST_SCENARIO_ALLOWED_SKILLS",
        "legal_zero_defaults": sorted(
            name for name, value in CharacterManager.BASE_SKILLS.items() if value == 0
        ),
        "findings": {
            "unresolved": unresolved,
            "ambiguous_aliases": ambiguous,
            "dice_unsupported": dice_unsupported,
            "invalid_defaults": invalid_defaults,
            "contract_failures": contract_failures,
        },
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", required=True)
    parser.add_argument("--pcs", required=True)
    parser.add_argument("--decision-cases")
    parser.add_argument("--output")
    args = parser.parse_args()
    report = audit(
        scenario_path=args.scenario,
        pcs_path=args.pcs,
        decision_cases_path=args.decision_cases,
    )
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
