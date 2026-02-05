from __future__ import annotations

from pathlib import Path
import sys

try:
    from run_fetch import run_with_config
except ModuleNotFoundError:  # pragma: no cover - import fallback for script execution
    module_dir = Path(__file__).resolve().parent
    search_dir = module_dir if (module_dir / "run_fetch.py").exists() else module_dir.parent
    sys.path.insert(0, str(search_dir))
    from run_fetch import run_with_config


def main() -> None:
    run_with_config("monthly_config.yaml")


if __name__ == "__main__":
    main()
