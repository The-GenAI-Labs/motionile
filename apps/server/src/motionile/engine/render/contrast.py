SRGB_THRESHOLD = 0.04045


def srgb_to_linear(channel: int) -> float:
    value = channel / 255
    return value / 12.92 if value <= SRGB_THRESHOLD else ((value + 0.055) / 1.055) ** 2.4


def relative_luminance(red: float, green: float, blue: float) -> float:
    return (
        0.2126 * srgb_to_linear(round(red))
        + 0.7152 * srgb_to_linear(round(green))
        + 0.0722 * srgb_to_linear(round(blue))
    )


def contrast_ratio(first: float, second: float) -> float:
    lighter, darker = (first, second) if first >= second else (second, first)
    return (lighter + 0.05) / (darker + 0.05)
