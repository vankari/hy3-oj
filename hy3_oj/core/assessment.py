"""只组合两条独立评估轴；不会重判代码或改写判题器结果。"""
import hashlib
import json
from pathlib import Path

from hy3_oj.core.schemas import Assessment, ProcessReview, ProcessStatus, ReviewMaterial, ReviewStep


def explanation_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_review_material(explanation: str, trace_file: str = "") -> ReviewMaterial:
    events = []
    if trace_file:
        try:
            for line in Path(trace_file).read_text(encoding="utf-8").splitlines():
                try:
                    event = json.loads(line)
                    if isinstance(event, dict) and event.get("state") not in ("JUDGED", "FINAL"):
                        events.append(event)
                except ValueError:
                    continue
        except OSError:
            pass
    return ReviewMaterial(explanation=explanation, trace_events=events)


def assess(answer_passed: bool | None, review: ProcessReview | None, explanation: str,
           review_error: bool = False) -> Assessment:
    status = ProcessStatus.PENDING
    if review_error:
        status = ProcessStatus.ERROR
    elif review and explanation and review.explanation_sha256 == explanation_hash(explanation):
        steps = {sv.step for sv in review.step_verdicts}
        if steps == set(ReviewStep) and len(review.step_verdicts) == len(ReviewStep):
            failed = bool(review.error_step or review.error_type or review.lucky_pass_flags
                          or any(not sv.passed for sv in review.step_verdicts))
            status = ProcessStatus.FAILED if failed else ProcessStatus.PASSED
    return Assessment(answer_passed=answer_passed, process_status=status)
