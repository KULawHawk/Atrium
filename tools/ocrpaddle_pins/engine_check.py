"""Build OcrPaddle's PP-Structure from the PINNED model files only and read one synthetic page (CR-09; python -I).

Run inside a Python 3.12 environment holding the side-environment versions (side_env_versions_py3.12.txt, the
versions of Conclave conclave_lens_ocrpaddle/engine_requirements.txt). Steps: paddle.utils.run_check(); unpack the
measured archives' three kept members into <models>/<folder> and re-check every sha256 against the measurement;
build PPStructure with the side_env_worker kwargs (lang "en", layout, table, ocr, CPU) and EXPLICIT model folders
with every network connection refused, so nothing can be fetched; then det+rec must read the known words on a
text page, the table model must return a table holding them, and the full pipeline (layout first) must find
at least one region and every word on a realistic page with a heading, a paragraph and a ruled table.

  python -I engine_check.py --measured <dir with ocrpaddle_models_measured.json + archives/> --models <dir>
Last line: OCRPADDLE-ENGINE: PASS <words read> | FAIL <exact error>
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import socket
import sys
import tarfile
import traceback
from pathlib import Path

WORDS = ("TOTAL", "SCORE", "21")
ABSENT = "ZEBRA"  # on no test page: if it is ever "read", the word check is broken (negative control)


def tokens(texts) -> list[str]:
    """Whole alphanumeric tokens of RECOGNIZED text only, case kept (never keys, scores, boxes or html)."""
    import re
    return [t for t in re.split(r"[^A-Za-z0-9]+", " ".join(str(x) for x in texts)) if t]


def recognized_texts(regions) -> list[str]:
    """The text the pipeline recognized: each region's res[].text, plus a table's rec_res texts."""
    out: list[str] = []
    for region in regions or []:
        res = region.get("res")
        for item in res if isinstance(res, list) else [res]:
            if not isinstance(item, dict):
                continue
            if "text" in item:
                out.append(str(item["text"]))
            for pair in item.get("rec_res") or []:
                if pair:
                    out.append(str(pair[0]))
    return out


def judge_words(texts) -> tuple[list[str], bool]:
    toks = tokens(texts)
    return [w for w in WORDS if w in toks], ABSENT in toks


def deny_network() -> None:
    def refuse(*_a, **_k):
        raise OSError("network refused by engine_check (models must come from the pinned files)")
    socket.socket.connect = refuse  # type: ignore[assignment]
    socket.socket.connect_ex = refuse  # type: ignore[assignment]
    socket.getaddrinfo = refuse  # type: ignore[assignment]


def place(measured: Path, models: Path) -> dict[str, str]:
    m = json.loads((measured / "ocrpaddle_models_measured.json").read_text(encoding="utf-8"))
    dirs = {}
    for key, e in m["models"].items():
        data = (measured / "archives" / e["file_name"]).read_bytes()
        if hashlib.sha256(data).hexdigest() != e["sha256"]:
            raise SystemExit(f"OCRPADDLE-ENGINE: FAIL {e['file_name']} is not the measured bytes")
        target = models / e["folder"]
        target.mkdir(parents=True, exist_ok=True)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r") as tar:
            for name, mem in e["members"].items():
                body = tar.extractfile(tar.getmember(mem["member"])).read()
                if hashlib.sha256(body).hexdigest() != mem["sha256"]:
                    raise SystemExit(f"OCRPADDLE-ENGINE: FAIL {key}/{name} is not the measured bytes")
                (target / name).write_bytes(body)
        dirs[e["paddleocr_arg"]] = str(target)
    return dirs


def _bgr(img):
    import numpy as np
    return np.array(img)[:, :, ::-1].copy()  # BGR, as the worker hands the engine


def text_page():
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1000, 400), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=64)
    d.text((60, 80), "TOTAL SCORE", fill="black", font=font)
    d.text((60, 220), "21", fill="black", font=font)
    return _bgr(img)


def table_page():
    """A ruled 3x3 table of score words, the kind of crop the layout step hands the table model."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (900, 330), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=40)
    rows = (("Scale", "Raw", "T"), ("TOTAL", "21", "65"), ("SCORE", "14", "58"))
    for r in range(4):
        d.line((20, 20 + r * 100, 880, 20 + r * 100), fill="black", width=3)
    for c in range(4):
        d.line((20 + c * 286, 20, 20 + c * 286, 320), fill="black", width=3)
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            d.text((50 + c * 286, 45 + r * 100), cell, fill="black", font=font)
    return _bgr(img)


def document_page():
    """A realistic page: a heading, a paragraph and a ruled table, at roughly 150 dpi letter size."""
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1275, 1650), "white")
    d = ImageDraw.Draw(img)
    head, body = ImageFont.load_default(size=56), ImageFont.load_default(size=30)
    d.text((110, 120), "Scoring Summary", fill="black", font=head)
    para = ("The examinee completed every item of the inventory in one session.",
            "Raw scores were converted to T scores with the adult norm table.",
            "The TOTAL SCORE of 21 falls in the average range for this sample.",
            "No validity scale was elevated, so the profile is interpretable.")
    for i, line in enumerate(para):
        d.text((110, 260 + i * 48), line, fill="black", font=body)
    rows = (("Scale", "Raw", "T"), ("TOTAL", "21", "65"), ("SCORE", "14", "58"), ("Validity", "3", "50"))
    x0, y0, cw, rh = 110, 560, 330, 80
    for r in range(len(rows) + 1):
        d.line((x0, y0 + r * rh, x0 + 3 * cw, y0 + r * rh), fill="black", width=3)
    for c in range(4):
        d.line((x0 + c * cw, y0, x0 + c * cw, y0 + len(rows) * rh), fill="black", width=3)
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            d.text((x0 + 30 + c * cw, y0 + 22 + r * rh), cell, fill="black", font=body)
    return _bgr(img)


