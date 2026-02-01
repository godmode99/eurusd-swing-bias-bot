from __future__ import annotations

from run_fred import run_with_config


def main() -> None:
    run_with_config("weekly_config.yaml", "Weekly")


if __name__ == "__main__":
    main()
