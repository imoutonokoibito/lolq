from pathlib import Path
from PIL import Image, ImageDraw

root = Path(__file__).parent
image = Image.new('RGBA', (256, 256))
draw = ImageDraw.Draw(image)
draw.rounded_rectangle((8, 8, 248, 248), radius=60, fill='#007aff')
draw.ellipse((65, 50, 185, 178), outline='white', width=22)
draw.line((150, 146, 199, 198), fill='white', width=22)
image.save(root / 'LoLQ.ico', sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
