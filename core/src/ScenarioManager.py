import copy
from ObjectLifecycle import apply_object_transition
import random
import re

from expression_evaluator import SafeExpressionEvaluator, build_scenario_eval_context
from schema_definition import EventTriggerSchema, compile_trigger_condition, infer_action_type, merge_payload_elements
from DiceEngine import SuccessLevel, normalize_difficulty
from ActionValidator import (
    phase_for_location,
    should_apply_location_exhausted_move,
    LOCATION_EXHAUSTED_RESEARCH_REJECT,
    HOUSE_ENTRY_LOCATION_ID,
    HOUSE_MOVE_ALIASES,
    HOUSE_FAST_TRAVEL_HUBS,
    TALK_ACTION_IDS,
    NEGOTIATION_ACTION_IDS,
    object_is_currently_available,
)


class ObjectContext:
    """eval() 内で object.STR などのドットアクセスを可能にするラッパー。"""

    def __init__(self, obj_dict):
        self._obj = obj_dict or {}

    def __getattr__(self, name):
        val = self._obj.get(name)
        if val is None:
            return 0 if name == "STR" else None
        return val

    def get(self, key, default=None):
        return self._obj.get(key, default)


class FlagContext:
    """eval()内で flags.found_button == true などのドットアクセスを安全に行うラッパー"""

    def __init__(self, flag_dict):
        self._flags = flag_dict

    def __getattr__(self, name):
        return self._flags.get(name, False)

    def get(self, key, default=None):
        return self._flags.get(key, default)


PHYSICAL_ACTIONS = frozenset({"break", "push", "pull", "kick", "force"})
INVESTIGATION_ACTIONS = frozenset({"search", "inspect"})
OBJECT_INTERACT_ACTIONS = INVESTIGATION_ACTIONS | PHYSICAL_ACTIONS | frozenset({
    "climb", "read", "use", "open", "enter",
})
IRON_GATE_TARGET = "iron_gate"
GATE_WEAKNESS_FLAG = "gate_weakness_found"
GATE_OPENED_FLAG = "gate_opened"
IRON_GATE_PHYSICAL_ACTIONS = frozenset({"break", "push", "kick", "force"})
ROOM_SAN_CHECKED_FLAG_PREFIX = "room_san_checked_"
STAGNATION_KP_INJECT_THRESHOLD = 5
STAGNATION_PAUSE_THRESHOLD = 6
MOVE_DENY_SYSTEM_LOG = (
    "[システム] その場所へ進むことはできません。"
    "別のオブジェクトを調査するか、適切な移動先を選択してください。"
)
MOVE_DENY_KP_INSTRUCTION = (
    "【システム確定】探索者はその方向へ進めなかった。"
    "ナレーションで「そちらには進めない／行く手がない」と明確に描写してください。"
    "調査済みオブジェクトを再度勧めるのではなく、未調査オブジェクトか有効な移動先を提示してください。"
)

_HANDOUT_NAME_KEYWORDS = (
    "依頼書", "メモ", "資料", "記事", "切り抜き", "日記", "手紙", "書類", "記録",
    "ハンドアウト", "新聞", "書簡",
)
_HANDOUT_FLAG_MARKERS = (
    "_read", "_found", "letter", "memo", "handout", "clipping", "newspaper", "diary",
)


_TEASER_DESCRIPTION_MARKERS = (
    "情報が眠っている",
    "相当する情報が",
    "閲覧には厳格な手続き",
    "アクセスは許可されていない",
    "正攻法なら",
    "別のアプローチを試そう",
    "成功すれば、プレイヤー資料",
)


def _is_teaser_description(text: str) -> bool:
    """案内・攻略ヒント文であり、資料本文ではない description か。"""
    text = str(text or "")
    return any(marker in text for marker in _TEASER_DESCRIPTION_MARKERS)


def should_emit_handout_ic(obj, fact=""):
    """資料・ハンドアウト系なら KP IC に本文を載せる対象とみなす。"""
    fact = str(fact or "").strip()
    obj = obj or {}
    if not fact:
        return False
    if obj.get("player_handout") or obj.get("handout_text") or obj.get("success_message"):
        return True
    if obj.get("empty_clue") or obj.get("no_roll"):
        return False
    if obj.get("clue_on_success"):
        return True
    flag = str(obj.get("investigated_flag") or "").lower()
    if any(marker in flag for marker in _HANDOUT_FLAG_MARKERS):
        return True
    name = str(obj.get("name") or "")
    return any(keyword in name for keyword in _HANDOUT_NAME_KEYWORDS)


def format_handout_ic_block(fact, obj_name=""):
    """KP IC に挿入する資料本文ブロック。"""
    fact = str(fact or "").strip()
    if not fact:
        return ""
    title = f"【資料本文・{obj_name}】" if obj_name else "【資料本文】"
    return f"{title}\n{fact}"


def fact_already_in_text(text, fact, min_len=24):
    """描写文に資料本文が既に含まれているか。"""
    text = str(text or "")
    fact = str(fact or "").strip()
    if not fact:
        return True
    if fact in text:
        return True
    snippet = fact[:max(12, int(min_len))]
    return len(snippet) >= 12 and snippet in text

# 旧スケール判定: 「success_level >= 1」（任意成功）は新スケールでは使わない
_LEGACY_ANY_SUCCESS_RE = re.compile(r"success_level\s*>=\s*1\b")
_LEGACY_EXACT_FAIL_RE = re.compile(r"success_level\s*==\s*0\b")


def migrate_legacy_success_level_condition(condition: str) -> str:
    """
    旧 success_level 条件式を新 SuccessLevel (0–5) へ変換する。

    旧: 0=失敗, 1=レギュラー, 2=ハード, 3=極限/クリティカル
    新: 0=ファンブル, 1=失敗, 2=レギュラー, 3=ハード, 4=極限, 5=クリティカル

    既に新スケール（>=2 / <=1 等）の式は、旧マーカーが無い限り変更しない。
    """
    text = str(condition or "")
    if not text:
        return text

    has_old_any_success = bool(_LEGACY_ANY_SUCCESS_RE.search(text))
    has_old_exact_fail = bool(_LEGACY_EXACT_FAIL_RE.search(text))
    if not has_old_any_success and not has_old_exact_fail:
        return text

    if has_old_any_success:
        # 式全体が旧スケール前提 → 閾値を底上げ
        text = re.sub(r"success_level\s*>=\s*3\b", "success_level >= 4", text)
        text = re.sub(r"success_level\s*>=\s*2\b", "success_level >= 3", text)
        text = re.sub(r"success_level\s*>=\s*1\b", "success_level >= 2", text)
        text = re.sub(r"success_level\s*==\s*1\b", "success_level == 2", text)
        text = re.sub(r"success_level\s*==\s*0\b", "success_level <= 1", text)
    else:
        # 失敗側だけ旧式 (==0) が残っている場合
        text = re.sub(r"success_level\s*==\s*0\b", "success_level <= 1", text)
    return text


