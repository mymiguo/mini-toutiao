"""Load and expose YAML configuration."""
from pathlib import Path
import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    settings = yaml.safe_load(f)

DATA_DIR = Path(settings["data"]["raw_dir"])
CLEANED_DIR = Path(settings["data"]["cleaned_dir"])
CACHE_DIR = Path(settings["data"]["cache_dir"])


def ensure_dirs():
    """Create data directories. Call once at startup."""
    for d in (DATA_DIR, CLEANED_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
