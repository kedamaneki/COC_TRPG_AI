"""
タスク5: PC別 Knowledge Context フィルタリングの単体テスト。

実行:
  python test_knowledge_isolation.py
"""
from __future__ import annotations

import unittest
from unittest import mock

import main
from CharacterManager import (
    CharacterManager,
    knowledge_id_for_object,
    object_has_private_clue_content,
)


class FakeCharMgr:
    """最小の CharacterManager 互換スタブ。"""

    def __init__(self):
        self.characters = {
            "pc_01": {
                "profile": {"name": "探索者A", "is_npc": False},
                "attributes": {"LUK": 40},
                "skills": {"目星": 50},
            },
            "pc_02": {
                "profile": {"name": "探索者B", "is_npc": False},
                "attributes": {"LUK": 45},
                "skills": {"目星": 40},
            },
        }
        self.active_pcs = ["pc_01", "pc_02"]
        # CharacterManager の知識 API をミックスイン
        for name in (
            "ensure_knowledge_context",
            "get_known_knowledge_ids",
            "get_pc_investigated_targets",
            "pc_knows",
            "pc_has_investigated",
            "grant_knowledge",
            "mark_pc_investigated_target",
            "get_knowledge_notes_for_prompt",
        ):
            setattr(self, name, getattr(CharacterManager, name).__get__(self, FakeCharMgr))

    @property
    def active_pc_list(self):
        return list(self.active_pcs)

    def get_pc(self, pc_id):
        char = self.characters.get(pc_id)
        if not char or char.get("profile", {}).get("is_npc", False):
            return None
        return char

    def get_pc_name(self, pc_id):
        char = self.get_pc(pc_id) or {}
        return (char.get("profile") or {}).get("name", pc_id)

    def get_pc_slot_label(self, pc_id):
        return pc_id

    def get_pc_log_prefix(self, pc_id, *, role="PC"):
        name = self.get_pc_name(pc_id)
        return f"{name}({role})"

    def list_pc_ids(self):
        return [cid for cid, c in self.characters.items() if not c.get("profile", {}).get("is_npc")]

    def is_pc_incapacitated(self, pc_id, state_mgr=None):
        return False

    def get_insanity_states(self, pl_id):
        return []

    def build_character_sheet_summary(self, pl_id):
        return f"【シート】{self.get_pc_name(pl_id)}"


class FakeScenarioMgr:
    def __init__(self):
        self.location = "study"
        self.flags = {"investigated_targets": []}
        self.turn_counter = 0
        self._objects = {
            "study": {
                "knott_letter": {
                    "name": "ノット氏からの依頼書",
                    "description": "【秘密】コービット家の地下室に偶像がある、と書かれている。",
                    "investigated_flag": "knott_letter_read",
                    "player_handout": "【秘密】コービット家の地下室に偶像がある、と書かれている。",
                    "purpose": "依頼の概要が書かれた手紙",
                    "usable_actions": ["search", "inspect"],
                    "reject_message": "すでに読んだ。",
                },
                "window": {
                    "name": "窓",
                    "description": "通りに面した窓。",
                    "purpose": "外を見られる",
                    "usable_actions": ["search"],
                    "empty_clue": True,
                },
            }
        }

    def get_location_info(self, loc_id=None):
        loc = loc_id or self.location
        return {
            "name": "書斎",
            "objects": dict(self._objects.get(loc, {})),
        }

    def get_object_info(self, loc_id, obj_id):
        return dict((self._objects.get(loc_id) or {}).get(obj_id) or {})

    def get_available_exits(self, loc_id=None):
        return [{"id": "hallway", "name": "廊下"}]

    def _is_target_investigated(self, target):
        return target in set(self.flags.get("investigated_targets") or [])

    def _is_research_reopened(self, target):
        return False

    def _track_investigated_target(self, target):
        targets = set(self.flags.get("investigated_targets") or [])
        targets.add(target)
        self.flags["investigated_targets"] = sorted(targets)

    def _object_confirmed_fact(self, target, loc_id=None):
        obj = self.get_object_info(loc_id or self.location, target)
        fact = (
            obj.get("player_handout")
            or obj.get("description")
            or ""
        )
        return str(fact).strip(), obj

    def _knowledge_scope_for_object(self, obj):
        return "public" if (obj or {}).get("knowledge_scope") == "public" else "private"

    def _build_object_knowledge_grant(self, target, fact="", *, obj=None):
        obj = obj if obj is not None else self.get_object_info(self.location, target)
        return {
            "knowledge_id": f"object:{target}",
            "scope": self._knowledge_scope_for_object(obj),
            "target": target,
            "summary": str(fact or "").strip()[:400],
            "mark_investigated": True,
        }

    def _attach_knowledge_grants(self, payload, action_id, target, success_level):
        from ScenarioManager import ScenarioManager
        return ScenarioManager._attach_knowledge_grants(
            self, payload, action_id, target, success_level,
        )


