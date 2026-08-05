import streamlit as st
import json
import uuid
import main
from SaveLoadManager import SaveLoadManager


def build_app_state():
    state = main.normalize_loaded_runtime_state({
        "all_events_log": st.session_state.all_events_log,
        "last_pl_action": st.session_state.last_pl_action,
        "last_system_result": st.session_state.last_system_result,
        "pending_san_check": st.session_state.pending_san_check,
        "pending_push_roll": st.session_state.get("pending_push_roll"),
        "pending_luck_burn": st.session_state.get("pending_luck_burn"),
        "pending_combat_defense": st.session_state.get("pending_combat_defense"),
        "partial_system_log": st.session_state.get("partial_system_log"),
        "push_decision_required": st.session_state.get("push_decision_required", False),
        "timeline_pending": st.session_state.get("timeline_pending"),
        "intervention_level": st.session_state.get("intervention_level", "standard"),
        "kp_style": st.session_state.get("kp_style", "collaborative"),
        "stagnation_kp_nudge": st.session_state.get("stagnation_kp_nudge"),
        "stagnation_pl_hint": st.session_state.get("stagnation_pl_hint"),
        "force_ic_action": st.session_state.get("force_ic_action", False),
        "autonomous_paused": st.session_state.get("autonomous_paused", False),
        "autonomous_pause_reason": st.session_state.get("autonomous_pause_reason"),
        "autonomous_guard": st.session_state.get("autonomous_guard"),
        "autonomous_step_count": st.session_state.get("autonomous_step_count", 0),
        "is_running": st.session_state.get("is_running", False),
        "stop_requested": st.session_state.get("stop_requested", False),
        "pl_id": st.session_state.pl_id,
        "char_name": st.session_state.char_name,
        "active_pcs": list(st.session_state.get("active_pcs") or []),
        "active_pc_id": st.session_state.get("active_pc_id") or st.session_state.pl_id,
        "pl_discussion_mode": st.session_state.get("pl_discussion_mode", False),
        "pl_discussion_rounds": st.session_state.get("pl_discussion_rounds", 0),
        "current_loc": st.session_state.current_loc,
        "scenario_file": st.session_state.get("scenario_file", main.DEFAULT_SCENARIO_FILE),
        "rp_eval_unit_ids": st.session_state.get("rp_eval_unit_ids", []),
        "rp_eval_last_summary": st.session_state.get("rp_eval_last_summary"),
        "rp_session_id": st.session_state.get("rp_session_id"),
        "rp_library_pending": st.session_state.get("rp_library_pending", []),
    }, enforce_half_turn_pause=False)
    if st.session_state.get("scenario_mgr"):
        main.normalize_game_action_targets(
            state, st.session_state.scenario_mgr, state.get("current_loc"),
        )
    return state


def apply_app_state(app_state, scenario_mgr=None):
    app_state = main.normalize_loaded_runtime_state(
        app_state,
        enforce_half_turn_pause=False,
    )
    if scenario_mgr:
        main.normalize_game_action_targets(app_state, scenario_mgr, app_state.get("current_loc"))
    st.session_state.all_events_log = app_state.get("all_events_log", [])
    st.session_state.last_pl_action = app_state.get("last_pl_action")
    st.session_state.last_system_result = app_state.get("last_system_result")
    st.session_state.pending_san_check = app_state.get("pending_san_check", None)
    st.session_state.pending_push_roll = app_state.get("pending_push_roll", None)
    st.session_state.pending_luck_burn = app_state.get("pending_luck_burn", None)
    st.session_state.pending_combat_defense = app_state.get("pending_combat_defense", None)
    st.session_state.partial_system_log = app_state.get("partial_system_log", None)
    st.session_state.push_decision_required = app_state.get("push_decision_required", False)
    st.session_state.timeline_pending = app_state.get("timeline_pending")
    st.session_state.intervention_level = app_state.get("intervention_level", "standard")
    st.session_state.kp_style = app_state.get("kp_style", "collaborative")
    st.session_state.stagnation_kp_nudge = app_state.get("stagnation_kp_nudge")
    st.session_state.stagnation_pl_hint = app_state.get("stagnation_pl_hint")
    st.session_state.force_ic_action = app_state.get("force_ic_action", False)
    st.session_state.autonomous_paused = app_state.get("autonomous_paused", False)
    st.session_state.autonomous_pause_reason = app_state.get("autonomous_pause_reason")
    st.session_state.autonomous_guard = app_state.get("autonomous_guard")
    st.session_state.autonomous_step_count = app_state.get("autonomous_step_count", 0)
    st.session_state.is_running = app_state.get("is_running", False)
    st.session_state.stop_requested = app_state.get("stop_requested", False)
    st.session_state.pl_id = app_state.get("pl_id", "pc_01")
    st.session_state.char_name = app_state.get("char_name", "")
    st.session_state.active_pcs = list(app_state.get("active_pcs") or [])
    st.session_state.active_pc_id = app_state.get("active_pc_id") or st.session_state.pl_id
    st.session_state.pl_discussion_mode = app_state.get("pl_discussion_mode", False)
    st.session_state.pl_discussion_rounds = app_state.get("pl_discussion_rounds", 0)
    st.session_state.current_loc = app_state.get("current_loc", "study")
    st.session_state.scenario_file = app_state.get("scenario_file", main.DEFAULT_SCENARIO_FILE)
    st.session_state.rp_eval_unit_ids = app_state.get("rp_eval_unit_ids", [])
    st.session_state.rp_eval_last_summary = app_state.get("rp_eval_last_summary")
    st.session_state.rp_session_id = app_state.get("rp_session_id")
    st.session_state.rp_library_pending = app_state.get("rp_library_pending", [])
    if scenario_mgr:
        main.normalize_session_action_targets(
            st.session_state, scenario_mgr, char_mgr=st.session_state.get("char_mgr"),
        )


