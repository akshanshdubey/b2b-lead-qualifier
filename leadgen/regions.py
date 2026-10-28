"""Tiny offline geography helper so 'Austin, Texas' can match an ICP region of 'United States'."""
from __future__ import annotations

import re
from functools import lru_cache

US_STATES = [
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa",
    "kansas", "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan",
    "minnesota", "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire",
    "new jersey", "new mexico", "new york", "north carolina", "north dakota", "ohio",
    "oklahoma", "oregon", "pennsylvania", "rhode island", "south carolina", "south dakota",
    "tennessee", "texas", "utah", "vermont", "virginia", "washington", "west virginia",
    "wisconsin", "wyoming", "san francisco", "silicon valley", "boston", "seattle", "austin",
]

COUNTRIES: dict[str, list[str]] = {
    "united states": ["united states", "usa", "u.s.a", "u.s", "us", "america", *US_STATES],
    "canada": ["canada", "ontario", "quebec", "british columbia", "alberta", "toronto",
               "vancouver", "montreal"],
    "united kingdom": ["united kingdom", "uk", "u.k", "england", "scotland", "wales",
                       "northern ireland", "great britain", "london"],
    "germany": ["germany", "deutschland", "berlin", "munich"],
    "france": ["france", "paris"],
    "netherlands": ["netherlands", "holland", "amsterdam", "rotterdam"],
    "ireland": ["ireland", "dublin"],
    "spain": ["spain", "madrid", "barcelona"],
    "sweden": ["sweden", "stockholm"],
    "india": ["india", "bengaluru", "bangalore", "mumbai", "delhi", "hyderabad", "pune", "chennai"],
    "pakistan": ["pakistan", "karachi", "lahore", "islamabad"],
    "australia": ["australia", "sydney", "melbourne"],
    "singapore": ["singapore"],
    "japan": ["japan", "tokyo"],
    "mexico": ["mexico"],
    "united arab emirates": ["united arab emirates", "uae", "dubai", "abu dhabi"],
    "saudi arabia": ["saudi arabia", "riyadh"],
}

GROUPS: dict[str, list[str]] = {
    "north america": ["united states", "canada", "mexico"],
    "europe": ["united kingdom", "germany", "france", "netherlands", "ireland", "spain", "sweden"],
    "emea": ["united kingdom", "germany", "france", "netherlands", "ireland", "spain", "sweden",
             "united arab emirates", "saudi arabia"],
    "apac": ["india", "australia", "singapore", "japan"],
}


@lru_cache(maxsize=None)
def _pattern(alias: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z]){re.escape(alias)}(?![a-z])")


def countries_in(text: str) -> set[str]:
    low = (text or "").lower()
    return {c for c, aliases in COUNTRIES.items() if any(_pattern(a).search(low) for a in aliases)}


def region_matches(value: str, targets: list[str]) -> tuple[bool, str | None]:
    """Return (matched, which_target). Matches by country alias, region group or literal text."""
    low = (value or "").lower()
    found = countries_in(low)
    for target in targets:
        tl = target.lower().strip()
        if not tl:
            continue
        allowed = set(GROUPS.get(tl, [])) or countries_in(tl)
        if found & allowed:
            return True, target
        if _pattern(tl).search(low):
            return True, target
    return False, None
