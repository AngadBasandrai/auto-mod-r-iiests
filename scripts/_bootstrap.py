"""Put src/ on sys.path so scripts run without installing the package.

Also forces UTF-8 on stdout/stderr. The Windows console defaults to cp1252,
which raises UnicodeEncodeError the moment we print an emoji or Devanagari —
and both are everywhere in this corpus.
"""

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

for stream in (sys.stdout, sys.stderr):
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8", errors="replace")
