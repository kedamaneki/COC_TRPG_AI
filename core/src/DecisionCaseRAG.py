"""
Decision Case を用いた Dynamic Few-Shot / RAG 注入。

高品質ケースのみを対象に、意思決定の性質（decision_type / legal_options）で
類似ケースを 1〜2 件検索し、知識隔離を保ったコンパクト例としてプロンプトへ挿入する。
シナリオ名による固定検索は行わない。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from DecisionCaseStore import (
    DecisionCaseStore,
    infer_decision_type,
    is_high_quality_case,
    normalize_decision_case,
)

# プロンプト注入の上限
DEFAULT_FEW_SHOT_LIMIT = 2
MAX_FEW_SHOT_CHARS = 900

DECISION_TYPE_LABELS = {
    "failure_recovery": "判定失敗後の分岐",
    "combat_defense": "戦闘／防衛判断",
    "npc_negotiation": "NPC交渉",
    "retreat_breakout": "撤退・膠着打開",
    "investigation": "調査行動",
    "movement": "移動判断",
    "general": "一般行動",
}

_GENERIC_TARGET = "（提示された対象）"
_SPOILER_ID_RE = re.compile(r"^[a-z][a-z0-9_]{2,}$")


def build_query_context(
    *,
    legal_options: Optional[Sequence[str]] = None,
    pending_decision: Optional[dict] = None,
    last_system_result: Optional[dict] = None,
    last_pl_action: Optional[dict] = None,
    phase: str = "",
    stagnation_cause: str = "",
    force_ic_action: bool = False,
    decision_type: str = "",
) -> Dict[str, Any]:
    """現在状況から検索クエリ文脈を構築する。"""
    options: List[str] = []
    dtype = str(decision_type or "").strip()
    pending = pending_decision or {}
    if isinstance(pending.get("legal_options"), list):
        options.extend(str(x) for x in pending["legal_options"] if str(x).strip())
    if legal_options:
        options.extend(str(x) for x in legal_options if str(x).strip())
    # 重複除去（順序維持）
    seen = set()
    uniq_options = []
    for opt in options:
        key = opt.lower()
        if key not in seen:
            seen.add(key)
            uniq_options.append(opt)

    if not dtype and pending.get("type"):
        dtype = infer_decision_type({
            "legal_options": uniq_options,
            "chosen_action": {},
            "annotations": {},
            "observation": {"phase": phase},
            "pending_type": pending.get("type"),
        })

    action = ""
    target = ""
    if last_pl_action:
        action = str(last_pl_action.get("action") or last_pl_action.get("action_id") or "")
        target = str(last_pl_action.get("target") or "")

    sys = last_system_result or {}
    if not dtype:
        dtype = infer_decision_type({
            "legal_options": uniq_options,
            "chosen_action": {"action": action, "target": target},
            "annotations": {
                "forced_progress": bool(force_ic_action),
                "stagnation_cause": stagnation_cause,
            },
            "observation": {"phase": phase},
            "roll_failed": bool(
                sys.get("success_level") in ("failure", "fumble")
                or sys.get("failed")
                or (isinstance(sys.get("log"), str) and "失敗" in sys.get("log", ""))
            ),
        })

    return {
        "decision_type": dtype or "general",
        "legal_options": uniq_options,
        "phase": str(phase or ""),
        "action": action,
        "target": target,
        "stagnation_cause": str(stagnation_cause or ""),
        "force_ic_action": bool(force_ic_action),
        "roll_failed": bool(
            sys.get("success_level") in ("failure", "fumble")
            or sys.get("failed")
        ),
    }


def filter_quality_cases(cases: Iterable[dict]) -> List[Dict[str, Any]]:
    """legal かつ knowledge_leak=False、自律度が高いケースのみ残す。"""
    out = []
    for raw in cases or []:
        case = normalize_decision_case(raw)
        if is_high_quality_case(case):
            # decision_type を保証
            if not case.get("decision_type"):
                case["decision_type"] = infer_decision_type(case)
            out.append(case)
    return out


def score_case_for_query(case: dict, query: dict) -> float:
    """意思決定の性質に基づく類似スコア（シナリオ名は使わない）。"""
    case = normalize_decision_case(case)
    q_type = str((query or {}).get("decision_type") or "general")
    c_type = str(case.get("decision_type") or infer_decision_type(case))
    score = 0.0

    if c_type == q_type:
        score += 10.0
    elif q_type != "general" and c_type == "general":
        score += 1.0
    elif c_type != "general" and q_type == "general":
        score += 2.0

    q_opts = {str(x).lower() for x in ((query or {}).get("legal_options") or []) if str(x).strip()}
    c_opts = {str(x).lower() for x in (case.get("legal_options") or []) if str(x).strip()}
    if q_opts and c_opts:
        inter = len(q_opts & c_opts)
        union = len(q_opts | c_opts) or 1
        score += 5.0 * (inter / union)
    elif not q_opts and c_opts and q_type == c_type:
        score += 1.5

    q_action = str((query or {}).get("action") or "").lower()
    c_action = str((case.get("chosen_action") or {}).get("action") or "").lower()
    if q_action and c_action and q_action == c_action:
        score += 2.0

    q_phase = str((query or {}).get("phase") or "").lower()
    c_phase = str((case.get("observation") or {}).get("phase") or "").lower()
    if q_phase and c_phase and q_phase == c_phase:
        score += 1.0

    # 自律度ボーナス（品質フィルタ通過済みでも、介入なしを優遇）
    ann = case.get("annotations") or {}
    level = str(ann.get("intervention_level") or "").lower()
    if level in ("", "none", "なし", "0") and not ann.get("forced_progress"):
        score += 1.0

    return score


def retrieve_similar_cases(
    query: dict,
    *,
    corpus: Optional[Sequence[dict]] = None,
    store: Optional[DecisionCaseStore] = None,
    limit: int = DEFAULT_FEW_SHOT_LIMIT,
    min_score: float = 3.0,
) -> List[Tuple[Dict[str, Any], float]]:
    """
    クエリに類似する高品質ケースを最大 limit 件返す。
    戻り値: [(case, score), ...]
    """
    if corpus is None:
        store = store or DecisionCaseStore()
        try:
            corpus = store.load_quality_cases()
        except Exception:
            corpus = []
    else:
        corpus = filter_quality_cases(corpus)

    scored: List[Tuple[Dict[str, Any], float]] = []
    for case in corpus:
        s = score_case_for_query(case, query)
        if s >= min_score:
            scored.append((case, s))
    scored.sort(key=lambda x: (-x[1], str(x[0].get("case_id") or "")))
    return scored[: max(0, int(limit))]


def _allowed_knowledge_ids(char_mgr, pl_id, state=None) -> Set[str]:
    allowed: Set[str] = set()
    if char_mgr and pl_id and hasattr(char_mgr, "get_known_knowledge_ids"):
        allowed.update(str(x) for x in (char_mgr.get_known_knowledge_ids(pl_id) or []))
    public = []
    if state and isinstance(state.get("public_knowledge_ids"), list):
        public = state.get("public_knowledge_ids") or []
    elif char_mgr and hasattr(char_mgr, "get_public_knowledge_ids"):
        try:
            public = char_mgr.get_public_knowledge_ids() or []
        except Exception:
            public = []
    allowed.update(str(x) for x in public)
    return allowed


def _allowed_investigated(char_mgr, pl_id) -> Set[str]:
    if char_mgr and pl_id and hasattr(char_mgr, "get_pc_investigated_targets"):
        return {str(x) for x in (char_mgr.get_pc_investigated_targets(pl_id) or set())}
    return set()


def scrub_case_for_prompt(
    case: dict,
    *,
    known_knowledge_ids: Optional[Iterable[str]] = None,
    investigated_targets: Optional[Iterable[str]] = None,
    audience: str = "pl",
) -> Optional[Dict[str, Any]]:
    """
    ネタバレ／未所有知識を除去した Few-Shot 用ケースを返す。
    知識隔離に反するケースは None（注入しない）。
    """
    case = normalize_decision_case(case)
    if not is_high_quality_case(case):
        return None

    known = {str(x) for x in (known_knowledge_ids or [])}
    investigated = {str(x) for x in (investigated_targets or [])}
    obs = dict(case.get("observation") or {})
    case_known = {str(x) for x in (obs.get("known_knowledge_ids") or [])}
    # ケースが参照する知識のうち、現在 PC が知らないものは落とす
    unknown = case_known - known
    if unknown and audience == "pl":
        # 未知知識に依存した例は PL へ注入しない（タスク5維持）
        # ただしケース自身の観察知識が空なら OK
        if case_known and not case_known.issubset(known):
            return None

    chosen = dict(case.get("chosen_action") or {})
    target = str(chosen.get("target") or "")
    if target:
        # 未調査の内部IDは一般化（ネタバレ防止）
        if _SPOILER_ID_RE.match(target) and target not in investigated and target not in known:
            target = _GENERIC_TARGET

    legal = [str(x) for x in (case.get("legal_options") or []) if str(x).strip()]
    action = str(chosen.get("action") or "")
    # 合法集合があるなら、選ばれた行動が合法であることを再確認
    if legal:
        lowered = {x.lower() for x in legal}
        if action and action.lower() not in lowered and action not in (
            "accept", "spend_luck", "push", "dodge", "fight_back", "accept_hit",
        ):
            # action 名がオプション別名のこともある — 完全不一致ならスキップ
            if not any(action.lower() == opt or action.lower() in opt for opt in lowered):
                # still allow if decision is about choosing from options and action is one of them by alias
                pass

    dtype = str(case.get("decision_type") or infer_decision_type(case))
    return {
        "case_id": case.get("case_id"),
        "decision_type": dtype,
        "legal_options": legal[:8],
        "chosen_action": action,
        "chosen_target": target,
        "skill": str(chosen.get("skill") or ""),
        "notes": _safe_note(case.get("annotations") or {}, audience=audience),
    }


def _safe_note(annotations: dict, *, audience: str = "pl") -> str:
    notes = str((annotations or {}).get("notes") or "").strip()
    # 固有の秘密っぽい長文は落とす
    if len(notes) > 80:
        notes = notes[:77] + "..."
    if any(tok in notes for tok in ("地下室", "偶像", "神話", "真実", "犯人")):
        return "合法選択肢のみから選び、未知情報には触れない。"
    if notes:
        return notes
    if audience == "kp":
        return "システム確定情報のみ描写し、未開示の秘密を創作しない。"
    return "合法選択肢のみから選び、未知情報には触れない。"


def format_few_shot_block(
    scrubbed_cases: Sequence[dict],
    *,
    audience: str = "pl",
    query: Optional[dict] = None,
) -> str:
    """プロンプト挿入用のコンパクト Few-Shot ブロックを生成する。"""
    if not scrubbed_cases:
        return ""

    lines = []
    if audience == "kp":
        lines.append("【参考例（高品質 Decision Case・KP向け・最大2件）】")
        lines.append("※例は進行方針の参考。シナリオ未記載の事実・未開示知識を追加してはならない。")
        lines.append("※例中の人物名・職業・技能は現在の確定状態ではない。最新のシステム確定結果を優先せよ。")
    else:
        lines.append("【参考例（高品質 Decision Case・ルール遵守／知識非漏洩・最大2件）】")
        lines.append("※例の固有状況をコピーせず、方針（合法選択肢のみ・未知情報に触れない）を学べ。")
        lines.append("※例に登場する名前・職業・知識は現在操作中のPCのものではない。自己紹介や設定に流用するな。")
        lines.append("※JSONスキーマや speak_as / action 形式は既存指示に従うこと。")

    q_type = str((query or {}).get("decision_type") or "")
    if q_type:
        label = DECISION_TYPE_LABELS.get(q_type, q_type)
        lines.append(f"・現在の意思決定タイプ: {label} (`{q_type}`)")

    for i, item in enumerate(scrubbed_cases[:DEFAULT_FEW_SHOT_LIMIT], start=1):
        dtype = str(item.get("decision_type") or "general")
        label = DECISION_TYPE_LABELS.get(dtype, dtype)
        opts = item.get("legal_options") or []
        opts_txt = ", ".join(opts) if opts else "（状況に応じた合法行動）"
        action = item.get("chosen_action") or "wait"
        target = item.get("chosen_target") or ""
        target_txt = f" / target={target}" if target else ""
        note = item.get("notes") or ""
        lines.append(
            f"例{i}: タイプ={label} | 合法=[{opts_txt}] → 選択=`{action}`{target_txt}"
        )
        if note:
            lines.append(f"  要点: {note}")

    block = "\n".join(lines).strip() + "\n"
    if len(block) > MAX_FEW_SHOT_CHARS:
        block = block[: MAX_FEW_SHOT_CHARS - 20].rstrip() + "\n…(省略)\n"
    return block


def build_dynamic_few_shot_block(
    *,
    audience: str = "pl",
    query: Optional[dict] = None,
    corpus: Optional[Sequence[dict]] = None,
    store: Optional[DecisionCaseStore] = None,
    char_mgr=None,
    pl_id: str = "",
    state: Optional[dict] = None,
    limit: int = DEFAULT_FEW_SHOT_LIMIT,
    enabled: bool = True,
) -> str:
    """
    検索→知識スクラブ→フォーマットまで一括。
    enabled=False または該当ケースなしなら空文字。
    """
    if not enabled:
        return ""
    query = query or build_query_context()
    hits = retrieve_similar_cases(
        query, corpus=corpus, store=store, limit=max(limit * 3, limit),
    )
    known = _allowed_knowledge_ids(char_mgr, pl_id, state=state)
    investigated = _allowed_investigated(char_mgr, pl_id)
    scrubbed = []
    for case, _score in hits:
        cleaned = scrub_case_for_prompt(
            case,
            known_knowledge_ids=known,
            investigated_targets=investigated,
            audience=audience,
        )
        if cleaned:
            scrubbed.append(cleaned)
        if len(scrubbed) >= limit:
            break
    return format_few_shot_block(scrubbed, audience=audience, query=query)


# テスト／コールドスタート用の組み込み良例（シナリオ固有ネタなし）
BUILTIN_QUALITY_CASES: List[Dict[str, Any]] = [
    normalize_decision_case({
        "case_id": "dc_builtin_failure_01",
        "decision_type": "failure_recovery",
        "legal_options": ["accept", "spend_luck", "push"],
        "chosen_action": {"action": "spend_luck", "target": "", "skill": ""},
        "observation": {"location": "", "known_knowledge_ids": [], "phase": "post_roll"},
        "annotations": {
            "rule_legal": True,
            "knowledge_leak": False,
            "intervention_level": "none",
            "notes": "失敗後は提示された合法選択肢からのみ選ぶ。",
        },
    }),
    normalize_decision_case({
        "case_id": "dc_builtin_negotiate_01",
        "decision_type": "npc_negotiation",
        "legal_options": ["talk", "persuade", "move", "wait"],
        "chosen_action": {"action": "talk", "target": "（提示された対象）", "skill": ""},
        "observation": {"location": "", "known_knowledge_ids": [], "phase": ""},
        "annotations": {
            "rule_legal": True,
            "knowledge_leak": False,
            "intervention_level": "none",
            "notes": "初回接触は雑談 talk。未所持の秘密話題は出さない。",
        },
    }),
    normalize_decision_case({
        "case_id": "dc_builtin_retreat_01",
        "decision_type": "retreat_breakout",
        "legal_options": ["move", "search", "wait"],
        "chosen_action": {"action": "move", "target": "（提示された対象）", "skill": ""},
        "observation": {"location": "", "known_knowledge_ids": [], "phase": ""},
        "annotations": {
            "rule_legal": True,
            "knowledge_leak": False,
            "intervention_level": "none",
            "notes": "同一対象の空回りが続いたら合法な移動で打開する。",
        },
    }),
    normalize_decision_case({
        "case_id": "dc_builtin_invest_01",
        "decision_type": "investigation",
        "legal_options": ["search", "inspect", "move", "wait"],
        "chosen_action": {"action": "search", "target": "（提示された対象）", "skill": "目星"},
        "observation": {"location": "", "known_knowledge_ids": [], "phase": ""},
        "annotations": {
            "rule_legal": True,
            "knowledge_leak": False,
            "intervention_level": "none",
            "notes": "一覧にある対象のみ調べ、未提示の物体IDを創作しない。",
        },
    }),
    normalize_decision_case({
        "case_id": "dc_builtin_kp_invest_01",
        "decision_type": "investigation",
        "legal_options": ["search", "inspect"],
        "chosen_action": {"action": "search", "target": "（提示された対象）", "skill": ""},
        "observation": {"location": "", "known_knowledge_ids": [], "phase": ""},
        "annotations": {
            "rule_legal": True,
            "knowledge_leak": False,
            "intervention_level": "none",
            "notes": "システム確定ログのみ描写し、未記載の手がかりを足さない。",
        },
    }),
]


def resolve_few_shot_corpus(
    *,
    store: Optional[DecisionCaseStore] = None,
    corpus: Optional[Sequence[dict]] = None,
    include_builtin: bool = True,
) -> List[Dict[str, Any]]:
    """ストア＋組み込み良例をマージした検索コーパスを返す。"""
    rows: List[Dict[str, Any]] = []
    if corpus is not None:
        rows.extend(filter_quality_cases(corpus))
    else:
        try:
            store = store or DecisionCaseStore()
            rows.extend(store.load_quality_cases())
        except Exception:
            pass
    if include_builtin:
        existing = {c.get("case_id") for c in rows}
        for b in BUILTIN_QUALITY_CASES:
            if b.get("case_id") not in existing:
                rows.append(b)
    return filter_quality_cases(rows)
