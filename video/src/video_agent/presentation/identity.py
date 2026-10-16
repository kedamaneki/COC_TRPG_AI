from __future__ import annotations


VALID_SPEAKER_MODES = {"KP", "PL", "PC", "NPC", "SYSTEM", "UNKNOWN"}


def resolve_display_identity(source_actor: str, speaker_mode: str | None,
                             controlled_character: str | None, schema: dict,
                             fallback: dict) -> dict:
    """Resolve presentation identity without changing the source session semantics."""
    mode = (speaker_mode or "UNKNOWN").upper()
    if mode not in VALID_SPEAKER_MODES:
        mode = "UNKNOWN"
    players = {item["player_id"]: item for item in schema.get("players", [])}
    pcs = {item["pc_id"]: item for item in schema.get("pcs", [])}
    player_id = source_actor if source_actor in players else None
    pc_id = controlled_character if controlled_character in pcs else source_actor if source_actor in pcs else None

    if mode == "PL" and player_id:
        profile = players[player_id]
    elif mode == "PC" and pc_id:
        profile = pcs[pc_id]
        player_id = profile.get("controlled_by_player_id")
    else:
        profile = fallback
        if pc_id:
            player_id = pcs[pc_id].get("controlled_by_player_id")

    return {
        "speaker_mode": mode,
        "player_id": player_id,
        "pc_id": pc_id,
        "resolved_display_name": profile.get("display_name") or fallback["display_name"],
        "resolved_voice_profile_id": profile.get("voice_profile_id") or fallback.get("voice_profile_id"),
        "resolved_portrait_profile_id": profile.get("portrait_profile_id") or fallback.get("portrait_profile_id"),
        "resolved_subtitle_profile_id": profile.get("subtitle_profile_id") or fallback.get("subtitle_profile_id"),
        "resolution": "EXPLICIT_MODE" if mode in {"PL", "PC"} and (player_id or pc_id) else "CURRENT_MAPPING_FALLBACK",
    }
