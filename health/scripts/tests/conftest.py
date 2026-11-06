"""Test del plugin health: repo dati finto (soglie generiche) e script importabili."""
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
os.environ["WELLNESS_DATA"] = str(HERE / "fixtures" / "data")
sys.path.insert(0, str(HERE.parent))
