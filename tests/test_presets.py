from autoclipper.engine import MAX_SECONDS
from autoclipper.presets import PRESETS


def test_presets_are_valid():
    for name, p in PRESETS.items():
        if p:
            assert p[0] in ("9:16", "16:9") and 3 <= p[1] <= MAX_SECONDS, name
