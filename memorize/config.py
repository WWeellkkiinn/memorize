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


@dataclass
class Config:
    bar_x: int | None = None
    passive_mode: bool = True
    active_mode: bool = True
    word_change_interval_sec: int = 60
    reminder_interval_min: int = 30
    auto_dismiss_sec: int = 8
    daily_new_words: int = 20


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
        return Config(
            bar_x=_parse_optional_int(data.get("bar_x", defaults.bar_x)),
            passive_mode=bool(data.get("passive_mode", defaults.passive_mode)),
            active_mode=bool(data.get("active_mode", defaults.active_mode)),
            word_change_interval_sec=max(5, int(
                data.get("word_change_interval_sec", defaults.word_change_interval_sec)
            )),
            reminder_interval_min=max(1, int(
                data.get("reminder_interval_min", defaults.reminder_interval_min)
            )),
            auto_dismiss_sec=max(1, int(
                data.get("auto_dismiss_sec", defaults.auto_dismiss_sec)
            )),
            daily_new_words=max(1, int(
                data.get("daily_new_words", defaults.daily_new_words)
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


def _parse_optional_int(value) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
