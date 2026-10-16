"""
TRPG セッションログの RP 品質を Judge LLM で評価し、良質ログをデータセット化する。

タスク7: Decision Case の構造化抽出と、完走率に依存しない 6 軸メトリクス評価。
タスク8 の Dynamic Few-Shot 注入は DecisionCaseRAG / main 側が担当する。
"""
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone

from DecisionCaseStore import (
    DecisionCaseStore,
    build_decision_case,
    normalize_decision_case,
)
from RPLibraryStore import JUDGE_TAG_PROMPT_BLOCK, sanitize_rp_tags

DEFAULT_SCORE_THRESHOLD = 7
DEFAULT_INSANE_SKIPPED_PATH = os.path.join("datasets", "insane_rp_skipped.json")
DEFAULT_SESSION_METRICS_PATH = os.path.join("datasets", "session_metrics.jsonl")
DEFAULT_DECISION_CASES_PATH = os.path.join("datasets", "decision_cases.jsonl")

# セッション結果の分類（ゲーム内結果とシステム障害を分離）
OUTCOME_GAME_CLEAR = "game_clear"
OUTCOME_DEFEAT_SAN = "defeat_san"
OUTCOME_DEFEAT_WIPE = "defeat_party_wipe"
OUTCOME_RETREAT = "retreat"
OUTCOME_STAGNATION = "stagnation"
OUTCOME_USER_STOP = "user_stop"
OUTCOME_MAX_ITERATIONS = "max_iterations"
OUTCOME_EMPTY_TICK = "empty_tick"
OUTCOME_ERROR = "error"
OUTCOME_UNKNOWN = "unknown"

GAME_OUTCOMES = frozenset({
    OUTCOME_GAME_CLEAR,
    OUTCOME_DEFEAT_SAN,
    OUTCOME_DEFEAT_WIPE,
    OUTCOME_RETREAT,
})
OPERATIONAL_FAILURES = frozenset({
    OUTCOME_ERROR,
    OUTCOME_EMPTY_TICK,
})
SOFT_STOPS = frozenset({
    OUTCOME_STAGNATION,
    OUTCOME_USER_STOP,
    OUTCOME_MAX_ITERATIONS,
})

_DEFEAT_SAN_MARKERS = (
    "SANが0",
    "SAN が 0",
    "SAN=0",
    "SAN：0",
    "永久的発狂",
    "【永久的発狂】",
)
_DEFEAT_WIPE_MARKERS = (
    "全滅",
    "パーティ全滅",
    "探索者全滅",
    "全員が戦闘不能",
    "全員行動不能",
)
_RETREAT_MARKERS = (
    "撤退",
    "退避",
    "探索を打ち切",
    "調査を中断",
)

JUDGE_RESPONSE_SCHEMA = """{
  "total_score": 8,
  "reason": "文字列で簡潔に評価理由を記述",
  "rp_tags": ["tone:cowardly", "expr:flair", "context:investigating"]
}"""

JUDGE_USER_PROMPT_TEMPLATE = """以下のプレイヤー行動ログを評価してください。

【キャラクター設定】
職業: {occupation}
年齢: {age}
性別: {gender}
性格メモ: {memo}

【プレイヤーのメタ思考（OOC）】
{ooc}

【キャラクターの発言・行動（IC）】
{pc_msg}

【システム判定（技能・成否）】
{action_context}
"""

_INSANITY_LOG_MARKERS = (
    "【一時的発狂】",
    "【一時的発狂・強制発症】",
    "【不定の発狂】",
    "【永久的発狂】",
    "一時的狂気",
    "永久的発狂",
)

_SKIP_ACTION_IDS = frozenset({"wait", "none", "", "san_check"})
_SKIP_ROLL_TYPES = frozenset({"san_check", "blocked"})


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _extract_json_object(text):
    text = (text or "").strip()
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


def _strip_speaker_prefix(text, prefix):
    text = str(text or "").strip()
    if text.startswith(prefix):
        return text[len(prefix):].strip()
    return text


def _log_indicates_insanity_onset(text):
    return any(marker in str(text or "") for marker in _INSANITY_LOG_MARKERS)


def _parse_roll_outcome(system_text):
    text = str(system_text or "")
    if "大成功" in text or "クリティカル" in text:
        return "critical_success"
    if "【成功】" in text or " ＞ 成功" in text or "成功（" in text:
        return "success"
    if "失敗" in text:
        return "failure"
    if "【自動成功】" in text or "判定なし" in text:
        return "auto_success"
    return "unknown"


def _parse_skill_from_system(system_text):
    match = re.search(r"【技能:([^】]+)】", str(system_text or ""))
    return match.group(1).strip() if match else ""


def normalize_judge_result(parsed, *, score_threshold=DEFAULT_SCORE_THRESHOLD):
    """Judge LLM の JSON 応答を正規化する。"""
    data = parsed if isinstance(parsed, dict) else {}
    score = int(data.get("total_score", 0) or 0)
    tags = sanitize_rp_tags(data.get("rp_tags") or data.get("tags"))
    if score < score_threshold:
        tags = []
    return {
        "total_score": score,
        "reason": str(data.get("reason", "") or "").strip(),
        "tags": tags,
        "rp_tags": tags,
    }


def build_character_profile(char_mgr, pl_id):
    """キャラクタープロフィール dict を組み立てる。"""
    char = (char_mgr.characters.get(pl_id) if char_mgr else None) or {}
    profile = char.get("profile", {})
    return {
        "name": profile.get("name", ""),
        "occupation": profile.get("occupation", ""),
        "age": profile.get("age", ""),
        "gender": profile.get("gender", ""),
        "memo": char.get("memo", ""),
    }


