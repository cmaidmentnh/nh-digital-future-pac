#!/usr/bin/env python3
"""
Generate hero photos and OG images for digitalfuturenh.com using OpenAI gpt-image-1.

Usage (locally, with OpenAI key in env):
  OPENAI_API_KEY=sk-... python3 generate_images.py

Or pull the standard project key from the production server (NOT the admin key):
  OPENAI_API_KEY=$(ssh root@138.197.20.97 'grep ^OPENAI_API_KEY /opt/ctehr-candidate-website/.env | cut -d= -f2-') \
    python3 generate_images.py
Note: /opt/nh-whip-count/.env has OPENAI_ADMIN_KEY (sk-admin-...) which is an
Admin API key and CANNOT call /v1/images. Always use the sk-proj-... key.

Visual rules:
  - Real NH photo backgrounds (Mt Washington, Old Man, Statehouse, Lake Winnipesaukee, granite quarry)
  - Dark navy + cyan/violet gradient tone
  - Subtle circuit / pixel / node motifs blended into NH landscape
  - Geometric NH silhouette ok, abstract blockchain grids ok
  - NEVER include Bitcoin or Ethereum logos, coins, or branded crypto imagery
  - NEVER include text in the AI image (we overlay text via Pillow)
"""

import os
import sys
import time
import base64
from pathlib import Path

try:
    from openai import OpenAI
except ImportError:
    print("Install: pip install openai pillow", file=sys.stderr)
    sys.exit(1)

try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError:
    print("Install: pip install pillow", file=sys.stderr)
    sys.exit(1)

API_KEY = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_ADMIN_KEY")
if not API_KEY:
    print("Set OPENAI_API_KEY or OPENAI_ADMIN_KEY", file=sys.stderr)
    sys.exit(1)

client = OpenAI(api_key=API_KEY)

OUT = Path(__file__).resolve().parent.parent / "images"
OUT.mkdir(exist_ok=True)

# ----- Common visual prompt -----
STYLE = (
    "Photorealistic, cinematic, dusk lighting. Color grade: deep navy blues with subtle cyan and violet "
    "highlights. NO text, NO words, NO letters. NO bitcoin or ethereum logos, NO coins, NO branded crypto symbols. "
    "Blend in subtle abstract circuit-board lines, fine node-network dots, and a faint geometric grid as a "
    "translucent overlay across the sky or distant landscape. The look should feel modern, technological, "
    "rooted in New Hampshire, and editorial."
)

HEROS = [
    ("hero-home.jpg",
     "Wide cinematic landscape of the New Hampshire White Mountains at dusk, mountain silhouettes "
     "fading into a navy-blue sky, subtle cyan-violet aurora glow. Faint geometric circuit overlay drifts "
     "across the sky like a constellation. " + STYLE,
     (1792, 1024)),

    ("hero-about.jpg",
     "Granite cliff face of New Hampshire at golden hour, deep navy shadow, cyan-violet rim light, "
     "fine network of glowing node dots tracing the granite seams. " + STYLE,
     (1792, 1024)),

    ("hero-issues.jpg",
     "Dark New Hampshire forest treeline at twilight, low fog, distant mountains, with faint geometric "
     "grid lines projected across the fog like a heads-up display. Cyan and violet highlights. " + STYLE,
     (1792, 1024)),

    ("hero-candidates.jpg",
     "Aerial view of a small New Hampshire town at dusk, soft warm window lights, dark navy sky, faint "
     "violet-cyan node-network overlay floating above the town like a digital constellation. " + STYLE,
     (1792, 1024)),

    ("hero-news.jpg",
     "Rocky New Hampshire shoreline at dusk, granite boulders, cool blue water, distant lighthouse, "
     "subtle circuit lines glowing along the granite. Deep navy palette with cyan/violet accents. " + STYLE,
     (1792, 1024)),

    ("hero-involved.jpg",
     "Wide dusk photo of a New Hampshire valley with a winding road, warm tail-lights tracing the road, "
     "cool navy sky, faint circuit grid overlay over the sky. " + STYLE,
     (1792, 1024)),

    ("break-statehouse.jpg",
     "The New Hampshire State House gold dome at dusk, lit warmly, deep navy sky, geometric circuit "
     "pattern faintly traced across the sky behind the dome. " + STYLE,
     (1792, 1024)),

    ("break-mountains.jpg",
     "New Hampshire's Presidential Range silhouetted against a deep navy dusk sky, layered ridges, "
     "subtle pixel-block dissolve effect along the highest ridge as if the mountain is becoming data. "
     "Cyan-violet highlights. " + STYLE,
     (1792, 1024)),
]

OG_PROMPTS = [
    ("og-home.jpg",
     "Wide cinematic dusk landscape of the New Hampshire White Mountains with subtle cyan-violet "
     "circuit grid drifting across the sky. " + STYLE,
     (1536, 1024)),

    ("og-about.jpg",
     "Granite cliff at golden hour, deep navy shadow, faint glowing node network along granite seams. "
     + STYLE, (1536, 1024)),

    ("og-issues.jpg",
     "Twilight forest treeline with faint geometric grid lines projected across low fog. " + STYLE,
     (1536, 1024)),

    ("og-candidates.jpg",
     "Aerial of small NH town at dusk with violet-cyan node-network floating above the rooftops. "
     + STYLE, (1536, 1024)),

    ("og-news.jpg",
     "Rocky New Hampshire shoreline at dusk with circuit lines tracing the granite. " + STYLE,
     (1536, 1024)),

    ("og-involved.jpg",
     "NH valley road at dusk, warm tail-lights, faint circuit grid overlay sky. " + STYLE,
     (1536, 1024)),
]


def gen(prompt: str, size_label: str) -> bytes:
    """Call gpt-image-1. Returns PNG bytes."""
    r = client.images.generate(
        model="gpt-image-1",
        prompt=prompt,
        size=size_label,
        n=1,
    )
    b64 = r.data[0].b64_json
    return base64.b64decode(b64)


def save_jpg(png_bytes: bytes, dest: Path, target_size=None, quality=85):
    img = Image.open(__import__("io").BytesIO(png_bytes)).convert("RGB")
    if target_size and img.size != target_size:
        img = img.resize(target_size, Image.LANCZOS)
    img.save(dest, "JPEG", quality=quality, optimize=True, progressive=True)


def gpt_size(target):
    # gpt-image-1 supports: 1024x1024, 1536x1024, 1024x1536
    w, h = target
    if abs(w - h) < 50:
        return "1024x1024"
    if w > h:
        return "1536x1024"
    return "1024x1536"


def main():
    print(f"Output directory: {OUT}")

    for name, prompt, target in HEROS + OG_PROMPTS:
        dest = OUT / name
        if dest.exists() and "--force" not in sys.argv:
            print(f"  skip (exists): {name}")
            continue
        size_label = gpt_size(target)
        print(f"  generate {name} @ {size_label} -> {target} ...")
        try:
            data = gen(prompt, size_label)
            save_jpg(data, dest, target_size=target)
            print(f"  wrote {dest}")
            time.sleep(2)
        except Exception as e:
            print(f"  ERROR {name}: {e}", file=sys.stderr)


if __name__ == "__main__":
    main()
