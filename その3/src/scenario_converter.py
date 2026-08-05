#!/usr/bin/env python3
"""
自然言語シナリオテキストを GenericScenarioSchema (JSON) へ変換するコンバーター。

使用例:
  python scenario_converter.py scenario.txt -o datasets/my_scenario.json
  python scenario_converter.py --stdin -o out.json < memo.txt
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from schema_definition import GenericScenarioSchema

_LOCAL_DIR = Path(__file__).resolve().parent / ".local"
_GEMINI_ENV_FILE = _LOCAL_DIR / "gemini.env"
_STAGED_THRESHOLD_CHARS = 10_000
_SCENE_HEADER_RE = re.compile(r"^Location\s*(\d+)\s*:\s*(.+)$", re.MULTILINE)


_PLACEHOLDER_KEY_MARKERS = (
    "ここに",
    "your_api_key",
    "YOUR_API_KEY",
    "paste",
    "example",
)


def _is_placeholder_api_key(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return True
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in _PLACEHOLDER_KEY_MARKERS)


def _load_gemini_local_env():
    """src/.local/gemini.env から Gemini 用の環境変数だけを読み込む（TRPG本体とは分離）。"""
    env_file = _GEMINI_ENV_FILE
    if not env_file.is_file():
        example_file = _LOCAL_DIR / "gemini.env.example"
        if example_file.is_file():
            sample = example_file.read_text(encoding="utf-8-sig")
            if "GOOGLE_API_KEY=" in sample or "GEMINI_API_KEY=" in sample:
                for line in sample.splitlines():
                    if line.strip().startswith(("GOOGLE_API_KEY=", "GEMINI_API_KEY=")):
                        _, _, value = line.partition("=")
                        if value.strip() and not _is_placeholder_api_key(value):
                            raise RuntimeError(
                                "APIキーが gemini.env.example に書かれています。"
                                f" {env_file} を作成して、そちらへキーを移してください。"
                                " （例: copy .local\\gemini.env.example .local\\gemini.env）"
                            )
        return

    for line in env_file.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if not key or not value or _is_placeholder_api_key(value):
            continue
        if key not in os.environ:
            os.environ[key] = value


def _sanitize_schema_for_gemini(schema):
    """Gemini Developer API が拒否する JSON Schema キーを再帰的に除去する。"""
    unsupported_keys = frozenset({"additionalProperties", "$schema"})
    if isinstance(schema, dict):
        cleaned = {}
        for key, value in schema.items():
            if key in unsupported_keys:
                continue
            cleaned[key] = _sanitize_schema_for_gemini(value)
        return cleaned
    if isinstance(schema, list):
        return [_sanitize_schema_for_gemini(item) for item in schema]
    return schema


CONVERTER_SYSTEM_PROMPT = """あなたはクトゥルフ神話TRPG（第7版）シナリオ設計の専門家です。
ユーザーが提供する自然言語のシナリオ資料を、汎用イベント駆動 JSON スキーマ（GenericScenarioSchema）に厳密に変換してください。

【コンバート原則（必須）】
1. ゾンビループ防止:
   - すべての調査可能オブジェクトに `investigated_flag`（例: "desk_investigated"）を必ず付与する。
   - 既読ブロック用の `reject_message`（プレイヤー向けシステムメッセージ）を必ず日本語で生成する。
2. イベント駆動への分離:
   - 罠・ダメージ・NPC遭遇・SANチェックは直列ナレーションではなく `event_triggers` に切り出す。
   - プレイヤーの行動（action_types, target_object, location）をトリガー条件に紐づける。
3. 条件式の抽象化:
   - 複雑な条件は `flags.<フラグ名> == true` のような Python 互換の単純式にする（`global_states.flags` も可）。
   - `custom_eval` / `trigger_condition` には比較・論理演算のみ（関数呼び出し禁止、len() のみ可）。
4. 移動（exits）:
   - 各出口に `condition` または `requires_flag` と `reject_message` を設定する。
   - exits のキーおよび connected_to は、必ず `locations` に存在するロケーションIDのみを使う。
5. payloads:
   - SANチェックは `action_type: "force_san_check"` + parameters
   - フラグ更新は `action_type: "set_flag"` + parameters: {flag, value}
   - 描写は `action_type: "update_and_describe"` + parameters: {system_log, kp_instruction}
   - 拒否は `action_type: "system_reject"`
6. 難易度（difficulty）— 第7版準拠:
   - オブジェクトや required_check の難易度は `"regular"` / `"hard"` / `"extreme"` のみを使う。
   - 日本語で書いてある場合も最終JSONでは必ず上記英語キーに正規化する（通常→regular, 困難→hard, 極限→extreme）。
