"""Entscheider: bündelt Hinweise, verhindert Reizüberflutung per Cooldown."""

from __future__ import annotations

from .zustand import Hinweis, Meeting


class Entscheider:
    def __init__(self, cooldown_sekunden: float):
        self.cooldown = cooldown_sekunden
        self._zuletzt: dict[str, float] = {}
        self._einmal: set[str] = set()

    def vorschlagen(
        self,
        meeting: Meeting,
        art: str,
        stufe: str,
        publikum: str,
        text: str,
        schluessel: str | None = None,
    ) -> Hinweis | None:
        """Hinweis ausgeben, sofern derselbe Schlüssel nicht gerade erst kam."""
        k = schluessel or art
        t = meeting.jetzt()
        if k in self._zuletzt and t - self._zuletzt[k] < self.cooldown:
            return None
        self._zuletzt[k] = t
        return self._ausgeben(meeting, art, stufe, publikum, text, t)

    def einmalig(
        self, meeting: Meeting, schluessel: str, art: str, stufe: str, publikum: str, text: str
    ) -> Hinweis | None:
        """Hinweis genau einmal pro Schlüssel (z. B. Ampel eines Agendapunkts)."""
        if schluessel in self._einmal:
            return None
        self._einmal.add(schluessel)
        return self._ausgeben(meeting, art, stufe, publikum, text, meeting.jetzt())

    @staticmethod
    def _ausgeben(meeting, art, stufe, publikum, text, t) -> Hinweis:
        h = Hinweis(art, stufe, publikum, text, t, id=len(meeting.hinweise) + 1)
        meeting.hinweise.append(h)
        return h
