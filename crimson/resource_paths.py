"""Resolve bundled public resources or an explicit local-only override."""
import os
import sys
from pathlib import Path

def resource_root():
    override = os.environ.get('CM_EDITOR_RESOURCES')
    return Path(override).expanduser().resolve() if override else Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parents[1]))
