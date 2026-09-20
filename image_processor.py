"""Downloads a candidate image and, once APPROVED (auto or by a human),
resizes to the exact target dimensions (center-crop, no distortion),
strips incidental metadata, and compresses under the max file size.
"""
import io
import requests
from PIL import Image, ImageOps


DOWNLOAD_HEADERS = {
    "User-Agent": "FoodImageAgent/1.0 (educational project; contact: set via .env)"
}


def download_image(url: str) -> Image.Image:
    if url.startswith("file://"):
        img = Image.open(url[len("file://"):])
    else:
        resp = requests.get(url, headers=DOWNLOAD_HEADERS, timeout=30)
        resp.raise_for_status()
        img = Image.open(io.BytesIO(resp.content))
    return img.convert("RGB")


def resize_exact(img: Image.Image, width: int, height: int) -> Image.Image:
    """Scale to cover the target box, then center-crop to the exact size --
    keeps the dish centred and avoids stretching/distortion."""
    return ImageOps.fit(img, (width, height), method=Image.LANCZOS, centering=(0.5, 0.5))


def compress_to_size(img: Image.Image, max_size_kb: int, min_quality: int = 70) -> bytes:
    quality = 95
    buffer = io.BytesIO()
    while quality >= min_quality:
        buffer.seek(0)
        buffer.truncate()
        # exif=b"" strips embedded metadata (GPS/camera info) from the saved copy
        img.save(buffer, format="JPEG", quality=quality, optimize=True, exif=b"")
        if buffer.tell() / 1024 <= max_size_kb:
            break
        quality -= 5
    return buffer.getvalue()


def process_image(img: Image.Image, width: int, height: int, max_size_kb: int) -> bytes:
    resized = resize_exact(img, width, height)
    return compress_to_size(resized, max_size_kb)


def final_validation(image_bytes: bytes, width: int, height: int, max_size_kb: int) -> tuple[bool, str]:
    """One last sanity check right before upload."""
    try:
        img = Image.open(io.BytesIO(image_bytes))
        img.verify()
    except Exception as e:
        return False, f"processed image is corrupt: {e}"
    if len(image_bytes) / 1024 > max_size_kb:
        return False, f"processed image exceeds {max_size_kb}KB limit"
    reopened = Image.open(io.BytesIO(image_bytes))
    if reopened.size != (width, height):
        return False, f"processed image is {reopened.size}, expected {(width, height)}"
    return True, "ok"
