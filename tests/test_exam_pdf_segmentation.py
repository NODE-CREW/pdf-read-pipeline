from pipelines.exam_pdf import _detect_subject, _split_block_into_segments, split_stem_and_choices


def test_split_stem_and_choices_handles_inline_choices():
    stem, choices = split_stem_and_choices(
        "다음 중 옳은 것은? ① 첫째 ② 둘째 ③ 셋째 ④ 넷째"
    )

    assert stem == "다음 중 옳은 것은?"
    assert [choice.label for choice in choices] == ["①", "②", "③", "④"]
    assert choices[1].text == "둘째"


def test_split_stem_and_choices_returns_empty_choices_without_markers():
    stem, choices = split_stem_and_choices("설명만 있는 문장")

    assert stem == "설명만 있는 문장"
    assert choices == []


def test_detect_subject_accepts_spaced_colon_format():
    assert _detect_subject("2과목 : 소프트웨어 개발") == "소프트웨어 개발"


def test_split_block_into_segments_splits_multiple_questions_in_one_block():
    segments = _split_block_into_segments(
        "45 테이블의 작성시 필드에 관한 설명 중 가장 옳은 것은?\n① A\n② B\n46 다음 중 Recordset 개체가 가지고 있는 메서드가 아닌 것은?\n① Open"
    )

    assert len(segments) == 2
    assert segments[0].startswith("45 테이블의 작성시")
    assert segments[1].startswith("46 다음 중 Recordset")
