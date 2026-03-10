import pipelines.base as base


def test_resolve_column_question_counts_prefers_detected_counts():
    left, right = base._resolve_column_question_counts(
        total_count=12,
        left_detected=6,
        right_detected=6,
    )
    assert (left, right) == (6, 6)


def test_resolve_column_question_counts_falls_back_to_balanced_split():
    left, right = base._resolve_column_question_counts(
        total_count=11,
        left_detected=0,
        right_detected=0,
    )
    assert (left, right) == (6, 5)


def test_resolve_column_question_counts_rebalances_when_detected_sum_differs():
    left, right = base._resolve_column_question_counts(
        total_count=10,
        left_detected=2,
        right_detected=20,
    )
    assert left + right == 10
    assert left >= 1 and right >= 1
