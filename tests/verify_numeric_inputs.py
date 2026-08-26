#!/usr/bin/env python3
"""Regression checks for numeric parsing, suction mode and hardware quantization."""
import asyncio
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from server.mcp_tools import (  # noqa: E402
    TOOLS, _coerce_number, _constrict_mode, _quantize_for_device,
    _snap_to_steps, current_user_id,
)
from server.models import DeviceCommand, OutputType, PatternCommand  # noqa: E402


def main() -> None:
    assert _coerce_number(0.85, "intensity") == 0.85
    assert _coerce_number("0.85", "intensity") == 0.85

    # Yingti vibration has ten real levels.
    assert _snap_to_steps(0.85, 10) == 0.9
    assert _snap_to_steps(0.84, 10) == 0.8
    assert _snap_to_steps(0.05, 10) == 0.1
    assert _snap_to_steps(0.0, 10) == 0.0
    assert _snap_to_steps(1.0, 10) == 1.0

    # SX589B suction byte5 has five real levels; 06 is a dead level.
    assert _snap_to_steps(0.85, 5) == 0.8
    assert _snap_to_steps(0.9, 5) == 1.0
    assert _snap_to_steps(1.0, 5) == 1.0

    # Explicit Yingti commands quantize before device_list arrives.
    current_user_id.set("quantization-test-user")
    assert asyncio.run(_quantize_for_device("yingti", "vibrate", 0.85)) == 0.9
    assert asyncio.run(_quantize_for_device("yingti", "constrict", 0.85)) == 0.8

    assert _constrict_mode(1) == 1
    assert _constrict_mode("8") == 8
    for invalid in (0, 9, 1.5, "pulse"):
        try:
            _constrict_mode(invalid)
            raise AssertionError(f"invalid mode accepted: {invalid!r}")
        except ValueError:
            pass

    direct = DeviceCommand(action=OutputType.CONSTRICT, mode=6)
    assert direct.model_dump()["mode"] == 6
    pattern = PatternCommand(pattern="pulse", output_type=OutputType.CONSTRICT, mode=7)
    assert pattern.model_dump()["mode"] == 7

    vibrate = next(tool for tool in TOOLS if tool["name"] == "vibrate")
    schema = vibrate["inputSchema"]["properties"]["intensity"]
    assert schema["type"] == "number"
    assert "0.1 steps" in schema["description"]

    constrict = next(tool for tool in TOOLS if tool["name"] == "constrict")
    properties = constrict["inputSchema"]["properties"]
    assert "1/5 steps" in properties["intensity"]["description"]
    assert properties["mode"]["minimum"] == 1
    assert properties["mode"]["maximum"] == 8
    assert properties["mode"]["default"] == 5

    print("numeric parsing, suction mode and hardware-step checks: OK")


if __name__ == "__main__":
    main()
