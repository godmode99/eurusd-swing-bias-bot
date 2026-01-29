from __future__ import annotations

from run_fred import run_with_config


def main() -> None:
    run_with_config("daily_config.yaml", "Daily")


if __name__ == "__main__":
    main()
