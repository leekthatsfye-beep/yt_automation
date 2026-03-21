import os
import shutil
from pathlib import Path

# Project root (two levels up from backend/)
ROOT = Path(__file__).resolve().parent.parent.parent
BEATS_DIR = ROOT / "beats"
OUTPUT_DIR = ROOT / "output"
METADATA_DIR = ROOT / "metadata"
IMAGES_DIR = ROOT / "images"
SHARED_CLIPS_DIR = Path.home() / "Shared_Clips"
BRAND_DIR = ROOT / "brand"
LOGS_DIR = ROOT / "logs"
FY3PACK_DIR = ROOT / "fy3pack"

UPLOADS_LOG = ROOT / "uploads_log.json"
SOCIAL_LOG = ROOT / "social_uploads_log.json"
CONFIG_YAML = ROOT / "config.yaml"

# Docker-aware Python path
if os.environ.get("FY3_DOCKER"):
    PYTHON = shutil.which("python3") or "python3"
    PYTHON_ML = PYTHON  # no separate ML venv in Docker
else:
    _venv = ROOT / ".venv" / "bin" / "python3.14"
    PYTHON = str(_venv) if _venv.exists() else "python3"
    PYTHON_ML = str(ROOT / ".venv_ml" / "bin" / "python")

SUNO_API_BASE = "https://apibox.erweima.ai"
STUDIO_DIR = ROOT / "studio"
STUDIO_PROJECTS = ROOT / "studio" / "projects.json"
APP_SETTINGS = ROOT / "app_settings.json"
LISTINGS_DIR = ROOT / "listings"
STORE_UPLOADS_LOG = ROOT / "store_uploads_log.json"
HEALTH_SCAN_LOG = ROOT / "health_scan_log.json"
PRODUCERS_DIR = ROOT / "producers"
ARRANGEMENTS_DIR = ROOT / "arrangements"
ARRANGEMENT_TEMPLATES_DIR = ROOT / "arrangements" / "templates"
