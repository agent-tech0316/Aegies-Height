"""d1/attitude_from_gamepad — 手柄「站立后右摇杆俯仰/转身 + 探头/身形」两种实现.

把 OEM 手柄的原地动作（站立后推右摇杆做俯仰/转身，X/B/Y/A 做探头/身形）
用代码复现，两条路任选：

  --backend sdk  : ff_sdk 高层 API（aegis 后端，连续速度，推荐）
  --backend udp  : 裸 dog_task UDP（不依赖 ff_sdk，自己 socket + 心跳）

手柄 → 参数对照：
  右摇杆 前/后 = 俯仰   → SDK pitch_vel  / UDP joystick ry
  右摇杆 左/右 = 转身   → SDK yaw_vel    / UDP joystick rx
  X / B 键 = 左/右探头  → SDK roll_vel±  / UDP button[6] / button[5]
  Y / A 键 = 高/低身形  → SDK height_vel±/ UDP button[7] / button[4]

四个量都是「速度」（±0.5），松手 = 调一次全 0。手柄是「按住」=持续推杆，
所以两条路都要 ~20Hz 持续发、松手补几帧 0，否则狗按最后一帧速度一直动。

Usage:
    FF_SDK_DRY_RUN=1 python d1/attitude_from_gamepad.py --backend sdk
    python d1/attitude_from_gamepad.py --backend sdk --target D1-XG03
    python d1/attitude_from_gamepad.py --backend udp --ip 192.168.234.1
    python d1/attitude_from_gamepad.py --backend udp --print-only   # 只打印不发包
"""
from __future__ import annotations

import argparse
import asyncio
import json
import socket
import threading
import time


# ── 路线一：ff_sdk 高层 API ───────────────────────────────────────────────
async def run_sdk(target: str) -> None:
    import ff_sdk
    from ff_sdk import Config

    sess = await ff_sdk.connect(target, config=Config.from_env())
    try:
        await sess.motion.stand()
        await asyncio.sleep(2)

        # 手柄是「按住」= 持续推杆 → 20Hz 循环维持速度
        async def hold(secs: float = 1.0, hz: int = 20, **vel: float) -> None:
            for _ in range(int(secs * hz)):
                await sess.motion.attitude_control(**vel)
                await asyncio.sleep(1 / hz)

        print(">> 右摇杆后推 = 低头 (pitch_vel)")
        await hold(pitch_vel=-0.3)
        print(">> 右摇杆左推 = 转身 (yaw_vel)")
        await hold(yaw_vel=0.3)
        print(">> 左探头(X)=roll_vel + 高身形(Y)=height_vel")
        await hold(roll_vel=0.4, height_vel=0.3)
        print(">> 松手 = 全 0 停")
        await sess.motion.attitude_control()
    finally:
        await sess.close()


# ── 路线二：裸 dog_task UDP（无 ff_sdk 依赖）───────────────────────────────
def run_udp(ip: str, port: int = 8081, print_only: bool = False) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    seq = {"n": 0}

    def send(d: dict) -> None:
        if print_only:
            print("  UDP>", json.dumps(d, separators=(",", ":")))
        else:
            sock.sendto(json.dumps(d).encode(), (ip, port))

    def cmd(n: int) -> None:
        send({"type": "cmd", "cmd": n})

    # 右摇杆 = rx(转身/AXIS_Z) / ry(俯仰/AXIS_RZ)；button 全 0 = 摇杆帧
    def joystick(lx: float = 0, ly: float = 0, rx: float = 0, ry: float = 0) -> None:
        seq["n"] += 1
        send({"type": "remote", "joystick": [lx, ly, rx, ry],
              "button": [0] * 14, "time": int(time.time() * 1000), "seq": seq["n"]})

    # 探头/身形 = 物理按键 → button 帧，固件按置位 slot 解释；连发 5 次提高送达
    def button(*idx: int, burst: int = 5) -> None:
        b = [0] * 14
        for i in idx:
            b[i] = 1
        for _ in range(burst):
            seq["n"] += 1
            send({"type": "remote", "joystick": [0, 0, 0, 0], "button": b,
                  "time": int(time.time() * 1000), "seq": seq["n"]})

    # ★心跳保活：dog_task 只回状态给「最近 2s 发过包」的 client，必须常发
    stop = threading.Event()

    def hb() -> None:
        while not stop.is_set():
            send({"type": "heartbeat"})
            time.sleep(1)

    threading.Thread(target=hb, daemon=True).start()

    try:
        print(">> 站立 cmd 122")
        cmd(122)
        time.sleep(2)
        print(">> 进原地模式 cmd 154 (STAY) ⚠️ 与跳跃高级 154 同号，真机首用必验")
        cmd(154)
        time.sleep(0.3)

        print(">> 右摇杆后推 = 低头 (ry)，~20Hz × 1s")
        for _ in range(20):
            joystick(ry=-0.3)
            time.sleep(0.05)
        print(">> 右摇杆左推 = 转身 (rx)")
        for _ in range(20):
            joystick(rx=0.3)
            time.sleep(0.05)
        print(">> 松手 = 连发几帧 0 停住")
        for _ in range(3):
            joystick()
            time.sleep(0.05)

        print(">> 左探头(X=button[6]) + 高身形(Y=button[7])")
        button(6)
        button(7)
    finally:
        stop.set()


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--backend", choices=["sdk", "udp"], default="sdk")
    p.add_argument("--target", default="D1-demo", help="ff_sdk connect target (sdk backend)")
    p.add_argument("--ip", default="192.168.234.1", help="dog_task UDP IP (udp backend)")
    p.add_argument("--print-only", action="store_true", help="udp: 只打印不发包，看协议")
    args = p.parse_args()

    if args.backend == "sdk":
        asyncio.run(run_sdk(args.target))
    else:
        run_udp(args.ip, print_only=args.print_only)


if __name__ == "__main__":
    main()
