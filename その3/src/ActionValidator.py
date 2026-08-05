"""
PL行動の厳密バリデーション（移動意図の一致・対人対象の調査禁止）。

エラー時は PL へ再生成を促すシステム通知文を返す。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple


# ---------------------------------------------------------------------------
# システム通知文（PL / KP へ渡す定型メッセージ）
# ---------------------------------------------------------------------------

MOVE_INTENT_MISMATCH_ERROR = (
    "【システム検証エラー・行動再選択】"
    "セリフ／OOCで示した移動希望先と、コマンドの move target が一致していません。"
    "（例: 「参考資料室へ行く」と言いながら `hall_of_records`＝公文書館へ move してはならない。"
    "参考資料室の切り抜きは boston_globe 内のオブジェクトであり、別ロケーションへの move ではない。）"
    "dialogue / pl_ooc_chat の目的地と `pc_ic_action.target` を一致させて、行動JSONを出し直してください。"
)

MOVE_NON_LOCATION_AS_MOVE_ERROR = (
    "【システム検証エラー・行動再選択】"
    "テキストが指しているのはロケーションへの移動ではなく、現在地の調査／対話対象です。"
    "move ではなく search / inspect / talk を使い、正しい target（オブジェクトIDまたはNPC ID）を指定して再出力してください。"
)

HUMAN_INSPECT_REWRITE_LOG = (
    "【アクション補正】対象は人物（または人がいる窓口）です。"
    "search / inspect / push は無効化し、talk（対話）へ切り替えました。"
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
FORCE_IC_ACTION_CHAT_ROUNDS = 3
FORCE_IC_ACTION_STAGNATION_STREAK = 4  # streak がこの値を超えたら発火（> 4）

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

FORCE_PROGRESS_BREAKOUT_LOG = (
    "[システム] 膠着が上限に達したため、次の調査先へ強制移動します。"
)

# 導入で移動解禁後に居座る対象
INTRODUCTION_STALE_TALK_NPCS = frozenset({
    "steven_knott", "npc_steven_knott", "mr_knott",
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
    "introduction": ("boston_globe", "central_library", "hall_of_records"),
    "boston_globe": ("central_library", "hall_of_records", "the_neighborhood", "introduction"),
    "central_library": ("hall_of_records", "boston_globe", "the_neighborhood"),
    "hall_of_records": ("higher_courts_police_station", "boston_globe", "central_library"),
    "the_neighborhood": ("corbitt_exterior", "boston_globe", "central_library"),
}

# talk 系（進展判定用）
TALK_ACTION_IDS = frozenset({
    "talk", "speak", "chat", "converse", "対話", "会話", "話す",
})

# 場面依存ヒント（膠着時）
LOCATION_STAGNATION_HINTS = {
    "introduction": (
        "【システムヒント】この場所での聞き込みは十分です。"
        "ボストン・グローブ紙（`move` / `boston_globe`）へ移動し、過去の新聞記事を調べましょう。"
        "中央図書館（`central_library`）も有効な次の候補です。"
    ),
    "boston_globe": (
        "【システムヒント】編集者との同じ交渉の繰り返しは膠着しています。"
        "アーティに対し〈言いくるめ〉〈信用〉〈魅惑〉など別の交渉技能を試すか、"
        "許可が取れない場合は中央図書館（`move` / `central_library`）や公文書館（`hall_of_records`）へ移動してください。"
    ),
    "central_library": (
        "【システムヒント】図書館での調査が進んでいません。"
        "未調査の資料オブジェクトを `search` / `inspect` するか、"
        "公文書館・新聞社など別ロケーションへ `move` してください。"
    ),
    "hall_of_records": (
        "【システムヒント】公文書館での進行が停滞しています。"
        "事務官に `talk` するか、未調査の記録を調べるか、"
        "警察署ルート（`higher_courts_police_station`）へ移動を検討してください。"
    ),
}

# 汎用フォールバック（場面不明時のみ） / 後方互換エイリアス
STAGNATION_STANDARD_PL_HINT_FALLBACK = (
    "【システムヒント】現在調査が難航しています。"
    "ダイス判定失敗による停滞を避けるため、他の技能を用いたアプローチを宣言するか、"
    "未調査の対象を調べるか、解放済みロケーションへ `move` してください。"
)
STAGNATION_STANDARD_PL_HINT = STAGNATION_STANDARD_PL_HINT_FALLBACK


# ロケーションID → テキスト照合キーワード
LOCATION_INTENT_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "introduction": ("導入", "探偵事務所", "喫茶店", "ノット氏の元", "introduction"),
    "boston_globe": (
        "ボストン・グローブ", "ボストングローブ", "新聞社", "グローブ紙", "boston_globe",
    ),
    "central_library": ("中央図書館", "図書館", "central_library"),
    "hall_of_records": (
        "公文書館", "記録保管所", "公文書", "hall_of_records",
    ),
    "higher_courts_police_station": (
        "警察署", "上級裁判所", "中央警察署", "higher_courts",
    ),
    "the_neighborhood": ("近隣", "近所", "住民", "the_neighborhood"),
    "roxbury_sanitarium": ("サナトリウム", "ロクスベリー", "roxbury"),
    "chapel_of_contemplation": ("チャペル", "黙想", "chapel"),
    "corbitt_exterior": ("屋敷の外", "コービット屋敷の外", "外観", "corbitt_exterior"),
    "corbitt_ground_floor": ("1階", "地上階", "corbitt_ground_floor"),
    "corbitt_upper_floor": ("2階", "上階", "corbitt_upper_floor"),
    "corbitt_basement": ("地下室", "地下", "corbitt_basement"),
}

# ロケーションではないが「行く／調べる」と誤って move されやすい対象
NON_LOCATION_DESTINATION_KEYWORDS: Dict[str, Tuple[str, ...]] = {
    "reference_room_clipping_files": (
        "参考資料室", "資料室", "切り抜きファイル", "切り抜き", "reference_room",
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
    return any(k and k in text for k in keywords)


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
        keywords = list(LOCATION_INTENT_KEYWORDS.get(loc_id, ()))
        if scenario_mgr:
            name = str(scenario_mgr.get_location_info(loc_id).get("name") or "")
            if name:
                keywords.append(name)
            keywords.append(loc_id)
        # 短い汎用語（「地下」「図書館」）の誤爆を抑えるため、複数ヒット優先は呼び出し側で扱う
        if _text_has_any(text, keywords):
            if loc_id not in found:
                found.append(loc_id)
    return found


def collect_intent_non_location_targets(intent_text: str) -> List[str]:
    """ロケーションではない移動・調査希望（参考資料室など）を検出する。"""
    found: List[str] = []
    text = intent_text or ""
    for target_id, keywords in NON_LOCATION_DESTINATION_KEYWORDS.items():
        if _text_has_any(text, keywords):
            found.append(target_id)
    return found


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
    if not target:
        return {
            "ok": False,
            "error": MOVE_INTENT_MISMATCH_ERROR + "（move target が空です）",
            "error_code": "move_missing_target",
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

    mentioned = collect_intent_location_ids(intent, scenario_mgr)
    # 現在地への言及は移動先判定から除外
    mentioned = [m for m in mentioned if m != current_loc]

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


def resolve_social_npc_id(target: str, char_mgr=None) -> Optional[str]:
    """対象が対人（NPC/窓口オブジェクト）なら NPC ID を返す。"""
    raw = str(target or "").strip()
    if not raw:
        return None
    if raw in SOCIAL_OBJECT_TO_NPC:
        return SOCIAL_OBJECT_TO_NPC[raw]
    if char_mgr:
        char = char_mgr.characters.get(raw)
        if char and (char.get("profile") or {}).get("is_npc") and not (char.get("profile") or {}).get("monster"):
            return raw
        # 名前部分一致
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
) -> Optional[Dict[str, Any]]:
    """
    対人対象への search/inspect/push 等を talk へ書き換える（Pattern A）。
    書き換え不要なら None。
    """
    action = str(action or "").lower()
    if action not in SOCIAL_BLOCKED_ACTIONS:
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
    """
    return is_completed_knott_talk_target(
        action, target, scenario_mgr=scenario_mgr, char_mgr=char_mgr,
    )