def get_location_display(scenario_mgr, loc_id):
    return scenario_mgr.get_location_info(loc_id).get("name", loc_id)


def format_slot_label(slot_id, slots_by_id):
    slot = slots_by_id[slot_id]
    prefix = "[自動] " if slot.get("is_autosave") else ""
    legacy = " [旧形式]" if slot.get("is_legacy") else ""
    return (
        f"{prefix}{slot_id}{legacy} — "
        f"{slot['char_name']} / {slot['modified_at']}"
    )


def format_manual_slot_label(slot_id, slots_by_id):
    if slot_id in slots_by_id:
        s = slots_by_id[slot_id]
        return f"{slot_id} — {s['char_name']} ({s['modified_at']})"
    return f"{slot_id} — （空）"


def _is_system_meta_log_entry(entry):
    """セッション開始・通知・停止など、PL ではないシステムメタログか。"""
    text = str(entry.get("text", "") or "")
    if text.startswith("システム:"):
        return True
    return main._is_session_meta_entry(entry)


def render_log_chat_messages(all_events_log, char_name, container=None, char_mgr=None, active_pcs=None):
    """st.chat_message でログをチャット風に描画する。"""
    # container 未指定時は呼び出し側の with ブロック（またはページ直下）に描画する。
    # st モジュール自体は context manager ではないので with に渡さない。
    writer = container if container is not None else st

    if not all_events_log:
        writer.markdown("（ログはまだありません）")
        return

    for entry in all_events_log:
        text = entry["text"]
        meta = entry.get("meta") or {}
        if _is_system_meta_log_entry(entry):
            role = "assistant"
            body = text.replace("システム: ", "") if text.startswith("システム:") else text
            label = "⚙️ システム"
        elif text.startswith("KP:") or text.startswith("KP(プレイヤー層):"):
            role = "assistant"
            body = text.replace("KP: ", "").replace("KP(プレイヤー層): ", "")
            label = "🧙 KP"
        elif entry.get("channel") == "OOC" or "(PL):" in text:
            role = "user"
            body = text
            label = "💭 PL (OOC)"
            pc_id = meta.get("pc_id")
            if pc_id and char_mgr:
                label = f"💭 {char_mgr.get_pc_log_prefix(pc_id, role='PL')}"
        elif "(PC):" in text or meta.get("pc_id"):
            role = "user"
            body = text
            pc_id = meta.get("pc_id")
            if pc_id and char_mgr:
                label = f"👤 {char_mgr.get_pc_log_prefix(pc_id, role='PC')}"
            elif f"{char_name}(PC):" in text:
                label = f"👤 {char_name}"
            else:
                label = "👤 PC"
        else:
            role = "assistant" if entry.get("channel") == "IC" else "user"
            body = text
            label = "ℹ️"

        ctx = container if container is not None else None
        if ctx is not None:
            with ctx:
                with st.chat_message(role):
                    if label:
                        st.caption(label)
                    st.markdown(body)
        else:
            with st.chat_message(role):
                if label:
                    st.caption(label)
                st.markdown(body)


def begin_autonomous_session():
    """自律巡航のランタイム状態を初期化して開始する。"""
    game_state = main.extract_game_state(st.session_state)
    main.begin_autonomous_runtime(game_state)
    game_state["autonomous_guard"] = None
    game_state["autonomous_step_count"] = 0
    main.apply_game_state(st.session_state, game_state, st.session_state.scenario_mgr)


def end_autonomous_session(pause_reason=None):
    """自律巡航を終了し、手動待機状態へ戻す。"""
    game_state = main.extract_game_state(st.session_state)
    if pause_reason:
        main.finalize_autonomous_pause(game_state, pause_reason)
    else:
        game_state["is_running"] = False
        game_state["stop_requested"] = False
    try:
        from LogEvaluator import evaluate_session_rp_logs
        summary = evaluate_session_rp_logs(
            game_state,
            st.session_state.char_mgr,
            scenario_file=st.session_state.get("scenario_file"),
            scenario_mgr=st.session_state.scenario_mgr,
        )
        if summary and summary.get("saved_library"):
            notify_user(
                f"RP評価: {summary['saved_library']}件の良質ログを rp_library に保存しました。"
            )
    except Exception as exc:
        print(f"[LogEvaluator] 評価スキップ: {exc}")
    if pause_reason == "game_clear":
        pl_id = game_state.get("pl_id")
        if pl_id:
            reward_logs = main.apply_session_end_rewards(
                st.session_state.char_mgr, pl_id, pause_reason=pause_reason,
            )
            for line in reward_logs:
                game_state.setdefault("all_events_log", []).append({
                    "channel": "OOC",
                    "location": game_state.get("current_loc", "all"),
                    "secret_to": None,
                    "text": line,
                })
                notify_user(line)
    main.apply_game_state(st.session_state, game_state, st.session_state.scenario_mgr)


