"""Load and expose YAML configuration."""
from pathlib import Path
import yaml

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
PROJECT_ROOT = CONFIG_PATH.parent

with open(CONFIG_PATH, "r", encoding="utf-8") as f:
    settings = yaml.safe_load(f)

DATA_DIR = PROJECT_ROOT / settings["data"]["raw_dir"]
CLEANED_DIR = PROJECT_ROOT / settings["data"]["cleaned_dir"]
CACHE_DIR = PROJECT_ROOT / settings["data"]["cache_dir"]


def ensure_dirs():
    """Create data directories. Call once at startup."""
    for d in (DATA_DIR, CLEANED_DIR, CACHE_DIR):
        d.mkdir(parents=True, exist_ok=True)
