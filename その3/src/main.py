import atexit
import json
import os
import random
import re
import sys
import time

import streamlit as st
from openai import OpenAI

from CharacterManager import CharacterManager
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
    is_casual_talk,
    is_social_action,
    npc_is_available,
    normalize_occupation_rp_judgment,
    default_occupation_rp_judgment,
    resolve_social_skill_name,
)
from ActionValidator import (
    MOVE_INTENT_MISMATCH_ERROR,
    HUMAN_INSPECT_REWRITE_LOG,
    PL_RETRY_PROMPT_PREFIX,
    KP_SUCCESS_FACT_GUARD,
    KP_LOCKED_ROUTE_GUARD,
    FORCE_IC_ACTION_CHAT_ROUNDS,
    FORCE_IC_ACTION_STAGNATION_STREAK,
    OOC_LOOP_FORCE_ACTION_WARNING,
    FORCE_IC_WAIT_REJECT_ERROR,
    FORCE_IC_STALE_TALK_REJECT_ERROR,
    STALE_KNOTT_TALK_REJECT_ERROR,
    FORCE_PROGRESS_BREAKOUT_LOG,
    STAGNATION_STANDARD_PL_HINT,
    validate_move_intent,
    validate_force_ic_action,
    validate_completed_knott_talk,
    is_stale_nonprogress_talk,
    build_forced_progress_move_action,
    build_forced_progress_action,
    build_context_stagnation_hint,
    rewrite_human_investigation_to_talk,
    resolve_social_npc_id,
)
from SaveLoadManager import SaveLoadManager
from ScenarioManager import (
    MOVE_DENY_SYSTEM_LOG,
    STAGNATION_PAUSE_THRESHOLD,
    ScenarioManager,
)

# ==========================================
# 1. ローカル LLM（OpenAI 互換 API）の設定
# ==========================================
_client = None
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

DEFAULT_LLM_BASE_URL = "http://localhost:11434/v1"
DEFAULT_LLM_API_KEY = "ollama"
DEFAULT_PL_MODEL = "qwen2.5:14b"
DEFAULT_KP_MODEL = "qwen2.5:14b"
DEFAULT_LLM_TIMEOUT = 120.0


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


def get_llm_config():
    """ローカル LLM 接続設定を返す。"""
    kp_model = _get_config_value("LLM_KP_MODEL", "LLM_KP_MODEL", DEFAULT_KP_MODEL)
    return {
        "base_url": _get_config_value("LLM_BASE_URL", "LLM_BASE_URL", DEFAULT_LLM_BASE_URL),
        "api_key": _get_config_value("LLM_API_KEY", "LLM_API_KEY", DEFAULT_LLM_API_KEY),
        "pl_model": _get_config_value("LLM_PL_MODEL", "LLM_PL_MODEL", DEFAULT_PL_MODEL),
        "kp_model": kp_model,
        "judge_model": _get_config_value("LLM_JUDGE_MODEL", "LLM_JUDGE_MODEL", kp_model),
        "timeout": float(_get_config_value("LLM_TIMEOUT", "LLM_TIMEOUT", str(DEFAULT_LLM_TIMEOUT))),
    }


def close_llm_client():
    """OpenAI 互換クライアントの HTTP 接続を明示的に閉じる。"""
    global _client
    if _client is None:
        return
    try:
        _client.close()
    except Exception:
        pass
    _client = None


def get_client():
    """OpenAI 互換クライアントをシングルトンで返す（Ollama / vLLM / LM Studio 等）。"""
    global _client
    if _client is None:
        cfg = get_llm_config()
        _client = OpenAI(
            base_url=cfg["base_url"],
            api_key=cfg["api_key"],
            timeout=cfg["timeout"],
        )
    return _client


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
    )
    return any(keyword in err for keyword in retry_keywords)


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
      "skill": "目星"
    }
  }
}

※ push / break / move / climb 時は skill を必ず空文字 "" にすること。目星は search 時のみ。"""

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
    skill = resolve_social_skill_name(action_id, skill_name) if not casual else "（雑談・判定なし）"
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
        )
        raw = json.loads(_extract_json_object(response_text))
        return normalize_occupation_rp_judgment(raw)
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


def get_timeline_pending_phase(state):
    """
    保留中システム処理の優先フェーズを返す。
    優先順位: SAN → 近接防衛 / 射撃防衛 → 幸運消費 → プッシュ決定 → PL相談
    """
    if _is_san_check_pending((state or {}).get("pending_san_check")):
        return PENDING_SAN_CHECK
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
    """システム処理結果から pending_san_check / pending_push_roll を同期する。"""
    san_check = result.get("san_check", {})
    if san_check.get("required"):
        state["pending_san_check"] = san_check
        state["pending_push_roll"] = None
        state["pending_luck_burn"] = None
        state["pending_combat_defense"] = None
        state["push_decision_required"] = False
        sync_timeline_pending_phase(state)
        return

    state["pending_san_check"] = None
    if had_san_pending:
        state["pending_push_roll"] = None
        state["push_decision_required"] = False
    elif result.get("push_decision_required") and result.get("pending_push_roll"):
        state["pending_push_roll"] = result["pending_push_roll"]
        state["push_decision_required"] = True
    elif "pending_push_roll" in result:
        state["pending_push_roll"] = result["pending_push_roll"]
        state["push_decision_required"] = bool(
            result.get("pending_push_roll") and result.get("push_decision_required")
        )
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
        target="",
        roll_type=san_result.get("roll_type", "san_check"),
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

    if is_success:
        return pending_san_check.get("success_loss", "0")
    return pending_san_check.get("fail_loss", "1d3")


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

    hint = "担当者と交渉して許可を得る"
    if permission_npc_id:
        hint = f"`{permission_npc_id}` と交渉して許可を得る"
    return {
        "blocked": True,
        "log": (
            "【進行ブロック】この対象にはまだアクセスできない。"
            f"{hint}必要がある。"
        ),
        "kp_instruction": (
            "アクセス許可条件が未達。許可交渉（説得・信用・言いくるめ等）か"
            "別ルートへの移動を促せ。"
        ),
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
    返り値: (system_log_append, kp_instruction_append)
    """
    if not scenario_mgr:
        return "", ""
    success_level = int((social_result or {}).get("success_level") or 0)
    rel = str((social_result or {}).get("relationship") or "")
    rules = _social_progress_rules_for(
        scenario_mgr, current_loc=current_loc, npc_id=npc_id,
    )
    sys_parts = []
    kp_parts = []
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
            continue

        set_flags = rule.get("set_flags") or {}
        for k, v in set_flags.items():
            scenario_mgr.flags[str(k)] = bool(v)
        clear_flags = [str(x) for x in (rule.get("clear_flags") or []) if x]
        for f in clear_flags:
            scenario_mgr.flags[f] = False

        sys_log = str(rule.get("system_log") or "").strip()
        kp_inst = str(rule.get("kp_instruction") or "").strip()
        if sys_log:
            sys_parts.append(sys_log)
        if kp_inst:
            kp_parts.append(kp_inst)
    return ("\n".join(sys_parts), "\n".join(kp_parts))


def _list_uninvestigated_object_hints(scenario_mgr, loc_id=None, limit=4, exclude=None):
    """未調査オブジェクトを『名前 (`id`)』形式で列挙する。"""
    if not scenario_mgr:
        return []
    loc_id = loc_id or scenario_mgr.location
    exclude = {str(x) for x in (exclude or set())}
    hints = []
    for obj_id, obj in _location_objects(scenario_mgr, loc_id).items():
        if obj_id in exclude:
            continue
        if scenario_mgr._is_target_investigated(obj_id) and not scenario_mgr._is_research_reopened(obj_id):
            continue
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


def _build_pl_phase_summary(scenario_mgr, current_loc):
    """PL向け: 現在地と調査進捗の一行要約（シナリオデータ駆動）。"""
    if not scenario_mgr:
        return ""
    loc_name = scenario_mgr.get_location_info(current_loc).get("name", current_loc)
    parts = [f"現在地: {loc_name}（{current_loc}）"]

    objects = _location_objects(scenario_mgr, current_loc)
    investigated = []
    pending = []
    for obj_id, obj in objects.items():
        name = obj.get("name", obj_id)
        if scenario_mgr._is_target_investigated(obj_id) and not scenario_mgr._is_research_reopened(obj_id):
            investigated.append(name)
        else:
            pending.append(name)
    if investigated:
        parts.append("調査済み: " + "、".join(investigated[:6]))
    if pending:
        parts.append("未調査: " + "、".join(pending[:6]))

    exits = scenario_mgr.get_available_exits(current_loc)
    if exits:
        parts.append("移動可: " + "、".join(e["name"] for e in exits[:5]))

    # レガシーシナリオ用フラグは、該当オブジェクトが実在するときだけ付記する
    flags = scenario_mgr.flags
    if _scenario_has_object(scenario_mgr, "iron_door", current_loc) and flags.get("door_opened"):
        parts.append("鉄扉: 開済み")
    if _scenario_has_object(scenario_mgr, "desk", current_loc) and flags.get("found_button"):
        parts.append("隠しボタン: 発見済み" + ("・作動済み" if flags.get("button_pushed") else "・未作動"))
    if _scenario_has_object(scenario_mgr, "iron_gate", current_loc):
        if flags.get("gate_weakness_found"):
            parts.append("鉄格子弱点: 発見済み")
        if flags.get("gate_opened"):
            parts.append("鉄格子: 開放済み")

    return "【現在の確定状況（厳守）】" + " / ".join(parts) + "\n"


def _build_pl_scenario_context(scenario_mgr, current_loc):
    """シナリオデータに基づく PL 向け状況メモ（無駄行動・再探索の誤誘導を防ぐ）。"""
    if not scenario_mgr:
        return ""

    flags = scenario_mgr.flags
    lines = []
    objects = _location_objects(scenario_mgr, current_loc)

    # 汎用: 調査済み／未調査の明示
    for obj_id, obj in objects.items():
        name = obj.get("name", obj_id)
        if scenario_mgr._is_target_investigated(obj_id) and not scenario_mgr._is_research_reopened(obj_id):
            reject = obj.get("reject_message") or "これ以上の発見はない"
            lines.append(f"【⚠️探索禁止】{name}（`{obj_id}`）は調査済み。{reject}")
        elif obj.get("purpose"):
            lines.append(f"【状況】{name}（`{obj_id}`）: {obj.get('purpose')}")

    # 既存テストシナリオ向けの詳細ガイド（該当オブジェクトがある場所だけ）
    if current_loc == "study" and _scenario_has_object(scenario_mgr, "desk", "study"):
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
            lines.append("【状況】祭壇の間への進入時SANは**処理済み**（部屋全体の恐怖は既に正気を試している）。")
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

    recommended = _build_pl_recommended_action(scenario_mgr, current_loc)
    if recommended:
        lines.append(recommended)
    if not lines:
        return ""
    return "【シナリオ状況メモ（システム確定情報・厳守）】\n" + "\n".join(f"- {line}" for line in lines) + "\n"


