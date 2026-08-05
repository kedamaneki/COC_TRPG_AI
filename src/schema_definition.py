"""
汎用 TRPG シナリオスキーマ（Pydantic v2）。
特定シナリオに依存しないイベント駆動 JSON の型定義。
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ScenarioMetaSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    title: str = "無題のシナリオ"
    background: str = ""
    summary: str = ""
    initial_phase: str = "start"
    initial_location: str = ""
    startup_effects: Dict[str, Any] = Field(default_factory=dict)


class ExitSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    condition: Optional[str] = Field(
        default=None,
        description="移動許可条件式。例: global_states.flags.key_found == true",
    )
    requires_flag: Optional[str] = Field(
        default=None,
        description="レガシー互換: フラグ名のみで判定",
    )
    reject_message: str = Field(
        default="【システムブロック】その方向へは進めません。",
    )


class ObjectSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    description: str = ""
    names: List[str] = Field(
        default_factory=list,
        description="調査キーワード（エイリアス）",
    )
    usable_actions: List[str] = Field(default_factory=lambda: ["search", "inspect"])
    is_visible_condition: Optional[str] = Field(
        default=None,
        description="オブジェクトが探索可能になる条件式",
    )
    investigated_flag: Optional[str] = Field(
        default=None,
        description="調査完了を示す global_states.flags キー",
    )
    reject_message: str = Field(
        default="【システムブロック】この対象は既に調査済みです。別の手がかりを探してください。",
    )
    purpose: str = ""


class PayloadElement(BaseModel):
    model_config = ConfigDict(extra="allow")

    action_type: Literal[
        "system_intercept_roll",
        "force_san_check",
        "set_flag",
        "apply_damage",
        "change_phase",
        "change_location",
        "update_and_describe",
        "system_reject",
        "mark_investigated",
    ]
    parameters: Dict[str, Any] = Field(default_factory=dict)
    on_success: List["PayloadElement"] = Field(default_factory=list)
    on_failure: List["PayloadElement"] = Field(default_factory=list)


class EventTriggerSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    event_id: str
    priority: int = 0
    required_phase: Optional[str] = None
    location: Optional[str] = None
    target_object: Optional[str] = None
    action_types: List[str] = Field(default_factory=list)
    custom_eval: Optional[str] = Field(
        default=None,
        description="追加の動的条件式。例: global_states.flags.door_open == false",
    )
    max_triggers: Optional[int] = None
    payloads: List[PayloadElement] = Field(default_factory=list)

    # レガシー互換フィールド（コンバータ出力後も許容）
    trigger_condition: Optional[str] = None
    action_type: Optional[str] = None
    payload: Optional[Dict[str, Any]] = None


class LocationSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    default_description: str = ""
    connected_to: List[str] = Field(default_factory=list)
    objects: Dict[str, ObjectSchema] = Field(default_factory=dict)
    exits: Dict[str, ExitSchema] = Field(default_factory=dict)
    entry_san_check: Optional[Dict[str, Any]] = None


class InitialStateSchema(BaseModel):
    model_config = ConfigDict(extra="allow")

    current_phase: str = "start"
    location: str = ""
    turn_counter: int = 0
    flags: Dict[str, Any] = Field(default_factory=dict)
    counters: Dict[str, Any] = Field(default_factory=dict)


class GenericScenarioSchema(BaseModel):
    """ルートシナリオ定義。"""

    model_config = ConfigDict(extra="allow")

    scenario_meta: ScenarioMetaSchema
    initial_state: InitialStateSchema = Field(default_factory=InitialStateSchema)
    locations: Dict[str, LocationSchema] = Field(default_factory=dict)
    event_triggers: List[EventTriggerSchema] = Field(default_factory=list)

    @field_validator("event_triggers", mode="before")
    @classmethod
    def _coerce_triggers(cls, value):
        return value or []

    def to_engine_dict(self) -> dict:
        """既存 ScenarioManager が読み込める JSON 辞書へ変換。"""
        meta = self.scenario_meta.model_dump(exclude_none=True)
        if self.scenario_meta.initial_phase and "initial_phase" not in meta:
            meta["initial_phase"] = self.scenario_meta.initial_phase
        if self.scenario_meta.initial_location and "initial_location" not in meta:
            meta["initial_location"] = self.scenario_meta.initial_location

        initial = self.initial_state.model_dump(exclude_none=True)
        if not initial.get("location") and self.scenario_meta.initial_location:
            initial["location"] = self.scenario_meta.initial_location
        if not initial.get("current_phase"):
            initial["current_phase"] = self.scenario_meta.initial_phase

        locations: Dict[str, Any] = {}
        for loc_id, loc in self.locations.items():
            loc_data = loc.model_dump(exclude_none=True)
            objects_out = {}
            for obj_id, obj in loc.objects.items():
                obj_data = obj.model_dump(exclude_none=True)
                if obj.names and "aliases" not in obj_data:
                    obj_data["aliases"] = list(obj.names)
                objects_out[obj_id] = obj_data
            loc_data["objects"] = objects_out
            locations[loc_id] = loc_data

        triggers_out = []
        for trigger in self.event_triggers:
            t = trigger.model_dump(exclude_none=True)
            if not t.get("trigger_condition"):
                t["trigger_condition"] = compile_trigger_condition(trigger)
            if not t.get("payload") and trigger.payloads:
                t["payload"] = merge_payload_elements(trigger.payloads)
                t["action_type"] = t.get("action_type") or infer_action_type(trigger.payloads)
            triggers_out.append(t)

        return {
            "scenario_meta": meta,
            "initial_state": initial,
            "locations": locations,
            "event_triggers": triggers_out,
        }


PayloadElement.model_rebuild()


def compile_trigger_condition(trigger: EventTriggerSchema) -> str:
    """構造化トリガーから Python 互換条件式文字列を合成する。"""
    parts: List[str] = []
    if trigger.location:
        parts.append(f"location == {trigger.location!r}")
    if trigger.target_object:
        parts.append(f"target == {trigger.target_object!r}")
    if trigger.action_types:
        parts.append(f"action_id in {trigger.action_types!r}")
    if trigger.custom_eval:
        parts.append(f"({trigger.custom_eval})")
    return " and ".join(parts) if parts else "True"


def infer_action_type(payloads: List[PayloadElement]) -> str:
    if not payloads:
        return "update_and_describe"
    primary = payloads[0].action_type
    mapping = {
        "system_reject": "system_reject",
        "force_san_check": "update_and_describe",
        "set_flag": "update_and_describe",
        "apply_damage": "update_and_describe",
        "change_phase": "update_and_describe",
        "change_location": "update_and_describe",
        "mark_investigated": "update_and_describe",
        "system_intercept_roll": "update_and_describe",
        "update_and_describe": "update_and_describe",
    }
    return mapping.get(primary, "update_and_describe")


def merge_payload_elements(payloads: List[PayloadElement]) -> Dict[str, Any]:
    """PayloadElement リストを既存エンジンの payload 辞書へマージする。"""
    merged: Dict[str, Any] = {
        "san_check": {"required": False},
    }
    flag_updates: Dict[str, Any] = {}

    for element in payloads:
        action = element.action_type
        params = dict(element.parameters or {})

        if action == "set_flag":
            key = params.get("flag") or params.get("name")
            if key:
                flag_updates[str(key)] = params.get("value", True)
        elif action == "force_san_check":
            merged["san_check"] = {
                "required": True,
                "value": params.get("value", "1d3"),
                "source": params.get("source", "generic"),
                **{k: v for k, v in params.items() if k not in ("value", "source")},
            }
        elif action == "apply_damage":
            merged.setdefault("damage_effects", []).append(params)
        elif action == "change_phase":
            if params.get("phase"):
                merged["new_phase"] = params["phase"]
        elif action == "change_location":
            if params.get("location"):
                merged["new_location"] = params["location"]
        elif action == "mark_investigated":
            merged["mark_investigated"] = True
            if params.get("flag"):
                flag_updates[str(params["flag"])] = True
        elif action == "system_reject":
            merged["blocked"] = True
        elif action == "update_and_describe":
            pass

        for key in ("system_log", "kp_instruction"):
            if params.get(key):
                merged[key] = params[key]
        if params.get("flag_updates"):
            flag_updates.update(params["flag_updates"])

    if flag_updates:
        merged["flag_updates"] = flag_updates
    return merged