def handle_user_stop_before_tick():
    """サイクル実行前に停止要求を処理（未完了の AI 処理は走らせない）。"""
    if not st.session_state.get("stop_requested"):
        return False
    game_state = main.extract_game_state(st.session_state)
    main.append_user_stop_message(game_state)
    do_autosave()
    main.apply_game_state(st.session_state, game_state, st.session_state.scenario_mgr)
    end_autonomous_session("user_stop")
    return True


def _has_user_stop_log(all_events_log):
    return any(
        entry.get("text") == main.USER_STOP_LOG_TEXT
        for entry in (all_events_log or [])
    )


def _refresh_chat_log(chat_placeholder, char_mgr=None):
    """セッションログ欄を最新の all_events_log で差し替える。"""
    if chat_placeholder is None:
        return
    with chat_placeholder.container():
        render_log_chat_messages(
            st.session_state.get("all_events_log", []),
            st.session_state.get("char_name", ""),
            char_mgr=char_mgr or st.session_state.get("char_mgr"),
            active_pcs=st.session_state.get("active_pcs"),
        )


def run_autonomous_tick(char_mgr, dice_engine, state_mgr, scenario_mgr, chat_placeholder):
    """自律巡航を1サイクルだけ進め、停止フラグをサイクル完結後に評価する。"""

    def ui_callback(state):
        # ステップ完了ごとにログを差し替え、次の LLM 待ち中も発言が見えるようにする
        main.apply_game_state(st.session_state, state, scenario_mgr)
        _refresh_chat_log(chat_placeholder, char_mgr=char_mgr)

    def autosave_callback(state):
        main.apply_game_state(st.session_state, state, scenario_mgr)
        do_autosave()

    def should_stop():
        return bool(st.session_state.get("stop_requested"))

    game_state = main.extract_game_state(st.session_state)
    game_state["is_running"] = True
    game_state["stop_requested"] = st.session_state.get("stop_requested", False)

    managers = (char_mgr, dice_engine, state_mgr, scenario_mgr)
    pause_reason = main.run_timeline_loop(
        game_state,
        managers,
        ui_callback=ui_callback,
        autosave_callback=autosave_callback,
        max_iterations=1,
        should_stop_callback=should_stop,
    )
    main.apply_game_state(st.session_state, game_state, scenario_mgr)
    _refresh_chat_log(chat_placeholder, char_mgr=char_mgr)
    return pause_reason


def drive_autonomous_session(char_mgr, dice_engine, state_mgr, scenario_mgr, chat_placeholder):
    """段階 rerun による自律巡航ドライバ。UI スレッドが停止ボタンを受け付けられる隙間を作る。"""
    if not st.session_state.get("is_running"):
        return

    if handle_user_stop_before_tick():
        st.rerun()

    with st.status("🚀 自律セッション進行中...", expanded=True) as status:
        pause_reason = run_autonomous_tick(
            char_mgr, dice_engine, state_mgr, scenario_mgr, chat_placeholder
        )

        if pause_reason == "user_stop":
            status.update(label="⏸ ユーザーにより一時停止", state="complete")
            end_autonomous_session("user_stop")
            st.rerun()
        elif pause_reason == "game_clear":
            status.update(label="🎉 シナリオクリア！", state="complete")
            end_autonomous_session("game_clear")
            st.rerun()
        elif pause_reason:
            status.update(label=f"⏸ 一時停止: {pause_reason}", state="complete")
            end_autonomous_session(pause_reason)
            st.rerun()
        else:
            status.update(label="🔄 次の発言を生成中...", state="running")

    # ティック結果を描画したうえで次ランへ進む（連続 rerun でログが飛ばないようにする）
    _refresh_chat_log(chat_placeholder, char_mgr=char_mgr)
    if st.session_state.get("is_running"):
        st.rerun()


def render_log_entries(all_events_log, char_name):
    """ログ全体を単一の markdown として描画し、DOM ノード数の増減を防ぐ。"""
    lines = []
    for entry in all_events_log:
        text = entry["text"]
        if _is_system_meta_log_entry(entry):
            body = text.replace("システム: ", "") if text.startswith("システム:") else text
            lines.append(f"**⚙️ システム:** {body}")
        elif text.startswith("KP:"):
            lines.append(f"**🧙 KP:** {text.replace('KP: ', '')}")
        elif text.startswith("KP(プレイヤー層):"):
            lines.append(f"**🎭 KP(プレイヤー層):** {text.replace('KP(プレイヤー層): ', '')}")
        elif char_name in text:
            lines.append(f"**👤 {char_name}:** {text}")
        else:
            lines.append(f"ℹ️ {text}")
    st.markdown("\n\n".join(lines) if lines else "（ログはまだありません）")


