"""save_autosave.json のロード修復を、現行仕様で検証するワンショットスクリプト。

現行仕様の要点:
  - flags / turn_count の SSOT は game_state（scenario_manager は固有状態のみ）
  - 旧セーブの scenario_manager.flags / turn_counter は sync_progress_managers で移行
  - 未処理 PL 行動（system_processed: false）の空 target は recover で補完
  - 未処理がある場合、次のタイムライン手番は system_process
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from CharacterManager import CharacterManager
from GameStateManager import GameStateManager
from ScenarioManager import ScenarioManager
import main as game_main

SAVE_PATH = Path(__file__).resolve().parent / "save_autosave.json"
SCENARIO_PATH = Path(__file__).resolve().parent / "scenario_corbitt.json"
REQUIRED_TOP_KEYS = ("game_state", "character_manager", "scenario_manager", "app_state")


def _fail(message: str) -> None:
    raise AssertionError(message)


def _print_section(title: str) -> None:
    print(f"\n=== {title} ===")


def verify_save_structure(save_data: dict) -> None:
    """現行セーブ形式の骨格を検証する。"""
    _print_section("Structure")
    for key in REQUIRED_TOP_KEYS:
        if key not in save_data:
            _fail(f"missing top-level key: {key}")

    scenario_file = (
        save_data.get("scenario_file")
        or save_data.get("app_state", {}).get("scenario_file")
    )
    print("scenario_file:", scenario_file)
    if scenario_file != "scenario_corbitt.json":
        _fail(f"unexpected scenario_file: {scenario_file}")
    if not SCENARIO_PATH.is_file():
        _fail(f"scenario file missing: {SCENARIO_PATH}")

    sm = save_data.get("scenario_manager") or {}
    # 現行 export は flags / turn_counter を scenario_manager に載せない
    for legacy_key in ("flags", "turn_counter"):
        if legacy_key in sm:
            print(f"note: legacy key present in scenario_manager.{legacy_key} (migration path)")
        else:
            print(f"scenario_manager.{legacy_key}: absent (current format)")

    gs = save_data.get("game_state") or {}
    if "flags" not in gs:
        _fail("game_state.flags missing (SSOT)")
    if "turn_count" not in gs:
        _fail("game_state.turn_count missing (SSOT)")
    print("game_state.turn_count:", gs.get("turn_count"))
    print("game_state.flags count:", len(gs.get("flags") or {}))


def verify_legacy_migration() -> None:
    """旧形式セーブからの flags / turn 移行が現行でも動くことを確認する。"""
    _print_section("Legacy migration fixture")
    char_mgr = CharacterManager("pcs.json", "npcs.json")
    state_mgr = GameStateManager(char_mgr)
    scenario_mgr = ScenarioManager(json.loads(SCENARIO_PATH.read_text(encoding="utf-8")))
    legacy_save = {
        "game_state": {"turn_count": 0, "flags": {}},
        "scenario_manager": {
            "turn_counter": 3,
            "flags": {"knott_letter_read": True, "talked_with_knott": True},
        },
    }
    game_main.sync_progress_managers(state_mgr, scenario_mgr, save_data=legacy_save)
    print("migrated turn_count:", state_mgr.turn_count)
    print("migrated talked_with_knott:", scenario_mgr.flags.get("talked_with_knott"))
    if state_mgr.turn_count != 3:
        _fail("legacy turn_counter migration failed")
    if scenario_mgr.turn_counter != 3:
        _fail("scenario turn_counter delegate failed after legacy migration")
    if not scenario_mgr.flags.get("talked_with_knott"):
        _fail("legacy flags migration failed")
    if not state_mgr.flags.get("knott_letter_read"):
        _fail("legacy knott_letter_read migration failed")


def verify_live_autosave_recovery(save_data: dict) -> None:
    """実際の save_autosave.json を restore_from_save_data 経路で検証する。"""
    _print_section("Before restore")
    app_raw = save_data.get("app_state") or {}
    gs_raw = save_data.get("game_state") or {}
    sm_raw = save_data.get("scenario_manager") or {}
    print("location (app/scenario):", app_raw.get("current_loc"), "/", sm_raw.get("location"))
    print("turn_count (raw):", gs_raw.get("turn_count"))
    print("talked_with_knott (raw):", (gs_raw.get("flags") or {}).get("talked_with_knott"))
    print("last_pl_action.target (raw):", (app_raw.get("last_pl_action") or {}).get("target"))
    print("is_running (raw):", app_raw.get("is_running"))

    pending_before = game_main.find_any_pending_pl_action(dict(app_raw), char_mgr=None)
    if pending_before:
        print("pending meta (raw):", pending_before.get("meta"))
    else:
        print("pending meta (raw): None")

    char_mgr = CharacterManager("pcs.json", "npcs.json")
    state_mgr = GameStateManager(char_mgr)
    scenario_mgr = ScenarioManager(json.loads(SCENARIO_PATH.read_text(encoding="utf-8")))

    app_state = game_main.restore_from_save_data(
        save_data, state_mgr, char_mgr, scenario_mgr,
    )

    _print_section("After restore/recover")
    print("state_mgr.turn_count:", state_mgr.turn_count)
    print("scenario_mgr.turn_counter:", scenario_mgr.turn_counter)
    print("scenario_mgr.location:", scenario_mgr.location)
    print("app current_loc:", app_state.get("current_loc"))
    print("flags.talked_with_knott:", scenario_mgr.flags.get("talked_with_knott"))
    print("last_pl_action:", app_state.get("last_pl_action"))
    print("is_running:", app_state.get("is_running"))
    print("autonomous_paused:", app_state.get("autonomous_paused"))

    # SSOT: game_state の値を scenario 側から参照できる
    expected_turn = int(gs_raw.get("turn_count") or 0)
    if state_mgr.turn_count != expected_turn:
        _fail(
            f"turn_count mismatch after sync: "
            f"state={state_mgr.turn_count} expected={expected_turn}"
        )
    if scenario_mgr.turn_counter != state_mgr.turn_count:
        _fail("scenario_mgr.turn_counter is not delegated to game_state")

    if not scenario_mgr.flags.get("talked_with_knott"):
        _fail("talked_with_knott should remain True after bind")

    if app_state.get("current_loc") != scenario_mgr.location and scenario_mgr.location:
        # restore は location を scenario に戻すが、app_state.current_loc はセーブ値のまま。
        # UI 側 (load_from_slot) で scenario.location を優先するため、ここでは警告のみ。
        print(
            "note: app_state.current_loc != scenario_mgr.location "
            f"({app_state.get('current_loc')} vs {scenario_mgr.location}); "
            "UI load_from_slot syncs from scenario_mgr.location"
        )

    pending = game_main.find_any_pending_pl_action(app_state, char_mgr)
    unnarrated = game_main.find_last_unnarrated_system_entry(
        app_state.get("all_events_log") or [],
    )
    next_step = game_main.determine_timeline_next_step(
        app_state,
        app_state.get("char_name") or "",
        scenario_mgr,
        state_mgr=state_mgr,
        char_mgr=char_mgr,
    )
    print("pending after recover:", bool(pending), (pending or {}).get("meta"))
    print("unnarrated system:", bool(unnarrated))
    print("next timeline step:", next_step)

    if pending:
        pending_meta = pending.get("meta") or {}
        if pending_meta.get("system_processed") is not False:
            _fail("pending action must remain system_processed=false")
        if not pending_meta.get("target"):
            _fail("recover_pending_timeline_on_load failed to fill pending target")
        last_target = (app_state.get("last_pl_action") or {}).get("target")
        if last_target != pending_meta.get("target"):
            _fail(
                f"last_pl_action.target ({last_target}) != "
                f"pending meta.target ({pending_meta.get('target')})"
            )
        # 導入シーンの talk 空 target はノットへ補完されるのが現行仕様
        if (
            app_state.get("current_loc") == "introduction"
            or scenario_mgr.location == "introduction"
        ):
            if pending_meta.get("target") != "steven_knott":
                _fail(
                    "introduction pending talk target should resolve to steven_knott, "
                    f"got {pending_meta.get('target')!r}"
                )
        if next_step != "system_process":
            _fail(f"expected next step system_process, got {next_step!r}")
        if app_state.get("is_running") and app_state.get("autonomous_paused"):
            _fail("is_running with pending action should clear autonomous_paused")
    elif unnarrated:
        if next_step != "kp_narrate":
            _fail(f"expected next step kp_narrate for unnarrated system, got {next_step!r}")
    else:
        print("note: no pending PL action / unnarrated system; mid-cycle interrupt not present")

    _warn_progress_flag_drift(save_data, scenario_mgr)


def _log_mentions_dolly(all_events_log: list) -> bool:
    """今セッションのログにドーリー対話があるか（古い session_social の誤検知を避ける）。"""
    for entry in all_events_log or []:
        meta = entry.get("meta") or {}
        if meta.get("target") == "dolly_shopkeeper":
            return True
        text = str(entry.get("text") or "")
        if "ドーリー" in text or "dolly_shopkeeper" in text:
            return True
    return False


def _warn_progress_flag_drift(save_data: dict, scenario_mgr: ScenarioManager) -> None:
    """物語上開示済みでも進行フラグが未設定なら警告する（ロード修復対象外の既知ギャップ）。"""
    _print_section("Progress flag consistency (warn)")
    chars = (save_data.get("character_manager") or {}).get("characters") or {}
    dolly = chars.get("dolly_shopkeeper") or {}
    revealed = set((dolly.get("session_social") or {}).get("revealed_secrets") or [])
    app_state = save_data.get("app_state") or {}
    logs = app_state.get("all_events_log") or []
    dolly_in_log = _log_mentions_dolly(logs)

    if not revealed:
        print("dolly secrets: none revealed — skip")
        return

    print("dolly revealed:", sorted(revealed))
    print("dolly mentioned in session log:", dolly_in_log)
    if revealed and not dolly_in_log:
        print(
            "WARN: dolly session_social has revealed secrets but the event log "
            "never mentions Dolly (stale NPC session state in character_manager)."
        )
        return

    chapel_secret = "secret_chapel_location" in revealed
    sanitarium_secret = "secret_sanitarium_hint" in revealed
    for flag_name, needed in (
        ("dolly_talked", True),
        ("dolly_told_chapel_location", chapel_secret),
        ("dolly_told_sanitarium_location", sanitarium_secret),
    ):
        actual = bool(scenario_mgr.flags.get(flag_name))
        print(f"  {flag_name}: {actual} (expected True if secrets disclosed: {needed})")
        if needed and not actual:
            print(
                f"WARN: {flag_name} is false despite Dolly disclosure. "
                "Movement gates may block chapel/sanitarium."
            )


def main() -> int:
    if not SAVE_PATH.is_file():
        print(f"ERROR: {SAVE_PATH} not found", file=sys.stderr)
        return 1

    save_data = json.loads(SAVE_PATH.read_text(encoding="utf-8"))
    verify_save_structure(save_data)
    verify_legacy_migration()
    verify_live_autosave_recovery(save_data)
    print("\nOK: save_autosave.json recovery checks passed (current spec).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AssertionError as exc:
        print(f"\nFAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
