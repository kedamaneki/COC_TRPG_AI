#!/usr/bin/env python3
"""悪霊の家: ステージングキャッシュ（配列loc + 中間events）を
エンジン・ネイティブ形式のシナリオJSONへコンパイルするビルドスクリプト。

出力: src/scenario_corbitt.json （ScenarioManager がそのまま読める形式）

- locations: 辞書（loc_id -> {..., objects: 辞書}）
- event_triggers: trigger_condition(文字列) + payload(辞書) を success_level で分割
- オブジェクト定義（investigated_flag / success_message / san_check /
  clue_flags_on_success / triggers_flag_on_success 等）を正としてイベント生成
"""
from __future__ import annotations

import json
from pathlib import Path

from scenario_validation import ScenarioValidationError, validate_scenario

CACHE_DIR = Path(__file__).resolve().parent / ".local" / ".staged_cache" / "e870e9f8fc96"
OUT_FILE = Path(__file__).resolve().parent / "scenario_corbitt.json"
CORBITT_SCENARIO_FILENAME = "scenario_corbitt.json"

# ファイル名 -> location_id
LOC_FILES = {
    "loc_01_introduction.json": "introduction",
    "loc_02_boston_globe.json": "boston_globe",
    "loc_03_central_library.json": "central_library",
    "loc_04_hall_of_records.json": "hall_of_records",
    "loc_05_higher_courts_police_station.json": "higher_courts_police_station",
    "loc_06_the_neighborhood.json": "the_neighborhood",
    "loc_07_roxbury_sanitarium.json": "roxbury_sanitarium",
    "loc_08_chapel_of_contemplation.json": "chapel_of_contemplation",
    "loc_09_corbitt_exterior.json": "corbitt_exterior",
    "loc_10_corbitt_ground_floor.json": "corbitt_ground_floor",
    "loc_11_corbitt_upper_floor.json": "corbitt_upper_floor",
    "loc_12_corbitt_basement.json": "corbitt_basement",
    "loc_13_corbitt_basement_room2.json": "corbitt_basement_room2",
    "loc_14_corbitt_basement_room3.json": "corbitt_basement_room3",
}

# 移動ゲート用フラグを追加で立てるオブジェクト（investigated_flag 以外）
EXTRA_SUCCESS_FLAGS = {
    "knott_letter": {"case_accepted": True},
}

# これらは汎用調査イベントではなく特殊生成する
SPECIAL_OBJECTS = {"basement_door", "basement_planks", "corbitt_knife", "corbitt_body"}


def _load(name):
    return json.loads((CACHE_DIR / name).read_text(encoding="utf-8"))


def _objects_to_dict(loc):
    """objects 配列 -> 辞書（object_id キー）。alias も同じ実体で引けるよう複製登録。"""
    result = {}
    objs = loc.get("objects", [])
    if isinstance(objs, dict):
        return objs
    for idx, obj in enumerate(objs):
        if not isinstance(obj, dict):
            continue
        oid = obj.get("object_id") or obj.get("id") or f"object_{idx + 1}"
        entry = dict(obj)
        entry.pop("object_id", None)
        result[oid] = entry
        for alias in obj.get("aliases", []) or []:
            if alias not in result:
                result[alias] = entry
    return result


def _build_exits(loc_id, connected_to, raw_exits):
    """connected_to を基準に、宛先IDをキーとした exits を再構築する。"""
    exits = {}
    raw = raw_exits or {}

    def find_raw_for(dest):
        for _, info in raw.items():
            if not isinstance(info, dict):
                continue
            cand = (
                info.get("destination")
                or info.get("target_location")
                or info.get("target_location_id")
                or info.get("connected_to")
            )
            if cand == dest:
                return info
        return None

    for dest in connected_to:
        info = find_raw_for(dest) or {}
        entry = {"name": info.get("name", dest)}
        if info.get("requires_flag") not in (None, ""):
            entry["requires_flag"] = info["requires_flag"]
        elif info.get("condition") not in (None, "", "true"):
            entry["condition"] = info["condition"]
        entry["reject_message"] = info.get(
            "reject_message", "【システムブロック】その方向へは進めません。"
        )
        exits[dest] = entry
    return exits


def _san_payload(obj):
    """オブジェクトの san_check 定義を payload の san_check へ変換。"""
    sc = obj.get("san_check")
    if not isinstance(sc, dict) or not sc.get("required"):
        return {"required": False}
    value = str(sc.get("value", "1D3"))
    # "1/1D8" 形式は失敗側ダイスを採用
    if "/" in value:
        value = value.split("/")[-1]
    return {"required": True, "value": value, "source": sc.get("source", "generic")}