class ScenarioManager:
    def __init__(self, json_data):
        self.scenario_data = json_data
        self.meta = json_data.get("scenario_meta", {})

        self.initial_state = json_data.get("initial_state", {})

        self.current_phase = self.initial_state.get("current_phase", "start")
        self.location = self.initial_state.get("location", "")
        self._game_state = None
        self._fallback_turn_counter = int(self.initial_state.get("turn_counter", 0) or 0)
        self._fallback_flags = dict(self.initial_state.get("flags", {}))
        self._fallback_flags.setdefault("investigated_targets", [])

        self.event_triggers = json_data.get("event_triggers", [])
        self._normalize_event_triggers()
        self.event_triggers.sort(key=lambda x: x.get("priority", 0), reverse=True)

        self.triggered_counts = {}
        self.stagnation_counter = 0

    def collect_scenario_npc_ids(self):
        """シナリオ定義（各地の npcs_present）に現れる NPC ID 集合を返す。"""
        ids = set()
        locations = self.scenario_data.get("locations") or {}
        if isinstance(locations, dict):
            loc_iter = locations.values()
        else:
            loc_iter = locations or []
        for loc in loc_iter:
            if not isinstance(loc, dict):
                continue
            for nid in loc.get("npcs_present") or []:
                if nid:
                    ids.add(str(nid))
        return ids

    def has_explicit_npc_placement(self, loc_id=None):
        """ロケーション定義に npcs_present キーがあるか（空配列も明示配置）。"""
        loc = self.get_location_info(loc_id)
        return isinstance(loc, dict) and "npcs_present" in loc

    def get_npcs_present(self, loc_id=None, char_mgr=None):
        """
        指定ロケーションに配置されている NPC ID のリスト。

        - npcs_present キーがある場合: その値を正とする（空配列＝誰もいない）。
        - キーが無い旧形式: char_mgr があれば profile.locations で絞る。
          全NPCへの暗黙許可はしない。char_mgr も無ければ空。
        """
        loc = self.get_location_info(loc_id)
        loc_id = str(loc_id or self.location or "")
        if isinstance(loc, dict) and "npcs_present" in loc:
            return [str(nid) for nid in (loc.get("npcs_present") or []) if nid]
        # 旧形式フォールバック: 所在地プロファイルがある NPC のみ
        if not char_mgr:
            return []
        found = []
        for cid, char in (getattr(char_mgr, "characters", None) or {}).items():
            profile = (char or {}).get("profile") or {}
            if not profile.get("is_npc", False) or profile.get("monster"):
                continue
            loc_filter = profile.get("locations") or (char or {}).get("locations")
            if not loc_filter:
                continue
            allowed = {str(x) for x in loc_filter}
            if loc_id in allowed or "all" in allowed:
                found.append(str(cid))
        return found

    def is_npc_at_location(self, npc_id, loc_id=None, char_mgr=None):
        """NPC が指定ロケーションに存在するかを返す。"""
        if not npc_id:
            return False
        present = set(self.get_npcs_present(loc_id, char_mgr=char_mgr))
        nid = str(npc_id)
        if nid in present:
            return True
        # エイリアス（npc_ 接頭辞の有無）
        alt = nid[4:] if nid.startswith("npc_") else f"npc_{nid}"
        if alt in present:
            return True
        # 明示配置がある場所では present 以外を拒否（上で判定済み）
        if self.has_explicit_npc_placement(loc_id):
            return False
        # 旧形式: profile.locations を直接確認
        if char_mgr:
            char = (getattr(char_mgr, "characters", None) or {}).get(nid) or {}
            if not char and alt:
                char = (getattr(char_mgr, "characters", None) or {}).get(alt) or {}
            profile = char.get("profile") or {}
            loc_filter = profile.get("locations") or char.get("locations")
            if loc_filter:
                allowed = {str(x) for x in loc_filter}
                here = str(loc_id or self.location or "")
                return here in allowed or "all" in allowed
        return False

    def build_location_change_invalidation(self, old_loc, new_loc):
        """
        ロケーション移動直後に破棄すべき旧ロケ宛ターゲット情報を返す。
        （幽霊NPC対話の物理遮断用メタデータ）
        """
        old_loc = str(old_loc or "")
        new_loc = str(new_loc or "")
        old_npcs = set(self.get_npcs_present(old_loc))
        new_npcs = set(self.get_npcs_present(new_loc))
        return {
            "old_location": old_loc,
            "new_location": new_loc,
            "invalid_npc_ids": sorted(old_npcs - new_npcs),
            "valid_npc_ids": sorted(new_npcs),
        }

    def bind_game_state(self, game_state_mgr):
        """GameStateManager を進行フラグ・ターン数の Single Source of Truth として接続する。"""
        self._game_state = game_state_mgr
        if game_state_mgr is None:
            return
        if not game_state_mgr.flags:
            game_state_mgr.flags = dict(self._fallback_flags)
        else:
            for key, value in self._fallback_flags.items():
                game_state_mgr.flags.setdefault(key, value)
        game_state_mgr.flags.setdefault("investigated_targets", [])
        # 参照を一本化: fallback も同一 dict 内容のミラーに保つ
        self._fallback_flags = dict(game_state_mgr.flags)
        if int(game_state_mgr.turn_count or 0) <= 0 and self._fallback_turn_counter > 0:
            game_state_mgr.turn_count = self._fallback_turn_counter
        self.ensure_flags_synced()

    @property
    def turn_counter(self):
        if self._game_state is not None:
            return int(self._game_state.turn_count or 0)
        return int(self._fallback_turn_counter or 0)

    @turn_counter.setter
    def turn_counter(self, value):
        value = int(value or 0)
        if self._game_state is not None:
            self._game_state.turn_count = value
        else:
            self._fallback_turn_counter = value

    @property
    def flags(self):
        if self._game_state is not None:
            if not self._game_state.flags:
                self._game_state.flags = dict(self._fallback_flags)
                self._game_state.flags.setdefault("investigated_targets", [])
            return self._game_state.flags
        return self._fallback_flags

    @flags.setter
    def flags(self, value):
        value = dict(value or {})
        value.setdefault("investigated_targets", [])
        if self._game_state is not None:
            self._game_state.flags = value
            self._fallback_flags = dict(value)
        else:
            self._fallback_flags = value

    def _increment_turn_counter(self, delta=1):
        self.turn_counter = self.turn_counter + int(delta or 0)

    def export_to_dict(self):
        """
        シナリオ進行状態を保存する。
        flags / turn_counter は game_state が SSOT だが、セーブ上でも
        必ずミラーしてロード時の不整合を防ぐ。
        """
        self.ensure_flags_synced()
        return {
            "current_phase": self.current_phase,
            "location": self.location,
            "triggered_counts": self.triggered_counts,
            "stagnation_counter": self.stagnation_counter,
            "flags": dict(self.flags or {}),
            "turn_counter": int(self.turn_counter or 0),
        }

    def load_from_dict(self, data):
        self.current_phase = data.get("current_phase", "start")
        self.location = data.get("location", "")
        self.triggered_counts = data.get("triggered_counts", {})
        self.stagnation_counter = data.get("stagnation_counter", 0)
        # ミラー／旧セーブの flags を fallback に取り込み（bind 前の保険）
        if isinstance(data.get("flags"), dict):
            merged = dict(self._fallback_flags)
            merged.update(data["flags"])
            merged.setdefault("investigated_targets", [])
            self._fallback_flags = merged
            if self._game_state is not None:
                # 既にバインド済みなら game_state へも反映（空の場合は全面置換）
                if not self._game_state.flags:
                    self._game_state.flags = dict(merged)
                else:
                    for key, value in merged.items():
                        self._game_state.flags.setdefault(key, value)
        if "turn_counter" in data:
            self._fallback_turn_counter = int(data.get("turn_counter") or 0)
            if self._game_state is not None and int(self._game_state.turn_count or 0) <= 0:
                self._game_state.turn_count = self._fallback_turn_counter
        self.ensure_flags_synced()

    def apply_implied_progress_flags(self):
        """
        進行フラグの依存関係を補正する（既存 True は壊さない）。
        例: 屋敷侵入済みなら外観接近済み、ドーリー会話済みなら近隣噂取得済み。
        """
        flags = self.flags
        if not isinstance(flags, dict):
            return flags
        loc = str(self.location or "")

        # 旧セーブでは礼拝堂の床下とコービット邸地下室が同じ
        # in_basement フラグを共有していた。現在地が礼拝堂なら場所別の
        # フラグへ一度だけ移し、屋敷侵入済みと誤判定しないようにする。
        if loc == "chapel_of_contemplation" and flags.get("in_basement"):
            flags["chapel_cellar_entered"] = True
            flags["in_basement"] = False

        interior_locs = (
            "corbitt_ground_floor",
            "corbitt_upper_floor",
            "corbitt_basement",
            "corbitt_basement_room2",
            "corbitt_basement_room3",
        )
        # 屋内にいる／地下室関連フラグ → 侵入済み
        if (
            loc in interior_locs
            or flags.get("in_basement")
            or flags.get("basement_accessible")
            or int(flags.get("visit_corbitt_ground_floor") or 0) > 0
            or int(flags.get("visit_corbitt_upper_floor") or 0) > 0
            or int(flags.get("visit_corbitt_basement") or 0) > 0
        ):
            flags["corbitt_house_entered"] = True
        # 侵入済みなら外観接近は必ず前提として満たす（ナラティブ飛躍防止）
        if flags.get("corbitt_house_entered") and not flags.get("exterior_approached"):
            flags["exterior_approached"] = True
        if (
            loc in ("corbitt_exterior",) + interior_locs
            or int(flags.get("visit_corbitt_exterior") or 0) > 0
            or flags.get("front_door_unlocked")
            or flags.get("front_door_investigated")
        ):
            if not flags.get("exterior_approached"):
                flags["exterior_approached"] = True

        # 個別会話フラグ → 近隣噂の概要フラグへ同期
        gossip = (
            flags.get("dolly_talked")
            or flags.get("dolly_told_chapel_location")
            or flags.get("dolly_told_sanitarium_location")
        )
        if gossip and not flags.get("neighbor_gossip_found"):
            flags["neighbor_gossip_found"] = True
        if gossip and not flags.get("dolly_talked"):
            flags["dolly_talked"] = True
        # sanitarium_info_found は患者記録の investigated_flag。
        # ドーリーから場所・噂を聞いただけでは立てない（本調査スキップ防止）。
        # 場所の認知は dolly_told_sanitarium_location が担う。
        return flags

    def ensure_flags_synced(self):
        """game_state.flags と scenario 側参照が同一になるよう強制同期する。"""
        if self._game_state is None:
            self._fallback_flags.setdefault("investigated_targets", [])
            self.apply_implied_progress_flags()
            return self._fallback_flags
        if not self._game_state.flags:
            self._game_state.flags = dict(self._fallback_flags)
        else:
            for key, value in self._fallback_flags.items():
                self._game_state.flags.setdefault(key, value)
        self._game_state.flags.setdefault("investigated_targets", [])
        self.apply_implied_progress_flags()
        # fallback を同一内容のミラーに保つ（export 前の保険）
        self._fallback_flags = dict(self._game_state.flags)
        return self._game_state.flags

    def _normalize_event_triggers(self):
        """GenericScenarioSchema 形式のトリガーを既存エンジン互換へ正規化する。"""
        normalized = []
        for raw in self.event_triggers or []:
            trigger = dict(raw)
            try:
                model = EventTriggerSchema.model_validate(raw)
            except Exception:
                model = None

            if model is not None:
                if not trigger.get("trigger_condition"):
                    trigger["trigger_condition"] = compile_trigger_condition(model)
                if not trigger.get("payload") and model.payloads:
                    trigger["payload"] = merge_payload_elements(model.payloads)
                if not trigger.get("action_type") and model.payloads:
                    trigger["action_type"] = infer_action_type(model.payloads)
                if model.required_phase and not trigger.get("required_phase"):
                    trigger["required_phase"] = model.required_phase

            if trigger.get("trigger_condition"):
                trigger["trigger_condition"] = migrate_legacy_success_level_condition(
                    trigger["trigger_condition"]
                )

            normalized.append(trigger)
        self.event_triggers = normalized

    def _build_expression_context(self, action_id="", target="", success_level=0, loc_id=None, extra=None):
        loc_id = loc_id or self.location
        obj = self.get_object_info(loc_id, target)
        counters = {
            "turn_counter": self.turn_counter,
            **{
                k: v for k, v in self.flags.items()
                if k.endswith("_counter") or k.startswith("counter_")
            },
        }
        return build_scenario_eval_context(
            action_id=action_id,
            target=target,
            success_level=success_level,
            location=loc_id,
            current_phase=self.current_phase,
            flags=self._flags_for_location(loc_id),
            counters=counters,
            investigated_targets=list(self._get_investigated_targets()),
            object_data=obj,
            extra=extra,
        )

    def evaluate_expression(self, expression, *, action_id="", target="", success_level=0, loc_id=None, default=False):
        """条件式文字列を安全に評価する。"""
        ctx = self._build_expression_context(
            action_id=action_id,
            target=target,
            success_level=success_level,
            loc_id=loc_id,
        )
        return SafeExpressionEvaluator(ctx).evaluate_safe(expression, default=default)

    def _legacy_eval_condition(self, condition, eval_context):
        """レガシー eval 互換（安全評価器で失敗した場合のみフォールバック）。"""
        try:
            evaluator = SafeExpressionEvaluator(eval_context)
            return evaluator.evaluate(condition)
        except Exception:
            pass
        try:
            return bool(eval(condition, {"__builtins__": None}, eval_context))
        except Exception as exc:
            print(f"[ScenarioManager] 条件評価エラー: {condition!r} ({exc})")
            return False

    def get_startup_effects(self):
        """シナリオ開始時に適用する SAN 減少・発狂などの設定を返す。"""
        effects = self.meta.get("startup_effects")
        if not isinstance(effects, dict):
            return {}
        return effects

    def get_max_stagnation_turns(self):
        """膠着と判定する連続ターン数（デフォルト 6）。"""
        raw = self.meta.get("max_stagnation_turns", STAGNATION_PAUSE_THRESHOLD)
        try:
            return max(1, int(raw))
        except (TypeError, ValueError):
            return STAGNATION_PAUSE_THRESHOLD

    def get_scenario_intervention_level(self):
        """シナリオ既定の介入レベル文字列（none/light/standard/force）。"""
        raw = self.meta.get("intervention_level", "standard")
        return str(raw or "standard").strip().lower()

    def get_stagnation_relief_events(self):
        """スタック救済用イベント定義の一覧。"""
        relief = []
        for trigger in self.event_triggers or []:
            if trigger.get("stagnation_relief") or trigger.get("is_stagnation_relief"):
                relief.append(trigger)
                continue
            tags = trigger.get("tags") or []
            if isinstance(tags, str):
                tags = [tags]
            if "stagnation_relief" in tags or "stack_relief" in tags:
                relief.append(trigger)
        meta_events = self.meta.get("stagnation_relief_events") or []
        if isinstance(meta_events, list):
            relief.extend(meta_events)
        return relief

    def get_stagnation_hint_text(self):
        """FORCE/STANDARD 用のシナリオ固有ヒント文。"""
        hint = self.meta.get("stagnation_hint") or self.meta.get("idea_roll_hint")
        if hint:
            return str(hint).strip()
        # 未調査オブジェクトから一般ヒントを生成
        loc = self.get_location_info(self.location) or {}
        objects = loc.get("objects") or {}
        investigated = set(self.flags.get("investigated_targets") or [])
        candidates = []
        for oid, obj in objects.items():
            if oid in investigated:
                continue
            name = (obj or {}).get("name") or oid
            candidates.append(name)
        if candidates:
            return (
                f"まだ十分に調べていないものがある（例: {candidates[0]}）。"
                "別の技能や別の対象でアプローチしてみよう。"
            )
        exits = self.get_available_exits(self.location) or []
        if exits:
            return f"状況を変えたいなら、移動（例: {exits[0].get('name', exits[0].get('id'))}）も検討しよう。"
        return "別の技能（歴史・オカルト・医学など）や視点の切り替えを試してみよう。"

    def fire_stagnation_relief_event(self):
        """
        スタック救済イベントを強制発火する。
        定義が無ければ None。
        """
        relief_events = self.get_stagnation_relief_events()
        if not relief_events:
            return None
        triggered = relief_events[0]
        event_id = triggered.get("event_id") or "stagnation_relief"
        self.triggered_counts[event_id] = self.triggered_counts.get(event_id, 0) + 1
        payload = dict(triggered.get("payload") or {})
        self._apply_payload_updates(payload)
        if "new_location" in payload:
            payload["location_changed"] = True
        self.stagnation_counter = 0
        payload.setdefault(
            "system_log",
            "【スタック救済】状況を打開する出来事が起きた。",
        )
        payload.setdefault(
            "kp_instruction",
            "【スタック救済】膠着を破る出来事を描写し、探索の次の一手を自然に示してください。",
        )
        return payload

    def increment_stagnation_counter(self):
        self.stagnation_counter += 1

    def reset_stagnation_counter(self):
        self.stagnation_counter = 0

    def is_stagnation_warning_level(self):
        # 介入開始の一歩手前（max-1、最低1）
        threshold = max(1, self.get_max_stagnation_turns() - 1)
        return self.stagnation_counter >= threshold

    def is_stagnation_pause_level(self):
        return self.stagnation_counter >= self.get_max_stagnation_turns()

    def build_object_status_summary(self, loc_id=None):
        """KP プロンプト用: 現在地のオブジェクト・移動先のシステム確定状態。"""
        loc_id = loc_id or self.location
        loc = self.get_location_info(loc_id)
        lines = ["【部屋のオブジェクト状態（システム確定・厳守）】"]

        # 屋敷1階: 居間ガラクタ／地下室ドアを先頭に明示（雑談誘導防止）
        priority_ids = []
        if loc_id == "corbitt_ground_floor":
            priority_ids = ["living_room_clutter", "basement_door"]
            lines.append(
                "【最優先（1階）】会話より室内調査。"
                "`living_room_clutter`（別名 `living_room_junk`）と"
                "`basement_door` を search/inspect で進めよ。"
            )

        objects = list((loc.get("objects") or {}).items())
        if priority_ids:
            rank = {oid: i for i, oid in enumerate(priority_ids)}
            objects.sort(key=lambda kv: (rank.get(kv[0], 10_000), kv[0]))

        for obj_id, obj in objects:
            if not object_is_currently_available(obj, self.flags or {}):
                continue
            name = obj.get("name", obj_id)
            alias_note = ""
            if obj_id == "living_room_clutter":
                alias_note = " / 別名 `living_room_junk`"
            if obj_id == IRON_GATE_TARGET and self.flags.get(GATE_OPENED_FLAG):
                status = "開放済み（向こうへは現在地から直接 move 不可）"
            elif self._is_target_investigated(obj_id) and not self._is_research_reopened(obj_id):
                status = "調査完了・これ以上情報なし"
            else:
                status = "未調査・調査可能"
                if obj_id in priority_ids:
                    status = "【最優先ターゲット】" + status
            lines.append(f'- `{obj_id}`（{name}{alias_note}）: {status}')

        exits = self.get_available_exits(loc_id)
        if exits:
            exit_str = ", ".join(f"`{e['id']}`（{e['name']}）" for e in exits)
            lines.append(f"【移動可能な場所】{exit_str}")
        else:
            lines.append("【移動可能な場所】（現在地から直接移動できる場所はない）")

        investigated = sorted(self._get_investigated_targets())
        if investigated:
            inv_str = ", ".join(f"`{t}`" for t in investigated)
            lines.append(f"【調査済みターゲット一覧】{inv_str}")

        return "\n".join(lines)

    def get_location_info(self, loc_id=None):
        loc_id = loc_id or self.location
        locations = self.scenario_data.get("locations", {})
        return locations.get(loc_id, {})

    def get_object_info(self, loc_id, object_id):
        if not object_id:
            return {}
        loc = self.get_location_info(loc_id)
        return loc.get("objects", {}).get(object_id, {})

    def get_all_location_ids(self):
        return list(self.scenario_data.get("locations", {}).keys())

    def _introduction_complete(self):
        flags = self.flags or {}
        return bool(
            flags.get("talked_with_knott")
            or flags.get("case_accepted")
            or flags.get("knott_letter_read")
        )

    def _canonical_move_target(self, target, loc_id=None):
        """PL が corbitt_house と書いた移動を、導入後の屋敷外観ロケへ正規化する。"""
        loc_id = loc_id or self.location
        t = str(target or "").strip()
        if t in HOUSE_MOVE_ALIASES and not str(loc_id or "").startswith("corbitt_"):
            return HOUSE_ENTRY_LOCATION_ID
        return t

    def get_connected_to(self, loc_id=None):
        loc_id = loc_id or self.location
        loc = self.get_location_info(loc_id)
        connected = list(loc.get("connected_to") or [])
        if (
            self._introduction_complete()
            and loc_id
            and loc_id in HOUSE_FAST_TRAVEL_HUBS
            and loc_id != HOUSE_ENTRY_LOCATION_ID
            and HOUSE_ENTRY_LOCATION_ID not in connected
        ):
            connected.append(HOUSE_ENTRY_LOCATION_ID)
        return connected

    def _flags_for_location(self, loc_id=None):
        """Return a location-scoped flag view without mutating canonical state."""
        loc_id = str(loc_id or self.location or "")
        scoped = dict(self.flags or {})
        if loc_id == "chapel_of_contemplation":
            scoped["in_basement"] = bool(scoped.get("chapel_cellar_entered"))
        return scoped

    def _flag_requirement_met(self, req_flag, loc_id=None):
        """requires_flag / !flag を評価する。未指定は常に満たす。"""
        if req_flag is None or req_flag == "":
            return True
        req = str(req_flag).strip()
        flags = self._flags_for_location(loc_id)
        if req.startswith("!"):
            return not bool(flags.get(req[1:]))
        return bool(flags.get(req, False))

    def get_available_exits(self, loc_id=None):
        loc_id = loc_id or self.location
        loc = self.get_location_info(loc_id)
        exits = loc.get("exits", {})
        connected = self.get_connected_to(loc_id)
        available = []

        for dest_id in connected:
            if dest_id not in exits:
                dest_name = self.get_location_info(dest_id).get("name", dest_id)
                available.append({"id": dest_id, "name": dest_name})
                continue

            info = exits[dest_id]
            req_flag = info.get("requires_flag")
            condition = info.get("condition")
            if condition and not self.evaluate_expression(condition, action_id="move", target=dest_id, loc_id=loc_id):
                continue
            if not self._flag_requirement_met(req_flag, loc_id):
                continue
            available.append({
                "id": dest_id,
                "name": info.get("name", dest_id),
            })

        return available

    def _get_exit_info(self, loc_id, dest_id):
        loc = self.get_location_info(loc_id)
        return (loc.get("exits") or {}).get(dest_id, {})

    def _evaluate_exit_guard(self, dest_id, loc_id=None):
        """移動先 exit の condition / requires_flag を評価する。"""
        loc_id = loc_id or self.location
        exit_info = self._get_exit_info(loc_id, dest_id)
        if not exit_info:
            return None

        condition = exit_info.get("condition")
        if condition and not self.evaluate_expression(
            condition, action_id="move", target=dest_id, loc_id=loc_id,
        ):
            return self._build_blocked_payload(
                exit_info.get("reject_message")
                or f"【システムブロック】{exit_info.get('name', dest_id)} へはまだ進めません。",
                "移動が条件未達のため拒否されました。現在地で取れる別行動を示唆してください。",
            )

        req_flag = exit_info.get("requires_flag")
        if not self._flag_requirement_met(req_flag, loc_id):
            return self._build_blocked_payload(
                exit_info.get("reject_message")
                or f"【システムブロック】{exit_info.get('name', dest_id)} へはまだ進めません。",
                "必要な条件（フラグ）が未達のため移動できません。別の手がかりを探すよう誘導してください。",
            )
        return None

    def _evaluate_object_requires_flag_guard(self, obj, action_id, target, loc_id=None):
        """requires_flag 未達のオブジェクト操作を拒否する。"""
        req = (obj or {}).get("requires_flag")
        if self._flag_requirement_met(req, loc_id):
            return None
        # An event whose full action/target/location/flag condition is true is
        # more specific than an object's coarse visibility requirement.  This
        # lets one structure serve different semantic actions from opposite
        # sides (a hatch used to enter and later climb out, for example)
        # without weakening the guard for unrelated actions.
        if self.find_applicable_action_event(action_id, target, loc_id=loc_id):
            return None
        name = (obj or {}).get("name", target)
        req_text = str(req or "").strip()
        if req_text.startswith("!"):
            detail = (
                f"現在は `{req_text[1:]}` 状態のため操作できない。"
                if req_text[1:] else "現在の状況では操作できない。"
            )
        else:
            detail = f"条件フラグ `{req_text}` が未達のため操作できない。"
        if loc_id == "chapel_of_contemplation" and req_text == "in_basement":
            detail = (
                "チャペル地階の対象だ。まずもろくなった床板（`rotting_floorboards`）を"
                "調べたうえで、`break` / `force` / `climb` で地階へ降りよ。"
            )
        elif loc_id == "chapel_of_contemplation" and req_text == "!in_basement":
            detail = (
                "地階にいる間は地上側の対象を操作できない。"
                "`climb` / `rotting_floorboards` で這い上がってから再試行せよ。"
            )
        return self._build_blocked_payload(
            f"【システムブロック】{name}（`{target}`）は今は操作できない。{detail}",
            "条件未達の対象であることを伝え、到達手段や別の手がかりへ誘導してください。"
            "存在しない経路や未解禁ロケーションを創作しないこと。",
        )

    def find_applicable_action_event(self, action_id, target, loc_id=None):
        """Return an active scenario event that explicitly permits this action.

        Success and failure branches are both checked because availability is
        decided before dice resolution.  Phase, trigger limit, location,
        target, action verb, and current scoped flags still have to match.
        """
        loc_id = str(loc_id or self.location or "")
        action_id = str(action_id or "").lower()
        target = str(target or "")
        if not action_id or not target:
            return None
        for event in self.event_triggers or []:
            required_phase = event.get("required_phase")
            if required_phase and required_phase != self.current_phase:
                continue
            event_id = event.get("event_id")
            max_triggers = event.get("max_triggers")
            if max_triggers is not None and self.triggered_counts.get(event_id, 0) >= max_triggers:
                continue
            condition = str(event.get("trigger_condition") or "False")
            for success_level in (int(SuccessLevel.REGULAR_SUCCESS), int(SuccessLevel.FAILURE)):
                if self.evaluate_expression(
                    condition,
                    action_id=action_id,
                    target=target,
                    success_level=success_level,
                    loc_id=loc_id,
                ):
                    return event
        return None

    def _evaluate_object_visibility(self, obj, action_id, target, loc_id=None):
        condition = (obj or {}).get("is_visible_condition")
        if not condition:
            return None
        if self.evaluate_expression(
            condition, action_id=action_id, target=target, loc_id=loc_id,
        ):
            return None
        reject = (obj or {}).get(
            "reject_message",
            "【システムブロック】今はその対象に気づけない、あるいは調査できない。",
        )
        return self._build_blocked_payload(
            reject,
            "対象がまだ探索可能な状態ではないことを伝え、別の手がかりへ誘導してください。",
        )

    def _evaluate_object_investigated_guard(self, obj, action_id, target, loc_id=None):
        if action_id not in INVESTIGATION_ACTIONS or not target:
            return None
        flag_key = (obj or {}).get("investigated_flag")
        if flag_key and self.flags.get(flag_key, False):
            loc_id = loc_id or self.location
            fact, _ = self._object_confirmed_fact(target, loc_id=loc_id)
            # 資料本文がある場合は再確認を優先（枯渇移動メッセージで上書きしない）
            if fact:
                reject = (obj or {}).get("investigated_reject_message") or (obj or {}).get(
                    "reject_message",
                    "【システムブロック】この対象は既に調査済みです。",
                )
                if any(
                    marker in str(reject)
                    for marker in ("断られた", "別のアプローチ", "丸め込む", "忍び込む", "別の対人")
                ) and "すでに" not in str(reject) and "済" not in str(reject):
                    reject = (
                        f"【調査済み】`{target}` はすでに調査・閲覧済みだ。"
                        "同じ交渉や潜入をやり直す必要はない。"
                        "得た内容を再確認するか、別の手がかりへ進もう。"
                    )
                reconfirm_kp = (
                    "【厳守・再確認のみ】これは新規発見ではない。既知手がかりの再確認のみだ。"
                    "『どうしますか？』で同対象の再調査・再交渉を勧めるな。"
                    "未調査の別オブジェクトか、解禁済みロケーションへの移動を促せ。"
                    "未取得の交渉・潜入をやり直すよう促すな。"
                    "資料がある場合は再確認として原文を示してよいが、新規入手のように扱うな。"
                )
                if target == "rotting_floorboards" and self.flags.get("floorboards_examined"):
                    reconfirm_kp += (
                        "床板は調査済み。地階へ進むなら `break` / `force` / `climb`"
                        " / `rotting_floorboards` を促せ（再 search ではない）。"
                    )
                elif should_apply_location_exhausted_move(self, loc_id):
                    reconfirm_kp += (
                        "この場所の調査が枯渇していれば、解禁済みロケーションへの move も促せ。"
                    )
                payload = self._build_blocked_payload(reject, reconfirm_kp)
                name = (obj or {}).get("name", target)
                payload["system_log"] = (
                    f"{reject}\n【再確認・確定手がかり】{fact}"
                    "\n【進行指示】新規手がかりはない。別の未調査対象か移動を選べ。"
                )
                payload["confirmed_fact"] = fact
                payload["handout_review"] = True
                if should_emit_handout_ic(obj, fact):
                    payload["handout_text"] = fact
                    payload["handout_ic_block"] = format_handout_ic_block(fact, name)
                grant = self._build_object_knowledge_grant(target, fact)
                if grant:
                    grant = dict(grant)
                    grant["mark_investigated"] = True
                    payload["knowledge_grants"] = [grant]
                return payload
            if should_apply_location_exhausted_move(self, loc_id):
                return self._build_blocked_payload(
                    LOCATION_EXHAUSTED_RESEARCH_REJECT,
                    "調査は完了済みです。未訪問の解禁ロケーションへの移動（move）を促してください。",
                )
            reject = (obj or {}).get("investigated_reject_message") or (obj or {}).get(
                "reject_message",
                "【システムブロック】この対象は既に調査済みです。",
            )
            return self._build_blocked_payload(
                reject,
                "同対象の再調査は無意味であることを伝え、部屋の別オブジェクトや次の行動へ誘導してください。",
            )
        return None

    @staticmethod
    def is_empty_clue_object(obj) -> bool:
        """手がかりのない／ロール不要のオブジェクトか。"""
        if not obj:
            return False
        if obj.get("no_roll") or obj.get("empty_clue") or obj.get("skill_check") is False:
            return True
        clue = str(obj.get("clue_value") or "").strip().lower()
        if clue in ("none", "empty", "flavor", "background"):
            return True
        return False

    def coerce_object_action(self, action_id, target, loc_id=None):
        """
        usable_actions に合わせ action を強制マッピングする。
        戻り値: {"action_id", "remapped", "log"} または None（対象外）
        """
        loc_id = loc_id or self.location
        action_id = str(action_id or "").lower().strip()
        target = str(target or "").strip()
        obj = self.get_object_info(loc_id, target)
        if obj and (action_id in TALK_ACTION_IDS or action_id in NEGOTIATION_ACTION_IDS):
            allowed = [str(a).lower() for a in (obj.get("usable_actions") or [])]
            if "talk" not in allowed and any(a in allowed for a in ("search", "inspect", "read")):
                new_action = "search" if "search" in allowed else (
                    "inspect" if "inspect" in allowed else "read"
                )
                return {
                    "action_id": new_action,
                    "remapped": True,
                    "log": (
                        f"【アクション補正】`{target}` は対話NPCではなく調査対象です。"
                        f"システムが `{new_action}` に読み替えました。"
                    ),
                }

        if action_id not in INVESTIGATION_ACTIONS or not target:
            return None
        obj = self.get_object_info(loc_id, target)
        if not obj:
            return None
        allowed = [str(a).lower() for a in (obj.get("usable_actions") or [])]
        if not allowed:
            return None
        if action_id in allowed:
            return {"action_id": action_id, "remapped": False, "log": ""}
        # search <-> inspect の自動マッピング
        if action_id == "search" and "inspect" in allowed:
            return {
                "action_id": "inspect",
                "remapped": True,
                "log": (
                    f"【アクション補正】`search` は `{target}` では使えません。"
                    "システムが `inspect` に読み替えました。"
                ),
            }
        if action_id == "inspect" and "search" in allowed:
            return {
                "action_id": "search",
                "remapped": True,
                "log": (
                    f"【アクション補正】`inspect` は `{target}` では使えません。"
                    "システムが `search` に読み替えました。"
                ),
            }
        name = obj.get("name", target)
        allowed_label = " / ".join(allowed)
        return {
            "action_id": action_id,
            "remapped": False,
            "blocked": True,
            "log": (
                f"【システムブロック】{name}（`{target}`）に対する `{action_id}` は許可されていません。"
                f"利用可能: [{allowed_label}]"
            ),
            "kp_instruction": (
                f"【システム確定】{name} へは当該アクションができません。"
                f"利用可能な行動（{allowed_label}）か、人物への会話・他の対象を促してください。"
            ),
        }

    def _evaluate_usable_action_guard(self, action_id, target, loc_id=None):
        coerced = self.coerce_object_action(action_id, target, loc_id=loc_id)
        if not coerced:
            return None, action_id
        if coerced.get("blocked"):
            return self._build_blocked_payload(
                coerced.get("log", "【システムブロック】その行動はできません。"),
                coerced.get("kp_instruction", "別の行動を促してください。"),
            ), action_id
        return None, coerced.get("action_id", action_id)

    def _is_scenario_combat_resolution_action(self, action_id, target, loc_id=None):
        """Allow actions explicitly declared by a combat-ending scenario event.

        Scenario event metadata is authoritative here; this avoids duplicating a
        boss/object id in engine code while preserving ordinary usable_actions.
        """
        loc_id = str(loc_id or self.location or "")
        action_id = str(action_id or "").lower()
        target = str(target or "")
        for event in self.scenario_data.get("event_triggers") or []:
            payload = event.get("payload") or {}
            if not payload.get("combat_end"):
                continue
            condition = str(event.get("trigger_condition") or "")
            targets = re.findall(r"target\s*==\s*['\"]([^'\"]+)['\"]", condition)
            locations = re.findall(r"location\s*==\s*['\"]([^'\"]+)['\"]", condition)
            list_match = re.search(r"action_id\s+in\s+\[([^\]]+)\]", condition)
            actions = re.findall(r"['\"]([^'\"]+)['\"]", list_match.group(1)) if list_match else []
            if target in targets and (not locations or loc_id in locations) and action_id in actions:
                return True
        return False

    def _evaluate_no_roll_guard(self, action_id, target, loc_id=None):
        """空オブジェクトはダイス無しで『何もなし』を確定する。"""
        if action_id not in INVESTIGATION_ACTIONS or not target:
            return None
        loc_id = loc_id or self.location
        obj = self.get_object_info(loc_id, target)
        if not self.is_empty_clue_object(obj):
            return None
        name = (obj or {}).get("name", target)
        desc = str((obj or {}).get("description") or "").strip()
        system_log = (
            f"【調査・判定なし】{name}を見渡した。"
            "調べるまでもなく、今回の依頼に特に関係のあるものはなさそうだ。"
        )
        if desc:
            system_log += f"\n（背景描写: {desc}）"
        kp = (
            f"【空オブジェクト・厳守】`{target}`（{name}）には手がかりがない。"
            "ダイス成功も失敗も無い。PLに執着させず、"
            "『これ以上調査しても依頼に役立つ情報は何もなさそうだ』と明確に引導を渡せ。"
            "スティーブン・ノット氏との会話や、依頼書・メモ・移動可能な場所へ誘導すること。"
            "未記載のホラー現象・新手がかりを創作しないこと。"
        )
        if desc:
            kp += f"\n【description原文（これ以上の捏造禁止）】{desc}"
        payload = self._build_blocked_payload(system_log, kp)
        payload["no_roll"] = True
        payload["empty_clue"] = True
        payload["blocked"] = True
        return payload

    def evaluate_pre_action_guard(
        self,
        action_id,
        target,
        loc_id=None,
        pending_san_check=None,
        success_level=0,
    ):
        """
        ダイスロール前の共通ガードレール。
        移動条件・usable_actions・空オブジェクト・可視性・調査済み・SAN保留を一括判定する。
        戻り値の payload に `_effective_action_id` を載せる場合がある。
        """
        loc_id = loc_id or self.location
        action_id = str(action_id or "").lower()
        target = str(target or "").strip()

        san_block = self.evaluate_san_pending_block(action_id, pending_san_check)
        if san_block:
            return san_block

        if action_id == "move" and target:
            target = self._canonical_move_target(target, loc_id=loc_id)
            move_check = self._validate_move(target)
            if not move_check.get("allowed"):
                return self._build_blocked_payload(
                    move_check["system_log"],
                    move_check["kp_instruction"],
                )
            exit_block = self._evaluate_exit_guard(target, loc_id=loc_id)
            if exit_block:
                return exit_block

        if action_id in OBJECT_INTERACT_ACTIONS and target:
            obj = self.get_object_info(loc_id, target)
            if not obj:
                return self._build_blocked_payload(
                    f"【システムブロック】'{target}' はこの場所に存在しない。",
                    "存在しない対象への調査はできない。有効なオブジェクトを提示してください。",
                )
            requires_block = self._evaluate_object_requires_flag_guard(
                obj, action_id, target, loc_id=loc_id,
            )
            if requires_block:
                return requires_block

            if action_id in INVESTIGATION_ACTIONS:
                action_block, action_id = self._evaluate_usable_action_guard(
                    action_id, target, loc_id=loc_id,
                )
                if action_block:
                    return action_block

                no_roll_block = self._evaluate_no_roll_guard(action_id, target, loc_id=loc_id)
                if no_roll_block:
                    no_roll_block["_effective_action_id"] = action_id
                    return no_roll_block

                visibility_block = self._evaluate_object_visibility(
                    obj, action_id, target, loc_id=loc_id,
                )
                if visibility_block:
                    return visibility_block
                investigated_block = self._evaluate_object_investigated_guard(
                    obj, action_id, target, loc_id=loc_id,
                )
                if investigated_block:
                    return investigated_block

                # マッピング済み action を呼び出し側へ伝える（ブロックでない場合）
                coerced = self.coerce_object_action(action_id, target, loc_id=loc_id)
                if coerced and coerced.get("remapped"):
                    # 再実行は不要だが、action差し替え通知用
                    pass
            else:
                # break / force / climb 等: usable_actions があれば遵守
                allowed = [str(a).lower() for a in (obj.get("usable_actions") or [])]
                if (
                    allowed and action_id not in allowed
                    and not self._is_scenario_combat_resolution_action(
                        action_id, target, loc_id=loc_id,
                    )
                ):
                    name = obj.get("name", target)
                    return self._build_blocked_payload(
                        f"【システムブロック】{name}（`{target}`）に対する `{action_id}` は許可されていません。"
                        f"利用可能: [{' / '.join(allowed)}]",
                        "許可された行動か別の対象を促してください。",
                    )

        block = self.evaluate_pre_roll_block(
            action_id, target, loc_id, pending_san_check=pending_san_check,
        )
        if block:
            block["_effective_action_id"] = action_id
        return block

    def get_room_entry_san_flag_key(self, loc_id=None):
        """部屋進入SANの完了フラグキーを返す。"""
        loc_id = loc_id or self.location
        entry = self.get_location_info(loc_id).get("entry_san_check") or {}
        return entry.get("flag_key") or f"{ROOM_SAN_CHECKED_FLAG_PREFIX}{loc_id}"

    def get_location_entry_san_check(self, loc_id=None):
        """ロケーション定義の進入時強制SANチェック設定を返す（無効時は None）。"""
        loc_id = loc_id or self.location
        entry = self.get_location_info(loc_id).get("entry_san_check") or {}
        if not entry.get("enabled") and not entry.get("trigger_immediate_san_check"):
            return None
        return entry

    def is_room_entry_san_due(self, loc_id=None):
        """進入時SANが未実行かどうか。"""
        loc_id = loc_id or self.location
        if not self.get_location_entry_san_check(loc_id):
            return False
        return not self.flags.get(self.get_room_entry_san_flag_key(loc_id), False)

    def mark_room_entry_san_completed(self, loc_id=None):
        """進入時SANを発火済みとしてマークする（再開時の二重発火防止）。"""
        loc_id = loc_id or self.location
        if not self.get_location_entry_san_check(loc_id):
            return
        self.flags[self.get_room_entry_san_flag_key(loc_id)] = True

    def build_room_entry_san_check_payload(self, loc_id=None):
        """進入時強制SAN用の pending_san_check / ログ / KP指示を組み立てる。"""
        loc_id = loc_id or self.location
        entry = self.get_location_entry_san_check(loc_id)
        if not entry:
            return None

        san_check = {
            "required": True,
            "value": entry.get("value", "1/1d3"),
            "source": entry.get("source", "room_entry"),
            "room_entry": True,
            "room_id": loc_id,
        }
        if entry.get("success_loss") is not None:
            san_check["success_loss"] = entry["success_loss"]
        if entry.get("fail_loss") is not None:
            san_check["fail_loss"] = entry["fail_loss"]

        loc_name = self.get_location_info(loc_id).get("name", loc_id)
        default_log = (
            f"【強制SAN・部屋進入】{loc_name}に足を踏み入れた瞬間、"
            "見えない恐怖が正気を試す！"
        )
        default_kp = (
            f"【システム指示】{loc_name}への進入直後の宇宙的恐怖を描写してください。"
            "SANチェックはシステムが自動解決します。結果を情景に組み込み、"
            "『どうしますか？』で締めないでください。"
        )
        return {
            "san_check": san_check,
            "system_log": entry.get("system_log", default_log),
            "kp_instruction": entry.get("kp_instruction", default_kp),
        }

    def _iron_gate_weakness_bypass_active(self, action_id, target, loc_id=None):
        """死体の手記で弱点を知っている場合、鉄格子への力技判定を省略する。"""
        loc_id = loc_id or self.location
        if str(target or "").strip() != IRON_GATE_TARGET:
            return False
        if str(action_id or "").lower() not in IRON_GATE_PHYSICAL_ACTIONS:
            return False
        if self.flags.get(GATE_OPENED_FLAG):
            return False
        return bool(self.flags.get(GATE_WEAKNESS_FLAG))

    def get_required_check(self, action_id, target, loc_id=None):
        """
        イベント評価前に main.py / DiceEngine が実行すべき判定仕様を返す。
        該当なしの場合は None。

        タスク3: オブジェクトの required_skill / skill / difficulty もエンジン正として返す。
        """
        loc_id = loc_id or self.location
        obj = self.get_object_info(loc_id, target)

        strength_skills = {
            str(skill).upper()
            for skill in self.list_object_required_skills(obj)
        }
        has_strength_contract = bool(
            obj.get("STR") is not None
            or obj.get("strength_check_type")
            or "STR" in strength_skills
        )
        if action_id in PHYSICAL_ACTIONS.union({"climb"}) and has_strength_contract:
            block_flag = obj.get("block_flag")
            if block_flag and self.flags.get(block_flag):
                return None

            if self._iron_gate_weakness_bypass_active(action_id, target, loc_id):
                label = obj.get("name", target)
                return {
                    "type": "auto_success",
                    "success_level": int(SuccessLevel.EXTREME_SUCCESS),
                    "label": label,
                    "log_message": (
                        f"【弱点活用・自動成功】{label}の錆びた下部ヒンジを正確に蹴りつけ、"
                        "経年劣化した接合部が外れ、格子が開いた！"
                    ),
                }

            check_type = str(obj.get("strength_check_type") or "OPPOSED_STR_CHECK").upper()
            if check_type != "OPPOSED_STR_CHECK":
                return {
                    "type": "blocked_spec",
                    "reason": f"unsupported strength_check_type: {check_type}",
                    "error_code": "STRENGTH_CHECK_SPEC_INSUFFICIENT",
                }
            return {
                "type": "opposed_str",
                "check_contract": check_type,
                "attribute": "STR",
                "opponent_value": obj.get("STR", 50),
                "difficulty": normalize_difficulty(obj.get("difficulty", "regular")),
                "label": obj.get("name", target),
                "penalty_dice": obj.get("penalty_dice", 0),
                "bonus_dice": obj.get("bonus_dice", 0),
            }

        if action_id == "search" and target and obj.get("re_search_penalty_dice"):
            if self.flags.get("desk_research_unlocked") or self.flags.get(f"{target}_research_unlocked"):
                allowed = self.list_object_required_skills(obj) or ["目星"]
                return {
                    "type": "skill",
                    "skill_name": allowed[0],
                    "allowed_skills": allowed,
                    "penalty_dice": obj.get("re_search_penalty_dice", 1),
                    "modifier": obj.get("re_search_modifier", 0),
                    "difficulty": normalize_difficulty(obj.get("difficulty", "regular")),
                }

        # 調査対象: シナリオ定義の required_skill / skill を正とする
        if action_id in INVESTIGATION_ACTIONS and target and obj:
            if self.is_empty_clue_object(obj):
                return {
                    "type": "no_roll",
                    "skill_name": "",
                    "allowed_skills": [],
                    "difficulty": "regular",
                }
            if obj.get("skill_check") is False or obj.get("no_roll"):
                return {
                    "type": "no_roll",
                    "skill_name": "",
                    "allowed_skills": [],
                    "difficulty": "regular",
                }
            allowed = self.list_object_required_skills(obj)
            if not allowed:
                allowed = ["目星"]
            return {
                "type": "skill",
                "skill_name": allowed[0],
                "allowed_skills": allowed,
                "penalty_dice": int(obj.get("penalty_dice") or 0),
                "bonus_dice": int(obj.get("bonus_dice") or 0),
                "modifier": int(obj.get("modifier") or 0),
                "difficulty": normalize_difficulty(obj.get("difficulty", "regular")),
            }

        return None

    @staticmethod
    def list_object_required_skills(obj) -> list:
        """オブジェクト定義から許可技能リストを抽出する。"""
        if not obj:
            return []
        raw = obj.get("required_skill")
        if raw is None:
            raw = obj.get("skills")
        if raw is None:
            raw = obj.get("skill")
        if raw is None:
            return []
        if isinstance(raw, str):
            text = raw.strip()
            return [text] if text else []
        if isinstance(raw, (list, tuple, set)):
            out = []
            for item in raw:
                text = str(item or "").strip()
                if text and text not in out:
                    out.append(text)
            return out
        return []

    @staticmethod
    def match_proposed_skill(proposed_skill, allowed_skills) -> str:
        """
        PL提案技能が許可リストにあればそれを返す。なければ空文字。
        部分一致（例: 〈目星〉と目星）も許容する。
        """
        proposed = str(proposed_skill or "").strip()
        allowed = [str(s).strip() for s in (allowed_skills or []) if str(s).strip()]
        if not proposed or not allowed:
            return ""
        # 完全一致優先
        for skill in allowed:
            if proposed == skill:
                return skill
        for skill in allowed:
            if proposed in skill or skill in proposed:
                return skill
        return ""

    def resolve_investigation_skill(
        self, action_id, target, proposed_skill="", loc_id=None, required_check=None,
    ):
        """
        調査行動の最終技能・難易度をエンジン側で確定する。
        戻り値: {skill_name, allowed_skills, difficulty, skill_overridden, proposed_skill, required_check}
        """
        loc_id = loc_id or self.location
        action_id = str(action_id or "").lower()
        proposed = str(proposed_skill or "").strip()
        required_check = required_check or self.get_required_check(action_id, target, loc_id)
        difficulty = self.get_action_difficulty(
            action_id, target, loc_id, required_check=required_check,
        )
        obj = self.get_object_info(loc_id, target) if target else {}

        if required_check and required_check.get("type") == "no_roll":
            return {
                "skill_name": "",
                "allowed_skills": [],
                "difficulty": difficulty,
                "skill_overridden": bool(proposed),
                "proposed_skill": proposed,
                "required_check": required_check,
            }

        allowed = []
        if required_check and required_check.get("type") == "skill":
            allowed = list(required_check.get("allowed_skills") or [])
            if not allowed and required_check.get("skill_name"):
                allowed = [str(required_check["skill_name"])]
        if not allowed:
            allowed = self.list_object_required_skills(obj)
        if action_id in INVESTIGATION_ACTIONS and target and obj and not allowed:
            if not self.is_empty_clue_object(obj):
                allowed = ["目星"]

        matched = self.match_proposed_skill(proposed, allowed)
        if matched:
            skill_name = matched
            overridden = False
        elif allowed:
            skill_name = allowed[0]
            overridden = bool(proposed and proposed != skill_name)
        else:
            skill_name = ""
            overridden = bool(proposed)

        # required_check に最終技能を反映したコピーを返す
        check_out = dict(required_check) if isinstance(required_check, dict) else None
        if check_out and check_out.get("type") == "skill":
            check_out["skill_name"] = skill_name
            check_out["allowed_skills"] = allowed
            check_out["difficulty"] = difficulty

        return {
            "skill_name": skill_name,
            "allowed_skills": allowed,
            "difficulty": difficulty,
            "skill_overridden": overridden,
            "proposed_skill": proposed,
            "required_check": check_out if check_out is not None else required_check,
        }

    def get_action_difficulty(self, action_id, target, loc_id=None, required_check=None):
        """オブジェクト / required_check から難易度を取得する。"""
        if required_check and required_check.get("difficulty"):
            return normalize_difficulty(required_check.get("difficulty"))
        loc_id = loc_id or self.location
        obj = self.get_object_info(loc_id, target) if target else {}
        return normalize_difficulty((obj or {}).get("difficulty", "regular"))

    def evaluate_san_pending_block(self, action_id, pending_san_check=None):
        """SANチェック保留中に wait 以外の行動をブロックする。"""
        if not pending_san_check:
            return None
        required = pending_san_check.get("required")
        if not (required is True or str(required).lower() == "true"):
            return None
        action_id = str(action_id or "").lower()
        if action_id in ("wait", "", "none"):
            return None
        return self._build_blocked_payload(
            "【システムブロック】現在、衝撃的な光景によるSANチェックが保留されています。"
            "恐怖のリアクション以外の行動コマンド（プッシュロールを含む）は受け付けられません。",
            "探索者は精神的衝撃の最中です。SANチェックはシステムが自動処理します。"
            "恐怖のリアクション描写のみを行い、行動の選択肢は提示しないでください。",
        )

    def evaluate_pre_roll_block(self, action_id, target, loc_id=None, pending_san_check=None):
        """ダイスロール前にブロックすべき行動か判定（探索済みの無駄ロール防止）。"""
        san_block = self.evaluate_san_pending_block(action_id, pending_san_check)
        if san_block:
            return san_block

        loc_id = loc_id or self.location
        if action_id == "push_roll":
            return None
        if action_id not in INVESTIGATION_ACTIONS or not target:
            return None

        if self._is_target_investigated(target) and not self._is_research_reopened(target):
            scenario_reject = self._get_scenario_specific_pre_roll_reject_payload(
                action_id=action_id,
                target=target,
            )
            if scenario_reject:
                return scenario_reject
            if should_apply_location_exhausted_move(self, loc_id):
                return self._build_blocked_payload(
                    LOCATION_EXHAUSTED_RESEARCH_REJECT,
                    "調査は完了済みです。未訪問の解禁ロケーションへの移動（move）を促してください。",
                )
            return self._build_blocked_payload(
                "【システム】この対象はすでに調査し、手がかりを発見済みです。",
                "同じ対象を再調査しても進展はないことを伝え、別の対象や次の行動へ誘導してください。",
            )

        return None

    def _get_scenario_specific_pre_roll_reject_payload(self, action_id, target):
        """調査済み対象の事前ブロック時、シナリオ固有の system_reject を優先取得する。"""
        eval_context = self._get_eval_context(action_id, target, success_level=0)
        for trigger in self.event_triggers:
            if trigger.get("action_type") != "system_reject":
                continue

            req_phase = trigger.get("required_phase")
            if req_phase and req_phase != self.current_phase:
                continue

            max_triggers = trigger.get("max_triggers")
            if max_triggers is not None:
                event_id = trigger.get("event_id")
                count = self.triggered_counts.get(event_id, 0)
                if count >= max_triggers:
                    continue

            condition = trigger.get("trigger_condition", "False")
            if not self._legacy_eval_condition(condition, eval_context):
                continue

            payload = dict(trigger.get("payload", {}))
            blocked = self._build_blocked_payload(
                payload.get("system_log") or "【システムブロック】この対象は調査済みです。",
                payload.get("kp_instruction") or "同対象の再調査は無意味であることを伝え、別行動を促してください。",
            )
            if "san_check" in payload:
                blocked["san_check"] = payload["san_check"]
            return blocked
        return None

    def finalize_blocked_action(self, action_id, target, block_payload):
        """ブロック行動をターン消費付きで確定する（ダイスロールなし）。"""
        self._increment_turn_counter()
        time_hints = self._advance_time_flags(action_id, target)
        return self._merge_time_hints(block_payload, time_hints, action_id, target)

    def _should_merge_desk_time_hints(self, action_id, target, time_hints, payload=None):
        """机の再調査に関する時間経過ヒントをマージすべきか判定する。"""
        hint_log = time_hints.get("system_log", "")
        hint_kp = time_hints.get("kp_instruction", "")
        if not hint_log and not hint_kp:
            return False
        is_desk_hint = any(k in hint_log or k in hint_kp for k in ("机", "再調査", "再捜索", "時間経過"))
        if not is_desk_hint:
            return True
        if action_id == "search" and target == "desk":
            return True
        if action_id in ("wait", "", "none"):
            return True
        payload_log = (payload or {}).get("system_log", "")
        if any(k in payload_log for k in ("再調査", "ボタン", "机の裏")):
            return False
        return False

    def _merge_time_hints(self, payload, time_hints, action_id="", target=""):
        if not time_hints.get("system_log") and not time_hints.get("kp_instruction"):
            return payload

        if not self._should_merge_desk_time_hints(action_id, target, time_hints, payload):
            return payload

        merged = dict(payload)
        if time_hints.get("system_log"):
            existing = merged.get("system_log", "")
            merged["system_log"] = f"{time_hints['system_log']}\n{existing}".strip()
        if time_hints.get("kp_instruction"):
            existing_kp = merged.get("kp_instruction", "")
            merged["kp_instruction"] = f"{time_hints['kp_instruction']}\n{existing_kp}".strip()
        return merged

    def _validate_move(self, target):
        target = self._canonical_move_target(target)
        if not target:
            return {
                "allowed": False,
                "system_log": f"{MOVE_DENY_SYSTEM_LOG}（移動先が指定されていません）",
                "kp_instruction": (
                    f"{MOVE_DENY_KP_INSTRUCTION} "
                    "PLは移動先を指定せずに動こうとしました。"
                ),
            }

        if target == self.location:
            loc_name = self.get_location_info().get("name", self.location)
            return {
                "allowed": False,
                "system_log": (
                    f"{MOVE_DENY_SYSTEM_LOG}"
                    f"（すでに {loc_name} にいます。別の場所へ移動するか、現在地を調査してください）"
                ),
                "kp_instruction": (
                    f"{MOVE_DENY_KP_INSTRUCTION} "
                    "探索者はすでにその場所にいます。移動ではなく、現在地の調査や会話を促してください。"
                ),
            }

        all_locations = self.get_all_location_ids()
        if target not in all_locations:
            return {
                "allowed": False,
                "system_log": (
                    f"{MOVE_DENY_SYSTEM_LOG}"
                    f"（指定: '{target}' はこのシナリオに存在しません）"
                ),
                "kp_instruction": (
                    f"{MOVE_DENY_KP_INSTRUCTION} "
                    f"PLは存在しない場所（{target}）へ進もうとしました。"
                ),
            }

        connected = self.get_connected_to()
        if target not in connected:
            loc_name = self.get_location_info().get("name", self.location)
            available = self.get_available_exits()
            hint = ""
            if available:
                ids = ", ".join(f"`{e['id']}`" for e in available)
                hint = f" 移動可能: {ids}。"
            return {
                "allowed": False,
                "system_log": (
                    f"{MOVE_DENY_SYSTEM_LOG}"
                    f"（{loc_name} から '{target}' へは直接進めません）{hint}"
                ),
                "kp_instruction": (
                    f"{MOVE_DENY_KP_INSTRUCTION} "
                    f"PLは接続されていない場所（{target}）へ進もうとしました。"
                ),
            }

        return {"allowed": True}

    def _build_blocked_payload(self, system_log, kp_instruction):
        return {
            "system_log": system_log,
            "kp_instruction": kp_instruction,
            "san_check": {"required": False},
            "blocked": True,
            "status": 0,
        }

    def _get_investigated_targets(self):
        targets = self.flags.get("investigated_targets", [])
        if not isinstance(targets, list):
            return set()
        return {str(t).strip() for t in targets if str(t).strip()}

    def _set_investigated_targets(self, targets):
        self.flags["investigated_targets"] = sorted(targets)

    def _is_target_investigated(self, target):
        return str(target or "").strip() in self._get_investigated_targets()

    def _is_research_reopened(self, target):
        target = str(target or "").strip()
        if not target:
            return False
        if self.flags.get(f"{target}_research_unlocked"):
            return True
        return target in self.flags.get("reopened_targets", [])

    def _knowledge_scope_for_object(self, obj):
        if not isinstance(obj, dict):
            return "private"
        scope = str(obj.get("knowledge_scope") or "").strip().lower()
        if scope in ("public", "shared", "party"):
            return "public"
        if obj.get("public_knowledge"):
            return "public"
        return "private"

    def _build_object_knowledge_grant(self, target, fact="", *, obj=None):
        target = str(target or "").strip()
        if not target:
            return None
        obj = obj if obj is not None else (self.get_object_info(self.location, target) or {})
        scope = self._knowledge_scope_for_object(obj)
        return {
            "knowledge_id": f"object:{target}",
            "scope": scope,
            "target": target,
            "summary": str(fact or "").strip()[:400],
            "mark_investigated": True,
        }

    def _attach_knowledge_grants(self, payload, action_id, target, success_level):
        """調査成功ペイロードに knowledge_grants を付与する。"""
        if not payload or not target:
            return payload
        if action_id not in INVESTIGATION_ACTIONS:
            return payload
        if int(success_level or 0) < int(SuccessLevel.REGULAR_SUCCESS):
            return payload
        if payload.get("blocked") or payload.get("dice_success") is False:
            return payload

        if payload.get("fact_policy") == "EVENT_ONLY":
            payload = dict(payload)
            payload["dice_success"] = True
            return payload
        payload = dict(payload)
        grants = list(payload.get("knowledge_grants") or [])
        fact = str(payload.get("confirmed_fact") or "").strip()
        if not fact:
            fact, _ = self._object_confirmed_fact(target)
        grant = self._build_object_knowledge_grant(target, fact)
        if grant:
            existing = {g.get("knowledge_id") for g in grants if isinstance(g, dict)}
            if grant["knowledge_id"] not in existing:
                grants.append(grant)
        payload["knowledge_grants"] = grants
        return payload

    def _should_mark_investigated(self, action_id, target, success_level, action_type, payload):
        if action_id not in INVESTIGATION_ACTIONS or not target:
            return False
        if action_type == "system_reject":
            return False
        if payload.get("blocked"):
            return False
        if payload.get("mark_investigated"):
            return True
        if success_level < int(SuccessLevel.REGULAR_SUCCESS):
            return False
        has_signal = bool(payload.get("flag_updates")) or bool(payload.get("capture_turn_flags"))
        clue_text = str(payload.get("system_log", "") or "")
        if any(word in clue_text for word in ("発見", "成功", "手がかり", "調査結果")):
            has_signal = True
        return has_signal

    def _track_investigated_target(self, target):
        target = str(target or "").strip()
        if not target:
            return
        targets = self._get_investigated_targets()
        targets.add(target)
        self._set_investigated_targets(targets)

    def _object_confirmed_fact(self, target, loc_id=None):
        """オブジェクトから KP に強制注入すべき確定手がかり文を取得する。"""
        obj = self.get_object_info(loc_id or self.location, target) or {}
        fact = (
            obj.get("player_handout")
            or obj.get("handout_text")
            or obj.get("success_message")
            or obj.get("clue_on_success")
            or ""
        )
        if not fact:
            desc = str(obj.get("description") or "").strip()
            # 案内・攻略ヒント文は確定手がかりにしない（依頼書本文などの本物 description は許可）
            if desc and not _is_teaser_description(desc):
                fact = desc
        return str(fact).strip(), obj

    def should_emit_handout_ic(self, obj, fact=""):
        """資料系オブジェクトなら KP IC に本文を載せる。"""
        return should_emit_handout_ic(obj, fact)

    def _enrich_investigation_success_payload(self, payload, action_id, target, success_level):
        """
        ダイス成功時、汎用ログ（『重要な手がかりを見つけた』等）でも
        オブジェクト確定情報を system_log / kp_instruction / confirmed_fact に注入する。
        """
        if not payload or not target:
            return payload
        if action_id not in INVESTIGATION_ACTIONS:
            return payload
        if int(success_level or 0) < int(SuccessLevel.REGULAR_SUCCESS):
            return payload
        if payload.get("blocked") or payload.get("dice_success") is False:
            return payload

        if payload.get("fact_policy") == "EVENT_ONLY":
            payload = dict(payload)
            payload["dice_success"] = True
            return payload

        fact, obj = self._object_confirmed_fact(target)
        if not fact:
            return payload

        payload = dict(payload)
        payload["confirmed_fact"] = fact
        payload["dice_success"] = True
        name = obj.get("name", target)
        log = str(payload.get("system_log") or "")
        generic = (
            not log
            or "重要な手がかりを見つけた" in log
            or "特になにも見つからなかった" in log
            or "これといった手がかりは見つからなかった" in log
        )
        if generic or "【確定手がかり】" not in log:
            base = log.strip() or f"{name}の調査に成功した。"
            if "【確定手がかり】" not in base:
                payload["system_log"] = f"{base}\n【確定手がかり】{fact}"
        if should_emit_handout_ic(obj, fact):
            payload["handout_text"] = fact
            payload["handout_ic_block"] = format_handout_ic_block(fact, name)
        kp = str(payload.get("kp_instruction") or "")
        guard = (
            "【ダイス成功】下記の確定手がかりを必ず描写に含めよ。"
            "「何も見つからなかった」と空振りさせるな。"
            "未記載の怪異・呪文・新事実を創作するな。"
            "資料・ハンドアウトがある場合は【資料本文】として原文を省略せず IC 描写に含めよ。"
            f"\n確定手がかり: {fact}"
        )
        if "確定手がかり" not in kp:
            payload["kp_instruction"] = f"{guard}\n{kp}".strip()
        return payload

    def _apply_payload_updates(self, payload):
        if "flag_updates" in payload:
            for key, value in payload["flag_updates"].items():
                if key == "in_basement" and self.location == "chapel_of_contemplation":
                    self.flags["chapel_cellar_entered"] = bool(value)
                    self.flags["in_basement"] = False
                else:
                    self.flags[key] = value

        for flag_name in payload.get("capture_turn_flags", []):
            self.flags[flag_name] = self.turn_counter
        if "flag_updates" in payload or payload.get("capture_turn_flags"):
            if hasattr(self, "ensure_flags_synced"):
                self.ensure_flags_synced()

        if "new_phase" in payload:
            self.current_phase = payload["new_phase"]

        if "new_location" in payload:
            new_loc = payload["new_location"]
            self.location = new_loc
            visit_key = f"visit_{new_loc}"
            self.flags[visit_key] = self.flags.get(visit_key, 0) + 1
            if hasattr(self, "ensure_flags_synced"):
                self.ensure_flags_synced()

        if payload.get("object_state_updates"):
            states = self.flags.setdefault("object_states", {})
            for object_id, update in payload["object_state_updates"].items():
                apply_object_transition(states, object_id, update or {})

    @staticmethod
    def _resolve_conditional_effects(payload, success_level):
        """Resolve conditional schema effects; mandatory effects may not vanish silently."""
        payload = copy.deepcopy(payload or {})
        success = int(success_level or 0) >= int(SuccessLevel.REGULAR_SUCCESS)
        branch = payload.pop("success_effects" if success else "failure_effects", None) or {}
        payload.pop("failure_effects" if success else "success_effects", None)
        unhandled = list(payload.pop("unhandled_mandatory_effects", []) or [])
        unhandled.extend(branch.pop("unhandled_mandatory_effects", []) or [])
        if unhandled:
            raise RuntimeError("UNHANDLED_MANDATORY_EFFECT: " + ",".join(sorted(set(unhandled))))
        for key, value in branch.items():
            if key == "flag_updates":
                combined = dict(payload.get(key) or {})
                combined.update(value or {})
                payload[key] = combined
            elif key == "system_log" and payload.get(key):
                payload[key] = f"{payload[key]}\n{value}".strip()
            elif isinstance(value, dict) and isinstance(payload.get(key), dict):
                combined = dict(payload[key])
                combined.update(value)
                payload[key] = combined
            else:
                payload[key] = value
        return payload

    def _advance_time_flags(self, action_id, target):
        """ターン経過フラグを更新し、条件成立時のヒントを返す。"""
        self.flags["turn_since_last_search"] = self.flags.get("turn_since_last_search", 0) + 1

        hints = {"system_log": "", "kp_instruction": ""}

        fail_turn = self.flags.get("desk_first_fail_turn")
        if fail_turn is not None and not self.flags.get("desk_research_unlocked"):
            turns_elapsed = self.turn_counter - fail_turn
            re_search_after = self.get_object_info(self.location, "desk").get("re_search_after_turns", 2)
            if turns_elapsed >= re_search_after:
                self.flags["desk_research_unlocked"] = True
                hints["system_log"] = (
                    "【時間経過】最初の探索から時間が経ち、落ち着いて机を見直す余裕ができた。"
                    "再度『目星』で精査できる（ペナルティダイス付き）。"
                )
                hints["kp_instruction"] = (
                    "【システム指示】時間経過により、机の再捜索が可能になりました。"
                    "PLに、もう一度丁寧に机を調べてもよいことを自然に示唆してください。"
                )

        if action_id == "search":
            self.flags["turn_since_last_search"] = 0

        return hints

    def _get_eval_context(self, action_id, target, success_level):
        obj = self.get_object_info(self.location, target)
        return self._build_expression_context(
            action_id=action_id,
            target=target,
            success_level=success_level,
            loc_id=self.location,
            extra={
                "turns_since_desk_fail": (
                    self.turn_counter - self.flags["desk_first_fail_turn"]
                    if self.flags.get("desk_first_fail_turn") is not None
                    else -1
                ),
            },
        )

    def process_action(self, action_id, target="", success_level=0):
        self._increment_turn_counter()
        time_hints = self._advance_time_flags(action_id, target)

        if action_id == "move":
            target = self._canonical_move_target(target)
            move_check = self._validate_move(target)
            if not move_check["allowed"]:
                payload = self._build_blocked_payload(
                    move_check["system_log"],
                    move_check["kp_instruction"],
                )
                return self._merge_time_hints(payload, time_hints, action_id, target)

        eval_context = self._get_eval_context(action_id, target, success_level)
        triggered_event = None

        for trigger in self.event_triggers:
            event_id = trigger.get("event_id")
            req_phase = trigger.get("required_phase")
            max_triggers = trigger.get("max_triggers")

            if req_phase and req_phase != self.current_phase:
                continue

            if max_triggers is not None:
                count = self.triggered_counts.get(event_id, 0)
                if count >= max_triggers:
                    continue

            condition = trigger.get("trigger_condition", "False")
            if self._legacy_eval_condition(condition, eval_context):
                triggered_event = trigger
                break

        if triggered_event:
            self.stagnation_counter = 0

            event_id = triggered_event.get("event_id")
            self.triggered_counts[event_id] = self.triggered_counts.get(event_id, 0) + 1

            action_type = triggered_event.get("action_type")
            payload = self._resolve_conditional_effects(
                triggered_event.get("payload", {}), success_level,
            )
            changed_keys = list((payload.get("flag_updates") or {}).keys())
            state_before = {key: copy.deepcopy(self.flags.get(key)) for key in changed_keys}
            self._apply_payload_updates(payload)
            state_after = {key: copy.deepcopy(self.flags.get(key)) for key in changed_keys}
            payload["trigger_event_id"] = event_id
            payload["state_before"] = state_before
            payload["state_after"] = state_after
            payload["cause_event_ids"] = [event_id] if event_id else []
            if self._should_mark_investigated(action_id, target, success_level, action_type, payload):
                self._track_investigated_target(target)

            if action_type == "call_custom_script":
                script_name = payload.get("script_name")
                args = payload.get("args", {})
                if hasattr(self, "custom_scripts") and hasattr(self.custom_scripts, script_name):
                    getattr(self.custom_scripts, script_name)(args)

            if "new_location" in payload:
                payload["location_changed"] = True

            payload = self._enrich_investigation_success_payload(
                payload, action_id, target, success_level,
            )
            payload = self._attach_knowledge_grants(payload, action_id, target, success_level)
            return self._merge_time_hints(payload, time_hints, action_id, target)

        if not action_id or action_id in ["none", "wait", "san_check", ""]:
            payload = {
                "system_log": "",
                "kp_instruction": "【システム指示】PLは直前の事象（発見やSANチェックなど）を終えて待機しています。先ほどの状況を引き継ぎ、どう行動するかPLに問いかけてください。",
                "san_check": {"required": False},
            }
            return self._merge_time_hints(payload, time_hints, action_id, target)

        if action_id == "move":
            exit_block = self._evaluate_exit_guard(target, loc_id=self.location)
            if exit_block:
                return self._merge_time_hints(exit_block, time_hints, action_id, target)

            old_loc = self.location
            old_name = self.get_location_info(old_loc).get("name", old_loc)
            dest_name = self.get_location_info(target).get("name", target)
            self.location = target
            self.flags[f"visit_{target}"] = self.flags.get(f"visit_{target}", 0) + 1
            # 屋内移動などで前提フラグが飛ばないよう、移動直後に依存関係を補正する
            if hasattr(self, "ensure_flags_synced"):
                self.ensure_flags_synced()
            # フェーズ同期: 導入ロケを離れたら investigation へ
            new_phase = phase_for_location(target, self.current_phase)
            phase_note = ""
            if new_phase != self.current_phase:
                self.current_phase = new_phase
                phase_note = f"\n【フェーズ遷移】current_phase → `{new_phase}`"

            invalidation = self.build_location_change_invalidation(old_loc, target)
            payload = {
                "system_log": f"【移動】{old_name} から {dest_name} へ移動した。{phase_note}".strip(),
                "kp_instruction": (
                    f"探索者が {dest_name} に到着したことを描写してください。"
                    "現在地で取れる調査や会話を自然に示唆してください。"
                    "未解放フラグのルート（例: 受付紹介前の資料室）を先回りで勧めてはならない。"
                    "移動前ロケーションのNPCとの対話を続けてはならない。"
                ),
                "new_location": target,
                "new_phase": new_phase,
                "location_changed": True,
                "from_location": old_loc,
                "invalidate_pending_actions": True,
                "invalidation": invalidation,
                "san_check": {"required": False},
            }
            return self._merge_time_hints(payload, time_hints, action_id, target)

        # 成功しているのにイベント未発火 → オブジェクト確定情報を返す（空振り禁止）
        if (
            action_id in INVESTIGATION_ACTIONS
            and target
            and int(success_level or 0) >= int(SuccessLevel.REGULAR_SUCCESS)
        ):
            fact, obj = self._object_confirmed_fact(target)
            name = obj.get("name", target)
            inv_flag = obj.get("investigated_flag")
            flag_updates = {}
            if inv_flag:
                flag_updates[inv_flag] = True
                self.flags[inv_flag] = True
            self.apply_implied_progress_flags()
            self._track_investigated_target(target)
            system_log = (
                f"{name}の調査に成功した。"
                + (f"\n【確定手がかり】{fact}" if fact else "")
            )
            payload = {
                "system_log": system_log,
                "kp_instruction": (
                    "【ダイス成功】下記の確定手がかりを必ず描写に含めよ。"
                    "「何も見つからなかった」と空振りさせるな。"
                    "未記載の怪異・呪文・新事実を創作するな。"
                    "資料・ハンドアウトがある場合は【資料本文】として原文を省略せず IC 描写に含めよ。"
                    + (f"\n確定手がかり: {fact}" if fact else f"\n対象 description を要約して伝えよ（`{target}`）。")
                ),
                "flag_updates": flag_updates,
                "mark_investigated": True,
                "confirmed_fact": fact,
                "dice_success": True,
                "san_check": {"required": False},
            }
            if should_emit_handout_ic(obj, fact):
                payload["handout_text"] = fact
                payload["handout_ic_block"] = format_handout_ic_block(fact, name)
            payload = self._attach_knowledge_grants(payload, action_id, target, success_level)
            return self._merge_time_hints(payload, time_hints, action_id, target)

        payload = {
            "system_log": "特になにも見つからなかった。",
            "kp_instruction": "行動の結果、特に有益な変化や手がかりがなかったことを描写し、どうするか問いかけてください。",
            "san_check": {"required": False},
        }
        return self._merge_time_hints(payload, time_hints, action_id, target)

