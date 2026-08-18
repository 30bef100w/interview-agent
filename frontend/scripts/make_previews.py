"""Landing previews: identical size, UI fully inside the frame."""
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SHOTS = ROOT / "shots"
PUBLIC = ROOT / "public"
OUT_W, OUT_H = 1200, 750
ASPECT = OUT_W / OUT_H


def side_bounds(im: Image.Image, pad: int = 40) -> tuple[int, int]:
    arr = np.asarray(im.convert("RGB"))
    mask = ~((arr[:, :, 0] > 248) & (arr[:, :, 1] > 248) & (arr[:, :, 2] > 248))
    xs = np.where(mask.any(axis=0))[0]
    if len(xs) == 0:
        return 0, im.width
    return max(0, int(xs.min()) - pad), min(im.width, int(xs.max()) + 1 + pad)


def crop_aspect(im: Image.Image, left: int, right: int, top_bias: float = 0.08) -> Image.Image:
    """Crop a OUT_ASPECT window covering [left,right] content, prefer top."""
    w, h = im.size
    cw = max(1, right - left)
    ch = int(cw / ASPECT)
    if ch > h:
        ch = h
        cw = int(ch * ASPECT)
        left = max(0, (w - cw) // 2)
    top = int((h - ch) * top_bias)
    top = max(0, min(top, h - ch))
    # center horizontally on the content span
    mid = (left + right) // 2
    left = max(0, min(mid - cw // 2, w - cw))
    return im.crop((left, top, left + cw, top + ch))


def main() -> None:
    jobs = [
        # chat spans full width — no side trim, just slight top-biased aspect crop
        ("final-chat.png", "chat-preview.png", False, 0.05),
        ("final-dashboard.png", "dashboard-preview.png", True, 0.06),
        ("final-report.png", "report-preview.png", True, 0.05),
    ]
    for src_name, dst_name, trim, bias in jobs:
        src = Image.open(SHOTS / src_name).convert("RGB")
        if trim:
            l, r = side_bounds(src)
            # expand a bit so cards aren't edge-flush
            span = r - l
            expand = int(span * 0.04)
            l = max(0, l - expand)
            r = min(src.width, r + expand)
            cropped = crop_aspect(src, l, r, top_bias=bias)
        else:
            cropped = crop_aspect(src, 0, src.width, top_bias=bias)
        out = cropped.resize((OUT_W, OUT_H), Image.Resampling.LANCZOS)
        out.save(PUBLIC / dst_name, optimize=True)
        print(f"{dst_name}: {src.size} -> crop {cropped.size} -> {out.size}")

    sizes = {
        Image.open(PUBLIC / n).size
        for n in ("chat-preview.png", "dashboard-preview.png", "report-preview.png")
    }
    assert sizes == {(OUT_W, OUT_H)}, sizes
    print("uniform ok")


if __name__ == "__main__":
    main()
