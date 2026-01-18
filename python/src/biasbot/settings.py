"""Settings loader."""

from dataclasses import dataclass


@dataclass
class Settings:
    mt5_files_dir: str = ""
