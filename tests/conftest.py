"""Gemeinsame Testumgebung: ein im Dashboard eingetragener Schlüssel des Rechners darf Tests nicht beeinflussen."""

import os
import tempfile
from pathlib import Path

os.environ["LMC_SCHLUESSEL_DATEI"] = str(Path(tempfile.mkdtemp()) / "openai_schluessel")
