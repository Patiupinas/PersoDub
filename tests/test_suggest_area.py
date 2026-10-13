"""The box the Erase tab opens with (app/scripts/suggest_area.py): tight around
the subtitle line, never a chain of boxes joined into half the frame."""
import importlib.util
import os

spec = importlib.util.spec_from_file_location(
    "suggest_area", os.path.join(os.path.dirname(__file__), "..", "app", "scripts", "suggest_area.py"))
sa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sa)

W, H = 1000, 1000


def test_box_hugs_the_line_with_a_small_margin():
    # (frame, xmin, xmax, ymin, ymax): one line, seen in three frames
    boxes = [(n, 300, 700, 850, 900) for n in range(3)]
    r = sa.pick_area(boxes, W, H, 3)
    assert r["found"] and r["area"] == [820, 930, 280, 720]


def test_a_chain_of_boxes_does_not_become_one_tall_band():
    # boxes stepping up the frame 15px apart would join into one 300px band
    chain = [(0, 100, 900, 600 + 15 * i, 640 + 15 * i) for i in range(10)]
    line = [(n, 300, 700, 850, 900) for n in range(4)]
    r = sa.pick_area(chain + line, W, H, 4)
    y0, y1, x0, x1 = r["area"]
    assert y1 - y0 <= H * (sa.MAX_LINE + 2 * sa.PAD_Y)
    assert (x0, x1) == (280, 720)


def test_a_box_too_tall_for_a_line_is_ignored_and_the_area_stays_in_frame():
    r = sa.pick_area([(0, 0, 1000, 500, 900)], W, H, 1)
    assert r["found"] is False and r["area"] == [750, 1000, 0, 1000]
    r = sa.pick_area([(0, 0, 1000, 960, 1000)], W, H, 1)
    assert r["area"][1] == 1000 and r["area"][2] == 0 and r["area"][3] == 1000
