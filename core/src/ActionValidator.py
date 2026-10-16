"""
PL行動の厳密バリデーション（移動意図の一致・対人対象の調査禁止）。

エラー時は PL へ再生成を促すシステム通知文を返す。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# システム通知文（PL / KP へ渡す定型メッセージ）
# ---------------------------------------------------------------------------

MOVE_INTENT_MISMATCH_ERROR = (
    "【システム検証エラー・行動再選択】"
    "セリフ／OOCで示した移動希望先と、コマンドの move target が一致していません。"
    "dialogue / pl_ooc_chat の目的地と `pc_ic_action.target` を一致させて、行動JSONを出し直してください。"
)

MOVE_MISSING_TARGET_ERROR = (
    "【システム検証エラー・行動再選択】"
    "move アクションの target が空です。"
    "別の場所へ行くなら、解放済みロケーションの ID を target に指定してください。"
    "今いる場所の物体を調べるなら action は search / inspect です。"
)

MOVE_SAME_LOCATION_ERROR = (
    "【システム検証エラー・行動再選択】"
    "いまいる場所への移動は無効です。"
    "別の解放済みロケーションへ `move` するか、"
    "現在地のオブジェクトを `search` / `inspect` / `talk` してください。"
)

ABSENT_NPC_TALK_RETRY_ERROR = (
    "【システム検証エラー・行動再選択】"
    "その人物は現在この場所にいません。"
    "現在地にいる NPC へ正しい target で talk するか、"
    "周囲のオブジェクトを search / inspect してください。"
)

PUSH_ROLL_UNAVAILABLE_ERROR = (
    "【システム検証エラー・行動再選択】"
    "現在プッシュロール可能な失敗判定はありません。"
    "成功後の深掘りや『慎重にもう一度』は通常の search / inspect / break / climb 等を使ってください。"
    "プッシュは直前の失敗判定が保留中のときのみ `push_roll` が使えます。"
)

# 推奨修正がある検証エラーは、LLM再生成より先に自動補正する
# 自動補正は「形式誤り・対象取り違え」に限定する。
# 会話／方針発言／移動の推測実行は自動補正しない。
VALIDATION_AUTO_CORRECT_CODES = frozenset({
    "move_missing_target",
    "move_non_location_destination",
})

# ---------------------------------------------------------------------------
# プレイヤー意図の構造化解釈（LLM候補とは分離し、Python側で確定する）
# ---------------------------------------------------------------------------

INTENT_ACTION_REQUEST = "ACTION_REQUEST"
INTENT_DISCUSSION_OR_PLAN = "DISCUSSION_OR_PLAN"
INTENT_IN_CHARACTER_DIALOGUE = "IN_CHARACTER_DIALOGUE"
INTENT_UNCLEAR = "UNCLEAR"

INTENT_TYPES = frozenset({
    INTENT_ACTION_REQUEST,
    INTENT_DISCUSSION_OR_PLAN,
    INTENT_IN_CHARACTER_DIALOGUE,
    INTENT_UNCLEAR,
})

_DISCUSSION_OR_PLAN_MARKERS = (
    "方がよさそう", "方が良さそう", "方がいい", "方が良い",
    "した方が", "移った方が", "移動した方が", "行った方が",
    "かもしれない", "かもしれません", "べきだ", "べきだろう",
    "十分そう", "十分だ", "十分だろう", "足りそう",
    "別の方法", "他の方法", "考えるべき", "考えた方が",
    "よさそうだ", "良さそうだ", "いいだろう", "良いだろう",
    "他の場所へ移", "別の場所へ移", "次の調査先を検討",
    "方針を", "作戦を", "相談し",
    # 日本語の曖昧提案（動詞なしの相談）
    "どうだろう", "どうかな", "のはどう",
    "そろそろ移動", "次は近所",
    # 英語の方針・提案
    "i think we should", "we should leave", "we should go",
    "maybe ", "perhaps ", "should we ", "how about ",
)

# 方針口調でも「動詞＋対象」が明確なら実行候補にする提案マーカー
_PROPOSAL_TALK_MARKERS = (
    "聞いてみ", "聞いてみる", "聞いてみよう", "聞いてみるのは",
    "尋ねてみ", "尋ねてみる", "尋ねてみよう",
    "話してみ", "話してみよう", "聞いてみるのはどう",
    "交渉してみ", "説得してみ", "質問してみ",
    "ask about", "ask the", "talk to", "speak to", "how about asking",
)

_PROPOSAL_SEARCH_MARKERS = (
    "調べてみ", "調べてみる", "調べてみよう", "調べようか",
    "見てみ", "見てみる", "見てみよう", "見てみようか",
    "確認してみ", "確認しよう", "もう少し調べ", "もう少し見",
    "資料を確認", "資料を調べ", "資料をもう少し",
    "maybe investigate", "perhaps investigate", "how about investigating",
    "should investigate", "look into", "take a look",
)

_PERSON_ROLE_MARKERS = (
    "事務官", "受付", "店員", "警官", "警備", "館員", "司書",
    "clerk", "receptionist", "librarian", "officer", "guard",
)

_EXPLICIT_MOVE_MARKERS = (
    "移動する", "移動します", "移動しよう", "移動しましょう",
    "向かう", "向かおう", "向かいます", "向かいましょう",
    "行く", "行こう", "行きます", "行きましょう",
    "出発する", "出発します", "赴く", "訪ねる", "訪ねます",
    "へ向か", "に向か", "へ移動", "に移動", "へと向か",
    # English
    "move to", "go to", "let's go", "lets go", "head to", "heading to",
)

_EXPLICIT_SEARCH_MARKERS = (
    "調べる", "調べます", "調べよう", "調査する", "調査します",
    "探索する", "探索します", "検索する", "読み込む", "読んでみる",
    "確認する", "確認します", "漁る", "探す", "探します",
    # English
    "investigate", "search for", "search the", "examine", "look through",
    "look at", "check the",
)

_EXPLICIT_TALK_MARKERS = (
    "聞く", "聞きます", "尋ねる", "尋ねます", "質問する", "質問します",
    "話しかける", "話しかけます", "話す", "話します", "問う",
    "交渉する", "説得する", "言いくるめ", "聞き出す", "情報提供を求め",
    # English
    "ask the", "ask about", "talk to", "speak to", "speak with", "question the",
)

_COURTESY_DIALOGUE_MARKERS = (
    "礼を言う", "お礼", "ありがとう", "感謝", "挨拶", "こんにちは",
    "失礼します", "よろしくお願いします", "失礼いたしました",
    "thank you", "thanks", "hello", "excuse me",
)

_AMBIGUOUS_MOVE_MARKERS = (
    "どこかへ", "別の場所", "他の場所", "よそへ", "移ろうか",
    "移動しようか", "行った方が", "移った方が",
    "そろそろ移動", "次は近所", "図書館かな", "近所か",
    "should leave", "we should leave", "leave?", "maybe leave",
)

# 文末・短文の曖昧提案（即時実行しない）
# ※ 「〜ですか？」一般疑問は含めない（会話質問を潰すため）
_SOFT_SUGGESTION_RE = re.compile(
    r"(?:"
    r"かな[？?！!。．…]*$|"
    r"そろそろ移動[？?！!。．…]*$|"
    r"次は.{0,12}か[？?！!。．…]*$|"
    r"どうだろう[？?！!。．…]*$|"
    r"どうかな[？?！!。．…]*$|"
    r"のはどう(?:だろう)?[？?！!。．…]*$|"
    r"\b(?:maybe|perhaps)\b|"
    r"\bi think we should\b|"
    r"\bwe should\b|"
    r"\bshould we\b|"
    r"\bhow about\b"
    r")",
    re.IGNORECASE,
)


def _intent_evidence(text: str, markers: Sequence[str], limit: int = 4) -> List[str]:
    text_l = str(text or "")
    text_cf = text_l.casefold()
    hits = []
    for m in markers:
        if not m:
            continue
        if m in text_l or m.casefold() in text_cf:
            hits.append(m)
        if len(hits) >= limit:
            break
    return hits


def _text_has_marker(text: str, markers: Sequence[str]) -> bool:
    text_l = str(text or "")
    text_cf = text_l.casefold()
    return any(m and (m in text_l or m.casefold() in text_cf) for m in markers)


def is_soft_suggestion_text(text: str) -> bool:
    """短文・文末の曖昧提案（『〜かな』『Maybe …』等）。"""
    text = str(text or "").strip()
    if not text:
        return False
    if _SOFT_SUGGESTION_RE.search(text):
        return True
    # 超短文の行き先だけの呟き（「図書館かな」は上で捕捉）
    if re.fullmatch(r".{1,12}か[？?！!。．…]*", text) and not _text_has_marker(
        text, _EXPLICIT_MOVE_MARKERS + _EXPLICIT_SEARCH_MARKERS + _EXPLICIT_TALK_MARKERS
    ):
        # 「ありますか？」のような一般疑問は除外
        if not re.search(r"(です|ます|ました|ない|いる|ある)か[？?]?$", text):
            return True
    return False


def has_explicit_move_expression(text: str) -> bool:
    """即時実行可能な移動表現があるか（方針発言の『方がよさそう』は除外）。"""
    text = str(text or "")
    if not text.strip():
        return False
    if is_soft_suggestion_text(text) and not _text_has_marker(
        text, ("移動します", "向かいます", "行きます", "move to", "go to", "let's go", "lets go")
    ):
        return False
    if _text_has_marker(text, _DISCUSSION_OR_PLAN_MARKERS) and not _text_has_marker(
        text, ("移動します", "向かいます", "行きます", "向かおう", "行こう", "移動する", "向かう",
               "move to", "go to", "let's go", "lets go", "head to")
    ):
        # 「移動した方がよさそう」は方針。明示実行形が併記されていなければ非実行。
        if any(m in text for m in ("方が", "べき", "かもしれない", "十分", "どうだろう", "かな")):
            return False
        if re.search(r"\b(maybe|perhaps|should|think)\b", text, re.I):
            return False
    return _text_has_marker(text, _EXPLICIT_MOVE_MARKERS)


def is_discussion_or_plan_text(text: str) -> bool:
    """方針・相談・感想であり、即時の行動命令ではないか。"""
    text = str(text or "").strip()
    if not text:
        return False
    if has_explicit_move_expression(text):
        # 「中央図書館へ向かおう」「move to the library」は実行命令
        return False
    if is_soft_suggestion_text(text):
        return True
    if _text_has_marker(text, _EXPLICIT_SEARCH_MARKERS) and not any(
        m in text for m in ("方が", "べき", "かもしれない", "十分そう", "十分だ")
    ) and not re.search(r"\b(maybe|perhaps|should|think)\b", text, re.I):
        return False
    if _text_has_marker(text, _EXPLICIT_TALK_MARKERS) and not any(
        m in text for m in ("方が", "べき", "かもしれない", "どうだろう", "のはどう")
    ) and not re.search(r"\b(maybe|perhaps|should|think|how about)\b", text, re.I):
        return False
    return _text_has_marker(text, _DISCUSSION_OR_PLAN_MARKERS) or is_soft_suggestion_text(text)


def is_courtesy_dialogue_text(text: str) -> bool:
    return _text_has_marker(text, _COURTESY_DIALOGUE_MARKERS)


def is_pure_consultation_text(text: str) -> bool:
    """
    対象・動作が特定できない純粋な相談・感想か。
    動詞＋対象が明確な提案は False（実行候補側へ回す）。
    """
    text = str(text or "").strip()
    if not text:
        # 空発話は相談ではない（proposed_action の後段処理へ）
        return False
    if classify_actionable_proposal(text):
        return False
    if has_explicit_move_expression(text):
        return False
    if _text_has_marker(text, _EXPLICIT_SEARCH_MARKERS) and not any(
        m in text for m in ("方が", "べき", "かもしれない", "十分そう", "十分だ")
    ):
        return False
    if _text_has_marker(text, _EXPLICIT_TALK_MARKERS) and not any(
        m in text for m in ("方が", "べき", "かもしれない")
    ):
        # 「どうだろう」付きでも動詞＋相手がいれば提案扱い（上で捕捉済み）
        return False
    return is_discussion_or_plan_text(text) or is_soft_suggestion_text(text)


def _resolve_proposal_npc_id(text: str, char_mgr=None, proposed_target: str = "") -> str:
    target = str(proposed_target or "").strip()
    if target:
        return target
    if char_mgr:
        try:
            from NPCSocialManager import find_npc_id_from_intent_text
            found = find_npc_id_from_intent_text(char_mgr, text)
            if found:
                return str(found)
        except Exception:
            pass
    return ""


def _resolve_proposal_search_target(
    text: str,
    *,
    scenario_mgr=None,
    current_loc: str = "",
    proposed_target: str = "",
) -> str:
    target = str(proposed_target or "").strip()
    loc_ids = set()
    if scenario_mgr:
        try:
            loc_ids = set(scenario_mgr.get_all_location_ids() or [])
        except Exception:
            loc_ids = set()
    # ロケーションIDは search 対象にしない（move の誤 target 流用を防ぐ）
    if target in loc_ids:
        target = ""
    if target:
        return target
    if not scenario_mgr:
        return ""
    objects = (scenario_mgr.get_location_info(current_loc) or {}).get("objects") or {}
    flags = getattr(scenario_mgr, "flags", None) or {}
    for obj_id, obj in objects.items():
        if not isinstance(obj, dict):
            continue
        if not object_is_currently_available(obj, flags):
            continue
        keywords = [str(obj.get("name") or ""), str(obj_id)]
        keywords.extend(str(a) for a in (obj.get("aliases") or []) if a)
        keywords = [k for k in keywords if k and len(k) >= 2]
        if _text_has_any(text, keywords):
            return str(obj_id)
    non_locs = collect_intent_non_location_targets(text)
    if non_locs:
        return non_locs[0]
    # 「資料をもう少し調べようか」等: 固有名がなくても現在地の未調査オブジェクトを候補化
    if any(k in text for k in ("資料", "記録", "文書", "アーカイブ", "archive", "records", "files", "調べ", "確認", "見てみ")):
        for obj_id, obj in objects.items():
            if not isinstance(obj, dict):
                continue
            if not object_is_currently_available(obj, flags):
                continue
            if object_is_investigated(scenario_mgr, str(obj_id), obj, flags):
                continue
            usable = obj.get("usable_actions") or ["search"]
            if "search" in usable or "inspect" in usable:
                return str(obj_id)
    return ""


def classify_actionable_proposal(
    text: str = "",
    *,
    scenario_mgr=None,
    current_loc: str = "",
    char_mgr=None,
    proposed_target: str = "",
) -> Optional[Dict[str, Any]]:
    """
    方針口調でも動詞と対象が明確なら talk / search / move の実行候補を返す。
    純粋な相談・感想（「図書館かな」等）は None。
    """
    text = str(text or "").strip()
    if not text:
        return None

    # 方針だけの移動（「移った方がよさそう」）は候補化しない
    soft_plan_only = any(m in text for m in ("方が", "べきだ", "べきだろう", "十分そう", "十分だ"))
    if soft_plan_only and not _text_has_marker(
        text, _PROPOSAL_TALK_MARKERS + _PROPOSAL_SEARCH_MARKERS + _EXPLICIT_TALK_MARKERS + _EXPLICIT_SEARCH_MARKERS
    ):
        return None

    # talk 提案: 「事務官に聞いてみるのはどうだろう」等
    if _text_has_marker(text, _PROPOSAL_TALK_MARKERS + _EXPLICIT_TALK_MARKERS):
        npc = _resolve_proposal_npc_id(text, char_mgr=char_mgr, proposed_target=proposed_target)
        if npc or _text_has_marker(text, _PERSON_ROLE_MARKERS):
            return {
                "action": "talk",
                "target": npc,
                "kind": "proposal",
                "evidence": _intent_evidence(text, _PROPOSAL_TALK_MARKERS + _EXPLICIT_TALK_MARKERS)
                or _intent_evidence(text, _PERSON_ROLE_MARKERS),
            }

    # search 提案: 「資料をもう少し調べようか」「図書館を調べてみようか」
    if _text_has_marker(text, _PROPOSAL_SEARCH_MARKERS + _EXPLICIT_SEARCH_MARKERS):
        # 移動複合は後段で処理
        if not re.search(r"(へ|に)行って.{0,12}(調べ|確認|見)", text):
            st = _resolve_proposal_search_target(
                text,
                scenario_mgr=scenario_mgr,
                current_loc=current_loc,
                proposed_target=proposed_target,
            )
            # 地名＋調査で現在地外なら search 候補（実行段で別地点チェック）
            if not st:
                dests = collect_intent_destination_ids(text, scenario_mgr, current_loc)
                if not dests:
                    dests = [
                        loc for loc in collect_intent_location_ids(text, scenario_mgr)
                        if loc != current_loc
                    ]
                # 「図書館を調べてみようか」は対象テキストを残す
                if dests or any(k in text for k in ("資料", "記録", "図書館", "archive", "library")):
                    return {
                        "action": "search",
                        "target": st or (dests[0] if dests else ""),
                        "kind": "proposal",
                        "evidence": _intent_evidence(
                            text, _PROPOSAL_SEARCH_MARKERS + _EXPLICIT_SEARCH_MARKERS
                        ),
                    }
            return {
                "action": "search",
                "target": st,
                "kind": "proposal",
                "evidence": _intent_evidence(text, _PROPOSAL_SEARCH_MARKERS + _EXPLICIT_SEARCH_MARKERS),
            }

    # 「図書館へ行って調べよう」→ 移動候補（調査は到着後）
    if re.search(r"(へ|に)(行って|向かって).{0,12}(調べ|確認|見)", text) or "行って調べ" in text:
        dests = collect_intent_destination_ids(text, scenario_mgr, current_loc)
        if not dests:
            dests = [
                loc for loc in collect_intent_location_ids(text, scenario_mgr)
                if loc != current_loc
            ]
        if dests:
            return {
                "action": "move",
                "target": dests[0],
                "kind": "proposal",
                "evidence": ["行って調べ"],
            }

    return None


def summarize_intent_context(intent_context: Optional[Dict[str, Any]] = None) -> str:
    """解釈用に直近文脈を短くまとめる（無制限ログは付けない）。"""
    ctx = intent_context or {}
    parts: List[str] = []
    for key, label in (
        ("recent_kp", "KP"),
        ("recent_npc", "NPC"),
        ("recent_player", "PL"),
    ):
        vals = ctx.get(key) or []
        if isinstance(vals, str):
            vals = [vals]
        for v in list(vals)[-2:]:
            s = str(v or "").strip()
            if s:
                parts.append(f"{label}:{s[:120]}")
    if ctx.get("current_loc"):
        parts.append(f"loc:{ctx.get('current_loc')}")
    if ctx.get("phase"):
        parts.append(f"phase:{ctx.get('phase')}")
    last = ctx.get("last_action") or {}
    if isinstance(last, dict) and (last.get("action") or last.get("target")):
        parts.append(f"last:{last.get('action')}/{last.get('target')}")
    npcs = ctx.get("npcs_here") or []
    if npcs:
        parts.append("npcs:" + ",".join(str(x) for x in list(npcs)[:6]))
    objs = ctx.get("objects_here") or []
    if objs:
        parts.append("objs:" + ",".join(str(x) for x in list(objs)[:6]))
    return " | ".join(parts)


def interpret_player_intent(
    text: str = "",
    *,
    proposed_action: str = "",
    proposed_target: str = "",
    pl_ooc: str = "",
    scenario_mgr=None,
    current_loc: str = "",
    char_mgr=None,
    intent_context: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    プレイヤー発話を構造化意図へ解釈する（実行は別段で確定する）。

    Returns:
        intent_type / action / target_text / purpose / explicitness /
        confidence / evidence / do_not_execute / notes
    """
    dialogue = str(text or "").strip()
    ooc = str(pl_ooc or "").strip()
    combined = f"{dialogue} {ooc}".strip()
    proposed_action = str(proposed_action or "wait").lower() or "wait"
    proposed_target = str(proposed_target or "").strip()
    current_loc = str(current_loc or "")
    ctx = intent_context or {}
    context_summary = summarize_intent_context(ctx)

    # focus_npc は会話・返答の補完専用。move/search の proposed_target には流用しない。
    focus_npc = str(ctx.get("focus_npc") or "").strip()

    result: Dict[str, Any] = {
        "intent_type": INTENT_UNCLEAR,
        "action": "wait",
        "target_text": proposed_target or "",
        "purpose": "",
        "explicitness": "unclear",
        "confidence": 0.4,
        "evidence": [],
        "do_not_execute": False,
        "notes": "",
        "context_summary": context_summary,
    }

    if not combined and proposed_action in ("", "wait", "none"):
        result.update({
            "intent_type": INTENT_UNCLEAR,
            "do_not_execute": True,
            "notes": "発話が空で行動も wait",
            "confidence": 0.2,
        })
        return result

    # 0) 行動を含む提案（方針口調でも動詞＋対象が明確なら wait にしない）
    proposal = classify_actionable_proposal(
        combined,
        scenario_mgr=scenario_mgr,
        current_loc=current_loc,
        char_mgr=char_mgr,
        proposed_target=proposed_target,
    )
    loc_ids = set()
    if scenario_mgr:
        try:
            loc_ids = set(scenario_mgr.get_all_location_ids() or [])
        except Exception:
            loc_ids = set()
    # 地点付き move は search へ置換せず検証層へ（目的地不一致の再生成を維持）
    defer_move_validation = (
        proposed_action == "move" and bool(proposed_target) and proposed_target in loc_ids
    )
    if proposal and not (
        defer_move_validation and str(proposal.get("action") or "") == "search"
    ):
        prop_action = str(proposal.get("action") or "")
        prop_target = str(proposal.get("target") or "")
        if prop_action == "search" and prop_target in loc_ids:
            prop_target = _resolve_proposal_search_target(
                combined,
                scenario_mgr=scenario_mgr,
                current_loc=current_loc,
                proposed_target="",
            )
        result.update({
            "intent_type": INTENT_ACTION_REQUEST,
            "action": prop_action or "wait",
            "target_text": prop_target or (
                "" if prop_action == "search" else proposed_target
            ),
            "purpose": "行動を含む提案（実行候補）",
            "explicitness": "soft",
            "confidence": 0.86,
            "evidence": proposal.get("evidence") or [],
            "do_not_execute": False,
            "notes": "DISCUSSION口調だが動詞と対象が明確なため実行候補化",
            "actionable_proposal": True,
        })
        return result

    # 1) 純粋な方針・相談・感想のみ wait（対象も動作もない）
    if is_pure_consultation_text(combined):
        evidence = _intent_evidence(combined, _DISCUSSION_OR_PLAN_MARKERS)
        if is_soft_suggestion_text(combined) and not evidence:
            evidence = ["soft_suggestion"]
        dests = collect_intent_destination_ids(combined, scenario_mgr, current_loc)
        if not dests:
            dests = [
                loc for loc in collect_intent_location_ids(combined, scenario_mgr)
                if loc != current_loc
            ]
        result.update({
            "intent_type": INTENT_DISCUSSION_OR_PLAN,
            "action": "wait",
            "target_text": dests[0] if dests else proposed_target,
            "purpose": "方針・相談の表明",
            "explicitness": "soft",
            "confidence": 0.9,
            "evidence": evidence,
            "do_not_execute": True,
            "notes": "対象・動作が特定できない相談のため即時実行しない",
            "suggested_destinations": dests,
        })
        return result

    # 2) 明示的な移動命令
    if has_explicit_move_expression(combined) or proposed_action == "move":
        dests = collect_intent_destination_ids(combined, scenario_mgr, current_loc)
        target = proposed_target
        # 発話の目的地を優先（NPC ID 等の非ロケーション混入を上書き）
        if dests and (not target or target == current_loc or target not in loc_ids):
            target = dests[0]
        if (
            dests
            and target in loc_ids
            and target not in dests
            and has_explicit_move_expression(combined)
        ):
            target = dests[0]
        explicit = has_explicit_move_expression(combined)
        if explicit and target and target != current_loc and (not loc_ids or target in loc_ids):
            result.update({
                "intent_type": INTENT_ACTION_REQUEST,
                "action": "move",
                "target_text": target,
                "purpose": "ロケーション移動",
                "explicitness": "explicit",
                "confidence": 0.93,
                "evidence": _intent_evidence(combined, _EXPLICIT_MOVE_MARKERS) or dests[:2],
                "do_not_execute": False,
            })
            return result
        if proposed_action == "move" and not explicit:
            # 発話が空の move は既存の validate / auto-correct に委ねる
            if not combined.strip():
                result.update({
                    "intent_type": INTENT_ACTION_REQUEST,
                    "action": "move",
                    "target_text": target or (dests[0] if dests else ""),
                    "purpose": "発話根拠の弱い move 候補",
                    "explicitness": "inferred",
                    "confidence": 0.35,
                    "evidence": [],
                    "do_not_execute": False,
                    "notes": "発話なしの move。実行可否は検証層で確定する",
                    "weak_move_candidate": True,
                    "suggested_destinations": dests,
                })
                return result
            # 地点付き move は DISCUSSION に落とさず検証層へ（目的地不一致の再生成）
            if defer_move_validation:
                result.update({
                    "intent_type": INTENT_ACTION_REQUEST,
                    "action": "move",
                    "target_text": proposed_target,
                    "purpose": "地点付き move（検証層で確定）",
                    "explicitness": "inferred",
                    "confidence": 0.5,
                    "evidence": dests[:2] or [proposed_target],
                    "do_not_execute": False,
                    "notes": "発話と move target の整合は検証層に委ねる",
                    "suggested_destinations": dests,
                })
                return result
            # 方針・曖昧な移動示唆は即時実行しない
            result.update({
                "intent_type": (
                    INTENT_DISCUSSION_OR_PLAN
                    if is_discussion_or_plan_text(combined)
                    else INTENT_UNCLEAR
                ),
                "action": "wait",
                "target_text": target or (dests[0] if dests else ""),
                "purpose": "曖昧な移動示唆",
                "explicitness": "inferred",
                "confidence": 0.55,
                "evidence": _intent_evidence(combined, _AMBIGUOUS_MOVE_MARKERS) or dests[:2],
                "do_not_execute": True,
                "notes": "曖昧な発言を移動命令としては採用しない",
                "ambiguous_move_inferred": True,
                "suggested_destinations": dests,
            })
            return result

    # 3) 礼・挨拶などの演技会話
    if is_courtesy_dialogue_text(combined) and not _text_has_marker(
        combined, ("聞く", "尋ね", "質問", "調べ", "移動", "向か", "ask ", "investigate", "move ")
    ):
        courtesy_target = proposed_target or focus_npc
        if not courtesy_target and char_mgr:
            courtesy_target = _resolve_proposal_npc_id(combined, char_mgr=char_mgr)
        result.update({
            "intent_type": INTENT_IN_CHARACTER_DIALOGUE,
            "action": "talk",
            "target_text": courtesy_target,
            "purpose": "礼・挨拶などの演技会話",
            "explicitness": "explicit",
            "confidence": 0.88,
            "evidence": _intent_evidence(combined, _COURTESY_DIALOGUE_MARKERS),
            "do_not_execute": False,
        })
        return result

    # 4) 明示的な調査（地点付き move との衝突時は検証層へ）
    if (
        not defer_move_validation
        and (
            _text_has_marker(combined, _EXPLICIT_SEARCH_MARKERS)
            or proposed_action in ("search", "inspect")
        )
    ):
        if not any(m in combined for m in ("方が", "べきだ", "十分そう")):
            result.update({
                "intent_type": INTENT_ACTION_REQUEST,
                "action": "search" if proposed_action != "inspect" else "inspect",
                "target_text": proposed_target if proposed_target not in loc_ids else _resolve_proposal_search_target(
                    combined, scenario_mgr=scenario_mgr, current_loc=current_loc,
                ),
                "purpose": "調査・探索",
                "explicitness": "explicit" if _text_has_marker(combined, _EXPLICIT_SEARCH_MARKERS) else "inferred",
                "confidence": 0.9 if _text_has_marker(combined, _EXPLICIT_SEARCH_MARKERS) else 0.7,
                "evidence": _intent_evidence(combined, _EXPLICIT_SEARCH_MARKERS) or [proposed_target],
                "do_not_execute": False,
            })
            return result

    # 5) 明示的な会話・質問・交渉
    if (
        _text_has_marker(combined, _EXPLICIT_TALK_MARKERS)
        or proposed_action in ("talk", "speak", "persuade", "negotiate", "fast_talk", "intimidate", "charm", "psychology")
    ):
        action = proposed_action if proposed_action not in ("", "wait", "search", "inspect", "move") else "talk"
        talk_target = proposed_target or _resolve_proposal_npc_id(combined, char_mgr=char_mgr)
        result.update({
            "intent_type": INTENT_ACTION_REQUEST,
            "action": action,
            "target_text": talk_target,
            "purpose": "NPCへの質問・会話・交渉",
            "explicitness": "explicit" if _text_has_marker(combined, _EXPLICIT_TALK_MARKERS) else "inferred",
            "confidence": 0.91,
            "evidence": _intent_evidence(combined, _EXPLICIT_TALK_MARKERS) or [talk_target or dialogue[:20]],
            "do_not_execute": False,
        })
        return result

    # 5b) NPC発言への短い返答（文脈あり）→ 会話維持
    if (
        dialogue
        and (ctx.get("recent_npc") or ctx.get("focus_npc"))
        and proposed_action in ("", "wait", "talk", "speak")
        and not has_explicit_move_expression(combined)
        and not _text_has_marker(combined, _EXPLICIT_SEARCH_MARKERS)
    ):
        reply_target = proposed_target or str(ctx.get("focus_npc") or "")
        if not reply_target and char_mgr:
            reply_target = _resolve_proposal_npc_id(combined, char_mgr=char_mgr)
        if not reply_target and ctx.get("npcs_here"):
            reply_target = str((ctx.get("npcs_here") or [""])[0] or "")
        result.update({
            "intent_type": INTENT_IN_CHARACTER_DIALOGUE,
            "action": "talk" if reply_target else "wait",
            "target_text": reply_target,
            "purpose": "NPC発言への返答",
            "explicitness": "soft",
            "confidence": 0.72,
            "evidence": [dialogue[:40], "recent_npc_context"],
            "do_not_execute": not bool(reply_target),
            "notes": "直近NPC文脈に基づく会話維持",
        })
        return result

    # 6) セリフだけの IC（行動コマンドが talk 想定）
    if dialogue and proposed_action in ("", "wait", "talk", "speak"):
        result.update({
            "intent_type": INTENT_IN_CHARACTER_DIALOGUE,
            "action": "talk" if proposed_target else "wait",
            "target_text": proposed_target,
            "purpose": "IC発言",
            "explicitness": "soft",
            "confidence": 0.65,
            "evidence": [dialogue[:40]],
            "do_not_execute": not bool(proposed_target),
        })
        return result

    # 7) 提案アクションを候補として残す（確定は呼び出し側）
    if proposed_action not in ("", "wait", "none"):
        result.update({
            "intent_type": INTENT_ACTION_REQUEST,
            "action": proposed_action,
            "target_text": proposed_target,
            "purpose": "LLM提案アクション",
            "explicitness": "inferred",
            "confidence": 0.55,
            "evidence": [proposed_action, proposed_target] if proposed_target else [proposed_action],
            "do_not_execute": False,
            "notes": "発話根拠が弱いため、実行前に整合性検証が必要",
        })
        return result

    result.update({
        "do_not_execute": True,
        "notes": "意図を特定できない（対象・動作なし）",
        "confidence": 0.3,
    })
    return result


