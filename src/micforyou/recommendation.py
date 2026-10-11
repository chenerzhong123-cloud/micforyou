"""Frame-chunk performance grading for the REAL-TSE live bridge.

The live bridge deliberately requires an explicit ``--frames-per-chunk``. This
module turns repeatable benchmark measurements into one of four explainable
levels (``fast`` / ``balanced`` / ``conservative`` / ``unsupported``) together
with the reasons behind every inclusion and exclusion. It never silently picks
a value at runtime and never fakes auto-tuning.
"""

from __future__ import annotations

from dataclasses import dataclass, field

FAST = "fast"
BALANCED = "balanced"
CONSERVATIVE = "conservative"
UNSUPPORTED = "unsupported"

# REAL-TSE tfmap_context_causal_100: 16 kHz model, 32 ms window, 8 ms hop.
# One model frame therefore advances 8 ms; the centered STFT must wait
# window - hop = 24 ms before the first frame is complete.
HOP_MS = 8.0
ALGORITHMIC_LATENCY_MS = 24.0

# The end-to-end latency target is p95 <= 500 ms. Everything after the bridge
# write (CoreAudio output buffer, BlackHole driver, Doubao capture, decode and
# UI) is not measured by this project, so the recommendation reserves headroom
# for it before accepting a candidate.
END_TO_END_TARGET_MS = 500.0
FAST_BALANCED_EXTERNAL_RESERVE_MS = 150.0
CONSERVATIVE_EXTERNAL_RESERVE_MS = 100.0

# RTF ceilings. RTF is measured over the complete 48->16->TSE->16->48 kHz path.
# A margin below 1.0 keeps the worker thread from slowly falling behind under
# normal desktop load, which remeasurement on the reference machine proved
# realistic.
FAST_MAX_RTF = 0.60
BALANCED_MAX_RTF = 0.80
CONSERVATIVE_MAX_RTF = 0.90

# A fast candidate must finish its p95 model call inside one chunk interval,
# i.e. the worker is idle-waiting for audio instead of audio waiting for the
# worker.
FAST_CALL_TO_CHUNK_RATIO = 1.0

# Percentiles from fewer calls describe the host, not the pipeline.
MIN_MODEL_CALLS = 10

THRESHOLDS: dict[str, float] = {
    "hop_ms": HOP_MS,
    "algorithmic_latency_ms": ALGORITHMIC_LATENCY_MS,
    "end_to_end_target_ms": END_TO_END_TARGET_MS,
    "fast_balanced_external_reserve_ms": FAST_BALANCED_EXTERNAL_RESERVE_MS,
    "conservative_external_reserve_ms": CONSERVATIVE_EXTERNAL_RESERVE_MS,
    "fast_max_rtf": FAST_MAX_RTF,
    "balanced_max_rtf": BALANCED_MAX_RTF,
    "conservative_max_rtf": CONSERVATIVE_MAX_RTF,
    "fast_call_to_chunk_ratio": FAST_CALL_TO_CHUNK_RATIO,
    "min_model_calls": MIN_MODEL_CALLS,
}


def estimate_core_latency_ms(
    frames_per_chunk: int,
    model_call_ms_p95: float,
    *,
    algorithmic_latency_ms: float = ALGORITHMIC_LATENCY_MS,
) -> float:
    """STFT wait + batch wait + p95 model call (the core-latency lower bound)."""
    return algorithmic_latency_ms + frames_per_chunk * HOP_MS + model_call_ms_p95


@dataclass(frozen=True)
class BenchmarkCandidate:
    """One benchmarked frames-per-chunk value over the complete bridge path."""

    frames_per_chunk: int
    rtf: float
    model_call_ms_p95: float
    model_call_ms_p50: float | None = None
    model_call_ms_max: float | None = None
    model_calls: int = 0
    input_samples: int | None = None
    output_samples: int | None = None
    nonfinite_samples: int = 0
    error: str | None = None

    @property
    def chunk_ms(self) -> float:
        return self.frames_per_chunk * HOP_MS

    def core_latency_ms(
        self, *, algorithmic_latency_ms: float = ALGORITHMIC_LATENCY_MS
    ) -> float:
        return estimate_core_latency_ms(
            self.frames_per_chunk,
            self.model_call_ms_p95,
            algorithmic_latency_ms=algorithmic_latency_ms,
        )

    def integrity_ok(self) -> bool:
        if self.error is not None:
            return False
        if self.nonfinite_samples:
            return False
        if self.input_samples is None or self.output_samples is None:
            return True
        return self.input_samples == self.output_samples


