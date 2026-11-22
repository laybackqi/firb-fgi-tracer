"""The advanced reader: a language model the user connects with their own key.

Any service with an OpenAI-compatible chat completions endpoint works. The
app offers presets for a few; the base URL and model name can be changed.

The model is asked for JSON in a fixed shape and its answer is turned into
the same Extraction the basic reader returns. Its answer is a draft:

* each holding must quote the sentence it came from; a quote that cannot be
  found in the text is flagged, because the figures may be invented;
* the model is told not to characterise anyone as a government or SOE, and
  every entity's government status is set to "uncertain" anyway (R1);
* indirect percentages must be left unread, not entered as holdings.

The key is sent only to the base URL the user chose, with the text. Nothing
is stored.
"""

from __future__ import annotations

import json
import re
import socket
import unicodedata
import urllib.error
import urllib.request
from typing import Any

from .extraction import Extraction, Found

# Presets checked against each provider's documentation on 2026-11-22.
PROVIDERS: dict[str, dict[str, str]] = {
    "DeepSeek": {"base_url": "https://api.deepseek.com", "model": "deepseek-flash"},
    "Qwen (Alibaba Cloud Model Studio, Beijing)": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1", "model": "qwen-plus"},
    "OpenAI": {"base_url": "https://api.openai.com/v1", "model": ""},
    "Other OpenAI-compatible service": {"base_url": "", "model": ""},
}

MAX_CHARS = 30_000
TIMEOUT_SECONDS = 120

SYSTEM_PROMPT = """You read ownership summaries for a foreign investment screening tool.
Return one JSON object, and nothing else, in exactly this shape:

{
  "entities": [{"name": "...", "kind": "government | corporation | individual", "country": "CN" or null}],
  "holdings": [{"holder": "...", "held": "...", "shares_pct": 25, "voting_pct": null,
                "proposed": false, "veto": false, "board_seats": null, "quote": "..."}],
  "buyer": "..." or null,
  "target": "..." or null,
  "unread": ["..."]
}

Rules:
1. One entity per legal person. Use its full name as written in the text; where the text
   defines a short name (以下简称, hereinafter, "the Buyer"), use the full name everywhere.
2. A holding is one DIRECT holding stated in the text: holder owns shares_pct percent of the
   issued shares or registered capital of held. Give voting_pct only if the text states a
   different voting percentage.
3. Never calculate. If the text gives an indirect or look-through percentage (间接, through,
   via), do not create a holding for it: put the sentence in "unread".
4. "proposed": true only for a holding the transaction would create (拟, will, proposes to).
   If the holder already has a stake and will acquire more, return two holdings: the existing
   stake (proposed false) and the additional stake (proposed true).
5. "veto": true only if the text says the holder can veto decisions of held.
   "board_seats": e.g. "2/5", only if stated.
6. "kind": "government" only for a government body itself (a ministry, a SASAC, a people's
   government). A state-owned company is a "corporation". Do NOT judge whether anyone is a
   foreign government, a separate government entity or state-owned: a lawyer decides that.
7. "country": an ISO 3166 two-letter code, only if the text states where the entity is
   incorporated or the place is part of its registered name; otherwise null.
8. "quote": copy, word for word, the sentence or list line the holding comes from.
9. "buyer" and "target": the acquirer and the Australian target, if the text says so.
10. "unread": every other sentence about ownership or control you could not express above,
    e.g. voting agreements, nominee arrangements, options, control by agreement.
Percentages are numbers without the % sign.
"""


class ModelError(RuntimeError):
    """The model could not be reached, or its answer could not be used."""


# --------------------------------------------------------------------------
# The request
# --------------------------------------------------------------------------


def _post(url: str, key: str, body: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {key}"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        reasons = {
            401: "the API key was rejected",
            403: "the API key is not allowed to use this model",
            404: "the address or model name was not found; check the base URL and model",
            429: "the service refused for rate or quota reasons; check your balance or wait",
        }
        raise ModelError(f"{reasons.get(exc.code, f'the service returned error {exc.code}')}. {detail}") from None
    except (socket.timeout, TimeoutError):
        raise ModelError(f"no answer within {TIMEOUT_SECONDS} seconds; try a shorter text") from None
    except urllib.error.URLError as exc:
        raise ModelError(f"could not reach {url}: {exc.reason}") from None
    except json.JSONDecodeError:
        raise ModelError("the service did not return JSON; check the base URL") from None