def word_check_selftest() -> str | None:
    """Prove the word check can fail: words only in keys, scores, boxes and html must count as unread,
    and words really recognized must all be found. Returns None on success, else why it failed."""
    unread = [
        {"type": "text", "score": 0.21, "bbox": [21, 21, 210, 121],
         "res": [{"text": "", "confidence": 0.21, "text_region": [[21, 21]], "TOTAL": 21, "SCORE": 21}]},
        {"type": "table", "score": 0.9, "bbox": [1, 2, 3, 4],
         "res": {"html": "<table><tr><td>TOTAL</td><td>SCORE</td><td>21</td></tr></table>",
                 "cell_bbox": [[21, 21]], "boxes": [[21]], "rec_res": []}},
    ]
    read = [
        {"type": "text", "res": [{"text": "The TOTAL SCORE of 21", "confidence": 0.9, "text_region": [[1, 1]]}]},
        {"type": "table", "res": {"html": "<table></table>", "rec_res": [["TOTAL", 0.99], ["21", 0.98]]}},
    ]
    got_u, ctrl_u = judge_words(recognized_texts(unread))
    got_r, ctrl_r = judge_words(recognized_texts(read))
    got_t, _ = judge_words(["total score 210"])  # wrong case / partial number: not a match
    if got_u or ctrl_u or ctrl_r or got_r != list(WORDS) or got_t:
        return f"unread gave {got_u}, read gave {got_r}, lowercase/partial gave {got_t}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--measured", type=Path, required=True)
    ap.add_argument("--models", type=Path, required=True)
    a = ap.parse_args()
    why = word_check_selftest()
    if why:
        print(f"OCRPADDLE-ENGINE: FAIL word-check self-test: {why}")
        return 1
    print("word-check self-test: nothing found where nothing was read; all found where read")
    try:
        import paddle
        paddle.utils.run_check()
        dirs = place(a.measured, a.models)
        deny_network()
        from paddleocr import PPStructure
        import paddleocr
        eng = PPStructure(lang="en", layout=True, table=True, ocr=True, show_log=False, use_gpu=False, **dirs)
        print(f"paddle {paddle.__version__}, paddleocr {paddleocr.__version__}: engine built from the pinned folders, network denied")
        fails = []
        # det + rec: every word on a plain text page
        boxes, rec, _ = eng.text_system(text_page())
        boxes, rec = boxes if boxes is not None else [], rec or []
        rtexts = [t for t, _s in rec]
        got, ctrl = judge_words(rtexts)
        print(f"det+rec: {len(boxes)} boxes, read {' '.join(rtexts)!r}")
        if len(got) != len(WORDS) or ctrl:
            fails.append(f"det+rec read {got} of {list(WORDS)}, control {ABSENT} found {ctrl}")
        # table model (SLANet) + det/rec inside the table
        tres, _ = eng.table_system(table_page(), True)
        html = tres.get("html") or ""
        cells = html.count("<td")
        print(f"table: {cells} cells: {html[:300]}")
        tgot, tctrl = judge_words(str(p[0]) for p in (tres.get("rec_res") or []) if p)
        if "<table" not in html or cells < 6 or len(tgot) != len(WORDS) or tctrl:
            fails.append(f"table gave {cells} cells, recognized words {tgot}, control {ABSENT} found {tctrl}")
        # layout model + the whole pipeline (what the reader runs), JUDGED on a realistic page
        lres, _ = eng.layout_predictor(document_page())
        lres = lres if lres is not None else []
        full = eng(document_page(), return_ocr_result_in_table=True)
        ftexts = recognized_texts(full)
        fgot, fctrl = judge_words(ftexts)
        kinds = sorted({str(r.get("type")) for r in full})
        print(f"layout: {len(lres)} regions on the document page; full pipeline: {len(full)} regions {kinds}; "
              f"recognized {ftexts!r}")
        if not lres or not full or len(fgot) != len(WORDS) or fctrl:
            fails.append(f"full pipeline on the document page: {len(lres)} layout regions, {len(full)} regions, "
                         f"recognized words {fgot}, control {ABSENT} found {fctrl}")
        if fails:
            print("OCRPADDLE-ENGINE: FAIL " + "; ".join(fails))
            return 1
        print(f"OCRPADDLE-ENGINE: PASS det+rec read {' '.join(got)}; table {cells} cells read {' '.join(tgot)}; "
              f"full pipeline {len(full)} regions {kinds} read {' '.join(fgot)}; control {ABSENT} absent")
        return 0
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        traceback.print_exc()
        print(f"OCRPADDLE-ENGINE: FAIL {type(exc).__name__}: {str(exc)[:500]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