@dataclass(frozen=True)
class CandidateVerdict:
    frames_per_chunk: int
    valid: bool
    tier: str | None
    estimated_core_latency_ms: float | None
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class Recommendation:
    level: str
    frames_per_chunk: int | None
    estimated_core_latency_ms: float | None
    reasons: list[str] = field(default_factory=list)
    verdicts: list[CandidateVerdict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "frames_per_chunk": self.frames_per_chunk,
            "estimated_core_latency_ms": self.estimated_core_latency_ms,
            "reasons": list(self.reasons),
            "verdicts": [
                {
                    "frames_per_chunk": verdict.frames_per_chunk,
                    "valid": verdict.valid,
                    "tier": verdict.tier,
                    "estimated_core_latency_ms": verdict.estimated_core_latency_ms,
                    "reasons": list(verdict.reasons),
                }
                for verdict in self.verdicts
            ],
            "thresholds": dict(THRESHOLDS),
        }


def _classify(
    candidate: BenchmarkCandidate,
    *,
    algorithmic_latency_ms: float,
) -> CandidateVerdict:
    reasons: list[str] = []
    frames = candidate.frames_per_chunk
    if frames < 1:
        return CandidateVerdict(frames, False, None, None, ["frames below 1"])

    if candidate.error is not None:
        reasons.append(f"benchmark error: {candidate.error}")
    if candidate.nonfinite_samples:
        reasons.append(
            f"{candidate.nonfinite_samples} non-finite output samples"
        )
    if (
        candidate.input_samples is not None
        and candidate.output_samples is not None
        and candidate.input_samples != candidate.output_samples
    ):
        reasons.append(
            "output length does not match input length "
            f"({candidate.output_samples} vs {candidate.input_samples})"
        )
    if candidate.model_calls < MIN_MODEL_CALLS:
        reasons.append(
            f"only {candidate.model_calls} model calls; need >= {MIN_MODEL_CALLS} "
            "for stable percentiles"
        )
    if candidate.rtf != candidate.rtf or candidate.model_call_ms_p95 < 0:
        reasons.append("non-finite benchmark statistics")
        return CandidateVerdict(frames, False, None, None, reasons)
    if reasons:
        return CandidateVerdict(frames, False, None, None, reasons)

    core = candidate.core_latency_ms(algorithmic_latency_ms=algorithmic_latency_ms)
    fast_budget = END_TO_END_TARGET_MS - FAST_BALANCED_EXTERNAL_RESERVE_MS
    conservative_budget = END_TO_END_TARGET_MS - CONSERVATIVE_EXTERNAL_RESERVE_MS
    call_limit_ms = candidate.chunk_ms * FAST_CALL_TO_CHUNK_RATIO

    tier = None
    if (
        candidate.rtf <= FAST_MAX_RTF
        and candidate.model_call_ms_p95 <= call_limit_ms
        and core <= fast_budget
    ):
        tier = FAST
    if tier is None and candidate.rtf <= BALANCED_MAX_RTF and core <= fast_budget:
        tier = BALANCED
    if tier is None and candidate.rtf <= CONSERVATIVE_MAX_RTF and core <= conservative_budget:
        tier = CONSERVATIVE

    reasons.append(
        f"RTF {candidate.rtf:.3f} vs fast/balanced/conservative ceilings "
        f"{FAST_MAX_RTF}/{BALANCED_MAX_RTF}/{CONSERVATIVE_MAX_RTF}"
    )
    reasons.append(
        f"estimated core latency {core:.1f} ms vs budgets "
        f"{fast_budget:.0f} ms (fast/balanced) and {conservative_budget:.0f} ms "
        "(conservative), excluding unmeasured CoreAudio/BlackHole/Doubao time"
    )
    if candidate.model_call_ms_p95 > call_limit_ms:
        reasons.append(
            f"p95 model call {candidate.model_call_ms_p95:.1f} ms exceeds the "
            f"{candidate.chunk_ms:.0f} ms chunk interval"
        )
    if tier == FAST:
        reasons.append(
            f"qualifies as fast: RTF <= {FAST_MAX_RTF}, p95 call fits one chunk, "
            f"core latency within {fast_budget:.0f} ms"
        )
    elif tier == BALANCED:
        reasons.append(
            f"qualifies as balanced: RTF <= {BALANCED_MAX_RTF} with >= "
            f"{1 - BALANCED_MAX_RTF:.0%} margin, core latency within "
            f"{fast_budget:.0f} ms"
        )
    elif tier == CONSERVATIVE:
        reasons.append(
            f"qualifies as conservative only: RTF <= {CONSERVATIVE_MAX_RTF}, "
            f"core latency within {conservative_budget:.0f} ms"
        )
    else:
        reasons.append(
            "no tier: cannot sustain real time with a conservative margin nor "
            "stay inside the latency budget at this chunk size"
        )
    return CandidateVerdict(frames, True, tier, core, reasons)


