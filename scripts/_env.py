"""Load KEY=VALUE pairs from a local, gitignored .env without overriding the process environment.
Values are never printed."""
import os
from pathlib import Path


def load_env(path=Path(__file__).resolve().parents[1] / '.env'):
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return os.environ
