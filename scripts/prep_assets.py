#!/usr/bin/env python3
"""Turn rendered PNG slides into API-ready JPEGs.

Meta's publishing API accepts JPEG only, so every rendered slide is converted
before it reaches assets/. Sizing follows the 4:5 portrait frame the account
uses, at 1080x1350, which is the largest size Instagram serves.

Usage:
    python scripts/prep_assets.py <source-folder> [--out assets] [--prefix aug19]

Slides are taken in filename order, which is the true reading order. The old
upload-order compensation for Meta Business Suite is not needed here.
"""

import argparse
import os
import sys

try:
    from PIL import Image
except ImportError:
    sys.exit("Pillow is required: pip install Pillow")

TARGET = (1080, 1350)
QUALITY = 90


def convert(src, dst):
    img = Image.open(src)
    if img.mode in ("RGBA", "LA", "P"):
        background = Image.new("RGB", img.size, (255, 255, 255))
        img = img.convert("RGBA")
        background.paste(img, mask=img.split()[-1])
        img = background
    else:
        img = img.convert("RGB")

    ratio_target = TARGET[0] / TARGET[1]
    ratio_src = img.width / img.height
    if abs(ratio_src - ratio_target) > 0.01:
        # Cover-crop to 4:5 rather than squash the layout.
        if ratio_src > ratio_target:
            new_w = int(img.height * ratio_target)
            left = (img.width - new_w) // 2
            img = img.crop((left, 0, left + new_w, img.height))
        else:
            new_h = int(img.width / ratio_target)
            top = (img.height - new_h) // 2
            img = img.crop((0, top, img.width, top + new_h))
    img = img.resize(TARGET, Image.LANCZOS)
    img.save(dst, "JPEG", quality=QUALITY, optimize=True, progressive=False, subsampling=0)
    return os.path.getsize(dst)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("--out", default="assets")
    ap.add_argument("--prefix", default="")
    args = ap.parse_args()

    os.makedirs(args.out, exist_ok=True)
    files = sorted(f for f in os.listdir(args.source) if f.lower().endswith((".png", ".jpg", ".jpeg")))
    if not files:
        sys.exit(f"no images found in {args.source}")

    written = []
    for i, name in enumerate(files, 1):
        stem = os.path.splitext(name)[0]
        out_name = f"{args.prefix}_{i:02d}.jpg" if args.prefix else f"{stem}.jpg"
        size = convert(os.path.join(args.source, name), os.path.join(args.out, out_name))
        written.append(out_name)
        print(f"{name} -> {out_name}  {size // 1024} KB")

    print("\nfiles list for queue.json, in reading order:")
    print("  " + str(written).replace("'", '"'))


if __name__ == "__main__":
    main()
