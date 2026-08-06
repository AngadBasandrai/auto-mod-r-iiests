"""One polling pass over r/iiests.

    python scripts/run_bot.py             # dry run (DRY_RUN default is true)
    python scripts/run_bot.py --live      # actually comment
"""

from __future__ import annotations

import _bootstrap  # noqa: F401

from automod.bot.poll import main

if __name__ == "__main__":
    raise SystemExit(main())