def can_auto_execute_move(
    intent: Optional[Dict[str, Any]],
    *,
    scenario_mgr=None,
    current_loc: str = "",
    target: str = "",
) -> Dict[str, Any]:
    """
    move を自動実行してよいかを厳格判定する。
    ok=False のとき reason / needs_confirmation を返す。
    """
    intent = intent or {}
    current_loc = str(current_loc or "")
    target = str(target or intent.get("target_text") or "").strip()
    if intent.get("intent_type") != INTENT_ACTION_REQUEST:
        return {
            "ok": False,
            "reason": "intent_type が ACTION_REQUEST ではない",
            "needs_confirmation": True,
        }
    if intent.get("do_not_execute"):
        return {"ok": False, "reason": "do_not_execute", "needs_confirmation": True}
    if intent.get("action") != "move" and not has_explicit_move_expression(
        " ".join(str(x) for x in (intent.get("evidence") or []))
    ):
        # action が move 以外でも、明示移動表現があれば後段で補正される
        if intent.get("action") != "move":
            return {"ok": False, "reason": "action が move ではない", "needs_confirmation": False}
    if intent.get("explicitness") != "explicit" and not intent.get("evidence"):
        return {
            "ok": False,
            "reason": "移動の明示性が不足",
            "needs_confirmation": True,
        }
    if not target:
        return {"ok": False, "reason": "移動先が未特定", "needs_confirmation": True}
    if target == current_loc:
        return {"ok": False, "reason": "現在地と同じ", "needs_confirmation": False}
    if scenario_mgr:
        loc_ids = set(scenario_mgr.get_all_location_ids() or [])
        if target not in loc_ids:
            return {"ok": False, "reason": "シナリオに存在しない移動先", "needs_confirmation": False}
        exits = {
            str(e.get("id") or "")
            for e in (scenario_mgr.get_available_exits(current_loc) or [])
            if e.get("id")
        }
        if target not in exits:
            return {
                "ok": False,
                "reason": "未解禁または到達不能な移動先",
                "needs_confirmation": False,
            }
    return {"ok": True, "reason": "", "needs_confirmation": False}


def classify_target_scope(
    target: str,
    *,
    scenario_mgr=None,
    current_loc: str = "",
    char_mgr=None,
) -> Dict[str, Any]:
    """
    対象が現在地／別地点／ロケーションのどこに属するかを返す。
    解決そのものは normalize 側で行い、ここでは所在判定に使う。
    """
    target = str(target or "").strip()
    current_loc = str(current_loc or "")
    info = {
        "target": target,
        "scope": "unknown",  # current | other_location | location | unknown
        "location_id": "",
    }
    if not target or not scenario_mgr:
        return info
    loc_ids = set(scenario_mgr.get_all_location_ids() or [])
    if target in loc_ids:
        info.update(scope="location", location_id=target)
        return info
    if current_loc:
        objects = (scenario_mgr.get_location_info(current_loc) or {}).get("objects") or {}
        if target in objects:
            info.update(scope="current", location_id=current_loc)
            return info
        if hasattr(scenario_mgr, "is_npc_at_location") and scenario_mgr.is_npc_at_location(
            target, current_loc, char_mgr=char_mgr,
        ):
            info.update(scope="current", location_id=current_loc)
            return info
        present = set(scenario_mgr.get_npcs_present(current_loc) or [])
        if target in present:
            info.update(scope="current", location_id=current_loc)
            return info
    for loc_id in loc_ids:
        objects = (scenario_mgr.get_location_info(loc_id) or {}).get("objects") or {}
        if target in objects:
            info.update(scope="other_location", location_id=loc_id)
            return info
        if hasattr(scenario_mgr, "is_npc_at_location") and scenario_mgr.is_npc_at_location(
            target, loc_id, char_mgr=char_mgr,
        ):
            info.update(scope="other_location", location_id=loc_id)
            return info
    return info


def is_duplicate_npc_dialogue(
    dialogue: str,
    npc_id: str,
    all_events_log=None,
    *,
    pc_id: str = "",
    lookback: int = 12,
) -> bool:
    """同一PCから同一NPCへの実質同じ発話が直近にあるか。"""
    dialogue = str(dialogue or "").strip()
    npc_id = str(npc_id or "").strip()
    if not dialogue or not npc_id:
        return False
    # 短すぎる礼は重複とみなす
    norm = re.sub(r"\s+", "", dialogue)
    count = 0
    for entry in reversed(list(all_events_log or [])[-lookback:]):
        meta = (entry or {}).get("meta") or {}
        if str(meta.get("action_id") or meta.get("action") or "").lower() not in (
            "talk", "speak", "chat", "persuade", "negotiate", "fast_talk", "intimidate", "charm", "psychology",
        ):
            continue
        if str(meta.get("target") or "") != npc_id:
            continue
        if pc_id and str(meta.get("pc_id") or "") not in ("", pc_id):
            continue
        text = str((entry or {}).get("text") or "")
        # プレフィックス除去
        body = text.split(":", 1)[-1].strip() if ":" in text else text
        body_norm = re.sub(r"\s+", "", body)
        if not body_norm:
            continue
        if body_norm == norm or (len(norm) >= 10 and (norm in body_norm or body_norm in norm)):
            count += 1
            if count >= 1:
                return True
    return False