def extract_rp_turn_units(all_events_log, char_name, *, insane_skip=True, default_turn=0):
    """
    all_events_log から RP 評価用ターン単位（OOC + PC IC + システム判定）を抽出する。

    insane_skip=True のとき、発狂ログ以降のターンは insane_units へ分類し通常評価から除外する。
    """
    normal_units = []
    insane_units = []
    insane_active = False
    pending_oocs = []
    pending_pc = None
    turn_counter = int(default_turn or 0)

    pl_prefix = f"{char_name}(PL):"
    pc_prefix = f"{char_name}(PC):"

    for idx, entry in enumerate(all_events_log or []):
        text = str(entry.get("text", "") or "")
        channel = entry.get("channel", "")

        if _log_indicates_insanity_onset(text):
            insane_active = True
            pending_oocs = []
            pending_pc = None

        if insane_active and insane_skip:
            if channel == "OOC" and pl_prefix in text:
                pending_oocs.append(_strip_speaker_prefix(text, pl_prefix))
            elif channel == "IC" and pc_prefix in text:
                meta = entry.get("meta") or {}
                if meta.get("turn") is not None:
                    turn_counter = int(meta.get("turn") or turn_counter)
                action_id = str(meta.get("action_id", "") or "").lower()
                if action_id in _SKIP_ACTION_IDS and not meta.get("needs_system"):
                    continue
                pending_pc = {
                    "text": _strip_speaker_prefix(text, pc_prefix),
                    "meta": meta,
                    "log_index": idx,
                }
            elif channel == "IC" and text.startswith("システム:") and pending_pc:
                meta = entry.get("meta") or {}
                roll_type = str(meta.get("roll_type", "") or "").lower()
                if roll_type in _SKIP_ROLL_TYPES:
                    pending_pc = None
                    pending_oocs = []
                    continue
                system_body = text.replace("システム:", "", 1).strip()
                insane_units.append(_make_unit(
                    pending_oocs,
                    pending_pc,
                    system_body,
                    meta,
                    char_name,
                    classification="insane_period",
                    turn=turn_counter,
                ))
                pending_oocs = []
                pending_pc = None
            continue

        if channel == "OOC" and pl_prefix in text:
            pending_oocs.append(_strip_speaker_prefix(text, pl_prefix))
            continue

        if channel == "IC" and pc_prefix in text:
            meta = entry.get("meta") or {}
            if meta.get("turn") is not None:
                turn_counter = int(meta.get("turn") or turn_counter)
            action_id = str(meta.get("action_id", "") or "").lower()
            if action_id in _SKIP_ACTION_IDS and not meta.get("needs_system"):
                continue
            pending_pc = {
                "text": _strip_speaker_prefix(text, pc_prefix),
                "meta": meta,
                "log_index": idx,
            }
            continue

        if channel == "IC" and text.startswith("システム:") and pending_pc:
            meta = entry.get("meta") or {}
            roll_type = str(meta.get("roll_type", "") or "").lower()
            if roll_type in _SKIP_ROLL_TYPES:
                pending_pc = None
                pending_oocs = []
                continue

            pc_meta = pending_pc.get("meta") or {}
            pc_action = str(pc_meta.get("action_id", "") or "").lower()
            sys_action = str(meta.get("action_id", "") or "").lower()
            if sys_action and pc_action and sys_action != pc_action:
                continue

            system_body = text.replace("システム:", "", 1).strip()
            unit = _make_unit(
                pending_oocs,
                pending_pc,
                system_body,
                meta,
                char_name,
                classification="normal",
                turn=turn_counter,
            )
            normal_units.append(unit)
            pending_oocs = []
            pending_pc = None

    return normal_units, insane_units


def _make_unit(pending_oocs, pc_entry, system_text, system_meta, char_name, classification, turn=0):
    pc_meta = pc_entry.get("meta") or {}
    sys_meta = system_meta or {}
    action_id = pc_meta.get("action_id") or sys_meta.get("action_id") or ""
    target = pc_meta.get("target") or sys_meta.get("target") or ""
    skill = pc_meta.get("skill") or _parse_skill_from_system(system_text or "")
    roll_outcome = _parse_roll_outcome(system_text or "")

    unit_id = hashlib.sha256(
        "|".join([
            classification,
            "\n".join(pending_oocs),
            pc_entry.get("text", ""),
            system_text or "",
        ]).encode("utf-8"),
    ).hexdigest()[:20]

    return {
        "unit_id": unit_id,
        "classification": classification,
        "turn": int(turn or 0),
        "log_index": pc_entry.get("log_index"),
        "ooc": "\n".join(pending_oocs).strip(),
        "pc_msg": pc_entry.get("text", "").strip(),
        "action_context": {
            "action_id": action_id,
            "target": target,
            "skill": skill,
            "roll_outcome": roll_outcome,
            "roll_type": sys_meta.get("roll_type", ""),
            "system_log": (system_text or "").strip(),
        },
    }


