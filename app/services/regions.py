"""Where a person mostly eats: context for naming dishes, never a filter.

The keys are what the app stores and sends; the labels go into prompts. A key
we don't know is ignored, so a newer app can't put arbitrary text into a prompt.
"""

REGIONS: dict[str, str] = {
    "north_america": "North America",
    "latin_america": "Latin America and the Caribbean",
    "europe": "Europe",
    "west_africa": "West Africa",
    "east_africa": "East Africa",
    "southern_africa": "Southern Africa",
    "north_africa_middle_east": "North Africa and the Middle East",
    "south_asia": "South Asia",
    "east_asia": "East Asia",
    "southeast_asia": "Southeast Asia",
    "oceania": "Australia and the Pacific",
    "other": "Other",
}


def region_label(key: str | None) -> str | None:
    """The label for a known key, else None ("Other" gives no useful hint)."""
    if not key or key == "other":
        return None
    return REGIONS.get(key)


def is_region(key: str) -> bool:
    return key in REGIONS
