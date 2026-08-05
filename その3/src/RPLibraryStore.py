"""
良質 RP ログの構造化ストック基盤（Few-Shot / ファインチューニング用データ蓄積のみ）。
プロンプトへの自動挿入は行わない。
"""
import hashlib
import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone

DEFAULT_LIBRARY_PATH = os.path.join("datasets", "rp_library.json")
LIBRARY_VERSION = 1
QUALIFIED_SCORE_THRESHOLD = 7

VALID_RP_TAGS = frozenset({
    "tone:serious",
    "tone:comic",
    "tone:cowardly",
    "tone:cool",
    "tone:emotional",
    "expr:flair",
    "expr:narrative_dice",
    "context:investigating",
    "context:stagnated",
})

VALID_TONE_TAGS = frozenset(
    tag for tag in VALID_RP_TAGS if tag.startswith("tone:")
)

JUDGE_TAG_PROMPT_BLOCK = """
提示されたプレイヤーの行動ログ（OOC、IC、状況）を分析し、そのロールプレイの性質を客観的に評価してください。評価スコア（10点満点）が「7点以上」の場合、ロールプレイの性質を表す適切なタグを以下の定義から【複数選択】し、指定のJSON構造のみで出力してください。

【タグ定義】
■ 演技トーン（合致するものを1〜2個選択）
- "tone:serious" （シリアス、緊迫感がある、真面目）
- "tone:comic" （コミカル、ユーモラス、お調子者）
- "tone:cowardly" （臆病、情けない、逃げ腰、命を最優先にしている）
- "tone:cool" （冷静沈着、知的、ハードボイルド）
- "tone:emotional" （感情的、激しい恐怖、怒り、パニック）

■ 表現の質（該当するものを選択）
- "expr:flair" （職業や設定メモ特有のキーワードや口調、専門用語がセリフに含まれている）
- "expr:narrative_dice" （ダイスの成否結果を、単なるシステム的な事実ではなくキャラの感情や周囲の描写にうまく昇華している）

■ ゲーム文脈（該当するものを選択）
- "context:investigating" （熱心に調査・探索、あるいは謎解きを行っている）
- "context:stagnated" （手詰まりや失敗による焦り、葛藤を演技に組み込んでいる）

【タグ付けのルール】
- 定義にないタグは出力しないこと。
- 演技トーン（tone:*）は最大2個まで。
- スコアが7点未満の場合は `rp_tags` を空配列にすること。
- 該当がなければ `rp_tags` は空配列でもよい。
"""


def sanitize_rp_tags(raw_tags):
    """Judge が返したタグをホワイトリストで正規化する。"""
    if not isinstance(raw_tags, list):
        return []
    cleaned = []
    tone_count = 0
    for item in raw_tags:
        tag = str(item or "").strip()
        if tag not in VALID_RP_TAGS or tag in cleaned:
            continue
        if tag.startswith("tone:"):
            if tone_count >= 2:
                continue
            tone_count += 1
        cleaned.append(tag)
    return cleaned


def build_system_meta_tags(action_context):
    """システム由来の検索用メタタグ（action:/result:/skill:/target:）。"""
    ctx = action_context or {}
    tags = []
    action_id = str(ctx.get("action_id") or "").strip()
    if action_id:
        tags.append(f"action:{action_id}")
    outcome = str(ctx.get("roll_outcome") or "").strip()
    if outcome and outcome != "unknown":
        tags.append(f"result:{outcome}")
    skill = str(ctx.get("skill") or "").strip()
    if skill:
        tags.append(f"skill:{skill}")
    target = str(ctx.get("target") or "").strip()
    if target:
        tags.append(f"target:{target}")
    return tags


def build_merged_tags(action_context, char_profile, rp_tags=None):
    """構造化フィールド・システムメタタグ・Judge RPタグを統合する。"""
    base = build_search_tags(action_context, char_profile)
    system_meta = build_system_meta_tags(action_context)
    rp_clean = sanitize_rp_tags(rp_tags or [])
    merged = sorted(set(system_meta + rp_clean))
    return {
        **base,
        "system": system_meta,
        "rp": rp_clean,
        "merged": merged,
    }


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def ensure_rp_session_id(state):
    """セッション用 UUID を state に付与（未設定時のみ生成）。"""
    if not state:
        return ""
    session_id = str(state.get("rp_session_id") or "").strip()
    if not session_id:
        session_id = str(uuid.uuid4())
        state["rp_session_id"] = session_id
    return session_id


def resolve_insane_status(char_mgr, pl_id):
    """発狂状態の要約文字列（通常時は normal）。"""
    if not char_mgr or not pl_id:
        return "normal"
    get_states = getattr(char_mgr, "get_insanity_states", None)
    if not get_states:
        return "normal"
    insanities = get_states(pl_id)
    if not insanities:
        return "normal"
    labels = [
        str(item.get("label") or item.get("type") or "狂気").strip()
        for item in insanities
        if item
    ]
    return "; ".join(labels) if labels else "normal"