class LogEvaluator:
    """RP ログの抽出・Judge 評価・データセット永続化。"""

    def __init__(
        self,
        insane_skipped_path=None,
        score_threshold=None,
        call_judge=None,
        library_store=None,
    ):
        self.insane_skipped_path = insane_skipped_path or DEFAULT_INSANE_SKIPPED_PATH
        self.score_threshold = (
            score_threshold if score_threshold is not None else DEFAULT_SCORE_THRESHOLD
        )
        self.call_judge = call_judge or self._default_call_judge
        self.library_store = library_store
        self.last_evaluated_hashes = []
        self.last_summary = {}

    def _default_call_judge(self, user_prompt):
        from main import _call_chat_completion, get_llm_config

        cfg = get_llm_config()
        judge_model = cfg.get("judge_model") or cfg.get("kp_model")
        system_prompt = (
            "あなたはTRPGの優れたリプレイ評価者（Judge AI）です。"
            "提示されたプレイヤーの行動ログ（通常時・発狂時を問わず）を読み、"
            "ロールプレイ（RP）の質を10点満点で客観的に採点してください。\n\n"
            "【評価基準】\n"
            "1. キャラクター設定（プロフィール、職業、性格メモ）が、セリフや行動に反映されているか？（3点）\n"
            "2. PLのメタ思考（OOC）と、実際のPCのセリフ（IC）の繋がりが自然か？（3点）\n"
            "3. ダイスの結果（成功・失敗）に対して、キャラクターらしいリアクションや描写の上書きができているか？（2点）\n"
            "4. 単調なテンプレ発言（「〜を調べます」だけなど）になっておらず、読み物として面白いか？（2点）\n"
            "※発狂状態のRPは、症状の一貫性・没入感も加点要素として評価してください。\n\n"
            + JUDGE_TAG_PROMPT_BLOCK.strip()
            + "\n\n【出力フォーマット】\n"
            "必ず、以下のJSON構造のみで返答してください。解説テキストは一切含めないでください。\n"
            + JUDGE_RESPONSE_SCHEMA
        )
        finalized = user_prompt.rstrip() + "\n\n{"
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": finalized},
        ]
        response_text = _call_chat_completion(
            messages,
            model=judge_model,
            temperature=0.2,
            max_retries=2,
            json_mode=True,
        )
        parsed = json.loads(_extract_json_object(response_text))
        return normalize_judge_result(parsed, score_threshold=self.score_threshold)

    def build_judge_prompt(self, unit, character_profile):
        action_ctx = unit.get("action_context") or {}
        context_lines = [
            f"行動: {action_ctx.get('action_id', '')} / 対象: {action_ctx.get('target', '')}",
            f"技能: {action_ctx.get('skill', '') or '（なし）'}",
            f"判定結果: {action_ctx.get('roll_outcome', 'unknown')}",
            f"システムログ:\n{action_ctx.get('system_log', '')}",
        ]
        if unit.get("classification") == "insane_period":
            context_lines.insert(0, "【発狂状態のRP】キャラクターは発狂症状下での演技です。")
        profile = character_profile or {}
        return JUDGE_USER_PROMPT_TEMPLATE.format(
            occupation=profile.get("occupation", ""),
            age=profile.get("age", ""),
            gender=profile.get("gender", ""),
            memo=profile.get("memo", ""),
            ooc=unit.get("ooc") or "（なし）",
            pc_msg=unit.get("pc_msg") or "（なし）",
            action_context="\n".join(context_lines),
        )

    def evaluate_unit(self, unit, character_profile):
        """単一ターンを Judge LLM で採点する。"""
        prompt = self.build_judge_prompt(unit, character_profile)
        try:
            return self.call_judge(prompt)
        except Exception as exc:
            print(f"[LogEvaluator] Judge 評価失敗 (unit={unit.get('unit_id')}): {exc}")
            return {"total_score": 0, "reason": f"評価エラー: {exc}", "tags": [], "rp_tags": []}

    def _load_dataset(self, path):
        if not os.path.exists(path):
            return {"version": 1, "entries": []}
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"version": 1, "entries": []}
        data.setdefault("version", 1)
        data.setdefault("entries", [])
        return data

    def _save_dataset(self, path, data):
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _append_entry(self, path, entry):
        data = self._load_dataset(path)
        existing_ids = {e.get("unit_id") for e in data["entries"]}
        if entry.get("unit_id") in existing_ids:
            return False
        data["entries"].append(entry)
        self._save_dataset(path, data)
        return True

    def persist_good_entry(
        self,
        unit,
        character_profile,
        judge_score,
        *,
        scenario_file=None,
        char_name="",
        state=None,
        scenario_mgr=None,
        char_mgr=None,
        pl_id=None,
    ):
        from RPLibraryStore import RPLibraryStore, stock_qualified_rp_to_library

        store = self.library_store or RPLibraryStore()
        saved = stock_qualified_rp_to_library(
            unit,
            character_profile,
            judge_score,
            state=state,
            scenario_mgr=scenario_mgr,
            char_mgr=char_mgr,
            pl_id=pl_id,
            scenario_file=scenario_file,
        )
        if not saved and state is not None:
            from RPLibraryStore import build_library_record_from_unit, ensure_rp_session_id

            session_id = ensure_rp_session_id(state)
            turn = int(unit.get("turn") or getattr(scenario_mgr, "turn_counter", 0) or 0) if scenario_mgr else int(unit.get("turn") or 0)
            pending = list(state.get("rp_library_pending") or [])
            record = build_library_record_from_unit(
                unit,
                character_profile,
                judge_score,
                session_id=session_id,
                turn=turn,
                scenario_file=scenario_file or "",
                insane_status=(
                    "insane"
                    if unit.get("classification") == "insane_period"
                    else "normal"
                ),
            )
            pending.append(record)
            state["rp_library_pending"] = pending
        return saved

    def persist_insane_skipped(self, unit, *, scenario_file=None, char_name=""):
        entry = {
            "unit_id": unit.get("unit_id"),
            "saved_at": _utc_now_iso(),
            "scenario_file": scenario_file or "",
            "char_name": char_name,
            "ooc": unit.get("ooc", ""),
            "pc_msg": unit.get("pc_msg", ""),
            "action_context": unit.get("action_context"),
            "skip_reason": "insane_period",
        }
        return self._append_entry(self.insane_skipped_path, entry)

    def evaluate_and_persist(
        self,
        all_events_log,
        char_mgr,
        pl_id,
        char_name,
        *,
        scenario_file=None,
        already_evaluated=None,
        state=None,
        scenario_mgr=None,
    ):
        """
        セッションログを評価し、7点以上を rp_library.json へ追記する。

        already_evaluated: 評価済み unit_id の set/list（重複評価防止）
        """
        from RPLibraryStore import RPLibraryStore, ensure_rp_session_id

        evaluated = set(already_evaluated or [])
        session_id = ensure_rp_session_id(state or {})
        store = self.library_store or RPLibraryStore()
        store.ensure_initialized()

        default_turn = int(getattr(scenario_mgr, "turn_counter", 0) or 0) if scenario_mgr else 0
        profile = build_character_profile(char_mgr, pl_id)
        normal_units, insane_units = extract_rp_turn_units(
            all_events_log,
            char_name,
            insane_skip=True,
            default_turn=default_turn,
        )
        units_to_evaluate = normal_units + insane_units

        summary = {
            "evaluated": 0,
            "skipped_already": 0,
            "skipped_registered": 0,
            "saved_good": 0,
            "saved_library": 0,
            "below_threshold": 0,
            "errors": 0,
        }
        new_hashes = []

        for unit in units_to_evaluate:
            unit_id = unit["unit_id"]
            turn_no = int(unit.get("turn") or default_turn)

            if unit_id in evaluated:
                summary["skipped_already"] += 1
                new_hashes.append(unit_id)
                continue

            if store.is_registered(session_id, unit_id, turn_no):
                summary["skipped_registered"] += 1
                evaluated.add(unit_id)
                new_hashes.append(unit_id)
                continue

            if not unit.get("pc_msg"):
                evaluated.add(unit_id)
                continue

            judge_score = self.evaluate_unit(unit, profile)
            summary["evaluated"] += 1
            evaluated.add(unit_id)
            new_hashes.append(unit_id)

            if judge_score.get("total_score", 0) >= self.score_threshold:
                if self.persist_good_entry(
                    unit, profile, judge_score,
                    scenario_file=scenario_file,
                    char_name=char_name,
                    state=state,
                    scenario_mgr=scenario_mgr,
                    char_mgr=char_mgr,
                    pl_id=pl_id,
                ):
                    summary["saved_good"] += 1
                    summary["saved_library"] += 1
            else:
                summary["below_threshold"] += 1

        self.last_evaluated_hashes = new_hashes
        self.last_summary = summary
        print(
            f"[LogEvaluator] 評価完了: {summary['evaluated']}件判定, "
            f"{summary['saved_library']}件を rp_library へ保存 "
            f"(閾値>={self.score_threshold}, "
            f"登録済みスキップ={summary['skipped_registered']})"
        )
        return summary, list(evaluated)


