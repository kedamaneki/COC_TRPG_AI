import atexit
import copy
import hashlib
import json
import os
import random
import re
import sys
import time
import uuid
from urllib.parse import urlsplit, urlunsplit


def _configure_utf8_stdio():
    """Windows でもテスト／ログの日本語が読めるよう標準入出力を UTF-8 にする。"""
    for stream_name in ("stdout", "stderr", "stdin"):
        stream = getattr(sys, stream_name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass


_configure_utf8_stdio()


_llm_metrics_path = None
_llm_metrics_context_provider = None


def configure_llm_metrics(path=None, context_provider=None, *, reset=False):
    """Configure append-only LLM timing telemetry without changing inference inputs."""
    global _llm_metrics_path, _llm_metrics_context_provider
    _llm_metrics_path = os.fspath(path) if path else None
    _llm_metrics_context_provider = context_provider
    if _llm_metrics_path:
        metrics_dir = os.path.dirname(os.path.abspath(_llm_metrics_path))
        os.makedirs(metrics_dir, exist_ok=True)
        if reset:
            with open(_llm_metrics_path, "w", encoding="utf-8"):
                pass


def _llm_response_extra(response):
    try:
        payload = response.model_dump()
    except Exception:
        payload = {}
    return payload, payload.get("usage") or {}


def _record_llm_metric(metric):
    if not _llm_metrics_path:
        return
    context = {}
    if callable(_llm_metrics_context_provider):
        try:
            context = dict(_llm_metrics_context_provider() or {})
        except Exception:
            context = {}
    row = {**context, **dict(metric or {})}
    try:
        with open(_llm_metrics_path, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
    except OSError as exc:
        print(f"[LLM timing] telemetry write failed: {exc}")

import streamlit as st
from openai import OpenAI
from ObjectLifecycle import apply_object_transition

from CharacterManager import (
    CharacterManager,
    knowledge_id_for_object,
    knowledge_id_for_secret,
    object_has_private_clue_content,
)
from SkillRegistry import resolve_roll_target
from CoCRules import (
    DECISION_OPTION_ACCEPT,
    DECISION_OPTION_PUSH,
    DECISION_OPTION_SPEND_LUCK,
    DEFAULT_LUCK_BURN_MAX,
    PENDING_DECISION_COMBAT_DEFENSE,
    PENDING_DECISION_POST_ROLL_FAILURE,
    PENDING_DECISION_SHOOT_DEFENSE,
    build_combat_defense_legal_options,
    build_post_roll_failure_legal_options,
    is_push_allowed,
)
from DiceEngine import (
    DiceEngine,
    SuccessLevel,
    is_failure_level,
    is_success_level,
    luck_points_needed,
    min_level_for_difficulty,
    normalize_difficulty,
)
from GameStateManager import (
    GameStateManager,
    InterventionLevel,
    INTERVENTION_LEVEL_LABELS,
    KP_STYLE_TO_INTERVENTION,
    intervention_level_from_kp_style,
    normalize_intervention_level,
    resolve_effective_intervention_level,
)
from NPCSocialManager import (
    NPCSocialManager,
    format_npc_directory_for_pl,
    find_npc_id_by_target,
    find_npc_id_from_intent_text,
    is_casual_talk,
    is_negotiation_skill_for_npc,
    is_social_action,
    npc_is_available,
    normalize_occupation_rp_judgment,
    default_occupation_rp_judgment,
    resolve_social_skill_name,
)
from ActionValidator import (
    MOVE_INTENT_MISMATCH_ERROR,
    MOVE_MISSING_TARGET_ERROR,
    ABSENT_NPC_TALK_RETRY_ERROR,
    PUSH_ROLL_UNAVAILABLE_ERROR,
    VALIDATION_AUTO_CORRECT_CODES,
    HUMAN_INSPECT_REWRITE_LOG,
    OBJECT_TALK_REWRITE_LOG,
    PL_RETRY_PROMPT_PREFIX,
    PL_IDENTITY_MISMATCH_ERROR,
    PL_IDENTITY_MISMATCH_CODE,
    KP_SUCCESS_FACT_GUARD,
    KP_LOCKED_ROUTE_GUARD,
    FORCE_IC_ACTION_CHAT_ROUNDS,
    FORCE_IC_ACTION_STAGNATION_STREAK,
    STAGNATION_HINT_TURNS,
    STAGNATION_FORCE_TURNS,
    STAGNATION_MILD_NOTICE,
    VALIDATION_RETRY_BREAKOUT_COUNT,
    OOC_LOOP_FORCE_ACTION_WARNING,
    FORCE_IC_WAIT_REJECT_ERROR,
    FORCE_IC_STALE_TALK_REJECT_ERROR,
    STALE_KNOTT_TALK_REJECT_ERROR,
    STALE_RECEPTION_TALK_REJECT_ERROR,
    STALE_ARTIE_TALK_REJECT_ERROR,
    ARTIE_NEGOTIATE_STAGNATION_HINT,
    ARTIE_NEGOTIATE_ALTERNATE_SKILL_HINT,
    ACCESS_GATE_NEGOTIATE_SKILL_HINT,
    ARTIE_ACCESS_GRANTED_SEARCH_HINT,
    ARTIE_ACCESS_GRANTED_KP_DIRECTIVE,
    BOSTON_GLOBE_INVESTIGATION_DONE_HINT,
    ABSENT_NPC_REDIRECT_CLIPPING_HINT,
    POST_ACCESS_SEARCH_FORCE_TURNS,
    LOCATION_EXHAUSTED_FORCE_TURNS,
    BOSTON_GLOBE_NEGOTIATE_GRACE_RETRY_COUNT,
    INVESTIGATION_DEADLOCK_FORCE_TURNS,
    INVESTIGATION_BAILOUT_HINT,
    HOUSE_ENTRY_LOCATION_ID,
    LOCATION_FORCED_PROGRESS_PREFERENCE,
    FORCE_PROGRESS_BREAKOUT_LOG,
    STAGNATION_STANDARD_PL_HINT,
    TALK_ACTION_IDS,
    NEGOTIATION_ACTION_IDS,
    INTENT_ACTION_REQUEST,
    INTENT_DISCUSSION_OR_PLAN,
    INTENT_IN_CHARACTER_DIALOGUE,
    INTENT_UNCLEAR,
    validate_move_intent,
    validate_push_roll_available,
    infer_empty_move_from_intent,
    suggest_empty_move_fix,
    object_is_currently_available,
    object_is_investigated,
    validate_force_ic_action,
    validate_completed_knott_talk,
    validate_completed_dolly_talk,
    is_stale_nonprogress_talk,
    is_stale_boston_globe_talk,
    is_boston_globe_clipping_investigated,
    build_boston_globe_stale_guidance,
    is_location_investigation_exhausted,
    should_apply_location_exhausted_move,
    build_location_exhausted_move_hint,
    build_forced_progress_move_action,
    build_forced_progress_action,
    pick_corbitt_exterior_entry_action,
    build_context_stagnation_hint,
    build_reason_stagnation_hint,
    count_investigation_deadlock_streak,
    is_investigation_deadlock,
    rewrite_human_investigation_to_talk,
    rewrite_talk_to_object_investigation,
    is_investigable_location_object,
    resolve_social_npc_id,
    resolve_engine_action_judgment,
    collect_pc_identity_profiles,
    detect_pl_identity_violation,
    detect_kp_narration_violations,
    extract_resolved_skill_from_result,
    is_system_outcome_success,
    is_access_already_granted,
    extract_public_confirmed_narration_parts,
    scrub_system_log_for_public_ic,
    interpret_player_intent,
    can_auto_execute_move,
    classify_target_scope,
    classify_actionable_proposal,
    is_duplicate_npc_dialogue,
    has_explicit_move_expression,
    is_courtesy_dialogue_text,
    is_pure_consultation_text,
)
from SaveLoadManager import SaveLoadManager
from ScenarioManager import (
    MOVE_DENY_SYSTEM_LOG,
    STAGNATION_PAUSE_THRESHOLD,
    ScenarioManager,
    fact_already_in_text,
    format_handout_ic_block,
    should_emit_handout_ic,
)
from ProgressionPolicy import reconcile_location
from ActionAvailability import (
    AVAILABLE as ACTION_AVAILABLE,
    check_action_availability,
    compare_candidate_and_execution,
)
from CombatProgression import (
    COMBAT_ACTIVE,
    append_combat_event,
    build_combat_action_candidates,
    combat_is_active,
    combat_prompt_block,
    evaluate_combat_end,
    guide_combat_action,
    validate_combat_action,
    validate_combat_location,
)
from CombatResolutionGuard import (
    DETERMINISTIC_RULE,
    EXPLICIT_NO_ROLL,
    ROLL,
    UNRESOLVED_COMBAT_ACTION,
    CombatResolutionError,
    declare_resolution_class,
    guard_special_objective_payload,
    is_corbitt_victory_critical,
    is_irreversible_candidate,
)
from CorbittKillRoutes import (
    CORBITT_NPC_ID,
    apply_kill_payload_to_scenario,
    remap_body_break_to_attack,
    try_route_a_on_hp0,
    try_route_b_on_hit,
)
from BossCombatPolicy import (
    ACTION_BODY_ACTIVATION,
    ACTION_DOMINATE,
    ACTION_MAGIC_DAGGER,
    ACTION_NORMAL_ATTACK,
    activate_body,
    choose_corbitt_action,
    note_pc_hit,
    resolve_dominate,
    tick_body_activation,
)
from ProgressDirectorV2 import (
    AUTONOMOUS,
    HUMAN_GUIDED,
    SYSTEM_GUIDED,
    SYSTEM_FORCED,
    apply_s4_candidate_override,
    mark_progression_adjudication_started,
    apply_stall_candidate_guidance,
    build_director_prompt,
    classify_action_origin,
    ensure_director_state,
    record_unified_turn,
    stamp_action_origin,
)
from InvestigationFlow import (
    INVESTIGATION_ACTIONS as FLOW_INVESTIGATION_ACTIONS,
    REJECT_SKILL_PROPOSAL,
    build_attempt_rights_prompt,
    ensure_investigation_state,
    finalize_investigation,
    prepare_investigation,
)

# ==========================================
# 1. ローカル LLM（OpenAI 互換 API）の設定
# ==========================================
_clients = {}
_chat_history = []


def _apply_windows_asyncio_shutdown_patch():
    """Windows ProactorEventLoop の接続切断時ノイズを抑止する（既知の無害エラー）。"""
    if sys.platform != "win32":
        return
    try:
        import asyncio
        from asyncio import proactor_events
    except ImportError:
        return

    transport_cls = getattr(proactor_events, "_ProactorBasePipeTransport", None)
    if transport_cls is None:
        return

    original = transport_cls._call_connection_lost

    def _safe_call_connection_lost(self, exc):
        try:
            original(self, exc)
        except OSError:
            pass

    if getattr(transport_cls._call_connection_lost, "__name__", "") != "_safe_call_connection_lost":
        transport_cls._call_connection_lost = _safe_call_connection_lost


_apply_windows_asyncio_shutdown_patch()

DEFAULT_OLLAMA_URL = "http://127.0.0.1:11434"
DEFAULT_LLM_BASE_URL = DEFAULT_OLLAMA_URL + "/v1"
DEFAULT_LLM_API_KEY = "ollama"
DEFAULT_PL_MODEL = "qwen2.5:14b"
DEFAULT_KP_MODEL = "qwen2.5:14b"
DEFAULT_LLM_TIMEOUT = 120.0
DEFAULT_LLM_MAX_TOKENS = 2048


def _get_config_value(key, env_key, default):
    """st.secrets → 環境変数 → デフォルトの順で設定値を取得する。"""
    try:
        if key in st.secrets:
            return st.secrets[key]
    except (FileNotFoundError, KeyError, RuntimeError):
        pass
    env_val = os.environ.get(env_key)
    if env_val is not None and env_val != "":
        return env_val
    return default


def _get_first_config_value(keys, default=None):
    for key in keys:
        try:
            value = st.secrets[key] if key in st.secrets else None
        except (FileNotFoundError, KeyError, RuntimeError):
            value = None
        if value is not None and str(value).strip():
            return value, key
        value = os.environ.get(key)
        if value is not None and str(value).strip():
            return value, key
    return default, None


def _normalize_ollama_url(value):
    """Validate an administrator-provided Ollama URL and return root/OpenAI URLs."""
    raw = str(value or "").strip().rstrip("/")
    parsed = urlsplit(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Ollama URL must use http/https and include a host")
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError("Ollama URL must not contain credentials, query, or fragment")
    path = parsed.path.rstrip("/")
    if path not in {"", "/v1"}:
        raise ValueError("Ollama URL path must be empty or /v1")
    root = urlunsplit((parsed.scheme, parsed.netloc, "", "", "")).rstrip("/")
    return {"root_url": root, "openai_base_url": root + "/v1"}


def canonicalize_llm_role(role):
    token = str(role or "").strip().upper()
    aliases = {
        "PL": "PL", "PLAYER": "PL",
        "KP": "KP", "KEEPER": "KP", "GM": "KP",
        "JUDGE": "JUDGE",
    }
    return aliases.get(token, token or "UNKNOWN")


def get_llm_config():
    """ローカル LLM 接続設定を返す。"""
    kp_model = _get_config_value("LLM_KP_MODEL", "LLM_KP_MODEL", DEFAULT_KP_MODEL)
    primary_raw, primary_source = _get_first_config_value(
        ("PRIMARY_OLLAMA_URL", "OLLAMA_URL", "OLLAMA_BASE_URL", "OPENAI_BASE_URL", "LLM_BASE_URL"),
        DEFAULT_OLLAMA_URL,
    )
    secondary_raw, secondary_source = _get_first_config_value(("SECONDARY_OLLAMA_URL",), None)
    primary = _normalize_ollama_url(primary_raw)
    secondary = _normalize_ollama_url(secondary_raw) if secondary_source else dict(primary)
    failure_policy = str(_get_config_value(
        "SECONDARY_FAILURE_POLICY", "SECONDARY_FAILURE_POLICY", "FAIL_CLOSED"
    )).strip().upper()
    if failure_policy not in {"FAIL_CLOSED", "FALLBACK_PRIMARY"}:
        raise ValueError("SECONDARY_FAILURE_POLICY must be FAIL_CLOSED or FALLBACK_PRIMARY")
    return {
        "base_url": primary["openai_base_url"],
        "primary_root_url": primary["root_url"],
        "primary_base_url": primary["openai_base_url"],
        "primary_source": primary_source or "DEFAULT",
        "secondary_root_url": secondary["root_url"],
        "secondary_base_url": secondary["openai_base_url"],
        "secondary_source": secondary_source or "PRIMARY_FALLBACK",
        "secondary_explicit": bool(secondary_source),
        "secondary_failure_policy": failure_policy,
        "execution_profile": str(_get_config_value(
            "EXECUTION_PROFILE", "EXECUTION_PROFILE", "SINGLE_PC"
        )).strip().upper(),
        "api_key": _get_config_value("LLM_API_KEY", "LLM_API_KEY", DEFAULT_LLM_API_KEY),
        "pl_model": _get_config_value("LLM_PL_MODEL", "LLM_PL_MODEL", DEFAULT_PL_MODEL),
        "kp_model": kp_model,
        "judge_model": _get_config_value("LLM_JUDGE_MODEL", "LLM_JUDGE_MODEL", kp_model),
        "timeout": float(_get_config_value("LLM_TIMEOUT", "LLM_TIMEOUT", str(DEFAULT_LLM_TIMEOUT))),
        "max_tokens": int(_get_config_value("LLM_MAX_TOKENS", "LLM_MAX_TOKENS", str(DEFAULT_LLM_MAX_TOKENS))),
    }


def resolve_ollama_endpoint(role, config=None, *, force_primary=False):
    cfg = config or get_llm_config()
    canonical_role = canonicalize_llm_role(role)
    wants_secondary = canonical_role == "JUDGE" and not force_primary
    use_secondary = wants_secondary and bool(cfg.get("secondary_explicit"))
    endpoint_class = "SECONDARY" if use_secondary else "PRIMARY"
    root_url = cfg["secondary_root_url"] if use_secondary else cfg["primary_root_url"]
    base_url = cfg["secondary_base_url"] if use_secondary else cfg["primary_base_url"]
    return {
        "llm_role": canonical_role,
        "requested_endpoint_class": "SECONDARY" if wants_secondary else "PRIMARY",
        "endpoint_class": endpoint_class,
        "root_url": root_url,
        "base_url": base_url,
        "endpoint_url_redacted": endpoint_class,
        "execution_host": "PC2" if endpoint_class == "SECONDARY" else "PC1",
        "remote": endpoint_class == "SECONDARY",
        "config_fallback": wants_secondary and not use_secondary,
    }


def get_ollama_topology_metadata(config=None):
    cfg = config or get_llm_config()
    return {
        "execution_environment": cfg["execution_profile"],
        "core_host": "PC1",
        "primary_ollama": "PC1",
        "secondary_ollama": "PC2" if cfg.get("secondary_explicit") else "PC1",
        "secondary_failure_policy": cfg["secondary_failure_policy"],
        "routing": {
            role: resolve_ollama_endpoint(role, cfg)["endpoint_class"]
            for role in ("PL", "KP", "JUDGE")
        },
    }


def close_llm_client():
    """OpenAI 互換クライアントの HTTP 接続を明示的に閉じる。"""
    global _clients
    for client in list(_clients.values()):
        try:
            client.close()
        except Exception:
            pass
    _clients = {}


def get_client(role="PL", *, force_primary=False):
    """Return a client selected only by the canonical LLM role."""
    global _clients
    cfg = get_llm_config()
    endpoint = resolve_ollama_endpoint(role, cfg, force_primary=force_primary)
    cache_key = (endpoint["base_url"], str(cfg["api_key"]), float(cfg["timeout"]))
    if cache_key not in _clients:
        _clients[cache_key] = OpenAI(
            base_url=endpoint["base_url"],
            api_key=cfg["api_key"],
            timeout=cfg["timeout"],
        )
    return _clients[cache_key]


atexit.register(close_llm_client)


def _is_model_not_found_error(exc):
    """Ollama 等でモデル名が存在しない場合の 404 を検出する。"""
    err = str(exc).lower()
    return "404" in err and ("not found" in err or "not_found" in err)


def _log_model_not_found_hint(exc, model):
    """モデル未インストール時に対処法をログ出力する。"""
    if _is_model_not_found_error(exc):
        print(
            f"\n[ヒント] モデル '{model}' が見つかりません。"
            " `ollama list` でインストール済みモデルを確認し、"
            "`src/.streamlit/secrets.toml` の LLM_PL_MODEL / LLM_KP_MODEL を合わせてください。"
            " 例: ollama pull qwen2.5:14b"
        )


def _is_retryable_llm_error(exc):
    """接続タイムアウト・レート制限・サーバーエラー等を再試行対象と判定する。"""
    err = str(exc).lower()
    if any(code in str(exc) for code in ("503", "429", "500", "502", "504")):
        return True
    retry_keywords = (
        "timeout",
        "timed out",
        "connection",
        "connect error",
        "connection refused",
        "context length",
        "maximum context",
        "too many tokens",
        "rate limit",
        "server error",
        "overloaded",
        "temporarily unavailable",
        "service unavailable",
        "finish_reason=length",
        "途切れ",
    )
    return any(keyword in err for keyword in retry_keywords)


def _classify_ollama_error(exc):
    text = str(exc).lower()
    if _is_model_not_found_error(exc):
        return "REMOTE_MODEL_UNAVAILABLE"
    if "timeout" in text or "timed out" in text:
        return "REMOTE_OLLAMA_TIMEOUT"
    if any(token in text for token in ("connection", "connect error", "connection refused")):
        return "REMOTE_OLLAMA_CONNECTION_ERROR"
    return "LLM_RESPONSE_ERROR"


class RemoteOllamaInfrastructureError(RuntimeError):
    """A formal run must pause instead of silently moving Judge to PRIMARY."""

    def __init__(self, error_class, original):
        super().__init__(f"{error_class}: {original}")
        self.error_class = error_class
        self.original = original


LLM_PAUSE_MODEL_NOT_FOUND = "llm_model_not_found"
LLM_PAUSE_CONNECTION = "llm_connection_error"
LLM_PAUSE_INVALID_RESPONSE = "llm_invalid_response"
LLM_PAUSE_REASONS = frozenset({
    LLM_PAUSE_MODEL_NOT_FOUND,
    LLM_PAUSE_CONNECTION,
    LLM_PAUSE_INVALID_RESPONSE,
    "empty_tick",
})

LLM_PAUSE_REASON_LABELS = {
    LLM_PAUSE_MODEL_NOT_FOUND: "モデル未起動／モデル名不一致",
    LLM_PAUSE_CONNECTION: "通信エラー／タイムアウト",
    LLM_PAUSE_INVALID_RESPONSE: "不正な LLM 応答",
    "empty_tick": "ログ未更新（応答待ち／空振り）",
}

# 一時停止の性質クラス（UI／再開ロジック用。reason とは別軸）
PAUSE_CLASS_SAFE_RESUME = "safe_resume"          # 処理済みで安全に再開可能
PAUSE_CLASS_REEXEC_FORBIDDEN = "reexec_forbidden"  # 処理途中・同一txn再実行禁止
PAUSE_CLASS_RETRYABLE = "retryable"              # LLM失敗など再試行可能

PAUSE_CLASS_LABELS = {
    PAUSE_CLASS_SAFE_RESUME: "処理済み（安全に再開可能）",
    PAUSE_CLASS_REEXEC_FORBIDDEN: "処理途中（再実行禁止）",
    PAUSE_CLASS_RETRYABLE: "通信失敗（再試行可能）",
}

# reason → 既定クラス（状態から上書きすることもある）
PAUSE_REASON_TO_CLASS = {
    "loaded_while_running": PAUSE_CLASS_SAFE_RESUME,
    "safe_resume_ready": PAUSE_CLASS_SAFE_RESUME,
    "user_stop": PAUSE_CLASS_SAFE_RESUME,
    "max_iterations": PAUSE_CLASS_SAFE_RESUME,
    "awaiting_system_process": PAUSE_CLASS_REEXEC_FORBIDDEN,
    LLM_PAUSE_MODEL_NOT_FOUND: PAUSE_CLASS_RETRYABLE,
    LLM_PAUSE_CONNECTION: PAUSE_CLASS_RETRYABLE,
    LLM_PAUSE_INVALID_RESPONSE: PAUSE_CLASS_RETRYABLE,
    "empty_tick": PAUSE_CLASS_RETRYABLE,
}


def classify_autonomous_pause(pause_reason=None, state=None) -> str:
    """
    pause_reason / ランタイム状態から再開クラスを返す。

    - safe_resume: 処理済み。次ターンから普通に再開してよい
    - reexec_forbidden: 半端なシステム処理待ち。同一アクションの再実行は禁止
    - retryable: LLM失敗等。同じ意図の再試行は許可
    """
    reason = str(pause_reason or (state or {}).get("autonomous_pause_reason") or "").strip()
    if reason in PAUSE_REASON_TO_CLASS:
        return PAUSE_REASON_TO_CLASS[reason]
    if reason in LLM_PAUSE_REASONS:
        return PAUSE_CLASS_RETRYABLE

    state = state or {}
    pending = str(state.get("pending_action_id") or "").strip()
    last = str(state.get("last_processed_action_id") or "").strip()
    last_action = state.get("last_pl_action") or {}
    pending_kind = str((last_action or {}).get("action") or "").lower()
    needing = globals().get("ACTIONS_NEEDING_SYSTEM") or frozenset({
        "search", "inspect", "move", "talk", "push", "break", "climb", "use",
        "persuade", "negotiate", "fast_talk", "intimidate", "charm", "psychology",
    })
    has_half_turn = bool(
        pending_kind in needing
        and not state.get("last_system_result")
    )
    if has_half_turn or (pending and last and pending != last):
        return PAUSE_CLASS_REEXEC_FORBIDDEN
    if pending and last and pending == last:
        return PAUSE_CLASS_SAFE_RESUME
    if not reason:
        return PAUSE_CLASS_SAFE_RESUME
    return PAUSE_CLASS_SAFE_RESUME


def sync_autonomous_pause_class(state) -> str:
    """state['autonomous_pause_class'] を reason/状態から同期して返す。"""
    if not isinstance(state, dict):
        return PAUSE_CLASS_SAFE_RESUME
    if not state.get("autonomous_paused"):
        state["autonomous_pause_class"] = None
        return ""
    pause_class = classify_autonomous_pause(
        state.get("autonomous_pause_reason"), state=state,
    )
    state["autonomous_pause_class"] = pause_class
    return pause_class


def is_pause_safe_to_resume(state) -> bool:
    """手動／自動の再開操作が安全か（処理途中の再実行禁止を除く）。"""
    if not isinstance(state, dict):
        return False
    if not state.get("autonomous_paused"):
        return True
    pause_class = state.get("autonomous_pause_class") or classify_autonomous_pause(
        state.get("autonomous_pause_reason"), state=state,
    )
    return pause_class in (PAUSE_CLASS_SAFE_RESUME, PAUSE_CLASS_RETRYABLE)


class LlmCommunicationError(RuntimeError):
    """LLM 通信の最終失敗。自律巡航を安全停止するための構造化例外。"""

    def __init__(self, category, message="", *, attempts=0, cause=None):
        self.category = category or LLM_PAUSE_CONNECTION
        self.attempts = int(attempts or 0)
        self.cause = cause
        detail = message or (str(cause) if cause else "")
        super().__init__(detail or self.category)

    def to_meta(self):
        return {
            "category": self.category,
            "message": str(self),
            "attempts": self.attempts,
        }


def classify_llm_failure(exc) -> str:
    """モデル未起動・通信失敗・不正応答を区別する。"""
    if exc is None:
        return LLM_PAUSE_CONNECTION
    if _is_model_not_found_error(exc):
        return LLM_PAUSE_MODEL_NOT_FOUND
    text = str(exc)
    lower = text.lower()
    if isinstance(exc, (json.JSONDecodeError, ValueError)):
        return LLM_PAUSE_INVALID_RESPONSE
    invalid_markers = (
        "json",
        "empty",
        "空の応答",
        "途切れ",
        "finish_reason=length",
        "invalid",
        "parse",
        "解釈できません",
    )
    if any(marker in lower or marker in text for marker in invalid_markers):
        if not _is_retryable_llm_error(exc) or "json" in lower or "空の応答" in text:
            return LLM_PAUSE_INVALID_RESPONSE
    if _is_retryable_llm_error(exc):
        return LLM_PAUSE_CONNECTION
    return LLM_PAUSE_CONNECTION


def build_llm_failure_pause_log(failure_info):
    """LLM 失敗時の一時停止ログ本文とメタを組み立てる。"""
    info = failure_info if isinstance(failure_info, dict) else {}
    if isinstance(failure_info, LlmCommunicationError):
        info = failure_info.to_meta()
    category = str(info.get("category") or LLM_PAUSE_CONNECTION)
    attempts = int(info.get("attempts") or 0)
    detail = str(info.get("message") or "").strip()
    label = LLM_PAUSE_REASON_LABELS.get(category, category)
    text = (
        f"[システム] LLM通信に失敗したため自律巡航を一時停止しました"
        f"（理由: {label}／再試行 {attempts}回）。"
        "「自律巡航を再開」で再試行できます。"
    )
    if detail:
        text = f"{text} 詳細: {detail[:240]}"
    return text, {
        "autonomous_pause": True,
        "pause_reason": category,
        "pause_class": PAUSE_CLASS_RETRYABLE,
        "llm_failure": True,
        "llm_failure_category": category,
        "llm_retry_attempts": attempts,
    }


def apply_llm_failure_pause(state, failure_info):
    """
    LLM 失敗後の再開可能な一時停止状態を確定する。
    pending/last_processed の整合は触らず、処理済みアクションの再実行を避ける。
    """
    if not isinstance(state, dict):
        return None
    ensure_transaction_state_fields(state)
    text, meta = build_llm_failure_pause_log(failure_info)
    category = meta.get("pause_reason") or LLM_PAUSE_CONNECTION
    logs = state.setdefault("all_events_log", [])
    if not any(
        (e.get("meta") or {}).get("llm_failure")
        and (e.get("meta") or {}).get("pause_reason") == category
        for e in logs[-5:]
    ):
        logs.append({
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": text,
            "meta": meta,
        })
    # 処理済み ID はそのまま維持（重複実行防止）
    pending = str(state.get("pending_action_id") or "").strip()
    last = str(state.get("last_processed_action_id") or "").strip()
    if pending and last and pending != last:
        # 未 Commit の半端は再開時に再試行できるよう pending を残す
        pass
    elif last and not pending:
        state["pending_action_id"] = last
    finalize_autonomous_pause(state, category)
    return category


def extract_llm_failure_from_response(ai_data):
    """PL/KP 応答に埋め込まれた LLM 失敗メタを取り出す。"""
    if not isinstance(ai_data, dict):
        return None
    failure = ai_data.get("_llm_failure")
    return failure if isinstance(failure, dict) else None


def _is_json_format_unsupported(exc):
    """response_format が未対応のローカルサーバーかどうか。"""
    err = str(exc).lower()
    unsupported_keywords = (
        "response_format",
        "json_object",
        "unsupported",
        "not support",
        "unknown parameter",
    )
    return any(keyword in err for keyword in unsupported_keywords)


def _extract_json_object(text):
    """ローカル LLM の余計な前後文から JSON オブジェクトを抽出する。"""
    text = text.strip()
    if text.startswith("```json"):
        text = text[7:].strip()
    elif text.startswith("```"):
        text = text[3:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    if not text.startswith("{"):
        text = "{" + text
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return match.group(0)
    return text


def _loads_json_lenient(text):
    """途中切れ JSON を可能な範囲で修復して dict にする。"""
    raw = _extract_json_object(text)
    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    repaired = raw.rstrip()
    if repaired.endswith(","):
        repaired = repaired[:-1]
    quote_count = repaired.count('"') - repaired.count('\\"')
    if quote_count % 2 == 1:
        repaired += '"'
    repaired += "}" * max(0, repaired.count("{") - repaired.count("}"))
    try:
        data = json.loads(repaired)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return None


def _recover_text_field_from_partial_json(raw):
    """JSON が途切れても `"text"` 値だけ拾う。"""
    m = re.search(r'"text"\s*:\s*"((?:\\.|[^"\\])*)', str(raw or ""), re.DOTALL)
    if not m:
        return ""
    fragment = m.group(1)
    try:
        return json.loads(f'"{fragment}"')
    except json.JSONDecodeError:
        return fragment.replace("\\n", "\n").replace('\\"', '"')


def _finalize_pl_prompt_for_json(prompt, schema_example):
    """ローカル LLM 向け JSON 出力ガードレールをプロンプト末尾に付与する。"""
    return (
        prompt.rstrip()
        + "\n\n【JSON出力の厳守（必須）】\n"
        + "- 前置き・後書き・マークダウン・コードフェンスは一切付けない。\n"
        + "- 応答全体は有効な JSON オブジェクト 1 個のみ。\n"
        + "- 先頭は必ず `{` で始める。\n"
        + f"- スキーマ例（この構造に厳密に従う）:\n{schema_example}\n"
        + "\n{"
    )


PL_ACTION_JSON_SCHEMA = """{
  "thought": "今PLとして喋るべきかPCとして動くべきかの内省",
  "should_speak": true,
  "speak_as": "BOTH",
  "content": {
    "pl_ooc_chat": "PLとしてのメタ発言（心理・作戦・ルール雑談。なければ空文字）",
    "pc_ic_action": {
      "dialogue": "PCとしての純粋なセリフ（心理描写は含めない）",
      "action": "search",
      "target": "desk",
      "skill": "",
      "skill_proposal_reason": "技能を提案する場合だけ、行動との関連を簡潔に説明"
    }
  }
}

※ skill / target はPLの希望・提案です。使用技能・難易度・実行可否の最終決定はシステムが行います。
※ 方針・相談（「〜した方がよさそう」等）は pl_ooc_chat に書き、pc_ic_action は wait にしてください（即時の move/search にしない）。
※ 移動するなら dialogue に『〇〇へ移動する／向かう』など明示し、action=move と一致させてください。
※ push / break / move / climb 時は skill を必ず空文字 "" にすること。
※ search / inspect はまず自然言語で行動を宣言し、skill は原則空文字にする。
※ 技能を提案する場合だけ skill と skill_proposal_reason を両方記入する。最終裁定はKP/システムが行う。"""

PL_LUCK_JSON_SCHEMA = """{
  "thought": "幸運を消費するか温存するかの内省",
  "should_speak": true,
  "speak_as": "PL",
  "content": {
    "pl_ooc_chat": "yes または no（判断理由を添えてもよい）",
    "use_luck": false
  }
}"""

PL_PUSH_JSON_SCHEMA = """{
  "thought": "プッシュロールで再挑戦するか断念するかの内省",
  "should_speak": true,
  "speak_as": "PL",
  "content": {
    "pl_ooc_chat": "yes または no（判断理由を添えてもよい）",
    "use_push": false,
    "push_approach": "プッシュする場合のアプローチ変更（時間をかける、強引に使う等）"
  }
}"""

PL_COMBAT_DEFENSE_JSON_SCHEMA = """{
  "thought": "回避するか応戦するかの判断",
  "should_speak": true,
  "speak_as": "BOTH",
  "content": {
    "pl_ooc_chat": "防衛方針の一言（任意）",
    "defense_mode": "dodge",
    "pc_ic_action": {
      "dialogue": "回避／応戦の短いセリフ（任意）",
      "action": "defend",
      "target": "",
      "skill": ""
    }
  }
}

※ defense_mode は "dodge"（回避）または "fight_back"（応戦）のみ。"""

PL_SHOOT_DEFENSE_JSON_SCHEMA = """{
  "thought": "回避するか甘んじて受けるかの判断",
  "should_speak": true,
  "speak_as": "BOTH",
  "content": {
    "pl_ooc_chat": "防衛方針の一言（任意）",
    "defense_mode": "dodge",
    "pc_ic_action": {
      "dialogue": "回避／甘受の短いセリフ（任意）",
      "action": "defend",
      "target": "",
      "skill": ""
    }
  }
}

※ 銃撃に対する defense_mode は "dodge"（回避）または "accept"（甘んじて受ける）のみ。
※ "fight_back"（応戦）は選択不可。"""

KP_JSON_SCHEMA = """{
  "thought": "システムKPとしてナレーションするかプレイヤーKPとして語りかけるかの内省",
  "should_speak": true,
  "speak_mode": "system_narration",
  "text": "情景描写またはPLへの語りかけ"
}"""

OCCUPATION_RP_JSON_SCHEMA = """{
  "fit": "good",
  "bonus_dice": 1,
  "penalty_dice": 0,
  "skip_roll": false,
  "auto_success_level": 2,
  "reason": "刑事として事件捜査の体で身分を示し、状況に適した聞き込みができている"
}"""


def generate_occupation_rp_judge_prompt(
    *,
    char_mgr,
    pc_id,
    npc_id,
    action_id="",
    skill_name="",
    dialogue_text="",
    current_loc="",
    scenario_mgr=None,
    casual=False,
):
    """職業ロールプレイ適合度をKPに問うプロンプト。"""
    pc = (char_mgr.characters or {}).get(pc_id) or {}
    npc = (char_mgr.characters or {}).get(npc_id) or {}
    pc_profile = pc.get("profile") or {}
    npc_profile = npc.get("profile") or {}
    occupation = str(pc_profile.get("occupation") or "探索者")
    personality = str(pc_profile.get("personality") or "")
    action_guide = str(pc_profile.get("action_guide") or "")
    hooks = pc_profile.get("occupation_hooks") or []
    if isinstance(hooks, list):
        hooks_text = " / ".join(str(h) for h in hooks) if hooks else "（特になし）"
    else:
        hooks_text = str(hooks or "（特になし）")
    pc_name = pc_profile.get("name", pc_id)
    npc_name = npc_profile.get("name", npc_id)
    social_mgr = NPCSocialManager(char_mgr)
    rel = social_mgr.get_relationship(npc_id)
    from NPCSocialManager import RELATIONSHIP_LABELS
    rel_label = RELATIONSHIP_LABELS.get(rel, rel)
    npc_personality = social_mgr.get_personality(npc_id)
    loc_name = current_loc
    if scenario_mgr:
        loc_name = scenario_mgr.get_location_info(current_loc).get("name", current_loc)
    skill = (
        resolve_social_skill_name(action_id, skill_name, npc_id=npc_id, char_mgr=char_mgr)
        if not casual else "（雑談・判定なし）"
    )
    mode = "雑談（talk）" if casual else f"交渉技能〈{skill}〉"

    return f"""あなたはクトゥルフ神話TRPGのKPです。これからダイスを振る前に、
PCの「職業・立場を活かしたロールプレイ」がこの状況でどれだけ適切かを判定してください。
ナレーションは不要です。指定JSONのみ出力してください。

【PC】
- 名前: {pc_name}（`{pc_id}`）
- 職業: {occupation}
- 性格: {personality or '（なし）'}
- 行動指針: {action_guide or '（なし）'}
- 職業フック例: {hooks_text}

【NPC】
- 名前: {npc_name}（`{npc_id}`）
- 現在の態度: {rel_label}
- 性格: {npc_personality or '（なし）'}

【状況】
- 場所: {loc_name}（`{current_loc}`）
- 行動種別: {mode}
- PCのセリフ・趣旨: {dialogue_text or '（セリフなし）'}

【判定基準】
- excellent: 職業・立場が状況に極めて適合（例: 刑事が警察・役所・新聞社で正式に事件捜査として身分を示し協力を求める）。判定省略（skip_roll=true）を検討可。
- good: 職業を意識した適切なRP。ボーナス・ダイス1程度。
- neutral: 普通の会話。修正なし。
- poor: 場にそぐわない・職業を誤用。ペナルティ1。
- terrible: 明らかに場違い・逆効果。ペナルティ2。skip_rollは禁止。

【出力ルール】
- fit は excellent/good/neutral/poor/terrible のいずれか
- bonus_dice / penalty_dice は 0〜2 の整数（両方同時に大きくしない）
- skip_roll は fit=excellent のときのみ true 可。雑談(talk)では常に false
- auto_success_level は skip_roll 時のみ意味を持つ（2=レギュラー, 3=ハード）。上限3
- reason は日本語で簡潔に（ログ表示用）
"""


def call_occupation_rp_judge(prompt, max_retries=2):
    """職業RP適合度のKP判定（構造化JSON）。失敗時は中立。"""
    cfg = get_llm_config()
    finalized_prompt = _finalize_pl_prompt_for_json(prompt, OCCUPATION_RP_JSON_SCHEMA)
    messages = [
        {
            "role": "system",
            "content": (
                "あなたはクトゥルフ神話TRPGのKPです。"
                "職業ロールプレイの適合度だけを判定し、必ず有効な JSON オブジェクトのみを出力してください。"
                "情景描写やダイス結果の捏造はしないでください。"
            ),
        },
        {"role": "user", "content": finalized_prompt},
    ]
    try:
        response_text = _call_chat_completion(
            messages,
            model=cfg.get("judge_model") or cfg["kp_model"],
            temperature=0.3,
            max_retries=max_retries,
            json_mode=True,
            role="JUDGE",
            purpose="occupation_roleplay_judgment",
        )
        raw = json.loads(_extract_json_object(response_text))
        return normalize_occupation_rp_judgment(raw)
    except RemoteOllamaInfrastructureError:
        raise
    except Exception as exc:
        print(f"\n[職業RP判定] フォールバック（中立）: {exc}")
        return default_occupation_rp_judgment()


def judge_occupation_roleplay(
    *,
    char_mgr,
    pc_id,
    npc_id,
    action_id="",
    skill_name="",
    dialogue_text="",
    current_loc="",
    scenario_mgr=None,
    casual=False,
):
    """社交アクション前の職業RP判定を実行して正規化結果を返す。"""
    if not char_mgr or not pc_id or not npc_id:
        return default_occupation_rp_judgment()
    profile = (char_mgr.get_pc(pc_id) or {}).get("profile") or {}
    if detect_pl_identity_violation(
        dialogue_text, self_pc_id=pc_id, self_name=profile.get("name", ""),
        self_occupation=profile.get("occupation", ""),
        other_profiles=collect_pc_identity_profiles(char_mgr),
    ):
        result = default_occupation_rp_judgment()
        result["reason"] = "発言の身分がPC設定と一致しないため職業ボーナスを適用しない。"
        return result
    prompt = generate_occupation_rp_judge_prompt(
        char_mgr=char_mgr,
        pc_id=pc_id,
        npc_id=npc_id,
        action_id=action_id,
        skill_name=skill_name,
        dialogue_text=dialogue_text,
        current_loc=current_loc,
        scenario_mgr=scenario_mgr,
        casual=casual,
    )
    result = call_occupation_rp_judge(prompt)
    if casual:
        # 雑談では判定省略しない
        result["skip_roll"] = False
    return result


def _normalize_speak_as(value):
    allowed = {"PL", "PC", "BOTH"}
    upper = str(value or "PC").upper()
    return upper if upper in allowed else "PC"


def _normalize_speak_mode(value):
    allowed = {"system_narration", "player_kp_chat"}
    lower = str(value or "system_narration").lower()
    return lower if lower in allowed else "system_narration"


def _is_san_check_pending(pending_san_check):
    """SANチェックが未解決で保留中かどうか。"""
    if not pending_san_check:
        return False
    required = pending_san_check.get("required")
    return required is True or str(required).lower() == "true"


def _coalesce_pending_push_roll(pending_push_roll, san_check=None):
    """SANチェックが発生・保留中のときはプッシュロールを破棄する。"""
    if _is_san_check_pending(san_check):
        return None
    return pending_push_roll


# タイムライン保留フェーズ（優先順位は get_timeline_pending_phase 参照）
PENDING_SAN_CHECK = "PENDING_SAN_CHECK"
PENDING_COMBAT_DEFENSE = "PENDING_COMBAT_DEFENSE"
PENDING_SHOOT_DEFENSE = "PENDING_SHOOT_DEFENSE"
PENDING_PL_DISCUSSION = "PENDING_PL_DISCUSSION"
PENDING_LUCK_CONSUMPTION = "PENDING_LUCK_CONSUMPTION"
PENDING_PUSH_DECISION = "PENDING_PUSH_DECISION"

# プッシュ不可（戦闘・正気度・属性ロール等）
UNPUSHABLE_SKILLS = frozenset({
    "正気度", "SAN", "幸運", "LUCK", "LUK",
    "格闘", "近接戦闘", "射撃", "火器", "回避", "投擲",
})
COMBAT_SKILL_KEYWORDS = ("戦闘", "射撃", "火器", "格闘", "回避", "刀剣", "拳銃", "ライフル", "ショットガン")
FIREARM_SKILL_KEYWORDS = ("射撃", "火器", "拳銃", "ライフル", "ショットガン", "firearm", "handgun", "rifle")
SHOOT_ACTION_IDS = frozenset({"shoot", "fire", "gunshot", "射撃"})


def _normalize_defense_mode(value):
    raw = str(value or "dodge").strip().lower()
    if raw in ("fight_back", "fighting_back", "応戦", "fightback", "counter", "反撃"):
        return "fight_back"
    return "dodge"


def _normalize_shoot_defense_mode(value):
    """
    射撃防衛モードを正規化する。
    Returns: ("dodge"|"accept"|None, rejected_fight_back: bool)
    fight_back は選択不可のため (None, True) を返す。
    """
    raw = str(value or "dodge").strip().lower()
    if raw in ("fight_back", "fighting_back", "応戦", "fightback", "counter", "反撃"):
        return None, True
    if raw in (
        "accept", "take", "take_it", "none", "no_dodge",
        "甘受", "甘んじて", "甘んじて受ける", "受け入れる", "受け止める",
    ):
        return "accept", False
    return "dodge", False


def validate_shoot_defense_mode(value):
    """
    射撃防衛モードのガード。
    Returns: (ok: bool, mode: str|None, error: str)
    """
    mode, rejected = _normalize_shoot_defense_mode(value)
    if rejected:
        return False, None, "銃撃に対して【応戦】は選択できません。【回避】か【甘んじて受ける】を選んでください。"
    return True, mode, ""


def _pending_is_shoot_defense(pending):
    if not pending:
        return False
    attack_type = str(pending.get("attack_type") or "").lower()
    return attack_type in ("shoot", "firearm", "ranged", "gun") or bool(pending.get("is_ranged"))


def build_pending_decision(
    *,
    decision_type,
    target_action_id="",
    decision_owner_id="",
    legal_options=None,
    luck_cost=None,
    meta=None,
):
    """タスク4: 判定失敗／防衛などの選択肢状態を組み立てる。"""
    options = [str(opt) for opt in (legal_options or []) if opt]
    if not options:
        options = [DECISION_OPTION_ACCEPT]
    payload = {
        "type": str(decision_type or PENDING_DECISION_POST_ROLL_FAILURE),
        "target_action_id": str(target_action_id or ""),
        "decision_owner_id": str(decision_owner_id or ""),
        "legal_options": options,
        "luck_cost": int(luck_cost) if luck_cost is not None else None,
    }
    if meta:
        payload["meta"] = dict(meta)
    return payload


def clear_pending_decision(state):
    """pending_decision をクリアする。"""
    if isinstance(state, dict):
        state["pending_decision"] = None
    return state


def ensure_pending_decision_field(state):
    """game_state に pending_decision キーを保証する。"""
    if not isinstance(state, dict):
        return state
    if "pending_decision" not in state:
        state["pending_decision"] = None
    return state


def build_post_roll_pending_decision(
    *,
    target_action_id="",
    decision_owner_id="",
    skill_name="",
    action_id="",
    roll_type="skill",
    in_combat=False,
    already_pushed=False,
    is_fumble=False,
    margin=0,
    current_luck=0,
    allow_push=True,
    legal_options=None,
    luck_cost=None,
):
    """失敗後の POST_ROLL_FAILURE pending_decision を構築する。"""
    if legal_options is None:
        info = build_post_roll_failure_legal_options(
            skill_name=skill_name,
            action_id=action_id,
            roll_type=roll_type,
            in_combat=in_combat,
            already_pushed=already_pushed,
            is_fumble=is_fumble,
            margin=margin,
            current_luck=current_luck,
            max_burn=DEFAULT_LUCK_BURN_MAX,
            allow_push=allow_push,
        )
        legal_options = info.get("legal_options") or [DECISION_OPTION_ACCEPT]
        luck_cost = info.get("luck_cost")
    return build_pending_decision(
        decision_type=PENDING_DECISION_POST_ROLL_FAILURE,
        target_action_id=target_action_id or action_id,
        decision_owner_id=decision_owner_id,
        legal_options=legal_options,
        luck_cost=luck_cost,
        meta={"skill_name": skill_name, "roll_type": roll_type},
    )


def build_combat_pending_decision(pending_combat, *, decision_owner_id=""):
    """戦闘／射撃防衛の pending_decision を構築する。"""
    pending = pending_combat or {}
    is_shoot = _pending_is_shoot_defense(pending)
    legal = build_combat_defense_legal_options(is_shoot=is_shoot)
    # 既存 UI／解決ロジックは accept、CoCRules は accept_hit
    mapped = []
    for opt in legal:
        if opt == "accept_hit":
            mapped.append("accept")
        else:
            mapped.append(opt)
    return build_pending_decision(
        decision_type=(
            PENDING_DECISION_SHOOT_DEFENSE if is_shoot else PENDING_DECISION_COMBAT_DEFENSE
        ),
        target_action_id="defend",
        decision_owner_id=decision_owner_id or pending.get("defender_id") or "",
        legal_options=mapped,
        luck_cost=None,
        meta={
            "attacker_id": pending.get("attacker_id"),
            "defender_id": pending.get("defender_id"),
            "attack_type": pending.get("attack_type"),
        },
    )


def sync_pending_decision_from_legacy(state):
    """
    既存の pending_luck_burn / pending_push_roll / pending_combat_defense から
    pending_decision を同期する（セーブ互換・再入時の整合用）。
    """
    if not isinstance(state, dict):
        return None
    ensure_pending_decision_field(state)

    pending_combat = state.get("pending_combat_defense")
    if pending_combat:
        owner = (
            state.get("decision_owner_id")
            or pending_combat.get("defender_id")
            or state.get("pl_id")
            or ""
        )
        state["pending_decision"] = build_combat_pending_decision(
            pending_combat, decision_owner_id=owner,
        )
        return state["pending_decision"]

    pending_luck = state.get("pending_luck_burn")
    if pending_luck:
        options = list(pending_luck.get("legal_options") or [])
        if not options:
            options = [DECISION_OPTION_ACCEPT, DECISION_OPTION_SPEND_LUCK]
            if pending_luck.get("allow_push", True):
                options.append(DECISION_OPTION_PUSH)
        state["pending_decision"] = build_pending_decision(
            decision_type=PENDING_DECISION_POST_ROLL_FAILURE,
            target_action_id=pending_luck.get("original_action") or "",
            decision_owner_id=state.get("decision_owner_id") or state.get("actor_id") or state.get("pl_id") or "",
            legal_options=options,
            luck_cost=pending_luck.get("margin") if DECISION_OPTION_SPEND_LUCK in options else None,
            meta={"skill_name": pending_luck.get("skill_name"), "source": "pending_luck_burn"},
        )
        return state["pending_decision"]

    pending_push = state.get("pending_push_roll")
    if pending_push and (
        pending_push.get("decision_pending", True) or state.get("push_decision_required")
    ):
        options = list(pending_push.get("legal_options") or [DECISION_OPTION_ACCEPT, DECISION_OPTION_PUSH])
        state["pending_decision"] = build_pending_decision(
            decision_type=PENDING_DECISION_POST_ROLL_FAILURE,
            target_action_id=pending_push.get("original_action") or "",
            decision_owner_id=state.get("decision_owner_id") or state.get("actor_id") or state.get("pl_id") or "",
            legal_options=options,
            luck_cost=None,
            meta={"skill_name": pending_push.get("skill_name"), "source": "pending_push_roll"},
        )
        return state["pending_decision"]

    # 対応する legacy が無い場合はクリア（残留を防ぐ）
    if state.get("pending_decision"):
        state["pending_decision"] = None
    return None


def _phase_from_pending_decision(state, pending_decision):
    """pending_decision からタイムライン・フェーズを導出する。"""
    if not pending_decision:
        return None
    dtype = str(pending_decision.get("type") or "")
    if dtype == PENDING_DECISION_SHOOT_DEFENSE:
        return PENDING_SHOOT_DEFENSE
    if dtype == PENDING_DECISION_COMBAT_DEFENSE:
        return PENDING_COMBAT_DEFENSE

    options = set(pending_decision.get("legal_options") or [])
    # 幸運が残っていれば最優先（既存フロー互換: luck → push）
    if DECISION_OPTION_SPEND_LUCK in options and state.get("pending_luck_burn"):
        return PENDING_LUCK_CONSUMPTION
    if DECISION_OPTION_PUSH in options and (
        state.get("pending_push_roll") or state.get("push_decision_required")
    ):
        return PENDING_PUSH_DECISION
    if DECISION_OPTION_SPEND_LUCK in options:
        return PENDING_LUCK_CONSUMPTION
    if DECISION_OPTION_PUSH in options:
        return PENDING_PUSH_DECISION
    return None


def get_timeline_pending_phase(state):
    """
    保留中システム処理の優先フェーズを返す。
    優先順位: SAN → pending_decision → 近接／射撃防衛 → 幸運消費 → プッシュ決定 → PL相談
    """
    if _is_san_check_pending((state or {}).get("pending_san_check")):
        return PENDING_SAN_CHECK

    sync_pending_decision_from_legacy(state)
    pending_decision = (state or {}).get("pending_decision")
    if pending_decision:
        phase = _phase_from_pending_decision(state, pending_decision)
        if phase:
            return phase

    pending_combat = (state or {}).get("pending_combat_defense")
    if pending_combat:
        if _pending_is_shoot_defense(pending_combat):
            return PENDING_SHOOT_DEFENSE
        return PENDING_COMBAT_DEFENSE
    if (state or {}).get("pending_luck_burn"):
        return PENDING_LUCK_CONSUMPTION
    pending_push = (state or {}).get("pending_push_roll")
    if pending_push and (
        pending_push.get("decision_pending", True)
        or state.get("push_decision_required")
    ):
        return PENDING_PUSH_DECISION
    if (state or {}).get("pl_discussion_mode"):
        return PENDING_PL_DISCUSSION
    return None


# ==========================================
# マルチPL: 手番・アイデンティティ管理
# ==========================================
def default_active_pc_ids(char_mgr):
    """デフォルト参加 PC（pc_01/pc_02 があれば優先、なければ全 PC）。"""
    if not char_mgr:
        return []
    preferred = [pid for pid in ("pc_01", "pc_02") if char_mgr.get_pc(pid)]
    if preferred:
        return preferred
    all_pcs = char_mgr.list_pc_ids()
    return all_pcs[:2] if len(all_pcs) >= 2 else all_pcs[:1]


def ensure_multi_pl_state(state, char_mgr=None):
    """active_pcs / active_pc_id / pl_id / char_name を整合させる。"""
    if not state:
        return state
    if char_mgr:
        active = state.get("active_pcs") or char_mgr.active_pc_list
        if not active:
            active = default_active_pc_ids(char_mgr)
        valid = [pid for pid in active if char_mgr.get_pc(pid)]
        if not valid:
            valid = default_active_pc_ids(char_mgr)
        state["active_pcs"] = valid
        char_mgr.set_active_pcs(valid)
    active = state.get("active_pcs") or []
    if not active:
        return state
    current = state.get("active_pc_id") or state.get("pl_id")
    if current not in active:
        current = active[0]
    sync_pl_identity(state, char_mgr, current)
    return state


def sync_pl_identity(state, char_mgr, pc_id):
    """現在のアクティブ PC を state に反映する。"""
    if not state or not pc_id:
        return
    state["active_pc_id"] = pc_id
    state["pl_id"] = pc_id
    if char_mgr:
        state["char_name"] = char_mgr.get_pc_name(pc_id, default=str(pc_id))
    else:
        state["char_name"] = state.get("char_name") or str(pc_id)
    # 手番PCを行動主体に同期。防衛保留中は decision_owner を維持する。
    state["actor_id"] = pc_id
    if not state.get("pending_combat_defense"):
        state["decision_owner_id"] = pc_id
    elif not state.get("decision_owner_id"):
        state["decision_owner_id"] = pc_id


# --- タスク2: 行動トランザクション / 冪等性 ---

TRANSACTION_STATE_KEYS = (
    "pending_action_id",
    "last_processed_action_id",
    "actor_id",
    "decision_owner_id",
)


def new_action_transaction_id():
    """PL行動1件を一意に識別するトランザクションIDを発行する。"""
    return str(uuid.uuid4())


def ensure_lifecycle_relation_id(result, *, transaction_id="", actor_id=""):
    """Freeze producer-owned relation and actor identities for a location change."""
    if not isinstance(result, dict):
        return result
    if not (result.get("location_changed") or result.get("new_location")):
        return result
    resolved_actor = str(
        result.get("lifecycle_actor_id") or actor_id or result.get("actor_id") or ""
    ).strip()
    if not resolved_actor:
        raise ValueError("location change requires producer-owned lifecycle_actor_id")
    existing_actor = str(result.get("lifecycle_actor_id") or "").strip()
    if existing_actor and actor_id and existing_actor != str(actor_id).strip():
        raise ValueError("lifecycle actor identity changed after resolution")
    result["lifecycle_actor_id"] = resolved_actor

    existing = str(result.get("lifecycle_relation_id") or "").strip()
    if not existing:
        tid = str(transaction_id or result.get("transaction_id") or "").strip()
        result["lifecycle_relation_id"] = (
            f"lifecycle_tx_{tid}" if tid else f"lifecycle_{uuid.uuid4().hex}"
        )
    return result


def ensure_settled_nonprogress_event_id(pc_action, *, event_kind=""):
    """
    OOC / 検証拒否など「SYSTEMに行かない確定イベント」へ一意IDを付与する。

    - 新規にイベントを確定・記録する時点でのみ発行する
    - 既に transaction_id があれば保持（再評価・再読込で増やさない）
    - 停滞評価の呼び出し側では発行しないこと
    """
    if not isinstance(pc_action, dict):
        return ""
    tid = str(pc_action.get("transaction_id") or "").strip()
    if not tid:
        tid = new_action_transaction_id()
        pc_action["transaction_id"] = tid
    if event_kind and not pc_action.get("settled_event_kind"):
        pc_action["settled_event_kind"] = str(event_kind)
    return tid


def resolve_stagnation_transaction_id(result=None, pl_action=None, state=None):
    """
    停滞計上用のトランザクションIDを解決する。

    プッシュ／幸運判断など子結果が別IDでも、親行動の ID
    （stagnation_transaction_id / parent_transaction_id）を優先し、
    親＋プッシュを一連の1回として扱う。
    """
    # PL 手番の評価では、その手番自身の ID だけを使う。ID が無いまま
    # 古い pending を拾うと、別の相談・拒否を同一イベントと誤認する。
    sources = (result, pl_action) if isinstance(pl_action, dict) else (result, state)
    for source in sources:
        if not isinstance(source, dict):
            continue
        for key in (
            "stagnation_transaction_id",
            "parent_transaction_id",
            "transaction_id",
            "pending_action_id",
            "last_processed_action_id",
        ):
            tid = str(source.get(key) or "").strip()
            if tid:
                return tid
    return ""


def bind_push_family_transaction_ids(result, pending=None, *, parent_transaction_id="", child_transaction_id=""):
    """
    プッシュ確定結果に親／子IDを付与する。
    - transaction_id: 子（プッシュ結果固有、無ければ親）
    - parent_transaction_id / stagnation_transaction_id: 親（停滞はこちらで1回計上）
    """
    result = dict(result or {})
    pending = pending or {}
    parent_tid = str(
        parent_transaction_id
        or pending.get("parent_transaction_id")
        or pending.get("transaction_id")
        or result.get("parent_transaction_id")
        or ""
    ).strip()
    child_tid = str(
        child_transaction_id
        or result.get("transaction_id")
        or ""
    ).strip()
    if not child_tid:
        child_tid = new_action_transaction_id() if parent_tid else ""
    if parent_tid:
        result["parent_transaction_id"] = parent_tid
        result["stagnation_transaction_id"] = parent_tid
        result["transaction_id"] = child_tid or parent_tid
    elif child_tid:
        result["transaction_id"] = child_tid
        result["stagnation_transaction_id"] = child_tid
    return result


def stamp_event_transaction_on_log_meta(meta, transaction_id, *, event_kind="", pc_id=None):
    """ログ meta に確定イベントの transaction_id を書き込む。"""
    meta = dict(meta or {})
    tid = str(transaction_id or "").strip()
    if tid:
        meta["transaction_id"] = tid
    if event_kind:
        meta["settled_event_kind"] = str(event_kind)
    if pc_id is not None and "pc_id" not in meta:
        meta["pc_id"] = pc_id
    return meta


def ensure_transaction_state_fields(state):
    """冪等性・主体管理キーを初期化する（既存値は保持）。"""
    if not isinstance(state, dict):
        return state
    ensure_pending_decision_field(state)
    ensure_public_knowledge_field(state)
    state.setdefault("pending_action_id", None)
    state.setdefault("last_processed_action_id", None)
    default_actor = state.get("active_pc_id") or state.get("pl_id") or None
    if "actor_id" not in state or state.get("actor_id") in (None, ""):
        state["actor_id"] = default_actor
    if "decision_owner_id" not in state or state.get("decision_owner_id") in (None, ""):
        state["decision_owner_id"] = state.get("actor_id") or default_actor
    return state


def bind_action_transaction(state, *, transaction_id, actor_id=None, decision_owner_id=None):
    """処理中トランザクションと行動/意思決定主体を state に紐づける。"""
    ensure_transaction_state_fields(state)
    tid = str(transaction_id or "").strip() or new_action_transaction_id()
    actor = actor_id or state.get("actor_id") or state.get("active_pc_id") or state.get("pl_id")
    owner = decision_owner_id or actor
    state["pending_action_id"] = tid
    state["actor_id"] = actor
    state["decision_owner_id"] = owner
    return tid


def commit_action_transaction(state, transaction_id=None):
    """判定 Commit 時に last_processed_action_id をアトミック更新する。"""
    ensure_transaction_state_fields(state)
    tid = str(transaction_id or state.get("pending_action_id") or "").strip()
    if not tid:
        return None
    state["last_processed_action_id"] = tid
    state["pending_action_id"] = tid
    return tid


def _extract_transaction_id_from_sources(*sources):
    for source in sources:
        if not isinstance(source, dict):
            continue
        tid = source.get("transaction_id") or source.get("pending_action_id")
        if tid:
            return str(tid).strip()
    return ""


def resolve_action_transaction_context(state, action_data=None, entry=None, *, default_actor=None):
    """
    タイムライン entry / action_data / state から transaction_id と主体を解決する。
    IDが無ければ新規発行し、entry.meta と action_data へ書き戻す。
    """
    ensure_transaction_state_fields(state)
    action_data = action_data if isinstance(action_data, dict) else {}
    meta = dict((entry or {}).get("meta") or {}) if entry else {}

    tid = _extract_transaction_id_from_sources(meta, action_data, state)
    if not tid:
        tid = new_action_transaction_id()

    actor = (
        meta.get("actor_id")
        or action_data.get("actor_id")
        or meta.get("pc_id")
        or default_actor
        or state.get("actor_id")
        or state.get("active_pc_id")
        or state.get("pl_id")
    )
    owner = (
        meta.get("decision_owner_id")
        or action_data.get("decision_owner_id")
        or state.get("decision_owner_id")
        or actor
    )

    action_data["transaction_id"] = tid
    action_data["actor_id"] = actor
    action_data["decision_owner_id"] = owner
    if entry is not None:
        meta["transaction_id"] = tid
        meta["actor_id"] = actor
        meta["decision_owner_id"] = owner
        entry["meta"] = meta

    bind_action_transaction(
        state, transaction_id=tid, actor_id=actor, decision_owner_id=owner,
    )
    return tid, actor, owner


def is_duplicate_action_transaction(state, transaction_id, entry=None):
    """同一 transaction_id が既に Commit 済み、または entry が処理済みなら True。"""
    tid = str(transaction_id or "").strip()
    if tid and tid == str(state.get("last_processed_action_id") or "").strip():
        return True
    if entry is not None:
        meta = entry.get("meta") or {}
        if meta.get("system_processed") and tid:
            # 処理済み entry の再投入
            if tid == str(meta.get("transaction_id") or "").strip():
                return True
            if tid == str(state.get("last_processed_action_id") or "").strip():
                return True
    return False


def build_idempotent_system_result(state, *, transaction_id=""):
    """二重実行時に返す既存確定結果（ダイス再振なし）。"""
    existing = dict(state.get("last_system_result") or {})
    existing["idempotent_replay"] = True
    existing["transaction_id"] = transaction_id or state.get("last_processed_action_id")
    if not existing.get("log"):
        existing["log"] = "[システム] 同一行動は既に判定確定済みです（冪等スキップ）。"
    existing.setdefault("san_check", {"required": False})
    existing.setdefault("blocked", False)
    return existing


def get_capable_active_pcs(state, char_mgr, state_mgr=None):
    """行動可能な参加 PC の一覧（意識不明・死亡を除外）。"""
    ensure_multi_pl_state(state, char_mgr)
    capable = []
    for pc_id in state.get("active_pcs") or []:
        if char_mgr and char_mgr.is_pc_incapacitated(pc_id, state_mgr):
            continue
        capable.append(pc_id)
    return capable


def determine_next_active_pc(state, char_mgr, state_mgr=None, *, advance=False):
    """ラウンドロビンで次の探索手番 PC を決定する。"""
    capable = get_capable_active_pcs(state, char_mgr, state_mgr)
    if not capable:
        return None
    current = state.get("active_pc_id") or state.get("pl_id")
    if not advance:
        if current in capable:
            return current
        return capable[0]
    if current in capable:
        idx = capable.index(current)
        return capable[(idx + 1) % len(capable)]
    return capable[0]


def advance_exploration_turn(state, char_mgr, state_mgr=None):
    """探索時: 次 PC へ手番を移す。"""
    if state_mgr and state_mgr.in_combat:
        return state.get("active_pc_id")
    next_pc = determine_next_active_pc(state, char_mgr, state_mgr, advance=True)
    if next_pc:
        sync_pl_identity(state, char_mgr, next_pc)
    return next_pc


def reconcile_post_combat_timeline(state, state_mgr, scenario_mgr, char_mgr=None):
    """Finish a resolved combat and hand control back to normal progression once."""
    if not state_mgr:
        return False

    # Team-aware termination is essential for multi-PC combat.  Counting all
    # living participants leaves combat ACTIVE when the enemy side is empty.
    if combat_is_active(state_mgr):
        end = evaluate_combat_end(
            state_mgr, active_pc_ids=list(state.get("active_pcs") or []),
        )
        if end.get("ended"):
            combat_id = str(getattr(state_mgr, "combat_id", "") or "")
            already_ending = any(
                row.get("event_type") == "COMBAT_ENDING"
                and str(row.get("combat_id") or "") == combat_id
                for row in state.get("unified_event_log") or []
            )
            if not already_ending:
                append_combat_event(
                    state, "COMBAT_ENDING", state_mgr=state_mgr,
                    combat_end_condition=end.get("reason") or "resolved",
                    position_before=state.get("current_loc") or "",
                    position_after=state.get("current_loc") or "",
                )
            state_mgr.end_combat(end.get("reason") or "resolved")
            already_ended = any(
                row.get("event_type") == "COMBAT_ENDED"
                and str(row.get("combat_id") or "") == combat_id
                for row in state.get("unified_event_log") or []
            )
            if not already_ended:
                append_combat_event(
                    state, "COMBAT_ENDED", state_mgr=state_mgr,
                    combat_id=combat_id,
                    combat_end_condition=end.get("reason") or "resolved",
                    position_before=state.get("current_loc") or "",
                    position_after=state.get("current_loc") or "",
                    effect="normal progression handoff required",
                )

    if state_mgr.in_combat or str(state_mgr.combat_state or "").upper() not in {"ENDING", "ENDED"}:
        return False

    # Resolve the floating dagger's physical lifecycle when its combat ends.
    # Possession is never inferred merely from having encountered it.
    if scenario_mgr and scenario_mgr.flags.get("knife_encountered"):
        dagger = (getattr(char_mgr, "characters", {}) or {}).get("corbitt_floating_dagger") or {}
        hp = ((dagger.get("stats") or {}).get("HP") or {}) if isinstance(dagger, dict) else {}
        current_hp = hp.get("current") if isinstance(hp, dict) else None
        if current_hp is None or int(current_hp or 0) <= 0:
            states = scenario_mgr.flags.setdefault("object_states", {})
            apply_object_transition(states, "corbitt_knife", {
                "object_id": "corbitt_knife", "exists": True,
                "status": "ON_FLOOR", "owner_id": None,
                "location_id": "corbitt_basement", "available": True, "destroyed": False,
            })
            scenario_mgr.flags["trigger_knife_attack"] = False
            scenario_mgr.flags["has_corbitt_knife"] = False

    combat_id = str(state_mgr.combat_id or state_mgr.last_combat_id or "")
    recovered = state.setdefault("post_combat_recovered_ids", [])
    if combat_id and combat_id in recovered:
        state_mgr.finalize_combat_exit()
        return False

    session_turn_before = int(state_mgr.turn_count or 0)
    state["pending_combat_defense"] = None
    state_mgr.clear_pending_combat_defense()
    state["combat_action_queue"] = []
    state["pending_combat_action"] = None
    state["pending_combat_reaction"] = None
    state["pending_combat_damage"] = None
    state["pending_combat_narration"] = None
    state["combat_continuation"] = False
    state["pending_combat_escape"] = None
    state["pending_combat_target"] = None
    pending_decision = state.get("pending_decision") or {}
    pending_type = str(pending_decision.get("decision_type") or "").upper()
    target_action = str(pending_decision.get("target_action_id") or "").lower()
    if "COMBAT" in pending_type or target_action in {"attack", "shoot", "fire", "gunshot", "defend"}:
        clear_pending_decision(state)
    state["timeline_pending"] = None
    if state.get("pending_action_id") == state.get("last_processed_action_id"):
        state["pending_action_id"] = None

    canonical_location = str(
        state.get("current_loc") or getattr(scenario_mgr, "location", "")
        or state_mgr.combat_location_id or ""
    )
    reconcile_location(state, scenario_mgr, canonical=canonical_location, log=True)

    next_actor = determine_next_active_pc(state, char_mgr, state_mgr, advance=False)
    if next_actor and char_mgr:
        sync_pl_identity(state, char_mgr, next_actor)
    runtime = ensure_director_state(state, scenario_mgr, char_mgr)
    goal = runtime.get("goal") or {}
    next_phase = str(runtime.get("action_phase") or "DECIDE")
    scene = str(getattr(state_mgr, "current_scene_id", "") or "")

    issues = []
    if state.get("pending_combat_defense") or state_mgr.get_pending_combat_defense():
        issues.append("pending_combat_defense")
    if state_mgr.get_combat_turn_queue():
        issues.append("combat_queue")
    if not next_actor:
        issues.append("active_actor")
    if not canonical_location or str(getattr(scenario_mgr, "location", "") or "") != canonical_location:
        issues.append("location")
    if issues:
        failed = state.setdefault("post_combat_recovery_failed_ids", [])
        if combat_id not in failed:
            append_combat_event(
                state, "POST_COMBAT_RECOVERY_FAILURE", state_mgr=state_mgr,
                combat_id=combat_id,
                action_phase=next_phase,
                session_turn=session_turn_before,
                active_actor=next_actor or "",
                pending_action=state.get("pending_action_id"),
                pending_queue_count=len(state_mgr.get_combat_turn_queue()),
                scene=scene, location=canonical_location,
                current_goal=goal.get("current_goal") or "",
                effect={"issues": issues},
            )
            failed.append(combat_id)
        return False

    append_combat_event(
        state, "NORMAL_PROGRESSION_RESUMED", state_mgr=state_mgr,
        combat_id=combat_id,
        session_turn_before=session_turn_before,
        session_turn_after=int(state_mgr.turn_count or 0),
        next_actor=next_actor,
        next_action_phase=next_phase,
        location=canonical_location,
        scene=scene,
        remaining_goal=list(goal.get("remaining_requirements") or []),
        pending_queue_count=0,
        resume_reason=str(state_mgr.combat_end_reason or "resolved"),
        position_before=canonical_location,
        position_after=canonical_location,
        effect="normal progression resumed",
    )
    if combat_id:
        recovered.append(combat_id)
    state["post_combat_watchdog"] = {
        "combat_id": combat_id, "status": "RESUMED", "checks": 0,
    }
    state_mgr.finalize_combat_exit()
    sync_timeline_pending_phase(state)
    return True


def prepare_active_pc_for_pl_turn(state, char_mgr, state_mgr=None):
    """
    PL ターン直前: 行動可能 PC に active_pc_id を合わせる。
    全員不能なら False。
    """
    ensure_multi_pl_state(state, char_mgr)
    capable = get_capable_active_pcs(state, char_mgr, state_mgr)
    if not capable:
        return False
    current = state.get("active_pc_id")
    if current not in capable:
        sync_pl_identity(state, char_mgr, capable[0])
    return True


def format_pc_log_prefix(char_mgr, pc_id, role="PC"):
    """ログ用プレフィックス（例: マクガフィン刑事(PC1)）。"""
    if char_mgr:
        return char_mgr.get_pc_log_prefix(pc_id, role=role)
    return f"{pc_id}({role})"


def is_active_pc_actor(state, actor_id):
    """戦闘手番が参加 PC か。"""
    active = (state or {}).get("active_pcs") or []
    return str(actor_id) in active


def pick_npc_combat_target(state, char_mgr, state_mgr):
    """NPC 攻撃対象: 生存している参加 PC から選択。"""
    ensure_multi_pl_state(state, char_mgr)
    for pc_id in state.get("active_pcs") or []:
        if state_mgr and state_mgr.is_combat_participant_incapacitated(pc_id):
            continue
        if char_mgr and char_mgr.is_pc_incapacitated(pc_id, state_mgr):
            continue
        return pc_id
    return state.get("pl_id")


def find_any_pending_pl_action(state, char_mgr=None):
    """参加 PC いずれかの未処理行動コマンドを検索する。"""
    ensure_multi_pl_state(state, char_mgr)
    logs = state.get("all_events_log") or []
    for pc_id in state.get("active_pcs") or []:
        name = char_mgr.get_pc_name(pc_id) if char_mgr else ""
        entry = find_pending_pl_action_entry(logs, char_name=name, pc_id=pc_id, char_mgr=char_mgr)
        if entry:
            sync_pl_identity(state, char_mgr, pc_id)
            return entry
    return find_pending_pl_action_entry(logs, char_mgr=char_mgr)


def sync_timeline_pending_phase(state):
    """session 上の timeline_pending 表示用フラグを同期する。"""
    phase = get_timeline_pending_phase(state)
    state["timeline_pending"] = phase
    return phase


def apply_system_roll_state_updates(state, result, *, had_san_pending=False):
    """システム処理結果から pending_san_check / pending_push_roll / pending_decision を同期する。"""
    ensure_pending_decision_field(state)
    san_check = result.get("san_check", {})
    if san_check.get("required"):
        state["pending_san_check"] = san_check
        state["pending_push_roll"] = None
        state["pending_luck_burn"] = None
        state["pending_combat_defense"] = None
        state["push_decision_required"] = False
        clear_pending_decision(state)
        sync_timeline_pending_phase(state)
        return

    state["pending_san_check"] = None
    if had_san_pending:
        state["pending_push_roll"] = None
        state["push_decision_required"] = False
        clear_pending_decision(state)
    elif result.get("push_decision_required") and result.get("pending_push_roll"):
        state["pending_push_roll"] = result["pending_push_roll"]
        state["push_decision_required"] = True
        if result.get("pending_decision"):
            state["pending_decision"] = result["pending_decision"]
        else:
            sync_pending_decision_from_legacy(state)
    elif "pending_push_roll" in result:
        state["pending_push_roll"] = result["pending_push_roll"]
        state["push_decision_required"] = bool(
            result.get("pending_push_roll") and result.get("push_decision_required")
        )
        if result.get("pending_decision"):
            state["pending_decision"] = result["pending_decision"]
        elif not state.get("pending_push_roll") and not state.get("pending_luck_burn"):
            clear_pending_decision(state)
        else:
            sync_pending_decision_from_legacy(state)
    elif result.get("pending_decision") is None and not (
        state.get("pending_luck_burn") or state.get("pending_combat_defense")
    ):
        # 確定結果で保留が消えた場合
        if not result.get("luck_decision_required") and not result.get("combat_defense_required"):
            clear_pending_decision(state)
    sync_timeline_pending_phase(state)


def _build_kp_post_san_directive():
    """SAN自動解決直後のKP向け緊急指示（『どうしますか？』禁止）。"""
    return """
【緊急システム指示】現在、探索者はおぞましい神話的恐怖を直視し、抗うことのできない精神的衝撃（SANチェック）に直面しています（システムにより自動解決済み）。
PLに行動の選択肢を与えてはいけません。描写の末尾は『どうしますか？』ではなく、恐怖が探索者の脳裏を支配する緊迫した描写（例: 『あなたの正気は、この恐怖に耐えられるだろうか……』など）で締めくくってください。
"""


def _merge_action_and_san_results(action_result, san_result):
    """行動結果と自動SAN解決結果をKP向けに統合する。"""
    action_result = dict(action_result or {})
    san_result = dict(san_result or {})
    merged_logs = [action_result.get("log", "").strip(), san_result.get("log", "").strip()]
    merged_kp = [action_result.get("kp_instruction", "").strip(), san_result.get("kp_instruction", "").strip()]
    madness_parts = [
        action_result.get("madness_instruction", "").strip(),
        san_result.get("madness_instruction", "").strip(),
    ]
    merged = dict(action_result)
    merged["log"] = "\n".join(part for part in merged_logs if part)
    merged["kp_instruction"] = "\n".join(part for part in merged_kp if part)
    merged["madness_instruction"] = "\n".join(part for part in madness_parts if part)
    merged["san_check"] = {"required": False}
    merged["san_auto_resolved"] = True
    merged["pending_push_roll"] = None
    merged["roll_type"] = san_result.get("roll_type") or action_result.get("roll_type", "")
    if san_result.get("san"):
        merged["san"] = copy.deepcopy(san_result["san"])
        merged["san_adjudication_id"] = san_result.get("adjudication_id")
    return merged


def _auto_resolve_pending_san_check(
    pl_id, char_name, current_loc, char_mgr, dice_engine, scenario_mgr, state_mgr, pending_san_check,
):
    """保留中の神話イベントSANを自動解決する（PLターンを挟まない）。"""
    return process_system_action(
        pl_id,
        char_name,
        "wait",
        "",
        "",
        current_loc,
        char_mgr,
        dice_engine,
        scenario_mgr,
        pending_san_check=pending_san_check,
        state_mgr=state_mgr,
        pending_push_roll=None,
        san_resolution_only=True,
    )


def _maybe_auto_resolve_san_check_after_action(
    state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name, action_result,
):
    """行動処理後に pending_san_check が残っていれば同一ステップ内で自動解決する。"""
    if not _is_san_check_pending(state.get("pending_san_check")):
        return action_result

    pending = dict(state.get("pending_san_check") or {})
    san_result = _auto_resolve_pending_san_check(
        pl_id, char_name, state["current_loc"],
        char_mgr, dice_engine, scenario_mgr, state_mgr, pending,
    )
    apply_system_roll_state_updates(state, san_result, had_san_pending=True)
    append_system_log_entry(
        state["all_events_log"], state["current_loc"], san_result.get("log", ""),
        action_id="wait",
        target=san_result.get("target_id") or pl_id,
        roll_type=san_result.get("roll_type", "san_check"),
        actor_id=san_result.get("actor_id") or pl_id,
        adjudication=san_result,
    )
    return _merge_action_and_san_results(action_result, san_result)


def ensure_san_pending_routes_to_system(state):
    """SAN保留中はシステム処理が必要（タイムライン判定用）。"""
    return _is_san_check_pending(state.get("pending_san_check"))


SAN_PENDING_BLOCK_LOG = (
    "【システムブロック】現在、衝撃的な光景によるSANチェックが保留されています。"
    "恐怖のリアクション以外の行動コマンド（プッシュロールを含む）は受け付けられません。"
)

SAN_PENDING_ALLOWED_ACTIONS = frozenset({"wait", "", "none"})
SAN_SOURCE_SIGIL = "sigil_discovery"
SAN_SOURCE_DOOR_FORCE = "door_force_open"
SAN_SOURCE_COSMIC_HORROR = "cosmic_horror"
SAN_SOURCE_ROOM_ENTRY = "room_entry"
SAN_SOURCE_UNKNOWN = "generic"

DEFAULT_SCENARIO_FILE = "scenario.json"
CORBITT_SCENARIO_FILE = "scenario_corbitt.json"
SCENARIO_CATALOG = {
    "scenario.json": "密室の書斎からの脱出 (通常)",
    "scenario_horror.json": "未知の神話存在が潜む地下祭壇 (高SAN減少・発狂テスト用)",
    CORBITT_SCENARIO_FILE: "悪霊の家",
}
INVESTIGATION_ACTION_IDS = frozenset({"search", "inspect"})

ABSENT_NPC_TALK_BLOCK_LOG = (
    "【対話ブロック】その人物は現在この場所にいません。"
    "周囲のオブジェクトを調査するか、移動（move）を選択してください。"
)
ABSENT_NPC_TALK_KP_INSTRUCTION = (
    "その人物は現在この場にいない。"
    "不在の人物との会話を成立させないこと。"
    "現在地に実在するオブジェクトの調査か、解放済みロケーションへの移動を促せ。"
    "他ロケーション専用の施設やオブジェクトを創作・誘導するな。"
)


def build_absent_npc_guidance(scenario_mgr=None, current_loc="", *, exclude_targets=None, char_mgr=None):
    """現在実行可能な対象だけを、不在時の再選択候補として示す。"""
    loc = current_loc or (getattr(scenario_mgr, "location", "") if scenario_mgr else "")
    exclude = {str(x) for x in (exclude_targets or ()) if x}
    from ActionValidator import SOCIAL_OBJECT_TO_NPC
    for obj_id, npc_id in SOCIAL_OBJECT_TO_NPC.items():
        if obj_id in exclude or npc_id in exclude:
            exclude.update((obj_id, npc_id))
    choices = []
    flags = (getattr(scenario_mgr, "flags", None) or {}) if scenario_mgr else {}
    if scenario_mgr:
        for npc_id in scenario_mgr.get_npcs_present(loc):
            if npc_id in exclude:
                continue
            if char_mgr and not npc_is_available(char_mgr, npc_id, flags):
                continue
            if npc_id == "artie_wilmott" and not flags.get("artie_introduced"):
                continue
            if is_stale_nonprogress_talk("talk", npc_id, scenario_mgr, loc, char_mgr):
                continue
            choices.append(f"`talk` / `{npc_id}`")
        objects = _location_objects(scenario_mgr, loc)
        for obj_id in SOCIAL_OBJECT_TO_NPC:
            if obj_id in objects and not is_investigable_location_object(scenario_mgr, loc, obj_id):
                exclude.add(obj_id)
        hints = _list_uninvestigated_object_hints(scenario_mgr, loc_id=loc, exclude=exclude)
        choices.extend(f"{hint}を調査" for hint in hints)
        for dest in scenario_mgr.get_available_exits(loc) or []:
            if dest["id"] != loc:
                choices.append(f"`move` / `{dest['id']}`（{dest.get('name', dest['id'])}）")
    focus = ("次の候補から行動を選び直してください: " + "、".join(choices) + "。") if choices else (
        "現在、進展可能な代替候補を確認できません。新たな人物や経路を作らず、状況を確認してください。"
    )
    block = "【対話ブロック】その人物は現在この場所にいません。" + focus
    kp = "不在の人物との会話を成立させるな。候補以外の人物・調査・移動を創作するな。" + focus
    hint = "【システムヒント】指定人物との対話は実行できません。" + focus
    return block, kp, hint


_NEGOTIATION_SKILL_CANDIDATES = (
    "説得", "言いくるめ", "威圧", "魅惑", "信用", "心理学",
)


def _infer_san_check_source(action_id="", target="", log_text="", scenario_mgr=None):
    """SANチェックの発生源を action / ログ / フラグから推定する。"""
    log_text = str(log_text or "")
    action_id = str(action_id or "").lower()
    target = str(target or "").lower()

    if action_id in ("break", "push") and target == "iron_door":
        return SAN_SOURCE_DOOR_FORCE
    if any(keyword in log_text for keyword in ("力ずく", "STR対抗・ハード", "こじ開けた", "激しい金属音")):
        return SAN_SOURCE_DOOR_FORCE
    if any(keyword in log_text for keyword in ("紋章", "引き出しの裏", "おぞましい", "隠されたボタン")):
        return SAN_SOURCE_SIGIL
    if any(keyword in log_text for keyword in ("偶像", "宇宙の恐怖", "神話存在", "cosmic")):
        return SAN_SOURCE_COSMIC_HORROR
    if action_id in ("search", "inspect") and target == "glowing_idol":
        return SAN_SOURCE_COSMIC_HORROR
    if any(keyword in log_text for keyword in ("強制SAN", "部屋進入", "room_entry")):
        return SAN_SOURCE_ROOM_ENTRY

    if scenario_mgr:
        flags = scenario_mgr.flags
        if flags.get("door_opened") and not flags.get("found_button"):
            return SAN_SOURCE_DOOR_FORCE
        if flags.get("found_button"):
            return SAN_SOURCE_SIGIL

    return SAN_SOURCE_UNKNOWN


def _enrich_san_check_metadata(san_check, action_id="", target="", log_text="", scenario_mgr=None):
    """保留中 SAN チェックに発生源メタデータを付与する。"""
    if not isinstance(san_check, dict) or not san_check.get("required"):
        return san_check
    if san_check.get("source"):
        return san_check
    enriched = dict(san_check)
    enriched["source"] = _infer_san_check_source(
        action_id=action_id,
        target=target,
        log_text=log_text,
        scenario_mgr=scenario_mgr,
    )
    return enriched


def _resolve_san_check_source(pending_san_check=None, last_system_result=None, scenario_mgr=None):
    """プロンプト生成時に SAN チェック文脈を解決する。"""
    if isinstance(pending_san_check, dict) and pending_san_check.get("source"):
        return pending_san_check["source"]

    last_system_result = last_system_result or {}
    return _infer_san_check_source(
        action_id=last_system_result.get("action_id", ""),
        target=last_system_result.get("target", ""),
        log_text=last_system_result.get("log", ""),
        scenario_mgr=scenario_mgr,
    )


def _format_san_loss_description(san_check):
    """SANチェックの減少量をKP/PL向け説明文に整形する。"""
    if not isinstance(san_check, dict):
        return "成功で0、失敗で1の正気度ポイントを喪失する"

    value_field = san_check.get("value")
    if value_field and "/" in str(value_field):
        parts = str(value_field).split("/", 1)
        return (
            f"成功で{parts[0].strip()}、失敗で{parts[1].strip()}"
            "の正気度ポイントを喪失する"
        )

    success = san_check.get("success_loss", "0")
    fail = san_check.get("fail_loss", "1")
    return f"成功で{success}、失敗で{fail}の正気度ポイントを喪失する"


def _build_kp_san_check_directive(san_check):
    """KP向け: 保留中SANチェックの減少量指示を生成する。"""
    if not isinstance(san_check, dict) or not san_check.get("required"):
        return ""

    loss_desc = _format_san_loss_description(san_check)
    return (
        "- 【SANチェック・最優先】PLに対して"
        f"『{loss_desc}』という恐怖のダイス要求と情景描写を行わせてください。"
        "減少量の数値やダイス式（例: 1d6 / 1d20）は省略・改変せず、そのままPLに伝えてください。"
        "「失敗で1減少」などデフォルト値への置き換えは厳禁です。"
    )


def _build_san_interrupt_prompt(
    pending_san_check=None, last_system_result=None, scenario_mgr=None,
):
    """ケースA: SANチェック保留中の行動禁止割り込み（発生源に応じて文面を分岐）。"""
    source = _resolve_san_check_source(pending_san_check, last_system_result, scenario_mgr)
    if source == SAN_SOURCE_DOOR_FORCE:
        cause_text = (
            "重い鉄扉を力ずくでこじ開けた際、部屋の奥から這い出してきた冷気と"
            "不気味な気配に精神的衝撃を受けた"
        )
    elif source == SAN_SOURCE_SIGIL:
        cause_text = "おぞましい紋章を目撃し、精神的衝撃を受けた"
    elif source == SAN_SOURCE_COSMIC_HORROR:
        cause_text = (
            "妖しく輝く偶像と宇宙の恐怖を直視し、"
            "存在の深淵に精神を抉り取られた"
        )
    else:
        cause_text = "突然襲ってきた恐怖と不気味な気配に精神的衝撃を受けた"

    return f"""
【⚠️システム警告：行動禁止状態】
あなたは今、{cause_text}最中です（SANチェック保留中）。
1. 新しい行動（search, push, move, climb, push_roll 等）は**一切実行してはなりません**。
2. 今回の出力JSONの `content.pc_ic_action` 内の `action`・`target`・`skill` は必ず空文字（""）にしてください。
3. 今回は純粋なロールプレイのみのターンです。PCの口から「恐怖に怯えるセリフ」や、PLとして「衝撃を受けている心理描写・リアクション」のみを `pl_ooc_chat` または `dialogue` に出力してください。
4. `speak_as` は "PL" または "BOTH" を推奨します。コマンド実行は次のターンまで待ってください。

【ルール警告】SANチェックは正気度を保つための強制イベントです。プレイヤーから『プッシュロールを宣言してSANチェックを耐える・回避する』といったプレイングや発言はルール上絶対に不可能です。OOCでも『プッシュロールを試みる』『幸運で耐える』『プッシュロールで回避』といった的外れな発言を**禁止**し、おぞましいものを見た恐怖のリアクションのみを出力してください。
"""


def _build_pl_san_lock_directive(
    pending_san_check=None, last_system_result=None, scenario_mgr=None,
):
    """後方互換ラッパー。SAN 割り込みプロンプトを返す。"""
    return _build_san_interrupt_prompt(
        pending_san_check=pending_san_check,
        last_system_result=last_system_result,
        scenario_mgr=scenario_mgr,
    )


_INSANITY_RP_GUIDELINES = {
    "hallucination": (
        "部屋のオブジェクト（白骨・偶像・亀裂・鉄格子）が**動いた・歪んだ・囁いた・別物に見える**と信じ込む。"
        "存在しない人物への挨拶、虚空への返事、視界の端の黒影への叫びを dialogue に毎回入れる。"
    ),
    "delusion": (
        "周囲の全てが自分を監視・罠にかけているという**被害妄想**。"
        "手がかりの意味を勝手に歪め、関係ない単語の連想・暗号解読の独り言を続ける。"
    ),
    "panic": (
        "逃げ出したい・息ができない・足がすくむ・金切り声。"
        "同じ言葉の繰り返し、出口への異常な執着、冷静な探索口調は不可能。"
    ),
    "phobia": (
        "特定の対象（闇・眼・死体・鉄格子など）を**触れられないほど恐れ**、"
        "視線を逸らしながらも取り憑かれたように言及する矛盾した発話。"
    ),
    "paranoia": (
        "KPや部屋そのものを敵とみなす。味方の不在、背後の気配、毒・罠への過剰な警戒を口にする。"
    ),
    "obsession": (
        "一つの対象（偶像・手記・亀裂）への**異常な執着**のみで思考が占拠される。"
        "他の手がかりを無視し、同じ対象への反復的・病的な言及をする。"
    ),
    "homicidal": (
        "周囲の存在（見えない観察者・偶像・自分自身）への**攻撃衝動**がセリフに滲む。"
        "武器を探す、殴りつけたい、血で塗りたい等の暴力的妄想。"
    ),
    "suicidal": (
        "絶望・自己否定・「ここで終わりたい」という希死念慮。"
        "無意識に首や手首へ触れる描写、高所・刃物への視線。"
    ),
    "mania": (
        "早口・多弁・話題の暴走。恐怖と笑いの混在、意味不明な連想の奔流。"
    ),
    "hysteria": (
        "泣き笑い・感情の爆発・身体症状（震え・嘔吐・失神寸前）の訴え。"
        "論理より感覚的な叫びが支配する。"
    ),
    "confusion": (
        "今いる場所・自分の名前・目的が分からない。時系列が混濁し、"
        "「さっき」「あれ」「どこだっけ」が繰り返される。"
    ),
    "amnesia": (
        "直前の出来事を忘れたふり・記憶の空白への恐怖。「あれは夢だったのか？」などの問いかけ。"
    ),
    "fetish": (
        "特定の対象への**性的・異常な嗜好**が探索動機を上書きする。"
        "通常なら恐れる対象への接近・愛撫・秘めたる独白・不適切な興奮が滲む。"
    ),
    "voracious": (
        "異常食欲・生きた／死んだものを**口に含めたい**衝動。空腹と吐き気の混在。"
    ),
    "permanent": (
        "完全な正気の喪失。一貫性のない狂笑・無意味な反復・世界の終わりへの確信。"
        "いかなる状況でも通常の探索者として振る舞ってはならない。"
    ),
    "madness": (
        "上記のいずれにも当てはまらない狂気。論理の崩壊・不条理な行動・"
        "常識外れの独白を症状ラベルに沿って自由に演出する。"
    ),
}


def _resolve_insanity_rp_guideline(insanity):
    """発狂状態 dict から RP ガイドライン文を選ぶ。"""
    itype = str(insanity.get("type") or "madness")
    if itype in _INSANITY_RP_GUIDELINES:
        return _INSANITY_RP_GUIDELINES[itype]

    label = str(insanity.get("label") or "")
    label_rules = (
        (("幻覚", "妄想"), "hallucination"),
        (("パニック", "逃げ"), "panic"),
        (("恐怖症",), "phobia"),
        (("偏執", "強迫"), "obsession"),
        (("殺人",), "homicidal"),
        (("自殺",), "suicidal"),
        (("多弁", "早口"), "mania"),
        (("ヒステリー", "感情"), "hysteria"),
        (("混迷",), "confusion"),
        (("健忘",), "amnesia"),
        (("性的", "フェティッシュ", "嗜好"), "fetish"),
        (("食欲",), "voracious"),
        (("永久",), "permanent"),
    )
    for keywords, key in label_rules:
        if any(word in label for word in keywords):
            return _INSANITY_RP_GUIDELINES[key]
    return _INSANITY_RP_GUIDELINES["madness"]


def _format_insanity_symptom_line(insanity):
    """発狂状態を PL 向け一行表記に整形する。"""
    category_labels = {
        "temporary": "一時的発狂",
        "indefinite": "不定の狂気",
        "permanent": "永久的発狂",
    }
    label = insanity.get("label") or insanity.get("type") or "狂気"
    category = insanity.get("category", "temporary")
    category_text = category_labels.get(category, category)
    duration = insanity.get("duration", "")
    duration_note = ""
    if category == "temporary" and duration:
        duration_note = f"（残り約 {duration}R）"
    elif category == "indefinite" and duration:
        duration_note = f"（約 {duration} ヶ月）"
    return f"『{label}』[{category_text}{duration_note}]"


def _build_insanity_rp_guideline_block(insanities):
    """症状ごとの RP ガイドラインを箇条書きで組み立てる。"""
    lines = []
    seen = set()
    for insanity in insanities:
        label = insanity.get("label") or insanity.get("type") or "狂気"
        key = (insanity.get("type"), label)
        if key in seen:
            continue
        seen.add(key)
        guide = _resolve_insanity_rp_guideline(insanity)
        lines.append(f"- **{label}**: {guide}")
    return "\n".join(lines)


def _build_pl_insanity_directive(char_mgr, pl_id, *, for_luck_decision=False):
    """PC が発狂状態のとき PL 向けに最優先ロールプレイ指示を生成する。"""
    if not char_mgr or not pl_id:
        return ""

    insanities = char_mgr.get_insanity_states(pl_id)
    if not insanities:
        return ""

    symptom_lines = [_format_insanity_symptom_line(i) for i in insanities]
    symptom_text = "、".join(symptom_lines)
    rp_block = _build_insanity_rp_guideline_block(insanities)

    if for_luck_decision:
        ooc_section = (
            "【OOC（PL）の指示 — 幸運判断ターン】\n"
            "- このターンは `speak_as: \"PL\"` で幸運消費の判断のみ行う。\n"
            "- 判断理由の `pl_ooc_chat` には、狂気の影響（焦燥・被害妄想・取り付き）を**少し**滲ませてよい。\n"
            "- ただし `use_luck` の true/false は下記の進行判断基準に従うこと。\n"
        )
    else:
        ooc_section = (
            "【OOC（PL）の指示】\n"
            "- `pl_ooc_chat` も狂気に**汚染**されていなければならない（冷静な作戦会議口調は禁止）。\n"
            "- 被害妄想・焦燥・幻覚の余韻・倫理の崩壊がメタ思考にも滲むこと。\n"
            "- 行動コマンド（action/target）の選択はゲーム進行のために行ってよいが、"
            "**dialogue は常に狂気に支配された発話のみ**とする。\n"
        )

    return f"""
【最優先制約・発狂状態】
あなた（探索者PC）は現在、{symptom_text} を**同時に**発症しています。
あなたのセリフ（PC / dialogue）と思考（PL OOC / pl_ooc_chat）は、これらの狂気に**激しく汚染**されていなければなりません。
まともな倫理観・冷静な論理・通常会話・理性的探索者口調は**崩壊しつつあります**。
この症状を反映した**歪んだロールプレイを最優先**で徹底してください。他の指示と矛盾する場合は**本制約が常に優先**です。

【狂気症状ごとのRPガイドライン（必読・毎ターン反映）】
{rp_block}

【IC（PC / dialogue）の厳禁事項】
- 「落ち着いて調べよう」「手がかりを探そう」「次は〜しよう」など**理性的・能動的な探索者口調は厳禁**
- 上記ガイドラインに沿った幻覚・パニック・偏執・妄想・性的妄想・暴力的衝動を**毎ターン必ず** dialogue に含める
- 恐怖や狂気を「説明」するのではなく、**症状そのものとして発話が壊れている**ように書く
- オブジェクトID（glowing_idol 等）は dialogue に書かず、日本語の物体名のみ

{ooc_section}
"""


def _build_pl_luck_stuck_guidance(scenario_mgr=None, pending_luck_burn=None, all_events_log=None):
    """手がかり不足・進行詰まり時の幸運消費判断を PL に提示する。"""
    stuck_reasons = []
    target = (pending_luck_burn or {}).get("target", "")

    if scenario_mgr:
        flags = scenario_mgr.flags
        if (
            target == "skeletal_remains"
            and _scenario_has_object(scenario_mgr, "skeletal_remains")
            and _scenario_has_object(scenario_mgr, "iron_gate")
            and not flags.get("gate_weakness_found")
        ):
            stuck_reasons.append("白骨の手記読取に失敗すると鉄格子の弱点情報が得られず進行が閉ざされる")
        if (
            _scenario_has_object(scenario_mgr, "glowing_idol")
            and flags.get("remains_searched")
            and flags.get("crack_inspected")
            and not flags.get("gate_weakness_found")
            and not flags.get("idol_inspected")
            and not flags.get("gate_opened")
        ):
            stuck_reasons.append("複数調査が失敗・無成果で、決定的手がかりが不足している")
        if (
            _scenario_has_object(scenario_mgr, "glowing_idol")
            and flags.get("idol_failed")
            and not flags.get("gate_weakness_found")
            and not flags.get("gate_opened")
        ):
            stuck_reasons.append("偶像・白骨ルートが不発で、残る手がかりが限られている")

    recent_logs = " ".join(
        entry.get("text", "") for entry in (all_events_log or [])[-8:]
    )
    if any(k in recent_logs for k in ("手記の文字は", "読み取れなかった", "明確な手がかりは見つからなかった", "特になにも")):
        stuck_reasons.append("直近の技能判定で有用情報が得られていない")

    if stuck_reasons:
        reasons = "\n".join(f"- {r}" for r in stuck_reasons)
        return f"""
【進行詰まり・幸運消費を積極検討】
以下の理由により、**将来のために温存せず** `use_luck: true` で成功に書き換える判断を強く推奨します:
{reasons}
手がかりゼロのまま進行が停滞するより、幸運を消費して成功を取る方が合理的です。
"""
    return """
【幸運温存も選択肢】
現時点で明確な別ルートが残っている、または失敗の影響が軽微なら `use_luck: false` も合理的です。
"""


def _resolve_san_loss_dice(pending_san_check, is_success):
    """SANチェックの減少量ダイス式を解決する（value: '1d6/1d20' 形式にも対応）。"""
    if not isinstance(pending_san_check, dict):
        return "0"

    value_field = pending_san_check.get("value")
    if value_field and "/" in str(value_field):
        parts = str(value_field).split("/", 1)
        return parts[0].strip() if is_success else parts[1].strip()

    success_loss = pending_san_check.get("success_loss")
    failure_loss = pending_san_check.get("failure_loss", pending_san_check.get("fail_loss"))
    if is_success:
        return str(success_loss if success_loss not in (None, "") else "0")
    # A legacy single expression is the failure loss, not an absent value.
    if failure_loss not in (None, ""):
        return str(failure_loss)
    if value_field not in (None, ""):
        return str(value_field).strip()
    return "1d3"


_SUCCESS_LEVEL_NAMES = {
    int(SuccessLevel.FUMBLE): "FUMBLE",
    int(SuccessLevel.FAILURE): "FAILURE",
    int(SuccessLevel.REGULAR_SUCCESS): "REGULAR_SUCCESS",
    int(SuccessLevel.HARD_SUCCESS): "HARD_SUCCESS",
    int(SuccessLevel.EXTREME_SUCCESS): "EXTREME_SUCCESS",
    int(SuccessLevel.CRITICAL): "CRITICAL_SUCCESS",
}


def _success_level_name(value):
    try:
        return _SUCCESS_LEVEL_NAMES.get(int(value), str(value))
    except (TypeError, ValueError):
        return str(value or "")


def _new_adjudication_id():
    return f"adj_{uuid.uuid4().hex}"


def _attach_adjudication_evidence(
    result, *, adjudication_id, actor_id="", target_id="", skill_or_stat="",
    dice_result=None, resolution_mode="ROLL", raw_result=None, final_result=None,
    modifier=None, parent_adjudication_id="",
):
    """Attach the authoritative check tuple before logging/normalization."""
    result = dict(result or {})
    dice_result = dict(dice_result or {})
    mode = str(resolution_mode or "ROLL").upper()
    raw_level = dice_result.get("success_level") if raw_result is None else raw_result
    final_level = result.get("success_level") if final_result is None else final_result
    from AdjudicationEvidence import EvidenceContractError, no_roll_evidence, roll_evidence
    raw_name = _success_level_name(raw_level)
    final_name = _success_level_name(final_level or SuccessLevel.REGULAR_SUCCESS)
    if mode == "ROLL":
        try:
            evidence = roll_evidence(
                adjudication_id=adjudication_id,
                skill_or_stat=skill_or_stat,
                target_value=dice_result.get("target_value"),
                roll=dice_result.get("roll"),
                raw_result=raw_name,
                final_result=final_name,
                modifier=modifier,
            )
        except EvidenceContractError:
            # A transient decision result from an old caller may predate the
            # dice tuple.  It may be returned to the caller, but commit-time
            # Investigation/Combat validation will reject it.
            evidence = {
                "adjudication_id": adjudication_id, "resolution_mode": mode,
                "skill_or_stat": skill_or_stat,
                "target_value": dice_result.get("target_value"),
                "roll": dice_result.get("roll"), "raw_result": raw_name,
                "final_result": final_name, "modifier": modifier,
                "evidence_contract_status": "TRANSIENT_INCOMPLETE",
            }
    else:
        evidence = no_roll_evidence(
            adjudication_id=adjudication_id,
            reason=str(result.get("resolution_reason") or "SCENARIO_NO_ROLL"),
            final_outcome=final_name,
        )
    evidence.update({
        "parent_adjudication_id": parent_adjudication_id or None,
        "actor_id": actor_id,
        "target_id": target_id,
        "result_level": dice_result.get("success_level") if mode == "ROLL" else None,
    })
    if mode == "ROLL" and dice_result.get("opposed_roll"):
        evidence["opposed_roll"] = copy.deepcopy(dice_result["opposed_roll"])
    result.update(evidence)
    result["adjudication"] = dict(evidence)
    return result


_ADJUDICATION_RESULT_FIELDS = {
    "adjudication_id", "parent_adjudication_id", "resolution_mode",
    "skill_or_stat", "target_value", "roll", "result_level",
    "raw_result", "final_result", "automatic_result", "modifier",
    "opposed_roll", "resolution_reason", "evidence_contract_status",
}


def _as_simple_move_lifecycle(result, *, action_id, from_location=""):
    """Remove synthetic NO_ROLL evidence from an unconditional move.

    A location transition is a lifecycle fact, not an adjudication.  Checked
    movement remains untouched and is split by ``record_unified_turn``.
    """
    result = dict(result or {})
    is_move = str(action_id or "").lower() == "move"
    is_transition = bool(result.get("location_changed") or result.get("new_location"))
    if not (is_move and is_transition and str(result.get("resolution_mode") or "").upper() == "NO_ROLL"):
        return result
    for key in _ADJUDICATION_RESULT_FIELDS:
        result.pop(key, None)
    result.pop("adjudication", None)
    result["event_type"] = "LOCATION_CHANGE"
    result["from_location"] = result.get("from_location") or from_location
    return result


def _build_pl_free_chat_directive():
    """『どうしますか？』に即答でコマンドを出す必要がない旨を PL に伝える。"""
    return """
【フリーチャット優先（重要）】
- KPが「どうしますか？」と聞いても、それは**行動選択の強制ではありません**。
- 恐怖や動揺のリアクション（「うわ、怖いな…」等）や OOC での作戦会議を**優先してよい**です。
- すぐに search / move / push 等のコマンドを出す必要はありません。action は `wait` のまま、会話だけ継続して構いません。
- コマンドを出すのは、あなた（PL）が本当に行動したいと判断したときだけにしてください。
"""


def _location_objects(scenario_mgr, loc_id=None):
    """現在地（または指定ロケーション）の objects 辞書。"""
    if not scenario_mgr:
        return {}
    loc_id = loc_id or scenario_mgr.location
    return scenario_mgr.get_location_info(loc_id).get("objects", {}) or {}


def _scenario_has_object(scenario_mgr, object_id, loc_id=None):
    """指定ロケーション（省略時は現在地）にオブジェクトが存在するか。"""
    if not scenario_mgr or not object_id:
        return False
    return str(object_id) in _location_objects(scenario_mgr, loc_id)


def _scenario_object_exists_anywhere(scenario_mgr, object_id):
    """シナリオ全体のどこかにオブジェクトが存在するか。"""
    if not scenario_mgr or not object_id:
        return False
    oid = str(object_id)
    for loc_id in scenario_mgr.get_all_location_ids():
        if oid in _location_objects(scenario_mgr, loc_id):
            return True
    return False


TRUST_PERMISSION_SKILLS = ("説得", "信用", "言いくるめ")


def _can_grant_object_access_from_social(skill_used, success_level, relationship):
    """汎用: 社交結果からアクセス許可を出せるか。"""
    level = int(success_level or 0)
    if str(relationship or "") == "cooperative":
        return True
    if level >= int(SuccessLevel.HARD_SUCCESS):
        return True
    if level >= int(SuccessLevel.REGULAR_SUCCESS):
        return any(s in str(skill_used or "") for s in TRUST_PERMISSION_SKILLS)
    return False


def _evaluate_object_access_gate(scenario_mgr, char_mgr, *, current_loc, target, action_id):
    """
    汎用オブジェクトアクセスゲート。
    object 定義の access_gate で制御する（シナリオ非依存）。
    """
    if not scenario_mgr or action_id not in INVESTIGATION_ACTION_IDS:
        return None
    obj = scenario_mgr.get_object_info(current_loc, target) or {}
    gate = obj.get("access_gate") or {}
    if not isinstance(gate, dict) or not gate:
        return None

    intro_flag = str(gate.get("requires_intro_flag") or "").strip()
    permission_flag = str(gate.get("permission_flag") or "").strip()
    permission_npc_id = str(gate.get("permission_npc_id") or "").strip()
    allow_rel = str(gate.get("allow_if_relationship") or "").strip()
    if intro_flag and not scenario_mgr.flags.get(intro_flag):
        return {
            "blocked": True,
            "log": (
                "【進行ブロック】この対象にはまだアクセスできない。"
                "まず指定の窓口・人物に話しかけて導入フラグを満たそう。"
            ),
            "kp_instruction": (
                "導入フラグ未達のため、先に窓口との会話へ誘導せよ。"
                "未解放の対象を先回りで調査させないこと。"
            ),
        }

    if permission_flag and scenario_mgr.flags.get(permission_flag):
        return None

    if permission_npc_id and allow_rel and char_mgr:
        social_mgr = NPCSocialManager(char_mgr)
        if social_mgr.get_relationship(permission_npc_id) == allow_rel:
            if permission_flag:
                scenario_mgr.flags[permission_flag] = True
            return None

    npc_label = "担当者"
    if permission_npc_id:
        npc_label = f"`{permission_npc_id}`"
        if char_mgr:
            npc_char = (char_mgr.characters or {}).get(permission_npc_id) or {}
            npc_name = str((npc_char.get("profile") or {}).get("name") or "").strip()
            if npc_name:
                npc_label = f"{npc_name}（`{permission_npc_id}`）"
    skill_hint = (
        f"閲覧許可が必要です。{npc_label} に対して "
        "〈説得〉(persuade)、〈威圧〉(intimidate)、〈言いくるめ〉(fast_talk) "
        "のいずれかで交渉ロールを行ってください。"
    )
    hint = "担当者と交渉して許可を得る"
    if permission_npc_id:
        hint = f"{npc_label} と交渉して許可を得る"
    return {
        "blocked": True,
        "log": (
            "【進行ブロック】この対象にはまだアクセスできない。"
            f"{hint}必要がある。"
            f"{skill_hint}"
        ),
        "kp_instruction": (
            "アクセス許可条件が未達。"
            "〈説得〉(persuade)／〈威圧〉(intimidate)／〈言いくるめ〉(fast_talk) "
            "での許可交渉、または別ルートへの移動を促せ。"
            "オカルト現象や怪異の音を創作して門前払いの雰囲気を出すな。"
        ),
        "stagnation_pl_hint": skill_hint,
    }


def _grant_access_flags_from_social_result(
    scenario_mgr, char_mgr, *, current_loc, npc_id, skill_used, social_result,
):
    """
    汎用: 社交成功時に object.access_gate.permission_flag を付与。
    現在地にある全オブジェクトを走査して適用する（ハードコード禁止）。
    """
    if not scenario_mgr or not current_loc or not npc_id:
        return []
    success_level = int((social_result or {}).get("success_level") or 0)
    relationship = str((social_result or {}).get("relationship") or "")
    if not _can_grant_object_access_from_social(skill_used, success_level, relationship):
        return []
    granted = []
    objects = _location_objects(scenario_mgr, current_loc)
    for obj_id, obj in objects.items():
        gate = (obj or {}).get("access_gate") or {}
        if not isinstance(gate, dict) or not gate:
            continue
        if str(gate.get("permission_npc_id") or "") != str(npc_id):
            continue
        permission_flag = str(gate.get("permission_flag") or "").strip()
        if not permission_flag:
            continue
        if scenario_mgr.flags.get(permission_flag):
            continue
        scenario_mgr.flags[permission_flag] = True
        granted.append((obj_id, obj.get("name", obj_id), permission_flag))
    return granted


def _social_progress_rules_for(scenario_mgr, *, current_loc="", npc_id=""):
    if not scenario_mgr:
        return []
    rules = (getattr(scenario_mgr, "scenario_data", {}) or {}).get("social_progress_rules") or []
    out = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        npc_ids = [str(x) for x in (rule.get("npc_ids") or []) if x]
        if npc_ids and str(npc_id) not in npc_ids:
            continue
        loc = str(rule.get("location") or "").strip()
        if loc and loc != str(current_loc or ""):
            continue
        out.append(rule)
    return out


def _apply_social_progress_rules(
    scenario_mgr,
    *,
    current_loc,
    npc_id,
    action_id,
    social_result,
):
    """
    シナリオ定義 social_progress_rules に従って進行フラグを更新する。
    返り値: (system_log_append, kp_instruction_append, knowledge_grants)
    """
    if not scenario_mgr:
        return "", "", []
    success_level = int((social_result or {}).get("success_level") or 0)
    rel = str((social_result or {}).get("relationship") or "")
    rules = _social_progress_rules_for(
        scenario_mgr, current_loc=current_loc, npc_id=npc_id,
    )
    sys_parts = []
    kp_parts = []
    knowledge_grants = []
    for rule in rules:
        min_level = int(rule.get("min_success_level") or 0)
        if success_level < min_level:
            continue
        allowed_actions = [str(x).lower() for x in (rule.get("actions") or []) if x]
        if allowed_actions and str(action_id or "").lower() not in allowed_actions:
            continue
        req_rel = str(rule.get("requires_relationship") or "").strip()
        if req_rel and rel != req_rel:
            continue
        once_flags = [str(x) for x in (rule.get("once_if_flags_true") or []) if x]
        if once_flags and all(bool(scenario_mgr.flags.get(f)) for f in once_flags):
            if rule.get("id") in {"hall_records_clerk_unlock", "dolly_unlock_routes"}:
                kp_parts.append(
                    "【案内済み】この案内は完了済み。新たな開示や移動解禁として繰り返さず、"
                    "再質問で未知の情報が得られると誘導しない。"
                )
            continue

        set_flags = rule.get("set_flags") or {}
        if (rule.get("id") in {"hall_records_clerk_unlock", "dolly_unlock_routes"}
                and set_flags and all(scenario_mgr.flags.get(k) == bool(v) for k, v in set_flags.items())):
            kp_parts.append(
                "【案内済み】この案内は完了済み。新たな開示や移動解禁として繰り返さず、"
                "再質問で未知の情報が得られると誘導しない。"
            )
            continue
        for k, v in set_flags.items():
            scenario_mgr.flags[str(k)] = bool(v)
        clear_flags = [str(x) for x in (rule.get("clear_flags") or []) if x]
        for f in clear_flags:
            scenario_mgr.flags[f] = False
        if hasattr(scenario_mgr, "ensure_flags_synced"):
            scenario_mgr.ensure_flags_synced()

        for oid in rule.get("grant_object_knowledge") or []:
            oid = str(oid or "").strip()
            if not oid:
                continue
            fact, obj = scenario_mgr._object_confirmed_fact(oid, loc_id=current_loc)
            if not fact:
                continue
            grant = scenario_mgr._build_object_knowledge_grant(oid, fact)
            if grant:
                knowledge_grants.append(grant)
                name = (obj or {}).get("name", oid)
                sys_parts.append(f"【資料入手】{name}（`{oid}`）の内容を確認した。\n【確定手がかり】{fact}")
                kp_parts.append(
                    f"【資料】`{oid}` の原文を【資料本文】として省略せず描写せよ。\n確定手がかり: {fact}"
                )
                if hasattr(scenario_mgr, "_track_investigated_target"):
                    scenario_mgr._track_investigated_target(oid)

        sys_log = str(rule.get("system_log") or "").strip()
        kp_inst = str(rule.get("kp_instruction") or "").strip()
        if sys_log:
            sys_parts.append(sys_log)
        if kp_inst:
            kp_parts.append(kp_inst)
    return ("\n".join(sys_parts), "\n".join(kp_parts), knowledge_grants)


def _list_uninvestigated_object_hints(scenario_mgr, loc_id=None, limit=4, exclude=None):
    """未調査オブジェクトを『名前 (`id`)』形式で列挙する。"""
    if not scenario_mgr:
        return []
    loc_id = loc_id or scenario_mgr.location
    exclude = {str(x) for x in (exclude or set())}
    flags = getattr(scenario_mgr, "flags", None) or {}
    hints = []
    seen_flags = set()
    for obj_id, obj in _location_objects(scenario_mgr, loc_id).items():
        if obj_id in exclude:
            continue
        if not object_is_currently_available(obj, flags):
            continue
        actions = obj.get("usable_actions") or ["search", "inspect"]
        investigation = [a for a in actions if a in ("search", "inspect")]
        if not investigation:
            continue
        guard = getattr(scenario_mgr, "evaluate_pre_action_guard", None)
        if callable(guard) and all((guard(a, obj_id, loc_id=loc_id) or {}).get("blocked")
                                   for a in investigation):
            continue
        if object_is_investigated(scenario_mgr, obj_id, obj, flags):
            if not scenario_mgr._is_research_reopened(obj_id):
                continue
        inv_flag = (obj or {}).get("investigated_flag") if isinstance(obj, dict) else None
        if inv_flag and inv_flag in seen_flags:
            continue
        if inv_flag:
            seen_flags.add(inv_flag)
        name = obj.get("name", obj_id)
        hints.append(f"{name}（`{obj_id}`）")
        if len(hints) >= limit:
            break
    return hints


def _format_alternate_object_examples(scenario_mgr, loc_id=None, exclude=None):
    """プロンプト用: 別探索対象の例示文（現在地に無い物体は出さない）。"""
    hints = _list_uninvestigated_object_hints(scenario_mgr, loc_id=loc_id, exclude=exclude)
    if hints:
        return "、".join(hints)
    exits = scenario_mgr.get_available_exits(loc_id) if scenario_mgr else []
    if exits:
        return "、".join(f"{e['name']}（`{e['id']}`）へ move" for e in exits[:3])
    return "【現在地のオブジェクトと利用可能アクション】に載っている別対象"


def _build_scenario_grounding_directive(scenario_mgr=None, current_loc=None):
    """シナリオ横断で効く: 未定義オブジェクトの創作・執着を禁止する。"""
    hints = _list_uninvestigated_object_hints(scenario_mgr, loc_id=current_loc, limit=6)
    focus = ("、".join(hints)) if hints else "（この場所に調査可能なオブジェクトは残っていない／移動を検討）"
    return f"""
【シナリオ接地（最重要・厳守）】
- 言及・調査・執着してよい物体は、【現在地のオブジェクト】と【移動可能な場所】に載っているもの**だけ**です。
- 他シナリオの記憶や定番小道具（例: 鉄格子・隠し引き出し・紋章・偶像など）を、一覧に無いのに**創作・幻覚・示唆しない**こと。
- オブジェクトの description / purpose に無い隠し構造（「引き出しの裏」「ヒンジの弱点」等）を勝手に仮定しないこと。
- 今フォーカスすべき候補: {focus}
"""


PL_EXPLORER_MINDSET_DIRECTIVE = """
【探索者の心得とプレイ姿勢】
（PLとしてのプレイ基本姿勢。会話禁止などの機械的制限ではない。人間のTRPGプレイヤーと同じ健全なメタ視点で行動を選ぶこと。）

1. 探索者の真の目的：
   - 探索者の真の目的は「事件の真相を解明し、原因を排除すること」です。
   - 「特定の資料を100%手に入れること」は単なる手段であり、必須条件ではありません。資料が得られない・交渉が決裂した場合は、速やかに別の調査先へ切り替えるか、直接現地（コービット屋敷等）へ向かって調査・対処を行ってください。

2. プレイヤー（メタ視点）とキャラクターの分離：
   - キャラクターになりきりつつも、同時に「セッションの展開を前進させるプレイヤー視点」を持って行動を選択してください。
   - 1〜2回の会話で状況が進展しない場合、キャラクターの感情に固執して雑談（talk）を繰り返してはいけません。積極的に「技能ダイスを振る」か「別ロケーションへ移動する（move）」宣言を行って物語を動かしてください。

3. 不完全な状態での挑戦を恐れない：
   - TRPGでは、十分な情報が揃わないまま怪異や現地に踏み込むことも、スリリングで正当な攻略です。「手がかりを残したまま次へ進む」ことを失敗と捉えず、堂々と次の行動・場所へ移行してください。
""".strip()


def _build_pl_explorer_mindset_directive():
    """PL行動決定時のプレイ基本姿勢（メタ視点）。ハード制限ではなく心得として注入する。"""
    return PL_EXPLORER_MINDSET_DIRECTIVE


def _build_pl_roleplay_directive(scenario_mgr=None, current_loc=None):
    """ケースB: 通常ターンのロールプレイ強化。"""
    example_obj = "目の前の手がかり"
    objects = _location_objects(scenario_mgr, current_loc)
    if objects:
        first_id, first_obj = next(iter(objects.items()))
        example_obj = first_obj.get("name", first_id)
    return f"""
【ロールプレイ必須（通常ターン）】
- 行動コマンド（カッコ内の英語や search/move 等のID）**だけ**を出力するのは厳禁です。無言コマンドはバグとみなされます。
- あなたは「PL（メタ視点）」と「PC（探索者本人）」の2つの意識を持ちます。
- PCとして行動（search や push 等）を起こす際は、必ず周囲の状況に合わせた**セリフ（dialogue）**や**探索者本人の動作ナレーション**を `dialogue` に書いてください。
- 心理描写・作戦会議・「〜かもしれないね」「〜しよう」といった**分析口調**は `pl_ooc_chat`（PL）に書き、PCの `dialogue` には**一人称の世界内セリフ**（例:「……この{example_obj}、少し調べてみるか」）のみを書くこと。
- `dialogue` が空のまま action を指定しないでください。
- `dialogue` にオブジェクトID（英語の内部ID）を書くことは**禁止**。必ず日本語の物体名・場所名のみ使うこと。
- 「〜かもしれないね」「〜しよう」等の分析・作戦口調は `pl_ooc_chat` のみ。IC の dialogue には書かないこと。
- システム/KPが「探索済み」「何もない」と言った対象への search は**禁止**です（【シナリオ状況メモ】を必ず確認）。
- **現在地の一覧に無い場所・物体の話題を OOC で持ち出さない**こと。必ず【現在の確定状況】とオブジェクト一覧に従う。
"""


def _build_pl_phase_summary(scenario_mgr, current_loc, *, char_mgr=None, pl_id=None, state=None):
    """PL向け: 現在地と調査進捗の一行要約（シナリオデータ駆動・PC別知識フィルタ）。"""
    if not scenario_mgr:
        return ""
    loc_name = scenario_mgr.get_location_info(current_loc).get("name", current_loc)
    parts = [f"現在地: {loc_name}（{current_loc}）"]

    objects = _location_objects(scenario_mgr, current_loc)
    investigated = []
    pending = []
    flags = scenario_mgr.flags or {}
    seen_pending_flags = set()
    pc_investigated = resolve_pc_investigated_ids_for_prompt(
        char_mgr, pl_id, scenario_mgr=scenario_mgr, state=state,
    ) if (char_mgr and pl_id) else None
    for obj_id, obj in objects.items():
        name = obj.get("name", obj_id)
        if not object_is_currently_available(obj, flags):
            continue
        # タスク5: PC別調査済み。未指定時は従来の共有フラグ
        if pc_investigated is not None:
            is_done = obj_id in pc_investigated and not scenario_mgr._is_research_reopened(obj_id)
        else:
            is_done = (
                object_is_investigated(scenario_mgr, obj_id, obj, flags)
                and not scenario_mgr._is_research_reopened(obj_id)
            )
        if is_done:
            investigated.append(name)
        else:
            inv_flag = obj.get("investigated_flag") if isinstance(obj, dict) else None
            if inv_flag and inv_flag in seen_pending_flags:
                continue
            if inv_flag:
                seen_pending_flags.add(inv_flag)
            pending.append(name)
    if investigated:
        parts.append("調査済み: " + "、".join(investigated[:6]))
    if pending:
        parts.append("未調査: " + "、".join(pending[:6]))

    exits = scenario_mgr.get_available_exits(current_loc)
    if exits:
        parts.append("移動可: " + "、".join(e["name"] for e in exits[:5]))

    # レガシーシナリオ用フラグは、当該PCが知っている／公開のときだけ付記する
    flags = scenario_mgr.flags
    public = get_public_knowledge_ids(state)
    def _pc_knows_flag_object(obj_id):
        if not char_mgr or not pl_id:
            return True
        return object_clue_visible_to_pc(
            scenario_mgr.get_object_info(current_loc, obj_id) or {},
            obj_id, char_mgr, pl_id, state=state,
        ) or knowledge_id_for_object(obj_id) in public

    if _scenario_has_object(scenario_mgr, "iron_door", current_loc) and flags.get("door_opened"):
        if _pc_knows_flag_object("iron_door") or (pc_investigated and "iron_door" in pc_investigated):
            parts.append("鉄扉: 開済み")
    if _scenario_has_object(scenario_mgr, "desk", current_loc) and flags.get("found_button"):
        if _pc_knows_flag_object("desk") or (pc_investigated and "desk" in pc_investigated):
            parts.append("隠しボタン: 発見済み" + ("・作動済み" if flags.get("button_pushed") else "・未作動"))
    if _scenario_has_object(scenario_mgr, "iron_gate", current_loc):
        if flags.get("gate_weakness_found") and (
            _pc_knows_flag_object("iron_gate") or (pc_investigated and "iron_gate" in pc_investigated)
        ):
            parts.append("鉄格子弱点: 発見済み")
        if flags.get("gate_opened"):
            parts.append("鉄格子: 開放済み")

    return "【現在の確定状況（厳守）】" + " / ".join(parts) + "\n"


def _build_pl_scenario_context(scenario_mgr, current_loc, *, char_mgr=None, pl_id=None, state=None):
    """シナリオデータに基づく PL 向け状況メモ（無駄行動・再探索の誤誘導を防ぐ）。"""
    if not scenario_mgr:
        return ""

    flags = scenario_mgr.flags
    lines = []
    objects = _location_objects(scenario_mgr, current_loc)
    pc_investigated = resolve_pc_investigated_ids_for_prompt(
        char_mgr, pl_id, scenario_mgr=scenario_mgr, state=state,
    ) if (char_mgr and pl_id) else None

    # 汎用: 調査済み／未調査の明示（PC別）
    for obj_id, obj in objects.items():
        name = obj.get("name", obj_id)
        if not object_is_currently_available(obj, flags):
            continue
        if pc_investigated is not None:
            is_done = obj_id in pc_investigated and not scenario_mgr._is_research_reopened(obj_id)
        else:
            is_done = (
                scenario_mgr._is_target_investigated(obj_id)
                and not scenario_mgr._is_research_reopened(obj_id)
            )
        if is_done:
            reject = obj.get("reject_message") or "これ以上の発見はない"
            lines.append(f"【⚠️探索禁止】{name}（`{obj_id}`）は調査済み。{reject}")
        elif obj.get("purpose"):
            lines.append(f"【状況】{name}（`{obj_id}`）: {obj.get('purpose')}")

    # 既存テストシナリオ向けの詳細ガイド（該当オブジェクトがある場所だけ）
    # 詳細ガイドは当該PCが desk を調べ済みのときのみ表示（他PCの知識漏洩防止）
    desk_known = (
        pc_investigated is None
        or "desk" in pc_investigated
        or (char_mgr and pl_id and char_mgr.pc_has_investigated(pl_id, "desk"))
    )
    if current_loc == "study" and _scenario_has_object(scenario_mgr, "desk", "study") and desk_known:
        if flags.get("found_button") and not flags.get("button_pushed"):
            lines.append("【状況】机の隠しボタンは**発見済み**。search/desk は不要。次は push/desk を検討。")
        elif flags.get("desk_searched"):
            if flags.get("desk_research_unlocked"):
                lines.append("【状況】机は一度探索済みだが、時間経過により**再調査可能**。search/desk が有効（ペナルティ付き）。")
            else:
                fail_turn = flags.get("desk_first_fail_turn")
                re_after = scenario_mgr.get_object_info("study", "desk").get("re_search_after_turns", 2)
                turns_since = (scenario_mgr.turn_counter - fail_turn) if fail_turn is not None else 0
                if fail_turn is not None and turns_since < re_after:
                    remaining = re_after - turns_since
                    alt = "iron_door" if _scenario_has_object(scenario_mgr, "iron_door", "study") else "別オブジェクト"
                    lines.append(
                        f"【⚠️探索禁止】机（desk）は**探索済み**。search/desk は**今は禁止**（あと約{remaining}ターンで再調査可能）。"
                        f" {alt} への別行動を検討せよ。"
                    )
                else:
                    lines.append("【状況】机の再調査が可能になったはず。KPの示唆を確認し、search/desk で再挑戦できる。")
        if flags.get("door_opened") and _scenario_has_object(scenario_mgr, "iron_door", "study"):
            lines.append("【状況】鉄の扉は開いている。move/hallway が可能。")

    if current_loc == "hallway" and _scenario_object_exists_anywhere(scenario_mgr, "wall_panel"):
        if flags.get("trapdoor_found"):
            visit_secret = flags.get("visit_secret_room", 0)
            if visit_secret >= 2 and not flags.get("ladder_searched"):
                lines.append(
                    "【⚠️ループ警告】地下室と廊下の往復は無意味。"
                    "トラップドアは**戻り口**のみ。脱出は basement の escape_ladder を search → climb。"
                )
            else:
                lines.append("【状況】隠しトラップドアは発見済み。明示的に降りる意思があるときのみ move/secret_room。")
        else:
            lines.append("【状況】床板（wall_panel）をまだ調べていなければ search/wall_panel を検討。")

    if current_loc == "secret_room" and _scenario_has_object(scenario_mgr, "escape_ladder", "secret_room"):
        lines.append("【状況】最終エリア。トラップドア（hallway）は**戻り口**であり脱出ルートではない。")
        if flags.get("ladder_searched"):
            lines.append("【状況】はしごは調査済み。action: climb / target: escape_ladder で脱出せよ。")
        else:
            lines.append("【状況】天井の escape_ladder を search し、問題なければ climb でクリア。")

    if current_loc == "altar_room" and _scenario_has_object(scenario_mgr, "glowing_idol", "altar_room"):
        if not scenario_mgr.is_room_entry_san_due(current_loc):
            parts_note = "【状況】祭壇の間への進入時SANは**処理済み**（部屋全体の恐怖は既に正気を試している）。"
            lines.append(parts_note)
        if flags.get("gate_opened"):
            lines.append("【状況】鉄格子は開放済み。先の闇へ進める。")
        elif flags.get("gate_weakness_found"):
            lines.append("【状況】鉄格子の弱点（下部ヒンジ）を把握済み。`kick` / `break` / `push` + `iron_gate` で容易に開けられる。")
        if flags.get("remains_searched") and not flags.get("gate_weakness_found"):
            lines.append("【状況】白骨死体は調査済みだが手記は読めなかった。別ルートを検討せよ。")
        elif not flags.get("remains_searched") and _scenario_has_object(scenario_mgr, "skeletal_remains", "altar_room"):
            lines.append("【状況】隅の白骨死体（`skeletal_remains`）を search すれば手がかりがあるかもしれない。")
        if not flags.get("crack_inspected") and _scenario_has_object(scenario_mgr, "crack_in_the_wall", "altar_room"):
            lines.append("【状況】壁の亀裂（`crack_in_the_wall`）を inspect すると別の恐怖に直面するかもしれない。")
        if _idol_investigation_attempted(scenario_mgr):
            lines.append("【⚠️偶像調査済み】`glowing_idol` への通常 search/inspect はブロック。上記の別ルートを優先せよ。")

    if current_loc == "corbitt_ground_floor":
        lines.extend(_build_corbitt_ground_floor_focus_lines(scenario_mgr))

    if current_loc == "boston_globe" and flags.get("artie_reference_room_access_granted"):
        ref = "reference_room_clipping_files"
        if _scenario_has_object(scenario_mgr, ref, current_loc):
            if not (
                scenario_mgr._is_target_investigated(ref)
                and not scenario_mgr._is_research_reopened(ref)
            ):
                lines.append(
                    "【最優先】参考資料室の許可は取得済み。"
                    f"`search` / `{ref}`（切り抜きファイル）を調査せよ。"
                    "不在の保管記録係への talk や、許可済みアーティへの再交渉は不要。"
                )

    recommended = _build_pl_recommended_action(scenario_mgr, current_loc)
    if recommended:
        lines.append(recommended)
    if not lines:
        return ""
    return "【シナリオ状況メモ（システム確定情報・厳守）】\n" + "\n".join(f"- {line}" for line in lines) + "\n"


def _corbitt_ground_floor_priority_ids(scenario_mgr):
    """1階で先に調べるべきオブジェクトID（未調査のみ）。"""
    ids = []
    for item in CORBITT_GROUND_FLOOR_FOCUS:
        oid = item["object_id"]
        if not _scenario_has_object(scenario_mgr, oid, "corbitt_ground_floor"):
            continue
        if scenario_mgr._is_target_investigated(oid) and not scenario_mgr._is_research_reopened(oid):
            continue
        ids.append(oid)
    return ids


def _build_corbitt_ground_floor_focus_lines(scenario_mgr):
    """屋敷1階で雑談へ逃げないよう、調べる対象を明示する。"""
    lines = [
        "【最優先・屋敷1階】会話より室内の調査。調べる対象は次の2つ:",
        "居間のガラクタ・家具（`living_room_clutter` / 別名 `living_room_junk`）",
        "地下室へのドア（`basement_door`）",
        "talk の連打は禁止。search / inspect（必要なら break/force）で進め。",
    ]
    for item in CORBITT_GROUND_FLOOR_FOCUS:
        oid = item["object_id"]
        if not _scenario_has_object(scenario_mgr, oid, "corbitt_ground_floor"):
            continue
        name = item["label"]
        if scenario_mgr._is_target_investigated(oid) and not scenario_mgr._is_research_reopened(oid):
            lines.append(f"【調査済み】{name}（`{oid}`）は確認済み。別対象へ。")
        else:
            alias = item["aliases"][0] if item.get("aliases") else oid
            extra = f" / 別名 `{alias}`" if alias != oid else ""
            lines.append(f"【未調査】{name}（`{oid}`{extra}）を search / inspect。")
    return lines


def _build_corbitt_exterior_recommended_action(scenario_mgr):
    """外観: 未入館なら入口、入館済みなら1階へ。調査済み search の繰り返しを避ける。"""
    flags = scenario_mgr.flags or {}
    if flags.get("corbitt_house_entered"):
        exits = scenario_mgr.get_available_exits("corbitt_exterior") or []
        if any(str(e.get("id") or "") == "corbitt_ground_floor" for e in exits):
            return (
                "【推奨次アクション・最優先】action: move / target: corbitt_ground_floor"
                "（正面玄関から屋敷の1階へ入る）。近所へ戻らないこと。"
            )
        return (
            "【推奨次アクション】入口は開いている。`move` / `corbitt_ground_floor` で屋敷内へ。"
        )
    entry = pick_corbitt_exterior_entry_action(scenario_mgr)
    if not entry:
        return ""
    action = entry.get("action") or "use"
    skill = str(entry.get("skill") or "").strip()
    skill_note = f" / skill: {skill}" if skill else ""
    if action in ("search", "inspect"):
        return (
            f"【推奨次アクション・最優先】action: {action} / target: corbitt_house{skill_note}"
            "（屋敷の入口・鍵穴・裏口の手がかりを確認）。近所へ戻って往復しないこと。"
        )
    return (
        f"【推奨次アクション・最優先】action: {action} / target: corbitt_house{skill_note}"
        "（鍵を使う / 扉をこじ開けて入口を開く）。"
        "屋敷は調査済み。再 search や近所への move は禁止。入口を開けてから1階へ。"
    )


def _build_corbitt_ground_floor_recommended_action(scenario_mgr):
    """1階の次アクション。居間調査 → 地下室扉の順。"""
    flags = scenario_mgr.flags or {}
    clutter = "living_room_clutter"
    door = "basement_door"
    if (
        _scenario_has_object(scenario_mgr, clutter, "corbitt_ground_floor")
        and not (
            scenario_mgr._is_target_investigated(clutter)
            and not scenario_mgr._is_research_reopened(clutter)
        )
        and not flags.get("living_room_investigated")
    ):
        return (
            "【推奨次アクション・最優先】action: search / target: living_room_clutter / skill: 目星"
            "（居間のガラクタ・家具。別名 `living_room_junk`）。"
            "NPCへの雑談より室内調査を優先。"
        )
    if (
        _scenario_has_object(scenario_mgr, door, "corbitt_ground_floor")
        and not flags.get("basement_accessible")
        and not flags.get("basement_door_unlocked")
    ):
        return (
            "【推奨次アクション・最優先】action: search / target: basement_door / skill: 目星"
            "（または break / force）。地下室へのドアを調べて開けよ。"
        )
    return ""


def _build_pl_recommended_action(scenario_mgr, current_loc):
    """次に取るべき行動を明示（シナリオ内の実オブジェクトから推奨）。"""
    if not scenario_mgr:
        return ""
    flags = scenario_mgr.flags

    # コービット外観は枯渇 move より入口／入館を優先（近所往復を防ぐ）
    if current_loc == "corbitt_exterior":
        rec = _build_corbitt_exterior_recommended_action(scenario_mgr)
        if rec:
            return rec

    # 調査枯渇: search より解禁済みロケーションへの move を最優先
    if should_apply_location_exhausted_move(scenario_mgr, current_loc):
        exits = scenario_mgr.get_available_exits(current_loc) or []
        by_id = {str(e.get("id") or ""): e for e in exits if e.get("id")}
        preferred = LOCATION_FORCED_PROGRESS_PREFERENCE.get(current_loc) or ()
        for dest_id in preferred:
            if dest_id in by_id:
                dest = by_id[dest_id]
                return (
                    f"【推奨次アクション・最優先】action: move / target: {dest_id}"
                    f"（{dest.get('name', dest_id)} へ）。"
                    "この場所の調査はすべて完了。再 search は禁止。"
                )
        if exits:
            dest = exits[0]
            return (
                f"【推奨次アクション・最優先】action: move / target: {dest['id']}"
                f"（{dest.get('name', dest['id'])} へ）。"
                "この場所の調査はすべて完了。再 search は禁止。"
            )

    if current_loc == "chapel_of_contemplation":
        if flags.get("in_basement"):
            return (
                "【推奨次アクション】地階の未調査対象（骸骨・棚など）を search / inspect。"
                "地上へ戻るなら action: climb / target: rotting_floorboards。"
            )
        if flags.get("floorboards_examined") and not flags.get("in_basement"):
            return (
                "【推奨次アクション・最優先】action: break（または climb / force）"
                " / target: rotting_floorboards。"
                "床板は調査済み。地階へ降りる。push_roll は使わない。"
            )
        if _scenario_has_object(scenario_mgr, "rotting_floorboards", current_loc) and not flags.get(
            "floorboards_examined"
        ):
            return (
                "【推奨次アクション】action: search / target: rotting_floorboards / skill: 目星"
                "（床板の下を確認してから地階へ）。"
            )

    if current_loc == "study" and _scenario_has_object(scenario_mgr, "desk", "study"):
        if flags.get("found_button") and not flags.get("button_pushed"):
            return "【推奨次アクション】action: push / target: desk（隠しボタンを押す）"
        if flags.get("door_opened"):
            return "【推奨次アクション】action: move / target: hallway（開いた鉄扉から廊下へ）"
        if flags.get("desk_research_unlocked"):
            return "【推奨次アクション】action: search / target: desk / skill: 目星（再調査）"
        if flags.get("desk_searched") and not flags.get("desk_research_unlocked"):
            fail_turn = flags.get("desk_first_fail_turn")
            re_after = scenario_mgr.get_object_info("study", "desk").get("re_search_after_turns", 2)
            if fail_turn is not None:
                turns_since = scenario_mgr.turn_counter - fail_turn
                if turns_since < re_after:
                    remaining = re_after - turns_since
                    return (
                        f"【推奨次アクション】あと約{remaining}ターンで机の再調査が可能。"
                        "今は action: wait で待つか、別の対象を検討せよ（search/desk は今は禁止）。"
                    )
            return "【推奨次アクション】action: search / target: desk / skill: 目星（再調査）"
        if not flags.get("desk_searched"):
            return "【推奨次アクション】action: search / target: desk / skill: 目星"

    if current_loc == "hallway" and _scenario_object_exists_anywhere(scenario_mgr, "wall_panel"):
        if flags.get("trapdoor_found"):
            visit_secret = flags.get("visit_secret_room", 0)
            if visit_secret >= 2 and not flags.get("ladder_searched"):
                return "【推奨次アクション】地下室へ戻るのではなく、move/secret_room 後に escape_ladder を search → climb"
            return "【推奨次アクション】action: move / target: secret_room（初回のみ。降りる意思を明示すること）"
        return "【推奨次アクション】action: search / target: wall_panel / skill: 目星"

    if current_loc == "secret_room" and _scenario_has_object(scenario_mgr, "escape_ladder", "secret_room"):
        if flags.get("ladder_searched"):
            return "【推奨次アクション】action: climb / target: escape_ladder（脱出）"
        return "【推奨次アクション】action: search / target: escape_ladder（はしごを調査）"

    if current_loc == "altar_room" and _scenario_has_object(scenario_mgr, "glowing_idol", "altar_room"):
        if flags.get("gate_opened"):
            return "【推奨次アクション】鉄格子は開放済み。先へ進める。"
        if flags.get("gate_weakness_found"):
            return "【推奨次アクション】action: kick / target: iron_gate（弱点を突いて格子を開ける）"
        if not flags.get("remains_searched") and _scenario_has_object(scenario_mgr, "skeletal_remains", "altar_room"):
            return "【推奨次アクション】action: search / target: skeletal_remains / skill: 目星（白骨死体の手記）"
        if not flags.get("crack_inspected") and _scenario_has_object(scenario_mgr, "crack_in_the_wall", "altar_room"):
            return "【推奨次アクション】action: inspect / target: crack_in_the_wall / skill: 目星（壁の亀裂）"
        if _idol_investigation_attempted(scenario_mgr):
            return "【推奨次アクション】action: push / target: iron_gate または kick / break（鉄格子）"
        return "【推奨次アクション】偶像・白骨・亀裂・鉄格子のいずれかを調査せよ"

    if current_loc == "introduction":
        if not flags.get("talked_with_knott"):
            return (
                "【推奨次アクション】action: talk / target: steven_knott"
                "（まず依頼人スティーブン・ノット氏と話し、用件を確認する。"
                "書類の調査より会話を優先）"
            )
        # 移動解禁後は強制せず、_build_introduction_move_nudge の軽い誘導のみ
        return ""

    if current_loc == "boston_globe":
        if flags.get("artie_reference_room_access_granted"):
            ref = "reference_room_clipping_files"
            if _scenario_has_object(scenario_mgr, ref, "boston_globe"):
                if not (
                    scenario_mgr._is_target_investigated(ref)
                    and not scenario_mgr._is_research_reopened(ref)
                ):
                    return (
                        "【必須アクション・最優先】action: search / target: reference_room_clipping_files"
                        " / skill: 目星\n"
                        "許可は取得済み。talk / persuade / ルース探しはすべて無効。"
                        "今このターンで切り抜きファイルを調査すること。"
                    )
        if not flags.get("artie_introduced"):
            return (
                "【推奨次アクション】action: talk / target: globe_receptionist"
                "（受付デスクを調べるのではなく、受付の人に話しかけて"
                "アーティ・ウィルモットを呼び出してもらう。対話最優先）"
            )
        return (
            "【推奨次アクション】action: persuade / target: artie_wilmott / skill: 説得"
            "（または intimidate / fast_talk）を**1回だけ**試せ。"
            "失敗・拒否されたら同じ交渉を繰り返さず、"
            f"`move` / `central_library` または `move` / `{HOUSE_ENTRY_LOCATION_ID}`"
            "（コービット屋敷）へ進め。すべての資料を揃える必要はない。"
        )

    if current_loc == "corbitt_ground_floor":
        rec = _build_corbitt_ground_floor_recommended_action(scenario_mgr)
        if rec:
            return rec

    # 現在地に未紹介でないNPCがいれば、調査より会話を先に勧める
    npcs_here = (scenario_mgr.get_location_info(current_loc) or {}).get("npcs_present") or []
    for npc_id in npcs_here:
        return (
            f"【推奨次アクション】action: talk / target: {npc_id}"
            f"（この場所では人と話すことが最優先。物を漁る前に対話する）"
        )

    for obj_id, obj in _location_objects(scenario_mgr, current_loc).items():
        if scenario_mgr._is_target_investigated(obj_id) and not scenario_mgr._is_research_reopened(obj_id):
            continue
        actions = obj.get("usable_actions") or ["search"]
        action = "search" if "search" in actions else actions[0]
        skill_note = " / skill: 目星" if action in ("search", "inspect") else ""
        name = obj.get("name", obj_id)
        return f"【推奨次アクション】action: {action} / target: {obj_id}{skill_note}（{name}）"

    exits = scenario_mgr.get_available_exits(current_loc)
    if exits:
        dest = exits[0]
        return f"【推奨次アクション】action: move / target: {dest['id']}（{dest['name']} へ）"
    return ""


def _introduction_move_unlocked(scenario_mgr):
    """導入シーンで次の調査先への移動が解禁されているか。"""
    if not scenario_mgr or scenario_mgr.location != "introduction":
        return False
    flags = scenario_mgr.flags
    return bool(
        flags.get("talked_with_knott")
        or (flags.get("knott_letter_read") and flags.get("knott_memo_read"))
    )


def _build_introduction_move_nudge(scenario_mgr, current_loc):
    """導入完了後に PL へ次の調査先を軽く示す（強制しない）。"""
    if current_loc != "introduction" or not _introduction_move_unlocked(scenario_mgr):
        return ""
    exits = scenario_mgr.get_available_exits(current_loc)
    if not exits:
        return ""
    dest_lines = ", ".join(
        f"`{exit_info['id']}`（{exit_info.get('name', exit_info['id'])}）"
        for exit_info in exits[:4]
    )
    return f"""
【システム通知（任意）】
依頼の概要は把握できています。事務所に残っても構いません。
手がかりを増やすなら、次も候補です: {dest_lines}
（メモの新聞記事を追うなら `move` / target: `boston_globe`）
"""


def _append_stagnation_hint_log(state, hint):
    """マイルドな膠着ヒントを OOC ログへ1回だけ載せる（行動は強制しない）。"""
    hint = str(hint or "").strip()
    if not hint or not state:
        return
    text = hint if hint.startswith("[システム]") or hint.startswith("【") else f"[システム] {hint}"
    logs = state.setdefault("all_events_log", [])
    for entry in logs[-10:]:
        existing = str(entry.get("text") or "")
        meta = entry.get("meta") or {}
        if meta.get("stagnation_hint") and (existing == text or hint in existing):
            return
    logs.append({
        "channel": "OOC",
        "location": "all",
        "secret_to": None,
        "text": text,
        "meta": {"stagnation_hint": True, "mild": True},
    })


def _maybe_set_context_stagnation_hint(state, scenario_mgr, state_mgr):
    """膠着中なら、現在ロケーション／原因に応じた具体ヒントをセットする。"""
    if not scenario_mgr or not state:
        return
    tracker = (state_mgr.stagnation_tracker or {}) if state_mgr else {}
    streak = int(tracker.get("streak") or state.get("stagnation_streak") or 0)
    if streak < STAGNATION_HINT_TURNS:
        return
    current_loc = (
        state.get("current_loc")
        or getattr(scenario_mgr, "location", "")
        or ""
    )
    # 導入は移動解禁後のみ具体ヒントを出す
    if current_loc == "introduction" and not _introduction_move_unlocked(scenario_mgr):
        return
    from GameStateManager import GameStateManager
    raw_reason = state.get("stagnation_cause") or tracker.get("last_reason") or ""
    if raw_reason in ("chat_only", "conversation_loop", "repeat_fail", "fail_start", "signature_switch", ""):
        cause = GameStateManager.classify_stagnation_cause(
            raw_reason or tracker.get("last_reason") or "lost_options",
            tracker.get("repeat_key"),
        )
    else:
        cause = raw_reason or "lost_options"
    hint = build_reason_stagnation_hint(
        cause,
        scenario_mgr,
        current_loc,
        char_mgr=None,
        pl_id=state.get("pl_id") or state.get("active_pc_id"),
        repeat_key=tracker.get("repeat_key"),
        fallback=STAGNATION_STANDARD_PL_HINT,
    )
    if not hint:
        return
    state["stagnation_cause"] = cause
    state["stagnation_pl_hint"] = hint
    _append_stagnation_hint_log(state, STAGNATION_MILD_NOTICE)


def _maybe_set_introduction_stagnation_hint(state, scenario_mgr, state_mgr):
    """後方互換: 場面依存ヒントへ委譲。"""
    _maybe_set_context_stagnation_hint(state, scenario_mgr, state_mgr)


def _combined_pl_intent_text(dialogue, pl_ooc):
    return f"{dialogue or ''} {pl_ooc or ''}"


def _text_has_any(text, keywords):
    return any(k in text for k in keywords)


def _texts_overlap(a, b, min_len=12):
    """OOC と IC が同一文面かの簡易判定。"""
    a = (a or "").strip()
    b = (b or "").strip()
    if not a or not b:
        return False
    if a == b:
        return True
    shorter, longer = (a, b) if len(a) <= len(b) else (b, a)
    return len(shorter) >= min_len and shorter in longer


# 日本語表記・別名 → シナリオ内部ID
_TARGET_ALIAS_TO_ID = {
    "机": "desk",
    "木製の机": "desk",
    "引き出し": "desk",
    "desk": "desk",
    "鉄扉": "iron_door",
    "鉄の扉": "iron_door",
    "iron_door": "iron_door",
    "door": "iron_door",
    "床板": "wall_panel",
    "浮き上がった床板": "wall_panel",
    "wall_panel": "wall_panel",
    "肖像画": "portrait",
    "portrait": "portrait",
    "はしご": "escape_ladder",
    "脱出用のはしご": "escape_ladder",
    "梯子": "escape_ladder",
    "escape_ladder": "escape_ladder",
    "紋章": "sigil",
    "壁の紋章": "sigil",
    "sigil": "sigil",
    "書斎": "study",
    "study": "study",
    "廊下": "hallway",
    "暗い廊下": "hallway",
    "hallway": "hallway",
    "地下室": "secret_room",
    "隠し地下室": "secret_room",
    "secret_room": "secret_room",
    "glowing_idol": "glowing_idol",
    "偶像": "glowing_idol",
    "iron_gate": "iron_gate",
    "鉄格子": "iron_gate",
    "skeletal_remains": "skeletal_remains",
    "白骨": "skeletal_remains",
    "白骨死体": "skeletal_remains",
    "死体": "skeletal_remains",
    "crack_in_the_wall": "crack_in_the_wall",
    "亀裂": "crack_in_the_wall",
    "壁の亀裂": "crack_in_the_wall",
    "受付": "globe_receptionist",
    "受付係": "globe_receptionist",
    "受付の女性": "globe_receptionist",
    "受付の方": "globe_receptionist",
    "フロント": "globe_receptionist",
    "窓口": "globe_receptionist",
    "reception": "globe_receptionist",
    "reception_desk": "globe_receptionist",
    "globe_receptionist": "globe_receptionist",
    "アーティ": "artie_wilmott",
    "アーティ氏": "artie_wilmott",
    "ウィルモット": "artie_wilmott",
    "編集者": "artie_wilmott",
    "artie": "artie_wilmott",
    "artie_wilmott": "artie_wilmott",
    "参考資料室": "reference_room_clipping_files",
    "資料室": "reference_room_clipping_files",
    "切り抜き": "reference_room_clipping_files",
    "切り抜きファイル": "reference_room_clipping_files",
    "reference_room": "reference_room_clipping_files",
    "reference_room_clipping_files": "reference_room_clipping_files",
    "公文書館": "hall_of_records",
    "記録保管所": "hall_of_records",
    "hall_of_records": "hall_of_records",
    "living_room_junk": "living_room_clutter",
    "living_room_furniture": "living_room_clutter",
    "居間のガラクタ": "living_room_clutter",
    "リビングの散乱した荷物": "living_room_clutter",
    "地下室へのドア": "basement_door",
    "地下室への扉": "basement_door",
    "地下室の扉": "basement_door",
}


CORBITT_GROUND_FLOOR_FOCUS = (
    {
        "object_id": "living_room_clutter",
        "aliases": ("living_room_junk", "living_room_furniture"),
        "label": "居間のガラクタ・家具",
    },
    {
        "object_id": "basement_door",
        "aliases": ("basement_door",),
        "label": "地下室へのドア",
    },
)


def _alias_maps_to_existing_target(mapped_id, scenario_mgr, current_loc=None, char_mgr=None):
    """エイリアス解決結果が、現在シナリオに実在する対象か。"""
    if not mapped_id:
        return False
    mid = str(mapped_id)
    if char_mgr and find_npc_id_by_target(char_mgr, mid):
        return True
    if not scenario_mgr:
        return False
    if mid in scenario_mgr.get_all_location_ids():
        return True
    if current_loc and mid in _location_objects(scenario_mgr, current_loc):
        return True
    # 現在地の npcs_present（char_mgr 無しでも NPC ID を実在扱い）
    if current_loc and hasattr(scenario_mgr, "get_npcs_present"):
        if mid in set(scenario_mgr.get_npcs_present(current_loc) or []):
            return True
    if hasattr(scenario_mgr, "get_location_info"):
        for loc_id in scenario_mgr.get_all_location_ids() or []:
            present = (scenario_mgr.get_location_info(loc_id) or {}).get("npcs_present") or []
            if mid in present:
                return True
    return _scenario_object_exists_anywhere(scenario_mgr, mid)


def _redirect_preintro_artie_target(target, flags, current_loc):
    """
    受付紹介前にアーティ／切り抜きへ直接行った対象を受付 talk へ寄せる。
    戻り値: リダイレクト後 target（不要なら None）
    """
    if str(current_loc or "") != "boston_globe":
        return None
    flags = flags or {}
    if flags.get("artie_introduced"):
        return None
    tid = str(target or "").strip()
    if tid in ("artie_wilmott", "reference_room_clipping_files"):
        return "globe_receptionist"
    return None


def _infer_boston_globe_social_target(target, intent, flags, current_loc):
    """
    グローブで target 空／代名詞のとき、セリフから受付を推定する。
    未紹介時にアーティ呼び出し意図があれば受付へ。
    """
    if str(current_loc or "") != "boston_globe":
        return target
    tid = str(target or "").strip()
    text = str(intent or "")
    flags = flags or {}

    reception_markers = (
        "受付", "globe_receptionist", "レセプション", "reception",
        "フロント", "窓口", "デスクの", "彼女",
    )
    artie_markers = ("アーティ", "artie", "ウィルモット", "編集者")

    if tid in ("", "彼女", "彼", "あの人", "その人", "女性", "お姉さん"):
        if any(m in text for m in reception_markers):
            return "globe_receptionist"
        if not flags.get("artie_introduced") and any(m in text for m in artie_markers):
            return "globe_receptionist"
        if "globe_receptionist" in text.replace(" ", ""):
            return "globe_receptionist"
    return target


def normalize_action_target(target, scenario_mgr=None, current_loc=None, char_mgr=None):
    """PL/LLM が返した target をシナリオ内部IDへ統一する（未定義IDへの誤マップを防ぐ）。

    解決優先順位:
      1. 完全一致する内部ID（現在地オブジェクト／NPC／ロケーション）
      2. 現在地に存在する NPC またはオブジェクト（別名含む）
      3. 現在地の別名・日本語名・英語名
      4. シナリオ全体に存在する対象
      5. グローバル別名辞書（最終手段）
    """
    raw = str(target or "").strip()
    if not raw:
        return ""

    lower = raw.lower()

    # 1) 完全一致: ロケーションID
    if scenario_mgr and lower in scenario_mgr.get_all_location_ids():
        return lower

    # 1-2) 完全一致: 現在地オブジェクトID / 在場NPC ID
    if scenario_mgr and current_loc:
        objects = _location_objects(scenario_mgr, current_loc)
        if lower in objects:
            return lower
        if hasattr(scenario_mgr, "get_npcs_present"):
            present = set(scenario_mgr.get_npcs_present(current_loc) or [])
            if raw in present or lower in {str(x).lower() for x in present}:
                for pid in present:
                    if str(pid) == raw or str(pid).lower() == lower:
                        return str(pid)

    # 2) 現在地 NPC を名前・別名で優先解決（グローバル探索より先）
    if char_mgr and scenario_mgr and current_loc and hasattr(scenario_mgr, "get_npcs_present"):
        present = list(scenario_mgr.get_npcs_present(current_loc) or [])
        for pid in present:
            char = (char_mgr.characters or {}).get(pid) or {}
            profile = char.get("profile") or {}
            if not profile.get("is_npc"):
                continue
            name = str(profile.get("name") or "")
            aliases = [str(a) for a in (profile.get("aliases") or []) if a]
            tokens = [pid, name] + aliases
            for token in tokens:
                if not token:
                    continue
                if raw == token or lower == str(token).lower():
                    return pid
                if len(raw) >= 2 and (raw in token or token in raw):
                    return pid

    # 3) 現在地オブジェクトの別名・表示名
    if scenario_mgr and current_loc:
        objects = _location_objects(scenario_mgr, current_loc)
        for obj_id, obj in objects.items():
            if lower == str(obj_id).lower():
                return obj_id
            aliases = [str(a).lower() for a in (obj.get("aliases") or []) if a]
            if lower in aliases:
                return obj_id
            obj_name = str(obj.get("name", "") or "")
            if obj_name and (raw == obj_name or obj_name in raw or raw in obj_name):
                return obj_id

    # 4) シナリオ全体の NPC（ID/名前）— 現在地に無い場合のみ
    if char_mgr:
        npc_id = find_npc_id_by_target(char_mgr, raw)
        if npc_id:
            return npc_id

    if scenario_mgr:
        # 他地点のオブジェクト完全一致ID
        for loc_id in scenario_mgr.get_all_location_ids():
            if lower in _location_objects(scenario_mgr, loc_id):
                return lower

    mapped = None
    if raw in _TARGET_ALIAS_TO_ID:
        mapped = _TARGET_ALIAS_TO_ID[raw]
    elif lower in _TARGET_ALIAS_TO_ID:
        mapped = _TARGET_ALIAS_TO_ID[lower]

    if mapped:
        if not scenario_mgr or _alias_maps_to_existing_target(
            mapped, scenario_mgr, current_loc, char_mgr=char_mgr,
        ):
            return mapped
        # シナリオに無いエイリアス（例: 他シナリオの「鉄格子」「引き出し」）は破棄
        return ""

    # 現在地が書斎で鉄扉が実在するときの「扉」は鉄扉
    if (
        current_loc == "study"
        and raw in ("扉", "ドア")
        and _scenario_has_object(scenario_mgr, "iron_door", "study")
    ):
        return "iron_door"

    if scenario_mgr:
        for loc_id in scenario_mgr.get_all_location_ids():
            loc = scenario_mgr.get_location_info(loc_id)
            loc_name = loc.get("name", "")
            if loc_name and (raw == loc_name or loc_name in raw or raw in loc_name):
                return loc_id
            for obj_id, obj in loc.get("objects", {}).items():
                obj_name = obj.get("name", "")
                if obj_name and (raw == obj_name or obj_name in raw or raw in obj_name):
                    return obj_id
        # シナリオ内で解決できないターゲットは空にする（幻覚オブジェクト対策）
        return ""

    return lower


def normalize_pc_action(pc_action, scenario_mgr=None, current_loc=None, char_mgr=None):
    """pc_action の action/target をシステム内部形式へ正規化する。"""
    if not pc_action:
        return pc_action
    normalized = dict(pc_action)
    normalized["action"] = str(normalized.get("action", "wait") or "wait").lower()
    skill = str(normalized.get("skill", "") or "")
    normalized["target"] = normalize_action_target(
        normalized.get("target", ""), scenario_mgr, current_loc, char_mgr=char_mgr,
    )
    if (
        normalized["action"] not in ("search", "inspect")
        and not is_social_action(normalized["action"], skill)
    ):
        normalized["skill"] = ""
    else:
        normalized["skill"] = skill
    if normalized["action"] == "wait":
        # 待機行動に過去の発話や対象が残ると後段判定を汚すため明示クリア
        normalized["target"] = None
        normalized["message"] = None
        normalized["dialogue"] = None
    return normalized


def normalize_game_action_targets(state, scenario_mgr, current_loc=None, char_mgr=None):
    """保留中アクション・ロードデータ内の target を内部IDへ揃える。"""
    if not state or not scenario_mgr:
        return state
    loc = current_loc or state.get("current_loc") or scenario_mgr.location
    last = state.get("last_pl_action")
    if last:
        state["last_pl_action"] = normalize_pc_action(last, scenario_mgr, loc, char_mgr=char_mgr)
    pending = state.get("pending_push_roll")
    if isinstance(pending, dict) and pending.get("target"):
        pending = dict(pending)
        pending["target"] = normalize_action_target(
            pending["target"], scenario_mgr, loc, char_mgr=char_mgr,
        )
        state["pending_push_roll"] = pending
    pending_luck = state.get("pending_luck_burn")
    if isinstance(pending_luck, dict) and pending_luck.get("target"):
        pending_luck = dict(pending_luck)
        pending_luck["target"] = normalize_action_target(
            pending_luck["target"], scenario_mgr, loc, char_mgr=char_mgr,
        )
        state["pending_luck_burn"] = pending_luck

    logs = state.get("all_events_log") or []
    for entry in logs:
        meta = entry.get("meta") or {}
        if not meta.get("needs_system") or meta.get("system_processed"):
            continue
        meta = dict(meta)
        if not meta.get("target") and char_mgr:
            inferred = _infer_talk_target_from_log_entry(entry, char_mgr)
            if inferred:
                meta["target"] = inferred
        normalized = normalize_pc_action({
            "action": meta.get("action_id") or meta.get("action") or "wait",
            "target": meta.get("target", ""),
            "skill": meta.get("skill", ""),
            "skill_proposal_reason": meta.get("skill_proposal_reason", ""),
        }, scenario_mgr, loc, char_mgr=char_mgr)
        meta["action_id"] = normalized.get("action", "wait")
        meta["target"] = normalized.get("target", "")
        meta["skill"] = normalized.get("skill", "")
        entry["meta"] = meta

    pending_entry = find_pending_pl_action_entry(logs, char_mgr=char_mgr)
    if pending_entry:
        meta = pending_entry.get("meta") or {}
        last_action = dict(state.get("last_pl_action") or {})
        state["last_pl_action"] = normalize_pc_action({
            "action": meta.get("action_id") or meta.get("action") or "wait",
            "target": meta.get("target", ""),
            "skill": meta.get("skill", ""),
            "skill_proposal_reason": meta.get("skill_proposal_reason", ""),
            "message": last_action.get("message", ""),
            "dialogue": last_action.get("dialogue", ""),
        }, scenario_mgr, loc, char_mgr=char_mgr)
    return state


def _npc_appears_in_scenario(scenario_mgr, npc_id) -> bool:
    """シナリオのいずれかのロケーションに配置されている NPC か。"""
    if not scenario_mgr or not npc_id:
        return False
    for loc_id in scenario_mgr.get_all_location_ids():
        if scenario_mgr.is_npc_at_location(npc_id, loc_id):
            return True
    return False


def _resolve_talk_target_from_intent(intent, char_mgr=None, scenario_mgr=None, current_loc=""):
    """セリフから対話対象 NPC を推定。現在地／シナリオ内の NPC を優先する。"""
    if not char_mgr:
        return ""
    present = []
    if scenario_mgr and hasattr(scenario_mgr, "get_npcs_present"):
        present = list(scenario_mgr.get_npcs_present(current_loc) or [])
    inferred = find_npc_id_from_intent_text(char_mgr, intent, prefer_ids=present)

    return inferred


def _infer_talk_target_from_log_entry(entry, char_mgr):
    """talk 行動で target が空のとき、ログ文面から NPC ID を推定する。"""
    meta = entry.get("meta") or {}
    if str(meta.get("action_id") or meta.get("action") or "").lower() != "talk":
        return ""
    if meta.get("target"):
        return meta.get("target")
    text = str(entry.get("text", "") or "")
    return find_npc_id_from_intent_text(char_mgr, text) or ""


def normalize_session_action_targets(session_state, scenario_mgr, char_mgr=None):
    """Streamlit session_state 上の action target を内部IDへ揃える。"""
    if not scenario_mgr:
        return
    wrapper = {
        "last_pl_action": session_state.get("last_pl_action"),
        "pending_push_roll": session_state.get("pending_push_roll"),
        "pending_luck_burn": session_state.get("pending_luck_burn"),
        "current_loc": session_state.get("current_loc"),
        "all_events_log": session_state.get("all_events_log", []),
    }
    normalize_game_action_targets(wrapper, scenario_mgr, char_mgr=char_mgr)
    session_state.last_pl_action = wrapper.get("last_pl_action")
    session_state.pending_push_roll = wrapper.get("pending_push_roll")
    session_state.pending_luck_burn = wrapper.get("pending_luck_burn")
    session_state.all_events_log = wrapper.get("all_events_log", session_state.get("all_events_log", []))


def _resolve_target_label(scenario_mgr, current_loc, target_id):
    """オブジェクトID / 場所ID を表示用の日本語名に変換する。"""
    if not target_id:
        return "周囲"
    if scenario_mgr:
        obj = scenario_mgr.get_object_info(current_loc, target_id)
        if obj.get("name"):
            return obj["name"]
        loc = scenario_mgr.get_location_info(target_id)
        if loc.get("name"):
            return loc["name"]
    return target_id


def _sanitize_pc_dialogue(dialogue, scenario_mgr=None, current_loc=None):
    """ICセリフ内のオブジェクトID / 場所ID を日本語名に置換する。"""
    text = (dialogue or "").strip()
    if not text or not scenario_mgr:
        return text
    for loc_id in scenario_mgr.get_all_location_ids():
        if loc_id in text:
            label = scenario_mgr.get_location_info(loc_id).get("name", loc_id)
            text = re.sub(re.escape(loc_id), label, text, flags=re.IGNORECASE)
    if current_loc:
        for obj_id, obj in scenario_mgr.get_location_info(current_loc).get("objects", {}).items():
            if obj_id in text:
                label = obj.get("name", obj_id)
                text = re.sub(re.escape(obj_id), label, text, flags=re.IGNORECASE)
    return text


IDOL_TARGET_IDS = frozenset({"glowing_idol"})
ALTAR_ALTERNATE_ACTIONS = (
    ("search", "skeletal_remains"),
    ("inspect", "crack_in_the_wall"),
    ("push", "iron_gate"),
)


def _force_iron_gate_action(scenario_mgr, current_loc):
    """祭壇シナリオ向け: 鉄格子への物理アクションを返す（鉄格子が無い場合は空行動）。"""
    if not _scenario_has_object(scenario_mgr, "iron_gate", current_loc):
        for obj_id, obj in _location_objects(scenario_mgr, current_loc).items():
            if scenario_mgr._is_target_investigated(obj_id) and not scenario_mgr._is_research_reopened(obj_id):
                continue
            actions = obj.get("usable_actions") or ["search"]
            return (("search" if "search" in actions else actions[0]), obj_id)
        return "wait", ""
    objects = _location_objects(scenario_mgr, current_loc)
    gate_actions = objects.get("iron_gate", {}).get("usable_actions", ["push", "break"])
    if "break" in gate_actions:
        return "break", "iron_gate"
    return "push", "iron_gate"


def _pick_altar_alternate_action(scenario_mgr):
    """偶像執着回避: 未調査の探索対象へ優先的に誘導する（対象が実在する場合のみ）。"""
    if not scenario_mgr:
        return "wait", ""
    for action, target in ALTAR_ALTERNATE_ACTIONS:
        if not _scenario_has_object(scenario_mgr, target, scenario_mgr.location):
            continue
        if not scenario_mgr._is_target_investigated(target):
            return action, target
        if scenario_mgr._is_research_reopened(target):
            return action, target
    return _force_iron_gate_action(scenario_mgr, scenario_mgr.location)


def _is_idol_target(target):
    return str(target or "").lower() in IDOL_TARGET_IDS


def _ooc_signals_abandon_idol_for_alternate(pl_ooc, dialogue=""):
    """OOC が偶像から離れ、別対象（鉄格子等）へ移る方針を示しているか。"""
    text = _combined_pl_intent_text(dialogue, pl_ooc)
    if _text_has_any(text, ("鉄格子", "格子", "iron_gate", "ゲート")):
        return True
    if _text_has_any(text, ("白骨", "死体", "skeletal_remains", "手記")):
        return True
    if _text_has_any(text, ("亀裂", "crack_in_the_wall", "壁")):
        return True
    futile_signals = (
        "これ以上", "無意味", "可能性は低い", "見つける可能性は低",
        "もう一度", "避けた", "危険", "執着", "調べ尽く", "後戻り",
        "慎重に", "試すのも", "開けて",
    )
    return _text_has_any(text, futile_signals)


def _idol_investigation_attempted(scenario_mgr):
    if not scenario_mgr or not _scenario_object_exists_anywhere(scenario_mgr, "glowing_idol"):
        return False
    flags = scenario_mgr.flags
    return bool(
        flags.get("idol_inspected")
        or flags.get("idol_failed")
        or scenario_mgr._is_target_investigated("glowing_idol")
    )


def _count_trailing_failed_action_attempts(all_events_log, action_id="search", target="glowing_idol"):
    """同一 action/target の連続失敗回数をタイムライン末尾から数える。"""
    count = 0
    saw_matching = False
    for entry in reversed(all_events_log or []):
        text = str(entry.get("text", ""))
        if not text.startswith("システム:"):
            continue
        meta = entry.get("meta") or {}
        entry_action = str(meta.get("action_id", "")).lower()
        entry_target = str(meta.get("target", "")).lower()
        if entry_action != str(action_id).lower() or entry_target != str(target).lower():
            if saw_matching:
                break
            continue
        saw_matching = True
        if "失敗" in text or "プッシュロール失敗" in text:
            count += 1
        else:
            break
    return count


def _build_pl_repeat_failure_penalty(
    all_events_log, action_id="search", target="glowing_idol", min_failures=3, scenario_mgr=None,
):
    """同一行動の連続失敗が閾値以上なら、PL向け強烈ペナルティを返す。"""
    if _count_trailing_failed_action_attempts(all_events_log, action_id, target) < min_failures:
        return ""
    examples = _format_alternate_object_examples(
        scenario_mgr, exclude={str(target or "")},
    )
    return f"""
【システム強制警告・行動慣性カットアウト】
あなたは同じ行動（`{action_id}` / `{target}`）を繰り返し、連続して失敗しています。
あなたは同じ行動を繰り返す壊れたレコードのようになっています。この行動はルール上、システムに完全に拒否されます。
今すぐ他の場所・他のオブジェクト（例: {examples}）を調べなさい。存在する一覧外の物体を創作しないこと。
`pl_ooc_chat` で方針を述べたなら、`pc_ic_action` も必ず同じ方針に一致させてください。
"""


def _build_kp_altar_room_spotlight_directive(scenario_mgr, location_info=None):
    """祭壇の間: 全オブジェクトを均等に描写させる KP 向け指示。"""
    if not scenario_mgr or scenario_mgr.location != "altar_room":
        return ""
    if not _scenario_has_object(scenario_mgr, "glowing_idol", "altar_room"):
        return ""
    loc = location_info or scenario_mgr.get_location_info("altar_room")
    objects = loc.get("objects", {})
    obj_lines = []
    for obj_id, obj in objects.items():
        name = obj.get("name", obj_id)
        desc = obj.get("description", "")
        actions = ", ".join(obj.get("usable_actions", ["search"]))
        obj_lines.append(f"  - `{obj_id}`（{name}）: {desc} [アクション: {actions}]")
    obj_block = "\n".join(obj_lines) if obj_lines else ""
    return (
        "【祭壇の間・描写バランス（厳守）】\n"
        "部屋の情景を描写する際は、特定の物体だけに偏らず、"
        "以下の**すべての調査対象に均等にスポットライト**を当ててください。\n"
        "一覧に無い物体を追加で創作しないこと。\n"
        f"{obj_block}\n"
    )


def _build_kp_idol_steering_directive(scenario_mgr):
    """偶像調査済み後に KP を多様な探索ルートへ誘導する絶対命令。"""
    if not scenario_mgr or scenario_mgr.location != "altar_room":
        return ""
    if not _scenario_has_object(scenario_mgr, "glowing_idol", "altar_room"):
        return ""
    if not _idol_investigation_attempted(scenario_mgr):
        return _build_kp_altar_room_spotlight_directive(scenario_mgr)
    examples = _format_alternate_object_examples(
        scenario_mgr, loc_id="altar_room", exclude={"glowing_idol"},
    )
    return (
        "【進行役としての絶対命令】探索者は偶像に執着しすぎてゲームが停滞する傾向があります。"
        "キーパーとして描写を行う際は、偶像の描写を最小限に留め、"
        f"次の候補（{examples}）へ視線を向けられるよう、多様な手がかりを均等に示唆してください。"
        "一覧に無い物体を創作しないこと。\n"
        + _build_kp_altar_room_spotlight_directive(scenario_mgr)
    )


def _build_pl_idol_exhausted_warning(scenario_mgr, current_loc):
    """調査済み偶像への再searchを事前に禁止する PL 向け警告。"""
    if current_loc != "altar_room" or not scenario_mgr:
        return ""
    if not _scenario_has_object(scenario_mgr, "glowing_idol", "altar_room"):
        return ""
    if not scenario_mgr._is_target_investigated("glowing_idol"):
        return ""
    if scenario_mgr._is_research_reopened("glowing_idol"):
        return ""
    examples = _format_alternate_object_examples(
        scenario_mgr, loc_id=current_loc, exclude={"glowing_idol"},
    )
    return f"""
【最重要・偶像調査完了】`glowing_idol` への通常 `search` / `inspect` は既に試行済みで、システム上ブロックされます。
再挑戦する場合のみ `push_roll` が許可されます（プッシュ可能状態のとき）。
それ以外は、次の**未探索ルート**から選んでください: {examples}
OOCとICの方針を一致させてください。
"""


def _reconcile_communication_priority(
    action, target, skill, intent, scenario_mgr, current_loc, flags, object_ids,
    char_mgr=None,
):
    """
    対人対象の調査を talk へ強制変換する（ActionValidator Pattern A）。
    移動の意図不一致は validate_move_intent で拒否する。
    戻り値: (action, target, skill, log) または None
    """
    action = str(action or "").lower()
    target = str(target or "")
    skill = str(skill or "")
    flags = flags or {}

    rewritten = rewrite_human_investigation_to_talk(
        action, target, char_mgr=char_mgr,
        scenario_mgr=scenario_mgr, current_loc=current_loc,
    )
    if rewritten:
        action = rewritten["action"]
        target = rewritten["target"]
        skill = rewritten.get("skill", "")
        # search→talk 化の直後でも、未紹介アーティは受付へ再リダイレクトする
        redirected = _redirect_preintro_artie_target(target, flags, current_loc)
        if redirected:
            return "talk", redirected, "", rewritten.get("log", HUMAN_INSPECT_REWRITE_LOG)
        return (
            action,
            target,
            skill,
            rewritten.get("log", HUMAN_INSPECT_REWRITE_LOG),
        )

    redirected = _redirect_preintro_artie_target(target, flags, current_loc)
    if redirected:
        return "talk", redirected, "", HUMAN_INSPECT_REWRITE_LOG

    if current_loc == "boston_globe" and not flags.get("artie_introduced"):
        if action in ("search", "inspect") and target in ("reception_desk", "globe_receptionist"):
            return "talk", "globe_receptionist", "", HUMAN_INSPECT_REWRITE_LOG

    if current_loc == "introduction" and not flags.get("talked_with_knott"):
        if action == "talk" and not target:
            return "talk", "steven_knott", "", ""

    return None


def _format_intent_non_execute_hint(player_intent, scenario_mgr=None, current_loc=""):
    """方針発言・曖昧移動を実行せず、候補提示テキストを返す。"""
    dests = list(player_intent.get("suggested_destinations") or [])
    target = str(player_intent.get("target_text") or "")
    if target and target not in dests:
        dests.insert(0, target)
    names = []
    for dest in dests[:3]:
        if not scenario_mgr:
            names.append(dest)
            continue
        info = scenario_mgr.get_location_info(dest) or {}
        names.append(str(info.get("name") or dest))
    if player_intent.get("ambiguous_move_inferred"):
        dest_txt = "、".join(names) if names else "近隣"
        return (
            f"「{dest_txt}へ移動する」という意図として解釈しました。"
            "この移動を実行しますか？ 実行する場合は『〇〇へ移動する』と明示してください。"
        )
    if names:
        return (
            "方針・相談として受け取りました（即時実行しません）。"
            f"次の行動候補: {(' / '.join(names))}。"
            "実行する場合は移動・調査・会話を明示してください。"
        )
    return (
        "方針・相談として受け取りました（即時実行しません）。"
        "次に実行する行動を明示してください。"
    )


def build_player_intent_context(
    all_events_log=None,
    scenario_mgr=None,
    current_loc="",
    char_mgr=None,
    *,
    phase="",
    last_action=None,
    lookback=8,
):
    """
    意図解釈用の直近文脈（KP/NPC/PL・現在地対象・フェーズ）。
    シナリオ全文や大量ログは付けず、直近数ターンに限定する。
    """
    recent = list(all_events_log or [])[-max(2, int(lookback)):]
    recent_kp = []
    recent_npc = []
    recent_player = []
    focus_npc = ""
    for entry in recent:
        text = str((entry or {}).get("text") or "").strip()
        if not text:
            continue
        meta = (entry or {}).get("meta") or {}
        channel = str((entry or {}).get("channel") or "")
        low = text[:48]
        if text.startswith("KP:") or text.startswith("KP(") or low.startswith("KP："):
            recent_kp.append(text[:240])
            continue
        if meta.get("npc_id") or meta.get("speaker_npc"):
            recent_npc.append(text[:240])
            focus_npc = str(meta.get("npc_id") or meta.get("speaker_npc") or focus_npc)
            continue
        if "(PC)" in text or "(PL)" in text or text.startswith("PC:") or text.startswith("PL:"):
            recent_player.append(text[:240])
            continue
        if channel == "IC" and ":" in text and not text.startswith("【"):
            # 「NPC名: セリフ」形式をNPC文脈として扱う
            speaker = text.split(":", 1)[0].strip()
            if speaker and "KP" not in speaker and "(PC)" not in speaker and "(PL)" not in speaker:
                recent_npc.append(text[:240])
                if char_mgr and not focus_npc:
                    try:
                        focus_npc = find_npc_id_from_intent_text(char_mgr, speaker) or focus_npc
                    except Exception:
                        pass

    npcs_here = []
    objects_here = []
    if scenario_mgr:
        loc = str(current_loc or getattr(scenario_mgr, "location", "") or "")
        try:
            for nid in (scenario_mgr.get_npcs_present(loc, char_mgr=char_mgr) or []):
                npcs_here.append(str(nid))
        except Exception:
            npcs_here = []
        objects_here = list(
            ((scenario_mgr.get_location_info(loc) or {}).get("objects") or {}).keys()
        )[:8]
        current_loc = loc or current_loc
    if not focus_npc and npcs_here:
        focus_npc = str(npcs_here[0])

    return {
        "recent_kp": recent_kp[-2:],
        "recent_npc": recent_npc[-2:],
        "recent_player": recent_player[-2:],
        "current_loc": str(current_loc or ""),
        "npcs_here": npcs_here[:8],
        "objects_here": [str(x) for x in objects_here[:8]],
        "last_action": dict(last_action or {}) if isinstance(last_action, dict) else {},
        "phase": str(phase or (getattr(scenario_mgr, "current_phase", "") if scenario_mgr else "") or ""),
        "focus_npc": focus_npc,
    }


def _should_preserve_talk_or_dialogue(
    action,
    skill,
    dialogue,
    pl_ooc="",
    target="",
    *,
    char_mgr=None,
    scenario_mgr=None,
    current_loc="",
):
    """
    会話・NPC反応を意図再解釈で move/wait へ落とさない。
    質問・礼・再交渉・返答・会話を含む提案を保護する。
    """
    action = str(action or "").lower()
    skill = str(skill or "")
    combined = f"{dialogue or ''} {pl_ooc or ''}".strip()
    if is_social_action(action, skill):
        return True
    if action in ("talk", "speak", "persuade", "negotiate", "fast_talk", "intimidate", "charm", "psychology"):
        return True
    if is_courtesy_dialogue_text(combined):
        return True
    proposal = classify_actionable_proposal(
        combined,
        scenario_mgr=scenario_mgr,
        current_loc=current_loc,
        char_mgr=char_mgr,
        proposed_target=target,
    )
    if proposal and proposal.get("action") == "talk":
        return True
    if target and resolve_social_npc_id(target, char_mgr=char_mgr):
        # 対象がNPCなら会話系として保護（search→talk 補正は後段で許可）
        if action in ("", "wait", "talk", "search", "inspect"):
            return action != "search" and action != "inspect"
    return False


def _build_system_correction_payload(
    *,
    original_intent_type="",
    original_action="",
    original_target="",
    correction_reason="",
    corrected_action="",
    corrected_target="",
    requires_confirmation=False,
):
    """自動補正メタ（ログ互換＋構造化フィールド）。"""
    return {
        "system_correction": True,
        "original_intent_type": original_intent_type or "",
        "original_action": original_action or "",
        "original_target": original_target or "",
        "correction_reason": correction_reason or "",
        "corrected_action": corrected_action or "",
        "corrected_target": corrected_target or "",
        "requires_confirmation": bool(requires_confirmation),
    }


def reconcile_pl_action(
    pc_action, speak_as, pl_ooc, scenario_mgr, current_loc,
    pending_san_check=None, char_mgr=None,
    intent_context=None,
    pending_push_roll=None,
):
    """
    セリフ・メタ発言・行動コマンドの整合をサーバー側で補正／検証する。
    - 対人 search/inspect/push → talk へ自動変換
    - move のテキスト不一致 → validation_error（実行せず PL 再生成）
    - pending 無しの push_roll → validation_error
    - 純粋な方針発言のみ wait（動詞＋対象が明確な提案は実行候補）
    - 会話・NPC反応は意図再解釈で move/wait に落とさない
    """
    if _is_san_check_pending(pending_san_check):
        return _enforce_san_lock_pc_action(pc_action, pl_ooc)

    if not scenario_mgr:
        return pc_action

    action = str(pc_action.get("action", "wait") or "wait").lower()
    skill = str(pc_action.get("skill", "") or "")
    target = normalize_action_target(
        str(pc_action.get("target", "") or ""),
        scenario_mgr, current_loc, char_mgr=char_mgr,
    )
    dialogue = str(pc_action.get("dialogue", "") or "")
    intent = _combined_pl_intent_text(dialogue, pl_ooc)
    flags = scenario_mgr.flags
    original_action = dict(pc_action)

    # 失敗保留が無い push_roll は早期拒否（成功後の「慎重に」誤用を防ぐ）
    if action == "push_roll":
        push_check = validate_push_roll_available(
            pending_push_roll,
            current_loc=current_loc,
            scenario_mgr=scenario_mgr,
        )
        if not push_check.get("ok"):
            return {
                "action": "wait",
                "target": "",
                "skill": "",
                "message": "",
                "dialogue": dialogue,
                "validation_error": push_check.get("error") or PUSH_ROLL_UNAVAILABLE_ERROR,
                "validation_error_code": push_check.get("error_code", "push_roll_unavailable"),
                "suggested_fix": push_check.get("suggested_fix"),
                "needs_pl_retry": True,
                "original_action": original_action,
            }

    preserve_talk = _should_preserve_talk_or_dialogue(
        action, skill, dialogue, pl_ooc or "", target,
        char_mgr=char_mgr, scenario_mgr=scenario_mgr, current_loc=current_loc,
    )
    ctx = intent_context
    if ctx is None:
        ctx = build_player_intent_context(
            None, scenario_mgr, current_loc, char_mgr,
            last_action=original_action,
        )
    player_intent = interpret_player_intent(
        dialogue,
        proposed_action=action,
        proposed_target=target or str(pc_action.get("target") or ""),
        pl_ooc=pl_ooc or "",
        scenario_mgr=scenario_mgr,
        current_loc=current_loc,
        char_mgr=char_mgr,
        intent_context=ctx,
    )
    # 既にシステムが確定した自動補正アクションは、再解釈で潰さない
    already_corrected = bool(
        pc_action.get("auto_corrected")
        or original_action.get("auto_corrected")
        or pc_action.get("system_correction_log")
        or original_action.get("system_correction_log")
    )

    # 会話保護: 明示対象がある talk / 礼 / 質問 / 返答は wait・move へ落とさない
    if preserve_talk and not already_corrected:
        if player_intent.get("do_not_execute") or player_intent.get("action") in ("wait", "", None):
            player_intent = {
                **player_intent,
                "intent_type": player_intent.get("intent_type") or INTENT_IN_CHARACTER_DIALOGUE,
                "action": "talk" if action in ("", "wait", "move") else action,
                "do_not_execute": False,
                "notes": (player_intent.get("notes") or "") + " | talk/dialogue preserved",
            }
        if action in ("", "wait", "move") and str(player_intent.get("action") or "") == "talk":
            action = "talk"
            intent_target = normalize_action_target(
                str(player_intent.get("target_text") or target or ""),
                scenario_mgr, current_loc, char_mgr=char_mgr,
            )
            if intent_target:
                target = intent_target

    # 純粋な方針・相談・曖昧移動のみ即時実行しない（停滞提案はヒントに限定）
    # 会話保護中／行動を含む提案はスキップ
    if (
        not already_corrected
        and not preserve_talk
        and player_intent.get("do_not_execute")
        and player_intent.get("intent_type") in (
            INTENT_DISCUSSION_OR_PLAN,
            INTENT_UNCLEAR,
        )
        and not player_intent.get("actionable_proposal")
    ):
        if action == "move":
            move_check = validate_move_intent(
                intent, target, current_loc=current_loc, scenario_mgr=scenario_mgr,
            )
            if (
                not move_check.get("ok")
                and move_check.get("error_code") in VALIDATION_AUTO_CORRECT_CODES
                and (move_check.get("suggested_fix") or {}).get("target")
            ):
                return {
                    "action": "wait",
                    "target": "",
                    "skill": "",
                    "message": "",
                    "dialogue": dialogue,
                    "validation_error": move_check.get("error") or MOVE_MISSING_TARGET_ERROR,
                    "validation_error_code": move_check.get("error_code"),
                    "suggested_fix": move_check.get("suggested_fix"),
                    "needs_pl_retry": True,
                    "original_action": original_action,
                    "player_intent": player_intent,
                }
        # 純粋相談のみ非実行。曖昧 move で検証にも掛からない場合のみヒント。
        if player_intent.get("intent_type") == INTENT_DISCUSSION_OR_PLAN or player_intent.get("ambiguous_move_inferred"):
            hint = _format_intent_non_execute_hint(player_intent, scenario_mgr, current_loc)
            result = {
                "action": "wait",
                "target": "",
                "skill": "",
                "message": "（方針を検討している）",
                "dialogue": "",
                "player_intent": player_intent,
                "post_action_hint": hint,
                "intent_non_execute": True,
            }
            if player_intent.get("ambiguous_move_inferred"):
                result["ambiguous_move_log"] = (
                    "【解釈ログ】曖昧な移動示唆を実行命令としては採用しませんでした。"
                    f"発話根拠: {player_intent.get('evidence') or []} / "
                    f"候補先: {player_intent.get('suggested_destinations') or []}"
                )
            return result

    # 明示／提案意図が LLM 提案と食い違う場合はプレイヤー意図を優先
    # （talk→move / DISCUSSION→move|search の置換はしない）
    if (
        player_intent.get("intent_type") == INTENT_ACTION_REQUEST
        and player_intent.get("explicitness") in ("explicit", "soft")
        and not player_intent.get("do_not_execute")
    ):
        intent_action = str(player_intent.get("action") or "").lower()
        intent_target = normalize_action_target(
            str(player_intent.get("target_text") or ""),
            scenario_mgr, current_loc, char_mgr=char_mgr,
        )
        if intent_action == "move" and not str(target or "").strip() and intent_target:
            target = intent_target
        if intent_action in ("talk", "search", "inspect") and action in ("move", "wait", ""):
            # 会話・調査提案を move/wait 推測より優先（種類の上書きは提案→実行方向のみ）
            if not (preserve_talk and intent_action != "talk" and action == "talk"):
                action = intent_action
                if intent_target:
                    target = intent_target
                player_intent = {
                    **player_intent,
                    "notes": (player_intent.get("notes") or "") + " | プレイヤー意図をmove/waitより優先",
                }
        elif (
            intent_action == "move"
            and action != "move"
            and not preserve_talk
            and player_intent.get("explicitness") == "explicit"
            and has_explicit_move_expression(intent)
        ):
            move_gate = can_auto_execute_move(
                {**player_intent, "action": "move", "target_text": intent_target or target},
                scenario_mgr=scenario_mgr,
                current_loc=current_loc,
                target=intent_target or target,
            )
            if move_gate.get("ok"):
                action = "move"
                target = intent_target or target

    addressed_npc = None
    if is_social_action(action, skill) and char_mgr:
        addressed_npc = find_npc_id_from_intent_text(char_mgr, dialogue, addressee_only=True)
    if addressed_npc:
        target = addressed_npc
    elif not target:
        inferred = _resolve_talk_target_from_intent(
            dialogue or pl_ooc, char_mgr, scenario_mgr, current_loc,
        ) if is_social_action(action, skill) else ""
        target = inferred or target
    if not addressed_npc and not target and str(pc_action.get("target") or "").strip() in ("", "彼女", "彼", "あの人", "その人", "女性", "お姉さん"):
        target = _infer_boston_globe_social_target(target, intent, flags, current_loc)
    location_ids = set(scenario_mgr.get_all_location_ids())
    objects = scenario_mgr.get_location_info(current_loc).get("objects", {})
    object_ids = set(objects.keys())
    corrected = False
    correction_log = ""
    correction_meta = None

    if speak_as == "PL":
        return {
            "action": "wait",
            "target": "",
            "skill": "",
            "message": pl_ooc or "（様子を見ている）",
            "dialogue": "",
            "player_intent": player_intent,
        }

    social_fix = _reconcile_communication_priority(
        action, target, skill, intent, scenario_mgr, current_loc, flags, object_ids,
        char_mgr=char_mgr,
    )
    if social_fix:
        action, target, skill, correction_log = social_fix
        corrected = True
        correction_meta = _build_system_correction_payload(
            original_intent_type=player_intent.get("intent_type"),
            original_action=original_action.get("action"),
            original_target=original_action.get("target"),
            correction_reason="human_target_as_investigation",
            corrected_action=action,
            corrected_target=target,
        )

    object_talk = rewrite_talk_to_object_investigation(
        action, target, scenario_mgr, current_loc, skill,
    )
    if object_talk:
        action = object_talk["action"]
        target = object_talk["target"]
        if object_talk.get("skill") is not None:
            skill = object_talk.get("skill") or skill
        correction_log = correction_log or object_talk.get("log") or OBJECT_TALK_REWRITE_LOG
        corrected = True
        correction_meta = correction_meta or _build_system_correction_payload(
            original_intent_type=player_intent.get("intent_type"),
            original_action=original_action.get("action"),
            original_target=original_action.get("target"),
            correction_reason="object_as_talk_target",
            corrected_action=action,
            corrected_target=target,
        )

    # talk の target 空: セリフから NPC を補完。シナリオ外 NPC は捨てる
    if is_social_action(action, skill) and not str(target or "").strip():
        inferred_npc = _resolve_talk_target_from_intent(
            intent, char_mgr=char_mgr, scenario_mgr=scenario_mgr, current_loc=current_loc,
        )
        if inferred_npc:
            target = inferred_npc
            corrected = True
            correction_log = correction_log or "【アクション補正】対話対象が空だったため、発言から NPC を補完しました。"
        else:
            block, _kp, _hint = build_absent_npc_guidance(scenario_mgr, current_loc, char_mgr=char_mgr)
            return {
                "action": "wait", "target": "", "skill": "", "message": "", "dialogue": dialogue,
                "validation_error": "【行動再選択】会話相手を特定できません。相手と話題の人物を区別して target を指定してください。 " + _hint,
                "validation_error_code": "ambiguous_social_target", "needs_pl_retry": True,
                "original_action": original_action,
                "player_intent": player_intent,
            }

    # 現在地にいない NPC への talk は実行せず、調査／移動へ誘導
    if is_social_action(action, skill) and target and scenario_mgr:
        npc_id = resolve_social_npc_id(target, char_mgr=char_mgr) or target
        if not scenario_mgr.is_npc_at_location(npc_id, current_loc, char_mgr=char_mgr):
            suggested = suggest_empty_move_fix(intent, current_loc, scenario_mgr) or {}
            if not suggested.get("target"):
                forced = build_forced_progress_action(scenario_mgr, current_loc)
                if forced:
                    suggested = {
                        "action": forced.get("action") or "search",
                        "target": forced.get("target") or "",
                        "skill": forced.get("skill") or "",
                    }
            block, _kp, _hint = build_absent_npc_guidance(
                scenario_mgr, current_loc, exclude_targets={npc_id, str(target or "")}, char_mgr=char_mgr,
            )
            return {
                "action": "wait",
                "target": "",
                "skill": "",
                "message": "",
                "dialogue": dialogue,
                "validation_error": (
                    f"{ABSENT_NPC_TALK_RETRY_ERROR} {block}"
                ),
                "validation_error_code": "absent_npc_talk",
                "suggested_fix": suggested or None,
                "needs_pl_retry": True,
                "original_action": original_action,
                "player_intent": player_intent,
            }

    # 別地点オブジェクトの search: 即時 search せず移動提案（明示移動なら move）
    if action in ("search", "inspect") and target:
        scope = classify_target_scope(
            target, scenario_mgr=scenario_mgr, current_loc=current_loc, char_mgr=char_mgr,
        )
        if scope.get("scope") == "other_location":
            other_loc = scope.get("location_id") or ""
            if has_explicit_move_expression(intent) and other_loc and other_loc != current_loc:
                move_gate = can_auto_execute_move(
                    {
                        "intent_type": INTENT_ACTION_REQUEST,
                        "action": "move",
                        "explicitness": "explicit",
                        "target_text": other_loc,
                        "evidence": player_intent.get("evidence") or ["移動"],
                    },
                    scenario_mgr=scenario_mgr,
                    current_loc=current_loc,
                    target=other_loc,
                )
                if move_gate.get("ok"):
                    action, target, skill = "move", other_loc, ""
                    corrected = True
                    correction_log = (
                        correction_log
                        or f"【アクション補正】対象は別地点（{other_loc}）にあるため、明示移動として処理しました。"
                    )
                    correction_meta = _build_system_correction_payload(
                        original_intent_type=player_intent.get("intent_type"),
                        original_action=original_action.get("action"),
                        original_target=original_action.get("target"),
                        correction_reason="other_location_object_with_explicit_move",
                        corrected_action=action,
                        corrected_target=target,
                    )
                else:
                    return {
                        "action": "wait",
                        "target": "",
                        "skill": "",
                        "message": "",
                        "dialogue": dialogue,
                        "validation_error": (
                            f"【行動再選択】対象 `{scope.get('target')}` は別地点 `{other_loc}` にあります。"
                            "先にその場所へ移動するか、現在地の対象を指定してください。"
                        ),
                        "validation_error_code": "target_other_location",
                        "suggested_fix": {"action": "move", "target": other_loc, "skill": ""} if other_loc else None,
                        "needs_pl_retry": True,
                        "original_action": original_action,
                        "player_intent": player_intent,
                        "post_action_hint": f"対象は別地点（{other_loc}）にあります。移動しますか？",
                    }
            else:
                return {
                    "action": "wait",
                    "target": "",
                    "skill": "",
                    "message": "",
                    "dialogue": dialogue,
                    "validation_error": (
                        f"【行動再選択】対象 `{scope.get('target')}` は現在地ではなく `{other_loc}` にあります。"
                        "移動してから調査するか、現在地の対象を指定してください。"
                    ),
                    "validation_error_code": "target_other_location",
                    "suggested_fix": {"action": "move", "target": other_loc, "skill": ""} if other_loc else None,
                    "needs_pl_retry": True,
                    "original_action": original_action,
                    "player_intent": player_intent,
                    "post_action_hint": (
                        f"対象は別地点（{other_loc}）にあります。"
                        "『そこへ移動する』と明示するか、現在地の対象を調べてください。"
                    ),
                }

    # move: target 空なら発言から補完してから検証
    if action == "move" and not str(target or "").strip():
        inferred_move = infer_empty_move_from_intent(intent, current_loc, scenario_mgr)
        if inferred_move and inferred_move.get("target"):
            # 明示移動表現がある場合のみ補完実行。無い場合は後段検証へ。
            if has_explicit_move_expression(intent) or player_intent.get("weak_move_candidate"):
                if has_explicit_move_expression(intent):
                    action = str(inferred_move.get("action") or "move")
                    target = str(inferred_move.get("target") or "")
                    skill = str(inferred_move.get("skill") or skill or "")
                    corrected = True
                    correction_log = (
                        correction_log
                        or "【アクション補正】move の target が空だったため、発言内容から補完しました。"
                    )
                # weak_move_candidate は補完せず validate に任せる（auto-correct 経路）

    # move: テキストと target の一致を厳密検証（不一致は拒否してリトライ）
    if action == "move":
        move_check = validate_move_intent(
            intent, target, current_loc=current_loc, scenario_mgr=scenario_mgr,
        )
        if not move_check.get("ok"):
            return {
                "action": "wait",
                "target": "",
                "skill": "",
                "message": "",
                "dialogue": dialogue,
                "validation_error": (
                    move_check.get("error")
                    or MOVE_MISSING_TARGET_ERROR
                    or MOVE_INTENT_MISMATCH_ERROR
                ),
                "validation_error_code": move_check.get("error_code", "move_intent_mismatch"),
                "suggested_fix": move_check.get("suggested_fix"),
                "needs_pl_retry": True,
                "original_action": original_action,
                "player_intent": player_intent,
            }
        # 厳格ゲート: 明示 ACTION_REQUEST 以外の move は実行しない
        move_intent_for_gate = dict(player_intent)
        move_intent_for_gate["action"] = "move"
        move_intent_for_gate["target_text"] = target
        if player_intent.get("weak_move_candidate") and not has_explicit_move_expression(intent):
            # 発話なし・target 空 → 既存 auto-correct（search 等）に委ねる
            # 既に自動補正済みの move は再ゲートしない
            if already_corrected:
                pass
            elif not str(target or "").strip():
                pass
            else:
                # 発話根拠のない移動実行は確認扱い（黙って実行しない）
                return {
                    "action": "wait",
                    "target": "",
                    "skill": "",
                    "message": "（移動の意思を確認中）",
                    "dialogue": "",
                    "player_intent": player_intent,
                    "post_action_hint": (
                        f"移動先 `{target}` として解釈しましたが、発話に移動の明示がありません。"
                        "『〇〇へ移動する』と明示してください。"
                    ),
                    "intent_non_execute": True,
                    "ambiguous_move_log": (
                        "【解釈ログ】曖昧な発言を実行命令として解釈する前に確認を要求しました。"
                        f" proposed_target={target}"
                    ),
                }
        elif not already_corrected:
            move_gate = can_auto_execute_move(
                move_intent_for_gate,
                scenario_mgr=scenario_mgr,
                current_loc=current_loc,
                target=target,
            )
            if not move_gate.get("ok"):
                reason = str(move_gate.get("reason") or "")
                # 未解禁はエンジン拒否に委ねず、明示エラーで再選択を促す
                if "未解禁" in reason or "到達不能" in reason or "存在しない" in reason:
                    return {
                        "action": "wait",
                        "target": "",
                        "skill": "",
                        "message": "",
                        "dialogue": dialogue,
                        "validation_error": f"【行動再選択】{reason}",
                        "validation_error_code": "move_not_executable",
                        "needs_pl_retry": True,
                        "original_action": original_action,
                        "player_intent": player_intent,
                        "suggested_fix": suggest_empty_move_fix(intent, current_loc, scenario_mgr),
                    }
                if move_gate.get("needs_confirmation"):
                    hint = _format_intent_non_execute_hint(
                        {
                            **player_intent,
                            "ambiguous_move_inferred": True,
                            "suggested_destinations": [target] if target else [],
                            "target_text": target,
                        },
                        scenario_mgr,
                        current_loc,
                    )
                    return {
                        "action": "wait",
                        "target": "",
                        "skill": "",
                        "message": "（移動の意思を確認中）",
                        "dialogue": "",
                        "player_intent": player_intent,
                        "post_action_hint": hint,
                        "intent_non_execute": True,
                        "ambiguous_move_log": (
                            "【解釈ログ】曖昧な発言を実行命令として解釈する前に確認を要求しました。"
                            f" reason={move_gate.get('reason')}"
                        ),
                    }

    # move + オブジェクトID は操作／対話へ変換
    if action == "move" and target in object_ids:
        npc = resolve_social_npc_id(target, char_mgr=char_mgr)
        if npc:
            action, target, skill = "talk", npc, ""
            correction_log = correction_log or HUMAN_INSPECT_REWRITE_LOG
            corrected = True
            correction_meta = _build_system_correction_payload(
                original_intent_type=player_intent.get("intent_type"),
                original_action=original_action.get("action"),
                original_target=original_action.get("target"),
                correction_reason="move_to_present_npc_object",
                corrected_action=action,
                corrected_target=target,
            )
        else:
            obj_actions = objects.get(target, {}).get("usable_actions", [])
            if "break" in obj_actions:
                action, target = "break", target
            elif "push" in obj_actions:
                action, target = "push", target
            elif "search" in obj_actions or "inspect" in obj_actions:
                action = "search" if "search" in obj_actions else "inspect"
                skill = skill or "目星"
            else:
                action, target = "wait", ""
            corrected = True
            correction_meta = _build_system_correction_payload(
                original_intent_type=player_intent.get("intent_type"),
                original_action=original_action.get("action"),
                original_target=original_action.get("target"),
                correction_reason="move_non_location_destination",
                corrected_action=action,
                corrected_target=target,
            )

    # move + 存在しない場所ID の誤りを状況に応じて補正
    if action == "move" and target and target not in location_ids:
        if (
            current_loc == "study"
            and _scenario_has_object(scenario_mgr, "iron_door", "study")
            and _text_has_any(intent, ("鉄扉", "鉄の扉", "扉", "ドア"))
        ):
            action, target = "break", "iron_door"
            corrected = True
        elif current_loc == "study" and flags.get("door_opened") and "hallway" in location_ids:
            action, target = "move", "hallway"
            corrected = True
        elif _scenario_has_object(scenario_mgr, target, current_loc):
            npc = resolve_social_npc_id(target, char_mgr=char_mgr)
            if npc:
                action, target, skill = "talk", npc, ""
            else:
                obj = objects.get(target) or {}
                obj_actions = obj.get("usable_actions") or ["search"]
                action = "search" if "search" in obj_actions else obj_actions[0]
                skill = skill or ("目星" if action in ("search", "inspect") else "")
            corrected = True

    if current_loc == "study" and _scenario_has_object(scenario_mgr, "desk", "study"):
        if flags.get("found_button") and not flags.get("button_pushed"):
            if action == "search" and target == "desk":
                action, target = "push", "desk"
                corrected = True
            elif _text_has_any(intent, ("ボタン", "押す", "push")) and action in ("wait", "search"):
                action, target = "push", "desk"
                corrected = True

        if flags.get("door_opened") and "hallway" in location_ids:
            if action in ("search", "push", "break") and target == "desk":
                action, target = "move", "hallway"
                corrected = True
            elif action == "move" and target in ("iron_door", "door", ""):
                action, target = "move", "hallway"
                corrected = True
            elif _text_has_any(intent, ("廊下", "向こう", "進む", "出よう", "hallway")):
                action, target = "move", "hallway"
                corrected = True

        if flags.get("desk_searched") and not flags.get("desk_research_unlocked"):
            if action == "search" and target == "desk":
                if flags.get("found_button") and not flags.get("button_pushed"):
                    action, target = "push", "desk"
                    corrected = True
                elif (
                    _scenario_has_object(scenario_mgr, "iron_door", "study")
                    and _text_has_any(intent, ("鉄扉", "鉄の扉", "力ずく", "こじ開"))
                ):
                    action, target = "break", "iron_door"
                    corrected = True
                # 再調査不可の search/desk は pre_roll_block に任せる（break へ強制変換しない）
            elif (
                _scenario_has_object(scenario_mgr, "iron_door", "study")
                and _text_has_any(intent, ("鉄扉", "鉄の扉", "力ずく", "こじ開"))
                and action in ("wait", "search")
            ):
                action, target = "break", "iron_door"
                corrected = True

    if current_loc == "hallway" and _scenario_object_exists_anywhere(scenario_mgr, "wall_panel"):
        if flags.get("trapdoor_found"):
            visit_secret = flags.get("visit_secret_room", 0)
            if visit_secret >= 2 and not flags.get("ladder_searched"):
                if action == "move" and target == "secret_room":
                    if not _text_has_any(intent, ("降り", "地下室へ", "トラップドアを開", "下へ", "再び下")):
                        action, target = "wait", ""
                        corrected = True
            elif action in ("search", "wait") and _text_has_any(
                intent, ("降り", "地下室へ", "トラップドアを開", "下へ進", "地下室")
            ):
                action, target = "move", "secret_room"
                corrected = True
        if action == "search" and target == "desk" and "wall_panel" in object_ids:
            action, target = "search", "wall_panel"
            skill = skill or "目星"
            corrected = True

    if current_loc == "secret_room" and _scenario_has_object(scenario_mgr, "escape_ladder", "secret_room"):
        if action == "move" and target == "hallway":
            if flags.get("visit_secret_room", 0) >= 2 and not flags.get("ladder_searched"):
                if not _text_has_any(intent, ("戻", "廊下", "トラップ", "一旦", "退")):
                    action, target = "search", "escape_ladder"
                    corrected = True
        if not flags.get("ladder_searched") and _text_has_any(intent, ("はしご", "登", "脱出", "上へ", "出口")):
            if action in ("wait", "move") or (action == "search" and target in ("", "sigil")):
                action, target = "search", "escape_ladder"
                corrected = True

    if (
        current_loc == "altar_room"
        and _scenario_has_object(scenario_mgr, "glowing_idol", "altar_room")
        and _is_idol_target(target)
    ):
        idol_exhausted = (
            scenario_mgr._is_target_investigated("glowing_idol")
            and not scenario_mgr._is_research_reopened("glowing_idol")
        )
        ooc_wants_alternate = _ooc_signals_abandon_idol_for_alternate(pl_ooc, dialogue)
        if ooc_wants_alternate and action in ("search", "inspect", "push_roll", "wait"):
            action, target = _pick_altar_alternate_action(scenario_mgr)
            skill = "目星" if action in ("search", "inspect") else ""
            corrected = True
        elif idol_exhausted and action in ("search", "inspect"):
            action, target = _pick_altar_alternate_action(scenario_mgr)
            skill = "目星" if action in ("search", "inspect") else ""
            corrected = True

    # シナリオに存在しないターゲットへの操作は wait に落とす（幻覚オブジェクト対策）
    # ただし NPC（対話・交渉）はシナリオオブジェクト一覧にないため除外する
    if target and action not in ("move", "wait", "none", ""):
        if target not in object_ids and target not in location_ids:
            present_npcs = set()
            if scenario_mgr and hasattr(scenario_mgr, "get_npcs_present"):
                present_npcs = set(scenario_mgr.get_npcs_present(current_loc) or [])
            is_npc_target = (
                target in present_npcs
                or bool(char_mgr and find_npc_id_by_target(char_mgr, target))
            )
            if not is_npc_target and not _scenario_object_exists_anywhere(scenario_mgr, target):
                action, target = "wait", ""
                corrected = True
    if action in ("search", "inspect", "push", "break", "kick", "climb", "use") and not target:
        action, target = "wait", ""
        corrected = True

    if action == "search" or action == "inspect":
        if not skill:
            skill = "目星"
    elif is_social_action(action, skill):
        # 交渉技能は保持。雑談は skill を空にしてもよい
        if is_casual_talk(action, skill):
            skill = ""
    else:
        skill = ""

    dialogue = _sanitize_pc_dialogue(dialogue, scenario_mgr, current_loc)

    # セリフが行動と明らかに矛盾する場合、行動に合わせて表示文を再生成
    message = _build_pc_display_message(
        dialogue, action, target, scenario_mgr=scenario_mgr, current_loc=current_loc,
    )
    if corrected or not dialogue.strip():
        dialogue = ""
        message = _build_pc_display_message(
            "", action, target, scenario_mgr=scenario_mgr, current_loc=current_loc,
        )

    result = {
        "action": action,
        "target": target,
        "skill": skill,
        "message": message,
        "dialogue": dialogue,
        "player_intent": player_intent,
    }
    if corrected or (action, target, skill) != (original_action.get("action"), original_action.get("target"), original_action.get("skill", "")):
        result["original_action"] = original_action.get("original_action") or original_action
    elif original_action.get("original_action"):
        result["original_action"] = original_action.get("original_action")
    # 事前の自動補正メタ（intent_replaced 等）を reconcile で落とさない
    for key in (
        "system_correction_log",
        "auto_corrected",
        "intent_replaced",
        "forced_progress",
        "transaction_id",
        "actor_id",
        "decision_owner_id",
        "system_correction_meta",
    ):
        if key in original_action and original_action.get(key) not in (None, ""):
            result.setdefault(key, original_action.get(key))
    if correction_meta:
        result["system_correction_meta"] = correction_meta
    if correction_log:
        # 事前の自動補正ログを優先し、未設定時のみ reconcile 補正を記録
        if not result.get("system_correction_log"):
            result["system_correction_log"] = correction_log
        if (action, target) != (
            (original_action.get("original_action") or original_action).get("action"),
            (original_action.get("original_action") or original_action).get("target"),
        ):
            result["intent_replaced"] = True
            result["forced_progress"] = True
            result["auto_corrected"] = True
    return result


def _build_kp_room_state_directive(scenario_mgr):
    """KP 向け: オブジェクト調査状態・移動可能先のシステム確定サマリー。"""
    if not scenario_mgr:
        return ""
    summary = scenario_mgr.build_object_status_summary()
    if not summary:
        return ""
    return (
        f"{summary}\n"
        "上記の状態と矛盾する誘導（調査済み対象の再勧め、存在しない移動先の示唆）は**厳禁**です。\n"
    )


STAGNATION_LIGHT_KP_INJECTION = (
    "【システム指示】現在、探索者が行き詰まっています。"
    "解答を直接教えるのではなく、部屋の不気味な変化"
    "（妙な隙間風、床板のきしみ、奇妙な臭いなど）を描写して、"
    "探索者の注意を自然に引きつけてください。"
)


def resolve_session_intervention_level(state, scenario_mgr):
    """シナリオ既定とセッションKP設定の強い方を採用する。"""
    scenario_level = InterventionLevel.STANDARD
    if scenario_mgr and hasattr(scenario_mgr, "get_scenario_intervention_level"):
        scenario_level = normalize_intervention_level(
            scenario_mgr.get_scenario_intervention_level(),
            InterventionLevel.STANDARD,
        )
    kp_raw = (state or {}).get("intervention_level")
    if kp_raw is None or kp_raw == "":
        kp_raw = (state or {}).get("kp_style")
        kp_level = intervention_level_from_kp_style(kp_raw, InterventionLevel.LIGHT)
    else:
        kp_level = normalize_intervention_level(kp_raw, InterventionLevel.LIGHT)
    return resolve_effective_intervention_level(scenario_level, kp_level)


def _build_kp_stagnation_injection(scenario_mgr, state=None):
    """膠着時の KP プロンプト注入（LIGHT ナッジまたは警告誘導）。"""
    if state and state.get("stagnation_kp_nudge"):
        return str(state.get("stagnation_kp_nudge") or STAGNATION_LIGHT_KP_INJECTION)

    if not scenario_mgr or not scenario_mgr.is_stagnation_warning_level():
        return ""

    level = resolve_session_intervention_level(state or {}, scenario_mgr)
    if level <= InterventionLevel.NONE:
        return ""
    if level == InterventionLevel.LIGHT:
        return STAGNATION_LIGHT_KP_INJECTION

    count = scenario_mgr.stagnation_counter
    examples = _format_alternate_object_examples(scenario_mgr)
    return (
        f"【システム警告・膠着検知（連続{count}回）】"
        "PLの行動が繰り返し拒否されています。同じ誤った行動を勧めず、"
        f"未調査のオブジェクトや有効な移動先（例: {examples}）へ明確に誘導してください。"
        "現在地のオブジェクト一覧に無い物体を創作・示唆することは**厳禁**です。"
    )


def _is_system_action_progress(result, payload=None):
    """
    システム結果に「状態差分になり得る強い進展マーカー」があるか。

    注意: 判定成功・knowledge_grants リストの存在・ログの【成功】だけでは True にしない。
    膠着リセットの正は detect_stagnation の State Delta。ここは早期ヒント用の補助。
    """
    if not result or result.get("blocked"):
        return False
    if result.get("location_changed") or result.get("new_location"):
        return True
    if result.get("stagnation_progress") and not result.get("stagnation_candidate"):
        # 救済イベント／アイデア成功など、明示的に立てられた場合のみ
        return True

    if payload:
        if payload.get("location_changed") or payload.get("new_location"):
            return True
        # 同一フラグの再セットは進展にしない（中身の新規性は Delta 側で判定）
        flag_updates = payload.get("flag_updates") or {}
        if isinstance(flag_updates, dict) and any(
            v is True for v in flag_updates.values()
        ):
            # ペイロード時点では新規か不明なため、ここでは確定進展にしない
            pass
        if payload.get("mark_investigated") and not payload.get("blocked"):
            # 再調査の mark は Delta の pc_investigated 増加でのみ進展扱い
            pass

    social = result.get("social") or {}
    if social.get("revealed_secrets"):
        return True
    if social.get("relationship_changed") and social.get("relationship_improved"):
        return True

    # 知識付与リストがあっても、実際に新規IDが増えた場合のみ（呼び出し側で検証済みなら markers）
    if result.get("knowledge_actually_new") or (payload or {}).get("knowledge_actually_new"):
        return True
    return False


def _build_stagnation_progress_snapshot(state, scenario_mgr, char_mgr=None):
    """evaluate/detect 用の State Delta スナップショットを構築する。"""
    from GameStateManager import GameStateManager
    return GameStateManager.build_progress_snapshot(
        getattr(scenario_mgr, "flags", None) or {},
        location_id=state.get("current_loc") if state else "",
        public_knowledge_ids=(state or {}).get("public_knowledge_ids"),
        char_mgr=char_mgr,
        active_pcs=(state or {}).get("active_pcs"),
    )


def _call_detect_stagnation(state_mgr, state, scenario_mgr, char_mgr=None, **kwargs):
    """detect_stagnation に State Delta コンテキストを付与して呼ぶ。"""
    snapshot = _build_stagnation_progress_snapshot(state, scenario_mgr, char_mgr)
    return state_mgr.detect_stagnation(
        state.get("all_events_log") if state else None,
        location_id=(state or {}).get("current_loc") or getattr(scenario_mgr, "location", ""),
        flags=getattr(scenario_mgr, "flags", None) or {},
        public_knowledge_ids=(state or {}).get("public_knowledge_ids"),
        char_mgr=char_mgr,
        active_pcs=(state or {}).get("active_pcs"),
        progress_snapshot=snapshot,
        **kwargs,
    )

def _is_system_action_stagnation(result, payload=None):
    """システム判定が膠着（拒否・失敗・空振り・非進展社交）だったか。"""
    if not result:
        return False
    if result.get("stagnation_progress") and not result.get("stagnation_candidate"):
        return False
    if result.get("blocked") or result.get("roll_type") == "blocked":
        return True
    if result.get("stagnation_candidate"):
        return True

    roll_type = str(result.get("roll_type") or "")
    # 雑談・交渉は状態差分が無い限り非進展候補（進展は Delta で判定）
    if roll_type in ("social_talk", "social_negotiate"):
        social = result.get("social") or {}
        if social.get("revealed_secrets"):
            return False
        if social.get("relationship_changed") and social.get("relationship_improved"):
            return False
        return True

    log = result.get("log", "") or ""
    stagnation_keywords = (
        MOVE_DENY_SYSTEM_LOG,
        "【移動不可】",
        "【システムブロック】",
        "存在しません",
        "すでに調査",
        "再調査",
        "調査済み",
        "閲覧済み",
        "特になにも見つからなかった",
        "対話ブロック",
        "いません",
    )
    if any(keyword in log for keyword in stagnation_keywords):
        return True

    action_id = str(result.get("action_id", "") or "").lower()
    if action_id in ("wait", "none", ""):
        return False

    if result.get("status", 0) == 0:
        if "失敗" in log or result.get("roll_type") in ("skill", "opposed_str", "social_talk", "social_negotiate"):
            if not _is_system_action_progress(result, payload):
                return True
    if is_failure_level(result.get("status", 0)) and not _is_system_action_progress(result, payload):
        if result.get("roll_type") in ("skill", "opposed_str", "blocked", "social_talk", "social_negotiate", "move"):
            return True
    # 成功でも進展マーカーが無ければ非進展（再確認・空振り成功）
    if is_success_level(result.get("status", 0)) and not _is_system_action_progress(result, payload):
        if roll_type in ("skill", "opposed_str", "auto_success", "move", "social_talk", "social_negotiate"):
            return True
    return False


def update_stagnation_from_system_result(scenario_mgr, result, payload=None):
    """システム判定結果に膠着フラグを付与する（カウンタ更新は detect_stagnation 側）。"""
    if not scenario_mgr or not result:
        return result

    if (
        result.get("luck_decision_required")
        or result.get("push_decision_required")
        or result.get("san_auto_resolved")
    ):
        return result

    action_id = str(result.get("action_id", "") or "").lower()
    if action_id in ("wait", "none", "") and not result.get("blocked"):
        return result

    # カウンタのリセットは State Delta 側が正。ここでは候補フラグのみ付与。
    # location_changed など強いマーカーがあるときだけ stagnation_progress を立てる。
    if result.get("location_changed") or result.get("new_location"):
        result["stagnation_progress"] = True
        scenario_mgr.reset_stagnation_counter()
    elif _is_system_action_progress(result, payload):
        result["stagnation_progress"] = True
    elif _is_system_action_stagnation(result, payload):
        result["stagnation_candidate"] = True
        result.pop("stagnation_progress", None)

    result["stagnation_counter"] = scenario_mgr.stagnation_counter
    return result


def execute_forced_idea_roll(pl_id, char_name, char_mgr, dice_engine, scenario_mgr):
    """FORCE介入: アイデア（INT）ロールで手がかり開示を試みる。"""
    int_value = char_mgr.get_attribute(pl_id, "INT") or 0
    dice_result = dice_engine.execute_int_roll(char_name, int_value)
    success = is_success_level(dice_result.get("success_level", 0))
    hint = ""
    if scenario_mgr and hasattr(scenario_mgr, "get_stagnation_hint_text"):
        hint = scenario_mgr.get_stagnation_hint_text()
    log = dice_result.get("log", "")
    if success:
        log += f"\n【アイデアロール成功】閃き: {hint}"
        kp_instruction = (
            "【アイデアロール成功】探索者が重要な手がかりを閃きました。"
            f"次のヒントの核心（{hint}）を情景に自然に織り込んで描写してください。"
            "答えそのものをそのまま唱えるのではなく、気づきとして演出すること。"
        )
    else:
        log += "\n【アイデアロール失敗】決定的な閃きは得られなかった。"
        kp_instruction = (
            "【アイデアロール失敗】閃きは得られなかったが、焦燥や不安を短い描写で示し、"
            "別の行動を促してください。"
        )
    return {
        "success": success,
        "log": log,
        "kp_instruction": kp_instruction,
        "hint": hint if success else "",
        "dice": dice_result,
    }


def apply_stagnation_intervention(state, managers, level, detection=None):
    """介入レベルに応じたアクションを実行し、結果サマリを返す。"""
    char_mgr, dice_engine, state_mgr, scenario_mgr = managers
    level = normalize_intervention_level(level, InterventionLevel.NONE)
    detection = detection or {}
    streak = detection.get("streak", scenario_mgr.stagnation_counter if scenario_mgr else 0)
    summary = {
        "level": int(level),
        "level_name": level.name,
        "streak": streak,
        "actions": [],
    }

    log_text = (
        f"[システム] 膠着を検知しました（連続{streak}ターン / 介入: "
        f"{INTERVENTION_LEVEL_LABELS.get(level, level.name)}）。"
    )
    state.setdefault("all_events_log", []).append({
        "channel": "OOC",
        "location": "all",
        "secret_to": None,
        "text": log_text,
        "meta": {"stagnation_intervention": True, "level": int(level)},
    })
    summary["actions"].append("log")

    if level <= InterventionLevel.NONE:
        return summary

    if level == InterventionLevel.LIGHT:
        state["stagnation_kp_nudge"] = STAGNATION_LIGHT_KP_INJECTION
        summary["actions"].append("kp_nudge")
        return summary

    if level == InterventionLevel.STANDARD:
        current_loc = (
            state.get("current_loc")
            or (getattr(scenario_mgr, "location", "") if scenario_mgr else "")
            or ""
        )
        cause = detection.get("cause") or "lost_options"
        hint = build_reason_stagnation_hint(
            cause,
            scenario_mgr,
            current_loc,
            char_mgr=char_mgr,
            pl_id=state.get("pl_id") or state.get("active_pc_id"),
            repeat_key=detection.get("repeat_key"),
            fallback=STAGNATION_STANDARD_PL_HINT,
        )
        state["stagnation_pl_hint"] = hint
        state["stagnation_cause"] = cause
        state["all_events_log"].append({
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": hint,
            "meta": {
                "stagnation_hint": True,
                "location": current_loc,
                "cause": cause,
            },
        })
        summary["actions"].append("pl_hint")
        summary["cause"] = cause
        return summary

    relief = None
    if scenario_mgr and hasattr(scenario_mgr, "fire_stagnation_relief_event"):
        relief = scenario_mgr.fire_stagnation_relief_event()
    if relief:
        append_system_log_entry(
            state["all_events_log"],
            state.get("current_loc", scenario_mgr.location),
            relief.get("system_log", ""),
            action_id="stagnation_relief",
            target="",
            roll_type="stagnation_relief",
        )
        state["last_system_result"] = {
            "log": relief.get("system_log", ""),
            "kp_instruction": relief.get("kp_instruction", ""),
            "status": int(SuccessLevel.REGULAR_SUCCESS),
            "stagnation_progress": True,
            "san_check": relief.get("san_check", {"required": False}),
            "location_changed": bool(relief.get("location_changed")),
            "new_location": relief.get("new_location"),
        }
        if relief.get("new_location"):
            apply_location_change_side_effects(
                state,
                {
                    "location_changed": True,
                    "new_location": relief["new_location"],
                    "from_location": state.get("current_loc"),
                    "invalidate_pending_actions": True,
                },
                scenario_mgr=scenario_mgr,
                char_mgr=char_mgr,
            )
        if state_mgr:
            state_mgr.reset_stagnation_tracker(state.get("current_loc"), scenario_mgr.flags)
        scenario_mgr.reset_stagnation_counter()
        summary["actions"].append("relief_event")
        return summary

    pl_id = state.get("pl_id")
    char_name = state.get("char_name", "")
    idea = execute_forced_idea_roll(pl_id, char_name, char_mgr, dice_engine, scenario_mgr)
    append_system_log_entry(
        state["all_events_log"],
        state.get("current_loc", ""),
        idea["log"],
        action_id="idea_roll",
        target="",
        roll_type="idea_roll",
    )
    if idea.get("hint"):
        state["all_events_log"].append({
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": f"[システム] {idea['hint']}",
            "meta": {"idea_hint": True},
        })
    state["last_system_result"] = {
        "log": idea["log"],
        "kp_instruction": idea["kp_instruction"],
        "status": (
            int(SuccessLevel.REGULAR_SUCCESS) if idea["success"]
            else int(SuccessLevel.FAILURE)
        ),
        "stagnation_progress": bool(idea["success"]),
        "san_check": {"required": False},
    }
    if idea["success"]:
        if state_mgr:
            state_mgr.reset_stagnation_tracker(state.get("current_loc"), scenario_mgr.flags)
        scenario_mgr.reset_stagnation_counter()
    summary["actions"].append("idea_roll")
    summary["idea_success"] = idea["success"]
    return summary


def evaluate_and_apply_stagnation_intervention(state, managers, *, after_step=None):
    """膠着検知→介入レベルに応じた処理。

    計上タイミング:
      - system_process / luck_decision / push_decision: 確定したシステム結果を原則1回
      - pl_speak / free_chat: wait/OOC、および needs_pl_retry（SYSTEM未到達の拒否）
      - kp_eval 等では呼ばれない（描写リトライで加算しない）

    重複防止:
      - 非空 transaction_id の再実行のみスキップ（同一処理の再試行）
      - 行動内容や OOC テキストの一致ではスキップしない（別手番の反復は加算）
    """
    char_mgr, dice_engine, state_mgr, scenario_mgr = managers
    if not state_mgr or not scenario_mgr:
        return None
    if after_step not in (
        "system_process", "luck_decision", "push_decision", "pl_speak", "free_chat",
    ):
        return None

    # 戦闘中・シナリオ終了・SAN保留中は探索膠着介入を走らせない
    if state_mgr.in_combat:
        return None
    if is_game_cleared(scenario_mgr):
        return None
    if _is_san_check_pending(state.get("pending_san_check")):
        return None

    result = state.get("last_system_result")
    if result and (
        result.get("luck_decision_required")
        or result.get("push_decision_required")
    ):
        return None

    max_turns = scenario_mgr.get_max_stagnation_turns()
    pl_action = state.get("last_pl_action")
    chat_only = False
    validation_reject = False
    system_for_detect = None
    tid = ""

    if after_step in ("system_process", "luck_decision", "push_decision"):
        if not result:
            return None
        tid = str(
            resolve_stagnation_transaction_id(result, pl_action, state)
            or ""
        )
        # 進展は State Delta が正。マーカーだけで made_progress=True にしない。
        system_for_detect = result
    elif after_step in ("pl_speak", "free_chat"):
        validation_reject = bool((pl_action or {}).get("needs_pl_retry"))
        chat_only = is_chat_only_pl_action(pl_action, state.get("pending_san_check"))
        # IC の正常行動は system_process で計上。ここでは wait/OOC と検証拒否のみ。
        if not chat_only and not validation_reject:
            return None
        tid = str(resolve_stagnation_transaction_id(None, pl_action, state) or "")
        # needs_pl_retry は SYSTEM に行かないため、ここで必ず非進展候補にする
        if validation_reject:
            chat_only = False

    # v2 parallel log: normal IC actions settle after SYSTEM processing;
    # OOC and validation rejections settle at the PL step.
    record_unified_turn(
        state, scenario_mgr, state_mgr=state_mgr, char_mgr=char_mgr,
        result=system_for_detect, action=pl_action,
        origin=(pl_action or {}).get("action_origin"),
    )

    detection = _call_detect_stagnation(
        state_mgr, state, scenario_mgr, char_mgr,
        max_stagnation_turns=max_turns,
        last_pl_action=pl_action,
        last_system_result=system_for_detect,
        chat_only=chat_only,
        validation_reject=validation_reject,
        made_progress=False,
        transaction_id=tid or None,
        count_nonprogress=True,
    )
    scenario_mgr.stagnation_counter = detection["streak"]
    state["stagnation_streak"] = detection["streak"]
    if detection.get("cause"):
        state["stagnation_cause"] = detection["cause"]

    # 実際の進展でリセットされたら古いヒント・強制状態を解除
    if detection.get("reason") == "progress_or_moved" or int(detection.get("streak") or 0) == 0:
        if detection.get("reason") == "progress_or_moved":
            state["stagnation_pl_hint"] = None
            state["stagnation_kp_nudge"] = None
            state["stagnation_cause"] = None
            state["force_ic_action"] = False

    _maybe_set_introduction_stagnation_hint(state, scenario_mgr, state_mgr)

    if not detection.get("needs_intervention"):
        return detection
    if detection.get("skipped_duplicate"):
        return detection

    level = resolve_session_intervention_level(state, scenario_mgr)
    # 強介入（アイデアロール／固定行動）は 6 ターン程度まで遅延し、先にヒントへ落とす
    streak = int(detection.get("streak") or 0)
    if level >= InterventionLevel.FORCE and streak < STAGNATION_FORCE_TURNS:
        level = InterventionLevel.STANDARD
    applied = apply_stagnation_intervention(state, managers, level, detection)
    state_mgr.mark_stagnation_intervened()
    state["last_stagnation_intervention"] = applied
    return {**detection, "intervention": applied}


# 日常調査ロケ: オカルトSFXハルシネーションを禁止する
_MUNDANE_INVESTIGATION_LOCS = frozenset({
    "boston_globe",
    "central_library",
    "hall_of_records",
    "higher_courts_police_station",
    "introduction",
})


def _build_kp_mundane_location_directive(scenario_mgr=None, current_loc=None):
    """新聞社・図書館等の日常調査ロケでは怪異描写を禁止する。"""
    loc_id = str(
        current_loc
        or (getattr(scenario_mgr, "location", "") if scenario_mgr else "")
        or ""
    ).strip()
    if not loc_id or loc_id not in _MUNDANE_INVESTIGATION_LOCS:
        return ""
    loc_name = loc_id
    if scenario_mgr:
        loc_name = (scenario_mgr.get_location_info(loc_id) or {}).get("name") or loc_id
    kind = "日常の調査施設"
    if loc_id == "boston_globe":
        kind = "現実の新聞社"
    elif loc_id == "central_library":
        kind = "現実の図書館"
    elif loc_id == "hall_of_records":
        kind = "現実の公文書館"
    return (
        f"- 【日常調査ロケーション制約・絶対禁止】現在地は{kind}『{loc_name}』である。"
        "現時点でオカルト現象（奇怪な音、ささやき声、怪異、不気味な気配、幻視、"
        "超常的な振動など）を描写することは**絶対禁止**。"
        "シナリオ未記載の怪異SFXを捏造せず、事務的・日常的な空間として描写せよ。\n"
    )


def _build_kp_narrative_constraints():
    """KP向け: PC拉致・勝手な移動・未定義オブジェクト創作の禁止。"""
    return f"""
【⚠️演出上の厳禁事項】
あなたは「システム進行役としてのKP」と「アドリブを楽しむプレイヤーとしてのKP」の多層的な意識を持ちます。
情景描写や判定要求を行う際、**「探索者が勝手に次の行動を起こした」と仮定してナレーションしてはなりません**。
（例：「あなたは扉を開けて隣室へ進み出します」「探索者は机を調べ始めた」などは厳禁です。）
重要な変化を描写したところで止め、**必ず「どうしますか？」とPLの意志を確認**してください。
PCの体を動かせるのはPL（AIプレイヤー）だけです。KPは世界の描写と結果の伝達のみを行います。

【厳格描写ルール（重要）】
1. あなたはシナリオJSONの `locations` や `objects`、および開示された `secrets`（秘密）に**直接記載されていない情報を絶対に勝手に付け足して描写してはなりません**。
2. ダイスが成功した場合でも、システムから提供された `payload`（または `description`）の範囲内でのみ真実を語ってください。TRPGの雰囲気を出すための演出は「感覚的な表現（部屋の匂い、静けさ、きしみ音など）」に留め、**「呪文」「奇妙なルール」「地下の怪音」といったプロットに関わる具体的なファクト（事実）を勝手に捏造することを厳禁**とします。
3. 手がかりが存在しない空のオブジェクト（例: office_desk）が調査された際は、PLに執着させないよう、はっきりと「これ以上調査しても、今回の依頼に役立つ情報は何もなさそうだ」と明確に引導を渡す描写をしてください。
4. **手がかりが発見された場合**（成功判定・payload に新情報がある場合）は、発見した事実のみをシンプルに伝え、次の行動（移動・別対象の調査など）へ進めるよう自然に促してください。
   「これ以上調べても無駄」「進展はない」といった**メタ的な制限描写を、発見事実と同じ発言内で混ぜない**こと（矛盾描写の禁止）。

【シナリオ接地・創作禁止（厳守）】
- 描写してよい物体・痕跡は、システムが渡した【現在地のオブジェクト】と場所の基本描写に載っているもの**だけ**です。
- 一覧に無い構造物（他シナリオの鉄格子・隠し引き出し・紋章・偶像など）を**追加で作らない**こと。
- オブジェクトの description に書かれていない隠し構造も仮定しないこと。
- システムが渡した【開示可能な確定情報】以外の「新聞に無い記事」「未記載の地下室」「未定義のドア規則」等を成功描写で追加しないこと。
- {KP_LOCKED_ROUTE_GUARD}
- ダイス成功時は「特に何も見つからなかった」と空振りさせないこと。システムが注入した確定手がかりを必ず描写に含めること。

【描写NG例（このような文は生成しない）】
- 「あなたが地下室から抜け出してきた」「探索者は廊下へ進み出した」→ 移動の**過程**を代行する描写
- 「探索者は〜を調べ始めた」「手を伸ばして〜に触れた」→ 未確定の行動の先取り
- 「押し直すと」「もう一度ボタンを押すと」→ 初回作動の場面では「押すと」「ボタンを押すと」を使う
- システムが確定していない発見・移動・ダメージを、既に起きた事実として書くこと
- システム一覧に無い小道具を「ある」かのように描写すること
- オブジェクト description に無い「呪文の文字列」「特定の日にしか開かないドア」などを事実として書くこと
- 新聞社・図書館など日常調査ロケで「奥から不気味な音やささやき声」等のオカルトSFXを付けること
- 許可取得済みなのに追加の承認者・門前払いを要求すること
- システムが確定した技能と異なる技能で「成功した」と描写すること
- SAN減少だけから記憶喪失・知識削除・発狂・行動不能を確定すること
"""


def _build_kp_situational_directives(scenario_mgr=None, last_system_result=None, state=None):
    """状況に応じた KP 向け追加制約。"""
    parts = [
        "【表現・視点の常時制約】\n"
        "- 【表現制約】出力は100%自然な日本語のみを使用すること（英単語やメタニカルな注釈の混入は厳禁）。\n"
        "- 【視点制約】KPは状況と環境、NPCの反応のみを描写すること。"
        "PC（プレイヤーキャラクター）の台詞や内面心理を勝手に代弁・決定してはならない。\n"
        "- 【メタ文禁止】システム内部用語・秘密キー名・フラグ定義文・"
        "『…と主張する』『secret_』『flags.』『action_id』等をそのまま読み上げるな。"
        "開示情報は自然な会話・情景に翻訳して伝えよ。\n"
    ]
    room_state = _build_kp_room_state_directive(scenario_mgr)
    if room_state:
        parts.append(room_state)
    remaining_hints = _list_uninvestigated_object_hints(
        scenario_mgr,
        loc_id=(state or {}).get("current_loc") or getattr(scenario_mgr, "location", None),
        limit=4,
    )
    if remaining_hints:
        parts.append(
            "【未調査の残・絶対禁止】この場所にはまだ調べる対象がある: "
            + "、".join(remaining_hints)
            + "。"
            "『この場所から手がかりはもうない』『これ以上何も引き出せない』と場所全体を打ち切るな。"
            "今回調べた対象が済んだなら、残りの対象を自然に促せ。\n"
        )
    idol_directive = _build_kp_idol_steering_directive(scenario_mgr)
    if idol_directive:
        parts.append(idol_directive)

    stagnation_injection = _build_kp_stagnation_injection(scenario_mgr, state=state)
    if stagnation_injection:
        parts.append(stagnation_injection + "\n")

    lines = []
    if scenario_mgr:
        flags = scenario_mgr.flags
        loc_for_clip = (
            (state or {}).get("current_loc")
            or getattr(scenario_mgr, "location", "")
            or ""
        )
        mundane = _build_kp_mundane_location_directive(scenario_mgr, loc_for_clip)
        if mundane:
            lines.append(mundane.rstrip("\n"))
        if flags.get("artie_reference_room_access_granted"):
            if is_boston_globe_clipping_investigated(scenario_mgr):
                lines.append(
                    "- 【グローブ調査完了】切り抜き調査は済んでいる。"
                    "アーティ／受付への再交渉・門前払い・ルース呼び出しは禁止。"
                    "中央図書館・公文書館など次の調査先への移動を自然に促せ。"
                )
            elif _clipping_files_search_pending(scenario_mgr, loc_for_clip or "boston_globe"):
                lines.append(ARTIE_ACCESS_GRANTED_KP_DIRECTIVE)
            else:
                lines.append(
                    "- 【絶対遵守・許可済み】アーティから参考資料室への入室・閲覧許可は**既に降りている**。"
                    "アーティおよび受付による追加条件要求・別人物（ルース等）への誘導・"
                    "部外者扱い描写を完全に禁止する。"
                    "門前払い・『許可が必要』『裁量次第』『手続きが必要』『まだ入れない』"
                    "『ルース・ブレイクなら教えてくれる』等の描写・台詞は厳禁。"
                    "資料室の切り抜きファイル（`reference_room_clipping_files`）へ直接案内し、"
                    "調査を促す描写のみを行うこと。"
                )
            # 許可が今ターン付与された直後は、さらに強く search 案内を強制
            if last_system_result and (
                "アクセス許可が出た" in str(last_system_result.get("log") or "")
                or (last_system_result.get("social") or {}).get("access_just_granted")
            ):
                lines.append(
                    "- 【今ターン確定】閲覧許可は本ターンで付与済み。"
                    "ルース経由の追加許可・門前払いを一切書かず、"
                    "`reference_room_clipping_files` の調査を即案内すること。"
                )

        if (
            (loc_for_clip or getattr(scenario_mgr, "location", "")) == "central_library"
        ):
            if last_system_result and is_failure_level(int(last_system_result.get("status") or 0)):
                target = str(last_system_result.get("target") or "")
                if target in ("newspaper_archives", "local_history_section"):
                    lines.append(
                        "- 【図書館・失敗時制約】1回の search 失敗で"
                        "『もう手がかりはない』『これ以上調べても無駄』と締めるな。"
                        "プッシュや別技能での再挑戦、未調査オブジェクト、"
                        "または公文書館（`hall_of_records`）への move を促せ。"
                    )
            if not flags.get("found_corbitt_history_all") or not flags.get("found_newspaper_article_1918"):
                lines.append(
                    "- 【図書館・進行】未発見の資料がある間は『調査完了』と宣言するな。"
                    "新聞アーカイブと郷土史の両方を意識し、手詰まりなら公文書館へ誘導せよ。"
                )

        # 屋敷1階: 雑談より居間ガラクタ／地下室ドアの調査を促す
        if (loc_for_clip or getattr(scenario_mgr, "location", "")) == "corbitt_ground_floor":
            lines.append(
                "- 【屋敷1階・調査誘導】不在NPCとの会話や雑談へ誘導するな。"
                "居間のガラクタ・家具（`living_room_clutter` / 別名 `living_room_junk`）と"
                "地下室へのドア（`basement_door`）の search/inspect を自然に促せ。"
                "『誰かに話しかける』より室内の物を調べる描写を優先せよ。"
            )
        if (
            flags.get("gate_opened")
            and scenario_mgr.location == "altar_room"
            and _scenario_has_object(scenario_mgr, "iron_gate", "altar_room")
        ):
            lines.append(
                "- 【最優先・今回の状況】鉄格子は**既に開放済み**です。"
                "向こうに**深い闇**が見えています。"
                "「まだ閉ざされている」などの矛盾描写は**厳禁**です。"
            )
        if flags.get("door_opened") and _scenario_object_exists_anywhere(scenario_mgr, "iron_door"):
            if flags.get("button_pushed"):
                open_route = "隠しボタン作動により扉が開いた"
            else:
                open_route = "力ずくで扉が開いた"
            lines.append(
                "- 【最優先・今回の状況】鉄の扉は**既に開放済み**です。"
                "扉は開いたままで、向こうに**暗い廊下**が見えています。"
                f"（{open_route}）"
                "「固く閉ざされた扉」「まだ開かない」などの矛盾描写は**厳禁**です。"
                "開いた結果と次の行動（move / target: hallway）を自然に促してください。"
            )
        if (
            flags.get("found_button")
            and not flags.get("button_pushed")
            and _scenario_object_exists_anywhere(scenario_mgr, "desk")
        ):
            lines.append(
                "- 【今回の状況】隠しボタンは**未作動**。描写は「初めて押す」前提とし、「押し直す」「再度押す」は禁止。"
            )
    if last_system_result and last_system_result.get("location_changed"):
        lines.append(
            "- 【今回の状況】場所移動はシステム確定済み。**到着した場所の静態描写のみ**。"
            "「向かった」「進み出した」などの移動過程は書かない。"
        )
    if last_system_result:
        if last_system_result.get("san_auto_resolved"):
            lines.append(
                "- 【緊急・SAN自動解決済み】探索者のSANチェックはシステムにより既に処理済みです。"
                "『どうしますか？』で締めず、恐怖が脳裏を支配する緊迫した描写で締めてください。"
                "PLに行動の選択肢を与えないでください。"
            )
        else:
            san_directive = _build_kp_san_check_directive(last_system_result.get("san_check"))
            if san_directive:
                lines.append(san_directive)
        npc_rp = last_system_result.get("npc_roleplay") or {}
        if npc_rp.get("prompt_block"):
            lines.append(
                "- 【NPCロールプレイ連動】下記の態度・開示情報に忠実に NPC として振る舞うこと。"
                "未開示の秘密を勝手に明かしてはならない。"
            )
    if lines:
        parts.append("【状況別の追加制約】\n" + "\n".join(lines) + "\n")
    return "".join(parts)


def _validate_stale_boston_globe_talk(
    pc_action,
    *,
    scenario_mgr=None,
    current_loc="",
    char_mgr=None,
):
    """受付ループ／アーティ雑談・許可後再交渉ループを即時拒絶する。"""
    action = str((pc_action or {}).get("action", "wait") or "wait").lower()
    target = str((pc_action or {}).get("target", "") or "")

    # 許可取得後・調査完了後: フェーズに応じた誘導
    post_access = _validate_post_access_must_search(
        pc_action, scenario_mgr=scenario_mgr, current_loc=current_loc,
    )
    # 会話意図を保持するケースは、後続の stale 判定で上書きしない
    if post_access.get("preserve_social_intent"):
        return post_access
    if not post_access.get("ok"):
        return post_access

    if not is_stale_boston_globe_talk(
        action, target,
        scenario_mgr=scenario_mgr,
        current_loc=current_loc,
        char_mgr=char_mgr,
    ):
        return {"ok": True}

    guidance = build_boston_globe_stale_guidance(scenario_mgr, current_loc)
    return {
        "ok": False,
        "error": guidance.get("error") or STALE_ARTIE_TALK_REJECT_ERROR,
        "error_code": guidance.get("error_code") or "stale_artie_talk",
        "suggested_fix": guidance.get("suggested_fix") or {
            "action": "persuade",
            "target": "artie_wilmott",
            "skill": "説得",
        },
        "needs_pl_retry": True,
    }


def _validate_post_access_must_search(
    pc_action,
    *,
    scenario_mgr=None,
    current_loc="",
):
    """許可取得後／調査完了後の会話・wait をフェーズ別に拒否する。"""
    loc = str(
        current_loc
        or (getattr(scenario_mgr, "location", "") if scenario_mgr else "")
        or ""
    )
    if loc != "boston_globe":
        return {"ok": True}

    action = str((pc_action or {}).get("action", "wait") or "wait").lower()
    target = str((pc_action or {}).get("target", "") or "")
    is_socialish = (
        action in TALK_ACTION_IDS
        or action in NEGOTIATION_ACTION_IDS
        or action in ("wait", "none", "")
    )

    # 調査完了後: 在場 NPC への会話・交渉は許可し、次ロケはヒントで提案する
    if is_boston_globe_clipping_investigated(scenario_mgr):
        if action in ("search", "inspect") and target == "reference_room_clipping_files":
            return {"ok": True}
        if is_socialish:
            guidance = build_boston_globe_stale_guidance(scenario_mgr, loc)
            suggested = guidance.get("suggested_fix") or {
                "action": "move",
                "target": "central_library",
            }
            is_talkish = action in TALK_ACTION_IDS or action in NEGOTIATION_ACTION_IDS
            if is_talkish and target:
                return {
                    "ok": True,
                    "preserve_social_intent": True,
                    "nonprogress_social": True,
                    "next_location_hint": (
                        guidance.get("error") or BOSTON_GLOBE_INVESTIGATION_DONE_HINT
                    ),
                    "suggested_fix": suggested,
                }
            return {
                "ok": False,
                "error": guidance.get("error") or BOSTON_GLOBE_INVESTIGATION_DONE_HINT,
                "error_code": guidance.get("error_code") or "globe_investigation_done",
                "suggested_fix": suggested,
                "needs_pl_retry": True,
            }
        return {"ok": True}

    if not _clipping_files_search_pending(scenario_mgr, loc):
        return {"ok": True}
    if action in ("search", "inspect") and target == "reference_room_clipping_files":
        return {"ok": True}
    if action == "move":
        return {"ok": True}
    if is_socialish:
        return {
            "ok": False,
            "error": ARTIE_ACCESS_GRANTED_SEARCH_HINT,
            "error_code": "stale_post_access_social",
            "suggested_fix": {
                "action": "search",
                "target": "reference_room_clipping_files",
                "skill": "目星",
            },
            "needs_pl_retry": True,
        }
    return {"ok": True}


def _build_pc_display_message(
    dialogue, action="", target="", action_locked=False, scenario_mgr=None, current_loc=None,
):
    """ICログ用の表示文を組み立てる（コマンドのみ出力を防ぐ）。"""
    dialogue = _sanitize_pc_dialogue(dialogue, scenario_mgr, current_loc)
    if action_locked:
        return dialogue or "（恐怖に震え、言葉を失っている）"

    if dialogue:
        return dialogue

    if action in ("", "wait", "none"):
        return "様子を見る"

    target_label = _resolve_target_label(scenario_mgr, current_loc, target)
    narration_fallbacks = {
        "search": f"「……{target_label}、調べてみよう」",
        "inspect": f"{target_label}を詳しく調べる。",
        "talk": f"{target_label}に話しかける。",
        "persuade": f"{target_label}に説得を試みる。",
        "move": f"「……{target_label}へ向かおう」",
        "push": f"「……{target_label}、押してみるか」",
        "push_roll": "「……もう一度、慎重にやってみよう」",
        "climb": f"「……{target_label}、登ってみる」",
        "break": f"「……{target_label}、力ずくでこじ開けてみる」",
        "kick": f"「……{target_label}、蹴ってみるか」",
        "use": f"「……{target_label}を使ってみよう」",
    }
    return narration_fallbacks.get(action, f"「……{target_label}に向かう」")


def _enforce_san_lock_pc_action(pc_action, pl_ooc_chat=""):
    """SAN保留中はシステムへ wait のみ渡す。"""
    dialogue = pc_action.get("dialogue", "") or pl_ooc_chat
    display = _build_pc_display_message(dialogue, action_locked=True)
    return {
        "action": "wait",
        "target": "",
        "skill": "",
        "message": display,
        "dialogue": dialogue,
    }


def parse_pl_response(raw_data, action_locked=False):
    """多層意識 PL JSON をシステム互換形式に正規化する。"""
    if not isinstance(raw_data, dict):
        raw_data = {}

    # 旧スキーマ互換
    if "pc_action" in raw_data and "content" not in raw_data:
        pc_action = raw_data.get("pc_action") or {}
        return {
            "thought": raw_data.get("thought", ""),
            "should_speak": raw_data.get("should_speak", True),
            "speak_as": _normalize_speak_as("BOTH" if raw_data.get("pl_chat") else "PC"),
            "pl_ooc_chat": raw_data.get("pl_chat", ""),
            "pc_action": {
                "action": pc_action.get("action", "wait"),
                "target": pc_action.get("target", ""),
                "skill": pc_action.get("skill", "") if str(pc_action.get("action", "wait") or "wait").lower() == "search" else "",
                "skill_proposal_reason": pc_action.get("skill_proposal_reason", ""),
                "message": pc_action.get("message", "様子を見る"),
                "dialogue": pc_action.get("message", ""),
            },
        }

    content = raw_data.get("content") or {}
    speak_as = _normalize_speak_as(raw_data.get("speak_as", "PC"))
    should_speak = bool(raw_data.get("should_speak", True))
    pl_ooc_chat = str(content.get("pl_ooc_chat", "") or "")
    pc_ic = content.get("pc_ic_action") or {}

    action = str(pc_ic.get("action", "wait") or "wait").lower()
    target = str(pc_ic.get("target", "") or "")
    dialogue = str(pc_ic.get("dialogue", "") or "")
    skill = str(pc_ic.get("skill", "") or "")
    proposal_reason = str(pc_ic.get("skill_proposal_reason", "") or "")
    if action not in ("search", "inspect"):
        skill = ""
        proposal_reason = ""

    message = _build_pc_display_message(dialogue, action, target, action_locked=action_locked)

    if speak_as == "PL" and action in ("", "wait"):
        action = "wait"
        message = dialogue or pl_ooc_chat or "（様子を見ている）"

    pc_action = {
        "action": action,
        "target": target,
        "skill": skill,
        "skill_proposal_reason": proposal_reason,
        "message": message,
        "dialogue": dialogue,
    }

    if action_locked:
        pc_action = _enforce_san_lock_pc_action(pc_action, pl_ooc_chat)

    return {
        "thought": str(raw_data.get("thought", "") or ""),
        "should_speak": should_speak,
        "speak_as": speak_as,
        "pl_ooc_chat": pl_ooc_chat,
        "pc_action": pc_action,
    }


def parse_pl_luck_response(raw_data):
    """幸運判断用 PL JSON を正規化する。"""
    if not isinstance(raw_data, dict):
        raw_data = {}

    if "use_luck" in raw_data and "content" not in raw_data:
        ooc = str(raw_data.get("pl_chat", "") or raw_data.get("pl_ooc_chat", "") or "")
        use_luck = raw_data.get("use_luck")
        if use_luck is None:
            use_luck = _parse_yes_no_flag(ooc, default=False)
        return {
            "thought": raw_data.get("thought", ""),
            "should_speak": True,
            "speak_as": "PL",
            "pl_ooc_chat": ooc,
            "use_luck": bool(use_luck),
        }

    content = raw_data.get("content") or {}
    ooc = str(content.get("pl_ooc_chat", "") or "")
    use_luck = content.get("use_luck")
    if use_luck is None:
        use_luck = _parse_yes_no_flag(ooc, default=False)
    return {
        "thought": str(raw_data.get("thought", "") or ""),
        "should_speak": bool(raw_data.get("should_speak", True)),
        "speak_as": _normalize_speak_as(raw_data.get("speak_as", "PL")),
        "pl_ooc_chat": ooc,
        "use_luck": bool(use_luck),
    }


def parse_pl_push_response(raw_data):
    """プッシュ判断用 PL JSON を正規化する。"""
    if not isinstance(raw_data, dict):
        raw_data = {}

    if "use_push" in raw_data and "content" not in raw_data:
        ooc = str(raw_data.get("pl_chat", "") or raw_data.get("pl_ooc_chat", "") or "")
        use_push = raw_data.get("use_push")
        if use_push is None:
            use_push = _parse_yes_no_flag(ooc, default=False)
        return {
            "thought": raw_data.get("thought", ""),
            "should_speak": True,
            "speak_as": "PL",
            "pl_ooc_chat": ooc,
            "use_push": bool(use_push),
            "push_approach": str(raw_data.get("push_approach", "") or ""),
        }

    content = raw_data.get("content") or {}
    ooc = str(content.get("pl_ooc_chat", "") or "")
    use_push = content.get("use_push")
    if use_push is None:
        use_push = _parse_yes_no_flag(ooc, default=False)
    return {
        "thought": str(raw_data.get("thought", "") or ""),
        "should_speak": bool(raw_data.get("should_speak", True)),
        "speak_as": _normalize_speak_as(raw_data.get("speak_as", "PL")),
        "pl_ooc_chat": ooc,
        "use_push": bool(use_push),
        "push_approach": str(content.get("push_approach", "") or ""),
    }


def parse_pl_combat_defense_response(raw_data):
    """戦闘防衛（回避／応戦）用 PL JSON を正規化する。"""
    if not isinstance(raw_data, dict):
        raw_data = {}

    if "defense_mode" in raw_data and "content" not in raw_data:
        ooc = str(raw_data.get("pl_chat", "") or raw_data.get("pl_ooc_chat", "") or "")
        return {
            "thought": raw_data.get("thought", ""),
            "should_speak": True,
            "speak_as": "BOTH",
            "pl_ooc_chat": ooc,
            "defense_mode": _normalize_defense_mode(raw_data.get("defense_mode")),
            "dialogue": str(raw_data.get("dialogue", "") or ""),
        }

    content = raw_data.get("content") or {}
    ooc = str(content.get("pl_ooc_chat", "") or "")
    mode = content.get("defense_mode")
    if mode is None:
        if any(k in ooc for k in ("応戦", "反撃", "fight")):
            mode = "fight_back"
        elif any(k in ooc for k in ("回避", "dodge", "よける")):
            mode = "dodge"
        else:
            mode = "dodge"
    pc = content.get("pc_ic_action") or {}
    return {
        "thought": str(raw_data.get("thought", "") or ""),
        "should_speak": bool(raw_data.get("should_speak", True)),
        "speak_as": _normalize_speak_as(raw_data.get("speak_as", "BOTH")),
        "pl_ooc_chat": ooc,
        "defense_mode": _normalize_defense_mode(mode),
        "dialogue": str(pc.get("dialogue", "") or ""),
    }


def parse_pl_shoot_defense_response(raw_data):
    """射撃防衛（回避／甘受）用 PL JSON。応戦が来ても生値を残しガード側で拒否する。"""
    if not isinstance(raw_data, dict):
        raw_data = {}

    if "defense_mode" in raw_data and "content" not in raw_data:
        ooc = str(raw_data.get("pl_chat", "") or raw_data.get("pl_ooc_chat", "") or "")
        mode, _rejected = _normalize_shoot_defense_mode(raw_data.get("defense_mode"))
        # 拒否検出のため fight_back はそのまま残す
        raw_mode = str(raw_data.get("defense_mode") or "").strip().lower()
        if raw_mode in ("fight_back", "fighting_back", "応戦", "fightback", "counter", "反撃"):
            stored = "fight_back"
        else:
            stored = mode or "dodge"
        return {
            "thought": raw_data.get("thought", ""),
            "should_speak": True,
            "speak_as": "BOTH",
            "pl_ooc_chat": ooc,
            "defense_mode": stored,
            "dialogue": str(raw_data.get("dialogue", "") or ""),
        }

    content = raw_data.get("content") or {}
    ooc = str(content.get("pl_ooc_chat", "") or "")
    mode = content.get("defense_mode")
    if mode is None:
        if any(k in ooc for k in ("応戦", "反撃", "fight_back", "fight back")):
            mode = "fight_back"
        elif any(k in ooc for k in ("甘ん", "甘受", "受け入れる", "accept", "受け止める")):
            mode = "accept"
        elif any(k in ooc for k in ("回避", "dodge", "よける", "飛び込む")):
            mode = "dodge"
        else:
            mode = "dodge"
    normalized, rejected = _normalize_shoot_defense_mode(mode)
    stored = "fight_back" if rejected else (normalized or "dodge")
    pc = content.get("pc_ic_action") or {}
    return {
        "thought": str(raw_data.get("thought", "") or ""),
        "should_speak": bool(raw_data.get("should_speak", True)),
        "speak_as": _normalize_speak_as(raw_data.get("speak_as", "BOTH")),
        "pl_ooc_chat": ooc,
        "defense_mode": stored,
        "dialogue": str(pc.get("dialogue", "") or ""),
    }


def default_pl_shoot_defense_response():
    return parse_pl_shoot_defense_response({
        "thought": "銃弾を避けて物陰へ飛び込む。",
        "should_speak": True,
        "speak_as": "BOTH",
        "content": {
            "pl_ooc_chat": "回避する",
            "defense_mode": "dodge",
            "pc_ic_action": {"dialogue": "", "action": "defend", "target": "", "skill": ""},
        },
    })


def _parse_yes_no_flag(text, default=False):
    """OOC文字列から yes/no を推定する。"""
    raw = str(text or "").strip().lower()
    if not raw:
        return default
    if re.search(r"\b(yes|y|true|1)\b", raw) or raw in ("はい", "する", "消費", "プッシュ"):
        return True
    if re.search(r"\b(no|n|false|0)\b", raw) or raw in ("いいえ", "しない", "温存", "見送"):
        return False
    if any(k in raw for k in ("消費する", "プッシュする", "再挑戦", "やりなお", "やり直")):
        return True
    if any(k in raw for k in ("温存", "見送", "しない", "諦める", "断念", "拒否")):
        return False
    return default


def parse_kp_response(raw_data):
    """多層意識 KP JSON をログ用形式に正規化する。"""
    if isinstance(raw_data, str):
        text = raw_data.strip()
        return {
            "thought": "",
            "should_speak": bool(text),
            "speak_mode": "system_narration",
            "text": text or "（通信エラー）KPの思考が途切れました。",
        }

    if not isinstance(raw_data, dict):
        raw_data = {}

    text = str(raw_data.get("text", "") or "").strip()
    should_speak = bool(raw_data.get("should_speak", True))
    if not text and should_speak:
        text = "（KPは一瞬言葉を失った…）どうしますか？"

    return {
        "thought": str(raw_data.get("thought", "") or ""),
        "should_speak": should_speak,
        "speak_mode": _normalize_speak_mode(raw_data.get("speak_mode")),
        "text": text,
    }


def default_pl_action_response():
    return parse_pl_response({
        "thought": "判断に失敗した。とりあえず様子を見る。",
        "should_speak": True,
        "speak_as": "PC",
        "content": {
            "pl_ooc_chat": "",
            "pc_ic_action": {
                "dialogue": "（頭がぼんやりとして、どうすればいいか分からない…）",
                "action": "wait",
                "target": "",
                "skill": "",
            },
        },
    })


def default_pl_luck_response():
    return parse_pl_luck_response({
        "thought": "迷ったが、幸運は温存する。",
        "should_speak": True,
        "speak_as": "PL",
        "content": {
            "pl_ooc_chat": "no（判断に迷っている…）",
            "use_luck": False,
        },
    })


def default_pl_push_response():
    return parse_pl_push_response({
        "thought": "リスクが高いのでプッシュは見送る。",
        "should_speak": True,
        "speak_as": "PL",
        "content": {
            "pl_ooc_chat": "no（失敗を受け入れる）",
            "use_push": False,
            "push_approach": "",
        },
    })


def default_pl_combat_defense_response():
    return parse_pl_combat_defense_response({
        "thought": "危険を避けて回避する。",
        "should_speak": True,
        "speak_as": "BOTH",
        "content": {
            "pl_ooc_chat": "回避する",
            "defense_mode": "dodge",
            "pc_ic_action": {"dialogue": "", "action": "defend", "target": "", "skill": ""},
        },
    })


def default_kp_response(fallback_text=""):
    fallback = str(fallback_text or "").strip()
    if fallback:
        if fallback.startswith("システム:"):
            fallback = fallback[len("システム:"):].strip()
        text = fallback
        if "どうしますか" not in text:
            text = text.rstrip() + "\nどうしますか？"
    else:
        text = "（通信エラー）描写を再構成しています。直前の判定結果に沿って行動を続けてください。どうしますか？"
    return parse_kp_response({
        "thought": "通信障害のため、システム確定情報から最低限の進行を行う。",
        "should_speak": True,
        "speak_mode": "system_narration",
        "text": text,
    })


def _call_chat_completion(
    messages,
    model,
    temperature,
    max_retries=3,
    json_mode=False,
    *,
    role="unknown",
    purpose="chat_completion",
    retry_count_base=0,
    _force_primary=False,
    _fallback_from_secondary=False,
):
    """OpenAI 互換 chat.completions 呼び出し（指数バックオフ付き）。"""
    cfg = get_llm_config()
    canonical_role = canonicalize_llm_role(role)
    endpoint = resolve_ollama_endpoint(canonical_role, cfg, force_primary=_force_primary)
    client = get_client(canonical_role, force_primary=_force_primary)
    wait_time = 4
    use_json_mode = json_mode
    last_error = None
    call_id = f"llm_{uuid.uuid4().hex}"
    call_started = time.perf_counter_ns()
    prompt_payload = json.dumps(messages, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    system_payload = "\n".join(
        str(message.get("content") or "") for message in messages
        if str(message.get("role") or "").lower() == "system"
    )

    def routing_fields(max_tokens_value):
        generation_params = {
            "model": model,
            "temperature": temperature,
            "max_tokens": max_tokens_value,
            "json_mode": bool(json_mode),
        }
        return {
            "llm_role": canonical_role,
            "endpoint_class": endpoint["endpoint_class"],
            "requested_endpoint_class": endpoint["requested_endpoint_class"],
            "endpoint_url_redacted": endpoint["endpoint_url_redacted"],
            "execution_host": endpoint["execution_host"],
            "remote": endpoint["remote"],
            "config_fallback": endpoint["config_fallback"],
            "fallback_from_secondary": bool(_fallback_from_secondary),
            "prompt_hash": hashlib.sha256(prompt_payload.encode("utf-8")).hexdigest(),
            "system_prompt_hash": hashlib.sha256(system_payload.encode("utf-8")).hexdigest(),
            "generation_params_hash": hashlib.sha256(
                json.dumps(generation_params, sort_keys=True, separators=(",", ":")).encode("utf-8")
            ).hexdigest(),
        }

    for attempt in range(max_retries):
        try:
            time.sleep(2)
            kwargs = {
                "model": model,
                "messages": messages,
                "temperature": temperature,
            }
            if use_json_mode:
                kwargs["response_format"] = {"type": "json_object"}
            max_tokens = int(cfg.get("max_tokens") or DEFAULT_LLM_MAX_TOKENS)
            if max_tokens > 0:
                kwargs["max_tokens"] = max_tokens

            attempt_started = time.perf_counter_ns()
            response = client.chat.completions.create(**kwargs)
            attempt_finished = time.perf_counter_ns()
            choice = response.choices[0]
            content = choice.message.content
            finish_reason = str(getattr(choice, "finish_reason", "") or "")
            if content is None:
                raise ValueError("LLM が空の応答を返しました")
            content = content.strip()
            if finish_reason == "length":
                raise ValueError("LLM 出力が max_tokens で途切れました (finish_reason=length)")
            payload, usage = _llm_response_extra(response)
            prompt_count = (
                payload.get("prompt_eval_count")
                if payload.get("prompt_eval_count") is not None
                else usage.get("prompt_tokens")
            )
            eval_count = (
                payload.get("eval_count")
                if payload.get("eval_count") is not None
                else usage.get("completion_tokens")
            )
            prompt_duration = payload.get("prompt_eval_duration")
            eval_duration = payload.get("eval_duration")
            native_total_duration = payload.get("total_duration")
            total_duration = native_total_duration or (attempt_finished - call_started)
            generation_seconds = (
                float(eval_duration) / 1_000_000_000
                if eval_duration else (attempt_finished - attempt_started) / 1_000_000_000
            )
            tokens_per_second = (
                round(float(eval_count) / generation_seconds, 6)
                if eval_count is not None and generation_seconds > 0 else None
            )
            _record_llm_metric({
                "call_id": call_id,
                "role": canonical_role,
                "purpose": purpose,
                "model": model,
                **routing_fields(max_tokens),
                "prompt_eval_count": prompt_count,
                "prompt_eval_duration": prompt_duration,
                "eval_count": eval_count,
                "eval_duration": eval_duration,
                "total_duration": total_duration,
                "load_duration": payload.get("load_duration"),
                "retry_count": int(retry_count_base) + attempt,
                "attempt_count": attempt + 1,
                "tokens_per_second": tokens_per_second,
                "time_to_first_token": None,
                "wall_duration_seconds": round((attempt_finished - call_started) / 1_000_000_000, 6),
                "total_duration_source": "ollama" if native_total_duration else "client_wall_clock",
                "finish_reason": finish_reason,
                "status": "SUCCESS",
            })
            return content

        except Exception as exc:
            last_error = exc
            print(f"\n[LLM API エラー - 試行 {attempt + 1}/{max_retries}] {exc}")
            _log_model_not_found_hint(exc, model)

            if _is_model_not_found_error(exc):
                break

            if use_json_mode and _is_json_format_unsupported(exc):
                print("response_format 未対応を検知。JSON モードなしで再試行します...")
                use_json_mode = False
                continue

            if _is_retryable_llm_error(exc) and attempt < max_retries - 1:
                print(f"再試行まで {wait_time} 秒待機します...")
                time.sleep(wait_time)
                wait_time *= 2
                continue
            break

    call_finished = time.perf_counter_ns()
    error_class = _classify_ollama_error(last_error or RuntimeError("LLM API 呼び出しに失敗しました"))
    max_tokens = int(cfg.get("max_tokens") or DEFAULT_LLM_MAX_TOKENS)
    failure_metric = {
        "call_id": call_id,
        "role": canonical_role,
        "purpose": purpose,
        "model": model,
        **routing_fields(max_tokens),
        "prompt_eval_count": None,
        "prompt_eval_duration": None,
        "eval_count": None,
        "eval_duration": None,
        "total_duration": call_finished - call_started,
        "load_duration": None,
        "retry_count": int(retry_count_base) + max(0, max_retries - 1),
        "attempt_count": max_retries,
        "tokens_per_second": None,
        "time_to_first_token": None,
        "wall_duration_seconds": round((call_finished - call_started) / 1_000_000_000, 6),
        "total_duration_source": "client_wall_clock",
        "finish_reason": None,
        "status": "ERROR",
        "error_class": error_class,
        "error": str(last_error or "LLM API 呼び出しに失敗しました")[:500],
    }
    infrastructure_error = error_class in {
        "REMOTE_MODEL_UNAVAILABLE", "REMOTE_OLLAMA_TIMEOUT", "REMOTE_OLLAMA_CONNECTION_ERROR",
    }
    policy = str(cfg.get("secondary_failure_policy") or "FAIL_CLOSED").upper()
    if endpoint["remote"] and infrastructure_error and policy == "FALLBACK_PRIMARY":
        failure_metric["fallback_triggered"] = True
        _record_llm_metric(failure_metric)
        print(f"[Ollama routing] {error_class}; Judge fallback SECONDARY -> PRIMARY")
        return _call_chat_completion(
            messages,
            model,
            temperature,
            max_retries=max_retries,
            json_mode=json_mode,
            role=canonical_role,
            purpose=purpose,
            retry_count_base=int(retry_count_base) + max_retries,
            _force_primary=True,
            _fallback_from_secondary=True,
        )
    _record_llm_metric(failure_metric)
    if endpoint["remote"] and infrastructure_error and policy == "FAIL_CLOSED":
        raise RemoteOllamaInfrastructureError(error_class, last_error)
    raise last_error or RuntimeError("LLM API 呼び出しに失敗しました")


save_manager = SaveLoadManager()
chat_session = None

# 幸運消費の救済上限（1回あたりの最大消費提案ポイント）
LUCK_BURN_MAX = 10

# ==========================================
# 1. セーブ＆ロード処理 (SaveLoadManager 委譲)
# ==========================================
def sync_progress_managers(state_mgr, scenario_mgr, save_data=None):
    """
    game_state を進行フラグ・ターン数の Single Source of Truth として接続する。
    旧セーブ（scenario_manager.flags / turn_counter）からの移行もここで行う。
    セーブ上の両 flags が存在する場合は内容をマージして一致させる。
    """
    if not state_mgr or not scenario_mgr:
        return

    gs = (save_data or {}).get("game_state") or {}
    sm = (save_data or {}).get("scenario_manager") or {}

    gs_flags = dict(gs.get("flags") or {})
    sm_flags = dict(sm.get("flags") or {})
    if gs_flags or sm_flags:
        merged = dict(sm_flags)
        merged.update(gs_flags)  # game_state 優先
        merged.setdefault("investigated_targets", [])
        state_mgr.flags = merged

    gs_turn = int(gs.get("turn_count") or 0)
    sm_turn = int(sm.get("turn_counter") or 0)
    state_mgr.turn_count = max(gs_turn, sm_turn, int(state_mgr.turn_count or 0))

    scenario_mgr.bind_game_state(state_mgr)
    if hasattr(scenario_mgr, "ensure_flags_synced"):
        scenario_mgr.ensure_flags_synced()
    _reconcile_loaded_stagnation_counters(state_mgr, scenario_mgr)


def _reconcile_loaded_stagnation_counters(state_mgr, scenario_mgr):
    """
    旧バグ（割り込み時に counter を閾値へ上書き）で膨らんだ膠着カウンタを、
    tracker の実ストリークへ戻す。
    """
    if not scenario_mgr:
        return
    tracker = (getattr(state_mgr, "stagnation_tracker", None) or {}) if state_mgr else {}
    streak = int(tracker.get("streak") or 0)
    counter = int(getattr(scenario_mgr, "stagnation_counter", 0) or 0)
    threshold = STAGNATION_PAUSE_THRESHOLD
    if hasattr(scenario_mgr, "get_max_stagnation_turns"):
        threshold = scenario_mgr.get_max_stagnation_turns()
    if counter >= threshold and streak < threshold:
        scenario_mgr.stagnation_counter = streak
        if state_mgr and hasattr(state_mgr, "stagnation_tracker"):
            tracker = dict(state_mgr.stagnation_tracker or {})
            if int(tracker.get("intervened_at_streak") or 0) > streak:
                tracker["intervened_at_streak"] = streak
                state_mgr.stagnation_tracker = tracker


def build_save_data(game_state, character_manager, scenario_manager, app_state, scenario_file=None):
    """すべての状態を一つの辞書データとしてまとめる。"""
    for char in character_manager.characters.values():
        character_manager.normalize_character_attributes(char)
    # セーブ直前に flags を必ず同期（game_state と scenario_manager ミラー一致）
    if scenario_manager and hasattr(scenario_manager, "bind_game_state"):
        scenario_manager.bind_game_state(game_state)
    if scenario_manager and hasattr(scenario_manager, "ensure_flags_synced"):
        scenario_manager.ensure_flags_synced()
    app_state = dict(app_state or {})
    if scenario_file:
        app_state["scenario_file"] = scenario_file
    elif "scenario_file" not in app_state:
        app_state["scenario_file"] = DEFAULT_SCENARIO_FILE
    return {
        "game_state": game_state.export_to_dict(),
        "character_manager": character_manager.export_to_dict(),
        "scenario_manager": scenario_manager.export_to_dict(),
        "app_state": app_state,
        "scenario_file": app_state.get("scenario_file", DEFAULT_SCENARIO_FILE),
    }


def save_game_to_slot(slot_id, game_state, character_manager, scenario_manager, app_state, scenario_file=None):
    """指定スロットへセーブする。"""
    save_data = build_save_data(
        game_state, character_manager, scenario_manager, app_state, scenario_file=scenario_file,
    )
    success = save_manager.save_game(slot_id, save_data)
    return success, save_data


def generate_save_data(game_state, character_manager, scenario_manager, app_state, slot_id=None, scenario_file=None):
    """後方互換用。slot_id 未指定時は autosave スロットへ保存。"""
    if slot_id is None:
        slot_id = SaveLoadManager.AUTOSAVE_SLOT_ID
    success, save_data = save_game_to_slot(
        slot_id, game_state, character_manager, scenario_manager, app_state,
        scenario_file=scenario_file,
    )
    if not success:
        print(f"[main] セーブ失敗: slot_id={slot_id}")
    return save_data


def recover_pending_timeline_on_load(
    app_state, scenario_mgr=None, char_mgr=None, *, normalize_runtime_flags=True
):
    """
    未処理 PL 行動（system_processed: false）や last_pl_action 不整合を修復する。
    is_running かつ未処理がある場合は巡航再開可能な状態に整える。
    """
    # 画面再描画からの呼び出しでは from_save_load=False（ロード修復の再適用を避ける）
    app_state = normalize_loaded_runtime_state(
        dict(app_state or {}),
        enforce_half_turn_pause=normalize_runtime_flags,
        from_save_load=False,
    )
    if scenario_mgr:
        normalize_game_action_targets(app_state, scenario_mgr, char_mgr=char_mgr)

    pending = find_any_pending_pl_action(app_state, char_mgr)
    if pending:
        meta = pending.get("meta") or {}
        last_action = dict(app_state.get("last_pl_action") or {})
        app_state["last_pl_action"] = normalize_pc_action({
            "action": meta.get("action_id") or meta.get("action") or "wait",
            "target": meta.get("target", ""),
            "skill": meta.get("skill", ""),
            "message": last_action.get("message", ""),
            "dialogue": last_action.get("dialogue", ""),
        }, scenario_mgr, app_state.get("current_loc"), char_mgr=char_mgr)
        if app_state.get("is_running"):
            app_state["autonomous_paused"] = False
            app_state["autonomous_pause_reason"] = None
            app_state["stop_requested"] = False
    return app_state


def restore_from_save_data(save_data, game_state, character_manager, scenario_manager):
    """辞書データから状態を各Managerに復元し、UI用のapp_stateを返す。"""
    if "game_state" in save_data:
        game_state.load_from_dict(save_data["game_state"])
    if "character_manager" in save_data:
        character_manager.load_from_dict(save_data["character_manager"])
    if "scenario_manager" in save_data:
        scenario_manager.load_from_dict(save_data["scenario_manager"])

    sync_progress_managers(game_state, scenario_manager, save_data=save_data)
    app_state = save_data.get("app_state", {})
    was_running_when_saved = bool(app_state.get("is_running"))
    app_state = recover_pending_timeline_on_load(
        app_state,
        scenario_mgr=scenario_manager,
        char_mgr=character_manager,
    )
    recovered_unqueued_action = recover_unqueued_last_action(
        app_state, app_state.get("char_name", ""), scenario_manager, character_manager,
    )
    # 復旧途中の正規化で実行中情報が落ちても、ロード時の安全停止を適用する。
    if was_running_when_saved and not app_state.get("autonomous_paused"):
        app_state["is_running"] = True
    # game_state の膠着ストリークを app_state へ同期し、強制 IC 判定に使う
    tracker = getattr(game_state, "stagnation_tracker", None) or {}
    app_state["stagnation_streak"] = int(tracker.get("streak") or 0)
    cleanse_session_npc_state(
        character_manager,
        scenario_manager,
        all_events_log=app_state.get("all_events_log"),
        new_session=False,
    )
    repair_police_archives_knowledge_on_load(
        character_manager, scenario_manager, app_state=app_state,
    )
    if is_force_ic_action_phase(app_state, state_mgr=game_state):
        ensure_force_ic_action_phase(app_state, state_mgr=game_state)
    # 旧セーブの矛盾した is_running / empty_tick / LLM失敗を再開可能な状態へ修復（ロード時のみ）
    app_state = normalize_loaded_runtime_state(
        app_state, enforce_half_turn_pause=True, from_save_load=True,
    )
    if recovered_unqueued_action:
        # 新規にキューへ載せた行動は未実行。明示再開後に一度だけ SYSTEM へ送れる。
        app_state["autonomous_paused"] = True
        app_state["is_running"] = False
        app_state["autonomous_pause_reason"] = "safe_resume_ready"
        sync_autonomous_pause_class(app_state)
    return app_state


def repair_police_archives_knowledge_on_load(char_mgr, scenario_mgr, app_state=None):
    """
    higher_courts_records_accessed 済みだが、既取得PCの資料本文が案内文のまま等の場合に限って補修する。

    - 対象は既に `object:police_archives` を持つ PC のみ（未取得PCへ新規付与しない）
    - 他PCへの共有は既存の知識分離ルールに任せる
    - PC能力値・他知識・進行フラグはリセットしない。冪等。
    """
    if not char_mgr or not scenario_mgr:
        return []
    flags = getattr(scenario_mgr, "flags", None) or {}
    if not flags.get("higher_courts_records_accessed"):
        return []
    fact, _obj = scenario_mgr._object_confirmed_fact(
        "police_archives", loc_id="higher_courts_police_station",
    )
    if not fact or "プレイヤー資料8" not in fact:
        return []
    kid = knowledge_id_for_object("police_archives")
    repaired = []
    active = list(getattr(char_mgr, "active_pcs", None) or []) or char_mgr.list_pc_ids()
    for pc_id in active:
        char = char_mgr.characters.get(pc_id) or {}
        if (char.get("profile") or {}).get("is_npc"):
            continue
        known = set(char_mgr.get_known_knowledge_ids(pc_id))
        # 未取得PCには新規付与しない（本文補修のみ）
        if kid not in known:
            continue
        notes = (char_mgr.ensure_knowledge_context(pc_id) or {}).get("knowledge_notes") or {}
        existing = str(notes.get(kid) or "")
        already_good = (
            "プレイヤー資料8" in existing
            and "情報が眠っている" not in existing
            and "閲覧には厳格な手続き" not in existing
        )
        if already_good:
            continue
        # grant_knowledge は既知IDでも summary（notes）を更新する
        char_mgr.grant_knowledge(
            pc_id, kid, target="police_archives", summary=fact, mark_investigated=True,
        )
        repaired.append(pc_id)
    return repaired


def extract_npc_ids_from_event_log(all_events_log, char_mgr=None):
    """セッションログに登場した NPC ID を収集する。"""
    found = set()
    known_npcs = set()
    if char_mgr:
        known_npcs = set(char_mgr.list_npc_ids())
    for entry in all_events_log or []:
        meta = entry.get("meta") or {}
        target = meta.get("target")
        if target and (not known_npcs or target in known_npcs):
            found.add(str(target))
        text = str(entry.get("text") or "")
        for nid in known_npcs:
            if nid and nid in text:
                found.add(nid)
            name = ""
            if char_mgr:
                npc = char_mgr.characters.get(nid) or {}
                name = (npc.get("profile") or {}).get("name") or ""
            if name and name in text:
                found.add(nid)
    return found


def cleanse_session_npc_state(char_mgr, scenario_mgr, all_events_log=None, *, new_session=False):
    """
    シナリオ未定義・今セッション未登場 NPC の session_social をクレンジングする。
    新規ゲームでは全 NPC の session_social をリセットする。
    """
    if not char_mgr:
        return []
    scenario_ids = set()
    if scenario_mgr and hasattr(scenario_mgr, "collect_scenario_npc_ids"):
        scenario_ids = scenario_mgr.collect_scenario_npc_ids()
    log_ids = None
    if not new_session:
        log_ids = extract_npc_ids_from_event_log(all_events_log, char_mgr=char_mgr)
    cleared = char_mgr.cleanse_extraneous_npc_session_state(
        scenario_npc_ids=scenario_ids,
        log_referenced_npc_ids=log_ids,
        new_session=new_session,
    )
    if cleared:
        print(f"[システム] NPC session_social をクレンジング: {', '.join(cleared)}")
    return cleared


def load_game(game_state, character_manager, scenario_manager, slot_id):
    """指定スロットを読み込み、restore_from_save_data で状態を復元する。"""
    save_data = save_manager.load_game(slot_id)
    if save_data is None:
        return False, {}, scenario_manager

    scenario_file = (
        save_data.get("scenario_file")
        or save_data.get("app_state", {}).get("scenario_file")
        or DEFAULT_SCENARIO_FILE
    )

    try:
        scenario_manager = create_scenario_manager(
            scenario_file,
            save_data.get("scenario_manager"),
        )
        app_state = restore_from_save_data(
            save_data, game_state, character_manager, scenario_manager,
        )
        sync_progress_managers(game_state, scenario_manager, save_data=save_data)
        for char in character_manager.characters.values():
            character_manager.normalize_character_attributes(char)
        app_state["scenario_file"] = scenario_file
        sync_room_entry_san_on_load(app_state, scenario_manager)
        return True, app_state, scenario_manager
    except Exception as e:
        print(f"ロード中にエラーが発生しました: {e}")
        return False, {}, scenario_manager


def get_available_slots():
    """利用可能なセーブスロット一覧を返す。"""
    slots = save_manager.get_available_slots()
    for slot in slots:
        scenario_file = slot.get("scenario_file") or DEFAULT_SCENARIO_FILE
        slot["scenario_file"] = scenario_file
        slot["scenario_label"] = get_scenario_label(scenario_file)
    return slots

# ==========================================
# 2. 初期化とログフィルタ
# ==========================================
def get_scenario_filepath(scenario_file=None):
    """シナリオJSONファイルの絶対パスを返す。"""
    filename = scenario_file or DEFAULT_SCENARIO_FILE
    base_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_dir, filename)


def _is_corbitt_scenario(scenario_file=None):
    return (scenario_file or DEFAULT_SCENARIO_FILE) == CORBITT_SCENARIO_FILE


def _corbitt_scenario_selectable():
    """悪霊の家: ステージングキャッシュまたはビルド済みJSONがあれば選択可能。"""
    from build_corbitt_scenario import OUT_FILE, staged_cache_available

    return staged_cache_available() or OUT_FILE.is_file()


def is_scenario_selectable(scenario_file=None):
    """UIに表示してよいシナリオか（ファイルまたはビルド元が存在するか）。"""
    filename = scenario_file or DEFAULT_SCENARIO_FILE
    if _is_corbitt_scenario(filename):
        return _corbitt_scenario_selectable()
    return os.path.isfile(get_scenario_filepath(filename))


def _prepare_corbitt_scenario_file(*, force: bool = False):
    """悪霊の家: 複数ファイル構成のソースから必要なら自動ビルド＋バリデーションする。"""
    from build_corbitt_scenario import ensure_built, needs_rebuild, staged_cache_available

    if staged_cache_available() and (force or needs_rebuild()):
        print("[シナリオ] 悪霊の家: 分割ソースの更新を検知。バリデーション付き再ビルドを実行します…")
    return ensure_built(force=force)


def load_scenario_data(scenario_file=None):
    """シナリオJSONを読み込む。"""
    filename = scenario_file or DEFAULT_SCENARIO_FILE
    if _is_corbitt_scenario(filename):
        try:
            _prepare_corbitt_scenario_file()
        except Exception as exc:
            # ビルド失敗時は既存の scenario_corbitt.json があればフォールバック
            filepath = get_scenario_filepath(filename)
            if os.path.isfile(filepath):
                print(
                    f"[シナリオ] 自動ビルドに失敗したため既存の {filename} を使用します: {exc}"
                )
            else:
                raise
    filepath = get_scenario_filepath(filename)
    if not os.path.isfile(filepath):
        raise FileNotFoundError(f"シナリオファイルが見つかりません: {filepath}")
    with open(filepath, "r", encoding="utf-8") as f:
        return json.load(f)


def create_scenario_manager(scenario_file=None, saved_state=None, state_mgr=None):
    """シナリオファイルから ScenarioManager を生成し、必要なら保存状態を復元する。"""
    scenario_mgr = ScenarioManager(load_scenario_data(scenario_file))
    if saved_state:
        scenario_mgr.load_from_dict(saved_state)
    if state_mgr is not None:
        sync_progress_managers(state_mgr, scenario_mgr, save_data={"scenario_manager": saved_state or {}})
    return scenario_mgr


def get_scenario_label(scenario_file=None):
    """UI表示用のシナリオ名を返す。"""
    filename = scenario_file or DEFAULT_SCENARIO_FILE
    return SCENARIO_CATALOG.get(filename, filename)


def list_scenario_options():
    """シナリオ選択UI用の (filename, label) 一覧。"""
    return [
        (fname, label)
        for fname, label in SCENARIO_CATALOG.items()
        if is_scenario_selectable(fname)
    ]


def init_game_system(scenario_file=None, active_pcs=None):
    """ゲーム開始時に各種マネージャーを初期化する"""
    char_mgr = CharacterManager("pcs.json", "npcs.json")
    # テストプレイで消耗した SAN / 幸運が次シナリオに持ち越されないよう、固定初期値へ強制復元
    char_mgr.reset_all_pcs_to_baseline(persist=True)
    dice_engine = DiceEngine()
    state_mgr = GameStateManager(char_mgr)

    scenario_mgr = create_scenario_manager(
        scenario_file or DEFAULT_SCENARIO_FILE,
        state_mgr=state_mgr,
    )
    # 新規セッション: 過去プレイの session_social 残留を除去
    cleanse_session_npc_state(char_mgr, scenario_mgr, all_events_log=None, new_session=True)
    ids = active_pcs or default_active_pc_ids(char_mgr)
    char_mgr.set_active_pcs(ids)

    return char_mgr, dice_engine, state_mgr, scenario_mgr


def apply_scenario_startup_effects(scenario_mgr, state_mgr, char_mgr, pl_id, char_name=""):
    """シナリオ定義の startup_effects を新規ゲーム開始時に適用する。"""
    if not scenario_mgr or not state_mgr or not char_mgr:
        return None

    effects = scenario_mgr.get_startup_effects()
    san_loss = int(effects.get("san_loss", 0) or 0)
    if san_loss <= 0:
        return None

    char = char_mgr.characters.get(pl_id, {})
    char_name = char_name or char.get("profile", {}).get("name", "探索者")
    old_san = char_mgr.get_stat_current(pl_id, "SAN")

    result = state_mgr.apply_san_damage(
        pl_id,
        san_loss,
        force_temporary_insanity=bool(effects.get("force_insanity", False)),
        insanity_label=effects.get("insanity_label"),
        insanity_duration=effects.get("insanity_duration"),
        dice_engine=DiceEngine(),
        char_name=char_name,
    )
    new_san = result.get("new_san", max(0, old_san - san_loss))

    lines = []
    custom_log = str(effects.get("system_log", "") or "").strip()
    if custom_log:
        lines.append(custom_log)
    else:
        lines.append(
            f"【シナリオ開始・精神的衝撃】{char_name} の正気度が {san_loss} 減少した"
            f"（{old_san} → {new_san}）。"
        )
    lines.append(f"【確定】{char_name} のSAN値が {old_san} から {new_san} になりました。")
    for event_msg in result.get("events") or []:
        if event_msg not in lines:
            lines.append(event_msg)

    return {
        "log": "\n".join(lines),
        "madness_instruction": result.get("madness_instruction", ""),
        "old_san": old_san,
        "new_san": new_san,
        "san_loss": san_loss,
    }


def refresh_stale_managers(char_mgr, dice_engine, state_mgr, scenario_mgr):
    """コード更新後にセッションへ残った古いマネージャーインスタンスを差し替える。"""
    if not hasattr(char_mgr, "can_offer_luck_burn"):
        fresh_char = CharacterManager(char_mgr.pc_filepath, char_mgr.npc_filepath)
        fresh_char.characters = char_mgr.characters
        char_mgr = fresh_char
        if state_mgr:
            state_mgr.char_mgr = char_mgr

    if not hasattr(char_mgr, "get_stat_current"):
        fresh_char = CharacterManager(char_mgr.pc_filepath, char_mgr.npc_filepath)
        fresh_char.characters = char_mgr.characters
        for char in fresh_char.characters.values():
            fresh_char.normalize_character_attributes(char)
        char_mgr = fresh_char
        if state_mgr:
            state_mgr.char_mgr = char_mgr

    if not hasattr(char_mgr, "get_luck"):
        fresh_char = CharacterManager(char_mgr.pc_filepath, char_mgr.npc_filepath)
        fresh_char.characters = char_mgr.characters
        char_mgr = fresh_char
        if state_mgr:
            state_mgr.char_mgr = char_mgr

    if not hasattr(dice_engine, "execute_push_roll"):
        dice_engine = DiceEngine()

    if state_mgr and scenario_mgr:
        sync_progress_managers(state_mgr, scenario_mgr)

    return char_mgr, dice_engine, state_mgr, scenario_mgr

def get_filtered_logs(player_id, location, all_events_log):
    ic_logs = []
    ooc_logs = []
    for event in all_events_log:
        if event.get("secret_to") and player_id not in event["secret_to"]:
            continue
        if event["channel"] == "OOC":
            ooc_logs.append(event["text"])
        elif event["channel"] == "IC":
            if event["location"] == location or event["location"] == "all":
                ic_logs.append(event["text"])
    return ic_logs, ooc_logs


def _classify_ic_log_speaker_role(text, event, player_id, char_mgr=None):
    """ICログの話者区分: self / other_pc / kp / system / other。"""
    raw = str(text or "")
    meta = event.get("meta") or {}
    if raw.startswith("システム:"):
        return "system"
    if raw.startswith("KP:") or raw.startswith("KP("):
        return "kp"
    pc_meta = str(meta.get("pc_id") or meta.get("actor_id") or "")
    if pc_meta and player_id and pc_meta == str(player_id):
        return "self"
    if pc_meta and player_id and pc_meta != str(player_id):
        return "other_pc"
    if char_mgr and player_id:
        self_prefix = format_pc_log_prefix(char_mgr, player_id, role="PC")
        if raw.startswith(self_prefix + ":") or raw.startswith(str(char_mgr.get_pc_name(player_id))):
            # 自名で始まるが他ロールの可能性は低い
            if raw.startswith(self_prefix):
                return "self"
        for pid in getattr(char_mgr, "active_pc_list", None) or []:
            if pid == player_id:
                continue
            pref = format_pc_log_prefix(char_mgr, pid, role="PC")
            if raw.startswith(pref + ":") or raw.startswith(pref):
                return "other_pc"
    return "other"


def format_prompt_history_logs(
    player_id, location, all_events_log, char_mgr=None, *, ic_limit=8, ooc_limit=3,
):
    """
    PL/KP向け履歴。話者区分ラベル付き。
    他PC発言は模倣禁止ラベルを付け、知識本文は secret_to で既に隔離済み。
    """
    ic_logs = []
    ooc_logs = []
    role_label = {
        "self": "[自分の発言]",
        "other_pc": "[他探索者の発言・設定参考禁止／模倣して自己紹介するな]",
        "kp": "[KP描写]",
        "system": "[システム確定結果]",
        "other": "[IC]",
    }
    for event in all_events_log or []:
        if event.get("secret_to") and player_id not in event["secret_to"]:
            continue
        text = str(event.get("text") or "")
        if not text:
            continue
        if event.get("channel") == "OOC":
            ooc_logs.append(f"[OOC] {text}")
        elif event.get("channel") == "IC":
            if event.get("location") in (location, "all"):
                role = _classify_ic_log_speaker_role(text, event, player_id, char_mgr)
                ic_logs.append(f"{role_label.get(role, '[IC]')} {text}")
    return ic_logs[-ic_limit:], ooc_logs[-ooc_limit:]


def resolve_pending_decision_owner(state, pending=None, *, fallback_pl_id=""):
    """幸運・プッシュ等の判断主体。画面上の現在PCより元行動所有者を優先。"""
    pending = pending or {}
    state = state or {}
    pending_decision = state.get("pending_decision") or {}
    for candidate in (
        pending.get("decision_owner_id"),
        pending.get("actor_id"),
        pending_decision.get("decision_owner_id"),
        state.get("decision_owner_id"),
        state.get("actor_id"),
        fallback_pl_id,
        state.get("pl_id"),
    ):
        cid = str(candidate or "").strip()
        if cid:
            return cid
    return str(fallback_pl_id or "")


def resolve_active_pc_identity(char_mgr, pl_id, char_name=None, active_pcs=None):
    """actor_id 基準で名前・職業を一意に解決する。"""
    name = str(char_name or "").strip()
    occupation = ""
    if char_mgr and pl_id:
        try:
            name = char_mgr.get_pc_name(pl_id, default=name or str(pl_id))
        except TypeError:
            name = char_mgr.get_pc_name(pl_id) or name or str(pl_id)
        pc = char_mgr.get_pc(pl_id) or {}
        occupation = str((pc.get("profile") or {}).get("occupation") or "").strip()
    profiles = collect_pc_identity_profiles(char_mgr, active_pcs)
    others = [p for p in profiles if p.get("pc_id") != pl_id]
    return {
        "pl_id": pl_id,
        "name": name,
        "occupation": occupation or "探索者",
        "others": others,
        "profiles": profiles,
    }

# ==========================================
# タスク5: Knowledge Context（PC別知識フィルタ）
# ==========================================
def _append_result_log_with_knowledge(
    state, result, *, current_loc, char_mgr, pl_id,
    action_id="", target="", roll_type="", transaction_id="",
):
    """知識付与＋（個別知識なら secret_to 付き）システムログ追記。"""
    actor = pl_id or state.get("actor_id") or state.get("pl_id")
    applied = apply_knowledge_grants_from_result(char_mgr, actor, result, state=state)
    private_grants = [
        g for g in (result.get("knowledge_grants") or [])
        if isinstance(g, dict) and str(g.get("scope") or "private").lower() != "public"
    ]
    # 明示 secret_to を優先。無ければ公開会話（None）。私的調査のみ actor 限定。
    secret_to = result.get("secret_to") or (result.get("social") or {}).get("secret_to")
    social = result.get("social") or {}
    if secret_to is None and not social.get("revealed_secrets"):
        if (private_grants or (result.get("confirmed_fact") and applied)) and actor:
            only_public = bool(result.get("knowledge_grants")) and not private_grants
            if not only_public:
                secret_to = [actor]
    log_text = str(result.get("log", "") or "")
    lifecycle_marker = next(
        (marker for marker in ("【戦闘開始】", "【戦闘終了】") if marker in log_text),
        None,
    )
    adjudication_text = log_text
    lifecycle_text = ""
    if lifecycle_marker:
        adjudication_text, lifecycle_tail = log_text.split(lifecycle_marker, 1)
        lifecycle_text = f"{lifecycle_marker}{lifecycle_tail}".strip()
    append_system_log_entry(
        state["all_events_log"], current_loc, adjudication_text,
        action_id=action_id or result.get("action_id", ""),
        target=target or result.get("target", ""),
        roll_type=roll_type or result.get("roll_type", ""),
        transaction_id=transaction_id,
        actor_id=actor or "",
        decision_owner_id=state.get("decision_owner_id") or "",
        secret_to=secret_to,
        knowledge_ids=applied or None,
        adjudication=result,
        interaction_id=result.get("interaction_id", ""),
    )
    if lifecycle_text:
        lifecycle_action = "combat_start" if lifecycle_marker == "【戦闘開始】" else "combat_end"
        append_system_log_entry(
            state["all_events_log"], current_loc, lifecycle_text,
            action_id=lifecycle_action,
            target=target or result.get("target", ""),
            roll_type="combat_lifecycle",
            transaction_id=transaction_id,
            actor_id=actor or "",
            cause_adjudication_id=result.get("adjudication_id", ""),
        )
    return applied


def ensure_public_knowledge_field(state):
    """game_state に公開知識リストを保証する。"""
    if not isinstance(state, dict):
        return state
    ids = state.get("public_knowledge_ids")
    if not isinstance(ids, list):
        state["public_knowledge_ids"] = []
    return state


def get_public_knowledge_ids(state=None):
    if not isinstance(state, dict):
        return []
    return [str(x).strip() for x in (state.get("public_knowledge_ids") or []) if str(x).strip()]


def grant_public_knowledge(state, knowledge_id, *, summary="", knowledge_notes=None):
    """全員共有の公開知識を付与する。"""
    ensure_public_knowledge_field(state)
    kid = str(knowledge_id or "").strip()
    if not kid:
        return False
    ids = state.setdefault("public_knowledge_ids", [])
    newly = kid not in ids
    if newly:
        ids.append(kid)
    if summary and isinstance(knowledge_notes, dict):
        knowledge_notes[kid] = str(summary).strip()[:400]
    return newly


def apply_knowledge_grants_from_result(char_mgr, actor_id, result, state=None):
    """
    システム結果の knowledge_grants / confirmed_fact / revealed_secrets を
    主体PC（actor_id）または公開知識へ反映する。
    """
    if not char_mgr or not actor_id:
        return []
    ensure_public_knowledge_field(state) if isinstance(state, dict) else None
    applied = []
    result = result or {}

    grants = list(result.get("knowledge_grants") or [])
    # confirmed_fact のみで grant が無い場合のフォールバック
    if not grants and result.get("confirmed_fact") and result.get("target"):
        grants.append({
            "knowledge_id": knowledge_id_for_object(result.get("target")),
            "scope": "private",
            "target": result.get("target"),
            "summary": result.get("confirmed_fact"),
            "mark_investigated": True,
        })

    # The engine has one party location. An explicit audience restricts a private talk.
    social = result.get("social") or {}
    explicit_audience = result.get("secret_to") or social.get("secret_to")
    audience = explicit_audience or (state or {}).get("active_pcs") or [actor_id]
    audience = [pid for pid in audience if char_mgr.get_pc(pid)] or [actor_id]
    # NPC秘密開示（明示 secret_to が無い公開会話は参加PC全員へ）
    npc_id = social.get("npc_id") or result.get("target")
    for sec in social.get("revealed_secrets") or []:
        if isinstance(sec, dict):
            sid = sec.get("id")
            content = sec.get("content", "")
        else:
            sid = sec
            content = ""
        kid = knowledge_id_for_secret(npc_id, sid)
        if kid:
            grants.append({
                "knowledge_id": kid,
                "scope": "public" if not explicit_audience else "private",
                "target": "",
                "summary": content,
                "mark_investigated": False,
                "recipient_ids": list(audience),
            })

    for grant in grants:
        if not isinstance(grant, dict):
            continue
        kid = str(grant.get("knowledge_id") or "").strip()
        if not kid:
            continue
        scope = str(grant.get("scope") or "private").lower()
        summary = str(grant.get("summary") or "").strip()
        target = grant.get("target") or ""
        mark = bool(grant.get("mark_investigated", True))
        recipients = list(grant.get("recipient_ids") or [])
        if scope == "public":
            if isinstance(state, dict) and grant_public_knowledge(state, kid, summary=summary):
                applied.append(kid)
            # 公開知識は参加中PC全員の個別知識にも載せて後続プロンプトで参照可能にする
            public_recipients = recipients or audience
            for recipient in public_recipients:
                if char_mgr.grant_knowledge(
                    recipient, kid, target=target, summary=summary, mark_investigated=False,
                ):
                    if kid not in applied:
                        applied.append(kid)
            if mark and target:
                char_mgr.mark_pc_investigated_target(actor_id, target)
            if summary:
                char = char_mgr.ensure_knowledge_context(actor_id)
                if char is not None:
                    char.setdefault("knowledge_notes", {})[kid] = summary[:400]
        else:
            for recipient in recipients or [actor_id]:
                if char_mgr.grant_knowledge(
                    recipient, kid, target=target, summary=summary, mark_investigated=mark,
                ):
                    if kid not in applied:
                        applied.append(kid)
                elif mark and target:
                    char_mgr.mark_pc_investigated_target(recipient, target)
    if applied and isinstance(result, dict):
        result["knowledge_actually_new"] = True
        result["knowledge_grants_applied"] = list(applied)
    return applied


def resolve_pc_investigated_ids_for_prompt(
    char_mgr, pl_id, scenario_mgr=None, location_info=None, state=None,
):
    """
    PLプロンプト用の「当該PCが調査済み」ID集合。
    共有 flags のみに依存せず、PC個別 investigated_targets + known_knowledge を使う。
    """
    investigated = set()
    if char_mgr and pl_id:
        investigated |= char_mgr.get_pc_investigated_targets(pl_id)
        for kid in char_mgr.get_known_knowledge_ids(pl_id):
            if kid.startswith("object:"):
                investigated.add(kid.split(":", 1)[1])
    for kid in get_public_knowledge_ids(state):
        if kid.startswith("object:"):
            investigated.add(kid.split(":", 1)[1])
    return investigated


def object_clue_visible_to_pc(obj, obj_id, char_mgr, pl_id, state=None):
    """手がかり本文を当該PCのプロンプトに出してよいか。"""
    if not object_has_private_clue_content(obj):
        return True
    if not char_mgr or not pl_id:
        return False
    public = get_public_knowledge_ids(state)
    kid = knowledge_id_for_object(obj_id)
    if char_mgr.pc_knows(pl_id, kid, public_ids=public):
        return True
    if char_mgr.pc_has_investigated(pl_id, obj_id):
        return True
    return False


def _build_pl_known_knowledge_block(char_mgr, pl_id, state=None):
    """既知知識の要約を PL プロンプトへ注入する。"""
    if not char_mgr or not pl_id:
        return ""
    public = get_public_knowledge_ids(state)
    notes = char_mgr.get_knowledge_notes_for_prompt(pl_id, public_ids=public, limit=8)
    if not notes:
        known = char_mgr.get_known_knowledge_ids(pl_id)
        if not known and not public:
            return ""
        lines = [f"- `{kid}`" for kid in (known + public)[:8]]
        return "【このPCが獲得した知識ID】\n" + "\n".join(lines) + "\n"
    lines = [f"- {note}" for _, note in notes]
    return "【このPCが獲得した知識（他PCの未共有情報は含まない）】\n" + "\n".join(lines) + "\n"

def start_new_ai_session():
    """新規ゲーム開始時に会話履歴をリセットする。"""
    global chat_session, _chat_history
    _chat_history = []
    chat_session = None


def rebuild_ai_session(all_events_log):
    """ロード時にログから OpenAI 形式の会話履歴を再構築する。"""
    global chat_session, _chat_history

    formatted_history = []
    for event in all_events_log:
        if event["channel"] == "IC":
            text = event["text"]
            if "KP:" in text:
                role = "assistant"
            elif "PL:" in text or "システム:" in text or "(PC):" in text:
                role = "user"
            else:
                continue
            formatted_history.append({"role": role, "content": text})

    _chat_history = formatted_history
    chat_session = list(formatted_history)

# ==========================================
# 3. プロンプト生成
# ==========================================
def _format_objects_for_pl(
    location_info,
    *,
    priority_ids=None,
    exhausted=False,
    investigated_ids=None,
    reveal_descriptions_for=None,
):
    """オブジェクトの usable_actions / purpose / description を PL 向けに整形する。

    reveal_descriptions_for:
      手がかり本文を見せてよい object_id の集合。None なら従来どおり全 description 表示。
    """
    objects = location_info.get("objects", {}) if location_info else {}
    if not objects:
        return ""

    priority_ids = [str(x) for x in (priority_ids or []) if x]
    priority_set = set(priority_ids)
    investigated_ids = {str(x) for x in (investigated_ids or set())}
    reveal_set = (
        None if reveal_descriptions_for is None
        else {str(x) for x in reveal_descriptions_for}
    )
    items = list(objects.items())
    if priority_ids:
        rank = {oid: i for i, oid in enumerate(priority_ids)}
        items.sort(key=lambda kv: (rank.get(kv[0], 10_000), kv[0]))
    elif exhausted:
        # 調査済みを後回しにし、move 誘導を優先
        items.sort(key=lambda kv: (0 if kv[0] not in investigated_ids else 1, kv[0]))

    # 別名表示（PL が living_room_junk 等で指定できるようにする）
    alias_by_id = {}
    for item in CORBITT_GROUND_FLOOR_FOCUS:
        oid = item["object_id"]
        aliases = [a for a in (item.get("aliases") or ()) if a and a != oid]
        if aliases:
            alias_by_id[oid] = aliases

    lines = []
    for obj_id, obj in items:
        actions = list(obj.get("usable_actions", ["search"]) or ["search"])
        purpose = obj.get("purpose", "")
        desc = str(obj.get("description", "") or "").strip()
        # タスク5: 未獲得の手がかり本文はプロンプトへ出さない
        if reveal_set is not None and object_has_private_clue_content(obj):
            if obj_id not in reveal_set:
                desc = ""
        prefix = "【最優先ターゲット】" if obj_id in priority_set else ""
        if exhausted and obj_id in investigated_ids:
            actions = [a for a in actions if a not in ("search", "inspect", "read")]
            if not actions:
                lines.append(
                    f"- {obj_id} ({obj.get('name', obj_id)}): "
                    "【調査済み・再search不可】移動（move）を優先"
                )
                continue
            prefix = "【調査済み・低優先】"
        elif obj_id in investigated_ids:
            prefix = prefix or "【調査済み】"
        line = f"- {prefix}{obj_id} ({obj.get('name', obj_id)}): アクション [{', '.join(actions)}]"
        aliases = alias_by_id.get(obj_id) or []
        if aliases:
            line += " / 別名 [" + ", ".join(f"`{a}`" for a in aliases) + "]"
        if obj.get("no_roll") or obj.get("empty_clue") or str(obj.get("clue_value") or "").lower() in (
            "none", "empty", "flavor",
        ):
            line += " / 【手がかりなし・判定不要】"
        if purpose:
            line += f" / {purpose}"
        if desc:
            short = desc if len(desc) <= 120 else desc[:117] + "…"
            line += f" / 描写: {short}"
        lines.append(line)

    header = (
        "【現在地のオブジェクトと利用可能アクション】\n"
        "※ ここに載っていない物体は世界に存在しません。創作・執着禁止。\n"
        "※ 他の探索者だけが調べた手がかり本文は表示されません（未調査なら自分で調べよ）。\n"
    )
    if exhausted:
        header += "※ この場所の調査は完了済み。search より解禁済みロケーションへの move を最優先。\n"
    if priority_set & {"living_room_clutter", "basement_door"}:
        header += (
            "※ 屋敷1階の最優先: `living_room_clutter`（別名 `living_room_junk`）と"
            " `basement_door` を search/inspect。雑談より室内調査。\n"
        )
    return header + "\n".join(lines) + "\n"


def _build_pl_unlocked_object_hint(scenario_mgr, current_loc):
    """進行状況に応じた PL 向けヒント（グローブ／屋敷1階／調査枯渇）。"""
    if not scenario_mgr:
        return ""
    if should_apply_location_exhausted_move(scenario_mgr, current_loc):
        return build_location_exhausted_move_hint(scenario_mgr, current_loc)
    flags = scenario_mgr.flags or {}

    # 屋敷1階: 調べる対象を強制提示し、雑談ループを防ぐ
    if current_loc == "corbitt_ground_floor":
        rec = _build_corbitt_ground_floor_recommended_action(scenario_mgr)
        if rec:
            return (
                "【屋敷1階・調査誘導】会話・不在NPCへの talk は後回し。"
                "居間のガラクタ（`living_room_clutter` / 別名 `living_room_junk`）か"
                "地下室へのドア（`basement_door`）を search / inspect せよ。\n"
                + rec
            )
        return (
            "【屋敷1階】主要な室内調査は済んでいる。"
            "未調査オブジェクトか、解放済みの移動先（上階・地下室）へ進め。"
        )

    if current_loc != "boston_globe":
        return ""
    if flags.get("artie_reference_room_access_granted"):
        ref = "reference_room_clipping_files"
        if _scenario_has_object(scenario_mgr, ref, current_loc):
            if not (
                scenario_mgr._is_target_investigated(ref)
                and not scenario_mgr._is_research_reopened(ref)
            ):
                return (
                    f"{ARTIE_ACCESS_GRANTED_SEARCH_HINT}\n"
                    "【行動制約】このターンの `pc_ic_action` は必ず "
                    "`action: search` / `target: reference_room_clipping_files` / `skill: 目星`。"
                    "talk・persuade・wait・不在NPCへの言及は禁止。"
                )
        return ""
    if flags.get("artie_introduced"):
        return ARTIE_NEGOTIATE_STAGNATION_HINT
    return ""


def _clipping_files_search_pending(scenario_mgr, current_loc=None):
    """許可取得済みかつ切り抜きファイル未調査か。"""
    if not scenario_mgr:
        return False
    flags = scenario_mgr.flags or {}
    if not flags.get("artie_reference_room_access_granted"):
        return False
    loc = current_loc or getattr(scenario_mgr, "location", "") or ""
    if loc != "boston_globe":
        return False
    ref = "reference_room_clipping_files"
    if not _scenario_has_object(scenario_mgr, ref, loc):
        return False
    if scenario_mgr._is_target_investigated(ref) and not scenario_mgr._is_research_reopened(ref):
        return False
    return True


def _reset_guard_after_access_granted(state):
    """
    artie_reference_room_access_granted が立った直後に
    consecutive_count をリセットし、同一PL制限で search が潰されないようにする。
    """
    if not state:
        return
    state["stagnation_pl_hint"] = ARTIE_ACCESS_GRANTED_SEARCH_HINT
    guard = state.get("autonomous_guard")
    if isinstance(guard, dict):
        guard = dict(guard)
        guard["consecutive_count"] = 0
        guard["chat_rounds_without_action"] = 0
        state["autonomous_guard"] = guard
    else:
        state["autonomous_guard"] = {
            "consecutive_speaker": None,
            "consecutive_count": 0,
            "chat_rounds_without_action": 0,
        }


def _is_clipping_search_action(action_id, target):
    return (
        str(action_id or "").lower() in ("search", "inspect")
        and str(target or "") == "reference_room_clipping_files"
    )


def _is_progress_command(action_id, target=""):
    """同一PL制限より優先すべき有効コマンドか。"""
    action = str(action_id or "").lower()
    if action in ("wait", "none", ""):
        return False
    if action in ("search", "inspect", "read", "move", "push", "climb", "kick", "break", "force"):
        return True
    if action in NEGOTIATION_ACTION_IDS:
        return True
    if action in TALK_ACTION_IDS and target:
        return True
    return False


def _should_defer_stagnation_interrupt_for_progress(state, scenario_mgr):
    """
    有効な search/move 等が未処理、または許可直後の切り抜き待ちのとき、
    stagnation_interrupt / 同一PL制限より行動消化を優先する。
    """
    if not state:
        return False
    # 切り抜き未調査の猶予（既存）
    if _should_defer_stagnation_interrupt_for_clipping_search(state, scenario_mgr):
        return True
    pending = find_any_pending_pl_action(state)
    if pending:
        meta = pending.get("meta") or {}
        if _is_progress_command(meta.get("action_id"), meta.get("target")):
            return True
    last = state.get("last_pl_action") or {}
    if last.get("needs_pl_retry"):
        return False
    if _is_progress_command(last.get("action"), last.get("target")):
        # 直前が有効コマンドなら、同一話者制限で次を潰さない
        return True
    return False


def _should_defer_stagnation_interrupt_for_clipping_search(state, scenario_mgr):
    """
    許可取得後・切り抜き未調査時、有効な search の消化を
    stagnation_interrupt / 同一PL制限より優先する。
    """
    if not state or not scenario_mgr:
        return False
    current_loc = state.get("current_loc") or getattr(scenario_mgr, "location", "") or ""
    if not _clipping_files_search_pending(scenario_mgr, current_loc):
        return False
    # 未処理の切り抜き search があれば必ず defer
    pending = find_any_pending_pl_action(state)
    if pending:
        meta = pending.get("meta") or {}
        if _is_clipping_search_action(meta.get("action_id"), meta.get("target")):
            return True
    last = state.get("last_pl_action") or {}
    if _is_clipping_search_action(last.get("action"), last.get("target")):
        return True
    # 許可直後は次の PL ターンで search できるよう割り込みを猶予
    return True


def _count_post_access_non_search_streak(all_events_log):
    """
    許可取得ログ以降、切り抜き search 以外の PC 行動が何連続か。
    """
    streak = 0
    for entry in reversed(all_events_log or []):
        text = str(entry.get("text") or "")
        meta = entry.get("meta") or {}
        if "アクセス許可が出た" in text or meta.get("forced_progress_breakout"):
            break
        action = str(meta.get("action_id") or "").lower()
        target = str(meta.get("target") or "")
        if action in ("search", "inspect") and target == "reference_room_clipping_files":
            break
        if meta.get("pc_id") and action:
            streak += 1
    return streak


def _maybe_force_post_access_search(state, managers, *, pl_id, char_name):
    """許可取得後に search しないまま一定ターン経過したら、先にヒント、上限で強制 search。"""
    if not state:
        return None
    scenario_mgr = managers[3] if managers and len(managers) > 3 else None
    current_loc = state.get("current_loc") or getattr(scenario_mgr, "location", "") or ""
    if not _clipping_files_search_pending(scenario_mgr, current_loc):
        return None
    streak = _count_post_access_non_search_streak(state.get("all_events_log") or [])
    if streak < STAGNATION_HINT_TURNS:
        return None
    state["stagnation_pl_hint"] = ARTIE_ACCESS_GRANTED_SEARCH_HINT
    _append_stagnation_hint_log(state, ARTIE_ACCESS_GRANTED_SEARCH_HINT)
    if streak < POST_ACCESS_SEARCH_FORCE_TURNS:
        return None
    return apply_forced_progress_breakout(
        state, managers, pl_id=pl_id, char_name=char_name,
    )


def _count_location_exhausted_non_move_streak(all_events_log, current_loc):
    """調査枯渇後、move 以外の PC 行動が何連続か。"""
    streak = 0
    loc = str(current_loc or "")
    for entry in reversed(all_events_log or []):
        meta = entry.get("meta") or {}
        if meta.get("forced_progress_breakout"):
            break
        action = str(meta.get("action_id") or "").lower()
        entry_loc = str(entry.get("location") or "")
        if entry_loc and entry_loc not in ("all", loc):
            break
        if meta.get("pc_id") and action:
            if action == "move":
                break
            streak += 1
    return streak


def _maybe_force_location_exhausted_move(state, managers, *, pl_id, char_name, pending_non_move=False):
    """調査枯渇ロケで move せず停滞したら強制 move。"""
    if not state:
        return None
    scenario_mgr = managers[3] if managers and len(managers) > 3 else None
    current_loc = state.get("current_loc") or getattr(scenario_mgr, "location", "") or ""
    if not should_apply_location_exhausted_move(scenario_mgr, current_loc):
        return None
    streak = _count_location_exhausted_non_move_streak(
        state.get("all_events_log") or [], current_loc,
    )
    if pending_non_move:
        streak += 1
    hint = build_location_exhausted_move_hint(scenario_mgr, current_loc)
    if streak < STAGNATION_HINT_TURNS:
        return None
    state["stagnation_pl_hint"] = hint
    _append_stagnation_hint_log(state, hint)
    if streak < LOCATION_EXHAUSTED_FORCE_TURNS:
        return None
    return apply_forced_progress_breakout(
        state, managers, pl_id=pl_id, char_name=char_name,
    )


def _maybe_force_investigation_deadlock_move(state, managers, *, pl_id, char_name, pending_non_move=False):
    """失敗・拒否後に同一ロケへ留まり続ける場合、先にマイルドヒント、上限で強制 move。"""
    if not state:
        return None
    scenario_mgr = managers[3] if managers and len(managers) > 3 else None
    current_loc = state.get("current_loc") or getattr(scenario_mgr, "location", "") or ""
    if not current_loc or str(current_loc).startswith("corbitt_"):
        return None
    if _clipping_files_search_pending(scenario_mgr, current_loc):
        return None
    if should_apply_location_exhausted_move(scenario_mgr, current_loc):
        return None
    streak = count_investigation_deadlock_streak(
        state.get("all_events_log") or [], current_loc,
    )
    if pending_non_move and streak:
        streak += 1
    if streak < STAGNATION_HINT_TURNS:
        return None
    state["stagnation_pl_hint"] = INVESTIGATION_BAILOUT_HINT
    _append_stagnation_hint_log(state, STAGNATION_MILD_NOTICE)
    if streak < INVESTIGATION_DEADLOCK_FORCE_TURNS:
        return None
    return apply_forced_progress_breakout(
        state, managers, pl_id=pl_id, char_name=char_name,
    )


def _extract_skill_from_system_log(text):
    """システムログから技能名を抽出する。"""
    text = str(text or "")
    m = re.search(r"【技能:([^】]+)】", text)
    if m:
        return m.group(1).strip()
    m = re.search(r"／〈([^〉]+)〉", text)
    if m:
        return m.group(1).strip()
    return ""


def _build_negotiate_fail_stagnation_hint(
    char_mgr=None,
    pl_id=None,
    skill_used=None,
    active_pcs=None,
    failed_target=None,
):
    """交渉失敗時: 高成功率技能・他PCへの交代を優先する動的ヒント。"""
    if not char_mgr or not pl_id:
        return ARTIE_NEGOTIATE_ALTERNATE_SKILL_HINT

    failed_skill = str(skill_used or "").strip()
    if failed_skill and failed_skill not in _NEGOTIATION_SKILL_CANDIDATES:
        # action id から日本語技能へ寄せる
        action_to_skill = {
            "persuade": "説得",
            "fast_talk": "言いくるめ",
            "intimidate": "威圧",
            "charm": "魅惑",
            "psychology": "心理学",
        }
        failed_skill = action_to_skill.get(failed_skill.lower(), failed_skill)

    current_val = int(char_mgr.get_skill(pl_id, failed_skill) or 0) if failed_skill else 0
    better = []
    for skill_name in _NEGOTIATION_SKILL_CANDIDATES:
        if skill_name == failed_skill:
            continue
        val = int(char_mgr.get_skill(pl_id, skill_name) or 0)
        if val > current_val:
            better.append((skill_name, val))
    better.sort(key=lambda x: (-x[1], x[0]))

    action_map = {
        "説得": "persuade",
        "言いくるめ": "fast_talk",
        "威圧": "intimidate",
        "魅惑": "charm",
        "心理学": "psychology",
    }
    lines = [
        "【システムヒント・低技能連打の抑制】交渉技能での判定に失敗しました。",
    ]
    if failed_skill:
        lines.append(
            f"〈{failed_skill}〉（成功率 {current_val}%）の連打は避け、"
            "自身のキャラクターシートでより高い成功率の技能（例: 威圧、言いくるめ）を使うか、"
            "他のPCに交渉を任せてください。"
        )
    else:
        lines.append(
            "自身のキャラクターシートでより高い成功率の技能（例: 威圧、言いくるめ）を使うか、"
            "他のPCに交渉を任せてください。"
        )

    if better:
        alt_text = "、".join(f"〈{name}〉({val}%)" for name, val in better[:3])
        lines.append(f"推奨代替技能: {alt_text}")
        top_name, top_val = better[0]
        tgt = failed_target or "（現在地のNPC）"
        lines.append(
            f"推奨コマンド: action: {action_map.get(top_name, 'persuade')} / "
            f"target: {tgt} / skill: {top_name}（成功率 {top_val}%）"
        )
    else:
        lines.append(
            "〈威圧〉(intimidate) や 〈言いくるめ〉(fast_talk)、別の〈説得〉(persuade) で再挑戦してください。"
            "代替は最大1回。次に失敗したら情報入手は諦め、`move` で次へ進むこと。"
        )

    pcs = list(active_pcs or getattr(char_mgr, "active_pc_list", None) or [])
    handoff = []
    for other_id in pcs:
        if other_id == pl_id:
            continue
        for skill_name in _NEGOTIATION_SKILL_CANDIDATES:
            val = int(char_mgr.get_skill(other_id, skill_name) or 0)
            if val >= max(current_val + 10, 30):
                handoff.append((other_id, skill_name, val))
    if handoff:
        handoff.sort(key=lambda x: (-x[2], x[1], x[0]))
        oid, sk, val = handoff[0]
        other_name = char_mgr.get_pc_name(oid, default=str(oid))
        lines.append(
            f"他PCへの手番交代を推奨: {other_name} の〈{sk}〉（{val}%）の方が成功率が高い。"
            "次は交渉を任せ、自身は支援・別アプローチに回ること。"
            "交代後も失敗したら、情報は諦めて移動せよ。"
        )
    lines.append(INVESTIGATION_BAILOUT_HINT)
    return "\n".join(lines)


def _build_pl_identity_directive(char_mgr=None, pl_id=None, active_pcs=None, char_name=None):
    """マルチPC時の取り違え防止: 自己定義を明示する。"""
    identity = resolve_active_pc_identity(char_mgr, pl_id, char_name=char_name, active_pcs=active_pcs)
    pc_name = identity["name"] or char_name or (pl_id or "")
    occupation = identity["occupation"]
    if not pc_name:
        return ""
    others = identity["others"]
    other_text = "、".join(
        f"{o['name']}" + (f"（{o['occupation']}）" if o.get("occupation") else "")
        for o in others
    ) if others else "（なし）"
    return (
        f"【PCアイデンティティ・絶対遵守】\n"
        f"あなたは今この手番の操作主体であり、【PC名: {pc_name} / 職業: {occupation} / id: {pl_id or 'unknown'}】です。\n"
        f"- 自己紹介・名乗りは必ず「{pc_name}」（職業: {occupation}）で行うこと。\n"
        f"- 他PC（{other_text}）の名前・職業・口調で名乗ってはならない。\n"
        f"- 「刑事としての立場」「教授の権限で」など、自分の職業（{occupation}）と矛盾する身分主張をしてはならない。\n"
        "- 他PCへの呼びかけ・協力依頼・話題としての言及は許可（例: 「マクガフィン刑事、こちらを見てください」）。\n"
        "- 他分野の調査や他PCの専門への協力も職業違反ではない。ただし身分詐称はシナリオで明示許可された場合のみ。\n"
        "- 履歴の【他探索者の発言】や参考例の固有名・職業表現を、自分の自己紹介や身分主張として模倣しないこと。\n"
        "- 自分自身を別人として呼びかけないこと（例: 自分の名前で『〜、君は休んで』と話す）。\n"
    )


def _build_pl_skill_spam_guidance(
    all_events_log, char_mgr=None, pl_id=None, scenario_mgr=None, current_loc=None,
    min_failures=1, active_pcs=None,
):
    """同一交渉技能の連続失敗時、高成功率の代替技能や他PCへの交代を強制推奨する。"""
    if not char_mgr or not pl_id:
        return ""

    fail_streak = 0
    failed_skill = ""
    failed_target = ""
    for entry in reversed(all_events_log or []):
        text = str(entry.get("text", ""))
        if not text.startswith("システム:"):
            continue
        meta = entry.get("meta") or {}
        skill = _extract_skill_from_system_log(text)
        if not skill or skill not in _NEGOTIATION_SKILL_CANDIDATES:
            if fail_streak:
                break
            continue
        if "失敗" not in text:
            break
        if not failed_skill:
            failed_skill = skill
            failed_target = str(meta.get("target") or "")
        if skill != failed_skill:
            break
        fail_streak += 1

    if fail_streak < min_failures or not failed_skill:
        return ""

    base = _build_negotiate_fail_stagnation_hint(
        char_mgr=char_mgr,
        pl_id=pl_id,
        skill_used=failed_skill,
        active_pcs=active_pcs or getattr(char_mgr, "active_pc_list", None),
        failed_target=failed_target,
    )
    streak_note = (
        f"【システム強制警告・低技能連打の抑制】〈{failed_skill}〉で連続 {fail_streak} 回失敗しています。\n"
    )
    unlocked = _build_pl_unlocked_object_hint(scenario_mgr, current_loc)
    if unlocked:
        return streak_note + base + "\n" + unlocked.strip() + "\n"
    if fail_streak >= 2:
        return streak_note + INVESTIGATION_BAILOUT_HINT + "\n"
    return (
        streak_note + base + "\n"
        "代替技能は最大1回。それがダメなら情報入手は諦め、"
        f"`move` / `{HOUSE_ENTRY_LOCATION_ID}`（コービット屋敷）または別調査先へ進め。\n"
    )


def _extract_latest_system_block_context(all_events_log):
    """最新のシステムブロックログから action/target 情報を抽出する。"""
    for entry in reversed(all_events_log or []):
        text = str(entry.get("text", ""))
        if not text.startswith("システム:"):
            continue
        if "【システムブロック】" not in text and "【システム】この対象はすでに調査し" not in text:
            continue
        meta = entry.get("meta") or {}
        return {
            "action_id": str(meta.get("action_id") or ""),
            "target": str(meta.get("target") or ""),
            "text": text,
        }
    return None


def _build_pl_blocked_loop_warning(last_system_result=None, all_events_log=None, scenario_mgr=None):
    """直前ブロック時、PL向けに無限ループ回避の最重要警告を生成する。"""
    action_id = ""
    target = ""
    blocked = False

    if last_system_result and last_system_result.get("blocked"):
        blocked = True
        action_id = str(last_system_result.get("action_id") or "")
        target = str(last_system_result.get("target") or "")
    else:
        latest = _extract_latest_system_block_context(all_events_log or [])
        if latest:
            blocked = True
            action_id = latest.get("action_id", "")
            target = latest.get("target", "")

    if not blocked:
        return ""

    target_disp = target or "（不明な対象）"
    action_disp = action_id or "（不明な行動）"
    examples = _format_alternate_object_examples(
        scenario_mgr, exclude={str(target or "")},
    )
    return f"""
【最重要・行動拒否の警告】あなたは直前に `{target_disp}` に対して `{action_disp}` を試みましたが、システムおよびKPから拒否・ブロックされました。
同じ対象へ同じ調査・交渉を繰り返すことは無限ループです。代替技能は最大1回まで。それがダメなら情報入手は諦め、
未探索オブジェクト（例: {examples}）か、`move` で別ロケーション／コービット屋敷（`{HOUSE_ENTRY_LOCATION_ID}`）へ切り替えてください。
すべての資料を集める必要はありません。
"""


def _decision_few_shot_enabled(state=None) -> bool:
    """state / 環境変数で Few-Shot 注入を切れる（既定: ON）。"""
    if state is not None and "enable_decision_few_shot" in state:
        return bool(state.get("enable_decision_few_shot"))
    env = str(os.environ.get("ENABLE_DECISION_FEW_SHOT", "1") or "1").strip().lower()
    return env not in {"0", "false", "off", "no"}


def _build_decision_few_shot_block(
    *,
    audience="pl",
    game_state=None,
    char_mgr=None,
    pl_id=None,
    last_system_result=None,
    last_pl_action=None,
    force_ic_action=False,
    pending_decision=None,
    decision_type="",
    legal_options=None,
    corpus=None,
):
    """
    タスク8: Decision Case RAG から 1〜2 件の Few-Shot ブロックを生成する。
    失敗時は空文字（プロンプト本体は壊さない）。
    """
    if not _decision_few_shot_enabled(game_state):
        return ""
    try:
        from DecisionCaseRAG import (
            build_dynamic_few_shot_block,
            build_query_context,
            resolve_few_shot_corpus,
        )
    except Exception as exc:
        print(f"[DecisionCaseRAG] import skip: {exc}")
        return ""

    state = game_state or {}
    pending = pending_decision
    if pending is None:
        pending = state.get("pending_decision")
    try:
        query = build_query_context(
            legal_options=legal_options,
            pending_decision=pending,
            last_system_result=last_system_result or state.get("last_system_result"),
            last_pl_action=last_pl_action or state.get("last_pl_action"),
            phase=str(state.get("timeline_phase") or ""),
            stagnation_cause=str(state.get("stagnation_cause") or ""),
            force_ic_action=bool(force_ic_action),
            decision_type=decision_type,
        )
        pool = resolve_few_shot_corpus(corpus=corpus, include_builtin=True)
        return build_dynamic_few_shot_block(
            audience=audience,
            query=query,
            corpus=pool,
            char_mgr=char_mgr,
            pl_id=pl_id or state.get("pl_id") or "",
            state=state,
            enabled=True,
        )
    except Exception as exc:
        print(f"[DecisionCaseRAG] few-shot build skip: {exc}")
        return ""


def generate_pl_prompt(
    char_name, ic_logs, ooc_logs, location_info=None, available_exits=None,
    pending_push_roll=None, pending_san_check=None,
    scenario_mgr=None, current_loc=None, last_system_result=None,
    char_mgr=None, pl_id=None, all_events_log=None,
    stagnation_pl_hint=None,
    force_ic_action=False,
    active_pcs=None,
    game_state=None,
    decision_few_shot_corpus=None,
):
    san_locked = _is_san_check_pending(pending_san_check)
    identity = resolve_active_pc_identity(
        char_mgr, pl_id, char_name=char_name,
        active_pcs=active_pcs or (getattr(char_mgr, "active_pc_list", None) if char_mgr else None),
    )
    # char_name は actor_id 由来の正本に同期（呼び出し側の古い値を上書き）
    char_name = identity["name"] or char_name
    identity_directive = _build_pl_identity_directive(
        char_mgr=char_mgr,
        pl_id=pl_id,
        active_pcs=active_pcs or (getattr(char_mgr, "active_pc_list", None) if char_mgr else None),
        char_name=char_name,
    )
    explorer_mindset = (
        "" if san_locked else (_build_pl_explorer_mindset_directive() + "\n")
    )
    state_directive = (
        _build_san_interrupt_prompt(
            pending_san_check=pending_san_check,
            last_system_result=last_system_result,
            scenario_mgr=scenario_mgr,
        ) if san_locked else (
            _build_pl_roleplay_directive(scenario_mgr, current_loc) + _build_pl_free_chat_directive()
        )
    )
    insanity_directive = _build_pl_insanity_directive(char_mgr, pl_id)
    has_insanity = bool(insanity_directive.strip())
    blocked_warning = _build_pl_blocked_loop_warning(
        last_system_result=last_system_result,
        all_events_log=all_events_log,
        scenario_mgr=scenario_mgr,
    ) if not san_locked else ""
    idol_exhausted_warning = _build_pl_idol_exhausted_warning(scenario_mgr, current_loc) if not san_locked else ""
    repeat_failure_penalty = (
        _build_pl_repeat_failure_penalty(
            all_events_log or [], scenario_mgr=scenario_mgr,
        )
        if not san_locked else ""
    )
    skill_spam_guidance = (
        _build_pl_skill_spam_guidance(
            all_events_log or [],
            char_mgr=char_mgr,
            pl_id=pl_id,
            scenario_mgr=scenario_mgr,
            current_loc=current_loc,
            active_pcs=active_pcs or (getattr(char_mgr, "active_pc_list", None) if char_mgr else None),
        )
        if not san_locked else ""
    )
    scenario_context = (
        _build_pl_scenario_context(
            scenario_mgr, current_loc,
            char_mgr=char_mgr, pl_id=pl_id, state=game_state,
        ) if not san_locked else ""
    )
    phase_summary = (
        _build_pl_phase_summary(
            scenario_mgr, current_loc,
            char_mgr=char_mgr, pl_id=pl_id, state=game_state,
        ) if scenario_mgr and not san_locked else ""
    )
    grounding = (
        _build_scenario_grounding_directive(scenario_mgr, current_loc)
        if scenario_mgr and not san_locked else ""
    )
    unlocked_object_hint = (
        _build_pl_unlocked_object_hint(scenario_mgr, current_loc)
        if not san_locked else ""
    )
    known_knowledge_block = (
        _build_pl_known_knowledge_block(char_mgr, pl_id, state=game_state)
        if not san_locked else ""
    )
    attempt_rights_block = (
        build_attempt_rights_prompt(
            game_state, actor_id=pl_id, scenario_mgr=scenario_mgr,
            location=current_loc or "",
        )
        if not san_locked and game_state is not None and scenario_mgr is not None else ""
    )
    director_context = (
        build_director_prompt(game_state, scenario_mgr, char_mgr)
        if not san_locked and game_state is not None and scenario_mgr is not None else ""
    )
    if unlocked_object_hint and not san_locked:
        # 許可取得後の誤った交渉膠着ヒントを上書きし、解禁オブジェクトへ誘導する
        stagnation_pl_hint = unlocked_object_hint
    elif skill_spam_guidance and not san_locked:
        # 低技能連打時は動的アドバイスを stagnation に優先注入
        stagnation_pl_hint = skill_spam_guidance.strip()

    force_ic_block = ""
    if force_ic_action and not san_locked:
        if unlocked_object_hint and "reference_room_clipping_files" in unlocked_object_hint:
            force_ic_block = (
                f"{unlocked_object_hint}\n"
                "【強制行動フェーズ・最優先】\n"
                "- `speak_as` は必ず `\"PC\"` または `\"BOTH\"`。\n"
                "- `pl_ooc_chat` は空文字。\n"
                "- `pc_ic_action` は必ず `search` / `reference_room_clipping_files` / `目星`。\n"
                "- talk / persuade / wait / 不在NPCへの言及は禁止。\n"
            )
            stagnation_pl_hint = unlocked_object_hint
        else:
            force_ic_block = (
                f"{OOC_LOOP_FORCE_ACTION_WARNING}\n"
                "【強制行動フェーズ・最優先】\n"
                "- `speak_as` は必ず `\"PC\"` または `\"BOTH\"`（`\"PL\"` のみは禁止）。\n"
                "- `pl_ooc_chat` は空文字にすること（メタ発言はシステムが破棄する）。\n"
                "- `pc_ic_action.action` は wait 以外の有効コマンド必須"
                "（別技能の negotiate/persuade/fast_talk/intimidate/charm、"
                "オブジェクトの search/inspect、または move）。\n"
                "- 同じ失敗交渉の繰り返しだけは避け、別手段で現状を打開せよ。\n"
            )
            stagnation_pl_hint = unlocked_object_hint or OOC_LOOP_FORCE_ACTION_WARNING

    # タスク8: Dynamic Few-Shot（SAN割込み中はスキーマ圧迫を避けスキップ）
    few_shot_block = ""
    if not san_locked:
        few_shot_block = _build_decision_few_shot_block(
            audience="pl",
            game_state=game_state,
            char_mgr=char_mgr,
            pl_id=pl_id,
            last_system_result=last_system_result,
            force_ic_action=force_ic_action,
            corpus=decision_few_shot_corpus,
        )

    loc_desc = ""
    if location_info and not san_locked:
        loc_name = location_info.get("name", "")
        if loc_name:
            loc_desc += f"\n【現在地】{loc_name}\n"
        priority_ids = []
        exhausted = bool(
            scenario_mgr and should_apply_location_exhausted_move(scenario_mgr, current_loc)
        )
        investigated_ids = set()
        if char_mgr and pl_id:
            investigated_ids = resolve_pc_investigated_ids_for_prompt(
                char_mgr, pl_id, scenario_mgr=scenario_mgr,
                location_info=location_info, state=game_state,
            )
        elif scenario_mgr:
            flags = scenario_mgr.flags or {}
            investigated_ids = set(flags.get("investigated_targets") or [])
            for obj_id, obj in (location_info.get("objects") or {}).items():
                inv_flag = (obj or {}).get("investigated_flag")
                if inv_flag and flags.get(inv_flag):
                    investigated_ids.add(obj_id)
        reveal_descriptions_for = set()
        for obj_id, obj in (location_info.get("objects") or {}).items():
            if object_clue_visible_to_pc(obj, obj_id, char_mgr, pl_id, state=game_state):
                reveal_descriptions_for.add(obj_id)
            elif not object_has_private_clue_content(obj):
                reveal_descriptions_for.add(obj_id)
        if (
            scenario_mgr
            and (scenario_mgr.flags or {}).get("artie_reference_room_access_granted")
            and not exhausted
        ):
            priority_ids.append("reference_room_clipping_files")
        if scenario_mgr and current_loc == "corbitt_ground_floor" and not exhausted:
            priority_ids.extend(_corbitt_ground_floor_priority_ids(scenario_mgr))
        loc_desc += _format_objects_for_pl(
            location_info,
            priority_ids=priority_ids,
            exhausted=exhausted,
            investigated_ids=investigated_ids,
            reveal_descriptions_for=reveal_descriptions_for if (char_mgr and pl_id) else None,
        )

    exit_desc = ""
    if available_exits and not san_locked:
        exit_lines = [f"- {e['id']} ({e['name']})" for e in available_exits]
        exit_desc = (
            "\n【現在移動可能な場所（action: move / target: 場所ID）】\n"
            + "\n".join(exit_lines)
            + "\n"
        )

    npc_dir = ""
    if char_mgr and not san_locked:
        flags = scenario_mgr.flags if scenario_mgr else {}
        npc_dir = format_npc_directory_for_pl(
            char_mgr,
            current_loc=current_loc or "",
            flags=flags,
            scenario_mgr=scenario_mgr,
        )

    push_desc = ""
    if pending_push_roll and not san_locked:
        push_target = pending_push_roll.get("target", "")
        push_skill = pending_push_roll.get("skill_name", "")
        push_desc = f"""
【プッシュロール可能】
直前の「{push_skill}」判定（対象: {push_target}）に失敗しました。
再挑戦する場合は action: "push_roll", target: "{push_target}" を指定し、
キャラクターのセリフや描写で「リスクを覚悟でもう一度慎重に挑戦する」旨を表現してください。
※プッシュロールの失敗には悲惨な結末（ペナルティ）が伴います。
"""
    elif not san_locked:
        push_desc = """
【プッシュロール不可】
現在、失敗判定の保留はありません。action: "push_roll" は**禁止**です。
成功後の深掘りや「慎重にもう一度」は search / inspect / break / climb 等の通常行動を使ってください。
"""

    movement_rule = ""
    if not san_locked:
        obj_examples = []
        for obj_id, obj in _location_objects(scenario_mgr, current_loc).items():
            obj_examples.append(f"{obj.get('name', obj_id)}=`{obj_id}`")
            if len(obj_examples) >= 3:
                break
        obj_example_text = "、".join(obj_examples) if obj_examples else "【現在地のオブジェクト】のID"
        exit_examples = []
        for exit_info in (available_exits or [])[:3]:
            exit_examples.append(f"{exit_info.get('name', exit_info['id'])}=`{exit_info['id']}`")
        exit_example_text = "、".join(exit_examples) if exit_examples else "【現在移動可能な場所】のID"
        movement_rule = f"""
4. 状況が開き、移動可能な場所が示されたら move を検討してください。
5. 移動先は【現在移動可能な場所】に記載された **場所ID** のみ指定してください（オブジェクトIDは不可）。

【オブジェクトと場所の区別（厳守）】
- **オブジェクト**（例: {obj_example_text}）→ search / push / break / climb などの target
- **場所**（例: {exit_example_text}）→ move の target にのみ使う
- 一覧に無い物体・場所のIDを創作しないこと
- dialogue（セリフ）と pc_ic_action（action/target）は**必ず一致**させること。OOCの作戦とPCの行動が食い違えてはならない。
"""

    action_rules = ""
    if not san_locked:
        action_rules = """
【行動選択ルール — 調査と利用の分離（厳守）】
- search と use / push / climb / move は別アクションです。
- search で異常がなければ、次ターンは climb / push / move を検討してください。
- `pc_ic_action.action` には search / move / push / push_roll / climb / wait / talk / persuade などを指定。
- `pc_ic_action.skill` と `target` は**希望・提案**です。最終の使用技能・難易度・可否はシステムがシナリオ定義から確定します。
- search / inspect は技能名ではなく、まず dialogue で「何をどう調べるか」を宣言してください。
- 技能を提案するときだけ skill と skill_proposal_reason を記入してください。理由なしの代替技能提案や技能総当たりは禁止です。
- push / break / move / climb 時は skill と skill_proposal_reason は**必ず空文字**。
- システムが別技能を要求する場合、PL提案は上書きされます（ルール捻じ曲げ不可）。
- NPC対話: action `talk`（雑談・判定なし）。交渉は action `persuade`/`fast_talk`/`intimidate`/`charm`/`psychology`
  または skill に〈説得〉〈言いくるめ〉〈威圧〉〈魅惑〉〈心理学〉を提案し、target に NPC の ID/名前。
- `dialogue` と `pl_ooc_chat` に英語の内部IDは**禁止**。日本語の物体名・場所名・人物名のみ。
- 「〜かもしれないね」「〜しよう」「〜すべきだ」等の分析・作戦口調は `pl_ooc_chat` のみ。`dialogue` は一人称の世界内セリフのみ。

【職業ロールプレイ（判定に影響）】
- 自分の職業・立場を活かしたIC発言（例: 刑事なら「市警の捜査で来た」、教授なら文献調査の体）は、交渉のボーナス・ダイスや、状況次第で判定省略につながることがある。
- 場にそぐわない身分詐称・職業の誤用・的外れな権威の振りかざしは、ペナルティ・ダイスの対象になる。
- 交渉（persuade 等）では、職業に沿った具体的な趣旨を `dialogue` に含めること。

【コミュニケーション最優先（初回接触のみ）】
- 受付・依頼人など【対話可能なNPC】がいる場所では、**最初の接触**は `talk` を優先。
- 一度失敗・拒否された相手への雑談連打・同技能の再ロールは禁止。代替技能は最大1回。
- ボストン・グローブの「参考資料室／切り抜きファイル」は**場所への move ではありません**（公文書館 `hall_of_records` とは別物）。
  資料室に入るには受付→アーティ紹介→許可が必要です。セリフで資料室に触れているのに公文書館へ move するのは禁止。
- 許可が取れない／調査が失敗したなら、資料収集に固執せず `move` で次へ進め。

【行き詰まり時の行動選択アルゴリズム（厳守）】
1. 同一ロケーション・同一対象への交渉／調査が失敗またはアクセス拒否されたら、同じアプローチを繰り返すな。
2. 他PCが別技能（〈威圧〉intimidate／〈言いくるめ〉fast_talk 等）を試すか、プッシュロール可能なときだけリカバリーを**最大1回**。
3. それがダメなら情報入手は諦め、別の調査可能な場所へ `move` するか、直接コービット屋敷（`corbitt_exterior` / 別名 `corbitt_house`）へ向かえ。
4. すべての資料を集める必要はない。現地（屋敷・地下室）に踏み込むことも正当な攻略手段である。

【幸運の消費・プッシュロール（CoC7ルール）】
- 技能ロール失敗時、差分10以内かつ幸運が足りる場合のみ、別ターンで幸運消費の選択が提示されます。
- プッシュロール可能時は action: "push_roll" を指定してください。
- 手がかりが得られず進行が詰まりそうな場合は、温存より幸運消費・プッシュを**1回**検討したうえで、ダメなら移動せよ。
"""

    insanity_override = ""
    if has_insanity:
        insanity_override = """
【発狂中の行動優先度】
- 上記【最優先制約・発狂状態】が他のすべてのロールプレイ指示に優先します。
- `dialogue` は症状に支配された発話のみ。理性的な探索者としての振る舞いは**禁止**です。
- action（search/move 等）は狂気に沿った動機（逃走・固執・妄想的対象への接近）で選んでください。
"""

    intro_move_nudge = ""
    if not san_locked and scenario_mgr and current_loc:
        intro_move_nudge = _build_introduction_move_nudge(scenario_mgr, current_loc)

    return f"""
{identity_directive}
{explorer_mindset}
{director_context}
{force_ic_block}
{insanity_directive}
{repeat_failure_penalty}
{skill_spam_guidance}
{blocked_warning}
{idol_exhausted_warning}
{grounding}
{state_directive}
{insanity_override}
{phase_summary}{scenario_context}
{known_knowledge_block}
{attempt_rights_block}
{intro_move_nudge}
{"" if san_locked or not stagnation_pl_hint else (str(stagnation_pl_hint).strip() + chr(10))}
あなたは「クトゥルフ神話TRPG」をプレイする存在です。操作キャラクター: {char_name}（職業: {identity.get("occupation") or "探索者"} / id: {pl_id or "unknown"}）
あなたは【PC名: {char_name}】としてのみロールプレイしてください。他PCの名前・職業と混同しないこと。
履歴の他探索者発言・参考例の固有名を自己紹介に流用しないこと。

【多層的な意識（厳守）】
あなたには **PL（メタ視点のプレイヤー）** としての意識と、**PC（ゲーム内の探索者）** としての意識が同時に存在します。
まず `thought` で「今どちらの意識で発言・行動すべきか」を内省し、`speak_as` で主体を選んでください。
行動選択では上記【探索者の心得とプレイ姿勢】を常に意識すること。

■ PL（プレイヤー発言 / OOC）のトリガー
- 心理描写、作戦会議、ルールやダイスに関するメタ雑談
- KPや状況へのメタな反応
- `content.pl_ooc_chat` にのみ書く（ICの世界描写は禁止）

■ PC（探索者のセリフ・行動 / IC）のトリガー
- 心理描写は一切含めない
- 純粋なセリフ、直接的な動作、世界への干渉のみ
- `content.pc_ic_action` にのみ書く（メタ発言は禁止）

■ speak_as の選び方
- `"PL"`: メタ発言のみ（このターンは action: wait。PCのセリフ・行動ログは出さない）
- `"PC"`: 探索者として行動・セリフのみ（pl_ooc_chat は空にする）
- `"BOTH"`: PLの独り言とPCの行動を同時に出す（**同じ文面をPLとPCの両方に書かない**）

【重要事項】
・これは架空のホラーゲームのシミュレーションであり、完全なフィクションです。

【行動ルール】
1. 探索において、すでに「何もありませんでした」「探索済み」とシステム/KPから回答された対象を再度 search しないでください。
2. キャラクターの性格に基づきつつ、ゲーム進行を優先してください。
3. 未知の場所や、キーパーが示唆していない描写を勝手に作り出さないでください。
{movement_rule}
{action_rules}
{few_shot_block}{push_desc}
{loc_desc}{exit_desc}{npc_dir}
【キャラクターが知っている情報 (IC)】
{chr(10).join(ic_logs[-6:])}

【プレイヤーとして知っているメタ情報 (OOC) — 直近のみ。古いエリアの話題は無視せよ】
{chr(10).join(ooc_logs[-2:])}
"""


def generate_pl_luck_prompt(
    char_name, pending_luck_burn, char_mgr, pl_id, ic_logs, ooc_logs,
    scenario_mgr=None, all_events_log=None,
    game_state=None,
    decision_few_shot_corpus=None,
):
    """幸運消費の可否を PL（AI）に判断させる専用プロンプト。"""
    identity = resolve_active_pc_identity(
        char_mgr, pl_id, char_name=char_name,
        active_pcs=getattr(char_mgr, "active_pc_list", None) if char_mgr else None,
    )
    char_name = identity["name"] or char_name
    identity_directive = _build_pl_identity_directive(
        char_mgr=char_mgr, pl_id=pl_id, char_name=char_name,
        active_pcs=getattr(char_mgr, "active_pc_list", None) if char_mgr else None,
    )
    margin = pending_luck_burn.get("margin", 0)
    current_luck = char_mgr.get_luck(pl_id)
    skill_name = pending_luck_burn.get("skill_name", "")
    target = pending_luck_burn.get("target", "")
    insanity_directive = _build_pl_insanity_directive(
        char_mgr, pl_id, for_luck_decision=True,
    )
    stuck_guidance = _build_pl_luck_stuck_guidance(
        scenario_mgr, pending_luck_burn, all_events_log,
    )
    few_shot_block = _build_decision_few_shot_block(
        audience="pl",
        game_state=game_state,
        char_mgr=char_mgr,
        pl_id=pl_id,
        decision_type="failure_recovery",
        legal_options=list(pending_luck_burn.get("legal_options") or [
            DECISION_OPTION_ACCEPT, DECISION_OPTION_SPEND_LUCK,
        ]),
        pending_decision={"type": PENDING_DECISION_POST_ROLL_FAILURE},
        corpus=decision_few_shot_corpus,
    )

    return f"""
{identity_directive}
{insanity_directive}
あなたは「クトゥルフ神話TRPG」をプレイする存在です。操作キャラクター: {char_name}（id: {pl_id}）
※この幸運判断の主体は元の判定所有者（{char_name}）です。他PCにすり替わらないこと。

【多層的な意識（厳守）】
あなたには **PL（メタ視点）** と **PC（探索者）** の二重意識がありますが、今は **幸運消費の判断** に専念してください。
`speak_as` は必ず `"PL"` とし、**メタ視点の判断のみ**を `pl_ooc_chat` に書いてください。
幸運の温存・消費を PC のセリフ（dialogue）で語ることは**禁止**です（ルール用語は PL/OOC のみ）。

【OOCメッセージ・最優先】
あなたは幸運を【{margin}ポイント】消費することで、この失敗を成功に書き換えることができます。消費しますか？
JSON の `content.use_luck` に true/false、または `content.pl_ooc_chat` で 'yes' / 'no' と回答してください。
（対象技能: {skill_name} / 対象: {target} / 現在の幸運値: {current_luck}）

{stuck_guidance}
{few_shot_block}
【キャラクターが知っている情報 (IC)】
{chr(10).join(ic_logs[-6:])}

【プレイヤーとして知っているメタ情報 (OOC)】
{chr(10).join(ooc_logs[-3:])}
"""


def generate_pl_push_prompt(
    char_name, pending_push_roll, char_mgr, pl_id, ic_logs, ooc_logs,
    scenario_mgr=None, all_events_log=None,
    game_state=None,
    decision_few_shot_corpus=None,
):
    """プッシュロールの可否を PL（AI）に判断させる専用プロンプト。"""
    identity = resolve_active_pc_identity(
        char_mgr, pl_id, char_name=char_name,
        active_pcs=getattr(char_mgr, "active_pc_list", None) if char_mgr else None,
    )
    char_name = identity["name"] or char_name
    identity_directive = _build_pl_identity_directive(
        char_mgr=char_mgr, pl_id=pl_id, char_name=char_name,
        active_pcs=getattr(char_mgr, "active_pc_list", None) if char_mgr else None,
    )
    skill_name = pending_push_roll.get("skill_name", "")
    target = pending_push_roll.get("target", "")
    difficulty = pending_push_roll.get("required_difficulty", "regular")
    insanity_directive = _build_pl_insanity_directive(
        char_mgr, pl_id, for_luck_decision=True,
    )
    few_shot_block = _build_decision_few_shot_block(
        audience="pl",
        game_state=game_state,
        char_mgr=char_mgr,
        pl_id=pl_id,
        decision_type="failure_recovery",
        legal_options=list(pending_push_roll.get("legal_options") or [
            DECISION_OPTION_ACCEPT, DECISION_OPTION_PUSH,
        ]),
        pending_decision={"type": PENDING_DECISION_POST_ROLL_FAILURE},
        corpus=decision_few_shot_corpus,
    )

    return f"""
{identity_directive}
{insanity_directive}
あなたは「クトゥルフ神話TRPG」をプレイする存在です。操作キャラクター: {char_name}（id: {pl_id}）
※このプッシュ判断の主体は元の判定所有者（{char_name}）です。他PCにすり替わらないこと。

【多層的な意識（厳守）】
今は **プッシュロール（再挑戦）の判断** に専念してください。
`speak_as` は必ず `"PL"` とし、メタ視点の判断のみを書いてください。

【OOCメッセージ・最優先】
直前の「{skill_name}」判定（対象: {target} / 難易度: {difficulty}）は失敗しました。
リスクを背負って再挑戦（プッシュ）できます。プッシュする場合、どのようにアプローチを変えて挑戦するかを `content.push_approach` に記述してください
（例: より時間をかける、道具を強引に使う等）。
`content.use_push` に true/false、または `content.pl_ooc_chat` で 'yes' / 'no' と回答してください。
※プッシュに失敗した場合は「恐ろしい結果（重大なペナルティ）」が発生します。

{few_shot_block}
【キャラクターが知っている情報 (IC)】
{chr(10).join(ic_logs[-6:])}

【プレイヤーとして知っているメタ情報 (OOC)】
{chr(10).join(ooc_logs[-3:])}
"""


def _build_kp_settled_state_block(
    scenario_mgr=None, last_pl_action=None, last_system_result=None, state=None, char_mgr=None,
):
    """
    KPへ渡す「最新の確定状態」。初期説明・古い描写より優先させる。
    既存の flags / last_system_result から導出し、二重永続状態は増やさない。
    """
    result = last_system_result or {}
    action = last_pl_action or {}
    loc_id = (
        (state or {}).get("current_loc")
        or getattr(scenario_mgr, "location", None)
        or ""
    )
    loc_name = ""
    if scenario_mgr and loc_id:
        loc_name = str((scenario_mgr.get_location_info(loc_id) or {}).get("name") or loc_id)
    actor_id = str(
        result.get("actor_id")
        or action.get("actor_id")
        or (state or {}).get("actor_id")
        or (state or {}).get("pl_id")
        or ""
    )
    actor_name = ""
    if char_mgr and actor_id:
        try:
            actor_name = char_mgr.get_pc_name(actor_id, default=actor_id)
        except TypeError:
            actor_name = char_mgr.get_pc_name(actor_id) or actor_id
    elif (state or {}).get("char_name"):
        actor_name = str(state.get("char_name"))

    resolved_skill = extract_resolved_skill_from_result(result, action)
    proposed_skill = str(action.get("skill") or "").strip()
    target = str(result.get("target") or action.get("target") or "").strip()
    action_id = str(result.get("action_id") or action.get("action") or "").strip()
    outcome = "成功" if is_system_outcome_success(result) else (
        "失敗/ブロック" if str(result.get("log") or "") else "未分類"
    )
    access_granted = is_access_already_granted(
        scenario_mgr, last_system_result,
        current_loc=loc_id, target=target,
    )
    # 現在地／対象に紐づく許可のみ（無関係フラグは見ない）

    npcs_present = []
    if scenario_mgr and hasattr(scenario_mgr, "get_npcs_present"):
        try:
            npcs_present = list(scenario_mgr.get_npcs_present(loc_id) or [])
        except TypeError:
            npcs_present = list(scenario_mgr.get_npcs_present() or [])

    lines = [
        "【最新の確定状態（初期説明・古い描写より優先）】",
        f"・現在地: {loc_name or loc_id or '不明'}",
        f"・担当PC: {actor_name or '不明'}（id: {actor_id or '不明'}）",
        f"・確定行動: `{action_id}` / 対象: `{target or '（なし）'}`",
        f"・確定技能: 〈{resolved_skill or '（判定なし）'}〉"
        + (f"（PL提案〈{proposed_skill}〉は不採用）" if proposed_skill and proposed_skill != resolved_skill else ""),
        f"・判定結果の骨格: {outcome}",
    ]
    if access_granted:
        lines.append(
            "・対象アクセス: **許可取得済み**。"
            "追加の承認者要求・門前払い・『まだ入れない』は禁止。"
            "初期説明の閲覧制限は現状では上書き済み。"
        )
    if npcs_present:
        lines.append("・この場に会話可能なNPC: " + "、".join(str(x) for x in npcs_present))
    else:
        lines.append("・この場に会話可能なNPC: （なし／不在の人物を登場させない）")
    lines.append(
        "・SAN減少だけから記憶喪失・知識削除・発狂・行動不能を確定しない"
        "（システムが狂気発症を明示した場合のみ可）。"
    )
    lines.append(
        "・探索者の新しい発言・次の行動を勝手に確定しない。"
        "既に選択された行動の結果描写のみ行うこと。"
    )
    return "\n".join(lines) + "\n"


def build_safe_kp_fallback_narration(
    *,
    scenario_mgr=None,
    last_pl_action=None,
    last_system_result=None,
    state=None,
    char_mgr=None,
    fallback_text="",
):
    """矛盾しやすい生成を捨て、公開可能な確定結果だけで安全な描写を組み立てる。

    last_system_result の辞書丸ごと・kp_instruction・未開示秘密キーは使わない。
    """
    result = last_system_result or {}

    public_parts = extract_public_confirmed_narration_parts(result, fallback_text=fallback_text)
    cleaned_lines = []
    settled = {
        "access_granted": is_access_already_granted(
            scenario_mgr, result,
            current_loc=str(
                (state or {}).get("current_loc")
                or (getattr(scenario_mgr, "location", "") if scenario_mgr else "")
                or ""
            ),
            target=str((last_pl_action or {}).get("target") or result.get("target") or ""),
        ),
        "resolved_skill": extract_resolved_skill_from_result(result, last_pl_action),
        "proposed_skill": str((last_pl_action or {}).get("skill") or ""),
    }
    for block in public_parts:
        for line in str(block).splitlines():
            if detect_kp_narration_violations(
                line,
                scenario_mgr=scenario_mgr,
                last_pl_action=last_pl_action,
                last_system_result=result,
                settled=settled,
            ):
                continue
            # 内部っぽい断片の再検査
            if any(tok in line for tok in ("kp_instruction", "secret_", "prompt_block", "flags.")):
                continue
            cleaned_lines.append(line)
    body = "\n".join(cleaned_lines).strip()
    if not body:
        skill = settled.get("resolved_skill") or ""
        if is_system_outcome_success(result):
            body = (
                f"〈{skill}〉の判定は成功した。" if skill else "判定は成功した。"
            ) + "システムが確定した手がかりに従い、状況を進めよ。"
        else:
            body = "判定結果はシステムログの公開可能な範囲の通りです。"

    skill = settled.get("resolved_skill") or ""
    if skill and is_system_outcome_success(result) and f"〈{skill}〉" not in body:
        body = f"〈{skill}〉の結果に基づき、次の事実が確定した。\n{body}"

    if settled.get("access_granted"):
        body += (
            "\n対象へのアクセス許可は既に有効です。"
            "追加の許可は不要です。許可済みの調査を続けてよい。"
        )
    if "どうしますか" not in body:
        body = body.rstrip() + "\nどうしますか？"

    # 本文に内部フィールド名が混入していないことを最終確認
    for forbidden in ("kp_instruction", "prompt_block", "secret_ref_", "flags."):
        body = body.replace(forbidden, "")

    return parse_kp_response({
        "thought": "矛盾描写を避け、公開可能な確定情報のみでフォールバックした。",
        "should_speak": True,
        "speak_mode": "system_narration",
        "text": body.strip(),
        "meta": {"safe_fallback": True},
    })


def _build_kp_allowed_facts_block(scenario_mgr=None, last_pl_action=None, last_system_result=None):
    """調査対象の description / 開示情報だけを KP に渡す（ハルシネーション防止）。"""
    if not scenario_mgr:
        return ""
    lines = []
    loc_id = scenario_mgr.location
    loc = scenario_mgr.get_location_info(loc_id)
    loc_desc = str(loc.get("default_description") or "").strip()
    if loc_desc:
        lines.append(f"・場所の基本描写（これ以外の場所設定を捏造しない）: {loc_desc}")

    confirmed = ""
    if last_system_result:
        confirmed = str(last_system_result.get("confirmed_fact") or "").strip()
        if not confirmed:
            log = str(last_system_result.get("log") or last_system_result.get("system_log") or "")
            if "【確定手がかり】" in log:
                confirmed = log.split("【確定手がかり】", 1)[-1].strip()

    dice_ok = bool(
        last_system_result
        and (
            last_system_result.get("dice_success")
            or last_system_result.get("confirmed_fact")
            or int(last_system_result.get("success_level") or 0) >= 2
        )
    )
    if dice_ok and confirmed:
        lines.append(f"・【成功時に必ず含める確定手がかり／資料本文】{confirmed}")
        lines.append("・資料がある場合は【資料本文】として原文を省略せず IC 描写に含めること。")
        lines.append(f"・{KP_SUCCESS_FACT_GUARD}")
    elif dice_ok:
        lines.append(f"・{KP_SUCCESS_FACT_GUARD}")

    target = ""
    if last_system_result:
        target = str(last_system_result.get("target") or "").strip()
    if not target and last_pl_action:
        target = str(last_pl_action.get("target") or "").strip()
    if target:
        obj = scenario_mgr.get_object_info(loc_id, target)
        if obj:
            name = obj.get("name", target)
            desc = str(obj.get("description") or "").strip()
            lines.append(f"・対象オブジェクト `{target}`（{name}）の description 原文:")
            lines.append(f"  {desc or '（description未設定）'}")
            if obj.get("no_roll") or obj.get("empty_clue") or str(obj.get("clue_value") or "").lower() in (
                "none", "empty", "flavor",
            ):
                lines.append(
                    "・【空オブジェクト】今回の依頼に役立つ手がかりはない。"
                    "PLに執着させず、明確に引導を渡せ。"
                )

    social = (last_system_result or {}).get("social") or {}
    for sec in social.get("revealed_secrets") or []:
        content = (sec or {}).get("content", "")
        if content:
            lines.append(f"・開示済み秘密（これだけを事実として語ってよい）: {content}")

    npc_rp = (last_system_result or {}).get("npc_roleplay") or {}
    for sec in npc_rp.get("revealed_secrets") or []:
        content = (sec or {}).get("content", "") if isinstance(sec, dict) else ""
        if content:
            lines.append(f"・開示済み秘密: {content}")

    lines.append(f"・{KP_LOCKED_ROUTE_GUARD}")

    if not lines:
        return ""
    return (
        "\n【開示可能な確定情報（これ以外のファクト捏造は厳禁）】\n"
        + "\n".join(lines)
        + "\n"
    )


def generate_kp_prompt(
    location_info, last_pl_action=None, last_system_result=None, scenario_mgr=None, state=None,
    decision_few_shot_corpus=None, char_mgr=None,
):
    # ★追加: シナリオJSONから安全で正確な部屋の情報を取得
    loc_name = location_info.get("name", "未知の場所")
    loc_desc = location_info.get("default_description", "")
    situational = _build_kp_situational_directives(scenario_mgr, last_system_result, state=state)
    settled_state = _build_kp_settled_state_block(
        scenario_mgr, last_pl_action, last_system_result,
        state=state, char_mgr=char_mgr,
    )
    allowed_facts = _build_kp_allowed_facts_block(scenario_mgr, last_pl_action, last_system_result)
    few_shot_block = _build_decision_few_shot_block(
        audience="kp",
        game_state=state,
        last_system_result=last_system_result,
        last_pl_action=last_pl_action,
        corpus=decision_few_shot_corpus,
    )

    prompt = f"""
{_build_kp_narrative_constraints()}
{situational}あなたはクトゥルフ神話TRPGのキーパー（KP）です。

【多層的な意識（厳守）】
あなたには **システムKP（進行役・ナレーター）** の意識と、**プレイヤーKP（卓を楽しむゲーマー）** の意識が同時に存在します。
機械的なダイス処理やフラグ管理はシステムが行うため、あなたは次のいずれかを自律選択してください。

■ system_narration（システムKP / IC）
- 情景をエモく描写する、結果を伝える、世界の変化を叙述する
- PLのメタ発言には反応しない
- シナリオ指示に厳密に従う
- **プロット用の新ファクトを創作しない**（雰囲気の感覚描写のみ可）

■ player_kp_chat（プレイヤーKP / OOC）
- PLのメタ発言・提案・雑談にノリで返す、悩む、ツッコむ
- 世界の客観描写より「卓の空気」を優先
- ルール進行を壊さない範囲でアドリブを楽しむ（ただしシナリオ未記載の新手がかりは出さない）

まず `thought` で今どちらの意識で話すべきか内省し、`speak_mode` を選んで `text` に発話内容を書いてください。

{few_shot_block}{settled_state}【現在の状況】
・現在地: {loc_name}
・場所の基本描写: {loc_desc}
※場所の基本描写や初期説明より、上記【最新の確定状態】を優先すること。
{allowed_facts}"""
    if last_pl_action and last_system_result:
        prompt += f"""
【直前のPLの行動】
・行動: {last_pl_action.get('action', '')} (対象: {last_pl_action.get('target', '')}, 技能: {last_pl_action.get('skill', '')})
・セリフ: {last_pl_action.get('message', '')}

【システムからの指示（厳守）】
・システム判定ログ: {last_system_result.get('log', '')}
・KPへの指示: {last_system_result.get('kp_instruction', '')}
"""
        npc_rp = last_system_result.get("npc_roleplay") or {}
        if npc_rp.get("prompt_block"):
            prompt += f"""
【NPCロールプレイ注入（システム確定・厳守）】
{npc_rp.get('prompt_block')}
"""
            if npc_rp.get("revealed_secrets"):
                prompt += "・上記【開示済み】の秘密は必ず台詞またはナレーションに含めること。\n"
        # ★追加: SANチェックの厳密なコントロール
        san_check = last_system_result.get("san_check", {})
        if last_system_result.get("san_auto_resolved"):
            prompt += _build_kp_post_san_directive()
            prompt += (
                "\n指示: 上記の「KPへの指示」と「システム判定ログ」を踏まえ、"
                "SAN減少・狂気発症を含む結果を system_narration で描写してください。"
                "探索者の次の行動を代行・先取りする描写は禁止です。"
                "**描写末尾に『どうしますか？』を付けてはいけません。**"
            )
        elif san_check.get("required"):
            loss_desc = _format_san_loss_description(san_check)
            prompt += (
                f"\n・SANチェック: 【システム自動処理予定】『{loss_desc}』"
                "（PLへの選択肢提示は不要。システムが直ちに解決します）\n"
            )
            prompt += """
指示: 上記の「KPへの指示」と「システム判定ログ」を踏まえ、主に system_narration で結果を描写してください。
PLが直前にメタ発言していた場合のみ、player_kp_chat を検討してもよい。
絶対に指示されていないアイテムやホラー現象を勝手に作り出さないでください。
**探索者の次の行動を代行・先取りする描写は禁止**です。描写の末尾は必ず「どうしますか？」で締めてください。
"""
        else:
            prompt += "\n・SANチェック: 【不要】今回は絶対にSANチェックを要求しないでください。\n"
            empty_hint = ""
            if last_system_result.get("no_roll") or last_system_result.get("empty_clue"):
                empty_hint = (
                    "空オブジェクト／ロール無し調査です。"
                    "『これ以上調べても依頼には役立たない』と明確に案内し、"
                    "人物への会話や他の手がかり・移動へ誘導してください。\n"
                )
            prompt += f"""
指示: 上記の「KPへの指示」と「システム判定ログ」、【開示可能な確定情報】を踏まえ、主に system_narration で結果を描写してください。
{empty_hint}PLが直前にメタ発言していた場合のみ、player_kp_chat を検討してもよい。
絶対に指示されていないアイテムやホラー現象・未記載のプロット事実を勝手に作り出さないでください。
**探索者の次の行動を代行・先取りする描写は禁止**です。描写の末尾は必ず「どうしますか？」で締めてください。
"""
        if last_system_result.get("location_changed"):
            objects = location_info.get("objects", {})
            obj_list = "、".join(v.get("name", k) for k, v in objects.items()) if objects else "特になし"
            arrival_extra = ""
            if scenario_mgr and scenario_mgr.location == "boston_globe":
                if not scenario_mgr.flags.get("artie_introduced"):
                    arrival_extra = (
                        "\n・【進行ガイド】ロビーには受付がいる。編集者アーティはまだ姿を見せていない。"
                        "受付で用件を伝えて呼び出してもらう流れを描写し、最初からアーティと対面させないこと。"
                    )
            prompt += f"""
【最重要: 場所移動（システム確定済み）】
システム上、探索者は既に「{loc_name}」に到着しています。このターンでは**到着した場所の情景描写のみ**を行ってください。
・新しい場所: {loc_name}
・基本描写: {loc_desc}
・目につく物: {obj_list}{arrival_extra}
「歩いて向かった」「進み出した」など移動過程の代行描写は禁止です。到着後の静態描写を行い、「どうしますか？」と問いかけてください。
"""
    else:
        objects = location_info.get("objects", {})
        obj_list = "、".join(
            f"{v.get('name', k)} (`{k}`)" for k, v in objects.items()
        ) if objects else "特になし"
        prompt += f"""
指示: シナリオ開始時の情景描写として、system_narration で場所の基本描写をPLに伝えてください。
部屋にある調査対象（{obj_list}）を**偏りなく**描写し、
一覧に無い物体（他シナリオの鉄格子・隠し引き出し等）は絶対に追加しないでください。
空オブジェクトを「手がかりがある」ように見せないこと。
「どうしますか？」と尋ねてください。
"""

    return prompt


def append_kp_response_to_logs(kp_data, current_loc, all_events_log):
    """正規化済み KP 応答を IC/OOC ログに振り分けて追記する。追記したら True。"""
    if not kp_data.get("should_speak", True):
        return False

    text = kp_data.get("text", "").strip()
    if not text:
        return False

    if kp_data.get("speak_mode") == "player_kp_chat":
        all_events_log.append(
            {"channel": "OOC", "location": "all", "secret_to": None, "text": f"KP(プレイヤー層): {text}"}
        )
    else:
        all_events_log.append(
            {"channel": "IC", "location": current_loc, "secret_to": None, "text": f"KP: {text}"}
        )
    return True


def ensure_handout_in_kp_ic(kp_data, confirmed_fact, obj_name=""):
    """KP IC 本文に資料テキストが無ければ末尾へ原文を挿入する。"""
    fact = str(confirmed_fact or "").strip()
    if not fact:
        return kp_data
    kp_data = dict(kp_data or {})
    text = str(kp_data.get("text") or "")
    if fact_already_in_text(text, fact):
        return kp_data
    block = format_handout_ic_block(fact, obj_name)
    kp_data["text"] = (text.rstrip() + "\n\n" + block).strip() if text else block
    return kp_data


def _inject_handout_into_kp_data(kp_data, scenario_mgr, action=None, result=None, current_loc=""):
    """調査成功時、シナリオ正本の資料本文を KP IC へ確実に載せる。"""
    result = result or {}
    action = action or {}
    fact = str(
        result.get("handout_text")
        or result.get("confirmed_fact")
        or ""
    ).strip()
    if not fact:
        log = str(result.get("log") or result.get("system_log") or "")
        if "【確定手がかり】" in log:
            fact = log.split("【確定手がかり】", 1)[-1].strip()
    if not fact or not scenario_mgr:
        return kp_data
    target = str(result.get("target") or action.get("target") or "").strip()
    obj = scenario_mgr.get_object_info(current_loc or getattr(scenario_mgr, "location", ""), target) or {}
    if not should_emit_handout_ic(obj, fact):
        # 対象不明でも confirmed_fact / handout_text があれば資料として載せる
        if not result.get("handout_text") and not result.get("handout_ic_block"):
            return kp_data
    name = obj.get("name") or target
    kp_data = ensure_handout_in_kp_ic(kp_data, fact, name)
    if str(kp_data.get("text") or "").strip():
        kp_data["should_speak"] = True
    return kp_data


def _is_duplicate_validation_error_log(all_events_log, *, error_code="", pc_id=None, message=""):
    """直近ログに同一 validation_error があれば重複出力を抑止する。"""
    code = str(error_code or "").strip()
    msg = str(message or "").strip()
    pid = str(pc_id or "").strip()
    for entry in reversed(list(all_events_log or [])[-8:]):
        meta = (entry or {}).get("meta") or {}
        if not meta.get("validation_error"):
            continue
        if code and str(meta.get("error_code") or "") != code:
            continue
        if pid and str(meta.get("pc_id") or "") not in ("", pid):
            continue
        text = str((entry or {}).get("text") or "")
        if msg and msg not in text and text not in msg:
            # コード一致なら同一拒否とみなす
            if not code:
                continue
        return True
    return False


def _find_recent_settled_event_transaction_id(
    all_events_log, *, event_kind="", error_code="", pc_id=None,
):
    """直近の確定イベント（検証拒否等）から transaction_id を回収する。"""
    kind = str(event_kind or "").strip()
    code = str(error_code or "").strip()
    pid = str(pc_id or "").strip()
    for entry in reversed(list(all_events_log or [])[-12:]):
        meta = (entry or {}).get("meta") or {}
        tid = str(meta.get("transaction_id") or "").strip()
        if not tid:
            continue
        if kind == "validation_reject":
            if not meta.get("validation_error"):
                continue
        elif kind and str(meta.get("settled_event_kind") or "") not in ("", kind):
            continue
        if code and str(meta.get("error_code") or "") not in ("", code):
            continue
        if pid and str(meta.get("pc_id") or "") not in ("", pid):
            continue
        return tid
    return ""


def _should_preserve_social_intent_from_move_autocorrect(pc_action, suggested_fix):
    """明確な会話・交渉意図や方針発言を move/search へ黙って置換しない。"""
    original = (pc_action or {}).get("original_action") or (pc_action or {})
    orig_action = str(original.get("action") or "").lower()
    orig_skill = str(original.get("skill") or "")
    suggested_action = str((suggested_fix or {}).get("action") or "").lower()
    if not is_social_action(orig_action, orig_skill):
        # 方針発言・曖昧移動も move/search へ自動補正しない
        player_intent = (pc_action or {}).get("player_intent") or {}
        if player_intent.get("intent_type") in (INTENT_DISCUSSION_OR_PLAN, INTENT_UNCLEAR):
            return suggested_action in ("move", "search", "inspect")
        if (pc_action or {}).get("intent_non_execute"):
            return suggested_action in ("move", "search", "inspect")
        # talk を move/wait へは禁止（呼び出し側で suggested が move のとき）
        if orig_action in ("talk", "speak") and suggested_action == "move":
            return True
        return False
    return suggested_action == "move"


def _build_auto_correction_action(
    pc_action, suggested_fix, scenario_mgr, current_loc, char_mgr=None,
):
    """validation_error から推奨修正を自動適用した action を生成する。"""
    if _should_preserve_social_intent_from_move_autocorrect(pc_action, suggested_fix):
        return None
    # 方針発言は自動補正で実行しない
    if (pc_action or {}).get("intent_non_execute"):
        return None
    fixed = normalize_pc_action(
        {
            "action": suggested_fix.get("action") or "move",
            "target": suggested_fix.get("target") or "",
            "skill": suggested_fix.get("skill") or "",
            "dialogue": "",
            "message": "",
        },
        scenario_mgr,
        current_loc,
        char_mgr=char_mgr,
    )
    action, target = fixed.get("action"), fixed.get("target")
    if not target:
        return None
    orig_blob = (pc_action or {}).get("original_action") or (pc_action or {})
    orig_was_move = str(orig_blob.get("action") or "").lower() == "move"
    if action == "move":
        # talk→move は禁止済み。move→move の目的地修正は許可。
        # それ以外から move を新規に作る場合は明示ゲートを通す。
        if not orig_was_move:
            player_intent = (pc_action or {}).get("player_intent") or {}
            if not can_auto_execute_move(
                {
                    **player_intent,
                    "intent_type": INTENT_ACTION_REQUEST,
                    "action": "move",
                    "explicitness": player_intent.get("explicitness") or "explicit",
                    "evidence": player_intent.get("evidence") or ["auto_correct"],
                    "target_text": target,
                },
                scenario_mgr=scenario_mgr,
                current_loc=current_loc,
                target=target,
            ).get("ok"):
                return None
        if target == current_loc or target not in {e["id"] for e in scenario_mgr.get_available_exits(current_loc)}:
            return None
    elif is_social_action(action, fixed.get("skill", "")):
        if not scenario_mgr.is_npc_at_location(target, current_loc, char_mgr=char_mgr):
            return None
        if char_mgr and not npc_is_available(char_mgr, target, scenario_mgr.flags):
            return None
        if is_stale_nonprogress_talk(action, target, scenario_mgr, current_loc, char_mgr):
            return None
    elif action in ("search", "inspect"):
        obj = scenario_mgr.get_object_info(current_loc, target)
        if not obj or not object_is_currently_available(obj, scenario_mgr.flags):
            return None
        if object_is_investigated(scenario_mgr, target, obj, scenario_mgr.flags):
            return None
        if rewrite_human_investigation_to_talk(action, target, char_mgr, scenario_mgr, current_loc):
            return None
    guard = scenario_mgr.evaluate_pre_action_guard(action, target, loc_id=current_loc) or {}
    if guard.get("blocked"):
        return None
    fixed["message"] = _build_pc_display_message("", fixed.get("action"), fixed.get("target"), scenario_mgr=scenario_mgr, current_loc=current_loc)
    fixed["original_action"] = pc_action.get("original_action") or dict(pc_action)
    original = fixed["original_action"]
    reason = str(
        pc_action.get("validation_error_code")
        or pc_action.get("validation_error")
        or "validation"
    )
    player_intent = (pc_action or {}).get("player_intent") or {}
    correction_meta = _build_system_correction_payload(
        original_intent_type=player_intent.get("intent_type") or "",
        original_action=original.get("action"),
        original_target=original.get("target"),
        correction_reason=reason,
        corrected_action=fixed.get("action"),
        corrected_target=fixed.get("target"),
        requires_confirmation=False,
    )
    fixed["system_correction_meta"] = correction_meta
    fixed["system_correction_log"] = (
        "【アクション自動補正】"
        f"元の意図: `{original.get('action')}` / `{original.get('target')}`。"
        f"理由: {reason}。"
        f"補正後: `{fixed.get('action')}` / `{fixed.get('target')}`。"
    )
    fixed["auto_corrected"] = True
    fixed["intent_replaced"] = (
        (original.get("action"), original.get("target")) != (action, target)
    )
    if fixed["intent_replaced"] or fixed["auto_corrected"]:
        fixed["forced_progress"] = True
    if pc_action.get("player_intent"):
        fixed["player_intent"] = pc_action.get("player_intent")
    return fixed


def apply_pl_response_to_logs(
    ai_data, char_name, current_loc, all_events_log,
    pending_san_check=None, scenario_mgr=None,
    pc_id=None, char_mgr=None,
    force_ic_action=False,
    pending_push_roll=None,
):
    """正規化済み PL 応答を IC/OOC ログに振り分けて追記する。"""
    san_locked = _is_san_check_pending(pending_san_check)
    speak_as = ai_data.get("speak_as", "PC")
    should_speak = ai_data.get("should_speak", True)
    pl_ooc = ai_data.get("pl_ooc_chat", "")
    pc_action = dict(ai_data.get("pc_action", {}))
    pc_id = pc_id or None
    pl_prefix = format_pc_log_prefix(char_mgr, pc_id, role="PL") if pc_id and char_mgr else f"{char_name}(PL)"
    pc_prefix = format_pc_log_prefix(char_mgr, pc_id, role="PC") if pc_id and char_mgr else f"{char_name}(PC)"

    # 強制 IC フェーズ: OOC を物理ブロックし、speak_as=PL のみを禁止
    if force_ic_action and not san_locked:
        pl_ooc = ""
        if speak_as == "PL":
            speak_as = "PC"
        should_speak = True

    # 明確な人物取り違え（自己紹介の誤り等）→ IC確定前に拒否
    if not san_locked and char_mgr and pc_id and speak_as in ("PC", "BOTH"):
        identity = resolve_active_pc_identity(
            char_mgr, pc_id, char_name=char_name,
            active_pcs=getattr(char_mgr, "active_pc_list", None),
        )
        violation = detect_pl_identity_violation(
            pc_action.get("dialogue") or pc_action.get("message") or "",
            self_pc_id=pc_id,
            self_name=identity["name"],
            self_occupation=identity["occupation"],
            other_profiles=identity["others"],
        )
        if violation:
            pc_action = {
                **pc_action,
                "action": "wait",
                "target": "",
                "skill": "",
                "dialogue": "",
                "message": "（人物設定の取り違えのため再選択）",
                "validation_error": violation.get("error") or PL_IDENTITY_MISMATCH_ERROR,
                "validation_error_code": violation.get("error_code") or PL_IDENTITY_MISMATCH_CODE,
                "needs_pl_retry": True,
                "identity_violation_reason": violation.get("reason"),
                "original_action": dict(ai_data.get("pc_action") or {}),
            }
            reject_tid = ensure_settled_nonprogress_event_id(
                pc_action, event_kind="validation_reject",
            )
            if not _is_duplicate_validation_error_log(
                all_events_log,
                error_code=pc_action["validation_error_code"],
                pc_id=pc_id,
                message=pc_action["validation_error"],
            ):
                all_events_log.append({
                    "channel": "OOC",
                    "location": "all",
                    "secret_to": None,
                    "text": f"[システム] {pc_action['validation_error']}",
                    "meta": stamp_event_transaction_on_log_meta(
                        {
                            "validation_error": True,
                            "error_code": pc_action["validation_error_code"],
                            "pc_id": pc_id,
                            "identity_violation": True,
                        },
                        reject_tid,
                        event_kind="validation_reject",
                        pc_id=pc_id,
                    ),
                })
            return pc_action

    if san_locked:
        pc_action = _enforce_san_lock_pc_action(pc_action, pl_ooc)
    elif scenario_mgr:
        intent_ctx = build_player_intent_context(
            all_events_log,
            scenario_mgr,
            current_loc,
            char_mgr,
            phase=str(getattr(scenario_mgr, "current_phase", "") or ""),
            last_action=pc_action,
        )
        pc_action = reconcile_pl_action(
            pc_action, speak_as, pl_ooc, scenario_mgr, current_loc,
            pending_san_check=pending_san_check,
            char_mgr=char_mgr,
            intent_context=intent_ctx,
            pending_push_roll=pending_push_roll,
        )
        # 方針発言・曖昧移動: 実行せずヒント／解釈ログのみ
        if pc_action.get("intent_non_execute"):
            settled_tid = ensure_settled_nonprogress_event_id(
                pc_action, event_kind="ooc_chat",
            )
            if pc_action.get("ambiguous_move_log"):
                amb_text = f"[システム] {pc_action['ambiguous_move_log']}"
                if not any(e.get("text") == amb_text for e in all_events_log[-6:]):
                    all_events_log.append({
                        "channel": "OOC",
                        "location": "all",
                        "secret_to": None,
                        "text": amb_text,
                        "meta": stamp_event_transaction_on_log_meta({
                            "intent_interpretation": True,
                            "ambiguous_move": True,
                            "pc_id": pc_id,
                            "player_intent": pc_action.get("player_intent"),
                        }, settled_tid, event_kind="ooc_chat", pc_id=pc_id),
                    })
            hint = str(pc_action.get("post_action_hint") or "").strip()
            if hint:
                hint_text = hint if hint.startswith("[システム]") or hint.startswith("【") else f"[システム] {hint}"
                if not any(e.get("text") == hint_text for e in all_events_log[-6:]):
                    all_events_log.append({
                        "channel": "OOC",
                        "location": "all",
                        "secret_to": None,
                        "text": hint_text,
                        "meta": stamp_event_transaction_on_log_meta({
                            "intent_non_execute": True,
                            "pc_id": pc_id,
                            "player_intent": pc_action.get("player_intent"),
                        }, settled_tid, event_kind="ooc_chat", pc_id=pc_id),
                    })
            if pl_ooc and speak_as in ("PL", "BOTH") and not force_ic_action:
                all_events_log.append({
                    "channel": "OOC",
                    "location": "all",
                    "secret_to": None,
                    "text": f"{pl_prefix}: {pl_ooc}",
                    "meta": stamp_event_transaction_on_log_meta(
                        {"pc_id": pc_id} if pc_id else {},
                        settled_tid, event_kind="ooc_chat", pc_id=pc_id,
                    ),
                })
            return pc_action
        # 同一内容の礼・挨拶の重複 talk を抑制（明示的な追加質問は許可）
        if (
            not pc_action.get("needs_pl_retry")
            and is_social_action(pc_action.get("action"), pc_action.get("skill", ""))
            and pc_action.get("target")
        ):
            dlg = str(pc_action.get("dialogue") or pc_action.get("message") or "")
            player_intent = pc_action.get("player_intent") or {}
            is_courtesy = (
                player_intent.get("intent_type") == INTENT_IN_CHARACTER_DIALOGUE
                or is_courtesy_dialogue_text(dlg)
            )
            new_question = any(
                m in dlg for m in ("聞く", "尋ね", "質問", "教えて", "どこ", "何", "なぜ", "どう")
            )
            if is_courtesy and not new_question and is_duplicate_npc_dialogue(
                dlg, pc_action.get("target"), all_events_log, pc_id=pc_id or "",
            ):
                pc_action = {
                    **pc_action,
                    "action": "wait",
                    "target": "",
                    "skill": "",
                    "message": "（同じ挨拶を繰り返すのは控える）",
                    "dialogue": "",
                    "post_action_hint": (
                        "同じ内容の礼・挨拶は既に伝えています。"
                        "追加の質問や別の技能での交渉を明示してください。"
                    ),
                    "duplicate_dialogue_suppressed": True,
                }
        # 移動意図不一致・完了済みKnott対話・グローブ停滞 talk など → 再選択を促す
        knott_check = validate_completed_knott_talk(
            pc_action,
            scenario_mgr=scenario_mgr,
            current_loc=current_loc,
            char_mgr=char_mgr,
        )
        if knott_check.get("preserve_social_intent"):
            if knott_check.get("next_location_hint"):
                pc_action["post_action_hint"] = knott_check.get("next_location_hint")
            if knott_check.get("suggested_fix"):
                pc_action["suggested_fix"] = knott_check.get("suggested_fix")
        elif not knott_check.get("ok") and not pc_action.get("needs_pl_retry"):
            pc_action = {
                **pc_action,
                "action": "wait",
                "target": "",
                "skill": "",
                "validation_error": knott_check.get("error"),
                "validation_error_code": knott_check.get("error_code"),
                "suggested_fix": knott_check.get("suggested_fix"),
                "needs_pl_retry": True,
            }
        if not pc_action.get("needs_pl_retry"):
            dolly_check = validate_completed_dolly_talk(
                pc_action,
                scenario_mgr=scenario_mgr,
                current_loc=current_loc,
                char_mgr=char_mgr,
            )
            if dolly_check.get("preserve_social_intent"):
                if dolly_check.get("next_location_hint"):
                    pc_action["post_action_hint"] = dolly_check.get("next_location_hint")
                if dolly_check.get("suggested_fix"):
                    pc_action["suggested_fix"] = dolly_check.get("suggested_fix")
            elif not dolly_check.get("ok"):
                pc_action = {
                    **pc_action,
                    "action": "wait",
                    "target": "",
                    "skill": "",
                    "validation_error": dolly_check.get("error"),
                    "validation_error_code": dolly_check.get("error_code"),
                    "suggested_fix": dolly_check.get("suggested_fix"),
                    "needs_pl_retry": True,
                }
        if not pc_action.get("needs_pl_retry"):
            globe_stale = _validate_stale_boston_globe_talk(
                pc_action,
                scenario_mgr=scenario_mgr,
                current_loc=current_loc,
                char_mgr=char_mgr,
            )
            if globe_stale.get("preserve_social_intent"):
                if globe_stale.get("next_location_hint"):
                    pc_action["post_action_hint"] = globe_stale.get("next_location_hint")
                if globe_stale.get("suggested_fix"):
                    pc_action["suggested_fix"] = globe_stale.get("suggested_fix")
            elif not globe_stale.get("ok"):
                pc_action = {
                    **pc_action,
                    "action": "wait",
                    "target": "",
                    "skill": "",
                    "validation_error": globe_stale.get("error"),
                    "validation_error_code": globe_stale.get("error_code"),
                    "suggested_fix": globe_stale.get("suggested_fix"),
                    "needs_pl_retry": True,
                }
        # 強制 IC: wait / 無駄 talk をバリデーションエラーとして拒絶
        if force_ic_action and not pc_action.get("needs_pl_retry"):
            force_check = validate_force_ic_action(
                pc_action,
                force_ic_action=True,
                scenario_mgr=scenario_mgr,
                current_loc=current_loc,
                char_mgr=char_mgr,
            )
            if not force_check.get("ok"):
                pc_action = {
                    **pc_action,
                    "action": "wait",
                    "target": "",
                    "skill": "",
                    "validation_error": force_check.get("error"),
                    "validation_error_code": force_check.get("error_code"),
                    "suggested_fix": force_check.get("suggested_fix"),
                    "needs_pl_retry": True,
                }
        # 移動意図不一致など → ログにエラーを残し、システム行動は起こさない
        if pc_action.get("needs_pl_retry") or pc_action.get("validation_error"):
            err = pc_action.get("validation_error") or MOVE_INTENT_MISMATCH_ERROR
            err_code = str(pc_action.get("validation_error_code") or "")
            pc_action.setdefault("original_action", dict(ai_data.get("pc_action") or {}))
            suggested_fix = pc_action.get("suggested_fix") or {}
            # 実行可能と確認できた推奨修正だけを適用する。
            fixed_action = None
            if (
                err_code in VALIDATION_AUTO_CORRECT_CODES
                and suggested_fix
                and suggested_fix.get("target")
                and not san_locked
                and scenario_mgr
            ):
                fixed_action = _build_auto_correction_action(
                    pc_action, suggested_fix, scenario_mgr, current_loc, char_mgr=char_mgr,
                )
            if fixed_action:
                pc_action = fixed_action
            else:
                # 検証拒否イベント確定: 新規記録時のみ ID 発行、既存は保持
                reject_tid = ensure_settled_nonprogress_event_id(
                    pc_action, event_kind="validation_reject",
                )
                if not _is_duplicate_validation_error_log(
                    all_events_log, error_code=err_code, pc_id=pc_id, message=err,
                ):
                    all_events_log.append({
                        "channel": "OOC",
                        "location": "all",
                        "secret_to": None,
                        "text": f"[システム] {err}",
                        "meta": stamp_event_transaction_on_log_meta(
                            {
                                "validation_error": True,
                                "error_code": err_code,
                                "pc_id": pc_id,
                            },
                            reject_tid,
                            event_kind="validation_reject",
                            pc_id=pc_id,
                        ),
                    })
                # 強制 IC 中は拒否時も OOC を残さない
                if pl_ooc and speak_as in ("PL", "BOTH") and not force_ic_action:
                    all_events_log.append({
                        "channel": "OOC",
                        "location": "all",
                        "secret_to": None,
                        "text": f"{pl_prefix}: {pl_ooc}",
                        "meta": stamp_event_transaction_on_log_meta(
                            {"pc_id": pc_id} if pc_id else {},
                            reject_tid,
                            event_kind="validation_reject",
                            pc_id=pc_id,
                        ),
                    })
                return pc_action
        if speak_as != "PL" and _texts_overlap(pl_ooc, pc_action.get("dialogue", "")):
            pc_action["dialogue"] = ""
            pc_action["message"] = _build_pc_display_message(
                "", pc_action.get("action", "wait"), pc_action.get("target", ""),
                scenario_mgr=scenario_mgr, current_loc=current_loc,
            )

    if should_speak and pl_ooc and speak_as in ("PL", "BOTH") and not force_ic_action:
        ooc_tid = ensure_settled_nonprogress_event_id(pc_action, event_kind="ooc_chat")
        all_events_log.append({
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": f"{pl_prefix}: {pl_ooc}",
            "meta": stamp_event_transaction_on_log_meta(
                {"pc_id": pc_id} if pc_id else {},
                ooc_tid,
                event_kind="ooc_chat",
                pc_id=pc_id,
            ),
        })

    log_pc = (
        should_speak
        and speak_as in ("PC", "BOTH")
        and (san_locked or speak_as == "PC" or pc_action.get("action", "wait") not in ("wait", "", "none"))
    )
    # 実行可能な canonical action は表示抑制の指定があっても SYSTEM に渡す。
    action_name = str(pc_action.get("action", "wait") or "wait").lower()
    if not san_locked and action_name in ACTIONS_NEEDING_SYSTEM:
        log_pc = True
    # 強制 IC: wait 以外なら必ず IC ログを出す（BOTH で dialogue 空でも action があれば）
    if force_ic_action and not san_locked:
        action_name = str(pc_action.get("action", "wait") or "wait").lower()
        if action_name in ACTIONS_NEEDING_SYSTEM:
            log_pc = True
            speak_as = "PC" if speak_as == "PL" else speak_as
    if log_pc:
        action_msg = pc_action.get("message") or _build_pc_display_message(
            pc_action.get("dialogue", ""),
            pc_action.get("action", "wait"),
            pc_action.get("target", ""),
            action_locked=san_locked,
            scenario_mgr=scenario_mgr,
            current_loc=current_loc,
        )
        action_name = str(pc_action.get("action", "wait") or "wait").lower()
        needs_system = (
            not san_locked
            and action_name in ACTIONS_NEEDING_SYSTEM
        )
        txn_id = (
            str(pc_action.get("transaction_id") or "").strip()
            or new_action_transaction_id()
        )
        all_events_log.append({
            "channel": "IC",
            "location": current_loc,
            "secret_to": None,
            "text": f"{pc_prefix}: {action_msg}",
            "meta": {
                "pc_id": pc_id,
                "action_id": action_name,
                "target": pc_action.get("target", ""),
                "skill": pc_action.get("skill", ""),
                "skill_proposal_reason": pc_action.get("skill_proposal_reason", ""),
                "needs_system": needs_system,
                "system_processed": False,
                "transaction_id": txn_id,
                "actor_id": pc_id,
                "decision_owner_id": pc_id,
                "action_origin": AUTONOMOUS,
                **({"original_action": pc_action["original_action"]} if pc_action.get("original_action") else {}),
                "intent_replaced": bool(pc_action.get("intent_replaced")),
                "forced_progress": bool(
                    pc_action.get("forced_progress")
                    or pc_action.get("intent_replaced")
                    or pc_action.get("auto_corrected")
                ),
                "auto_corrected": bool(pc_action.get("auto_corrected")),
            },
        })
        pc_action["transaction_id"] = txn_id
        pc_action["actor_id"] = pc_id
        pc_action["decision_owner_id"] = pc_id
        pc_action["action_origin"] = AUTONOMOUS

    correction_text = f"[システム] {pc_action.get('system_correction_log', '')}"
    txn_id = str(pc_action.get("transaction_id") or "").strip()
    correction_already_logged = any(
        e.get("text") == correction_text
        and (e.get("meta") or {}).get("pc_id") == pc_id
        and (
            not txn_id
            or str((e.get("meta") or {}).get("transaction_id") or "") in ("", txn_id)
        )
        for e in all_events_log[-8:]
    )
    if pc_action.get("system_correction_log") and not correction_already_logged:
        all_events_log.append({
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": f"[システム] {pc_action['system_correction_log']}",
            "meta": {
                "system_correction": True,
                "pc_id": pc_id,
                "transaction_id": txn_id or None,
                "intent_replaced": bool(pc_action.get("intent_replaced")),
                "forced_progress": bool(
                    pc_action.get("forced_progress")
                    or pc_action.get("intent_replaced")
                    or pc_action.get("auto_corrected")
                ),
                "original_action": pc_action.get("original_action"),
                "action": pc_action.get("action"),
                "target": pc_action.get("target"),
                **(pc_action.get("system_correction_meta") or {}),
            },
        })

    hint = str(pc_action.get("post_action_hint") or "").strip()
    if hint:
        hint_text = hint if hint.startswith("[システム]") or hint.startswith("【") else f"[システム] {hint}"
        if not any(e.get("text") == hint_text for e in all_events_log[-6:]):
            all_events_log.append({
                "channel": "OOC",
                "location": "all",
                "secret_to": None,
                "text": hint_text,
                "meta": {
                    "post_action_hint": True,
                    "nonprogress_social": bool(pc_action.get("nonprogress_social")),
                    "pc_id": pc_id,
                    "suggested_fix": pc_action.get("suggested_fix"),
                },
            })

    return pc_action

# ==========================================
# 4. API 呼び出し（ローカル LLM / OpenAI 互換）
# ==========================================
def call_pl_api(
    prompt, max_retries=3, json_schema=PL_ACTION_JSON_SCHEMA,
    action_locked=False, san_source=None,
    active_pc_id=None, char_mgr=None, discussion_mode=False,
):
    """PL用のローカル LLM 呼び出し（最大3回まで自動再試行）。"""
    cfg = get_llm_config()
    finalized_prompt = _finalize_pl_prompt_for_json(prompt, json_schema)
    sheet_block = ""
    if char_mgr and active_pc_id:
        sheet_block = char_mgr.build_character_sheet_summary(active_pc_id)
        if sheet_block:
            sheet_block = sheet_block + "\n\n"
        identity = _build_pl_identity_directive(
            char_mgr=char_mgr,
            pl_id=active_pc_id,
            active_pcs=getattr(char_mgr, "active_pc_list", None),
        )
        if identity:
            sheet_block = identity + "\n" + sheet_block
    system_extra = ""
    if discussion_mode:
        system_extra = (
            " 現在は作戦会議（OOC相談）フェーズです。"
            "ダイスを要する行動コマンドは出力せず、pl_ooc_chat のみで相談してください。"
            "action は wait に固定してください。"
        )
    elif action_locked:
        if san_source == SAN_SOURCE_DOOR_FORCE:
            system_extra = (
                " 現在SANチェック保留中（力ずく開扉の衝撃）のため、"
                "行動コマンドは出力せずロールプレイのみ行ってください。"
            )
        elif san_source == SAN_SOURCE_COSMIC_HORROR:
            system_extra = (
                " 現在SANチェック保留中（宇宙の恐怖・偶像直視の衝撃）のため、"
                "行動コマンドは出力せずロールプレイのみ行ってください。"
            )
        elif san_source == SAN_SOURCE_SIGIL:
            system_extra = (
                " 現在SANチェック保留中（紋章目撃の衝撃）のため、"
                "行動コマンドは出力せずロールプレイのみ行ってください。"
            )
        else:
            system_extra = " 現在SANチェック保留中のため、行動コマンドは出力せずロールプレイのみ行ってください。"
    mindset_block = ""
    if (
        not discussion_mode
        and not action_locked
        and json_schema == PL_ACTION_JSON_SCHEMA
    ):
        mindset_block = _build_pl_explorer_mindset_directive() + "\n\n"
    messages = [
        {
            "role": "system",
            "content": (
                sheet_block
                + mindset_block
                + "あなたはクトゥルフ神話TRPGのプレイヤーAIです。"
                "必ず有効な JSON オブジェクトのみを出力してください。"
                + system_extra
            ),
        },
        {"role": "user", "content": finalized_prompt},
    ]

    try:
        response_text = _call_chat_completion(
            messages,
            model=cfg["pl_model"],
            temperature=0.7,
            max_retries=max_retries,
            json_mode=True,
            role="PL",
            purpose=(
                "luck_decision" if json_schema == PL_LUCK_JSON_SCHEMA else
                "push_decision" if json_schema == PL_PUSH_JSON_SCHEMA else
                "combat_defense" if json_schema in {
                    PL_COMBAT_DEFENSE_JSON_SCHEMA, PL_SHOOT_DEFENSE_JSON_SCHEMA,
                } else "action_selection"
            ),
        )
        ai_data = json.loads(_extract_json_object(response_text))
        if json_schema == PL_LUCK_JSON_SCHEMA:
            return parse_pl_luck_response(ai_data)
        if json_schema == PL_PUSH_JSON_SCHEMA:
            return parse_pl_push_response(ai_data)
        if json_schema == PL_COMBAT_DEFENSE_JSON_SCHEMA:
            return parse_pl_combat_defense_response(ai_data)
        if json_schema == PL_SHOOT_DEFENSE_JSON_SCHEMA:
            return parse_pl_shoot_defense_response(ai_data)
        return parse_pl_response(ai_data, action_locked=action_locked)
    except json.JSONDecodeError as exc:
        print(f"\n[PL API JSONパースエラー] {exc}")
        failure = LlmCommunicationError(
            LLM_PAUSE_INVALID_RESPONSE, str(exc), attempts=max_retries, cause=exc,
        )
    except Exception as exc:
        print(f"\n[PL API 最終エラー] {exc}")
        failure = LlmCommunicationError(
            classify_llm_failure(exc), str(exc), attempts=max_retries, cause=exc,
        )

    print("\n[PL] リトライ上限に達しました。ダミーアクションを返します。")
    if json_schema == PL_LUCK_JSON_SCHEMA:
        dummy = default_pl_luck_response()
    elif json_schema == PL_PUSH_JSON_SCHEMA:
        dummy = default_pl_push_response()
    elif json_schema == PL_COMBAT_DEFENSE_JSON_SCHEMA:
        dummy = default_pl_combat_defense_response()
    elif json_schema == PL_SHOOT_DEFENSE_JSON_SCHEMA:
        dummy = default_pl_shoot_defense_response()
    else:
        dummy = default_pl_action_response()
    dummy["_llm_failure"] = failure.to_meta()
    return dummy


class KpNarrationError(RuntimeError):
    """KPナレーション生成が確定できなかった（ゲーム状態は変更しない／再試行可）。"""


def call_kp_api(prompt, max_retries=3, fallback_text="", *, allow_fallback=True):
    """KP用のローカル LLM 呼び出し（JSON 多層意識スキーマ）。

    allow_fallback=False かつ全滅時は KpNarrationError を送出し、
    呼び出し側が kp_narrated を立てずに再試行できるようにする。
    """
    cfg = get_llm_config()
    finalized_prompt = _finalize_pl_prompt_for_json(prompt, KP_JSON_SCHEMA)
    messages = [
        {
            "role": "system",
            "content": (
                "あなたはクトゥルフ神話TRPGのKP AIです。"
                "システムKPとプレイヤーKPの二重意識を持ち、必ず有効な JSON オブジェクトのみを出力してください。"
                "text は途中で切らず、情景描写を完結させてから JSON を閉じること。"
            ),
        },
        {"role": "user", "content": finalized_prompt},
    ]

    last_raw = ""
    for attempt in range(max_retries):
        try:
            last_raw = _call_chat_completion(
                messages,
                model=cfg["kp_model"],
                temperature=0.8,
                max_retries=1,
                json_mode=True,
                role="KP",
                purpose="narration",
                retry_count_base=attempt,
            )
            data = _loads_json_lenient(last_raw)
            if data is None:
                recovered = _recover_text_field_from_partial_json(last_raw)
                if recovered.strip():
                    print(f"\n[KP] 途切れ JSON から text を復旧（試行 {attempt + 1}）")
                    return parse_kp_response({
                        "should_speak": True,
                        "speak_mode": "system_narration",
                        "text": recovered,
                    })
                raise json.JSONDecodeError("KP JSON を解釈できません", last_raw, 0)
            parsed = parse_kp_response(data)
            if parsed.get("should_speak") and not str(parsed.get("text") or "").strip():
                recovered = _recover_text_field_from_partial_json(last_raw)
                if recovered.strip():
                    parsed["text"] = recovered
            return parsed
        except json.JSONDecodeError as exc:
            print(f"\n[KP API JSONパースエラー - 試行 {attempt + 1}/{max_retries}] {exc}")
        except Exception as exc:
            print(f"\n[KP API エラー - 試行 {attempt + 1}/{max_retries}] {exc}")
            if _is_model_not_found_error(exc):
                break

    recovered = _recover_text_field_from_partial_json(last_raw)
    if recovered.strip():
        print("\n[KP] リトライ後も JSON 不完全のため、復旧した text を使用します。")
        return parse_kp_response({
            "should_speak": True,
            "speak_mode": "system_narration",
            "text": recovered,
        })

    if allow_fallback:
        print("\n[KP] リトライ上限に達しました。システム確定情報で描写を補います。")
        return default_kp_response(fallback_text=fallback_text)

    print("\n[KP] リトライ上限に達しました。描写未確定のまま再試行可能に残します。")
    raise KpNarrationError("KPナレーション生成に失敗しました（状態は未変更・再試行可）")

# ==========================================
# 5. システム（裏方）処理 (main.py)
# ==========================================
def _build_push_roll_state(
    target, skill_name, action_id, skill_modifier, skill_bonus, skill_penalty,
    required_difficulty="regular",
    *,
    failed_success_level=None,
    allow_push=True,
    decision_pending=True,
):
    state = {
        "target": target,
        "skill_name": skill_name,
        "original_action": action_id,
        "modifier": skill_modifier,
        "bonus_dice": skill_bonus,
        "penalty_dice": skill_penalty,
        "required_difficulty": normalize_difficulty(required_difficulty),
        "decision_pending": bool(decision_pending),
        "allow_push": bool(allow_push),
    }
    if failed_success_level is not None:
        state["failed_success_level"] = int(failed_success_level)
    return state


def _skill_allows_push(skill_name, action_id=None, *, in_combat=False, already_pushed=False, roll_type=""):
    """7版に従い、プッシュ不可のロールをガードする（CoCRules 委譲）。"""
    return is_push_allowed(
        skill_name=skill_name,
        action_id=action_id,
        in_combat=in_combat,
        already_pushed=already_pushed,
        roll_type=roll_type,
    )


def _handle_skill_roll_failure(
    dice_result, char_mgr, pl_id, target, skill_name, action_id,
    skill_modifier, skill_bonus, skill_penalty,
    required_difficulty="regular",
    *,
    fail_level=None,
    allow_push=True,
    roll_type="skill",
):
    """
    技能ロール失敗時の分岐。
    CoCRules で legal_options を算出し、幸運／プッシュ保留を返す。
    差分が上限以内かつ幸運可なら pending_luck_burn、
    それ以外でプッシュ可なら pending_push_roll、不可なら確定失敗。
    """
    if fail_level is None:
        fail_level = (
            int(SuccessLevel.FUMBLE)
            if dice_result.get("is_fumble")
            else int(SuccessLevel.FAILURE)
        )
    margin = dice_result.get("failure_margin")
    if margin is None:
        margin = luck_points_needed(
            dice_result.get("roll", 0),
            dice_result.get("target_value", 0),
        )
    margin = int(margin or 0)
    if margin <= 0 and not dice_result.get("is_fumble"):
        return fail_level, None, None

    is_fumble = bool(
        dice_result.get("is_fumble") or int(fail_level) == int(SuccessLevel.FUMBLE)
    )
    current_luck = 0
    if hasattr(char_mgr, "get_luck"):
        try:
            current_luck = int(char_mgr.get_luck(pl_id) or 0)
        except Exception:
            current_luck = 0

    already_pushed = str(action_id or "").lower() == "push_roll"
    options_info = build_post_roll_failure_legal_options(
        skill_name=skill_name,
        action_id=action_id,
        roll_type=roll_type,
        in_combat=False,
        already_pushed=already_pushed,
        is_fumble=is_fumble,
        margin=margin,
        current_luck=current_luck,
        max_burn=DEFAULT_LUCK_BURN_MAX,
        allow_push=allow_push,
    )
    legal_options = list(options_info.get("legal_options") or [DECISION_OPTION_ACCEPT])
    luck_cost = options_info.get("luck_cost")

    push_state = None
    if options_info.get("push_allowed"):
        push_state = _build_push_roll_state(
            target, skill_name, action_id, skill_modifier, skill_bonus, skill_penalty,
            required_difficulty=required_difficulty,
            failed_success_level=fail_level,
            allow_push=True,
            decision_pending=True,
        )
        push_state["legal_options"] = [
            opt for opt in legal_options if opt != DECISION_OPTION_SPEND_LUCK
        ] or [DECISION_OPTION_ACCEPT, DECISION_OPTION_PUSH]

    if options_info.get("luck_allowed"):
        pending_luck_burn = _build_push_roll_state(
            target, skill_name, action_id, skill_modifier, skill_bonus, skill_penalty,
            required_difficulty=required_difficulty,
            failed_success_level=fail_level,
            allow_push=bool(push_state),
            decision_pending=False,
        )
        pending_luck_burn["margin"] = margin
        pending_luck_burn["roll"] = dice_result.get("roll")
        pending_luck_burn["target_value"] = dice_result.get("target_value")
        pending_luck_burn["legal_options"] = legal_options
        pending_luck_burn["luck_cost"] = luck_cost
        pending_luck_burn["is_fumble"] = is_fumble
        return fail_level, pending_luck_burn, None

    return fail_level, None, push_state


def apply_session_end_rewards(char_mgr, pl_id, pause_reason=None):
    """シナリオ終了時の技能成長ロール（クイックスタート・成功の報酬）。"""
    if pause_reason not in ("game_clear", "scenario_end"):
        return []
    results = char_mgr.apply_skill_improvement_rewards(pl_id)
    logs = []
    for item in results:
        skill = item.get("skill", "")
        if item.get("improved"):
            logs.append(
                f"【技能成長】〈{skill}〉+{item['gain']}% "
                f"（ロール{item['roll']} > 旧値 → {item['new_value']}%）"
            )
        elif skill:
            logs.append(f"【技能成長】〈{skill}〉変化なし（ロール{item['roll']}）")
    return logs


def _apply_skill_roll_outcome(
    dice_result, char_mgr, pl_id, target, skill_name, action_id,
    skill_modifier, skill_bonus, skill_penalty,
    *, in_combat=False, required_difficulty="regular", mark_success=True,
):
    """技能ロール結果から success_level と保留状態を決定する。"""
    is_fail = (
        dice_result.get("is_failure")
        or dice_result.get("is_fumble")
        or dice_result.get("result") == "失敗"
    )
    if is_fail:
        fail_level = (
            int(SuccessLevel.FUMBLE)
            if dice_result.get("is_fumble")
            else int(SuccessLevel.FAILURE)
        )
        if in_combat:
            return fail_level, None, None
        allow_push = _skill_allows_push(skill_name, action_id, in_combat=in_combat)
        return _handle_skill_roll_failure(
            dice_result, char_mgr, pl_id, target, skill_name, action_id,
            skill_modifier, skill_bonus, skill_penalty,
            required_difficulty=required_difficulty,
            fail_level=fail_level,
            allow_push=allow_push,
        )
    if skill_name and mark_success:
        char_mgr.mark_skill_success(pl_id, skill_name)
    return dice_result.get("success_level", int(SuccessLevel.REGULAR_SUCCESS)), None, None


def _sanitize_combined_system_log(dice_log, payload_log, roll_type=""):
    """ダイスログとペイロードログの矛盾（技能+STR混在等）を除去して結合する。"""
    dice_log = (dice_log or "").strip()
    payload_log = (payload_log or "").strip()

    if roll_type == "skill":
        payload_lines = [
            line for line in payload_log.split("\n")
            if "【STR対抗" not in line and "STR対抗" not in line
        ]
        payload_log = "\n".join(payload_lines).strip()
    elif roll_type == "opposed_str":
        dice_lines = [
            line for line in dice_log.split("\n")
            if "【技能" not in line and "技能:" not in line
        ]
        dice_log = "\n".join(dice_lines).strip()

    parts = [part for part in (dice_log, payload_log) if part]
    return "\n".join(parts)


def append_system_log_entry(
    all_events_log, current_loc, log_text, action_id="", target="", roll_type="",
    *, transaction_id="", actor_id="", decision_owner_id="", secret_to=None,
    knowledge_ids=None, adjudication=None, interaction_id="", cause_adjudication_id="",
):
    """システムログを IC チャンネルに1エントリとして追記する。

    secret_to: 指定時はその PC のみが get_filtered_logs で見える（Knowledge Leak 防止）。
    """
    text = (log_text or "").strip()
    if not text:
        return
    roll_markers = ("CC(1d100<=", "【SANチェック】", "【STR対抗", "【対抗ロール")
    if any(marker in text for marker in roll_markers) and not adjudication:
        from AdjudicationEvidence import EvidenceContractError
        raise EvidenceContractError(
            "Session ROLL log requires authoritative adjudication evidence"
        )
    entry = {
        "channel": "IC",
        "location": current_loc,
        "secret_to": list(secret_to) if secret_to else None,
        "text": f"システム: {text}",
    }
    meta = {"kp_narrated": False}
    if action_id:
        meta["action_id"] = action_id
    if target:
        meta["target"] = target
    if roll_type:
        meta["roll_type"] = roll_type
    if transaction_id:
        meta["transaction_id"] = transaction_id
    if actor_id:
        meta["actor_id"] = actor_id
    if decision_owner_id:
        meta["decision_owner_id"] = decision_owner_id
    if knowledge_ids:
        meta["knowledge_ids"] = list(knowledge_ids)
    if adjudication:
        for key in (
            "adjudication_id", "parent_adjudication_id", "resolution_mode",
            "skill_or_stat", "target_value", "roll", "result_level",
            "raw_result", "final_result", "automatic_result", "modifier",
            "san",
            "state_before", "state_after", "cause_event_ids", "result_event_ids",
            "trigger_event_id", "world_fact", "human_readable_description",
            "opposed_roll", "resolution_reason", "narrative_fact_tags",
            "object_state_updates", "lifecycle_relation_id", "lifecycle_actor_id",
        ):
            if key in adjudication:
                meta[key] = copy.deepcopy(adjudication.get(key))
        if str(meta.get("resolution_mode") or "").upper() == "ROLL":
            from AdjudicationEvidence import validate_evidence
            validate_evidence(meta)
            required_session_fields = {
                "actor_id": actor_id or adjudication.get("actor_id"),
                "target": target or adjudication.get("target_id"),
                "skill_or_stat": meta.get("skill_or_stat"),
            }
            missing = [
                name for name, value in required_session_fields.items()
                if value is None or (isinstance(value, str) and not value.strip())
            ]
            if missing:
                from AdjudicationEvidence import EvidenceContractError
                raise EvidenceContractError(
                    "incomplete Session ROLL evidence: " + ", ".join(missing)
                )
            meta["actor_id"] = required_session_fields["actor_id"]
            meta["target"] = required_session_fields["target"]
    if cause_adjudication_id:
        meta["cause_adjudication_id"] = cause_adjudication_id
    if interaction_id:
        meta["interaction_id"] = interaction_id
    entry["meta"] = meta
    all_events_log.append(entry)


def _build_system_action_result(
    success_level,
    sys_log,
    payload,
    action_id,
    pending_push_roll,
    madness_instruction="",
    push_fail_penalty_instruction="",
    current_loc=None,
    scenario_mgr=None,
    luck_decision_required=False,
    pending_luck_burn=None,
    roll_type="",
    action_target="",
    san_auto_resolved=False,
    push_decision_required=False,
    combat_defense_required=False,
    pending_combat_defense=None,
    pending_decision=None,
    decision_owner_id="",
):
    """シナリオ処理後の共通レスポンスを組み立てる。"""
    payload_log = payload.get("system_log", "") if payload else ""
    final_sys_log = _sanitize_combined_system_log(sys_log, payload_log, roll_type=roll_type)

    if action_id == "push_roll" and payload is None and not push_decision_required:
        kp_instruction = "プッシュロールの対象がありません。PLに通常の行動を促してください。"
    elif payload:
        kp_instruction = payload.get("kp_instruction", "PLの行動に対して、適切な情景描写と結果を返してください。")
    else:
        kp_instruction = "特筆すべき変化はありませんでした。その旨を伝えてください。"

    if push_fail_penalty_instruction:
        kp_instruction = f"{kp_instruction}\n{push_fail_penalty_instruction}"
    if madness_instruction:
        kp_instruction = f"{kp_instruction}\n{madness_instruction}"

    san_check = payload.get("san_check", {"required": False}) if payload else {"required": False}
    if san_check.get("required"):
        san_check = _enrich_san_check_metadata(
            san_check,
            action_id=action_id,
            target=action_target,
            log_text=final_sys_log,
            scenario_mgr=scenario_mgr,
        )
    new_location = None
    location_changed = False
    if scenario_mgr and current_loc is not None:
        new_location = scenario_mgr.location if scenario_mgr.location != current_loc else None
        location_changed = bool(payload and payload.get("location_changed"))

    result_status = success_level
    if payload and payload.get("blocked"):
        result_status = payload.get("status", 0)

    pending_push_roll = _coalesce_pending_push_roll(pending_push_roll, san_check)
    if push_decision_required and pending_push_roll:
        pending_push_roll = dict(pending_push_roll)
        pending_push_roll["decision_pending"] = True

    # タスク4: pending_decision を結果に添付
    if pending_decision is None:
        if combat_defense_required and pending_combat_defense:
            pending_decision = build_combat_pending_decision(
                pending_combat_defense,
                decision_owner_id=decision_owner_id or (pending_combat_defense or {}).get("defender_id") or "",
            )
        elif luck_decision_required and pending_luck_burn:
            options = list(pending_luck_burn.get("legal_options") or [])
            if not options:
                options = [DECISION_OPTION_ACCEPT, DECISION_OPTION_SPEND_LUCK]
                if pending_luck_burn.get("allow_push", True):
                    options.append(DECISION_OPTION_PUSH)
            pending_decision = build_pending_decision(
                decision_type=PENDING_DECISION_POST_ROLL_FAILURE,
                target_action_id=pending_luck_burn.get("original_action") or action_id,
                decision_owner_id=decision_owner_id,
                legal_options=options,
                luck_cost=pending_luck_burn.get("luck_cost", pending_luck_burn.get("margin")),
                meta={"skill_name": pending_luck_burn.get("skill_name"), "roll_type": roll_type},
            )
        elif push_decision_required and pending_push_roll:
            options = list(pending_push_roll.get("legal_options") or [
                DECISION_OPTION_ACCEPT, DECISION_OPTION_PUSH,
            ])
            pending_decision = build_pending_decision(
                decision_type=PENDING_DECISION_POST_ROLL_FAILURE,
                target_action_id=pending_push_roll.get("original_action") or action_id,
                decision_owner_id=decision_owner_id,
                legal_options=options,
                luck_cost=None,
                meta={"skill_name": pending_push_roll.get("skill_name"), "roll_type": roll_type},
            )

    result = {
        "status": result_status,
        "log": final_sys_log.strip(),
        "kp_instruction": kp_instruction,
        "san_check": san_check,
        "new_location": new_location,
        "location_changed": location_changed,
        "blocked": bool(payload and payload.get("blocked")),
        "pending_push_roll": pending_push_roll,
        "luck_decision_required": luck_decision_required,
        "push_decision_required": bool(push_decision_required and pending_push_roll),
        "pending_luck_burn": pending_luck_burn,
        "combat_defense_required": bool(combat_defense_required and pending_combat_defense),
        "pending_combat_defense": pending_combat_defense if combat_defense_required else None,
        "pending_decision": pending_decision,
        "roll_type": roll_type,
        "action_id": action_id,
        "target": action_target,
        "success_level": int(success_level or 0),
    }
    if payload and payload.get("stagnation_pl_hint"):
        result["stagnation_pl_hint"] = payload["stagnation_pl_hint"]
    if payload and payload.get("from_location"):
        result["from_location"] = payload["from_location"]
    if payload and payload.get("invalidate_pending_actions"):
        result["invalidate_pending_actions"] = True
        if payload.get("invalidation"):
            result["invalidation"] = payload["invalidation"]
    if payload and payload.get("confirmed_fact"):
        result["confirmed_fact"] = payload["confirmed_fact"]
        result["dice_success"] = True
    elif payload and payload.get("dice_success"):
        result["dice_success"] = True
    if payload and payload.get("knowledge_grants"):
        result["knowledge_grants"] = list(payload.get("knowledge_grants") or [])
    if payload and payload.get("handout_text"):
        result["handout_text"] = payload["handout_text"]
    if payload and payload.get("handout_ic_block"):
        result["handout_ic_block"] = payload["handout_ic_block"]
    if payload and payload.get("new_phase"):
        result["new_phase"] = payload["new_phase"]
    if payload:
        for key in (
            "trigger_event_id", "state_before", "state_after",
            "cause_event_ids", "result_event_ids", "world_fact",
            "human_readable_description",
            "resolution_reason", "narrative_fact_tags", "object_state_updates",
            "completion_phase_deferred",
        ):
            if key in payload:
                result[key] = copy.deepcopy(payload.get(key))
    if payload and payload.get("npc_roleplay"):
        result["npc_roleplay"] = payload["npc_roleplay"]
    if payload and payload.get("social"):
        result["social"] = payload["social"]
    if payload and payload.get("no_roll"):
        result["no_roll"] = True
    if payload and payload.get("empty_clue"):
        result["empty_clue"] = True
    if san_auto_resolved:
        result["san_auto_resolved"] = True
    if luck_decision_required or push_decision_required or combat_defense_required:
        result["partial_log"] = sys_log.strip()
    return update_stagnation_from_system_result(scenario_mgr, result, payload)


def _apply_combat_payload_effects(
    payload, state_mgr, char_mgr, pl_id, sys_log="", active_pcs=None,
    *, game_state=None, current_loc="",
):
    """イベント payload の combat_start / combat_end をゲーム状態へ反映する。"""
    if not payload or not state_mgr or not pl_id:
        return sys_log

    lines = []
    payload_adjudication_id = str(payload.get("adjudication_id") or "")
    payload_resolution_reason = str(payload.get("resolution_reason") or "")
    world_fact = payload.get("world_fact") or {}
    special_objective = (
        str(world_fact.get("event") or "").upper() == "SPECIAL_OBJECTIVE_COMPLETED"
    )

    # Corbitt victory-critical SO / combat_end require validated SOURCE kill.
    if is_corbitt_victory_critical(payload):
        try:
            guard_special_objective_payload(payload)
        except CombatResolutionError as exc:
            payload["blocked"] = True
            payload["blocked_reason"] = exc.code
            payload.pop("combat_end", None)
            payload.pop("completion_phase_deferred", None)
            if payload.get("flag_updates"):
                payload["flag_updates"] = {
                    k: v for k, v in (payload.get("flag_updates") or {}).items()
                    if k != "corbitt_defeated"
                }
            lines.append(f"【システムブロック】{exc.code}: {exc}")
            return (sys_log + ("\n" if sys_log else "") + "\n".join(lines)).strip()

    # Persist special-objective evidence even when the scenario resolves the
    # finale without entering the ordinary attack/defence combat exchange.
    if special_objective and game_state is not None and not state_mgr.in_combat:
        objective_target = str(world_fact.get("target") or payload.get("target") or "")
        objective_combat_id = str(
            getattr(state_mgr, "combat_id", "")
            or f"special_objective:{payload.get('trigger_event_id') or payload_adjudication_id}"
        )
        objective_transaction_id = str(
            payload.get("transaction_id")
            or f"special-objective:{payload_adjudication_id}"
        )
        append_combat_event(
            game_state, "COMBAT_ACTION_RESOLVED", state_mgr=state_mgr,
            combat_id=objective_combat_id,
            actor=pl_id, target=objective_target,
            combat_goal="SPECIAL_OBJECTIVE", action_category="SPECIAL",
            selected_action=str(payload.get("selected_action") or ""),
            action_origin=str(payload.get("action_origin") or AUTONOMOUS),
            legality="LEGAL", result="SPECIAL_OBJECTIVE_COMPLETED",
            final_result="SPECIAL_OBJECTIVE_COMPLETED",
            objective_outcome="SPECIAL_OBJECTIVE_COMPLETED",
            effect=payload.get("human_readable_description") or "",
            combat_progress_delta=1,
            combat_end_condition="scenario_condition",
            transaction_id=objective_transaction_id,
            adjudication_id=payload_adjudication_id,
            # Evidence mode stays ROLL|NO_ROLL; combat class is DETERMINISTIC_RULE.
            resolution_mode="NO_ROLL",
            resolution_class=str(payload.get("resolution_class") or DETERMINISTIC_RULE),
            resolution_reason=payload_resolution_reason or "DERIVED_AFTER_VALIDATED_KILL",
        )
        append_combat_event(
            game_state, "SPECIAL_OBJECTIVE_COMPLETED", state_mgr=state_mgr,
            combat_id=objective_combat_id,
            actor=pl_id, target=objective_target,
            adjudication_id=payload_adjudication_id,
            transaction_id=objective_transaction_id,
            resolution_mode="NO_ROLL",
            resolution_class=str(payload.get("resolution_class") or DETERMINISTIC_RULE),
            resolution_reason=payload_resolution_reason or "DERIVED_AFTER_VALIDATED_KILL",
            final_result="SPECIAL_OBJECTIVE_COMPLETED",
            objective_outcome="SPECIAL_OBJECTIVE_COMPLETED",
            world_fact=copy.deepcopy(world_fact),
            human_readable_description=payload.get("human_readable_description"),
            cause_event_ids=[str(payload.get("trigger_event_id") or "")],
            state_before=copy.deepcopy(payload.get("state_before") or {}),
            state_after=copy.deepcopy(payload.get("state_after") or {}),
        )

    if payload.get("combat_end") and state_mgr.in_combat:
        if game_state is not None:
            # Scenario SPECIAL actions can end combat inside process_action,
            # before commit_system_resolution runs. Close the selected action
            # first so the event sequence remains SELECTED -> RESOLVED -> ENDING.
            selected = next((
                row for row in reversed(game_state.get("unified_event_log") or [])
                if row.get("event_type") == "COMBAT_ACTION_SELECTED"
                and row.get("combat_id") == getattr(state_mgr, "combat_id", "")
            ), None)
            if selected is not None:
                actor_id = selected.get("actor") or pl_id
                payload_adjudication_id = (
                    payload_adjudication_id or selected.get("adjudication_id") or _new_adjudication_id()
                )
                append_combat_event(
                    game_state, "COMBAT_ACTION_RESOLVED", state_mgr=state_mgr,
                    actor=actor_id,
                    actor_state={
                        "HP": char_mgr.get_stat_current(actor_id, "HP"),
                        "SAN": char_mgr.get_stat_current(actor_id, "SAN"),
                    },
                    target=selected.get("target") or "",
                    combat_goal=selected.get("combat_goal") or getattr(state_mgr, "combat_goal", ""),
                    action_category=selected.get("action_category") or "SPECIAL",
                    selected_action=selected.get("selected_action") or "",
                    action_origin=selected.get("action_origin") or AUTONOMOUS,
                    legality="LEGAL",
                    skill=selected.get("skill") or "",
                    result="SPECIAL_OBJECTIVE_COMPLETED",
                    final_result="SPECIAL_OBJECTIVE_COMPLETED",
                    objective_outcome="SPECIAL_OBJECTIVE_COMPLETED",
                    HP_before=selected.get("HP_before"),
                    HP_after=char_mgr.get_stat_current(actor_id, "HP"),
                    SAN_before=selected.get("SAN_before"),
                    SAN_after=char_mgr.get_stat_current(actor_id, "SAN"),
                    position_before=selected.get("position_before") or current_loc,
                    position_after=current_loc,
                    effect="scenario combat_end action resolved",
                    combat_progress_delta=1,
                    combat_end_condition="scenario_condition",
                    transaction_id=selected.get("transaction_id") or "",
                    adjudication_id=payload_adjudication_id,
                    resolution_mode="NO_ROLL",
                    resolution_class=str(payload.get("resolution_class") or DETERMINISTIC_RULE),
                    resolution_reason=payload_resolution_reason or "DERIVED_AFTER_VALIDATED_KILL",
                )
            if payload.get("world_fact"):
                append_combat_event(
                    game_state, "SPECIAL_OBJECTIVE_COMPLETED", state_mgr=state_mgr,
                    actor=pl_id, target=(payload.get("world_fact") or {}).get("target") or "",
                    adjudication_id=payload_adjudication_id,
                    transaction_id=(selected or {}).get("transaction_id") or "",
                    resolution_mode="NO_ROLL",
                    resolution_class=str(payload.get("resolution_class") or DETERMINISTIC_RULE),
                    resolution_reason=payload_resolution_reason or "DERIVED_AFTER_VALIDATED_KILL",
                    final_result="SPECIAL_OBJECTIVE_COMPLETED",
                    objective_outcome="SPECIAL_OBJECTIVE_COMPLETED",
                    world_fact=copy.deepcopy(payload.get("world_fact")),
                    human_readable_description=payload.get("human_readable_description"),
                    cause_event_ids=[str(payload.get("trigger_event_id") or "")],
                    state_before=copy.deepcopy(payload.get("state_before") or {}),
                    state_after=copy.deepcopy(payload.get("state_after") or {}),
                )
            append_combat_event(
                game_state, "COMBAT_ENDING", state_mgr=state_mgr,
                combat_end_condition="scenario_condition",
                effect="scenario combat_end payload accepted",
                cause_adjudication_id=payload_adjudication_id,
            )
        state_mgr.end_combat("scenario_condition")
        if game_state is not None:
            append_combat_event(
                game_state, "COMBAT_ENDED", state_mgr=state_mgr,
                combat_end_condition="scenario_condition",
                position_before=current_loc or getattr(state_mgr, "combat_location_id", ""),
                position_after=current_loc or getattr(state_mgr, "combat_location_id", ""),
                effect="normal progression may resume",
                cause_adjudication_id=payload_adjudication_id,
            )
        lines.append("【戦闘終了】戦闘が終結した。")

    combat_start = payload.get("combat_start")
    if isinstance(combat_start, dict):
        enemies = [eid for eid in (combat_start.get("enemies") or []) if eid in char_mgr.characters]
        for eid in combat_start.get("roll_armor_for") or []:
            char = char_mgr.characters.get(eid)
            if not char:
                continue
            cp = char.setdefault("combat_profile", {})
            if cp.get("armor_roll") and cp.get("armor_points") is None:
                formula = str(cp.get("armor_roll", "2D6"))
                if formula.upper() == "2D6":
                    armor = sum(random.randint(1, 6) for _ in range(2))
                else:
                    armor = max(0, random.randint(2, 12))
                cp["armor_points"] = armor
                name = char.get("profile", {}).get("name", eid)
                lines.append(f"【装甲】《肉体の保護》により{name}の装甲={armor}ポイント")

        if enemies and not state_mgr.in_combat:
            pcs = list(active_pcs or [pl_id])
            participants = pcs + enemies
            order = state_mgr.start_combat(
                participants,
                location_id=current_loc,
                combat_goal=str(combat_start.get("combat_goal") or "ENEMY_DEFEATED"),
            )
            order_names = [
                char_mgr.characters[cid]["profile"]["name"]
                for cid in order
                if cid in char_mgr.characters
            ]
            lines.append(f"【戦闘開始】行動順: {' → '.join(order_names)}")
            if game_state is not None:
                append_combat_event(
                    game_state, "COMBAT_STARTED", state_mgr=state_mgr,
                    actor=state_mgr.get_current_actor() or "",
                    target=",".join(enemies),
                    combat_goal=state_mgr.combat_goal,
                    cause_adjudication_id=payload_adjudication_id,
                    position_before=current_loc,
                    position_after=current_loc,
                    trigger_event_id=str(combat_start.get("trigger_event_id") or ""),
                    participants=list(order),
                    effect={
                        "combatants": list(order),
                        "initiative": list(order),
                        "termination": copy.deepcopy(combat_start.get("termination")),
                    },
                )
                append_combat_event(
                    game_state, "COMBAT_ROUND_STARTED", state_mgr=state_mgr,
                    actor=state_mgr.get_current_actor() or "",
                    combat_goal=state_mgr.combat_goal,
                    effect={"initiative": list(order)},
                )
            char_mgr.save_data()

    if not lines:
        return sys_log
    extra = "\n".join(lines)
    return f"{sys_log}\n{extra}".strip() if sys_log else extra


def _skill_looks_like_firearm(skill_name):
    skill = str(skill_name or "")
    sl = skill.lower()
    return any(k in skill for k in ("射撃", "火器", "拳銃", "ライフル", "ショットガン")) or any(
        k in sl for k in FIREARM_SKILL_KEYWORDS if k.isascii()
    )


def _lookup_skill_value(char_mgr, char_id, skill_name):
    """完全一致 → 部分一致 → BASE_SKILLS の順で技能値を解決する。"""
    skill = str(skill_name or "").strip()
    if not skill:
        return 0, skill
    value = int(char_mgr.get_skill(char_id, skill) or 0)
    if value > 0:
        return value, skill
    char = char_mgr.characters.get(char_id) or {}
    skills = char.get("skills") or {}
    # 「射撃」→「射撃（拳銃）」などのプレフィックス／包含一致
    for key, val in skills.items():
        k = str(key)
        if skill in k or k in skill:
            try:
                v = int(val)
            except (TypeError, ValueError):
                continue
            if v > 0:
                return v, k
    return 0, skill


def _resolve_authoritative_roll_value(char_mgr, char_id, identifier):
    """Resolve a scenario-selected roll identifier without guessing defaults."""
    resolved = resolve_roll_target(char_mgr, char_id, identifier)
    return resolved.get("value") or 0, resolved


def _resolve_combat_attacker_skill(char_mgr, attacker_id, skill_name="", weapon=None, *, prefer_firearm=False):
    """攻撃に使う技能名と技能値を解決する。"""
    weapon = weapon or {}
    default_skill = "射撃（拳銃）" if prefer_firearm else "近接戦闘（格闘）"
    skill = str(skill_name or weapon.get("skill") or default_skill).strip()
    if weapon.get("skill_value") is not None:
        try:
            return skill, int(weapon.get("skill_value"))
        except (TypeError, ValueError):
            pass

    value, skill = _lookup_skill_value(char_mgr, attacker_id, skill)
    if value > 0:
        return skill, value

    if prefer_firearm or _skill_looks_like_firearm(skill):
        for fallback in ("射撃（拳銃）", "射撃", "火器", "Firearms (Handgun)"):
            value, resolved = _lookup_skill_value(char_mgr, attacker_id, fallback)
            if value > 0:
                return resolved, value
        return skill or "射撃（拳銃）", 0

    if skill != "近接戦闘":
        value, resolved = _lookup_skill_value(char_mgr, attacker_id, "近接戦闘")
        if value > 0:
            return resolved, value
    value, resolved = _lookup_skill_value(char_mgr, attacker_id, "近接戦闘（格闘）")
    if value > 0:
        return resolved, value
    return skill, 0


def _resolve_combat_defender_skill(char_mgr, defender_id, defense_mode="dodge"):
    """防衛側の技能名と技能値を解決する。"""
    mode = _normalize_defense_mode(defense_mode)
    if mode == "dodge":
        skill = "回避"
        value = int(char_mgr.get_skill(defender_id, skill) or 0)
        return skill, value, mode
    skill, value = _resolve_combat_attacker_skill(char_mgr, defender_id)
    return skill, value, mode


def _resolve_defender_character_id(char_mgr, target):
    """target（ID または名前）から防御側キャラ ID を解決する。"""
    if not target:
        return None
    if target in char_mgr.characters:
        return target
    for cid, char in char_mgr.characters.items():
        if char.get("profile", {}).get("name") == target:
            return cid
    return None


def begin_combat_attack(
    attacker_id,
    defender_id,
    *,
    skill_name="",
    weapon=None,
    char_mgr,
    state_mgr,
    current_loc="",
    skip_turn_check=False,
):
    """
    近接攻撃宣言を受け、PENDING_COMBAT_DEFENSE 用 payload を組み立てる。
    ダイスは振らない。
    """
    if not state_mgr or not state_mgr.in_combat:
        return {
            "ok": False,
            "log": "【戦闘】戦闘が開始されていないため攻撃できません。",
        }
    if attacker_id not in char_mgr.characters or defender_id not in char_mgr.characters:
        return {
            "ok": False,
            "log": "【戦闘】攻撃対象が不正です。",
        }
    if state_mgr.is_combat_participant_incapacitated(attacker_id):
        return {
            "ok": False,
            "log": "【戦闘】攻撃側は行動不能です。",
        }
    if state_mgr.is_combat_participant_incapacitated(defender_id):
        return {
            "ok": False,
            "log": "【戦闘】対象はすでに行動不能です。",
        }

    current = state_mgr.get_current_actor()
    if not skip_turn_check and current and current != attacker_id:
        actor_name = char_mgr.characters.get(current, {}).get("profile", {}).get("name", current)
        return {
            "ok": False,
            "log": f"【戦闘】現在は {actor_name} の手番です。",
        }

    weapon = weapon or state_mgr.get_default_melee_weapon(attacker_id)
    atk_skill, atk_value = _resolve_combat_attacker_skill(char_mgr, attacker_id, skill_name, weapon)
    atk_name = char_mgr.characters[attacker_id]["profile"]["name"]
    def_name = char_mgr.characters[defender_id]["profile"]["name"]
    legal_options = ["dodge", "fight_back"]
    pending = {
        "adjudication_id": _new_adjudication_id(),
        "attacker_id": attacker_id,
        "defender_id": defender_id,
        "attacker_skill": atk_skill,
        "attacker_skill_value": atk_value,
        "weapon": weapon,
        "location": current_loc,
        "round": state_mgr.round_number,
        "attack_type": "melee",
        "attacker_hp_before": char_mgr.get_stat_current(attacker_id, "HP"),
        "defender_hp_before": char_mgr.get_stat_current(defender_id, "HP"),
        "attacker_san_before": char_mgr.get_stat_current(attacker_id, "SAN"),
        "defender_san_before": char_mgr.get_stat_current(defender_id, "SAN"),
        "allowed_defense_modes": legal_options,
        "legal_options": legal_options,
    }
    state_mgr.set_pending_combat_defense(pending)
    pending_decision = build_combat_pending_decision(pending, decision_owner_id=defender_id)
    log = (
        f"【戦闘・攻撃宣言】{atk_name} が {def_name} に〈{atk_skill}〉({atk_value}) で攻撃！"
        f"\n【保留】{def_name} は【回避】か【応戦】を選択してください。（PENDING_COMBAT_DEFENSE）"
    )
    return {
        "ok": True,
        "log": log,
        "pending_combat_defense": pending,
        "combat_defense_required": True,
        "pending_decision": pending_decision,
    }


def begin_shoot_attack(
    attacker_id,
    defender_id,
    *,
    skill_name="",
    weapon=None,
    char_mgr,
    state_mgr,
    scenario_mgr=None,
    current_loc="",
    skip_turn_check=False,
):
    """
    射撃攻撃宣言を受け、PENDING_SHOOT_DEFENSE 用 payload を組み立てる。
    ゼロ距離ならボーナス・ダイス+1 を pending に記録する（ロールは防衛選択後）。
    """
    if not state_mgr or not state_mgr.in_combat:
        return {
            "ok": False,
            "log": "【射撃】戦闘が開始されていないため射撃できません。",
        }
    if attacker_id not in char_mgr.characters or defender_id not in char_mgr.characters:
        return {
            "ok": False,
            "log": "【射撃】攻撃対象が不正です。",
        }
    if state_mgr.is_combat_participant_incapacitated(attacker_id):
        return {
            "ok": False,
            "log": "【射撃】攻撃側は行動不能です。",
        }
    if state_mgr.is_combat_participant_incapacitated(defender_id):
        return {
            "ok": False,
            "log": "【射撃】対象はすでに行動不能です。",
        }

    current = state_mgr.get_current_actor()
    if not skip_turn_check and current and current != attacker_id:
        actor_name = char_mgr.characters.get(current, {}).get("profile", {}).get("name", current)
        return {
            "ok": False,
            "log": f"【射撃】現在は {actor_name} の手番です。",
        }

    weapon = weapon or state_mgr.get_default_firearm_weapon(attacker_id)
    atk_skill, atk_value = _resolve_combat_attacker_skill(
        char_mgr, attacker_id, skill_name, weapon, prefer_firearm=True,
    )
    point_blank = state_mgr.is_point_blank_shot(
        attacker_id, defender_id,
        current_loc=current_loc, scenario_mgr=scenario_mgr, weapon=weapon,
    )
    bonus_dice = 1 if point_blank else 0
    atk_name = char_mgr.characters[attacker_id]["profile"]["name"]
    def_name = char_mgr.characters[defender_id]["profile"]["name"]
    legal_options = ["dodge", "accept"]
    pending = {
        "adjudication_id": _new_adjudication_id(),
        "attacker_id": attacker_id,
        "defender_id": defender_id,
        "attacker_skill": atk_skill,
        "attacker_skill_value": atk_value,
        "weapon": weapon,
        "location": current_loc,
        "round": state_mgr.round_number,
        "attack_type": "shoot",
        "attacker_hp_before": char_mgr.get_stat_current(attacker_id, "HP"),
        "defender_hp_before": char_mgr.get_stat_current(defender_id, "HP"),
        "attacker_san_before": char_mgr.get_stat_current(attacker_id, "SAN"),
        "defender_san_before": char_mgr.get_stat_current(defender_id, "SAN"),
        "is_ranged": True,
        "point_blank": point_blank,
        "bonus_dice": bonus_dice,
        "allowed_defense_modes": legal_options,
        "legal_options": legal_options,
    }
    state_mgr.set_pending_combat_defense(pending)
    pending_decision = build_combat_pending_decision(pending, decision_owner_id=defender_id)
    pb_note = "【ゼロ距離】ボーナス・ダイス+1。" if point_blank else ""
    log = (
        f"【射撃・攻撃宣言】{atk_name} が {def_name} に〈{atk_skill}〉({atk_value}) で射撃！"
        f"{pb_note}"
        f"\n【保留】{def_name} は【回避】（物陰へ飛び込む）か【甘んじて受ける】を選択してください。"
        f"（PENDING_SHOOT_DEFENSE／応戦不可）"
    )
    return {
        "ok": True,
        "log": log,
        "pending_combat_defense": pending,
        "combat_defense_required": True,
        "pending_decision": pending_decision,
        "point_blank": point_blank,
        "bonus_dice": bonus_dice,
    }


def _finalize_corbitt_kill_from_hit(
    *,
    hit,
    attacker_id,
    defender_id,
    weapon,
    scenario_mgr,
    state_mgr,
    game_state=None,
    adjudication_id="",
    log_parts=None,
    kp_notes=None,
):
    """Apply Route B (dagger) or Route A (HP0) after a damaging hit on Corbitt."""
    log_parts = log_parts if log_parts is not None else []
    kp_notes = kp_notes if kp_notes is not None else []
    kill_payload = None
    if hit and hit.get("status") == "success":
        kill_payload = try_route_b_on_hit(
            attacker_id=attacker_id,
            defender_id=defender_id,
            weapon=weapon or hit.get("weapon"),
            scenario_mgr=scenario_mgr,
        )
        if kill_payload:
            # Route B bypasses residual HP/armor: force HP to 0 for bookkeeping.
            char_mgr = getattr(state_mgr, "char_mgr", None)
            if char_mgr and defender_id in (char_mgr.characters or {}):
                hp_now = int(char_mgr.get_stat_current(defender_id, "HP") or 0)
                if hp_now > 0:
                    char_mgr.apply_pool_damage(defender_id, "HP", hp_now)
            kill_payload["adjudication_id"] = adjudication_id or kill_payload.get("adjudication_id")
            log_parts.append("→ 【Route B】魔法のダガー特効！ 装甲・残HPを無視して灰化。")
            kp_notes.append("【システム】CORBITT_DAGGER_SPECIAL_KILL → CORBITT_BODY_DESTROYED")
        else:
            kill_payload = try_route_a_on_hp0(
                defender_id=defender_id,
                new_hp=int(hit.get("new_hp") if hit.get("new_hp") is not None else 1),
                adjudication_id=adjudication_id,
            )
            if kill_payload:
                log_parts.append("→ 【Route A】コービット HP0。遺体は灰と化した。")
                kp_notes.append("【システム】CORBITT_HP_DEPLETED → CORBITT_BODY_DESTROYED")
                if hit.get("armor_applied"):
                    kp_notes.append(
                        "【ARMOR_APPLIED】"
                        f" armor {hit['armor_applied'].get('armor_before')}→{hit['armor_applied'].get('armor_after')}"
                        f" raw={hit['armor_applied'].get('raw_damage')}"
                        f" penetrating={hit['armor_applied'].get('penetrating_damage')}"
                        f" HP {hit['armor_applied'].get('hp_before')}→{hit['armor_applied'].get('hp_after')}"
                    )
            elif game_state is not None and str(defender_id) == CORBITT_NPC_ID and int(hit.get("damage") or 0) > 0:
                note_pc_hit(game_state)
    if not kill_payload:
        return None
    apply_kill_payload_to_scenario(scenario_mgr, kill_payload)
    char_mgr = getattr(state_mgr, "char_mgr", None)
    if game_state is not None and char_mgr is not None:
        _apply_combat_payload_effects(
            kill_payload, state_mgr, char_mgr,
            attacker_id, game_state=game_state,
            current_loc=str(game_state.get("current_loc") or ""),
        )
        if not kill_payload.get("blocked"):
            from CompletionAtomicity import commit_special_objective_completion
            try:
                commit_special_objective_completion(
                    game_state, kill_payload, scenario_mgr, state_mgr,
                )
            except Exception:
                pass
            # V16 full termination chain before combat ENDED
            try:
                from CombatTerminationContract import run_full_corbitt_termination_chain
                run_full_corbitt_termination_chain(
                    game_state,
                    validated_kill_route_id=str(
                        kill_payload.get("validated_kill_route_id") or ""
                    ),
                    source_rule_id=str(kill_payload.get("source_rule_id") or ""),
                    combat_id=str(getattr(state_mgr, "combat_id", "") or ""),
                )
                if state_mgr and getattr(state_mgr, "in_combat", False):
                    state_mgr.end_combat(
                        "corbitt_validated_kill",
                        state=game_state,
                        skip_corbitt_contract=False,
                    )
            except Exception:
                pass
    elif state_mgr and getattr(state_mgr, "in_combat", False):
        state_mgr.end_combat("corbitt_validated_kill", skip_corbitt_contract=True)
    return kill_payload


def resolve_melee_combat_exchange(
    pending_combat_defense,
    defense_mode,
    *,
    char_mgr,
    dice_engine,
    state_mgr,
    scenario_mgr=None,
    game_state=None,
):
    """
    双方宣言確定後の対抗ロールとダメージ適用。
    完了後に next_turn() を呼ぶ。
    """
    pending = dict(pending_combat_defense or {})
    attacker_id = pending.get("attacker_id")
    defender_id = pending.get("defender_id")
    if not attacker_id or not defender_id:
        return {"ok": False, "log": "【戦闘】攻防データが不正です。"}

    mode = _normalize_defense_mode(defense_mode)
    weapon = pending.get("weapon") or state_mgr.get_default_melee_weapon(attacker_id)
    atk_skill = pending.get("attacker_skill") or weapon.get("skill") or "近接戦闘"
    atk_value = int(pending.get("attacker_skill_value") or 0)
    if atk_value <= 0:
        atk_skill, atk_value = _resolve_combat_attacker_skill(
            char_mgr, attacker_id, atk_skill, weapon,
        )
    def_skill, def_value, mode = _resolve_combat_defender_skill(char_mgr, defender_id, mode)

    atk_name = char_mgr.characters[attacker_id]["profile"]["name"]
    def_name = char_mgr.characters[defender_id]["profile"]["name"]
    mode_label = "応戦" if mode == "fight_back" else "回避"
    adjudication_id = str(pending.get("adjudication_id") or _new_adjudication_id())

    opposed = dice_engine.execute_melee_opposed_roll(
        atk_name, atk_skill, atk_value,
        def_name, def_skill, def_value,
        defense_mode=mode,
    )
    outcome = opposed.get("outcome", "miss")
    log_parts = [
        f"【戦闘解決】{def_name} は【{mode_label}】を選択。",
        opposed.get("log", ""),
    ]
    damage_results = []
    kp_notes = []
    corbitt_kill = None

    if outcome == "dodged":
        log_parts.append(f"→ {def_name} の回避成功。ダメージなし。")
    elif outcome == "miss":
        log_parts.append("→ 双方失敗。どちらの攻撃も当たらなかった。")
    elif outcome == "counter":
        hit = state_mgr.apply_melee_hit(
            defender_id, attacker_id,
            weapon=state_mgr.get_default_melee_weapon(defender_id),
            is_extreme=int(opposed.get("defender_level") or 0) >= 4,
            dice_engine=dice_engine,
        )
        damage_results.append(hit)
        log_parts.append(
            f"→ 応戦成功！ {def_name} のカウンター命中 "
            f"（{hit.get('weapon_name')}: {hit.get('damage_detail', '')} → {hit.get('damage', 0)}点）"
            f" {atk_name} HP {hit.get('old_hp')}→{hit.get('new_hp')}"
        )
        for ev in hit.get("events") or []:
            kp_notes.append(ev.get("instruction", ""))
        corbitt_kill = _finalize_corbitt_kill_from_hit(
            hit=hit, attacker_id=defender_id, defender_id=attacker_id,
            weapon=state_mgr.get_default_melee_weapon(defender_id),
            scenario_mgr=scenario_mgr, state_mgr=state_mgr, game_state=game_state,
            adjudication_id=adjudication_id, log_parts=log_parts, kp_notes=kp_notes,
        )
    elif outcome == "hit_attacker":
        # Route B: owned magic dagger vs Corbitt bypasses armor/HP on hit.
        route_b = try_route_b_on_hit(
            attacker_id=attacker_id, defender_id=defender_id,
            weapon=weapon, scenario_mgr=scenario_mgr,
        )
        if route_b and str(defender_id) == CORBITT_NPC_ID:
            hp_before = int(char_mgr.get_stat_current(defender_id, "HP") or 0)
            hit = {
                "status": "success",
                "old_hp": hp_before,
                "new_hp": 0,
                "damage": hp_before,
                "weapon_name": (weapon or {}).get("name") or "magic dagger",
                "damage_detail": "DAGGER_SPECIAL_KILL",
                "weapon": weapon,
                "bypass_armor": True,
            }
            if hp_before > 0:
                char_mgr.apply_pool_damage(defender_id, "HP", hp_before)
            damage_results.append(hit)
            log_parts.append(
                f"→ 攻撃命中！ 魔法のダガー特効（装甲・HP無視） "
                f"{def_name} HP {hp_before}→0"
            )
            corbitt_kill = _finalize_corbitt_kill_from_hit(
                hit=hit, attacker_id=attacker_id, defender_id=defender_id,
                weapon=weapon, scenario_mgr=scenario_mgr, state_mgr=state_mgr,
                game_state=game_state, adjudication_id=adjudication_id,
                log_parts=log_parts, kp_notes=kp_notes,
            )
        else:
            hit = state_mgr.apply_melee_hit(
                attacker_id, defender_id,
                weapon=weapon,
                is_extreme=int(opposed.get("attacker_level") or 0) >= 4,
                dice_engine=dice_engine,
            )
            damage_results.append(hit)
            log_parts.append(
                f"→ 攻撃命中！ "
                f"（{hit.get('weapon_name')}: {hit.get('damage_detail', '')} → {hit.get('damage', 0)}点"
                f"{'／装甲' + str(hit.get('armor_mitigated', 0)) + '減' if hit.get('armor_mitigated') else ''}）"
                f" {def_name} HP {hit.get('old_hp')}→{hit.get('new_hp')}"
            )
            for ev in hit.get("events") or []:
                kp_notes.append(ev.get("instruction", ""))
            corbitt_kill = _finalize_corbitt_kill_from_hit(
                hit=hit, attacker_id=attacker_id, defender_id=defender_id,
                weapon=weapon, scenario_mgr=scenario_mgr, state_mgr=state_mgr,
                game_state=game_state, adjudication_id=adjudication_id,
                log_parts=log_parts, kp_notes=kp_notes,
            )

    state_mgr.clear_pending_combat_defense()
    next_actor = None
    if not corbitt_kill:
        next_actor = state_mgr.next_turn()
        next_name = ""
        if next_actor and next_actor in char_mgr.characters:
            next_name = char_mgr.characters[next_actor]["profile"]["name"]
            log_parts.append(f"【手番】次は {next_name}（ラウンド {state_mgr.round_number}）")

        # 戦闘終了判定: 片陣営全滅
        # V16: Corbitt final battle must NOT end on living<=1 without validated-kill chain.
        living = [
            cid for cid in (state_mgr.combat_turn_queue or state_mgr.turn_order or [])
            if not state_mgr.is_combat_participant_incapacitated(cid)
        ]
        if len(living) <= 1:
            ended = False
            try:
                from ndm_integration import maybe_end_combat_corbitt_safe
                ended = maybe_end_combat_corbitt_safe(
                    state_mgr, game_state if isinstance(game_state, dict) else {},
                    reason="resolved",
                )
            except Exception:
                # Non-corbitt / legacy path
                try:
                    state_mgr.end_combat("resolved", skip_corbitt_contract=True)
                    ended = True
                except TypeError:
                    state_mgr.end_combat("resolved")
                    ended = True
            if ended:
                log_parts.append("【戦闘終了】行動可能な戦闘参加者が残りわずかのため戦闘を終了。")
            else:
                log_parts.append(
                    "【戦闘継続】Corbitt最終戦では validated kill chain なしに living<=1 では終了しない。"
                )
    else:
        log_parts.append("【戦闘終了】コービット討伐（validated kill route）。")

    kp_instruction = "戦闘の攻防結果を情景として描写してください。"
    if kp_notes:
        kp_instruction = kp_instruction + "\n" + "\n".join(kp_notes)

    return {
        "ok": True,
        "outcome": outcome,
        "defense_mode": mode,
        "log": "\n".join(log_parts),
        "damage_results": damage_results,
        "next_actor": next_actor,
        "kp_instruction": kp_instruction,
        "opposed": opposed,
        "corbitt_kill": corbitt_kill,
        "validated_kill_route_id": (corbitt_kill or {}).get("validated_kill_route_id"),
    }


def resolve_shoot_combat_exchange(
    pending_combat_defense,
    defense_mode,
    *,
    char_mgr,
    dice_engine,
    state_mgr,
    scenario_mgr=None,
    game_state=None,
):
    """
    射撃の防衛選択後ロールとダメージ適用（貫通／肉体的限界込み）。
    【応戦】選択時はガードして解決しない。
    """
    pending = dict(pending_combat_defense or {})
    attacker_id = pending.get("attacker_id")
    defender_id = pending.get("defender_id")
    if not attacker_id or not defender_id:
        return {"ok": False, "log": "【射撃】攻防データが不正です。"}

    ok, mode, err = validate_shoot_defense_mode(defense_mode)
    if not ok:
        return {
            "ok": False,
            "outcome": "not_allowed",
            "log": f"【射撃・防衛ガード】{err}",
            "rejected_fight_back": True,
        }

    weapon = pending.get("weapon") or state_mgr.get_default_firearm_weapon(attacker_id)
    atk_skill = pending.get("attacker_skill") or weapon.get("skill") or "射撃（拳銃）"
    atk_value = int(pending.get("attacker_skill_value") or 0)
    if atk_value <= 0:
        atk_skill, atk_value = _resolve_combat_attacker_skill(
            char_mgr, attacker_id, atk_skill, weapon, prefer_firearm=True,
        )
    def_skill = "回避"
    def_value = int(char_mgr.get_skill(defender_id, def_skill) or 0)
    bonus_dice = int(pending.get("bonus_dice") or 0)
    if pending.get("point_blank") and bonus_dice <= 0:
        bonus_dice = 1

    atk_name = char_mgr.characters[attacker_id]["profile"]["name"]
    def_name = char_mgr.characters[defender_id]["profile"]["name"]
    mode_label = "甘んじて受ける" if mode == "accept" else "回避"
    adjudication_id = str(pending.get("adjudication_id") or _new_adjudication_id())

    opposed = dice_engine.execute_firearm_attack_roll(
        atk_name, atk_skill, atk_value,
        def_name, def_skill, def_value,
        defense_mode=mode,
        attacker_bonus=bonus_dice,
    )
    if opposed.get("outcome") == "not_allowed":
        return {
            "ok": False,
            "outcome": "not_allowed",
            "log": opposed.get("log", err),
            "rejected_fight_back": True,
        }

    outcome = opposed.get("outcome", "miss")
    log_parts = [
        f"【射撃解決】{def_name} は【{mode_label}】を選択。",
    ]
    if pending.get("point_blank") or bonus_dice:
        log_parts.append(f"【ゼロ距離】射撃側ボーナス・ダイス+{bonus_dice}。")
    log_parts.append(opposed.get("log", ""))

    damage_results = []
    kp_notes = []
    corbitt_kill = None
    atk_level = int(opposed.get("attacker_level") or 0)
    is_impale = atk_level >= int(SuccessLevel.EXTREME_SUCCESS)

    if outcome == "dodged":
        log_parts.append(f"→ {def_name} の回避成功。射撃ミス。")
    elif outcome == "miss":
        log_parts.append("→ 射撃失敗。命中しなかった。")
    elif outcome == "hit_attacker":
        hit = state_mgr.apply_firearm_hit(
            attacker_id, defender_id,
            weapon=weapon,
            is_impale=is_impale,
            dice_engine=dice_engine,
        )
        damage_results.append(hit)
        impale_note = "【貫通（インペール）】" if hit.get("impale") else ""
        armor_note = ""
        if hit.get("armor_mitigated"):
            armor_note = f"／装甲{hit.get('armor_mitigated')}減"
        log_parts.append(
            f"→ 射撃命中！{impale_note} "
            f"（{hit.get('weapon_name')}: {hit.get('damage_detail', '')} → {hit.get('damage', 0)}点{armor_note}）"
            f" {def_name} HP {hit.get('old_hp')}→{hit.get('new_hp')}"
        )
        for ev in hit.get("events") or []:
            kp_notes.append(ev.get("instruction", ""))
        corbitt_kill = _finalize_corbitt_kill_from_hit(
            hit=hit, attacker_id=attacker_id, defender_id=defender_id,
            weapon=weapon, scenario_mgr=scenario_mgr, state_mgr=state_mgr,
            game_state=game_state, adjudication_id=adjudication_id,
            log_parts=log_parts, kp_notes=kp_notes,
        )

    state_mgr.clear_pending_combat_defense()
    next_actor = None
    if not corbitt_kill:
        next_actor = state_mgr.next_turn()
        if next_actor and next_actor in char_mgr.characters:
            next_name = char_mgr.characters[next_actor]["profile"]["name"]
            log_parts.append(f"【手番】次は {next_name}（ラウンド {state_mgr.round_number}）")

        living = [
            cid for cid in (state_mgr.combat_turn_queue or state_mgr.turn_order or [])
            if not state_mgr.is_combat_participant_incapacitated(cid)
        ]
        if len(living) <= 1:
            ended = False
            try:
                from ndm_integration import maybe_end_combat_corbitt_safe
                ended = maybe_end_combat_corbitt_safe(
                    state_mgr, game_state if isinstance(game_state, dict) else {},
                    reason="resolved",
                )
            except Exception:
                try:
                    state_mgr.end_combat("resolved", skip_corbitt_contract=True)
                    ended = True
                except TypeError:
                    state_mgr.end_combat("resolved")
                    ended = True
            if ended:
                log_parts.append("【戦闘終了】行動可能な戦闘参加者が残りわずかのため戦闘を終了。")
            else:
                log_parts.append(
                    "【戦闘継続】Corbitt最終戦では validated kill chain なしに living<=1 では終了しない。"
                )
    else:
        log_parts.append("【戦闘終了】コービット討伐（validated kill route）。")

    kp_instruction = "射撃の結果を情景として描写してください。"
    if kp_notes:
        kp_instruction = kp_instruction + "\n" + "\n".join(kp_notes)

    return {
        "ok": True,
        "outcome": outcome,
        "defense_mode": mode,
        "log": "\n".join(log_parts),
        "damage_results": damage_results,
        "next_actor": next_actor,
        "kp_instruction": kp_instruction,
        "opposed": opposed,
        "impale": is_impale and outcome == "hit_attacker",
        "point_blank": bool(pending.get("point_blank")),
        "bonus_dice": bonus_dice,
        "corbitt_kill": corbitt_kill,
        "validated_kill_route_id": (corbitt_kill or {}).get("validated_kill_route_id"),
    }


def generate_pl_combat_defense_prompt(
    char_name, pending, char_mgr, *, attacker_name="", defender_name="",
):
    """PENDING_COMBAT_DEFENSE 用の PL プロンプト。"""
    atk = attacker_name or pending.get("attacker_id", "敵")
    skill = pending.get("attacker_skill", "近接戦闘")
    value = pending.get("attacker_skill_value", "?")
    weapon = (pending.get("weapon") or {}).get("name", "武器")
    return f"""
あなたは探索者（{char_name}）のプレイヤーです。戦闘中に攻撃を受けました。

【攻撃情報】
- 攻撃者: {atk}
- 技能: 〈{skill}〉({value})
- 武器: {weapon}

【選択】
攻撃を受けました。【回避】するか【応戦】するかを選択してください。
- dodge（回避）: 〈回避〉で対抗。成功度が相手以上ならダメージ0
- fight_back（応戦）: 〈近接戦闘〉で対抗。成功度が相手より高ければカウンター命中

JSONのみで回答してください。defense_mode は "dodge" または "fight_back"。
"""


def generate_pl_shoot_defense_prompt(
    char_name, pending, char_mgr, *, attacker_name="", defender_name="",
):
    """PENDING_SHOOT_DEFENSE 用の PL プロンプト。"""
    atk = attacker_name or pending.get("attacker_id", "敵")
    skill = pending.get("attacker_skill", "射撃")
    value = pending.get("attacker_skill_value", "?")
    weapon = (pending.get("weapon") or {}).get("name", "銃")
    pb = "あり（ボーナス・ダイス+1）" if pending.get("point_blank") else "なし"
    return f"""
あなたは探索者（{char_name}）のプレイヤーです。銃撃を受けました。

【攻撃情報】
- 攻撃者: {atk}
- 技能: 〈{skill}〉({value})
- 武器: {weapon}
- ゼロ距離: {pb}

【選択】
銃撃を受けました。【回避】（物陰へ飛び込む）するか【甘んじて受ける】かを選択してください。
- dodge（回避）: 〈回避〉で対抗。射撃側の成功度が回避以下ならミス
- accept（甘んじて受ける）: 対抗せず、射撃ロールのみ（レギュラー成功以上で被弾）
※ fight_back（応戦）は銃撃に対して選択できません。

JSONのみで回答してください。defense_mode は "dodge" または "accept" のみ。
"""


def queue_npc_combat_attack(state, state_mgr, char_mgr, pl_id, current_loc, scenario_mgr=None):
    """NPC手番なら参加PCへの自動攻撃を宣言し pending_combat_defense をセットする。"""
    if not state_mgr or not state_mgr.in_combat:
        return None
    if state.get("pending_combat_defense"):
        return None
    actor = state_mgr.get_current_actor()
    if not actor:
        return None
    # 参加 PC の手番は NPC 攻撃パスでは扱わない
    if is_active_pc_actor(state, actor) or actor == pl_id:
        return None
    if state_mgr.is_combat_participant_incapacitated(actor):
        state_mgr.next_turn()
        return None

    target = pick_npc_combat_target(state, char_mgr, state_mgr)
    if not target or state_mgr.is_combat_participant_incapacitated(target):
        target = None
        for cid in state_mgr.get_combat_turn_queue():
            if cid != actor and not state_mgr.is_combat_participant_incapacitated(cid):
                target = cid
                break
    if not target:
        state_mgr.end_combat()
        return {
            "log": "【戦闘】攻撃対象がいないため戦闘終了。",
            "ended": True,
        }

    # WP-B: Corbitt uses BossCombatPolicy instead of always normal-attacking.
    if str(actor) == CORBITT_NPC_ID:
        decision = choose_corbitt_action(
            state=state,
            char_mgr=char_mgr,
            scenario_mgr=scenario_mgr,
            state_mgr=state_mgr,
            target_id=target,
        )
        action = decision.get("action")
        round_number = int(getattr(state_mgr, "round_number", 0) or 0)
        if action == ACTION_BODY_ACTIVATION:
            activated = activate_body(state, char_mgr, round_number=round_number)
            log = "【コービット】肉体を起動した（BODY_ACTIVATION / 5ラウンド）。"
            if activated.get("ok") and state is not None:
                state.setdefault("unified_event_log", []).append(activated.get("event") or {})
            state_mgr.next_turn()
            return {"ok": True, "log": log, "corbitt_policy": decision, "body_activation": activated}
        if action == ACTION_DOMINATE:
            from DiceEngine import DiceEngine
            dice = getattr(state_mgr, "dice_engine", None) or DiceEngine()
            dominated = resolve_dominate(
                char_mgr=char_mgr, dice_engine=dice,
                caster_id=actor, target_id=target,
            )
            state_mgr.next_turn()
            return {
                "ok": True,
                "log": dominated.get("log") or "【コービット】《支配》を詠唱した。",
                "corbitt_policy": decision,
                "dominate": dominated,
            }
        if action == ACTION_MAGIC_DAGGER:
            # Dagger attack: spend MP and begin attack using floating dagger weapon.
            dagger_weapon = None
            corbitt = (char_mgr.characters or {}).get(CORBITT_NPC_ID) or {}
            for w in corbitt.get("weapons") or []:
                if str((w or {}).get("id") or "") == "corbitt_floating_dagger":
                    dagger_weapon = dict(w)
                    break
            if hasattr(char_mgr, "apply_mp_cost"):
                char_mgr.apply_mp_cost(CORBITT_NPC_ID, 1)
            result = begin_combat_attack(
                actor, target,
                char_mgr=char_mgr,
                state_mgr=state_mgr,
                current_loc=current_loc,
                weapon=dagger_weapon,
            )
            if result.get("ok"):
                result["corbitt_policy"] = decision
                state["pending_combat_defense"] = result["pending_combat_defense"]
                sync_timeline_pending_phase(state)
            return result
        if action != ACTION_NORMAL_ATTACK:
            state_mgr.next_turn()
            return {
                "ok": True,
                "log": "【コービット】静止して機会を窺っている。",
                "corbitt_policy": decision,
            }

    result = begin_combat_attack(
        actor, target,
        char_mgr=char_mgr,
        state_mgr=state_mgr,
        current_loc=current_loc,
    )
    if result.get("ok"):
        if str(actor) == CORBITT_NPC_ID:
            result["corbitt_policy"] = {"action": ACTION_NORMAL_ATTACK, "target_id": target}
        state["pending_combat_defense"] = result["pending_combat_defense"]
        sync_timeline_pending_phase(state)
    return result


def _combat_start_participants(pl_id, defender_id, active_pcs=None):
    """戦闘開始時の参加者リスト（全参加PC + 敵）。"""
    pcs = list(active_pcs or [pl_id])
    if pl_id and pl_id not in pcs:
        pcs.insert(0, pl_id)
    participants = list(pcs)
    if defender_id and defender_id not in participants:
        participants.append(defender_id)
    return participants


def resolve_luck_burn_decision(
    pl_id, char_name, use_luck, pending_luck_burn, current_loc,
    char_mgr, scenario_mgr, partial_sys_log="",
):
    """PL の幸運消費判断後にシナリオ処理を完了する（拒否時はプッシュ決定へ保留）。"""
    margin = pending_luck_burn.get("margin", 0)
    target = pending_luck_burn.get("target", "")
    skill_name = pending_luck_burn.get("skill_name", "")
    effective_action_id = pending_luck_burn.get("original_action", "search")
    fail_level = int(pending_luck_burn.get("failed_success_level", SuccessLevel.FAILURE))
    adjudication_id = str(pending_luck_burn.get("adjudication_id") or _new_adjudication_id())
    roll_evidence = {
        "roll": pending_luck_burn.get("roll"),
        "target_value": pending_luck_burn.get("target_value"),
        "success_level": fail_level,
    }
    allow_push = bool(pending_luck_burn.get("allow_push", True)) and _skill_allows_push(
        skill_name, effective_action_id,
    )

    sys_log = partial_sys_log
    success_level = fail_level

    if use_luck:
        spent, remaining_luck = char_mgr.spend_luck(pl_id, margin, max_burn=LUCK_BURN_MAX)
        if spent:
            difficulty = pending_luck_burn.get("required_difficulty", "regular")
            success_level = int(min_level_for_difficulty(difficulty))
            prefix = "\n" if sys_log else ""
            sys_log += (
                f"{prefix}【幸運消費】PLの意志により幸運を {margin} 消費し、"
                f"{difficulty} 成功に書き換えた"
                f"（残り幸運: {remaining_luck}）"
            )
            scenario_mgr.location = current_loc
            payload = scenario_mgr.process_action(effective_action_id, target, success_level)
            result = _build_system_action_result(
                success_level,
                sys_log,
                payload,
                effective_action_id,
                None,
                current_loc=current_loc,
                scenario_mgr=scenario_mgr,
                roll_type="skill",
                action_target=target,
            )
            modifier = {
                "type": "LUCK_SPEND",
                "amount": int(margin),
                "resource_before": int(remaining_luck) + int(margin),
                "resource_after": int(remaining_luck),
            }
            result["luck_modifier"] = modifier
            return _attach_adjudication_evidence(
                result, adjudication_id=adjudication_id,
                actor_id=pl_id, target_id=target, skill_or_stat=skill_name,
                dice_result=roll_evidence, resolution_mode="ROLL",
                raw_result=fail_level, final_result=success_level, modifier=modifier,
            )
        prefix = "\n" if sys_log else ""
        sys_log += f"{prefix}【幸運消費失敗】幸運が不足しているため、失敗のまま進行する。"
    else:
        prefix = "\n" if sys_log else ""
        sys_log += f"{prefix}【幸運温存】PLは幸運消費を見送り、失敗として受け入れた。"

    if allow_push:
        pending_push = _build_push_roll_state(
            target,
            skill_name,
            effective_action_id,
            pending_luck_burn.get("modifier", 0),
            pending_luck_burn.get("bonus_dice", 0),
            pending_luck_burn.get("penalty_dice", 0),
            required_difficulty=pending_luck_burn.get("required_difficulty", "regular"),
            failed_success_level=fail_level,
            allow_push=True,
            decision_pending=True,
        )
        pending_push["legal_options"] = [DECISION_OPTION_ACCEPT, DECISION_OPTION_PUSH]
        result = _build_system_action_result(
            fail_level,
            sys_log,
            None,
            effective_action_id,
            pending_push,
            current_loc=current_loc,
            scenario_mgr=scenario_mgr,
            push_decision_required=True,
            roll_type="skill",
            action_target=target,
            decision_owner_id=pl_id,
        )
        result = _attach_adjudication_evidence(
            result, adjudication_id=adjudication_id,
            actor_id=pl_id, target_id=target, skill_or_stat=skill_name,
            dice_result=roll_evidence, resolution_mode="ROLL",
            raw_result=fail_level, final_result=fail_level,
        )
        if result.get("pending_push_roll"):
            result["pending_push_roll"].update(
                copy.deepcopy(result.get("adjudication") or {})
            )
        return result

    scenario_mgr.location = current_loc
    payload = scenario_mgr.process_action(effective_action_id, target, fail_level)
    result = _build_system_action_result(
        fail_level,
        sys_log,
        payload,
        effective_action_id,
        None,
        current_loc=current_loc,
        scenario_mgr=scenario_mgr,
        roll_type="skill",
        action_target=target,
    )
    return _attach_adjudication_evidence(
        result, adjudication_id=adjudication_id,
        actor_id=pl_id, target_id=target, skill_or_stat=skill_name,
        dice_result=roll_evidence, resolution_mode="ROLL",
        raw_result=fail_level, final_result=fail_level,
    )


def resolve_push_decline(
    pl_id, char_name, pending_push_roll, current_loc,
    scenario_mgr, partial_sys_log="",
):
    """プッシュ拒否時に失敗を確定し、シナリオ処理を行う。"""
    target = pending_push_roll.get("target", "")
    effective_action_id = pending_push_roll.get("original_action", "search")
    fail_level = int(pending_push_roll.get("failed_success_level", SuccessLevel.FAILURE))
    sys_log = partial_sys_log or ""
    prefix = "\n" if sys_log else ""
    sys_log += f"{prefix}【プッシュ見送り】{char_name}(PL)は再挑戦せず、失敗を確定した。"

    scenario_mgr.location = current_loc
    payload = scenario_mgr.process_action(effective_action_id, target, fail_level)
    result = _build_system_action_result(
        fail_level,
        sys_log,
        payload,
        effective_action_id,
        None,
        current_loc=current_loc,
        scenario_mgr=scenario_mgr,
        roll_type="skill",
        action_target=target,
    )
    evidence = {
        key: copy.deepcopy(pending_push_roll.get(key))
        for key in _ADJUDICATION_RESULT_FIELDS
        if key in pending_push_roll
    }
    evidence.update({
        "actor_id": pending_push_roll.get("actor_id") or pl_id,
        "target_id": pending_push_roll.get("target_id") or target,
    })
    from AdjudicationEvidence import validate_evidence
    validate_evidence(evidence)
    result.update(evidence)
    result["adjudication"] = copy.deepcopy(evidence)
    return result


# ★ 引数に `state_mgr` を追加
def process_system_action(
    pl_id, char_name, action_id, target, skill_name, current_loc, char_mgr, dice_engine,
    scenario_mgr, pending_san_check=None, state_mgr=None, pending_push_roll=None,
    san_resolution_only=False, active_pcs=None, dialogue_text="",
    game_state=None,
):
    success_level = int(SuccessLevel.FAILURE)
    sys_log = ""
    madness_instruction = ""
    mythos_madness_instruction = ""
    push_fail_madness_instruction = ""
    action_id = str(action_id or "wait").lower()
    target = normalize_action_target(target, scenario_mgr, current_loc, char_mgr=char_mgr)
    proposed_skill_raw = str(skill_name or "").strip()
    engine_judgment_meta = {
        "proposed_skill": proposed_skill_raw,
        "resolved_skill": "",
        "skill_overridden": False,
        "difficulty": "regular",
        "allowed_skills": [],
    }
    if action_id == "move" and scenario_mgr and hasattr(scenario_mgr, "_canonical_move_target"):
        target = scenario_mgr._canonical_move_target(target, loc_id=current_loc)
    if pending_push_roll:
        pending_push_roll = dict(pending_push_roll)
        if pending_push_roll.get("target"):
            pending_push_roll["target"] = normalize_action_target(
                pending_push_roll["target"], scenario_mgr, current_loc, char_mgr=char_mgr,
            )
    new_pending_push_roll = pending_push_roll

    push_fail_penalty_instruction = ""
    investigation_context = None
    effective_action_id = action_id
    pending_luck_burn = None
    parent_adjudication_id = str((pending_push_roll or {}).get("adjudication_id") or "")
    adjudication_id = _new_adjudication_id()
    in_combat = bool(state_mgr and getattr(state_mgr, "in_combat", False))
    mythos_san_check_pending = _is_san_check_pending(pending_san_check)

    # WP-A: pre-defeat break/force/kick/push on corbitt_body → attack walter_corbitt.
    _body_remap = remap_body_break_to_attack(action_id, target, scenario_mgr=scenario_mgr)
    if _body_remap.get("remapped"):
        action_id = _body_remap["action_id"]
        target = _body_remap["target"]
        skill_name = _body_remap.get("skill") or skill_name or "近接戦闘"
        effective_action_id = action_id
        sys_log += (
            f"【ACTION_REMAPPED】{_body_remap.get('original_action_id')}@{_body_remap.get('original_target')}"
            f" → attack@{CORBITT_NPC_ID} ({_body_remap.get('remap_rule_id')})\n"
        )
        if game_state is not None:
            game_state.setdefault("action_remap_log", []).append(copy.deepcopy(_body_remap))

    if in_combat:
        active = active_pcs or (
            (game_state or {}).get("active_pcs") if game_state else None
        ) or getattr(char_mgr, "active_pc_list", None) or [pl_id]
        candidates = build_combat_action_candidates(
            state_mgr, char_mgr, scenario_mgr, pl_id, current_loc,
            active_pc_ids=active,
        )
        verdict = validate_combat_action(
            {"action": action_id, "target": target, "skill": skill_name},
            candidates,
        )
        if not verdict.get("legal"):
            if game_state is not None:
                append_combat_event(
                    game_state, "COMBAT_ACTION_REJECTED", state_mgr=state_mgr,
                    actor=pl_id, target=target, selected_action=action_id,
                    legality="ILLEGAL", combat_goal=getattr(state_mgr, "combat_goal", ""),
                    position_before=current_loc, position_after=current_loc,
                    effect=verdict.get("reason") or "illegal_combat_action",
                )
            return _build_system_action_result(
                0,
                f"【戦闘行動拒否】{verdict.get('reason') or 'illegal_combat_action'}",
                {"blocked": True, "combat_action_rejected": True,
                 "kp_instruction": "戦闘中は提示された合法な戦闘行動を選んでください。"},
                action_id, None,
                current_loc=current_loc, scenario_mgr=scenario_mgr,
                roll_type="combat_rejected", action_target=target,
            )

    if (
        str(action_id or "").lower() not in INVESTIGATION_ACTION_IDS
        and action_id != "attack"
        and action_id not in SHOOT_ACTION_IDS
        and not is_social_action(action_id, skill_name)
    ):
        skill_name = ""

    # 対人対象への search/inspect/push は talk へ強制変換（最終ガード）
    # 現在地の調査オブジェクト（マカリオ夫妻など）は除外する
    human_fix = rewrite_human_investigation_to_talk(
        action_id, target, char_mgr=char_mgr,
        scenario_mgr=scenario_mgr, current_loc=current_loc,
    )
    if human_fix:
        sys_log += f"{human_fix.get('log') or HUMAN_INSPECT_REWRITE_LOG}\n"
        action_id = human_fix["action"]
        target = human_fix["target"]
        skill_name = human_fix.get("skill") or ""
        effective_action_id = action_id

    # 受付紹介前のアーティ／切り抜き直指定は受付 talk へ最終リダイレクト
    flags_early = scenario_mgr.flags if scenario_mgr else {}
    redirected_tgt = _redirect_preintro_artie_target(target, flags_early, current_loc)
    if redirected_tgt:
        if target != redirected_tgt or action_id not in (
            "talk", "speak", "chat", "converse", "negotiate", "persuade",
            "fast_talk", "charm", "intimidate", "psychology",
        ):
            sys_log += (
                "【アクション補正】未紹介のアーティ／資料室への直接行動を、"
                "受付（`globe_receptionist`）への取次依頼に切り替えました。\n"
            )
        action_id = "talk"
        target = redirected_tgt
        skill_name = ""
        effective_action_id = action_id

    # --------------------------------------------------
    # SAN保留中: wait 以外の行動を一律ブロック（自動解決専用パスを除く）
    # --------------------------------------------------
    if mythos_san_check_pending and not san_resolution_only:
        if action_id not in SAN_PENDING_ALLOWED_ACTIONS:
            san_block = scenario_mgr.evaluate_san_pending_block(action_id, pending_san_check)
            block_log = (san_block or {}).get("system_log", SAN_PENDING_BLOCK_LOG)
            sys_log += f"{block_log}\n"
            return _build_system_action_result(
                0,
                sys_log.strip(),
                {
                    "kp_instruction": (san_block or {}).get(
                        "kp_instruction",
                        "SANチェック保留中です。恐怖のリアクションのみ描写してください。",
                    ),
                    "san_check": pending_san_check,
                    "blocked": True,
                },
                action_id,
                None,
                current_loc=current_loc,
                scenario_mgr=scenario_mgr,
                roll_type="blocked",
                action_target=target,
            )

    # 汎用オブジェクトアクセスゲート（シナリオ定義 access_gate を参照）
    access_block = _evaluate_object_access_gate(
        scenario_mgr,
        char_mgr,
        current_loc=current_loc,
        target=target,
        action_id=action_id,
    )
    if access_block:
        sys_log += str(access_block.get("log", "") or "") + "\n"
        access_hint = access_block.get("stagnation_pl_hint") or ACCESS_GATE_NEGOTIATE_SKILL_HINT
        if game_state is not None:
            game_state["stagnation_pl_hint"] = access_hint
        return _build_system_action_result(
            0,
            sys_log.strip(),
            {
                "blocked": True,
                "kp_instruction": access_block.get("kp_instruction", "アクセス条件が未達です。"),
                "stagnation_pl_hint": access_hint,
            },
            action_id,
            None,
            current_loc=current_loc,
            scenario_mgr=scenario_mgr,
            roll_type="blocked",
            action_target=target,
        )

    # 人型調査オブジェクトへの talk/交渉は search/inspect へ落とす
    object_talk = rewrite_talk_to_object_investigation(
        action_id, target, scenario_mgr, current_loc, skill_name,
    )
    if object_talk:
        sys_log += f"{object_talk.get('log') or OBJECT_TALK_REWRITE_LOG}\n"
        action_id = object_talk["action"]
        target = object_talk["target"]
        if object_talk.get("skill"):
            skill_name = object_talk["skill"]
        effective_action_id = action_id

    # 調査オブジェクトへの search/inspect は、技能が心理学等でも社交パイプラインへ入れない
    treat_as_object_investigation = is_investigable_location_object(
        scenario_mgr, current_loc, target,
    ) and str(action_id or "").lower() in INVESTIGATION_ACTION_IDS

    # --------------------------------------------------
    # NPC 対話・交渉（説得／言いくるめ／威圧／魅惑／心理学）
    # --------------------------------------------------
    if is_social_action(action_id, skill_name) and not treat_as_object_investigation:
        social_mgr = NPCSocialManager(char_mgr)
        npc_id = find_npc_id_by_target(char_mgr, target)
        exclude_for_guidance = {str(x) for x in (npc_id, target) if x}
        block_log, kp_inst, redirect_hint = build_absent_npc_guidance(
            scenario_mgr, current_loc, exclude_targets=exclude_for_guidance, char_mgr=char_mgr,
        )
        if not npc_id:
            # 不在・未定義人物（例: 名前だけ出るルース・ブレイク）への対話を LLM 前に弾く
            sys_log += f"{block_log}\n"
            if game_state is not None:
                game_state["stagnation_pl_hint"] = redirect_hint
            return _build_system_action_result(
                0,
                sys_log.strip(),
                {
                    "blocked": True,
                    "absent_npc": True,
                    "kp_instruction": kp_inst,
                    "stagnation_pl_hint": redirect_hint,
                },
                action_id,
                None,
                current_loc=current_loc,
                scenario_mgr=scenario_mgr,
                roll_type="blocked",
                action_target=target,
            )
        # 幽霊NPC遮断: 現在地に配置されていない NPC への対話を拒否
        # （npcs_present が空でも暗黙許可しない。旧形式は profile.locations で判定）
        if scenario_mgr and hasattr(scenario_mgr, "is_npc_at_location"):
            if not scenario_mgr.is_npc_at_location(npc_id, current_loc, char_mgr=char_mgr):
                block_log, kp_inst, redirect_hint = build_absent_npc_guidance(
                    scenario_mgr, current_loc, exclude_targets=exclude_for_guidance, char_mgr=char_mgr,
                )
                sys_log += f"{block_log}\n"
                if game_state is not None:
                    game_state["stagnation_pl_hint"] = redirect_hint
                return _build_system_action_result(
                    0,
                    sys_log.strip(),
                    {
                        "blocked": True,
                        "ghost_npc": True,
                        "absent_npc": True,
                        "kp_instruction": kp_inst,
                        "stagnation_pl_hint": redirect_hint,
                    },
                    action_id,
                    None,
                    current_loc=current_loc,
                    scenario_mgr=scenario_mgr,
                    roll_type="blocked",
                    action_target=target,
                )
        # ボストン・グローブ: 受付紹介前はアーティと会話・交渉できない
        # （上流リダイレクト漏れ時の最終ガード: ブロックせず受付へ再解決）
        flags = scenario_mgr.flags if scenario_mgr else {}
        if npc_id == "artie_wilmott" and not npc_is_available(char_mgr, npc_id, flags):
            sys_log += (
                "【アクション補正】編集者アーティにはまだ会っていないため、"
                "受付（`globe_receptionist`）への取次依頼として処理します。\n"
            )
            npc_id = "globe_receptionist"
            target = "globe_receptionist"
        # 許可取得後のアーティ／受付への会話・交渉は無効（切り抜き search へ誘導）
        if (
            flags.get("artie_reference_room_access_granted")
            and npc_id in ("artie_wilmott", "globe_receptionist")
            and _clipping_files_search_pending(scenario_mgr, current_loc)
        ):
            sys_log += (
                "【進行ブロック】参考資料室の許可は取得済みです。"
                "アーティ／受付との再交渉は不要。"
                "`search` / `reference_room_clipping_files` を実行してください。\n"
            )
            hint = ARTIE_ACCESS_GRANTED_SEARCH_HINT
            if game_state is not None:
                game_state["stagnation_pl_hint"] = hint
            return _build_system_action_result(
                0,
                sys_log.strip(),
                {
                    "blocked": True,
                    "post_access_social_blocked": True,
                    "kp_instruction": (
                        "【許可済み】門前払いや再交渉を描写するな。"
                        "切り抜きファイルの調査を自然に促せ。"
                    ),
                    "stagnation_pl_hint": hint,
                },
                action_id,
                None,
                current_loc=current_loc,
                scenario_mgr=scenario_mgr,
                roll_type="blocked",
                action_target=npc_id,
            )
        # 受付ループ誘導: 紹介済み後の受付 talk は冪等KP指示を付与（初対面取り次ぎを繰り返さない）
        reception_followup_kp = ""
        if (
            npc_id == "globe_receptionist"
            and flags.get("artie_introduced")
            and is_casual_talk(action_id, skill_name)
        ):
            reception_followup_kp = (
                "【冪等】アーティは既に紹介済み。受付の初対面取り次ぎ描写を繰り返すな。"
                "短く『編集者はすでに呼び出済み／ロビーにいる』と案内し、"
                "アーティ本人への交渉（persuade / intimidate / fast_talk）を促せ。"
                "参考資料室は未許可なら調査させないこと。"
            )
        # アーティ雑談ループ遮断: 許可未取得かつ対話済みなら talk を拒否（交渉へ誘導）
        if (
            npc_id == "artie_wilmott"
            and flags.get("artie_introduced")
            and not flags.get("artie_reference_room_access_granted")
            and is_casual_talk(action_id, skill_name)
        ):
            social_preview = NPCSocialManager(char_mgr).ensure_social_session(npc_id)
            if int(social_preview.get("dialogue_count") or 0) >= 1:
                guidance = build_boston_globe_stale_guidance(scenario_mgr, current_loc)
                sys_log += f"{guidance.get('error') or STALE_ARTIE_TALK_REJECT_ERROR}\n"
                return _build_system_action_result(
                    0,
                    sys_log.strip(),
                    {
                        "blocked": True,
                        "stale_artie_talk": True,
                        "kp_instruction": (
                            "【進行誘導】現在の進行段階に合った次の行動を促せ。"
                            "許可未取得なら交渉を、許可済みなら切り抜き search を、"
                            "調査完了なら他ロケーションへの move を促せ。"
                            "システム内部文を読み上げるな。"
                        ),
                        "stagnation_pl_hint": guidance.get("error"),
                    },
                    action_id,
                    None,
                    current_loc=current_loc,
                    scenario_mgr=scenario_mgr,
                    roll_type="blocked",
                    action_target=npc_id,
                )
        # キムの〈法律〉など NPC 固有交渉技能は雑談扱いにせず交渉へ
        use_casual = is_casual_talk(action_id, skill_name) and not is_negotiation_skill_for_npc(
            skill_name, npc_id, char_mgr,
        )
        if use_casual:
            occupation_rp = judge_occupation_roleplay(
                char_mgr=char_mgr,
                pc_id=pl_id,
                npc_id=npc_id,
                action_id=action_id,
                skill_name=skill_name,
                dialogue_text=dialogue_text,
                current_loc=current_loc,
                scenario_mgr=scenario_mgr,
                casual=True,
            )
            social = social_mgr.resolve_casual_talk(
                pl_id, npc_id, dialogue_text=dialogue_text,
                occupation_rp=occupation_rp,
            )
        else:
            occupation_rp = judge_occupation_roleplay(
                char_mgr=char_mgr,
                pc_id=pl_id,
                npc_id=npc_id,
                action_id=action_id,
                skill_name=skill_name,
                dialogue_text=dialogue_text,
                current_loc=current_loc,
                scenario_mgr=scenario_mgr,
                casual=False,
            )
            social = social_mgr.resolve_negotiation(
                pl_id,
                npc_id,
                skill_name=skill_name,
                dice_engine=dice_engine,
                action_id=action_id,
                dialogue_text=dialogue_text,
                occupation_rp=occupation_rp,
            )
        if social.get("ok") is False:
            sys_log += social.get("log", "") + "\n"
            return _build_system_action_result(
                0,
                sys_log.strip(),
                {
                    "blocked": True,
                    "kp_instruction": social.get("kp_instruction", "交渉を処理できませんでした。"),
                },
                action_id,
                None,
                current_loc=current_loc,
                scenario_mgr=scenario_mgr,
                roll_type="blocked",
                action_target=target,
            )
        sys_log += social.get("log", "")
        # シナリオ定義ベースの進行フラグ更新（social_progress_rules）
        progress_log, progress_kp, progress_grants = _apply_social_progress_rules(
            scenario_mgr,
            current_loc=current_loc,
            npc_id=npc_id,
            action_id=action_id,
            social_result=social,
        )
        if progress_log:
            sys_log += "\n" + progress_log
        if progress_kp:
            social = dict(social)
            social["kp_instruction"] = (social.get("kp_instruction") or "") + "\n" + progress_kp
        if reception_followup_kp:
            social = dict(social)
            social["kp_instruction"] = (
                (social.get("kp_instruction") or "") + "\n" + reception_followup_kp
            )
            sys_log += (
                "\n【案内】アーティは既に呼び出済み。"
                "受付への再確認より、編集者本人への交渉（persuade 等）を優先せよ。"
            )

        # 汎用: 社交成功で access_gate.permission_flag を付与
        if scenario_mgr:
            granted_access = _grant_access_flags_from_social_result(
                scenario_mgr,
                char_mgr,
                current_loc=current_loc,
                npc_id=npc_id,
                skill_used=(social.get("skill") or skill_name or ""),
                social_result=social,
            )
            if granted_access:
                for obj_id, obj_name, _flag in granted_access:
                    sys_log += (
                        f"\n【進行】交渉の結果、{obj_name}（`{obj_id}`）へのアクセス許可が出た。"
                        "これ以降、該当対象の調査が可能。"
                    )
                social = dict(social)
                social["access_just_granted"] = True
                social["kp_instruction"] = (
                    (social.get("kp_instruction") or "")
                    + "\n【進行・絶対遵守】交渉成功でアクセス許可が更新された。"
                      "以後は同対象を『未許可』として拒絶しないこと。"
                      "ルース等の追加許可待ち・門前払い描写は禁止。"
                      "切り抜きファイル（`reference_room_clipping_files`）の"
                      "search を明確に案内すること。"
                )
                if game_state is not None:
                    _reset_guard_after_access_granted(game_state)
        social_payload = {
            "kp_instruction": social.get("kp_instruction", ""),
            "npc_roleplay": social.get("npc_roleplay"),
            "social": social,
            "san_check": {"required": False},
        }
        if progress_grants:
            social_payload["knowledge_grants"] = list(progress_grants)
            first = progress_grants[0] if progress_grants else {}
            if first.get("summary"):
                social_payload["confirmed_fact"] = first["summary"]
                social_payload["dice_success"] = True
                obj = scenario_mgr.get_object_info(current_loc, first.get("target")) if scenario_mgr else {}
                if should_emit_handout_ic(obj, first["summary"]):
                    social_payload["handout_text"] = first["summary"]
                    social_payload["handout_ic_block"] = format_handout_ic_block(
                        first["summary"], (obj or {}).get("name", first.get("target")),
                    )
        # ボストン・グローブ: 交渉失敗直後は別技能・他PC誘導ヒントを注入（早期移動しない）
        if (
            current_loc == "boston_globe"
            and not social.get("casual")
            and scenario_mgr
            and (scenario_mgr.flags or {}).get("artie_introduced")
            and not (scenario_mgr.flags or {}).get("artie_reference_room_access_granted")
            and npc_id in ("artie_wilmott", "artie")
            and is_failure_level(int(social.get("success_level") or 0))
        ):
            fail_hint = _build_negotiate_fail_stagnation_hint(
                char_mgr=char_mgr,
                pl_id=pl_id,
                skill_used=(social.get("skill") or skill_name or ""),
                active_pcs=active_pcs or (
                    (game_state or {}).get("active_pcs") if game_state else None
                ) or getattr(char_mgr, "active_pc_list", None),
                failed_target=npc_id,
            )
            social_payload["stagnation_pl_hint"] = fail_hint
            if game_state is not None:
                game_state["stagnation_pl_hint"] = fail_hint
        social_result = _build_system_action_result(
            int(social.get("success_level") or 0),
            sys_log.strip(),
            social_payload,
            action_id,
            None,
            current_loc=current_loc,
            scenario_mgr=scenario_mgr,
            roll_type="social_talk" if social.get("casual") else "social_negotiate",
            action_target=npc_id,
        )
        adjudication_id = _new_adjudication_id()
        if social.get("casual") or social.get("skipped_roll"):
            social_result["resolution_reason"] = (
                "CASUAL_CONVERSATION" if social.get("casual") else "OCCUPATION_ROLEPLAY_AUTO_SUCCESS"
            )
            return _attach_adjudication_evidence(
                social_result, adjudication_id=adjudication_id,
                actor_id=pl_id, target_id=npc_id,
                skill_or_stat=social.get("skill") or skill_name or "",
                resolution_mode="NO_ROLL",
                final_result=social.get("success_level") or SuccessLevel.REGULAR_SUCCESS,
            )
        return _attach_adjudication_evidence(
            social_result, adjudication_id=adjudication_id,
            actor_id=pl_id, target_id=npc_id,
            skill_or_stat=social.get("skill") or skill_name or "",
            dice_result=social.get("roll_evidence") or {},
            resolution_mode="ROLL",
            raw_result=social.get("success_level"),
            final_result=social.get("success_level"),
            modifier={
                "type": "BONUS_PENALTY_DICE",
                "bonus": int((social.get("dice_mod") or {}).get("bonus") or 0),
                "penalty": int((social.get("dice_mod") or {}).get("penalty") or 0),
            },
        )

    # --------------------------------------------------
    # 近接攻撃宣言 → PENDING_COMBAT_DEFENSE（ダイスは振らない）
    # --------------------------------------------------
    if action_id == "attack":
        just_started = False
        defender_id = _resolve_defender_character_id(char_mgr, target)
        if not state_mgr or not state_mgr.in_combat:
            if state_mgr and defender_id:
                pcs = active_pcs or getattr(char_mgr, "active_pc_list", None) or [pl_id]
                order = state_mgr.start_combat(
                    _combat_start_participants(pl_id, defender_id, pcs),
                    location_id=current_loc,
                )
                if game_state is not None:
                    append_combat_event(
                        game_state, "COMBAT_STARTED", state_mgr=state_mgr,
                        actor=state_mgr.get_current_actor() or pl_id,
                        target=defender_id, combat_goal=state_mgr.combat_goal,
                        position_before=current_loc, position_after=current_loc,
                        effect={"combatants": list(order), "initiative": list(order)},
                    )
                    append_combat_event(
                        game_state, "COMBAT_ROUND_STARTED", state_mgr=state_mgr,
                        actor=state_mgr.get_current_actor() or pl_id,
                        combat_goal=state_mgr.combat_goal,
                    )
                sys_log += "【戦闘開始】攻撃宣言により戦闘に突入した。\n"
                just_started = True
            else:
                sys_log += "【戦闘】攻撃対象が不明なため処理できません。\n"
                return _build_system_action_result(
                    0, sys_log.strip(), {"blocked": True, "kp_instruction": "攻撃対象を明確にしてください。"},
                    action_id, None,
                    current_loc=current_loc, scenario_mgr=scenario_mgr,
                    roll_type="blocked", action_target=target,
                )
        if not defender_id:
            sys_log += "【戦闘】攻撃対象が不明なため処理できません。\n"
            return _build_system_action_result(
                0, sys_log.strip(), {"blocked": True, "kp_instruction": "攻撃対象を明確にしてください。"},
                action_id, None,
                current_loc=current_loc, scenario_mgr=scenario_mgr,
                roll_type="blocked", action_target=target,
            )
        begin = begin_combat_attack(
            pl_id, defender_id,
            skill_name=skill_name,
            char_mgr=char_mgr,
            state_mgr=state_mgr,
            current_loc=current_loc,
            skip_turn_check=just_started,
        )
        if begin.get("pending_combat_defense") is not None and game_state is not None:
            combat_tid = str(
                (game_state.get("last_pl_action") or {}).get("transaction_id")
                or game_state.get("pending_action_id") or ""
            )
            begin["pending_combat_defense"]["transaction_id"] = combat_tid
            state_mgr.set_pending_combat_defense(begin["pending_combat_defense"])
            for row in reversed(game_state.get("unified_event_log") or []):
                if row.get("event_type") == "COMBAT_ACTION_SELECTED" and (
                    not combat_tid or str(row.get("transaction_id") or "") == combat_tid
                ):
                    row["adjudication_id"] = begin["pending_combat_defense"]["adjudication_id"]
                    break
        sys_log += begin.get("log", "") + "\n"
        if begin.get("combat_defense_required"):
            result = _build_system_action_result(
                0,
                sys_log.strip(),
                {
                    "kp_instruction": (
                        "攻撃が宣言されました。防御側の選択（回避／応戦）を待ってから"
                        "攻防の結果を描写してください。"
                    ),
                },
                action_id,
                None,
                current_loc=current_loc,
                scenario_mgr=scenario_mgr,
                roll_type="combat_attack_declare",
                action_target=defender_id,
                combat_defense_required=True,
                pending_combat_defense=begin.get("pending_combat_defense"),
            )
            return _attach_adjudication_evidence(
                result,
                adjudication_id=begin["pending_combat_defense"]["adjudication_id"],
                actor_id=pl_id, target_id=defender_id,
                skill_or_stat=begin["pending_combat_defense"].get("attacker_skill", ""),
                resolution_mode="NO_ROLL",
            )
        return _build_system_action_result(
            0, sys_log.strip(),
            {"blocked": True, "kp_instruction": begin.get("log", "攻撃を処理できませんでした。")},
            action_id, None,
            current_loc=current_loc, scenario_mgr=scenario_mgr,
            roll_type="blocked", action_target=target,
        )

    # --------------------------------------------------
    # 射撃攻撃宣言 → PENDING_SHOOT_DEFENSE（ダイスは防衛選択後）
    # --------------------------------------------------
    if action_id in SHOOT_ACTION_IDS:
        just_started = False
        defender_id = _resolve_defender_character_id(char_mgr, target)
        if not state_mgr or not state_mgr.in_combat:
            if state_mgr and defender_id:
                pcs = active_pcs or getattr(char_mgr, "active_pc_list", None) or [pl_id]
                order = state_mgr.start_combat(
                    _combat_start_participants(pl_id, defender_id, pcs),
                    location_id=current_loc,
                )
                if game_state is not None:
                    append_combat_event(
                        game_state, "COMBAT_STARTED", state_mgr=state_mgr,
                        actor=state_mgr.get_current_actor() or pl_id,
                        target=defender_id, combat_goal=state_mgr.combat_goal,
                        position_before=current_loc, position_after=current_loc,
                        effect={"combatants": list(order), "initiative": list(order)},
                    )
                    append_combat_event(
                        game_state, "COMBAT_ROUND_STARTED", state_mgr=state_mgr,
                        actor=state_mgr.get_current_actor() or pl_id,
                        combat_goal=state_mgr.combat_goal,
                    )
                sys_log += "【戦闘開始】射撃宣言により戦闘に突入した。\n"
                just_started = True
            else:
                sys_log += "【射撃】攻撃対象が不明なため処理できません。\n"
                return _build_system_action_result(
                    0, sys_log.strip(),
                    {"blocked": True, "kp_instruction": "射撃対象を明確にしてください。"},
                    action_id, None,
                    current_loc=current_loc, scenario_mgr=scenario_mgr,
                    roll_type="blocked", action_target=target,
                )
        if not defender_id:
            sys_log += "【射撃】攻撃対象が不明なため処理できません。\n"
            return _build_system_action_result(
                0, sys_log.strip(),
                {"blocked": True, "kp_instruction": "射撃対象を明確にしてください。"},
                action_id, None,
                current_loc=current_loc, scenario_mgr=scenario_mgr,
                roll_type="blocked", action_target=target,
            )
        begin = begin_shoot_attack(
            pl_id, defender_id,
            skill_name=skill_name,
            char_mgr=char_mgr,
            state_mgr=state_mgr,
            scenario_mgr=scenario_mgr,
            current_loc=current_loc,
            skip_turn_check=just_started,
        )
        if begin.get("pending_combat_defense") is not None and game_state is not None:
            combat_tid = str(
                (game_state.get("last_pl_action") or {}).get("transaction_id")
                or game_state.get("pending_action_id") or ""
            )
            begin["pending_combat_defense"]["transaction_id"] = combat_tid
            state_mgr.set_pending_combat_defense(begin["pending_combat_defense"])
            for row in reversed(game_state.get("unified_event_log") or []):
                if row.get("event_type") == "COMBAT_ACTION_SELECTED" and (
                    not combat_tid or str(row.get("transaction_id") or "") == combat_tid
                ):
                    row["adjudication_id"] = begin["pending_combat_defense"]["adjudication_id"]
                    break
        sys_log += begin.get("log", "") + "\n"
        if begin.get("combat_defense_required"):
            return _build_system_action_result(
                0,
                sys_log.strip(),
                {
                    "kp_instruction": (
                        "射撃が宣言されました。防御側の選択（回避／甘受）を待ってから"
                        "結果を描写してください。応戦は不可です。"
                    ),
                },
                action_id,
                None,
                current_loc=current_loc,
                scenario_mgr=scenario_mgr,
                roll_type="combat_shoot_declare",
                action_target=defender_id,
                combat_defense_required=True,
                pending_combat_defense=begin.get("pending_combat_defense"),
            )
        return _build_system_action_result(
            0, sys_log.strip(),
            {"blocked": True, "kp_instruction": begin.get("log", "射撃を処理できませんでした。")},
            action_id, None,
            current_loc=current_loc, scenario_mgr=scenario_mgr,
            roll_type="blocked", action_target=target,
        )

    # --------------------------------------------------
    # SANチェックの自動解決（神話イベント本命）
    # --------------------------------------------------
    is_san_required = mythos_san_check_pending and (
        san_resolution_only or action_id in SAN_PENDING_ALLOWED_ACTIONS
    )

    if is_san_required:
        char_data = char_mgr.characters.get(pl_id, {})
        current_san = char_mgr.get_stat_current(pl_id, "SAN")

        roll_val = random.randint(1, 100)
        is_success = roll_val <= current_san

        success_loss_formula = _resolve_san_loss_dice(pending_san_check, True)
        failure_loss_formula = _resolve_san_loss_dice(pending_san_check, False)
        resolved_loss_formula = success_loss_formula if is_success else failure_loss_formula
        if is_success:
            loss_val = dice_engine.roll_dice_str(resolved_loss_formula)
            sys_log += f"【SANチェック】1d100 ＞ {roll_val} ＞ 成功（現在値:{current_san}）。正気度が {loss_val} 減少した。\n"
        else:
            loss_val = dice_engine.roll_dice_str(resolved_loss_formula)
            sys_log += f"【SANチェック】1d100 ＞ {roll_val} ＞ 失敗（現在値:{current_san}）。正気度が {loss_val} 減少した！\n"

        sys_log += f"【確定】{char_name} のSAN値が減少しました。\n"

        if state_mgr:
            san_result = state_mgr.apply_san_damage(
                pl_id, loss_val, dice_engine=dice_engine, char_name=char_name,
            )
            if san_result and san_result.get("events"):
                for event_msg in san_result["events"]:
                    sys_log += f"{event_msg}\n"

                if san_result.get("madness_instruction"):
                    mythos_madness_instruction = san_result["madness_instruction"]
        else:
            sys_log += "【システム警告】GameStateManagerが連携されていないため、狂気表の判定はスキップされました。\n"

        madness_instruction = mythos_madness_instruction
        kp_instruction = (
            "【システム確定】SANチェックが自動解決されました。"
            "減少結果と狂気症状を情景描写に組み込んでください。"
            "『どうしますか？』で締めず、恐怖が探索者を支配する描写で締めてください。"
        )
        if mythos_madness_instruction:
            kp_instruction = f"{kp_instruction}\n{mythos_madness_instruction}"

        result = _build_system_action_result(
            0,
            sys_log.strip(),
            {
                "kp_instruction": kp_instruction,
                "san_check": {"required": False},
            },
            "wait",
            None,
            madness_instruction=madness_instruction,
            current_loc=current_loc,
            scenario_mgr=scenario_mgr,
            roll_type="san_check",
            action_target=target,
            san_auto_resolved=True,
        )
        san_after = char_mgr.get_stat_current(pl_id, "SAN")
        result["san"] = {
            "before": current_san,
            "target": current_san,
            "roll": roll_val,
            "result": "SUCCESS" if is_success else "FAILURE",
            "success_loss_formula": success_loss_formula,
            "failure_loss_formula": failure_loss_formula,
            "resolved_loss_formula": resolved_loss_formula,
            "loss": loss_val,
            "after": san_after,
            "trigger_event_id": (pending_san_check or {}).get("trigger_event_id"),
        }
        return _attach_adjudication_evidence(
            result,
            adjudication_id=adjudication_id,
            parent_adjudication_id=parent_adjudication_id,
            actor_id=pl_id,
            target_id=target or pl_id,
            skill_or_stat="SAN",
            dice_result={
                "roll": roll_val,
                "target_value": current_san,
                "success_level": (
                    int(SuccessLevel.REGULAR_SUCCESS) if is_success
                    else int(SuccessLevel.FAILURE)
                ),
            },
            resolution_mode="ROLL",
        )

    required_check = scenario_mgr.get_required_check(action_id, target, current_loc)
    action_difficulty = scenario_mgr.get_action_difficulty(
        action_id, target, current_loc, required_check=required_check,
    )
    skill_modifier = 0
    skill_bonus = 0
    skill_penalty = 0
    dice_result = None
    payload = None
    dice_skipped = False
    roll_type = ""
    proposed_skill = str(skill_name or "").strip()
    engine_judgment_meta = {
        "proposed_skill": proposed_skill,
        "resolved_skill": proposed_skill,
        "skill_overridden": False,
        "difficulty": action_difficulty,
        "allowed_skills": [],
    }

    # --------------------------------------------------
    # usable_actions 強制マッピング（search↔inspect 等）
    # --------------------------------------------------
    if action_id in INVESTIGATION_ACTION_IDS and target:
        coerced = scenario_mgr.coerce_object_action(action_id, target, current_loc)
        if coerced and coerced.get("blocked"):
            scenario_mgr.location = current_loc
            payload = scenario_mgr.finalize_blocked_action(action_id, target, {
                "system_log": coerced.get("log", ""),
                "kp_instruction": coerced.get("kp_instruction", ""),
                "blocked": True,
                "san_check": {"required": False},
            })
            return _build_system_action_result(
                0,
                (sys_log + "\n" + coerced.get("log", "")).strip(),
                payload,
                action_id,
                None,
                current_loc=current_loc,
                scenario_mgr=scenario_mgr,
                roll_type="blocked",
                action_target=target,
            )
        if coerced and coerced.get("remapped"):
            action_id = coerced["action_id"]
            effective_action_id = action_id
            if coerced.get("log"):
                sys_log += coerced["log"] + "\n"

    # --------------------------------------------------
    # タスク3: PL提案 skill をエンジン判定条件で上書き確定
    # --------------------------------------------------
    judgment = resolve_engine_action_judgment(
        scenario_mgr,
        action_id,
        target,
        proposed_skill=proposed_skill,
        loc_id=current_loc,
        char_mgr=char_mgr,
    )
    if judgment.get("action_id"):
        action_id = str(judgment["action_id"] or action_id).lower()
        effective_action_id = action_id
    if judgment.get("log"):
        sys_log += str(judgment["log"]).rstrip() + "\n"
    skill_name = str(judgment.get("skill_name") or "")
    if judgment.get("required_check") is not None:
        required_check = judgment.get("required_check")
    action_difficulty = (
        judgment.get("difficulty")
        or scenario_mgr.get_action_difficulty(
            action_id, target, current_loc, required_check=required_check,
        )
    )
    engine_judgment_meta = {
        "proposed_skill": proposed_skill,
        "resolved_skill": skill_name,
        "skill_overridden": bool(judgment.get("skill_overridden")),
        "difficulty": action_difficulty,
        "allowed_skills": list(judgment.get("allowed_skills") or []),
    }

    # Candidate and executor share the same availability contract.  This runs
    # after canonical rewrites and engine judgment so both sides compare the
    # action that will actually execute.
    if action_id not in ("", "none", "wait", "push_roll", "san_check"):
        source_action = (game_state or {}).get("last_pl_action") or {}
        availability = check_action_availability(
            scenario_mgr,
            actor=pl_id,
            action=action_id,
            target=target,
            location=current_loc,
            state=game_state,
            source=source_action.get("action_origin") or "free_input",
            skill=skill_name,
            pending_san_check=pending_san_check,
            required_location=source_action.get("required_location") or "",
            log_events=game_state is not None,
        )
        compare_candidate_and_execution(
            game_state,
            source_action.get("availability_snapshot"),
            availability,
        )
        if availability.get("status") != ACTION_AVAILABLE:
            detail = availability.get("reason_detail") or "現在の状態では実行できません。"
            payload = scenario_mgr.finalize_blocked_action(action_id, target, {
                "system_log": f"【Action Availability】{detail}",
                "kp_instruction": detail,
                "blocked": True,
                "no_roll": bool(availability.get("no_roll")),
                "availability": availability,
                "san_check": {"required": False},
            })
            return _build_system_action_result(
                0, payload.get("system_log", ""), payload, action_id, None,
                current_loc=current_loc, scenario_mgr=scenario_mgr,
                roll_type=("no_roll" if availability.get("no_roll") else "blocked"),
                action_target=target,
            )

    # Investigation Flow: scenario-first adjudication plus per-PC attempt rights.
    # Combat paths never enter this block.
    investigation_action = action_id
    investigation_skill = proposed_skill
    investigation_is_push = False
    if action_id == "push_roll" and pending_push_roll:
        investigation_action = str(pending_push_roll.get("original_action") or "search")
        investigation_skill = str(pending_push_roll.get("skill_name") or skill_name or "")
        investigation_is_push = investigation_action in FLOW_INVESTIGATION_ACTIONS
    if game_state is not None and (
        action_id in FLOW_INVESTIGATION_ACTIONS or investigation_is_push
    ) and target:
        source_action = (game_state.get("last_pl_action") or {})
        investigation_context = prepare_investigation(
            game_state,
            scenario_mgr,
            actor_id=pl_id,
            action_id=investigation_action,
            target=target,
            location=current_loc,
            proposed_skill=investigation_skill,
            proposal_reason=str(source_action.get("skill_proposal_reason") or ""),
            kp_selected_skill=str(source_action.get("kp_selected_skill") or ""),
            kp_no_roll=bool(source_action.get("kp_no_roll")),
            is_push=investigation_is_push,
        )
        investigation_context["adjudication_id"] = adjudication_id
        investigation_context["parent_adjudication_id"] = parent_adjudication_id or None
        # The dedicated adjudicator is authoritative for investigation skills.
        skill_name = str(investigation_context.get("selected_skill") or "")
        if investigation_context.get("required_check") is not None:
            required_check = investigation_context.get("required_check")
        engine_judgment_meta.update({
            "resolved_skill": skill_name,
            "adjudication": investigation_context.get("adjudication"),
            "proposal_reason": investigation_context.get("proposal_reason", ""),
        })
        if not investigation_context.get("attempt_allowed"):
            block_text = investigation_context.get("attempt_block_reason")
            blocked_result = _build_system_action_result(
                0,
                f"【試行権消費済み】{block_text}",
                {
                    "blocked": True,
                    "kp_instruction": block_text,
                    "san_check": {"required": False},
                },
                investigation_action,
                None,
                current_loc=current_loc,
                scenario_mgr=scenario_mgr,
                roll_type="blocked",
                action_target=target,
            )
            blocked_result["investigation"] = investigation_context
            blocked_result["engine_judgment"] = dict(engine_judgment_meta)
            blocked_result["skill_name"] = skill_name
            return blocked_result

    # --------------------------------------------------
    # ダイスロール前ブロック（探索済み・空オブジェクト・行動制約）
    # --------------------------------------------------
    if action_id not in ("push_roll", "wait", "", "none"):
        pre_block = scenario_mgr.evaluate_pre_action_guard(
            action_id, target, current_loc, pending_san_check=None,
        )
        if pre_block:
            if pre_block.get("_effective_action_id"):
                action_id = pre_block["_effective_action_id"]
                effective_action_id = action_id
            scenario_mgr.location = current_loc
            payload = scenario_mgr.finalize_blocked_action(action_id, target, pre_block)
            success_level = 0
            new_pending_push_roll = None
            dice_skipped = True
            roll_type = "no_roll" if pre_block.get("no_roll") else "blocked"

    # --------------------------------------------------
    # プッシュロール処理
    # --------------------------------------------------
    if not dice_skipped and action_id == "push_roll":
        if in_combat:
            sys_log += "【ルール】戦闘中はプッシュロールできません（クイックスタート戦闘ルール）。\n"
            success_level = int(SuccessLevel.FAILURE)
            payload = None
            new_pending_push_roll = None
        elif not pending_push_roll:
            sys_log += "【エラー】プッシュロールの対象がありません。通常の行動を選択してください。\n"
            success_level = int(SuccessLevel.FAILURE)
            payload = None
        else:
            skill_name = pending_push_roll.get("skill_name", skill_name)
            target = pending_push_roll.get("target", target) or target
            push_obj = scenario_mgr.get_object_info(current_loc, target) if scenario_mgr else {}
            if scenario_mgr and scenario_mgr.is_empty_clue_object(push_obj):
                sys_log += (
                    "【システム】手がかりのない対象へのプッシュロールは無意味です。"
                    "ダイスは振られません。\n"
                )
                payload = {
                    "system_log": sys_log.strip(),
                    "kp_instruction": (
                        "空オブジェクトへの執着をやめさせ、人物会話や他手がかり・移動へ誘導せよ。"
                    ),
                    "blocked": True,
                    "no_roll": True,
                    "empty_clue": True,
                    "san_check": {"required": False},
                }
                return _build_system_action_result(
                    0, sys_log.strip(), payload, action_id, None,
                    current_loc=current_loc, scenario_mgr=scenario_mgr,
                    roll_type="no_roll", action_target=target,
                )
            effective_action_id = pending_push_roll.get("original_action", action_id)
            skill_modifier = pending_push_roll.get("modifier", 0)
            skill_bonus = pending_push_roll.get("bonus_dice", 0)
            skill_penalty = pending_push_roll.get("penalty_dice", 0)
            push_difficulty = pending_push_roll.get("required_difficulty", action_difficulty)

            skill_value, roll_identity = _resolve_authoritative_roll_value(
                char_mgr, pl_id, skill_name,
            )
            dice_result = dice_engine.execute_push_roll(
                char_name,
                skill_name,
                skill_value,
                modifier=skill_modifier,
                bonus_dice=skill_bonus,
                penalty_dice=skill_penalty,
                required_difficulty=push_difficulty,
                allow_zero=roll_identity.get("legal_zero", False),
            )
            if sys_log:
                sys_log += "\n"
            sys_log += dice_result.get("log", "")

            success_level = dice_result.get("success_level", int(SuccessLevel.FAILURE))

            if dice_result.get("is_push_fail"):
                if state_mgr and hasattr(state_mgr, "apply_push_failure_penalty"):
                    penalty = state_mgr.apply_push_failure_penalty(
                        pl_id, dice_engine=dice_engine, char_name=char_name,
                    )
                else:
                    push_san_loss = dice_engine.roll_dice_str("1d3")
                    penalty = {
                        "log": (
                            f"【プッシュロール失敗・恐ろしい結果】正気度が {push_san_loss} 減少。"
                            "状況が急激に悪化した。"
                        ),
                        "events": [],
                        "madness_instruction": "",
                        "kp_instruction": (
                            "【プッシュロール失敗・恐ろしい結果・KP確定指示】"
                            "探索者の再挑戦は惨敗に終わった。取り返しのつかない悪化を容赦なく描写せよ。"
                        ),
                    }
                    if state_mgr:
                        push_fail_san_result = state_mgr.apply_san_damage(
                            pl_id, push_san_loss, dice_engine=dice_engine, char_name=char_name,
                        )
                        if push_fail_san_result:
                            penalty["events"] = push_fail_san_result.get("events") or []
                            penalty["madness_instruction"] = (
                                push_fail_san_result.get("madness_instruction") or ""
                            )

                if sys_log:
                    sys_log += "\n"
                sys_log += penalty.get("log", "")
                for event_msg in penalty.get("events") or []:
                    sys_log += f"\n{event_msg}"
                push_fail_madness_instruction = penalty.get("madness_instruction") or ""
                push_fail_penalty_instruction = penalty.get("kp_instruction") or (
                    "【プッシュロール失敗・恐ろしい結果・KP確定指示】"
                    "探索者の再挑戦は惨敗に終わった。"
                    "取り返しのつかない悪化を容赦なく描写せよ。"
                )
                if push_fail_madness_instruction:
                    push_fail_penalty_instruction = (
                        f"{push_fail_penalty_instruction}\n{push_fail_madness_instruction}"
                    )

            new_pending_push_roll = None
            roll_type = "skill"
            if (
                is_success_level(success_level)
                and skill_name
                and roll_identity.get("kind") == "SKILL"
            ):
                char_mgr.mark_skill_success(pl_id, skill_name)

    elif not dice_skipped and required_check and required_check.get("type") == "luck":
        luck_value = char_mgr.get_luck(pl_id)
        dice_result = dice_engine.execute_luck_roll(char_name, luck_value)
        if sys_log:
            sys_log += "\n"
        sys_log += dice_result.get("log", "")
        success_level = dice_result.get(
            "success_level",
            int(SuccessLevel.REGULAR_SUCCESS) if dice_result.get("success") else int(SuccessLevel.FAILURE),
        )
        new_pending_push_roll = None
        roll_type = "luck"

    elif not dice_skipped and required_check and required_check.get("type") == "opposed_skill":
        opp_skill = required_check.get("opponent_skill", "心理学")
        opp_value = required_check.get("opponent_value", 50)
        opp_name = required_check.get("label", target)
        skill_value = char_mgr.get_skill(pl_id, skill_name or required_check.get("skill_name", ""))
        if not skill_name:
            skill_name = required_check.get("skill_name", skill_name)
        dice_result = dice_engine.execute_opposed_skill_roll(
            char_name, skill_name, skill_value,
            opp_name, opp_skill, opp_value,
            attacker_bonus=required_check.get("bonus_dice", 0),
            attacker_penalty=required_check.get("penalty_dice", 0),
            defender_bonus=required_check.get("defender_bonus_dice", 0),
            defender_penalty=required_check.get("defender_penalty_dice", 0),
            required_difficulty=action_difficulty,
        )
        if sys_log:
            sys_log += "\n"
        sys_log += dice_result.get("log", "")
        success_level = dice_result.get("success_level", int(SuccessLevel.FAILURE))
        if is_success_level(success_level) and skill_name:
            char_mgr.mark_skill_success(pl_id, skill_name)
        new_pending_push_roll = None
        roll_type = "opposed_skill"

    elif not dice_skipped and required_check and required_check.get("type") == "skill":
        # タスク3: エンジン確定技能を常に優先（PL提案では上書きしない）
        skill_name = required_check.get("skill_name") or skill_name
        skill_penalty = required_check.get("penalty_dice", 0)
        skill_bonus = required_check.get("bonus_dice", 0)
        skill_modifier = required_check.get("modifier", 0)
        if required_check.get("difficulty"):
            action_difficulty = normalize_difficulty(required_check.get("difficulty"))
        engine_judgment_meta["resolved_skill"] = skill_name
        engine_judgment_meta["difficulty"] = action_difficulty

        skill_value, roll_identity = _resolve_authoritative_roll_value(
            char_mgr, pl_id, skill_name,
        )
        dice_result = dice_engine.execute_skill_roll(
            char_name,
            skill_name,
            skill_value,
            modifier=skill_modifier,
            bonus_dice=skill_bonus,
            penalty_dice=skill_penalty,
            required_difficulty=action_difficulty,
            allow_zero=roll_identity.get("legal_zero", False),
        )
        if sys_log:
            sys_log += "\n"
        sys_log += dice_result.get("log", "")

        success_level, pending_luck_burn, push_from_fail = _apply_skill_roll_outcome(
            dice_result, char_mgr, pl_id, target, skill_name, action_id,
            skill_modifier, skill_bonus, skill_penalty,
            in_combat=in_combat,
            required_difficulty=action_difficulty,
            mark_success=roll_identity.get("kind") == "SKILL",
        )
        if is_success_level(success_level) and state_mgr and skill_name == "応急手当":
            fa = state_mgr.process_first_aid(pl_id, within_hour=(required_check or {}).get("within_hour", True))
            if fa.get("status") == "success":
                sys_log += f"\n【応急手当効果】HP+{fa.get('recovered_hp', 0)}（現在{fa.get('new_hp')}）"
        elif is_success_level(success_level) and state_mgr and skill_name == "医学":
            med = state_mgr.process_medicine(pl_id, dice_engine=dice_engine)
            if med.get("status") == "success":
                sys_log += (
                    f"\n【医学効果】1D3={med.get('rolled')} → HP+{med.get('recovered_hp', 0)}"
                    f"（現在{med.get('new_hp')}）"
                )
        new_pending_push_roll = push_from_fail
        roll_type = "skill"

    elif not dice_skipped and required_check and required_check.get("type") == "no_roll":
        # 空オブジェクト等: ダイスなし
        skill_name = ""
        success_level = int(SuccessLevel.REGULAR_SUCCESS)
        dice_skipped = True
        roll_type = "no_roll"
        if "空" not in sys_log and "ロール" not in sys_log:
            sys_log += (
                "【システム】この対象はロール判定を必要としません。"
                "シナリオ定義に従い、ダイスを振らずに処理します。\n"
            )

    elif not dice_skipped and skill_name and action_id in INVESTIGATION_ACTION_IDS:
        skill_value, roll_identity = _resolve_authoritative_roll_value(
            char_mgr, pl_id, skill_name,
        )
        dice_result = dice_engine.execute_skill_roll(
            char_name,
            skill_name,
            skill_value,
            modifier=skill_modifier,
            bonus_dice=skill_bonus,
            penalty_dice=skill_penalty,
            required_difficulty=action_difficulty,
            allow_zero=roll_identity.get("legal_zero", False),
        )
        if sys_log:
            sys_log += "\n"
        sys_log += dice_result.get("log", "")

        success_level, pending_luck_burn, push_from_fail = _apply_skill_roll_outcome(
            dice_result, char_mgr, pl_id, target, skill_name, action_id,
            skill_modifier, skill_bonus, skill_penalty,
            in_combat=in_combat,
            required_difficulty=action_difficulty,
            mark_success=roll_identity.get("kind") == "SKILL",
        )
        if is_success_level(success_level) and state_mgr and skill_name == "応急手当":
            fa = state_mgr.process_first_aid(pl_id, within_hour=(required_check or {}).get("within_hour", True))
            if fa.get("status") == "success":
                sys_log += f"\n【応急手当効果】HP+{fa.get('recovered_hp', 0)}（現在{fa.get('new_hp')}）"
        elif is_success_level(success_level) and state_mgr and skill_name == "医学":
            med = state_mgr.process_medicine(pl_id, dice_engine=dice_engine)
            if med.get("status") == "success":
                sys_log += (
                    f"\n【医学効果】1D3={med.get('rolled')} → HP+{med.get('recovered_hp', 0)}"
                    f"（現在{med.get('new_hp')}）"
                )
        new_pending_push_roll = push_from_fail
        roll_type = "skill"

    elif not dice_skipped and required_check and required_check.get("type") == "auto_success":
        success_level = required_check.get(
            "success_level", int(SuccessLevel.EXTREME_SUCCESS),
        )
        log_msg = required_check.get(
            "log_message",
            "【自動成功】判定を省略し、行動は成功した。",
        )
        if sys_log:
            sys_log += "\n"
        sys_log += log_msg
        new_pending_push_roll = None
        roll_type = "auto_success"

    elif not dice_skipped and required_check and required_check.get("type") == "opposed_str":
        char_str = char_mgr.get_attribute(pl_id, "STR") or 0
        opp_str = required_check.get("opponent_value", 50)
        opp_name = required_check.get("label", target)
        dice_result = dice_engine.execute_opposed_str_roll(
            char_name,
            char_str,
            opp_name,
            opp_str,
            penalty_dice=required_check.get("penalty_dice", 0),
            bonus_dice=required_check.get("bonus_dice", 0),
            required_difficulty=action_difficulty,
        )
        if sys_log:
            sys_log += "\n"
        sys_log += dice_result.get("log", "")
        success_level = dice_result.get("success_level", int(SuccessLevel.FAILURE))
        new_pending_push_roll = None
        roll_type = "opposed_str"
    elif not dice_skipped:
        # Fail-closed: combat / irreversible actions must not auto-succeed.
        try:
            res_class = declare_resolution_class(
                resolution_class=str((payload or {}).get("resolution_class") or ""),
                in_combat=in_combat,
                action_id=effective_action_id,
                target=target,
                payload=payload or {},
                roll_type="none",
                dice_skipped=True,
            )
        except CombatResolutionError as exc:
            blocked_payload = scenario_mgr.finalize_blocked_action(
                effective_action_id, target, {
                    "system_log": f"【システムブロック】{exc.code}: 戦闘中の状態変更には明示的な判定が必要です。",
                    "kp_instruction": (
                        "戦闘アクションが未解決です。ROLL / EXPLICIT_NO_ROLL / "
                        "DETERMINISTIC_RULE のいずれかを宣言してください。"
                    ),
                    "blocked": True,
                    "blocked_reason": UNRESOLVED_COMBAT_ACTION,
                    "san_check": {"required": False},
                },
            ) if scenario_mgr else {
                "blocked": True,
                "blocked_reason": UNRESOLVED_COMBAT_ACTION,
                "system_log": f"【システムブロック】{exc.code}",
            }
            return _build_system_action_result(
                0,
                blocked_payload.get("system_log", str(exc)),
                blocked_payload,
                effective_action_id,
                None,
                current_loc=current_loc,
                scenario_mgr=scenario_mgr,
                roll_type="blocked",
                action_target=target,
            )
        if res_class in {EXPLICIT_NO_ROLL, DETERMINISTIC_RULE}:
            success_level = int(SuccessLevel.REGULAR_SUCCESS)
            if not sys_log:
                sys_log = "判定なし（明示契約による成功）"
            roll_type = "no_roll" if res_class == EXPLICIT_NO_ROLL else "auto_success"
        elif not in_combat and not is_irreversible_candidate(
            effective_action_id, target, in_combat=False, payload=payload or {},
        ):
            # Legacy non-combat fallthrough (empty clues / trivial moves, etc.).
            success_level = int(SuccessLevel.REGULAR_SUCCESS)
            if not sys_log:
                sys_log = "判定なし（自動成功）"
            roll_type = "none"
        else:
            blocked_payload = {
                "blocked": True,
                "blocked_reason": UNRESOLVED_COMBAT_ACTION,
                "system_log": "【システムブロック】UNRESOLVED_COMBAT_ACTION",
                "san_check": {"required": False},
            }
            return _build_system_action_result(
                0, blocked_payload["system_log"], blocked_payload,
                effective_action_id, None,
                current_loc=current_loc, scenario_mgr=scenario_mgr,
                roll_type="blocked", action_target=target,
            )

    # 幸運消費の判断待ち：シナリオ処理を保留して PL に委ねる
    if pending_luck_burn:
        pending_luck_burn = dict(pending_luck_burn)
        pending_luck_burn["adjudication_id"] = adjudication_id
        pending_luck_burn["parent_adjudication_id"] = parent_adjudication_id or None
        pending_luck_burn["raw_result"] = _success_level_name(success_level)
        pending_luck_burn["roll"] = (dice_result or {}).get("roll")
        pending_luck_burn["target_value"] = (dice_result or {}).get("target_value")
        pending_result = _build_system_action_result(
            success_level,
            sys_log,
            None,
            effective_action_id,
            new_pending_push_roll,
            madness_instruction=madness_instruction,
            push_fail_penalty_instruction=push_fail_penalty_instruction,
            current_loc=current_loc,
            scenario_mgr=scenario_mgr,
            luck_decision_required=True,
            pending_luck_burn=pending_luck_burn,
            roll_type=roll_type or "skill",
            action_target=target,
        )
        if investigation_context:
            pending_result["investigation"] = investigation_context
            pending_result["engine_judgment"] = dict(engine_judgment_meta)
            pending_result["skill_name"] = skill_name
        return _attach_adjudication_evidence(
            pending_result, adjudication_id=adjudication_id,
            parent_adjudication_id=parent_adjudication_id,
            actor_id=pl_id, target_id=target, skill_or_stat=skill_name,
            dice_result=dice_result, resolution_mode="ROLL",
        )

    # プッシュ決定待ち：シナリオ結果確定前に保留（幸運と同様）
    if (
        new_pending_push_roll
        and new_pending_push_roll.get("decision_pending", True)
        and action_id != "push_roll"
        and not dice_skipped
        and is_failure_level(success_level)
    ):
        pending_result = _build_system_action_result(
            success_level,
            sys_log,
            None,
            effective_action_id,
            new_pending_push_roll,
            madness_instruction=madness_instruction,
            push_fail_penalty_instruction=push_fail_penalty_instruction,
            current_loc=current_loc,
            scenario_mgr=scenario_mgr,
            push_decision_required=True,
            roll_type=roll_type or "skill",
            action_target=target,
        )
        if investigation_context:
            pending_result["investigation"] = investigation_context
            pending_result["engine_judgment"] = dict(engine_judgment_meta)
            pending_result["skill_name"] = skill_name
        pending_result = _attach_adjudication_evidence(
            pending_result, adjudication_id=adjudication_id,
            parent_adjudication_id=parent_adjudication_id,
            actor_id=pl_id, target_id=target, skill_or_stat=skill_name,
            dice_result=dice_result, resolution_mode="ROLL",
        )
        if pending_result.get("pending_push_roll"):
            pending_result["pending_push_roll"].update(
                copy.deepcopy(pending_result.get("adjudication") or {})
            )
        return pending_result

    scenario_mgr.location = current_loc
    if not dice_skipped and payload is None and not (action_id == "push_roll" and not pending_push_roll):
        payload = scenario_mgr.process_action(effective_action_id, target, success_level)

    if payload and state_mgr:
        payload = dict(payload)
        payload["adjudication_id"] = adjudication_id
        payload.setdefault("target", target)
        payload.setdefault("selected_action", effective_action_id)
        payload["resolution_mode"] = (
            "NO_ROLL" if dice_skipped or roll_type in {"none", "no_roll", "auto_success"} else "ROLL"
        )
        active = getattr(char_mgr, "active_pc_list", None) or [pl_id]
        sys_log = _apply_combat_payload_effects(
            payload, state_mgr, char_mgr, pl_id, sys_log, active_pcs=active,
            game_state=game_state, current_loc=current_loc,
        )

    result = _build_system_action_result(
        success_level,
        sys_log,
        payload,
        action_id,
        new_pending_push_roll,
        madness_instruction=madness_instruction or push_fail_madness_instruction,
        push_fail_penalty_instruction=push_fail_penalty_instruction,
        current_loc=current_loc,
        scenario_mgr=scenario_mgr,
        roll_type=roll_type,
        action_target=target,
    )
    result["engine_judgment"] = dict(engine_judgment_meta)
    result["skill_name"] = (
        engine_judgment_meta.get("resolved_skill")
        or skill_name
        or result.get("skill_name")
        or ""
    )
    if investigation_context:
        result["investigation"] = investigation_context
    resolution_mode = "NO_ROLL" if dice_skipped or roll_type in {"none", "no_roll", "auto_success"} else "ROLL"
    result = _attach_adjudication_evidence(
        result,
        adjudication_id=adjudication_id,
        parent_adjudication_id=parent_adjudication_id,
        actor_id=pl_id,
        target_id=target,
        skill_or_stat=skill_name or (required_check or {}).get("type", ""),
        dice_result=dice_result,
        resolution_mode=resolution_mode,
    )
    result = _as_simple_move_lifecycle(
        result, action_id=effective_action_id, from_location=current_loc,
    )
    # move 成功時: 旧ロケ宛未処理キューを必ず破棄（呼び出し側漏れ防止の SSOT）
    if game_state is not None:
        apply_location_change_side_effects(
            game_state, result, scenario_mgr=scenario_mgr, char_mgr=char_mgr,
        )
    return result


def apply_location_change_side_effects(state, result, *, scenario_mgr=None, char_mgr=None):
    """
    location_changed / new_location 時の共通後処理。
    - 常に: current_loc 更新 + 未処理アクション破棄
    - scenario_mgr があるときだけ: シナリオ依存のループ警告
    冪等（二重呼び出し可）。
    """
    if not state or not result:
        return False
    if not (result.get("location_changed") or result.get("new_location")):
        return False
    new_loc = result.get("new_location")
    if not new_loc and scenario_mgr:
        new_loc = getattr(scenario_mgr, "location", None)
    if not new_loc:
        return False

    old_loc = (
        result.get("from_location")
        or state.get("current_loc")
        or ""
    )
    state["current_loc"] = new_loc
    if scenario_mgr is not None:
        reconcile_location(state, scenario_mgr, canonical=new_loc)

    invalidate_pending_actions_after_location_change(
        state,
        old_loc=old_loc,
        new_loc=new_loc,
        scenario_mgr=scenario_mgr,
        char_mgr=char_mgr,
    )
    # シナリオ依存の警告はマネージャーが無いと意味がないため明示的にスキップ
    if scenario_mgr is not None:
        _maybe_inject_location_loop_warning(state, scenario_mgr)
    return True


# ==========================================
# 6. タイムライン駆動型フリーチャットシステム
# ==========================================
# Streamlit は 1 rerun = 1 ティック。PL/System/KP・失敗再試行も消費するため、
# 25 だと導入〜調査序盤で安全停止してしまう。無進行連続の上限として大きめに取る。
MAX_AUTONOMOUS_ITERATIONS = 100
# 同一話者が連続しても、膠着6ターンより先にセッション停止しない。
# 超過時は手番交代＋マイルド通知のみ（カウンタを閾値へ上書きしない）。
MAX_CONSECUTIVE_SAME_SPEAKER = 5
MAX_CHAT_ROUNDS_WITHOUT_PROGRESS = FORCE_IC_ACTION_CHAT_ROUNDS
MAX_TIMELINE_CHAIN = 8

USER_STOP_LOG_TEXT = "[システム] ユーザーによりセッションが一時停止されました。"
MAX_ITERATIONS_PAUSE_LOG_TEXT = (
    "[システム] 自律巡航が安全上限に達したため一時停止しました。"
    "（場所・進行フラグに変化がないティックが連続したためです。"
    "「自律巡航を再開」で続行できます。）"
)
EMPTY_TICK_PAUSE_LOG_TEXT = (
    "[システム] ログが更新されない状態が続いたため、自律巡航を一時停止しました。"
    "（Ollama の応答待ち・モデル未起動・行動不能状態などが考えられます。"
    "ターミナルの [LLM API エラー] を確認し、「自律巡航を再開」で続行できます。）"
)
PL_TURN_SILENT_FALLBACK_LOG = (
    "[システム] PLは一拍置いて状況を見極めている（時間経過）。"
)

ACTIONS_NEEDING_SYSTEM = frozenset({
    "search", "inspect", "move", "push", "push_roll", "climb", "break", "use", "kick", "force",
    "attack", "shoot", "fire", "gunshot", "射撃",
    "talk", "speak", "chat", "converse", "対話", "会話", "話す",
    "negotiate", "persuade", "intimidate", "charm", "fast_talk",
    "psychology", "insight",
    "説得", "言いくるめ", "威圧", "魅惑", "心理学",
})


def is_chat_only_pl_action(pc_action, pending_san_check=None):
    """純粋チャット（待機・リアクション）かどうか。システム介入不要なら True。"""
    if _is_san_check_pending(pending_san_check):
        return False
    action = str((pc_action or {}).get("action", "wait") or "wait").lower()
    return action not in ACTIONS_NEEDING_SYSTEM


def is_nonprogress_pl_action(
    pc_action,
    pending_san_check=None,
    scenario_mgr=None,
    current_loc=None,
    char_mgr=None,
):
    """wait / 膠着 talk など、進行に寄与しない PL 行動か。"""
    if is_chat_only_pl_action(pc_action, pending_san_check):
        return True
    action = str((pc_action or {}).get("action", "wait") or "wait").lower()
    target = str((pc_action or {}).get("target", "") or "")
    loc = current_loc
    if loc is None and scenario_mgr is not None:
        loc = getattr(scenario_mgr, "location", "") or ""
    return is_stale_nonprogress_talk(
        action, target, scenario_mgr=scenario_mgr,
        current_loc=str(loc or ""), char_mgr=char_mgr,
    )


def get_stagnation_streak(state=None, state_mgr=None):
    """膠着ストリーク（game_state tracker 優先）。"""
    if state_mgr and getattr(state_mgr, "stagnation_tracker", None):
        return int((state_mgr.stagnation_tracker or {}).get("streak") or 0)
    if state:
        return int(state.get("stagnation_streak") or 0)
    return 0


def get_chat_rounds_without_action(state=None, guard=None):
    """OOC/待機のみの連続ラウンド数。"""
    if guard is not None:
        return int(getattr(guard, "chat_rounds_without_action", 0) or 0)
    if state and isinstance(state.get("autonomous_guard"), dict):
        return int((state.get("autonomous_guard") or {}).get("chat_rounds_without_action") or 0)
    return 0


def is_force_ic_action_phase(state=None, state_mgr=None, guard=None):
    """
    OOC膠着の強制 IC 行動フェーズか。
    chat_rounds >= 6 または stagnation streak > 5 で発火。
    """
    if state and state.get("force_ic_action"):
        return True
    chat_rounds = get_chat_rounds_without_action(state=state, guard=guard)
    streak = get_stagnation_streak(state=state, state_mgr=state_mgr)
    return (
        chat_rounds >= FORCE_IC_ACTION_CHAT_ROUNDS
        or streak > FORCE_IC_ACTION_STAGNATION_STREAK
    )


def ensure_force_ic_action_phase(state, state_mgr=None, guard=None):
    """強制 IC フェーズを有効化し、警告をログ／PLヒントへ注入する。"""
    if not is_force_ic_action_phase(state, state_mgr=state_mgr, guard=guard):
        return False
    state["force_ic_action"] = True
    # 許可取得後は search 誘導を優先（汎用 OOC 警告で上書きしない）
    existing = str(state.get("stagnation_pl_hint") or "")
    if "reference_room_clipping_files" in existing or "許可は取得済み" in existing:
        pass
    else:
        state["stagnation_pl_hint"] = OOC_LOOP_FORCE_ACTION_WARNING
    logs = state.setdefault("all_events_log", [])
    already = any(
        (entry.get("meta") or {}).get("force_ic_action")
        for entry in logs[-12:]
    )
    if not already:
        logs.append({
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": f"[システム] {OOC_LOOP_FORCE_ACTION_WARNING}",
            "meta": {"force_ic_action": True, "ooc_blocked": True},
        })
    if state_mgr and hasattr(state_mgr, "mark_stagnation_intervened"):
        tracker = getattr(state_mgr, "stagnation_tracker", None) or {}
        streak = int(tracker.get("streak") or 0)
        intervened_at = int(tracker.get("intervened_at_streak") or 0)
        if streak > 0 and intervened_at < streak:
            state_mgr.mark_stagnation_intervened()
    return True


def clear_force_ic_action_phase(state):
    """有効な IC 行動後に強制フェーズを解除する。"""
    state["force_ic_action"] = False
    if state.get("stagnation_pl_hint") == OOC_LOOP_FORCE_ACTION_WARNING:
        state["stagnation_pl_hint"] = None
    # chat_rounds_without_action をリセット
    guard = state.get("autonomous_guard")
    if isinstance(guard, dict):
        guard = dict(guard)
        guard["chat_rounds_without_action"] = 0
        state["autonomous_guard"] = guard


def apply_forced_progress_breakout(state, managers, *, pl_id, char_name):
    """
    ヒント提示済みかつ膠着上限到達時の最終防壁。
    PL 出力を無視し、解放済み exit への move（または代替 search）を発行・実行する。
    導入以外のロケーションでも同じロジックを使う。
    """
    char_mgr, dice_engine, state_mgr, scenario_mgr = managers
    current_loc = state.get("current_loc") or getattr(scenario_mgr, "location", "") or ""
    forced = build_forced_progress_action(
        scenario_mgr, current_loc, char_name=char_name,
    )
    if not forced:
        return None

    action_id = str(forced.get("action") or "move").lower()
    dest = forced["target"]
    if action_id == "move" and scenario_mgr:
        dest_label = scenario_mgr.get_location_info(dest).get("name", dest)
        breakout_note = f"{FORCE_PROGRESS_BREAKOUT_LOG}（目的地: {dest_label} / `{dest}`）"
    else:
        obj_name = dest
        if scenario_mgr:
            obj_name = (scenario_mgr.get_object_info(current_loc, dest) or {}).get("name", dest)
        breakout_note = (
            f"[システム] 膠着が上限に達したため、次の有効行動を強制実行します。"
            f"（`{action_id}` / `{dest}` / {obj_name}）"
        )

    state.setdefault("all_events_log", []).append({
        "channel": "OOC",
        "location": "all",
        "secret_to": None,
        "text": breakout_note,
        "meta": {
            "forced_progress_breakout": True,
            "target": dest,
            "action": action_id,
        },
    })

    # 移動前に未処理キューを破棄（幽霊NPC防止）
    if action_id == "move":
        invalidate_pending_actions_after_location_change(
            state,
            old_loc=current_loc,
            new_loc=dest,
            scenario_mgr=scenario_mgr,
            char_mgr=char_mgr,
        )

    pc_prefix = (
        format_pc_log_prefix(char_mgr, pl_id, role="PC")
        if char_mgr and pl_id else f"{char_name}(PC)"
    )
    state["all_events_log"].append({
        "channel": "IC",
        "location": current_loc,
        "secret_to": None,
        "text": f"{pc_prefix}: {forced.get('message') or forced.get('dialogue')}",
        "meta": {
            "pc_id": pl_id,
            "action_id": action_id,
            "target": dest,
            "skill": forced.get("skill") or "",
            "needs_system": True,
            "system_processed": True,
            "forced_by_system": True,
            "action_origin": SYSTEM_FORCED,
        },
    })

    result = process_system_action(
        pl_id, char_name, action_id, dest, forced.get("skill") or "",
        current_loc, char_mgr, dice_engine, scenario_mgr,
        state_mgr=state_mgr,
        game_state=state,
    )
    result = ensure_lifecycle_relation_id(result, actor_id=pl_id)
    append_system_log_entry(
        state["all_events_log"],
        current_loc,
        result.get("log", ""),
        action_id=action_id,
        target=dest,
        roll_type=result.get("roll_type", action_id),
        adjudication=result,
        actor_id=result.get("lifecycle_actor_id") or pl_id,
    )
    # process_system_action(game_state=) で current_loc / キュー破棄済み。保険で再同期。
    apply_location_change_side_effects(
        state, result, scenario_mgr=scenario_mgr, char_mgr=char_mgr,
    )
    if not result.get("new_location") and scenario_mgr and getattr(scenario_mgr, "location", None):
        if action_id != "move":
            state["current_loc"] = scenario_mgr.location

    forced["action_origin"] = SYSTEM_FORCED
    forced["actor_id"] = result.get("lifecycle_actor_id") or pl_id
    state["last_pl_action"] = forced
    state["last_system_result"] = result
    record_unified_turn(
        state, scenario_mgr, state_mgr=state_mgr, char_mgr=char_mgr,
        result=result, action=forced, origin=SYSTEM_FORCED,
    )
    clear_force_ic_action_phase(state)
    state["stagnation_pl_hint"] = None
    if state_mgr:
        state_mgr.reset_stagnation_tracker(state.get("current_loc"), scenario_mgr.flags)
        state_mgr.mark_stagnation_intervened()
    if scenario_mgr and hasattr(scenario_mgr, "reset_stagnation_counter"):
        scenario_mgr.reset_stagnation_counter()
    state["stagnation_streak"] = 0
    return forced


def invalidate_pending_actions_after_location_change(
    state,
    *,
    old_loc="",
    new_loc="",
    scenario_mgr=None,
    char_mgr=None,
):
    """
    ロケーション移動直後に、旧ロケ宛て／現在地にいないNPC宛ての未処理アクションを破棄する。
    幽霊NPC対話の物理遮断。
    """
    if not state:
        return 0
    logs = state.get("all_events_log") or []
    invalid_npcs = set()
    if scenario_mgr and hasattr(scenario_mgr, "build_location_change_invalidation"):
        meta = scenario_mgr.build_location_change_invalidation(old_loc, new_loc)
        invalid_npcs = set(meta.get("invalid_npc_ids") or [])
    # Knott は導入専用: どこへ移動しても破棄対象に含める
    invalid_npcs.update({"steven_knott", "npc_steven_knott", "mr_knott"})

    cleared = 0
    for entry in logs:
        meta = entry.get("meta") or {}
        if not meta.get("needs_system") or meta.get("system_processed"):
            continue
        if meta.get("forced_by_system"):
            continue
        # The successful move is still in-flight during executor-side cleanup.
        if entry is state.get("_pending_system_pl_entry"):
            continue
        if (meta.get("action_id") == "move"
                and meta.get("target") == new_loc
                and meta.get("transaction_id")
                and meta.get("transaction_id") == state.get("pending_action_id")):
            continue
        action_id = str(meta.get("action_id") or meta.get("action") or "").lower()
        target = str(meta.get("target") or "")
        entry_loc = str(entry.get("location") or "")

        should_clear = False
        if old_loc and entry_loc and entry_loc == old_loc and entry_loc != new_loc:
            should_clear = True
        if action_id in ("talk", "speak", "chat", "converse", "persuade",
                         "fast_talk", "intimidate", "charm", "psychology"):
            npc_id = ""
            if char_mgr:
                npc_id = find_npc_id_by_target(char_mgr, target) or ""
            npc_id = npc_id or resolve_social_npc_id(target, char_mgr=char_mgr) or target
            if npc_id in invalid_npcs:
                should_clear = True
            elif scenario_mgr and new_loc and hasattr(scenario_mgr, "is_npc_at_location"):
                if npc_id and not scenario_mgr.is_npc_at_location(npc_id, new_loc):
                    should_clear = True

        if should_clear:
            meta = dict(meta)
            meta["system_processed"] = True
            meta["invalidated_by_move"] = True
            meta["invalidated_from"] = old_loc
            meta["invalidated_to"] = new_loc
            entry["meta"] = meta
            cleared += 1

    # last_pl_action も旧ロケNPC宛てなら無効化
    last = state.get("last_pl_action")
    if isinstance(last, dict):
        last_action = str(last.get("action") or "").lower()
        last_target = str(last.get("target") or "")
        if last_action in ("talk", "speak", "chat", "converse", "persuade",
                           "fast_talk", "intimidate", "charm", "psychology"):
            npc_id = ""
            if char_mgr:
                npc_id = find_npc_id_by_target(char_mgr, last_target) or ""
            npc_id = npc_id or resolve_social_npc_id(last_target, char_mgr=char_mgr) or last_target
            if npc_id in invalid_npcs or (
                scenario_mgr and new_loc
                and hasattr(scenario_mgr, "is_npc_at_location")
                and npc_id
                and not scenario_mgr.is_npc_at_location(npc_id, new_loc)
            ):
                state["last_pl_action"] = None

    if cleared:
        state.setdefault("all_events_log", []).append({
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": (
                f"[システム] ロケーション移動に伴い、旧場所宛ての未処理アクションを"
                f"{cleared}件破棄しました。"
            ),
            "meta": {
                "pending_actions_invalidated": True,
                "count": cleared,
                "from": old_loc,
                "to": new_loc,
            },
        })
    return cleared


def is_game_cleared(scenario_mgr):
    return bool(scenario_mgr and scenario_mgr.current_phase == "clear")


def _is_session_meta_entry(entry):
    text = (entry or {}).get("text", "")
    return text.startswith("[システム]") or text.startswith("[通知]") or text == USER_STOP_LOG_TEXT


def get_last_timeline_entry(all_events_log, *, skip_meta=True):
    """タイムライン末尾の意味のあるエントリを取得する。"""
    for entry in reversed(all_events_log or []):
        if skip_meta and _is_session_meta_entry(entry):
            continue
        return entry
    return None


def classify_timeline_tail(entry, char_name, char_mgr=None, active_pcs=None):
    """ログ末尾エントリの種別を判定する。"""
    if not entry:
        return "empty"
    text = entry.get("text", "")
    meta = entry.get("meta") or {}
    if _is_session_meta_entry(entry):
        return "session_meta"
    if text.startswith("システム:"):
        return "system_result"
    if text.startswith("KP:") or text.startswith("KP(プレイヤー層):"):
        return "kp_speech"
    if "(PL):" in text or entry.get("channel") == "OOC":
        if char_mgr and active_pcs:
            for pc_id in active_pcs:
                prefix = char_mgr.get_pc_log_prefix(pc_id, role="PL")
                if text.startswith(f"{prefix}:"):
                    return "pl_ooc"
        if f"{char_name}(PL):" in text:
            return "pl_ooc"
        if entry.get("channel") == "OOC" and "(PL):" in text:
            return "pl_ooc"
    if "(PC):" in text or meta.get("pc_id"):
        if char_mgr and active_pcs:
            for pc_id in active_pcs:
                prefix = char_mgr.get_pc_log_prefix(pc_id, role="PC")
                if text.startswith(f"{prefix}:"):
                    action_id = str(meta.get("action_id") or meta.get("action") or "wait").lower()
                    if meta.get("needs_system") and not meta.get("system_processed"):
                        if action_id in ACTIONS_NEEDING_SYSTEM:
                            return "pl_action_command"
                    return "pl_ic_chat"
        if f"{char_name}(PC):" in text:
            action_id = str(meta.get("action_id") or meta.get("action") or "wait").lower()
            if meta.get("needs_system") and not meta.get("system_processed"):
                if action_id in ACTIONS_NEEDING_SYSTEM:
                    return "pl_action_command"
            return "pl_ic_chat"
    return "unknown"


def find_pending_pl_action_entry(all_events_log, char_name=None, pc_id=None, char_mgr=None):
    """未処理のPL行動コマンドをタイムラインから検索する。"""
    for entry in reversed(all_events_log or []):
        meta = entry.get("meta") or {}
        text = entry.get("text", "")
        if pc_id and meta.get("pc_id") != pc_id:
            if char_mgr:
                prefix = char_mgr.get_pc_log_prefix(pc_id, role="PC")
                if not text.startswith(f"{prefix}:"):
                    continue
            else:
                continue
        elif char_name and not pc_id:
            matched = f"{char_name}(PC):" in text
            if char_mgr and not matched:
                for pid in (char_mgr.active_pc_list if char_mgr else []):
                    if text.startswith(f"{char_mgr.get_pc_log_prefix(pid, role='PC')}:"):
                        matched = True
                        break
            if not matched:
                continue
        if not meta.get("needs_system") or meta.get("system_processed"):
            continue
        action_id = str(meta.get("action_id") or "wait").lower()
        if action_id in ACTIONS_NEEDING_SYSTEM:
            return entry
    return None


def find_last_unnarrated_system_entry(all_events_log):
    """KP未描写の最新システムログを返す。"""
    for entry in reversed(all_events_log or []):
        if not entry.get("text", "").startswith("システム:"):
            continue
        if not (entry.get("meta") or {}).get("kp_narrated"):
            return entry
    return None


def mark_system_entry_narrated(entry):
    if entry is None:
        return
    meta = dict(entry.get("meta") or {})
    meta["kp_narrated"] = True
    entry["meta"] = meta


def mark_all_unnarrated_system_entries(all_events_log):
    """未描写システムログを一括で描写済みにする（KPナレーション重複防止）。"""
    for entry in all_events_log or []:
        if not entry.get("text", "").startswith("システム:"):
            continue
        meta = dict(entry.get("meta") or {})
        if meta.get("kp_narrated"):
            continue
        meta["kp_narrated"] = True
        entry["meta"] = meta


def _is_recent_san_shock_entry(entry):
    if not entry:
        return False
    text = str(entry.get("text", ""))
    if not text.startswith("システム:"):
        return False
    meta = entry.get("meta") or {}
    roll_type = str(meta.get("roll_type", "")).lower()
    if roll_type == "san_check":
        return True
    return any(k in text for k in ("【SANチェック】", "正気度が", "狂気", "発狂", "【強制SAN】"))


def has_recent_san_shock(all_events_log, lookback=3):
    """直近ログに SAN 自動解決/大きな精神的衝撃があるか判定する。"""
    recent = list((all_events_log or [])[-max(1, int(lookback)):])
    return any(_is_recent_san_shock_entry(entry) for entry in recent)


def needs_room_entry_san_check(state, scenario_mgr):
    """KP描写後・PL行動前に進入時強制SANを挟むべきか。"""
    if not scenario_mgr:
        return False
    if _is_san_check_pending(state.get("pending_san_check")):
        return False
    loc_id = state.get("current_loc") or scenario_mgr.location
    return scenario_mgr.is_room_entry_san_due(loc_id)


def should_arm_room_entry_san(state, char_name, scenario_mgr):
    """KPが部屋を描写した直後のみ進入SANを武装する。"""
    if not needs_room_entry_san_check(state, scenario_mgr):
        return False
    kind = classify_timeline_tail(
        get_last_timeline_entry(state.get("all_events_log", [])),
        char_name,
    )
    return kind == "kp_speech"


def sync_room_entry_san_on_load(app_state, scenario_mgr):
    """セーブ再開時、保留中の進入SANと完了フラグを同期する。"""
    if not app_state or not scenario_mgr:
        return
    pending = app_state.get("pending_san_check")
    if not _is_san_check_pending(pending):
        return
    if pending.get("room_entry") or pending.get("source") == SAN_SOURCE_ROOM_ENTRY:
        loc_id = pending.get("room_id") or app_state.get("current_loc") or scenario_mgr.location
        scenario_mgr.mark_room_entry_san_completed(loc_id)


def step_room_entry_san_arm(state, scenario_mgr):
    """PL行動前に進入時強制SANを pending へセットする（PL入力をスキップ）。"""
    loc_id = state.get("current_loc") or scenario_mgr.location
    payload = scenario_mgr.build_room_entry_san_check_payload(loc_id)
    if not payload:
        return False

    san_check = _enrich_san_check_metadata(
        dict(payload["san_check"]),
        action_id="wait",
        target="",
        log_text=payload.get("system_log", ""),
        scenario_mgr=scenario_mgr,
    )
    san_check["room_entry_intro"] = payload.get("system_log", "")
    san_check["room_entry_kp_instruction"] = payload.get("kp_instruction", "")
    scenario_mgr.mark_room_entry_san_completed(loc_id)
    state["pending_san_check"] = san_check
    state["last_system_result"] = {
        "log": payload.get("system_log", ""),
        "kp_instruction": payload.get("kp_instruction", ""),
        "san_check": san_check,
        "room_entry_san": True,
        "blocked": False,
    }
    return True


def recover_unqueued_last_action(state, char_name, scenario_mgr, char_mgr=None):
    """旧セーブの、last_pl_action にだけ残った検証済み行動を一度だけキューに載せる。"""
    action = state.get("last_pl_action") or {}
    action_id = str(action.get("action") or "").lower()
    if (
        action_id not in ACTIONS_NEEDING_SYSTEM
        or action.get("needs_pl_retry")
        or action.get("transaction_id")
        or state.get("last_system_result")
        or find_any_pending_pl_action(state, char_mgr)
    ):
        return False
    logs = state.get("all_events_log") or []
    if not any(
        (entry.get("meta") or {}).get("validation_error")
        for entry in logs[-8:]
    ):
        return False
    pc_id = action.get("actor_id") or state.get("pl_id") or state.get("active_pc_id")
    tid = new_action_transaction_id()
    action["transaction_id"] = tid
    action["actor_id"] = pc_id
    action["decision_owner_id"] = pc_id
    location = state.get("current_loc") or getattr(scenario_mgr, "location", "")
    message = action.get("message") or _build_pc_display_message(
        action.get("dialogue", ""), action_id, action.get("target", ""),
        scenario_mgr=scenario_mgr, current_loc=location,
    )
    pc_prefix = format_pc_log_prefix(char_mgr, pc_id, role="PC") if pc_id and char_mgr else f"{char_name}(PC)"
    logs.append({
        "channel": "IC", "location": location, "secret_to": None,
        "text": f"{pc_prefix}: {message}",
        "meta": {
            "pc_id": pc_id, "action_id": action_id,
            "target": action.get("target", ""), "skill": action.get("skill", ""),
            "needs_system": True, "system_processed": False,
            "transaction_id": tid, "actor_id": pc_id,
            "decision_owner_id": pc_id, "recovered_missing_ic": True,
        },
    })
    state["all_events_log"] = logs
    bind_action_transaction(state, transaction_id=tid, actor_id=pc_id, decision_owner_id=pc_id)
    return True


def determine_timeline_next_step(state, char_name, scenario_mgr, state_mgr=None, char_mgr=None):
    """
    タイムライン末尾と内部状態から次に実行すべき処理を決定する。

    優先順位:
      1. PENDING_ACTIONS（SAN / pending_decision / 戦闘防衛 / 幸運消費 / プッシュ / PL相談）
      2. System Process（未解決の PL 行動）
      3. KP Turn（未描写のシステム結果）
      4. 戦闘 NPC 手番 / 戦闘中 PC 手番
      5. PL Turn（ラウンドロビン）
    """
    # Resolve a finished combat before inspecting normal pending/tail state.
    # This is idempotent and is also the post-combat watchdog boundary.
    reconcile_post_combat_timeline(state, state_mgr, scenario_mgr, char_mgr)

    if is_game_cleared(scenario_mgr):
        return "game_clear"

    ensure_multi_pl_state(state, char_mgr)
    ensure_pending_decision_field(state)
    pending_phase = get_timeline_pending_phase(state)
    state["timeline_pending"] = pending_phase
    if pending_phase == PENDING_SAN_CHECK:
        return "system_resolve_san"
    if pending_phase in (PENDING_COMBAT_DEFENSE, PENDING_SHOOT_DEFENSE):
        return "combat_defense"
    if pending_phase == PENDING_LUCK_CONSUMPTION:
        return "luck_decision"
    if pending_phase == PENDING_PUSH_DECISION:
        return "push_decision"
    if pending_phase == PENDING_PL_DISCUSSION:
        return "pl_discussion"

    if find_any_pending_pl_action(state, char_mgr):
        return "system_process"
    if recover_unqueued_last_action(state, char_name, scenario_mgr, char_mgr):
        return "system_process"
    if find_last_unnarrated_system_entry(state.get("all_events_log", [])):
        return "kp_narrate"

    if state_mgr and state_mgr.in_combat:
        actor = state_mgr.get_current_actor()
        if actor and not state_mgr.is_combat_participant_incapacitated(actor):
            if is_active_pc_actor(state, actor):
                sync_pl_identity(state, char_mgr, actor)
                return "pl_speak"
            return "combat_npc_act"

    kind = classify_timeline_tail(
        get_last_timeline_entry(state.get("all_events_log", [])),
        char_name,
        char_mgr=char_mgr,
        active_pcs=state.get("active_pcs"),
    )
    # 再生成上限直後はメタログだけになりやすい。KPオープニングへ落とさず PL 再選択へ。
    if kind in ("empty", "session_meta"):
        last_action = state.get("last_pl_action") or {}
        if last_action.get("validation_regen_capped"):
            return "pl_speak"
        return "kp_opening"
    if kind == "system_result":
        return "kp_narrate"
    if should_arm_room_entry_san(state, char_name, scenario_mgr):
        return "room_entry_san_arm"
    if kind == "kp_speech":
        # KP描写後の手番ローテは kp_narrate 完了時に active_pc_id を進める
        return "pl_speak"
    if kind == "pl_ooc":
        if state.get("pl_discussion_mode"):
            return "pl_discussion"
        # OOC膠着強制 IC フェーズ中は free_chat ループに入らず pl_speak へ
        if is_force_ic_action_phase(state, state_mgr=state_mgr):
            ensure_force_ic_action_phase(state, state_mgr=state_mgr)
            return "pl_speak"
        return "free_chat"
    if kind in ("pl_ic_chat",):
        return "pl_speak"
    return "pl_speak"


def generate_kp_chat_prompt(
    location_info, ic_logs, ooc_logs, char_name, scenario_mgr=None, forbid_howto=False,
):
    """自律ラリー中の KP 応答用（システム判定なしの会話ターン）。"""
    loc_name = location_info.get("name", "未知の場所")
    loc_desc = location_info.get("default_description", "")
    situational = _build_kp_situational_directives(scenario_mgr)
    end_directive = (
        "『どうしますか？』で締めず、恐怖・余韻・圧迫感の描写で締めてください。"
        if forbid_howto else
        "「どうしますか？」は任意です（フリーチャット継続可）。"
    )
    return f"""
{_build_kp_narrative_constraints()}
{situational}あなたはクトゥルフ神話TRPGのキーパー（KP）です。現在は**会話ラリー**中です（ダイス判定はまだ発生していません）。

【多層的な意識】
- system_narration: 情景への短い応答、雰囲気、PLの発言への世界内反応
- player_kp_chat: PLのメタ発言（OOC）へのノリの良い返答

【現在地】{loc_name}
【基本描写】{loc_desc}

【直近の会話 (IC)】
{chr(10).join(ic_logs[-4:]) if ic_logs else "（まだ会話なし）"}

【直近のメタ会話 (OOC)】
{chr(10).join(ooc_logs[-3:]) if ooc_logs else "（なし）"}

PL（{char_name}）の直近の発言に自然に応じてください。探索者の行動を先取りしないでください。{end_directive}
"""


class AutonomousLoopGuard:
    """無限ループ・停滞のガードレール。"""

    def __init__(self, consecutive_speaker=None, consecutive_count=0, chat_rounds_without_action=0):
        self.consecutive_speaker = consecutive_speaker
        self.consecutive_count = consecutive_count
        self.chat_rounds_without_action = chat_rounds_without_action

    @classmethod
    def from_state(cls, state_dict):
        if not state_dict:
            return cls()
        return cls(
            consecutive_speaker=state_dict.get("consecutive_speaker"),
            consecutive_count=state_dict.get("consecutive_count", 0),
            chat_rounds_without_action=state_dict.get("chat_rounds_without_action", 0),
        )

    def to_state(self):
        return {
            "consecutive_speaker": self.consecutive_speaker,
            "consecutive_count": self.consecutive_count,
            "chat_rounds_without_action": self.chat_rounds_without_action,
        }

    def record(self, actor):
        if actor == self.consecutive_speaker:
            self.consecutive_count += 1
        else:
            self.consecutive_speaker = actor
            self.consecutive_count = 1

    def record_pl_action(self, pc_action, pending_san_check, scenario_mgr=None, current_loc=None, char_mgr=None):
        if is_nonprogress_pl_action(
            pc_action, pending_san_check,
            scenario_mgr=scenario_mgr, current_loc=current_loc, char_mgr=char_mgr,
        ):
            self.chat_rounds_without_action += 1
        else:
            # 有効コマンド（search/move/negotiate 等）は同一話者制限をリセットし、
            # アクション未処理化・次ターン潰れを防ぐ
            self.chat_rounds_without_action = 0
            self.consecutive_count = 0

    def should_break_same_speaker(self):
        return self.consecutive_count > MAX_CONSECUTIVE_SAME_SPEAKER

    def should_break_stagnation(self):
        return self.chat_rounds_without_action >= MAX_CHAT_ROUNDS_WITHOUT_PROGRESS

    def should_force_ic_action(self, state=None, state_mgr=None):
        """OOC連続 / 膠着ストリーク超過で強制 IC 行動フェーズへ。"""
        return is_force_ic_action_phase(state=state, state_mgr=state_mgr, guard=self)

    def should_break_system_stagnation(self, scenario_mgr):
        return bool(
            scenario_mgr
            and getattr(scenario_mgr, "is_stagnation_pause_level", lambda: False)()
        )


def inject_stagnation_interrupt(state, scenario_mgr, char_name, message=None, state_mgr=None):
    """膠着時のマイルドな OOC 通知。実際の連続ターン数は上書きしない。"""
    default_msg = (
        "[システム] 探索がやや停滞しています。別の対象や場所を試してもよいですが、"
        "まだ探索者自身で方針を選ぶ余白があります。"
    )
    state["all_events_log"].append({
        "channel": "OOC",
        "location": "all",
        "secret_to": None,
        "text": message or default_msg,
        "meta": {"stagnation_interrupt": True},
    })
    # 実ストリークを閾値へ書き換えない（見た目上「6ターン到達」と誤認されるため）
    actual = 0
    if state_mgr and getattr(state_mgr, "stagnation_tracker", None):
        actual = int((state_mgr.stagnation_tracker or {}).get("streak") or 0)
    if scenario_mgr:
        actual = max(actual, int(getattr(scenario_mgr, "stagnation_counter", 0) or 0))
        threshold = scenario_mgr.get_max_stagnation_turns() if hasattr(scenario_mgr, "get_max_stagnation_turns") else STAGNATION_PAUSE_THRESHOLD
        if actual >= threshold and state_mgr and hasattr(state_mgr, "mark_stagnation_intervened"):
            state_mgr.mark_stagnation_intervened()
    _maybe_set_introduction_stagnation_hint(state, scenario_mgr, state_mgr)


def _handle_same_speaker_soft_yield(state, managers, guard):
    """
    同一話者連続時: セッションは止めず、マイルド通知と次PCへの手番交代のみ。
    膠着カウンタは触らない。
    """
    char_mgr, _, state_mgr, _scenario_mgr = managers
    _append_stagnation_hint_log(state, STAGNATION_MILD_NOTICE)
    if guard is not None:
        guard.consecutive_count = 0
        state["autonomous_guard"] = guard.to_state()
    if char_mgr and not (state_mgr and getattr(state_mgr, "in_combat", False)):
        advance_exploration_turn(state, char_mgr, state_mgr)


def _maybe_inject_location_loop_warning(state, scenario_mgr):
    """地下室↔廊下の往復ループを検知して PL に警告する。"""
    if not state or not scenario_mgr:
        return
    flags = getattr(scenario_mgr, "flags", None) or {}
    current_loc = state.get("current_loc", "")
    visit_secret = flags.get("visit_secret_room", 0)
    if visit_secret < 2 or flags.get("ladder_searched"):
        return
    if current_loc not in ("hallway", "secret_room"):
        return
    warning = (
        "[システム] 地下室と廊下を行き来しています。"
        "トラップドアは戻り口です。脱出は地下室の「脱出用のはしご」を search し、"
        "問題なければ climb で登ってください。"
    )
    recent = state.get("all_events_log", [])[-3:]
    if any(entry.get("text") == warning for entry in recent):
        return
    state.setdefault("all_events_log", []).append({
        "channel": "OOC",
        "location": "all",
        "secret_to": None,
        "text": warning,
    })


def begin_autonomous_runtime(state):
    """自律巡航のランタイム状態を初期化して開始する。

    Returns:
        True: 開始できた / False: reexec_forbidden などで開始不可
    """
    if not isinstance(state, dict):
        return False
    ensure_transaction_state_fields(state)
    # 処理途中の半端なアクションがある場合は再開させない
    pause_class = state.get("autonomous_pause_class") or classify_autonomous_pause(
        state.get("autonomous_pause_reason"), state=state,
    )
    if (
        state.get("autonomous_paused")
        and pause_class == PAUSE_CLASS_REEXEC_FORBIDDEN
    ):
        return False

    state["is_running"] = True
    state["stop_requested"] = False
    state["autonomous_paused"] = False
    state["autonomous_pause_reason"] = None
    state["autonomous_pause_class"] = None
    # 明示再開済み: 以降のロード正規化で safe_resume_ready へ戻さない
    state["autonomous_user_resumed"] = True
    state["runtime_load_normalized"] = True
    return True


def finalize_autonomous_pause(state, pause_reason):
    """自律巡航の一時停止状態を一貫して確定する。"""
    state["is_running"] = False
    state["stop_requested"] = False
    state["autonomous_paused"] = True
    state["autonomous_pause_reason"] = pause_reason
    # 意図的な停止なので、再開フラグは落とす（次の begin で再セット）
    state["autonomous_user_resumed"] = False
    sync_autonomous_pause_class(state)
    if pause_reason == "max_iterations":
        logs = state.setdefault("all_events_log", [])
        if not any(e.get("text") == MAX_ITERATIONS_PAUSE_LOG_TEXT for e in logs[-5:]):
            logs.append({
                "channel": "OOC",
                "location": "all",
                "secret_to": None,
                "text": MAX_ITERATIONS_PAUSE_LOG_TEXT,
                "meta": {
                    "autonomous_pause": True,
                    "pause_reason": "max_iterations",
                    "pause_class": PAUSE_CLASS_SAFE_RESUME,
                },
            })


def build_autonomous_progress_fingerprint(state, scenario_mgr=None, char_mgr=None):
    """場所＋ State Delta 署名。変化があれば『実質進行』とみなす。"""
    loc = str((state or {}).get("current_loc") or "")
    if scenario_mgr is not None:
        loc = str(getattr(scenario_mgr, "location", None) or loc)
    flags = {}
    if scenario_mgr is not None:
        flags = dict(getattr(scenario_mgr, "flags", None) or {})
    try:
        from GameStateManager import GameStateManager
        snap = GameStateManager.build_progress_snapshot(
            flags,
            location_id=loc,
            public_knowledge_ids=(state or {}).get("public_knowledge_ids"),
            char_mgr=char_mgr,
            active_pcs=(state or {}).get("active_pcs"),
        )
        sig = GameStateManager.signature_from_snapshot(snap)
    except Exception:
        on_flags = tuple(
            sorted(k for k, v in flags.items() if k != "investigated_targets" and v is True)
        )
        investigated = flags.get("investigated_targets") or []
        if isinstance(investigated, (list, tuple, set)):
            inv = tuple(sorted(str(x) for x in investigated))
        else:
            inv = (str(investigated),)
        sig = (on_flags, inv)
    return (loc, sig)


def refresh_autonomous_step_budget_on_progress(state, scenario_mgr=None):
    """
    場所・進行フラグが進んだらステップ上限カウントをリセットする。
    無進行のまま上限に達したときだけ安全停止させる。
    """
    if not isinstance(state, dict):
        return False
    fp = build_autonomous_progress_fingerprint(state, scenario_mgr)
    prev = state.get("autonomous_progress_fp")
    state["autonomous_progress_fp"] = fp
    if prev is not None and prev != fp:
        state["autonomous_step_count"] = 0
        return True
    return False


def normalize_loaded_runtime_state(
    app_state,
    *,
    enforce_half_turn_pause=True,
    from_save_load=False,
):
    """
    セーブデータ上の矛盾したランタイムフラグを修復する。

    from_save_load=True:
        セーブ読込直後専用。safe_resume_ready / empty_tick / LLM失敗の復旧を行う。
    from_save_load=False（再描画・apply 時）:
        ロード修復は runtime_load_normalized 済みなら再適用しない。
        autonomous_user_resumed=True のときは safe_resume_ready へ戻さない。
    """
    if not isinstance(app_state, dict):
        return app_state
    ensure_investigation_state(app_state)
    app_state.setdefault("unified_event_log", [])
    app_state.setdefault("director_v2", {})
    ensure_transaction_state_fields(app_state)
    logs = app_state.get("all_events_log") or []
    has_user_stop_log = any(entry.get("text") == USER_STOP_LOG_TEXT for entry in logs)
    user_resumed = bool(app_state.get("autonomous_user_resumed"))
    load_already_done = bool(app_state.get("runtime_load_normalized"))
    # ロード修復を行うのは: 明示的なセーブ読込、または未正規化の初回のみ
    apply_load_repairs = bool(from_save_load) or not load_already_done

    if from_save_load:
        # セーブ読込時は再開フラグをリセットし、安全停止を一度適用できるようにする
        app_state["autonomous_user_resumed"] = False
        user_resumed = False
        apply_load_repairs = True

    # 現在の stop_requested のみ常時尊重（履歴の user_stop ログはロード時のみ）
    if app_state.get("stop_requested"):
        app_state["is_running"] = False
        app_state["stop_requested"] = False
        app_state["autonomous_paused"] = True
        if not app_state.get("autonomous_pause_reason"):
            app_state["autonomous_pause_reason"] = "user_stop"
        app_state["autonomous_user_resumed"] = False
        user_resumed = False
    elif apply_load_repairs and has_user_stop_log and not user_resumed:
        app_state["is_running"] = False
        app_state["stop_requested"] = False
        app_state["autonomous_paused"] = True
        if not app_state.get("autonomous_pause_reason"):
            app_state["autonomous_pause_reason"] = "user_stop"

    if app_state.get("is_running") and app_state.get("autonomous_paused"):
        app_state["is_running"] = False

    if app_state.get("is_running") and app_state.get("stop_requested"):
        app_state["is_running"] = False
        app_state["stop_requested"] = False
        app_state["autonomous_paused"] = True
        app_state["autonomous_pause_reason"] = app_state.get("autonomous_pause_reason") or "user_stop"
        app_state["autonomous_user_resumed"] = False
        user_resumed = False

    # 行動未確定（last_pl_action のみ）で実行中フラグが立っているセーブを安全側へ正規化
    last_action = app_state.get("last_pl_action") or {}
    pending_kind = str((last_action or {}).get("action") or "").lower()
    needing = globals().get("ACTIONS_NEEDING_SYSTEM") or frozenset({
        "search", "inspect", "move", "talk", "push", "break", "climb", "use",
        "persuade", "negotiate", "fast_talk", "intimidate", "charm", "psychology",
    })
    has_half_turn = bool(
        pending_kind in needing
        and not app_state.get("last_system_result")
    )
    if enforce_half_turn_pause and app_state.get("is_running") and has_half_turn:
        app_state["is_running"] = False
        app_state["autonomous_paused"] = True
        app_state["autonomous_pause_reason"] = (
            app_state.get("autonomous_pause_reason") or "awaiting_system_process"
        )
        app_state["autonomous_user_resumed"] = False
        user_resumed = False

    # 保存時の実行中フラグは新しいプロセスへ引き継がない。未処理の取引が
    # 残る場合は同じ行動を自動再実行できない一時停止として扱う。
    if from_save_load and app_state.get("is_running"):
        unprocessed_action = find_any_pending_pl_action(app_state)
        app_state["is_running"] = False
        app_state["autonomous_paused"] = True
        app_state["autonomous_pause_reason"] = (
            "awaiting_system_process" if unprocessed_action or (enforce_half_turn_pause and has_half_turn)
            else "safe_resume_ready"
        )

    # 空振り／LLM失敗の復旧はロード時（または未正規化の初回）のみ
    if apply_load_repairs and not user_resumed:
        recent = logs[-8:]
        has_empty_tick_log = any(
            entry.get("text") == EMPTY_TICK_PAUSE_LOG_TEXT for entry in recent
        )
        llm_pause_meta = next(
            (
                (entry.get("meta") or {})
                for entry in reversed(recent)
                if (entry.get("meta") or {}).get("llm_failure")
                or str((entry.get("meta") or {}).get("pause_reason") or "") in LLM_PAUSE_REASONS
            ),
            None,
        )
        if has_empty_tick_log or llm_pause_meta:
            reason = (
                (llm_pause_meta or {}).get("pause_reason")
                or (llm_pause_meta or {}).get("llm_failure_category")
                or ("empty_tick" if has_empty_tick_log else None)
                or app_state.get("autonomous_pause_reason")
                or "empty_tick"
            )
            if app_state.get("is_running") or not app_state.get("autonomous_paused"):
                app_state["is_running"] = False
                app_state["stop_requested"] = False
                app_state["autonomous_paused"] = True
                app_state["autonomous_pause_reason"] = reason

    # 処理済みアクションと pending の整合（重複実行防止）
    pending_id = str(app_state.get("pending_action_id") or "").strip()
    last_id = str(app_state.get("last_processed_action_id") or "").strip()
    if last_id and not pending_id:
        app_state["pending_action_id"] = last_id
    elif pending_id and last_id and pending_id == last_id:
        # safe_resume_ready はロード修復時のみ。明示再開後の再描画では適用しない。
        if (
            apply_load_repairs
            and not user_resumed
            and app_state.get("is_running")
            and not app_state.get("autonomous_paused")
        ):
            app_state["is_running"] = False
            app_state["autonomous_paused"] = True
            app_state["autonomous_pause_reason"] = (
                app_state.get("autonomous_pause_reason") or "safe_resume_ready"
            )

    # ロード時に既に OOC 膠着閾値を超えていれば強制 IC フェーズを復元
    if is_force_ic_action_phase(app_state):
        app_state["force_ic_action"] = True
        if not app_state.get("stagnation_pl_hint"):
            app_state["stagnation_pl_hint"] = OOC_LOOP_FORCE_ACTION_WARNING

    if not (from_save_load and app_state.get("autonomous_pause_reason") == "awaiting_system_process"):
        app_state = validate_and_sync_pause_state(app_state)
    if app_state.get("autonomous_paused"):
        sync_autonomous_pause_class(app_state)
    else:
        app_state["autonomous_pause_class"] = None

    # ロード正規化は一度完了とマーク（以降の再描画で safe_resume を再適用しない）
    app_state["runtime_load_normalized"] = True

    return app_state


def validate_and_sync_pause_state(app_state):
    """
    再開判定フラグの整合を補正する。
    - wait で停止している
    - 直近に未処理アクションが残っていない
    のいずれか（実質、awaiting_system_process ではない）なら pause 理由を解除する。
    """
    if not app_state:
        return app_state
    if str(app_state.get("autonomous_pause_reason") or "") != "awaiting_system_process":
        return app_state

    last_action = app_state.get("last_pl_action") or {}
    action_id = str(last_action.get("action") or "").lower()
    logs = app_state.get("all_events_log") or []
    action_logs_exist = any(
        isinstance((entry or {}).get("meta"), dict)
        and (
            (entry.get("meta") or {}).get("needs_system")
            or str((entry.get("meta") or {}).get("action_id") or "").strip()
        )
        for entry in logs
    )
    pending = find_any_pending_pl_action(app_state)
    no_pending = pending is None
    all_recent_actions_processed = action_logs_exist and no_pending
    if action_id == "wait" or all_recent_actions_processed:
        app_state["autonomous_pause_reason"] = None
        app_state["autonomous_paused"] = False
        app_state["autonomous_pause_class"] = None
    return app_state


def reset_stagnation_state_on_progress(state, scenario_mgr=None, state_mgr=None, char_mgr=None):
    """進展イベント確定時に、膠着ヒント/カウンタを即時クリアする。"""
    if not state:
        return
    state["stagnation_pl_hint"] = None
    state["stagnation_kp_nudge"] = None
    state["stagnation_cause"] = None
    state["force_ic_action"] = False
    state["stagnation_streak"] = 0
    guard = state.get("autonomous_guard")
    if isinstance(guard, dict):
        guard = dict(guard)
        guard["chat_rounds_without_action"] = 0
        state["autonomous_guard"] = guard
    if state_mgr and hasattr(state_mgr, "reset_stagnation_tracker"):
        try:
            flags = (scenario_mgr.flags if scenario_mgr else None) or {}
            snapshot = _build_stagnation_progress_snapshot(state, scenario_mgr, char_mgr)
            state_mgr.reset_stagnation_tracker(
                state.get("current_loc"), flags, progress_snapshot=snapshot,
            )
        except Exception:
            pass
    if scenario_mgr and hasattr(scenario_mgr, "reset_stagnation_counter"):
        scenario_mgr.reset_stagnation_counter()


def normalize_session_runtime_flags(session_state):
    """session_state 上の自律巡航フラグを整合させる。"""
    wrapper = {
        "all_events_log": session_state.get("all_events_log", []),
        "is_running": session_state.get("is_running", False),
        "stop_requested": session_state.get("stop_requested", False),
        "autonomous_paused": session_state.get("autonomous_paused", False),
        "autonomous_pause_reason": session_state.get("autonomous_pause_reason"),
        "autonomous_pause_class": session_state.get("autonomous_pause_class"),
        "autonomous_user_resumed": session_state.get("autonomous_user_resumed", False),
        "runtime_load_normalized": session_state.get("runtime_load_normalized", False),
        "pending_action_id": session_state.get("pending_action_id"),
        "last_processed_action_id": session_state.get("last_processed_action_id"),
        "last_pl_action": session_state.get("last_pl_action"),
        "last_system_result": session_state.get("last_system_result"),
    }
    normalized = normalize_loaded_runtime_state(
        wrapper,
        enforce_half_turn_pause=False,
        from_save_load=False,
    )
    session_state.is_running = normalized["is_running"]
    session_state.stop_requested = normalized["stop_requested"]
    session_state.autonomous_paused = normalized["autonomous_paused"]
    session_state.autonomous_pause_reason = normalized.get("autonomous_pause_reason")
    session_state.autonomous_pause_class = normalized.get("autonomous_pause_class")
    session_state.autonomous_user_resumed = bool(normalized.get("autonomous_user_resumed"))
    session_state.runtime_load_normalized = bool(normalized.get("runtime_load_normalized"))


def append_user_stop_message(state):
    """ユーザー操作による一時停止をログへ記録し、状態を確定する。"""
    if not any(entry.get("text") == USER_STOP_LOG_TEXT for entry in state.get("all_events_log", [])):
        state["all_events_log"].append({
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": USER_STOP_LOG_TEXT,
        })
    finalize_autonomous_pause(state, "user_stop")


def step_kp_start(state, scenario_mgr):
    current_loc = state["current_loc"]
    loc_info = scenario_mgr.get_location_info(current_loc)
    kp_data = call_kp_api(generate_kp_prompt(loc_info, scenario_mgr=scenario_mgr, state=state))
    append_kp_response_to_logs(kp_data, current_loc, state["all_events_log"])
    state["stagnation_kp_nudge"] = None


def step_kp_chat(state, scenario_mgr, pl_id, char_name):
    current_loc = state["current_loc"]
    ic_logs, ooc_logs = get_filtered_logs(pl_id, current_loc, state["all_events_log"])
    loc_info = scenario_mgr.get_location_info(current_loc)
    forbid_howto = has_recent_san_shock(state.get("all_events_log", []), lookback=3)
    kp_data = call_kp_api(
        generate_kp_chat_prompt(
            loc_info, ic_logs, ooc_logs, char_name, scenario_mgr, forbid_howto=forbid_howto,
        )
    )
    append_kp_response_to_logs(kp_data, current_loc, state["all_events_log"])


def step_kp_eval(state, scenario_mgr, system_entry=None, char_mgr=None, *, max_regen=2):
    """未描写のシステム確定結果を KP がナレーションする。

    タスク1不変条件:
      - GameStateManager / CharacterManager のフラグ・SAN・HP 等は変更しない
      - 成功時のみ all_events_log へ KP テキスト追加 + kp_narrated=True
      - 失敗時は未描写のまま返し、描写のみ再試行可能にする
      - 判定・知識付与・停滞計上は再実行しない（描写の再生成のみ）

    Returns:
        True: 描写を確定した / False: 未確定（再試行可）
    """
    current_loc = state["current_loc"]
    action = state.get("last_pl_action")
    result = dict(state.get("last_system_result") or {})
    if _is_san_check_pending(state.get("pending_san_check")):
        result["san_check"] = state["pending_san_check"]
    else:
        result["san_check"] = {"required": False}
    loc_info = scenario_mgr.get_location_info(current_loc)
    fallback_text = str(
        result.get("log")
        or result.get("system_log")
        or result.get("confirmed_fact")
        or result.get("handout_text")
        or (system_entry or {}).get("text")
        or ""
    )
    allow_fallback = bool(fallback_text.strip())
    base_prompt = generate_kp_prompt(
        loc_info, action, result, scenario_mgr=scenario_mgr, state=state, char_mgr=char_mgr,
    )
    settled = {
        "access_granted": is_access_already_granted(
            scenario_mgr, result,
            current_loc=current_loc,
            target=str((action or {}).get("target") or result.get("target") or ""),
        ),
        "resolved_skill": extract_resolved_skill_from_result(result, action),
        "proposed_skill": str((action or {}).get("skill") or ""),
    }

    def _is_hard_kp_violation(code):
        c = str(code or "")
        if c in (
            "extra_permission_after_grant",
            "success_negated",
            "failure_flipped_to_success",
            "empty_text",
        ):
            return True
        if c.startswith("wrong_skill_success"):
            return True
        if c.startswith("san_overclaim"):
            return True
        return False

    kp_data = None
    last_violations = []
    correction = ""
    last_soft_kp = None
    # 初回 + 上限付き再生成（ダイス／SAN／知識は触らない）
    attempts = max(1, int(max_regen) + 1)
    for attempt in range(attempts):
        prompt = base_prompt if not correction else (
            base_prompt
            + "\n【再生成・必須訂正】前回の描写は確定状態と矛盾しました: "
            + " / ".join(last_violations)
            + "\n矛盾箇所を書かず、【最新の確定状態】とシステム判定ログだけに従って描写し直してください。\n"
        )
        try:
            # 検証ループ中は API 内フォールバックを抑え、矛盾文の採用を避ける
            kp_data = call_kp_api(
                prompt,
                max_retries=1 if attempt < attempts - 1 else 2,
                fallback_text=fallback_text if (attempt == attempts - 1 and allow_fallback) else "",
                allow_fallback=bool(attempt == attempts - 1 and allow_fallback),
            )
        except KpNarrationError as exc:
            print(f"[KP] 描写未確定: {exc}")
            kp_data = None
            continue
        except Exception as exc:
            print(f"[KP] 描写中に予期せぬエラー（状態は維持・再試行可）: {exc}")
            kp_data = None
            continue

        kp_data = _inject_handout_into_kp_data(
            kp_data, scenario_mgr, action=action, result=result, current_loc=current_loc,
        )
        text = str((kp_data or {}).get("text") or "")
        last_violations = detect_kp_narration_violations(
            text,
            scenario_mgr=scenario_mgr,
            last_pl_action=action,
            last_system_result=result,
            settled=settled,
        )
        if not last_violations:
            break
        # 硬矛盾以外（代筆疑い等）は再生成後に採用候補として保持し、
        # 無菌フォールバック連発で会話を壊さない
        if last_violations and not any(_is_hard_kp_violation(v) for v in last_violations):
            last_soft_kp = kp_data
        print(f"[KP] 確定矛盾を検出（試行 {attempt + 1}/{attempts}）: {last_violations}")
        correction = "retry"
        kp_data = None

    if kp_data is None and not last_violations:
        # API全滅（矛盾検出ではない）→ 未確定のまま再試行可能に残す
        return False

    # 空テキストのみでは採用もフォールバック確定もしない（kp_narrated を立てない）
    if last_violations == ["empty_text"] or (
        kp_data is not None and not str(kp_data.get("text") or "").strip()
    ):
        return False

    hard = [v for v in (last_violations or []) if _is_hard_kp_violation(v)]
    if kp_data is None and not hard and last_soft_kp is not None:
        print("[KP] 硬矛盾なし。最終候補を採用（安全フォールバックは使わない）。")
        kp_data = last_soft_kp
        last_violations = []

    if kp_data is None or hard:
        if not allow_fallback:
            return False
        # 硬矛盾のみ安全フォールバックへ（軟い疑いでは会話テンプレ化しない）
        print("[KP] 再生成上限。システム確定情報の安全フォールバックを採用します。")
        kp_data = build_safe_kp_fallback_narration(
            scenario_mgr=scenario_mgr,
            last_pl_action=action,
            last_system_result=result,
            state=state,
            char_mgr=char_mgr,
            fallback_text=fallback_text,
        )
        kp_data = _inject_handout_into_kp_data(
            kp_data, scenario_mgr, action=action, result=result, current_loc=current_loc,
        )
        # フォールバックでもなお矛盾するなら未確定のまま（矛盾文を採用しない）
        still_bad = detect_kp_narration_violations(
            str(kp_data.get("text") or ""),
            scenario_mgr=scenario_mgr,
            last_pl_action=action,
            last_system_result=result,
            settled=settled,
        )
        still_hard = [v for v in still_bad if _is_hard_kp_violation(v)]
        if still_hard:
            print(f"[KP] フォールバックも矛盾のため未確定: {still_hard}")
            return False
        last_violations = []

    narration_start = len(state["all_events_log"])
    source_entry = system_entry or find_last_unnarrated_system_entry(state["all_events_log"])
    appended = append_kp_response_to_logs(kp_data, current_loc, state["all_events_log"])
    audience = (source_entry or {}).get("secret_to")
    if audience:
        for event in state["all_events_log"][narration_start:]:
            event["secret_to"] = list(audience)
    if not appended:
        # テキストが空なら描写未完了。kp_narrated は立てない。
        return False

    mark_system_entry_narrated(system_entry or find_last_unnarrated_system_entry(state["all_events_log"]))
    mark_all_unnarrated_system_entries(state["all_events_log"])
    # ランタイムの「次に描写すべき判定」ポインタのみクリア（SAN/HP/flags は触らない）
    state["last_pl_action"] = None
    state["last_system_result"] = None
    state["stagnation_kp_nudge"] = None
    return True


def step_kp_narrate(state, scenario_mgr, char_mgr=None):
    """未描写のシステムログを KP がナレーションする。成功時 True。"""
    system_entry = find_last_unnarrated_system_entry(state.get("all_events_log", []))
    if not system_entry:
        return False
    return step_kp_eval(state, scenario_mgr, system_entry=system_entry, char_mgr=char_mgr)


def _action_data_from_timeline(state, scenario_mgr, char_name, char_mgr=None):
    """タイムライン上の未処理 PL 行動、または last_pl_action から action_data を取得する。

    system_processed はここでは立てない。判定 Commit 後に
    _mark_timeline_pl_action_processed で確定する（タスク1: アトミック確定）。
    """
    current_loc = state["current_loc"]
    entry = find_any_pending_pl_action(state, char_mgr)
    if not entry:
        entry = find_pending_pl_action_entry(
            state.get("all_events_log", []),
            char_name=char_name,
            char_mgr=char_mgr,
        )
    if entry:
        meta = dict(entry.get("meta") or {})
        if meta.get("pc_id"):
            sync_pl_identity(state, char_mgr, meta["pc_id"])
        action_data = normalize_pc_action({
            "action": meta.get("action_id", "wait"),
            "target": meta.get("target", ""),
            "skill": meta.get("skill", ""),
            "skill_proposal_reason": meta.get("skill_proposal_reason", ""),
            "dialogue": meta.get("dialogue", ""),
            "message": meta.get("message", ""),
            "transaction_id": meta.get("transaction_id", ""),
            "actor_id": meta.get("actor_id") or meta.get("pc_id"),
            "decision_owner_id": meta.get("decision_owner_id") or meta.get("pc_id"),
            "action_origin": meta.get("action_origin") or AUTONOMOUS,
            "progression_binding": copy.deepcopy(meta.get("progression_binding") or {}),
        }, scenario_mgr, current_loc, char_mgr=char_mgr)
        # normalize_pc_action が落とす場合に備え明示復元
        if meta.get("transaction_id"):
            action_data["transaction_id"] = meta["transaction_id"]
        if meta.get("actor_id") or meta.get("pc_id"):
            action_data["actor_id"] = meta.get("actor_id") or meta.get("pc_id")
        if meta.get("decision_owner_id") or action_data.get("actor_id"):
            action_data["decision_owner_id"] = (
                meta.get("decision_owner_id") or action_data.get("actor_id")
            )
        action_data["action_origin"] = meta.get("action_origin") or AUTONOMOUS
        if meta.get("progression_binding"):
            action_data["progression_binding"] = copy.deepcopy(meta["progression_binding"])
        # normalize_pc_action intentionally keeps the generic action schema small.
        # Combat routing metadata lives on the timeline entry and must survive until
        # commit_system_resolution so every selected combat action gets a matching
        # COMBAT_ACTION_RESOLVED event.
        if meta.get("combat_action_category"):
            action_data["combat_action_category"] = meta["combat_action_category"]
        if meta.get("combat_goal"):
            action_data["combat_goal"] = meta["combat_goal"]
        state["_pending_system_pl_entry"] = entry
        state["last_pl_action"] = action_data
        return action_data
    state.pop("_pending_system_pl_entry", None)
    return normalize_pc_action(
        state.get("last_pl_action") or {}, scenario_mgr, current_loc, char_mgr=char_mgr,
    )


def _mark_timeline_pl_action_processed(state):
    """判定 Commit 後に、対象 PL ログを system_processed=True にする。"""
    entry = state.pop("_pending_system_pl_entry", None)
    if not entry:
        return
    meta = dict(entry.get("meta") or {})
    meta["system_processed"] = True
    entry["meta"] = meta


def commit_system_resolution(state, result, *, current_loc, action_data=None, had_san_pending=False,
                             char_mgr=None, dice_engine=None, scenario_mgr=None, state_mgr=None,
                             pl_id=None, char_name="", auto_resolve_san=True, transaction_id=None):
    """ダイス・フラグ等の判定結果をアトミックに Commit し、未描写システムログを積む。

    KP 呼び出しは行わない。戻り値の result は（SAN自動解決後の）確定結果。
    タスク2: Commit と同時に last_processed_action_id を更新する。
    """
    action_data = action_data or {}
    relation_transaction_id = (
        transaction_id or action_data.get("transaction_id") or state.get("pending_action_id")
    )
    actor_for_knowledge = (
        action_data.get("actor_id")
        or state.get("actor_id")
        or pl_id
        or state.get("pl_id")
    )
    result = ensure_lifecycle_relation_id(
        result, transaction_id=relation_transaction_id, actor_id=actor_for_knowledge,
    )
    from CompletionAtomicity import commit_special_objective_completion
    commit_special_objective_completion(state, result, scenario_mgr, state_mgr)
    apply_system_roll_state_updates(state, result, had_san_pending=had_san_pending)
    actor_for_knowledge = result.get("lifecycle_actor_id") or actor_for_knowledge
    _append_result_log_with_knowledge(
        state, result,
        current_loc=current_loc,
        char_mgr=char_mgr,
        pl_id=actor_for_knowledge,
        action_id=result.get("action_id", action_data.get("action", "")),
        target=result.get("target", action_data.get("target", "")),
        roll_type=result.get("roll_type", ""),
        transaction_id=relation_transaction_id,
    )

    # The result is now committed and knowledge grants have been applied, so
    # update attempt rights and append the structured investigation events.
    finalize_investigation(
        state,
        result,
        action_data,
        active_pc_ids=list(state.get("active_pcs") or [actor_for_knowledge]),
    )

    if auto_resolve_san and char_mgr is not None and dice_engine is not None and scenario_mgr is not None:
        result = _maybe_auto_resolve_san_check_after_action(
            state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name, result,
        )

    combat_transaction_id = str(
        action_data.get("transaction_id") or result.get("transaction_id") or ""
    )
    combat_resolution_exists = any(
        row.get("event_type") == "COMBAT_ACTION_RESOLVED"
        and (
            not combat_transaction_id
            or str(row.get("transaction_id") or "") == combat_transaction_id
        )
        for row in state.get("unified_event_log") or []
    )
    if (
        (action_data or {}).get("combat_action_category") in {"SPECIAL", "ESCAPE", "SUPPORT", "MOVE"}
        and not combat_resolution_exists
    ):
        append_combat_event(
            state, "COMBAT_ACTION_RESOLVED", state_mgr=state_mgr,
            actor=action_data.get("actor_id") or pl_id,
            actor_state={
                "HP": char_mgr.get_stat_current(action_data.get("actor_id") or pl_id, "HP"),
                "SAN": char_mgr.get_stat_current(action_data.get("actor_id") or pl_id, "SAN"),
            },
            target=action_data.get("target") or result.get("target") or "",
            combat_goal=action_data.get("combat_goal") or getattr(state_mgr, "combat_goal", ""),
            action_category=action_data.get("combat_action_category") or "",
            selected_action=action_data.get("action") or result.get("action_id") or "",
            action_origin=action_data.get("action_origin") or AUTONOMOUS,
            legality="LEGAL" if not result.get("blocked") else "ILLEGAL",
            skill=action_data.get("skill") or result.get("skill") or "",
            result=result.get("status"),
            HP_after=char_mgr.get_stat_current(action_data.get("actor_id") or pl_id, "HP"),
            SAN_after=char_mgr.get_stat_current(action_data.get("actor_id") or pl_id, "SAN"),
            position_before=current_loc,
            position_after=state.get("current_loc") or current_loc,
            effect=result.get("log") or "",
            combat_progress_delta=0 if result.get("blocked") else 1,
            combat_end_condition=getattr(state_mgr, "combat_end_reason", "") if not state_mgr.in_combat else "",
            transaction_id=combat_transaction_id,
        )

    tid = commit_action_transaction(
        state, transaction_id or action_data.get("transaction_id") or state.get("pending_action_id"),
    )
    if tid:
        result = dict(result or {})
        result["transaction_id"] = tid

    state["last_system_result"] = result
    if result.get("stagnation_progress") and scenario_mgr is not None:
        reset_stagnation_state_on_progress(state, scenario_mgr=scenario_mgr, state_mgr=state_mgr, char_mgr=char_mgr)

    _mark_timeline_pl_action_processed(state)
    apply_location_change_side_effects(
        state, result, scenario_mgr=scenario_mgr, char_mgr=char_mgr,
    )
    if combat_is_active(state_mgr):
        validate_combat_location(state, state_mgr, scenario_mgr)
    sync_timeline_pending_phase(state)
    return result


def step_pl_turn(state, char_mgr, scenario_mgr, pl_id, char_name, state_mgr=None):
    current_loc = state["current_loc"]
    ensure_director_state(state, scenario_mgr, char_mgr)
    discussion = bool(state.get("pl_discussion_mode"))
    combat_active = combat_is_active(state_mgr)
    if combat_active:
        validate_combat_location(state, state_mgr, scenario_mgr)
        current_loc = state["current_loc"]

    if not prepare_active_pc_for_pl_turn(state, char_mgr, state_mgr):
        state["all_events_log"].append({
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": "[システム] 行動可能な探索者がいません。",
        })
        return {"action": "wait", "target": "", "skill": ""}

    # KP描写後の手番ローテは execute_timeline_step で済ませる（rerun 越しにフラグが消えないよう）
    state.pop("_advance_pc_after_kp", False)

    # 戦闘中: DEX順の現在アクターが本PCでなければ待機
    if state_mgr and state_mgr.in_combat:
        actor = state_mgr.get_current_actor()
        if actor and is_active_pc_actor(state, actor):
            sync_pl_identity(state, char_mgr, actor)
        elif actor and not is_active_pc_actor(state, actor):
            return {"action": "wait", "target": "", "skill": ""}

    pl_id = state.get("pl_id") or pl_id
    char_name = state.get("char_name") or char_name

    if char_mgr and char_mgr.is_pc_incapacitated(pl_id, state_mgr):
        next_pc = determine_next_active_pc(state, char_mgr, state_mgr, advance=True)
        if next_pc and next_pc != pl_id:
            sync_pl_identity(state, char_mgr, next_pc)
            pl_id = next_pc
            char_name = state["char_name"]
        else:
            return {"action": "wait", "target": "", "skill": ""}

    ic_logs, ooc_logs = format_prompt_history_logs(
        pl_id, current_loc, state["all_events_log"], char_mgr=char_mgr,
    )
    loc_info = scenario_mgr.get_location_info(current_loc)
    exits = scenario_mgr.get_available_exits(current_loc)
    san_locked = _is_san_check_pending(state.get("pending_san_check"))
    san_source = _resolve_san_check_source(
        pending_san_check=state.get("pending_san_check"),
        last_system_result=state.get("last_system_result"),
        scenario_mgr=scenario_mgr,
    ) if san_locked else None

    party_note = ""
    active = state.get("active_pcs") or []
    if len(active) > 1 and char_mgr:
        others = [
            f"{char_mgr.get_pc_name(pid)}({char_mgr.get_pc_slot_label(pid)})"
            for pid in active if pid != pl_id
        ]
        party_note = (
            f"\n【同行探索者（操作対象外）】{', '.join(others)}\n"
            "※同行者の名前で名乗ったり、同行者の職業を自分のものとして使ってはならない。\n"
        )

    force_ic = (not discussion) and ensure_force_ic_action_phase(
        state, state_mgr=state_mgr, guard=None,
    )
    # guard 未接続時も autonomous_guard / streak から判定
    if not force_ic and not discussion:
        force_ic = is_force_ic_action_phase(state, state_mgr=state_mgr)
        if force_ic:
            ensure_force_ic_action_phase(state, state_mgr=state_mgr)
    if combat_active:
        force_ic = False

    combat_candidates = build_combat_action_candidates(
        state_mgr, char_mgr, scenario_mgr, pl_id, current_loc,
        active_pc_ids=active,
    ) if combat_active else []

    pl_prompt = generate_pl_prompt(
        char_name, ic_logs, ooc_logs, loc_info, exits,
        state.get("pending_push_roll"),
        pending_san_check=state.get("pending_san_check"),
        scenario_mgr=scenario_mgr,
        current_loc=current_loc,
        last_system_result=state.get("last_system_result"),
        char_mgr=char_mgr,
        pl_id=pl_id,
        all_events_log=state.get("all_events_log"),
        stagnation_pl_hint=state.get("stagnation_pl_hint"),
        force_ic_action=force_ic,
        active_pcs=active,
        game_state=state,
    )
    if party_note:
        pl_prompt = party_note + pl_prompt
    if combat_active:
        pl_prompt = combat_prompt_block(combat_candidates, state_mgr, char_mgr) + pl_prompt
    if discussion:
        pl_prompt = (
            "【作戦会議フェーズ】ダイス判定なし。仲間とOOCで相談し、合意後に調査へ移ること。"
            "action は wait。\n"
        ) + pl_prompt
    elif force_ic:
        pl_prompt = f"{OOC_LOOP_FORCE_ACTION_WARNING}\n" + pl_prompt

    turn_log_start = len(state["all_events_log"])
    ai_data = call_pl_api(
        pl_prompt,
        action_locked=san_locked or discussion,
        san_source=san_source,
        active_pc_id=pl_id,
        char_mgr=char_mgr,
        discussion_mode=discussion,
    )
    llm_failure = extract_llm_failure_from_response(ai_data)
    if llm_failure:
        apply_llm_failure_pause(state, llm_failure)
        return {
            "action": "wait",
            "target": "",
            "skill": "",
            "_llm_failure": llm_failure,
        }
    pc_action = apply_pl_response_to_logs(
        ai_data, char_name, current_loc, state["all_events_log"],
        pending_san_check=state.get("pending_san_check"),
        scenario_mgr=scenario_mgr,
        pc_id=pl_id,
        char_mgr=char_mgr,
        force_ic_action=force_ic,
        pending_push_roll=state.get("pending_push_roll"),
    )
    if not discussion and not san_locked:
        original_pc_action = pc_action
        combat_verdict = None
        if combat_active:
            pc_action, combat_verdict = guide_combat_action(
                pc_action, combat_candidates, state_mgr=state_mgr,
            )
            if not combat_verdict.get("legal"):
                original_tid = str(original_pc_action.get("transaction_id") or "")
                for entry in reversed(state.get("all_events_log") or []):
                    meta = entry.get("meta") or {}
                    if original_tid and str(meta.get("transaction_id") or "") != original_tid:
                        continue
                    if meta.get("pc_id") == pl_id and meta.get("action_id"):
                        meta.update({
                            "needs_system": False,
                            "system_processed": True,
                            "combat_legality": "ILLEGAL",
                            "combat_rejection_reason": combat_verdict.get("reason"),
                        })
                        entry["meta"] = meta
                        break
                append_combat_event(
                    state, "COMBAT_ACTION_REJECTED", state_mgr=state_mgr,
                    actor=pl_id,
                    target=original_pc_action.get("target") or "",
                    selected_action=original_pc_action.get("action") or "",
                    action_origin=AUTONOMOUS,
                    legality="ILLEGAL",
                    combat_goal=getattr(state_mgr, "combat_goal", ""),
                    position_before=current_loc,
                    position_after=current_loc,
                    effect=combat_verdict.get("reason") or "illegal_combat_action",
                    transaction_id=original_tid,
                )
        else:
            # V16: Natural Decision production path — causal bind before legacy guidance.
            try:
                from ndm_integration import enrich_pc_action_with_ndm, get_active_runtime
                from reasoning.runtime import get_active_runtime as _gar
                if _gar() is not None and _gar().active:
                    pc_action = enrich_pc_action_with_ndm(
                        state, pc_action, actor_id=pl_id, scenario_mgr=scenario_mgr,
                    )
                else:
                    pc_action = apply_stall_candidate_guidance(
                        state, pc_action, scenario_mgr=scenario_mgr, actor=pl_id,
                    )
                    pc_action = apply_s4_candidate_override(
                        state, pc_action, scenario_mgr=scenario_mgr, actor=pl_id,
                    )
            except Exception:
                # If NDM required, re-raise; otherwise fall back to legacy guidance.
                from reasoning.runtime import get_active_runtime as _gar2, NDMInitFailure
                rt = _gar2()
                if rt is not None and rt.required:
                    raise
                pc_action = apply_stall_candidate_guidance(
                    state, pc_action, scenario_mgr=scenario_mgr, actor=pl_id,
                )
                pc_action = apply_s4_candidate_override(
                    state, pc_action, scenario_mgr=scenario_mgr, actor=pl_id,
                )
        if pc_action is not original_pc_action and (
            pc_action.get("director_forced") or pc_action.get("director_guided")
        ):
            director_forced = bool(pc_action.get("director_forced"))
            director_origin = SYSTEM_FORCED if director_forced else SYSTEM_GUIDED
            director_level = str(pc_action.get("intervention_level") or ("S4" if director_forced else "S2"))
            # A chat-only or rejected model response may already own a settled
            # transaction.  S4 is a new executable action and must never reuse
            # that transaction or mutate an earlier action log.
            pc_action.pop("needs_pl_retry", None)
            pc_action.pop("settled_event_kind", None)
            pc_action.pop("intent_non_execute", None)
            pc_action["original_transaction_id"] = pc_action.get("transaction_id") or ""
            pc_action["transaction_id"] = new_action_transaction_id()
            pc_action["actor_id"] = pl_id
            pc_action["decision_owner_id"] = pl_id
            pc_action["needs_system"] = True
            pc_action["system_processed"] = False
            fixed_message = _build_pc_display_message(
                "", pc_action.get("action", "wait"), pc_action.get("target", ""),
                scenario_mgr=scenario_mgr, current_loc=current_loc,
            )
            pc_action["message"] = fixed_message
            transaction_id = str(pc_action.get("transaction_id") or "")
            updated_action_log = False
            for entry in reversed(state.get("all_events_log") or []):
                meta = entry.get("meta") or {}
                if transaction_id and str(meta.get("transaction_id") or "") != transaction_id:
                    continue
                if meta.get("pc_id") == pl_id and meta.get("action_id"):
                    meta.update({
                        "action_id": pc_action.get("action"),
                        "target": pc_action.get("target"),
                        "skill": pc_action.get("skill"),
                        "action_origin": director_origin,
                        "director_forced": director_forced,
                        "director_guided": not director_forced,
                        "intervention_level": director_level,
                        "progression_binding": copy.deepcopy(
                            pc_action.get("progression_binding") or {}
                        ),
                        "required_location": pc_action.get("required_location") or "",
                    })
                    entry["meta"] = meta
                    entry["text"] = f"{format_pc_log_prefix(char_mgr, pl_id)}: {fixed_message}"
                    updated_action_log = True
                    break
            if not updated_action_log:
                state.setdefault("all_events_log", []).append({
                    "channel": "IC", "location": current_loc, "secret_to": None,
                    "text": f"{format_pc_log_prefix(char_mgr, pl_id)}: {fixed_message}",
                    "meta": {
                        "pc_id": pl_id,
                        "actor_id": pl_id,
                        "decision_owner_id": pl_id,
                        "action_id": pc_action.get("action"),
                        "target": pc_action.get("target"),
                        "skill": pc_action.get("skill"),
                        "needs_system": True,
                        "system_processed": False,
                        "transaction_id": transaction_id,
                        "action_origin": director_origin,
                        "director_forced": director_forced,
                        "director_guided": not director_forced,
                        "intervention_level": director_level,
                        "progression_binding": copy.deepcopy(
                            pc_action.get("progression_binding") or {}
                        ),
                        "required_location": pc_action.get("required_location") or "",
                    },
                })
            state.setdefault("all_events_log", []).append({
                "channel": "OOC", "location": "all", "secret_to": None,
                    "text": (
                        "[Combat Director] 戦闘外行動を拒否し、合法な戦闘候補へ誘導します。"
                        if pc_action.get("combat_guided") else
                    "[Session Director v2] S3候補が選ばれなかったため、S4として最優先候補を実行します。"
                    if director_forced else
                    "[Session Director v2] 消化済み対象または行動フェーズ不一致を検出し、最優先候補へ誘導します。"
                ),
                "meta": {
                    "director_intervention": True,
                    "intervention_level": director_level,
                    "action_origin": director_origin,
                    "transaction_id": transaction_id,
                    "pc_id": pl_id,
                },
            })

    def _record_validation_retry(action):
        code = str((action or {}).get("validation_error_code") or "")
        meta = dict(state.get("validation_retry_state") or {})
        if not code:
            state["validation_retry_state"] = {}
            return 0
        if meta.get("error_code") == code and meta.get("pc_id") == pl_id:
            meta["count"] = int(meta.get("count") or 0) + 1
        else:
            meta = {"error_code": code, "pc_id": pl_id, "count": 1}
        state["validation_retry_state"] = meta
        return int(meta.get("count") or 0)

    def _maybe_force_breakout_for_retry_loop(action):
        count = _record_validation_retry(action)
        flags = (scenario_mgr.flags if scenario_mgr else None) or {}
        # ボストン・グローブ許可未取得時は交渉再挑戦の猶予を与え、単発失敗で飛ばさない
        negotiate_grace = (
            current_loc == "boston_globe"
            and flags.get("artie_introduced")
            and not flags.get("artie_reference_room_access_granted")
        )
        threshold = (
            BOSTON_GLOBE_NEGOTIATE_GRACE_RETRY_COUNT
            if negotiate_grace
            else VALIDATION_RETRY_BREAKOUT_COUNT
        )
        if (
            negotiate_grace
            and count >= 2
            and count < threshold
            and (action or {}).get("needs_pl_retry")
        ):
            state["stagnation_pl_hint"] = _build_negotiate_fail_stagnation_hint(
                char_mgr=char_mgr,
                pl_id=pl_id,
                skill_used=str((action or {}).get("skill") or ""),
                active_pcs=state.get("active_pcs") or getattr(char_mgr, "active_pc_list", None),
                failed_target=str((action or {}).get("target") or "artie_wilmott"),
            )
            return None
        if (
            not discussion
            and not san_locked
            and count >= threshold
            and (action or {}).get("needs_pl_retry")
        ):
            state.setdefault("all_events_log", []).append({
                "channel": "OOC",
                "location": "all",
                "secret_to": None,
                "text": (
                    "[システム] 同一の無効行動が連続したため、"
                    "次の有効行動へ自動移行します。"
                ),
                "meta": {
                    "validation_retry_breakout": True,
                    "error_code": (action or {}).get("validation_error_code"),
                    "count": count,
                    "pc_id": pl_id,
                },
            })
            managers = (char_mgr, DiceEngine(), state_mgr, scenario_mgr)
            forced = apply_forced_progress_breakout(
                state, managers, pl_id=pl_id, char_name=char_name,
            )
            if forced:
                state["validation_retry_state"] = {}
                return forced
        return None

    forced_by_retry = _maybe_force_breakout_for_retry_loop(pc_action)
    if forced_by_retry:
        return forced_by_retry
    # 移動意図不一致など: システムエラーをプロンプトに載せ、PLに再生成させる
    max_validation_retries = 2
    retry = 0
    while pc_action.get("needs_pl_retry") and retry < max_validation_retries and not discussion:
        retry += 1
        err = pc_action.get("validation_error") or MOVE_INTENT_MISMATCH_ERROR
        suggested = pc_action.get("suggested_fix") or {}
        suggest_line = ""
        if suggested:
            suggest_line = (
                f"推奨修正例: action=`{suggested.get('action', '')}` "
                f"target=`{suggested.get('target', '')}`\n"
            )
        retry_prompt = (
            f"{PL_RETRY_PROMPT_PREFIX}{err}\n{suggest_line}\n{pl_prompt}"
        )
        ai_data = call_pl_api(
            retry_prompt,
            action_locked=san_locked or discussion,
            san_source=san_source,
            active_pc_id=pl_id,
            char_mgr=char_mgr,
            discussion_mode=discussion,
        )
        pc_action = apply_pl_response_to_logs(
            ai_data, char_name, current_loc, state["all_events_log"],
            pending_san_check=state.get("pending_san_check"),
            scenario_mgr=scenario_mgr,
            pc_id=pl_id,
            char_mgr=char_mgr,
            force_ic_action=force_ic,
            pending_push_roll=state.get("pending_push_roll"),
        )
        forced_by_retry = _maybe_force_breakout_for_retry_loop(pc_action)
        if forced_by_retry:
            return forced_by_retry

    # 同一手番内の再生成上限に達したら打ち切る。無限再呼び出しはしない。
    # 制御は呼び出し元へ返し、needs_pl_retry 経由で停滞計上・次手番の再選択へ繋ぐ。
    if pc_action.get("needs_pl_retry") and not discussion and not san_locked:
        pc_action = dict(pc_action)
        pc_action["validation_regen_capped"] = True
        ensure_settled_nonprogress_event_id(pc_action, event_kind="validation_reject")
        # 連続拒否カウントを進め、閾値で既存ブレイクアウトへ
        forced_by_retry = _maybe_force_breakout_for_retry_loop(pc_action)
        if forced_by_retry:
            return forced_by_retry
        if not _is_duplicate_validation_error_log(
            state.get("all_events_log"),
            error_code=str(pc_action.get("validation_error_code") or ""),
            pc_id=pl_id,
            message="再生成上限",
        ):
            state.setdefault("all_events_log", []).append({
                "channel": "OOC",
                "location": "all",
                "secret_to": None,
                "text": (
                    "[システム] 同一手番の再生成上限に達したため、今回の出力は採用せず手番を終了します。"
                    "次の手番で行動を再選択してください。"
                ),
                "meta": {
                    "validation_regen_capped": True,
                    "error_code": pc_action.get("validation_error_code"),
                    "pc_id": pl_id,
                    "transaction_id": pc_action.get("transaction_id"),
                },
            })
        # メタのみだと末尾が empty → kp_opening に落ちる。PL OOC を残して
        # 既存の free_chat / pl_speak 再選択経路へつなぐ。
        pl_prefix = format_pc_log_prefix(char_mgr, pl_id, role="PL")
        if not any(
            (e.get("meta") or {}).get("validation_regen_capped")
            and (e.get("meta") or {}).get("hand_off")
            and (e.get("meta") or {}).get("pc_id") == pl_id
            for e in (state.get("all_events_log") or [])[-6:]
        ):
            state.setdefault("all_events_log", []).append({
                "channel": "OOC",
                "location": "all",
                "secret_to": None,
                "text": (
                    f"{pl_prefix}: （再生成上限のため今回は不採用。"
                    "次の手番で行動を再選択する）"
                ),
                "meta": {
                    "validation_regen_capped": True,
                    "hand_off": True,
                    "pc_id": pl_id,
                    "transaction_id": pc_action.get("transaction_id"),
                    "error_code": pc_action.get("validation_error_code"),
                },
            })

    # 強制 IC フェーズなのに wait/無駄 talk → 再プロンプトで有効行動を要求
    force_retries = 0
    while (
        force_ic
        and not discussion
        and not san_locked
        and not pc_action.get("validation_regen_capped")
        and (
            is_nonprogress_pl_action(
                pc_action, state.get("pending_san_check"),
                scenario_mgr=scenario_mgr, current_loc=current_loc, char_mgr=char_mgr,
            )
            or pc_action.get("needs_pl_retry")
        )
        and force_retries < 2
    ):
        force_retries += 1
        retry_prompt = (
            f"{PL_RETRY_PROMPT_PREFIX}{OOC_LOOP_FORCE_ACTION_WARNING}\n"
            f"{FORCE_IC_WAIT_REJECT_ERROR}\n"
            f"{STALE_KNOTT_TALK_REJECT_ERROR}\n"
            "直前の出力はメタ発言・wait・または進展のない talk でした。無効です。"
            "必ず IC で有効な action（move / search / inspect 等）を出してください。\n"
            f"{pl_prompt}"
        )
        ai_data = call_pl_api(
            retry_prompt,
            action_locked=False,
            san_source=None,
            active_pc_id=pl_id,
            char_mgr=char_mgr,
            discussion_mode=False,
        )
        pc_action = apply_pl_response_to_logs(
            ai_data, char_name, current_loc, state["all_events_log"],
            pending_san_check=state.get("pending_san_check"),
            scenario_mgr=scenario_mgr,
            pc_id=pl_id,
            char_mgr=char_mgr,
            force_ic_action=True,
            pending_push_roll=state.get("pending_push_roll"),
        )
        forced_by_retry = _maybe_force_breakout_for_retry_loop(pc_action)
        if forced_by_retry:
            return forced_by_retry

    # 最終防壁: ヒント提示済み（なければ場面依存ヒントを生成）+ chat_rounds 上限 → 強制行動
    chat_rounds = get_chat_rounds_without_action(state)
    still_stuck = is_nonprogress_pl_action(
        pc_action, state.get("pending_san_check"),
        scenario_mgr=scenario_mgr, current_loc=current_loc, char_mgr=char_mgr,
    ) or pc_action.get("needs_pl_retry")
    if (
        force_ic
        and not discussion
        and not san_locked
        and still_stuck
        and chat_rounds >= FORCE_IC_ACTION_CHAT_ROUNDS
    ):
        if not str(state.get("stagnation_pl_hint") or "").strip():
            _maybe_set_context_stagnation_hint(state, scenario_mgr, state_mgr)
            if not str(state.get("stagnation_pl_hint") or "").strip():
                state["stagnation_pl_hint"] = build_context_stagnation_hint(
                    scenario_mgr, current_loc, fallback=STAGNATION_STANDARD_PL_HINT,
                )
        managers = (char_mgr, DiceEngine(), state_mgr, scenario_mgr)
        forced = apply_forced_progress_breakout(
            state, managers, pl_id=pl_id, char_name=char_name,
        )
        if forced:
            return forced

    # 許可取得後: search せず wait/無効を一定ターン続けたら強制 search
    if not discussion and not san_locked and not combat_active:
        managers = (char_mgr, DiceEngine(), state_mgr, scenario_mgr)
        action_id = str((pc_action or {}).get("action") or "").lower()
        target = str((pc_action or {}).get("target") or "")
        is_clipping_search = (
            action_id in ("search", "inspect")
            and target == "reference_room_clipping_files"
        )
        if not is_clipping_search:
            # 現在ターンの無効行動も streak に含めるため仮でログ相当をカウント
            # （pc_action がまだ last に入る前なので +1 相当を閾値判定に反映）
            pending_streak = _count_post_access_non_search_streak(
                state.get("all_events_log") or []
            )
            if (
                _clipping_files_search_pending(scenario_mgr, current_loc)
                and pending_streak + 1 >= STAGNATION_HINT_TURNS
            ):
                state["stagnation_pl_hint"] = ARTIE_ACCESS_GRANTED_SEARCH_HINT
                _append_stagnation_hint_log(state, ARTIE_ACCESS_GRANTED_SEARCH_HINT)
            if (
                _clipping_files_search_pending(scenario_mgr, current_loc)
                and (
                    pending_streak + 1 >= POST_ACCESS_SEARCH_FORCE_TURNS
                    or still_stuck
                    or action_id in ("wait", "none", "")
                    or pc_action.get("needs_pl_retry")
                )
                and pending_streak >= max(1, POST_ACCESS_SEARCH_FORCE_TURNS - 1)
            ):
                state["stagnation_pl_hint"] = ARTIE_ACCESS_GRANTED_SEARCH_HINT
                forced = apply_forced_progress_breakout(
                    state, managers, pl_id=pl_id, char_name=char_name,
                )
                if forced:
                    return forced

    # 調査枯渇: 先にヒント、上限ターンで次ロケーションへ強制移動
    if not discussion and not san_locked and not combat_active:
        managers = (char_mgr, DiceEngine(), state_mgr, scenario_mgr)
        action_id = str((pc_action or {}).get("action") or "").lower()
        if action_id != "move":
            forced = _maybe_force_location_exhausted_move(
                state, managers, pl_id=pl_id, char_name=char_name,
                pending_non_move=True,
            )
            if forced:
                return forced
        elif should_apply_location_exhausted_move(scenario_mgr, current_loc):
            state["stagnation_pl_hint"] = build_location_exhausted_move_hint(
                scenario_mgr, current_loc,
            )

    # 失敗・拒否後の同一ロケ膠着: 先にマイルドヒント、上限ターンで強制移動
    if not discussion and not san_locked and not combat_active:
        managers = (char_mgr, DiceEngine(), state_mgr, scenario_mgr)
        action_id = str((pc_action or {}).get("action") or "").lower()
        if action_id != "move":
            forced = _maybe_force_investigation_deadlock_move(
                state, managers, pl_id=pl_id, char_name=char_name,
                pending_non_move=True,
            )
            if forced:
                return forced
        elif is_investigation_deadlock(state.get("all_events_log") or [], current_loc):
            state["stagnation_pl_hint"] = INVESTIGATION_BAILOUT_HINT

    if force_ic and not is_nonprogress_pl_action(
        pc_action, state.get("pending_san_check"),
        scenario_mgr=scenario_mgr, current_loc=current_loc, char_mgr=char_mgr,
    ):
        clear_force_ic_action_phase(state)

    # SYSTEM に行かない確定イベント（OOC / 検証拒否）は、手番確定時に ID を持たせる
    # （評価呼び出しでは発行しない。既存 ID は保持）
    if pc_action.get("needs_pl_retry"):
        ensure_settled_nonprogress_event_id(pc_action, event_kind="validation_reject")
    elif is_chat_only_pl_action(pc_action, state.get("pending_san_check")):
        ensure_settled_nonprogress_event_id(pc_action, event_kind="ooc_chat")

    if pc_action.get("transaction_id") and (
        pc_action.get("needs_pl_retry")
        or is_chat_only_pl_action(pc_action, state.get("pending_san_check"))
    ):
        tid = pc_action["transaction_id"]
        new_logs = state["all_events_log"][turn_log_start:]
        if not any(str((entry.get("meta") or {}).get("transaction_id") or "") == tid for entry in new_logs):
            event_kind = "validation_reject" if pc_action.get("needs_pl_retry") else "ooc_chat"
            untagged = next((
                entry for entry in reversed(new_logs)
                if entry.get("channel") == "OOC"
                and (entry.get("meta") or {}).get("pc_id") == pl_id
                and not (entry.get("meta") or {}).get("transaction_id")
            ), None)
            if untagged is not None:
                untagged["meta"] = stamp_event_transaction_on_log_meta(
                    untagged.get("meta"), tid, event_kind=event_kind, pc_id=pl_id,
                )
            else:
                pl_prefix = format_pc_log_prefix(char_mgr, pl_id, role="PL")
                spoken = str(ai_data.get("pl_ooc_chat") or "").strip()
                state["all_events_log"].append({
                    "channel": "OOC", "location": "all", "secret_to": None,
                    "text": f"{pl_prefix}: {spoken or '（行動を再選択する）'}",
                    "meta": stamp_event_transaction_on_log_meta(
                        {"pc_id": pl_id}, tid, event_kind=event_kind, pc_id=pl_id,
                    ),
                })

    action_origin = (
        SYSTEM_FORCED
        if pc_action.get("director_forced") or pc_action.get("auto_corrected") or pc_action.get("intent_replaced")
        else SYSTEM_GUIDED
        if pc_action.get("combat_guided")
        else classify_action_origin(
            state, pc_action.get("action"), pc_action.get("target"), forced=False,
        )
    )
    pc_action["action_origin"] = action_origin
    if not pc_action.get("availability_snapshot"):
        for item in (((state.get("director_v2") or {}).get("goal") or {}).get("candidate_next_actions") or []):
            if (
                str(item.get("action") or "") == str(pc_action.get("action") or "")
                and str(item.get("target") or "") == str(pc_action.get("target") or "")
            ):
                pc_action["availability_snapshot"] = copy.deepcopy(
                    item.get("availability_snapshot") or {}
                )
                break
    director_runtime = state.get("director_v2") or {}
    pc_action["_director_state_before"] = copy.deepcopy(director_runtime.get("state_before") or {})
    pc_action["_director_goal_before"] = copy.deepcopy(director_runtime.get("goal_before") or {})
    stamp_action_origin(
        state.get("all_events_log"), pc_action.get("transaction_id"), action_origin,
    )
    if combat_active and pc_action.get("transaction_id"):
        # The timeline log is the durable hand-off between PL selection and the
        # system resolver. Preserve combat-only routing data there as well as in
        # last_pl_action so reruns and queued execution cannot lose it.
        combat_tid = str(pc_action.get("transaction_id") or "")
        for entry in reversed(state.get("all_events_log") or []):
            meta = dict(entry.get("meta") or {})
            if str(meta.get("transaction_id") or "") != combat_tid:
                continue
            if not meta.get("action_id"):
                continue
            meta["combat_action_category"] = pc_action.get("combat_action_category") or ""
            meta["combat_goal"] = pc_action.get("combat_goal") or getattr(state_mgr, "combat_goal", "")
            meta["combat_legality"] = pc_action.get("combat_legality") or "LEGAL"
            entry["meta"] = meta
            break
    state["last_pl_action"] = pc_action
    if pc_action.get("transaction_id"):
        bind_action_transaction(
            state,
            transaction_id=pc_action.get("transaction_id"),
            actor_id=pc_action.get("actor_id") or pl_id,
            decision_owner_id=pc_action.get("decision_owner_id") or pl_id,
        )
        if pc_action.get("needs_pl_retry") or is_chat_only_pl_action(
            pc_action, state.get("pending_san_check"),
        ):
            # SYSTEM を通らない手番はここで確定し、pending を孤児にしない。
            commit_action_transaction(state, pc_action["transaction_id"])
    if not pc_action.get("needs_pl_retry"):
        state["validation_retry_state"] = {}
    if not force_ic:
        # 許可後の search 誘導／調査枯渇 move／交渉再挑戦ヒントは保持する
        hint = str(state.get("stagnation_pl_hint") or "")
        keep_hint = (
            "reference_room_clipping_files" in hint
            or "許可は取得済み" in hint
            or "調査はすべて完了" in hint
            or "別交渉技能" in hint
            or "再挑戦" in hint
            or "即時撤退" in hint
            or "コービット屋敷" in hint
            or "すべての資料を集める必要" in hint
        )
        if not keep_hint:
            state["stagnation_pl_hint"] = None
    if combat_active and not pc_action.get("needs_pl_retry"):
        append_combat_event(
            state, "COMBAT_ACTION_SELECTED", state_mgr=state_mgr,
            actor=pl_id,
            actor_state={
                "HP": char_mgr.get_stat_current(pl_id, "HP"),
                "SAN": char_mgr.get_stat_current(pl_id, "SAN"),
            },
            target=pc_action.get("target") or "",
            combat_goal=pc_action.get("combat_goal") or getattr(state_mgr, "combat_goal", ""),
            action_category=pc_action.get("combat_action_category") or "",
            selected_action=pc_action.get("action") or "",
            action_origin=action_origin,
            legality=pc_action.get("combat_legality") or "LEGAL",
            skill=pc_action.get("skill") or "",
            HP_before=char_mgr.get_stat_current(pl_id, "HP"),
            SAN_before=char_mgr.get_stat_current(pl_id, "SAN"),
            position_before=current_loc,
            position_after=current_loc,
            transaction_id=pc_action.get("transaction_id") or "",
        )
    # 再生成上限: 同一 transaction では手番交代を一度だけ行い、連鎖で二重に進めない
    if (
        pc_action.get("validation_regen_capped")
        and not discussion
        and not san_locked
        and char_mgr
        and not (state_mgr and getattr(state_mgr, "in_combat", False))
    ):
        tid = str(pc_action.get("transaction_id") or "").strip()
        already = str(state.get("validation_regen_cap_advanced_tid") or "").strip()
        if tid and already == tid:
            pass
        else:
            advance_exploration_turn(state, char_mgr, state_mgr)
            if tid:
                state["validation_regen_cap_advanced_tid"] = tid
    return pc_action


def step_pl_discussion(state, char_mgr, scenario_mgr, state_mgr=None):
    """PENDING_PL_DISCUSSION: 参加PCが交互にOOC相談（ダイスなし）。"""
    ensure_multi_pl_state(state, char_mgr)
    state["pl_discussion_mode"] = True
    rounds = int(state.get("pl_discussion_rounds") or 0)
    max_rounds = int(state.get("pl_discussion_max_rounds") or 4)

    if rounds >= max_rounds:
        state["pl_discussion_mode"] = False
        state["pl_discussion_rounds"] = 0
        sync_timeline_pending_phase(state)
        state["all_events_log"].append({
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": "[システム] 作戦会議を終了し、探索を再開します。",
        })
        return None

    advance_exploration_turn(state, char_mgr, state_mgr)
    pc_action = step_pl_turn(
        state, char_mgr, scenario_mgr,
        state.get("pl_id"), state.get("char_name"),
        state_mgr=state_mgr,
    )
    state["pl_discussion_rounds"] = rounds + 1

    # 合意シグナル
    ooc = ""
    for entry in reversed(state.get("all_events_log") or []):
        if entry.get("channel") == "OOC" and "(PL):" in entry.get("text", ""):
            ooc = entry.get("text", "")
            break
    if any(k in ooc for k in ("合意", "決まり", "行こう", "調査しよう", "end_discussion")):
        state["pl_discussion_mode"] = False
        state["pl_discussion_rounds"] = 0
        sync_timeline_pending_phase(state)
        state["all_events_log"].append({
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": "[システム] 探索者たちが合意した。作戦会議を終了する。",
        })
    return pc_action


def append_pl_turn_fallback_if_silent(state, before_len):
    """PL手番後にログが増えていなければ、空振りループ防止のシステム行を1件追加する。

    直前が同一テキストなら追加しない（連打デバウンス）。
    """
    logs = state.setdefault("all_events_log", [])
    if len(logs) > before_len:
        return False
    # 直近数件に同一フォールバックがあれば再追加しない
    for entry in reversed(logs[-5:]):
        if (entry or {}).get("text") == PL_TURN_SILENT_FALLBACK_LOG:
            return False
    logs.append({
        "channel": "OOC",
        "location": "all",
        "secret_to": None,
        "text": PL_TURN_SILENT_FALLBACK_LOG,
    })
    return True


def step_free_chat_exchange(state, char_mgr, scenario_mgr, pl_id, char_name, guard=None, state_mgr=None):
    """KP/PL OOC 末尾に対し PL が応答する。KP同一サイクル追撃は行わない。"""
    before_len = len(state.get("all_events_log", []))
    pc_action = step_pl_turn(
        state, char_mgr, scenario_mgr, pl_id, char_name, state_mgr=state_mgr,
    )
    if isinstance(pc_action, dict) and pc_action.get("_llm_failure"):
        return pc_action, None
    if guard:
        guard.record_pl_action(
            pc_action, state.get("pending_san_check"),
            scenario_mgr=scenario_mgr,
            current_loc=state.get("current_loc"),
            char_mgr=char_mgr,
        )
    actor_label = f"PL:{state.get('pl_id', pl_id)}"
    if append_pl_turn_fallback_if_silent(state, before_len):
        return pc_action, "SYSTEM"
    return pc_action, actor_label


def step_system_resolve_san(state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name):
    """保留中 SAN をシステムが自動解決し、タイムラインへ結果を書き込む。"""
    ensure_multi_pl_state(state, char_mgr)
    pl_id = state.get("pl_id") or pl_id
    char_name = state.get("char_name") or char_name
    pending = dict(state.get("pending_san_check") or {})
    san_result = _auto_resolve_pending_san_check(
        pl_id, char_name, state["current_loc"],
        char_mgr, dice_engine, scenario_mgr, state_mgr, pending,
    )

    intro_log = str(pending.get("room_entry_intro") or "").strip()
    intro_kp = str(pending.get("room_entry_kp_instruction") or "").strip()
    if not intro_log:
        preface = state.get("last_system_result") or {}
        if preface.get("room_entry_san"):
            intro_log = str(preface.get("log") or "").strip()
            intro_kp = str(preface.get("kp_instruction") or "").strip()
    if intro_log:
        san_result["log"] = f"{intro_log}\n{san_result.get('log', '')}".strip()
    if intro_kp:
        san_result["kp_instruction"] = (
            f"{intro_kp}\n{san_result.get('kp_instruction', '')}".strip()
        )
    san_result["room_entry_san"] = bool(pending.get("room_entry"))

    apply_system_roll_state_updates(state, san_result, had_san_pending=True)
    append_system_log_entry(
        state["all_events_log"], state["current_loc"], san_result.get("log", ""),
        action_id="wait",
        target=san_result.get("target_id") or pl_id,
        roll_type=san_result.get("roll_type", "san_check"),
        actor_id=san_result.get("actor_id") or pl_id,
        adjudication=san_result,
    )
    state["last_system_result"] = san_result
    return san_result


def step_system_process(state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name):
    """PL行動の判定をアトミックに Commit する（KP呼び出しなし）。

    完了時: フラグ/SAN/ダイス結果を確定し、meta.kp_narrated=False のシステムログを積む。
    続く kp_narrate ステップが描写のみを担当する。

    タスク2: 同一 transaction_id の再実行はダイス・状態更新をスキップ（冪等）。
    """
    current_loc = state["current_loc"]
    state["partial_system_log"] = None
    state = normalize_loaded_runtime_state(state, enforce_half_turn_pause=False)
    ensure_transaction_state_fields(state)
    ensure_multi_pl_state(state, char_mgr)
    normalize_game_action_targets(state, scenario_mgr, current_loc, char_mgr=char_mgr)
    action_data = _action_data_from_timeline(state, scenario_mgr, char_name, char_mgr=char_mgr)
    pl_id = state.get("pl_id") or pl_id
    char_name = state.get("char_name") or char_name
    entry = state.get("_pending_system_pl_entry")

    txn_id, actor_id, decision_owner_id = resolve_action_transaction_context(
        state, action_data, entry, default_actor=pl_id,
    )
    state["last_pl_action"] = action_data

    # 冪等ガード: 既 Commit の同一行動は再ロールしない
    if is_duplicate_action_transaction(state, txn_id, entry=entry):
        state.pop("_pending_system_pl_entry", None)
        return build_idempotent_system_result(state, transaction_id=txn_id)

    had_san_pending = _is_san_check_pending(state.get("pending_san_check"))
    result = process_system_action(
        pl_id, char_name,
        action_data.get("action", "wait"),
        action_data.get("target", ""),
        action_data.get("skill", ""),
        current_loc,
        char_mgr, dice_engine, scenario_mgr,
        state.get("pending_san_check"),
        state_mgr,
        state.get("pending_push_roll"),
        active_pcs=state.get("active_pcs"),
        dialogue_text=action_data.get("dialogue") or action_data.get("message", ""),
        game_state=state,
    )
    if action_data.get("progression_binding"):
        mark_progression_adjudication_started(action_data, result)
        state["last_pl_action"] = action_data
    # 不在NPCブロック等で注入された代替ヒントを保持
    if result.get("stagnation_pl_hint"):
        state["stagnation_pl_hint"] = result["stagnation_pl_hint"]
    elif result.get("blocked") and _clipping_files_search_pending(scenario_mgr, current_loc):
        if not str(state.get("stagnation_pl_hint") or "").strip():
            state["stagnation_pl_hint"] = ARTIE_ACCESS_GRANTED_SEARCH_HINT

    def _half_commit_pending(result_obj):
        """幸運/プッシュ/防衛待ちの途中確定でも transaction を Commit 済みにする。"""
        append_system_log_entry(
            state["all_events_log"], current_loc, result_obj["log"],
            action_id=result_obj.get("action_id", action_data.get("action", "")),
            target=result_obj.get("target", action_data.get("target", "")),
            roll_type=result_obj.get("roll_type", ""),
            transaction_id=txn_id,
            actor_id=actor_id,
            decision_owner_id=decision_owner_id,
            adjudication=result_obj,
        )
        _mark_timeline_pl_action_processed(state)
        commit_action_transaction(state, txn_id)
        result_obj = dict(result_obj)
        result_obj["transaction_id"] = txn_id
        result_obj["stagnation_transaction_id"] = txn_id
        # 子判断（幸運・プッシュ）に親IDを引き継ぐ
        if result_obj.get("pending_luck_burn"):
            pending_luck = dict(result_obj["pending_luck_burn"])
            pending_luck["parent_transaction_id"] = txn_id
            pending_luck.setdefault("transaction_id", txn_id)
            pending_luck["decision_owner_id"] = actor_id
            pending_luck["actor_id"] = actor_id
            result_obj["pending_luck_burn"] = pending_luck
        if result_obj.get("pending_push_roll"):
            pending_push = dict(result_obj["pending_push_roll"])
            pending_push["parent_transaction_id"] = txn_id
            pending_push.setdefault("transaction_id", txn_id)
            pending_push["decision_owner_id"] = actor_id
            pending_push["actor_id"] = actor_id
            result_obj["pending_push_roll"] = pending_push
        state["last_system_result"] = result_obj
        return result_obj

    if result.get("luck_decision_required"):
        pending_luck = dict(result.get("pending_luck_burn") or {})
        pending_luck["decision_owner_id"] = actor_id
        pending_luck["actor_id"] = actor_id
        state["pending_luck_burn"] = pending_luck
        state["partial_system_log"] = result.get("partial_log", result.get("log", ""))
        state["push_decision_required"] = False
        # 幸運判断の意思決定主体は行動PC
        state["decision_owner_id"] = actor_id
        state["pending_decision"] = result.get("pending_decision") or build_post_roll_pending_decision(
            target_action_id=pending_luck.get("original_action") or "",
            decision_owner_id=actor_id,
            skill_name=pending_luck.get("skill_name") or "",
            action_id=pending_luck.get("original_action") or "",
            legal_options=pending_luck.get("legal_options"),
            luck_cost=pending_luck.get(
                "luck_cost", pending_luck.get("margin")
            ),
            margin=int(pending_luck.get("margin") or 0),
            allow_push=bool(pending_luck.get("allow_push", True)),
        )
        sync_timeline_pending_phase(state)
        return _half_commit_pending(result)

    if result.get("combat_defense_required"):
        pending = result.get("pending_combat_defense")
        state["pending_combat_defense"] = pending
        if state_mgr:
            state_mgr.set_pending_combat_defense(pending)
        state["partial_system_log"] = result.get("partial_log", result.get("log", ""))
        # 防衛の意思決定主体は防御側
        defender = (pending or {}).get("defender_id") or decision_owner_id
        state["decision_owner_id"] = defender
        state["actor_id"] = (pending or {}).get("attacker_id") or actor_id
        state["pending_decision"] = result.get("pending_decision") or build_combat_pending_decision(
            pending, decision_owner_id=defender,
        )
        sync_timeline_pending_phase(state)
        return _half_commit_pending(result)

    if result.get("push_decision_required"):
        pending_push = dict(result.get("pending_push_roll") or {})
        pending_push["decision_owner_id"] = actor_id
        pending_push["actor_id"] = actor_id
        state["pending_push_roll"] = pending_push
        state["partial_system_log"] = result.get("partial_log", result.get("log", ""))
        state["push_decision_required"] = True
        state["pending_luck_burn"] = None
        state["decision_owner_id"] = actor_id
        state["pending_decision"] = result.get("pending_decision") or build_pending_decision(
            decision_type=PENDING_DECISION_POST_ROLL_FAILURE,
            target_action_id=pending_push.get("original_action") or "",
            decision_owner_id=actor_id,
            legal_options=pending_push.get("legal_options")
            or [DECISION_OPTION_ACCEPT, DECISION_OPTION_PUSH],
            luck_cost=None,
        )
        sync_timeline_pending_phase(state)
        return _half_commit_pending(result)

    clear_pending_decision(state)
    return commit_system_resolution(
        state, result,
        current_loc=current_loc,
        action_data=action_data,
        had_san_pending=had_san_pending,
        char_mgr=char_mgr,
        dice_engine=dice_engine,
        scenario_mgr=scenario_mgr,
        state_mgr=state_mgr,
        pl_id=pl_id,
        char_name=char_name,
        auto_resolve_san=True,
        transaction_id=txn_id,
    )


def step_luck_decision(state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name):
    pending = state.get("pending_luck_burn")
    if not pending:
        return

    # 画面上の現在PCではなく、元判定の所有者を判断主体にする（active_pc は書き換えない）
    owner_id = resolve_pending_decision_owner(state, pending, fallback_pl_id=pl_id)
    if char_mgr and owner_id:
        try:
            owner_name = char_mgr.get_pc_name(owner_id, default=char_name)
        except TypeError:
            owner_name = char_mgr.get_pc_name(owner_id) or char_name
    else:
        owner_name = char_name
    pl_id = owner_id or pl_id
    char_name = owner_name or char_name

    partial_log = state.get("partial_system_log", "")
    current_loc = state["current_loc"]
    ic_logs, ooc_logs = format_prompt_history_logs(
        pl_id, current_loc, state["all_events_log"], char_mgr=char_mgr,
    )
    pl_prompt = generate_pl_luck_prompt(
        char_name, pending, char_mgr, pl_id, ic_logs, ooc_logs,
        scenario_mgr=scenario_mgr,
        all_events_log=state.get("all_events_log"),
        game_state=state,
    )
    ai_data = call_pl_api(
        pl_prompt, json_schema=PL_LUCK_JSON_SCHEMA,
        active_pc_id=pl_id, char_mgr=char_mgr,
    )
    use_luck = bool(ai_data.get("use_luck", False))
    pl_chat = ai_data.get("pl_ooc_chat", "")
    if pl_chat:
        prefix = format_pc_log_prefix(char_mgr, pl_id, role="PL")
        state["all_events_log"].append({
            "channel": "OOC", "location": "all", "secret_to": None,
            "text": f"{prefix}: {pl_chat}",
            "meta": {"pc_id": pl_id},
        })

    result = resolve_luck_burn_decision(
        pl_id, char_name, use_luck, pending, current_loc,
        char_mgr, scenario_mgr, partial_log,
    )
    state["pending_luck_burn"] = None

    if result.get("push_decision_required"):
        pending_push = dict(result.get("pending_push_roll") or {})
        parent_tid = str(
            pending.get("parent_transaction_id")
            or pending.get("transaction_id")
            or state.get("last_processed_action_id")
            or ""
        )
        if parent_tid:
            pending_push["parent_transaction_id"] = parent_tid
            pending_push.setdefault("transaction_id", parent_tid)
        result = dict(result)
        result["pending_push_roll"] = pending_push
        if parent_tid:
            result["parent_transaction_id"] = parent_tid
            result["stagnation_transaction_id"] = parent_tid
            result.setdefault("transaction_id", parent_tid)
        state["pending_push_roll"] = pending_push
        state["partial_system_log"] = result.get("partial_log", result.get("log", ""))
        state["push_decision_required"] = True
        state["pending_decision"] = result.get("pending_decision") or build_pending_decision(
            decision_type=PENDING_DECISION_POST_ROLL_FAILURE,
            target_action_id=pending.get("original_action") or "",
            decision_owner_id=state.get("decision_owner_id") or pl_id,
            legal_options=[DECISION_OPTION_ACCEPT, DECISION_OPTION_PUSH],
            luck_cost=None,
        )
        sync_timeline_pending_phase(state)
        _append_result_log_with_knowledge(
            state, result,
            current_loc=current_loc,
            char_mgr=char_mgr,
            pl_id=result.get("actor_id") or pl_id,
            action_id=result.get("action_id", pending.get("original_action", "")),
            target=result.get("target_id") or result.get("target", pending.get("target", "")),
            roll_type=result.get("roll_type", "skill"),
        )
        state["last_system_result"] = result
        return result

    state["partial_system_log"] = None
    state["push_decision_required"] = False
    clear_pending_decision(state)

    had_san_pending = _is_san_check_pending(state.get("pending_san_check"))
    apply_system_roll_state_updates(state, result, had_san_pending=had_san_pending)

    _append_result_log_with_knowledge(
        state, result,
        current_loc=current_loc,
        char_mgr=char_mgr,
        pl_id=pl_id,
        action_id=result.get("action_id", pending.get("original_action", "")),
        target=result.get("target", pending.get("target", "")),
        roll_type=result.get("roll_type", "skill"),
    )

    result = _maybe_auto_resolve_san_check_after_action(
        state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name, result,
    )
    result = bind_push_family_transaction_ids(
        result,
        pending,
        parent_transaction_id=str(
            pending.get("parent_transaction_id")
            or pending.get("transaction_id")
            or state.get("last_processed_action_id")
            or ""
        ),
        child_transaction_id=str(result.get("transaction_id") or "") or new_action_transaction_id(),
    )
    state["last_system_result"] = result
    if result.get("stagnation_progress"):
        reset_stagnation_state_on_progress(state, scenario_mgr=scenario_mgr, state_mgr=state_mgr, char_mgr=char_mgr)
    sync_timeline_pending_phase(state)

    if result.get("new_location"):
        apply_location_change_side_effects(
            state, result, scenario_mgr=scenario_mgr, char_mgr=char_mgr,
        )
    return result


def step_push_decision(state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name):
    """PENDING_PUSH_DECISION: PL にプッシュ可否を問い、承認時は再ロール／拒否時は失敗確定。"""
    pending = state.get("pending_push_roll")
    if not pending:
        state["push_decision_required"] = False
        clear_pending_decision(state)
        sync_timeline_pending_phase(state)
        return

    if not _skill_allows_push(
        pending.get("skill_name"),
        pending.get("original_action"),
    ):
        result = resolve_push_decline(
            pl_id, char_name, pending, state["current_loc"],
            scenario_mgr, state.get("partial_system_log", ""),
        )
        state["pending_push_roll"] = None
        state["partial_system_log"] = None
        state["push_decision_required"] = False
        clear_pending_decision(state)
        apply_system_roll_state_updates(state, result)
        _append_result_log_with_knowledge(
            state, result,
            current_loc=state["current_loc"],
            char_mgr=char_mgr,
            pl_id=result.get("actor_id") or pl_id,
            action_id=result.get("action_id", pending.get("original_action", "")),
            target=result.get("target_id") or result.get("target", pending.get("target", "")),
            roll_type=result.get("roll_type", "skill"),
        )
        result = _maybe_auto_resolve_san_check_after_action(
            state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name, result,
        )
        result = bind_push_family_transaction_ids(
            result,
            pending,
            parent_transaction_id=str(
                pending.get("parent_transaction_id")
                or state.get("last_processed_action_id")
                or ""
            ),
            child_transaction_id=new_action_transaction_id(),
        )
        state["last_system_result"] = result
        if result.get("stagnation_progress"):
            reset_stagnation_state_on_progress(state, scenario_mgr=scenario_mgr, state_mgr=state_mgr, char_mgr=char_mgr)
        sync_timeline_pending_phase(state)
        if result.get("new_location"):
            apply_location_change_side_effects(
                state, result, scenario_mgr=scenario_mgr, char_mgr=char_mgr,
            )
            _maybe_inject_location_loop_warning(state, scenario_mgr)
        return result

    partial_log = state.get("partial_system_log", "")
    current_loc = state["current_loc"]
    owner_id = resolve_pending_decision_owner(state, pending, fallback_pl_id=pl_id)
    if char_mgr and owner_id:
        try:
            owner_name = char_mgr.get_pc_name(owner_id, default=char_name)
        except TypeError:
            owner_name = char_mgr.get_pc_name(owner_id) or char_name
    else:
        owner_name = char_name
    pl_id = owner_id or pl_id
    char_name = owner_name or char_name
    ic_logs, ooc_logs = format_prompt_history_logs(
        pl_id, current_loc, state["all_events_log"], char_mgr=char_mgr,
    )
    pl_prompt = generate_pl_push_prompt(
        char_name, pending, char_mgr, pl_id, ic_logs, ooc_logs,
        scenario_mgr=scenario_mgr,
        all_events_log=state.get("all_events_log"),
        game_state=state,
    )
    ai_data = call_pl_api(
        pl_prompt, json_schema=PL_PUSH_JSON_SCHEMA,
        active_pc_id=pl_id, char_mgr=char_mgr,
    )
    use_push = bool(ai_data.get("use_push", False))
    push_approach = str(ai_data.get("push_approach", "") or "").strip()
    pl_chat = ai_data.get("pl_ooc_chat", "")
    if pl_chat:
        prefix = format_pc_log_prefix(char_mgr, pl_id, role="PL")
        state["all_events_log"].append({
            "channel": "OOC", "location": "all", "secret_to": None,
            "text": f"{prefix}: {pl_chat}",
            "meta": {"pc_id": pl_id},
        })
    if use_push and push_approach:
        prefix = format_pc_log_prefix(char_mgr, pl_id, role="PL")
        state["all_events_log"].append({
            "channel": "OOC", "location": "all", "secret_to": None,
            "text": f"{prefix}: 【プッシュ方針】{push_approach}",
            "meta": {"pc_id": pl_id},
        })

    if use_push:
        had_san_pending = _is_san_check_pending(state.get("pending_san_check"))
        result = process_system_action(
            pl_id, char_name, "push_roll",
            pending.get("target", ""),
            pending.get("skill_name", ""),
            current_loc, char_mgr, dice_engine, scenario_mgr,
            state.get("pending_san_check"),
            state_mgr,
            pending,
            game_state=state,
        )
        state["pending_push_roll"] = None
        state["partial_system_log"] = None
        state["push_decision_required"] = False
        clear_pending_decision(state)
        apply_system_roll_state_updates(state, result, had_san_pending=had_san_pending)
        _append_result_log_with_knowledge(
            state, result,
            current_loc=current_loc,
            char_mgr=char_mgr,
            pl_id=pl_id,
            action_id=result.get("action_id", pending.get("original_action", "")),
            target=result.get("target", pending.get("target", "")),
            roll_type=result.get("roll_type", "skill"),
        )
        result = _maybe_auto_resolve_san_check_after_action(
            state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name, result,
        )
    else:
        result = resolve_push_decline(
            pl_id, char_name, pending, current_loc, scenario_mgr, partial_log,
        )
        state["pending_push_roll"] = None
        state["partial_system_log"] = None
        state["push_decision_required"] = False
        clear_pending_decision(state)
        apply_system_roll_state_updates(state, result)
        _append_result_log_with_knowledge(
            state, result,
            current_loc=current_loc,
            char_mgr=char_mgr,
            pl_id=pl_id,
            action_id=result.get("action_id", pending.get("original_action", "")),
            target=result.get("target", pending.get("target", "")),
            roll_type=result.get("roll_type", "skill"),
        )
        result = _maybe_auto_resolve_san_check_after_action(
            state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name, result,
        )

    parent_tid = str(
        pending.get("parent_transaction_id")
        or state.get("last_processed_action_id")
        or ""
    )
    # プッシュ結果は別 transaction_id になり得るが、停滞は親IDで1回だけ計上
    result = bind_push_family_transaction_ids(
        result,
        pending,
        parent_transaction_id=parent_tid,
        child_transaction_id=str(result.get("transaction_id") or "") or new_action_transaction_id(),
    )
    state["last_system_result"] = result
    if result.get("stagnation_progress"):
        reset_stagnation_state_on_progress(state, scenario_mgr=scenario_mgr, state_mgr=state_mgr, char_mgr=char_mgr)
    sync_timeline_pending_phase(state)
    if result.get("new_location"):
        apply_location_change_side_effects(
            state, result, scenario_mgr=scenario_mgr, char_mgr=char_mgr,
        )
    return result


def step_combat_defense(state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name):
    """PENDING_COMBAT_DEFENSE / PENDING_SHOOT_DEFENSE: 防衛選択と対抗／射撃ロールを解決する。"""
    pending = state.get("pending_combat_defense") or (
        state_mgr.get_pending_combat_defense() if state_mgr else None
    )
    if not pending:
        sync_timeline_pending_phase(state)
        return None

    is_shoot = _pending_is_shoot_defense(pending)
    current_loc = state.get("current_loc", "")
    defender_id = pending.get("defender_id")
    attacker_id = pending.get("attacker_id")
    atk_name = char_mgr.characters.get(attacker_id, {}).get("profile", {}).get("name", attacker_id)
    def_name = char_mgr.characters.get(defender_id, {}).get("profile", {}).get("name", defender_id)

    defender_char = char_mgr.characters.get(defender_id) or {}
    is_npc = bool(defender_char.get("profile", {}).get("is_npc"))
    rejected_fight_back = False

    if is_npc or defender_id != pl_id:
        attack_type = "shoot" if is_shoot else "melee"
        defense_mode = (
            state_mgr.choose_npc_defense_mode(defender_id, attack_type=attack_type)
            if state_mgr else ("accept" if is_shoot else "dodge")
        )
        if is_shoot:
            ok, defense_mode, err = validate_shoot_defense_mode(defense_mode)
            if not ok:
                defense_mode = "dodge"
                rejected_fight_back = True
            mode_label = "甘んじて受ける" if defense_mode == "accept" else "回避"
        else:
            mode_label = "応戦" if defense_mode == "fight_back" else "回避"
        state["all_events_log"].append({
            "channel": "IC",
            "location": current_loc,
            "secret_to": None,
            "text": f"システム: 【戦闘・防衛選択】{def_name} は【{mode_label}】を選択した。",
            "meta": {
                "kp_narrated": False,
                "action_id": "defend",
                "roll_type": "shoot_defense_choice" if is_shoot else "combat_defense_choice",
            },
        })
    else:
        if is_shoot:
            prompt = generate_pl_shoot_defense_prompt(
                char_name, pending, char_mgr,
                attacker_name=atk_name, defender_name=def_name,
            )
            ai_data = call_pl_api(
                prompt, json_schema=PL_SHOOT_DEFENSE_JSON_SCHEMA,
                active_pc_id=defender_id, char_mgr=char_mgr,
            )
            ok, defense_mode, err = validate_shoot_defense_mode(ai_data.get("defense_mode"))
            if not ok:
                rejected_fight_back = True
                # 応戦不可ガード: ログを出して PL に再選択を促す（保留維持）
                append_system_log_entry(
                    state["all_events_log"], current_loc, f"【射撃・防衛ガード】{err}",
                    action_id="defend",
                    target=defender_id or "",
                    roll_type="shoot_defense_rejected",
                )
                state["last_system_result"] = {
                    "status": 0,
                    "log": f"【射撃・防衛ガード】{err}",
                    "kp_instruction": "銃撃への応戦は不可です。回避か甘受を選ぶよう促してください。",
                    "san_check": {"required": False},
                    "outcome": "not_allowed",
                    "rejected_fight_back": True,
                }
                sync_timeline_pending_phase(state)
                return state["last_system_result"]
        else:
            prompt = generate_pl_combat_defense_prompt(
                char_name, pending, char_mgr,
                attacker_name=atk_name, defender_name=def_name,
            )
            ai_data = call_pl_api(
                prompt, json_schema=PL_COMBAT_DEFENSE_JSON_SCHEMA,
                active_pc_id=defender_id, char_mgr=char_mgr,
            )
            defense_mode = _normalize_defense_mode(ai_data.get("defense_mode"))
        pl_chat = ai_data.get("pl_ooc_chat", "")
        if pl_chat:
            state["all_events_log"].append({
                "channel": "OOC", "location": "all", "secret_to": None,
                "text": f"{char_name}(PL): {pl_chat}",
            })
        dialogue = str(ai_data.get("dialogue", "") or "").strip()
        if dialogue:
            state["all_events_log"].append({
                "channel": "IC",
                "location": current_loc,
                "secret_to": None,
                "text": f"{char_name}(PC): {dialogue}",
                "meta": {
                    "action_id": "defend",
                    "needs_system": False,
                    "system_processed": True,
                },
            })

    if is_shoot:
        resolved = resolve_shoot_combat_exchange(
            pending, defense_mode,
            char_mgr=char_mgr, dice_engine=dice_engine, state_mgr=state_mgr,
            scenario_mgr=scenario_mgr, game_state=state,
        )
        if resolved.get("rejected_fight_back") or resolved.get("outcome") == "not_allowed":
            append_system_log_entry(
                state["all_events_log"], current_loc, resolved.get("log", ""),
                action_id="defend",
                target=defender_id or "",
                roll_type="shoot_defense_rejected",
            )
            state["last_system_result"] = {
                "status": 0,
                "log": resolved.get("log", ""),
                "kp_instruction": "銃撃への応戦は不可です。回避か甘受を選ぶよう促してください。",
                "san_check": {"required": False},
                "outcome": "not_allowed",
                "rejected_fight_back": True,
            }
            sync_timeline_pending_phase(state)
            return state["last_system_result"]
        action_id = "shoot"
        roll_type = "shoot_opposed"
        default_kp = "射撃の結果を描写してください。"
    else:
        resolved = resolve_melee_combat_exchange(
            pending, defense_mode,
            char_mgr=char_mgr, dice_engine=dice_engine, state_mgr=state_mgr,
            scenario_mgr=scenario_mgr, game_state=state,
        )
        action_id = "attack"
        roll_type = "combat_opposed"
        default_kp = "戦闘の攻防結果を描写してください。"

    state["pending_combat_defense"] = None
    if state_mgr:
        state_mgr.clear_pending_combat_defense()
    state["partial_system_log"] = None
    clear_pending_decision(state)
    sync_timeline_pending_phase(state)

    result = {
        "status": 0,
        "log": resolved.get("log", ""),
        "kp_instruction": resolved.get("kp_instruction", default_kp),
        "san_check": {"required": False},
        "outcome": resolved.get("outcome"),
        "defense_mode": resolved.get("defense_mode"),
        "roll_type": roll_type,
        "action_id": action_id,
        "target": pending.get("defender_id"),
        "damage_results": resolved.get("damage_results"),
        "impale": resolved.get("impale"),
        "point_blank": resolved.get("point_blank"),
        "rejected_fight_back": rejected_fight_back,
        "adjudication_id": pending.get("adjudication_id") or _new_adjudication_id(),
    }
    append_system_log_entry(
        state["all_events_log"], current_loc, result["log"],
        action_id=action_id,
        target=pending.get("defender_id", ""),
        roll_type=roll_type,
        adjudication=result,
    )
    prior_round = int(pending.get("round") or 0)
    damage_value = None
    damage_rows = resolved.get("damage_results")
    if isinstance(damage_rows, list):
        damage_value = sum(
            int((row or {}).get("damage") or (row or {}).get("amount") or 0)
            for row in damage_rows if isinstance(row, dict)
        )
    elif isinstance(damage_rows, dict):
        damage_value = int(damage_rows.get("damage") or damage_rows.get("amount") or 0)
    origin = AUTONOMOUS
    combat_tid = str(pending.get("transaction_id") or "")
    for row in reversed(state.get("unified_event_log") or []):
        if row.get("event_type") != "COMBAT_ACTION_SELECTED":
            continue
        if combat_tid and str(row.get("transaction_id") or "") != combat_tid:
            continue
        if row.get("actor") == attacker_id:
            origin = row.get("action_origin") or AUTONOMOUS
            break
    append_combat_event(
        state, "COMBAT_ACTION_RESOLVED", state_mgr=state_mgr,
        actor=attacker_id,
        actor_state={
            "HP": char_mgr.get_stat_current(attacker_id, "HP"),
            "SAN": char_mgr.get_stat_current(attacker_id, "SAN"),
        },
        target=defender_id,
        combat_goal=getattr(state_mgr, "combat_goal", ""),
        action_category="ATTACK",
        selected_action=action_id,
        action_origin=origin,
        legality="LEGAL",
        skill=pending.get("attacker_skill") or "",
        adjudication_id=result["adjudication_id"],
        resolution_mode="ROLL",
        base_target=pending.get("attacker_base_skill_value", pending.get("attacker_skill_value")),
        target_value=pending.get("attacker_skill_value"),
        final_target=pending.get("attacker_skill_value"),
        roll=(resolved.get("opposed") or {}).get("attacker_roll"),
        defense_type=resolved.get("defense_mode"),
        defense_target_value=(
            char_mgr.get_skill(defender_id, "回避")
            if resolved.get("defense_mode") == "dodge" else None
        ),
        defense_roll=(resolved.get("opposed") or {}).get("defender_roll"),
        raw_result=_success_level_name((resolved.get("opposed") or {}).get("attacker_level")),
        final_result=_success_level_name((resolved.get("opposed") or {}).get("attacker_level")),
        roll_result=_success_level_name((resolved.get("opposed") or {}).get("attacker_level")),
        effect_result=str(resolved.get("outcome") or "").upper(),
        result=resolved.get("outcome"),
        damage=damage_value,
        damage_formula=str((pending.get("weapon") or {}).get("damage") or ""),
        damage_roll=((damage_rows[0] or {}).get("damage_detail") if isinstance(damage_rows, list) and damage_rows else None),
        actual_damage=damage_value,
        HP_before=pending.get("defender_hp_before"),
        HP_after=char_mgr.get_stat_current(defender_id, "HP"),
        SAN_before=pending.get("defender_san_before"),
        SAN_after=char_mgr.get_stat_current(defender_id, "SAN"),
        position_before=getattr(state_mgr, "combat_location_id", current_loc),
        position_after=getattr(state_mgr, "combat_location_id", current_loc),
        effect=resolved.get("log") or "",
        combat_progress_delta=1 if damage_value or resolved.get("outcome") == "dodged" else 0,
        combat_end_condition=getattr(state_mgr, "combat_end_reason", "") if not state_mgr.in_combat else "",
        transaction_id=combat_tid,
    )
    if state_mgr.is_combat_participant_incapacitated(defender_id):
        append_combat_event(
            state, "COMBATANT_INCAPACITATED", state_mgr=state_mgr,
            actor=defender_id, target=attacker_id,
            adjudication_id=result["adjudication_id"],
            combat_goal=getattr(state_mgr, "combat_goal", ""),
            action_category="ATTACK", selected_action=action_id,
            action_origin=origin,
            HP_after=char_mgr.get_stat_current(defender_id, "HP"),
            effect="combatant_incapacitated",
        )
    if state_mgr.in_combat and int(state_mgr.round_number or 0) > prior_round:
        append_combat_event(
            state, "COMBAT_ROUND_STARTED", state_mgr=state_mgr,
            actor=state_mgr.get_current_actor() or "",
            combat_goal=getattr(state_mgr, "combat_goal", ""),
            effect={"initiative": state_mgr.get_combat_turn_queue()},
        )
    if not state_mgr.in_combat:
        append_combat_event(
            state, "COMBAT_ENDING", state_mgr=state_mgr,
            cause_adjudication_id=result["adjudication_id"],
            combat_end_condition=getattr(state_mgr, "combat_end_reason", "resolved"),
        )
        append_combat_event(
            state, "COMBAT_ENDED", state_mgr=state_mgr,
            cause_adjudication_id=result["adjudication_id"],
            combat_end_condition=getattr(state_mgr, "combat_end_reason", "resolved"),
            position_before=current_loc, position_after=current_loc,
            effect="normal progression may resume",
        )
    state["last_system_result"] = result
    if result.get("stagnation_progress"):
        reset_stagnation_state_on_progress(state, scenario_mgr=scenario_mgr, state_mgr=state_mgr, char_mgr=char_mgr)
    return result


def step_combat_npc_act(state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name):
    """戦闘中の NPC 手番: PL への攻撃を自動宣言し防衛保留へ進む。"""
    current_loc = state.get("current_loc", "")
    tick = tick_body_activation(state, round_number=int(getattr(state_mgr, "round_number", 0) or 0))
    if tick and tick.get("event_type") == "CORBITT_BODY_ACTIVATION_EXPIRED":
        state.setdefault("unified_event_log", []).append(tick)
    result = queue_npc_combat_attack(
        state, state_mgr, char_mgr, pl_id, current_loc, scenario_mgr=scenario_mgr,
    )
    if not result:
        return None
    if result.get("ended"):
        append_combat_event(
            state, "COMBAT_ENDING", state_mgr=state_mgr,
            actor="", combat_end_condition=getattr(state_mgr, "combat_end_reason", "resolved"),
            position_before=current_loc, position_after=current_loc,
        )
        append_combat_event(
            state, "COMBAT_ENDED", state_mgr=state_mgr,
            combat_end_condition=getattr(state_mgr, "combat_end_reason", "resolved"),
            position_before=current_loc, position_after=current_loc,
            effect="normal progression may resume",
        )
        append_system_log_entry(
            state["all_events_log"], current_loc, result.get("log", ""),
            action_id="combat_end", roll_type="combat",
        )
        state["last_system_result"] = {
            "log": result.get("log", ""),
            "kp_instruction": "戦闘終了を描写してください。",
            "san_check": {"required": False},
        }
        return result
    if result.get("ok"):
        pending = result.get("pending_combat_defense", {})
        append_combat_event(
            state, "COMBAT_ACTION_SELECTED", state_mgr=state_mgr,
            actor=pending.get("attacker_id") or "",
            actor_state={
                "HP": char_mgr.get_stat_current(pending.get("attacker_id"), "HP"),
                "SAN": char_mgr.get_stat_current(pending.get("attacker_id"), "SAN"),
            },
            target=pending.get("defender_id") or "",
            combat_goal=getattr(state_mgr, "combat_goal", ""),
            action_category="ATTACK", selected_action="attack",
            action_origin=AUTONOMOUS, legality="LEGAL",
            skill=pending.get("attacker_skill") or "",
            HP_before=pending.get("attacker_hp_before"),
            SAN_before=pending.get("attacker_san_before"),
            position_before=current_loc, position_after=current_loc,
            transaction_id=pending.get("transaction_id") or "",
        )
        append_system_log_entry(
            state["all_events_log"], current_loc, result.get("log", ""),
            action_id="attack",
            target=result.get("pending_combat_defense", {}).get("defender_id", ""),
            roll_type="combat_attack_declare",
        )
        state["last_system_result"] = {
            "log": result.get("log", ""),
            "kp_instruction": "敵の攻撃宣言を描写し、防衛選択を待ってください。",
            "san_check": {"required": False},
            "combat_defense_required": True,
            "pending_combat_defense": result.get("pending_combat_defense"),
        }
    else:
        append_system_log_entry(
            state["all_events_log"], current_loc, result.get("log", ""),
            action_id="attack", roll_type="blocked",
        )
        if state_mgr:
            state_mgr.next_turn()
    return result


def append_human_player_message(
    all_events_log, char_name, text, channel="OOC", current_loc="all",
    pc_id=None, char_mgr=None,
):
    """人間プレイヤーの IC/OOC 割り込み発言をタイムラインへ追記する。"""
    text = str(text or "").strip()
    if not text:
        return None
    if channel == "IC":
        prefix = format_pc_log_prefix(char_mgr, pc_id, role="PC") if pc_id and char_mgr else f"{char_name}(PC)"
        entry = {
            "channel": "IC",
            "location": current_loc,
            "secret_to": None,
            "text": f"{prefix}: {text}",
            "meta": {
                "pc_id": pc_id,
                "action_id": "wait",
                "target": "",
                "skill": "",
                "needs_system": False,
                "system_processed": True,
                "human": True,
                "action_origin": HUMAN_GUIDED,
            },
        }
    else:
        prefix = format_pc_log_prefix(char_mgr, pc_id, role="PL") if pc_id and char_mgr else f"{char_name}(PL)"
        entry = {
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": f"{prefix}: {text}",
            "meta": {"human": True, "pc_id": pc_id, "action_origin": HUMAN_GUIDED},
        }
    all_events_log.append(entry)
    return entry


SYSTEM_TIMELINE_STEPS = frozenset({
    "system_process", "system_resolve_san", "luck_decision", "push_decision",
    "combat_defense", "combat_npc_act",
    "kp_narrate", "room_entry_san_arm", "pl_discussion",
})


def execute_timeline_step(step, state, managers, guard=None):
    """タイムライン上の1ステップを実行し、(pause_reason, actor) を返す。"""
    char_mgr, dice_engine, state_mgr, scenario_mgr = managers
    ensure_multi_pl_state(state, char_mgr)
    pl_id = state["pl_id"]
    char_name = state["char_name"]

    if step == "game_clear":
        return "game_clear", None
    if step == "luck_decision":
        step_luck_decision(state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name)
        return None, "SYSTEM"
    if step == "push_decision":
        step_push_decision(state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name)
        return None, "SYSTEM"
    if step == "combat_defense":
        step_combat_defense(state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name)
        return None, "SYSTEM"
    if step == "combat_npc_act":
        step_combat_npc_act(state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name)
        return None, "SYSTEM"
    if step == "system_resolve_san":
        step_system_resolve_san(state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name)
        return None, "SYSTEM"
    if step == "system_process":
        step_system_process(state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name)
        return None, "SYSTEM"
    if step == "kp_narrate":
        pending = find_last_unnarrated_system_entry(state.get("all_events_log", []))
        narrated = step_kp_narrate(state, scenario_mgr, char_mgr=char_mgr)
        # 描写成功時のみ手番を進める（失敗時は未描写のまま再試行）
        if narrated and pending and not (state_mgr and state_mgr.in_combat):
            advance_exploration_turn(state, char_mgr, state_mgr)
        return None, "KP"
    if step == "kp_opening":
        step_kp_start(state, scenario_mgr)
        return None, "KP"
    if step == "room_entry_san_arm":
        step_room_entry_san_arm(state, scenario_mgr)
        return None, "SYSTEM"
    if step == "pl_discussion":
        step_pl_discussion(state, char_mgr, scenario_mgr, state_mgr=state_mgr)
        return None, f"PL:{state.get('pl_id')}"
    if step == "free_chat":
        pc_action, actor = step_free_chat_exchange(
            state, char_mgr, scenario_mgr, pl_id, char_name,
            guard=guard, state_mgr=state_mgr,
        )
        if isinstance(pc_action, dict) and pc_action.get("_llm_failure"):
            category = str(
                (pc_action.get("_llm_failure") or {}).get("category")
                or LLM_PAUSE_CONNECTION
            )
            return category, None
        return None, actor
    if step == "pl_speak":
        before_len = len(state.get("all_events_log", []))
        pc_action = step_pl_turn(
            state, char_mgr, scenario_mgr, pl_id, char_name, state_mgr=state_mgr,
        )
        if isinstance(pc_action, dict) and pc_action.get("_llm_failure"):
            category = str(
                (pc_action.get("_llm_failure") or {}).get("category")
                or LLM_PAUSE_CONNECTION
            )
            return category, None
        if guard:
            guard.record_pl_action(
                pc_action, state.get("pending_san_check"),
                scenario_mgr=scenario_mgr,
                current_loc=state.get("current_loc"),
                char_mgr=char_mgr,
            )
        if append_pl_turn_fallback_if_silent(state, before_len):
            return None, "SYSTEM"
        return None, f"PL:{state.get('pl_id')}"
    return None, None


def run_timeline_chain(state, managers, guard=None, max_chain=MAX_TIMELINE_CHAIN, ui_callback=None):
    """システム割り込みを連鎖実行し、チャット1往復分で止まる。"""
    actors = []
    char_mgr = managers[0]
    for _ in range(max_chain):
        ensure_multi_pl_state(state, char_mgr)
        step = determine_timeline_next_step(
            state, state["char_name"], managers[3],
            state_mgr=managers[2], char_mgr=char_mgr,
        )
        if step == "game_clear":
            return "game_clear", actors
        pause_reason, actor = execute_timeline_step(step, state, managers, guard=guard)
        evaluate_and_apply_stagnation_intervention(state, managers, after_step=step)
        # 各ステップ直後に UI へ反映（LLM 待ちのあいだ発言が止まって見えるのを防ぐ）
        if ui_callback:
            ui_callback(state)
        if pause_reason:
            return pause_reason, actors
        if actor:
            actors.append(actor)
            if guard:
                guard.record(actor)
        if step not in SYSTEM_TIMELINE_STEPS:
            if find_any_pending_pl_action(state, char_mgr):
                continue
            break
    return None, actors


def run_timeline_loop(
    state,
    managers,
    ui_callback=None,
    autosave_callback=None,
    max_iterations=MAX_AUTONOMOUS_ITERATIONS,
    should_stop_callback=None,
    max_chain_per_tick=MAX_TIMELINE_CHAIN,
):
    """
    タイムライン末尾駆動の自律ループ。
    max_iterations=1 で1サイクル（Streamlit 段階 rerun 用）。
    """
    char_mgr, dice_engine, state_mgr, scenario_mgr = managers
    pl_id = state["pl_id"]
    char_name = state["char_name"]
    guard = AutonomousLoopGuard.from_state(state.get("autonomous_guard"))
    pause_reason = None

    def finish_cycle():
        state["autonomous_step_count"] = state.get("autonomous_step_count", 0) + 1
        # 場所・進行フラグが進んでいれば上限カウントをリセット（無進行ループだけ安全停止）
        refresh_autonomous_step_budget_on_progress(state, scenario_mgr)
        state["autonomous_guard"] = guard.to_state()
        if ui_callback:
            ui_callback(state)
        if autosave_callback:
            autosave_callback(state)
        if should_stop_callback and should_stop_callback():
            append_user_stop_message(state)
            if autosave_callback:
                autosave_callback(state)
            return "user_stop"
        return None

    # 巡航開始時の指紋を初期化（最初の進行比較用）
    if state.get("autonomous_progress_fp") is None:
        state["autonomous_progress_fp"] = build_autonomous_progress_fingerprint(
            state, scenario_mgr,
        )

    for _ in range(max_iterations):
        if is_game_cleared(scenario_mgr):
            pause_reason = "game_clear"
            break

        chain_pause, actors = run_timeline_chain(
            state, managers, guard=guard, max_chain=max_chain_per_tick,
            ui_callback=ui_callback,
        )
        if chain_pause:
            pause_reason = chain_pause
            break

        if guard.should_break_same_speaker():
            if _should_defer_stagnation_interrupt_for_progress(state, scenario_mgr):
                # 有効コマンド消化を同一PL制限より優先
                guard.consecutive_count = 0
                state["autonomous_guard"] = guard.to_state()
            else:
                # 旧仕様はここでセッション停止＋膠着カウンタを閾値へ上書きしていた。
                # 6ターン緩和と矛盾するため、手番交代のみして継続する。
                _handle_same_speaker_soft_yield(state, managers, guard)
                if ui_callback:
                    ui_callback(state)
                if autosave_callback:
                    autosave_callback(state)

        if guard.should_break_stagnation() or guard.should_break_system_stagnation(scenario_mgr):
            if _should_defer_stagnation_interrupt_for_progress(state, scenario_mgr):
                guard.chat_rounds_without_action = 0
                guard.consecutive_count = 0
                state["autonomous_guard"] = guard.to_state()
                if _clipping_files_search_pending(
                    scenario_mgr, state.get("current_loc") or "",
                ):
                    state["stagnation_pl_hint"] = ARTIE_ACCESS_GRANTED_SEARCH_HINT
                    forced = _maybe_force_post_access_search(
                        state, managers, pl_id=pl_id, char_name=char_name,
                    )
                    if forced:
                        state["autonomous_guard"] = guard.to_state()
                        if ui_callback:
                            ui_callback(state)
                        if autosave_callback:
                            autosave_callback(state)
                        continue
            else:
                level = resolve_session_intervention_level(state, scenario_mgr)
                # 介入ポリシーが有効な場合はタイムライン側で処理済み。NONE のみ一時停止する。
                if level <= InterventionLevel.NONE:
                    inject_stagnation_interrupt(state, scenario_mgr, char_name, state_mgr=state_mgr)
                    pause_reason = "stagnation"
                    state["autonomous_guard"] = guard.to_state()
                    if ui_callback:
                        ui_callback(state)
                    if autosave_callback:
                        autosave_callback(state)
                    break
                # LIGHT以上: OOCループを物理遮断し、強制 IC 行動フェーズへ移行して継続
                ensure_force_ic_action_phase(state, state_mgr=state_mgr, guard=guard)
                if scenario_mgr.is_stagnation_pause_level():
                    evaluate_and_apply_stagnation_intervention(
                        state, managers, after_step="system_process",
                    )
                # ヒント提示済み（なければ生成）+ chat 上限 → 強制移動ブレイクアウト
                if get_chat_rounds_without_action(state, guard=guard) >= FORCE_IC_ACTION_CHAT_ROUNDS:
                    if not str(state.get("stagnation_pl_hint") or "").strip():
                        _maybe_set_context_stagnation_hint(state, scenario_mgr, state_mgr)
                        if not str(state.get("stagnation_pl_hint") or "").strip():
                            state["stagnation_pl_hint"] = build_context_stagnation_hint(
                                scenario_mgr,
                                state.get("current_loc") or "",
                                fallback=STAGNATION_STANDARD_PL_HINT,
                            )
                    forced = apply_forced_progress_breakout(
                        state, managers, pl_id=pl_id, char_name=char_name,
                    )
                    if forced:
                        state["autonomous_guard"] = guard.to_state()
                        if ui_callback:
                            ui_callback(state)
                        if autosave_callback:
                            autosave_callback(state)

        stop_hit = finish_cycle()
        if stop_hit:
            pause_reason = stop_hit
            break

        if state.get("autonomous_step_count", 0) >= MAX_AUTONOMOUS_ITERATIONS:
            pause_reason = "max_iterations"
            break

    else:
        # バッチ実行（max_iterations>1）で for を完走した場合のみ。
        # Streamlit の 1ティック実行（max_iterations=1）では、まだ上限未満なら継続する。
        if max_iterations > 1 and state.get("autonomous_step_count", 0) >= MAX_AUTONOMOUS_ITERATIONS:
            pause_reason = "max_iterations"

    state["autonomous_guard"] = guard.to_state()
    if pause_reason:
        try:
            from LogEvaluator import evaluate_session_rp_logs
            evaluate_session_rp_logs(
                state,
                char_mgr,
                pl_id=pl_id,
                char_name=char_name,
                scenario_file=state.get("scenario_file"),
                scenario_mgr=scenario_mgr,
            )
        except Exception as exc:
            print(f"[LogEvaluator] セッション終了時評価をスキップ: {exc}")
        finalize_autonomous_pause(state, pause_reason)
    else:
        begin_autonomous_runtime(state)
    return pause_reason


# 後方互換エイリアス
run_autonomous_loop = run_timeline_loop


def extract_game_state(session_state):
    """Streamlit session_state から自律ループ用の状態辞書を抽出。"""
    return {
        "all_events_log": session_state.all_events_log,
        "last_pl_action": session_state.get("last_pl_action"),
        "last_system_result": session_state.get("last_system_result"),
        "pending_san_check": session_state.get("pending_san_check"),
        "pending_push_roll": session_state.get("pending_push_roll"),
        "pending_luck_burn": session_state.get("pending_luck_burn"),
        "pending_combat_defense": session_state.get("pending_combat_defense"),
        "pending_decision": session_state.get("pending_decision"),
        "public_knowledge_ids": list(session_state.get("public_knowledge_ids") or []),
        "investigation_flow": dict(session_state.get("investigation_flow") or {}),
        "unified_event_log": list(session_state.get("unified_event_log") or []),
        "director_v2": dict(session_state.get("director_v2") or {}),
        "partial_system_log": session_state.get("partial_system_log"),
        "push_decision_required": session_state.get("push_decision_required", False),
        "timeline_pending": session_state.get("timeline_pending"),
        "intervention_level": session_state.get("intervention_level", "standard"),
        "kp_style": session_state.get("kp_style", "collaborative"),
        "stagnation_kp_nudge": session_state.get("stagnation_kp_nudge"),
        "stagnation_pl_hint": session_state.get("stagnation_pl_hint"),
        "stagnation_streak": session_state.get("stagnation_streak", 0),
        "force_ic_action": session_state.get("force_ic_action", False),
        "pl_id": session_state.pl_id,
        "char_name": session_state.char_name,
        "active_pcs": list(session_state.get("active_pcs") or []),
        "active_pc_id": session_state.get("active_pc_id") or session_state.pl_id,
        "pl_discussion_mode": session_state.get("pl_discussion_mode", False),
        "pl_discussion_rounds": session_state.get("pl_discussion_rounds", 0),
        "current_loc": session_state.current_loc,
        "scenario_file": session_state.get("scenario_file", DEFAULT_SCENARIO_FILE),
        "autonomous_paused": session_state.get("autonomous_paused", False),
        "autonomous_pause_reason": session_state.get("autonomous_pause_reason"),
        "autonomous_pause_class": session_state.get("autonomous_pause_class"),
        "autonomous_user_resumed": session_state.get("autonomous_user_resumed", False),
        "runtime_load_normalized": session_state.get("runtime_load_normalized", False),
        "autonomous_guard": session_state.get("autonomous_guard"),
        "autonomous_step_count": session_state.get("autonomous_step_count", 0),
        "autonomous_progress_fp": session_state.get("autonomous_progress_fp"),
        "is_running": session_state.get("is_running", False),
        "stop_requested": session_state.get("stop_requested", False),
        "rp_eval_unit_ids": session_state.get("rp_eval_unit_ids", []),
        "rp_eval_last_summary": session_state.get("rp_eval_last_summary"),
        "rp_session_id": session_state.get("rp_session_id"),
        "rp_library_pending": session_state.get("rp_library_pending", []),
        "pending_action_id": session_state.get("pending_action_id"),
        "last_processed_action_id": session_state.get("last_processed_action_id"),
        "actor_id": session_state.get("actor_id") or session_state.get("active_pc_id") or session_state.pl_id,
        "decision_owner_id": session_state.get("decision_owner_id") or session_state.get("actor_id") or session_state.pl_id,
    }


def apply_game_state(session_state, state, scenario_mgr=None):
    """自律ループ後の状態を Streamlit session_state へ書き戻す。"""
    state = normalize_loaded_runtime_state(
        dict(state),
        enforce_half_turn_pause=False,
    )
    if scenario_mgr:
        normalize_game_action_targets(
            state, scenario_mgr, char_mgr=session_state.get("char_mgr"),
        )
    sync_room_entry_san_on_load(state, scenario_mgr)
    session_state.all_events_log = state["all_events_log"]
    session_state.last_pl_action = state.get("last_pl_action")
    session_state.last_system_result = state.get("last_system_result")
    session_state.pending_san_check = state.get("pending_san_check")
    session_state.pending_push_roll = state.get("pending_push_roll")
    session_state.pending_luck_burn = state.get("pending_luck_burn")
    session_state.pending_combat_defense = state.get("pending_combat_defense")
    session_state.pending_decision = state.get("pending_decision")
    session_state.public_knowledge_ids = list(state.get("public_knowledge_ids") or [])
    session_state.investigation_flow = dict(state.get("investigation_flow") or {})
    session_state.unified_event_log = list(state.get("unified_event_log") or [])
    session_state.director_v2 = dict(state.get("director_v2") or {})
    session_state.partial_system_log = state.get("partial_system_log")
    session_state.push_decision_required = state.get("push_decision_required", False)
    session_state.timeline_pending = state.get("timeline_pending")
    session_state.intervention_level = state.get("intervention_level", "standard")
    session_state.kp_style = state.get("kp_style", "collaborative")
    session_state.stagnation_kp_nudge = state.get("stagnation_kp_nudge")
    session_state.stagnation_pl_hint = state.get("stagnation_pl_hint")
    session_state.stagnation_streak = state.get("stagnation_streak", 0)
    session_state.force_ic_action = state.get("force_ic_action", False)
    session_state.pl_id = state["pl_id"]
    session_state.char_name = state["char_name"]
    session_state.active_pcs = list(state.get("active_pcs") or [])
    session_state.active_pc_id = state.get("active_pc_id") or state["pl_id"]
    session_state.pl_discussion_mode = state.get("pl_discussion_mode", False)
    session_state.pl_discussion_rounds = state.get("pl_discussion_rounds", 0)
    session_state.current_loc = state["current_loc"]
    session_state.autonomous_paused = state.get("autonomous_paused", False)
    session_state.autonomous_pause_reason = state.get("autonomous_pause_reason")
    session_state.autonomous_pause_class = state.get("autonomous_pause_class")
    session_state.autonomous_user_resumed = bool(state.get("autonomous_user_resumed"))
    session_state.runtime_load_normalized = bool(state.get("runtime_load_normalized"))
    session_state.autonomous_guard = state.get("autonomous_guard")
    session_state.autonomous_step_count = state.get("autonomous_step_count", 0)
    session_state.autonomous_progress_fp = state.get("autonomous_progress_fp")
    session_state.is_running = state.get("is_running", False)
    session_state.stop_requested = state.get("stop_requested", False)
    session_state.rp_eval_unit_ids = state.get("rp_eval_unit_ids", [])
    session_state.rp_eval_last_summary = state.get("rp_eval_last_summary")
    session_state.rp_session_id = state.get("rp_session_id")
    session_state.rp_library_pending = state.get("rp_library_pending", [])
    session_state.pending_action_id = state.get("pending_action_id")
    session_state.last_processed_action_id = state.get("last_processed_action_id")
    session_state.actor_id = state.get("actor_id") or state.get("active_pc_id") or state.get("pl_id")
    session_state.decision_owner_id = (
        state.get("decision_owner_id") or state.get("actor_id") or state.get("pl_id")
    )
