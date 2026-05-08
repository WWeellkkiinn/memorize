from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path


def _appdata_dir() -> Path:
    base = os.environ.get("APPDATA") or Path.home()
    return Path(base) / "memorize"


CONFIG_PATH = _appdata_dir() / "config.json"
DB_PATH = _appdata_dir() / "words.db"
LOG_PATH = _appdata_dir() / "memorize.log"
FSRS_PARAMS_PATH = _appdata_dir() / "fsrs_params.json"


@dataclass
class Config:
    bar_x: int | None = None
    passive_mode: bool = True
    word_change_interval_sec: int = 10


def load_config() -> Config:
    if not CONFIG_PATH.exists():
        return Config()
    try:
        data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        logging.warning("config.json corrupted, using defaults")
        return Config()

    defaults = Config()
    try:
        raw_x = data.get("bar_x", defaults.bar_x)
        bar_x = None if raw_x is None else int(raw_x)
        return Config(
            bar_x=bar_x,
            passive_mode=bool(data.get("passive_mode", defaults.passive_mode)),
            word_change_interval_sec=max(5, int(
                data.get("word_change_interval_sec", defaults.word_change_interval_sec)
            )),
        )
    except (TypeError, ValueError):
        logging.warning("config.json has invalid values, using defaults")
        return Config()


def save_config(config: Config) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(asdict(config), ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(CONFIG_PATH)
