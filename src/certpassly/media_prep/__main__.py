"""python -m certpassly.media_prep entry point."""
import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
