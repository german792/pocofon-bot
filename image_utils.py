import io
from typing import Optional
from PIL import Image, ImageDraw, ImageFilter, ImageOps, ImageFont


def prepare_user_image(image_bytes: bytes, target_ratio: str = "16:9") -> bytes:
    """
    Prepare user-provided reference image WITHOUT cropping any part of it.
    Preserves the exact original aspect ratio of the reference image, composites
    transparent PNGs onto a clean white background, and ensures dimensions are within [320, 4096].
    """
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)

    # Composite transparent PNGs onto a white background instead of turning alpha black
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    # Ensure minimum dimension >= 320px while keeping exact aspect ratio
    min_side = min(w, h)
    if min_side < 320 and min_side > 0:
        scale = 320.0 / min_side
        w = int(round(w * scale))
        h = int(round(h * scale))
        img = img.resize((w, h), Image.Resampling.LANCZOS)

    # Ensure maximum dimension <= 4096px while keeping exact aspect ratio
    max_side = max(w, h)
    if max_side > 4096:
        scale = 4096.0 / max_side
        w = int(round(w * scale))
        h = int(round(h * scale))
        img = img.resize((w, h), Image.Resampling.LANCZOS)

    out_buf = io.BytesIO()
    img.save(out_buf, format="JPEG", quality=95)
    return out_buf.getvalue()


def generate_text_seed_image(ratio: str = "16:9") -> bytes:
    """
    Generate an aesthetic background image to seed Text-to-Video
    when the user has not uploaded a photo.
    """
    dimensions = {
        "16:9": (1280, 720),
        "9:16": (720, 1280),
        "1:1": (960, 960)
    }
    width, height = dimensions.get(ratio, (1280, 720))

    # Create smooth dark modern gradient
    img = Image.new("RGB", (width, height), color=(20, 24, 33))

    # Soft ambient glows
    glow1 = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow1)

    cx1, cy1 = int(width * 0.3), int(height * 0.4)
    r1 = int(min(width, height) * 0.45)
    glow_draw.ellipse([cx1 - r1, cy1 - r1, cx1 + r1, cy1 + r1], fill=(45, 75, 115, 130))

    cx2, cy2 = int(width * 0.7), int(height * 0.6)
    r2 = int(min(width, height) * 0.5)
    glow_draw.ellipse([cx2 - r2, cy2 - r2, cx2 + r2, cy2 + r2], fill=(60, 40, 90, 110))

    glow1 = glow1.filter(ImageFilter.GaussianBlur(radius=80))
    img.paste(glow1, (0, 0), glow1)

    out_buf = io.BytesIO()
    img.save(out_buf, format="JPEG", quality=95)
    return out_buf.getvalue()


def overlay_grid(
    image_bytes: bytes,
    rows: int = 3,
    cols: int = 3,
    thickness: Optional[int] = None,
    thickness_mode: str = "thick",
    color: str = "contrast",
    show_border: bool = True,
    show_labels: bool = False,
) -> bytes:
    """
    Overlays a prominent, thick grid onto an image.
    Supports customizable rows x cols (e.g. 3x3, 4x4, 2x2, 5x5, 8x8), line thickness,
    and colors (contrast, white, black, red, green, yellow, cyan).
    Default 'contrast' draws a high-visibility dual-tone line (white core with black outline)
    guaranteed to be clearly visible against any dark, bright, or textured background.
    """
    img = Image.open(io.BytesIO(image_bytes))
    img = ImageOps.exif_transpose(img)

    # Composite transparent PNGs onto a clean white background
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[3])
        img = bg
    elif img.mode != "RGB":
        img = img.convert("RGB")

    w, h = img.size
    rows = max(1, min(rows, 50))
    cols = max(1, min(cols, 50))
    min_dim = min(w, h)

    # Calculate thickness: adaptive to image size and cell density so dense grids stay crisp
    min_cell = min(w / cols, h / rows)
    if thickness and thickness > 0:
        actual_thickness = max(2, min(thickness, int(min_dim * 0.15)))
    else:
        mode_multipliers = {
            "thin": 0.0035,
            "medium": 0.007,
            "thick": 0.012,
            "heavy": 0.019,
        }
        mode_key = thickness_mode.lower()
        mult = mode_multipliers.get(mode_key, 0.012)
        min_px = 2 if mode_key == "thin" else 4 if mode_key == "medium" else 6
        actual_thickness = max(min_px, int(round(min_dim * mult)))
        max_for_cell = max(2, int(min_cell * 0.18))
        if actual_thickness > max_for_cell:
            actual_thickness = max_for_cell

    color_map = {
        "contrast": ((255, 255, 255), (0, 0, 0)),
        "white": ((255, 255, 255), (0, 0, 0)),
        "black": ((0, 0, 0), (255, 255, 255)),
        "red": ((255, 40, 40), (0, 0, 0)),
        "green": ((0, 255, 80), (0, 0, 0)),
        "yellow": ((255, 225, 0), (0, 0, 0)),
        "cyan": ((0, 230, 255), (0, 0, 0)),
    }
    fg_col, bg_col = color_map.get(color.lower(), color_map["contrast"])

    outline_extra = max(1, int(round(actual_thickness * 0.35)))
    total_thickness = actual_thickness + outline_extra * 2 if bg_col else actual_thickness

    draw = ImageDraw.Draw(img)

    v_xs = [int(round(w * i / cols)) for i in range(1, cols)]
    h_ys = [int(round(h * j / rows)) for j in range(1, rows)]

    # 1. Background / outline pass (crisp contrast)
    if bg_col:
        if show_border:
            draw.rectangle([0, 0, w - 1, h - 1], outline=bg_col, width=total_thickness)
        for x in v_xs:
            draw.line([(x, 0), (x, h)], fill=bg_col, width=total_thickness)
        for y in h_ys:
            draw.line([(0, y), (w, y)], fill=bg_col, width=total_thickness)

    # 2. Foreground main lines
    if show_border:
        draw.rectangle([0, 0, w - 1, h - 1], outline=fg_col, width=actual_thickness)
    for x in v_xs:
        draw.line([(x, 0), (x, h)], fill=fg_col, width=actual_thickness)
    for y in h_ys:
        draw.line([(0, y), (w, y)], fill=fg_col, width=actual_thickness)

    # 3. Optional cell labels (A1, A2... or numbers)
    if show_labels and min_dim >= 200:
        cell_w = w / cols
        cell_h = h / rows
        font_size = max(10, min(28, int(min(cell_w, cell_h) * 0.24)))
        try:
            font = ImageFont.load_default(size=font_size)
        except TypeError:
            font = ImageFont.load_default()
        for r in range(rows):
            for c in range(cols):
                label = f"{chr(65 + c)}{r + 1}"
                offset = max(3, min(8, int(min(cell_w, cell_h) * 0.08)))
                lx = int(c * cell_w + actual_thickness + offset)
                ly = int(r * cell_h + actual_thickness + offset)
                tb = draw.textbbox((lx, ly), label, font=font)
                pad = 2
                draw.rectangle([tb[0] - pad, tb[1] - pad, tb[2] + pad, tb[3] + pad], fill=(0, 0, 0))
                draw.text((lx, ly), label, fill=(255, 255, 255), font=font)

    out_buf = io.BytesIO()
    img.save(out_buf, format="JPEG", quality=95)
    return out_buf.getvalue()
