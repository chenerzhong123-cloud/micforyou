"""App entry point. Paths are derived from this file after every relocation."""
from pathlib import Path
import os
import sys

root = Path(__file__).resolve().parent
os.environ["MICFORYOU_BUNDLE_ROOT"] = str(root)
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
sys.dont_write_bytecode = True
sys.path.insert(0, str(root / "src"))
from micforyou.cli import main

main()
