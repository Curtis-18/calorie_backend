"""The server's own words (report sentences, badges, push text...) in the
languages the app offers. English is the key and the default: a language or a
phrase that is missing is simply answered in English.

`lang` is one of SUPPORTED, from the request's Accept-Language header (the app
sends its language there) or, for push notifications, the language the person
last used the app in.
"""

import re

from app.i18n import de, errors, es, fr, it, pt

SUPPORTED = ("en", "es", "fr", "de", "pt", "it")
DEFAULT = "en"

# For prompts to the language model.
LANGUAGE_NAMES = {
    "en": "English",
    "es": "Spanish",
    "fr": "French",
    "de": "German",
    "pt": "Portuguese",
    "it": "Italian",
}

TABLES: dict[str, dict[str, str]] = {
    "es": es.TABLE,
    "fr": fr.TABLE,
    "de": de.TABLE,
    "pt": pt.TABLE,
    "it": it.TABLE,
}

# The error messages join the same tables (kept in their own file: errors.py).
for _i, _code in enumerate(errors.ORDER):
    TABLES[_code] = {**TABLES[_code], **{en: tr[_i] for en, tr in errors.ERRORS.items()}}

_TEMPLATES = {
    _code: [
        (re.compile("^" + re.escape(en).replace(r"\{date\}", "(?P<date>.+?)").replace(r"\{name\}", "(?P<name>.+)") + "$"), tr[_i])
        for en, tr in errors.TEMPLATES.items()
    ]
    for _i, _code in enumerate(errors.ORDER)
}


def translate_detail(lang: str, text):
    """An error message in [lang]: a listed message, or a listed message with a
    value inside it (a date, a food name); anything else (a machine code such as
    `ai_quota`, a list of validation problems) is returned as it was."""
    if not isinstance(text, str) or lang == DEFAULT:
        return text
    hit = TABLES.get(lang, {}).get(text)
    if hit:
        return hit
    for pattern, template in _TEMPLATES.get(lang, []):
        m = pattern.match(text)
        if m:
            return template.format(**m.groupdict())
    return text


_TAG = re.compile(r"^\s*([A-Za-z]{2,3})(?:-[A-Za-z0-9]+)*\s*(?:;\s*q\s*=\s*([0-9.]+))?\s*$")


def parse_language(header: str | None) -> str:
    """The best supported language in an Accept-Language value ("es-MX,es;q=0.9,en;q=0.8"),
    or English. Only the language part matters ("pt-BR" is Portuguese)."""
    if not header:
        return DEFAULT
    best, best_q = DEFAULT, -1.0
    for part in header.split(",")[:20]:
        m = _TAG.match(part)
        if not m:
            continue
        code = m.group(1).lower()
        try:
            q = float(m.group(2)) if m.group(2) else 1.0
        except ValueError:
            continue
        if code in SUPPORTED and q > best_q and q > 0:
            best, best_q = code, q
    return best


def normalize(language: str | None) -> str:
    """A stored or supplied language code as one of SUPPORTED."""
    code = (language or "").strip().lower()[:2]
    return code if code in SUPPORTED else DEFAULT


def t(lang: str, english: str, **params) -> str:
    """[english] in [lang], with {placeholders} filled in."""
    text = TABLES.get(lang, {}).get(english, english)
    return text.format(**params) if params else text
