"""Generate physical favicon files and app icons for KeyFlint."""

import os
from pathlib import Path
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent

def generate_icons(target_dir: Path):
    target_dir.mkdir(parents=True, exist_ok=True)
    
    # 512x512 base canvas
    size = 512
    # Create canvas with background #0B0D17
    img = Image.new("RGBA", (size, size), (11, 13, 23, 255))
    draw = ImageDraw.Draw(img)
    
    # Volt lime #CCFF00
    brand_color = (204, 255, 0, 255)
    w = 52 # stroke width for 512px
    
    # Monogram K lines
    # Vertical line
    draw.line([(160, 112), (160, 400)], fill=brand_color, width=w)
    # Upper diagonal
    draw.line([(160, 256), (320, 112)], fill=brand_color, width=w)
    # Lower diagonal
    draw.line([(224, 208), (336, 400)], fill=brand_color, width=w)
    
    # Round end-caps
    r = w // 2
    for x, y in [(160, 112), (160, 400), (320, 112), (336, 400)]:
        draw.ellipse([x - r, y - r, x + r, y + r], fill=brand_color)
        
    img.save(target_dir / "icon-512.png", "PNG")
    img.resize((192, 192), Image.Resampling.LANCZOS).save(target_dir / "icon-192.png", "PNG")
    img.resize((180, 180), Image.Resampling.LANCZOS).save(target_dir / "apple-touch-icon.png", "PNG")
    img.resize((48, 48), Image.Resampling.LANCZOS).save(target_dir / "icon-48.png", "PNG")
    img.resize((32, 32), Image.Resampling.LANCZOS).save(target_dir / "icon-32.png", "PNG")
    img.resize((16, 16), Image.Resampling.LANCZOS).save(target_dir / "icon-16.png", "PNG")
    
    # Multi-resolution ICO
    img.save(target_dir / "favicon.ico", format="ICO", sizes=[(16, 16), (32, 32), (48, 48)])
    
    # Vector SVG
    svg_data = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="6" fill="#0B0D17"/><path d="M10 7v18M10 16l10-9M14 13l7 12" stroke="#CCFF00" stroke-width="3.2" fill="none" stroke-linecap="round"/></svg>\n'
    (target_dir / "favicon.svg").write_text(svg_data, encoding="utf-8")
    
    print(f"Generated icons in {target_dir}")

if __name__ == "__main__":
    generate_icons(ROOT / "docs")
    generate_icons(ROOT / "app" / "presentation" / "static")
