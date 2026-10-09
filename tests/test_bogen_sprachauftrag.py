"""Enge Erkennung eindeutiger gesprochener Aufträge zum Bündeln von Ergebnissen."""

import pytest

from coach.bogen import karten_art


@pytest.mark.parametrize("auftrag", [
    "bündel mir mal die Ergebnisse",
    "Fasse die Ergebnisse zusammen",
    "fass mir die Ergebnisse zusammen",
    "Ergebnisse bündeln",
])
def test_ergebnisse_buendeln_imperativ_wird_erkannt(auftrag):
    assert karten_art(auftrag) == "zusammenfassen"


@pytest.mark.parametrize("frage", [
    "Was hältst du von den Ergebnissen?",
    "Kannst du erklären, wie die Ergebnisse zusammenhängen?",
    "Fasse zusammen, was Anna zum Budget gesagt hat",
    "Warum bündelst du mir die Ergebnisse nicht?",
])
def test_beilaeufige_ergebniswoerter_bleiben_normale_fragen(frage):
    assert karten_art(frage) is None
