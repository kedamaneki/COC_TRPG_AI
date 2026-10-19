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

import copy
import json
import os
from pathlib import Path

from scenario_validation import ScenarioValidationError, validate_scenario

_PACKAGED_SOURCE_DIR = (
    Path(__file__).resolve().parents[1]
    / "scenario_sources"
    / "corbitt"
    / "e870e9f8fc96"
)
CACHE_DIR = Path(
    os.environ.get("CORBITT_SCENARIO_SOURCE_ROOT", str(_PACKAGED_SOURCE_DIR))
).expanduser().resolve()
OUT_FILE = Path(__file__).resolve().parent / "scenario_corbitt.json"
CORBITT_SCENARIO_FILENAME = "scenario_corbitt.json"

# 原典『悪霊の家』プレイヤー資料8（再ビルドでも失われないようビルド時に注入）
PLAYER_HANDOUT_8 = (
    "【プレイヤー資料8】\n"
    "この資料は、黙想チャペルへの秘密の手入れに関するものである。"
    "警察によるこの手入れは、近所の子供が行方不明になるのはこの教会のメンバーたちの仕業だという"
    "宣誓供述書に基づいて行なわれた。手入れの最中に、3人の警察官と17人のカルティストが銃撃や火事によって死亡した。"
    "検死報告書は不思議にも詳細があいまいで、必要な情報が盛り込まれていない。"
    "実際には検死官が調べていないかのようだ。\n"
    "54人の教会のメンバーが逮捕されたものの、8人を除いてあとは釈放された。"
    "この記録から察するに、地元の偉い役人がこれに違法な介入をしたようである。"
    "市の歴史の中でも最大の犯罪事件として戦いの物語が綴られているものの、一度も公表されたことがないからだ。\n"
    "マイケル・トーマス牧師は逮捕され、5件の第2級殺人罪により40年の禁固刑を言い渡された。"
    "しかし彼は1917年に刑務所を脱走し、別の州へ逃亡した。"
)
POLICE_ARCHIVES_CLUE = (
    "黙想チャペルへの秘密の手入れで警官3名・カルト17名が死亡し、"
    "逮捕54名のうち大半が釈放された。マイケル・トーマス牧師は殺人罪で40年の刑を受けたが1917年に脱走した。"
)
POLICE_ARCHIVES_INVESTIGATED_REJECT = (
    "この警察記録はすでに閲覧済みだ。"
    "内容を再確認するなら得た資料を思い出すか、別の手がかり・場所へ進もう。"
    "再び交渉や潜入で同じ閲覧許可を取り直す必要はない。"
)

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
SPECIAL_OBJECTS = {
    "corbitt_house", "basement_door", "hidden_passage", "basement_planks", "wall_planks", "corbitt_knife", "corbitt_body",
    "rotting_floorboards",
}


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
        # キーが宛先IDそのもの（導入ロケ等）
        direct = raw.get(dest)
        if isinstance(direct, dict):
            return direct
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
        # 名前が無い／IDそのもののときは、宛先ロケーションの日本語名を後で補えないため
        # ここでは raw の name を優先し、無ければ dest を仮置き（ビルド後に補完）
        entry = {"name": info.get("name") or dest}
        if info.get("requires_flag") not in (None, ""):
            entry["requires_flag"] = info["requires_flag"]
        elif info.get("condition") not in (None, "", "true"):
            entry["condition"] = info["condition"]
        entry["reject_message"] = info.get(
            "reject_message", "【システムブロック】その方向へは進めません。"
        )
        exits[dest] = entry
    return exits


def _fill_exit_display_names(locations):
    """exits の name が ID のままなら、宛先ロケーションの name で埋める。"""
    for loc in locations.values():
        for dest_id, exit_info in (loc.get("exits") or {}).items():
            if not isinstance(exit_info, dict):
                continue
            name = str(exit_info.get("name") or "")
            if not name or name == dest_id:
                dest_loc = locations.get(dest_id) or {}
                dest_name = dest_loc.get("name")
                if dest_name:
                    exit_info["name"] = dest_name
    return locations


def _san_payload(obj):
    """オブジェクトの san_check 定義を payload の san_check へ変換。"""
    sc = obj.get("san_check")
    if not isinstance(sc, dict) or not sc.get("required"):
        return {"required": False}
    value = str(sc.get("value", "1D3")).strip()
    # Preserve the complete SAN rule. A single expression means 0 on success
    # and that expression on failure (for example 1D4 -> 0/1D4).
    if "/" in value:
        success_loss, failure_loss = (part.strip() for part in value.split("/", 1))
    else:
        success_loss, failure_loss = "0", value
    return {
        "required": True,
        "value": value,
        "success_loss": success_loss or "0",
        "failure_loss": failure_loss or "0",
        "source": sc.get("source", "generic"),
    }


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


