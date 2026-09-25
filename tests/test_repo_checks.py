"""Language and secret checks run as pytest cases, so a hit fails locally before CI."""

import check_language
import check_secrets


def test_language_check_passes_on_repository():
    hits = check_language.scan()
    assert hits == [], "\n".join(f"{f}:{n}: {w}" for f, n, w in hits)


def test_language_check_catches_planted_words():
    audience, pronoun = "stu" + "dent", "yo" + "u"
    hits = check_language.scan_text([f"The {audience} opens the app.", f"Then {pronoun} click.", "US dollars pass."])
    assert [w for _, w in hits] == [audience, pronoun]


def test_roman_numeral_one_is_not_the_pronoun():
    pronoun = "i".upper()
    lines = [f"## {pronoun}. Programs", f"Term {pronoun} starts in May.", f"Then {pronoun} click."]
    assert [n for n, _ in check_language.scan_text(lines)] == [3]


def test_language_markers_switch_off_checking():
    hidden, shown = "w" + "e", "ou" + "r"
    lines = ["<!-- language-check: off -->", hidden, "<!-- language-check: on -->", shown]
    assert [w for _, w in check_language.scan_text(lines)] == [shown]


def test_secret_scan_passes_on_repository():
    assert check_secrets.main([]) == 0


def test_secret_scan_catches_planted_keys():
    planted = "NVIDIA_API_KEY=nvapi-" + "A1b2C3d4E5f6G7h8I9j0K1" + "\nLAYA_API_KEY=" + "laya_srv_0123456789"
    assert len(check_secrets.scan_text(planted)) == 2
    assert check_secrets.scan_text("LAYA_API_KEY=laya-replace-with-a-real-key") == []
