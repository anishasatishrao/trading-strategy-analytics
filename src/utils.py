"""Shared helpers: config loading and logging setup.

Not in the originally sketched repo structure, but every script in src/
needs the same two things (load settings.yaml, configure logging), so a
small shared module avoids duplicating that code five times.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent

load_dotenv(PROJECT_ROOT / ".env")


def load_config(path: str | Path = PROJECT_ROOT / "config" / "settings.yaml") -> dict[str, Any]:
    with open(path, "r") as f:
        return yaml.safe_load(f)


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger


def env(key: str, default: str | None = None) -> str | None:
    return os.environ.get(key, default)
