from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "logo.jpg"
OUTPUT = ROOT / "build_assets" / "logo.ico"
SIZES = (16, 24, 32, 48, 64, 128, 256)


def main():
    if not SOURCE.exists():
        raise FileNotFoundError(f"Logo file not found: {SOURCE}")

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image = Image.open(SOURCE).convert("RGBA")

    canvas_size = max(image.size)
    canvas = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    offset = ((canvas_size - image.width) // 2, (canvas_size - image.height) // 2)
    canvas.paste(image, offset)

    canvas.save(OUTPUT, format="ICO", sizes=[(size, size) for size in SIZES])
    print(f"Icon written: {OUTPUT}")


if __name__ == "__main__":
    main()