def recommend(
    candidates: list[BenchmarkCandidate],
    *,
    algorithmic_latency_ms: float = ALGORITHMIC_LATENCY_MS,
) -> Recommendation:
    """Grade benchmarked chunk sizes into one explicit recommendation."""
    if not candidates:
        return Recommendation(
            UNSUPPORTED,
            None,
            None,
            ["no benchmark candidates supplied"],
            [],
        )

    seen: set[int] = set()
    unique: list[BenchmarkCandidate] = []
    for candidate in candidates:
        if candidate.frames_per_chunk in seen:
            continue
        seen.add(candidate.frames_per_chunk)
        unique.append(candidate)

    verdicts = [
        _classify(candidate, algorithmic_latency_ms=algorithmic_latency_ms)
        for candidate in unique
    ]
    by_frames = dict(zip([v.frames_per_chunk for v in verdicts], verdicts))

    fast_frames = [
        v.frames_per_chunk
        for v in verdicts
        if v.valid and v.tier == FAST
    ]
    balanced_frames = [
        v.frames_per_chunk
        for v in verdicts
        if v.valid and v.tier in {FAST, BALANCED}
    ]
    conservative_frames = [
        v.frames_per_chunk
        for v in verdicts
        if v.valid and v.tier in {FAST, BALANCED, CONSERVATIVE}
    ]

    if fast_frames:
        frames = min(fast_frames)
        reasons = [
            f"{frames} frames is the lowest-latency candidate with ample headroom "
            f"(RTF <= {FAST_MAX_RTF}, p95 call inside one chunk interval)"
        ]
    elif balanced_frames:
        frames = min(balanced_frames)
        reasons = [
            f"{frames} frames is the lowest-latency candidate with a conservative "
            f"RTF margin (<= {BALANCED_MAX_RTF}); no candidate met the fast tier"
        ]
    elif conservative_frames:
        frames = max(conservative_frames)
        reasons = [
            f"only conservative candidates remain; choosing {frames} frames "
            "(largest chunk, continuity over latency)"
        ]
    else:
        reasons = [
            "no candidate sustains real time with a conservative margin inside "
            "the latency budget; refusing to recommend a live configuration"
        ]
        reasons.extend(
            f"{v.frames_per_chunk} frames: {v.reasons[-1]}" for v in verdicts
        )
        return Recommendation(UNSUPPORTED, None, None, reasons, verdicts)

    chosen = by_frames[frames]
    reasons.append(
        "estimated core latency "
        f"{chosen.estimated_core_latency_ms:.1f} ms excludes unmeasured "
        "CoreAudio/BlackHole/Doubao time and queueing dynamics; confirm with "
        "tools/inference/measure_bridge_latency.py before live use"
    )
    reasons.append(
        "the live bridge still requires passing --frames-per-chunk explicitly; "
        "this recommendation does not change the bridge on its own"
    )
    level = chosen.tier or UNSUPPORTED
    return Recommendation(
        level, frames, chosen.estimated_core_latency_ms, reasons, verdicts
    )
