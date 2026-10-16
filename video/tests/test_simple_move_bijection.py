import copy
import pytest
from video_agent.normalizer.session import normalize_session


def fixture():
    source = {'root': 'fixture', 'source_files': [], 'result': {'session_id': 'test'},
              'scenarios': [], 'pcs': {}, 'npcs': {}, 'unified_events': [], 'session_events': []}
    for i, (before, after) in enumerate([('a', 'b'), ('b', 'c'), ('c', 'b'), ('b', 'c')]):
        transaction = f'tx{i}' if i < 3 else ''
        source['unified_events'].append({
            'event_id': f'u{i}', 'raw_event_offset': i, 'event_type': 'LOCATION_CHANGE',
            'selected_action': 'move', 'location': before, 'target': after,
            'state_before': {'location': before}, 'state_after': {'location': after},
            'actor': 'pc_01', 'transaction_id': transaction, 'forced_action': i == 3})
        source['session_events'].append({'text': 'システム: 【移動】', 'location': before,
            'meta': {'event_id': f's{i}', 'action_id': 'move', 'target': after,
                     'roll_type': 'none', 'transaction_id': transaction, 'kp_narrated': i != 3}})
    return source


def test_four_moves_keep_all_eight_sources_without_mutating_raw():
    source = fixture()
    original = copy.deepcopy(source)
    doc = normalize_session(source)
    assert source == original
    assert len(doc['events']) == 4
    assert {s for e in doc['events'] for s in e['source_event_ids']} == {f'{p}{i}' for p in 'us' for i in range(4)}
    assert all(not e['dice'] and not e['adjudication_id'] for e in doc['events'])
    assert normalize_session(source) == doc


@pytest.mark.parametrize('damage', ['missing', 'extra', 'reorder', 'target', 'actor', 'transaction', 'duplicate_tx', 'no_offset', 'unknown_forced'])
def test_uncertain_or_contradictory_pairing_is_not_silently_merged(damage):
    source = fixture()
    u, s = source['unified_events'], source['session_events']
    if damage == 'missing': s.pop()
    if damage == 'extra': s.append(copy.deepcopy(s[-1]))
    if damage == 'reorder': s[0], s[1] = s[1], s[0]
    if damage == 'target': s[0]['meta']['target'] = 'elsewhere'
    if damage == 'actor': s[0]['meta']['actor_id'] = 'other'
    if damage == 'transaction': s[0]['meta']['transaction_id'] = 'other'
    if damage == 'duplicate_tx': u[1]['transaction_id'] = s[1]['meta']['transaction_id'] = 'tx0'
    if damage == 'no_offset': u[0].pop('raw_event_offset')
    if damage == 'unknown_forced': u[-1]['forced_action'] = False
    if damage in {'duplicate_tx', 'extra'}:
        with pytest.raises(ValueError, match='DEDUP_'):
            normalize_session(source)
    else:
        assert len(normalize_session(source)['events']) == len(u) + len(s)


def test_independent_session_move_preserved():
    source = fixture()
    source['unified_events'] = []
    assert len(normalize_session(source)['events']) == 4


def test_single_explicit_pair_preserves_display_payload():
    source = fixture()
    source['unified_events'] = source['unified_events'][:1]
    source['session_events'] = source['session_events'][:1]
    rows = normalize_session(source)['events']
    assert len(rows) == 1
    assert rows[0]['source_event_ids'] == ['u0', 's0']
    assert rows[0]['metadata']['simple_move_relation']['display_source_payload'] == source['session_events'][0]


def test_multiple_unkeyed_moves_fail_explicitly():
    source = fixture()
    for i in (2, 3):
        source['unified_events'][i]['transaction_id'] = ''
        source['unified_events'][i]['forced_action'] = True
        source['session_events'][i]['meta']['transaction_id'] = ''
        source['session_events'][i]['meta']['kp_narrated'] = False
    with pytest.raises(ValueError, match='DEDUP_AMBIGUOUS'):
        normalize_session(source)


def test_legacy_inferred_movements_are_preserved_without_dedup():
    source = fixture()
    for row in source['unified_events']:
        row.pop('event_type')
        row.pop('raw_event_offset')
        row['transaction_id'] = ''
    for row in source['session_events']:
        row['meta']['transaction_id'] = ''
    rows = normalize_session(source)['events']
    assert len(rows) == 8
    assert all('simple_move_relation' not in e['metadata'] for e in rows)


