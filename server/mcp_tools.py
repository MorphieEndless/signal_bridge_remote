"""
Signal Bridge Remote — MCP Tool Definitions

All tools that Claude can call to control devices. Each tool:
  1. Validates input
  2. Builds a command message
  3. Routes it through the session registry to the user's phone
  4. Returns the result to Claude

Expanded to support ALL output types:
  vibrate, rotate, oscillate, constrict, temperature, led, position, spray

And sensor input types:
  battery, rssi, pressure, button, depth, position
"""
from __future__ import annotations
import asyncio
import contextvars
import json
import math
from typing import Any, Optional

from .models import (
    OutputType, InputType,
    DeviceCommand, PatternCommand, StopCommand, ScanCommand, ReadSensorCommand,
    CommandAck,
)
from .governor import governor
from .session_registry import registry

# Set by auth middleware before each MCP request
current_user_id: contextvars.ContextVar[str] = contextvars.ContextVar("current_user_id")


# ════════════════════════════════════════════════════════════════════════
# Tool registry — built at import time, consumed by the MCP endpoint
# ════════════════════════════════════════════════════════════════════════

TOOLS: list[dict] = []        # MCP tool definitions (schema)
HANDLERS: dict[str, callable] = {}  # tool_name → async handler function


def _register_tool(name: str, description: str, params: dict, required: list[str] = None):
    """Decorator factory for registering MCP tools."""
    def decorator(fn):
        schema = {
            "type": "object",
            "properties": params,
        }
        # Infer required fields: any param without a "default" key is required
        if required is not None:
            schema["required"] = required
        else:
            inferred = [k for k, v in params.items() if "default" not in v]
            if inferred:
                schema["required"] = inferred
        TOOLS.append({
            "name": name,
            "description": description,
            "inputSchema": schema,
        })
        HANDLERS[name] = fn
        return fn
    return decorator


# ════════════════════════════════════════════════════════════════════════
# Helper
# ════════════════════════════════════════════════════════════════════════


def _coerce_number(value: Any, field: str) -> float:
    """Accept JSON numbers and common LLM numeric-string variants safely."""
    if isinstance(value, bool):
        raise ValueError(f"{field} must be numeric, not boolean")

    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field} must not be empty")
        is_percent = text.endswith("%")
        if is_percent:
            text = text[:-1].strip()
        try:
            number = float(text)
        except ValueError as exc:
            raise ValueError(f"{field} is not numeric: {value!r}") from exc
        if is_percent:
            number /= 100.0
    else:
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be a number or numeric string") from exc

    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _numeric_schema(description: str, default: float) -> dict:
    return {
        "type": "number",
        "description": description,
        "default": default,
    }


def _constrict_mode(value: Any) -> int:
    """Validate SX589B suction mode (protocol byte4)."""
    number = _coerce_number(value, "mode")
    if not number.is_integer() or not 1 <= number <= 8:
        raise ValueError("mode must be an integer from 1 to 8")
    return int(number)


_CONSTRICT_MODE_PARAM = {
    "type": "integer",
    "minimum": 1,
    "maximum": 8,
    "default": 5,
    "description": (
        "Suction protocol mode (byte4): 1=pulse, 2/3=flutter, "
        "4=alternate pulse, 5=continuous, 6/7=rhythm, 8≈pulse."
    ),
}


# Built-in fallback for clients that have not yet reported machine-readable
# output step counts. Device reports override this table when available.
_BUILTIN_OUTPUT_STEPS: dict[str, dict[str, int]] = {
    "yingti": {"vibrate": 10, "constrict": 5},
}


def _snap_to_steps(intensity: float, steps: int) -> float:
    """Snap a normalized intensity to a real hardware level (half rounds up)."""
    value = max(0.0, min(1.0, intensity))
    if value <= 0.0 or steps <= 0:
        return 0.0 if value <= 0.0 else value
    level = math.floor(value * steps + 0.5)
    level = max(1, min(steps, level))
    return level / steps


async def _quantize_for_device(device: str, output_type: str, intensity: float) -> float:
    """Use the connected device's discrete output levels when it has any."""
    user_id = current_user_id.get()
    devices = await registry.get_devices(user_id)

    if device == "all":
        targets = devices
    else:
        targets = [d for d in devices if d.get("short_name") == device]

    # A single command can only carry one intensity. Quantize when every target
    # that advertises steps agrees; otherwise leave continuous values untouched.
    counts: set[int] = set()
    for target in targets:
        short_name = str(target.get("short_name", ""))
        reported = target.get("output_steps", {})
        steps = reported.get(output_type) if isinstance(reported, dict) else None
        if not isinstance(steps, int) or steps <= 0:
            steps = _BUILTIN_OUTPUT_STEPS.get(short_name, {}).get(output_type)
        if isinstance(steps, int) and steps > 0:
            counts.add(steps)

    # Explicit Yingti commands still quantize during the brief reconnect window
    # before device_list has arrived.
    if not counts and device != "all":
        fallback = _BUILTIN_OUTPUT_STEPS.get(device, {}).get(output_type)
        if fallback:
            counts.add(fallback)

    return _snap_to_steps(intensity, counts.pop()) if len(counts) == 1 else intensity


