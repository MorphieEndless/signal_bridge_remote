"""
Signal Bridge Remote — Pattern Library verification

Offline checks for the server-side waveform CRUD (pattern_store + the
create_pattern/list_patterns/get_pattern/delete_pattern/play_pattern MCP tools).

Run:  PYTHONPATH=. python3 tests/verify_patterns.py
"""
from __future__ import annotations
import asyncio
import os
import sys
import tempfile
from pathlib import Path

# ── Isolate storage to a temp dir BEFORE importing the package ──────────
_tmp = tempfile.mkdtemp(prefix="sb_patterns_test_")
os.environ["SB_PATTERNS_DIR"] = str(Path(_tmp) / "patterns")
os.environ["SB_SECRET_KEY"] = "verify-patterns-key-0123456789abcdef"

from server import mcp_tools
from server.models import CommandAck
from server.pattern_store import pattern_store, StoredPattern, PatternStep


PASS = 0
FAIL = 0


def check(name: str, cond: bool, detail: str = ""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


# ── Mock the transport so play_pattern doesn't need a real phone ─────────
_SENT: list[dict] = []


async def _fake_send_to_user(user_id: str, command: dict, wait_ack: bool = True):
    _SENT.append(command)
    return CommandAck(success=True, message="OK (mocked)")


mcp_tools.registry.send_to_user = _fake_send_to_user  # type: ignore[assignment]


def _run(coro):
    return asyncio.run(coro)


def set_user(uid: str = "user-test"):
    mcp_tools.current_user_id.set(uid)


# ════════════════════════════════════════════════════════════════════════

print("== 1. pattern_store 基础 CRUD ==")


def test_crud():
    uid = "user-crud"
    # 初始为空
    check("list 为空", pattern_store.list(uid) == [])

    # 创建
    p = pattern_store.create(
        uid,
        name="build_up",
        steps=[
            {"duration_ms": 1000, "vibrate": 0.3},
            {"duration_ms": 2000, "vibrate": 0.8, "constrict": 0.6, "constrict_mode": 6},
            {"duration_ms": 1000, "constrict": 1.0, "constrict_mode": 5},
        ],
        repeat=2,
        description="渐强",
    )
    check("create 返回 StoredPattern", isinstance(p, StoredPattern))
    check("create 生成 id", len(p.id) == 12)
    check("create 名称正确", p.name == "build_up")
    check("total_ms = (1+2+1)s × 2 = 8s", p.total_ms() == 8000)
    check("peak = 1.0（constrict 1.0 最大）", abs(p.peak_intensity() - 1.0) < 1e-9)

    # 重复名称报错
    try:
        pattern_store.create(uid, name="build_up", steps=[{"duration_ms": 500, "vibrate": 0.5}])
        check("重复名报错", False, "——没抛异常")
    except ValueError:
        check("重复名报错", True)

    # get 按名/按 id
    check("get 按名", pattern_store.get(uid, "BUILD_UP") is not None)
    check("get 按 id", pattern_store.get(uid, p.id) is not None)
    check("get 不存在返回 None", pattern_store.get(uid, "nope") is None)

    # 持久化：重新 new 一个 store 指向同一目录
    store2 = __import__("server.pattern_store", fromlist=["PatternStore"]).PatternStore(_tmp + "/patterns")
    check("持久化后仍可读到", len(store2.list(uid)) == 1)

    # delete
    check("delete 存在", pattern_store.delete(uid, "build_up") is True)
    check("delete 后为空", pattern_store.list(uid) == [])
    check("delete 不存在返回 False", pattern_store.delete(uid, "build_up") is False)


test_crud()

print("\n== 2. 边界校验 ==")


def test_validation():
    uid = "user-val"
    base = [{"duration_ms": 500, "vibrate": 0.5}]

    # duration_ms < 100
    try:
        pattern_store.create(uid, "bad_ms", [{"duration_ms": 50, "vibrate": 0.5}])
        check("duration_ms>=100 校验", False, "——50 通过了")
    except Exception:
        check("duration_ms>=100 校验", True)

    # 超 128 步
    many = [{"duration_ms": 100, "vibrate": 0.1}] * 129
    try:
        pattern_store.create(uid, "bad_steps", many)
        check("steps<=128 校验", False, "——129 通过了")
    except Exception:
        check("steps<=128 校验", True)

    # 总时长超 10 分钟
    long_step = [{"duration_ms": 601_000, "vibrate": 0.5}]
    try:
        pattern_store.create(uid, "bad_len", long_step, repeat=1)
        check("总时长<=10min 校验", False, "——601s 通过了")
    except Exception:
        check("总时长<=10min 校验", True)

    # intensity_scale 超范围被 clamp
    p = pattern_store.create(uid, "clamp_scale", base, intensity_scale=5.0)
    check("intensity_scale clamp 到 1.0", p.intensity_scale == 1.0)

    # 名称空/超长
    try:
        pattern_store.create(uid, "  ", base)
        check("空名拒绝", False)
    except ValueError:
        check("空名拒绝", True)
    try:
        pattern_store.create(uid, "x" * 65, base)
        check("超长名拒绝", False)
    except ValueError:
        check("超长名拒绝", True)

    # constrict_mode 范围
    try:
        pattern_store.create(uid, "bad_mode", [{"duration_ms": 500, "constrict": 0.5, "constrict_mode": 9}])
        check("constrict_mode 1-8 校验", False)
    except Exception:
        check("constrict_mode 1-8 校验", True)


test_validation()

print("\n== 3. MCP 工具 handler ==")


def test_mcp_tools():
    set_user("user-mcp")
    mcp_tools._SENT = []

    # create_pattern
    result = _run(mcp_tools.create_pattern(
        name="wave_rise",
        steps=[
            {"duration_ms": 1000, "vibrate": 0.2},
            {"duration_ms": 1000, "vibrate": 0.5, "constrict": 0.4, "constrict_mode": 6},
            {"duration_ms": 1000, "vibrate": 0.9},
        ],
        repeat=1,
        description="起浪",
    ))
    check("create_pattern 返回成功提示", "saved" in result, result)

    # list_patterns
    listing = _run(mcp_tools.list_patterns())
    check("list_patterns 包含新 pattern", "wave_rise" in listing, listing)

    # get_pattern
    detail = _run(mcp_tools.get_pattern(name_or_id="wave_rise"))
    check("get_pattern 返回 JSON", '"steps"' in detail and "wave_rise" in detail)

    # play_pattern → 应展开成 custom_pattern 并发送
    _SENT.clear()
    result = _run(mcp_tools.play_pattern(name_or_id="wave_rise"))
    check("play_pattern 发送成功", "OK" in result or "Custom" in result, result)
    check("play_pattern 发出 custom_pattern", len(_SENT) == 1 and _SENT[0]["type"] == "custom_pattern")
    if _SENT:
        cmd = _SENT[0]
        check("命令带 steps", isinstance(cmd.get("steps"), list) and len(cmd["steps"]) == 3)
        check("命令带 repeat", cmd.get("repeat") == 1)
        check("命令带 name", cmd.get("name") == "wave_rise")
        # intensity_scale 默认 1.0 → vibrate 原样
        check("默认 scale 原样透传", abs(cmd["steps"][1]["vibrate"] - 0.5) < 1e-6)

    # play_pattern 覆盖 scale
    _SENT.clear()
    _run(mcp_tools.play_pattern(name_or_id="wave_rise", intensity_scale=0.5))
    cmd = _SENT[0]
    check("scale=0.5 缩半", abs(cmd["steps"][1]["vibrate"] - 0.25) < 1e-4, str(cmd["steps"][1]))

    # play_pattern 不存在
    result = _run(mcp_tools.play_pattern(name_or_id="ghost"))
    check("play_pattern 不存在报错", "no pattern" in result, result)

    # delete_pattern
    result = _run(mcp_tools.delete_pattern(name_or_id="wave_rise"))
    check("delete_pattern 成功", "deleted" in result, result)
    result = _run(mcp_tools.delete_pattern(name_or_id="wave_rise"))
    check("delete_pattern 不存在报错", "no pattern" in result, result)


test_mcp_tools()

print("\n== 4. governor 集成（保留、禁用态放行）==")


def test_governor_integration():
    set_user("user-gov")
    # 先建一个 pattern 供本组测试用
    _run(mcp_tools.create_pattern(
        name="gov_check",
        steps=[{"duration_ms": 500, "vibrate": 0.6}],
        repeat=1,
    ))
    # governor 禁用态（线上现状）：check 直接放行
    allowed, reason = mcp_tools.governor.check("user-gov")
    check("governor 禁用态放行", allowed is True, reason)

    # 手动启用后，play_pattern 应被 governor 拦截（热量过高时）
    gov = mcp_tools.governor
    state = gov._get("user-gov")
    state.cfg.enabled = True
    state.heat = 95.0
    state.in_cooldown = True
    try:
        result = _run(mcp_tools.play_pattern(name_or_id="gov_check"))
        check("cooldown 时 play_pattern 被拦", "Blocked by governor" in result, result)
    finally:
        # 恢复：不影响其他测试
        state.cfg.enabled = False
        state.in_cooldown = False
        state.heat = 0.0


test_governor_integration()

print(f"\n═══ 结果: {PASS} 通过, {FAIL} 失败 ═══")
sys.exit(1 if FAIL else 0)
