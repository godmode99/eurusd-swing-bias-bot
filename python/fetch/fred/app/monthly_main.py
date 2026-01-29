from __future__ import annotations

from run_fred import run_with_config


def main() -> None:
    run_with_config("monthly_config.yaml", "Monthly")


if __name__ == "__main__":
    main()
