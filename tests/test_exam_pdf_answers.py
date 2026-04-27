from pipelines.exam_pdf import parse_answer_grid_block, parse_inline_answer_pairs


def test_parse_answer_grid_block_reads_dense_answer_table():
    text = """1 2 3 4 5\n4 1 모두답 2,4 3\n"""

    answers = parse_answer_grid_block(text)

    assert answers == {1: "④", 2: "①", 3: "모두답", 4: "②,④", 5: "③"}


def test_parse_inline_answer_pairs_reads_single_line_pairs():
    answers = parse_inline_answer_pairs("1.① 2.③ 3.모두답 4.2,4")

    assert answers == {1: "①", 2: "③", 3: "모두답", 4: "②,④"}