def _build_pl_recommended_action(scenario_mgr, current_loc):
    """次に取るべき行動を明示（シナリオ内の実オブジェクトから推奨）。"""
    if not scenario_mgr:
        return ""
    flags = scenario_mgr.flags

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
        if _introduction_move_unlocked(scenario_mgr):
            exits = scenario_mgr.get_available_exits(current_loc)
            for preferred in ("boston_globe", "central_library"):
                for exit_info in exits:
                    if exit_info.get("id") == preferred:
                        return (
                            f"【推奨次アクション】action: move / target: {preferred}"
                            f"（{exit_info.get('name', preferred)} へ）"
                        )
            if exits:
                dest = exits[0]
                return (
                    f"【推奨次アクション】action: move / target: {dest['id']}"
                    f"（{dest.get('name', dest['id'])} へ）"
                )

    if current_loc == "boston_globe":
        if not flags.get("artie_introduced"):
            return (
                "【推奨次アクション】action: talk / target: globe_receptionist"
                "（受付デスクを調べるのではなく、受付の人に話しかけて"
                "アーティ・ウィルモットを呼び出してもらう。対話最優先）"
            )
        return (
            "【推奨次アクション】action: talk または persuade / target: artie_wilmott"
            "（まず編集者と会話し、参考資料室の許可を得る。"
            "無断で資料室オブジェクトを search しない）"
        )

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
    """導入完了後に PL へ移動を強く促すシステム通知。"""
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
【システム通知（推奨行動）】
現在の場所（introduction）での基本調査とNPCへの聞き込みは完了し、次の目的地への移動が解禁されています。
同じ質問をNPCに繰り返すのではなく、`move` アクションを使用して次の調査先へ移動することを強く推奨します。
移動可能先の例: {dest_lines}
（メモの手がかりに従うなら `move` / target: `boston_globe` を優先）
"""


def _maybe_set_context_stagnation_hint(state, scenario_mgr, state_mgr):
    """膠着中なら、現在ロケーションに応じた具体ヒントをセットする。"""
    if not state_mgr or not scenario_mgr or not state:
        return
    tracker = state_mgr.stagnation_tracker or {}
    streak = int(tracker.get("streak") or 0)
    if streak < 1:
        return
    current_loc = (
        state.get("current_loc")
        or getattr(scenario_mgr, "location", "")
        or ""
    )
    # 導入は移動解禁後のみ具体ヒントを出す
    if current_loc == "introduction" and not _introduction_move_unlocked(scenario_mgr):
        return
    hint = build_context_stagnation_hint(scenario_mgr, current_loc)
    if not hint:
        return
    state["stagnation_pl_hint"] = hint
    intervened_at = int(tracker.get("intervened_at_streak") or 0)
    if intervened_at < streak:
        state_mgr.mark_stagnation_intervened()


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
}


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
    return _scenario_object_exists_anywhere(scenario_mgr, mid)


def normalize_action_target(target, scenario_mgr=None, current_loc=None, char_mgr=None):
    """PL/LLM が返した target をシナリオ内部IDへ統一する（未定義IDへの誤マップを防ぐ）。"""
    raw = str(target or "").strip()
    if not raw:
        return ""

    lower = raw.lower()

    # NPC（ID または名前）はシナリオオブジェクト正規化より優先して保持する
    if char_mgr:
        npc_id = find_npc_id_by_target(char_mgr, raw)
        if npc_id:
            return npc_id

    if scenario_mgr:
        if lower in scenario_mgr.get_all_location_ids():
            return lower
        if current_loc:
            objects = _location_objects(scenario_mgr, current_loc)
            if lower in objects:
                # 受付デスク等は対話時に NPC へ寄せるため、ID 自体は保持
                return lower
            # 現在地の日本語名との部分一致を優先（別名グローバル辞書より先）
            for obj_id, obj in objects.items():
                obj_name = str(obj.get("name", "") or "")
                if obj_name and (raw == obj_name or obj_name in raw or raw in obj_name):
                    return obj_id
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
            "message": last_action.get("message", ""),
            "dialogue": last_action.get("dialogue", ""),
        }, scenario_mgr, loc, char_mgr=char_mgr)
    return state


def _infer_talk_target_from_log_entry(entry, char_mgr):
    """talk 行動で target が空のとき、ログ文面から NPC ID を推定する。"""
    meta = entry.get("meta") or {}
    if str(meta.get("action_id") or meta.get("action") or "").lower() != "talk":
        return ""
    if meta.get("target"):
        return meta.get("target")
    text = str(entry.get("text", "") or "")
    if not char_mgr:
        return ""
    for cid, char in char_mgr.characters.items():
        if not char.get("profile", {}).get("is_npc"):
            continue
        name = str(char.get("profile", {}).get("name") or "")
        if not name:
            continue
        if name in text:
            return cid
        if "ノット" in text and "ノット" in name:
            return cid
    return ""


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

    rewritten = rewrite_human_investigation_to_talk(action, target, char_mgr=char_mgr)
    if rewritten:
        return (
            rewritten["action"],
            rewritten["target"],
            rewritten.get("skill", ""),
            rewritten.get("log", HUMAN_INSPECT_REWRITE_LOG),
        )

    if current_loc == "boston_globe" and not flags.get("artie_introduced"):
        if target in ("reference_room_clipping_files", "artie_wilmott"):
            return "talk", "globe_receptionist", "", HUMAN_INSPECT_REWRITE_LOG
        if action in ("search", "inspect") and target in ("reception_desk", "globe_receptionist"):
            return "talk", "globe_receptionist", "", HUMAN_INSPECT_REWRITE_LOG

    if current_loc == "introduction" and not flags.get("talked_with_knott"):
        if action == "talk" and not target:
            return "talk", "steven_knott", "", ""

    return None


def reconcile_pl_action(
    pc_action, speak_as, pl_ooc, scenario_mgr, current_loc,
    pending_san_check=None, char_mgr=None,
):
    """
    セリフ・メタ発言・行動コマンドの整合をサーバー側で補正／検証する。
    - 対人 search/inspect/push → talk へ自動変換
    - move のテキスト不一致 → validation_error（実行せず PL 再生成）
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
    location_ids = set(scenario_mgr.get_all_location_ids())
    objects = scenario_mgr.get_location_info(current_loc).get("objects", {})
    object_ids = set(objects.keys())
    corrected = False
    correction_log = ""

    if speak_as == "PL":
        return {
            "action": "wait",
            "target": "",
            "skill": "",
            "message": pl_ooc or "（様子を見ている）",
            "dialogue": "",
        }

    social_fix = _reconcile_communication_priority(
        action, target, skill, intent, scenario_mgr, current_loc, flags, object_ids,
        char_mgr=char_mgr,
    )
    if social_fix:
        action, target, skill, correction_log = social_fix
        corrected = True

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
                "validation_error": move_check.get("error") or MOVE_INTENT_MISMATCH_ERROR,
                "validation_error_code": move_check.get("error_code", "move_intent_mismatch"),
                "suggested_fix": move_check.get("suggested_fix"),
                "needs_pl_retry": True,
            }

    # move + オブジェクトID は操作／対話へ変換
    if action == "move" and target in object_ids:
        npc = resolve_social_npc_id(target, char_mgr=char_mgr)
        if npc:
            action, target, skill = "talk", npc, ""
            correction_log = correction_log or HUMAN_INSPECT_REWRITE_LOG
            corrected = True
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
            is_npc_target = bool(char_mgr and find_npc_id_by_target(char_mgr, target))
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
    }
    if correction_log:
        result["system_correction_log"] = correction_log
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
    """システム判定が実質的な進展だったか。"""
    if not result or result.get("blocked"):
        return False
    if result.get("location_changed"):
        return True

    if payload:
        if payload.get("flag_updates") or payload.get("location_changed") or payload.get("new_location"):
            return True
        if payload.get("mark_investigated") and not payload.get("blocked"):
            return True

    log = result.get("log", "") or ""
    progress_keywords = (
        "【成功】", "【弱点活用・成功】", "【クリア】", "手がかり", "発見",
        "【移動】", "移動した", "到着", "【スタック救済】", "【アイデアロール成功】",
    )
    if any(keyword in log for keyword in progress_keywords):
        return True

    status = result.get("status", 0)
    if is_success_level(status):
        if "【STR対抗・僅差】" in log or "特になにも" in log:
            return False
        if "失敗" in log and "【成功】" not in log and not payload:
            return False
        return True
    return False


