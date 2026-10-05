"""Alle Endpunkte, die das Dashboard (static/app.js) aufruft, müssen existieren."""

import os
import re
from pathlib import Path

os.environ.setdefault("LMC_OFFLINE", "1")

from coach.server import app  # noqa: E402


def test_dashboard_endpunkte_existieren():
    js = (Path(__file__).resolve().parent.parent / "static" / "app.js").read_text(encoding="utf-8")
    aufgerufen = set(re.findall(r'["`](/(?:api|ws)/[a-z/._]+)', js)) | {"/ws"}
    vorhanden = {r.path for r in app.routes}
    fehlend = {p for p in aufgerufen if p.rstrip("/") not in vorhanden}
    assert not fehlend, f"Dashboard ruft fehlende Endpunkte auf: {sorted(fehlend)}"
