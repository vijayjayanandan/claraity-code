"""
Validation Framework Entry Point

Usage:
    python -m src.validation.run --all
    python -m src.validation.run --scenario easy_cli_weather
    python -m src.validation.run --difficulty easy
"""

from .runner import main

if __name__ == "__main__":
    main()
