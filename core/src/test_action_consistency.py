"""会話相手・補正表示・案内候補の回帰検証。実通信／保存原本への書き込みなし。"""
import copy
import unittest
from NPCSocialManager import find_npc_id_from_intent_text
from test_npc_placement_and_police_archives import _Base
import main as game_main


class TestActionConsistency(_Base):
    def test_vocative_beats_longer_topic_name(self):
        self.assertEqual(find_npc_id_from_intent_text(self.char_mgr,
            'ボブさん、事務官キム・デブランさんの居場所を教えてください。',
            prefer_ids=['kim_deblanc']), 'npc_guard_01')

    def test_recipient_beats_topic(self):
        self.assertEqual(find_npc_id_from_intent_text(self.char_mgr,
            '警備員のボブにキム・デブランの所在を尋ねる。'), 'npc_guard_01')

    def test_ambiguous_mentions_do_not_pick_longest(self):
        self.assertIsNone(find_npc_id_from_intent_text(self.char_mgr,
            'ボブとキム・デブランのことを考える。'))

    def test_absent_addressee_not_replaced_by_present_topic(self):
        self.scenario.location = 'higher_courts_police_station'
        logs = []
        result = game_main.apply_pl_response_to_logs({
            'speak_as': 'PC', 'should_speak': True, 'pc_action': {
                'action': 'talk', 'target': 'kim_deblanc', 'skill': '',
                'dialogue': 'ボブさん、事務官キム・デブランさんの所在を教えてください。',
            }}, '刑事', self.scenario.location, logs, scenario_mgr=self.scenario,
            char_mgr=self.char_mgr, pc_id='pc_01')
        self.assertTrue(result.get('needs_pl_retry'))
        self.assertEqual(result['validation_error_code'], 'absent_npc_talk')
        self.assertFalse(any(e.get('meta', {}).get('needs_system') for e in logs))

    def test_present_addressee_corrects_wrong_target(self):
        self.scenario.location = 'higher_courts_police_station'
        result = game_main.reconcile_pl_action({
            'action': 'talk', 'target': 'npc_guard_01', 'skill': '',
            'dialogue': 'キムさん、ボブの所在を教えてください。',
        }, 'PC', '', self.scenario, self.scenario.location, char_mgr=self.char_mgr)
        self.assertEqual(result['target'], 'kim_deblanc')
        self.assertFalse(result.get('needs_pl_retry'))
        self.assertEqual(result['original_action']['target'], 'npc_guard_01')

    def test_empty_ambiguous_target_requires_retry(self):
        self.scenario.location = 'higher_courts_police_station'
        result = game_main.reconcile_pl_action({
            'action': 'talk', 'target': '', 'skill': '', 'dialogue': '少し話したい。',
        }, 'PC', '', self.scenario, self.scenario.location, char_mgr=self.char_mgr)
        self.assertEqual(result.get('validation_error_code'), 'ambiguous_social_target')

    def test_auto_correction_replaces_old_dialogue_and_keeps_history(self):
        self.scenario.flags.update(talked_with_knott=True, knott_letter_read=True, knott_memo_read=True)
        action = {'action': 'move', 'target': 'corbitt_exterior', 'dialogue': '屋敷へ向かう。'}
        fixed = game_main._build_auto_correction_action(action,
            {'action': 'move', 'target': 'boston_globe'}, self.scenario, 'introduction', self.char_mgr)
        self.assertEqual(fixed['dialogue'], '')
        self.assertIn('ボストン・グローブ', fixed['message'])
        self.assertNotIn('屋敷', fixed['message'])
        self.assertEqual(fixed['original_action'], action)
        self.assertNotIn('反復', fixed['system_correction_log'])

    def test_locked_auto_correction_is_not_executed(self):
        self.scenario.location = 'boston_globe'
        self.assertIsNone(game_main._build_auto_correction_action(
            {'action': 'talk', 'target': ''},
            {'action': 'search', 'target': 'reference_room_clipping_files'},
            self.scenario, 'boston_globe', self.char_mgr))

    def test_empty_globe_talk_does_not_choose_reception_without_evidence(self):
        self.scenario.location = 'boston_globe'
        result = game_main.reconcile_pl_action({
            'action': 'talk', 'target': '', 'dialogue': '少し話したい。',
        }, 'PC', '', self.scenario, 'boston_globe', char_mgr=self.char_mgr)
        self.assertTrue(result.get('needs_pl_retry'))

    def test_log_carries_original_proposal(self):
        self.scenario.location = 'introduction'
        self.scenario.flags.update(talked_with_knott=True, knott_letter_read=True, knott_memo_read=True)
        logs = []
        action = {'action': 'talk', 'target': 'steven_knott', 'dialogue': 'ノットさん、もう一度確認します。'}
        result = game_main.apply_pl_response_to_logs({'speak_as': 'PC', 'pc_action': action},
            '刑事', 'introduction', logs, scenario_mgr=self.scenario, char_mgr=self.char_mgr, pc_id='pc_01')
        entries = [e for e in logs if e.get('meta', {}).get('needs_system')]
        self.assertEqual(len(entries), 1)
        # 会話意図は保持し、発話本文も残す（move へ黙って置換しない）
        self.assertEqual(result.get('action'), 'talk')
        self.assertEqual(result.get('target'), 'steven_knott')
        self.assertIn('もう一度確認', entries[0]['text'])
        self.assertEqual(entries[0]['meta']['action_id'], 'talk')
        self.assertTrue(any((e.get('meta') or {}).get('post_action_hint') for e in logs))

    def test_globe_guidance_does_not_offer_locked_clipping(self):
        self.scenario.location = 'boston_globe'
        text = '\n'.join(game_main.build_absent_npc_guidance(self.scenario,
            'boston_globe', char_mgr=self.char_mgr))
        self.assertNotIn('reference_room_clipping_files', text)
        self.assertIn('globe_receptionist', text)
        self.assertNotIn('artie_wilmott', text)

    def test_globe_guidance_does_not_offer_completed_clipping(self):
        self.scenario.location = 'boston_globe'
        self.scenario.flags.update(artie_introduced=True, artie_reference_room_access_granted=True,
            investigated_targets=['reference_room_clipping_files'])
        text = '\n'.join(game_main.build_absent_npc_guidance(self.scenario,
            'boston_globe', exclude_targets={'globe_receptionist', 'artie_wilmott'}, char_mgr=self.char_mgr))
        self.assertNotIn('reference_room_clipping_files', text)
        self.assertNotIn('globe_receptionist', text)
        self.assertNotIn('artie_wilmott', text)
        self.assertIn('move', text)

    def test_hidden_objects_and_locked_exits_not_suggested(self):
        from ScenarioManager import ScenarioManager
        sm = ScenarioManager({'locations': {
            'room': {'npcs_present': [], 'objects': {
                'hidden': {'name': '隠し資料', 'is_visible_condition': 'false', 'usable_actions': ['search']},
                'visible': {'name': '公開資料', 'description': '本文', 'usable_actions': ['search']},
            }, 'connected_to': ['locked'], 'exits': {'locked': {'requires_flag': 'key'}}},
            'locked': {'name': '施錠先', 'objects': {}}}, 'initial_flags': {}})
        sm.location = 'room'
        before = copy.deepcopy(sm.export_to_dict())
        text = '\n'.join(game_main.build_absent_npc_guidance(sm, 'room'))
        self.assertNotIn('hidden', text)
        self.assertNotIn('locked', text)
        self.assertIn('visible', text)
        self.assertEqual(sm.export_to_dict(), before)


if __name__ == '__main__':
    unittest.main()