# ---------------------------------------------------------------------------
# タスク7: Decision Case 抽出 / 6軸評価 / 結果分離
# ---------------------------------------------------------------------------


def _clamp01(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, v))


def _safe_div(numer, denom, default=1.0):
    if not denom:
        return float(default)
    return float(numer) / float(denom)


def _intervention_label(level) -> str:
    try:
        from GameStateManager import InterventionLevel, INTERVENTION_LEVEL_LABELS, normalize_intervention_level

        lvl = normalize_intervention_level(level, InterventionLevel.NONE)
        return INTERVENTION_LEVEL_LABELS.get(lvl, str(int(lvl)))
    except Exception:
        mapping = {0: "なし", 1: "控えめ", 2: "標準", 3: "積極的"}
        try:
            return mapping.get(int(level), str(level))
        except (TypeError, ValueError):
            return str(level or "none")


def _pc_observation_snapshot(char_mgr, actor_id, *, location="", phase="", public_knowledge_ids=None):
    known = []
    investigated = []
    if char_mgr and actor_id:
        if hasattr(char_mgr, "get_known_knowledge_ids"):
            known = list(char_mgr.get_known_knowledge_ids(actor_id) or [])
        elif hasattr(char_mgr, "ensure_knowledge_context"):
            char = char_mgr.ensure_knowledge_context(actor_id) or {}
            known = list(char.get("known_knowledge_ids") or [])
        if hasattr(char_mgr, "get_pc_investigated_targets"):
            investigated = sorted(str(x) for x in (char_mgr.get_pc_investigated_targets(actor_id) or set()))
        else:
            char = (getattr(char_mgr, "characters", {}) or {}).get(actor_id) or {}
            investigated = list(char.get("investigated_targets") or [])
    return {
        "location": str(location or ""),
        "known_knowledge_ids": [str(x) for x in known],
        "public_knowledge_ids": [str(x) for x in (public_knowledge_ids or [])],
        "investigated_targets": [str(x) for x in investigated],
        "phase": str(phase or ""),
    }


def _detect_knowledge_leak_in_entry(entry, known_ids):
    """
    ログエントリが未知知識への言及・漏洩を示唆するか。
    meta.knowledge_leak / knowledge_ids が known にない場合を検出。
    """
    meta = entry.get("meta") or {}
    if meta.get("knowledge_leak"):
        return True
    known = set(str(x) for x in (known_ids or []))
    leaked_ids = meta.get("knowledge_ids") or meta.get("referenced_knowledge_ids") or []
    if isinstance(leaked_ids, (str, int)):
        leaked_ids = [leaked_ids]
    unknown = [str(x) for x in leaked_ids if str(x) and str(x) not in known]
    # secret_to 付きのシステム開示は正規経路なのでリークではない
    if entry.get("secret_to"):
        return False
    if meta.get("knowledge_grant") and unknown:
        # 公開チャンネルへの個別知識付与はリーク候補
        return True
    if meta.get("meta_knowledge_use") or meta.get("ooc_secret_use"):
        return True
    return bool(unknown and meta.get("action_used_unknown_knowledge"))


def _collect_legal_options(state, entry_meta=None):
    meta = entry_meta or {}
    if isinstance(meta.get("legal_options"), list) and meta.get("legal_options"):
        return [str(x) for x in meta["legal_options"]]
    pending = (state or {}).get("pending_decision") or {}
    if isinstance(pending.get("legal_options"), list) and pending.get("legal_options"):
        return [str(x) for x in pending["legal_options"]]
    action_id = str(meta.get("action_id") or "").strip()
    if action_id:
        return [action_id]
    return []


def _find_matching_system_entry(logs, start_idx, *, action_id="", transaction_id=""):
    aid = str(action_id or "").lower()
    tid = str(transaction_id or "").strip()
    for j in range(start_idx + 1, min(len(logs), start_idx + 12)):
        entry = logs[j]
        if entry.get("channel") != "IC":
            continue
        text = str(entry.get("text") or "")
        if not text.startswith("システム:"):
            continue
        meta = entry.get("meta") or {}
        if tid and str(meta.get("transaction_id") or "").strip() == tid:
            return entry, j
        sys_aid = str(meta.get("action_id") or "").lower()
        if aid and sys_aid and sys_aid == aid:
            return entry, j
        if not tid and not aid:
            return entry, j
    return None, None


