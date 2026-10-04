from __future__ import annotations

import math
from dataclasses import dataclass, field
from threading import Lock

#: Prometheus text exposition format version 0.0.4.
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

DEFAULT_BUCKETS: tuple[float, ...] = (
    0.005,
    0.01,
    0.025,
    0.05,
    0.1,
    0.25,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _labels(pairs: tuple[tuple[str, str], ...]) -> str:
    if not pairs:
        return ""
    inner = ",".join(f'{k}="{_escape(v)}"' for k, v in pairs)
    return "{" + inner + "}"


def _render_value(value: float) -> str:
    if math.isinf(value):
        return "+Inf"
    if value == int(value) and abs(value) < 1e15:
        return str(int(value))
    return repr(value)


@dataclass
class Histogram:
    """Cumulative histogram: bucket counts, total sum and observation count."""

    buckets: tuple[float, ...] = DEFAULT_BUCKETS
    counts: dict[float, int] = field(default_factory=dict)
    total: float = 0.0
    count: int = 0

    def observe(self, value: float) -> None:
        self.count += 1
        self.total += value
        for bound in self.buckets:
            if value <= bound:
                self.counts[bound] = self.counts.get(bound, 0) + 1

    def render(self, name: str, labels: tuple[tuple[str, str], ...] = ()) -> list[str]:
        lines = []
        for bound in self.buckets:
            bucket_labels = labels + (("le", _render_value(bound)),)
            lines.append(f"{name}_bucket{_labels(bucket_labels)} {self.counts.get(bound, 0)}")
        inf_labels = labels + (("le", "+Inf"),)
        lines.append(f"{name}_bucket{_labels(inf_labels)} {self.count}")
        base = _labels(labels)
        lines.append(f"{name}_sum{base} {_render_value(self.total)}")
        lines.append(f"{name}_count{base} {self.count}")
        return lines


class MetricsRegistry:
    """Minimal counter / gauge / histogram registry.

    Hand-rolled rather than pulling in ``prometheus_client``: the coordinator needs a
    handful of series, and the runtime dependency list here is deliberately small.
    Output is standard Prometheus text format, so any scraper can read it.
    """

    def __init__(self) -> None:
        self._lock = Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], Histogram] = {}
        self._help: dict[str, str] = {}
        self._types: dict[str, str] = {}

    def describe(self, name: str, help_text: str) -> None:
        with self._lock:
            self._help[name] = help_text

    def increment(
        self, name: str, labels: tuple[tuple[str, str], ...] = (), amount: float = 1.0
    ) -> None:
        with self._lock:
            self._types.setdefault(name, "counter")
            key = (name, labels)
            self._counters[key] = self._counters.get(key, 0.0) + amount

    def set_gauge(self, name: str, value: float, labels: tuple[tuple[str, str], ...] = ()) -> None:
        with self._lock:
            self._types.setdefault(name, "gauge")
            self._gauges[(name, labels)] = value

    def observe(self, name: str, value: float, labels: tuple[tuple[str, str], ...] = ()) -> None:
        with self._lock:
            self._types.setdefault(name, "histogram")
            key = (name, labels)
            hist = self._histograms.get(key)
            if hist is None:
                hist = Histogram()
                self._histograms[key] = hist
            hist.observe(value)

    def counter_value(self, name: str, labels: tuple[tuple[str, str], ...] = ()) -> float:
        with self._lock:
            return self._counters.get((name, labels), 0.0)

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()
            self._help.clear()
            self._types.clear()

    def render(self) -> str:
        with self._lock:
            snapshot = {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": dict(self._histograms),
                "helps": dict(self._help),
                "types": dict(self._types),
            }

        lines: list[str] = []
        emitted: set[str] = set()

        def emit_header(name: str) -> None:
            if name in emitted:
                return
            emitted.add(name)
            help_text = snapshot["helps"].get(name)
            if help_text:
                lines.append(f"# HELP {name} {help_text}")
            lines.append(f"# TYPE {name} {snapshot['types'].get(name, 'untyped')}")

        series: list[tuple[str, tuple[tuple[str, str], ...], float]] = [
            (name, labels, value) for (name, labels), value in snapshot["counters"].items()
        ]
        series += [(name, labels, value) for (name, labels), value in snapshot["gauges"].items()]
        for name, labels, value in sorted(series, key=lambda item: (item[0], item[1])):
            emit_header(name)
            lines.append(f"{name}{_labels(labels)} {_render_value(value)}")

        for (name, labels), hist in sorted(
            snapshot["histograms"].items(), key=lambda kv: (kv[0][0], kv[0][1])
        ):
            emit_header(name)
            lines.extend(hist.render(name, labels))

        return "\n".join(lines) + "\n"


_registry: MetricsRegistry | None = None


def get_registry() -> MetricsRegistry:
    global _registry
    if _registry is None:
        _registry = MetricsRegistry()
    return _registry


def reset_registry() -> None:
    """Drop all series (test isolation)."""
    global _registry
    _registry = None