def _success_text(obj, name):
    for key in ("success_message", "clue_on_success", "investigated_description", "clue_on_investigate"):
        if obj.get(key):
            return obj[key]
    return f"{name}を注意深く調べ、重要な手がかりを見つけた。"


def _collect_success_flags(oid, obj):
    """成功時に立てるフラグを収集する。"""
    flags = {}
    inv = obj.get("investigated_flag")
    if inv:
        flags[inv] = True
    for f in obj.get("clue_flags_on_success", []) or []:
        flags[f] = True
    trg = obj.get("triggers_flag_on_success")
    if isinstance(trg, dict):
        flags.update(trg)
    elif isinstance(trg, str) and trg:
        flags[trg] = True
    flags.update(EXTRA_SUCCESS_FLAGS.get(oid, {}))
    return flags


def _make_investigation_events(loc_id, oid, obj):
    """汎用調査（search/inspect）イベント: 成功/失敗を success_level で分割。"""
    name = obj.get("name", oid)
    inv = obj.get("investigated_flag") or f"{oid}_investigated"
    flags = _collect_success_flags(oid, obj)
    san = _san_payload(obj)
    base = (
        f"action_id in ['search', 'inspect'] and target == '{oid}' "
        f"and location == '{loc_id}' and flags.{inv} == false"
    )
    success = {
        "event_id": f"{loc_id}__{oid}__success",
        "priority": 60,
        "trigger_condition": f"{base} and success_level >= 2",
        "action_type": "update_and_describe",
        "payload": {
            "system_log": _success_text(obj, name),
            "kp_instruction": (
                "システムが判定した調査成功の結果を、情景に自然に織り込んで描写してください。"
                "その後どうするかをPLに問いかけてください。"
            ),
            "flag_updates": flags,
            "mark_investigated": True,
            "san_check": san,
        },
    }
    failure = {
        "event_id": f"{loc_id}__{oid}__failure",
        "priority": 60,
        "trigger_condition": f"{base} and success_level <= 1",
        "action_type": "update_and_describe",
        "payload": {
            "system_log": f"{name}を調べたが、これといった手がかりは見つからなかった。",
            "kp_instruction": (
                "調査に失敗したことを描写し、再挑戦（プッシュ）や別の対象・アプローチを促してください。"
            ),
            "san_check": {"required": False},
        },
    }
    return [success, failure]