MOVE_NON_LOCATION_AS_MOVE_ERROR = (
    "【システム検証エラー・行動再選択】"
    "テキストが指しているのはロケーションへの移動ではなく、現在地の調査／対話対象です。"
    "move ではなく search / inspect / talk を使い、正しい target（オブジェクトIDまたはNPC ID）を指定して再出力してください。"
)

HUMAN_INSPECT_REWRITE_LOG = (
    "【アクション補正】対象は人物（または人がいる窓口）です。"
    "search / inspect / push は無効化し、talk（対話）へ切り替えました。"
)

OBJECT_TALK_REWRITE_LOG = (
    "【アクション補正】対象は現在地の調査オブジェクトです。"
    "talk / 交渉技能を search / inspect に切り替え、調査イベントとして処理します。"
)

HUMAN_INSPECT_BLOCK_ERROR = (
    "【システム検証エラー・行動再選択】"
    "その対象は人間（NPC／窓口係）です。"
    "目星や調査（search / inspect）、こじ開け（push / break）ではなく、"
    "話しかける（talk）か交渉技能（persuade / fast_talk / intimidate / charm / psychology）を使用してください。"
)

PL_RETRY_PROMPT_PREFIX = (
    "【直前の行動はシステムに拒否されました。必ず修正して再出力すること】\n"
)

KP_SUCCESS_FACT_GUARD = (
    "【ダイス成功・確定ファクト必須】"
    "今回の判定は成功している。"
    "下記【成功時に必ず含める確定手がかり】を描写に必ず織り込むこと。"
    "「特に何も見つからなかった」と成功を空振りにしてはならない。"
    "下記に無い怪異・呪文・新キャラ・未記載プロットを創作（ハルシネーション）してはならない。"
)

KP_LOCKED_ROUTE_GUARD = (
    "【未解放ルートの先回り誘導禁止】"
    "PLが正規手順（フラグ）を踏んでいない場所・ルート・担当者を、先回りして提案・誘導してはならない。"
    "例: artie_introduced 前に参考資料室への侵入を勧める、受付を飛ばして編集者と既に会っている体で描写する、など。"
)

# OOC 膠着ループ遮断（強制 IC 行動フェーズ）
# マイルド化: 2〜3ターンでは強制せず、5〜6ターン程度まで自律リカバリーの余白を残す
STAGNATION_HINT_TURNS = 3  # OOC/システム通知のマイルドヒント開始
STAGNATION_FORCE_TURNS = 6  # 固定行動の強制・アイデアロール等の強介入
FORCE_IC_ACTION_CHAT_ROUNDS = 3
FORCE_IC_ACTION_STAGNATION_STREAK = 5  # streak がこの値を超えたら発火（> 5 → 6ターン目）
VALIDATION_RETRY_BREAKOUT_COUNT = 5  # 同一無効行動の自動補正ブレイクアウト

OOC_LOOP_FORCE_ACTION_WARNING = (
    "【システム警告】作戦会議（OOC）の連続上限に達しました。"
    "これ以上のメタ発言はブロックされます。"
    "現状を打破するため、別の技能（言いくるめ/信用など）を宣言するか、"
    "他のオブジェクトの調査、あるいは[図書館]など別のロケーションへの移動アクション（move）を必ずICで実行してください。"
)

FORCE_IC_WAIT_REJECT_ERROR = (
    "【システム検証エラー・行動再選択】"
    "強制 IC 行動フェーズ中です。`action: wait` および待機のみの出力は無効です。"
    "`move` / `search` / `inspect` など、場面を進展させる IC 行動を必ず指定して再出力してください。"
)

FORCE_IC_STALE_TALK_REJECT_ERROR = (
    "【システム検証エラー・行動再選択】"
    "導入の依頼確認は完了済みです。"
    "同じ NPC（スティーブン・ノット氏）への繰り返し talk は進展になりません。"
    "`move` / target: `boston_globe`（または解放済みの別ロケーション）へ移動してください。"
)

STALE_KNOTT_TALK_REJECT_ERROR = (
    "【システム】スティーブン・ノット氏からの聞き込みは既に完了しています。"
    "速やかに次の調査先（ボストン・グローブ紙など）へ移動アクション（move）を起こしてください。"
)

STALE_DOLLY_TALK_REJECT_ERROR = (
    "【システム】ドーリー氏からの聞き込みは既に完了しています。"
    "同じ話を繰り返さず、屋敷の外観（`corbitt_house_exterior_view`）を調べるか、"
    "黙想チャペル・サナトリウム・コービット屋敷へ `move` してください。"
)

STALE_RECEPTION_TALK_REJECT_ERROR = (
    "【システム】受付からのアーティ取り次ぎは完了済みです。"
    "受付への繰り返し talk では進みません。"
    "アーティへ〈説得〉（persuade）／〈威圧〉（intimidate）／〈言いくるめ〉（fast_talk）で交渉するか、"
    "中央図書館などへ `move` してください。"
)

STALE_ARTIE_TALK_REJECT_ERROR = (
    "【システム】アーティとの雑談（talk）だけでは資料室の許可は得られません。"
    "〈説得〉（persuade）、〈威圧〉（intimidate）、〈言いくるめ〉（fast_talk）など"
    "交渉技能を指定したアクションでダイスロールしてください。"
)

ARTIE_NEGOTIATE_STAGNATION_HINT = (
    "【システムヒント】アーティから参考資料室の閲覧許可を得るには、単なる雑談（talk）ではなく、"
    "〈説得〉（persuade）、〈威圧〉（intimidate）、〈言いくるめ〉（fast_talk）などの"
    "交渉技能を指定したアクション・ダイスロールを実行する必要があります。"
)

ARTIE_NEGOTIATE_ALTERNATE_SKILL_HINT = (
    "【システムヒント】交渉技能での判定に失敗しました。"
    "すぐに他ロケーションへ移動せず、自身のキャラクターシートでより高い成功率の技能"
    "（例: 〈威圧〉intimidate、〈言いくるめ〉fast_talk、別の〈説得〉persuade）で再挑戦するか、"
    "成功率の高い他のPCに交渉を任せてください。"
    "代替は最大1回です。それが失敗・拒否されたら情報入手は諦め、"
    "`move` で別ロケーションまたはコービット屋敷（`corbitt_exterior`）へ進んでください。"
)

ARTIE_ACCESS_GRANTED_SEARCH_HINT = (
    "【システムヒント・最優先】参考資料室への許可は取得済みです。"
    "今すぐ `search` / `reference_room_clipping_files`（切り抜きファイル）を実行してください。"
    "アーティ・受付への talk/persuade、不在の保管記録係（ルース等）への執着は禁止です。"
)

ACCESS_GATE_NEGOTIATE_SKILL_HINT = (
    "閲覧許可が必要です。担当者に対して 〈説得〉(persuade)、〈威圧〉(intimidate)、"
    "〈言いくるめ〉(fast_talk) のいずれかで交渉ロールを行ってください。"
)

BOSTON_GLOBE_INVESTIGATION_DONE_HINT = (
    "【システム】ボストン・グローブでの調査は完了しています。"
    "中央図書館（`central_library`）や公文書館（`hall_of_records`）、"
    "警察署（`higher_courts_police_station`）などへ移動（`move`）してください。"
    "アーティ／受付への再交渉や雑談ではこれ以上進展しません。"
)

ARTIE_ACCESS_GRANTED_KP_DIRECTIVE = (
    "- 【絶対遵守・許可済み・未調査】参考資料室への入室許可は**既に降りている**。"
    "アーティおよび受付による追加条件要求・別人物（ルース・ブレイク等）への誘導・"
    "部外者扱い・門前払い描写を**完全に禁止**する。"
    "『まだ入れない』『ルースなら教えてくれる』『ルースに声をかける』"
    "『許可を確認する』『裁量次第』『手続きが必要』は矛盾であり厳禁。"
    "資料室の切り抜きファイル（`reference_room_clipping_files`）へ**直接**案内し、"
    "`search` で調べるよう明確に促せ。"
    "背景としてルースの名が出ても、それは追加の入室条件ではない。"
)

ABSENT_NPC_REDIRECT_SEARCH_HINT = (
    "【システムヒント】指定された人物は現在この場に存在しません。"
    "現在地のオブジェクトを調査するか、解放済みロケーションへ move してください。"
)

# ボストン・グローブ限定（許可取得後の切り抜き誘導）
ABSENT_NPC_REDIRECT_CLIPPING_HINT = (
    "【システムヒント】指定された人物は現在この場に存在しません。"
    "参考資料室の切り抜きファイル（reference_room_clipping_files）を search で調査してください。"
)

POST_ACCESS_SEARCH_FORCE_TURNS = 6

# 調査枯渇ロケで move しない停滞がこのターン数に達したら強制ブレイクアウト
LOCATION_EXHAUSTED_FORCE_TURNS = 5

# ボストン・グローブ: 許可未取得時、別技能の再挑戦猶予を与え、その後は移動ブレイクアウト
BOSTON_GLOBE_NEGOTIATE_GRACE_RETRY_COUNT = 5

# 失敗・拒否のあと同一ロケに留まって進展しないターン数で強制移動（ヒントは STAGNATION_HINT_TURNS）
INVESTIGATION_DEADLOCK_FORCE_TURNS = 6

# 導入完了後に常時解禁する本命目的地（PL が corbitt_house と書いてもここへ正規化）
HOUSE_ENTRY_LOCATION_ID = "corbitt_exterior"
HOUSE_MOVE_ALIASES = frozenset({
    "corbitt_house", "corbitt_house_exterior", "コービット屋敷",
})

INVESTIGATION_BAILOUT_HINT = (
    "【システムヒント・即時撤退】これ以上この場所で情報を得ることは困難です。"
    "留まらずに『別の移動可能な場所へ移動する』か、"
    "『直接コービット屋敷（`move` / `corbitt_exterior`。別名 `corbitt_house`）へ向かう』"
    "行動を選択してください。"
    "すべての資料を集める必要はありません。現地に踏み込むことも正当な攻略手段です。"
)

LOCATION_EXHAUSTED_MOVE_HINT = (
    "【システムヒント】この場所での調査はすべて完了しました。"
    "公文書館（`hall_of_records`）などの新しい場所へ移動（`move`）してください。"
)

LOCATION_EXHAUSTED_RESEARCH_REJECT = (
    "【システム】調査済みです。他ロケーションへ移動してください。"
)

FORCE_PROGRESS_BREAKOUT_LOG = (
    "[システム] 膠着が上限に達したため、次の調査先へ強制移動します。"
)

# 導入で移動解禁後に居座る対象
INTRODUCTION_STALE_TALK_NPCS = frozenset({
    "steven_knott", "npc_steven_knott", "mr_knott",
})

# 近所: 情報開示後に居座るドーリー
NEIGHBORHOOD_STALE_TALK_NPCS = frozenset({
    "dolly_shopkeeper", "local_residents", "dolly_the_shopkeeper",
    "dolly",
})

# 屋敷への直行を自動追加してよいハブ（出口ゲート付きロケには足さない）
HOUSE_FAST_TRAVEL_HUBS = frozenset({
    "introduction",
    "boston_globe",
    "central_library",
    "hall_of_records",
    "higher_courts_police_station",
    "the_neighborhood",
})

# ボストン・グローブ: 紹介後に居座る受付
BOSTON_GLOBE_RECEPTION_NPCS = frozenset({
    "globe_receptionist", "reception_desk",
})

# ボストン・グローブ: 許可前の雑談のみでは進まない編集者
BOSTON_GLOBE_ARTIE_NPCS = frozenset({
    "artie_wilmott", "artie",
})

NEGOTIATION_ACTION_IDS = frozenset({
    "persuade", "negotiate", "intimidate", "charm", "fast_talk",
    "psychology", "insight",
    "説得", "言いくるめ", "威圧", "魅惑", "心理学",
})

# 強制ブレイクアウト時の優先移動先（現在地以外）
FORCED_PROGRESS_MOVE_PREFERENCE = (
    "boston_globe",
    "central_library",
    "hall_of_records",
    "the_neighborhood",
    "higher_courts_police_station",
    "corbitt_exterior",
)

# ロケーション別の優先強制アクション候補
LOCATION_FORCED_PROGRESS_PREFERENCE = {
    "introduction": ("boston_globe", "central_library", "hall_of_records", "corbitt_exterior"),
    "boston_globe": ("central_library", "hall_of_records", "the_neighborhood", "corbitt_exterior", "introduction"),
    "central_library": ("hall_of_records", "boston_globe", "the_neighborhood", "corbitt_exterior"),
    "hall_of_records": ("higher_courts_police_station", "boston_globe", "central_library", "corbitt_exterior"),
    "higher_courts_police_station": ("the_neighborhood", "hall_of_records", "corbitt_exterior"),
    "the_neighborhood": ("corbitt_exterior", "boston_globe", "central_library"),
    "chapel_of_contemplation": ("the_neighborhood", "corbitt_exterior", "roxbury_sanitarium"),
    # 入館後は1階へ。未入館時は入口行動を優先するため the_neighborhood は載せない。
    "corbitt_exterior": ("corbitt_ground_floor",),
}

# 近所↔外観だけの往復はシナリオ進捗に数えない
CORBITT_APPROACH_PINGPONG_LOCS = frozenset({"the_neighborhood", "corbitt_exterior"})

# 調査枯渇時の move 誘導・強制ブレイクアウトを適用するロケーション
LOCATION_EXHAUSTED_MOVE_LOCATIONS = frozenset(LOCATION_FORCED_PROGRESS_PREFERENCE.keys())

# talk 系（進展判定用）
TALK_ACTION_IDS = frozenset({
    "talk", "speak", "chat", "converse", "対話", "会話", "話す",
})

# 場面依存ヒント（膠着時）
LOCATION_STAGNATION_HINTS = {
    "introduction": (
        "【システムヒント】依頼の概要は把握できています。"
        "急がなくて構いませんが、手がかりを増やすなら"
        "ボストン・グローブ紙（`move` / `boston_globe`）や"
        "中央図書館（`central_library`）、近所（`the_neighborhood`）も候補です。"
    ),
    "boston_globe": (
        "【システムヒント】まず受付（`talk` / `globe_receptionist`）で用件を伝え、"
        "アーティ・ウィルモットを呼び出してもらってください。"
        "未紹介のまま編集者と交渉はできません。"
        "進まない場合は中央図書館（`move` / `central_library`）や"
        "公文書館（`hall_of_records`）へ移動するか、"
        "資料を揃えずに直接コービット屋敷（`corbitt_exterior`）へ向かってください。"
    ),
    "central_library": (
        "【システムヒント】図書館での調査が進んでいません。"
        "未調査の資料オブジェクトを `search` / `inspect` するか、"
        "公文書館・新聞社など別ロケーションへ `move` するか、"
        "直接コービット屋敷（`corbitt_exterior`）へ向かってください。"
    ),
    "hall_of_records": (
        "【システムヒント】公文書館での進行が停滞しています。"
        "事務官に `talk` するか、未調査の記録を調べるか、"
        "警察署ルート（`higher_courts_police_station`）へ移動するか、"
        "直接コービット屋敷（`corbitt_exterior`）へ向かってください。"
    ),
    "roxbury_sanitarium": (
        "【システムヒント】マカリオ夫妻は施設内の調査対象です。"
        "`search` / `inspect`（または talk）で `gabriella_macario`・`vittorio_macario`、"
        "あるいは患者記録（`patient_records`）を調べてください。"
        "話を聞いたら近所へ戻れます。"
    ),
}

# 汎用フォールバック（場面不明時のみ） / 後方互換エイリアス
STAGNATION_STANDARD_PL_HINT_FALLBACK = (
    "【システムヒント】現在調査が難航しています。"
    "ダイス判定失敗による停滞を避けるため、他の技能を用いたアプローチを宣言するか、"
    "未調査の対象を調べるか、解放済みロケーションへ `move` してください。"
)
STAGNATION_STANDARD_PL_HINT = STAGNATION_STANDARD_PL_HINT_FALLBACK

# 強介入の前に出すマイルドな OOC 通知（行動の強制はしない）
STAGNATION_MILD_NOTICE = (
    "【システム通知】進行に少し時間がかかっています。"
    "同じ手段にこだわらず、別の対象・技能・場所を試しても構いません。"
    "焦って結論を急ぐ必要はありません。探索者自身の判断で次の一手を選んでください。"
)


# ロケーションID → テキスト照合キーワード
LOCATION_INTENT_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "introduction": ("導入", "探偵事務所", "喫茶店", "ノット氏の元", "introduction"),
    "boston_globe": (
        "ボストン・グローブ", "ボストングローブ", "新聞社", "グローブ紙",
        "boston_globe", "boston globe", "globe",
    ),
    "central_library": (
        "中央図書館", "図書館", "central_library", "central library", "library",
    ),
    "hall_of_records": (
        "公文書館", "記録保管所", "公文書", "hall_of_records", "hall of records", "records hall",
    ),
    "higher_courts_police_station": (
        "警察署", "上級裁判所", "中央警察署", "higher_courts", "police station",
    ),
    "the_neighborhood": (
        "近隣", "近所", "住民", "the_neighborhood", "neighborhood", "neighbourhood",
    ),
    "roxbury_sanitarium": ("サナトリウム", "ロクスベリー", "roxbury", "sanitarium"),
    "chapel_of_contemplation": ("チャペル", "黙想", "chapel"),
    "corbitt_exterior": (
        "屋敷の外", "コービット屋敷の外", "外観", "corbitt_exterior", "corbitt house",
    ),
    "corbitt_ground_floor": ("1階", "地上階", "corbitt_ground_floor"),
    "corbitt_upper_floor": ("2階", "上階", "corbitt_upper_floor"),
    "corbitt_basement": ("地下室", "地下", "corbitt_basement"),
}

# ロケーションではないが「行く／調べる」と誤って move されやすい対象
NON_LOCATION_DESTINATION_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "reference_room_clipping_files": (
        "参考資料室", "資料室", "切り抜きファイル", "切り抜き", "reference_room",
    ),
    "newspaper_archives": (
        "新聞アーカイブ", "新聞アーカイヴ", "アーカイブ", "archive", "archives",
        "newspaper archive", "newspaper archives",
    ),
}

