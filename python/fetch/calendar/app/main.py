"""Entry point for running the calendar fetch pipeline."""

from __future__ import annotations

from pipeline import main as run_pipeline


def main() -> None:
    run_pipeline()


if __name__ == "__main__":
    main()
