"""Typed agent trajectory representation and replay validation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .domain import JsonObject, SystemOutput

TrajectoryKind = Literal[
    "action",
    "observation",
    "state_transition",
    "tool_result",
    "termination",
]


@dataclass(frozen=True)
class TrajectoryEvent:
    step: int
    kind: TrajectoryKind
    name: str
    payload: JsonObject
    timestamp_utc: str | None = None

    def __post_init__(self) -> None:
        if self.step < 1:
            raise ValueError("Trajectory step must be >= 1.")
        if not self.name.strip():
            raise ValueError("Trajectory event name must not be empty.")


@dataclass(frozen=True)
class Trajectory:
    events: tuple[TrajectoryEvent, ...]

    def validate(self) -> None:
        if not self.events:
            raise ValueError("Trajectory must contain at least one event.")
        previous_step = 0
        terminated = False
        for event in self.events:
            if event.step < previous_step:
                raise ValueError("Trajectory steps must be non-decreasing.")
            if terminated:
                raise ValueError("No events are allowed after termination.")
            if event.kind == "termination":
                terminated = True
            previous_step = event.step

    @property
    def step_count(self) -> int:
        return max((event.step for event in self.events), default=0)

    @property
    def terminated(self) -> bool:
        return bool(self.events) and self.events[-1].kind == "termination"

    @property
    def tool_names(self) -> tuple[str, ...]:
        names = [
            event.name
            for event in self.events
            if event.kind in {"action", "tool_result"} and event.payload.get("tool_name")
        ]
        return tuple(names)

    def replay(self) -> tuple[JsonObject, ...]:
        self.validate()
        return tuple(
            {
                "step": event.step,
                "kind": event.kind,
                "name": event.name,
                "payload": event.payload,
                **({"timestamp_utc": event.timestamp_utc} if event.timestamp_utc else {}),
            }
            for event in self.events
        )

    @classmethod
    def from_system_output(cls, output: SystemOutput) -> Trajectory:
        events: list[TrajectoryEvent] = []
        for index, raw in enumerate(output.trace, start=1):
            kind = raw.get("kind", "action")
            if kind not in {
                "action",
                "observation",
                "state_transition",
                "tool_result",
                "termination",
            }:
                raise ValueError(f"Unsupported trajectory kind: {kind!r}")
            name = str(raw.get("name") or raw.get("tool_name") or kind)
            payload: JsonObject = dict(raw)
            events.append(
                TrajectoryEvent(
                    step=int(raw.get("step", index)),
                    kind=kind,
                    name=name,
                    payload=payload,
                    timestamp_utc=str(raw["timestamp_utc"]) if "timestamp_utc" in raw else None,
                )
            )
        trajectory = cls(tuple(events))
        if events:
            trajectory.validate()
        return trajectory

    @classmethod
    def from_events(cls, events: list[TrajectoryEvent]) -> Trajectory:
        trajectory = cls(tuple(events))
        trajectory.validate()
        return trajectory