# 人物／窓口オブジェクト → 対話NPC ID（Pattern A: talk へ強制変換）
SOCIAL_OBJECT_TO_NPC: Dict[str, str] = {
    "reception_desk": "globe_receptionist",
    "globe_receptionist": "globe_receptionist",
    "steven_knott": "steven_knott",
    "clerk_desk": "hall_records_clerk",
    "hall_records_clerk": "hall_records_clerk",
    "local_residents": "dolly_shopkeeper",
    "dolly_shopkeeper": "dolly_shopkeeper",
    "dolly_the_shopkeeper": "dolly_shopkeeper",
    "kim_deblanc": "kim_deblanc",
    "artie_wilmott": "artie_wilmott",
}

# 対人対象への物理・調査アクション
SOCIAL_BLOCKED_ACTIONS = frozenset({
    "search", "inspect", "push", "break", "kick", "force", "push_roll",
})


def _text_has_any(text: str, keywords: Sequence[str]) -> bool:
    text = text or ""
    text_cf = text.casefold()
    return any(k and (k in text or k.casefold() in text_cf) for k in keywords)


def collect_intent_location_ids(intent_text: str, scenario_mgr=None) -> List[str]:
    """テキストから言及されているロケーションIDを収集する。"""
    found: List[str] = []
    text = intent_text or ""
    loc_ids = []
    if scenario_mgr:
        loc_ids = list(scenario_mgr.get_all_location_ids())
    else:
        loc_ids = list(LOCATION_INTENT_KEYWORDS.keys())

    for loc_id in loc_ids:
        keywords = _location_intent_keywords(loc_id, scenario_mgr)
        # 短い汎用語（「地下」「図書館」）の誤爆を抑えるため、複数ヒット優先は呼び出し側で扱う
        if _text_has_any(text, keywords):
            if loc_id not in found:
                found.append(loc_id)
    return found


def _location_intent_keywords(loc_id: str, scenario_mgr=None) -> List[str]:
    keywords = list(LOCATION_INTENT_KEYWORDS.get(loc_id, ()))
    if scenario_mgr:
        name = str(scenario_mgr.get_location_info(loc_id).get("name") or "")
        if name:
            keywords.append(name)
        keywords.append(loc_id)
    return [k for k in keywords if k]


_TRAVEL_VERB_RE = re.compile(
    r"(向か|行こ|行きま|行く|移動|訪ね|赴|"
    r"move\s+to|go\s+to|let'?s\s+go|lets\s+go|head(?:ing)?\s+to|\bmove\b|\bgo\b)",
    re.IGNORECASE,
)
_INFO_OBTAINED_MARKERS = (
    "情報を得", "手に入れ", "聞いた", "聞き出した", "教えてもら",
    "話を聞いた", "得た", " rumored",
)
_STAY_AND_INVESTIGATE_MARKERS = (
    "まずは", "近隣", "住民", "聞き込み", "もう少し", "この場", "周囲",
    "探ろう", "探して", "引き出して",
)


def intent_wants_travel_to(intent_text: str, loc_id: str, scenario_mgr=None) -> bool:
    """言及が『そこに行く』意図か。『情報を得た』だけの言及は除外する。"""
    intent = str(intent_text or "")
    if not intent.strip() or not loc_id:
        return False
    keywords = _location_intent_keywords(loc_id, scenario_mgr)
    intent_cf = intent.casefold()
    for kw in keywords:
        if not kw:
            continue
        kw_cf = kw.casefold()
        if kw not in intent and kw_cf not in intent_cf:
            continue
        # 「図書館へ」「to the library」
        if re.search(re.escape(kw) + r"へ", intent):
            return True
        if re.search(r"(?:to\s+(?:the\s+)?)?" + re.escape(kw_cf), intent_cf):
            # 英語: move/go が近くにある場合のみ
            if _TRAVEL_VERB_RE.search(intent):
                return True
        window = 24
        # 大文字小文字を無視して位置を探す
        idx = 0
        source = intent if kw in intent else intent_cf
        needle = kw if kw in intent else kw_cf
        while True:
            found = source.find(needle, idx)
            if found < 0:
                break
            after = source[found + len(needle): found + len(needle) + window]
            before = source[max(0, found - window): found]
            if _TRAVEL_VERB_RE.search(after) or _TRAVEL_VERB_RE.search(before):
                return True
            idx = found + len(needle)
    return False


def collect_intent_destination_ids(
    intent_text: str, scenario_mgr=None, current_loc: str = "",
) -> List[str]:
    """移動したいロケーションだけを返す（情報として出た地名は除外）。"""
    current_loc = str(current_loc or "")
    dests = []
    for loc_id in collect_intent_location_ids(intent_text, scenario_mgr):
        if loc_id == current_loc:
            continue
        if intent_wants_travel_to(intent_text, loc_id, scenario_mgr):
            dests.append(loc_id)
    return dests


def _intent_prefers_staying(intent_text: str) -> bool:
    text = str(intent_text or "")
    if any(m in text for m in _STAY_AND_INVESTIGATE_MARKERS):
        return True
    if any(m in text for m in _INFO_OBTAINED_MARKERS) and not _TRAVEL_VERB_RE.search(
        re.sub(r"聞きに行", "", text)
    ):
        return True
    return False


def collect_intent_non_location_targets(intent_text: str) -> List[str]:
    """ロケーションではない移動・調査希望（参考資料室など）を検出する。"""
    found: List[str] = []
    text = intent_text or ""
    for target_id, keywords in NON_LOCATION_DESTINATION_KEYWORDS.items():
        if _text_has_any(text, keywords):
            found.append(target_id)
    return found


def infer_empty_move_from_intent(
    intent_text: str,
    current_loc: str = "",
    scenario_mgr=None,
) -> Optional[Dict[str, str]]:
    """
    target 空の move を、発言テキストから補完する。
    補完できない場合は None（呼び出し側で suggested_fix / エラーへ）。
    """
    intent = str(intent_text or "")
    current_loc = str(current_loc or "")
    if not intent.strip():
        return None

    non_locs = collect_intent_non_location_targets(intent)
    if non_locs:
        primary = non_locs[0]
        if primary == "reference_room_clipping_files":
            return {"action": "talk", "target": "globe_receptionist", "skill": ""}
        return {"action": "search", "target": primary, "skill": "目星"}

    mentioned = collect_intent_destination_ids(intent, scenario_mgr, current_loc)
    if mentioned:
        return {"action": "move", "target": mentioned[0], "skill": ""}

    if not scenario_mgr:
        return None
    objects = (scenario_mgr.get_location_info(current_loc) or {}).get("objects") or {}
    flags = getattr(scenario_mgr, "flags", None) or {}
    for obj_id, obj in objects.items():
        if not isinstance(obj, dict):
            continue
        if not object_is_currently_available(obj, flags):
            continue
        if object_is_investigated(scenario_mgr, str(obj_id), obj, flags):
            continue
        keywords = [str(obj.get("name") or ""), str(obj_id)]
        keywords.extend(str(a) for a in (obj.get("aliases") or []) if a)
        keywords = [k for k in keywords if k and len(k) >= 2]
        if _text_has_any(intent, keywords):
            return {"action": "search", "target": str(obj_id), "skill": "目星"}
    return None


def suggest_empty_move_fix(
    intent_text: str,
    current_loc: str = "",
    scenario_mgr=None,
) -> Optional[Dict[str, str]]:
    """空 move 用の推奨修正。発言から推定できなければ、未調査オブジェクトを優先する。"""
    inferred = infer_empty_move_from_intent(intent_text, current_loc, scenario_mgr)
    if inferred:
        return inferred
    search_target = pick_forced_progress_search_target(scenario_mgr, current_loc)
    if search_target:
        return {"action": "search", "target": search_target, "skill": "目星"}
    forced = build_forced_progress_action(scenario_mgr, current_loc)
    if not forced:
        return None
    return {
        "action": str(forced.get("action") or "search"),
        "target": str(forced.get("target") or ""),
        "skill": str(forced.get("skill") or ""),
    }


def validate_push_roll_available(
    pending_push_roll: Optional[Dict[str, Any]] = None,
    *,
    current_loc: str = "",
    scenario_mgr=None,
) -> Dict[str, Any]:
    """
    push_roll が実行可能か（失敗判定の保留があるか）を検証する。

    Returns:
        {"ok": True} または
        {"ok": False, "error": str, "error_code": str, "suggested_fix": optional}
    """
    if pending_push_roll:
        return {"ok": True}

    suggested = None
    if scenario_mgr:
        suggested = suggest_empty_move_fix(
            "別の手がかりを調べる",
            current_loc=current_loc or getattr(scenario_mgr, "location", "") or "",
            scenario_mgr=scenario_mgr,
        )
    if not suggested or not suggested.get("target"):
        suggested = {"action": "search", "target": "", "skill": "目星"}
    return {
        "ok": False,
        "error": PUSH_ROLL_UNAVAILABLE_ERROR,
        "error_code": "push_roll_unavailable",
        "suggested_fix": suggested,
    }


def validate_move_intent(
    intent_text: str,
    target: str,
    current_loc: str = "",
    scenario_mgr=None,
) -> Dict[str, Any]:
    """
    move の target と IC/OOC テキストの目的地が一致するか検証する。

    Returns:
        {"ok": True} または
        {"ok": False, "error": str, "error_code": str, "suggested_fix": optional}
    """
    target = str(target or "").strip()
    intent = str(intent_text or "")
    current_loc = str(current_loc or "")
    if target and current_loc and target == current_loc:
        suggested = suggest_empty_move_fix(intent, current_loc, scenario_mgr)
        return {
            "ok": False,
            "error": MOVE_SAME_LOCATION_ERROR,
            "error_code": "move_same_location",
            "suggested_fix": suggested,
        }
    if not target:
        suggested = suggest_empty_move_fix(intent, current_loc, scenario_mgr)
        error = MOVE_MISSING_TARGET_ERROR
        if suggested and suggested.get("target"):
            error += (
                f" 推奨: action=`{suggested.get('action')}`"
                f" target=`{suggested.get('target')}`。"
            )
        return {
            "ok": False,
            "error": error,
            "error_code": "move_missing_target",
            "suggested_fix": suggested,
        }

    non_locs = collect_intent_non_location_targets(intent)
    if non_locs:
        # 「資料室へ行く」等は move 先ロケーションではない
        primary = non_locs[0]
        return {
            "ok": False,
            "error": (
                f"{MOVE_NON_LOCATION_AS_MOVE_ERROR}"
                f" テキスト上の対象候補: `{primary}`。"
                f" 誤った move target: `{target}`。"
            ),
            "error_code": "move_non_location_destination",
            "suggested_fix": {
                "action": "talk" if primary == "reference_room_clipping_files" else "search",
                "target": (
                    "globe_receptionist"
                    if primary == "reference_room_clipping_files"
                    else primary
                ),
            },
        }

    destinations = collect_intent_destination_ids(intent, scenario_mgr, current_loc)
    mentioned = collect_intent_location_ids(intent, scenario_mgr)
    mentioned = [m for m in mentioned if m != current_loc]
    if destinations:
        mentioned = destinations
    elif _intent_prefers_staying(intent) and target and target != current_loc:
        suggested = suggest_empty_move_fix(intent, current_loc, scenario_mgr) or {
            "action": "search",
            "target": pick_forced_progress_search_target(scenario_mgr, current_loc) or "",
            "skill": "目星",
        }
        return {
            "ok": False,
            "error": (
                f"{MOVE_INTENT_MISMATCH_ERROR}"
                "テキストは現在地での調査・聞き込みを示しています。"
                f" 誤った move target: `{target}`。"
            ),
            "error_code": "move_intent_mismatch",
            "suggested_fix": suggested if suggested.get("target") else None,
        }

    if mentioned and target not in mentioned:
        names = []
        for mid in mentioned:
            if scenario_mgr:
                names.append(scenario_mgr.get_location_info(mid).get("name", mid))
            else:
                names.append(mid)
        return {
            "ok": False,
            "error": (
                f"{MOVE_INTENT_MISMATCH_ERROR}"
                f" テキスト上の目的地: {', '.join(names)} / コマンド target: `{target}`。"
            ),
            "error_code": "move_intent_mismatch",
            "suggested_fix": {"action": "move", "target": mentioned[0]},
        }

    # テキストに明確な別目的地が無く、target 自身のキーワードとも無関係な場合は警告のみ通す
    # （短文「行こう」等）— ただし target の正式名がテキストに無く、かつ別ロケーション名だけがあるケースは上で拒否済
    return {"ok": True}


def resolve_location_object(scenario_mgr, current_loc: str, target: str):
    """現在地のオブジェクト ID と定義を返す。無ければ (None, None)。"""
    if not scenario_mgr or not target:
        return None, None
    loc = str(current_loc or getattr(scenario_mgr, "location", "") or "")
    objects = (scenario_mgr.get_location_info(loc) or {}).get("objects") or {}
    if not isinstance(objects, dict):
        return None, None
    raw = str(target or "").strip()
    if not raw:
        return None, None
    if raw in objects and isinstance(objects.get(raw), dict):
        return raw, objects[raw]
    raw_l = raw.lower()
    for oid, obj in objects.items():
        if not isinstance(obj, dict):
            continue
        name = str(obj.get("name") or "")
        if name and (raw == name or raw_l == name.lower()):
            return str(oid), obj
        for alias in obj.get("aliases") or []:
            if raw == alias or raw_l == str(alias).lower():
                return str(oid), obj
    return None, None


def is_investigable_location_object(scenario_mgr, current_loc: str, target: str) -> bool:
    """
    NPC 窓口ではなく、search/inspect で調べる人型オブジェクトか。
    （サナトリウムのマカリオ夫妻など）
    """
    oid, obj = resolve_location_object(scenario_mgr, current_loc, target)
    if not oid or not obj:
        return False
    if oid in SOCIAL_OBJECT_TO_NPC:
        return False
    usable = [str(a).lower() for a in (obj.get("usable_actions") or [])]
    return any(a in usable for a in ("search", "inspect", "read"))


def rewrite_talk_to_object_investigation(
    action: str,
    target: str,
    scenario_mgr=None,
    current_loc: str = "",
    skill: str = "",
) -> Optional[Dict[str, Any]]:
    """人型オブジェクトへの talk/交渉を search/inspect へ落とす。"""
    action = str(action or "").lower()
    if action not in TALK_ACTION_IDS and action not in NEGOTIATION_ACTION_IDS:
        return None
    if not is_investigable_location_object(scenario_mgr, current_loc, target):
        return None
    oid, obj = resolve_location_object(scenario_mgr, current_loc, target)
    usable = [str(a).lower() for a in ((obj or {}).get("usable_actions") or [])]
    if "search" in usable:
        new_action = "search"
    elif "inspect" in usable:
        new_action = "inspect"
    else:
        new_action = "search"
    return {
        "action": new_action,
        "target": oid,
        "skill": str(skill or "").strip(),
        "log": OBJECT_TALK_REWRITE_LOG,
        "rewritten": True,
    }


def resolve_social_npc_id(target: str, char_mgr=None) -> Optional[str]:
    """対象が対人（NPC/窓口オブジェクト）なら NPC ID を返す。"""
    raw = str(target or "").strip()
    if not raw:
        return None
    if raw in SOCIAL_OBJECT_TO_NPC:
        return SOCIAL_OBJECT_TO_NPC[raw]
    if char_mgr:
        try:
            from NPCSocialManager import find_npc_id_by_target
            resolved = find_npc_id_by_target(char_mgr, raw)
            if resolved:
                char = char_mgr.characters.get(resolved) or {}
                profile = char.get("profile") or {}
                if profile.get("is_npc") and not profile.get("monster"):
                    return resolved
        except Exception:
            pass
        char = char_mgr.characters.get(raw)
        if char and (char.get("profile") or {}).get("is_npc") and not (char.get("profile") or {}).get("monster"):
            return raw
        # 名前部分一致（フォールバック）
        for cid, c in char_mgr.characters.items():
            profile = c.get("profile") or {}
            if not profile.get("is_npc") or profile.get("monster"):
                continue
            name = str(profile.get("name") or "")
            if name and (raw == name or raw in name or name in raw):
                return cid
            for alias in profile.get("aliases") or []:
                if raw == alias or raw in str(alias) or str(alias) in raw:
                    return cid
    return None


def rewrite_human_investigation_to_talk(
    action: str,
    target: str,
    char_mgr=None,
    scenario_mgr=None,
    current_loc: str = "",
) -> Optional[Dict[str, Any]]:
    """
    対人対象への search/inspect/push 等を talk へ書き換える（Pattern A）。
    現在地の調査オブジェクト（マカリオ夫妻など）は書き換えない。
    書き換え不要なら None。
    """
    action = str(action or "").lower()
    if action not in SOCIAL_BLOCKED_ACTIONS:
        return None
    if is_investigable_location_object(scenario_mgr, current_loc, target):
        return None
    npc_id = resolve_social_npc_id(target, char_mgr=char_mgr)
    if not npc_id:
        return None
    return {
        "action": "talk",
        "target": npc_id,
        "skill": "",
        "log": HUMAN_INSPECT_REWRITE_LOG,
        "rewritten": True,
    }


def phase_for_location(loc_id: str, current_phase: str = "") -> str:
    """移動後に同期すべきフェーズ名。"""
    loc_id = str(loc_id or "")
    if loc_id in ("", "introduction"):
        return current_phase or "introduction"
    # 導入を離れたら調査フェーズへ
    if current_phase in ("", "introduction", "start"):
        return "investigation"
    return current_phase or "investigation"


def _introduction_move_unlocked(scenario_mgr) -> bool:
    if not scenario_mgr:
        return False
    flags = getattr(scenario_mgr, "flags", None) or {}
    if flags.get("talked_with_knott"):
        return True
    return bool(flags.get("knott_letter_read") and flags.get("knott_memo_read"))


def _resolve_talk_npc_id(target: str, char_mgr=None) -> str:
    npc_id = resolve_social_npc_id(target, char_mgr=char_mgr) or str(target or "").strip()
    if char_mgr and npc_id and npc_id not in INTRODUCTION_STALE_TALK_NPCS:
        resolved = resolve_social_npc_id(npc_id, char_mgr=char_mgr)
        if resolved:
            return str(resolved)
    return str(npc_id or "")


