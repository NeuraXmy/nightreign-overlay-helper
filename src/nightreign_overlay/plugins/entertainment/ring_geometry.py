"""Pure geometric templates shared by self and teammate ring classifiers."""

import numpy as np

_SIZE = 32


def make_ring_template(*, first_sector: bool = False, fill_degrees: float | None = None) -> np.ndarray:
    y, x = np.mgrid[:_SIZE, :_SIZE].astype(np.float32)
    x = (x - (_SIZE - 1) / 2) / (_SIZE / 2)
    y = (y - (_SIZE - 1) / 2) / (_SIZE / 2)
    radius = np.hypot(x, y)
    angle = np.degrees(np.arctan2(y, x))
    separator = np.minimum.reduce([np.abs((angle - center + 180) % 360 - 180) for center in (-90, 30, 150)])
    groove = (radius > 0.40) & (radius < 0.75) & (separator > 10)
    highlight = (
        (radius < 0.27)
        | ((radius > 0.89) & (radius < 0.98))
        | ((radius > 0.40) & (radius < 0.80) & (separator < 3))
    )
    template = np.zeros((_SIZE, _SIZE), np.float32)
    if first_sector:
        groove &= np.abs((angle + 30 + 180) % 360 - 180) < 46
    if fill_degrees is not None:
        groove &= (angle + 90) % 360 < fill_degrees
    template[groove] = -1
    template[highlight] = 1
    # Three pixels of search margin in the normalized input, roughly ±11 pixels
    # at 115×115. The surrounding game scene does not enter the template.
    return np.ascontiguousarray(template[3:-3, 3:-3])