async def _send(
    command: dict, intensity: float = 0.0, duration: float = 0.0
) -> str:
    """
    Route a command to the current user's phone and return result text.

    If intensity > 0, the governor checks if the command is allowed
    and records the intensity for heat tracking.

    `duration` is how long the command runs before the phone stops it by
    itself. Pass it so the heat model can expire the intensity; 0 means the
    command runs until an explicit stop.
    """
    user_id = current_user_id.get()

    # Governor check (skip for stop commands and scans)
    cmd_type = command.get("type", "")
    if cmd_type not in ("stop", "scan") and intensity > 0:
        allowed, reason = governor.check(user_id)
        if not allowed:
            return f"Blocked by governor: {reason}"

    ack = await registry.send_to_user(user_id, command)

    # Record intensity for heat tracking
    if ack.success and intensity > 0:
        governor.record_command(user_id, intensity, duration)
    elif ack.success and cmd_type == "stop":
        governor.record_stop(user_id)

    if ack.success:
        return ack.message or "OK"
    else:
        return f"Error: {ack.message}"


# ════════════════════════════════════════════════════════════════════════
# Device Discovery
# ════════════════════════════════════════════════════════════════════════

@_register_tool(
    "list_devices",
    "List all connected devices and their supported outputs, operating ranges, and metadata.",
    {},
)
async def list_devices(**kwargs) -> str:
    user_id = current_user_id.get()
    devices = await registry.get_devices(user_id)

    # If cache is empty but phone is connected, try requesting a fresh scan
    if not devices:
        session = await registry.get_session(user_id)
        if session:
            # Phone is connected but device list is empty — request a scan
            try:
                scan_ack = await session.send_command({"type": "scan"}, timeout=15.0)
                if scan_ack.success:
                    # Give a moment for the device_list message to arrive and be processed
                    await asyncio.sleep(0.5)
                    devices = await registry.get_devices(user_id)
            except Exception:
                pass

    if not devices:
        # Check if there's even a session
        session = await registry.get_session(user_id)
        if not session:
            return (
                "No phone connected. Start the relay client on your phone/PC "
                "and connect it to the server."
            )
        return (
            "Phone is connected but no devices found. Make sure Intiface Central "
            "is running and devices are turned on."
        )

    lines = []
    for d in devices:
        caps_dict = d.get("capabilities", {})
        # Surface capability values when present so the model knows what each
        # output channel actually does; fall back to bare keys for terse entries.
        caps_parts = [f"{k} ({v})" if v else k for k, v in caps_dict.items()]
        caps = ", ".join(caps_parts)
        notes = d.get("notes", "")
        floor = d.get("intensity_floor", 0)
        output_steps = d.get("output_steps", {})
        steps_text = ", ".join(f"{key}={value}" for key, value in output_steps.items()) \
            if isinstance(output_steps, dict) else ""
        options = d.get("output_options", {})
        mode_text = ""
        if isinstance(options, dict) and isinstance(options.get("constrict_mode"), dict):
            mode = options["constrict_mode"]
            mode_text = f"constrict mode={mode.get('min', 1)}-{mode.get('max', 8)} (default {mode.get('default', 5)})"
        lines.append(
            f"• {d.get('short_name', '?')} — capabilities: [{caps}]"
            + (f" | steps: {steps_text}" if steps_text else "")
            + (f" | {mode_text}" if mode_text else "")
            + (f" | floor: {floor}" if floor > 0 else "")
            + (f" | {notes}" if notes else "")
        )

    # Append governor state so AI knows the session budget.
    # Say nothing at all when the governor is off — a disabled subsystem must
    # not report a limit it will never enforce.
    gov = governor.get_state(user_id)
    heat = gov["heat_pct"]
    if not gov.get("enabled", True):
        pass
    elif gov["in_cooldown"]:
        lines.append(f"\n⚠ Governor: COOLDOWN ({gov['cooldown_remaining']}s remaining)")
    elif heat > 0:
        lines.append(f"\nGovernor: {heat:.0f}% heat"
                     + (f" (~{gov['predicted_seconds']}s to cooldown)"
                        if gov["predicted_seconds"] is not None else ""))

    return "\n".join(lines)