def extract_decision_cases(
    all_events_log,
    *,
    state=None,
    char_mgr=None,
    session_id="",
    default_actor_id="",
    public_knowledge_ids=None,
):
    """
    all_events_log から意思決定単位（Decision Case）を構造化抽出する。

    PC の IC 行動ログを中心に、対応するシステム結果・合法性注釈を付与する。
    """
    state = state or {}
    logs = list(all_events_log or [])
    cases = []
    seen_txns = Counter()
    public_ids = list(public_knowledge_ids or state.get("public_knowledge_ids") or [])

    for idx, entry in enumerate(logs):
        if entry.get("channel") != "IC":
            continue
        text = str(entry.get("text") or "")
        meta = entry.get("meta") or {}
        action_id = str(meta.get("action_id") or "").lower()
        if not action_id or action_id in _SKIP_ACTION_IDS:
            if not meta.get("needs_system"):
                continue
        # システム行自体はスキップ
        if text.startswith("システム:") or text.startswith("[システム]"):
            continue
        # PC 行動行（meta に action_id がある）のみ
        if not meta.get("action_id") and not meta.get("needs_system"):
            continue

        actor_id = str(
            meta.get("actor_id")
            or meta.get("pc_id")
            or meta.get("decision_owner_id")
            or default_actor_id
            or ""
        )
        txn_id = str(meta.get("transaction_id") or "").strip()
        if txn_id:
            seen_txns[txn_id] += 1

        sys_entry, sys_idx = _find_matching_system_entry(
            logs, idx, action_id=action_id, transaction_id=txn_id,
        )
        sys_meta = (sys_entry or {}).get("meta") or {}
        resolved_ids = []
        if sys_meta.get("knowledge_ids"):
            resolved_ids = [str(x) for x in sys_meta["knowledge_ids"]]
        if sys_meta.get("resolved_event_ids"):
            resolved_ids = [str(x) for x in sys_meta["resolved_event_ids"]]
        elif sys_idx is not None:
            resolved_ids = resolved_ids or [f"log:{sys_idx}"]

        observation = _pc_observation_snapshot(
            char_mgr,
            actor_id,
            location=entry.get("location") or state.get("current_loc") or "",
            phase=str(state.get("timeline_phase") or meta.get("phase") or ""),
            public_knowledge_ids=public_ids,
        )
        # ログ時点の既知情報ヒント（meta にあれば優先）
        if isinstance(meta.get("known_knowledge_ids"), list):
            observation["known_knowledge_ids"] = [str(x) for x in meta["known_knowledge_ids"]]
        if isinstance(meta.get("investigated_targets"), list):
            observation["investigated_targets"] = [str(x) for x in meta["investigated_targets"]]

        legal_options = _collect_legal_options(state, meta)
        chosen = str(meta.get("action_id") or action_id or "")
        rule_legal = True
        validation_error = bool(meta.get("validation_error"))
        # 直近に同一 actor の validation_error があれば紐付け
        for k in range(max(0, idx - 3), idx + 4):
            if k >= len(logs):
                break
            m2 = (logs[k].get("meta") or {})
            if m2.get("validation_error") and (
                not m2.get("pc_id") or str(m2.get("pc_id")) == actor_id
            ):
                validation_error = True
                rule_legal = False
                break
        if legal_options and chosen and chosen not in {str(x).lower() for x in legal_options} and len(legal_options) > 1:
            # pending_decision の合法集合に含まれない選択
            lowered = {str(x).lower() for x in legal_options}
            if chosen.lower() not in lowered:
                rule_legal = False

        knowledge_leak = _detect_knowledge_leak_in_entry(entry, observation["known_knowledge_ids"])
        if sys_entry:
            knowledge_leak = knowledge_leak or _detect_knowledge_leak_in_entry(
                sys_entry, observation["known_knowledge_ids"],
            )

        intervention = meta.get("intervention_level")
        if intervention is None:
            intervention = (state.get("last_stagnation_intervention") or {}).get("level")
        action_origin = str(meta.get("action_origin") or "AUTONOMOUS").upper()
        forced = action_origin in ("SYSTEM_FORCED", "HUMAN_FORCED")
        duplicate = bool(txn_id and seen_txns[txn_id] > 1)

        case = build_decision_case(
            actor_id=actor_id,
            session_id=session_id or state.get("rp_session_id") or state.get("session_id") or "",
            turn=int(meta.get("turn") or state.get("turn") or 0),
            observation=observation,
            legal_options=legal_options,
            chosen_action={
                "action": chosen,
                "target": str(meta.get("target") or ""),
                "skill": str(meta.get("skill") or ""),
                "transaction_id": txn_id,
            },
            resolved_event_ids=resolved_ids,
            annotations={
                "rule_legal": rule_legal and not validation_error,
                "knowledge_leak": knowledge_leak,
                "intervention_level": _intervention_label(intervention) if intervention is not None else "none",
                "validation_error": validation_error,
                "duplicate_transaction": duplicate,
                "forced_progress": forced,
                "action_origin": action_origin,
                "stagnation_cause": str(
                    meta.get("stagnation_cause")
                    or state.get("stagnation_cause")
                    or ""
                ),
                "notes": str(meta.get("decision_notes") or ""),
            },
            case_id=str(meta.get("case_id") or ""),
        )
        # 決定的 ID（回帰テスト向け）: txn があればそれで安定化
        if txn_id and not meta.get("case_id"):
            case["case_id"] = f"dc_{hashlib.sha256(txn_id.encode('utf-8')).hexdigest()[:16]}"
        cases.append(case)

    return cases


