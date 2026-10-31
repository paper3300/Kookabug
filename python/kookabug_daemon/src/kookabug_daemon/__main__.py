"""`python -m kookabug_daemon` (CLI `kookabug daemon`과 같다)."""

import sys

from kookabug_daemon.app import main

if __name__ == "__main__":
    sys.exit(main())