@_register_tool(
    "scan_devices",
    "Rescan for new or reconnected Bluetooth devices.",
    {},
)
async def scan_devices(**kwargs) -> str:
    return await _send(ScanCommand().model_dump())


# ════════════════════════════════════════════════════════════════════════
# Output Commands — one tool per output type
# ════════════════════════════════════════════════════════════════════════

_OUTPUT_PARAMS = {
    "device": {
        "type": "string",
        "description": "Device short name or 'all'",
        "default": "all",
    },
    "intensity": _numeric_schema(
        "Requested intensity from 0.0 to 1.0. Discrete devices snap it to the nearest real hardware level (yingti vibration: 0.1 steps; suction: 1/5 steps)",
        0.5,
    ),
    "duration": _numeric_schema(
        "Duration in seconds. 0 = stay on until stop command", 0
    ),
    "feature_index": {
        "type": "integer",
        "description": (
            "Target a specific actuator by index when a device has multiple "
            "actuators of the same type (e.g. Dolce motor 0 = primary, "
            "motor 1 = secondary). Omit to drive all matching actuators together."
        ),
    },
}


def _make_output_handler(output_type: OutputType):
    """Factory for output command handlers."""
    async def handler(
        device: str = "all", intensity: float = 0.5, duration: float = 0,
        feature_index: Optional[int] = None, mode: Any = 5, **kw
    ) -> str:
        requested = max(0.0, min(1.0, _coerce_number(intensity, "intensity")))
        clamped = await _quantize_for_device(device, output_type.value, requested)
        dur = max(0.0, _coerce_number(duration, "duration"))
        suction_mode = _constrict_mode(mode) if output_type == OutputType.CONSTRICT else None
        cmd = DeviceCommand(
            action=output_type,
            device=device,
            intensity=clamped,
            duration=dur,
            feature_index=feature_index,
            mode=suction_mode,
        )
        return await _send(cmd.model_dump(), intensity=clamped, duration=dur)
    return handler


# Standard outputs (available on most devices)
_register_tool(
    "vibrate",
    "Send vibration to a device. Most common output type. "
    "For dual-motor devices (Dolce, Edge), use feature_index to target a "
    "specific motor (e.g. Dolce: 0 = internal, 1 = external).",
    _OUTPUT_PARAMS,
    required=["device"],
)(_make_output_handler(OutputType.VIBRATE))

_register_tool(
    "rotate",
    "Control rotational or oscillatory high-frequency actuator output. "
    "Interpretation depends on device firmware.",
    _OUTPUT_PARAMS,
    required=["device"],
)(_make_output_handler(OutputType.ROTATE))

_register_tool(
    "oscillate",
    "Control linear reciprocating actuator output. Intensity controls stroke amplitude/speed "
    "depending on hardware.",
    _OUTPUT_PARAMS,
    required=["device"],
)(_make_output_handler(OutputType.OSCILLATE))

# Extended outputs (device-specific, may not be available on all hardware)
_register_tool(
    "constrict",
    "Control suction/constriction output. On Yingti SX589B, mode selects the protocol rhythm and intensity selects one of five real strength levels.",
    _OUTPUT_PARAMS | {"mode": _CONSTRICT_MODE_PARAM},
    required=["device"],
)(_make_output_handler(OutputType.CONSTRICT))

_register_tool(
    "temperature",
    "Set temperature output. Device-specific — available on devices with "
    "heating or cooling elements. Intensity maps to temperature range.",
    _OUTPUT_PARAMS,
    required=["device"],
)(_make_output_handler(OutputType.TEMPERATURE))

_register_tool(
    "led",
    "Control LED light output. Device-specific — intensity controls brightness.",
    _OUTPUT_PARAMS,
    required=["device"],
)(_make_output_handler(OutputType.LED))

_register_tool(
    "position",
    "Set linear position. Device-specific — intensity maps to position "
    "along the device's range of motion (0.0 = retracted, 1.0 = extended).",
    _OUTPUT_PARAMS,
    required=["device"],
)(_make_output_handler(OutputType.POSITION))

_register_tool(
    "spray",
    "Trigger spray/liquid output. Device-specific.",
    _OUTPUT_PARAMS,
    required=["device"],
)(_make_output_handler(OutputType.SPRAY))


# ════════════════════════════════════════════════════════════════════════
# Stop
# ════════════════════════════════════════════════════════════════════════

@_register_tool(
    "stop",
    "Immediately stop all output on a device (or all devices). "
    "Also cancels any running patterns.",
    {
        "device": {
            "type": "string",
            "description": "Device short name or 'all'",
            "default": "all",
        },
    },
)
async def stop(device: str = "all", **kwargs) -> str:
    return await _send(StopCommand(device=device).model_dump())