def _special_events(loc_id, oid, obj):
    """移動解放・破壊・戦闘など特殊オブジェクトのネイティブイベント。"""
    name = obj.get("name", oid)
    events = []

    if oid == "basement_door":
        base = (
            f"action_id in ['search', 'inspect', 'break', 'force', 'push'] "
            f"and target == '{oid}' and location == '{loc_id}' "
            f"and flags.basement_accessible == false"
        )
        events.append({
            "event_id": f"{loc_id}__basement_door__success",
            "priority": 70,
            "trigger_condition": f"{base} and success_level >= 2",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": obj.get("success_message", "地下室への扉を開けた。"),
                "kp_instruction": "扉が開いたことを描写し、地階へ降りるか問いかけてください。",
                "flag_updates": {
                    "basement_accessible": True,
                    "basement_door_unlocked": True,
                    "hidden_passage_found": True,
                },
                "mark_investigated": True,
                "san_check": {"required": False},
            },
        })
        events.append({
            "event_id": f"{loc_id}__basement_door__failure",
            "priority": 70,
            "trigger_condition": f"{base} and success_level <= 1",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": obj.get("reject_message", "扉はまだ開かない。"),
                "kp_instruction": "扉が開かなかったことを描写し、STRでこじ開けるか目星で弱点を探すよう促してください。",
                "san_check": {"required": False},
            },
        })
        return events

    if oid == "basement_planks":
        base = (
            f"action_id in ['search', 'inspect', 'break', 'force', 'push'] "
            f"and target == '{oid}' and location == '{loc_id}' "
            f"and flags.basement_planks_broken == false"
        )
        events.append({
            "event_id": f"{loc_id}__basement_planks__success",
            "priority": 70,
            "trigger_condition": f"{base} and success_level >= 2",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": obj.get("success_message", "板を破壊し、奥の部屋への通路を開けた。"),
                "kp_instruction": "板が砕けて奥への道が開けたことを描写してください。",
                "flag_updates": {"basement_planks_broken": True, "basement_planks_examined": True},
                "mark_investigated": True,
                "san_check": {"required": False},
            },
        })
        events.append({
            "event_id": f"{loc_id}__basement_planks__failure",
            "priority": 70,
            "trigger_condition": f"{base} and success_level <= 1",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": obj.get("reject_message", "板はまだ壊れない。"),
                "kp_instruction": "板を壊せなかったことを描写し、再挑戦を促してください。",
                "san_check": {"required": False},
            },
        })
        return events

    if oid == "corbitt_knife":
        base = (
            f"action_id in ['search', 'inspect', 'use'] and target == '{oid}' "
            f"and location == '{loc_id}' and flags.has_corbitt_knife == false"
        )
        events.append({
            "event_id": f"{loc_id}__corbitt_knife__encounter",
            "priority": 75,
            "trigger_condition": f"{base}",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": obj.get("clue_on_investigate", "ナイフがひとりでに宙に浮き、襲いかかってきた！"),
                "kp_instruction": (
                    "コービットの魔法のダガーが自律的に襲撃してくる戦闘シーンを描写してください。"
                    "システムは戦闘フラグを立てています。緊迫した戦闘描写を行ってください。"
                ),
                "flag_updates": {"has_corbitt_knife": True, "trigger_knife_attack": True},
                "mark_investigated": True,
                "san_check": {"required": True, "value": "1D4", "source": "generic"},
                "combat_start": {"enemies": ["corbitt_floating_dagger"]},
            },
        })
        return events

    if oid == "corbitt_body":
        # 遭遇（SANチェックと戦闘開始）
        enc_base = (
            f"action_id in ['search', 'inspect'] and target == '{oid}' "
            f"and location == '{loc_id}' and flags.corbitt_body_encountered == false"
        )
        events.append({
            "event_id": f"{loc_id}__corbitt_body__encounter",
            "priority": 90,
            "trigger_condition": f"{enc_base}",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": (
                    "干からびた遺体の『ぎらぎらと輝く目』がぐるりと動き、憎悪を込めて凝視してきた。"
                    "ウォルター・コービットは生きている！ 彼が身を起こし、襲いかかろうとする！"
                ),
                "kp_instruction": (
                    "生ける屍コービットとの戦闘開始を描写してください。"
                    "探索者は攻撃するか、遺体を破壊・浄化するか、逃走するかを選べます。"
                    "遺体（corbitt_body）を破壊すればシナリオクリアです。"
                ),
                "flag_updates": {"corbitt_body_encountered": True, "trigger_corbitt_boss_battle": True},
                "san_check": {"required": True, "value": "1D8", "source": "generic"},
                "combat_start": {
                    "enemies": ["walter_corbitt"],
                    "roll_armor_for": ["walter_corbitt"],
                },
            },
        })
        # 撃破 → クリア
        defeat_base = (
            f"action_id in ['break', 'force', 'attack', 'use', 'push', 'kick'] "
            f"and target == '{oid}' and location == '{loc_id}' "
            f"and flags.corbitt_defeated == false and flags.corbitt_body_encountered == true"
        )
        events.append({
            "event_id": f"{loc_id}__corbitt_body__defeat",
            "priority": 95,
            "trigger_condition": f"{defeat_base} and success_level >= 2",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": (
                    "渾身の一撃、あるいは浄化の儀式によってウォルター・コービットの遺体は崩れ落ち、"
                    "屋敷を覆っていた冒涜的な気配が霧散していく。悪霊の家の呪いは解かれた。"
                ),
                "kp_instruction": "コービット討伐とシナリオクリアを劇的に描写して、セッションを締めくくってください。",
                "flag_updates": {"corbitt_defeated": True},
                "new_phase": "clear",
                "combat_end": True,
                "san_check": {"required": False},
            },
        })
        events.append({
            "event_id": f"{loc_id}__corbitt_body__defeat_fail",
            "priority": 95,
            "trigger_condition": f"{defeat_base} and success_level <= 1",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": "攻撃は決定打とならず、コービットは反撃してくる。戦いは続く。",
                "kp_instruction": "攻撃が失敗し反撃されることを描写し、再挑戦を促してください。",
                "san_check": {"required": False},
            },
        })
        return events

    return events


def _staged_source_files():
    """ビルド入力となるステージングファイル一覧。"""
    names = ["outline.json", *LOC_FILES.keys()]
    return [CACHE_DIR / name for name in names]


def staged_cache_available() -> bool:
    """複数ファイル構成のステージングキャッシュが揃っているか。"""
    return CACHE_DIR.is_dir() and all(path.is_file() for path in _staged_source_files())


