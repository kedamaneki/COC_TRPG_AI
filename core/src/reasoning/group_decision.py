"""Group deliberation — proposals, responses, minority opinion preserved."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Mapping, Optional, Sequence


class ProposalResponse(str, Enum):
    AGREE = "agree"
    DISAGREE = "disagree"
    COUNTERPROPOSAL = "counterproposal"
    DEFER = "defer"


@dataclass
class PlayerProposal:
    actor_id: str
    proposal: dict
    reason: str
    confidence: float = 0.5
    risk: float = 0.5
    role: str = ""  # e.g. investigate / watch / alternative

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PlayerResponse:
    actor_id: str
    toward_actor_id: str
    response: ProposalResponse
    reason: str = ""
    counterproposal: Optional[dict] = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["response"] = self.response.value if isinstance(self.response, ProposalResponse) else str(self.response)
        return data


@dataclass
class GroupDecision:
    selected_proposal: dict
    executor: str
    minority_opinion: list = field(default_factory=list)
    reason: str = ""
    role_assignments: dict = field(default_factory=dict)
    auto_consensus_only: bool = False

    def to_dict(self) -> dict:
        return asdict(self)


class GroupDeliberation:
    """Multi-PL deliberation; consensus is not the only path."""

    def __init__(self):
        self.proposals: list[PlayerProposal] = []
        self.responses: list[PlayerResponse] = []

    def add_proposal(self, proposal: PlayerProposal | Mapping[str, Any]) -> PlayerProposal:
        obj = proposal if isinstance(proposal, PlayerProposal) else PlayerProposal(
            actor_id=str(proposal.get("actor_id") or ""),
            proposal=dict(proposal.get("proposal") or {}),
            reason=str(proposal.get("reason") or ""),
            confidence=float(proposal.get("confidence") if proposal.get("confidence") is not None else 0.5),
            risk=float(proposal.get("risk") if proposal.get("risk") is not None else 0.5),
            role=str(proposal.get("role") or ""),
        )
        if not obj.reason.strip():
            raise ValueError("proposal reason required")
        self.proposals.append(obj)
        return obj

    def add_response(self, response: PlayerResponse | Mapping[str, Any]) -> PlayerResponse:
        if isinstance(response, PlayerResponse):
            obj = response
        else:
            resp = response.get("response") or ProposalResponse.DEFER
            if not isinstance(resp, ProposalResponse):
                resp = ProposalResponse(str(resp))
            obj = PlayerResponse(
                actor_id=str(response.get("actor_id") or ""),
                toward_actor_id=str(response.get("toward_actor_id") or ""),
                response=resp,
                reason=str(response.get("reason") or ""),
                counterproposal=dict(response.get("counterproposal") or {}) or None,
            )
        self.responses.append(obj)
        return obj

    def decide(
        self,
        *,
        prefer_executor: str = "",
        allow_split_roles: bool = True,
    ) -> GroupDecision:
        if not self.proposals:
            raise ValueError("no proposals")

        # Score by confidence - risk, weighted by agreements
        agree_counts: dict[str, int] = {p.actor_id: 0 for p in self.proposals}
        minority: list[dict] = []
        for r in self.responses:
            if r.response == ProposalResponse.AGREE:
                agree_counts[r.toward_actor_id] = agree_counts.get(r.toward_actor_id, 0) + 1
            elif r.response in {ProposalResponse.DISAGREE, ProposalResponse.COUNTERPROPOSAL}:
                minority.append(r.to_dict())

        def score(p: PlayerProposal) -> float:
            return float(p.confidence) - float(p.risk) * 0.5 + agree_counts.get(p.actor_id, 0) * 0.3

        ranked = sorted(self.proposals, key=score, reverse=True)
        winner = ranked[0]
        for p in ranked[1:]:
            minority.append({"actor_id": p.actor_id, "proposal": p.proposal, "reason": p.reason})

        executor = prefer_executor or winner.actor_id
        roles: dict[str, str] = {}
        if allow_split_roles:
            for p in self.proposals:
                if p.role:
                    roles[p.actor_id] = p.role
            # Default complementary roles for non-executors
            for p in self.proposals:
                if p.actor_id == executor:
                    roles.setdefault(p.actor_id, p.role or "execute")
                else:
                    roles.setdefault(p.actor_id, p.role or "watch")

        return GroupDecision(
            selected_proposal=dict(winner.proposal),
            executor=executor,
            minority_opinion=minority,
            reason=winner.reason,
            role_assignments=roles,
            auto_consensus_only=False,
        )