def detect_in_game_defeat(state=None, char_mgr=None, all_events_log=None):
    """
    ゲーム内敗北（SAN枯渇・全滅）を検知する。システム障害とは独立。
    戻り値: None | 'defeat_san' | 'defeat_party_wipe'
    """
    state = state or {}
    explicit = str(state.get("game_outcome") or state.get("in_game_outcome") or "").strip()
    if explicit in (OUTCOME_DEFEAT_SAN, OUTCOME_DEFEAT_WIPE):
        return explicit

    logs = all_events_log if all_events_log is not None else state.get("all_events_log") or []
    for entry in reversed(list(logs)[-40:]):
        text = str(entry.get("text") or "")
        meta = entry.get("meta") or {}
        outcome_hint = str(meta.get("game_outcome") or "")
        if outcome_hint in (OUTCOME_DEFEAT_SAN, OUTCOME_DEFEAT_WIPE):
            return outcome_hint
        if any(m in text for m in _DEFEAT_WIPE_MARKERS):
            return OUTCOME_DEFEAT_WIPE
        if any(m in text for m in _DEFEAT_SAN_MARKERS):
            return OUTCOME_DEFEAT_SAN

    if char_mgr is not None:
        pc_ids = []
        if hasattr(char_mgr, "list_pc_ids"):
            pc_ids = list(char_mgr.list_pc_ids() or [])
        elif hasattr(char_mgr, "active_pc_list"):
            pc_ids = list(char_mgr.active_pc_list or [])
        if pc_ids:
            san_dead = 0
            hp_dead = 0
            for pc_id in pc_ids:
                san = 999
                if hasattr(char_mgr, "get_stat_current"):
                    try:
                        san = int(char_mgr.get_stat_current(pc_id, "SAN"))
                    except Exception:
                        san = 999
                if san <= 0:
                    san_dead += 1
                incapacitated = False
                if hasattr(char_mgr, "is_pc_incapacitated"):
                    try:
                        incapacitated = bool(char_mgr.is_pc_incapacitated(pc_id))
                    except Exception:
                        incapacitated = False
                if incapacitated or (
                    hasattr(char_mgr, "get_stat_current")
                    and int(char_mgr.get_stat_current(pc_id, "HP") or 0) <= 0
                ):
                    hp_dead += 1
            if san_dead >= len(pc_ids):
                return OUTCOME_DEFEAT_SAN
            if hp_dead >= len(pc_ids):
                return OUTCOME_DEFEAT_WIPE

    return None


def detect_retreat(state=None, all_events_log=None):
    """ゲーム内撤退の検知。"""
    state = state or {}
    if str(state.get("game_outcome") or "") == OUTCOME_RETREAT:
        return True
    if state.get("retreated") or state.get("party_retreated"):
        return True
    logs = all_events_log if all_events_log is not None else state.get("all_events_log") or []
    for entry in reversed(list(logs)[-30:]):
        text = str(entry.get("text") or "")
        meta = entry.get("meta") or {}
        if meta.get("game_outcome") == OUTCOME_RETREAT or meta.get("retreat"):
            return True
        if any(m in text for m in _RETREAT_MARKERS):
            return True
    return False


def classify_session_outcome(state=None, char_mgr=None, *, pause_reason=None, all_events_log=None):
    """
    セッション結果を分類する。

    重要: ゲーム内敗北/撤退/クリアと、システムの実行障害（error）を分離する。
    pause_reason が error でも、ログ上にゲーム敗北が明示されていればゲーム結果を優先しない
    （error は運用品質側で別途減点）。ただし pause_reason=game_clear は常にクリア。
    """
    state = state or {}
    reason = str(
        pause_reason
        if pause_reason is not None
        else state.get("autonomous_pause_reason") or ""
    ).strip()

    if reason == "game_clear" or state.get("game_cleared"):
        return {
            "outcome": OUTCOME_GAME_CLEAR,
            "category": "game",
            "is_system_failure": False,
            "pause_reason": reason or "game_clear",
            "label": "真相解明・シナリオクリア",
        }

    defeat = detect_in_game_defeat(state, char_mgr, all_events_log)
    if defeat:
        label = "SAN枯渇による敗北" if defeat == OUTCOME_DEFEAT_SAN else "パーティ全滅による敗北"
        return {
            "outcome": defeat,
            "category": "game",
            "is_system_failure": False,
            "pause_reason": reason,
            "label": label,
        }

    if detect_retreat(state, all_events_log) or reason == "retreat":
        return {
            "outcome": OUTCOME_RETREAT,
            "category": "game",
            "is_system_failure": False,
            "pause_reason": reason,
            "label": "撤退・探索打ち切り",
        }

    if reason == "error":
        return {
            "outcome": OUTCOME_ERROR,
            "category": "system",
            "is_system_failure": True,
            "pause_reason": reason,
            "label": "システム実行障害",
        }
    if reason == "empty_tick":
        return {
            "outcome": OUTCOME_EMPTY_TICK,
            "category": "system",
            "is_system_failure": True,
            "pause_reason": reason,
            "label": "空振りティック（実行障害寄り）",
        }
    if reason == "stagnation":
        return {
            "outcome": OUTCOME_STAGNATION,
            "category": "soft_stop",
            "is_system_failure": False,
            "pause_reason": reason,
            "label": "停滞による打ち切り",
        }
    if reason == "user_stop":
        return {
            "outcome": OUTCOME_USER_STOP,
            "category": "soft_stop",
            "is_system_failure": False,
            "pause_reason": reason,
            "label": "ユーザー停止",
        }
    if reason == "max_iterations":
        return {
            "outcome": OUTCOME_MAX_ITERATIONS,
            "category": "soft_stop",
            "is_system_failure": False,
            "pause_reason": reason,
            "label": "安全上限到達",
        }
    if reason:
        return {
            "outcome": reason,
            "category": "soft_stop",
            "is_system_failure": False,
            "pause_reason": reason,
            "label": reason,
        }
    return {
        "outcome": OUTCOME_UNKNOWN,
        "category": "unknown",
        "is_system_failure": False,
        "pause_reason": "",
        "label": "未分類",
    }


