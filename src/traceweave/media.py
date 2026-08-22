from __future__ import annotations

import asyncio
import json
import shutil
from io import BytesIO
from typing import Any


async def analyze_media_locally(
    data: bytes, *, media_type: str, language: str = "all"
) -> list[dict[str, Any]]:
    """Run deterministic, fixed-command media tools before optional remote vision."""
    observations: list[dict[str, Any]] = []
    exiftool = shutil.which("exiftool")
    if exiftool:
        code, output = await _run_tool([exiftool, "-json", "-"], data)
        if code == 0 and output:
            try:
                payload = json.loads(output.decode("utf-8", errors="replace"))
            except (TypeError, ValueError):
                payload = []
            if isinstance(payload, list) and payload and isinstance(payload[0], dict):
                metadata = {
                    str(key): value
                    for key, value in payload[0].items()
                    if key not in {"SourceFile", "FileName", "Directory"}
                }
                if metadata:
                    observations.append(
                        {
                            "kind": "metadata:exiftool",
                            "text": json.dumps(metadata, ensure_ascii=False, default=str)[:8000],
                            "confidence": 0.75,
                            "importance": 35,
                            "rarity": 35,
                            "locator": {"tool": "exiftool"},
                        }
                    )

    if media_type.casefold().startswith("image/"):
        fingerprint = _perceptual_hash(data)
        if fingerprint:
            observations.append(
                {
                    "kind": "media:phash",
                    "text": fingerprint,
                    "confidence": 1.0,
                    "importance": 20,
                    "rarity": 20,
                    "locator": {"algorithm": "phash"},
                }
            )
        metrics = _image_metrics(data)
        if metrics:
            observations.append(
                {
                    "kind": "media:image_metrics",
                    "text": json.dumps(metrics, ensure_ascii=False),
                    "confidence": 1.0,
                    "importance": 15,
                    "rarity": 10,
                    "locator": {"tool": "opencv"},
                }
            )
        tesseract = shutil.which("tesseract")
        if tesseract:
            requested = _ocr_language(language)
            code, output = await _run_tool(
                [tesseract, "stdin", "stdout", "-l", requested, "--psm", "11"], data
            )
            if code != 0 and requested != "eng":
                code, output = await _run_tool(
                    [tesseract, "stdin", "stdout", "-l", "eng", "--psm", "11"], data
                )
            text = "\n".join(
                line.strip() for line in output.decode(errors="replace").splitlines() if line.strip()
            )
            if code == 0 and text:
                observations.append(
                    {
                        "kind": "ocr:text",
                        "text": text[:12000],
                        "confidence": 0.72,
                        "importance": 60,
                        "rarity": 55,
                        "locator": {"tool": "tesseract", "language": requested},
                    }
                )
    return observations


async def _run_tool(args: list[str], data: bytes, timeout: float = 25.0) -> tuple[int, bytes]:
    try:
        process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        output, _ = await asyncio.wait_for(process.communicate(data), timeout=timeout)
        return int(process.returncode or 0), output
    except (OSError, TimeoutError):
        return 1, b""


def _perceptual_hash(data: bytes) -> str:
    try:
        import imagehash
        from PIL import Image

        with Image.open(BytesIO(data)) as image:
            return str(imagehash.phash(image.convert("RGB")))
    except (ImportError, OSError, ValueError):
        return ""


def _image_metrics(data: bytes) -> dict[str, float | int]:
    try:
        import cv2
        import numpy as np

        encoded = np.frombuffer(data, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if image is None or image.size == 0:
            return {}
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        height, width = gray.shape[:2]
        edges = cv2.Canny(gray, 100, 200)
        return {
            "width": int(width),
            "height": int(height),
            "brightness_mean": round(float(gray.mean()), 3),
            "sharpness_laplacian_variance": round(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 3),
            "edge_density": round(float((edges > 0).mean()), 5),
        }
    except (ImportError, TypeError, ValueError):
        return {}


def _ocr_language(language: str) -> str:
    primary = language.casefold().split("-", 1)[0]
    return {
        "fa": "fas+eng",
        "ar": "ara+eng",
        "ja": "jpn+eng",
        "ko": "kor+eng",
        "zh": "chi_sim+eng",
        "ru": "rus+eng",
    }.get(primary, "eng")
