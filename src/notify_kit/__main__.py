"""Allow python -m notify_kit without import-time side effects."""

from notify_kit.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
