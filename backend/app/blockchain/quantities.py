import re

_KILOGRAM_PATTERN = re.compile(r"([0-9]+)(?:\.([0-9]{1,3}))?")


def kilograms_to_grams(text: object) -> int:
    match = _KILOGRAM_PATTERN.fullmatch(text) if isinstance(text, str) else None
    if match is None:
        raise ValueError("A quantity must be a number of kilograms with at most three decimal places.")
    whole, fraction = match.group(1), match.group(2) or ""
    return int(whole) * 1000 + int(fraction.ljust(3, "0"))