def notify_user(message):
    """条件付き st.success を避け、ログへ追記して DOM を安定させる。"""
    if "all_events_log" not in st.session_state:
        st.session_state.all_events_log = []
    st.session_state.all_events_log.append(
        {"channel": "OOC", "location": "all", "secret_to": None, "text": f"[通知] {message}"}
    )


def do_autosave():
    app_state = build_app_state()
    try:
        from LogEvaluator import evaluate_session_rp_logs

        evaluate_session_rp_logs(
            app_state,
            st.session_state.char_mgr,
            scenario_file=st.session_state.get("scenario_file"),
            scenario_mgr=st.session_state.scenario_mgr,
        )
    except Exception as exc:
        print(f"[LogEvaluator] オートセーブ時評価スキップ: {exc}")
        from RPLibraryStore import on_autosave_rp_library_hook

        on_autosave_rp_library_hook(app_state)
    st.session_state.rp_eval_unit_ids = app_state.get("rp_eval_unit_ids", [])
    st.session_state.rp_eval_last_summary = app_state.get("rp_eval_last_summary")
    st.session_state.rp_library_pending = app_state.get("rp_library_pending", [])
    if st.session_state.get("scenario_mgr"):
        main.normalize_session_action_targets(
            st.session_state, st.session_state.scenario_mgr,
            char_mgr=st.session_state.get("char_mgr"),
        )
    slot_id = st.session_state.get("current_slot_id", SaveLoadManager.AUTOSAVE_SLOT_ID)
    main.generate_save_data(
        st.session_state.state_mgr,
        st.session_state.char_mgr,
        st.session_state.scenario_mgr,
        build_app_state(),
        slot_id=slot_id,
        scenario_file=st.session_state.get("scenario_file", main.DEFAULT_SCENARIO_FILE),
    )


def start_new_game(scenario_file=None):
    scenario_file = scenario_file or main.DEFAULT_SCENARIO_FILE
    char_mgr, dice_engine, state_mgr, scenario_mgr = main.init_game_system(scenario_file)
    st.session_state.char_mgr = char_mgr
    st.session_state.dice_engine = dice_engine
    st.session_state.state_mgr = state_mgr
    st.session_state.scenario_mgr = scenario_mgr
    st.session_state.scenario_file = scenario_file

    st.session_state.all_events_log = [
        {
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": f"[システム] セッションを開始します。（シナリオ: {main.get_scenario_label(scenario_file)}）",
        }
    ]
    st.session_state.last_pl_action = None
    st.session_state.last_system_result = None
    st.session_state.pending_san_check = None
    st.session_state.pending_push_roll = None
    st.session_state.pending_luck_burn = None
    st.session_state.pending_combat_defense = None
    st.session_state.partial_system_log = None
    st.session_state.push_decision_required = False
    st.session_state.timeline_pending = None
    st.session_state.intervention_level = st.session_state.get("intervention_level", "standard")
    st.session_state.kp_style = st.session_state.get("kp_style", "collaborative")
    st.session_state.stagnation_kp_nudge = None
    st.session_state.stagnation_pl_hint = None
    st.session_state.force_ic_action = False
    st.session_state.autonomous_paused = False
    st.session_state.autonomous_pause_reason = None
    st.session_state.autonomous_guard = None
    st.session_state.autonomous_step_count = 0
    st.session_state.is_running = False
    st.session_state.stop_requested = False
    st.session_state.rp_eval_unit_ids = []
    st.session_state.rp_eval_last_summary = None
    st.session_state.rp_session_id = str(uuid.uuid4())
    st.session_state.rp_library_pending = []
    from RPLibraryStore import RPLibraryStore
    RPLibraryStore().ensure_initialized()
    active_ids = main.default_active_pc_ids(st.session_state.char_mgr)
    st.session_state.char_mgr.set_active_pcs(active_ids)
    st.session_state.active_pcs = list(active_ids)
    start_pc = active_ids[0] if active_ids else "pc_01"
    st.session_state.pl_id = start_pc
    st.session_state.active_pc_id = start_pc
    st.session_state.char_name = st.session_state.char_mgr.get_pc_name(start_pc)
    for pid in active_ids:
        st.session_state.char_mgr.begin_session_stats(pid)
    st.session_state.pl_discussion_mode = False
    st.session_state.pl_discussion_rounds = 0
    st.session_state.current_loc = scenario_mgr.location or scenario_mgr.initial_state.get("location", "study")

    for pid in active_ids:
        startup = main.apply_scenario_startup_effects(
            scenario_mgr,
            state_mgr,
            st.session_state.char_mgr,
            pid,
            st.session_state.char_mgr.get_pc_name(pid),
        )
        if startup:
            st.session_state.all_events_log.append({
                "channel": "IC",
                "location": st.session_state.current_loc,
                "secret_to": None,
                "text": f"システム: {startup['log']}",
                "meta": {
                    "roll_type": "san_check",
                    "kp_narrated": False,
                    "pc_id": pid,
                },
            })

    st.session_state.current_slot_id = SaveLoadManager.AUTOSAVE_SLOT_ID
    main.start_new_ai_session()
    st.session_state.game_started = True