# Exact movement fields and complete display payloads extracted from frozen V3.
V3_UNIFIED = [{'actor': 'pc_02',
  'event_id': 'evt_000014_3d4d6e968b7977ebe75b',
  'event_type': 'LOCATION_CHANGE',
  'forced_action': False,
  'location': 'introduction',
  'raw_event_offset': 13,
  'scene_id': 'scene_001',
  'selected_action': 'move',
  'state_after': {'location': 'the_neighborhood'},
  'state_before': {'location': 'introduction'},
  'target': 'the_neighborhood',
  'transaction_id': 'e160777f-f50a-4923-a16e-35d02fadbf8e',
  'turn_id': 14},
 {'actor': 'pc_02',
  'event_id': 'evt_000017_92a3ef55298254ca171d',
  'event_type': 'LOCATION_CHANGE',
  'forced_action': False,
  'location': 'the_neighborhood',
  'raw_event_offset': 16,
  'scene_id': 'scene_001',
  'selected_action': 'move',
  'state_after': {'location': 'corbitt_exterior'},
  'state_before': {'location': 'the_neighborhood'},
  'target': 'corbitt_exterior',
  'transaction_id': '1112c629-3770-4f3f-bcce-69980abf295b',
  'turn_id': 17},
 {'actor': 'pc_02',
  'event_id': 'evt_000020_42703e164544916d1fa1',
  'event_type': 'LOCATION_CHANGE',
  'forced_action': False,
  'location': 'corbitt_exterior',
  'raw_event_offset': 19,
  'scene_id': 'scene_001',
  'selected_action': 'move',
  'state_after': {'location': 'the_neighborhood'},
  'state_before': {'location': 'corbitt_exterior'},
  'target': 'the_neighborhood',
  'transaction_id': '1838ae9d-ba8d-43d2-9306-2ca154f56397',
  'turn_id': 20},
 {'actor': 'pc_02',
  'event_id': 'evt_000032_9ac16e611b48a113757a',
  'event_type': 'LOCATION_CHANGE',
  'forced_action': True,
  'location': 'the_neighborhood',
  'raw_event_offset': 31,
  'scene_id': 'scene_001',
  'selected_action': 'move',
  'state_after': {'location': 'corbitt_exterior'},
  'state_before': {'location': 'the_neighborhood'},
  'target': 'corbitt_exterior',
  'transaction_id': '',
  'turn_id': 32}]
V3_SESSION = [{'channel': 'IC',
  'location': 'introduction',
  'meta': {'action_id': 'move',
           'actor_id': 'pc_02',
           'decision_owner_id': 'pc_02',
           'kp_narrated': True,
           'roll_type': 'none',
           'target': 'the_neighborhood',
           'transaction_id': 'e160777f-f50a-4923-a16e-35d02fadbf8e'},
  'secret_to': None,
  'text': 'システム: 判定なし（自動成功）\n【移動】導入 から 屋敷の近所 へ移動した。\n【フェーズ遷移】current_phase → `investigation`'},
 {'channel': 'IC',
  'location': 'the_neighborhood',
  'meta': {'action_id': 'move',
           'actor_id': 'pc_02',
           'decision_owner_id': 'pc_02',
           'kp_narrated': True,
           'roll_type': 'none',
           'target': 'corbitt_exterior',
           'transaction_id': '1112c629-3770-4f3f-bcce-69980abf295b'},
  'secret_to': None,
  'text': 'システム: 判定なし（自動成功）\n【移動】屋敷の近所 から コービット屋敷（外観） へ移動した。'},
 {'channel': 'IC',
  'location': 'corbitt_exterior',
  'meta': {'action_id': 'move',
           'actor_id': 'pc_02',
           'decision_owner_id': 'pc_02',
           'kp_narrated': True,
           'roll_type': 'none',
           'target': 'the_neighborhood',
           'transaction_id': '1838ae9d-ba8d-43d2-9306-2ca154f56397'},
  'secret_to': None,
  'text': 'システム: 判定なし（自動成功）\n【移動】コービット屋敷（外観） から 屋敷の近所 へ移動した。'},
 {'channel': 'IC',
  'location': 'the_neighborhood',
  'meta': {'action_id': 'move',
           'kp_narrated': False,
           'roll_type': 'none',
           'target': 'corbitt_exterior'},
  'secret_to': None,
  'text': 'システム: 判定なし（自動成功）\n【移動】屋敷の近所 から コービット屋敷（外観） へ移動した。'}]


def test_frozen_v3_four_plus_four_becomes_four_with_all_sources():
    source = fixture()
    source['unified_events'] = copy.deepcopy(V3_UNIFIED)
    source['session_events'] = copy.deepcopy(V3_SESSION)
    original = copy.deepcopy(source)
    doc = normalize_session(source)
    rows = [e for e in doc['events'] if e['event_type'] == 'LOCATION_CHANGE']
    assert len(rows) == 4
    assert len(rows) - len(V3_UNIFIED) == 0
    assert source == original
    assert all(len(e['source_event_ids']) == 2 for e in rows)
    expected = {e['event_id'] for e in V3_UNIFIED} | {f'session_log:{i:06d}' for i in range(4)}
    assert {sid for e in rows for sid in e['source_event_ids']} == expected
    assert [e['metadata']['simple_move_relation']['display_source_payload'] for e in rows] == V3_SESSION
    assert all(e['adjudication_id'] is None and e['cause_adjudication_id'] is None and e['dice'] is None for e in rows)
    assert normalize_session(source) == doc
