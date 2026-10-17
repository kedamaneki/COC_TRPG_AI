"""Audit producer-owned lifecycle relations without modifying a Raw Run."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path


def _load(root: Path, final: str, partial: str):
    path = root / final
    if not path.exists():
        path = root / partial
    return json.loads(path.read_text(encoding="utf-8"))


def audit(root):
    root = Path(root)
    unified = _load(root, "unified-event-log.json", "unified-event-log.partial.json")
    session = _load(root, "session-log.json", "session-log.partial.json")
    authority = [row for row in unified if row.get("event_type") == "LOCATION_CHANGE"]
    display = [row for row in session if "【移動】" in str(row.get("text") or "")]

    authority_ids = [str(row.get("lifecycle_relation_id") or "") for row in authority]
    display_ids = [str((row.get("meta") or {}).get("lifecycle_relation_id") or "") for row in display]
    missing = sum(not token for token in authority_ids) + sum(not token for token in display_ids)
    a_counts, d_counts = Counter(filter(None, authority_ids)), Counter(filter(None, display_ids))
    ambiguous_ids = sorted({key for key, count in a_counts.items() if count != 1}
                           | {key for key, count in d_counts.items() if count != 1})
    unmatched = sorted((set(a_counts) ^ set(d_counts)))
    contradictory = []
    actor_contradictions = []
    contradiction_details = []
    by_display = {
        str((row.get("meta") or {}).get("lifecycle_relation_id")): row
        for row in display if (row.get("meta") or {}).get("lifecycle_relation_id")
    }
    for row in authority:
        relation = str(row.get("lifecycle_relation_id") or "")
        counterpart = by_display.get(relation)
        if not relation or counterpart is None:
            continue
        meta = counterpart.get("meta") or {}
        before = (row.get("state_before") or {}).get("location")
        after = (row.get("state_after") or {}).get("location")
        actor_mismatch = bool(meta.get("actor_id") and meta.get("actor_id") != row.get("actor"))
        structural_mismatch = (
            row.get("selected_action") != "move"
            or meta.get("action_id") != "move"
            or counterpart.get("location") != before
            or meta.get("target") != after
        )
        if actor_mismatch:
            actor_contradictions.append(relation)
        if structural_mismatch or actor_mismatch:
            contradictory.append(relation)
            contradiction_details.append({
                "lifecycle_relation_id": relation,
                "authority_actor": row.get("actor"),
                "display_actor": meta.get("actor_id"),
                "authority_from": before,
                "display_from": counterpart.get("location"),
                "authority_to": after,
                "display_to": meta.get("target"),
                "actor_contradiction": actor_mismatch,
                "structural_contradiction": structural_mismatch,
            })
    return {
        "lifecycle_relation_missing": missing,
        "lifecycle_relation_ambiguous": len(ambiguous_ids),
        "lifecycle_relation_unmatched": len(unmatched),
        "lifecycle_relation_contradictory": len(contradictory),
        "lifecycle_actor_contradiction": len(set(actor_contradictions)),
        "authority_location_changes": len(authority),
        "display_location_changes": len(display),
        "relation_pairs": len(set(a_counts) & set(d_counts)),
        "ambiguous_relation_ids": ambiguous_ids,
        "unmatched_relation_ids": unmatched,
        "contradictory_relation_ids": sorted(set(contradictory)),
        "contradiction_details": contradiction_details,
        "status": "PASS" if not (missing or ambiguous_ids or unmatched or contradictory) else "FAIL",
    }


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("raw_run")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    report = audit(args.raw_run)
    if args.output:
        path = Path(args.output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
