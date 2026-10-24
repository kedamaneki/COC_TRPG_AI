"""Natural Decision production runtime — init, causal bind, S-authority, telemetry."""

from __future__ import annotations

import hashlib
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Optional, Sequence

from .evidence import ReasoningEvidence, build_reasoning_evidence
from .knowledge_boundary import KnowledgeBoundaryError, ReasoningKnowledgeBoundary, KnownFactView, EpistemicKind
from .kp_assessment import assess_party_progress, stall_weight
from .kp_intervention import InterventionRuntimeState, KPInterventionPolicy
from .lead_tracker import Lead, LeadStatus, LeadTracker
from .hypothesis_tracker import HypothesisTracker
from .pipeline import NaturalDecisionPipeline, NaturalDecisionResult
from .pl_policy import PLDecisionPolicy, UnexplainedActionError
from .pl_state import PLReasoningState
from .safe_fallback import SafeLegacyProgression, FallbackUnboundedError
from .recent_action import (
    RECENT_ACTION_SCHEMA_VERSION,
    normalize_recent_actions,
    recent_actions_as_dicts,
    RecentActionContractError,
)
from .error_class import (
    classify_exception,
    NDMRuntimeContractViolation,
    SafeFallbackFailure,
    FALLBACK_ELIGIBLE,
    PROGRAMMING_ERROR,
    RUNTIME_CONTRACT_VIOLATION,
)


DECISION_SOURCE_NDM = "natural_decision_v1"
DECISION_SOURCE_SAFE_LEGACY = "safe_legacy_progression"
DECISION_SOURCE_HUMAN = "human_forced"
LEGACY_SOURCES = frozenset({
    "safe_legacy_progression",
    "legacy_stall_detector",
    "legacy_director_primary",
    "unbound_legacy",
})
ALLOWED_SOURCES = frozenset({
    DECISION_SOURCE_NDM,
    DECISION_SOURCE_SAFE_LEGACY,
    "human_forced",
    "human_guided",
})


class NDMInitFailure(RuntimeError):
    code = "NATURAL_DECISION_INIT_FAILED"


class UnboundDecisionCommit(ValueError):
    code = "UNBOUND_DECISION_COMMIT"


class LegacySLevelCommitRejected(ValueError):
    code = "LEGACY_S_LEVEL_COMMIT_REJECTED"


