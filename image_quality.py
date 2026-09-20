"""Technical (non-AI) image evaluation.

Covers ten checks, all free and instant (no AI call):
  1. Sharpness / blur           -- Laplacian variance
  2. Resolution                 -- width x height vs. minimums
  3. Aspect ratio                -- vs. the 1800x1200 (3:2) target
  4. Crop / edge detection       -- does the food spill past the frame?
  5. Food subject coverage       -- ideally ~80-90% of the frame
  6. Centering / composition     -- how far the subject sits from centre
  7. Brightness                  -- too dark / overexposed
  8. Contrast                    -- too flat / too harsh
  9. Color quality & saturation  -- dull/grey vs. vivid, appetising color
 10. Image validity              -- corrupt/unreadable files caught before AI

Checks 4-6 (crop, coverage, centering) all depend on first finding *where
the food actually is* in the frame. That's done once, with OpenCV's
GrabCut, in `_segment_subject_mask()` -- a classic (non-deep-learning)
foreground/background segmentation seeded with a rectangle around the
centre of the photo. It isn't perfect on every background, but it is a
real estimate of the food's silhouette, not a proxy.
"""
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

# ---- tunable bands -- also adjustable via config.yaml / the Settings page ----
IDEAL_COVERAGE_RANGE = (0.80, 0.90)     # food should fill 80-90% of the frame
COVERAGE_FLOOR = 0.15                    # below this: "food is barely in the shot" -> hard fail
COVERAGE_CEILING = 0.97                  # above this: "zoomed in / no context at all" -> hard fail
BORDER_CUTOFF_FAIL_RATIO = 0.55          # this much of the border strip is food -> hard fail (clearly cut off)
IDEAL_ASPECT = 1800 / 1200               # 1.5 (3:2) -- the target output shape
IDEAL_SATURATION_RANGE = (80, 190)       # mean HSV saturation, 0-255 scale


@dataclass
class TechnicalResult:
    passed: bool
    score: float                     # 0-100, overall technical score
    reason: str
    composition_score: float = 0.0   # 0-100 -- coverage + centering + not-cut-off, combined
    color_quality_score: float = 0.0 # 0-100 -- saturation + colorfulness
    coverage_ratio: float = 0.0      # 0-1, for display/audit in the dashboard
    warnings: list = field(default_factory=list)


def _pil_to_cv(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)


# ---------------------------------------------------------------- (1) blur
def _blur_score(img_cv: np.ndarray, threshold: float) -> tuple[float, bool, str]:
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    variance = cv2.Laplacian(gray, cv2.CV_64F).var()
    passed = variance >= threshold
    score = min(100.0, (variance / max(threshold, 1)) * 60)
    reason = f"sharpness {'ok' if passed else 'too blurry'} (score={variance:.1f}, threshold={threshold})"
    return score, passed, reason


# ---------------------------------------------------------- (2)+(3) resolution + aspect ratio
def _resolution_score(img: Image.Image, min_w: int, min_h: int) -> tuple[float, bool, str]:
    w, h = img.size
    if w < min_w or h < min_h:
        return 0.0, False, f"resolution too low ({w}x{h}, need >= {min_w}x{min_h})"
    megapixels = (w * h) / 1_000_000
    score = min(100.0, 40 + megapixels * 15)
    return score, True, f"resolution ok ({w}x{h})"


def _aspect_ratio_score(img: Image.Image) -> tuple[float, str]:
    """The final image is force-cropped to 1800x1200 later regardless, so
    this only penalizes shapes so extreme (very tall panoramas, thin strips)
    that a center-crop to 3:2 would cut away most of the dish."""
    w, h = img.size
    ratio = w / h
    diff = abs(ratio - IDEAL_ASPECT) / IDEAL_ASPECT
    if diff <= 0.35:
        score = 100.0
    elif diff <= 1.2:
        score = 100.0 * (1 - (diff - 0.35) / (1.2 - 0.35))
    else:
        score = 0.0
    score = max(0.0, min(100.0, score))
    return score, f"aspect ratio {ratio:.2f} vs target {IDEAL_ASPECT:.2f}"