7. 成功度（success_level）— 新スケール（必須・厳守）:
   - 0 = ファンブル / 1 = 失敗 / 2 = レギュラー成功 / 3 = ハード成功 / 4 = イクストリーム成功 / 5 = クリティカル
   - 「成功したとき」の条件は必ず `success_level >= 2` と書く（`>= 1` は旧式・禁止）。
   - 「失敗したとき」の条件は必ず `success_level <= 1` と書く（`== 0` のみは旧式・禁止）。
   - ハード成功が必要な行為は `success_level >= 3`、イクストリームは `success_level >= 4`。
   - イベント例:
     - 調査成功: `action_id in ['search','inspect'] and target == 'desk' and location == 'study' and flags.desk_investigated == false and success_level >= 2`
     - 調査失敗: `... and success_level <= 1`
8. 識別子の一意性:
   - `event_id` はシナリオ全体で一意。
   - `object_id` も可能な限りロケーション横断で一意にする（同じ名前の机でも room_a_desk / room_b_desk のように分ける）。
9. フラグ整合:
   - 条件式や requires_flag で参照するフラグは、必ずどこかで定義・更新する（initial_state.flags / investigated_flag / flag_updates）。

【出力】
- 有効な JSON オブジェクト1個のみ（GenericScenarioSchema 準拠）
- 解説・マークダウン・コードフェンスは禁止
- locations は必ず1件以上、主要な調査場所を漏れなく含める
- 各 location には調査可能な objects を適宜、exits / connected_to を含める
- event_triggers は SANチェック・技能ロール・フラグ更新・移動条件を十分に含める
"""

# LLM向け: 難易度・成功度スケールだけの短い参照カード（追加 system / user 注入用）
COC7_RULES_REFERENCE_PROMPT = """【CoC7 ルール参照カード（変換時に必ず遵守）】
difficulty: "regular" | "hard" | "extreme"
success_level 新スケール:
  0=ファンブル, 1=失敗, 2=レギュラー成功, 3=ハード成功, 4=イクストリーム成功, 5=クリティカル
条件式の定石:
  成功 → success_level >= 2
  失敗 → success_level <= 1
  ハード成功が必要 → success_level >= 3
  イクストリーム成功が必要 → success_level >= 4
旧式（success_level >= 1 / success_level == 0）は出力禁止。
"""

OUTLINE_SYSTEM_PROMPT = """あなたはTRPGシナリオ設計の専門家です。
長大なシナリオ資料から、ゲームエンジン用の骨格（アウトライン）だけを JSON で抽出してください。

【必須フィールド】
- scenario_meta: { title, background, summary, initial_phase, initial_location }
- initial_state: { current_phase, location, flags }
- location_plan: 配列（各要素は id, name, scene_nums のみ。notes は書かない）

【location_plan のルール】
- 最低8件以上
- id は英小文字とアンダースコアのみ（例: boston_globe, corbitt_basement）
- scene_nums は文字列配列（例: ["2"]）
- コービット屋敷（Location 9）は corbitt_exterior / corbitt_ground_floor / corbitt_upper_floor / corbitt_basement に分割

【JSON出力の厳守】
- 前置き・解説・コードフェンス禁止
- 有効な JSON オブジェクト1個のみ
- 文字列内の改行は \\n でエスケープ
- 末尾カンマ禁止
- event_hints や locations の詳細は含めない
"""

OUTLINE_JSON_EXAMPLE = """{
  "scenario_meta": {
    "title": "シナリオ名",
    "background": "背景",
    "summary": "あらすじ",
    "initial_phase": "introduction",
    "initial_location": "introduction"
  },
  "initial_state": {
    "current_phase": "introduction",
    "location": "introduction",
    "flags": {}
  },
  "location_plan": [
    { "id": "introduction", "name": "導入", "scene_nums": ["1"] },
    { "id": "boston_globe", "name": "ボストン・グローブ", "scene_nums": ["2"] }
  ]
}"""

LOCATION_SYSTEM_PROMPT = """あなたはTRPGシナリオ設計の専門家です。
与えられた1つの場所について、ゲームエンジン用 location オブジェクトを JSON で生成してください。

【必須】
- name, default_description, connected_to, objects, exits
- 調査可能オブジェクトには investigated_flag と reject_message を付与
- exits には condition または requires_flag と reject_message
- objects は最低2件、シナリオ本文に基づく具体的な手がかりを含める

【重要: 辞書形式】
- objects と exits は配列禁止。ID をキーとするオブジェクト（辞書）で書く
- 例: "objects": { "desk": { "name": "机", "description": "..." } }
- 例: "exits": { "hallway": { "name": "廊下へ", "requires_flag": "door_opened" } }

出力は { "location_id": "...", "location": { ... } } の形のみ。

【JSON出力の厳守】
- 前置き・解説・コードフェンス禁止
- 有効な JSON のみ。文字列内改行は \\n。末尾カンマ禁止
"""

EVENTS_SYSTEM_PROMPT = """あなたはTRPGシナリオ設計の専門家です。
シナリオ骨格と場所一覧に基づき、event_triggers 配列だけを JSON で生成してください。

