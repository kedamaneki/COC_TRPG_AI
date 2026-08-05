"""
TRPG セッションログの RP 品質を Judge LLM で評価し、良質ログをデータセット化する。
"""
import hashlib
import json
import os
import re
from datetime import datetime, timezone

from RPLibraryStore import JUDGE_TAG_PROMPT_BLOCK, sanitize_rp_tags

DEFAULT_SCORE_THRESHOLD = 7
DEFAULT_INSANE_SKIPPED_PATH = os.path.join("datasets", "insane_rp_skipped.json")

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


def evaluate_session_rp_logs(
    state,
    char_mgr,
    pl_id=None,
    char_name=None,
    scenario_file=None,
    scenario_mgr=None,
    *,
    score_threshold=None,
):
    """main / app から呼び出すヘルパー。state の rp_eval_unit_ids を更新する。"""
    if not state or not char_mgr:
        return None

    from RPLibraryStore import ensure_rp_session_id, on_autosave_rp_library_hook

    pl_id = pl_id or state.get("pl_id", "new_investigator")
    char_name = char_name or state.get("char_name", "")
    scenario_file = scenario_file or state.get("scenario_file", "")
    logs = state.get("all_events_log") or []
    if not logs or not char_name:
        return None

    ensure_rp_session_id(state)
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
    return summary
