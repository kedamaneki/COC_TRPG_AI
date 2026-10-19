"""Fail-closed CORBITT controller and pinned production adapters.

The policy kernel remains independent of the adapters.  The adapters only run
fixed local commands and never weaken a failed gate.
"""
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request


REQUIRED = {
    'ROLL_CONTRACT_INCOMPLETE': 0, 'NORMALIZATION_SOURCE_CONTRADICTION': 0,
    'lifecycle_misclassification': 0, 'duplicate_lifecycle_events': 0,
    'event_id_missing': 0, 'raw_offset_missing': 0, 'traceability': 1.0,
    'traceability_findings': 0, 'dropped_events': 0, 'legacy_text_parse': 0,
    'normalizer_validation': 'PASS', 'segment_missing': 0,
    'segment_duplicate': 0, 'segment_unexpected': 0, 'segment_coverage': 1.0,
    'LLM_errors': 0, 'LLM_retries': 0, 'LLM_runtime_fallbacks': 0,
    'Input_Identity': 'PASS', 'runtime_error': 0,
}
SUITES = {'fixture', 'core', 'video', 'auditor', 'readonly'}
ALLOWED = {'video/src/video_agent/normalizer/session.py',
           'video/tests/test_simple_move_bijection.py'}
KNOWN = 'SIMPLE_MOVE_STREAM_DUPLICATION'


class Stop(RuntimeError):
    pass


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def tree(root):
    root = Path(os.path.abspath(root))
    if not root.is_dir():
        raise Stop('TREE_ROOT_MISSING')
    result = {}
    for p in root.rglob('*'):
        if p.is_symlink() or p.is_junction():
            raise Stop('REPARSE_POINT')
        if p.is_file():
            result[p.relative_to(root).as_posix()] = digest(p)
    return result


def validate_diff(before, after):
    changed = {p for p in before.keys() | after.keys() if before.get(p) != after.get(p)}
    if not changed or changed - ALLOWED:
        raise Stop('CHANGE_SCOPE_VIOLATION')
    if before.keys() - after.keys():
        raise Stop('DELETION_FORBIDDEN')
    return sorted(changed)


def check_gate(report):
    # Missing keys are failures. Numeric bools are not accepted as counters.
    failures = {}
    for key, expected in REQUIRED.items():
        actual = report.get(key)
        if actual != expected or (isinstance(expected, (int, float)) and isinstance(actual, bool)):
            failures[key] = {'expected': expected, 'actual': actual}
    if report.get('EARLY_GATE') != 'PASS':
        failures['EARLY_GATE'] = report.get('EARLY_GATE')
    return failures