@dataclass
class NDMTelemetry:
    NATURAL_DECISION_RUNTIME_ACTIVE: bool = False
    s_level_authority: str = ""
    legacy_stall_detector_primary: bool = True
    pl_reasoning_event_count: int = 0
    kp_progress_assessment_count: int = 0
    selected_action_with_ndm_reasoning_count: int = 0
    selected_action_reasoning_id_missing: int = 0
    # V17 separated counters
    NDM_DECISION_COMMIT_COUNT: int = 0
    SAFE_LEGACY_DECISION_COMMIT_COUNT: int = 0
    UNSAFE_LEGACY_DECISION_COMMIT_COUNT: int = 0
    REASONING_FALLBACK_COUNT: int = 0
    RUNTIME_CONTRACT_VIOLATION_COUNT: int = 0
    SAFE_FALLBACK_FAILURE_COUNT: int = 0
    SAFE_FALLBACK_RECURSION_COUNT: int = 0
    # Compat aliases (SAFE only — never conflate unsafe)
    SAFE_LEGACY_PROGRESSION_COUNT: int = 0
    LEGACY_DECISION_COMMIT_COUNT: int = 0  # deprecated alias; mirrors UNSAFE only after V17
    fallback_streak: int = 0
    unexplained_action_count: int = 0
    lead_abandon_count: int = 0
    self_recovery_count: int = 0
    meaningful_progress_count: int = 0
    goal_directed_progress_count: int = 0
    lateral_exploration_progress_count: int = 0
    progress_event_count: int = 0
    progression_local_optimum_count: int = 0
    max_goal_directed_no_progress_streak: int = 0
    frontier_switch_count: int = 0
    location_revisit_count: int = 0
    location_visit_count: int = 0
    frontier_persistence_count: int = 0
    critical_frontier_ignore_count: int = 0
    goal_relevant_action_count: int = 0
    total_autonomous_commits: int = 0
    ndm_decision_causal_coverage: float = 0.0
    recent_action_schema_version: int = RECENT_ACTION_SCHEMA_VERSION
    events: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    def recompute_coverage(self) -> float:
        # V17: NDM / (NDM + SAFE_LEGACY); unsafe excluded (run should block)
        denom = max(1, int(self.NDM_DECISION_COMMIT_COUNT) + int(self.SAFE_LEGACY_DECISION_COMMIT_COUNT))
        self.ndm_decision_causal_coverage = float(self.NDM_DECISION_COMMIT_COUNT) / float(denom)
        return self.ndm_decision_causal_coverage

    def rates(self) -> dict:
        turns = max(1, int(self.total_autonomous_commits) or int(self.pl_reasoning_event_count) or 1)
        visits = max(1, int(self.location_visit_count) or turns)
        return {
            "UNEXPLAINED_ACTION_RATE": float(self.unexplained_action_count) / turns,
            "UNRESOLVED_LEAD_ABANDON_RATE": float(self.lead_abandon_count) / turns,
            "SELF_RECOVERY_RATE": float(self.self_recovery_count) / turns,
            "MEANINGFUL_PROGRESS_RATE": float(self.meaningful_progress_count) / turns,
            "GOAL_DIRECTED_PROGRESS_RATE": float(self.goal_directed_progress_count) / turns,
            "LATERAL_EXPLORATION_PROGRESS_RATE": float(self.lateral_exploration_progress_count) / turns,
            "MAX_GOAL_DIRECTED_NO_PROGRESS_STREAK": int(self.max_goal_directed_no_progress_streak),
            "FRONTIER_SWITCH_RATE": float(self.frontier_switch_count) / turns,
            "FRONTIER_PERSISTENCE": int(self.frontier_persistence_count),
            "CRITICAL_FRONTIER_IGNORE_RATE": float(self.critical_frontier_ignore_count) / turns,
            "LOCATION_REVISIT_RATE": float(self.location_revisit_count) / visits,
            "GOAL_RELEVANT_ACTION_RATE": float(self.goal_relevant_action_count) / turns,
            "PROGRESSION_LOCAL_OPTIMUM_COUNT": int(self.progression_local_optimum_count),
            "NDM_DECISION_CAUSAL_COVERAGE": self.recompute_coverage(),
            "SAFE_FALLBACK_RATE": float(self.SAFE_LEGACY_DECISION_COMMIT_COUNT) / turns,
            "NDM_DECISION_COMMIT_COUNT": self.NDM_DECISION_COMMIT_COUNT,
            "SAFE_LEGACY_DECISION_COMMIT_COUNT": self.SAFE_LEGACY_DECISION_COMMIT_COUNT,
            "UNSAFE_LEGACY_DECISION_COMMIT_COUNT": self.UNSAFE_LEGACY_DECISION_COMMIT_COUNT,
            "REASONING_FALLBACK_COUNT": self.REASONING_FALLBACK_COUNT,
            "RUNTIME_CONTRACT_VIOLATION_COUNT": self.RUNTIME_CONTRACT_VIOLATION_COUNT,
            "SAFE_FALLBACK_FAILURE_COUNT": self.SAFE_FALLBACK_FAILURE_COUNT,
            "PROGRESS_EVENT_COUNT": self.progress_event_count,
            "SELECTED_ACTION_REASONING_ID_MISSING": self.selected_action_reasoning_id_missing,
            # deprecated: unsafe-only mirror
            "LEGACY_DECISION_COMMIT_COUNT": self.UNSAFE_LEGACY_DECISION_COMMIT_COUNT,
        }