def load_from_slot(slot_id):
    success, app_state, scenario_mgr = main.load_game(
        st.session_state.state_mgr,
        st.session_state.char_mgr,
        st.session_state.scenario_mgr,
        slot_id,
    )
    if not success:
        return False

    st.session_state.scenario_mgr = scenario_mgr
    st.session_state.scenario_file = app_state.get("scenario_file", main.DEFAULT_SCENARIO_FILE)
    main.sync_progress_managers(st.session_state.state_mgr, scenario_mgr)
    app_state = main.recover_pending_timeline_on_load(
        app_state, scenario_mgr=scenario_mgr, char_mgr=st.session_state.char_mgr,
    )
    apply_app_state(app_state, scenario_mgr)
    if st.session_state.scenario_mgr.location:
        st.session_state.current_loc = st.session_state.scenario_mgr.location
    st.session_state.current_slot_id = slot_id
    st.session_state.rp_eval_unit_ids = app_state.get("rp_eval_unit_ids", [])
    st.session_state.rp_eval_last_summary = app_state.get("rp_eval_last_summary")
    main.rebuild_ai_session(st.session_state.all_events_log)
    st.session_state.game_started = True
    st.session_state.flash_message = f"「{slot_id}」をロードしました。"
    return True


def handle_manual_timeline_step(char_mgr, dice_engine, state_mgr, scenario_mgr):
    """手動でタイムラインを1チェーン進める（システム割り込みは連鎖実行）。"""
    game_state = main.extract_game_state(st.session_state)
    managers = (char_mgr, dice_engine, state_mgr, scenario_mgr)
    main.run_timeline_chain(game_state, managers)
    main.apply_game_state(st.session_state, game_state, scenario_mgr)
    if not main.is_game_cleared(scenario_mgr):
        do_autosave()


def handle_human_chat_message(text, channel, char_name, current_loc):
    """人間プレイヤーの IC/OOC 割り込み発言をタイムラインへ追記する。"""
    main.append_human_player_message(
        st.session_state.all_events_log,
        char_name,
        text,
        channel=channel,
        current_loc=current_loc,
        pc_id=st.session_state.get("active_pc_id") or st.session_state.get("pl_id"),
        char_mgr=st.session_state.get("char_mgr"),
    )
    do_autosave()


st.set_page_config(page_title="AI TRPG モニター", layout="wide")
st.title("AI クトゥルフ神話TRPG システム")

if "game_started" not in st.session_state:
    st.session_state.game_started = False
    st.session_state.pending_san_check = None
    st.session_state.pending_push_roll = None
    st.session_state.pending_luck_burn = None
    st.session_state.pending_combat_defense = None
    st.session_state.partial_system_log = None
    st.session_state.push_decision_required = False
    st.session_state.timeline_pending = None
    st.session_state.intervention_level = st.session_state.get("intervention_level", "standard")
    st.session_state.kp_style = st.session_state.get("kp_style", "collaborative")
    st.session_state.stagnation_kp_nudge = None
    st.session_state.stagnation_pl_hint = None
    st.session_state.force_ic_action = False
    st.session_state.autonomous_paused = False
    st.session_state.autonomous_pause_reason = None
    st.session_state.autonomous_guard = None
    st.session_state.autonomous_step_count = 0
    st.session_state.is_running = False
    st.session_state.stop_requested = False
    st.session_state.current_slot_id = SaveLoadManager.AUTOSAVE_SLOT_ID
    st.session_state.flash_message = None
    st.session_state.scenario_file = main.DEFAULT_SCENARIO_FILE

    char_mgr, dice_engine, state_mgr, scenario_mgr = main.init_game_system()
    st.session_state.char_mgr = char_mgr
    st.session_state.dice_engine = dice_engine
    st.session_state.state_mgr = state_mgr
    st.session_state.scenario_mgr = scenario_mgr

