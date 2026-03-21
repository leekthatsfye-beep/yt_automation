"""Generate PWA icons for the FY3! brand."""

from PIL import Image, ImageDraw, ImageFont

BG_COLOR = (10, 10, 15)        # #0a0a0f
WHITE = (255, 255, 255)
BLUE_ACCENT = (10, 132, 255)   # #0a84ff
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
OUT_DIR = "/Users/fyefye/yt_automation/app/frontend/public"


def make_rounded_mask(size, radius):
    """Create an alpha mask with rounded corners."""
    mask = Image.new("L", (size, size), 0)
    draw = ImageDraw.Draw(mask)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    return mask


def draw_fy3_icon(size, round_corners=False, corner_radius=0):
    """Draw an FY3! icon at the given size."""
    img = Image.new("RGBA", (size, size), BG_COLOR + (255,))
    draw = ImageDraw.Draw(img)

    # Size the font to fill ~65% of the icon width for the full "FY3!" text
    font_size = int(size * 0.38)
    font = ImageFont.truetype(FONT_PATH, font_size)

    # Measure "FY3" and "!" separately
    fy3_text = "FY3"
    bang_text = "!"

    fy3_bbox = draw.textbbox((0, 0), fy3_text, font=font)
    bang_bbox = draw.textbbox((0, 0), bang_text, font=font)

    fy3_w = fy3_bbox[2] - fy3_bbox[0]
    bang_w = bang_bbox[2] - bang_bbox[0]
    total_w = fy3_w + bang_w

    # Use the height from the combined text for vertical centering
    full_bbox = draw.textbbox((0, 0), "FY3!", font=font)
    text_h = full_bbox[3] - full_bbox[1]
    text_top_offset = full_bbox[1]  # baseline offset from top

    # Center the combined text block
    x_start = (size - total_w) / 2
    y_start = (size - text_h) / 2 - text_top_offset

    # Draw "FY3" in white
    draw.text((x_start, y_start), fy3_text, fill=WHITE, font=font)

    # Draw "!" in blue accent, immediately after FY3
    draw.text((x_start + fy3_w, y_start), bang_text, fill=BLUE_ACCENT, font=font)

    # Apply rounded corners if requested
    if round_corners and corner_radius > 0:
        mask = make_rounded_mask(size, corner_radius)
        result = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        result.paste(img, (0, 0), mask)
        return result

    return img


def main():
    # 1. icon-192.png (192x192) - standard PWA icon
    icon_192 = draw_fy3_icon(192)
    path_192 = f"{OUT_DIR}/icon-192.png"
    icon_192.save(path_192, "PNG")
    print(f"Created {path_192}")

    # 2. icon-512.png (512x512) - large PWA icon
    icon_512 = draw_fy3_icon(512)
    path_512 = f"{OUT_DIR}/icon-512.png"
    icon_512.save(path_512, "PNG")
    print(f"Created {path_512}")

    # 3. apple-touch-icon.png (180x180) - rounded corners for iOS
    apple_icon = draw_fy3_icon(180, round_corners=True, corner_radius=36)
    path_apple = f"{OUT_DIR}/apple-touch-icon.png"
    apple_icon.save(path_apple, "PNG")
    print(f"Created {path_apple}")


if __name__ == "__main__":
    main()
