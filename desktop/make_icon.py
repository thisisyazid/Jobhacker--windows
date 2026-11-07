"""Build desktop/icon.ico (the exe's icon) from the app's 512px PNG icon."""
from pathlib import Path

from PIL import Image

root = Path(__file__).resolve().parent.parent
img = Image.open(root / "static" / "icons" / "icon-512.png").convert("RGBA")
img.save(root / "desktop" / "icon.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
print("wrote desktop/icon.ico")