def needs_rebuild() -> bool:
    """出力JSONが無い、またはソースより古い場合 True。"""
    if not OUT_FILE.is_file():
        return True
    if not staged_cache_available():
        return False
    out_mtime = OUT_FILE.stat().st_mtime
    return any(path.stat().st_mtime > out_mtime for path in _staged_source_files())


def build_scenario_dict() -> dict:
    """ステージングキャッシュからシナリオ辞書を組み立てる。"""
    if not staged_cache_available():
        raise FileNotFoundError(
            f"悪霊の家のステージングキャッシュが見つかりません: {CACHE_DIR}"
        )

    outline = _load("outline.json")
    meta = outline.get("scenario_meta", {})
    initial_state = outline.get("initial_state", {})

    locations = {}
    event_triggers = []

    for fname, loc_id in LOC_FILES.items():
        loc = _load(fname)
        objects = _objects_to_dict(loc)
        connected = loc.get("connected_to", []) or []
        if loc_id == "introduction" and not connected:
            connected = loc.get("_unlockable_locations", []) or []
        exits = _build_exits(loc_id, connected, loc.get("exits"))

        locations[loc_id] = {
            "name": loc.get("name", loc_id),
            "default_description": loc.get("default_description", ""),
            "connected_to": connected,
            "objects": objects,
            "exits": exits,
        }

        seen_oids = set()
        for oid, obj in objects.items():
            if oid in seen_oids:
                continue
            seen_oids.add(oid)
            if oid in SPECIAL_OBJECTS:
                event_triggers.extend(_special_events(loc_id, oid, obj))
            elif obj.get("investigated_flag") or obj.get("clue_flags_on_success"):
                event_triggers.extend(_make_investigation_events(loc_id, oid, obj))

    scenario = {
        "scenario_meta": {
            "title": meta.get("title", "悪霊の家"),
            "background": meta.get("background", ""),
            "summary": meta.get("summary", ""),
            "initial_phase": meta.get("initial_phase", "introduction"),
            "initial_location": meta.get("initial_location", "introduction"),
            "startup_effects": {},
            "intervention_level": meta.get("intervention_level", "light"),
            "max_stagnation_turns": meta.get("max_stagnation_turns", 4),
            "stagnation_hint": meta.get(
                "stagnation_hint",
                "住人への聞き込み、屋敷内の別室、書物や痕跡など別の手がかりを当たってみよう。",
            ),
        },
        "initial_state": {
            "current_phase": initial_state.get("current_phase", "introduction"),
            "location": initial_state.get("location", "introduction"),
            "turn_counter": 0,
            "flags": initial_state.get("flags", {}),
            "counters": {},
        },
        "locations": locations,
        "event_triggers": event_triggers,
    }
    return scenario


def validate_built_scenario(scenario: dict, *, raise_on_error: bool = True):
    """結合後シナリオに対する静的バリデーション。"""
    errors, warnings = validate_scenario(scenario, raise_on_error=False)
    for msg in warnings:
        print(f"[build:warn] {msg}")
    if errors and raise_on_error:
        raise ScenarioValidationError(errors, warnings=warnings)
    return errors, warnings


def build(*, skip_validation: bool = False) -> Path:
    """ステージングキャッシュをコンパイルして scenario_corbitt.json を書き出す。"""
    scenario = build_scenario_dict()
    if not skip_validation:
        try:
            validate_built_scenario(scenario, raise_on_error=True)
        except ScenarioValidationError as exc:
            print(str(exc))
            print("[build] バリデーション失敗のため scenario_corbitt.json は更新しません。")
            raise
        print("[build] static validation: OK")

    OUT_FILE.write_text(json.dumps(scenario, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[build] wrote {OUT_FILE}")
    print(f"[build] locations={len(scenario['locations'])} events={len(scenario['event_triggers'])}")
    return OUT_FILE


def ensure_built(*, force: bool = False) -> Path:
    """必要ならビルド（＋自動バリデーション）し、プレイ用シナリオJSONのパスを返す。"""
    if not staged_cache_available():
        if OUT_FILE.is_file():
            return OUT_FILE
        raise FileNotFoundError(
            "悪霊の家シナリオが未ビルドです。"
            f"ステージングキャッシュ ({CACHE_DIR}) も {OUT_FILE} も見つかりません。"
        )
    if force or needs_rebuild():
        print(
            "[build] ソース（loc_*.json / outline.json）が出力より新しいため再ビルドします。"
            if needs_rebuild() and not force else
            "[build] 強制再ビルドを実行します。"
        )
        return build()
    return OUT_FILE


if __name__ == "__main__":
    build()
