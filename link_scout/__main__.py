"""Allow ``python3 -m link_scout`` as a console entry point."""

from link_scout.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
