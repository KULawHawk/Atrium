"""Build OcrPaddle's PP-Structure from the PINNED model files only and read one synthetic page (CR-09; python -I).

Run inside a Python 3.12 environment holding the side-environment versions (side_env_versions_py3.12.txt, the
versions of Conclave conclave_lens_ocrpaddle/engine_requirements.txt). Steps: paddle.utils.run_check(); unpack the
measured archives' three kept members into <models>/<folder> and re-check every sha256 against the measurement;
build PPStructure with the side_env_worker kwargs (lang "en", layout, table, ocr, CPU) and EXPLICIT model folders
with every network connection refused, so nothing can be fetched; read a synthetic page with known words.

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


def page():
    import numpy as np
    from PIL import Image, ImageDraw, ImageFont
    img = Image.new("RGB", (1000, 400), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.load_default(size=64)
    d.text((60, 80), "TOTAL SCORE", fill="black", font=font)
    d.text((60, 220), "21", fill="black", font=font)
    return np.array(img)[:, :, ::-1].copy()  # BGR, as the worker hands the engine


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--measured", type=Path, required=True)
    ap.add_argument("--models", type=Path, required=True)
    a = ap.parse_args()
    try:
        import paddle
        paddle.utils.run_check()
        dirs = place(a.measured, a.models)
        deny_network()
        from paddleocr import PPStructure
        import paddleocr
        eng = PPStructure(lang="en", layout=True, table=True, ocr=True, show_log=False, use_gpu=False, **dirs)
        res = eng(page(), return_ocr_result_in_table=True)
        text = json.dumps(res, default=str)
        got = [w for w in WORDS if w in text.upper()]
        print(f"paddle {paddle.__version__}, paddleocr {paddleocr.__version__}, regions {len(res)}")
        if len(got) != len(WORDS):
            print(f"OCRPADDLE-ENGINE: FAIL read {got} of {list(WORDS)}: {text[:600]}")
            return 1
        print(f"OCRPADDLE-ENGINE: PASS {' '.join(got)}")
        return 0
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001
        traceback.print_exc()
        print(f"OCRPADDLE-ENGINE: FAIL {type(exc).__name__}: {str(exc)[:500]}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
