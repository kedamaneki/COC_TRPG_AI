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
# マイルド化: 2〜3ターンでは強制せず、5〜6ターン程度まで自律リカバリーの余白を残す
STAGNATION_HINT_TURNS = 3  # OOC/システム通知のマイルドヒント開始
STAGNATION_FORCE_TURNS = 6  # 固定行動の強制・アイデアロール等の強介入
FORCE_IC_ACTION_CHAT_ROUNDS = 6
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
    "参考資料室の切り抜きファイル（reference_room_clipping_files）を search で調査してください。"
)

POST_ACCESS_SEARCH_FORCE_TURNS = 6

# 調査枯渇ロケで move しない停滞がこのターン数に達したら強制ブレイクアウト
LOCATION_EXHAUSTED_FORCE_TURNS = 6

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
}

# 調査枯渇時の move 誘導・強制ブレイクアウトを適用するロケーション
LOCATION_EXHAUSTED_MOVE_LOCATIONS = frozenset(LOCATION_FORCED_PROGRESS_PREFERENCE.keys())

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
        ARTIE_NEGOTIATE_STAGNATION_HINT
        + "許可が取れない場合は中央図書館（`move` / `central_library`）や"
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


def _object_is_empty_clue(obj: Optional[Dict[str, Any]]) -> bool:
    """手がかりのない／ロール不要のオブジェクトか。"""
    if not obj or not isinstance(obj, dict):
        return False
    if obj.get("no_roll") or obj.get("empty_clue") or obj.get("skill_check") is False:
        return True
    clue = str(obj.get("clue_value") or "").strip().lower()
    return clue in ("none", "empty", "flavor", "background")


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


def is_location_investigation_exhausted(scenario_mgr, current_loc: str = "") -> bool:
    """
    現在地の調査可能オブジェクトがすべて調査済みか。
    empty_clue / アクセスゲート未達の対象は集計から除外する。
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
        usable = obj.get("usable_actions") or []
        if not any(a in usable for a in ("search", "inspect", "read")):
            continue
        if not _object_access_gate_open(obj, flags):
            continue
        searchable += 1
        if not _object_is_investigated(scenario_mgr, str(obj_id), obj, flags):
            pending += 1
    return searchable > 0 and pending == 0


def should_apply_location_exhausted_move(scenario_mgr, current_loc: str = "") -> bool:
    """調査ハブロケかつ調査枯渇のとき、move 誘導／強制を適用するか。"""
    loc = str(
        current_loc
        or (getattr(scenario_mgr, "location", "") if scenario_mgr else "")
        or ""
    )
    if loc not in LOCATION_EXHAUSTED_MOVE_LOCATIONS:
        return False
    return is_location_investigation_exhausted(scenario_mgr, loc)


def build_location_exhausted_move_hint(scenario_mgr=None, current_loc: str = "") -> str:
    """調査枯渇時の move 誘導ヒント（解禁済み exit を動的に列挙）。"""
    loc = str(
        current_loc
        or (getattr(scenario_mgr, "location", "") if scenario_mgr else "")
        or ""
    )
    preferred = LOCATION_FORCED_PROGRESS_PREFERENCE.get(loc) or FORCED_PROGRESS_MOVE_PREFERENCE
    bits = []
    if scenario_mgr and hasattr(scenario_mgr, "get_available_exits"):
        exits = scenario_mgr.get_available_exits(loc) or []
        by_id = {str(e.get("id") or ""): e for e in exits if e.get("id")}
        for dest_id in preferred:
            if dest_id == loc or dest_id not in by_id:
                continue
            name = by_id[dest_id].get("name") or dest_id
            bits.append(f"`move` / `{dest_id}`（{name}）")
            if len(bits) >= 3:
                break
        if not bits:
            for exit_info in exits[:3]:
                dest_id = exit_info.get("id")
                if not dest_id or dest_id == loc:
                    continue
                bits.append(f"`move` / `{dest_id}`（{exit_info.get('name') or dest_id}）")
    if bits:
        return (
            "【システムヒント】この場所での調査はすべて完了しました。"
            "新しい場所へ移動（`move`）してください。例: "
            + " / ".join(bits)
            + "。すべての資料を集める必要はありません。"
            "直接コービット屋敷（`corbitt_exterior`）へ向かっても構いません。"
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
        # アクセスゲート未達のオブジェクトは強制 search 候補から除外
        if not _object_access_gate_open(obj, flags):
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
    - boston_globe + 許可未取得: LOCATION_FORCED_PROGRESS_PREFERENCE に従い move
    - それ以外 / search 不可: 解放済み exit への move
    - move も不可: 未調査オブジェクトの search
    """
    loc = str(current_loc or getattr(scenario_mgr, "location", "") or "")
    flags = getattr(scenario_mgr, "flags", None) or {}

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

    # ボストン・グローブ: フラグ状態に応じて交渉／調査を明示
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
        return LOCATION_STAGNATION_HINTS.get(loc, "") or (
            ARTIE_NEGOTIATE_STAGNATION_HINT
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
            + " "
            + INVESTIGATION_BAILOUT_HINT
        )
    return fallback or STAGNATION_STANDARD_PL_HINT_FALLBACK


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