class TestKnowledgeIsolation(unittest.TestCase):
    def test_grant_knowledge_is_pc_specific(self):
        char_mgr = FakeCharMgr()
        kid = knowledge_id_for_object("knott_letter")
        char_mgr.grant_knowledge(
            "pc_01", kid,
            target="knott_letter",
            summary="【秘密】コービット家の地下室に偶像がある",
        )
        self.assertTrue(char_mgr.pc_knows("pc_01", kid))
        self.assertFalse(char_mgr.pc_knows("pc_02", kid))
        self.assertIn("knott_letter", char_mgr.get_pc_investigated_targets("pc_01"))
        self.assertNotIn("knott_letter", char_mgr.get_pc_investigated_targets("pc_02"))

    def test_apply_knowledge_grants_from_result(self):
        char_mgr = FakeCharMgr()
        state = main.ensure_public_knowledge_field({})
        result = {
            "confirmed_fact": "【秘密】地下室に偶像",
            "target": "knott_letter",
            "knowledge_grants": [{
                "knowledge_id": "object:knott_letter",
                "scope": "private",
                "target": "knott_letter",
                "summary": "【秘密】地下室に偶像",
                "mark_investigated": True,
            }],
        }
        applied = main.apply_knowledge_grants_from_result(
            char_mgr, "pc_01", result, state=state,
        )
        self.assertIn("object:knott_letter", applied)
        self.assertTrue(char_mgr.pc_knows("pc_01", "object:knott_letter"))
        self.assertFalse(char_mgr.pc_knows("pc_02", "object:knott_letter"))

    def test_public_knowledge_visible_to_all(self):
        char_mgr = FakeCharMgr()
        state = {"public_knowledge_ids": []}
        main.grant_public_knowledge(state, "object:town_square", summary="広場の案内板")
        self.assertTrue(
            char_mgr.pc_knows("pc_01", "object:town_square", public_ids=state["public_knowledge_ids"])
        )
        self.assertTrue(
            char_mgr.pc_knows("pc_02", "object:town_square", public_ids=state["public_knowledge_ids"])
        )

    def test_pl_prompt_hides_other_pc_clue_text(self):
        char_mgr = FakeCharMgr()
        scenario = FakeScenarioMgr()
        state = main.ensure_public_knowledge_field({
            "pl_id": "pc_02",
            "active_pc_id": "pc_02",
            "actor_id": "pc_02",
        })
        # pc_01 だけが依頼書を読んだ
        char_mgr.grant_knowledge(
            "pc_01",
            "object:knott_letter",
            target="knott_letter",
            summary="【秘密】コービット家の地下室に偶像がある、と書かれている。",
        )
        scenario.flags["investigated_targets"] = ["knott_letter"]
        scenario.flags["knott_letter_read"] = True

        loc = scenario.get_location_info("study")
        prompt_b = main.generate_pl_prompt(
            "探索者B",
            ic_logs=[],
            ooc_logs=[],
            location_info=loc,
            available_exits=scenario.get_available_exits(),
            scenario_mgr=scenario,
            current_loc="study",
            char_mgr=char_mgr,
            pl_id="pc_02",
            game_state=state,
        )
        self.assertNotIn("地下室に偶像", prompt_b)
        self.assertNotIn("【秘密】", prompt_b)
        # 未調査として扱われる（他PC分の調査済み禁止が出ない）
        self.assertNotIn("探索禁止】ノット氏からの依頼書", prompt_b)

        prompt_a = main.generate_pl_prompt(
            "探索者A",
            ic_logs=[],
            ooc_logs=[],
            location_info=loc,
            available_exits=scenario.get_available_exits(),
            scenario_mgr=scenario,
            current_loc="study",
            char_mgr=char_mgr,
            pl_id="pc_01",
            game_state={**state, "pl_id": "pc_01", "active_pc_id": "pc_01"},
        )
        self.assertIn("地下室に偶像", prompt_a)
        self.assertIn("このPCが獲得した知識", prompt_a)

    def test_secret_to_filters_system_log(self):
        logs = [
            {
                "channel": "IC",
                "location": "study",
                "secret_to": ["pc_01"],
                "text": "システム: 【確定手がかり】地下室に偶像",
            },
            {
                "channel": "IC",
                "location": "study",
                "secret_to": None,
                "text": "システム: 窓の外は静かだ。",
            },
        ]
        ic_a, _ = main.get_filtered_logs("pc_01", "study", logs)
        ic_b, _ = main.get_filtered_logs("pc_02", "study", logs)
        self.assertTrue(any("地下室に偶像" in t for t in ic_a))
        self.assertFalse(any("地下室に偶像" in t for t in ic_b))
        self.assertTrue(any("窓の外" in t for t in ic_b))

    def test_format_objects_hides_private_description(self):
        loc = {
            "objects": {
                "knott_letter": {
                    "name": "依頼書",
                    "description": "【秘密】偶像の記述",
                    "investigated_flag": "knott_letter_read",
                    "player_handout": "【秘密】偶像の記述",
                    "purpose": "手紙",
                    "usable_actions": ["search"],
                }
            }
        }
        shown = main._format_objects_for_pl(
            loc,
            investigated_ids=set(),
            reveal_descriptions_for=set(),  # 誰も知らない
        )
        self.assertNotIn("偶像の記述", shown)
        self.assertIn("knott_letter", shown)

        revealed = main._format_objects_for_pl(
            loc,
            investigated_ids={"knott_letter"},
            reveal_descriptions_for={"knott_letter"},
        )
        self.assertIn("偶像の記述", revealed)

    def test_object_has_private_clue_detection(self):
        self.assertTrue(object_has_private_clue_content({
            "investigated_flag": "x",
            "description": "secret",
        }))
        self.assertFalse(object_has_private_clue_content({
            "empty_clue": True,
            "description": "flavor",
        }))
        self.assertFalse(object_has_private_clue_content({
            "knowledge_scope": "public",
            "description": "public board",
            "investigated_flag": "board_read",
        }))

    def test_scenario_attach_knowledge_grants(self):
        from ScenarioManager import ScenarioManager

        class Mini(FakeScenarioMgr):
            pass

        sm = Mini()
        # bind real helper
        sm._attach_knowledge_grants = ScenarioManager._attach_knowledge_grants.__get__(sm, Mini)
        sm._build_object_knowledge_grant = ScenarioManager._build_object_knowledge_grant.__get__(sm, Mini)
        sm._knowledge_scope_for_object = ScenarioManager._knowledge_scope_for_object.__get__(sm, Mini)
        from DiceEngine import SuccessLevel
        payload = {
            "confirmed_fact": "【秘密】偶像",
            "dice_success": True,
        }
        out = sm._attach_knowledge_grants(payload, "search", "knott_letter", int(SuccessLevel.REGULAR_SUCCESS))
        grants = out.get("knowledge_grants") or []
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0]["knowledge_id"], "object:knott_letter")
        self.assertEqual(grants[0]["scope"], "private")


if __name__ == "__main__":
    unittest.main(verbosity=2)