def _is_system_action_stagnation(result, payload=None):
    """システム判定が膠着（拒否・失敗・空振り）だったか。"""
    if not result:
        return False
    if result.get("blocked") or result.get("roll_type") == "blocked":
        return True

    log = result.get("log", "") or ""
    stagnation_keywords = (
        MOVE_DENY_SYSTEM_LOG,
        "【移動不可】",
        "【システムブロック】",
        "存在しません",
        "すでに調査",
        "再調査",
        "特になにも見つからなかった",
    )
    if any(keyword in log for keyword in stagnation_keywords):
        return True

    action_id = str(result.get("action_id", "") or "").lower()
    if action_id in ("wait", "none", ""):
        return False

    if result.get("status", 0) == 0:
        if "失敗" in log or result.get("roll_type") in ("skill", "opposed_str"):
            if not _is_system_action_progress(result, payload):
                return True
    if is_failure_level(result.get("status", 0)) and not _is_system_action_progress(result, payload):
        if result.get("roll_type") in ("skill", "opposed_str", "blocked"):
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

    if _is_system_action_progress(result, payload):
        scenario_mgr.reset_stagnation_counter()
        result["stagnation_progress"] = True
    elif _is_system_action_stagnation(result, payload):
        result["stagnation_candidate"] = True

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
        hint = build_context_stagnation_hint(
            scenario_mgr, current_loc, fallback=STAGNATION_STANDARD_PL_HINT,
        )
        state["stagnation_pl_hint"] = hint
        state["all_events_log"].append({
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": hint,
            "meta": {"stagnation_hint": True, "location": current_loc},
        })
        summary["actions"].append("pl_hint")
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
    """膠着検知→介入レベルに応じた処理。"""
    char_mgr, dice_engine, state_mgr, scenario_mgr = managers
    if not state_mgr or not scenario_mgr:
        return None
    if after_step not in (
        "system_process", "luck_decision", "push_decision", "pl_speak", "free_chat",
    ):
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
    system_for_detect = None

    if after_step in ("system_process", "luck_decision", "push_decision"):
        if not result:
            return None
        made_progress = bool(
            result.get("stagnation_progress")
            or _is_system_action_progress(result)
            or result.get("new_location")
        )
        if made_progress:
            detection = state_mgr.detect_stagnation(
                state.get("all_events_log"),
                location_id=state.get("current_loc"),
                flags=scenario_mgr.flags,
                max_stagnation_turns=max_turns,
                last_pl_action=pl_action,
                last_system_result=result,
                made_progress=True,
            )
            scenario_mgr.stagnation_counter = detection["streak"]
            return detection
        if not _is_system_action_stagnation(result):
            return None
        system_for_detect = result
    elif after_step in ("pl_speak", "free_chat"):
        chat_only = is_nonprogress_pl_action(
            pl_action, state.get("pending_san_check"),
            scenario_mgr=scenario_mgr,
            current_loc=state.get("current_loc"),
            char_mgr=char_mgr,
        )
        if not chat_only:
            return None

    detection = state_mgr.detect_stagnation(
        state.get("all_events_log"),
        location_id=state.get("current_loc"),
        flags=scenario_mgr.flags,
        max_stagnation_turns=max_turns,
        last_pl_action=pl_action,
        last_system_result=system_for_detect,
        chat_only=chat_only,
        made_progress=False,
    )
    scenario_mgr.stagnation_counter = detection["streak"]
    state["stagnation_streak"] = detection["streak"]
    _maybe_set_introduction_stagnation_hint(state, scenario_mgr, state_mgr)

    if not detection.get("needs_intervention"):
        return detection

    level = resolve_session_intervention_level(state, scenario_mgr)
    applied = apply_stagnation_intervention(state, managers, level, detection)
    state_mgr.mark_stagnation_intervened()
    state["last_stagnation_intervention"] = applied
    return {**detection, "intervention": applied}


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
"""


def _build_kp_situational_directives(scenario_mgr=None, last_system_result=None, state=None):
    """状況に応じた KP 向け追加制約。"""
    parts = []
    room_state = _build_kp_room_state_directive(scenario_mgr)
    if room_state:
        parts.append(room_state)
    idol_directive = _build_kp_idol_steering_directive(scenario_mgr)
    if idol_directive:
        parts.append(idol_directive)

    stagnation_injection = _build_kp_stagnation_injection(scenario_mgr, state=state)
    if stagnation_injection:
        parts.append(stagnation_injection + "\n")

    lines = []
    if scenario_mgr:
        flags = scenario_mgr.flags
        if flags.get("artie_reference_room_access_granted"):
            lines.append(
                "- 【絶対遵守】NPCアーティは既に参考資料室への立ち入りを許可済み。"
                "アクセス不可・未許可を示唆する描写や台詞を絶対に生成しないこと。"
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
    if action == "search" or action == "inspect":
        if not skill:
            skill = "目星"
    else:
        skill = ""

    message = _build_pc_display_message(dialogue, action, target, action_locked=action_locked)

    if speak_as == "PL" and action in ("", "wait"):
        action = "wait"
        message = dialogue or pl_ooc_chat or "（様子を見ている）"

    pc_action = {
        "action": action,
        "target": target,
        "skill": skill,
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


def default_kp_response():
    return parse_kp_response({
        "thought": "通信障害のため最低限の進行を行う。",
        "should_speak": True,
        "speak_mode": "system_narration",
        "text": "（通信エラー）KPの思考が途切れました。しばらく様子を見てください。",
    })


def _call_chat_completion(
    messages,
    model,
    temperature,
    max_retries=3,
    json_mode=False,
):
    """OpenAI 互換 chat.completions 呼び出し（指数バックオフ付き）。"""
    client = get_client()
    wait_time = 4
    use_json_mode = json_mode
    last_error = None

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

            response = client.chat.completions.create(**kwargs)
            content = response.choices[0].message.content
            if content is None:
                raise ValueError("LLM が空の応答を返しました")
            return content.strip()

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

    raise last_error or RuntimeError("LLM API 呼び出しに失敗しました")


save_manager = SaveLoadManager()
chat_session = None

# 幸運消費の救済上限（1回あたりの最大消費提案ポイント）
LUCK_BURN_MAX = 10

# ==========================================
# 1. セーブ＆ロード処理 (SaveLoadManager 委譲)
# ==========================================
def build_save_data(game_state, character_manager, scenario_manager, app_state, scenario_file=None):
    """すべての状態を一つの辞書データとしてまとめる。"""
    for char in character_manager.characters.values():
        character_manager.normalize_character_attributes(char)
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


def sync_progress_managers(state_mgr, scenario_mgr, save_data=None):
    """
    game_state を進行フラグ・ターン数の Single Source of Truth として接続する。
    旧セーブ（scenario_manager.flags / turn_counter）からの移行もここで行う。
    """
    if not state_mgr or not scenario_mgr:
        return

    gs = (save_data or {}).get("game_state") or {}
    sm = (save_data or {}).get("scenario_manager") or {}

    if gs.get("flags"):
        state_mgr.flags = dict(gs["flags"])
    elif sm.get("flags"):
        state_mgr.flags = dict(sm["flags"])

    gs_turn = int(gs.get("turn_count") or 0)
    sm_turn = int(sm.get("turn_counter") or 0)
    state_mgr.turn_count = max(gs_turn, sm_turn, int(state_mgr.turn_count or 0))

    scenario_mgr.bind_game_state(state_mgr)


def recover_pending_timeline_on_load(
    app_state, scenario_mgr=None, char_mgr=None, *, normalize_runtime_flags=True
):
    """
    未処理 PL 行動（system_processed: false）や last_pl_action 不整合を修復する。
    is_running かつ未処理がある場合は巡航再開可能な状態に整える。
    """
    app_state = normalize_loaded_runtime_state(
        dict(app_state or {}),
        enforce_half_turn_pause=normalize_runtime_flags,
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
    app_state = recover_pending_timeline_on_load(
        app_state,
        scenario_mgr=scenario_manager,
        char_mgr=character_manager,
    )
    # game_state の膠着ストリークを app_state へ同期し、強制 IC 判定に使う
    tracker = getattr(game_state, "stagnation_tracker", None) or {}
    app_state["stagnation_streak"] = int(tracker.get("streak") or 0)
    cleanse_session_npc_state(
        character_manager,
        scenario_manager,
        all_events_log=app_state.get("all_events_log"),
        new_session=False,
    )
    if is_force_ic_action_phase(app_state, state_mgr=game_state):
        ensure_force_ic_action_phase(app_state, state_mgr=game_state)
    return app_state


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
def _format_objects_for_pl(location_info):
    """オブジェクトの usable_actions / purpose / description を PL 向けに整形する。"""
    objects = location_info.get("objects", {}) if location_info else {}
    if not objects:
        return ""

    lines = []
    for obj_id, obj in objects.items():
        actions = obj.get("usable_actions", ["search"])
        purpose = obj.get("purpose", "")
        desc = str(obj.get("description", "") or "").strip()
        line = f"- {obj_id} ({obj.get('name', obj_id)}): アクション [{', '.join(actions)}]"
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

    return (
        "【現在地のオブジェクトと利用可能アクション】\n"
        "※ ここに載っていない物体は世界に存在しません。創作・執着禁止。\n"
        + "\n".join(lines) + "\n"
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
【最重要・行動拒否の警告】あなたは直前に `{target_disp}` に対して `{action_disp}` を試みましたが、システムおよびKPから「すでに調査し尽くされており、これ以上の発見は絶対にない（無意味である）」と完全に拒否・ブロックされました。
同じ対象へ同じ調査を繰り返すことは、AIとしての致命的なバグ（無限ループ）とみなされます。現在の思考（OOC）と行動（IC）において、その対象への執着を完全に捨て、未探索の他のオブジェクト（例: {examples}）へ100%視野を切り替えて次の行動を決定してください。一覧に無い物体を創作しないこと。
"""


def generate_pl_prompt(
    char_name, ic_logs, ooc_logs, location_info=None, available_exits=None,
    pending_push_roll=None, pending_san_check=None,
    scenario_mgr=None, current_loc=None, last_system_result=None,
    char_mgr=None, pl_id=None, all_events_log=None,
    stagnation_pl_hint=None,
    force_ic_action=False,
):
    san_locked = _is_san_check_pending(pending_san_check)
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
    scenario_context = _build_pl_scenario_context(scenario_mgr, current_loc) if not san_locked else ""
    phase_summary = _build_pl_phase_summary(scenario_mgr, current_loc) if scenario_mgr and not san_locked else ""
    grounding = (
        _build_scenario_grounding_directive(scenario_mgr, current_loc)
        if scenario_mgr and not san_locked else ""
    )

    force_ic_block = ""
    if force_ic_action and not san_locked:
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
        stagnation_pl_hint = OOC_LOOP_FORCE_ACTION_WARNING

    loc_desc = ""
    if location_info and not san_locked:
        loc_name = location_info.get("name", "")
        if loc_name:
            loc_desc += f"\n【現在地】{loc_name}\n"
        loc_desc += _format_objects_for_pl(location_info)

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
            char_mgr, current_loc=current_loc or "", flags=flags,
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
- search / inspect 時のみ `pc_ic_action.skill` に技能名（例: 目星）を入れてください。push / break / move / climb 時は skill は**必ず空文字**。
- NPC対話: action `talk`（雑談・判定なし）。交渉は action `persuade`/`fast_talk`/`intimidate`/`charm`/`psychology`
  または skill に〈説得〉〈言いくるめ〉〈威圧〉〈魅惑〉〈心理学〉を指定し、target に NPC の ID/名前。
- `dialogue` と `pl_ooc_chat` に英語の内部IDは**禁止**。日本語の物体名・場所名・人物名のみ。
- 「〜かもしれないね」「〜しよう」「〜すべきだ」等の分析・作戦口調は `pl_ooc_chat` のみ。`dialogue` は一人称の世界内セリフのみ。

【職業ロールプレイ（判定に影響）】
- 自分の職業・立場を活かしたIC発言（例: 刑事なら「市警の捜査で来た」、教授なら文献調査の体）は、交渉のボーナス・ダイスや、状況次第で判定省略につながることがある。
- 場にそぐわない身分詐称・職業の誤用・的外れな権威の振りかざしは、ペナルティ・ダイスの対象になる。
- 交渉（persuade 等）では、職業に沿った具体的な趣旨を `dialogue` に含めること。

【コミュニケーション最優先（厳守）】
- このゲームでは**人と話すこと**が最も重要です。受付・依頼人・編集者など【対話可能なNPC】がいる場所では、物を調べる前にまず `talk` してください。
- 受付デスクや事務机など「人がいる家具」を search/inspect するより、その人本人に話しかけてください。
- ボストン・グローブの「参考資料室／切り抜きファイル」は**場所への move ではありません**（公文書館 `hall_of_records` とは別物）。
  資料室に入るには受付→アーティ紹介→許可が必要です。セリフで資料室に触れているのに公文書館へ move するのは禁止。
