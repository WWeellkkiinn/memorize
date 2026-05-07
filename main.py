"""Entry point for the Memorize desktop vocabulary app."""
import sys

from memorize.runtime_env import prepare_runtime_env

prepare_runtime_env()

from memorize.qt_app import MemorizeApp  # noqa: E402 — must import after DPI setup

if __name__ == "__main__":
    app = MemorizeApp()
    sys.exit(app.run())