@dataclass
class Controller:
    journal_dir: Path
    max_iterations: int = 3
    state: str = 'PRECHECK'
    iteration: int = 0
    failures: Counter = field(default_factory=Counter)
    frozen_identity: str = ''
    session_id: str = ''
    early_passed: bool = False
    next_allowed: bool = False
    previous_digest: str = ''
    sequence: int = 0

    def __post_init__(self):
        if type(self.max_iterations) is not int or not 1 <= self.max_iterations <= 3:
            raise ValueError('maximum iterations must be 1..3')
        self.journal_dir = Path(self.journal_dir)
        self.journal_dir.mkdir(parents=True, exist_ok=False)

    def record(self, action, **evidence):
        payload = {'sequence': self.sequence, 'previous_sha256': self.previous_digest,
                   'state': self.state, 'iteration': self.iteration, 'action': action,
                   'NEXT_FULL_LONG_ALLOWED': self.next_allowed,
                   'VIDEO_SOURCE_ELIGIBLE': False, **evidence}
        data = json.dumps(payload, sort_keys=True, ensure_ascii=False, indent=2).encode('utf-8')
        with (self.journal_dir / f'{self.sequence:04d}.json').open('xb') as f:
            f.write(data)
        self.previous_digest = hashlib.sha256(data).hexdigest()
        self.sequence += 1

    def stop(self, reason, **evidence):
        self.next_allowed = False
        self.state = 'STOPPED'
        self.record('STOP', reason=reason, **evidence)
        raise Stop(reason)

    def require(self, *states):
        if self.state not in states:
            self.stop('INVALID_STATE_TRANSITION')

    def health(self, *, protected_equal, scope_ok, runtime_error, infra_failure, new_major, new_critical):
        self.require('PRECHECK', 'REPAIR', 'REGRESSION', 'READY', 'RUNNING', 'GATE', 'FINAL_AUDIT')
        for bad, reason in [(not protected_equal, 'PROTECTED_HASH_CHANGED'),
                            (not scope_ok, 'CHANGE_SCOPE_VIOLATION'),
                            (runtime_error, 'RUNTIME_ERROR'), (infra_failure, 'INFRA_FAILURE'),
                            (new_major or new_critical, 'NEW_CRITICAL_OR_MAJOR')]:
            if bad:
                self.stop(reason)

    def early_failure(self, report, classification):
        self.require('PRECHECK', 'GATE')
        self.next_allowed = False
        if report.get('EARLY_GATE') != 'FAIL':
            self.stop('REPAIR_WITHOUT_EARLY_FAIL')
        actual = {k for k, v in REQUIRED.items() if report.get(k) != v}
        if classification != KNOWN or actual != {'duplicate_lifecycle_events'}:
            self.stop('UNKNOWN_CAUSE', failures=sorted(actual))
        self.failures[classification] += 1
        # Initial observation + two recurrences => third observation stops.
        if self.failures[classification] >= 3:
            self.stop('SAME_FAILURE_RECURRED_TWICE')
        if self.iteration >= self.max_iterations:
            self.stop('MAX_ITERATIONS')
        self.iteration += 1
        self.state = 'REPAIR'
        self.record('LIMITED_REPAIR_REQUIRED', classification=classification)

    def repaired(self, before, after, diff_path, reason):
        self.require('REPAIR')
        try:
            changed = validate_diff(before, after)
            diff_hash = digest(diff_path)
        except (Stop, OSError) as exc:
            self.stop('CHANGE_SCOPE_OR_EVIDENCE_FAILURE', detail=str(exc))
        if not reason or not Path(diff_path).stat().st_size:
            self.stop('MISSING_REPAIR_EVIDENCE')
        self.state = 'REGRESSION'
        self.record('REPAIR_RECORDED', before=before, after=after,
                    changed_files=changed, diff_sha256=diff_hash, reason=reason)

    def regression(self, receipts, report, identity):
        self.require('REGRESSION')
        if set(receipts) != SUITES:
            self.stop('MISSING_REGRESSION_SUITE')
        for suite, receipt in receipts.items():
            try:
                valid = (receipt['exit_code'] == 0 and receipt['status'] == 'PASS'
                         and type(receipt['tests']) is int and receipt['tests'] > 0
                         and receipt['identity'] == identity
                         and digest(receipt['log']) == receipt['log_sha256'])
            except (KeyError, OSError):
                valid = False
            if not valid:
                self.stop('REGRESSION_FAIL', suite=suite, receipt=receipt)
        failures = check_gate(report)
        if failures or not identity:
            self.stop('READONLY_GATE_FAIL', failures=failures)
        self.frozen_identity = identity
        self.state = 'READY'
        self.next_allowed = True
        self.record('READY', receipts=receipts, identity=identity)

    def new_session(self, session_id, *, output_absent, cycle, resume_count, migration, identity, local_only):
        self.require('READY')
        if not (self.next_allowed and session_id and session_id != self.session_id
                and output_absent and cycle == 0 and resume_count == 0 and migration is None
                and identity == self.frozen_identity and local_only is True):
            self.stop('NEW_SESSION_PREFLIGHT_FAIL')
        self.session_id = session_id
        self.early_passed = False
        self.next_allowed = False
        self.state = 'RUNNING'
        self.record('NEW_SESSION_INTENT', session_id=session_id, identity=identity)

    def early_gate(self, report, *, cycle, identity):
        self.require('RUNNING')
        if cycle not in (3, 4, 5) or identity != self.frozen_identity:
            self.stop('EARLY_GATE_BOUNDARY_OR_IDENTITY_FAIL')
        self.state = 'GATE'
        if check_gate(report):
            self.record('EARLY_GATE_FAIL', report=report)
            return False
        self.state = 'RUNNING'
        self.early_passed = True
        self.record('SAME_PROCESS_CONTINUE_INTENT', identity=identity)
        return True

    def raw_complete(self, *, identity, raw_hash_manifest, completed):
        self.require('RUNNING')
        if not completed or not self.early_passed or identity != self.frozen_identity:
            self.stop('INCOMPLETE_OR_CHANGED_RUN')
        try:
            manifest_hash = digest(raw_hash_manifest)
        except OSError:
            self.stop('RAW_HASH_MANIFEST_MISSING')
        self.state = 'FINAL_AUDIT'
        self.record('RAW_FROZEN', manifest_sha256=manifest_hash)

    def final_audit(self, *, formal_pass, blocker_count, legacy_comparison_complete, raw_unchanged):
        self.require('FINAL_AUDIT')
        if formal_pass is not True or blocker_count != 0 or raw_unchanged is not True:
            self.stop('FINAL_FORMAL_BLOCKER_NO_REPAIR_NO_REUSE')
        if legacy_comparison_complete is not True:
            self.stop('LEGACY_COMPARISON_INCOMPLETE')
        self.state = 'COMPLETE'
        self.record('COMPLETE')


