from autoclipper.updates import is_newer


def test_is_newer():
    assert is_newer("0.1.2", "0.1.1")
    assert is_newer("0.2.0", "0.1.9")
    assert not is_newer("0.1.1", "0.1.1")
    assert not is_newer("0.1.0", "0.1.1")
    assert not is_newer("", "0.1.1")