# ════════════════════════════════════════════════════════════════════════
# Patterns — work with ANY output type
# ════════════════════════════════════════════════════════════════════════

_PATTERN_PARAMS = {
    "device": {
        "type": "string",
        "description": "Device short name or 'all'",
        "default": "all",
    },
    "output_type": {
        "type": "string",
        "description": "Which output to modulate: vibrate, rotate, oscillate, "
                       "constrict, temperature, led, position, spray",
        "default": "vibrate",
    },
    "intensity": _numeric_schema(
        "Requested peak intensity (0.0–1.0); snapped to the nearest real hardware level on discrete devices",
        0.5,
    ),
    "duration": _numeric_schema("Duration in seconds", 60),
    "feature_index": {
        "type": "integer",
        "description": (
            "Target a specific actuator by index when a device has multiple "
            "actuators of the same type. Omit to drive all matching actuators."
        ),
    },
    "mode": {
        **_CONSTRICT_MODE_PARAM,
        "description": _CONSTRICT_MODE_PARAM["description"] + " Used only when output_type=constrict.",
    },
}


def _make_pattern_handler(pattern_name: str):
    async def handler(
        device: str = "all",
        output_type: str = "vibrate",
        intensity: float = 0.6,
        duration: float = 10,
        hold_seconds: float = 0,
        feature_index: Optional[int] = None,
        mode: Any = 5,
        **kw,
    ) -> str:
        requested = max(0.0, min(1.0, _coerce_number(intensity, "intensity")))
        clamped = await _quantize_for_device(device, output_type, requested)
        dur = max(0.0, _coerce_number(duration, "duration"))
        hold = max(0.0, _coerce_number(hold_seconds, "hold_seconds"))
        output = OutputType(output_type)
        suction_mode = _constrict_mode(mode) if output == OutputType.CONSTRICT else None
        cmd = PatternCommand(
            pattern=pattern_name,
            output_type=output,
            device=device,
            intensity=clamped,
            duration=dur,
            hold_seconds=hold,
            feature_index=feature_index,
            mode=suction_mode,
        )
        # How long before the phone stops this by itself. escalate ramps over
        # `duration` and then holds — indefinitely unless hold_seconds is set,
        # which is the one case where it auto-stops. Every other pattern runs
        # for `duration` and ends. 0 means "until an explicit stop".
        if pattern_name == "escalate":
            effective = (dur + hold) if hold > 0 else 0.0
        else:
            effective = dur
        return await _send(
            cmd.model_dump(), intensity=clamped, duration=effective
        )
    return handler


_register_tool(
    "pulse",
    "Rhythmic on/off pattern. 0.5s on at intensity, 0.3s off, repeating. "
    "Works with any output type (default: vibrate).",
    _PATTERN_PARAMS,
    required=["device"],
)(_make_pattern_handler("pulse"))

_register_tool(
    "wave",
    "Smooth continuous sine-wave amplitude modulation. "
    "Works with any output type (default: vibrate).",
    _PATTERN_PARAMS,
    required=["device"],
)(_make_pattern_handler("wave"))

_register_tool(
    "escalate",
    "Apply linear interpolation from current output level to target level over duration; optionally maintain target after transition. "
    "Use hold_seconds to auto-stop after holding (0 = hold indefinitely until stop command). "
    "Works with any output type (default: vibrate).",
    {k: v for k, v in _PATTERN_PARAMS.items() if k != "intensity"}
    | {
        "intensity": _numeric_schema("Peak intensity to ramp up to", 1.0),
        "hold_seconds": _numeric_schema(
            "Seconds to hold at peak after ramp completes. 0 = hold indefinitely until explicit stop",
            0,
        ),
    },
    required=["device"],
)(_make_pattern_handler("escalate"))


# ════════════════════════════════════════════════════════════════════════
# Sensor Inputs — read data FROM the device
# ════════════════════════════════════════════════════════════════════════

@_register_tool(
    "read_battery",
    "Read battery level from a device. Returns percentage (0-100).",
    {
        "device": {
            "type": "string",
            "description": "Device short name",
        },


    },
    required=["device"],
)
async def read_battery(device: str = "all", **kwargs) -> str:
    return await _send(ReadSensorCommand(sensor=InputType.BATTERY, device=device).model_dump())


@_register_tool(
    "read_rssi",
    "Read signal strength of a connected device. Returns dBm value (0 to -100).",
    {
        "device": {
            "type": "string",
            "description": "Device short name",
        },
    },
    required=["device"],
)
async def read_rssi(device: str = "all", **kwargs) -> str:
    return await _send(ReadSensorCommand(sensor=InputType.RSSI, device=device).model_dump())