def build_record_id(session_id, unit_id, turn=None):
    """セッションID・ユニットID（＋任意でターン）から一意 ID を生成。"""
    raw = f"{session_id}|{unit_id}"
    if turn is not None:
        raw = f"{session_id}|{turn}|{unit_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _format_last_action(action_context):
    """検索用にアクション・技能・対象を1文字列にまとめる。"""
    ctx = action_context or {}
    parts = []
    action_id = str(ctx.get("action_id") or "").strip()
    skill = str(ctx.get("skill") or "").strip()
    target = str(ctx.get("target") or "").strip()
    if action_id:
        parts.append(action_id)
    if skill:
        parts.append(skill)
    if target:
        parts.append(target)
    return " / ".join(parts) if parts else ""


def build_search_tags(action_context, char_profile):
    """将来のフィルタ用タグ。"""
    ctx = action_context or {}
    profile = char_profile or {}
    return {
        "occupation": str(profile.get("occupation") or ""),
        "action_id": str(ctx.get("action_id") or ""),
        "skill": str(ctx.get("skill") or ""),
        "target": str(ctx.get("target") or ""),
        "roll_outcome": str(ctx.get("roll_outcome") or "unknown"),
        "roll_type": str(ctx.get("roll_type") or ""),
    }


def cleanse_library_record(record):
    """レコードを保存用スキーマに正規化・クレンジングする。"""
    char_profile = (
        record.get("character_profile")
        or record.get("char_profile")
        or {}
    )
    game_state = record.get("game_state") or {}
    dialog = record.get("dialog") or {}
    judge = record.get("judge") or {}
    judge_tags = sanitize_rp_tags(
        judge.get("tags")
        or judge.get("rp_tags")
        or record.get("rp_tags")
        or []
    )

    cleaned = {
        "id": str(record.get("id") or "").strip(),
        "timestamp": str(record.get("timestamp") or _utc_now_iso()),
        "session_id": str(record.get("session_id") or "").strip(),
        "turn": int(record.get("turn") or 0),
        "character_profile": {
            "occupation": str(char_profile.get("occupation") or ""),
            "age": char_profile.get("age", ""),
            "memo": str(char_profile.get("memo") or "").strip(),
        },
        "game_state": {
            "insane_status": str(game_state.get("insane_status") or "normal"),
            "last_action": str(game_state.get("last_action") or "").strip(),
            "last_result": str(game_state.get("last_result") or "unknown"),
        },
        "dialog": {
            "ooc": str(dialog.get("ooc") or "").strip(),
            "pc": str(dialog.get("pc") or "").strip(),
        },
        "judge": {
            "score": int(judge.get("score") or judge.get("total_score") or 0),
            "reason": str(judge.get("reason") or "").strip(),
            "tags": judge_tags,
        },
    }
    return cleaned


def build_library_record_from_unit(
    unit,
    char_profile,
    judge_score,
    *,
    session_id,
    turn=0,
    scenario_file="",
    insane_status="normal",
):
    """LogEvaluator のターン単位データからライブラリレコードを組み立てる。"""
    action_ctx = unit.get("action_context") or {}
    unit_id = unit.get("unit_id") or ""
    turn_no = int(unit.get("turn") or turn or 0)
    record_id = build_record_id(session_id, unit_id, turn_no)
    score = int((judge_score or {}).get("total_score") or (judge_score or {}).get("score") or 0)
    rp_tags = sanitize_rp_tags(
        (judge_score or {}).get("tags")
        or (judge_score or {}).get("rp_tags")
        or []
    )
    if score < QUALIFIED_SCORE_THRESHOLD:
        rp_tags = []

    record = {
        "id": record_id,
        "timestamp": _utc_now_iso(),
        "session_id": session_id,
        "turn": turn_no,
        "character_profile": {
            "occupation": char_profile.get("occupation", ""),
            "age": char_profile.get("age", ""),
            "memo": char_profile.get("memo", ""),
        },
        "game_state": {
            "insane_status": insane_status or "normal",
            "last_action": _format_last_action(action_ctx),
            "last_result": str(action_ctx.get("roll_outcome") or "unknown"),
        },
        "dialog": {
            "ooc": unit.get("ooc", ""),
            "pc": unit.get("pc_msg", ""),
        },
        "judge": {
            "score": score,
            "reason": str((judge_score or {}).get("reason") or ""),
            "tags": rp_tags,
        },
    }
    return cleanse_library_record(record)