def is_completed_knott_talk_target(
    action: str,
    target: str,
    scenario_mgr=None,
    char_mgr=None,
) -> bool:
    """移動解禁後の Knott 宛 talk（ロケーション不問・幽霊NPC含む）。"""
    action = str(action or "").lower()
    if action not in TALK_ACTION_IDS:
        return False
    if not _introduction_move_unlocked(scenario_mgr):
        return False
    npc_id = _resolve_talk_npc_id(target, char_mgr=char_mgr)
    return npc_id in INTRODUCTION_STALE_TALK_NPCS


def is_completed_dolly_talk_target(
    action: str,
    target: str,
    scenario_mgr=None,
    char_mgr=None,
) -> bool:
    """ドーリーの秘密開示後の再 talk。"""
    action = str(action or "").lower()
    if action not in TALK_ACTION_IDS:
        return False
    flags = getattr(scenario_mgr, "flags", None) or {}
    if not (
        flags.get("dolly_talked")
        or flags.get("dolly_told_chapel_location")
        or flags.get("dolly_told_sanitarium_location")
    ):
        return False
    npc_id = _resolve_talk_npc_id(target, char_mgr=char_mgr)
    raw = str(target or "").strip().lower()
    return (
        npc_id in NEIGHBORHOOD_STALE_TALK_NPCS
        or raw in NEIGHBORHOOD_STALE_TALK_NPCS
    )


def _dolly_stale_suggested_fix(scenario_mgr=None, current_loc: str = "") -> Dict[str, str]:
    loc = str(
        current_loc
        or (getattr(scenario_mgr, "location", "") if scenario_mgr else "")
        or ""
    )
    flags = getattr(scenario_mgr, "flags", None) or {} if scenario_mgr else {}
    if loc == "the_neighborhood" and scenario_mgr:
        ext = "corbitt_house_exterior_view"
        obj = scenario_mgr.get_object_info(loc, ext) or {}
        if obj and not object_is_investigated(scenario_mgr, ext, obj, flags):
            return {"action": "search", "target": ext, "skill": "目星"}
        # チャペル未訪問のみ案内。調査済み／強制退去後は屋敷外観を優先（逆流防止）
        if flags.get("dolly_told_chapel_location") and not flags.get("chapel_investigated"):
            return {"action": "move", "target": "chapel_of_contemplation", "skill": ""}
        if flags.get("dolly_told_sanitarium_location") and not flags.get("sanitarium_info_found"):
            return {"action": "move", "target": "roxbury_sanitarium", "skill": ""}
        # 本筋: コービット屋敷外観へ
        exits = {
            str(e.get("id") or "")
            for e in (scenario_mgr.get_available_exits(loc) or [])
            if e.get("id")
        }
        if "corbitt_exterior" in exits:
            return {"action": "move", "target": "corbitt_exterior", "skill": ""}
    forced = build_forced_progress_action(scenario_mgr, loc) or {}
    return {
        "action": str(forced.get("action") or "move"),
        "target": str(forced.get("target") or "corbitt_exterior"),
        "skill": str(forced.get("skill") or ""),
    }


def validate_completed_dolly_talk(
    pc_action: Optional[Dict[str, Any]],
    *,
    scenario_mgr=None,
    current_loc: str = "",
    char_mgr=None,
) -> Dict[str, Any]:
    """ドーリー聞き取り済みの再 talk。現在地にいる会話は許可し、次行動を提案する。"""
    action = str((pc_action or {}).get("action", "wait") or "wait").lower()
    target = str((pc_action or {}).get("target", "") or "")
    if not is_completed_dolly_talk_target(
        action, target, scenario_mgr=scenario_mgr, char_mgr=char_mgr,
    ):
        return {"ok": True}
    suggested = _dolly_stale_suggested_fix(scenario_mgr, current_loc)
    npc_id = _resolve_talk_npc_id(target, char_mgr=char_mgr) or "dolly_shopkeeper"
    loc = str(
        current_loc
        or (getattr(scenario_mgr, "location", "") if scenario_mgr else "")
        or ""
    )
    present = bool(
        scenario_mgr
        and loc
        and hasattr(scenario_mgr, "is_npc_at_location")
        and scenario_mgr.is_npc_at_location(npc_id, loc, char_mgr=char_mgr)
    )
    if present:
        return {
            "ok": True,
            "preserve_social_intent": True,
            "nonprogress_social": True,
            "next_location_hint": (
                "【システム】ドーリーからの主要情報は得済みです。"
                f"次は `{suggested.get('action', 'move')}` / "
                f"`{suggested.get('target', '')}` を検討してください。"
            ),
            "suggested_fix": suggested,
        }
    return {
        "ok": False,
        "error": STALE_DOLLY_TALK_REJECT_ERROR,
        "error_code": "stale_dolly_talk",
        "suggested_fix": suggested,
        "needs_pl_retry": True,
    }


def is_boston_globe_clipping_investigated(scenario_mgr) -> bool:
    """切り抜きファイル調査が完了しているか。"""
    flags = getattr(scenario_mgr, "flags", None) or {}
    if flags.get("accessed_clipping_files"):
        return True
    investigated = set(flags.get("investigated_targets") or [])
    return "reference_room_clipping_files" in investigated


def build_boston_globe_stale_guidance(
    scenario_mgr=None,
    current_loc: str = "",
) -> Dict[str, Any]:
    """
    ボストン・グローブの無効行動に対する、フェーズ別エラー／推奨修正。
    """
    flags = getattr(scenario_mgr, "flags", None) or {}
    loc = str(
        current_loc
        or (getattr(scenario_mgr, "location", "") if scenario_mgr else "")
        or "boston_globe"
    )

    if is_boston_globe_clipping_investigated(scenario_mgr):
        suggested = build_forced_progress_action(scenario_mgr, loc) or {
            "action": "move",
            "target": "central_library",
        }
        return {
            "error": BOSTON_GLOBE_INVESTIGATION_DONE_HINT,
            "error_code": "globe_investigation_done",
            "suggested_fix": {
                "action": suggested.get("action", "move"),
                "target": suggested.get("target", "central_library"),
                "skill": suggested.get("skill") or "",
            },
        }

    if flags.get("artie_reference_room_access_granted"):
        return {
            "error": ARTIE_ACCESS_GRANTED_SEARCH_HINT,
            "error_code": "stale_post_access_social",
            "suggested_fix": {
                "action": "search",
                "target": "reference_room_clipping_files",
                "skill": "目星",
            },
        }

    if flags.get("artie_introduced"):
        return {
            "error": STALE_ARTIE_TALK_REJECT_ERROR,
            "error_code": "stale_artie_talk",
            "suggested_fix": {
                "action": "persuade",
                "target": "artie_wilmott",
                "skill": "説得",
            },
        }

    return {
        "error": STALE_RECEPTION_TALK_REJECT_ERROR,
        "error_code": "stale_reception_talk",
        "suggested_fix": {
            "action": "talk",
            "target": "globe_receptionist",
            "skill": "",
        },
    }


def is_stale_boston_globe_talk(
    action: str,
    target: str,
    scenario_mgr=None,
    current_loc: str = "",
    char_mgr=None,
) -> bool:
    """
    ボストン・グローブで進展しない対話/交渉:
    - 紹介済み後の受付への繰り返し talk
    - 許可未取得のままアーティへの雑談 talk（交渉ではない）
    - 許可取得後の受付・アーティへの talk/persuade（search へ誘導）
    """
    action = str(action or "").lower()
    flags = getattr(scenario_mgr, "flags", None) or {}
    loc = str(
        current_loc
        or (getattr(scenario_mgr, "location", "") if scenario_mgr else "")
        or ""
    )
    if loc and loc != "boston_globe":
        return False
    if not flags.get("artie_introduced"):
        return False

    npc_id = _resolve_talk_npc_id(target, char_mgr=char_mgr)
    raw = str(target or "").strip().lower()
    is_reception = npc_id in BOSTON_GLOBE_RECEPTION_NPCS or raw in BOSTON_GLOBE_RECEPTION_NPCS
    is_artie = npc_id in BOSTON_GLOBE_ARTIE_NPCS or raw in BOSTON_GLOBE_ARTIE_NPCS

    # 許可取得後: talk / 交渉とも受付・アーティは停滞（切り抜き search が必須）
    if flags.get("artie_reference_room_access_granted"):
        if action not in TALK_ACTION_IDS and action not in NEGOTIATION_ACTION_IDS:
            return False
        if is_reception or is_artie:
            return True
        return False

    # 許可前: 雑談 talk のみ停滞判定（交渉は有効）
    if action not in TALK_ACTION_IDS:
        return False
    if action in NEGOTIATION_ACTION_IDS:
        return False
    if is_reception:
        return True
    if is_artie:
        # 初回 talk はゲート秘密開示のため許可。2回目以降の雑談を停滞とみなす
        if char_mgr:
            char = (char_mgr.characters or {}).get(npc_id) or {}
            social = char.get("session_social") or {}
            if int(social.get("dialogue_count") or 0) < 1:
                return False
        return True
    return False


def is_stale_nonprogress_talk(
    action: str,
    target: str,
    scenario_mgr=None,
    current_loc: str = "",
    char_mgr=None,
) -> bool:
    """
    導入移動解禁後に Knott へ居座る talk など、進展を伴わない対話か。
    現在地が introduction 以外でも（幽霊NPC）検知する。
    ボストン・グローブの受付／アーティ雑談ループも含む。
    """
    if is_completed_knott_talk_target(
        action, target, scenario_mgr=scenario_mgr, char_mgr=char_mgr,
    ):
        return True
    if is_completed_dolly_talk_target(
        action, target, scenario_mgr=scenario_mgr, char_mgr=char_mgr,
    ):
        return True
    return is_stale_boston_globe_talk(
        action, target,
        scenario_mgr=scenario_mgr,
        current_loc=current_loc,
        char_mgr=char_mgr,
    )


def validate_completed_knott_talk(
    pc_action: Optional[Dict[str, Any]],
    *,
    scenario_mgr=None,
    current_loc: str = "",
    char_mgr=None,
) -> Dict[str, Any]:
    """
    talked_with_knott 後の Knott talk を扱う。
    - 現在地に Knott がいる追加質問は許可し、次ロケ提案だけ付与する
    - 別ロケの幽霊NPC対話は拒絶する
    """
    action = str((pc_action or {}).get("action", "wait") or "wait").lower()
    target = str((pc_action or {}).get("target", "") or "")
    if not is_completed_knott_talk_target(
        action, target, scenario_mgr=scenario_mgr, char_mgr=char_mgr,
    ):
        return {"ok": True}

    npc_id = _resolve_talk_npc_id(target, char_mgr=char_mgr) or "steven_knott"
    loc = str(
        current_loc
        or (getattr(scenario_mgr, "location", "") if scenario_mgr else "")
        or ""
    )
    present = bool(
        scenario_mgr
        and loc
        and hasattr(scenario_mgr, "is_npc_at_location")
        and scenario_mgr.is_npc_at_location(npc_id, loc, char_mgr=char_mgr)
    )
    suggested = build_forced_progress_action(scenario_mgr, loc) or {
        "action": "move",
        "target": "boston_globe",
    }
    if present:
        return {
            "ok": True,
            "preserve_social_intent": True,
            "nonprogress_social": True,
            "next_location_hint": (
                "【システム】追加の確認は可能ですが、依頼の核心情報は既に得ています。"
                f"次は `{suggested.get('action', 'move')}` / "
                f"`{suggested.get('target', 'boston_globe')}` への移動を検討してください。"
            ),
            "suggested_fix": {
                "action": suggested.get("action", "move"),
                "target": suggested.get("target", "boston_globe"),
            },
        }

    return {
        "ok": False,
        "error": STALE_KNOTT_TALK_REJECT_ERROR,
        "error_code": "stale_knott_talk",
        "suggested_fix": {
            "action": suggested.get("action", "move"),
            "target": suggested.get("target", "boston_globe"),
        },
        "needs_pl_retry": True,
    }


def pick_forced_progress_move_target(scenario_mgr, current_loc: str = "") -> Optional[str]:
    """解放済み exit から強制移動先を選ぶ（ロケーション別優先）。"""
    if not scenario_mgr:
        return None
    loc = str(current_loc or getattr(scenario_mgr, "location", "") or "")
    flags = getattr(scenario_mgr, "flags", None) or {}
    exits = scenario_mgr.get_available_exits(loc) if hasattr(scenario_mgr, "get_available_exits") else []
    if not exits:
        return None
    by_id = {str(e.get("id") or ""): e for e in exits if e.get("id")}

    def _skip_dest(dest: str) -> bool:
        if _omit_exhausted_hint_destination(dest, flags):
            return True
        # 未入館の外観から近所へ戻す往復を禁止（入口行動を先に取る）
        if (
            loc == "corbitt_exterior"
            and dest == "the_neighborhood"
            and not flags.get("corbitt_house_entered")
        ):
            return True
        return False

    preferred_list = LOCATION_FORCED_PROGRESS_PREFERENCE.get(loc) or FORCED_PROGRESS_MOVE_PREFERENCE
    for preferred in preferred_list:
        if preferred == loc:
            continue
        if preferred not in by_id:
            continue
        if _skip_dest(preferred):
            continue
        return preferred
    for preferred in FORCED_PROGRESS_MOVE_PREFERENCE:
        if preferred == loc:
            continue
        if preferred not in by_id:
            continue
        if _skip_dest(preferred):
            continue
        return preferred
    for exit_info in exits:
        dest = str(exit_info.get("id") or "")
        if not dest or dest == loc:
            continue
        if _skip_dest(dest):
            continue
        return dest
    return None


def _object_is_empty_clue(obj: Optional[Dict[str, Any]]) -> bool:
    """手がかりのない／ロール不要のオブジェクトか。"""
    if not obj or not isinstance(obj, dict):
        return False
    if obj.get("no_roll") or obj.get("empty_clue") or obj.get("skill_check") is False:
        return True
    clue = str(obj.get("clue_value") or "").strip().lower()
    return clue in ("none", "empty", "flavor", "background")


def _object_requires_flag_met(obj: Optional[Dict[str, Any]], flags: Dict[str, Any]) -> bool:
    """requires_flag / !flag の可視条件を満たしているか。"""
    if not obj or not isinstance(obj, dict):
        return True
    req = obj.get("requires_flag")
    if req is None or req == "":
        return True
    req = str(req).strip()
    flags = flags or {}
    if req.startswith("!"):
        return not bool(flags.get(req[1:]))
    return bool(flags.get(req))


def _object_access_gate_open(obj: Optional[Dict[str, Any]], flags: Dict[str, Any]) -> bool:
    """access_gate が未定義、または条件を満たしているか。"""
    if not obj or not isinstance(obj, dict):
        return True
    gate = obj.get("access_gate") or {}
    if not isinstance(gate, dict) or not gate:
        return True
    intro = str(gate.get("requires_intro_flag") or "").strip()
    perm = str(gate.get("permission_flag") or "").strip()
    if intro and not flags.get(intro):
        return False
    if perm and not flags.get(perm):
        return False
    return True


def object_is_currently_available(obj: Optional[Dict[str, Any]], flags: Optional[Dict[str, Any]] = None) -> bool:
    """現在のフラグで調査・操作可能なオブジェクトか（requires_flag / access_gate）。"""
    flags = flags or {}
    if not _object_requires_flag_met(obj, flags):
        return False
    if not _object_access_gate_open(obj, flags):
        return False
    return True


def object_is_investigated(
    scenario_mgr,
    obj_id: str,
    obj: Optional[Dict[str, Any]] = None,
    flags: Optional[Dict[str, Any]] = None,
) -> bool:
    """investigated_targets / investigated_flag のいずれかで調査済みか。"""
    return _object_is_investigated(scenario_mgr, str(obj_id or ""), obj, flags or {})


def _object_is_investigated(scenario_mgr, obj_id: str, obj: Optional[Dict[str, Any]], flags: Dict[str, Any]) -> bool:
    """investigated_targets / investigated_flag のいずれかで調査済みか。"""
    investigated = set(flags.get("investigated_targets") or [])
    if obj_id in investigated:
        if scenario_mgr and hasattr(scenario_mgr, "_is_research_reopened"):
            if scenario_mgr._is_research_reopened(obj_id):
                return False
        return True
    if obj and isinstance(obj, dict):
        inv_flag = obj.get("investigated_flag")
        if inv_flag and flags.get(inv_flag):
            return True
    return False


def _object_has_pending_followup_action(
    scenario_mgr,
    obj_id: str,
    obj: Optional[Dict[str, Any]],
    flags: Dict[str, Any],
    loc: str = "",
) -> bool:
    """
    search/inspect 済みでも、break/climb 等の未完了フォローアップが残っているか。
    チャペル床板→地階など「調べただけ」で枯渇扱いにしないために使う。
    """
    if not obj or not isinstance(obj, dict):
        return False
    if not object_is_currently_available(obj, flags):
        return False
    usable = {str(a).lower() for a in (obj.get("usable_actions") or [])}
    # use も含める（コービット外観の鍵開け等）
    followups = usable & {"break", "force", "push", "climb", "kick", "use"}
    if not followups:
        return False
    has_search = bool(usable & {"search", "inspect", "read"})
    inv_flag = obj.get("investigated_flag")
    search_done = bool(inv_flag and flags.get(inv_flag))
    if has_search and not search_done:
        # 通常の未調査カウント側で扱う
        return False
    oid = str(obj_id or "")
    loc = str(loc or "")
    # 黙想チャペル: 床板を調べた／壊せる状態だが未降下
    if oid == "rotting_floorboards" and loc == "chapel_of_contemplation":
        return not bool(flags.get("chapel_cellar_entered"))
    # コービット外観: 屋敷は調査済みでも未入館なら入口操作が残る
    if oid == "corbitt_house" and loc == "corbitt_exterior":
        return not bool(flags.get("corbitt_house_entered"))
    triggers = obj.get("triggers_flag_on_success") or {}
    if isinstance(triggers, dict) and triggers:
        return any(not flags.get(k) for k in triggers)
    clue_flags = obj.get("clue_flags_on_success") or []
    if clue_flags:
        return any(not flags.get(str(k)) for k in clue_flags)
    return False


