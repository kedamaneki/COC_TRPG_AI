"""
シナリオ JSON の静的バリデーション。

ビルド時・ロード前に呼び、スキーマ適合・移動経路・フラグ参照・ID重複を検査する。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from schema_definition import GenericScenarioSchema

# 条件式から flags.xxx / global_states.flags.xxx を抽出
_FLAG_DOT_RE = re.compile(
    r"(?:flags|global_states\.flags)\.([A-Za-z_][A-Za-z0-9_]*)"
)
_FLAG_GET_RE = re.compile(
    r"(?:flags|global_states\.flags)\s*\[\s*['\"]([A-Za-z_][A-Za-z0-9_]*)['\"]\s*\]"
)

# エンジンが暗黙に使う／生成するフラグ（シナリオ定義不要）
ENGINE_IMPLICIT_FLAGS = frozenset({
    "investigated_targets",
    "turn_since_last_search",
})

ENGINE_IMPLICIT_FLAG_PREFIXES = (
    "visit_",
    "room_san_checked_",
    "counter_",
)


class ScenarioValidationError(Exception):
    """シナリオ静的バリデーション失敗。"""

    def __init__(self, errors: List[str], *, warnings: Optional[List[str]] = None):
        self.errors = list(errors or [])
        self.warnings = list(warnings or [])
        parts = ["シナリオバリデーションに失敗しました:"]
        for i, msg in enumerate(self.errors, 1):
            parts.append(f"  [{i}] {msg}")
        if self.warnings:
            parts.append("警告:")
            for msg in self.warnings:
                parts.append(f"  - {msg}")
        super().__init__("\n".join(parts))


def normalize_flag_token(raw: str) -> str:
    """requires_flag 等の '!flag_name' 記法から実フラグ名を取り出す。"""
    text = str(raw or "").strip()
    if text.startswith("!"):
        text = text[1:].strip()
    return text


def extract_flag_names_from_expression(expr: str) -> Set[str]:
    """条件式文字列から参照フラグ名を抽出する。"""
    text = str(expr or "")
    names: Set[str] = set()
    for match in _FLAG_DOT_RE.finditer(text):
        names.add(match.group(1))
    for match in _FLAG_GET_RE.finditer(text):
        names.add(match.group(1))
    return names


def _is_engine_implicit_flag(name: str) -> bool:
    if name in ENGINE_IMPLICIT_FLAGS:
        return True
    return any(name.startswith(prefix) for prefix in ENGINE_IMPLICIT_FLAG_PREFIXES)


def collect_defined_flags(scenario: dict) -> Set[str]:
    """シナリオ内で定義・更新されるフラグ名を収集する。"""
    defined: Set[str] = set()
    initial = (scenario or {}).get("initial_state") or {}
    flags = initial.get("flags") or {}
    if isinstance(flags, dict):
        defined.update(str(k) for k in flags.keys())

    for loc in ((scenario or {}).get("locations") or {}).values():
        if not isinstance(loc, dict):
            continue
        objects = loc.get("objects") or {}
        if isinstance(objects, dict):
            iterable = objects.items()
        elif isinstance(objects, list):
            iterable = (
                (o.get("object_id") or o.get("id") or "", o)
                for o in objects if isinstance(o, dict)
            )
        else:
            iterable = []
        for _oid, obj in iterable:
            if not isinstance(obj, dict):
                continue
            inv = obj.get("investigated_flag")
            if inv:
                defined.add(str(inv))
            for f in obj.get("clue_flags_on_success") or []:
                defined.add(str(f))
            trg = obj.get("triggers_flag_on_success")
            if isinstance(trg, dict):
                defined.update(str(k) for k in trg.keys())
            elif isinstance(trg, str) and trg:
                defined.add(trg)
            auto = obj.get("auto_success_flag")
            if auto:
                defined.add(str(auto))

    for trigger in (scenario or {}).get("event_triggers") or []:
        if not isinstance(trigger, dict):
            continue
        payload = trigger.get("payload") or {}
        if isinstance(payload, dict):
            fu = payload.get("flag_updates") or {}
            if isinstance(fu, dict):
                defined.update(str(k) for k in fu.keys())
        for element in trigger.get("payloads") or []:
            if not isinstance(element, dict):
                continue
            params = element.get("parameters") or {}
            if element.get("action_type") == "set_flag":
                key = params.get("flag") or params.get("name")
                if key:
                    defined.add(str(key))
            if isinstance(params.get("flag_updates"), dict):
                defined.update(str(k) for k in params["flag_updates"].keys())

    return defined


def collect_referenced_flags(scenario: dict) -> Set[str]:
    """条件式・requires_flag 等で参照されているフラグ名を収集する。"""
    referenced: Set[str] = set()

    for loc in ((scenario or {}).get("locations") or {}).values():
        if not isinstance(loc, dict):
            continue
        for exit_info in (loc.get("exits") or {}).values():
            if not isinstance(exit_info, dict):
                continue
            if exit_info.get("requires_flag"):
                referenced.add(normalize_flag_token(exit_info["requires_flag"]))
            if exit_info.get("condition"):
                referenced.update(extract_flag_names_from_expression(exit_info["condition"]))
        for obj in (loc.get("objects") or {}).values() if isinstance(loc.get("objects"), dict) else []:
            if not isinstance(obj, dict):
                continue
            for key in ("is_visible_condition", "condition"):
                if obj.get(key):
                    referenced.update(extract_flag_names_from_expression(obj[key]))

    for trigger in (scenario or {}).get("event_triggers") or []:
        if not isinstance(trigger, dict):
            continue
        for key in ("trigger_condition", "custom_eval"):
            if trigger.get(key):
                referenced.update(extract_flag_names_from_expression(trigger[key]))

    # 空文字・条件リテラル除外
    referenced.discard("")
    referenced.discard("true")
    referenced.discard("false")
    return referenced


def validate_schema(scenario: dict) -> List[str]:
    """GenericScenarioSchema による構造チェック。"""
    errors: List[str] = []
    try:
        GenericScenarioSchema.model_validate(scenario)
    except Exception as exc:
        errors.append(f"[スキーマ] {exc}")
    return errors


def validate_exits_and_locations(scenario: dict) -> List[str]:
    """connected_to / exits の移動先が locations に実在するか。"""
    errors: List[str] = []
    locations = (scenario or {}).get("locations") or {}
    if not isinstance(locations, dict):
        return ["[移動経路] locations が辞書ではありません。"]
    loc_ids = set(locations.keys())
    initial_loc = ((scenario or {}).get("initial_state") or {}).get("location")
    if initial_loc and initial_loc not in loc_ids:
        errors.append(
            f"[移動経路] initial_state.location の '{initial_loc}' が locations に存在しません。"
        )
    meta_loc = ((scenario or {}).get("scenario_meta") or {}).get("initial_location")
    if meta_loc and meta_loc not in loc_ids:
        errors.append(
            f"[移動経路] scenario_meta.initial_location の '{meta_loc}' が locations に存在しません。"
        )

    for loc_id, loc in locations.items():
        if not isinstance(loc, dict):
            errors.append(f"[移動経路] locations['{loc_id}'] が辞書ではありません。")
            continue
        for dest in loc.get("connected_to") or []:
            if dest not in loc_ids:
                errors.append(
                    f"[移動経路] locations['{loc_id}'].connected_to の '{dest}' は未定義のロケーションです。"
                )
        exits = loc.get("exits") or {}
        if isinstance(exits, dict):
            for exit_key, exit_info in exits.items():
                dest = exit_key
                if isinstance(exit_info, dict):
                    dest = (
                        exit_info.get("destination")
                        or exit_info.get("target_location")
                        or exit_info.get("target_location_id")
                        or exit_info.get("connected_to")
                        or exit_key
                    )
                if dest not in loc_ids:
                    errors.append(
                        f"[移動経路] locations['{loc_id}'].exits['{exit_key}'] の移動先 '{dest}' "
                        "は未定義のロケーションです。"
                    )
    return errors


def validate_flag_references(scenario: dict) -> List[str]:
    """参照フラグが定義・更新されているか。"""
    errors: List[str] = []
    defined = collect_defined_flags(scenario)
    referenced = collect_referenced_flags(scenario)
    for name in sorted(referenced):
        if _is_engine_implicit_flag(name):
            continue
        if name not in defined:
            errors.append(
                f"[フラグ] '{name}' が条件式または requires_flag で参照されていますが、"
                "initial_state / investigated_flag / flag_updates 等で定義・更新されていません。"
            )
    return errors


def validate_unique_ids(scenario: dict) -> Tuple[List[str], List[str]]:
    """
    event_id のグローバル一意性、object_id のロケーション横断重複を検査する。

    Returns:
        (errors, warnings)
    """
    errors: List[str] = []
    warnings: List[str] = []

    seen_events: Dict[str, str] = {}
    for idx, trigger in enumerate((scenario or {}).get("event_triggers") or []):
        if not isinstance(trigger, dict):
            continue
        eid = trigger.get("event_id")
        if not eid:
            errors.append(f"[ID重複] event_triggers[{idx}] に event_id がありません。")
            continue
        eid = str(eid)
        if eid in seen_events:
            errors.append(
                f"[ID重複] event_id '{eid}' が重複しています"
                f"（先: {seen_events[eid]}, 後: index={idx}）。"
            )
        else:
            seen_events[eid] = f"index={idx}"

    object_owners: Dict[str, str] = {}
    for loc_id, loc in ((scenario or {}).get("locations") or {}).items():
        if not isinstance(loc, dict):
            continue
        objects = loc.get("objects") or {}
        if not isinstance(objects, dict):
            continue
        # 同一ロケーション内で同一オブジェクト実体へのエイリアスは許容
        id_map: Dict[int, str] = {}
        for oid, obj in objects.items():
            oid = str(oid)
            obj_id_key = id(obj) if isinstance(obj, dict) else None
            if obj_id_key is not None and obj_id_key in id_map:
                # エイリアス（同一 dict）→ OK
                continue
            if obj_id_key is not None:
                id_map[obj_id_key] = oid

            prev = object_owners.get(oid)
            if prev and prev != loc_id:
                errors.append(
                    f"[ID重複] object_id '{oid}' が複数ロケーションで使用されています"
                    f"（'{prev}' と '{loc_id}'）。識別子を一意にしてください。"
                )
            else:
                object_owners[oid] = loc_id

    return errors, warnings


def validate_scenario(
    scenario: dict,
    *,
    raise_on_error: bool = True,
) -> Tuple[List[str], List[str]]:
    """
    全静的チェックを実行する。

    Returns:
        (errors, warnings)
    Raises:
        ScenarioValidationError: raise_on_error=True かつ errors がある場合
    """
    errors: List[str] = []
    warnings: List[str] = []

    errors.extend(validate_schema(scenario))
    errors.extend(validate_exits_and_locations(scenario))
    errors.extend(validate_flag_references(scenario))
    id_errors, id_warnings = validate_unique_ids(scenario)
    errors.extend(id_errors)
    warnings.extend(id_warnings)

    if errors and raise_on_error:
        raise ScenarioValidationError(errors, warnings=warnings)
    return errors, warnings