def ask_model(text: str, base_url: str, api_key: str, model: str) -> dict[str, Any]:
    """Send the text and return the model's JSON answer as a dict."""
    if not text.strip():
        raise ModelError("there is no text to read")
    if len(text) > MAX_CHARS:
        raise ModelError(f"the text is longer than {MAX_CHARS:,} characters; paste only the ownership part")
    if not (base_url and api_key and model):
        raise ModelError("base URL, API key and model name are all needed")

    reply = _post(
        base_url.rstrip("/") + "/chat/completions",
        api_key.strip(),
        {
            "model": model.strip(),
            "messages": [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": text}],
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "max_tokens": 4000,
        },
    )
    try:
        content = reply["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError):
        raise ModelError("the answer was not in the expected chat completions format") from None
    content = re.sub(r"^\s*```(?:json)?|```\s*$", "", content or "").strip()  # some models fence JSON
    try:
        answer = json.loads(content)
    except json.JSONDecodeError:
        raise ModelError("the model's answer was not valid JSON; try again or use another model") from None
    if not isinstance(answer, dict):
        raise ModelError("the model's answer was not a JSON object")
    return answer


# --------------------------------------------------------------------------
# The answer, as an Extraction
# --------------------------------------------------------------------------


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", text))


def _pct(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(str(value).replace("%", "").strip())
    except ValueError:
        return None
    return number if 0 < number <= 100 else None


def to_extraction(answer: dict[str, Any], text: str) -> Extraction:
    """Check the model's answer against the text and turn it into a draft."""
    out = Extraction(reader="model")
    source_text = _squash(text)

    for raw in answer.get("entities") or []:
        if not isinstance(raw, dict) or not str(raw.get("name") or "").strip():
            continue
        name = str(raw["name"]).strip()
        kind = str(raw.get("kind") or "").lower()
        out.kinds[name] = kind if kind in ("government", "individual") else "corporation"
        country = str(raw.get("country") or "").strip().upper()
        if re.fullmatch(r"[A-Z]{2}", country):
            out.countries[name] = country

    for raw in answer.get("holdings") or []:
        if not isinstance(raw, dict):
            continue
        holder, held = str(raw.get("holder") or "").strip(), str(raw.get("held") or "").strip()
        pct, quote = _pct(raw.get("shares_pct")), str(raw.get("quote") or "").strip()
        if not holder or not held or holder == held or pct is None:
            out.notes.append(f"Skipped a holding the model returned incompletely: {json.dumps(raw, ensure_ascii=False)}")
            continue
        if not quote or _squash(quote) not in source_text:
            out.notes.append(f"{holder} → {held} ({pct:g}%): the model's quote is not in your text. "
                             "Check this row against the original; the figure may be wrong.")
        board = str(raw.get("board_seats") or "").strip()
        out.add(Found(
            holder=holder, held=held, pct=pct, proposed=raw.get("proposed") is True, source=quote,
            voting_pct=_pct(raw.get("voting_pct")), veto=raw.get("veto") is True,
            board_seats=board if re.fullmatch(r"\d+\s*/\s*\d+", board) else "",
        ))

    known = set(out.names)
    for role in ("buyer", "target"):
        value = str(answer.get(role) or "").strip()
        if value and value in known:
            setattr(out, role, value)
        elif value:
            out.notes.append(f"The model named '{value}' as the {role}, but it is not in any holding; choose it in section 3.")

    out.unread = [str(s).strip() for s in answer.get("unread") or [] if str(s).strip()]
    return out


def read_with_model(text: str, base_url: str, api_key: str, model: str) -> Extraction:
    """Ask the model, then check and convert its answer."""
    return to_extraction(ask_model(text, base_url, api_key, model), text)
