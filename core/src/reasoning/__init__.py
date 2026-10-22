"""Natural TRPG Decision Model V1 — reasoning layer (design-approved).

Does not mutate Core/world truth. Proposes enriched decisions and KP intervention.
"""

from .pipeline import NaturalDecisionPipeline, run_natural_decision_cycle
from .evidence import ReasoningEvidence, build_reasoning_evidence
from .knowledge_boundary import (
    KnowledgeBoundaryError,
    ReasoningKnowledgeBoundary,
    KnownFactView,
    EpistemicKind,
)
from .lead_tracker import LeadTracker, LeadStatus
from .hypothesis_tracker import HypothesisTracker, HypothesisStatus
from .pl_state import PLReasoningState, FailureClass
from .pl_policy import PLDecisionPolicy
from .kp_assessment import KPProgressAssessment
from .kp_intervention import KPInterventionPolicy, InterventionLevel
from .frontier_recovery import FrontierRecoveryPolicy
from .group_decision import GroupDeliberation
from .safe_fallback import SafeLegacyProgression, REASONING_MODEL_FALLBACK
from .runtime import (
    NaturalDecisionRuntime,
    NDMInitFailure,
    UnboundDecisionCommit,
    bootstrap_natural_decision,
    DECISION_SOURCE_NDM,
)

__all__ = [
    "NaturalDecisionPipeline",
    "run_natural_decision_cycle",
    "ReasoningEvidence",
    "build_reasoning_evidence",
    "KnowledgeBoundaryError",
    "ReasoningKnowledgeBoundary",
    "KnownFactView",
    "EpistemicKind",
    "LeadTracker",
    "LeadStatus",
    "HypothesisTracker",
    "HypothesisStatus",
    "PLReasoningState",
    "FailureClass",
    "PLDecisionPolicy",
    "KPProgressAssessment",
    "KPInterventionPolicy",
    "InterventionLevel",
    "FrontierRecoveryPolicy",
    "GroupDeliberation",
    "SafeLegacyProgression",
    "REASONING_MODEL_FALLBACK",
    "NaturalDecisionRuntime",
    "NDMInitFailure",
    "UnboundDecisionCommit",
    "bootstrap_natural_decision",
    "DECISION_SOURCE_NDM",
]