class RPLibraryStore:
    """rp_library.json への安全な追記・重複排除ストア。"""

    _process_lock = threading.Lock()

    def __init__(self, library_path=None):
        self.library_path = library_path or DEFAULT_LIBRARY_PATH

    @staticmethod
    def empty_library():
        now = _utc_now_iso()
        return {
            "version": LIBRARY_VERSION,
            "meta": {
                "created_at": now,
                "updated_at": now,
                "description": "良質RPログの構造化ライブラリ（Judge自動タグ付け・蓄積専用・プロンプト未使用）",
            },
            "index": {},
            "records": [],
        }

    def ensure_initialized(self):
        """ライブラリファイルが無ければ空構造を生成する。"""
        with self._process_lock:
            if os.path.exists(self.library_path):
                data = self._read_file_unsafe()
                if isinstance(data, dict) and "records" in data:
                    return data
            data = self.empty_library()
            self._write_file_unsafe(data)
            return data

    def _read_file_unsafe(self):
        if not os.path.exists(self.library_path):
            return self.empty_library()
        try:
            with open(self.library_path, encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[RPLibraryStore] 読み込み失敗、空ライブラリで再初期化: {exc}")
            return self.empty_library()
        if isinstance(data, list):
            return {
                "version": LIBRARY_VERSION,
                "meta": {"migrated_from": "plain_array"},
                "index": {},
                "records": data,
            }
        if not isinstance(data, dict):
            return self.empty_library()
        data.setdefault("version", LIBRARY_VERSION)
        data.setdefault("meta", {})
        data.setdefault("index", {})
        data.setdefault("records", [])
        if not isinstance(data["index"], dict):
            data["index"] = {}
        if not isinstance(data["records"], list):
            data["records"] = []
        return data

    def _write_file_unsafe(self, data):
        directory = os.path.dirname(self.library_path) or "."
        os.makedirs(directory, exist_ok=True)
        data = dict(data)
        data.setdefault("meta", {})
        data["meta"]["updated_at"] = _utc_now_iso()
        if not data["meta"].get("created_at"):
            data["meta"]["created_at"] = data["meta"]["updated_at"]

        fd, tmp_path = tempfile.mkstemp(
            prefix=".rp_library_",
            suffix=".tmp",
            dir=directory,
            text=True,
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as tmp_file:
                json.dump(data, tmp_file, ensure_ascii=False, indent=2)
                tmp_file.flush()
                os.fsync(tmp_file.fileno())
            os.replace(tmp_path, self.library_path)
        except Exception:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            raise

    def is_registered(self, session_id, unit_id, turn=None):
        """セッション内のユニットが既に登録済みか（重複ガード）。"""
        record_id = build_record_id(session_id, unit_id, turn)
        with self._process_lock:
            data = self._read_file_unsafe()
            return record_id in data.get("index", {})

    def append_record(self, record):
        """
        レコードを追記する。id が既存 index にあれば False を返す（重複登録防止）。
        """
        cleaned = cleanse_library_record(record)
        if not cleaned["id"]:
            return False

        with self._process_lock:
            data = self._read_file_unsafe()
            index = data.setdefault("index", {})
            if cleaned["id"] in index:
                return False
            data.setdefault("records", []).append(cleaned)
            index[cleaned["id"]] = {
                "session_id": cleaned["session_id"],
                "turn": cleaned["turn"],
                "timestamp": cleaned["timestamp"],
            }
            self._write_file_unsafe(data)
            return True

    def append_from_evaluator_unit(
        self,
        unit,
        char_profile,
        judge_score,
        *,
        session_id,
        turn=0,
        scenario_file="",
        insane_status="normal",
    ):
        """LogEvaluator 出力からライブラリへ追記。"""
        record = build_library_record_from_unit(
            unit,
            char_profile,
            judge_score,
            session_id=session_id,
            turn=turn,
            scenario_file=scenario_file,
            insane_status=insane_status,
        )
        return self.append_record(record)

    def flush_pending_queue(self, pending_records):
        """メモリ上の保留レコードを一括追記（オートセーブ用）。"""
        if not pending_records:
            return 0
        saved = 0
        for record in pending_records:
            if self.append_record(record):
                saved += 1
        return saved

    def count_records(self):
        data = self.ensure_initialized()
        return len(data.get("records", []))


def stock_qualified_rp_to_library(
    unit,
    char_profile,
    judge_score,
    *,
    state=None,
    scenario_mgr=None,
    char_mgr=None,
    pl_id=None,
    scenario_file="",
):
    """
    良質判定済みログを rp_library.json へクレンジング保存する。
    プロンプトへは一切注入しない。
    """
    session_id = ensure_rp_session_id(state or {})
    turn = int(unit.get("turn") or 0)
    if scenario_mgr is not None and not turn:
        turn = int(getattr(scenario_mgr, "turn_counter", 0) or 0)
    insane_status = "normal"
    if unit.get("classification") == "insane_period":
        insane_status = resolve_insane_status(char_mgr, pl_id) or "insane"

    store = RPLibraryStore()
    store.ensure_initialized()
    if store.is_registered(session_id, unit.get("unit_id") or "", turn):
        return False
    return store.append_from_evaluator_unit(
        unit,
        char_profile,
        judge_score,
        session_id=session_id,
        turn=turn,
        scenario_file=scenario_file,
        insane_status=insane_status,
    )


def on_autosave_rp_library_hook(state=None):
    """オートセーブ時: ライブラリ初期化と保留キューのフラッシュのみ。"""
    store = RPLibraryStore()
    store.ensure_initialized()
    pending = list((state or {}).get("rp_library_pending") or [])
    if not pending:
        return 0
    saved = store.flush_pending_queue(pending)
    if state is not None:
        state["rp_library_pending"] = []
    return saved
