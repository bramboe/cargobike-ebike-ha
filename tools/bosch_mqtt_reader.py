#!/usr/bin/env python3
"""Compatibility entry point: use the add-on reader, never a divergent copy."""
import runpy
import sys
from pathlib import Path

addon = Path(__file__).resolve().parents[1] / "ebike_battery"
sys.path.insert(0, str(addon))
runpy.run_path(str(addon / "bosch_mqtt_reader.py"), run_name="__main__")