def is_corbitt_approach_pingpong_move(from_loc: str, to_loc: str) -> bool:
    """近所↔外観だけの移動か（フラグ進展なしの往復判定用）。"""
    pair = {str(from_loc or ""), str(to_loc or "")}
    return pair == CORBITT_APPROACH_PINGPONG_LOCS


def pick_corbitt_exterior_entry_action(scenario_mgr) -> Optional[Dict[str, Any]]:
    """
    コービット外観での侵入系アクションを返す。
    - 未調査: search/corbitt_house
    - 調査済み・未入館: use（鍵）または break/force
    - 入館済み: None（呼び出し側で ground_floor への move を優先）
    """
    if not scenario_mgr:
        return None
    loc = "corbitt_exterior"
    flags = getattr(scenario_mgr, "flags", None) or {}
    if flags.get("corbitt_house_entered"):
        return None
    house = {}
    if hasattr(scenario_mgr, "get_object_info"):
        house = scenario_mgr.get_object_info(loc, "corbitt_house") or {}
    if not house:
        return None
    usable = {str(a).lower() for a in (house.get("usable_actions") or [])}
    examined = bool(flags.get("corbitt_house_examined")) or _object_is_investigated(
        scenario_mgr, "corbitt_house", house, flags,
    )
    if not examined and ("search" in usable or "inspect" in usable):
        dialogue = "コービット屋敷の外観と入口を調べる。"
        return {
            "action": "search" if "search" in usable else "inspect",
            "target": "corbitt_house",
            "skill": "目星",
            "message": dialogue,
            "dialogue": dialogue,
            "forced_by_system": True,
        }
    # 調査済み（または search 不可）→ 入口を開く
    auto_flag = str(house.get("auto_success_flag") or "case_accepted").strip()
    key_ready = bool(house.get("allows_key_use")) and bool(flags.get(auto_flag))
    if "use" in usable and key_ready:
        action = "use"
        skill = ""
        dialogue = "ノット氏の鍵でコービット屋敷の正面玄関を開ける。"
    elif "break" in usable:
        action = "break"
        skill = "STR"
        dialogue = "コービット屋敷の扉を力ずくでこじ開ける。"
    elif "force" in usable:
        action = "force"
        skill = "STR"
        dialogue = "コービット屋敷の扉を力ずくで押し開ける。"
    elif "use" in usable:
        action = "use"
        skill = ""
        dialogue = "コービット屋敷の入口を開ける。"
    else:
        return None
    return {
        "action": action,
        "target": "corbitt_house",
        "skill": skill,
        "message": dialogue,
        "dialogue": dialogue,
        "forced_by_system": True,
    }


def is_location_investigation_exhausted(scenario_mgr, current_loc: str = "") -> bool:
    """
    現在地の調査可能オブジェクトがすべて調査済みか。
    empty_clue / アクセスゲート未達の対象は集計から除外する。
    search 済みでも break/climb 等のフォローアップが残る場合は未枯渇。
    調査可能対象が1つも無い場合は False（移動強制の対象外）。
    """
    if not scenario_mgr:
        return False
    loc = str(current_loc or getattr(scenario_mgr, "location", "") or "")
    objects = (scenario_mgr.get_location_info(loc) or {}).get("objects") or {}
    flags = getattr(scenario_mgr, "flags", None) or {}
    searchable = 0
    pending = 0
    for obj_id, obj in objects.items():
        if not isinstance(obj, dict):
            continue
        if _object_is_empty_clue(obj):
            continue
        if not object_is_currently_available(obj, flags):
            continue
        usable = obj.get("usable_actions") or []
        has_search = any(a in usable for a in ("search", "inspect", "read"))
        has_followup = _object_has_pending_followup_action(
            scenario_mgr, str(obj_id), obj, flags, loc,
        )
        if not has_search and not has_followup:
            continue
        searchable += 1
        if has_followup:
            pending += 1
            continue
        if has_search and not _object_is_investigated(scenario_mgr, str(obj_id), obj, flags):
            pending += 1
    return searchable > 0 and pending == 0


def should_apply_location_exhausted_move(scenario_mgr, current_loc: str = "") -> bool:
    """調査ハブロケかつ調査枯渇のとき、move 誘導／強制を適用するか。"""
    loc = str(
        current_loc
        or (getattr(scenario_mgr, "location", "") if scenario_mgr else "")
        or ""
    )
    # 導入は「調査完了→強制移動」にしない（軽い誘導のみ）
    if loc == "introduction":
        return False
    if loc not in LOCATION_EXHAUSTED_MOVE_LOCATIONS:
        return False
    return is_location_investigation_exhausted(scenario_mgr, loc)


def _omit_exhausted_hint_destination(dest_id: str, flags: Optional[Dict[str, Any]] = None) -> bool:
    """枯渇ヒント／優先リストから除外すべき既取得ロケーションか。"""
    flags = flags or {}
    dest = str(dest_id or "")
    if dest == "boston_globe" and flags.get("found_newspaper_article_1918"):
        return True
    if dest == "central_library" and flags.get("found_corbitt_history_all"):
        return True
    if (
        dest == "chapel_of_contemplation"
        and flags.get("chapel_investigated")
        and flags.get("chapel_cellar_entered")
    ):
        return True
    return False


def build_location_exhausted_move_hint(scenario_mgr=None, current_loc: str = "") -> str:
    """調査枯渇時の move 誘導ヒント（現在地から行ける exit のみ列挙）。"""
    loc = str(
        current_loc
        or (getattr(scenario_mgr, "location", "") if scenario_mgr else "")
        or ""
    )
    flags = getattr(scenario_mgr, "flags", None) or {} if scenario_mgr else {}
    preferred = LOCATION_FORCED_PROGRESS_PREFERENCE.get(loc) or FORCED_PROGRESS_MOVE_PREFERENCE
    bits = []
    if scenario_mgr and hasattr(scenario_mgr, "get_available_exits"):
        exits = scenario_mgr.get_available_exits(loc) or []
        by_id = {str(e.get("id") or ""): e for e in exits if e.get("id")}
        for dest_id in preferred:
            if dest_id == loc or dest_id not in by_id:
                continue
            if _omit_exhausted_hint_destination(dest_id, flags):
                continue
            name = by_id[dest_id].get("name") or dest_id
            bits.append(f"`move` / `{dest_id}`（{name}）")
            if len(bits) >= 3:
                break
        if not bits:
            for exit_info in exits[:5]:
                dest_id = exit_info.get("id")
                if not dest_id or dest_id == loc:
                    continue
                if _omit_exhausted_hint_destination(str(dest_id), flags):
                    continue
                bits.append(f"`move` / `{dest_id}`（{exit_info.get('name') or dest_id}）")
                if len(bits) >= 3:
                    break
    if bits:
        extra = ""
        if "corbitt_exterior" in {
            str(e.get("id") or "")
            for e in ((scenario_mgr.get_available_exits(loc) or []) if scenario_mgr else [])
        }:
            extra = "直接コービット屋敷（`corbitt_exterior`）へ向かっても構いません。"
        return (
            "【システムヒント】この場所での調査はすべて完了しました。"
            "新しい場所へ移動（`move`）してください。例: "
            + " / ".join(bits)
            + "。すべての資料を集める必要はありません。"
            + extra
        )
    return LOCATION_EXHAUSTED_MOVE_HINT + " " + INVESTIGATION_BAILOUT_HINT


def pick_forced_progress_search_target(scenario_mgr, current_loc: str = "") -> Optional[str]:
    """移動先が無い／膠着時の代替: 現在地の未調査オブジェクト。"""
    if not scenario_mgr:
        return None
    loc = str(current_loc or getattr(scenario_mgr, "location", "") or "")
    objects = (scenario_mgr.get_location_info(loc) or {}).get("objects") or {}
    flags = getattr(scenario_mgr, "flags", None) or {}
    investigated = set(flags.get("investigated_targets") or [])

    # ボストン・グローブ: 許可取得後のみ資料室を優先候補に（未許可 search は access_gate で弾かれる）
    if (
        loc == "boston_globe"
        and flags.get("artie_reference_room_access_granted")
    ):
        ref = "reference_room_clipping_files"
        obj = objects.get(ref) or {}
        inv_flag = obj.get("investigated_flag") if isinstance(obj, dict) else None
        already = (
            ref in investigated
            or (inv_flag and flags.get(inv_flag))
            or flags.get("accessed_clipping_files")
        )
        if ref in objects and not already:
            return ref

    for obj_id, obj in objects.items():
        if not isinstance(obj, dict):
            continue
        if obj_id in investigated:
            continue
        if _object_is_empty_clue(obj):
            continue
        # アクセスゲート未達・requires_flag 未達は強制 search 候補から除外
        if not object_is_currently_available(obj, flags):
            continue
        usable = obj.get("usable_actions") or []
        if any(a in usable for a in ("search", "inspect", "read")):
            inv_flag = obj.get("investigated_flag")
            if inv_flag and flags.get(inv_flag):
                continue
            return str(obj_id)
    return None


def build_forced_progress_action(
    scenario_mgr,
    current_loc: str = "",
    *,
    char_name: str = "",
) -> Optional[Dict[str, Any]]:
    """
    ロケーション汎用の強制ブレイクアウト行動。
    - boston_globe + 許可取得済み: 未調査の参考資料室 search を優先
    - chapel + 床板フォローアップ未完了: break/climb を優先（地階未達のまま退去しない）
    - corbitt_exterior + 未入館: 入口を開く use/break/force（または未調査なら search）を近所への move より優先
    - corbitt_exterior + 入館済み: corbitt_ground_floor への move を優先
    - boston_globe + 許可未取得: LOCATION_FORCED_PROGRESS_PREFERENCE に従い move
    - それ以外 / search 不可: 解放済み exit への move
    - move も不可: 未調査オブジェクトの search
    """
    loc = str(current_loc or getattr(scenario_mgr, "location", "") or "")
    flags = getattr(scenario_mgr, "flags", None) or {}

    # チャペル: 床板の break/climb が残っているなら移動より優先
    if loc == "chapel_of_contemplation" and scenario_mgr:
        floor = scenario_mgr.get_object_info(loc, "rotting_floorboards") or {}
        if _object_has_pending_followup_action(
            scenario_mgr, "rotting_floorboards", floor, flags, loc,
        ):
            dialogue = "もろくなった床板を壊して地階へ降りる。"
            return {
                "action": "break",
                "target": "rotting_floorboards",
                "skill": "",
                "message": dialogue,
                "dialogue": dialogue,
                "forced_by_system": True,
            }

    # コービット外観: 未入館なら入口、入館済みなら1階へ（近所往復より優先）
    if loc == "corbitt_exterior" and scenario_mgr:
        if flags.get("corbitt_house_entered"):
            ground = "corbitt_ground_floor"
            exits = scenario_mgr.get_available_exits(loc) if hasattr(scenario_mgr, "get_available_exits") else []
            if any(str(e.get("id") or "") == ground for e in (exits or [])):
                loc_name = scenario_mgr.get_location_info(ground).get("name", ground)
                dialogue = f"{loc_name}へ入る。"
                return {
                    "action": "move",
                    "target": ground,
                    "skill": "",
                    "message": dialogue,
                    "dialogue": dialogue,
                    "forced_by_system": True,
                }
        else:
            entry = pick_corbitt_exterior_entry_action(scenario_mgr)
            if entry:
                return entry

    # 新聞社膠着: 許可取得済みなら資料室調査を先に試す（移動より優先）
    if loc == "boston_globe" and flags.get("artie_reference_room_access_granted"):
        search_target = pick_forced_progress_search_target(scenario_mgr, loc)
        if search_target == "reference_room_clipping_files":
            name = search_target
            if scenario_mgr:
                obj = scenario_mgr.get_object_info(loc, search_target) or {}
                name = obj.get("name", search_target)
            dialogue = f"{name}を調べる。"
            return {
                "action": "search",
                "target": search_target,
                "skill": "目星",
                "message": dialogue,
                "dialogue": dialogue,
                "forced_by_system": True,
            }

    target = pick_forced_progress_move_target(scenario_mgr, current_loc)
    if target:
        loc_name = target
        if scenario_mgr:
            loc_name = scenario_mgr.get_location_info(target).get("name", target)
        dialogue = f"{loc_name}へ向かう。"
        return {
            "action": "move",
            "target": target,
            "skill": "",
            "message": dialogue,
            "dialogue": dialogue,
            "forced_by_system": True,
        }

    search_target = pick_forced_progress_search_target(scenario_mgr, current_loc)
    if search_target:
        name = search_target
        if scenario_mgr:
            obj = scenario_mgr.get_object_info(current_loc, search_target) or {}
            name = obj.get("name", search_target)
        dialogue = f"{name}を調べる。"
        return {
            "action": "search",
            "target": search_target,
            "skill": "目星",
            "message": dialogue,
            "dialogue": dialogue,
            "forced_by_system": True,
        }
    return None


def build_forced_progress_move_action(
    scenario_mgr,
    current_loc: str = "",
    *,
    char_name: str = "",
) -> Optional[Dict[str, Any]]:
    """後方互換: 強制ブレイクアウト用アクション（move または search）。"""
    return build_forced_progress_action(
        scenario_mgr, current_loc, char_name=char_name,
    )


def build_context_stagnation_hint(
    scenario_mgr=None,
    current_loc: str = "",
    *,
    fallback: str = "",
) -> str:
    """場面・文脈依存の膠着ヒントを返す。"""
    loc = str(
        current_loc
        or (getattr(scenario_mgr, "location", "") if scenario_mgr else "")
        or ""
    )
    flags = getattr(scenario_mgr, "flags", None) or {}

    # 調査枯渇: search より move を最優先で提示（調査ハブロケのみ）
    if should_apply_location_exhausted_move(scenario_mgr, loc):
        return build_location_exhausted_move_hint(scenario_mgr, loc)

    # ボストン・グローブ: フラグ状態に応じて受付／交渉／調査を明示
    if loc == "boston_globe":
        if flags.get("artie_reference_room_access_granted"):
            return ARTIE_ACCESS_GRANTED_SEARCH_HINT
        if flags.get("artie_introduced"):
            return (
                ARTIE_NEGOTIATE_STAGNATION_HINT
                + "許可が取れない場合は中央図書館（`move` / `central_library`）や"
                "公文書館（`hall_of_records`）へ移動するか、"
                "資料を諦め直接コービット屋敷（`corbitt_exterior`）へ向かってください。"
            )
        return LOCATION_STAGNATION_HINTS.get("boston_globe", "")

    if loc in LOCATION_STAGNATION_HINTS:
        return LOCATION_STAGNATION_HINTS[loc]

    # 動的フォールバック: 解放済み移動先を列挙
    dest_bits = []
    if scenario_mgr and hasattr(scenario_mgr, "get_available_exits"):
        for exit_info in scenario_mgr.get_available_exits(loc) or []:
            dest_id = exit_info.get("id")
            dest_name = exit_info.get("name") or dest_id
            if dest_id:
                dest_bits.append(f"`move` / `{dest_id}`（{dest_name}）")
    if dest_bits:
        return (
            "【システムヒント】現在の場所での同じ行動の繰り返しは膠着しています。"
            "別の技能や対象を試すか、次の調査先へ移動してください。例: "
            + " / ".join(dest_bits[:3])
            + " "
            + INVESTIGATION_BAILOUT_HINT
        )
    return fallback or STAGNATION_STANDARD_PL_HINT_FALLBACK


def list_reachable_uninvestigated_for_pc(
    scenario_mgr,
    current_loc: str = "",
    *,
    char_mgr=None,
    pl_id=None,
    limit: int = 4,
) -> list:
    """
    手番PCが認識・到達可能な未調査オブジェクト候補（知識漏洩ガード付き）。
    隠し要素・未解放フラグ対象は含めない。
    """
    if not scenario_mgr:
        return []
    loc = str(current_loc or getattr(scenario_mgr, "location", "") or "")
    objects = (scenario_mgr.get_location_info(loc) or {}).get("objects") or {}
    flags = getattr(scenario_mgr, "flags", None) or {}
    pc_done = set()
    if char_mgr and pl_id and hasattr(char_mgr, "get_pc_investigated_targets"):
        pc_done = set(char_mgr.get_pc_investigated_targets(pl_id) or set())
    shared_done = set(flags.get("investigated_targets") or [])

    candidates = []
    for obj_id, obj in objects.items():
        if not isinstance(obj, dict):
            continue
        if not object_is_currently_available(obj, flags):
            continue
        if _object_is_empty_clue(obj):
            continue
        # 当該PCが既に調べた対象は除外（他PCの調査済みは候補に残す＝自分で調べられる）
        if obj_id in pc_done:
            continue
        # 世界進行上すでに枯渇し reject される共有済みは除外
        inv_flag = obj.get("investigated_flag")
        if inv_flag and flags.get(inv_flag) and obj_id in shared_done:
            # 共有で調査済みでも PC 未調査なら、再調査不可の場合のみ除外
            if not getattr(scenario_mgr, "_is_research_reopened", lambda *_: False)(obj_id):
                # reject_message がある＝再調査不可
                if obj.get("reject_message"):
                    continue
        usable = obj.get("usable_actions") or []
        if not any(a in usable for a in ("search", "inspect", "read")):
            continue
        name = obj.get("name") or obj_id
        purpose = str(obj.get("purpose") or "").strip()
        # purpose は表面情報（手がかり本文は出さない）
        label = f"`{obj_id}`（{name}）"
        if purpose:
            label += f" — {purpose[:40]}"
        candidates.append(label)
        if len(candidates) >= limit:
            break
    return candidates


def build_repeat_investigated_hint(
    scenario_mgr=None,
    current_loc: str = "",
    *,
    char_mgr=None,
    pl_id=None,
    repeat_key=None,
    fallback: str = "",
) -> str:
    """既調査対象の反復向け介入ヒント（未調査候補のみ提示）。"""
    target = ""
    if isinstance(repeat_key, (list, tuple)) and len(repeat_key) >= 2:
        target = str(repeat_key[-1] or "")
    target_name = target
    if scenario_mgr and target:
        obj = scenario_mgr.get_object_info(current_loc, target) or {}
        target_name = obj.get("name") or target
    head = (
        f"【システムヒント・既調査の反復】`{target}`（{target_name}）は"
        "すでに調べた／拒否された対象です。同じ search を繰り返さず、未調査の対象へ切り替えてください。"
        if target else
        "【システムヒント・既調査の反復】同じ対象への調査を繰り返しています。未調査の対象へ切り替えてください。"
    )
    candidates = list_reachable_uninvestigated_for_pc(
        scenario_mgr, current_loc, char_mgr=char_mgr, pl_id=pl_id, limit=3,
    )
    if candidates:
        return head + " 候補: " + " / ".join(candidates)
    # 候補が無ければ移動ヒントへフォールバック（隠し要素は暴露しない）
    move_hint = build_context_stagnation_hint(
        scenario_mgr, current_loc, fallback=fallback or STAGNATION_STANDARD_PL_HINT_FALLBACK,
    )
    return head + " " + move_hint


