"""Gemeinsame Testumgebung: ein im Dashboard eingetragener Schlüssel des Rechners darf Tests nicht beeinflussen."""

import os
import tempfile
from pathlib import Path

os.environ["LMC_SCHLUESSEL_DATEI"] = str(Path(tempfile.mkdtemp()) / "openai_schluessel")
# Sofort-Bestätigung (Ticket #21) spielt zusätzliche Floskeln ab – die meisten Tests zählen Tonstücke ohne sie;
# tests/test_bestaetigung.py schaltet sie gezielt ein
os.environ.setdefault("LMC_BESTAETIGUNG", "0")
os.environ.setdefault("LMC_FLOSKEL_ORDNER", str(Path(tempfile.mkdtemp()) / "floskeln"))
