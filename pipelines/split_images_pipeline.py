"""Compatibility facade for the split-images pipeline package.

Phase-2 package split:
- pipelines.base: core orchestration and shared logic
- pipelines.refine: image boundary refine helpers
- pipelines.db_ready: db-ready export helpers
- pipelines.ocr: OCR fallback helpers
"""

from .base import *  # noqa: F401,F403