def build_discussion_loop_hint(*, fallback: str = "") -> str:
    """OOC／作戦会議の空回り向け介入ヒント。"""
    return (
        "【システムヒント・作戦会議の整理】議論が空回りしています。"
        "未決事項を1つに絞り、合意したら IC で具体行動（`search` / `move` / 交渉）を実行してください。"
        "メタ発言だけの連続は進展になりません。"
        + (f" {fallback}" if fallback else "")
    )


def build_lost_options_hint(
    scenario_mgr=None,
    current_loc: str = "",
    *,
    char_mgr=None,
    pl_id=None,
    fallback: str = "",
) -> str:
    """選択肢迷子向け: 到達可能な手掛かり／移動候補のみ提示。"""
    candidates = list_reachable_uninvestigated_for_pc(
        scenario_mgr, current_loc, char_mgr=char_mgr, pl_id=pl_id, limit=3,
    )
    bits = []
    if candidates:
        bits.append("未調査候補: " + " / ".join(candidates))
    if scenario_mgr and hasattr(scenario_mgr, "get_available_exits"):
        exits = []
        for exit_info in scenario_mgr.get_available_exits(current_loc) or []:
            dest_id = exit_info.get("id")
            if dest_id:
                exits.append(f"`move` / `{dest_id}`（{exit_info.get('name') or dest_id}）")
            if len(exits) >= 2:
                break
        if exits:
            bits.append("移動候補: " + " / ".join(exits))
    if bits:
        return (
            "【システムヒント・進行の手押し】同じ失敗パターンから離れてください。"
            + " ".join(bits)
        )
    return build_context_stagnation_hint(
        scenario_mgr, current_loc, fallback=fallback or STAGNATION_STANDARD_PL_HINT_FALLBACK,
    )


def build_reason_stagnation_hint(
    cause: str = "",
    scenario_mgr=None,
    current_loc: str = "",
    *,
    char_mgr=None,
    pl_id=None,
    repeat_key=None,
    fallback: str = "",
) -> str:
    """
    タスク6: 膠着原因別の段階的介入ヒント。
    提示対象は手番PCが到達・認識可能な範囲に限定する。
    """
    cause = str(cause or "lost_options")
    if cause == "discussion_loop":
        return build_discussion_loop_hint(fallback=fallback)
    if cause == "repeat_investigated":
        return build_repeat_investigated_hint(
            scenario_mgr, current_loc,
            char_mgr=char_mgr, pl_id=pl_id, repeat_key=repeat_key, fallback=fallback,
        )
    return build_lost_options_hint(
        scenario_mgr, current_loc,
        char_mgr=char_mgr, pl_id=pl_id, fallback=fallback,
    )


def count_investigation_deadlock_streak(all_events_log, current_loc: str = "") -> int:
    """
    失敗・拒否・ブロックのあと、同一ロケーションで move していない PC 行動の連続数。
    進展（成功・許可付与・移動）があれば 0。
    """
    loc = str(current_loc or "")
    streak = 0
    saw_failure = False
    for entry in reversed(all_events_log or []):
        meta = entry.get("meta") or {}
        if meta.get("forced_progress_breakout"):
            break
        text = str(entry.get("text") or "")
        entry_loc = str(entry.get("location") or "")
        if entry_loc and entry_loc not in ("all", loc):
            break
        action = str(meta.get("action_id") or "").lower()
        if action == "move":
            break
        if text.startswith("システム:"):
            if any(k in text for k in ("アクセス許可が出た", "【進行】", "レギュラー成功", "ハード成功", "イクストリーム")):
                if "失敗" not in text and "ブロック" not in text:
                    break
            if any(k in text for k in ("失敗", "進行ブロック", "システムブロック", "拒否", "アクセスできない")):
                saw_failure = True
                continue
        if meta.get("pc_id") and action:
            streak += 1
    if not saw_failure:
        return 0
    return streak


def is_investigation_deadlock(
    all_events_log,
    current_loc: str = "",
    *,
    min_turns: int = INVESTIGATION_DEADLOCK_FORCE_TURNS,
) -> bool:
    """失敗後に同一ロケへ一定ターン以上留まり、進展がない。"""
    loc = str(current_loc or "")
    if not loc or loc.startswith("corbitt_"):
        return False
    return count_investigation_deadlock_streak(all_events_log, loc) >= min_turns


def validate_force_ic_action(
    pc_action: Optional[Dict[str, Any]],
    *,
    force_ic_action: bool = False,
    scenario_mgr=None,
    current_loc: str = "",
    char_mgr=None,
) -> Dict[str, Any]:
    """
    強制 IC フェーズ中の wait / 無駄 talk を拒絶する。

    Returns:
        {"ok": True} または
        {"ok": False, "error", "error_code", "suggested_fix", "needs_pl_retry": True}
    """
    if not force_ic_action:
        return {"ok": True}

    action = str((pc_action or {}).get("action", "wait") or "wait").lower()
    target = str((pc_action or {}).get("target", "") or "")
    suggested = build_forced_progress_action(scenario_mgr, current_loc) or {
        "action": "move",
        "target": "boston_globe",
    }

    if action in ("wait", "none", ""):
        return {
            "ok": False,
            "error": FORCE_IC_WAIT_REJECT_ERROR,
            "error_code": "force_ic_wait",
            "suggested_fix": {
                "action": suggested.get("action", "move"),
                "target": suggested.get("target", "boston_globe"),
            },
            "needs_pl_retry": True,
        }

    if is_stale_nonprogress_talk(
        action, target, scenario_mgr=scenario_mgr,
        current_loc=current_loc, char_mgr=char_mgr,
    ):
        error = STALE_KNOTT_TALK_REJECT_ERROR
        if is_stale_boston_globe_talk(
            action, target, scenario_mgr=scenario_mgr,
            current_loc=current_loc, char_mgr=char_mgr,
        ):
            npc_id = _resolve_talk_npc_id(target, char_mgr=char_mgr)
            raw = str(target or "").strip().lower()
            if npc_id in BOSTON_GLOBE_RECEPTION_NPCS or raw in BOSTON_GLOBE_RECEPTION_NPCS:
                error = STALE_RECEPTION_TALK_REJECT_ERROR
            else:
                error = STALE_ARTIE_TALK_REJECT_ERROR
        # 許可未取得時の強制進行は move 優先（資料室 search はゲートで弾かれる）
        if not suggested.get("forced_by_system"):
            suggested = build_forced_progress_action(scenario_mgr, current_loc) or suggested
        return {
            "ok": False,
            "error": error,
            "error_code": "force_ic_stale_talk",
            "suggested_fix": {
                "action": suggested.get("action", "move"),
                "target": suggested.get("target", "central_library"),
            },
            "needs_pl_retry": True,
        }

    return {"ok": True}


# ---------------------------------------------------------------------------
# タスク3: PL提案技能のエンジン上書き（判定権限の一元化）
# ---------------------------------------------------------------------------

ENGINE_NO_SKILL_ACTIONS = frozenset({
    "move", "wait", "", "none", "climb", "push", "break", "kick", "force",
    "use", "open", "close", "defend", "attack", "shoot", "flee",
})

INVESTIGATION_ACTION_IDS_FOR_JUDGMENT = frozenset({"search", "inspect", "read", "listen", "spot"})


def resolve_engine_action_judgment(
    scenario_mgr,
    action_id,
    target="",
    proposed_skill="",
    loc_id=None,
    *,
    char_mgr=None,
):
    """
    PLの action/target/skill 提案を受け取り、エンジン側の最終判定条件を確定する。

    - skill / difficulty の正は ScenarioManager（オブジェクト定義・required_check）
    - 社交は許可技能集合内のみ PL 提案を採用し、それ以外は既定技能へ上書き
    - 未対応行動は usable_actions マッピング情報を返す（実行側で coerce / reject）

    戻り値 dict:
      action_id, target, proposed_skill, skill_name, difficulty,
      skill_overridden, allowed_skills, required_check, log, remapped
    """
    from NPCSocialManager import (
        SOCIAL_SKILLS,
        find_npc_id_by_target,
        is_casual_talk,
        is_negotiation_skill_for_npc,
        is_social_action,
        npc_negotiation_skills,
        resolve_social_skill_name,
    )

    action_id = str(action_id or "wait").lower().strip()
    target = str(target or "").strip()
    proposed = str(proposed_skill or "").strip()
    loc_id = loc_id or (getattr(scenario_mgr, "location", None) if scenario_mgr else None)
    npc_id = ""
    if char_mgr and target:
        npc_id = find_npc_id_by_target(char_mgr, target) or ""

    out = {
        "action_id": action_id,
        "target": target,
        "proposed_skill": proposed,
        "skill_name": "",
        "difficulty": "regular",
        "skill_overridden": False,
        "allowed_skills": [],
        "required_check": None,
        "log": "",
        "remapped": False,
    }

    if not scenario_mgr:
        if is_social_action(action_id, proposed) and not (
            is_casual_talk(action_id, proposed)
            and not is_negotiation_skill_for_npc(proposed, npc_id, char_mgr)
        ):
            allowed = sorted(set(SOCIAL_SKILLS) | set(npc_negotiation_skills(char_mgr, npc_id)))
            engine_skill = resolve_social_skill_name(
                action_id, proposed, npc_id=npc_id, char_mgr=char_mgr,
            )
            if proposed and not is_negotiation_skill_for_npc(proposed, npc_id, char_mgr):
                out["skill_overridden"] = True
                out["log"] = (
                    f"【判定条件・システム確定】提案技能〈{proposed}〉は社交判定に使えません。"
                    f"システムが〈{engine_skill}〉で判定します。"
                )
                engine_skill = resolve_social_skill_name(
                    action_id, "", npc_id=npc_id, char_mgr=char_mgr,
                )
            out["skill_name"] = engine_skill
            out["allowed_skills"] = allowed
        return out

    logs = []

    # usable_actions 補正は process_system_action 側で先行適用済み想定。
    # ここでも未適用なら補完する（単体呼び出し互換）。
    if hasattr(scenario_mgr, "coerce_object_action") and target:
        allowed = []
        obj = scenario_mgr.get_object_info(loc_id, target) if hasattr(scenario_mgr, "get_object_info") else {}
        if obj:
            allowed = [str(a).lower() for a in (obj.get("usable_actions") or [])]
        if allowed and action_id not in allowed:
            coerced = scenario_mgr.coerce_object_action(action_id, target, loc_id)
            if coerced and coerced.get("blocked"):
                out["required_check"] = {
                    "type": "blocked",
                    "system_log": coerced.get("log", ""),
                    "kp_instruction": coerced.get("kp_instruction", ""),
                }
                out["log"] = str(coerced.get("log") or "").strip()
                return out
            if coerced and coerced.get("remapped"):
                action_id = coerced["action_id"]
                out["action_id"] = action_id
                out["remapped"] = True
                if coerced.get("log"):
                    logs.append(coerced["log"])

    required = scenario_mgr.get_required_check(action_id, target, loc_id)
    out["required_check"] = required
    out["difficulty"] = scenario_mgr.get_action_difficulty(
        action_id, target, loc_id, required_check=required,
    )

    if required and required.get("type") in ("opposed_str", "auto_success", "luck"):
        if proposed:
            out["skill_overridden"] = True
            logs.append(
                f"【判定条件・システム確定】提案技能〈{proposed}〉は本行動では使用しません。"
                f"システムが {required.get('type')} 判定を適用します。"
            )
        out["skill_name"] = ""
        out["log"] = "\n".join(logs).strip()
        return out

    if action_id in INVESTIGATION_ACTION_IDS_FOR_JUDGMENT and target:
        inv = scenario_mgr.resolve_investigation_skill(
            action_id, target, proposed_skill=proposed, loc_id=loc_id, required_check=required,
        )
        out["skill_name"] = inv.get("skill_name", "")
        out["allowed_skills"] = list(inv.get("allowed_skills") or [])
        out["difficulty"] = inv.get("difficulty") or out["difficulty"]
        out["skill_overridden"] = bool(inv.get("skill_overridden"))
        out["required_check"] = inv.get("required_check")
        if out["skill_overridden"]:
            allowed_text = " / ".join(out["allowed_skills"]) or "（既定）"
            logs.append(
                f"【判定条件・システム確定】PL提案技能〈{proposed or '（空）'}〉を採用せず、"
                f"シナリオ定義に従い〈{out['skill_name']}〉"
                f"（許可: {allowed_text} / 難易度: {out['difficulty']}）で判定します。"
            )
        out["log"] = "\n".join(logs).strip()
        return out

    if is_social_action(action_id, proposed):
        npc_extra = npc_negotiation_skills(char_mgr, npc_id)
        if is_casual_talk(action_id, proposed) and not is_negotiation_skill_for_npc(
            proposed, npc_id, char_mgr,
        ):
            if proposed:
                out["skill_overridden"] = True
                logs.append(
                    f"【判定条件・システム確定】雑談（talk）のため提案技能〈{proposed}〉は無視し、"
                    "ダイス判定なしで処理します。"
                )
            out["skill_name"] = ""
            out["allowed_skills"] = []
            out["log"] = "\n".join(logs).strip()
            return out

        allowed = sorted(set(SOCIAL_SKILLS) | set(npc_extra))
        matched = ""
        if proposed:
            for skill in allowed:
                if proposed == skill or proposed in skill or skill in proposed:
                    matched = skill
                    break
        if matched:
            engine_skill = matched
            overridden = False
        else:
            engine_skill = resolve_social_skill_name(
                action_id, "", npc_id=npc_id, char_mgr=char_mgr,
            )
            overridden = bool(proposed and proposed != engine_skill)
        out["skill_name"] = engine_skill
        out["allowed_skills"] = allowed
        out["skill_overridden"] = overridden
        if overridden:
            logs.append(
                f"【判定条件・システム確定】提案技能〈{proposed}〉は交渉技能として無効です。"
                f"システムが〈{engine_skill}〉で判定します。"
            )
        out["log"] = "\n".join(logs).strip()
        return out

    if action_id in ENGINE_NO_SKILL_ACTIONS or not proposed:
        if proposed and action_id in ENGINE_NO_SKILL_ACTIONS:
            out["skill_overridden"] = True
            logs.append(
                f"【判定条件・システム確定】action `{action_id}` では技能判定を行いません。"
                f"提案技能〈{proposed}〉は無視します。"
            )
        out["skill_name"] = ""
        out["log"] = "\n".join(logs).strip()
        return out

    out["skill_name"] = ""
    out["skill_overridden"] = True
    logs.append(
        f"【判定条件・システム確定】未対応または非調査アクション `{action_id}` のため、"
        f"提案技能〈{proposed}〉は採用しません。"
    )
    out["log"] = "\n".join(logs).strip()
    return out


# ==========================================
# PC 人物誤認 / KP 確定矛盾の検出（明確な違反のみ）
# ==========================================

PL_IDENTITY_MISMATCH_ERROR = (
    "【システム検証エラー・人物取り違え】"
    "現在操作中の探索者の名前・職業と矛盾する自己紹介／自己扱いです。"
    "他PCの身分を名乗らず、自身の設定で再出力してください。"
    "他PCへの呼びかけや協力自体は問題ありません。"
)
PL_IDENTITY_MISMATCH_CODE = "pl_identity_mismatch"

KP_NARRATION_CONTRADICTION_CODE = "kp_narration_contradiction"

# 自己紹介として他PC名を名乗る明確パターン
_SELF_INTRO_SUFFIX_RE = re.compile(
    r"(です|だ|である|と申します|と申す|と言います|と言う|でございます)([。．!！?？\s]|$)"
)
_SELF_ADDRESS_RE = re.compile(
    r"(?P<name>[\w一-龥ぁ-んァ-ン]{2,12})[、,]\s*(君|きみ|あなた|お前|おまえ)(は|も)"
)

# SAN減少だけから確定してはならない表現（断定）
_SAN_OVERCLAIM_RE = re.compile(
    r"(記憶を失った|記憶喪失した|記憶が消えた|知識が消えた|知識を失った|"
    r"発狂した|狂ってしまった|行動不能になった|意識を完全に失った)"
)

# 未選択PC行動の先取り（二人称の明確な断定のみ。
# 「教授は／刑事は」は同席PCの描写や呼びかけで誤爆しやすいので含めない）
_UNAUTHORIZED_PC_ACTION_RE = re.compile(
    r"(あなたは|探索者は).{0,12}(調べ始めた|歩き出した|扉を開けた|"
    r"隣室へ進んだ|次の部屋へ入った|新たに宣言した)"
)

_EXTRA_PERMISSION_RE = re.compile(
    r"("
    r"(?:追加|別|新たな|もう一人の|別の担当).{0,16}(?:許可|承認).{0,16}(?:必要|要る|要する)|"
    r"(?:許可|承認)(?:も|が)(?:必要|要る)|"
    r"[\w一-龥ぁ-んァ-ン・]{2,24}(?:さん|氏)?(?:の|が|へ|に).{0,8}(?:許可|承認).{0,16}(?:必要|要る|要する)|"
    r"まだ入れない|容易には得られない|門前払い|手続きが必要|"
    r"(?:アクセス|入室|閲覧).{0,10}(?:できない|させない|認められない)"
    r")"
)

# 「以前は許可が必要だったが今は許可済み」など、過去／上書き説明
_PAST_PERMISSION_CONTEXT_RE = re.compile(
    r"("
    r"(?:以前|前回|かつては|通常は|もともと|本来は).{0,24}(?:許可|承認).{0,16}(?:必要|要る)|"
    r"(?:今は|今回は|すでに|既に).{0,12}(?:許可|入れ|アクセス|閲覧).{0,12}(?:済み|できた|可能|有効)|"
    r"許可(?:は)?(?:既に|すでに)(?:降りて|出て|有効|済み)"
    r")"
)

