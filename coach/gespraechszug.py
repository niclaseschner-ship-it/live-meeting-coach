"""Gesprächszug: was eine Person an Nestor richtet, als EINE Anfrage (Premium im Gespräch).

Der Live-Text zerlegt eine Äußerung in Segmente („…kannst du uns zusammenfassen“ | „was wir beschlossen haben“).
Entschiede Nestor am ersten Segment, verstünde er nur die Hälfte. Deshalb sammelt ein Zug alle Sätze, bis eine
Pause kommt (kein neuer Satz und kein laufender Teiltext für `zug_pause_sekunden`), und geht dann als ein Aufruf
an das Modell.

Ein Zug beginnt mit dem Namen („Nestor, …“), nach „Ja?“/dem Knopf, oder ohne Namen im Hörfenster direkt nach
Nestors Antwort. Sagt währenddessen jemand anderes etwas, schließt das den Zug nicht: der Satz kommt mit
Sprecherangabe in dieselbe Anfrage, und das Modell entscheidet, ob es gemeint war (Werkzeug `nicht_an_mich`).

Reine Logik ohne Netz und ohne Uhr – die Zeiten kommen von außen (coach/assistent.py).
"""

from __future__ import annotations

from dataclasses import dataclass, field

HOECHSTENS_SAETZE = 8
# Hinweis vor einem Zug, der ohne Namen im Hörfenster kam: das Modell entscheidet, ob er an Nestor ging
OHNE_NAMEN = "(Ohne deinen Namen, direkt nach deiner Antwort gesagt – ist das an dich gerichtet?)"


@dataclass
class Teil:
    sprecher: str | None
    text: str
    start: float
    ende: float


@dataclass
class Zug:
    ausloeser: str            # ansprache | frage_nach_knopf | hoerfenster
    gerichtet: bool           # mit Namen, nach „Ja?“ oder dem Knopf; False = Hörfenster (Modell entscheidet)
    sprecher: str | None      # wer den Zug begonnen hat
    angekommen: float         # Uhr (monoton) beim letzten Satz – für die Höchstwartezeit
    teile: list[Teil] = field(default_factory=list)

    def dazu(self, teil: Teil, jetzt: float, gerichtet: bool = False) -> None:
        """Ein weiterer Satz, solange der Zug offen ist – von wem auch immer; mit Namen wird der Zug gerichtet."""
        self.teile.append(teil)
        self.angekommen = jetzt
        self.gerichtet = self.gerichtet or gerichtet

    @property
    def ende(self) -> float:
        """Meetingzeit, zu der der letzte Satz endete – ab hier zählt die Pause."""
        return max(t.ende for t in self.teile)

    def fertig(self, meetingzeit: float, uhr: float, teiltext_laeuft: bool, pause: float, max_warten: float) -> bool:
        """Pause erreicht (seit dem letzten Satzende `pause` s, und niemand spricht gerade) oder zu lange gewartet
        (`max_warten` s Uhrzeit seit dem letzten Satz, auch wenn weiter geredet wird) oder zu viele Sätze."""
        if uhr - self.angekommen >= max_warten or len(self.teile) >= HOECHSTENS_SAETZE:
            return True
        return meetingzeit - self.ende >= pause and not teiltext_laeuft

    def mehrere_sprecher(self) -> bool:
        return len({t.sprecher for t in self.teile if t.text}) > 1

    def eigener_text(self) -> str:
        """Nur, was die Person gesagt hat, die den Zug begonnen hat (für „nur der Name?“)."""
        return " ".join(t.text for t in self.teile if t.sprecher == self.sprecher and t.text).strip()

    def anfrage(self) -> str:
        """Der Text für das Modell: eine Person → ihr zusammengefügter Text; mehrere → je Zeile mit Sprecher."""
        teile = [t for t in self.teile if t.text]
        if self.mehrere_sprecher():
            text = "\n".join(f"{t.sprecher or 'Jemand'}: {t.text}" for t in teile)
        else:
            text = " ".join(t.text for t in teile)
        return text.strip()


def fuer_modell(text: str, gerichtet: bool) -> str:
    """Die Anfrage, wie das Modell sie bekommt: ohne Namen mit dem Hinweis, dass es selbst entscheidet."""
    return text if gerichtet else f"{OHNE_NAMEN}\n{text}"


def im_hoerfenster(start: float, ende: float, ab: float, bis: float) -> bool:
    """Beginnt der Satz rechtzeitig (bis zum Ende der Frist) und endet er nach Nestors Antwort?"""
    return bis > ab and ende >= ab and start <= bis
