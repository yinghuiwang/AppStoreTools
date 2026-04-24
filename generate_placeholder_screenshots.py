#!/usr/bin/env python3
"""Generate placeholder screenshot images for App Store Connect."""
from PIL import Image, ImageDraw, ImageFont
from pathlib import Path

def create_placeholder(width, height, text, output_path):
    """Create a placeholder image with gradient background and text."""
    # Create gradient background
    img = Image.new('RGB', (width, height))
    draw = ImageDraw.Draw(img)

    # Draw gradient from top to bottom
    for y in range(height):
        ratio = y / height
        r = int(70 + (150 - 70) * ratio)
        g = int(130 + (200 - 130) * ratio)
        b = int(180 + (230 - 180) * ratio)
        draw.line([(0, y), (width, y)], fill=(r, g, b))

    # Add text
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 80)
    except:
        font = ImageFont.load_default()

    # Draw text with shadow
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    x = (width - text_width) // 2
    y = (height - text_height) // 2

    # Shadow
    draw.text((x + 3, y + 3), text, fill=(0, 0, 0, 128), font=font)
    # Main text
    draw.text((x, y), text, fill=(255, 255, 255), font=font)

    # Add decorative elements
    draw.rectangle([50, 50, width-50, height-50], outline=(255, 255, 255), width=5)

    img.save(output_path, 'PNG')
    print(f"✓ Created: {output_path}")

def main():
    base_dir = Path(__file__).parent / "data" / "screenshots"

    # iPhone 6.7" dimensions (1320x2868)
    width, height = 1320, 2868

    locales = {
        'cn': ['示例截图 1', '示例截图 2', '示例截图 3', '示例截图 4'],
        'en-US': ['Screenshot 1', 'Screenshot 2', 'Screenshot 3', 'Screenshot 4']
    }

    for locale, texts in locales.items():
        locale_dir = base_dir / locale
        locale_dir.mkdir(parents=True, exist_ok=True)

        for i, text in enumerate(texts, 1):
            filename = f"IMG_270{i+1}.PNG"
            output_path = locale_dir / filename
            create_placeholder(width, height, text, output_path)

    print("\n✅ All placeholder screenshots generated!")

if __name__ == "__main__":
    main()
