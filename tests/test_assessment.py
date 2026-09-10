import pytest

from hy3_oj.core.assessment import assess, explanation_hash
from hy3_oj.core.schemas import ProcessReview, ReviewStep, StepVerdict, ProcessStatus, CombinedStatus


def review_for(text, failed=False):
    return ProcessReview(explanation_sha256=explanation_hash(text),
        step_verdicts=[StepVerdict(step=s, passed=not (failed and s == ReviewStep.COMPLEXITY_PROOF)) for s in ReviewStep])


@pytest.mark.parametrize("answer,failed,combined", [
    (True, False, CombinedStatus.BOTH_PASSED), (True, True, CombinedStatus.ANSWER_ONLY),
    (False, False, CombinedStatus.PROCESS_ONLY), (False, True, CombinedStatus.BOTH_FAILED),
])
def test_independent_axes(answer, failed, combined):
    result = assess(answer, review_for("proof", failed), "proof")
    assert result.answer_passed is answer
    assert result.combined_status == combined
    assert result.model_dump(mode="json")["combined_status"] == combined.value


def test_changed_explanation_requires_new_review():
    review = review_for("old proof")
    result = assess(True, review, "rewritten proof")
    assert result.answer_passed is True
    assert result.process_status == ProcessStatus.PENDING
    assert result.combined_status == CombinedStatus.PENDING


def test_missing_failed_and_legacy_reviews_do_not_change_ac():
    assert assess(True, None, "proof", review_error=True).process_status == ProcessStatus.ERROR
    assert assess(True, ProcessReview(), "proof").process_status == ProcessStatus.PENDING
    assert assess(None, review_for("proof"), "proof").combined_status == CombinedStatus.PENDING