# --- スタートメニュー ---
if not st.session_state.game_started:
    st.subheader("スタートメニュー")
    available_slots = main.get_available_slots()
    slots_by_id = {s["slot_id"]: s for s in available_slots}

    scenario_options = main.list_scenario_options()
    scenario_labels = [label for _, label in scenario_options]
    scenario_files = [fname for fname, _ in scenario_options]
    selected_scenario_label = st.selectbox(
        "プレイするシナリオ",
        options=scenario_labels,
        index=0,
        key="new_game_scenario_select",
    )
    selected_scenario_file = scenario_files[scenario_labels.index(selected_scenario_label)]

    if selected_scenario_file == main.CORBITT_SCENARIO_FILE:
        try:
            from build_corbitt_scenario import needs_rebuild, staged_cache_available
            if staged_cache_available() and needs_rebuild():
                st.info(
                    "悪霊の家: 分割ソース（loc_*.json / outline.json）が更新されています。"
                    "ゲーム開始時にバリデーション付きで自動再ビルドします。"
                )
            elif staged_cache_available():
                st.caption("悪霊の家: ビルド済みシナリオはソースと同期済みです。")
        except Exception:
            pass

    intervention_labels = ["なし", "控えめ", "標準", "積極的"]
    intervention_values = ["none", "light", "standard", "force"]
    current_iv = st.session_state.get("intervention_level", "standard")
    try:
        iv_index = intervention_values.index(current_iv)
    except ValueError:
        iv_index = 2
    selected_iv_label = st.selectbox(
        "介入度設定（膠着時）",
        options=intervention_labels,
        index=iv_index,
        key="new_game_intervention_select",
        help="同じ場所で失敗が続くときのシステム介入の強さです。シナリオ設定との強い方が採用されます。",
    )
    st.session_state.intervention_level = intervention_values[intervention_labels.index(selected_iv_label)]

    kp_style_labels = ["クラシック (classic)", "協調 (collaborative)", "ヘルプフル (helpful)"]
    kp_style_values = ["classic", "collaborative", "helpful"]
    current_style = st.session_state.get("kp_style", "collaborative")
    try:
        style_index = kp_style_values.index(current_style)
    except ValueError:
        style_index = 1
    selected_style_label = st.selectbox(
        "KPプレイスタイル",
        options=kp_style_labels,
        index=style_index,
        key="new_game_kp_style_select",
        help="classic=介入弱 / collaborative=ライト / helpful=標準。シナリオ設定との強い方が採用されます。",
    )
    st.session_state.kp_style = kp_style_values[kp_style_labels.index(selected_style_label)]

    col1, col2 = st.columns(2)
    with col1:
        if st.button("初めからプレイ", key="btn_new_game", use_container_width=True):
            try:
                start_new_game(selected_scenario_file)
                st.rerun()
            except FileNotFoundError as exc:
                notify_user(f"シナリオの読み込みに失敗しました: {exc}")

    with col2:
        st.markdown("**続きからプレイ**")
        if not available_slots:
            st.caption("セーブデータがありません。")
        else:
            slot_ids = [s["slot_id"] for s in available_slots]
            selected_slot_id = st.selectbox(
                "セーブスロットを選択",
                options=slot_ids,
                format_func=lambda sid: format_slot_label(sid, slots_by_id),
                key="load_slot_select",
            )
            if st.button("選択したスロットをロード", key="btn_load_game", use_container_width=True):
                if load_from_slot(selected_slot_id):
                    st.rerun()
                else:
                    notify_user("ロードに失敗しました。セーブデータを確認してください。")

    if available_slots:
        st.divider()
        st.markdown("**保存済みスロット一覧**")
        for slot in available_slots:
            legacy = "（旧形式）" if slot.get("is_legacy") else ""
            autosave = "（自動セーブ）" if slot.get("is_autosave") else ""
            st.text(
                f"・{slot['slot_id']}{legacy}{autosave} — "
                f"{slot['char_name']} / 更新: {slot['modified_at']} / "
                f"場所: {slot.get('current_loc', '-')} / "
                f"シナリオ: {slot.get('scenario_label', '-')}"
            )

    st.stop()

# --- ゲーム本編 ---
char_mgr, dice_engine, _, scenario_mgr = main.refresh_stale_managers(
    st.session_state.char_mgr,
    st.session_state.dice_engine,
    st.session_state.state_mgr,
    st.session_state.scenario_mgr,
)
st.session_state.char_mgr = char_mgr
st.session_state.dice_engine = dice_engine
scenario_mgr = st.session_state.scenario_mgr
main.normalize_session_runtime_flags(st.session_state)
main.normalize_session_action_targets(
    st.session_state, scenario_mgr, char_mgr=st.session_state.get("char_mgr"),
)
_recovered_state = main.recover_pending_timeline_on_load(
    build_app_state(),
    scenario_mgr=scenario_mgr,
    char_mgr=st.session_state.get("char_mgr"),
    normalize_runtime_flags=False,
)
apply_app_state(_recovered_state, scenario_mgr)

pl_id = st.session_state.get("pl_id", "new_investigator")
char_name = st.session_state.get("char_name", "調査員")
current_loc = st.session_state.get("current_loc", "study")
current_slot_id = st.session_state.get("current_slot_id", SaveLoadManager.AUTOSAVE_SLOT_ID)

if st.session_state.get("flash_message"):
    notify_user(st.session_state.flash_message)
    st.session_state.flash_message = None