- dialogue（やりたいこと）と pc_ic_action（実際の action/target）を一致させてください。

【幸運の消費・プッシュロール（CoC7ルール）】
- 技能ロール失敗時、差分10以内かつ幸運が足りる場合のみ、別ターンで幸運消費の選択が提示されます。
- プッシュロール可能時は action: "push_roll" を指定してください。
- 手がかりが得られず進行が詰まりそうな場合は、温存より幸運消費・プッシュを**積極的に**検討してください。
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
{force_ic_block}
{insanity_directive}
{repeat_failure_penalty}
{blocked_warning}
{idol_exhausted_warning}
{grounding}
{state_directive}
{insanity_override}
{phase_summary}{scenario_context}
{intro_move_nudge}
{"" if san_locked or not stagnation_pl_hint else (str(stagnation_pl_hint).strip() + chr(10))}
あなたは「クトゥルフ神話TRPG」をプレイする存在です。操作キャラクター: {char_name}

【多層的な意識（厳守）】
あなたには **PL（メタ視点のプレイヤー）** としての意識と、**PC（ゲーム内の探索者）** としての意識が同時に存在します。
まず `thought` で「今どちらの意識で発言・行動すべきか」を内省し、`speak_as` で主体を選んでください。

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
{push_desc}
{loc_desc}{exit_desc}{npc_dir}
【キャラクターが知っている情報 (IC)】
{chr(10).join(ic_logs[-6:])}

【プレイヤーとして知っているメタ情報 (OOC) — 直近のみ。古いエリアの話題は無視せよ】
{chr(10).join(ooc_logs[-2:])}
"""


def generate_pl_luck_prompt(
    char_name, pending_luck_burn, char_mgr, pl_id, ic_logs, ooc_logs,
    scenario_mgr=None, all_events_log=None,
):
    """幸運消費の可否を PL（AI）に判断させる専用プロンプト。"""
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

    return f"""
{insanity_directive}
あなたは「クトゥルフ神話TRPG」をプレイする存在です。操作キャラクター: {char_name}

【多層的な意識（厳守）】
あなたには **PL（メタ視点）** と **PC（探索者）** の二重意識がありますが、今は **幸運消費の判断** に専念してください。
`speak_as` は必ず `"PL"` とし、**メタ視点の判断のみ**を `pl_ooc_chat` に書いてください。
幸運の温存・消費を PC のセリフ（dialogue）で語ることは**禁止**です（ルール用語は PL/OOC のみ）。

【OOCメッセージ・最優先】
あなたは幸運を【{margin}ポイント】消費することで、この失敗を成功に書き換えることができます。消費しますか？
JSON の `content.use_luck` に true/false、または `content.pl_ooc_chat` で 'yes' / 'no' と回答してください。
（対象技能: {skill_name} / 対象: {target} / 現在の幸運値: {current_luck}）

{stuck_guidance}

【キャラクターが知っている情報 (IC)】
{chr(10).join(ic_logs[-6:])}

【プレイヤーとして知っているメタ情報 (OOC)】
{chr(10).join(ooc_logs[-3:])}
"""


def generate_pl_push_prompt(
    char_name, pending_push_roll, char_mgr, pl_id, ic_logs, ooc_logs,
    scenario_mgr=None, all_events_log=None,
):
    """プッシュロールの可否を PL（AI）に判断させる専用プロンプト。"""
    skill_name = pending_push_roll.get("skill_name", "")
    target = pending_push_roll.get("target", "")
    difficulty = pending_push_roll.get("required_difficulty", "regular")
    insanity_directive = _build_pl_insanity_directive(
        char_mgr, pl_id, for_luck_decision=True,
    )

    return f"""
{insanity_directive}
あなたは「クトゥルフ神話TRPG」をプレイする存在です。操作キャラクター: {char_name}

【多層的な意識（厳守）】
今は **プッシュロール（再挑戦）の判断** に専念してください。
`speak_as` は必ず `"PL"` とし、メタ視点の判断のみを書いてください。

【OOCメッセージ・最優先】
直前の「{skill_name}」判定（対象: {target} / 難易度: {difficulty}）は失敗しました。
リスクを背負って再挑戦（プッシュ）できます。プッシュする場合、どのようにアプローチを変えて挑戦するかを `content.push_approach` に記述してください
（例: より時間をかける、道具を強引に使う等）。
`content.use_push` に true/false、または `content.pl_ooc_chat` で 'yes' / 'no' と回答してください。
※プッシュに失敗した場合は「恐ろしい結果（重大なペナルティ）」が発生します。

【キャラクターが知っている情報 (IC)】
{chr(10).join(ic_logs[-6:])}

【プレイヤーとして知っているメタ情報 (OOC)】
{chr(10).join(ooc_logs[-3:])}
"""


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
        lines.append(f"・【成功時に必ず含める確定手がかり】{confirmed}")
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


def generate_kp_prompt(location_info, last_pl_action=None, last_system_result=None, scenario_mgr=None, state=None):
    # ★追加: シナリオJSONから安全で正確な部屋の情報を取得
    loc_name = location_info.get("name", "未知の場所")
    loc_desc = location_info.get("default_description", "")
    situational = _build_kp_situational_directives(scenario_mgr, last_system_result, state=state)
    allowed_facts = _build_kp_allowed_facts_block(scenario_mgr, last_pl_action, last_system_result)

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

【現在の状況】
・現在地: {loc_name}
・場所の基本描写: {loc_desc}
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
    """正規化済み KP 応答を IC/OOC ログに振り分けて追記する。"""
    if not kp_data.get("should_speak", True):
        return

    text = kp_data.get("text", "").strip()
    if not text:
        return

    if kp_data.get("speak_mode") == "player_kp_chat":
        all_events_log.append(
            {"channel": "OOC", "location": "all", "secret_to": None, "text": f"KP(プレイヤー層): {text}"}
        )
    else:
        all_events_log.append(
            {"channel": "IC", "location": current_loc, "secret_to": None, "text": f"KP: {text}"}
        )


def _is_duplicate_validation_error_log(all_events_log, *, error_code="", pc_id=None, message=""):
    """直近ログに同一 validation_error があれば重複出力を抑止する。"""
    if not error_code:
        return False
    recent = list(all_events_log or [])[-8:]
    for entry in reversed(recent):
        meta = entry.get("meta") or {}
        if not meta.get("validation_error"):
            continue
        if str(meta.get("error_code") or "") != str(error_code):
            continue
        if pc_id and meta.get("pc_id") and meta.get("pc_id") != pc_id:
            continue
        if message and entry.get("text") != f"[システム] {message}":
            continue
        return True
    return False


def _build_auto_correction_action(
    pc_action, suggested_fix, scenario_mgr, current_loc, char_mgr=None,
):
    """validation_error から推奨修正を自動適用した action を生成する。"""
    fixed = normalize_pc_action(
        {
            "action": suggested_fix.get("action") or "move",
            "target": suggested_fix.get("target") or "",
            "skill": suggested_fix.get("skill") or "",
            "dialogue": pc_action.get("dialogue", ""),
            "message": "",
        },
        scenario_mgr,
        current_loc,
        char_mgr=char_mgr,
    )
    fixed["system_correction_log"] = (
        "【アクション自動補正】同一無効行動の反復を検知したため、"
        f"`{fixed.get('action')}` / `{fixed.get('target')}` に補正しました。"
    )
    fixed["auto_corrected"] = True
    return fixed


def apply_pl_response_to_logs(
    ai_data, char_name, current_loc, all_events_log,
    pending_san_check=None, scenario_mgr=None,
    pc_id=None, char_mgr=None,
    force_ic_action=False,
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

    if san_locked:
        pc_action = _enforce_san_lock_pc_action(pc_action, pl_ooc)
    elif scenario_mgr:
        pc_action = reconcile_pl_action(
            pc_action, speak_as, pl_ooc, scenario_mgr, current_loc,
            pending_san_check=pending_san_check,
            char_mgr=char_mgr,
        )
        # 移動意図不一致・完了済みKnott対話など → ログにエラーを残し、システム行動は起こさない
        knott_check = validate_completed_knott_talk(
            pc_action,
            scenario_mgr=scenario_mgr,
            current_loc=current_loc,
            char_mgr=char_mgr,
        )
        if not knott_check.get("ok") and not pc_action.get("needs_pl_retry"):
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
            suggested_fix = pc_action.get("suggested_fix") or {}
            # stale_knott_talk は即時拒絶でループしやすいため、自動補正で move/search へ寄せる。
            if (
                err_code in ("stale_knott_talk", "force_ic_stale_talk")
                and suggested_fix
                and not san_locked
                and scenario_mgr
            ):
                pc_action = _build_auto_correction_action(
                    pc_action, suggested_fix, scenario_mgr, current_loc, char_mgr=char_mgr,
                )
            else:
                if not _is_duplicate_validation_error_log(
                    all_events_log, error_code=err_code, pc_id=pc_id, message=err,
                ):
                    all_events_log.append({
                        "channel": "OOC",
                        "location": "all",
                        "secret_to": None,
                        "text": f"[システム] {err}",
                        "meta": {
                            "validation_error": True,
                            "error_code": err_code,
                            "pc_id": pc_id,
                        },
                    })
                # 強制 IC 中は拒否時も OOC を残さない
                if pl_ooc and speak_as in ("PL", "BOTH") and not force_ic_action:
                    all_events_log.append({
                        "channel": "OOC",
                        "location": "all",
                        "secret_to": None,
                        "text": f"{pl_prefix}: {pl_ooc}",
                        "meta": {"pc_id": pc_id} if pc_id else {},
                    })
                return pc_action
        if speak_as != "PL" and _texts_overlap(pl_ooc, pc_action.get("dialogue", "")):
            pc_action["dialogue"] = ""
            pc_action["message"] = _build_pc_display_message(
                "", pc_action.get("action", "wait"), pc_action.get("target", ""),
                scenario_mgr=scenario_mgr, current_loc=current_loc,
            )

    if should_speak and pl_ooc and speak_as in ("PL", "BOTH") and not force_ic_action:
        all_events_log.append({
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": f"{pl_prefix}: {pl_ooc}",
            "meta": {"pc_id": pc_id} if pc_id else {},
        })

    log_pc = (
        should_speak
        and speak_as in ("PC", "BOTH")
        and (san_locked or speak_as == "PC" or pc_action.get("action", "wait") not in ("wait", "", "none"))
    )
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
                "needs_system": needs_system,
                "system_processed": False,
            },
        })

    if pc_action.get("system_correction_log"):
        all_events_log.append({
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": f"[システム] {pc_action['system_correction_log']}",
            "meta": {"system_correction": True, "pc_id": pc_id},
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
    messages = [
        {
            "role": "system",
            "content": (
                sheet_block
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
    except Exception as exc:
        print(f"\n[PL API 最終エラー] {exc}")

    print("\n[PL] リトライ上限に達しました。ダミーアクションを返します。")
    if json_schema == PL_LUCK_JSON_SCHEMA:
        return default_pl_luck_response()
    if json_schema == PL_PUSH_JSON_SCHEMA:
        return default_pl_push_response()
    if json_schema == PL_COMBAT_DEFENSE_JSON_SCHEMA:
        return default_pl_combat_defense_response()
    if json_schema == PL_SHOOT_DEFENSE_JSON_SCHEMA:
        return default_pl_shoot_defense_response()
    return default_pl_action_response()


def call_kp_api(prompt, max_retries=3):
    """KP用のローカル LLM 呼び出し（JSON 多層意識スキーマ）。"""
    cfg = get_llm_config()
    finalized_prompt = _finalize_pl_prompt_for_json(prompt, KP_JSON_SCHEMA)
    messages = [
        {
            "role": "system",
            "content": (
                "あなたはクトゥルフ神話TRPGのKP AIです。"
                "システムKPとプレイヤーKPの二重意識を持ち、必ず有効な JSON オブジェクトのみを出力してください。"
            ),
        },
        {"role": "user", "content": finalized_prompt},
    ]

    try:
        response_text = _call_chat_completion(
            messages,
            model=cfg["kp_model"],
            temperature=0.8,
            max_retries=max_retries,
            json_mode=True,
        )
        return parse_kp_response(json.loads(_extract_json_object(response_text)))
    except json.JSONDecodeError as exc:
        print(f"\n[KP API JSONパースエラー] {exc}")
    except Exception as exc:
        print(f"\n[KP API 最終エラー] {exc}")

    print("\n[KP] リトライ上限に達しました。ダミーメッセージを返します。")
    return default_kp_response()

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


def _skill_allows_push(skill_name, action_id=None, *, in_combat=False, already_pushed=False):
    """7版に従い、プッシュ不可のロールをガードする。"""
    if in_combat or already_pushed:
        return False
    action = str(action_id or "").lower()
    if action in ("san_check", "wait"):
        return False
    skill = str(skill_name or "").strip()
    if not skill:
        # 純粋な力比べ等で技能名が空の場合はプッシュ不可（状況依存の行為はシナリオ側）
        return False
    if skill in UNPUSHABLE_SKILLS:
        return False
    if any(kw in skill for kw in COMBAT_SKILL_KEYWORDS):
        return False
    return True


def _handle_skill_roll_failure(
    dice_result, char_mgr, pl_id, target, skill_name, action_id,
    skill_modifier, skill_bonus, skill_penalty,
    required_difficulty="regular",
    *,
    fail_level=None,
    allow_push=True,
):
    """
    技能ロール失敗時の分岐。
    差分が LUCK_BURN_MAX 以内かつ幸運が足りる場合は pending_luck_burn を返す。
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
    if margin <= 0:
        return fail_level, None, None

    push_state = None
    if allow_push and _skill_allows_push(
        skill_name, action_id, in_combat=False, already_pushed=False,
    ):
        push_state = _build_push_roll_state(
            target, skill_name, action_id, skill_modifier, skill_bonus, skill_penalty,
            required_difficulty=required_difficulty,
            failed_success_level=fail_level,
            allow_push=True,
            decision_pending=True,
        )

    if char_mgr.can_offer_luck_burn(pl_id, margin, max_burn=LUCK_BURN_MAX):
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
    *, in_combat=False, required_difficulty="regular",
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
    if skill_name:
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