【必須】
- 各 trigger: event_id, priority, location, target_object, action_types, payloads
- priority は整数のみ（0=通常, 50=中, 80=高, 100=最重要）。文字列は使わない
- payloads の action_type は次のいずれかのみ使用: system_intercept_roll, force_san_check, set_flag, apply_damage, change_phase, change_location, update_and_describe, system_reject, mark_investigated
- 移動解放は system_unlock_location ではなく set_flag（出口用フラグ）または change_location を使う
- SANチェック、技能ロール、調査完了フラグ、移動解放をカバーする
- 最低10件以上

出力は { "event_triggers": [ ... ] } の形のみ。

【JSON出力の厳守】
- 前置き・解説・コードフェンス禁止
- 有効な JSON のみ。文字列内改行は \\n。末尾カンマ禁止
"""


def _get_reference_scenario_excerpt() -> str:
    path = Path(__file__).resolve().parent / "scenario.json"
    if not path.is_file():
        return ""
    data = json.loads(path.read_text(encoding="utf-8"))
    loc_ids = list((data.get("locations") or {}).keys())[:1]
    excerpt = {
        "scenario_meta": data.get("scenario_meta"),
        "initial_state": data.get("initial_state"),
        "locations": {loc_id: data["locations"][loc_id] for loc_id in loc_ids},
        "event_triggers": (data.get("event_triggers") or [])[:2],
    }
    return json.dumps(excerpt, ensure_ascii=False, indent=2)


def _split_scenario_scenes(text: str) -> List[Dict[str, str]]:
    matches = list(_SCENE_HEADER_RE.finditer(text))
    if not matches:
        return [{"scene_num": "0", "title": "main", "content": text.strip()}]

    scenes = []
    for index, match in enumerate(matches):
        start = match.start()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        scenes.append({
            "scene_num": match.group(1),
            "title": match.group(2).strip(),
            "content": text[start:end].strip(),
        })
    return scenes


def _truncate_middle(text: str, max_chars: int = 12_000) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    head = max_chars * 2 // 3
    tail = max_chars - head
    return (
        f"{text[:head]}\n\n"
        f"...[中略: {len(text) - head - tail} 文字]...\n\n"
        f"{text[-tail:]}"
    )


def _summarize_scenes_for_outline(scenes: List[Dict[str, str]], max_chars_per_scene: int = 1500) -> str:
    parts = []
    for scene in scenes:
        excerpt = _truncate_middle(scene["content"], max_chars_per_scene)
        parts.append(
            f"### Location {scene['scene_num']}: {scene['title']}\n{excerpt}"
        )
    return "\n\n".join(parts)


def _scene_content_for_plan(scenes: List[Dict[str, str]], scene_nums: List[str]) -> str:
    by_num = {scene["scene_num"]: scene for scene in scenes}
    chunks = []
    for num in scene_nums:
        scene = by_num.get(str(num))
        if scene:
            chunks.append(f"### Location {scene['scene_num']}: {scene['title']}\n{scene['content']}")
    return _truncate_middle("\n\n".join(chunks), 14_000)


def _ensure_scenario_completeness(scenario: GenericScenarioSchema) -> None:
    loc_count = len(scenario.locations or {})
    event_count = len(scenario.event_triggers or [])
    if loc_count == 0:
        raise ValueError(
            "変換結果に locations が空です。"
            " 長いシナリオは --mode staged を使うか、入力を場面ごとに分割してください。"
        )
    if event_count == 0:
        print("[scenario_converter] 警告: event_triggers が空です。手動で追記を検討してください。")
    if loc_count < 3:
        print(f"[scenario_converter] 警告: locations が {loc_count} 件のみです。内容が不足している可能性があります。")


def _slugify_location_id(text: str, fallback: str = "location") -> str:
    ascii_text = text.encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^\w\s-]", "", ascii_text).strip().lower()
    slug = re.sub(r"[\s-]+", "_", slug)
    slug = re.sub(r"_+", "_", slug).strip("_")
    if slug:
        return slug
    digits = re.sub(r"\D", "", text)
    return f"{fallback}_{digits}" if digits else fallback


_PRIORITY_MAP = {
    "critical": 100,
    "highest": 100,
    "high": 80,
    "medium": 50,
    "normal": 0,
    "low": 20,
}


def _normalize_priority(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        text = value.strip().lower()
        if text in _PRIORITY_MAP:
            return _PRIORITY_MAP[text]
        try:
            return int(text)
        except ValueError:
            return 0
    return 0


def _list_to_id_dict(items: Any, default_prefix: str) -> Dict[str, Any]:
    if isinstance(items, dict):
        return dict(items)
    if not isinstance(items, list):
        return {}

    result: Dict[str, Any] = {}
    used_ids = set()
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        entry = dict(item)
        key = (
            entry.pop("id", None)
            or entry.get("to")
            or entry.get("target")
            or entry.get("destination")
            or _slugify_location_id(str(entry.get("name", "")), f"{default_prefix}_{index + 1}")
        )
        key = str(key)
        if key in used_ids:
            key = f"{key}_{index + 1}"
        used_ids.add(key)
        entry.pop("to", None)
        entry.pop("target", None)
        entry.pop("destination", None)
        result[key] = entry
    return result


def _normalize_object_entry(obj: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(obj)
    if "desc" in normalized and "description" not in normalized:
        normalized["description"] = normalized.pop("desc")
    if not normalized.get("investigated_flag"):
        label = normalized.get("name") or normalized.get("id") or "object"
        normalized["investigated_flag"] = f"{_slugify_location_id(str(label), 'object')}_investigated"
    normalized.setdefault(
        "reject_message",
        "【システムブロック】この対象は既に調査済みです。別の手がかりを探してください。",
    )
    normalized.setdefault("usable_actions", ["search", "inspect"])
    return normalized


def _normalize_exit_entry(exit_item: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(exit_item)
    if normalized.get("reject_message") in (None, ""):
        normalized["reject_message"] = "【システムブロック】その方向へは進めません。"
    return normalized


def _normalize_location_body(location: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(location)
    objects = _list_to_id_dict(normalized.get("objects"), "object")
    exits = _list_to_id_dict(normalized.get("exits"), "exit")
    normalized["objects"] = {
        key: _normalize_object_entry(value)
        for key, value in objects.items()
        if isinstance(value, dict)
    }
    normalized["exits"] = {
        key: _normalize_exit_entry(value)
        for key, value in exits.items()
        if isinstance(value, dict)
    }
    connected = normalized.get("connected_to")
    if not isinstance(connected, list):
        if isinstance(connected, str) and connected:
            normalized["connected_to"] = [connected]
        else:
            normalized["connected_to"] = list(exits.keys())
    return normalized


_VALID_PAYLOAD_ACTION_TYPES = frozenset({
    "system_intercept_roll",
    "force_san_check",
    "set_flag",
    "apply_damage",
    "change_phase",
    "change_location",
    "update_and_describe",
    "system_reject",
    "mark_investigated",
})

_PAYLOAD_ACTION_TYPE_ALIASES = {
    "system_unlock_location": "set_flag",
    "unlock_location": "change_location",
    "unlock_exit": "set_flag",
    "unlock": "set_flag",
    "system_roll": "system_intercept_roll",
    "skill_roll": "system_intercept_roll",
    "roll": "system_intercept_roll",
    "san_check": "force_san_check",
    "describe": "update_and_describe",
    "narration": "update_and_describe",
    "reject": "system_reject",
    "investigated": "mark_investigated",
    "mark_investigated_flag": "mark_investigated",
    "damage": "apply_damage",
    "change_phase_to": "change_phase",
}


def _coerce_payload_action_type(action_type: str, parameters: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
    params = dict(parameters or {})
    raw = str(action_type or "").strip()
    lowered = raw.lower()

    if lowered == "system_unlock_location":
        if params.get("location") or params.get("new_location") or params.get("target_location"):
            location = params.get("location") or params.get("new_location") or params.get("target_location")
            return "change_location", {**params, "location": location}
        flag = (
            params.get("flag")
            or params.get("requires_flag")
            or params.get("exit_id")
            or params.get("target")
            or "exit_unlocked"
        )
        coerced = dict(params)
        coerced["flag"] = flag
        coerced.setdefault("value", True)
        return "set_flag", coerced

    if lowered in _VALID_PAYLOAD_ACTION_TYPES:
        return lowered, params

    mapped = _PAYLOAD_ACTION_TYPE_ALIASES.get(lowered)
    if mapped == "change_location":
        location = params.get("location") or params.get("new_location") or params.get("target_location")
        if location:
            return "change_location", {**params, "location": location}
        return "set_flag", params
    if mapped:
        return mapped, params

    # 未知の action_type は描写更新にフォールバック
    if raw:
        params.setdefault("kp_instruction", params.get("kp_instruction") or f"（変換: {raw}）")
    return "update_and_describe", params


def _normalize_payload_element(element: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(element, dict):
        return None
    entry = dict(element)
    action_type, parameters = _coerce_payload_action_type(
        str(entry.get("action_type") or ""),
        dict(entry.get("parameters") or {}),
    )
    entry["action_type"] = action_type
    entry["parameters"] = parameters
    for key in ("on_success", "on_failure"):
        children = entry.get(key) or []
        if isinstance(children, list):
            entry[key] = [
                normalized
                for child in children
                if (normalized := _normalize_payload_element(child)) is not None
            ]
    return entry


def _normalize_event_triggers(triggers: Any) -> List[Dict[str, Any]]:
    if not isinstance(triggers, list):
        return []
    normalized: List[Dict[str, Any]] = []
    for trigger in triggers:
        if not isinstance(trigger, dict):
            continue
        entry = dict(trigger)
        entry["priority"] = _normalize_priority(entry.get("priority", 0))
        action_types = entry.get("action_types")
        if isinstance(action_types, str):
            entry["action_types"] = [action_types]
        payloads = entry.get("payloads") or []
        if isinstance(payloads, list):
            entry["payloads"] = [
                payload_item
                for payload in payloads
                if (payload_item := _normalize_payload_element(payload)) is not None
            ]
        normalized.append(entry)
    return normalized


def _normalize_scenario_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    normalized = dict(payload)
    locations: Dict[str, Any] = {}
    for loc_id, loc in (normalized.get("locations") or {}).items():
        if isinstance(loc, dict):
            locations[str(loc_id)] = _normalize_location_body(loc)
    normalized["locations"] = locations
    normalized["event_triggers"] = _normalize_event_triggers(normalized.get("event_triggers"))
    return normalized


def _extract_balanced_json_object(text: str) -> str:
    """括弧の対応をたどって最初の JSON オブジェクトを切り出す。"""
    text = (text or "").strip()
    if text.startswith("```json"):
        text = text[7:].strip()
    elif text.startswith("```"):
        text = text[3:].strip()
    if text.endswith("```"):
        text = text[:-3].strip()

    start = text.find("{")
    if start < 0:
        return text

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return text[start:]


def _repair_json_text(text: str) -> str:
    """よくある LLM JSON の軽微な構文エラーを修復する。"""
    repaired = text.replace("\ufeff", "")
    repaired = repaired.replace("“", '"').replace("”", '"').replace("’", "'")
    repaired = re.sub(r",\s*([}\]])", r"\1", repaired)
    return repaired


JSON_REPAIR_SYSTEM_PROMPT = (
    "あなたはJSON修復ツールです。"
    "壊れたJSONを有効なJSONオブジェクト1個だけに直して返してください。"
    "解説・コードフェンスは禁止。"
)


def _parse_llm_json(
    raw_text: str,
    *,
    label: str,
    model: Optional[str] = None,
    max_retries: int = 2,
) -> dict:
    candidate = raw_text or ""
    last_exc: Optional[json.JSONDecodeError] = None

    for attempt in range(max_retries + 1):
        json_text = _repair_json_text(_extract_balanced_json_object(candidate))
        try:
            parsed = json.loads(json_text)
            if not isinstance(parsed, dict):
                raise json.JSONDecodeError(f"{label} のJSONがオブジェクトではありません", json_text, 0)
            return parsed
        except json.JSONDecodeError as exc:
            last_exc = exc
            if attempt >= max_retries:
                break
            print(f"[scenario_converter] {label} のJSON修復を試行 ({attempt + 1}/{max_retries})...")
            candidate = _call_gemini_json(
                JSON_REPAIR_SYSTEM_PROMPT,
                (
                    f"以下のJSONを修復してください。label={label}\n"
                    f"エラー: {exc}\n\n"
                    f"{candidate}"
                ),
                model=model,
            )

    snippet = _repair_json_text(_extract_balanced_json_object(candidate))
    preview = snippet[max(0, (last_exc.pos or 0) - 80):(last_exc.pos or 0) + 80] if last_exc else snippet[:160]
    raise ValueError(
        f"{label} のJSON解析に失敗しました: {last_exc}\n"
        f"問題付近: {preview!r}"
    ) from last_exc


def _build_fallback_outline(scenes: List[Dict[str, str]], keeper_intro: str) -> dict:
    """LLM アウトライン失敗時の決定的な骨格。"""
    title_match = re.search(r"粘土板に描かれた恐怖|悪霊の家|The Haunting", keeper_intro)
    title = title_match.group(0) if title_match else "変換シナリオ"

    location_plan: List[Dict[str, Any]] = []
    for scene in scenes:
        if scene["scene_num"] == "9":
            for loc_id, loc_name in (
                ("corbitt_exterior", "コービット屋敷・外観"),
                ("corbitt_ground_floor", "コービット屋敷・1階"),
                ("corbitt_upper_floor", "コービット屋敷・2階"),
                ("corbitt_basement", "コービット屋敷・地階"),
            ):
                location_plan.append({
                    "id": loc_id,
                    "name": loc_name,
                    "scene_nums": ["9"],
                })
            continue
        location_plan.append({
            "id": _slugify_location_id(scene["title"], f"scene_{scene['scene_num']}"),
            "name": scene["title"],
            "scene_nums": [scene["scene_num"]],
        })

    first_id = location_plan[0]["id"] if location_plan else "introduction"
    background = _truncate_middle(keeper_intro, 800)
    return {
        "scenario_meta": {
            "title": title,
            "background": background,
            "summary": "自然言語シナリオから自動生成された骨格です。",
            "initial_phase": "introduction",
            "initial_location": first_id,
        },
        "initial_state": {
            "current_phase": "introduction",
            "location": first_id,
            "flags": {},
        },
        "location_plan": location_plan,
    }


def _extract_json_object(text: str) -> str:
    return _extract_balanced_json_object(text)


def _call_openai_compatible(prompt: str, *, schema_hint: dict, model: Optional[str] = None) -> str:
    from main import _call_chat_completion, get_llm_config

    cfg = get_llm_config()
    model = model or cfg.get("kp_model")
    schema_text = json.dumps(schema_hint, ensure_ascii=False, indent=2)
    user_prompt = (
        f"{prompt.strip()}\n\n"
        "【JSONスキーマ参考】\n"
        f"{schema_text}\n\n"
        "上記スキーマに従った GenericScenarioSchema JSON のみを出力してください。"
    )
    messages = [
        {
            "role": "system",
            "content": f"{CONVERTER_SYSTEM_PROMPT}\n\n{COC7_RULES_REFERENCE_PROMPT}",
        },
        {"role": "user", "content": user_prompt},
    ]
    return _call_chat_completion(
        messages,
        model=model,
        temperature=0.2,
        max_retries=2,
        json_mode=True,
    )


def _is_retryable_gemini_error(exc: Exception) -> bool:
    """503/429/500 等、時間をおけば回復する一時的エラーか判定する。"""
    status = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    if status in (429, 500, 502, 503, 504):
        return True
    text = str(exc).lower()
    retry_markers = (
        "503",
        "429",
        "unavailable",
        "high demand",
        "overloaded",
        "deadline",
        "timeout",
        "temporarily",
        "try again",
        "rate limit",
        "resource_exhausted",
    )
    return any(marker in text for marker in retry_markers)


def _call_gemini_json(
    system_prompt: str,
    user_prompt: str,
    *,
    model: Optional[str] = None,
    response_schema: Optional[dict] = None,
    max_retries: int = 5,
) -> str:
    try:
        from google import genai
        from google.genai import types
    except ImportError as exc:
        raise RuntimeError("google-genai が未インストールです: pip install google-genai") from exc

    _load_gemini_local_env()
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY または GEMINI_API_KEY が未設定です。"
            f" {_GEMINI_ENV_FILE} を作成するか、環境変数を設定してください。"
            " （例: copy .local/gemini.env.example .local/gemini.env）"
        )

    client = genai.Client(api_key=api_key)
    model = model or os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    config_kwargs = {
        "response_mime_type": "application/json",
        "temperature": 0.2,
    }
    if response_schema:
        config_kwargs["response_schema"] = _sanitize_schema_for_gemini(response_schema)

    last_exc: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            response = client.models.generate_content(
                model=model,
                contents=[
                    types.Content(
                        role="user",
                        parts=[types.Part(text=f"{system_prompt}\n\n{user_prompt}")],
                    )
                ],
                config=types.GenerateContentConfig(**config_kwargs),
            )
            return (response.text or "").strip()
        except Exception as exc:
            last_exc = exc
            if attempt >= max_retries or not _is_retryable_gemini_error(exc):
                raise
            wait = min(60.0, 2.0 * (2 ** attempt)) + random.uniform(0, 1.0)
            print(
                f"[scenario_converter] Gemini 一時エラー（{attempt + 1}/{max_retries}）: "
                f"{str(exc)[:80]}... {wait:.1f}秒待機して再試行"
            )
            time.sleep(wait)

    if last_exc:
        raise last_exc
    raise RuntimeError("Gemini 呼び出しに失敗しました。")


def _call_google_genai(prompt: str, *, response_schema: dict, model: Optional[str] = None) -> str:
    return _call_gemini_json(
        f"{CONVERTER_SYSTEM_PROMPT}\n\n{COC7_RULES_REFERENCE_PROMPT}",
        prompt,
        model=model,
        response_schema=response_schema,
    )


def _convert_scenario_single(
    source_text: str,
    *,
    provider: str,
    model: Optional[str] = None,
) -> GenericScenarioSchema:
    schema_hint = GenericScenarioSchema.model_json_schema()
    reference = _get_reference_scenario_excerpt()
    prompt = source_text.strip()
    if reference:
        prompt = (
            f"{prompt}\n\n"
            "【出力例（構造の参考。内容は入力シナリオに合わせること）】\n"
            f"{reference}"
        )

    raw_json = ""
    if provider in ("auto", "google", "gemini"):
        try:
            raw_json = _call_google_genai(
                prompt,
                response_schema=schema_hint,
                model=model,
            )
        except Exception as exc:
            if provider == "google":
                raise
            print(f"[scenario_converter] Gemini 変換失敗、OpenAI互換へフォールバック: {exc}")

    if not raw_json:
        raw_json = _call_openai_compatible(
            prompt,
            schema_hint=schema_hint,
            model=model,
        )

    parsed = _parse_llm_json(raw_json, label="単発変換", model=model)
    return GenericScenarioSchema.model_validate(_normalize_scenario_payload(parsed))


def _get_staged_cache_dir(source_text: str) -> Path:
    digest = hashlib.md5(source_text.encode("utf-8")).hexdigest()[:12]
    cache_dir = _LOCAL_DIR / ".staged_cache" / digest
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def _convert_scenario_staged(
    source_text: str,
    *,
    model: Optional[str] = None,
) -> GenericScenarioSchema:
    scenes = _split_scenario_scenes(source_text)
    keeper_intro = _truncate_middle(source_text[:4000], 4000)
    cache_dir = _get_staged_cache_dir(source_text)
    outline_cache = cache_dir / "outline.json"

    outline_prompt = (
        f"【出力フォーマット例】\n{OUTLINE_JSON_EXAMPLE}\n\n"
        f"【キーパー向け導入部】\n{keeper_intro}\n\n"
        f"【場面一覧（要約）】\n{_summarize_scenes_for_outline(scenes)}"
    )
    print(f"[scenario_converter] 多段変換 1/3: アウトライン抽出（{len(scenes)} 場面）...")
    if outline_cache.is_file():
        print("  （キャッシュからアウトラインを再利用）")
        outline = json.loads(outline_cache.read_text(encoding="utf-8"))
    else:
        try:
            outline_raw = _call_gemini_json(OUTLINE_SYSTEM_PROMPT, outline_prompt, model=model)
            outline = _parse_llm_json(outline_raw, label="アウトライン", model=model)
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"[scenario_converter] アウトライン生成失敗、フォールバック骨格を使用: {exc}")
            outline = _build_fallback_outline(scenes, keeper_intro)
        outline_cache.write_text(
            json.dumps(outline, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    scenario_meta = outline.get("scenario_meta") or {}
    initial_state = outline.get("initial_state") or {}
    location_plan = outline.get("location_plan") or []
    if not location_plan:
        print("[scenario_converter] location_plan が空のためフォールバック骨格を使用")
        outline = _build_fallback_outline(scenes, keeper_intro)
        scenario_meta = outline.get("scenario_meta") or {}
        initial_state = outline.get("initial_state") or {}
        location_plan = outline.get("location_plan") or []

    locations: Dict[str, Any] = {}
    print(f"[scenario_converter] 多段変換 2/3: 場所詳細（{len(location_plan)} 件）...")
    for index, plan in enumerate(location_plan, start=1):
        loc_id = str(plan.get("id") or f"location_{index}")
        loc_cache = cache_dir / f"loc_{index:02d}_{_slugify_location_id(loc_id)}.json"
        if loc_cache.is_file():
            print(f"  - ({index}/{len(location_plan)}) {loc_id} （キャッシュ再利用）")
            locations[loc_id] = json.loads(loc_cache.read_text(encoding="utf-8"))
            continue

        scene_nums = [str(n) for n in (plan.get("scene_nums") or [])]
        scene_text = _scene_content_for_plan(scenes, scene_nums)
        location_prompt = (
            f"【場所ID】{loc_id}\n"
            f"【表示名】{plan.get('name', loc_id)}\n"
            f"【設計メモ】{plan.get('notes', '')}\n\n"
            f"【関連シナリオ本文】\n{scene_text}\n\n"
            f"【接続候補】{json.dumps([p.get('id') for p in location_plan], ensure_ascii=False)}"
        )
        print(f"  - ({index}/{len(location_plan)}) {loc_id}")
        try:
            loc_raw = _call_gemini_json(LOCATION_SYSTEM_PROMPT, location_prompt, model=model)
            loc_parsed = _parse_llm_json(loc_raw, label=f"場所:{loc_id}", model=model)
        except Exception as exc:
            print(f"    警告: {loc_id} の詳細生成に失敗 ({exc})")
            if loc_cache.is_file():
                loc_cache.unlink()
            continue
        location_body = loc_parsed.get("location") or loc_parsed
        if isinstance(location_body, dict) and "name" in location_body:
            normalized_loc = _normalize_location_body(location_body)
            locations[loc_id] = normalized_loc
            loc_cache.write_text(
                json.dumps(normalized_loc, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        else:
            print(f"    警告: {loc_id} の詳細生成に失敗、スキップ")

    if not locations:
        raise ValueError("場所詳細の生成にすべて失敗しました。")

    print("[scenario_converter] 多段変換 3/3: event_triggers 生成...")
    events_cache = cache_dir / "events.json"
    if events_cache.is_file():
        print("  （キャッシュから event_triggers を再利用）")
        event_triggers = json.loads(events_cache.read_text(encoding="utf-8"))
        event_triggers = _normalize_event_triggers(event_triggers)
    else:
        events_prompt = (
            f"【アウトライン】\n{json.dumps(outline, ensure_ascii=False, indent=2)}\n\n"
            f"【生成済み locations の ID 一覧】\n{json.dumps(list(locations.keys()), ensure_ascii=False)}"
        )
        try:
            events_raw = _call_gemini_json(EVENTS_SYSTEM_PROMPT, events_prompt, model=model)
            events_parsed = _parse_llm_json(events_raw, label="event_triggers", model=model)
            event_triggers = events_parsed.get("event_triggers") or []
            event_triggers = _normalize_event_triggers(event_triggers)
            events_cache.write_text(
                json.dumps(event_triggers, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            print(f"[scenario_converter] 警告: event_triggers 生成失敗 ({exc})")
            if events_cache.is_file():
                events_cache.unlink()
            event_triggers = []

    scenario = GenericScenarioSchema.model_validate(_normalize_scenario_payload({
        "scenario_meta": scenario_meta,
        "initial_state": initial_state,
        "locations": locations,
        "event_triggers": event_triggers,
    }))
    return scenario


def convert_scenario_text(
    source_text: str,
    *,
    provider: str = "auto",
    model: Optional[str] = None,
    mode: str = "auto",
) -> GenericScenarioSchema:
    """自然言語シナリオを GenericScenarioSchema に変換する。"""
    if not str(source_text or "").strip():
        raise ValueError("変換元テキストが空です")

    provider = (provider or "auto").lower()
    mode = (mode or "auto").lower()
    use_staged = mode == "staged" or (
        mode == "auto" and len(source_text) >= _STAGED_THRESHOLD_CHARS
    )

    if use_staged:
        if provider not in ("auto", "google", "gemini"):
            raise ValueError("多段変換（--mode staged）は現在 Gemini のみ対応しています。")
        print(
            f"[scenario_converter] 長文のため多段変換を使用します"
            f"（{len(source_text)} 文字 / 閾値 {_STAGED_THRESHOLD_CHARS}）"
        )
        scenario = _convert_scenario_staged(source_text, model=model)
        provider_label = "google-staged"
    else:
        scenario = _convert_scenario_single(
            source_text,
            provider=provider,
            model=model,
        )
        provider_label = provider
        if not scenario.locations and mode == "auto" and len(source_text) >= 3000:
            print(
                "[scenario_converter] 単発変換で locations が空のため、多段変換へ自動切替..."
            )
            scenario = _convert_scenario_staged(source_text, model=model)
            provider_label = "google-staged"

    _ensure_scenario_completeness(scenario)
    print(
        f"[scenario_converter] 変換完了 (provider={provider_label}, "
        f"locations={len(scenario.locations)}, events={len(scenario.event_triggers)})"
    )
    return scenario


def convert_file(
    input_path: str,
    output_path: str,
    *,
    provider: str = "auto",
    model: Optional[str] = None,
    mode: str = "auto",
    engine_format: bool = True,
) -> dict:
    text = Path(input_path).read_text(encoding="utf-8")
    scenario = convert_scenario_text(
        text,
        provider=provider,
        model=model,
        mode=mode,
    )
    data = scenario.to_engine_dict() if engine_format else scenario.model_dump(exclude_none=True)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[scenario_converter] 保存: {out}")
    return data


def main(argv=None):
    parser = argparse.ArgumentParser(description="自然言語シナリオ → GenericScenarioSchema JSON")
    parser.add_argument("input", nargs="?", help="入力テキストファイル")
    parser.add_argument("-o", "--output", required=True, help="出力 JSON パス")
    parser.add_argument("--stdin", action="store_true", help="標準入力から読み込む")
    parser.add_argument(
        "--provider",
        choices=["auto", "openai", "google", "gemini"],
        default="auto",
        help="LLM プロバイダー",
    )
    parser.add_argument("--model", default=None, help="モデル名（省略時は環境設定）")
    parser.add_argument(
        "--mode",
        choices=["auto", "single", "staged"],
        default="auto",
        help="変換方式（auto: 長文は多段変換 / single: 一括 / staged: 場面分割）",
    )
    parser.add_argument(
        "--raw-schema",
        action="store_true",
        help="エンジン変換前の GenericScenarioSchema をそのまま保存",
    )
    args = parser.parse_args(argv)

    if args.stdin:
        source = sys.stdin.read()
        scenario = convert_scenario_text(
            source,
            provider=args.provider,
            model=args.model,
            mode=args.mode,
        )
        data = (
            scenario.model_dump(exclude_none=True)
            if args.raw_schema
            else scenario.to_engine_dict()
        )
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[scenario_converter] 保存: {args.output}")
        return 0

    if not args.input:
        parser.error("input ファイルを指定するか --stdin を使用してください")

    convert_file(
        args.input,
        args.output,
        provider=args.provider,
        model=args.model,
        mode=args.mode,
        engine_format=not args.raw_schema,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
