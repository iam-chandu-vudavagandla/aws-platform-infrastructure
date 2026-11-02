import json
import sys
from contextvars import ContextVar, Token
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Histogram,
    write_to_textfile,
)


def emit_event(
    event: str,
    *,
    level: str = "info",
    stream: TextIO | None = None,
    **fields: Any,
) -> None:
    """Write one structured operational event as JSON."""

    payload = dict(fields)
    payload.update(
        {
            "timestamp": (
                datetime.now(UTC)
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z")
            ),
            "level": level,
            "event": event,
        }
    )

    output = sys.stderr if stream is None else stream

    output.write(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    )
    output.flush()


class AgentMetrics:
    """Collect and export metrics for one CLI invocation."""

    def __init__(
        self,
        output_path: str | None,
    ) -> None:
        self.output_path = (
            Path(output_path)
            if output_path
            else None
        )

        self.registry = CollectorRegistry()

        self.command_count = Counter(
            "platform_agent_commands",
            "Completed platform-agent commands.",
            (
                "command",
                "status",
            ),
            registry=self.registry,
        )

        self.command_duration = Histogram(
            "platform_agent_command_duration_seconds",
            "Platform-agent command duration in seconds.",
            (
                "command",
            ),
            registry=self.registry,
        )

        self.tool_count = Counter(
            "platform_agent_tool_calls",
            "Completed platform-agent tool calls.",
            (
                "status",
                "tool",
            ),
            registry=self.registry,
        )

        self.tool_duration = Histogram(
            "platform_agent_tool_duration_seconds",
            "Platform-agent tool duration in seconds.",
            (
                "tool",
            ),
            registry=self.registry,
        )

    def record_command(
        self,
        *,
        command: str,
        status: str,
        duration_seconds: float,
    ) -> None:
        """Record one completed CLI command."""

        self.command_count.labels(
            command=command,
            status=status,
        ).inc()

        self.command_duration.labels(
            command=command,
        ).observe(duration_seconds)

    def record_tool(
        self,
        *,
        tool: str,
        status: str,
        duration_seconds: float,
    ) -> None:
        """Record one completed tool call."""

        self.tool_count.labels(
            status=status,
            tool=tool,
        ).inc()

        self.tool_duration.labels(
            tool=tool,
        ).observe(duration_seconds)

    def write(self) -> None:
        """Write collected metrics in Prometheus text format."""

        if self.output_path is None:
            return

        self.output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        write_to_textfile(
            str(self.output_path),
            self.registry,
        )


_ACTIVE_METRICS: ContextVar[AgentMetrics | None] = (
    ContextVar(
        "platform_agent_active_metrics",
        default=None,
    )
)


def activate_metrics(
    metrics: AgentMetrics,
) -> Token:
    """Make one metrics registry active in this context."""

    return _ACTIVE_METRICS.set(metrics)


def reset_metrics(token: Token) -> None:
    """Restore the previously active metrics registry."""

    _ACTIVE_METRICS.reset(token)


def record_tool_metrics(
    *,
    tool: str,
    status: str,
    duration_seconds: float,
) -> None:
    """Record tool metrics when a registry is active."""

    metrics = _ACTIVE_METRICS.get()

    if metrics is None:
        return

    metrics.record_tool(
        tool=tool,
        status=status,
        duration_seconds=duration_seconds,
    )