def _event_success_overrides(raw_events):
    """Recover mandatory nested success effects from staged scenario events."""
    overrides = {}
    for event in raw_events or []:
        target = event.get("target_object")
        if not target:
            continue
        stack = []
        for item in event.get("payloads") or []:
            stack.extend(item.get("success_payloads") or item.get("on_success") or [])
        override = {}
        for effect in stack:
            action = effect.get("action_type")
            if action == "force_san_check":
                value = effect.get("san_loss_range") or effect.get("value") or "1D3"
                override["san_check"] = {"required": True, "value": value, "source": "scenario_effect"}
            elif action == "update_and_describe" and effect.get("text"):
                override["success_message"] = effect["text"]
        if override:
            overrides[(event.get("location"), target)] = override
    return overrides


def _special_events(loc_id, oid, obj):
    """移動解放・破壊・戦闘など特殊オブジェクトのネイティブイベント。"""
    name = obj.get("name", oid)
    events = []

    if oid == "corbitt_house":
        base = f"target == '{oid}' and location == '{loc_id}' and flags.corbitt_house_entered == false"
        events.append({
            "event_id": f"{loc_id}__{oid}__examine",
            "priority": 70,
            "trigger_condition": f"action_id in ['search', 'inspect'] and {base} and flags.corbitt_house_examined == false and success_level >= 2",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": "屋敷を調べ、正面玄関と窓の様子を確認した。中へ入るなら鍵を使うか、扉をこじ開ける必要がある。",
                "kp_instruction": "調査で分かったことだけを描写し、侵入はまだ確定しないでください。",
                "flag_updates": {"corbitt_house_examined": True},
                "san_check": {"required": False},
            },
        })
        events.append({
            "event_id": f"{loc_id}__{oid}__enter",
            "priority": 70,
            "trigger_condition": f"action_id in ['use', 'break', 'force'] and {base} and success_level >= 2",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": "鍵を使うか扉をこじ開け、屋敷への入口を開いた。",
                "kp_instruction": "入口が開いたことを描写し、屋敷へ移動するか問いかけてください。",
                "flag_updates": {"corbitt_house_entered": True, "front_door_unlocked": True},
                "san_check": {"required": False},
            },
        })
        return events

    if oid in ("basement_door", "hidden_passage"):
        examine_base = (
            f"action_id in ['search', 'inspect'] and target == '{oid}' "
            f"and location == '{loc_id}' and flags.basement_door_examined == false"
        )
        events.append({
            "event_id": f"{loc_id}__{oid}__examine",
            "priority": 70,
            "trigger_condition": f"{examine_base} and success_level >= 2",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": "地下室への扉を調べ、錠と板の弱点を見つけた。扉はまだ閉ざされている。",
                "kp_instruction": "弱点の発見を描写し、開けるには別の行動が必要と伝えてください。",
                "fact_policy": "EVENT_ONLY",
                "flag_updates": {"basement_door_examined": True},
                "san_check": {"required": False},
            },
        })
        base = (
            f"action_id in ['break', 'force', 'push'] "
            f"and target == '{oid}' and location == '{loc_id}' "
            f"and flags.basement_accessible == false"
        )
        events.append({
            "event_id": f"{loc_id}__{oid}__success",
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
            "event_id": f"{loc_id}__{oid}__failure",
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

    if oid in ("basement_planks", "wall_planks"):
        events.append({
            "event_id": f"{loc_id}__{oid}__examine",
            "priority": 70,
            "trigger_condition": (
                f"action_id in ['search', 'inspect'] and target == '{oid}' "
                f"and location == '{loc_id}' and flags.basement_planks_examined == false "
                "and success_level >= 2"
            ),
            "action_type": "update_and_describe",
            "payload": {
                "system_log": "板の向こうに空間があると分かった。通るには板を壊す必要がある。",
                "kp_instruction": "奥の空間を示唆し、板はまだ壊れていないと伝えてください。",
                "fact_policy": "EVENT_ONLY",
                "flag_updates": {"basement_planks_examined": True},
                "san_check": {"required": False},
            },
        })
        base = (
            f"action_id in ['break', 'force', 'push'] "
            f"and target == '{oid}' and location == '{loc_id}' "
            f"and flags.basement_planks_broken == false"
        )
        events.append({
            "event_id": f"{loc_id}__{oid}__success",
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
            "event_id": f"{loc_id}__{oid}__failure",
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

    if oid == "rotting_floorboards":
        examine_base = (
            f"action_id in ['search', 'inspect'] and target == '{oid}' "
            f"and location == '{loc_id}' and flags.floorboards_examined == false"
        )
        events.append({
            "event_id": f"{loc_id}__rotting_floorboards__examine_success",
            "priority": 70,
            "trigger_condition": f"{examine_base} and success_level >= 2",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": (
                    obj.get("success_message")
                    or "もろくなった床板の下に空間があることに気づいた。"
                    "踏み抜く／壊す（break / force / climb）で地階へ降りられそうだ。"
                ),
                "kp_instruction": (
                    "床板の下に地階があることを描写し、"
                    "次は break / force / climb で降りるか問いかけてください。"
                    "再 search やプッシュロールを勧めないこと。"
                ),
                "flag_updates": {"floorboards_examined": True},
                "mark_investigated": True,
                "san_check": {"required": False},
            },
        })
        events.append({
            "event_id": f"{loc_id}__rotting_floorboards__examine_failure",
            "priority": 70,
            "trigger_condition": f"{examine_base} and success_level <= 1",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": "もろくなった床板を調べたが、これといった手がかりは見つからなかった。",
                "kp_instruction": "調査失敗を描写し、プッシュまたは別対象を促してください。",
                "san_check": {"required": False},
            },
        })
        enter_base = (
            f"action_id in ['break', 'force', 'push', 'climb'] and target == '{oid}' "
            f"and location == '{loc_id}' and flags.in_basement == false"
        )
        events.append({
            "event_id": f"{loc_id}__rotting_floorboards__enter_success",
            "priority": 75,
            "trigger_condition": f"{enter_base} and success_level >= 2",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": (
                    "床板が砕け、チャペル地階（焼け落ちた祭壇下の保管庫側）へ降りた。"
                ),
                "kp_instruction": (
                    "地階へ降りた直後の暗く埃っぽい情景を描写し、"
                    "骸骨や棚など地階側の未調査対象を示唆してください。"
                    "通りへ戻るにはまず這い上がる必要があると伝えること。"
                ),
                "flag_updates": {
                    "in_basement": True,
                    "floorboards_examined": True,
                },
                "san_check": {"required": False},
            },
        })
        events.append({
            "event_id": f"{loc_id}__rotting_floorboards__enter_failure",
            "priority": 75,
            "trigger_condition": f"{enter_base} and success_level <= 1",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": "床板は軋んだが、まだ落ちずに踏みとどまった。",
                "kp_instruction": "地階へ降りられなかったことを描写し、再挑戦や別手段を促してください。",
                "san_check": {"required": False},
            },
        })
        climb_out = (
            f"action_id in ['climb', 'break', 'force', 'push'] and target == '{oid}' "
            f"and location == '{loc_id}' and flags.in_basement == true"
        )
        events.append({
            "event_id": f"{loc_id}__rotting_floorboards__climb_out_success",
            "priority": 75,
            "trigger_condition": f"{climb_out} and success_level >= 2",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": "崩れた床板の隙間から這い上がり、チャペル地上へ戻った。",
                "kp_instruction": "地上へ戻ったことを描写し、通りへ出るか他の地上対象を促してください。",
                "flag_updates": {"in_basement": False},
                "san_check": {"required": False},
            },
        })
        events.append({
            "event_id": f"{loc_id}__rotting_floorboards__climb_out_failure",
            "priority": 75,
            "trigger_condition": f"{climb_out} and success_level <= 1",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": "這い上がろうとしたが足を滑らせ、まだ地階に留まっている。",
                "kp_instruction": "這い上がりに失敗したことを描写し、再挑戦を促してください。",
                "san_check": {"required": False},
            },
        })
        return events

    if oid == "corbitt_knife":
        base = (
            f"action_id in ['search', 'inspect', 'use'] and target == '{oid}' "
            f"and location == '{loc_id}' and flags.knife_encountered == false"
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
                "flag_updates": {"has_corbitt_knife": False, "knife_encountered": True, "trigger_knife_attack": True},
                "object_state_updates": {
                    "corbitt_knife": {
                        "object_id": "corbitt_knife", "exists": True,
                        "status": "IN_COMBAT", "owner_id": "walter_corbitt",
                        "location_id": loc_id, "available": False, "destroyed": False,
                        "transition_path": ["AVAILABLE", "IN_COMBAT"],
                    }
                },
                "mark_investigated": True,
                "san_check": {"required": True, "value": "1D4", "source": "generic"},
                "combat_start": {
                    "enemies": ["corbitt_floating_dagger"],
                    "combat_goal": "ENEMY_DEFEATED",
                    "termination": {
                        "type": "ENEMY_INCAPACITATED",
                        "enemy_id": "corbitt_floating_dagger",
                    },
                    "trigger_event_id": f"{loc_id}__corbitt_knife__encounter",
                },
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
            "trigger_condition": f"{defeat_base} and flags.learned_corbitt_weakness == false and success_level >= 2",
            "action_type": "update_and_describe",
            "payload": {
                "system_log": "ウォルター・コービットの遺体が破壊され、屋敷の呪いが解けた。",
                "kp_instruction": "コービット討伐とシナリオクリアを劇的に描写して、セッションを締めくくってください。",
                "flag_updates": {"corbitt_defeated": True},
                "world_fact": {
                    "event": "SPECIAL_OBJECTIVE_COMPLETED",
                    "target": "corbitt_body",
                    "fact": "CORBITT_BODY_DESTROYED",
                },
                "human_readable_description": "コービットの遺体が破壊され、屋敷の呪いが解けた。",
                "resolution_reason": "SPECIAL_OBJECTIVE:CORBITT_BODY_DESTROYED",
                "narrative_fact_tags": ["CORBITT_BODY_DESTROYED", "HOUSE_CURSE_BROKEN"],
                "new_phase": "clear",
                "combat_end": True,
                "san_check": {"required": False},
            },
        })
        informed_defeat = copy.deepcopy(events[-1])
        informed_defeat["event_id"] = f"{loc_id}__corbitt_body__informed_defeat"
        informed_defeat["trigger_condition"] = (
            f"{defeat_base} and flags.learned_corbitt_weakness == true and success_level >= 2"
        )
        informed_defeat["payload"]["system_log"] = (
            "祭壇で知った弱点に従って遺体を清め、破壊した。"
            "ウォルター・コービットの力は断たれ、屋敷の呪いが解けた。"
        )
        events.append(informed_defeat)
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
    names = ["outline.json", "events.json", *LOC_FILES.keys()]
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
    event_overrides = _event_success_overrides(_load("events.json"))

    locations = {}
    event_triggers = []

    for fname, loc_id in LOC_FILES.items():
        loc = _load(fname)
        objects = _objects_to_dict(loc)
        connected = loc.get("connected_to", []) or []
        if loc_id == "introduction" and not connected:
            connected = loc.get("_unlockable_locations", []) or []
        exits = _build_exits(loc_id, connected, loc.get("exits"))

        loc_entry = {
            "name": loc.get("name", loc_id),
            "default_description": loc.get("default_description", ""),
            "connected_to": connected,
            "objects": objects,
            "exits": exits,
        }
        npcs_present = loc.get("npcs_present") or []
        if npcs_present:
            loc_entry["npcs_present"] = list(npcs_present)
        locations[loc_id] = loc_entry

        seen_oids = set()
        for oid, obj in objects.items():
            if oid in seen_oids:
                continue
            seen_oids.add(oid)
            if (loc_id, oid) in event_overrides:
                obj = copy.deepcopy(obj)
                obj.update(event_overrides[(loc_id, oid)])
                objects[oid] = obj
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
            "max_stagnation_turns": meta.get("max_stagnation_turns", 6),
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
    if outline.get("social_progress_rules"):
        scenario["social_progress_rules"] = list(outline.get("social_progress_rules") or [])
    _fill_exit_display_names(scenario["locations"])
    _apply_runtime_overlays(scenario)
    _merge_curated_fields_from_existing(scenario)
    _apply_runtime_overlays(scenario)  # overlay を最終優先
    return scenario


