"""Page diagnostics are routing signals, never probabilities of factual truth."""

from __future__ import annotations

from itertools import pairwise


def area_uniao(boxes: list, page_bbox: list | tuple) -> float:
    x0, y0, x1, y1 = page_bbox
    clipped = [(max(x0, b[0]), max(y0, b[1]), min(x1, b[2]), min(y1, b[3])) for b in boxes]
    clipped = [b for b in clipped if b[2] > b[0] and b[3] > b[1]]
    xs = sorted({x for b in clipped for x in (b[0], b[2])})
    area = 0.0
    for left, right in pairwise(xs):
        intervals = sorted((b[1], b[3]) for b in clipped if b[0] < right and b[2] > left)
        upper = -float("inf")
        covered = 0.0
        for low, high in intervals:
            covered += max(0, high - max(low, upper))
            upper = max(upper, high)
        area += (right - left) * covered
    return area


def diagnosticar_pagina(page, numero: int, texto: str, tables: list) -> dict:
    bbox = list(page.bbox)
    area = max(1, (bbox[2] - bbox[0]) * (bbox[3] - bbox[1]))
    images = [[im["x0"], im["top"], im["x1"], im["bottom"]] for im in page.images]
    ratio = area_uniao(images, bbox) / area
    native = len(page.chars)
    empty_tables = sum(
        not any(c and str(c).strip() for row in t.extract() for c in row) for t in tables
    )
    header_only = sum(len(t.rows) == 1 and len(t.columns) > 1 for t in tables)
    useful_tables = sum(
        len(t.rows) > 1 and sum(bool(c and str(c).strip()) for row in t.extract() for c in row) >= 4
        for t in tables
    )
    flags = []
    status = "complete"
    if not texto.strip() and not images:
        status = "empty"
    elif native < 100 and (ratio >= 0.4 or (images and not texto.strip())):
        status = "needs_ocr"
        flags.append("low_text_image_mismatch")
    elif (empty_tables or header_only) and not useful_tables:
        status = "needs_layout"
    if empty_tables:
        flags.append("empty_detected_table")
    if header_only:
        flags.append("header_only_table")
    if "\ufffd" in texto:
        flags.append("replacement_characters")
        if texto.count("\ufffd") / max(1, len(texto.strip())) > 0.05:
            status = "needs_ocr"
    return {
        "pagina": numero,
        "motor": "pdfplumber",
        "status": status,
        "bbox": bbox,
        "coord_origin": "top_left",
        "rotation": getattr(page, "rotation", 0),
        "q_pdf": {
            "native_chars": native,
            "text_chars": len(texto.strip()),
            "image_count": len(images),
            "image_union_ratio": round(ratio, 4),
            "empty_tables": empty_tables,
            "header_only_tables": header_only,
            "useful_tables": useful_tables,
            "flags": flags,
        },
        "regioes": [{"kind": "image", "bbox": b, "coord_origin": "top_left"} for b in images],
    }