def validate_completed_knott_talk(
    pc_action: Optional[Dict[str, Any]],
    *,
    scenario_mgr=None,
    current_loc: str = "",
    char_mgr=None,
) -> Dict[str, Any]:
    """
    talked_with_knott 後の Knott talk を最終防壁待ちせず即時拒絶する。
    """
    action = str((pc_action or {}).get("action", "wait") or "wait").lower()
    target = str((pc_action or {}).get("target", "") or "")
    if not is_completed_knott_talk_target(
        action, target, scenario_mgr=scenario_mgr, char_mgr=char_mgr,
    ):
        return {"ok": True}

    suggested = build_forced_progress_action(scenario_mgr, current_loc) or {
        "action": "move",
        "target": "boston_globe",
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
    exits = scenario_mgr.get_available_exits(loc) if hasattr(scenario_mgr, "get_available_exits") else []
    if not exits:
        return None
    by_id = {str(e.get("id") or ""): e for e in exits if e.get("id")}
    preferred_list = LOCATION_FORCED_PROGRESS_PREFERENCE.get(loc) or FORCED_PROGRESS_MOVE_PREFERENCE
    for preferred in preferred_list:
        if preferred == loc:
            continue
        if preferred in by_id:
            return preferred
    for preferred in FORCED_PROGRESS_MOVE_PREFERENCE:
        if preferred == loc:
            continue
        if preferred in by_id:
            return preferred
    for exit_info in exits:
        dest = str(exit_info.get("id") or "")
        if dest and dest != loc:
            return dest
    return None


def pick_forced_progress_search_target(scenario_mgr, current_loc: str = "") -> Optional[str]:
    """移動先が無い／膠着時の代替: 現在地の未調査オブジェクト。"""
    if not scenario_mgr:
        return None
    loc = str(current_loc or getattr(scenario_mgr, "location", "") or "")
    objects = (scenario_mgr.get_location_info(loc) or {}).get("objects") or {}
    flags = getattr(scenario_mgr, "flags", None) or {}
    investigated = set(flags.get("investigated_targets") or [])

    # ボストン・グローブ: 紹介済みなら資料室を優先候補に
    if loc == "boston_globe" and flags.get("artie_introduced"):
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
    - boston_globe + artie_introduced: 未調査の参考資料室 search を優先
    - それ以外 / search 不可: 解放済み exit への move
    - move も不可: 未調査オブジェクトの search
    """
    loc = str(current_loc or getattr(scenario_mgr, "location", "") or "")
    flags = getattr(scenario_mgr, "flags", None) or {}

    # 新聞社膠着: 紹介済みなら資料室調査を先に試す（移動より優先）
    if loc == "boston_globe" and flags.get("artie_introduced"):
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
        )
    return fallback or STAGNATION_STANDARD_PL_HINT_FALLBACK


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
        return {
            "ok": False,
            "error": STALE_KNOTT_TALK_REJECT_ERROR,
            "error_code": "force_ic_stale_talk",
            "suggested_fix": {
                "action": suggested.get("action", "move"),
                "target": suggested.get("target", "boston_globe"),
            },
            "needs_pl_retry": True,
        }

    return {"ok": True}