def append_system_log_entry(all_events_log, current_loc, log_text, action_id="", target="", roll_type=""):
    """システムログを IC チャンネルに1エントリとして追記する。"""
    text = (log_text or "").strip()
    if not text:
        return
    entry = {
        "channel": "IC",
        "location": current_loc,
        "secret_to": None,
        "text": f"システム: {text}",
    }
    if action_id or target or roll_type:
        entry["meta"] = {
            "action_id": action_id,
            "target": target,
            "roll_type": roll_type,
            "kp_narrated": False,
        }
    else:
        entry["meta"] = {"kp_narrated": False}
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
        "roll_type": roll_type,
        "action_id": action_id,
        "target": action_target,
        "success_level": int(success_level or 0),
    }
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
    if payload and payload.get("new_phase"):
        result["new_phase"] = payload["new_phase"]
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


def _apply_combat_payload_effects(payload, state_mgr, char_mgr, pl_id, sys_log="", active_pcs=None):
    """イベント payload の combat_start / combat_end をゲーム状態へ反映する。"""
    if not payload or not state_mgr or not pl_id:
        return sys_log

    lines = []

    if payload.get("combat_end") and state_mgr.in_combat:
        state_mgr.end_combat()
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
            order = state_mgr.start_combat(participants)
            order_names = [
                char_mgr.characters[cid]["profile"]["name"]
                for cid in order
                if cid in char_mgr.characters
            ]
            lines.append(f"【戦闘開始】行動順: {' → '.join(order_names)}")
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
    pending = {
        "attacker_id": attacker_id,
        "defender_id": defender_id,
        "attacker_skill": atk_skill,
        "attacker_skill_value": atk_value,
        "weapon": weapon,
        "location": current_loc,
        "round": state_mgr.round_number,
        "attack_type": "melee",
        "allowed_defense_modes": ["dodge", "fight_back"],
    }
    state_mgr.set_pending_combat_defense(pending)
    log = (
        f"【戦闘・攻撃宣言】{atk_name} が {def_name} に〈{atk_skill}〉({atk_value}) で攻撃！"
        f"\n【保留】{def_name} は【回避】か【応戦】を選択してください。（PENDING_COMBAT_DEFENSE）"
    )
    return {
        "ok": True,
        "log": log,
        "pending_combat_defense": pending,
        "combat_defense_required": True,
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
    pending = {
        "attacker_id": attacker_id,
        "defender_id": defender_id,
        "attacker_skill": atk_skill,
        "attacker_skill_value": atk_value,
        "weapon": weapon,
        "location": current_loc,
        "round": state_mgr.round_number,
        "attack_type": "shoot",
        "is_ranged": True,
        "point_blank": point_blank,
        "bonus_dice": bonus_dice,
        "allowed_defense_modes": ["dodge", "accept"],
    }
    state_mgr.set_pending_combat_defense(pending)
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
        "point_blank": point_blank,
        "bonus_dice": bonus_dice,
    }


def resolve_melee_combat_exchange(
    pending_combat_defense,
    defense_mode,
    *,
    char_mgr,
    dice_engine,
    state_mgr,
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
    elif outcome == "hit_attacker":
        hit = state_mgr.apply_melee_hit(
            attacker_id, defender_id,
            weapon=weapon,
            is_extreme=int(opposed.get("attacker_level") or 0) >= 4,
            dice_engine=dice_engine,
        )
        damage_results.append(hit)
        log_parts.append(
            f"→ 攻撃命中！ "
            f"（{hit.get('weapon_name')}: {hit.get('damage_detail', '')} → {hit.get('damage', 0)}点）"
            f" {def_name} HP {hit.get('old_hp')}→{hit.get('new_hp')}"
        )
        for ev in hit.get("events") or []:
            kp_notes.append(ev.get("instruction", ""))

    state_mgr.clear_pending_combat_defense()
    next_actor = state_mgr.next_turn()
    next_name = ""
    if next_actor and next_actor in char_mgr.characters:
        next_name = char_mgr.characters[next_actor]["profile"]["name"]
        log_parts.append(f"【手番】次は {next_name}（ラウンド {state_mgr.round_number}）")

    # 戦闘終了判定: 片陣営全滅
    living = [
        cid for cid in (state_mgr.combat_turn_queue or state_mgr.turn_order or [])
        if not state_mgr.is_combat_participant_incapacitated(cid)
    ]
    if len(living) <= 1:
        state_mgr.end_combat()
        log_parts.append("【戦闘終了】行動可能な戦闘参加者が残りわずかのため戦闘を終了。")

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
    }


