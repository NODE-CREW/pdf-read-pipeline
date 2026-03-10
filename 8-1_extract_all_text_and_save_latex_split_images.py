#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import base64
import json
import os
import sys
from pathlib import Path
from urllib import error, request

from pipelines.split_images_pipeline import *  # noqa: F401,F403
import pipelines.split_images_pipeline as _pipeline
import pipelines.base as _base


_OCR_SAAS_WARNED_KEYS: set[str] = set()


def _warn_saas_once(key: str, message: str) -> None:
    if key in _OCR_SAAS_WARNED_KEYS:
        return
    _OCR_SAAS_WARNED_KEYS.add(key)
    print(message, file=sys.stderr)


def _extract_text_from_saas_response(payload) -> str:
    if isinstance(payload, dict):
        for key in ("text", "result", "ocr_text", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()

        results = payload.get("results")
        if isinstance(results, list):
            merged = []
            for item in results:
                if not isinstance(item, dict):
                    continue
                text = item.get("text") or item.get("ocr_text") or item.get("result")
                if isinstance(text, str) and text.strip():
                    merged.append(text.strip())
            return "\n".join(merged).strip()
    return ""


def _ocr_text_from_image_paths_saas(image_paths, ocr_lang: str = "kor+eng") -> str:
    endpoint = (os.getenv("OCR_SAAS_ENDPOINT") or "").strip()
    api_key = (os.getenv("OCR_SAAS_API_KEY") or "").strip()
    if not endpoint or not api_key:
        return ""

    images = []
    for image_path in image_paths:
        try:
            raw = Path(image_path).read_bytes()
        except Exception:
            continue
        images.append(
            {
                "filename": Path(image_path).name,
                "content_base64": base64.b64encode(raw).decode("ascii"),
            }
        )

    if not images:
        return ""

    timeout_sec = int((os.getenv("OCR_SAAS_TIMEOUT_SEC") or "30").strip())
    body = {
        "lang": ocr_lang,
        "images": images,
    }
    data = json.dumps(body).encode("utf-8")
    req = request.Request(
        endpoint,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except error.HTTPError as exc:
        _warn_saas_once("saas_http_error", f"[OCR-SAAS] HTTP 오류({exc.code})로 SaaS OCR을 건너뜁니다.")
        return ""
    except Exception as exc:
        _warn_saas_once(
            "saas_runtime_error",
            f"[OCR-SAAS] SaaS OCR 호출 중 오류({type(exc).__name__})가 발생해 fallback 합니다.",
        )
        return ""

    return _extract_text_from_saas_response(payload)


def ocr_text_from_image_paths(image_paths, ocr_lang: str = "kor+eng") -> str:
    saas_text = _ocr_text_from_image_paths_saas(image_paths=image_paths, ocr_lang=ocr_lang)
    if saas_text:
        return saas_text
    return _base.ocr_text_from_image_paths(image_paths=image_paths, ocr_lang=ocr_lang)


def enhance_question_texts_with_ocr(
    module5,
    question_images,
    question_texts,
    min_chars: int = 30,
    ocr_lang: str = "kor+eng",
):
    original_ocr = _base.ocr_text_from_image_paths
    _base.ocr_text_from_image_paths = ocr_text_from_image_paths
    try:
        return _base.enhance_question_texts_with_ocr(
            module5=module5,
            question_images=question_images,
            question_texts=question_texts,
            min_chars=min_chars,
            ocr_lang=ocr_lang,
        )
    finally:
        _base.ocr_text_from_image_paths = original_ocr


def process_one_pdf(module5, pdf_path: str, output_root: Path, dpi: int) -> Path:
    return _pipeline.process_one_pdf(
        module5,
        pdf_path=pdf_path,
        output_root=output_root,
        dpi=dpi,
        enable_refine=True,
        enable_ocr=True,
        enable_db_ready=True,
    )


def main() -> None:
    _pipeline.main(enable_refine=True, enable_ocr=True, enable_db_ready=True)


if __name__ == "__main__":
    main()
