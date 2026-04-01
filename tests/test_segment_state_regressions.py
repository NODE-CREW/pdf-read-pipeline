import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw

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


def test_collect_visual_block_boxes_for_clip_returns_image_blocks_in_clip():
    class FakePage:
        def get_text(self, mode, sort=True):
            assert mode == "dict"
            assert sort is True
            return {
                "blocks": [
                    {"type": 1, "bbox": (300.0, 60.0, 560.0, 210.0)},
                    {"type": 1, "bbox": (20.0, 20.0, 80.0, 40.0)},
                    {"type": 0, "bbox": (310.0, 220.0, 450.0, 240.0)},
                ]
            }

    out = base.collect_visual_block_boxes_for_clip(
        FakePage(),
        clip_x0=289.5,
        clip_x1=595.0,
        raw_y0=0.0,
        raw_y1=253.0,
    )

    assert out == [(300.0, 60.0, 560.0, 210.0)]


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


def test_resolve_segment_clips_pulls_split_up_for_sparse_table_markers():
    problem_clip, choices_clip, choices_started = base.resolve_segment_clips_for_state(
        clip_y0=100.0,
        clip_y1=320.0,
        text_blocks=[
            (40.0, 110.0, 300.0, 120.0, "26. 문제"),
            (40.0, 130.0, 300.0, 140.0, "표시 결과로 옳지 않은 것은?"),
            (20.0, 200.0, 40.0, 210.0, "①"),
            (20.0, 228.0, 40.0, 238.0, "②"),
            (20.0, 256.0, 40.0, 266.0, "③"),
            (20.0, 284.0, 40.0, 294.0, "④"),
        ],
        choices_started=False,
    )

    assert problem_clip is not None
    assert choices_clip is not None
    assert choices_started is True
    assert problem_clip[1] <= 180.0
    assert choices_clip[0] <= 181.0


def test_is_probable_appendix_segment_detects_cbt_promo_and_answer_grid():
    text = "\n".join(
        [
            "전자문제집 CBT란?",
            "종이 문제집이 아닌 인터넷으로 문제를 풀고 자동으로 채점하며",
            "최신 수정된(오타, 오답, 규정변경) 자료와 해설은",
            "1 2 3 4 5 6 7 8 9 10",
            "④ ④ ① ③ ④ ③ ③ ③ ② ④",
            "11 12 13 14 15 16 17 18 19 20",
            "④ ② ② ④ ④ ② ④ ③ ① ③",
        ]
    )

    assert base.is_probable_appendix_segment(text) is True


def test_is_probable_appendix_segment_does_not_flag_normal_choices():
    text = "\n".join(
        [
            "① 기본 폼과 하위 폼을 연결할 필드의 데이터 형식은 같거나 호환되어야 한다.",
            "② 본 폼 내에 삽입된 다른 폼을 하위 폼이라 한다.",
            "③ 일대다 관계가 설정되어 있는 테이블들을 효과적으로 표시하기 위해 사용된다.",
            "④ '폼 분할' 도구를 이용하여 폼을 생성하면 하위 폼 컨트롤이 자동으로 삽입된다.",
        ]
    )

    assert base.is_probable_appendix_segment(text) is False


def test_is_probable_appendix_segment_does_not_flag_number_heavy_non_appendix_text():
    text = "\n".join(
        [
            "IPv4 주소는 32비트로 구성된다.",
            "10진수 255는 2진수로 11111111이다.",
            "16진수 FF는 10진수 255와 같다.",
        ]
    )

    assert base.is_probable_appendix_segment(text) is False


def test_is_sparse_choice_marker_text_detects_marker_only_choices():
    assert base.is_sparse_choice_marker_text("①\n②\n③\n④")
    assert not base.is_sparse_choice_marker_text("① 보기A\n② 보기B")


def test_merge_sparse_choice_marker_lines_with_ocr_rows():
    out = base.merge_sparse_choice_marker_lines_with_ocr_rows(
        marker_text="①\n②\n③\n④",
        ocr_rows=[
            "0  #  #",
            "123,456  #.#  123.5",
            "100  ##,##  100,00",
            "12345  #,###  12,345",
        ],
    )

    assert "① 0 # #" in out
    assert "② 123,456 #.# 123.5" in out
    assert "③ 100 ##,## 100,00" in out
    assert "④ 12345 #,### 12,345" in out


def test_select_dark_spans_from_boundaries_prefers_content_intervals():
    scores = {
        (0, 20): 5,
        (20, 40): 1,
        (40, 90): 9,
        (90, 110): 2,
        (110, 160): 8,
    }

    out = base._select_dark_spans_from_boundaries(
        boundaries=[20, 40, 90, 110],
        limit=160,
        target_count=3,
        min_span_px=10,
        include_start_edge=True,
        include_end_edge=True,
        score_fn=lambda start, end: scores[(start, end)],
    )

    assert out == [(0, 20), (40, 90), (110, 160)]


def test_infer_symbol_mask_from_cell_image_recovers_hash_pattern():
    image = Image.new("L", (120, 40), 255)
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 8, 34, 28), fill=0)
    draw.rectangle((46, 24, 52, 31), fill=0)
    draw.rectangle((66, 8, 80, 28), fill=0)

    assert base.infer_symbol_mask_from_cell_image(image) == "#,#"


def test_merge_sparse_choice_row_candidates_prefers_more_structured_candidate():
    out = base.merge_sparse_choice_row_candidates(
        primary_rows=["", "123,456 #,# 123.5", "100 ##,## 100.00", "12345 #,### 12.345"],
        fallback_rows=["0 # #", "123,456 #.# 123.5", "100 고구고군 100,00", "12345 구꾼고구 12.345"],
    )

    assert out == [
        "0 # #",
        "123,456 #,# 123.5",
        "100 ##,## 100.00",
        "12345 #,### 12.345",
    ]


def test_merge_sparse_choice_row_candidates_prefers_structured_table_row_over_noisy_fallback():
    out = base.merge_sparse_choice_row_candidates(
        primary_rows=["123,456 #,# 123.5"],
        fallback_rows=["이 122.450 # # 1602.90"],
    )

    assert out == ["123,456 #,# 123.5"]


def test_enhance_question_texts_with_ocr_recovers_sparse_choice_text(monkeypatch):
    module5 = base.load_module_5()

    images = [
        module5.QuestionImageSet(
            index=1,
            qno=26,
            problem_image_paths=["/tmp/q26_problem.png"],
            choices_image_paths=["/tmp/q26_choices.png"],
        )
    ]
    texts = [
        module5.QuestionTextSet(
            index=1,
            qno=26,
            question_text="26. 문제",
            choices_text="①\n②\n③\n④",
        )
    ]

    monkeypatch.setattr(
        base,
        "ocr_sparse_choice_rows_from_image_paths",
        lambda image_paths, choice_count, ocr_lang="kor+eng": [
            "0 # #",
            "123,456 #.# 123.5",
            "100 ##,## 100,00",
            "12345 #,### 12,345",
        ],
    )

    out = base.enhance_question_texts_with_ocr(
        module5=module5,
        question_images=images,
        question_texts=texts,
        min_chars=30,
        ocr_lang="kor+eng",
    )

    assert len(out) == 1
    assert "② 123,456 #.# 123.5" in out[0].choices_text
    assert out[0].question_text == "26. 문제"
