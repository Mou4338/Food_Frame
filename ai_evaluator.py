"""Optional AI vision evaluation -- judges whether a candidate actually,
semantically, shows the requested dish in a way suitable for a restaurant
menu photo. Technical checks alone (blur, resolution, coverage) cannot
tell a photo of fries apart from a photo of biryani -- this step can.

Two providers are supported:
  - Google Gemini  (primary, default)
  - Groq            (fallback -- openai/gpt-oss-120b by default,
                     an OpenAI-compatible chat-completions vision model,
                     used automatically ONLY if Gemini's call fails/errors
                     and GROQ_API_KEY is configured)

Critical rule from the spec: an AI/API failure must NEVER be silently
turned into a passing score. If BOTH providers fail (or the configured
one(s) aren't reachable), the caller treats the candidate as ERROR/needs
retry for the AI step, not as "AI said it's fine".
"""
import base64
import io
import json
from dataclasses import dataclass

import requests
from PIL import Image

GEMINI_URL_TEMPLATE = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Groq's vision models have been deprecated one after another (Llama 4 Scout
# on 2026-07-17, Llama 4 Maverick on 2026-03-09) in favor of text-only
# openai/gpt-oss-120b, which CANNOT accept images (every image request to it
# returns 400 Bad Request). qwen/qwen3.8-27b is Groq's current -- and only --
# vision-capable chat model as of Sept 2026. Check
# https://console.groq.com/docs/vision before changing this again.
GROQ_DEFAULT_MODEL = "qwen/qwen3.8-27b"

PROMPT_TEMPLATE = """You are grading a candidate photo for the restaurant menu item "{food_name}".
Look only at what is visible in the image. Respond with ONLY a compact JSON object
(no markdown fences, no extra text) with exactly these keys:
{{
  "food_match": true/false,        // does the image plausibly show this dish (or a very close visual match)?
  "menu_suitable": true/false,     // would this be acceptable as a restaurant menu photo?
  "food_visible": true/false,      // is food actually visible and not obscured?
  "blur": true/false,              // is the image noticeably blurry?
  "excessive_crop": true/false,    // is the dish cropped too tightly / zoomed too far in?
  "watermark": true/false,         // any visible watermark?
  "logo_or_text": true/false,      // any logos, heavy text overlays, or screenshots?
  "screenshot_or_collage": true/false,
  "composition_score": 0-100,      // framing/centering/plating quality
  "confidence": 0-100,             // your confidence in this judgement
  "score": 0-100,                  // your OVERALL suitability score for this exact dish as a menu photo
  "reason": "one short sentence explaining the score"
}}"""


@dataclass
class AIResult:
    ok: bool                      # False means the AI call itself failed -- treat as ERROR, not a pass
    score: float = 0.0
    composition_score: float = 0.0
    confidence: float = 0.0
    raw: dict | None = None
    error: str = ""
    provider: str = ""            # "gemini" or "groq" -- which provider actually produced this result


def _image_to_jpeg_b64(img: Image.Image) -> str:
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="JPEG", quality=85)
    return base64.b64encode(buffer.getvalue()).decode()


def _parse_json_result(data: dict, provider: str) -> AIResult:
    try:
        score = float(data.get("score", 0))
        composition = float(data.get("composition_score", score))
        confidence = float(data.get("confidence", 0))
    except (TypeError, ValueError):
        return AIResult(False, error=f"{provider} returned a malformed response", provider=provider)
    return AIResult(True, score=score, composition_score=composition, confidence=confidence,
                    raw=data, provider=provider)


def evaluate_with_gemini(img: Image.Image, food_name: str, api_key: str, model: str = "gemini-flash-latest") -> AIResult:
    if not api_key:
        return AIResult(False, error="no Gemini API key configured", provider="gemini")
    try:
        b64 = _image_to_jpeg_b64(img)
        prompt = PROMPT_TEMPLATE.format(food_name=food_name)
        resp = requests.post(
            GEMINI_URL_TEMPLATE.format(model=model),
            headers={"content-type": "application/json"},
            params={"key": api_key},
            json={
                "contents": [{"parts": [
                    {"inline_data": {"mime_type": "image/jpeg", "data": b64}},
                    {"text": prompt},
                ]}],
                # maxOutputTokens must cover Gemini's internal "thinking" pass
                # too, or the real JSON answer gets cut off mid-string before
                # it's ever written (that's the "Unterminated string" parse
                # errors) -- thinkingBudget: 0 turns thinking off entirely so
                # every token goes to the actual answer, and 1024 is a safety
                # margin even if a future model ignores that setting.
                "generationConfig": {
                    "maxOutputTokens": 1024,
                    "temperature": 0.1,
                    "thinkingConfig": {"thinkingBudget": 0},
                },
            },
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()["candidates"][0]["content"]["parts"][0]["text"].strip()
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:].strip()
        data = json.loads(text)
    except Exception as e:
        # AI failure -> explicit error, never a silent pass.
        return AIResult(False, error=f"Gemini evaluation failed: {e}", provider="gemini")

    return _parse_json_result(data, "gemini")


def evaluate_with_groq(img: Image.Image, food_name: str, api_key: str,
                       model: str = GROQ_DEFAULT_MODEL) -> AIResult:
    """Groq's chat-completions API is OpenAI-compatible; vision-capable
    models (llama-4-scout / llama-4-maverick) accept an image_url content
    block with a base64 data URI. JSON mode is used to make the structured
    response reliable."""
    if not api_key:
        return AIResult(False, error="no Groq API key configured", provider="groq")
    try:
        b64 = _image_to_jpeg_b64(img)
        prompt = PROMPT_TEMPLATE.format(food_name=food_name)
        resp = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [{
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
                    ],
                }],
                "temperature": 0.1,
                "max_tokens": 300,
                "response_format": {"type": "json_object"},
            },
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        data = json.loads(text)
    except Exception as e:
        return AIResult(False, error=f"Groq evaluation failed: {e}", provider="groq")

    return _parse_json_result(data, "groq")


def evaluate_with_fallback(img: Image.Image, food_name: str, secrets, cfg: dict) -> AIResult:
    """Tries the configured primary AI provider (Gemini by default) first;
    if that call itself fails (bad key, timeout, rate limit, malformed
    response -- NOT a low score, which is a valid result), and a Groq key
    is configured, automatically retries with Groq before giving up.
    A genuine low/negative score from the primary provider is a real
    result and is returned as-is -- fallback only fires on call failure."""
    ai_cfg = cfg["ai"]
    primary = ai_cfg.get("provider", "gemini")

    if primary == "groq":
        result = evaluate_with_groq(img, food_name, secrets.GROQ_API_KEY, ai_cfg.get("groq_model", GROQ_DEFAULT_MODEL))
        if result.ok or not secrets.GEMINI_API_KEY:
            return result
        fallback = evaluate_with_gemini(img, food_name, secrets.GEMINI_API_KEY, ai_cfg.get("model", "gemini-flash-latest"))
        fallback.error = f"primary (groq) failed: {result.error}; fallback (gemini): {fallback.error}" if not fallback.ok else fallback.error
        return fallback

    result = evaluate_with_gemini(img, food_name, secrets.GEMINI_API_KEY, ai_cfg.get("model", "gemini-flash-latest"))
    if result.ok or not secrets.GROQ_API_KEY:
        return result
    fallback = evaluate_with_groq(img, food_name, secrets.GROQ_API_KEY, ai_cfg.get("groq_model", GROQ_DEFAULT_MODEL))
    fallback.error = f"primary (gemini) failed: {result.error}; fallback (groq): {fallback.error}" if not fallback.ok else fallback.error
    return fallback