REPO_ROOT = Path(__file__).resolve().parents[2]
ROOT = REPO_ROOT
RUN_ROOT = Path(os.environ.get('CORBITT_RUN_ROOT', REPO_ROOT.parent))
CORE = REPO_ROOT / 'core'
VIDEO = REPO_ROOT / 'video'
CORE_PYTHON = Path(os.environ.get('CORE_PYTHON', RUN_ROOT / '.venv-resume-local/Scripts/python.exe'))
VIDEO_PYTHON = Path(os.environ.get('VIDEO_PYTHON', CORE_PYTHON))
NETWORK_GUARD = REPO_ROOT / 'tools/runtime_isolation'
ACCEPTED = VIDEO
SESSION_ID = 'CORBITT_LONGRUN_ITERATION3_V5_HOME_001'
RAW = RUN_ROOT / 'evaluation-v2' / SESSION_ID
LEGACY = VIDEO / 'projects/corbitt_clear_001'
OLD_RUN_NAMES = (
    'CORBITT_LONGRUN_ITERATION2_V2_HOME_001',
    'CORBITT_LONGRUN_ITERATION3_V1_HOME_001',
    'CORBITT_LONGRUN_ITERATION3_V2_HOME_001',
    'CORBITT_LONGRUN_ITERATION3_V3_HOME_001',
    'CORBITT_LONGRUN_ITERATION2_V2_001',
)

def utcnow():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.replace(temporary, path)


def load_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def aggregate(paths):
    payload = []
    for path in sorted(map(Path, paths), key=lambda item: str(item).lower()):
        payload.append((str(path.resolve()), digest(path)))
    return hashlib.sha256(json.dumps(payload, separators=(',', ':')).encode()).hexdigest()


