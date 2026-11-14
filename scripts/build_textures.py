"""WebP versions of the bundled globe textures (assets/textures), from the JPEG/PNG originals, which stay as the
fallback for browsers without WebP:
  earth-night.webp, earth-blue-marble.webp   4096 x 2048, for larger screens
  earth-night-2k.webp, earth-blue-marble-2k.webp   2048 x 1024, for phone-sized screens and small GPUs
  earth-topology.webp   the bump map, 2048 x 1024 like its original
Prints size and SSIM / PSNR against the original (the 2k ones against the original scaled to 2048 the same way).

  python scripts/build_textures.py [--check]      (Pillow with WebP; ffmpeg, if found, for SSIM and PSNR)
"""
import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
DIR = ROOT / "assets" / "textures"
# name -> (source, size or None for the original size, WebP quality)
OUTPUTS = {
    "earth-night.webp": ("earth-night.jpg", None, 82),
    "earth-night-2k.webp": ("earth-night.jpg", (2048, 1024), 82),
    "earth-blue-marble.webp": ("earth-blue-marble.jpg", None, 80),
    "earth-blue-marble-2k.webp": ("earth-blue-marble.jpg", (2048, 1024), 80),
    "earth-topology.webp": ("earth-topology.png", None, 85),
}


def source_image(name, size):
    image = Image.open(DIR / name).convert("RGB")
    return image.resize(size, Image.LANCZOS) if size else image


def encode(image, quality):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "out.webp"
        image.save(path, "WEBP", quality=quality, method=6)
        return path.read_bytes()


def compare(reference, data):
    """SSIM (all planes) and PSNR of `data` against `reference`, with ffmpeg; None without it."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        ref, out = Path(tmp) / "ref.png", Path(tmp) / "out.webp"
        reference.save(ref)
        out.write_bytes(data)
        log = subprocess.run([ffmpeg, "-hide_banner", "-i", str(out), "-i", str(ref), "-lavfi", "[0:v][1:v]ssim;[0:v][1:v]psnr", "-f", "null", "-"],
                             capture_output=True, text=True).stderr
    ssim = next((l.split("All:")[1].split()[0] for l in log.splitlines() if "SSIM" in l and "All:" in l), None)
    psnr = next((l.split("average:")[1].split()[0] for l in log.splitlines() if "PSNR" in l and "average:" in l), None)
    return float(ssim), float(psnr)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="only verify that every output exists and decodes at its size")
    args = ap.parse_args()
    failed = False
    for name, (source, size, quality) in OUTPUTS.items():
        target = DIR / name
        reference = source_image(source, size)
        if args.check:
            ok = target.exists() and Image.open(target).size == reference.size
            failed |= not ok
            print(f"{name}: {'ok' if ok else 'missing or wrong size'}")
            continue
        data = encode(reference, quality)
        target.write_bytes(data)
        original = (DIR / source).stat().st_size
        quality_text = compare(reference, data)
        measured = f"SSIM {quality_text[0]:.4f}, PSNR {quality_text[1]:.1f} dB" if quality_text else "no ffmpeg for SSIM"
        print(f"{name}: {reference.size[0]}x{reference.size[1]} q{quality}, {len(data):,} B (original {source} {original:,} B), {measured}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
