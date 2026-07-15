import random
import re

from expression_evaluator import SafeExpressionEvaluator, build_scenario_eval_context
from schema_definition import EventTriggerSchema, compile_trigger_condition, infer_action_type, merge_payload_elements
from DiceEngine import SuccessLevel, normalize_difficulty


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


PHYSICAL_ACTIONS = frozenset({"break", "push", "kick", "force"})
INVESTIGATION_ACTIONS = frozenset({"search", "inspect"})
IRON_GATE_TARGET = "iron_gate"
GATE_WEAKNESS_FLAG = "gate_weakness_found"
GATE_OPENED_FLAG = "gate_opened"
IRON_GATE_PHYSICAL_ACTIONS = frozenset({"break", "push", "kick", "force"})
ROOM_SAN_CHECKED_FLAG_PREFIX = "room_san_checked_"
STAGNATION_KP_INJECT_THRESHOLD = 2
STAGNATION_PAUSE_THRESHOLD = 3
MOVE_DENY_SYSTEM_LOG = (
    "[システム] その場所へ進むことはできません。"
    "別のオブジェクトを調査するか、適切な移動先を選択してください。"
)
MOVE_DENY_KP_INSTRUCTION = (
    "【システム確定】探索者はその方向へ進めなかった。"
    "ナレーションで「そちらには進めない／行く手がない」と明確に描写してください。"
    "調査済みオブジェクトを再度勧めるのではなく、未調査オブジェクトか有効な移動先を提示してください。"
)

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
        self.turn_counter = self.initial_state.get("turn_counter", 0)
        self.flags = dict(self.initial_state.get("flags", {}))
        self.flags.setdefault("investigated_targets", [])

        self.event_triggers = json_data.get("event_triggers", [])
        self._normalize_event_triggers()
        self.event_triggers.sort(key=lambda x: x.get("priority", 0), reverse=True)

        self.triggered_counts = {}
        self.stagnation_counter = 0

    def export_to_dict(self):
        return {
            "current_phase": self.current_phase,
            "location": self.location,
            "turn_counter": self.turn_counter,
            "flags": self.flags,
            "triggered_counts": self.triggered_counts,
            "stagnation_counter": self.stagnation_counter,
        }

    def load_from_dict(self, data):
        self.current_phase = data.get("current_phase", "start")
        self.location = data.get("location", "")
        self.turn_counter = data.get("turn_counter", 0)
        self.flags = data.get("flags", {})
        if not isinstance(self.flags, dict):
            self.flags = {}
        self.flags.setdefault("investigated_targets", [])
        self.triggered_counts = data.get("triggered_counts", {})
        self.stagnation_counter = data.get("stagnation_counter", 0)

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
            flags=self.flags,
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
        """膠着と判定する連続ターン数（デフォルト 3）。"""
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

        for obj_id, obj in loc.get("objects", {}).items():
            name = obj.get("name", obj_id)
            if obj_id == IRON_GATE_TARGET and self.flags.get(GATE_OPENED_FLAG):
                status = "開放済み（向こうへは現在地から直接 move 不可）"
            elif self._is_target_investigated(obj_id) and not self._is_research_reopened(obj_id):
                status = "調査完了・これ以上情報なし"
            else:
                status = "未調査・調査可能"
            lines.append(f'- `{obj_id}`（{name}）: {status}')

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

    def get_connected_to(self, loc_id=None):
        loc = self.get_location_info(loc_id)
        return loc.get("connected_to", [])

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
            if req_flag is not None and not self.flags.get(req_flag, False):
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
        if req_flag and not self.flags.get(req_flag, False):
            return self._build_blocked_payload(
                exit_info.get("reject_message")
                or f"【システムブロック】{exit_info.get('name', dest_id)} へはまだ進めません。",
                "必要な条件（フラグ）が未達のため移動できません。別の手がかりを探すよう誘導してください。",
            )
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
            reject = (obj or {}).get(
                "reject_message",
                "【システムブロック】この対象は既に調査済みです。",
            )
            return self._build_blocked_payload(
                reject,
                "同対象の再調査は無意味であることを伝え、部屋の別オブジェクトや次の行動へ誘導してください。",
            )
        return None

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
        移動条件・オブジェクト可視性・調査済みブロック・SAN保留を一括判定する。
        """
        loc_id = loc_id or self.location
        action_id = str(action_id or "").lower()
        target = str(target or "").strip()

        san_block = self.evaluate_san_pending_block(action_id, pending_san_check)
        if san_block:
            return san_block

        if action_id == "move" and target:
            move_check = self._validate_move(target)
            if not move_check.get("allowed"):
                return self._build_blocked_payload(
                    move_check["system_log"],
                    move_check["kp_instruction"],
                )
            exit_block = self._evaluate_exit_guard(target, loc_id=loc_id)
            if exit_block:
                return exit_block

        if action_id in INVESTIGATION_ACTIONS and target:
            obj = self.get_object_info(loc_id, target)
            if not obj:
                return self._build_blocked_payload(
                    f"【システムブロック】'{target}' はこの場所に存在しない。",
                    "存在しない対象への調査はできない。有効なオブジェクトを提示してください。",
                )
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

        return self.evaluate_pre_roll_block(
            action_id, target, loc_id, pending_san_check=pending_san_check,
        )

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
        """
        loc_id = loc_id or self.location
        obj = self.get_object_info(loc_id, target)

        if action_id in PHYSICAL_ACTIONS and obj.get("STR"):
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

            return {
                "type": "opposed_str",
                "attribute": "STR",
                "opponent_value": obj.get("STR", 50),
                "difficulty": normalize_difficulty(obj.get("difficulty", "regular")),
                "label": obj.get("name", target),
                "penalty_dice": obj.get("penalty_dice", 0),
                "bonus_dice": obj.get("bonus_dice", 0),
            }

        if action_id == "search" and target and obj.get("re_search_penalty_dice"):
            if self.flags.get("desk_research_unlocked") or self.flags.get(f"{target}_research_unlocked"):
                return {
                    "type": "skill",
                    "skill_name": "目星",
                    "penalty_dice": obj.get("re_search_penalty_dice", 1),
                    "modifier": obj.get("re_search_modifier", 0),
                    "difficulty": normalize_difficulty(obj.get("difficulty", "regular")),
                }

        return None

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
        self.turn_counter += 1
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
        if not target:
            return {
                "allowed": False,
                "system_log": f"{MOVE_DENY_SYSTEM_LOG}（移動先が指定されていません）",
                "kp_instruction": (
                    f"{MOVE_DENY_KP_INSTRUCTION} "
                    "PLは移動先を指定せずに動こうとしました。"
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

    def _apply_payload_updates(self, payload):
        if "flag_updates" in payload:
            for key, value in payload["flag_updates"].items():
                self.flags[key] = value

        for flag_name in payload.get("capture_turn_flags", []):
            self.flags[flag_name] = self.turn_counter

        if "new_phase" in payload:
            self.current_phase = payload["new_phase"]

        if "new_location" in payload:
            new_loc = payload["new_location"]
            self.location = new_loc
            visit_key = f"visit_{new_loc}"
            self.flags[visit_key] = self.flags.get(visit_key, 0) + 1

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
        self.turn_counter += 1
        time_hints = self._advance_time_flags(action_id, target)

        if action_id == "move":
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
            payload = dict(triggered_event.get("payload", {}))

            self._apply_payload_updates(payload)
            if self._should_mark_investigated(action_id, target, success_level, action_type, payload):
                self._track_investigated_target(target)

            if action_type == "call_custom_script":
                script_name = payload.get("script_name")
                args = payload.get("args", {})
                if hasattr(self, "custom_scripts") and hasattr(self.custom_scripts, script_name):
                    getattr(self.custom_scripts, script_name)(args)

            if "new_location" in payload:
                payload["location_changed"] = True

            return self._merge_time_hints(payload, time_hints, action_id, target)

        if not action_id or action_id in ["none", "wait", "san_check", ""]:
            payload = {
                "system_log": "",
                "kp_instruction": "【システム指示】PLは直前の事象（発見やSANチェックなど）を終えて待機しています。先ほどの状況を引き継ぎ、どう行動するかPLに問いかけてください。",
                "san_check": {"required": False},
            }
            return self._merge_time_hints(payload, time_hints, action_id, target)

        if action_id == "move":
            payload = self._build_blocked_payload(
                MOVE_DENY_SYSTEM_LOG,
                MOVE_DENY_KP_INSTRUCTION,
            )
            return self._merge_time_hints(payload, time_hints, action_id, target)

        payload = {
            "system_log": "特になにも見つからなかった。",
            "kp_instruction": "行動の結果、特に有益な変化や手がかりがなかったことを描写し、どうするか問いかけてください。",
            "san_check": {"required": False},
        }
        return self._merge_time_hints(payload, time_hints, action_id, target)