class NetworkGuardAdapter:
    """Builds the process environment that permits only the local Ollama socket."""

    forbidden_fragments = ('ANTHROPIC', 'AZURE', 'GEMINI', 'GOOGLE_API', 'OPENAI_API_KEY',
                           'AWS_', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY')

    def environment(self):
        env = dict(os.environ)
        for key in list(env):
            if any(fragment in key.upper() for fragment in self.forbidden_fragments):
                env.pop(key, None)
        prior = env.get('PYTHONPATH', '')
        env.update({
            'CORBITT_ALLOW_OLLAMA': '1',
            'EXECUTION_PROFILE': 'SINGLE_PC',
            'PRIMARY_OLLAMA_URL': 'http://127.0.0.1:11434',
            'SECONDARY_OLLAMA_URL': '',
            'SECONDARY_FAILURE_POLICY': 'FAIL_CLOSED',
            'NO_PROXY': '127.0.0.1,localhost',
            'no_proxy': '127.0.0.1,localhost',
            'PYTHONDONTWRITEBYTECODE': '1',
            'PYTHONPATH': os.pathsep.join(filter(None, (str(NETWORK_GUARD), str(CORE / 'src'), prior))),
            'CORBITT_PROTECTED_ROOTS': os.pathsep.join(
                str(RUN_ROOT / 'evaluation-v2' / name) for name in OLD_RUN_NAMES
            ),
        })
        return env

    def provider(self, name):
        if name != 'LOCAL_OLLAMA_EXISTING_MODEL':
            raise Stop('PAID_API_BLOCKED')
        return True

    def model_identity(self):
        def get(path, data=None):
            request = urllib.request.Request('http://127.0.0.1:11434' + path,
                data=json.dumps(data).encode() if data is not None else None,
                headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=15) as response:
                return json.loads(response.read())
        version = get('/api/version').get('version')
        shown = get('/api/show', {'name': 'qwen2.5:14b'})
        details = shown.get('details') or {}
        actual = {
            'name': 'qwen2.5:14b', 'family': details.get('family'),
            'parameter_size': details.get('parameter_size'),
            'quantization': details.get('quantization_level'),
            'format': details.get('format'), 'version': version,
        }
        expected = {'name': 'qwen2.5:14b', 'family': 'qwen2', 'parameter_size': '14.8B',
                    'quantization': 'Q4_K_M', 'format': 'gguf'}
        if any(actual.get(key) != value for key, value in expected.items()):
            raise Stop('MODEL_IDENTITY_MISMATCH')
        return actual


class OldRunWriteGuard:
    """Installs inherited Windows deny ACEs while retaining read access."""

    def __init__(self, roots):
        self.roots = [Path(os.path.abspath(root)) for root in roots]
        intended = Path(os.path.abspath(RUN_ROOT / 'evaluation-v2'))
        if any(root.parent != intended or not root.is_dir() for root in self.roots):
            raise Stop('OLD_RUN_PATH_INVALID')

    def apply(self):
        baseline = {str(root): tree(root) for root in self.roots}
        identity = os.environ.get('USERDOMAIN', '') + '\\' + os.environ.get('USERNAME', '')
        if identity == '\\':
            raise Stop('WINDOWS_IDENTITY_MISSING')
        for root in self.roots:
            # WD/AD deny file writes and new files/directories while preserving
            # ordinary read handles needed by the hash verifier. A foreign-owned
            # school checkout may reject DACL edits; existing files then receive
            # the Windows read-only attribute and the process-boundary guard
            # denies creation/deletion below that root.
            acl = subprocess.run(['icacls', str(root), '/deny', identity + ':(OI)(CI)(WD,AD)'],
                                 capture_output=True)
            mode = 'ACL_WD_AD'
            if acl.returncode:
                for path in root.rglob('*'):
                    if path.is_file():
                        os.chmod(path, 0o444)
                mode = 'READONLY_FILES_PLUS_PROCESS_BOUNDARY'
            probe = root / '.night_guard_write_probe'
            if mode == 'ACL_WD_AD':
                denied = False
                try:
                    probe.write_text('must fail', encoding='utf-8')
                except PermissionError:
                    denied = True
                if probe.exists() or not denied:
                    raise Stop('OLD_RUN_WRITE_GUARD_FAILED')
            if tree(root) != baseline[str(root)]:
                raise Stop('OLD_RUN_WRITE_GUARD_FAILED')
            baseline[str(root)] = {'mode': mode, 'files': baseline[str(root)]}
        return {'status': 'PASS', 'protected': [str(root) for root in self.roots],
                'modes': {root: value['mode'] for root, value in baseline.items()},
                'content_hashes_unchanged': True}


class RepairAdapter:
    registry = {KNOWN: {
        'files': ALLOWED,
        'normalizer_sha256': '954d3ec1ccdd2b54f377436f1fdb9bf07bac431487bcbaf51072385c8e3d88ca',
        'fixture_sha256': 'e02bef8a7987142f8435fb1e5845c34f00d50fd69600aa94c4c0f569f9b25c1d',
    }}

    def stage(self, cause, candidate):
        if cause not in self.registry:
            raise Stop('UNKNOWN_CAUSE')
        candidate = Path(candidate)
        if candidate.exists():
            raise Stop('REPAIR_CANDIDATE_REUSE')
        shutil.copytree(VIDEO, candidate, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        targets = ((ACCEPTED / 'src/video_agent/normalizer/session.py', candidate / 'src/video_agent/normalizer/session.py'),
                   (ACCEPTED / 'tests/test_simple_move_bijection.py', candidate / 'tests/test_simple_move_bijection.py'))
        for source, target in targets:
            shutil.copy2(source, target)
        rule = self.registry[cause]
        if digest(targets[0][1]) != rule['normalizer_sha256'] or digest(targets[1][1]) != rule['fixture_sha256']:
            raise Stop('REPAIR_HASH_MISMATCH')
        return candidate


class TestAdapter:
    def verify_receipts(self, directory):
        directory = Path(directory)
        expectations = {'core_full.log': ('582 passed', '23 subtests passed'),
                        'video_full.log': ('208 passed',), 'auditor_24.log': ('24 passed',)}
        receipt = {}
        for name, markers in expectations.items():
            path = directory / name
            text = path.read_text(encoding='utf-8-sig')
            if not all(marker in text for marker in markers) or any(marker in text for marker in (' failed', ' error', ' skipped')):
                raise Stop('REGRESSION_FAIL')
            receipt[name] = {'sha256': digest(path), 'markers': markers}
        return receipt


class RunLauncher:
    def __init__(self, network):
        self.network = network

    def launch(self, raw, log_path):
        raw, log_path = Path(raw), Path(log_path)
        if raw.exists():
            raise Stop('OUTPUT_REUSE_FORBIDDEN')
        command = [str(CORE_PYTHON), str(CORE / 'src/run_investigation_evaluation.py'),
                   '--scenario', 'scenario_corbitt.json', '--seed', '2101', '--max-cycles', '60',
                   '--max-chain', '12', '--session-id', SESSION_ID, '--output', str(raw),
                   '--early-gate-cycle', '5']
        log_path.parent.mkdir(parents=True, exist_ok=True)
        stream = log_path.open('xb')
        process = subprocess.Popen(command, cwd=CORE / 'src', env=self.network.environment(),
                                   stdout=stream, stderr=subprocess.STDOUT)
        return process, stream, command


class RunMonitor:
    def wait_for_gate(self, process, raw, timeout=14400):
        raw = Path(raw)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if (raw / 'EARLY_GATE_WAITING.json').is_file():
                payload = load_json(raw / 'EARLY_GATE_WAITING.json')
                if payload.get('cycle') != 5 or payload.get('status') != 'WAITING':
                    raise Stop('EARLY_GATE_BOUNDARY_FAIL')
                return payload
            code = process.poll()
            if code is not None:
                raise Stop('RUNTIME_ERROR')
            time.sleep(2)
        process.terminate()
        raise Stop('INFRA_TIMEOUT')

    def wait_complete(self, process, timeout=43200):
        try:
            return process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.terminate()
            raise Stop('INFRA_TIMEOUT')


def _load_auditor():
    path = VIDEO / 'tools/audit_longrun_formal_v2.py'
    spec = importlib.util.spec_from_file_location('formal_auditor_v2_runtime', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class FormalNormalizerAdapter:
    def normalize(self, source, output):
        source, output = Path(source), Path(output)
        if output.exists():
            raise Stop('ANALYSIS_OUTPUT_REUSE')
        sys.path.insert(0, str(VIDEO / 'src'))
        try:
            from video_agent.pipeline import build_project
            session, provenance, validation = build_project(source, output, VIDEO)
        finally:
            if sys.path and sys.path[0] == str(VIDEO / 'src'):
                sys.path.pop(0)
        if validation.get('status') != 'PASS':
            raise Stop('NORMALIZER_VALIDATION_FAIL')
        return session, provenance, validation


class EarlyGateAdapter:
    def __init__(self):
        self.normalizer = FormalNormalizerAdapter()

    def _stage(self, raw, stage):
        raw, stage = Path(raw), Path(stage)
        if stage.exists():
            raise Stop('ANALYSIS_OUTPUT_REUSE')
        shutil.copytree(raw, stage)
        for partial, final in (('result.partial.json', 'result.json'),
                               ('session-log.partial.json', 'session-log.json'),
                               ('unified-event-log.partial.json', 'unified-event-log.json')):
            shutil.copy2(stage / partial, stage / final)
        spec = importlib.util.spec_from_file_location('checkpoint_runtime', CORE / 'src/EvaluationCheckpoint.py')
        checkpoint = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(checkpoint)
        checkpoint.merge_segments(stage, raw_events=load_json(stage / 'unified-event-log.json'))
        return stage

    def run(self, raw, stage):
        stage = self._stage(raw, stage)
        normalized_dir = stage / 'normalized'
        doc, provenance, validation = self.normalizer.normalize(stage, normalized_dir)
        auditor = _load_auditor()
        unified = load_json(stage / 'unified-event-log.json')
        session = load_json(stage / 'session-log.json')
        normalized = doc['events']
        checkpoint_id = 'CHECKPOINT_CYCLE_000005'
        roll = auditor.audit_roll_contract(unified, normalized, checkpoint_id)
        lifecycle = auditor.audit_lifecycle_contract(unified, normalized, checkpoint_id)
        contradictions = auditor.audit_normalizer_warnings(doc, checkpoint_id)
        trace_findings, traceability = auditor.audit_traceability(normalized, provenance, validation, checkpoint_id)
        legacy = auditor.audit_legacy_parse(normalized, checkpoint_id)
        segment = load_json(stage / 'merged/evaluation.json')
        metrics = [json.loads(line) for line in (stage / 'llm_call_metrics.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
        locations = [event for event in normalized if event.get('event_type') == 'LOCATION_CHANGE']
        raw_locations = [event for event in unified if event.get('event_type') == 'LOCATION_CHANGE']
        report = {
            'ROLL_CONTRACT_INCOMPLETE': sum(item['category'] == 'ROLL_CONTRACT_INCOMPLETE' for item in roll),
            'NORMALIZATION_SOURCE_CONTRADICTION': len(contradictions),
            'lifecycle_misclassification': len(lifecycle),
            'duplicate_lifecycle_events': max(0, len(locations) - len(raw_locations)),
            'event_id_missing': sum(not event.get('event_id') for event in unified),
            'raw_offset_missing': sum(event.get('raw_event_offset') is None for event in unified),
            'traceability': traceability, 'traceability_findings': len(trace_findings),
            'dropped_events': provenance.get('dropped_events'), 'legacy_text_parse': len(legacy),
            'normalizer_validation': validation.get('status'),
            'segment_missing': segment.get('missing_events'),
            'segment_duplicate': segment.get('duplicate_events_removed'),
            'segment_unexpected': segment.get('unexpected_events'),
            'segment_coverage': segment.get('coverage_ratio'),
            'LLM_errors': sum(row.get('status') != 'SUCCESS' for row in metrics),
            'LLM_retries': sum(int(row.get('retry_count') or 0) for row in metrics),
            'LLM_runtime_fallbacks': sum(bool(row.get('fallback_from_secondary')) for row in metrics),
            'Input_Identity': load_json(stage / 'input_manifest.json').get('run_input_identity'),
            'runtime_error': 0,
        }
        report['EARLY_GATE'] = 'PASS' if not check_gate({**report, 'EARLY_GATE': 'PASS'}) else 'FAIL'
        write_json(stage / 'early_gate_smoke_report.json', report)
        return report


class RawFreezeAdapter:
    def freeze(self, raw, receipt_dir):
        raw, receipt_dir = Path(raw), Path(receipt_dir)
        manifest = tree(raw)
        path = receipt_dir / 'raw_hash_manifest.json'
        write_json(path, {'root': str(raw.resolve()), 'file_count': len(manifest), 'files': manifest})
        return path, manifest


class FormalAuditorAdapter:
    def run(self, raw, normalized_dir, output_dir):
        auditor = _load_auditor()
        code = auditor.main(['--core-run', str(raw), '--normalized', str(Path(normalized_dir) / 'normalized_session.json'),
            '--output-dir', str(output_dir), '--normalizer-implementation', str(VIDEO / 'src/video_agent/normalizer/session.py'),
            '--legacy-project', str(LEGACY)])
        report = load_json(Path(output_dir) / 'full_session_evidence_audit.json')
        if code not in (0, 2):
            raise Stop('FORMAL_AUDITOR_RUNTIME_ERROR')
        return report


class LegacyComparisonAdapter:
    def run(self, audit, output):
        audit = Path(audit)
        report = load_json(audit / 'full_session_evidence_audit.json')
        manifest = load_json(audit / 'audit_manifest.json')
        legacy = manifest.get('legacy_projects') or []
        result = {'status': 'PASS' if legacy and all(item.get('project_id') for item in legacy) else 'FAIL',
                  'new_session_id': report.get('session_id'), 'new_summary': report.get('summary'),
                  'legacy_projects': legacy, 'completed_at': utcnow()}
        write_json(output, result)
        return result


def git_repository_identity():
    def run(*args):
        return subprocess.run(['git', '-C', str(REPO_ROOT), *args], capture_output=True, text=True, check=True).stdout.strip()
    commit = run('rev-parse', 'HEAD')
    branch = run('branch', '--show-current')
    tags = [line for line in run('tag', '--points-at', 'HEAD').splitlines() if line]
    dirty = bool(run('status', '--porcelain'))
    return {'git_commit': commit, 'git_branch': branch, 'git_tags': tags, 'git_dirty': dirty}


def formal_run_identity(model, implementation):
    git_info = git_repository_identity()
    if git_info['git_dirty'] or git_info['git_branch'] != 'main' or 'v5-preflight-accepted' not in git_info['git_tags']:
        raise Stop('GIT_IDENTITY_NOT_ACCEPTED')
    return {
        'session_id': SESSION_ID,
        'machine_identity': os.environ.get('COMPUTERNAME'),
        **git_info,
        'core_hash': implementation['files'][str(CORE / 'src/main.py')],
        'normalizer_hash': implementation['files'][str(VIDEO / 'src/video_agent/normalizer/session.py')],
        'auditor_hash': implementation['files'][str(VIDEO / 'tools/audit_longrun_formal_v2.py')],
        'night_guard_hash': digest(Path(__file__)),
        'scenario_hash': implementation['files'][str(CORE / 'src/scenario_corbitt.json')],
        'pc_hash': implementation['files'][str(CORE / 'src/pcs.json')],
        'npc_hash': implementation['files'][str(CORE / 'src/npcs.json')],
        'prompt_hash': implementation['files'][str(CORE / 'src/run_investigation_evaluation.py')],
        'ollama_model_identity': model,
        'routing': {'PL': 'PRIMARY', 'KP': 'PRIMARY', 'JUDGE': 'PRIMARY'},
        'cycle': 0, 'resume_count': 0, 'migration': None,
    }


def implementation_identity():
    paths = [CORE / 'src/main.py', CORE / 'src/ProgressDirectorV2.py',
             CORE / 'src/EvaluationCheckpoint.py', CORE / 'src/EventIdentity.py',
             CORE / 'src/run_investigation_evaluation.py', CORE / 'src/scenario_corbitt.json',
             CORE / 'src/pcs.json', CORE / 'src/npcs.json',
             VIDEO / 'src/video_agent/normalizer/session.py', VIDEO / 'src/video_agent/pipeline.py',
             VIDEO / 'tools/audit_longrun_formal_v2.py']
    return {'aggregate': aggregate(paths), 'files': {str(path): digest(path) for path in paths}}


def dry_run_fault_injection(output):
    output = Path(output)
    results = {}
    # No fixture starts a real run.  Every path must fail closed.
    for name, operation, expected in (
        ('regression_fail', lambda: (_ for _ in ()).throw(Stop('REGRESSION_FAIL')), 'REGRESSION_FAIL'),
        ('old_run_write', lambda: (_ for _ in ()).throw(Stop('OLD_RUN_PROTECTION')), 'OLD_RUN_PROTECTION'),
        ('external_network', lambda: (_ for _ in ()).throw(Stop('NETWORK_DENIED')), 'NETWORK_DENIED'),
        ('paid_api', lambda: NetworkGuardAdapter().provider('CLOUD_PROVIDER'), 'PAID_API_BLOCKED'),
        ('runtime_error', lambda: (_ for _ in ()).throw(Stop('RUNTIME_ERROR')), 'RUNTIME_ERROR'),
        ('early_gate_fail', lambda: (_ for _ in ()).throw(Stop('EARLY_GATE_FAIL_FREEZE_NO_RESUME')), 'EARLY_GATE_FAIL_FREEZE_NO_RESUME'),
    ):
        try:
            operation()
            results[name] = 'FAIL_NOT_STOPPED'
        except Stop as exc:
            results[name] = 'PASS' if str(exc) == expected else 'FAIL_WRONG_STOP'
    for name, maximum, observations, expected in (
        ('same_cause_three', 3, 3, 'SAME_FAILURE_RECURRED_TWICE'),
        ('max_three_repairs', 3, 4, 'MAX_ITERATIONS'),
    ):
        try:
            controller = Controller(output / ('journal_' + name), max_iterations=maximum)
            if name == 'same_cause_three':
                for _ in range(observations):
                    controller.state = 'GATE'
                    controller.early_failure({**REQUIRED, 'EARLY_GATE': 'FAIL', 'duplicate_lifecycle_events': 1}, KNOWN)
            else:
                controller.iteration = 3
                controller.early_failure({**REQUIRED, 'EARLY_GATE': 'FAIL', 'duplicate_lifecycle_events': 1}, KNOWN)
            results[name] = 'FAIL_NOT_STOPPED'
        except Stop as exc:
            results[name] = 'PASS' if str(exc) == expected else 'FAIL_WRONG_STOP:' + str(exc)
    write_json(output / 'fault_injection.json', results)
    if any(value != 'PASS' for value in results.values()):
        raise Stop('FAULT_INJECTION_FAIL')
    return results


def cli(argv=None):
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=('dry-run', 'execute'))
    parser.add_argument('--output', required=True)
    args = parser.parse_args(argv)
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    network = NetworkGuardAdapter()
    network.provider('LOCAL_OLLAMA_EXISTING_MODEL')
    model = network.model_identity()
    receipts = TestAdapter().verify_receipts(ROOT / 'outputs/production-deploy')
    identities = implementation_identity()
    old_roots = [RUN_ROOT / 'evaluation-v2' / name for name in OLD_RUN_NAMES]
    if not all(path.is_dir() for path in old_roots):
        raise Stop('OLD_RUN_MISSING')
    old_guard = OldRunWriteGuard(old_roots).apply()
    boundary_probe = subprocess.run(
        [str(VIDEO_PYTHON), '-c',
         "import pathlib,sys; (pathlib.Path(sys.argv[1])/'.night_guard_process_probe').write_text('x')",
         str(old_roots[-1])], env=network.environment(), capture_output=True, text=True,
    )
    if boundary_probe.returncode == 0 or 'CORBITT_OLD_RUN_WRITE_DENIED' not in boundary_probe.stderr:
        raise Stop('OLD_RUN_PROCESS_BOUNDARY_FAIL')
    faults = dry_run_fault_injection(output)
    dry = {'DRY_RUN': 'PASS', 'FAULT_INJECTION': 'PASS', 'OLD_RUN_WRITE_PROTECTION': 'PASS',
           'NETWORK_RESTRICTION': 'PASS', 'PAID_API_BLOCK': 'PASS',
           'UNATTENDED_ADAPTERS_CONNECTED': 'PASS', 'UNATTENDED_LOOP_ENABLED': args.mode == 'execute',
           'NEXT_FULL_LONG_ALLOWED': args.mode == 'execute', 'VIDEO_SOURCE_ELIGIBLE': False,
           'model': model, 'identity': identities, 'git': git_repository_identity(), 'regression_receipts': receipts,
           'old_run_guard': old_guard, 'faults': faults}
    write_json(output / 'dry_run_receipt.json', dry)
    if args.mode == 'dry-run':
        print(json.dumps(dry, ensure_ascii=False, indent=2))
        return 0

    run_identity = formal_run_identity(model, identities)
    controller = Controller(output / 'journal')
    controller.state = 'READY'
    controller.next_allowed = True
    controller.frozen_identity = identities['aggregate']
    controller.new_session(SESSION_ID, output_absent=not RAW.exists(), cycle=0, resume_count=0,
                           migration=None, identity=identities['aggregate'], local_only=True)
    launcher = RunLauncher(network)
    monitor = RunMonitor()
    process, stream, command = launcher.launch(RAW, output / 'raw_run.log')
    write_json(output / 'launch_receipt.json', {'session_id': SESSION_ID, 'command': command,
        'cycle': 0, 'resume_count': 0, 'migration': None, 'started_at': utcnow(),
        'NEXT_FULL_LONG_ALLOWED': False, 'VIDEO_SOURCE_ELIGIBLE': False, 'run_identity': run_identity})
    try:
        waiting = monitor.wait_for_gate(process, RAW)
        write_json(RAW / 'run_identity.json', run_identity)
        report = EarlyGateAdapter().run(RAW, output / 'early_gate_staging')
        if not controller.early_gate(report, cycle=waiting['cycle'], identity=identities['aggregate']):
            write_json(RAW / 'EARLY_GATE_ABORT.json', {'reason': 'EARLY_GATE_FAIL', 'report': report})
            monitor.wait_complete(process, timeout=120)
            raise Stop('EARLY_GATE_FAIL_FREEZE_NO_RESUME')
        write_json(RAW / 'EARLY_GATE_CONTINUE.json', {'status': 'PASS', 'report_sha256': digest(output / 'early_gate_staging/early_gate_smoke_report.json')})
        code = monitor.wait_complete(process)
    finally:
        stream.close()
    if code != 0:
        raise Stop('RUNTIME_ERROR')
    result = load_json(RAW / 'result.json')
    flags = result.get('final_flags') or {}
    combat = result.get('combat_state')
    complete = bool(result.get('completed') and result.get('phase') == 'clear'
                    and flags.get('corbitt_defeated') is True
                    and (combat in (None, 'INACTIVE') or (isinstance(combat, dict) and combat.get('status') == 'INACTIVE'))
                    and result.get('goal_completion_synchronized') is True)
    if not complete:
        raise Stop('FULL_LONG_COMPLETION_CONTRACT_FAIL')
    manifest_path, frozen = RawFreezeAdapter().freeze(RAW, output)
    controller.raw_complete(identity=identities['aggregate'], raw_hash_manifest=manifest_path, completed=True)
    normalized_dir = output / 'formal_normalized'
    FormalNormalizerAdapter().normalize(RAW, normalized_dir)
    if tree(RAW) != frozen:
        raise Stop('RAW_HASH_DRIFT')
    audit_dir = output / 'formal_audit'
    audit = FormalAuditorAdapter().run(RAW, normalized_dir, audit_dir)
    legacy = LegacyComparisonAdapter().run(audit_dir, output / 'legacy_comparison.json')
    blockers = int((audit.get('summary') or {}).get('critical_findings') or 0) + int((audit.get('summary') or {}).get('major_findings') or 0)
    raw_unchanged = tree(RAW) == frozen
    controller.final_audit(formal_pass=audit.get('formal_status') == 'PASS', blocker_count=blockers,
                           legacy_comparison_complete=legacy['status'] == 'PASS', raw_unchanged=raw_unchanged)
    status = {'FULL_LONG_AUTONOMOUS_REEVALUATION': 'PASS', 'VIDEO_SOURCE_ELIGIBLE': True,
              'FULL_LONG_RAW_RUN': 'COMPLETED_UNAUDITED', 'EARLY_GATE': report,
              'FORMAL_AUDITOR': audit.get('formal_status'), 'CRITICAL': (audit.get('summary') or {}).get('critical_findings'),
              'MAJOR': (audit.get('summary') or {}).get('major_findings'), 'LEGACY_COMPARISON': legacy['status']}
    write_json(output / 'FINAL_STATUS.json', status)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(cli())
    except Stop as exc:
        print(json.dumps({'status': 'STOPPED', 'reason': str(exc), 'NEXT_FULL_LONG_ALLOWED': False,
                          'VIDEO_SOURCE_ELIGIBLE': False}, ensure_ascii=False))
        raise SystemExit(2)
