"""
Decision Case の構造化保存（Few-Shot / RAG / 回帰テスト用データ蓄積）。
検索・プロンプト注入は DecisionCaseRAG が担当する。
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

DEFAULT_DECISION_CASES_PATH = os.path.join("datasets", "decision_cases.jsonl")
DEFAULT_DECISION_CASES_INDEX = os.path.join("datasets", "decision_cases_index.json")
STORE_VERSION = 1

_lock = threading.Lock()

# 自律度が高いとみなす介入レベル
_AUTONOMOUS_INTERVENTION_LEVELS: Set[str] = {
    "",
    "none",
    "なし",
    "0",
    "light",
    "控えめ",
    "1",
}

_FAILURE_OPTIONS = {"accept", "spend_luck", "push"}
_COMBAT_OPTIONS = {"dodge", "fight_back", "accept_hit"}
_NEGOTIATE_ACTIONS = {
    "talk", "persuade", "fast_talk", "intimidate", "charm", "psychology",
}
_INVESTIGATE_ACTIONS = {"search", "inspect", "listen", "spot", "read"}
_RETREAT_CAUSES = {
    "chat_only", "repeat_search", "location_exhausted", "investigation_deadlock",
    "blocked_loop", "skill_spam",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_case_id() -> str:
    return f"dc_{uuid.uuid4().hex[:16]}"


def infer_decision_type(case_or_ctx: Optional[dict]) -> str:
    """
    意思決定の性質を推定する（シナリオ名は使わない）。

    戻り値例: failure_recovery / combat_defense / npc_negotiation /
              retreat_breakout / investigation / movement / general
    """
    data = dict(case_or_ctx or {})
    # 明示指定を優先
    explicit = str(data.get("decision_type") or "").strip()
    if explicit:
        return explicit

    pending_type = str(data.get("pending_type") or data.get("type") or "").upper()
    if pending_type in ("POST_ROLL_FAILURE", "LUCK", "PUSH"):
        return "failure_recovery"
    if pending_type in ("COMBAT_DEFENSE", "SHOOT_DEFENSE"):
        return "combat_defense"

    legal = {str(x).lower() for x in (data.get("legal_options") or []) if str(x).strip()}
    chosen = data.get("chosen_action") if isinstance(data.get("chosen_action"), dict) else {}
    action = str(chosen.get("action") or chosen.get("action_id") or "").lower()
    ann = data.get("annotations") if isinstance(data.get("annotations"), dict) else {}
    cause = str(ann.get("stagnation_cause") or data.get("stagnation_cause") or "").lower()
    obs = data.get("observation") if isinstance(data.get("observation"), dict) else {}
    phase = str(obs.get("phase") or data.get("phase") or "").lower()

    if legal & _FAILURE_OPTIONS or phase in ("post_roll", "luck", "push"):
        return "failure_recovery"
    if legal & _COMBAT_OPTIONS or phase in ("combat", "defense"):
        return "combat_defense"
    if action in _NEGOTIATE_ACTIONS or (legal & _NEGOTIATE_ACTIONS):
        return "npc_negotiation"
    if (
        action == "move"
        and (cause in _RETREAT_CAUSES or data.get("roll_failed") or ann.get("forced_progress"))
    ):
        return "retreat_breakout"
    if "retreat" in cause or phase in ("retreat", "breakout"):
        return "retreat_breakout"
    if action in _INVESTIGATE_ACTIONS or (legal and legal <= (_INVESTIGATE_ACTIONS | {"move", "wait", "talk"})):
        if action in _INVESTIGATE_ACTIONS or (legal & _INVESTIGATE_ACTIONS):
            return "investigation"
    if action == "move" or (legal == {"move"} or legal == {"move", "wait"}):
        return "movement"
    return "general"


def is_high_quality_case(case: Optional[dict]) -> bool:
    """
    Few-Shot / RAG 検索対象の品質フィルタ。

    - rule_legal（legal）が True
    - knowledge_leak が False
    - 検証エラー・二重処理なし
    - 強制介入（FORCE / forced_progress）に依存していない（自律度が高い）
    """
    data = normalize_decision_case(case)
    ann = data.get("annotations") or {}
    if not ann.get("rule_legal", True):
        return False
    if ann.get("knowledge_leak"):
        return False
    if ann.get("validation_error"):
        return False
    if ann.get("duplicate_transaction"):
        return False
    if ann.get("forced_progress"):
        return False
    level = str(ann.get("intervention_level") or "none").strip().lower()
    # なし〜控えめのみ（standard / FORCE は除外＝自律度が高い事例のみ）
    if level not in _AUTONOMOUS_INTERVENTION_LEVELS:
        return False
    return True


def normalize_decision_case(raw: Optional[dict]) -> Dict[str, Any]:
    """Decision Case を正規化する。"""
    data = dict(raw or {})
    observation = data.get("observation") if isinstance(data.get("observation"), dict) else {}
    chosen = data.get("chosen_action") if isinstance(data.get("chosen_action"), dict) else {}
    annotations = data.get("annotations") if isinstance(data.get("annotations"), dict) else {}
    legal = data.get("legal_options")
    if not isinstance(legal, list):
        legal = []
    resolved = data.get("resolved_event_ids")
    if not isinstance(resolved, list):
        resolved = []

    normalized = {
        "case_id": str(data.get("case_id") or new_case_id()),
        "session_id": str(data.get("session_id") or ""),
        "actor_id": str(data.get("actor_id") or ""),
        "turn": int(data.get("turn") or 0),
        "created_at": str(data.get("created_at") or _utc_now_iso()),
        "observation": {
            "location": str(observation.get("location") or ""),
            "known_knowledge_ids": list(observation.get("known_knowledge_ids") or []),
            "public_knowledge_ids": list(observation.get("public_knowledge_ids") or []),
            "investigated_targets": list(observation.get("investigated_targets") or []),
            "phase": str(observation.get("phase") or ""),
        },
        "legal_options": [str(x) for x in legal if str(x).strip()],
        "chosen_action": {
            "action": str(chosen.get("action") or chosen.get("action_id") or ""),
            "target": str(chosen.get("target") or ""),
            "skill": str(chosen.get("skill") or ""),
            "transaction_id": str(chosen.get("transaction_id") or ""),
        },
        "resolved_event_ids": [str(x) for x in resolved if str(x).strip()],
        "annotations": {
            "rule_legal": bool(annotations.get("rule_legal", True)),
            "knowledge_leak": bool(annotations.get("knowledge_leak", False)),
            "intervention_level": str(annotations.get("intervention_level") or "none"),
            "validation_error": bool(annotations.get("validation_error", False)),
            "duplicate_transaction": bool(annotations.get("duplicate_transaction", False)),
            "forced_progress": bool(annotations.get("forced_progress", False)),
            "stagnation_cause": str(annotations.get("stagnation_cause") or ""),
            "notes": str(annotations.get("notes") or ""),
        },
        "schema_version": int(data.get("schema_version") or STORE_VERSION),
    }
    dtype = str(data.get("decision_type") or "").strip()
    if not dtype:
        dtype = infer_decision_type({
            **normalized,
            "pending_type": data.get("pending_type") or data.get("type"),
            "roll_failed": data.get("roll_failed"),
            "stagnation_cause": annotations.get("stagnation_cause"),
        })
    normalized["decision_type"] = dtype
    return normalized


def build_decision_case(
    *,
    actor_id: str,
    observation: Optional[dict] = None,
    legal_options: Optional[list] = None,
    chosen_action: Optional[dict] = None,
    resolved_event_ids: Optional[list] = None,
    annotations: Optional[dict] = None,
    session_id: str = "",
    turn: int = 0,
    case_id: str = "",
    decision_type: str = "",
) -> Dict[str, Any]:
    """Decision Case を組み立てる。"""
    return normalize_decision_case({
        "case_id": case_id or new_case_id(),
        "session_id": session_id,
        "actor_id": actor_id,
        "turn": turn,
        "observation": observation or {},
        "legal_options": legal_options or [],
        "chosen_action": chosen_action or {},
        "resolved_event_ids": resolved_event_ids or [],
        "annotations": annotations or {},
        "decision_type": decision_type,
        "created_at": _utc_now_iso(),
        "schema_version": STORE_VERSION,
    })


class DecisionCaseStore:
    """Decision Case を JSONL で追記保存し、インデックスで参照する。"""

    def __init__(
        self,
        path: str = DEFAULT_DECISION_CASES_PATH,
        index_path: str = DEFAULT_DECISION_CASES_INDEX,
    ):
        self.path = path
        self.index_path = index_path

    def ensure_initialized(self) -> None:
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        if not os.path.exists(self.path):
            with open(self.path, "w", encoding="utf-8") as fh:
                fh.write("")
        if not os.path.exists(self.index_path):
            self._write_index({"version": STORE_VERSION, "case_ids": [], "by_session": {}})

    def _read_index(self) -> dict:
        if not os.path.exists(self.index_path):
            return {"version": STORE_VERSION, "case_ids": [], "by_session": {}}
        try:
            with open(self.index_path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            if not isinstance(data, dict):
                return {"version": STORE_VERSION, "case_ids": [], "by_session": {}}
            data.setdefault("case_ids", [])
            data.setdefault("by_session", {})
            return data
        except Exception:
            return {"version": STORE_VERSION, "case_ids": [], "by_session": {}}

    def _write_index(self, data: dict) -> None:
        directory = os.path.dirname(self.index_path) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix="decision_cases_", suffix=".json", dir=directory)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self.index_path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

    def append_case(self, case: dict) -> Dict[str, Any]:
        """1件追記して正規化済みケースを返す。"""
        normalized = normalize_decision_case(case)
        with _lock:
            self.ensure_initialized()
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(normalized, ensure_ascii=False) + "\n")
            index = self._read_index()
            cid = normalized["case_id"]
            if cid not in index["case_ids"]:
                index["case_ids"].append(cid)
            sid = normalized.get("session_id") or ""
            if sid:
                bucket = index["by_session"].setdefault(sid, [])
                if cid not in bucket:
                    bucket.append(cid)
            index["version"] = STORE_VERSION
            index["updated_at"] = _utc_now_iso()
            self._write_index(index)
        return normalized

    def append_cases(self, cases: List[dict]) -> List[Dict[str, Any]]:
        saved = []
        for case in cases or []:
            saved.append(self.append_case(case))
        return saved

    def load_all(self, *, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """全ケースを読み込む（新しい順ではない・ファイル順）。"""
        self.ensure_initialized()
        rows = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(normalize_decision_case(json.loads(line)))
                except Exception:
                    continue
                if limit is not None and len(rows) >= limit:
                    break
        return rows

    def load_by_session(self, session_id: str) -> List[Dict[str, Any]]:
        sid = str(session_id or "")
        if not sid:
            return []
        return [c for c in self.load_all() if c.get("session_id") == sid]

    def has_case_id(self, case_id: str) -> bool:
        index = self._read_index()
        return str(case_id) in set(index.get("case_ids") or [])

    def load_quality_cases(self, *, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """
        Few-Shot / RAG 用: legal・非リーク・高自律度のケースのみ返す。
        """
        rows = []
        for case in self.load_all():
            if not is_high_quality_case(case):
                continue
            rows.append(case)
            if limit is not None and len(rows) >= limit:
                break
        return rows