with st.sidebar:
    st.header("ステータス")
    st.markdown(f"**シナリオ:** {main.get_scenario_label(st.session_state.get('scenario_file'))}")
    st.markdown(f"**現在地:** {get_location_display(scenario_mgr, current_loc)}")
    st.caption(f"（ID: `{current_loc}`）")

    st.subheader("膠着介入")
    intervention_labels = ["なし", "控えめ", "標準", "積極的"]
    intervention_values = ["none", "light", "standard", "force"]
    current_iv = st.session_state.get("intervention_level", "standard")
    try:
        iv_index = intervention_values.index(current_iv)
    except ValueError:
        iv_index = 2
    selected_iv_label = st.selectbox(
        "介入度",
        options=intervention_labels,
        index=iv_index,
        key="sidebar_intervention_select",
    )
    st.session_state.intervention_level = intervention_values[
        intervention_labels.index(selected_iv_label)
    ]
    kp_style_labels = ["クラシック", "協調", "ヘルプフル"]
    kp_style_values = ["classic", "collaborative", "helpful"]
    current_style = st.session_state.get("kp_style", "collaborative")
    try:
        style_index = kp_style_values.index(current_style)
    except ValueError:
        style_index = 1
    selected_style_label = st.selectbox(
        "KPスタイル",
        options=kp_style_labels,
        index=style_index,
        key="sidebar_kp_style_select",
    )
    st.session_state.kp_style = kp_style_values[kp_style_labels.index(selected_style_label)]
    effective = main.resolve_session_intervention_level(
        {
            "intervention_level": st.session_state.intervention_level,
            "kp_style": st.session_state.kp_style,
        },
        scenario_mgr,
    )
    st.caption(
        f"実効介入: {main.INTERVENTION_LEVEL_LABELS.get(effective, effective.name)} "
        f"/ 膠着連続: {st.session_state.get('stagnation_streak', scenario_mgr.stagnation_counter)}"
    )

    active_pcs = list(st.session_state.get("active_pcs") or [pl_id])
    active_pc_id = st.session_state.get("active_pc_id") or pl_id
    st.subheader("探索者パーティ")
    st.caption(f"手番: `{active_pc_id}`")
    for pid in active_pcs:
        name = char_mgr.get_pc_name(pid)
        slot = char_mgr.get_pc_slot_label(pid)
        marker = " ▶" if pid == active_pc_id else ""
        st.markdown(f"**{name} ({slot}){marker}**")
        stats = char_mgr.get_stat_display(pid)
        san = stats["SAN"]
        hp = stats["HP"]
        mp = stats["MP"]
        luck_val = char_mgr.get_luck(pid)
        incap = "〔行動不能〕" if char_mgr.is_pc_incapacitated(pid, st.session_state.get("state_mgr")) else ""
        st.markdown(
            f"SAN {san['current']}/{san['max']} · "
            f"HP {hp['current']}/{hp['max']} · "
            f"MP {mp['current']}/{mp['max']} · 幸運 {luck_val} {incap}"
        )
        dex_val = char_mgr.get_attribute(pid, "DEX")
        if dex_val is not None:
            st.caption(f"DEX {dex_val}")

    if st.button("🗣️ 作戦会議を開始", key="btn_start_discussion", use_container_width=True):
        st.session_state.pl_discussion_mode = True
        st.session_state.pl_discussion_rounds = 0
        st.rerun()
    if st.session_state.get("pl_discussion_mode"):
        st.info("作戦会議中（ダイスなし OOC）")

    pending_push = st.session_state.get("pending_push_roll")
    if pending_push:
        push_note = (
            f"⚠️ プッシュ決定待ち: {pending_push.get('skill_name', '')} "
            f"（対象: {pending_push.get('target', '')}）"
        )
    else:
        push_note = "プッシュロール: なし"
    st.caption(push_note)

    pending_luck = st.session_state.get("pending_luck_burn")
    if pending_luck:
        luck_note = (
            f"🍀 幸運消費待ち: {pending_luck.get('margin', 0)}pt "
            f"（{pending_luck.get('skill_name', '')} / {pending_luck.get('target', '')}）"
        )
    else:
        luck_note = "幸運消費判断: なし"
    st.caption(luck_note)

    pending_combat = st.session_state.get("pending_combat_defense")
    if pending_combat:
        is_shoot = str(pending_combat.get("attack_type") or "").lower() in (
            "shoot", "firearm", "ranged", "gun",
        ) or bool(pending_combat.get("is_ranged"))
        if is_shoot:
            st.caption(
                f"🔫 射撃防衛待ち: {pending_combat.get('defender_id', '')} が"
                f" 銃撃（{pending_combat.get('attacker_id', '')}）への回避／甘受を選択中"
                f"（応戦不可"
                + ("・ゼロ距離" if pending_combat.get("point_blank") else "")
                + "）"
            )
        else:
            st.caption(
                f"⚔️ 戦闘防衛待ち: {pending_combat.get('defender_id', '')} が"
                f" 攻撃（{pending_combat.get('attacker_id', '')}）への回避／応戦を選択中"
            )

    timeline_pending = st.session_state.get("timeline_pending")
    if timeline_pending:
        st.caption(f"保留フェーズ: {timeline_pending}")

    available_exits = scenario_mgr.get_available_exits(current_loc)
    st.markdown("**移動可能**")
    if available_exits:
        exit_text = "\n".join(
            f"→ {exit_info['name']} (`{exit_info['id']}`)" for exit_info in available_exits
        )
    else:
        exit_text = "（なし）"
    st.caption(exit_text)

    st.divider()
    st.header("セーブ / ロード")
    st.caption(f"現在のスロット: `{current_slot_id}`")
    st.caption("タイムライン進行時は現在のスロットへ自動保存されます。")

    manual_slots = list(SaveLoadManager.DEFAULT_MANUAL_SLOTS)
    slots_by_id = {s["slot_id"]: s for s in main.get_available_slots()}

    manual_target = st.selectbox(
        "手動セーブ先",
        options=manual_slots,
        format_func=lambda sid: format_manual_slot_label(sid, slots_by_id),
        key="manual_save_slot",
    )
    if st.button("💾 手動セーブ", key="btn_manual_save", use_container_width=True):
        success, _ = main.save_game_to_slot(
            manual_target,
            st.session_state.state_mgr,
            st.session_state.char_mgr,
            st.session_state.scenario_mgr,
            build_app_state(),
            scenario_file=st.session_state.get("scenario_file", main.DEFAULT_SCENARIO_FILE),
        )
        if success:
            notify_user(f"「{manual_target}」に保存しました。")
            st.rerun()
        else:
            notify_user("保存に失敗しました。")

    st.divider()
    st.markdown("**保存済みスロット**")
    sidebar_slots = main.get_available_slots()
    if sidebar_slots:
        slot_text = "\n".join(
            f"{slot['slot_id']}: {slot['char_name']} ({slot['modified_at']})"
            for slot in sidebar_slots
        )
        st.text(slot_text)
    else:
        st.caption("なし")