def _count_force_interventions(state, decision_cases, all_events_log):
    from ProgressDirectorV2 import count_forced_from_action_origin
    return count_forced_from_action_origin(state, all_events_log)


def _estimate_repeat_waste(decision_cases):
    """重複調査・同一行動の空回りを数える。"""
    pairs = []
    waste = 0
    for case in decision_cases or []:
        chosen = case.get("chosen_action") or {}
        key = (str(chosen.get("action") or ""), str(chosen.get("target") or ""))
        loc = str((case.get("observation") or {}).get("location") or "")
        full = (loc, key[0], key[1])
        pairs.append(full)
    counter = Counter(pairs)
    for key, n in counter.items():
        if key[1] in ("search", "inspect", "listen", "spot") and n > 1:
            waste += n - 1
        elif n > 2:
            waste += n - 2
    return waste


def evaluate_session_metrics(
    state=None,
    char_mgr=None,
    *,
    decision_cases=None,
    all_events_log=None,
    pause_reason=None,
    rp_summary=None,
):
    """
    6軸メトリクスを集計する。

    ① 機械的正確性  ② 知識一貫性  ③ 自律度
    ④ 進行効率      ⑤ 役割品質    ⑥ 運用品質（結果分離込み）
    """
    state = state or {}
    logs = all_events_log if all_events_log is not None else state.get("all_events_log") or []
    cases = decision_cases
    if cases is None:
        cases = extract_decision_cases(
            logs,
            state=state,
            char_mgr=char_mgr,
            session_id=state.get("rp_session_id") or state.get("session_id") or "",
            default_actor_id=state.get("pl_id") or "",
        )

    n = max(len(cases), 1)
    validation_errors = sum(1 for c in cases if (c.get("annotations") or {}).get("validation_error"))
    duplicates = sum(1 for c in cases if (c.get("annotations") or {}).get("duplicate_transaction"))
    illegal = sum(1 for c in cases if not (c.get("annotations") or {}).get("rule_legal", True))
    leaks = sum(1 for c in cases if (c.get("annotations") or {}).get("knowledge_leak"))
    force_count = _count_force_interventions(state, cases, logs)
    waste = _estimate_repeat_waste(cases)

    mechanical = _clamp01(1.0 - _safe_div(validation_errors + duplicates + illegal, n, 0.0))
    knowledge = _clamp01(1.0 - _safe_div(leaks, n, 0.0))
    autonomy = _clamp01(1.0 - _safe_div(force_count, max(n, force_count, 1), 0.0))
    efficiency = _clamp01(1.0 - _safe_div(waste, n, 0.0))

    # 役割品質: RP 評価サマリがあればそれを、なければテンプレ行動率の逆数で近似
    rp_summary = rp_summary or state.get("rp_eval_last_summary") or {}
    evaluated = int(rp_summary.get("evaluated") or 0)
    saved = int(rp_summary.get("saved_library") or rp_summary.get("saved_good") or 0)
    below = int(rp_summary.get("below_threshold") or 0)
    if evaluated > 0:
        role_quality = _clamp01(_safe_div(saved + 0.5 * max(evaluated - saved - below, 0), evaluated, 0.5))
        # より直感的: 閾値以上比率
        role_quality = _clamp01(_safe_div(saved, evaluated, 0.5))
    else:
        template_like = 0
        for c in cases:
            action = str((c.get("chosen_action") or {}).get("action") or "")
            if action in ("search", "inspect", "wait", "move") and not (c.get("annotations") or {}).get("notes"):
                template_like += 1
        role_quality = _clamp01(1.0 - 0.5 * _safe_div(template_like, n, 0.0))

    outcome_info = classify_session_outcome(
        state, char_mgr, pause_reason=pause_reason, all_events_log=logs,
    )
    # ⑥ 運用品質: システム障害のみ減点。ゲーム敗北は運用成功（正常終了）として扱う
    if outcome_info["is_system_failure"]:
        operational = 0.0 if outcome_info["outcome"] == OUTCOME_ERROR else 0.35
    elif outcome_info["outcome"] in GAME_OUTCOMES:
        operational = 1.0
    elif outcome_info["outcome"] in SOFT_STOPS:
        operational = 0.7
    else:
        operational = 0.5

    axes = {
        "mechanical_accuracy": {
            "score": round(mechanical, 4),
            "label": "機械的正確性",
            "detail": {
                "validation_errors": validation_errors,
                "duplicate_transactions": duplicates,
                "illegal_choices": illegal,
                "cases": len(cases),
            },
        },
        "knowledge_consistency": {
            "score": round(knowledge, 4),
            "label": "知識一貫性（Zero Knowledge Leak）",
            "detail": {"knowledge_leaks": leaks, "cases": len(cases)},
        },
        "autonomy": {
            "score": round(autonomy, 4),
            "label": "自律度（FORCE非依存）",
            "detail": {"force_interventions": force_count, "cases": len(cases)},
        },
        "progress_efficiency": {
            "score": round(efficiency, 4),
            "label": "進行効率",
            "detail": {"repeat_waste": waste, "cases": len(cases)},
        },
        "role_quality": {
            "score": round(role_quality, 4),
            "label": "役割品質",
            "detail": {
                "rp_evaluated": evaluated,
                "rp_saved": saved,
                "rp_below_threshold": below,
            },
        },
        "operational_quality": {
            "score": round(operational, 4),
            "label": "運用品質・結果分離",
            "detail": {
                "outcome": outcome_info["outcome"],
                "outcome_category": outcome_info["category"],
                "outcome_label": outcome_info["label"],
                "is_system_failure": outcome_info["is_system_failure"],
                "pause_reason": outcome_info["pause_reason"],
                "game_defeat_separated_from_error": (
                    outcome_info["outcome"] in (OUTCOME_DEFEAT_SAN, OUTCOME_DEFEAT_WIPE)
                    and not outcome_info["is_system_failure"]
                ),
            },
        },
    }

    scores = [axes[k]["score"] for k in axes]
    aggregate = round(sum(scores) / len(scores), 4) if scores else 0.0

    return {
        "axes": axes,
        "aggregate_score": aggregate,
        "outcome": outcome_info,
        "case_count": len(cases),
        "evaluated_at": _utc_now_iso(),
        # 後方互換: 「完走」だけに依存しないことを明示
        "completion_rate_deprecated": None,
    }