# 「ただし／しかし」で追加条件を載せる場合は過去説明でも違反寄り
_ADDITIONAL_CONDITION_CONJ_RE = re.compile(
    r"(ただし|しかし|なお|その代わり).{0,60}(?:許可|承認).{0,16}(?:必要|要る|要する)"
)

_SKILL_SUCCESS_CLAIM_RE = re.compile(
    r"〈?(?P<skill>目星|信用|説得|言いくるめ|威圧|図書館|心理学|鍵開け|隠密|歴史|科学|医学|考古学)〉?"
    r".{0,6}(が見事に当た|が当たった|が功を奏|に成功|判定に成功|が見事)"
)


def _normalize_person_token(text):
    return str(text or "").strip().replace(" ", "").replace("　", "")


def collect_pc_identity_profiles(char_mgr, active_pcs=None):
    """active PC の名前・職業プロファイル一覧。"""
    profiles = []
    if not char_mgr:
        return profiles
    ids = list(active_pcs or getattr(char_mgr, "active_pc_list", None) or [])
    if not ids and hasattr(char_mgr, "list_pc_ids"):
        try:
            ids = list(char_mgr.list_pc_ids())
        except Exception:
            ids = []
    for pid in ids:
        pc = char_mgr.get_pc(pid) or {}
        profile = pc.get("profile") or {}
        name = str(profile.get("name") or char_mgr.get_pc_name(pid) or pid).strip()
        occupation = str(profile.get("occupation") or "").strip()
        # 姓・名の短縮形（呼びかけ検出用）
        short = name
        for suffix in ("刑事", "教授", "博士", "氏", "さん"):
            if short.endswith(suffix) and len(short) > len(suffix) + 1:
                short = short[: -len(suffix)]
                break
        profiles.append({
            "pc_id": pid,
            "name": name,
            "occupation": occupation,
            "short_name": short,
            "name_norm": _normalize_person_token(name),
            "short_norm": _normalize_person_token(short),
        })
    return profiles


def detect_pl_identity_violation(
    dialogue,
    *,
    self_pc_id=None,
    self_name="",
    self_occupation="",
    other_profiles=None,
    allowed_aliases=None,
):
    """
    明確な人物取り違えのみ検出する。
    - 他PC名での自己紹介
    - 自身を別人として呼びかける自己言及
    他PCへの呼びかけ・協力・別分野への言及は違反にしない。
    曖昧な文は検出しない（置換もしない）。
    """
    text = str(dialogue or "").strip()
    if not text:
        return None

    allowed = {
        _normalize_person_token(a)
        for a in (allowed_aliases or [])
        if str(a or "").strip()
    }
    self_name_n = _normalize_person_token(self_name)
    self_occ = str(self_occupation or "").strip()
    others = list(other_profiles or [])

    # 1) 他PC名での自己紹介
    for other in others:
        oname = other.get("name") or ""
        onorm = other.get("name_norm") or _normalize_person_token(oname)
        if not onorm or onorm == self_name_n:
            continue
        if onorm in allowed:
            continue
        # 「他PC名です／と申します」
        idx = text.find(oname)
        if idx < 0 and other.get("short_name"):
            # 短縮名単体は呼びかけと区別しづらいので、自己紹介接尾辞付きのみ
            short = other.get("short_name")
            idx = text.find(short)
            if idx >= 0:
                oname = short
                onorm = other.get("short_norm") or _normalize_person_token(short)
            else:
                continue
        if idx < 0:
            continue
        after = text[idx + len(oname): idx + len(oname) + 16]
        if _SELF_INTRO_SUFFIX_RE.match(after.lstrip()):
            # 直前が呼びかけ（「〜へ」「〜さん、」）なら自己紹介ではない
            before = text[max(0, idx - 8): idx]
            if any(tok in before for tok in ("さん", "氏", "へ", "に", "、", ",")):
                # 「マクガフィン刑事さん、」は呼びかけ
                if before.rstrip().endswith(("、", ",", "へ", "に")) or "さん" in before or "氏" in before:
                    continue
            return {
                "error": PL_IDENTITY_MISMATCH_ERROR,
                "error_code": PL_IDENTITY_MISMATCH_CODE,
                "reason": f"other_pc_self_intro:{oname}",
            }

    # 2) 他PCの職業身分を「〜と申します」で名乗る（例: 教授が「刑事のトムと申します」）
    if self_occ and "教授" in self_occ:
        if re.search(r"(刑事|探偵).{0,8}(と申します|と申す|です)", text):
            # 他に刑事PCがいる、または明示的な身分詐称許可が無い場合
            if any("刑事" in str(o.get("occupation") or "") for o in others) or True:
                if not allowed:
                    return {
                        "error": PL_IDENTITY_MISMATCH_ERROR,
                        "error_code": PL_IDENTITY_MISMATCH_CODE,
                        "reason": "false_occupation_intro",
                    }
    if self_occ and "刑事" in self_occ:
        if re.search(r"(教授|博士).{0,8}(と申します|と申す|です)", text) and not allowed:
            # 「民俗学の研究の一環」は自己紹介ではないので、申します/ですが職業直結のときだけ
            if re.search(r"(私は|我々は)?\s*(民俗学)?教授.{0,6}(と申します|です)", text):
                return {
                    "error": PL_IDENTITY_MISMATCH_ERROR,
                    "error_code": PL_IDENTITY_MISMATCH_CODE,
                    "reason": "false_occupation_intro",
                }

    # 自身の職業と矛盾する身分主張（正式自己紹介以外も含む）
    # 例: 「刑事としての立場」「刑事の権限で」「教授として捜査」
    foreign_roles = ("刑事", "探偵") if "教授" in self_occ else (("教授", "博士") if "刑事" in self_occ else ())
    if not allowed:
        for role in foreign_roles:
            claim_re = re.compile(
                re.escape(role)
                + r"(?:"
                r"として(?:の)?(?:立場|身分|調査|捜査|協力|情報提供|お願い)|"
                r"の(?:権限|名において|資格)(?:で|により|による)?|"
                r"として.{0,16}(?:情報提供|捜査|調査|お願い)"
                r")"
            )
            for claim in claim_re.finditer(text):
                before = text[max(0, claim.start() - 24):claim.start()]
                if re.search(r"(?:彼|彼女|あなた|仲間|同僚|同行者|友人)(?:の)?$", before):
                    continue
                # 「マクガフィン刑事としての立場を尊重」など他PC言及は除外
                if any(
                    str(o.get("name") or "").endswith(role)
                    and before.endswith(str(o.get("name") or "")[:-len(role)])
                    for o in others
                    if len(str(o.get("name") or "")) > len(role)
                ):
                    continue
                # 「〜刑事としての立場」で名前付き他PCを指す場合
                if any(
                    str(o.get("short_name") or "")
                    and before.endswith(str(o.get("short_name")))
                    for o in others
                ):
                    continue
                return {
                    "error": PL_IDENTITY_MISMATCH_ERROR,
                    "error_code": PL_IDENTITY_MISMATCH_CODE,
                    "reason": "false_occupation_claim",
                }

    # 3) 自分自身を別人として呼びかける（「エレノア、君は少し休んで」）
    m = _SELF_ADDRESS_RE.search(text)
    if m:
        addressed = _normalize_person_token(m.group("name"))
        self_short = ""
        if self_name_n:
            self_short = self_name_n
            for suffix in ("刑事", "教授", "博士"):
                if self_short.endswith(suffix):
                    self_short = self_short[: -len(suffix)]
                    break
        if addressed and addressed in {self_name_n, self_short} and addressed:
            return {
                "error": PL_IDENTITY_MISMATCH_ERROR,
                "error_code": PL_IDENTITY_MISMATCH_CODE,
                "reason": "self_as_other_address",
            }

    return None


def extract_resolved_skill_from_result(last_system_result=None, last_pl_action=None):
    """システム確定技能を優先して返す（PL提案技能ではない）。"""
    result = last_system_result or {}
    for key in ("resolved_skill", "skill_name", "engine_skill", "skill"):
        val = str(result.get(key) or "").strip()
        if val:
            return val
    log = str(result.get("log") or "")
    # 【技能:信用】 or 〈信用〉で判定
    m = re.search(r"【技能[:：]([^】]+)】", log)
    if m:
        return m.group(1).strip()
    m = re.search(r"〈([^〉]+)〉[^。\n]{0,20}で判定", log)
    if m:
        return m.group(1).strip()
    m = re.search(r"システム確定】[^〈\n]*〈([^〉]+)〉", log)
    if m:
        return m.group(1).strip()
    # PL提案を採用せず…〈信用〉
    m = re.search(r"採用せず[^〈\n]*〈([^〉]+)〉", log)
    if m:
        return m.group(1).strip()
    return str((last_pl_action or {}).get("skill") or "").strip()


def is_system_outcome_success(last_system_result=None):
    result = last_system_result or {}
    if result.get("dice_success") or result.get("confirmed_fact") or result.get("handout_text"):
        return True
    if result.get("blocked"):
        return False
    try:
        level = int(result.get("success_level") or result.get("status") or 0)
    except (TypeError, ValueError):
        level = 0
    return level >= 2


def is_system_outcome_failure(last_system_result=None):
    result = last_system_result or {}
    if result.get("dice_success") or result.get("confirmed_fact"):
        return False
    if result.get("blocked"):
        return True
    try:
        level = int(result.get("success_level") or result.get("status") or -1)
    except (TypeError, ValueError):
        level = -1
    return 0 <= level < 2 and (
        "失敗" in str(result.get("log") or "")
        or result.get("roll_type") in ("skill", "social_talk", "social_negotiate")
    )


def _access_flag_matches_context(flag_key, *, current_loc="", target=""):
    """許可フラグが現在地／対象に関係するか（グローバル全マッチはしない）。"""
    k = str(flag_key or "").lower()
    if not (
        k.endswith("_access_granted")
        or k.endswith("_access_allowed")
        or "access_granted" in k
    ):
        return False
    loc = str(current_loc or "").lower().replace("-", "_")
    tgt = str(target or "").lower().replace("-", "_")
    if loc and loc in k:
        return True
    if tgt and tgt and tgt in k:
        return True
    # 代表ロケの別名マッピング（フラグ名が loc_id と完全一致しない場合）
    loc_aliases = {
        "boston_globe": ("artie", "boston_globe", "globe", "reference_room"),
        "central_library": ("library", "central_library", "archives"),
        "hall_of_records": ("hall_of_records", "records"),
        "higher_courts_police_station": ("police", "archives", "higher_courts"),
    }
    for alias in loc_aliases.get(loc, ()):
        if alias and alias in k:
            return True
    return False


def is_access_already_granted(
    scenario_mgr=None,
    last_system_result=None,
    settled=None,
    *,
    current_loc=None,
    target=None,
):
    """現在文脈のアクセス許可を検出（特定NPC名に依存しない／無関係フラグは見ない）。"""
    settled = settled or {}
    if settled.get("access_granted"):
        return True
    result = last_system_result or {}
    if (result.get("social") or {}).get("access_just_granted"):
        return True
    log = str(result.get("log") or "")
    if "アクセス許可が出た" in log or ("閲覧許可" in log and "出た" in log):
        return True

    loc = str(
        current_loc
        or (getattr(scenario_mgr, "location", "") if scenario_mgr else "")
        or result.get("location")
        or ""
    )
    tgt = str(target or result.get("target") or "").strip()

    flags = {}
    if scenario_mgr is not None:
        flags = getattr(scenario_mgr, "flags", None) or {}
    for key, val in flags.items():
        if not val:
            continue
        if _access_flag_matches_context(key, current_loc=loc, target=tgt):
            return True
    return False


def detects_extra_permission_demand_after_grant(text):
    """
    許可取得済みなのに追加承認者・門前払いを要求しているか。
    固有名詞（ルース等）に依存せず、過去説明・正常な対比は除外する。
    """
    body = str(text or "")
    if not body.strip():
        return False
    # 「ただし〜の許可が必要」は明確な追加条件
    if _ADDITIONAL_CONDITION_CONJ_RE.search(body):
        return True
    if not _EXTRA_PERMISSION_RE.search(body):
        return False
    # 過去／上書き文脈のみで、追加条件の接続詞が無ければ許容
    if _PAST_PERMISSION_CONTEXT_RE.search(body) and not _ADDITIONAL_CONDITION_CONJ_RE.search(body):
        # 「以前は必要だったが今は許可済み」→ OK
        # 「許可済み。ただしXの許可が必要」は上で既に True
        if re.search(r"(今は|今回は|すでに|既に|許可済み|許可は有効)", body):
            return False
    return True


def scrub_system_log_for_public_ic(log_text):
    """
    ICフォールバック用に、公開可能な確定文だけを残す。
    kp_instruction・secret_キー・内部プロンプト等は落とす。
    """
    text = str(log_text or "")
    if text.startswith("システム:"):
        text = text[len("システム:"):].strip()
    kept = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        low = line.lower()
        if any(tok in low for tok in (
            "kp_instruction", "prompt_block", "npc_roleplay", "flags.",
            "action_id=", "session_social", "内部指示", "システム内部",
        )):
            continue
        if "secret_" in line and line.startswith("【秘密開示】"):
            # secret_id は隠し、開示本文のみ残す
            m = re.match(r"【秘密開示】\s*[\w_]+:\s*(.*)$", line)
            if m and m.group(1).strip():
                kept.append(m.group(1).strip())
            continue
        if line.startswith("【秘密開示】") and "secret_" in line:
            continue
        if "未開示" in line or "KPへの指示" in line:
            continue
        kept.append(line)
    return "\n".join(kept).strip()


def extract_public_confirmed_narration_parts(last_system_result=None, fallback_text=""):
    """フォールバック本文の素材。辞書全体や内部指示は使わない。"""
    result = last_system_result or {}
    parts = []
    for key in ("confirmed_fact", "handout_text", "handout_ic_block"):
        val = str(result.get(key) or "").strip()
        if val and val not in parts:
            parts.append(val)
    public_log = scrub_system_log_for_public_ic(result.get("log") or result.get("system_log") or "")
    if public_log and public_log not in parts:
        parts.append(public_log)
    fb = scrub_system_log_for_public_ic(fallback_text)
    if fb and fb not in parts:
        # fallback_text が log と同一なら重複しない
        if fb not in "\n".join(parts):
            parts.append(fb)
    return parts


def detect_kp_narration_violations(
    text,
    *,
    scenario_mgr=None,
    last_pl_action=None,
    last_system_result=None,
    settled=None,
):
    """
    KP描写の明確な矛盾のみ返す（list[str]）。
    一般語の有無だけでは成功/失敗を判定しない。
    「以前は失敗したが今回は成功」は拒否しない。
    追加許可要求は固有名詞に依存せず検出する。
    """
    body = str(text or "")
    if not body.strip():
        return ["empty_text"]

    settled = dict(settled or {})
    result = last_system_result or {}
    loc = str(
        (getattr(scenario_mgr, "location", "") if scenario_mgr else "")
        or result.get("location")
        or ""
    )
    tgt = str(
        result.get("target")
        or (last_pl_action or {}).get("target")
        or ""
    )
    access_granted = is_access_already_granted(
        scenario_mgr, result, settled=settled, current_loc=loc, target=tgt,
    )

    violations = []

    # 許可済みなのに追加許可・門前払い（固有名詞非依存）
    if access_granted and detects_extra_permission_demand_after_grant(body):
        violations.append("extra_permission_after_grant")

    # 確定技能の取り違え（成功描写で別技能を成功させたと断言）
    resolved_skill = str(
        settled.get("resolved_skill")
        or extract_resolved_skill_from_result(result, last_pl_action)
        or ""
    ).strip()
    proposed = str(
        settled.get("proposed_skill")
        or (last_pl_action or {}).get("skill")
        or ""
    ).strip()
    if resolved_skill and is_system_outcome_success(result):
        for m in _SKILL_SUCCESS_CLAIM_RE.finditer(body):
            claimed = m.group("skill")
            if claimed and claimed != resolved_skill:
                if not proposed or claimed == proposed or claimed != resolved_skill:
                    violations.append(f"wrong_skill_success:{claimed}!={resolved_skill}")
                    break

    # 成功を空振り・失敗へ（強い否定のみ。過去失敗の対比は除外）
    if is_system_outcome_success(result):
        if re.search(r"(何も見つからなかった|何も見つかっていない|何も見つかったわけではない|何も発見できなかった|手がかりはなかった|手がかり[はが]得られなかった|失敗に終わった|許可は得られなかった)", body):
            if not re.search(r"(以前|前回|かつては).{0,12}(失敗|見つからなかった)", body):
                violations.append("success_negated")

    # 失敗を成功へ（強い成功断定のみ）
    if is_system_outcome_failure(result) and not is_system_outcome_success(result):
        if re.search(r"(見事に成功した|判定に成功した|許可を得た|手がかりを見つけた)", body):
            if not re.search(r"(以前|前回|かつては).{0,12}(失敗)", body):
                violations.append("failure_flipped_to_success")

    # SAN減少のみから記憶喪失等を確定
    san = result.get("san_check") or {}
    san_only = bool(result.get("san_auto_resolved") or san.get("required") or result.get("san_loss"))
    insanity_confirmed = bool(
        result.get("temporary_insanity")
        or result.get("indefinite_insanity")
        or (result.get("madness") or {}).get("triggered")
        or settled.get("insanity_confirmed")
    )
    if san_only and not insanity_confirmed and _SAN_OVERCLAIM_RE.search(body):
        violations.append("san_overclaim_memory_or_incapacity")

    # 未選択のPC行動の先取り
    dialogue = str((last_pl_action or {}).get("dialogue") or "")
    if _UNAUTHORIZED_PC_ACTION_RE.search(body):
        if not dialogue or not any(tok in body for tok in ("調べ始めた", "歩き出した") if tok in dialogue):
            violations.append("unauthorized_pc_action_or_speech")

    # KPが新しいPCセリフを代筆
    for qm in re.finditer(r"あなたは[「『]([^」』]{4,80})[」』]と(言った|述べた|答えた)", body):
        spoken = qm.group(1).strip()
        if spoken and spoken not in dialogue:
            violations.append("invented_pc_dialogue")
            break

    return violations


