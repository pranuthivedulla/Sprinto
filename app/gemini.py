"""Gemini Flash client. The only AI used anywhere in this pipeline.

Tries the Interactions API first (the current endpoint) and falls back to the
legacy generateContent endpoint, so a key that only works on one of them still runs.
Which endpoint answered is recorded in LAST_ENDPOINT for the spike report.
"""
import json
import re

import requests

from . import config

INTERACTIONS_URL = "https://generativelanguage.googleapis.com/v1beta/interactions"
GENERATE_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)
TIMEOUT = 60

LAST_ENDPOINT = ""
_WORKING_ENDPOINT = ""


def model_name():
    return config.get("GEMINI_MODEL") or config.GEMINI_DEFAULT_MODEL


def _headers():
    key = config.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is not set")
    return {"x-goog-api-key": key, "Content-Type": "application/json"}


def _parse_interactions(payload):
    chunks = []
    for step in payload.get("steps", []) or []:
        if step.get("type") != "model_output":
            continue
        for part in step.get("content", []) or []:
            if part.get("text"):
                chunks.append(part["text"])
    return "\n".join(chunks).strip()


def _parse_generate(payload):
    chunks = []
    for cand in payload.get("candidates", []) or []:
        for part in cand.get("content", {}).get("parts", []) or []:
            if part.get("text"):
                chunks.append(part["text"])
    return "\n".join(chunks).strip()


def _call_interactions(prompt, temperature):
    body = {
        "model": model_name(),
        "input": prompt,
        "generation_config": {"temperature": temperature},
    }
    resp = requests.post(INTERACTIONS_URL, headers=_headers(), json=body, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"interactions HTTP {resp.status_code}: {resp.text[:300]}")
    text = _parse_interactions(resp.json())
    if not text:
        raise RuntimeError("interactions returned no model_output text")
    return text


def _call_generate(prompt, temperature):
    body = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": temperature},
    }
    url = GENERATE_URL.format(model=model_name())
    resp = requests.post(url, headers=_headers(), json=body, timeout=TIMEOUT)
    if resp.status_code != 200:
        raise RuntimeError(f"generateContent HTTP {resp.status_code}: {resp.text[:300]}")
    text = _parse_generate(resp.json())
    if not text:
        raise RuntimeError("generateContent returned no text")
    return text


def call_model(prompt, temperature=0.2):
    """Return the model's text. Remembers which endpoint worked and reuses it."""
    global LAST_ENDPOINT, _WORKING_ENDPOINT
    order = ["interactions", "generate"]
    if _WORKING_ENDPOINT:
        order = [_WORKING_ENDPOINT] + [e for e in order if e != _WORKING_ENDPOINT]
    errors = []
    for endpoint in order:
        try:
            fn = _call_interactions if endpoint == "interactions" else _call_generate
            text = fn(prompt, temperature)
            LAST_ENDPOINT = _WORKING_ENDPOINT = endpoint
            return text
        except RuntimeError as exc:
            errors.append(f"{endpoint}: {exc}")
    raise RuntimeError(" | ".join(errors))


def call_json(prompt, temperature=0.1):
    """Call the model and parse the first JSON object or array out of the reply."""
    text = call_model(prompt + "\n\nReturn JSON only. No prose, no code fences.",
                      temperature)
    return extract_json(text)


def extract_json(text):
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    for opener, closer in (("{", "}"), ("[", "]")):
        start = cleaned.find(opener)
        end = cleaned.rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(cleaned[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise RuntimeError(f"model did not return JSON: {cleaned[:200]}")