def resolve_shoot_combat_exchange(
    pending_combat_defense,
    defense_mode,
    *,
    char_mgr,
    dice_engine,
    state_mgr,
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
        log_parts.append(
            f"→ 射撃命中！{impale_note} "
            f"（{hit.get('weapon_name')}: {hit.get('damage_detail', '')} → {hit.get('damage', 0)}点）"
            f" {def_name} HP {hit.get('old_hp')}→{hit.get('new_hp')}"
        )
        for ev in hit.get("events") or []:
            kp_notes.append(ev.get("instruction", ""))

    state_mgr.clear_pending_combat_defense()
    next_actor = state_mgr.next_turn()
    if next_actor and next_actor in char_mgr.characters:
        next_name = char_mgr.characters[next_actor]["profile"]["name"]
        log_parts.append(f"【手番】次は {next_name}（ラウンド {state_mgr.round_number}）")

    living = [
        cid for cid in (state_mgr.combat_turn_queue or state_mgr.turn_order or [])
        if not state_mgr.is_combat_participant_incapacitated(cid)
    ]
    if len(living) <= 1:
        state_mgr.end_combat()
        log_parts.append("【戦闘終了】行動可能な戦闘参加者が残りわずかのため戦闘を終了。")

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


def queue_npc_combat_attack(state, state_mgr, char_mgr, pl_id, current_loc):
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
    result = begin_combat_attack(
        actor, target,
        char_mgr=char_mgr,
        state_mgr=state_mgr,
        current_loc=current_loc,
    )
    if result.get("ok"):
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
            return _build_system_action_result(
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
        return _build_system_action_result(
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
        )

    scenario_mgr.location = current_loc
    payload = scenario_mgr.process_action(effective_action_id, target, fail_level)
    return _build_system_action_result(
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
    return _build_system_action_result(
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
    if pending_push_roll:
        pending_push_roll = dict(pending_push_roll)
        if pending_push_roll.get("target"):
            pending_push_roll["target"] = normalize_action_target(
                pending_push_roll["target"], scenario_mgr, current_loc, char_mgr=char_mgr,
            )
    new_pending_push_roll = pending_push_roll
    push_fail_penalty_instruction = ""
    effective_action_id = action_id
    pending_luck_burn = None
    in_combat = bool(state_mgr and getattr(state_mgr, "in_combat", False))
    mythos_san_check_pending = _is_san_check_pending(pending_san_check)

    if (
        str(action_id or "").lower() not in INVESTIGATION_ACTION_IDS
        and action_id != "attack"
        and action_id not in SHOOT_ACTION_IDS
        and not is_social_action(action_id, skill_name)
    ):
        skill_name = ""

    # 対人対象への search/inspect/push は talk へ強制変換（最終ガード）
    human_fix = rewrite_human_investigation_to_talk(action_id, target, char_mgr=char_mgr)
    if human_fix:
        sys_log += f"{human_fix.get('log') or HUMAN_INSPECT_REWRITE_LOG}\n"
        action_id = human_fix["action"]
        target = human_fix["target"]
        skill_name = human_fix.get("skill") or ""
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
        return _build_system_action_result(
            0,
            sys_log.strip(),
            {
                "blocked": True,
                "kp_instruction": access_block.get("kp_instruction", "アクセス条件が未達です。"),
            },
            action_id,
            None,
            current_loc=current_loc,
            scenario_mgr=scenario_mgr,
            roll_type="blocked",
            action_target=target,
        )

    # --------------------------------------------------
    # NPC 対話・交渉（説得／言いくるめ／威圧／魅惑／心理学）
    # --------------------------------------------------
    if is_social_action(action_id, skill_name):
        social_mgr = NPCSocialManager(char_mgr)
        npc_id = find_npc_id_by_target(char_mgr, target)
        if not npc_id:
            sys_log += "【対話】対象のNPCが特定できません。target に名前またはIDを指定してください。\n"
            return _build_system_action_result(
                0,
                sys_log.strip(),
                {
                    "blocked": True,
                    "kp_instruction": "対象NPCが不明です。正しい target を指定するよう促してください。",
                },
                action_id,
                None,
                current_loc=current_loc,
                scenario_mgr=scenario_mgr,
                roll_type="blocked",
                action_target=target,
            )
        # 幽霊NPC遮断: 現在地にいないNPCへの対話を拒否
        if scenario_mgr and hasattr(scenario_mgr, "is_npc_at_location"):
            if not scenario_mgr.is_npc_at_location(npc_id, current_loc):
                # エイリアス解決済みIDでもう一度確認
                present_ids = set(scenario_mgr.get_npcs_present(current_loc) or [])
                if npc_id not in present_ids and str(target) not in present_ids:
                    sys_log += (
                        f"【ロケーション不整合】`{npc_id}` は現在地（`{current_loc}`）にいません。"
                        "移動前にキューされた対話は破棄されました。"
                        "現在地のNPC／オブジェクトへ行動してください。\n"
                    )
                    return _build_system_action_result(
                        0,
                        sys_log.strip(),
                        {
                            "blocked": True,
                            "ghost_npc": True,
                            "kp_instruction": (
                                "移動前ロケーションのNPCとの対話は発生させない。"
                                "現在地の情景と有効な次アクションのみ描写せよ。"
                            ),
                        },
                        action_id,
                        None,
                        current_loc=current_loc,
                        scenario_mgr=scenario_mgr,
                        roll_type="blocked",
                        action_target=target,
                    )
        # ボストン・グローブ: 受付紹介前はアーティと会話・交渉できない
        flags = scenario_mgr.flags if scenario_mgr else {}
        if npc_id == "artie_wilmott" and not npc_is_available(char_mgr, npc_id, flags):
            sys_log += (
                "【対話ブロック】編集者アーティ・ウィルモットにはまだ会っていない。"
                "まず受付（`globe_receptionist`）で用件を伝え、呼び出してもらおう。\n"
            )
            return _build_system_action_result(
                0,
                sys_log.strip(),
                {
                    "blocked": True,
                    "kp_instruction": (
                        "アーティ本人はまだ姿を見せていない。受付の女性にコービット屋敷や古い記事の照会を頼み、"
                        "編集者を取り次いでもらうよう促せ。未紹介のままアーティと会話したことにしないこと。"
                    ),
                },
                action_id,
                None,
                current_loc=current_loc,
                scenario_mgr=scenario_mgr,
                roll_type="blocked",
                action_target=npc_id,
            )
        if is_casual_talk(action_id, skill_name):
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
        progress_log, progress_kp = _apply_social_progress_rules(
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
                social["kp_instruction"] = (
                    (social.get("kp_instruction") or "")
                    + "\n【進行】交渉成功でアクセス許可が更新された。"
                      "以後は同対象を『未許可』として拒絶しないこと。"
                )
        return _build_system_action_result(
            int(social.get("success_level") or 0),
            sys_log.strip(),
            {
                "kp_instruction": social.get("kp_instruction", ""),
                "npc_roleplay": social.get("npc_roleplay"),
                "social": social,
                "san_check": {"required": False},
            },
            action_id,
            None,
            current_loc=current_loc,
            scenario_mgr=scenario_mgr,
            roll_type="social_talk" if social.get("casual") else "social_negotiate",
            action_target=npc_id,
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
                state_mgr.start_combat(_combat_start_participants(pl_id, defender_id, pcs))
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
        sys_log += begin.get("log", "") + "\n"
        if begin.get("combat_defense_required"):
            return _build_system_action_result(
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
                state_mgr.start_combat(_combat_start_participants(pl_id, defender_id, pcs))
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

        if is_success:
            loss_val = dice_engine.roll_dice_str(_resolve_san_loss_dice(pending_san_check, True))
            sys_log += f"【SANチェック】1d100 ＞ {roll_val} ＞ 成功（現在値:{current_san}）。正気度が {loss_val} 減少した。\n"
        else:
            loss_val = dice_engine.roll_dice_str(_resolve_san_loss_dice(pending_san_check, False))
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

        return _build_system_action_result(
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

            skill_value = char_mgr.get_skill(pl_id, skill_name)
            dice_result = dice_engine.execute_push_roll(
                char_name,
                skill_name,
                skill_value,
                modifier=skill_modifier,
                bonus_dice=skill_bonus,
                penalty_dice=skill_penalty,
                required_difficulty=push_difficulty,
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
            if is_success_level(success_level) and skill_name:
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
        if not skill_name:
            skill_name = required_check.get("skill_name", "")
        skill_penalty = required_check.get("penalty_dice", 0)
        skill_bonus = required_check.get("bonus_dice", 0)
        skill_modifier = required_check.get("modifier", 0)

        skill_value = char_mgr.get_skill(pl_id, skill_name)
        dice_result = dice_engine.execute_skill_roll(
            char_name,
            skill_name,
            skill_value,
            modifier=skill_modifier,
            bonus_dice=skill_bonus,
            penalty_dice=skill_penalty,
            required_difficulty=action_difficulty,
        )
        if sys_log:
            sys_log += "\n"
        sys_log += dice_result.get("log", "")

        success_level, pending_luck_burn, push_from_fail = _apply_skill_roll_outcome(
            dice_result, char_mgr, pl_id, target, skill_name, action_id,
            skill_modifier, skill_bonus, skill_penalty,
            in_combat=in_combat,
            required_difficulty=action_difficulty,
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

    elif not dice_skipped and skill_name and action_id in INVESTIGATION_ACTION_IDS:
        skill_value = char_mgr.get_skill(pl_id, skill_name)
        dice_result = dice_engine.execute_skill_roll(
            char_name,
            skill_name,
            skill_value,
            modifier=skill_modifier,
            bonus_dice=skill_bonus,
            penalty_dice=skill_penalty,
            required_difficulty=action_difficulty,
        )
        if sys_log:
            sys_log += "\n"
        sys_log += dice_result.get("log", "")

        success_level, pending_luck_burn, push_from_fail = _apply_skill_roll_outcome(
            dice_result, char_mgr, pl_id, target, skill_name, action_id,
            skill_modifier, skill_bonus, skill_penalty,
            in_combat=in_combat,
            required_difficulty=action_difficulty,
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
        success_level = int(SuccessLevel.REGULAR_SUCCESS)
        if not sys_log:
            sys_log = "判定なし（自動成功）"
        roll_type = "none"

    # 幸運消費の判断待ち：シナリオ処理を保留して PL に委ねる
    if pending_luck_burn:
        return _build_system_action_result(
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

    # プッシュ決定待ち：シナリオ結果確定前に保留（幸運と同様）
    if (
        new_pending_push_roll
        and new_pending_push_roll.get("decision_pending", True)
        and action_id != "push_roll"
        and not dice_skipped
        and is_failure_level(success_level)
    ):
        return _build_system_action_result(
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

    scenario_mgr.location = current_loc
    if not dice_skipped and payload is None and not (action_id == "push_roll" and not pending_push_roll):
        payload = scenario_mgr.process_action(effective_action_id, target, success_level)

    if payload and state_mgr:
        active = getattr(char_mgr, "active_pc_list", None) or [pl_id]
        sys_log = _apply_combat_payload_effects(
            payload, state_mgr, char_mgr, pl_id, sys_log, active_pcs=active,
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
    # move 成功時: 旧ロケ宛未処理キューを必ず破棄（呼び出し側漏れ防止の SSOT）
    if game_state is not None:
        apply_location_change_side_effects(
            game_state, result, scenario_mgr=scenario_mgr, char_mgr=char_mgr,
        )
    return result


def apply_location_change_side_effects(state, result, *, scenario_mgr=None, char_mgr=None):
    """
    location_changed / new_location 時の共通後処理。
    current_loc 更新 + 未処理アクション破棄 + ループ警告。
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
    if scenario_mgr and getattr(scenario_mgr, "location", None) != new_loc:
        # scenario 側が先行更新済みなら追従のみ
        pass

    invalidate_pending_actions_after_location_change(
        state,
        old_loc=old_loc,
        new_loc=new_loc,
        scenario_mgr=scenario_mgr,
        char_mgr=char_mgr,
    )
    _maybe_inject_location_loop_warning(state, scenario_mgr)
    return True


# ==========================================
# 6. タイムライン駆動型フリーチャットシステム
# ==========================================
MAX_AUTONOMOUS_ITERATIONS = 25
MAX_CONSECUTIVE_SAME_SPEAKER = 2
MAX_CHAT_ROUNDS_WITHOUT_PROGRESS = FORCE_IC_ACTION_CHAT_ROUNDS
MAX_TIMELINE_CHAIN = 8

USER_STOP_LOG_TEXT = "[システム] ユーザーによりセッションが一時停止されました。"

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
    chat_rounds >= 3 または stagnation streak > 4 で発火。
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
        },
    })

    result = process_system_action(
        pl_id, char_name, action_id, dest, forced.get("skill") or "",
        current_loc, char_mgr, dice_engine, scenario_mgr,
        state_mgr=state_mgr,
        game_state=state,
    )
    append_system_log_entry(
        state["all_events_log"],
        current_loc,
        result.get("log", ""),
        action_id=action_id,
        target=dest,
        roll_type=result.get("roll_type", action_id),
    )
    # process_system_action(game_state=) で current_loc / キュー破棄済み。保険で再同期。
    apply_location_change_side_effects(
        state, result, scenario_mgr=scenario_mgr, char_mgr=char_mgr,
    )
    if not result.get("new_location") and scenario_mgr and getattr(scenario_mgr, "location", None):
        if action_id != "move":
            state["current_loc"] = scenario_mgr.location

    state["last_pl_action"] = forced
    state["last_system_result"] = result
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


def determine_timeline_next_step(state, char_name, scenario_mgr, state_mgr=None, char_mgr=None):
    """
    タイムライン末尾と内部状態から次に実行すべき処理を決定する。

    優先順位:
      1. PENDING_ACTIONS（SAN / 戦闘防衛 / 幸運消費 / プッシュ / PL相談）
      2. System Process（未解決の PL 行動）
      3. KP Turn（未描写のシステム結果）
      4. 戦闘 NPC 手番 / 戦闘中 PC 手番
      5. PL Turn（ラウンドロビン）
    """
    if is_game_cleared(scenario_mgr):
        return "game_clear"

    ensure_multi_pl_state(state, char_mgr)
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
    if kind in ("empty", "session_meta"):
        return "kp_opening"
    if kind == "system_result":
        return "kp_narrate"
    if should_arm_room_entry_san(state, char_name, scenario_mgr):
        return "room_entry_san_arm"
    if kind == "kp_speech":
        # KP描写後の手番ローテは step_pl_turn 側で _advance_pc_after_kp を処理
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
            self.chat_rounds_without_action = 0

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
    """3往復進展なし時にシステムが割り込む。"""
    default_msg = (
        "[システム] 探索が停滞しています。別の対象への行動、移動、"
        "または状況の変化を検討してください。"
    )
    state["all_events_log"].append({
        "channel": "OOC",
        "location": "all",
        "secret_to": None,
        "text": message or default_msg,
        "meta": {"stagnation_interrupt": True},
    })
    scenario_mgr.stagnation_counter = STAGNATION_PAUSE_THRESHOLD
    if state_mgr and hasattr(state_mgr, "mark_stagnation_intervened"):
        state_mgr.mark_stagnation_intervened()
    elif state_mgr is None:
        # state に紐づく tracker が無い場合でも、ヒントがあれば介入済み扱いに近づける
        pass
    _maybe_set_introduction_stagnation_hint(state, scenario_mgr, state_mgr)


def _maybe_inject_location_loop_warning(state, scenario_mgr):
    """地下室↔廊下の往復ループを検知して PL に警告する。"""
    flags = scenario_mgr.flags
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
    state["all_events_log"].append({
        "channel": "OOC",
        "location": "all",
        "secret_to": None,
        "text": warning,
    })


def begin_autonomous_runtime(state):
    """自律巡航のランタイム状態を開始用に正規化する。"""
    state["is_running"] = True
    state["stop_requested"] = False
    state["autonomous_paused"] = False
    state["autonomous_pause_reason"] = None


def finalize_autonomous_pause(state, pause_reason):
    """自律巡航の一時停止状態を一貫して確定する。"""
    state["is_running"] = False
    state["stop_requested"] = False
    state["autonomous_paused"] = True
    state["autonomous_pause_reason"] = pause_reason


def normalize_loaded_runtime_state(app_state, *, enforce_half_turn_pause=True):
    """セーブデータ上の矛盾したランタイムフラグを修復する。"""
    logs = app_state.get("all_events_log") or []
    has_user_stop_log = any(entry.get("text") == USER_STOP_LOG_TEXT for entry in logs)

    if app_state.get("stop_requested") or has_user_stop_log:
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

    # 行動未確定（last_pl_action のみ）で実行中フラグが立っているセーブを安全側へ正規化
    last_action = app_state.get("last_pl_action") or {}
    pending_kind = str((last_action or {}).get("action") or "").lower()
    has_half_turn = bool(
        pending_kind in ACTIONS_NEEDING_SYSTEM
        and not app_state.get("last_system_result")
    )
    if enforce_half_turn_pause and app_state.get("is_running") and has_half_turn:
        app_state["is_running"] = False
        app_state["autonomous_paused"] = True
        app_state["autonomous_pause_reason"] = (
            app_state.get("autonomous_pause_reason") or "awaiting_system_process"
        )

    # ロード時に既に OOC 膠着閾値を超えていれば強制 IC フェーズを復元
    if is_force_ic_action_phase(app_state):
        app_state["force_ic_action"] = True
        if not app_state.get("stagnation_pl_hint"):
            app_state["stagnation_pl_hint"] = OOC_LOOP_FORCE_ACTION_WARNING

    app_state = validate_and_sync_pause_state(app_state)

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
    return app_state


def reset_stagnation_state_on_progress(state, scenario_mgr=None, state_mgr=None):
    """進展イベント確定時に、膠着ヒント/カウンタを即時クリアする。"""
    if not state:
        return
    state["stagnation_pl_hint"] = None
    state["stagnation_kp_nudge"] = None
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
            state_mgr.reset_stagnation_tracker(state.get("current_loc"), flags)
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
    }
    normalized = normalize_loaded_runtime_state(
        wrapper,
        enforce_half_turn_pause=False,
    )
    session_state.is_running = normalized["is_running"]
    session_state.stop_requested = normalized["stop_requested"]
    session_state.autonomous_paused = normalized["autonomous_paused"]
    session_state.autonomous_pause_reason = normalized.get("autonomous_pause_reason")


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


def step_kp_eval(state, scenario_mgr, system_entry=None):
    current_loc = state["current_loc"]
    action = state.get("last_pl_action")
    result = dict(state.get("last_system_result") or {})
    if _is_san_check_pending(state.get("pending_san_check")):
        result["san_check"] = state["pending_san_check"]
    else:
        result["san_check"] = {"required": False}
    loc_info = scenario_mgr.get_location_info(current_loc)
    kp_data = call_kp_api(
        generate_kp_prompt(loc_info, action, result, scenario_mgr=scenario_mgr, state=state)
    )
    append_kp_response_to_logs(kp_data, current_loc, state["all_events_log"])
    mark_system_entry_narrated(system_entry or find_last_unnarrated_system_entry(state["all_events_log"]))
    mark_all_unnarrated_system_entries(state["all_events_log"])
    state["last_pl_action"] = None
    state["last_system_result"] = None
    state["stagnation_kp_nudge"] = None
    # 探索時は次 PC へ手番を回すフラグ
    state["_advance_pc_after_kp"] = True


def step_kp_narrate(state, scenario_mgr):
    """未描写のシステムログを KP がナレーションする。"""
    system_entry = find_last_unnarrated_system_entry(state.get("all_events_log", []))
    if not system_entry:
        return
    step_kp_eval(state, scenario_mgr, system_entry=system_entry)


def _action_data_from_timeline(state, scenario_mgr, char_name, char_mgr=None):
    """タイムライン上の未処理 PL 行動、または last_pl_action から action_data を取得する。"""
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
        }, scenario_mgr, current_loc, char_mgr=char_mgr)
        meta["system_processed"] = True
        entry["meta"] = meta
        state["last_pl_action"] = action_data
        return action_data
    return normalize_pc_action(
        state.get("last_pl_action") or {}, scenario_mgr, current_loc, char_mgr=char_mgr,
    )


def step_pl_turn(state, char_mgr, scenario_mgr, pl_id, char_name, state_mgr=None):
    current_loc = state["current_loc"]
    discussion = bool(state.get("pl_discussion_mode"))

    if not prepare_active_pc_for_pl_turn(state, char_mgr, state_mgr):
        state["all_events_log"].append({
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": "[システム] 行動可能な探索者がいません。",
        })
        return {"action": "wait", "target": "", "skill": ""}

    # KP描写後の探索手番ローテ
    if state.pop("_advance_pc_after_kp", False) and not (state_mgr and state_mgr.in_combat):
        advance_exploration_turn(state, char_mgr, state_mgr)

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

    ic_logs, ooc_logs = get_filtered_logs(pl_id, current_loc, state["all_events_log"])
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
        party_note = f"\n【同行探索者】{', '.join(others)}\n"

    force_ic = (not discussion) and ensure_force_ic_action_phase(
        state, state_mgr=state_mgr, guard=None,
    )
    # guard 未接続時も autonomous_guard / streak から判定
    if not force_ic and not discussion:
        force_ic = is_force_ic_action_phase(state, state_mgr=state_mgr)
        if force_ic:
            ensure_force_ic_action_phase(state, state_mgr=state_mgr)

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
    )
    if party_note:
        pl_prompt = party_note + pl_prompt
    if discussion:
        pl_prompt = (
            "【作戦会議フェーズ】ダイス判定なし。仲間とOOCで相談し、合意後に調査へ移ること。"
            "action は wait。\n"
        ) + pl_prompt
    elif force_ic:
        pl_prompt = f"{OOC_LOOP_FORCE_ACTION_WARNING}\n" + pl_prompt

    ai_data = call_pl_api(
        pl_prompt,
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
    )

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
        if (
            not discussion
            and not san_locked
            and count >= 2
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
        )
        forced_by_retry = _maybe_force_breakout_for_retry_loop(pc_action)
        if forced_by_retry:
            return forced_by_retry

    # 強制 IC フェーズなのに wait/無駄 talk → 再プロンプトで有効行動を要求
    force_retries = 0
    while (
        force_ic
        and not discussion
        and not san_locked
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

    if force_ic and not is_nonprogress_pl_action(
        pc_action, state.get("pending_san_check"),
        scenario_mgr=scenario_mgr, current_loc=current_loc, char_mgr=char_mgr,
    ):
        clear_force_ic_action_phase(state)

    state["last_pl_action"] = pc_action
    if not pc_action.get("needs_pl_retry"):
        state["validation_retry_state"] = {}
    if not force_ic:
        state["stagnation_pl_hint"] = None
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


def step_free_chat_exchange(state, char_mgr, scenario_mgr, pl_id, char_name, guard=None, state_mgr=None):
    """KP/PL OOC 末尾に対し PL が応答する。KP同一サイクル追撃は行わない。"""
    before_len = len(state.get("all_events_log", []))
    pc_action = step_pl_turn(
        state, char_mgr, scenario_mgr, pl_id, char_name, state_mgr=state_mgr,
    )
    if guard:
        guard.record_pl_action(
            pc_action, state.get("pending_san_check"),
            scenario_mgr=scenario_mgr,
            current_loc=state.get("current_loc"),
            char_mgr=char_mgr,
        )
    after_len = len(state.get("all_events_log", []))
    actor_label = f"PL:{state.get('pl_id', pl_id)}"
    if after_len == before_len:
        state["all_events_log"].append({
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": "[システム] PLは一拍置いて状況を見極めている（時間経過）。",
        })
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
        target="",
        roll_type=san_result.get("roll_type", "san_check"),
    )
    state["last_system_result"] = san_result
    return san_result


def step_system_process(state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name):
    current_loc = state["current_loc"]
    state["partial_system_log"] = None
    state = normalize_loaded_runtime_state(state, enforce_half_turn_pause=False)
    ensure_multi_pl_state(state, char_mgr)
    normalize_game_action_targets(state, scenario_mgr, current_loc, char_mgr=char_mgr)
    action_data = _action_data_from_timeline(state, scenario_mgr, char_name, char_mgr=char_mgr)
    pl_id = state.get("pl_id") or pl_id
    char_name = state.get("char_name") or char_name
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

    if result.get("luck_decision_required"):
        state["pending_luck_burn"] = result.get("pending_luck_burn")
        state["partial_system_log"] = result.get("partial_log", result.get("log", ""))
        state["push_decision_required"] = False
        sync_timeline_pending_phase(state)
        append_system_log_entry(
            state["all_events_log"], current_loc, result["log"],
            action_id=result.get("action_id", action_data.get("action", "")),
            target=result.get("target", action_data.get("target", "")),
            roll_type=result.get("roll_type", ""),
        )
        return result

    if result.get("combat_defense_required"):
        pending = result.get("pending_combat_defense")
        state["pending_combat_defense"] = pending
        if state_mgr:
            state_mgr.set_pending_combat_defense(pending)
        state["partial_system_log"] = result.get("partial_log", result.get("log", ""))
        sync_timeline_pending_phase(state)
        append_system_log_entry(
            state["all_events_log"], current_loc, result["log"],
            action_id=result.get("action_id", action_data.get("action", "")),
            target=result.get("target", action_data.get("target", "")),
            roll_type=result.get("roll_type", ""),
        )
        state["last_system_result"] = result
        return result

    if result.get("push_decision_required"):
        state["pending_push_roll"] = result.get("pending_push_roll")
        state["partial_system_log"] = result.get("partial_log", result.get("log", ""))
        state["push_decision_required"] = True
        state["pending_luck_burn"] = None
        sync_timeline_pending_phase(state)
        append_system_log_entry(
            state["all_events_log"], current_loc, result["log"],
            action_id=result.get("action_id", action_data.get("action", "")),
            target=result.get("target", action_data.get("target", "")),
            roll_type=result.get("roll_type", ""),
        )
        return result

    apply_system_roll_state_updates(state, result, had_san_pending=had_san_pending)

    append_system_log_entry(
        state["all_events_log"], current_loc, result["log"],
        action_id=result.get("action_id", action_data.get("action", "")),
        target=result.get("target", action_data.get("target", "")),
        roll_type=result.get("roll_type", ""),
    )

    result = _maybe_auto_resolve_san_check_after_action(
        state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name, result,
    )
    state["last_system_result"] = result
    if result.get("stagnation_progress"):
        reset_stagnation_state_on_progress(state, scenario_mgr=scenario_mgr, state_mgr=state_mgr)

    # process_system_action(game_state=) で移動時キュー破棄済み。保険で再同期。
    apply_location_change_side_effects(
        state, result, scenario_mgr=scenario_mgr, char_mgr=char_mgr,
    )

    return result


def step_luck_decision(state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name):
    pending = state.get("pending_luck_burn")
    if not pending:
        return

    partial_log = state.get("partial_system_log", "")
    current_loc = state["current_loc"]
    ic_logs, ooc_logs = get_filtered_logs(pl_id, current_loc, state["all_events_log"])
    pl_prompt = generate_pl_luck_prompt(
        char_name, pending, char_mgr, pl_id, ic_logs, ooc_logs,
        scenario_mgr=scenario_mgr,
        all_events_log=state.get("all_events_log"),
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
        state["pending_push_roll"] = result.get("pending_push_roll")
        state["partial_system_log"] = result.get("partial_log", result.get("log", ""))
        state["push_decision_required"] = True
        sync_timeline_pending_phase(state)
        append_system_log_entry(
            state["all_events_log"], current_loc, result["log"],
            action_id=result.get("action_id", pending.get("original_action", "")),
            target=result.get("target", pending.get("target", "")),
            roll_type=result.get("roll_type", "skill"),
        )
        state["last_system_result"] = result
        return result

    state["partial_system_log"] = None
    state["push_decision_required"] = False

    had_san_pending = _is_san_check_pending(state.get("pending_san_check"))
    apply_system_roll_state_updates(state, result, had_san_pending=had_san_pending)

    append_system_log_entry(
        state["all_events_log"], current_loc, result["log"],
        action_id=result.get("action_id", pending.get("original_action", "")),
        target=result.get("target", pending.get("target", "")),
        roll_type=result.get("roll_type", "skill"),
    )

    result = _maybe_auto_resolve_san_check_after_action(
        state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name, result,
    )
    state["last_system_result"] = result
    if result.get("stagnation_progress"):
        reset_stagnation_state_on_progress(state, scenario_mgr=scenario_mgr, state_mgr=state_mgr)
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
        apply_system_roll_state_updates(state, result)
        append_system_log_entry(
            state["all_events_log"], state["current_loc"], result["log"],
            action_id=result.get("action_id", pending.get("original_action", "")),
            target=result.get("target", pending.get("target", "")),
            roll_type=result.get("roll_type", "skill"),
        )
        result = _maybe_auto_resolve_san_check_after_action(
            state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name, result,
        )
        state["last_system_result"] = result
        if result.get("stagnation_progress"):
            reset_stagnation_state_on_progress(state, scenario_mgr=scenario_mgr, state_mgr=state_mgr)
        sync_timeline_pending_phase(state)
        if result.get("new_location"):
            apply_location_change_side_effects(
                state, result, scenario_mgr=scenario_mgr, char_mgr=char_mgr,
            )
            _maybe_inject_location_loop_warning(state, scenario_mgr)
        return result

    partial_log = state.get("partial_system_log", "")
    current_loc = state["current_loc"]
    ic_logs, ooc_logs = get_filtered_logs(pl_id, current_loc, state["all_events_log"])
    pl_prompt = generate_pl_push_prompt(
        char_name, pending, char_mgr, pl_id, ic_logs, ooc_logs,
        scenario_mgr=scenario_mgr,
        all_events_log=state.get("all_events_log"),
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
        apply_system_roll_state_updates(state, result, had_san_pending=had_san_pending)
        append_system_log_entry(
            state["all_events_log"], current_loc, result["log"],
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
        apply_system_roll_state_updates(state, result)
        append_system_log_entry(
            state["all_events_log"], current_loc, result["log"],
            action_id=result.get("action_id", pending.get("original_action", "")),
            target=result.get("target", pending.get("target", "")),
            roll_type=result.get("roll_type", "skill"),
        )
        result = _maybe_auto_resolve_san_check_after_action(
            state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name, result,
        )

    state["last_system_result"] = result
    if result.get("stagnation_progress"):
        reset_stagnation_state_on_progress(state, scenario_mgr=scenario_mgr, state_mgr=state_mgr)
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
        )
        action_id = "attack"
        roll_type = "combat_opposed"
        default_kp = "戦闘の攻防結果を描写してください。"

    state["pending_combat_defense"] = None
    if state_mgr:
        state_mgr.clear_pending_combat_defense()
    state["partial_system_log"] = None
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
    }
    append_system_log_entry(
        state["all_events_log"], current_loc, result["log"],
        action_id=action_id,
        target=pending.get("defender_id", ""),
        roll_type=roll_type,
    )
    state["last_system_result"] = result
    if result.get("stagnation_progress"):
        reset_stagnation_state_on_progress(state, scenario_mgr=scenario_mgr, state_mgr=state_mgr)
    return result


def step_combat_npc_act(state, char_mgr, dice_engine, scenario_mgr, state_mgr, pl_id, char_name):
    """戦闘中の NPC 手番: PL への攻撃を自動宣言し防衛保留へ進む。"""
    current_loc = state.get("current_loc", "")
    result = queue_npc_combat_attack(state, state_mgr, char_mgr, pl_id, current_loc)
    if not result:
        return None
    if result.get("ended"):
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
            },
        }
    else:
        prefix = format_pc_log_prefix(char_mgr, pc_id, role="PL") if pc_id and char_mgr else f"{char_name}(PL)"
        entry = {
            "channel": "OOC",
            "location": "all",
            "secret_to": None,
            "text": f"{prefix}: {text}",
            "meta": {"human": True, "pc_id": pc_id},
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
        step_kp_narrate(state, scenario_mgr)
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
        _, actor = step_free_chat_exchange(
            state, char_mgr, scenario_mgr, pl_id, char_name,
            guard=guard, state_mgr=state_mgr,
        )
        return None, actor
    if step == "pl_speak":
        pc_action = step_pl_turn(
            state, char_mgr, scenario_mgr, pl_id, char_name, state_mgr=state_mgr,
        )
        if guard:
            guard.record_pl_action(
                pc_action, state.get("pending_san_check"),
                scenario_mgr=scenario_mgr,
                current_loc=state.get("current_loc"),
                char_mgr=char_mgr,
            )
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
            inject_stagnation_interrupt(state, scenario_mgr, char_name, state_mgr=state_mgr)
            pause_reason = "speaker_limit"
            state["autonomous_guard"] = guard.to_state()
            if ui_callback:
                ui_callback(state)
            if autosave_callback:
                autosave_callback(state)
            break

        if guard.should_break_stagnation() or guard.should_break_system_stagnation(scenario_mgr):
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
        if max_iterations > 1:
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
        "autonomous_guard": session_state.get("autonomous_guard"),
        "autonomous_step_count": session_state.get("autonomous_step_count", 0),
        "is_running": session_state.get("is_running", False),
        "stop_requested": session_state.get("stop_requested", False),
        "rp_eval_unit_ids": session_state.get("rp_eval_unit_ids", []),
        "rp_eval_last_summary": session_state.get("rp_eval_last_summary"),
        "rp_session_id": session_state.get("rp_session_id"),
        "rp_library_pending": session_state.get("rp_library_pending", []),
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
    session_state.autonomous_guard = state.get("autonomous_guard")
    session_state.autonomous_step_count = state.get("autonomous_step_count", 0)
    session_state.is_running = state.get("is_running", False)
    session_state.stop_requested = state.get("stop_requested", False)
    session_state.rp_eval_unit_ids = state.get("rp_eval_unit_ids", [])
    session_state.rp_eval_last_summary = state.get("rp_eval_last_summary")
    session_state.rp_session_id = state.get("rp_session_id")
    session_state.rp_library_pending = state.get("rp_library_pending", [])