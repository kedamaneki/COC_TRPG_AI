"""Canonical RecentAction schema + legacy adapter (V17).

Consumers must not interpret legacy [action, target] lists directly.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, Mapping, Optional, Sequence, Union


RECENT_ACTION_SCHEMA_VERSION = 1


class RecentActionContractError(ValueError):
    """Raised for malformed recent-action shapes (runtime contract violation)."""

    code = "RUNTIME_CONTRACT_VIOLATION"
    error_class = "RUNTIME_CONTRACT_VIOLATION"

    def __init__(self, message: str, *, input_shape: str = "unknown", module: str = "reasoning.recent_action"):
        super().__init__(message)
        self.input_shape = input_shape
        self.module = module
        self.schema_version = RECENT_ACTION_SCHEMA_VERSION


@dataclass(frozen=True)
class RecentAction:
    schema_version: int = RECENT_ACTION_SCHEMA_VERSION
    actor_id: str = ""
    action: str = ""
    target: str = ""
    location: str = ""
    cycle: Optional[int] = None
    turn: Optional[int] = None
    result: Optional[str] = None
    source_event_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    def as_pair(self) -> tuple[str, str]:
        """Compatibility helper for pair-based scoring (does not reintroduce list writes)."""
        return (str(self.action or ""), str(self.target or ""))


def _shape_of(raw: Any) -> str:
    if raw is None:
        return "null"
    if isinstance(raw, (list, tuple)):
        return f"list[{len(raw)}]"
    if isinstance(raw, Mapping):
        return "dict"
    return type(raw).__name__


def normalize_recent_action(raw: Any) -> RecentAction:
    """Convert legacy or canonical input to RecentAction. Fail-closed on unknown shapes."""
    if isinstance(raw, RecentAction):
        if int(raw.schema_version) != RECENT_ACTION_SCHEMA_VERSION:
            raise RecentActionContractError(
                f"unsupported schema_version={raw.schema_version}",
                input_shape="RecentAction",
            )
        return raw

    if isinstance(raw, Mapping):
        version = raw.get("schema_version", None)
        if version is None:
            # legacy dict with action/target
            if "action" not in raw:
                raise RecentActionContractError(
                    "legacy dict missing required field action",
                    input_shape="dict",
                )
            return RecentAction(
                schema_version=RECENT_ACTION_SCHEMA_VERSION,
                actor_id=str(raw.get("actor_id") or ""),
                action=str(raw.get("action") or ""),
                target=str(raw.get("target") or ""),
                location=str(raw.get("location") or ""),
                cycle=_opt_int(raw.get("cycle")),
                turn=_opt_int(raw.get("turn")),
                result=_opt_str(raw.get("result")),
                source_event_id=_opt_str(raw.get("source_event_id")),
            )
        try:
            ver = int(version)
        except (TypeError, ValueError) as exc:
            raise RecentActionContractError(
                f"invalid schema_version={version!r}",
                input_shape="dict",
            ) from exc
        if ver != RECENT_ACTION_SCHEMA_VERSION:
            raise RecentActionContractError(
                f"unsupported schema_version={ver}",
                input_shape="dict",
            )
        if "action" not in raw or "target" not in raw:
            raise RecentActionContractError(
                "canonical RecentAction missing required field action/target",
                input_shape="dict",
            )
        if not isinstance(raw.get("action"), (str, int, float)) and raw.get("action") is not None:
            # allow stringifyables; reject nested structures
            if isinstance(raw.get("action"), (list, dict)):
                raise RecentActionContractError(
                    "action must be a scalar stringable",
                    input_shape="dict",
                )
        return RecentAction(
            schema_version=RECENT_ACTION_SCHEMA_VERSION,
            actor_id=str(raw.get("actor_id") or ""),
            action=str(raw.get("action") or ""),
            target=str(raw.get("target") or ""),
            location=str(raw.get("location") or ""),
            cycle=_opt_int(raw.get("cycle")),
            turn=_opt_int(raw.get("turn")),
            result=_opt_str(raw.get("result")),
            source_event_id=_opt_str(raw.get("source_event_id")),
        )

    if isinstance(raw, (list, tuple)):
        if len(raw) != 2:
            raise RecentActionContractError(
                f"legacy recent action list must have length 2, got {len(raw)}",
                input_shape=_shape_of(raw),
            )
        a, t = raw[0], raw[1]
        if isinstance(a, (list, dict)) or isinstance(t, (list, dict)):
            raise RecentActionContractError(
                "legacy recent action elements must be scalar",
                input_shape=_shape_of(raw),
            )
        return RecentAction(
            schema_version=RECENT_ACTION_SCHEMA_VERSION,
            action=str(a or ""),
            target=str(t or ""),
        )

    raise RecentActionContractError(
        f"unsupported recent action shape: {type(raw).__name__}",
        input_shape=_shape_of(raw),
    )


def normalize_recent_actions(raw_seq: Optional[Sequence[Any]]) -> list[RecentAction]:
    if raw_seq is None:
        return []
    if not isinstance(raw_seq, (list, tuple)):
        raise RecentActionContractError(
            "recent_actions must be a sequence",
            input_shape=type(raw_seq).__name__,
        )
    return [normalize_recent_action(item) for item in raw_seq]


def recent_actions_as_dicts(actions: Sequence[RecentAction | Mapping[str, Any]]) -> list[dict]:
    out: list[dict] = []
    for item in actions:
        if isinstance(item, RecentAction):
            out.append(item.to_dict())
        else:
            out.append(normalize_recent_action(item).to_dict())
    return out


def make_recent_action(
    *,
    action: str,
    target: str = "",
    actor_id: str = "",
    location: str = "",
    cycle: Optional[int] = None,
    turn: Optional[int] = None,
    result: Optional[str] = None,
    source_event_id: Optional[str] = None,
) -> dict:
    """Canonical write helper for producers (StallDetector etc.)."""
    return RecentAction(
        schema_version=RECENT_ACTION_SCHEMA_VERSION,
        actor_id=str(actor_id or ""),
        action=str(action or ""),
        target=str(target or ""),
        location=str(location or ""),
        cycle=cycle,
        turn=turn,
        result=result,
        source_event_id=source_event_id,
    ).to_dict()


def _opt_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise RecentActionContractError(
            f"cycle/turn must be int-compatible, got {value!r}",
            input_shape="dict",
        ) from exc


def _opt_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    return str(value)
