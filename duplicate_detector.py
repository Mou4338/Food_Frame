"""Duplicate detection: SHA-256 for exact byte-for-byte duplicates, and a
perceptual average-hash (aHash) for near-duplicates (same photo re-saved,
resized, or lightly cropped) -- catches the same stock photo being
auto-selected for two different dishes.
"""
import hashlib

import numpy as np
from PIL import Image


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def average_hash(img: Image.Image, hash_size: int = 8) -> str:
    small = img.convert("L").resize((hash_size, hash_size), Image.LANCZOS)
    pixels = np.asarray(small, dtype=np.float64)
    avg = pixels.mean()
    bits = (pixels > avg).flatten()
    return "".join("1" if b else "0" for b in bits)


def hamming_distance(hash_a: str, hash_b: str) -> int:
    if len(hash_a) != len(hash_b):
        return max(len(hash_a), len(hash_b))
    return sum(a != b for a, b in zip(hash_a, hash_b))


def is_near_duplicate(hash_a: str, hash_b: str, threshold: int = 6) -> bool:
    return hamming_distance(hash_a, hash_b) <= threshold