def _apply_runtime_overlays(scenario: dict) -> None:
    """再ビルドでも警察記録本文・キム配置が落ちないよう注入する。"""
    locs = scenario.setdefault("locations", {})
    exterior = locs.get("corbitt_exterior") or {}
    exterior_objects = exterior.get("objects") or {}
    # 屋外の窓には専用IDを使い、屋内の窓と衝突させない。
    exterior_objects.pop("ground_floor_windows", None)
    house = exterior_objects.get("corbitt_house")
    if isinstance(house, dict):
        house["investigated_flag"] = "corbitt_house_examined"
        house["usable_actions"] = ["search", "inspect", "use", "break", "force"]

    ground_floor = locs.get("corbitt_ground_floor") or {}
    for oid in ("basement_door", "hidden_passage"):
        obj = (ground_floor.get("objects") or {}).get(oid)
        if isinstance(obj, dict):
            obj["investigated_flag"] = "basement_door_examined"
            obj["usable_actions"] = ["search", "inspect", "break", "force", "push"]

    basement = locs.get("corbitt_basement") or {}
    return_exit = (basement.get("exits") or {}).get("corbitt_ground_floor")
    if isinstance(return_exit, dict):
        # condition は Python 式専用。技能ロールの説明文を置くと通行不能になる。
        return_exit.pop("condition", None)
    for oid in ("basement_planks", "wall_planks"):
        obj = (basement.get("objects") or {}).get(oid)
        if isinstance(obj, dict):
            obj["usable_actions"] = ["search", "inspect", "break", "force", "push"]
            obj["clue_flags_on_success"] = ["basement_planks_examined"]
            # This scenario intentionally uses the existing opposed-STR
            # resolver.  Make the choice data, rather than a runtime guess.
            obj["strength_check_type"] = "OPPOSED_STR_CHECK"

    flags = (scenario.get("initial_state") or {}).setdefault("flags", {})
    flags.setdefault("corbitt_house_examined", False)
    flags.setdefault("basement_door_examined", False)
    flags.setdefault("knife_encountered", False)
    flags.setdefault("object_states", {
        "corbitt_knife": {
            "object_id": "corbitt_knife", "exists": True,
            "status": "UNDISCOVERED", "owner_id": "walter_corbitt",
            "location_id": "corbitt_basement", "available": False, "destroyed": False,
        }
    })
    lib = locs.get("central_library")
    if isinstance(lib, dict) and "npcs_present" not in lib:
        lib["npcs_present"] = []

    hc = locs.get("higher_courts_police_station")
    if isinstance(hc, dict):
        objs = dict(hc.get("objects") or {})
        objs.pop("kim_deblanc", None)
        police = dict(objs.get("police_archives") or {"name": "保管されている記録"})
        police["player_handout"] = PLAYER_HANDOUT_8
        police["handout_text"] = PLAYER_HANDOUT_8
        police["success_message"] = PLAYER_HANDOUT_8
        police["clue_on_success"] = POLICE_ARCHIVES_CLUE
        police["reject_message"] = POLICE_ARCHIVES_INVESTIGATED_REJECT
        police["investigated_reject_message"] = POLICE_ARCHIVES_INVESTIGATED_REJECT
        police["investigated_flag"] = "higher_courts_records_accessed"
        police.setdefault(
            "required_skill",
            ["信用", "言いくるめ", "説得", "隠密", "鍵開け", "法律"],
        )
        police.setdefault("usable_actions", ["search", "inspect"])
        objs["police_archives"] = police
        hc["objects"] = objs
        hc["npcs_present"] = ["kim_deblanc"]

    flags.setdefault("kim_deblanc_interacted", False)

    triggers = scenario.get("event_triggers") or []
    scenario["event_triggers"] = [
        t for t in triggers
        if "kim_deblanc" not in str((t or {}).get("event_id") or "")
        and not str((t or {}).get("event_id") or "").startswith("corbitt_exterior__ground_floor_windows__")
    ]


def _merge_curated_fields_from_existing(scenario: dict) -> None:
    """既存 scenario_corbitt.json の手詰め本文・社交ルールを可能な範囲で引き継ぐ。"""
    if not OUT_FILE.is_file():
        return
    try:
        old = json.loads(OUT_FILE.read_text(encoding="utf-8"))
    except Exception:
        return
    if not scenario.get("social_progress_rules") and old.get("social_progress_rules"):
        scenario["social_progress_rules"] = list(old.get("social_progress_rules") or [])
    old_locs = old.get("locations") or {}
    for loc_id, loc in (scenario.get("locations") or {}).items():
        old_loc = old_locs.get(loc_id) or {}
        if "npcs_present" in old_loc and "npcs_present" not in loc:
            loc["npcs_present"] = list(old_loc.get("npcs_present") or [])
        for oid, obj in (loc.get("objects") or {}).items():
            old_obj = (old_loc.get("objects") or {}).get(oid) or {}
            for key in (
                "success_message", "clue_on_success", "player_handout",
                "handout_text", "reject_message", "investigated_reject_message",
                "description",
            ):
                if old_obj.get(key) and not obj.get(key):
                    obj[key] = old_obj[key]


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
