import json
from pathlib import Path
import pytest
from night_guard import Controller, Stop, REQUIRED, KNOWN, check_gate, validate_diff, digest


def report(passed=True):
    return {**REQUIRED, 'EARLY_GATE': 'PASS' if passed else 'FAIL',
            'duplicate_lifecycle_events': 0 if passed else 4}


def controller(tmp_path):
    return Controller(tmp_path / 'journal')


@pytest.mark.parametrize('key', list(REQUIRED))
def test_missing_gate_field_fails(key):
    r = report()
    del r[key]
    assert check_gate(r)


def test_boolean_is_not_zero():
    r = report()
    r['duplicate_lifecycle_events'] = False
    assert check_gate(r)


@pytest.mark.parametrize('failure', ['protected_equal', 'scope_ok', 'runtime_error', 'infra_failure', 'new_major', 'new_critical'])
def test_health_failure_stops_and_logs(tmp_path, failure):
    c = controller(tmp_path)
    flags = dict(protected_equal=True, scope_ok=True, runtime_error=False,
                 infra_failure=False, new_major=False, new_critical=False)
    flags[failure] = not flags[failure]
    with pytest.raises(Stop): c.health(**flags)
    assert c.state == 'STOPPED' and not c.next_allowed
    assert json.loads((c.journal_dir / '0000.json').read_text())['action'] == 'STOP'


def test_scope_cannot_touch_auditor_or_prompt():
    with pytest.raises(Stop): validate_diff({'core/main.py': 'a'}, {'core/main.py': 'b'})
    with pytest.raises(Stop): validate_diff({}, {'video/tools/audit_longrun_formal_v2.py': 'b'})


@pytest.mark.parametrize('kind', ['UNKNOWN', 'PASS', 'OTHER_FAIL'])
def test_only_classified_early_fail_can_repair(tmp_path, kind):
    c = controller(tmp_path)
    r = report(kind == 'PASS')
    if kind == 'OTHER_FAIL': r['dropped_events'] = 1
    with pytest.raises(Stop): c.early_failure(r, 'unknown' if kind == 'UNKNOWN' else KNOWN)


def test_twice_recurrence_and_iteration_limit(tmp_path):
    c = controller(tmp_path)
    c.early_failure(report(False), KNOWN)
    c.state = 'GATE'
    c.early_failure(report(False), KNOWN)
    c.state = 'GATE'
    with pytest.raises(Stop, match='RECURRED'): c.early_failure(report(False), KNOWN)
    d = Controller(tmp_path / 'other', max_iterations=1)
    d.early_failure(report(False), KNOWN)
    d.state = 'GATE'
    with pytest.raises(Stop, match='MAX_ITERATIONS'): d.early_failure(report(False), KNOWN)


def test_regression_failure_never_allows_launch(tmp_path):
    c = controller(tmp_path)
    c.state = 'REGRESSION'
    with pytest.raises(Stop): c.regression({}, report(), 'identity')
    with pytest.raises(Stop): c.new_session('new', output_absent=True, cycle=0,
        resume_count=0, migration=None, identity='identity', local_only=True)


@pytest.mark.parametrize('field,value', [('cycle', 1), ('resume_count', 1), ('migration', 'old'),
                                      ('identity', 'changed'), ('local_only', False), ('output_absent', False)])
def test_new_session_constraints(tmp_path, field, value):
    c = controller(tmp_path)
    c.state, c.next_allowed, c.frozen_identity = 'READY', True, 'fixed'
    kwargs = dict(output_absent=True, cycle=0, resume_count=0, migration=None, identity='fixed', local_only=True)
    kwargs[field] = value
    with pytest.raises(Stop): c.new_session('new', **kwargs)


def test_gate_cannot_be_skipped_or_configuration_changed(tmp_path):
    c = controller(tmp_path)
    c.state, c.frozen_identity = 'RUNNING', 'fixed'
    with pytest.raises(Stop): c.raw_complete(identity='fixed', raw_hash_manifest=__file__, completed=True)
    d = Controller(tmp_path / 'other')
    d.state, d.frozen_identity = 'RUNNING', 'fixed'
    with pytest.raises(Stop): d.early_gate(report(), cycle=5, identity='changed')


def test_completed_blocker_is_terminal(tmp_path):
    c = controller(tmp_path)
    c.state = 'FINAL_AUDIT'
    with pytest.raises(Stop): c.final_audit(formal_pass=False, blocker_count=1,
        legacy_comparison_complete=True, raw_unchanged=True)
    with pytest.raises(Stop): c.early_failure(report(False), KNOWN)


def test_policy_happy_path_only_records_intents(tmp_path):
    c = controller(tmp_path)
    c.early_failure(report(False), KNOWN)
    diff = tmp_path / 'change.diff'
    diff.write_text('reviewable diff')
    key = 'video/src/video_agent/normalizer/session.py'
    c.repaired({key: 'before'}, {key: 'after'}, diff, 'known duplicate pairing')
    receipts = {s: {'exit_code': 0, 'status': 'PASS', 'tests': 1, 'identity': 'fixed',
                    'log': str(diff), 'log_sha256': digest(diff)}
                for s in ('fixture', 'core', 'video', 'auditor', 'readonly')}
    c.regression(receipts, report(), 'fixed')
    c.new_session('new', output_absent=True, cycle=0, resume_count=0, migration=None,
                  identity='fixed', local_only=True)
    assert c.early_gate(report(), cycle=5, identity='fixed')
    c.raw_complete(identity='fixed', raw_hash_manifest=diff, completed=True)
    c.final_audit(formal_pass=True, blocker_count=0, legacy_comparison_complete=True, raw_unchanged=True)
    assert c.state == 'COMPLETE' and not c.next_allowed