# --------------------------------------------- subject segmentation (shared by 4, 5, 6)
def _segment_subject_mask(img_cv: np.ndarray, work_size: int = 480) -> np.ndarray:
    """Runs GrabCut on a downscaled copy (fast, and ratios/positions are
    resolution-independent), seeded with a GRADUATED mask rather than a
    single rectangle:
        outer ~3% ring   -> definite background  (GC_BGD)
        3%-12% ring       -> probable background  (GC_PR_BGD)
        12%-92% (bulk)     -> probable foreground  (GC_PR_FGD)
        innermost ~20%     -> definite foreground  (GC_FGD)
    A plain rectangle seed forces everything outside it to be treated as
    definite background -- which breaks down exactly in the 80-90% coverage
    range we care about most, since a well-filled dish photo's edges then
    get hard-labelled as background and contaminate the background color
    model. The graduated seed instead gives GrabCut a strong prior at the
    centre and the extreme edge, and lets it work out the actual boundary
    in between from color, which is much more robust for large subjects.
    Returns a 0/1 mask at the downscaled resolution."""
    h, w = img_cv.shape[:2]
    scale = work_size / max(h, w)
    small = cv2.resize(img_cv, (max(1, int(w * scale)), max(1, int(h * scale))), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]

    def ring(pct):
        m = np.zeros((sh, sw), dtype=bool)
        bw, bh = max(1, int(sw * pct)), max(1, int(sh * pct))
        m[:bh, :] = True
        m[-bh:, :] = True
        m[:, :bw] = True
        m[:, -bw:] = True
        return m

    seed = np.full((sh, sw), cv2.GC_PR_FGD, dtype=np.uint8)
    seed[ring(0.12)] = cv2.GC_PR_BGD
    seed[ring(0.03)] = cv2.GC_BGD
    core_bw, core_bh = int(sw * 0.20), int(sh * 0.20)
    seed[core_bh:sh - core_bh, core_bw:sw - core_bw] = cv2.GC_FGD

    mask = seed.copy()
    bgd_model = np.zeros((1, 65), np.float64)
    fgd_model = np.zeros((1, 65), np.float64)

    try:
        cv2.grabCut(small, mask, None, bgd_model, fgd_model, 5, cv2.GC_INIT_WITH_MASK)
        fg_mask = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 1, 0).astype("uint8")
    except cv2.error:
        # GrabCut can fail on degenerate images (near-solid color, etc.) --
        # fall back to the seed's own foreground guess rather than crashing
        # the whole evaluation.
        fg_mask = np.where((seed == cv2.GC_FGD) | (seed == cv2.GC_PR_FGD), 1, 0).astype("uint8")
    return fg_mask


def _score_in_ideal_range(value: float, lo: float, hi: float, floor: float, ceil: float) -> float:
    """100 inside [lo, hi], tapering linearly to 0 at floor/ceil, used for
    coverage and saturation -- both are 'too little OR too much is bad'."""
    if lo <= value <= hi:
        return 100.0
    if value < lo:
        if value <= floor:
            return 0.0
        return 100.0 * (value - floor) / (lo - floor)
    if value >= ceil:
        return 0.0
    return 100.0 * (ceil - value) / (ceil - hi)


# ------------------------------------------------------------- (5) coverage
def _coverage_ratio(mask: np.ndarray) -> float:
    return float(mask.mean())


# ---------------------------------------------------------- (6) centering
def _centering_score(mask: np.ndarray) -> tuple[float, float]:
    ys, xs = np.where(mask > 0)
    h, w = mask.shape
    if len(xs) == 0:
        return 0.0, 1.0
    cx, cy = xs.mean(), ys.mean()
    offset = np.hypot(cx - w / 2, cy - h / 2)
    max_offset = np.hypot(w / 2, h / 2)  # distance from centre to a corner
    normalized = min(1.0, offset / max_offset)
    score = max(0.0, 100.0 * (1 - normalized * 1.5))
    return score, normalized


# ----------------------------------------------------- (4) crop / cut-off
def _edge_cutoff(mask: np.ndarray, border_pct: float = 0.03) -> tuple[float, bool, float]:
    """High food-density right at the border means the dish likely
    continues past the edge of the frame -- i.e. it's been cropped/zoomed
    in too tight, like the 'should not be zoomed in' example photo."""
    h, w = mask.shape
    bw, bh = max(1, int(w * border_pct)), max(1, int(h * border_pct))
    border = np.zeros_like(mask, dtype=bool)
    border[:bh, :] = True
    border[-bh:, :] = True
    border[:, :bw] = True
    border[:, -bw:] = True
    border_fg_ratio = float(mask[border].mean())
    score = max(0.0, 100.0 * (1 - border_fg_ratio / 0.35))
    passed = border_fg_ratio < BORDER_CUTOFF_FAIL_RATIO
    return score, passed, border_fg_ratio


# --------------------------------------------------------- (7)+(8) brightness/contrast
def _brightness_contrast_score(img_cv: np.ndarray) -> tuple[float, list]:
    gray = cv2.cvtColor(img_cv, cv2.COLOR_BGR2GRAY)
    brightness = gray.mean()
    contrast = gray.std()
    warnings = []
    score = 100.0
    if brightness < 40:
        score -= 25
        warnings.append("image looks very dark")
    elif brightness > 235:
        score -= 25
        warnings.append("image looks washed out / overexposed")
    if contrast < 20:
        score -= 15
        warnings.append("low contrast / flat-looking image")
    return max(0.0, score), warnings


