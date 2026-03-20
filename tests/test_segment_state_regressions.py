import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pipelines.base as base


def test_filter_page_noise_blocks_removes_header_and_footer_but_keeps_real_content():
    blocks = [
        (22.7, 21.8, 314.1, 35.0, "컴퓨터활용능력 1급         ◐2020년 07월 04일 필기 기출"),
        (54.2, 65.0, 113.3, 74.0, "$E$2:$E$13)}"),
        (376.4, 182.0, 500.4, 192.0, "3과목 : 데이터베이스 일반"),
    ]

    out = base.filter_page_noise_blocks(blocks, page_height=841.0)

    assert out == [(54.2, 65.0, 113.3, 74.0, "$E$2:$E$13)}")]


def test_filter_page_noise_blocks_drops_header_only_segment():
    blocks = [
        (22.7, 21.8, 186.9, 35.0, "컴퓨터활용능력 1급         ◐20"),
    ]

    out = base.filter_page_noise_blocks(blocks, page_height=841.0)

    assert out == []


def test_split_segment_text_respects_existing_choices_state():
    module5 = base.load_module_5()
    clip_text = "[페이지 설정] 대화 상자에서 '셀 오류 표시'를 '<공백>'\n으로 선택한다."

    question_text, choices_text, choices_started = base.split_segment_text_for_state(
        module5=module5,
        clip_text=clip_text,
        choices_started=True,
    )

    assert question_text == ""
    assert "셀 오류 표시" in choices_text
    assert choices_started is True


def test_resolve_segment_clips_keeps_followup_segment_as_choices_after_choices_started():
    problem_clip, choices_clip, choices_started = base.resolve_segment_clips_for_state(
        clip_y0=18.8,
        clip_y1=195.0,
        text_blocks=[
            (336.1, 65.0, 568.9, 84.8, "[페이지 설정] 대화 상자에서 '셀 오류 표시'를 '<공백>'"),
            (304.5, 90.6, 565.4, 121.1, "③ 인쇄 내용을 페이지의 가운데에 맞춰 인쇄하려면"),
        ],
        choices_started=True,
    )

    assert problem_clip is None
    assert choices_clip == (18.8, 195.0)
    assert choices_started is True
