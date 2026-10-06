"""Transkriptzeilen je Sprecher, wenn die Stimme mitten in der Äußerung wechselt (Raumtest 06.10.)."""

from coach.hoeren import text_aufteilen


def test_ein_sprecher_bleibt_eine_zeile():
    assert text_aufteilen("Hallo zusammen, los geht's.", [(0, 3, 0)]) == [(0, "Hallo zusammen, los geht's.", 0, 3)]


def test_wechsel_am_satzende():
    text = "Ich finde den kleinen Stand besser. Nein, das sehe ich anders, wir brauchen Platz."
    teile = text_aufteilen(text, [(0, 3.5, 0), (3.5, 8, 1)])
    assert [(p, t) for p, t, _, _ in teile] == [
        (0, "Ich finde den kleinen Stand besser."), (1, "Nein, das sehe ich anders, wir brauchen Platz.")]


def test_unsicherer_abschnitt_wird_eigene_zeile_und_splitter_verschwinden():
    text = "Wir machen das so. Ja aber ich wollte noch sagen dass das nicht reicht. Gut dann weiter."
    teile = text_aufteilen(text, [(0, 2, 0), (2, 2.4, 1), (2.4, 6, None), (6, 8, 2)])
    assert [p for p, *_ in teile] == [0, None, 2]
    assert teile[0][1] == "Wir machen das so." and teile[-1][1].endswith("weiter.")
    assert " ".join(t for _, t, _, _ in teile) == text


def test_zu_wenig_woerter_nicht_teilen():
    assert len(text_aufteilen("Ja genau.", [(0, 1.5, 0), (1.5, 3, 1)])) == 1