def persist_session_metrics(metrics, *, path=DEFAULT_SESSION_METRICS_PATH, session_id=""):
    """6軸評価結果を JSONL に追記する。"""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    row = {
        "session_id": session_id,
        "saved_at": _utc_now_iso(),
        **(metrics or {}),
    }
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def extract_and_persist_decision_cases(
    state,
    char_mgr=None,
    *,
    store=None,
    already_case_ids=None,
):
    """
    Decision Case を抽出し datasets/decision_cases.jsonl へ保存する。
    既知 case_id はスキップ（冪等）。
    """
    from RPLibraryStore import ensure_rp_session_id

    state = state or {}
    ensure_rp_session_id(state)
    session_id = state.get("rp_session_id") or state.get("session_id") or ""
    logs = state.get("all_events_log") or []
    cases = extract_decision_cases(
        logs,
        state=state,
        char_mgr=char_mgr,
        session_id=session_id,
        default_actor_id=state.get("pl_id") or "",
    )
    store = store or DecisionCaseStore()
    known = set(already_case_ids or state.get("decision_case_ids") or [])
    saved = []
    for case in cases:
        cid = case.get("case_id")
        if cid in known:
            continue
        if store.has_case_id(cid):
            known.add(cid)
            continue
        saved.append(store.append_case(case))
        known.add(cid)
    state["decision_case_ids"] = list(known)
    return {"extracted": len(cases), "saved": len(saved), "cases": cases, "saved_cases": saved}


def record_decision_case(
    *,
    actor_id,
    observation=None,
    legal_options=None,
    chosen_action=None,
    resolved_event_ids=None,
    annotations=None,
    session_id="",
    turn=0,
    store=None,
    persist=True,
):
    """単一の意思決定イベントから Decision Case を生成（必要なら保存）。"""
    case = build_decision_case(
        actor_id=actor_id,
        observation=observation,
        legal_options=legal_options,
        chosen_action=chosen_action,
        resolved_event_ids=resolved_event_ids,
        annotations=annotations,
        session_id=session_id,
        turn=turn,
    )
    if persist:
        store = store or DecisionCaseStore()
        return store.append_case(case)
    return normalize_decision_case(case)


def evaluate_session_rp_logs(
    state,
    char_mgr,
    pl_id=None,
    char_name=None,
    scenario_file=None,
    scenario_mgr=None,
    *,
    score_threshold=None,
    skip_rp_judge=False,
    decision_store=None,
    metrics_path=None,
):
    """main / app から呼び出すヘルパー。

    - 既存: RP Judge 評価と rp_library 永続化
    - タスク7: Decision Case 抽出保存 + 6軸メトリクス
    """
    if not state or not char_mgr:
        return None

    from RPLibraryStore import ensure_rp_session_id, on_autosave_rp_library_hook

    pl_id = pl_id or state.get("pl_id", "new_investigator")
    char_name = char_name or state.get("char_name", "")
    scenario_file = scenario_file or state.get("scenario_file", "")
    logs = state.get("all_events_log") or []
    if not logs:
        return None

    ensure_rp_session_id(state)
    summary = None

    if not skip_rp_judge and char_name:
        evaluator = LogEvaluator(score_threshold=score_threshold)
        already = set(state.get("rp_eval_unit_ids") or [])
        summary, all_ids = evaluator.evaluate_and_persist(
            logs,
            char_mgr,
            pl_id,
            char_name,
            scenario_file=scenario_file,
            already_evaluated=already,
            state=state,
            scenario_mgr=scenario_mgr,
        )
        state["rp_eval_unit_ids"] = all_ids
        state["rp_eval_last_summary"] = summary
        on_autosave_rp_library_hook(state)

    # Decision Case + 6軸（Judge 失敗時でも実行）
    try:
        dc_result = extract_and_persist_decision_cases(
            state, char_mgr, store=decision_store,
        )
        metrics = evaluate_session_metrics(
            state,
            char_mgr,
            decision_cases=dc_result.get("cases"),
            all_events_log=logs,
            pause_reason=state.get("autonomous_pause_reason"),
            rp_summary=summary or state.get("rp_eval_last_summary"),
        )
        persist_session_metrics(
            metrics,
            path=metrics_path or DEFAULT_SESSION_METRICS_PATH,
            session_id=state.get("rp_session_id") or "",
        )
        state["session_metrics_last"] = metrics
        state["decision_case_last_summary"] = {
            "extracted": dc_result.get("extracted", 0),
            "saved": dc_result.get("saved", 0),
        }
        print(
            f"[LogEvaluator] DecisionCase={dc_result.get('saved', 0)}件保存 / "
            f"6軸aggregate={metrics.get('aggregate_score')} "
            f"outcome={((metrics.get('outcome') or {}).get('outcome'))}"
        )
        if summary is not None:
            summary = dict(summary)
            summary["decision_cases_saved"] = dc_result.get("saved", 0)
            summary["metrics_aggregate"] = metrics.get("aggregate_score")
            summary["session_outcome"] = (metrics.get("outcome") or {}).get("outcome")
            state["rp_eval_last_summary"] = summary
        else:
            summary = {
                "decision_cases_saved": dc_result.get("saved", 0),
                "metrics_aggregate": metrics.get("aggregate_score"),
                "session_outcome": (metrics.get("outcome") or {}).get("outcome"),
                "axes": {k: v.get("score") for k, v in (metrics.get("axes") or {}).items()},
            }
            state["rp_eval_last_summary"] = summary
    except Exception as exc:
        print(f"[LogEvaluator] DecisionCase/6軸評価をスキップ: {exc}")

    return summary