st.subheader("セッションログ")
st.caption(f"📍 現在地: {get_location_display(scenario_mgr, current_loc)}")

# empty に差し替えることで、自律巡航中の再描画でもゴースト（薄い二重表示）を出さない
chat_log_area = st.empty()

st.divider()

is_game_clear = main.is_game_cleared(scenario_mgr)
is_running = st.session_state.get("is_running", False)
is_paused = st.session_state.get("autonomous_paused", False)
pause_reason = st.session_state.get("autonomous_pause_reason")

if is_game_clear:
    st.markdown("🎉 シナリオクリア条件が満たされました！ゲーム終了です。")
elif is_running:
    st.info("🔄 自律セッション稼働中 — いつでも下の「一時停止」ボタンで止められます。")
elif is_paused and pause_reason:
    pause_labels = {
        "user_stop": "ユーザー操作",
        "stagnation": "会話停滞",
        "speaker_limit": "同一話者連続",
        "max_iterations": "最大ステップ到達",
        "game_clear": "シナリオクリア",
    }
    st.info(f"自律巡航を一時停止しました（理由: {pause_labels.get(pause_reason, pause_reason)}）")

col_auto, col_manual = st.columns(2)

with col_auto:
    if is_game_clear:
        if st.button("リプレイログを保存", key="btn_autonomous", use_container_width=True):
            with open("replay_log.json", "w", encoding="utf-8") as f:
                json.dump(st.session_state.all_events_log, f, ensure_ascii=False, indent=4)
            notify_user("replay_log.json に保存しました。")
            st.rerun()
    elif is_running:
        if st.button(
            "🛑 一時停止（セッションを止める）",
            key="btn_autonomous_stop",
            type="primary",
            use_container_width=True,
        ):
            st.session_state.stop_requested = True
            st.rerun()
    else:
        auto_label = "▶ 自律巡航を再開" if is_paused else "🚀 自律セッション開始（自動進行）"
        if st.button(auto_label, key="btn_autonomous_start", use_container_width=True):
            begin_autonomous_session()
            st.rerun()

with col_manual:
    manual_disabled = is_running
    if st.button(
        "▶ 次のステップを自律駆動させる",
        key="btn_manual_step",
        use_container_width=True,
        disabled=manual_disabled,
    ):
        handle_manual_timeline_step(char_mgr, dice_engine, st.session_state.state_mgr, scenario_mgr)
        st.rerun()

if not is_game_clear and not is_running:
    st.markdown("**あなたの発言（割り込み）**")
    with st.form("human_chat_form", clear_on_submit=True):
        chat_col1, chat_col2 = st.columns([3, 1])
        with chat_col2:
            human_channel = st.radio(
                "チャンネル",
                options=["OOC", "IC"],
                horizontal=True,
                help="OOC: メタ発言 / IC: キャラクターとしての発言",
            )
        with chat_col1:
            human_text = st.text_input(
                "メッセージ",
                placeholder="いつでも OOC/IC でチャット割り込みできます",
                label_visibility="collapsed",
            )
        if st.form_submit_button("💬 発言を送る", disabled=False):
            if human_text.strip():
                handle_human_chat_message(human_text.strip(), human_channel, char_name, current_loc)
                st.rerun()

# ログ描画は自律巡航の st.rerun() より前に行う（rerun で以降のコードが実行されなくなるため）
_refresh_chat_log(chat_log_area, char_mgr=char_mgr)

drive_autonomous_session(
    char_mgr, dice_engine, st.session_state.state_mgr, scenario_mgr, chat_log_area
)
