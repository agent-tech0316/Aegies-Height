# FF Robotics SDK — D1 Release Notes

**Build:** 20260619 · **Package:** `ff_sdk 0.1.0a1` · **Platform:** D1 / AEGIS

> 本版起版本号升到 **0.1.0a1**（上一版是 0.1.0a0）。装好后用 `pip show ff_sdk` 看到
> `Version: 0.1.0a1` 即为本版 —— 以后判断有没有装上新版，认版本号即可。

---

## 中文

### 本次更新

- **新增拍帧接口 `vision.frame()`**：一行抓一张相机帧返回 JPEG —— `await sess.vision.frame()`。
  内部已封装 ffmpeg 抓帧 + **强制软解**（避开 RK 平台 h264 硬解卡死）+ 超时/失败处理，你不用再自己写 ffmpeg。
  支持指定相机源（默认 `rtsp://<host>:8554/test`，也可传完整 RTSP URL）。
  见 `examples/d1/capture_frame.py`。
  说明：这是 RTSP 帧（H.264 解码后，分辨率 = 流分辨率，默认 1920×1080），与"从视频流截一帧"是同一路相机；
  机型没有更高分辨率的独立拍照通道。
- **明确确认：走路 `cmd_vel` 修复已包含在内**。上一版（0.1.0a0 的较早构建）`motion.cmd_vel(...)`
  存在"无报错但不走"的 bug，**已修复并经点足真机三轮验证**——本版（及 0614 那版）都已含此修复。
  之前的 release notes 漏列了这条，特此补上：`await sess.motion.cmd_vel(linear=0.3)` 现在可直接让狗走，
  **不再需要任何 dog_task workaround 脚本**。

### 沿用上版的能力（仍在）

- `motion.two_leg_stand()` 双腿站立（可指定速度边站边走）
- `motion.crawl(vx, vy, yaw_rate)` 匍匐爬行（轮足机型），`do_preset('cancel_crawl')` 退出
- `motion.attitude_control(roll_vel, pitch_vel, yaw_vel, height_vel)` 原地姿态（各 ±0.5，速度语义，需持续发）
- 关节级电机控制接口（危险接口，架空测试）
- 点足/轮足自动识别 + 指令安全范围保护

### 升级方法（业务代码无需改动）

```bash
# D1 机载 / 树莓派 (aarch64)
pip install --force-reinstall wheels/ff_sdk-0.1.0a1-cp310-cp310-linux_aarch64.whl
# x86 开发机 (x86_64)
pip install --force-reinstall wheels/ff_sdk-0.1.0a1-cp310-cp310-linux_x86_64.whl
# 确认版本
pip show ff_sdk     # 应显示 Version: 0.1.0a1
```

### 验证

软件回归全部通过（含新增 `vision.frame()` 的接线测试）。`vision.frame()` 的真机抓帧、
以及双腿站立 / 匍匐 / 姿态 / 关节级动作的真机回归步骤请向我们索取。

⚠️ **关节级控制是危险接口**：直接驱动电机、绕过整机保护。首次务必将机器人架空 / 吊起测试。

### 包内容

| 目录 | 内容 |
|---|---|
| `wheels/` | Python SDK（aarch64 + x86_64，CPython 3.10） |
| `examples/` | 示例脚本（连接 / 运动 / 状态 / 拍帧 / 诊断） |
| `docs/` | 快速上手 / 部署 / 模型说明 |

---

## English

### What's new
- **New frame-grab API `vision.frame()`**: grab one camera frame as JPEG in a single call —
  `await sess.vision.frame()`. ffmpeg capture + **forced software decode** (avoids the RK
  h264 hardware-decode hang) + timeout/error handling are all wrapped for you. Optional source
  arg (defaults to `rtsp://<host>:8554/test`, or pass a full RTSP URL). See
  `examples/d1/capture_frame.py`. Note: this is an RTSP (H.264-decoded) frame at the stream's
  resolution (1920×1080 by default) — same camera as "a frame off the video stream"; there is
  no separate higher-resolution still-capture path on this hardware.
- **Explicit confirmation: the `cmd_vel` walking fix is included.** An earlier 0.1.0a0 build had a
  "no error but doesn't walk" bug in `motion.cmd_vel(...)`; it is **fixed and verified on real
  footed hardware (3 runs)** — this build (and the 0614 one) contain the fix. The previous release
  notes omitted this line; adding it here. `await sess.motion.cmd_vel(linear=0.3)` now drives the
  dog directly — **no dog_task workaround needed**.

### Carried over (still here)
- `two_leg_stand()`, `crawl()`, `attitude_control()` (±0.5 velocities, must be sent repeatedly),
  joint-level motor control (dangerous — test suspended), footed/wheeled auto-detect, command clamps.

### Upgrade (no app code changes)
Same `pip install --force-reinstall` of the matching `0.1.0a1` wheel as above; `pip show ff_sdk`
should read `Version: 0.1.0a1`.

⚠️  Joint-level control is a DANGEROUS interface — test with the robot suspended first.
