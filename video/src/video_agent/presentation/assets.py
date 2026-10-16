from __future__ import annotations

from pathlib import Path


ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".wav", ".mp3", ".ogg"}
EXPRESSIONS = {"NORMAL", "HAPPY", "ANGRY", "SAD", "SURPRISED", "SCARED", "THINKING"}
EXPRESSION_FALLBACKS = {
    "SCARED": ["SCARED", "SURPRISED", "NORMAL"],
    "SURPRISED": ["SURPRISED", "NORMAL"],
    "ANGRY": ["ANGRY", "NORMAL"],
    "SAD": ["SAD", "NORMAL"],
    "HAPPY": ["HAPPY", "NORMAL"],
    "THINKING": ["THINKING", "NORMAL"],
    "NORMAL": ["NORMAL"],
}


def scan_asset_folder(root: Path) -> list[Path]:
    root = Path(root)
    if not root.exists():
        return []
    return sorted(path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in ALLOWED_EXTENSIONS)


def resolve_expression(requested: str, mapping: dict[str, str]) -> tuple[str, str | None]:
    requested = requested if requested in EXPRESSIONS else "NORMAL"
    for expression in EXPRESSION_FALLBACKS[requested]:
        if mapping.get(expression):
            return expression, mapping[expression]
    return "NORMAL", None


def resolve_background(location_id: str | None, mapping: dict[str, str], category_fallback: str,
                       neutral_fallback: str) -> tuple[str, str]:
    if location_id and mapping.get(location_id):
        return mapping[location_id], "LOCATION_SPECIFIC"
    if category_fallback and mapping.get(category_fallback):
        return mapping[category_fallback], "CATEGORY_GENERIC"
    return neutral_fallback, "NEUTRAL_FALLBACK"


def license_gate(assets: list[dict], used_ids: set[str]) -> dict:
    used = [item for item in assets if item["asset_id"] in used_ids]
    blocked = [item["asset_id"] for item in used if item["status"] == "BLOCKED"]
    unknown = [item["asset_id"] for item in used if item["status"] == "UNKNOWN"]
    noncommercial = [item["asset_id"] for item in used if item.get("commercial_use") is False]
    publishable = not blocked and not unknown and not noncommercial and bool(used)
    return {
        "blocked_assets": blocked, "unknown_assets": unknown, "noncommercial_assets": noncommercial,
        "local_preview_allowed": not blocked, "review_ready": not blocked,
        "publishable": publishable,
        "warnings": (["NON_PUBLISHABLE_ASSET_USED"] if unknown or noncommercial else []),
    }


def generate_credits(assets: list[dict], used_ids: set[str]) -> str:
    rows, seen = [], set()
    for item in sorted((a for a in assets if a["asset_id"] in used_ids), key=lambda a: a["asset_id"]):
        credit = item.get("credit_text") or f"{item['asset_id']}: {item.get('creator') or '作者不明'} / {item.get('source') or '出典不明'} / license={item.get('license') or 'UNKNOWN'}"
        if credit not in seen:
            rows.append(credit)
            seen.add(credit)
    return "\n".join(rows) + ("\n" if rows else "")