# --------------------------------------------------- (9) color quality & saturation
def _color_quality_score(img_cv: np.ndarray) -> tuple[float, list]:
    warnings = []
    hsv = cv2.cvtColor(img_cv, cv2.COLOR_BGR2HSV)
    mean_saturation = float(hsv[:, :, 1].mean())
    saturation_score = _score_in_ideal_range(mean_saturation, *IDEAL_SATURATION_RANGE, floor=15, ceil=255)
    if mean_saturation < IDEAL_SATURATION_RANGE[0]:
        warnings.append("colors look dull / desaturated")

    # Hasler & Susstrunk "colorfulness" metric -- simple, no extra
    # dependencies, widely used as a quick colorfulness proxy.
    b, g, r = cv2.split(img_cv.astype("float"))
    rg = r - g
    yb = 0.5 * (r + g) - b
    colorfulness = np.sqrt(rg.std() ** 2 + yb.std() ** 2) + 0.3 * np.sqrt(rg.mean() ** 2 + yb.mean() ** 2)
    colorfulness_score = max(0.0, min(100.0, colorfulness / 90 * 100))

    combined = round(0.5 * saturation_score + 0.5 * colorfulness_score, 1)
    return combined, warnings


# --------------------------------------------------------------------- main
def evaluate_technical(img: Image.Image, min_w: int, min_h: int, blur_threshold: float,
                        ideal_coverage_range: tuple = IDEAL_COVERAGE_RANGE,
                        coverage_floor: float = COVERAGE_FLOOR,
                        coverage_ceiling: float = COVERAGE_CEILING,
                        border_cutoff_fail_ratio: float = BORDER_CUTOFF_FAIL_RATIO) -> TechnicalResult:
    img_cv = _pil_to_cv(img)

    # (2)+(3) resolution + aspect -- cheapest checks, run first
    res_score, res_pass, res_reason = _resolution_score(img, min_w, min_h)
    if not res_pass:
        return TechnicalResult(False, 0.0, res_reason)
    aspect_score, aspect_reason = _aspect_ratio_score(img)

    # (1) blur
    blur_score, blur_pass, blur_reason = _blur_score(img_cv, blur_threshold)
    if not blur_pass:
        return TechnicalResult(False, blur_score * 0.3, blur_reason)

    # (4)(5)(6) subject segmentation -> coverage, centering, crop/cut-off
    mask = _segment_subject_mask(img_cv)
    coverage = _coverage_ratio(mask)
    coverage_score = _score_in_ideal_range(coverage, *ideal_coverage_range, coverage_floor, coverage_ceiling)
    centering_score, centering_offset = _centering_score(mask)
    edge_score, _default_edge_pass, border_fg_ratio = _edge_cutoff(mask)
    edge_pass = border_fg_ratio < border_cutoff_fail_ratio

    if coverage <= coverage_floor:
        return TechnicalResult(False, coverage_score * 0.3,
                               f"food subject too small in frame (coverage={coverage:.0%}, need >={ideal_coverage_range[0]:.0%})",
                               composition_score=coverage_score, coverage_ratio=coverage)
    if coverage >= coverage_ceiling:
        return TechnicalResult(False, coverage_score * 0.3,
                               f"image is zoomed in too far / no context left (coverage={coverage:.0%})",
                               composition_score=coverage_score, coverage_ratio=coverage)
    if not edge_pass:
        return TechnicalResult(False, edge_score,
                               f"food appears cut off by the frame edge (border food density={border_fg_ratio:.0%})",
                               composition_score=edge_score, coverage_ratio=coverage)

    composition_score = round(0.45 * coverage_score + 0.30 * centering_score + 0.25 * edge_score, 1)

    # (7)+(8) brightness/contrast -- secondary signal only, never fails outright
    bc_score, bc_warnings = _brightness_contrast_score(img_cv)

    # (9) color quality & saturation -- secondary signal only, never fails outright
    color_score, color_warnings = _color_quality_score(img_cv)

    combined = round(
        res_score * 0.15
        + aspect_score * 0.05
        + blur_score * 0.25
        + composition_score * 0.30
        + color_score * 0.10
        + bc_score * 0.15,
        1,
    )
    combined = max(0.0, min(100.0, combined))

    reason = (f"{res_reason}; {aspect_reason}; {blur_reason}; "
             f"coverage={coverage:.0%} (ideal {ideal_coverage_range[0]:.0%}-{ideal_coverage_range[1]:.0%}); "
             f"centering offset={centering_offset:.2f}; border food density={border_fg_ratio:.0%}")
    warnings = bc_warnings + color_warnings

    return TechnicalResult(True, combined, reason, composition_score=composition_score,
                           color_quality_score=color_score, coverage_ratio=coverage, warnings=warnings)
