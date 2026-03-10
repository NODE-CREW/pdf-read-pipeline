import pipelines.base as base


def test_extract_ocr_question_block_truncates_at_next_question_after_choices():
    text = "\n".join(
        [
            "1. 첫 번째 문제",
            "문제 본문",
            "@ 보기A",
            "@ 보기B",
            "@ 보기C",
            "@ 보기D",
            "2. 두 번째 문제",
            "두 번째 문제 본문",
        ]
    )

    out = base._extract_ocr_question_block(text, expected_qno=None)

    assert "1. 첫 번째 문제" in out
    assert "@ 보기D" in out
    assert "2. 두 번째 문제" not in out


def test_extract_ocr_question_block_uses_expected_question_number_when_available():
    text = "\n".join(
        [
            "1. 이전 문항",
            "잡음",
            "7. 대상 문항",
            "문제 본문",
            "@ 보기1",
            "@ 보기2",
            "@ 보기3",
            "@ 보기4",
            "8. 다음 문항",
        ]
    )

    out = base._extract_ocr_question_block(text, expected_qno=7)

    assert out.startswith("7. 대상 문항")
    assert "1. 이전 문항" not in out
    assert "8. 다음 문항" not in out


def test_split_ocr_question_and_choices_supports_at_markers():
    text = "\n".join(
        [
            "1. 문제",
            "설명 문장",
            "@ 보기A",
            "@ 보기B",
            "@ 보기C",
            "@ 보기D",
        ]
    )

    question_text, choices_text = base._split_ocr_question_and_choices(text)

    assert "설명 문장" in question_text
    assert "@ 보기A" in choices_text
    assert "@ 보기D" in choices_text


def test_split_ocr_question_and_choices_supports_symbol_choice_markers():
    text = "\n".join(
        [
            "1. 문제",
            "설명 문장",
            "© 보기A",
            "© 보기B",
            "© 보기C",
            "© 보기D",
        ]
    )

    question_text, choices_text = base._split_ocr_question_and_choices(text)

    assert "설명 문장" in question_text
    assert "© 보기A" in choices_text
    assert "© 보기D" in choices_text


def test_select_best_ocr_candidate_prefers_low_question_number_with_choices():
    candidate_q1 = "\n".join(
        [
            "1. 첫 번째 문제",
            "문제 본문",
            "@ 보기A",
            "@ 보기B",
            "@ 보기C",
            "@ 보기D",
        ]
    )
    candidate_q7 = "\n".join(
        [
            "7. 일곱 번째 문제",
            "문제 본문",
            "@ 보기A",
            "@ 보기B",
            "@ 보기C",
            "@ 보기D",
        ]
    )

    out = base._select_best_ocr_candidate([candidate_q7, candidate_q1])

    assert out.startswith("1. 첫 번째 문제")


def test_split_ocr_text_by_question_starts_accepts_no_space_after_dot():
    text = "\n".join(
        [
            "7.다음 중 네트워크 관련 장비로 브리지(Bridge)에 관한 설명으로 옳지 않은 것은?",
            "@ 보기A",
            "8.다음 중 인터넷 기반 기술을 이용하여",
            "@ 보기A",
        ]
    )

    chunks = base._split_ocr_text_by_question_starts(text)

    assert [qno for qno, _ in chunks] == [7, 8]


def test_split_ocr_text_by_question_starts_accepts_slash_dot_for_7():
    text = "\n".join(
        [
            "/. 다음 중 네트워크 관련 장비로 브리지(Bridge)에 관한 설명으로 옳지 않은 것은?",
            "@ 보기A",
            "8. 다음 중 인터넷 기반 기술을 이용하여",
            "@ 보기A",
        ]
    )

    chunks = base._split_ocr_text_by_question_starts(text)

    assert [qno for qno, _ in chunks] == [7, 8]


def test_normalize_common_ocr_phrases_fixes_known_exam_patterns():
    raw = (
        "1. 다음 중 컴퓨터 및 정보기기에서 사용하는 펌웨어 Firmware)O\n"
        "관한 설명으로 22 것은?\n"
        "7. 다음 중 네트워크 관련 장비로 브리지(31006)에 관한 설명으로 올지 않은 것은?"
    )

    out = base._normalize_common_ocr_phrases(raw)

    assert "(Firmware)에" in out
    assert "옳은 것은?" in out
    assert "브리지(Bridge)" in out
    assert "옳지 않은 것은?" in out


def test_normalize_common_ocr_phrases_fixes_boot_record_avec_phrase():
    raw = "@ 주로 하드디스크의 부트 레코드 부분에 AVEC"

    out = base._normalize_common_ocr_phrases(raw)

    assert "주로 하드디스크의 부트 레코드 부분에 저장된다." in out


def test_normalize_common_ocr_phrases_fixes_number_system_choice_noise():
    raw = (
        "@ 16%!-=(Hexadecimal}= 0~9까지의 숫자와 A~FILAL 문지\n"
        "@ 2진수, 8진수, 16진수를 10진수 실수0030로 변환 하려면\n"
        "(3 10진수(0600130 정수를 2진수, 8진수, 16진수로 변환 히려면"
    )

    out = base._normalize_common_ocr_phrases(raw)

    assert "16진수(Hexadecimal)" in out
    assert "A~F의 문자" in out
    assert "10진수 실수로" in out
    assert "(3) 10진수의 정수를" in out
    assert "변환하려면" in out
    assert "나머지를 나머지를" not in out


def test_normalize_common_ocr_phrases_fixes_olji_typo_variants():
    raw = "다음 중 수의 표현에 있어 진법에 대한 설명으로 율지 않은 것은?"

    out = base._normalize_common_ocr_phrases(raw)

    assert "설명으로 옳지 않은 것은?" in out


def test_should_prefer_ocr_split_when_primary_question_contains_choice_lines():
    primary_q = "\n".join(
        [
            "1. 문제",
            "설명",
            "@ 보기A",
            "@ 보기B",
        ]
    )
    primary_c = "(3) 보기C"
    ocr_q = "1. 문제\n설명"
    ocr_c = "@ 보기A\n@ 보기B\n(3) 보기C"

    assert base._should_prefer_ocr_split(
        primary_question_text=primary_q,
        primary_choices_text=primary_c,
        ocr_question_text=ocr_q,
        ocr_choices_text=ocr_c,
    )
