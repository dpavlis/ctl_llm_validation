"""Stage 5 — Candidate labeling, DPO pair construction, and composition controls."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

from .generator import Candidate, normalize_ctl
from .judge import JudgeVerdict
from .loader import SourceExample
from .runner import ExecResult


# ---------------------------------------------------------------------------
# Labeled candidate
# ---------------------------------------------------------------------------

@dataclass
class LabeledCandidate:
    candidate: Candidate
    exec_result: ExecResult
    verdict: Optional[JudgeVerdict]
    is_rejected: bool
    is_correct: bool


# ---------------------------------------------------------------------------
# DPO pair — matches the existing CTL_LoRA_DPO_data.jsonl format
# ---------------------------------------------------------------------------

@dataclass
class DPOPair:
    example_id: str
    system: Optional[str]
    prompt: str
    chosen: str
    rejected: str
    rejected_exec_level: str
    rejected_failure_modes: list[str] = field(default_factory=list)
    pairing_strategy: str = ""
    source_file: str = ""
    source_index: int = 0
    provenance: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Labeling (§7.1)
# ---------------------------------------------------------------------------

def label_candidate(
    candidate: Candidate,
    exec_result: ExecResult,
    verdict: Optional[JudgeVerdict],
    confidence_threshold: float = 0.6,
) -> LabeledCandidate:
    """
    Determine whether a candidate is rejected or correct.

      L1_fail / L2_fail           → always rejected
      L3_mismatch + no verdict    → rejected (execution is authoritative)
      L3_mismatch + verdict=correct (high conf) → correct via alternate output
          (will be dropped from pairing, not labeled rejected — §7.3)
      L3_pass + no/neutral verdict → correct
      L3_pass + verdict=incorrect (high conf) → judge overrides execution → rejected
    """
    level = exec_result.exec_level

    if level in ("L1_fail", "L2_fail"):
        return LabeledCandidate(candidate, exec_result, verdict,
                                is_rejected=True, is_correct=False)

    if level == "L3_mismatch":
        if verdict is not None and verdict.confidence >= confidence_threshold:
            if verdict.verdict == "correct":
                # Correct via a different valid output (e.g. added null safety) — drop
                return LabeledCandidate(candidate, exec_result, verdict,
                                        is_rejected=False, is_correct=True)
            if verdict.verdict == "partially_correct":
                # Ambiguous: not clearly wrong enough to be a useful rejected example;
                # not clearly right enough to be chosen. Drop from pairing — weak signal.
                return LabeledCandidate(candidate, exec_result, verdict,
                                        is_rejected=False, is_correct=False)
        return LabeledCandidate(candidate, exec_result, verdict,
                                is_rejected=True, is_correct=False)

    # L3_pass
    if (verdict is not None
            and verdict.verdict == "incorrect"
            and verdict.confidence >= confidence_threshold):
        return LabeledCandidate(candidate, exec_result, verdict,
                                is_rejected=True, is_correct=False)
    return LabeledCandidate(candidate, exec_result, verdict,
                            is_rejected=False, is_correct=True)


# ---------------------------------------------------------------------------
# Pair construction (§7.2)
# ---------------------------------------------------------------------------

_EXEC_RANK = {"L3_mismatch": 3, "L2_fail": 2, "L1_fail": 1}


def build_pairs(
    example: SourceExample,
    labeled: list[LabeledCandidate],
    strategy: str = "best_vs_worst",
    max_pairs: int = 3,
    chosen_override: Optional[str] = None,
) -> list[DPOPair]:
    """
    Build DPO pairs for one example from its labeled candidates.

    Returns [] when no informative contrast can be constructed.
    """
    chosen_text = normalize_ctl(chosen_override or example.reference)
    if not chosen_text:
        return []

    rejecteds = [lc for lc in labeled if lc.is_rejected]
    if not rejecteds:
        return []  # all candidates correct — no signal

    # Discard trivially short/empty rejecteds (length guard)
    rejecteds = [lc for lc in rejecteds if len(lc.candidate.text.strip()) > 20]

    # Discard sandbox-limitation failures — these are not model errors and would
    # produce misleading DPO signal (e.g. correct sequence usage failing because
    # the forge sandbox has no named sequences defined).
    _SANDBOX_STATUSES = {"UNRESOLVED_SEQUENCE"}
    rejecteds = [lc for lc in rejecteds if lc.exec_result.run_status not in _SANDBOX_STATUSES]
    if not rejecteds:
        return []

    # Dedup rejected texts
    seen: set[str] = set()
    deduped: list[LabeledCandidate] = []
    for lc in rejecteds:
        key = _norm(lc.candidate.text)
        if key not in seen:
            seen.add(key)
            deduped.append(lc)
    rejecteds = deduped

    # Drop chosen ≈ rejected
    chosen_key = _norm(chosen_text)
    rejecteds = [lc for lc in rejecteds if _norm(lc.candidate.text) != chosen_key]
    if not rejecteds:
        return []

    if strategy == "best_vs_worst":
        best = _most_informative(rejecteds)
        return [_make_pair(example, chosen_text, best, "best_vs_worst")] if best else []

    if strategy == "all_pairs":
        return [
            _make_pair(example, chosen_text, lc, "all_pairs")
            for lc in rejecteds[:max_pairs]
        ]

    return []


def _most_informative(rejecteds: list[LabeledCandidate]) -> Optional[LabeledCandidate]:
    """Prefer L3_mismatch > L2_fail > L1_fail; break ties by judge confidence."""
    if not rejecteds:
        return None
    return max(
        rejecteds,
        key=lambda lc: (
            _EXEC_RANK.get(lc.exec_result.exec_level, 0),
            lc.verdict.confidence if lc.verdict else 0.0,
        ),
    )


def _make_pair(
    example: SourceExample,
    chosen: str,
    lc: LabeledCandidate,
    strategy: str,
) -> DPOPair:
    v = lc.verdict
    return DPOPair(
        example_id=example.id,
        system=example.system,
        prompt=example.prompt,
        chosen=chosen,
        rejected=lc.candidate.text,
        rejected_exec_level=lc.exec_result.exec_level,
        rejected_failure_modes=v.failure_modes if v else [],
        pairing_strategy=strategy,
        source_file=example.source_file,
        source_index=example.source_index,
        provenance={
            "candidate_index": lc.candidate.index,
            "gen_meta": lc.candidate.gen_meta,
            "exec_level": lc.exec_result.exec_level,
            "run_status": lc.exec_result.run_status,
            "log_excerpt": lc.exec_result.log_excerpt,
            "output_diff": lc.exec_result.output_diff,
            "verdict": (
                {
                    "verdict":       v.verdict,
                    "confidence":    v.confidence,
                    "failure_modes": v.failure_modes,
                    "explanation":   v.explanation,
                    "minimal_fix":   v.minimal_fix,
                }
                if v else None
            ),
        },
    )


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


# ---------------------------------------------------------------------------
# Composition stats & caps (§8.4)
# ---------------------------------------------------------------------------

@dataclass
class CompositionStats:
    total: int = 0
    by_failure_mode: dict = field(default_factory=dict)
    by_component: dict = field(default_factory=dict)
    l1_count: int = 0

    def add(self, pair: DPOPair, component_type: str = ""):
        self.total += 1
        for fm in pair.rejected_failure_modes:
            self.by_failure_mode[fm] = self.by_failure_mode.get(fm, 0) + 1
        if component_type:
            self.by_component[component_type] = self.by_component.get(component_type, 0) + 1
        if pair.rejected_exec_level == "L1_fail":
            self.l1_count += 1

    def check_caps(
        self,
        max_fm_share: float = 0.25,
        max_comp_share: float = 0.40,
        max_l1_share: float = 0.20,
    ) -> list[str]:
        """Return a list of violation descriptions (empty if all caps satisfied)."""
        if self.total == 0:
            return []
        violations: list[str] = []
        for fm, count in self.by_failure_mode.items():
            share = count / self.total
            if share > max_fm_share:
                violations.append(
                    f"failure_mode '{fm}': {share:.1%} > cap {max_fm_share:.1%}"
                )
        for comp, count in self.by_component.items():
            share = count / self.total
            if share > max_comp_share:
                violations.append(
                    f"component '{comp}': {share:.1%} > cap {max_comp_share:.1%}"
                )
        l1_share = self.l1_count / self.total
        if l1_share > max_l1_share:
            violations.append(
                f"L1_fail share: {l1_share:.1%} > cap {max_l1_share:.1%}"
            )
        return violations
