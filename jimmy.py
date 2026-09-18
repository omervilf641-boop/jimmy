#!/usr/bin/env python3
"""Run Jimmy straight from a checkout: `python jimmy.py`.

Installed copies get the `jimmy` command instead; both land in the same place.
"""

import sys

from jimmy_agent.agent import main

if __name__ == "__main__":
    sys.exit(main())
