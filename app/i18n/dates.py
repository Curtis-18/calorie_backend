"""Short, natural day names for text the server writes or feeds to the model
("Wed 18 Nov" instead of "2026-11-18"), in the languages the app offers.

Own tables on purpose: `strftime` and `locale` follow the server's settings,
not the person's language.
"""

from datetime import date

_WEEKDAYS = {  # Monday first, like date.weekday()
    "en": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    "es": ("lun", "mar", "mié", "jue", "vie", "sáb", "dom"),
    "fr": ("lun", "mar", "mer", "jeu", "ven", "sam", "dim"),
    "de": ("Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"),
    "pt": ("seg", "ter", "qua", "qui", "sex", "sáb", "dom"),
    "it": ("lun", "mar", "mer", "gio", "ven", "sab", "dom"),
}

_MONTHS = {
    "en": ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"),
    "es": ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"),
    "fr": ("janv", "févr", "mars", "avr", "mai", "juin", "juil", "août", "sept", "oct", "nov", "déc"),
    "de": ("Jan", "Feb", "Mär", "Apr", "Mai", "Jun", "Jul", "Aug", "Sep", "Okt", "Nov", "Dez"),
    "pt": ("jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"),
    "it": ("gen", "feb", "mar", "apr", "mag", "giu", "lug", "ago", "set", "ott", "nov", "dic"),
}


def day_label(day: date, lang: str = "en") -> str:
    """"Wed 18 Nov" (English) or the same in [lang]; English for an unknown language."""
    code = lang if lang in _WEEKDAYS else "en"
    return f"{_WEEKDAYS[code][day.weekday()]} {day.day} {_MONTHS[code][day.month - 1]}"
