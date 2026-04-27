from pipelines.exam_pdf import BBox, detect_columns_for_blocks


def test_detect_columns_for_blocks_returns_two_columns_for_distinct_starts():
    blocks = [
        BBox(22.8, 60.0, 296.0, 180.0),
        BBox(22.8, 190.0, 296.0, 300.0),
        BBox(22.8, 320.0, 296.0, 430.0),
        BBox(301.9, 60.0, 575.0, 120.0),
        BBox(301.9, 140.0, 575.0, 260.0),
        BBox(301.9, 280.0, 575.0, 390.0),
    ]

    columns = detect_columns_for_blocks(blocks, 595.0)

    assert len(columns) == 2
    assert columns[0][1] < columns[1][0]


def test_detect_columns_for_blocks_returns_single_column_when_gap_is_small():
    blocks = [
        BBox(22.8, 60.0, 560.0, 160.0),
        BBox(25.0, 180.0, 558.0, 280.0),
        BBox(28.0, 300.0, 562.0, 400.0),
        BBox(26.0, 420.0, 559.0, 520.0),
    ]

    columns = detect_columns_for_blocks(blocks, 595.0)

    assert columns == [(0.0, 595.0)]
