"""Measure the four PaddleOCR 2.8.1 model archives OcrPaddle's PP-Structure loads (CR-09; run with python -I).

PP-Structure (paddleocr 2.8.1, lang "en", layout + table + ocr, the kwargs OcrPaddle's side_env_worker passes)
fetches four .tar archives from paddleocr.bj.bcebos.com at first use and keeps only the members ending in
.pdiparams, .pdiparams.info and .pdmodel, renamed inference.<suffix> (paddleocr/ppocr/utils/network.py maybe_download).
The URLs below are paddleocr 2.8.1's own MODEL_URLS for those four, and the folders are the ones its
confirm_model_dir_url computes under ~/.paddleocr/whl. Nothing at those URLs carries a revision, so the bytes are
pinned here by sha256: each archive is downloaded, hashed, and the three members PaddleOCR keeps are hashed as it
would write them.

  python -I measure_ocrpaddle_models.py --out <dir> [--keep]    (--keep leaves the archives in <dir>/archives)
Writes <dir>/ocrpaddle_models_measured.json; last line OCRPADDLE-MODELS: MEASURED 4 | FAIL <why>.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

PADDLEOCR = "2.8.1"
MODELS = {  # key: (url, folder under ~/.paddleocr/whl, the paddleocr argument it feeds)
    "det": ("https://paddleocr.bj.bcebos.com/PP-OCRv3/english/en_PP-OCRv3_det_infer.tar",
            "det/en/en_PP-OCRv3_det_infer", "det_model_dir"),
    "rec": ("https://paddleocr.bj.bcebos.com/PP-OCRv4/english/en_PP-OCRv4_rec_infer.tar",
            "rec/en/en_PP-OCRv4_rec_infer", "rec_model_dir"),
    "table": ("https://paddleocr.bj.bcebos.com/ppstructure/models/slanet/en_ppstructure_mobile_v2.0_SLANet_infer.tar",
              "table/en_ppstructure_mobile_v2.0_SLANet_infer", "table_model_dir"),
    "layout": ("https://paddleocr.bj.bcebos.com/ppstructure/models/layout/picodet_lcnet_x1_0_fgd_layout_infer.tar",
               "layout/picodet_lcnet_x1_0_fgd_layout_infer", "layout_model_dir"),
}
KEEP = (".pdiparams", ".pdiparams.info", ".pdmodel")  # maybe_download's tar_file_name_list, in its order


def members(data: bytes) -> dict[str, dict]:
    """The files maybe_download writes from this archive: for each member, the LAST suffix in KEEP that its name
    ends with names the output (its loop overwrites), exactly as paddleocr 2.8.1 does."""
    out: dict[str, dict] = {}
    with tarfile.open(fileobj=io.BytesIO(data), mode="r") as tar:
        for m in tar.getmembers():
            name = None
            for suf in KEEP:
                if m.name.endswith(suf):
                    name = "inference" + suf
            if name is None:
                continue
            f = tar.extractfile(m)
            if f is None:
                continue
            body = f.read()
            out[name] = {"member": m.name, "bytes": len(body), "sha256": hashlib.sha256(body).hexdigest()}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--keep", action="store_true")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    res: dict = {"paddleocr": PADDLEOCR, "measured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "models": {}}
    for key, (url, folder, arg) in MODELS.items():
        try:
            with urllib.request.urlopen(url, timeout=300) as r:
                data = r.read()
        except Exception as exc:  # noqa: BLE001
            print(f"OCRPADDLE-MODELS: FAIL {key}: {url} not downloaded ({type(exc).__name__}: {exc})")
            return 1
        mem = members(data)
        if set(mem) != {"inference.pdiparams", "inference.pdiparams.info", "inference.pdmodel"}:
            print(f"OCRPADDLE-MODELS: FAIL {key}: archive has {sorted(mem)}, not the three files PaddleOCR keeps")
            return 1
        res["models"][key] = {"url": url, "file_name": url.rsplit("/", 1)[-1], "bytes": len(data),
                              "sha256": hashlib.sha256(data).hexdigest(), "folder": folder, "paddleocr_arg": arg,
                              "members": mem}
        if a.keep:
            (a.out / "archives").mkdir(exist_ok=True)
            (a.out / "archives" / url.rsplit("/", 1)[-1]).write_bytes(data)
        print(f"{key:<7} {res['models'][key]['sha256']}  {len(data):>10}  {url}")
        for n, m in sorted(mem.items()):
            print(f"        {m['sha256']}  {m['bytes']:>10}  {folder}/{n}")
    (a.out / "ocrpaddle_models_measured.json").write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print("OCRPADDLE-MODELS: MEASURED 4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