class NaturalDecisionRuntime:
    """Session-scoped production NDM controller."""

    def __init__(self):
        self.enabled = False
        self.required = False
        self.active = False
        self.pipeline: Optional[NaturalDecisionPipeline] = None
        self.boundary: Optional[ReasoningKnowledgeBoundary] = None
        self.leads: Optional[LeadTracker] = None
        self.hypotheses: Optional[HypothesisTracker] = None
        self.kp_policy: Optional[KPInterventionPolicy] = None
        self.intervention_runtime = InterventionRuntimeState()
        self.telemetry = NDMTelemetry()
        self.config_hash = ""
        self.implementation_commit = ""
        self._emitted_reasoning_ids: set[str] = set()
        self._candidate_sets: dict[str, set[str]] = {}
        self._started_at = ""

    def bootstrap(
        self,
        state: dict,
        *,
        enabled: bool = True,
        required: bool = True,
        implementation_commit: str = "",
        known_facts: Optional[Sequence[Mapping[str, Any]]] = None,
    ) -> dict:
        self.enabled = bool(enabled)
        self.required = bool(required)
        self.implementation_commit = str(implementation_commit or "")
        cfg = {"enabled": self.enabled, "required": self.required, "version": "natural_decision_v1"}
        self.config_hash = hashlib.sha256(
            repr(sorted(cfg.items())).encode("utf-8")
        ).hexdigest()[:16]
        if not self.enabled:
            if self.required:
                raise NDMInitFailure("NATURAL_DECISION_REQUIRED but enabled=false")
            return self._stamp_state(state, active=False)

        try:
            facts = list(known_facts or [])
            self.boundary = ReasoningKnowledgeBoundary(facts)
            self.leads = LeadTracker(self.boundary)
            self.hypotheses = HypothesisTracker()
            self.pipeline = NaturalDecisionPipeline(
                boundary=self.boundary,
                lead_tracker=self.leads,
                hypothesis_tracker=self.hypotheses,
            )
            self.kp_policy = KPInterventionPolicy(boundary=self.boundary)
            self.active = True
            self.telemetry.NATURAL_DECISION_RUNTIME_ACTIVE = True
            self.telemetry.s_level_authority = DECISION_SOURCE_NDM
            self.telemetry.legacy_stall_detector_primary = False
            self._started_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            event = {
                "event_type": "NATURAL_DECISION_RUNTIME_STARTED",
                "version": "natural_decision_v1",
                "config_hash": self.config_hash,
                "implementation_commit": self.implementation_commit,
                "enabled": True,
                "required": self.required,
            }
            self.telemetry.events.append(event)
            return self._stamp_state(state, active=True, start_event=event)
        except Exception as exc:
            self.active = False
            if self.required:
                raise NDMInitFailure(f"NATURAL_DECISION_INIT_FAILED: {exc}") from exc
            raise

    def _stamp_state(self, state: dict, *, active: bool, start_event: Optional[dict] = None) -> dict:
        runtime = state.setdefault("director_v2", {})
        runtime["natural_decision_v1"] = bool(active)
        runtime["NATURAL_DECISION_RUNTIME_ACTIVE"] = bool(active)
        runtime["s_level_authority"] = DECISION_SOURCE_NDM if active else "legacy_stall_detector"
        runtime["legacy_stall_detector_primary"] = not bool(active)
        runtime["natural_decision"] = runtime.get("natural_decision") or {}
        runtime["natural_decision"].update({
            "enabled": self.enabled,
            "required": self.required,
            "config_hash": self.config_hash,
            "implementation_commit": self.implementation_commit,
        })
        ndm = state.setdefault("ndm_runtime", {})
        ndm.update({
            "active": bool(active),
            "required": self.required,
            "config_hash": self.config_hash,
            "telemetry": self.telemetry.to_dict(),
        })
        if start_event:
            logs = state.setdefault("ndm_event_log", [])
            logs.append(dict(start_event))
        return state

    def observe_stall_signals(self, stall: Mapping[str, Any]) -> dict:
        """StallDetector may supply features only — never authority."""
        return {
            "no_progress_streak": int(stall.get("no_progress_streak") or 0),
            "signals": list(stall.get("signals") or []),
            "same_action_streak": int(stall.get("same_action_streak") or 0),
            "roundtrip_count": int(stall.get("roundtrip_count") or 0),
        }

    def reject_legacy_s_level_write(self, *, from_level: str, to_level: str, source: str) -> None:
        if self.active and source not in {DECISION_SOURCE_NDM, "natural_decision_v1"}:
            raise LegacySLevelCommitRejected(
                f"LEGACY_S_LEVEL_COMMIT_REJECTED: {source} tried {from_level}->{to_level}"
            )

    def decide(
        self,
        state: dict,
        *,
        actor_id: str,
        candidates: Sequence[Mapping[str, Any]],
        pl_state: Optional[PLReasoningState | Mapping[str, Any]] = None,
        recent_actions: Sequence[Mapping[str, Any]] = (),
        progress_events: Sequence[Mapping[str, Any]] = (),
        restore_location: str = "",
    ) -> dict:
        if not self.active or not self.pipeline:
            raise NDMInitFailure("NATURAL_DECISION_RUNTIME_ACTIVE=false")

        candidate_set_id = f"cset_{uuid.uuid4().hex[:12]}"
        enriched_candidates = []
        id_set: set[str] = set()
        for i, raw in enumerate(candidates):
            item = dict(raw)
            cid = str(item.get("candidate_id") or item.get("id") or f"cand_{i}")
            item["candidate_id"] = cid
            id_set.add(cid)
            if not str(item.get("reason") or "").strip():
                item["reason"] = str(item.get("expected_purpose") or item.get("selection_reason") or "candidate")
            enriched_candidates.append(item)
        self._candidate_sets[candidate_set_id] = id_set

        st = pl_state if isinstance(pl_state, PLReasoningState) else PLReasoningState.from_dict(
            pl_state or {"actor_id": actor_id, "known_facts": list(self.boundary.known_fact_ids if self.boundary else [])}
        )
        if not st.actor_id:
            st.actor_id = actor_id

        # Sync open leads into PL state
        if self.leads:
            open_hv = [f["frontier_id"] for f in self.leads.unresolved_high_value_frontier_set()]
            st.high_value_leads = open_hv

        decision_transaction_id = f"dtx_{uuid.uuid4().hex[:12]}"
        # V17: validate RecentAction context before pipeline (first failure → BLOCK)
        try:
            recent_canon = recent_actions_as_dicts(normalize_recent_actions(recent_actions or []))
        except RecentActionContractError as exc:
            self._emit_contract_violation(exc, decision_transaction_id=decision_transaction_id, module="reasoning.runtime")
            raise NDMRuntimeContractViolation(str(exc), evidence={"decision_transaction_id": decision_transaction_id}) from exc

        # Track progress events for telemetry completeness
        if progress_events:
            self.telemetry.progress_event_count += sum(1 for e in progress_events if isinstance(e, Mapping))

        try:
            result = self.pipeline.run_cycle(
                pl_states=[st],
                candidate_actions_by_actor={actor_id: enriched_candidates},
                recent_actions=recent_canon,
                progress_events=progress_events,
                restore_location=restore_location,
                use_group=False,
            )
            if result.mode == "REJECT":
                raise UnboundDecisionCommit("NDM rejected candidates")
            if result.mode in {"FAIL_CLOSED", "SAFE_FALLBACK_FAILURE"}:
                self.telemetry.SAFE_FALLBACK_FAILURE_COUNT += 1
                self.telemetry.events.append({
                    "event_type": "SAFE_FALLBACK_FAILURE",
                    "decision_transaction_id": decision_transaction_id,
                    "mode": result.mode,
                    "errors": list(result.errors or []),
                })
                raise SafeFallbackFailure(
                    f"pipeline mode={result.mode}",
                    evidence={"decision_transaction_id": decision_transaction_id, "errors": result.errors},
                )
            if result.mode == "SAFE_LEGACY_PROGRESSION":
                return self._commit_safe_legacy(
                    state, result, actor_id=actor_id, candidate_set_id=candidate_set_id,
                    decision_transaction_id=decision_transaction_id,
                    recent_actions=recent_canon,
                )
            selected = dict(result.selected_action or {})
            evidence = result.reasoning_evidence or {}
            reasoning_id = str(evidence.get("reasoning_id") or "")
            if not reasoning_id:
                # Build evidence if pipeline did not attach
                ev = build_reasoning_evidence(
                    actor_id=actor_id,
                    selection_reason=str(selected.get("reason") or ""),
                    considered_actions=enriched_candidates,
                    selected_action=selected,
                    reasoning_mode="PL",
                )
                reasoning_id = ev.reasoning_id
                evidence = ev.to_dict()
            if not str(selected.get("reason") or evidence.get("selection_reason") or "").strip():
                self.telemetry.unexplained_action_count += 1
                raise UnexplainedActionError("UNEXPLAINED_ACTION_PATH")

            selected_candidate_id = str(
                selected.get("candidate_id")
                or self._match_candidate_id(selected, enriched_candidates)
                or ""
            )
            if selected_candidate_id and selected_candidate_id not in id_set:
                raise UnboundDecisionCommit("selected_candidate_id not in candidate_set_id")

            selected.update({
                "reasoning_id": reasoning_id,
                "decision_source": DECISION_SOURCE_NDM,
                "candidate_set_id": candidate_set_id,
                "selected_candidate_id": selected_candidate_id,
                "decision_transaction_id": decision_transaction_id,
                "selection_reason": str(selected.get("reason") or evidence.get("selection_reason") or ""),
            })
            self._emitted_reasoning_ids.add(reasoning_id)
            self.telemetry.pl_reasoning_event_count += 1
            self.telemetry.events.append({
                "event_type": "PL_REASONING_COMPLETED",
                "reasoning_id": reasoning_id,
                "actor_id": actor_id,
                "decision_source": DECISION_SOURCE_NDM,
                "candidate_set_id": candidate_set_id,
                "selected_action": selected.get("action"),
                "selected_target": selected.get("target"),
                "selection_reason": selected.get("selection_reason"),
                "decision_transaction_id": decision_transaction_id,
            })

            # V18 progression convergence tick (additive; historical Raw untouched)
            from .progression_convergence import (
                ensure_progression_runtime,
                persist_progression_runtime,
                tick_progression_cycle,
            )
            prog = ensure_progression_runtime(state)
            prog_summary = tick_progression_cycle(
                prog,
                progress_events=progress_events,
                visible_goal_ids=list(st.high_value_leads or []),
                unresolved_lead_ids=list(st.high_value_leads or []),
                known_frontier_ids=list(st.high_value_leads or []),
                cycle=None,
                location=str(selected.get("location") or selected.get("target") or ""),
                selected_frontier_id=str(selected.get("frontier_id") or selected.get("target") or ""),
                goal_relevant_action=_action_goal_relevant(selected, st.high_value_leads or []),
            )
            persist_progression_runtime(state, prog)
            self._sync_progression_telemetry(prog)

            # KP assessment + S-level
            assessment = assess_party_progress(
                unresolved_leads=list(st.high_value_leads or []),
                available_frontiers=list(st.high_value_leads or []),
                recent_actions=recent_actions,
                progress_events=progress_events,
                current_hint_level=self.intervention_runtime.current_s_level,
                activity_stall=int(prog.dual_stall.activity_stall_streak),
                goal_convergence_stall=int(prog.dual_stall.goal_convergence_stall_streak),
                local_optimum=bool(prog_summary.get("local_optimum")),
                frontier_ignore_streak=int(prog.frontiers.frontier_ignore_streak),
            )
            self.telemetry.kp_progress_assessment_count += 1
            assessment_id = f"kpa_{uuid.uuid4().hex[:10]}"
            self.telemetry.events.append({
                "event_type": "KP_PROGRESS_ASSESSED",
                "assessment_id": assessment_id,
                "intervention_source": DECISION_SOURCE_NDM,
                **assessment.to_dict(),
            })
            if assessment.meaningful_progress_this_cycle:
                self.telemetry.meaningful_progress_count += 1
            if assessment.goal_directed_progress_this_cycle:
                self.telemetry.goal_directed_progress_count += 1
            if assessment.lateral_exploration_progress_this_cycle:
                self.telemetry.lateral_exploration_progress_count += 1
            if assessment.testing_valid_hypothesis or assessment.exploring_valid_alternative:
                self.telemetry.self_recovery_count += 1

            decision, self.intervention_runtime = self.kp_policy.decide(
                assessment,
                self.intervention_runtime,
                frontier_set=list(st.high_value_leads or []),
                restore_location=restore_location,
                stall_increment=stall_weight(assessment),
            )
            intervention_id = f"kpi_{uuid.uuid4().hex[:10]}"
            self.telemetry.events.append({
                "event_type": "KP_INTERVENTION_APPLIED",
                "intervention_id": intervention_id,
                "assessment_id": assessment_id,
                "intervention_source": DECISION_SOURCE_NDM,
                **decision.to_dict(),
            })
            self._apply_s_level(state, decision.s_level, intervention_id=intervention_id)

            if decision.s_level == 4 and result.frontier_set:
                selected.setdefault("s4_recovery_mode", "FRONTIER_SET_RECOVERY")
                runtime = state.setdefault("director_v2", {})
                runtime.setdefault("natural_decision", {})["frontier_set"] = list(
                    (result.frontier_set or {}).get("frontier_ids") or st.high_value_leads or []
                )
                if restore_location:
                    runtime["natural_decision"]["restore_location"] = restore_location

            selected["ndm_assessment_id"] = assessment_id
            selected["ndm_intervention_id"] = intervention_id
            self.assert_commit_bound(selected)
            self.telemetry.selected_action_with_ndm_reasoning_count += 1
            self.telemetry.NDM_DECISION_COMMIT_COUNT += 1
            self.telemetry.total_autonomous_commits += 1
            self.telemetry.fallback_streak = 0
            if self.pipeline and getattr(self.pipeline, "fallback", None):
                self.pipeline.fallback.reset_streak_on_success()
            self.telemetry.events.append({
                "event_type": "ACTION_SELECTED",
                "decision_source": DECISION_SOURCE_NDM,
                "reasoning_id": reasoning_id,
                "candidate_set_id": candidate_set_id,
                "selected_candidate_id": selected_candidate_id,
                "decision_transaction_id": decision_transaction_id,
                "action": selected.get("action"),
                "target": selected.get("target"),
            })
            self._stamp_state(state, active=True)
            return selected
        except (UnexplainedActionError, KnowledgeBoundaryError, UnboundDecisionCommit):
            raise
        except (NDMRuntimeContractViolation, SafeFallbackFailure):
            raise
        except FallbackUnboundedError as exc:
            self.telemetry.SAFE_FALLBACK_FAILURE_COUNT += 1
            raise SafeFallbackFailure(str(exc), evidence={"decision_transaction_id": decision_transaction_id}) from exc
        except Exception as exc:
            classified = classify_exception(
                exc,
                module="reasoning.runtime.decide",
                decision_transaction_id=decision_transaction_id,
            )
            self.telemetry.events.append({"event_type": "NDM_FAILURE_CLASSIFIED", **classified.to_dict()})
            if not classified.fallback_eligible or classified.error_class not in FALLBACK_ELIGIBLE:
                self._emit_contract_violation(
                    exc,
                    decision_transaction_id=decision_transaction_id,
                    module=classified.module,
                    classified=classified,
                )
                raise NDMRuntimeContractViolation(
                    classified.message or str(exc),
                    evidence=classified.to_dict(),
                ) from exc
            # Recoverable → SAFE_LEGACY (single shot; no recursion)
            return self._fallback_select(
                state,
                actor_id=actor_id,
                candidates=enriched_candidates,
                candidate_set_id=candidate_set_id,
                decision_transaction_id=decision_transaction_id,
                failure_reason=str(exc),
                failure_class=classified.error_class,
                recent_actions=recent_canon,
            )

    def _sync_progression_telemetry(self, prog) -> None:
        """Mirror V18 progression_convergence counters into NDMTelemetry."""
        self.telemetry.max_goal_directed_no_progress_streak = max(
            int(self.telemetry.max_goal_directed_no_progress_streak),
            int(prog.dual_stall.max_goal_convergence_stall_streak),
        )
        self.telemetry.progression_local_optimum_count = int(
            prog.goals.progression_local_optimum_count
        )
        self.telemetry.frontier_switch_count = int(prog.metrics.frontier_switch_count)
        self.telemetry.location_revisit_count = int(prog.metrics.location_revisit_count)
        self.telemetry.location_visit_count = int(prog.metrics.location_visit_count)
        self.telemetry.frontier_persistence_count = len(
            [f for f in prog.frontiers.frontiers.values() if f.status in ("ACTIVE", "DEFERRED")]
        )
        self.telemetry.critical_frontier_ignore_count = int(
            prog.frontiers.critical_frontier_ignore_count
        )
        self.telemetry.goal_relevant_action_count = int(prog.metrics.goal_relevant_action_count)

    def _match_candidate_id(self, selected: Mapping[str, Any], candidates: Sequence[Mapping[str, Any]]) -> str:
        sa = str(selected.get("action") or "")
        st = str(selected.get("target") or "")
        for c in candidates:
            if str(c.get("action") or "") == sa and str(c.get("target") or "") == st:
                return str(c.get("candidate_id") or "")
        return ""

    def _emit_contract_violation(
        self,
        exc: BaseException,
        *,
        decision_transaction_id: str = "",
        module: str = "",
        classified: Any = None,
    ) -> None:
        info = classified.to_dict() if classified is not None else classify_exception(
            exc, module=module, decision_transaction_id=decision_transaction_id
        ).to_dict()
        self.telemetry.RUNTIME_CONTRACT_VIOLATION_COUNT += 1
        self.telemetry.events.append({
            "event_type": "NDM_RUNTIME_CONTRACT_VIOLATION",
            **info,
        })

    def _commit_safe_legacy(
        self,
        state: dict,
        result: NaturalDecisionResult,
        *,
        actor_id: str,
        candidate_set_id: str,
        decision_transaction_id: str,
        recent_actions: Sequence[Mapping[str, Any]] = (),
        failure_class: str = "RECOVERABLE_REASONING_FAILURE",
    ) -> dict:
        # Re-validate contract before SAFE_LEGACY commit
        try:
            normalize_recent_actions(recent_actions or [])
        except RecentActionContractError as exc:
            self.telemetry.SAFE_FALLBACK_FAILURE_COUNT += 1
            self._emit_contract_violation(exc, decision_transaction_id=decision_transaction_id, module="reasoning.safe_legacy")
            raise SafeFallbackFailure(str(exc), evidence={"decision_transaction_id": decision_transaction_id}) from exc

        selected = dict(result.selected_action or {"action": "wait", "target": ""})
        fallback_id = f"fb_{uuid.uuid4().hex[:10]}"
        fb_payload = dict(result.fallback or {})
        selected.update({
            "decision_source": DECISION_SOURCE_SAFE_LEGACY,
            "candidate_set_id": candidate_set_id,
            "decision_transaction_id": decision_transaction_id,
            "reasoning_id": f"fallback_{uuid.uuid4().hex[:10]}",
            "selection_reason": "SAFE_LEGACY_PROGRESSION",
            "fallback": fb_payload,
            "fallback_id": fallback_id,
            "fallback_error_class": failure_class,
            "selected_candidate_id": str(selected.get("candidate_id") or selected.get("selected_candidate_id") or ""),
        })
        self.telemetry.SAFE_LEGACY_DECISION_COMMIT_COUNT += 1
        self.telemetry.SAFE_LEGACY_PROGRESSION_COUNT += 1
        self.telemetry.REASONING_FALLBACK_COUNT += 1
        self.telemetry.fallback_streak += 1
        self.telemetry.total_autonomous_commits += 1
        # Do NOT increment UNSAFE / deprecated LEGACY violation bucket
        self.telemetry.events.append({
            "event_type": "PL_REASONING_FALLBACK",
            "fallback_id": fallback_id,
            "fallback_mode": "SAFE_LEGACY_PROGRESSION",
            "fallback_reason": fb_payload.get("failure_reason") or failure_class,
            "fallback_error_class": failure_class,
            "decision_source": DECISION_SOURCE_SAFE_LEGACY,
            "decision_transaction_id": decision_transaction_id,
            "candidate_id": selected.get("selected_candidate_id"),
            "selected_action": selected.get("action"),
            "selected_target": selected.get("target"),
            "fallback_streak": self.telemetry.fallback_streak,
            "failure_reason": fb_payload.get("failure_reason"),
        })
        self._stamp_state(state, active=True)
        return selected

    def _fallback_select(
        self,
        state: dict,
        *,
        actor_id: str,
        candidates: Sequence[Mapping[str, Any]],
        candidate_set_id: str,
        decision_transaction_id: str,
        failure_reason: str,
        failure_class: str = "RECOVERABLE_REASONING_FAILURE",
        recent_actions: Sequence[Mapping[str, Any]] = (),
        _depth: int = 0,
    ) -> dict:
        if _depth > 0:
            self.telemetry.SAFE_FALLBACK_RECURSION_COUNT += 1
            self.telemetry.SAFE_FALLBACK_FAILURE_COUNT += 1
            raise SafeFallbackFailure(
                "SAFE_FALLBACK_RECURSION forbidden",
                evidence={"decision_transaction_id": decision_transaction_id},
            )
        try:
            fb = SafeLegacyProgression(self.boundary)
            selected, evidence = fb.select(
                candidates,
                failure_reason=failure_reason,
                recent_actions=recent_actions,
            )
        except Exception as exc:
            self.telemetry.SAFE_FALLBACK_FAILURE_COUNT += 1
            classified = classify_exception(exc, module="reasoning.safe_fallback", decision_transaction_id=decision_transaction_id)
            self.telemetry.events.append({"event_type": "SAFE_FALLBACK_FAILURE", **classified.to_dict()})
            raise SafeFallbackFailure(str(exc), evidence=classified.to_dict()) from exc
        result = NaturalDecisionResult(
            selected_action=selected or {"action": "wait", "target": "", "reason": "fallback_wait"},
            fallback=evidence.to_dict(),
            mode="SAFE_LEGACY_PROGRESSION",
        )
        return self._commit_safe_legacy(
            state, result, actor_id=actor_id, candidate_set_id=candidate_set_id,
            decision_transaction_id=decision_transaction_id,
            recent_actions=recent_actions,
            failure_class=failure_class,
        )

    def _apply_s_level(self, state: dict, level: int, *, intervention_id: str) -> None:
        runtime = state.setdefault("director_v2", {})
        stall = runtime.setdefault("stall", {})
        from_level = str(stall.get("intervention_level") or "S0")
        to_level = f"S{int(level)}"
        # Only NDM writes
        stall["intervention_level"] = to_level
        stall["s_level_authority"] = DECISION_SOURCE_NDM
        runtime["s_level_authority"] = DECISION_SOURCE_NDM
        runtime["legacy_stall_detector_primary"] = False
        self.telemetry.events.append({
            "event_type": "S_LEVEL_CHANGED",
            "from_level": from_level,
            "to_level": to_level,
            "authority": DECISION_SOURCE_NDM,
            "intervention_id": intervention_id,
            "intervention_source": DECISION_SOURCE_NDM,
        })

    def assert_commit_bound(self, action: Mapping[str, Any]) -> None:
        if not self.active:
            return
        source = str(action.get("decision_source") or "")
        rid = str(action.get("reasoning_id") or "")
        if not source or source not in ALLOWED_SOURCES:
            self.telemetry.selected_action_reasoning_id_missing += 1
            if source in LEGACY_SOURCES or source.startswith("legacy") or source == "unbound_legacy":
                self.telemetry.UNSAFE_LEGACY_DECISION_COMMIT_COUNT += 1
                self.telemetry.LEGACY_DECISION_COMMIT_COUNT = self.telemetry.UNSAFE_LEGACY_DECISION_COMMIT_COUNT
            raise UnboundDecisionCommit("UNBOUND_DECISION_COMMIT: missing/invalid decision_source")
        if source == DECISION_SOURCE_NDM:
            if not rid:
                self.telemetry.selected_action_reasoning_id_missing += 1
                raise UnboundDecisionCommit("UNBOUND_DECISION_COMMIT: missing reasoning_id")
            if rid not in self._emitted_reasoning_ids and not rid.startswith("fallback_"):
                # Allow if just emitted in same decide() before set update race
                if rid not in self._emitted_reasoning_ids:
                    self._emitted_reasoning_ids.add(rid)
            cset = str(action.get("candidate_set_id") or "")
            scid = str(action.get("selected_candidate_id") or "")
            if cset and scid and cset in self._candidate_sets:
                if scid not in self._candidate_sets[cset]:
                    raise UnboundDecisionCommit("UNBOUND_DECISION_COMMIT: candidate set mismatch")
        if source in LEGACY_SOURCES and source != DECISION_SOURCE_SAFE_LEGACY:
            self.telemetry.UNSAFE_LEGACY_DECISION_COMMIT_COUNT += 1
            self.telemetry.LEGACY_DECISION_COMMIT_COUNT = self.telemetry.UNSAFE_LEGACY_DECISION_COMMIT_COUNT
            raise UnboundDecisionCommit("LEGACY_DECISION_COMMIT forbidden under NDM authority")

    def mark_executed(self, action: Mapping[str, Any]) -> None:
        self.telemetry.events.append({
            "event_type": "ACTION_EXECUTED",
            "reasoning_id": action.get("reasoning_id"),
            "decision_source": action.get("decision_source"),
            "decision_transaction_id": action.get("decision_transaction_id"),
            "selected_action_event_id": action.get("transaction_id") or action.get("event_id"),
            "action": action.get("action"),
            "target": action.get("target"),
        })

    def record_lead_abandon(self, lead_id: str, *, old_status: str, new_status: str, reason: str, cycle: Any = None) -> None:
        self.telemetry.lead_abandon_count += 1
        self.telemetry.events.append({
            "event_type": "LEAD_STATUS_CHANGED",
            "lead_id": lead_id,
            "old_status": old_status,
            "new_status": new_status,
            "reason": reason,
            "last_referenced_cycle": cycle,
        })

    def metrics_snapshot(self) -> dict:
        snap = self.telemetry.to_dict()
        snap["rates"] = self.telemetry.rates()
        return snap


def _action_goal_relevant(selected: Mapping[str, Any], leads: Sequence[str]) -> bool:
    blob = " ".join(
        str(selected.get(k) or "")
        for k in ("target", "frontier_id", "lead_id", "goal_id", "action", "reason")
    )
    return any(str(lead) and str(lead) in blob for lead in (leads or []))


# Process-global for evaluation runner / smoke (tests may replace)
_ACTIVE_RUNTIME: Optional[NaturalDecisionRuntime] = None


def get_active_runtime() -> Optional[NaturalDecisionRuntime]:
    return _ACTIVE_RUNTIME


def set_active_runtime(runtime: Optional[NaturalDecisionRuntime]) -> None:
    global _ACTIVE_RUNTIME
    _ACTIVE_RUNTIME = runtime


def bootstrap_natural_decision(state: dict, **kwargs: Any) -> NaturalDecisionRuntime:
    rt = NaturalDecisionRuntime()
    rt.bootstrap(state, **kwargs)
    set_active_runtime(rt)
    return rt
