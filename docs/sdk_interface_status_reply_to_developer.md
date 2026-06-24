# 关于 Aegis SDK 接口清单 —— 逐项答复 + 身高测量项目针对性建议

亲爱的开发者：

收到你整理的《SDK Interface Status》清单，非常清晰 —— 你把"已知 / 部分已知 / 待我们确认"分得很明白，省了我们大量来回。下面我对照你的 17 项 checklist **逐项核实了源码后**给出确切答案（标注了真实的方法签名、单位、限位），再回答你列的 8 个具体问题，最后针对你的"机器狗给人测身高"项目给 3 条最关键的提醒。

> 口径说明：本机型对外代号 **Aegis**（你拿到的 devkit 就是 `ff_sdk_aegis_devkit`）。底层有两条后端：**Aegis 原生 SDK**（真机验证主路径，UDP 直连 mc_ctrl）和 **dog_task UDP**（fallback）。下文凡说"Aegis 路径 / dog_task 路径"即指这两条。

---

## 一、逐项 checklist 答复

| 项目 | 真实状态 | 你能直接用的 function | 限位 / 单位 / 注意 |
|---|---|---|---|
| **Velocity** | ✅ 有 | `motion.cmd_vel(linear, angular, lateral)` | dog_task 路径限速 x≤1.0 m/s、y≤0.5 m/s、yaw≤1.0 rad/s；Aegis 路径 `move(vx,vy,yaw_rate)` 是 body-FLU（vx+前 / vy+左 / yaw+逆时针），实测 vx=0.2 指令实走约 0.15 m/s。⚠️ **0.1.0a0 的 cmd_vel 有已知 bug**（见上次单独回信），修复版即将发布；身高项目用到走路时先用那封信里的 workaround。 |
| **Gait** | ✅ 有 | `motion.do_preset(name)`、`motion.known_presets()`、`motion.preset_timeout(name)` | 支持的 name：`stand` / `stand_up` / `lie_down` / `damping` / `stop` / `shake_hand` / `jump` / `front_jump` / `backflip` / `two_leg_stand` / `crawl` / `recover`。`preset_timeout(name)` 返回每个动作的物理时长（秒），dispatch 后请 `await asyncio.sleep(preset_timeout)` 再发下一条。**特技类动作受底盘门控**：点足型 (zsl-1) 才有 `two_leg_stand`，轮足型 (zsl-1w) 才有 `crawl`，调用不支持的会明确 `raise CapabilityNotSupported`（绝不假成功）。 |
| **Pose / Attitude** | ✅ 有（你项目核心） | `motion.attitude_control(roll_vel, pitch_vel, yaw_vel, height_vel)` | **四个参数全是速度，不是绝对姿态**：roll/pitch/yaw_vel 是角速度 (rad/s)，height_vel 是垂直速度 (m/s)，**每个都被 clamp 到 ±0.5**。Aegis 路径 = 真连续 4 轴速度控制；dog_task fallback 下只有 **yaw + pitch 连续**（走右摇杆），**roll / height 退化成离散按钮脉冲**（只能给方向、给不了幅度），且 dog_task 路径下必须先进 **STAY（原地）模式**摇杆才被解释成姿态而非位移。**前提：狗必须已经站立。** |
| **Camera Stream** | 🟡 SDK 未接线 | （继续用你现在的 OpenCV/ffmpeg 直读 RTSP —— 做法正确） | SDK 的 `vision.frame()` / `vision.stream_camera()` **当前抛 NotImplementedError**，还没接进 SDK。默认流地址 `rtsp://192.168.234.1:8554/test`（1920×1080）。我们内部抓单帧实测的 ffmpeg 参数供你参考：`-rtsp_transport tcp -analyzeduration 500000 -probesize 500000 -frames:v 1 -q:v 5`。**SDK 不提供帧时间戳 / 内参 / 与 IMU 的同步** —— 你自己标定的 charuco 内参就是当前最佳来源。 |
| **IMU** | ✅ 有 | `state.pose()` → roll/pitch/yaw；底层还可取 quaternion / body_acc / body_gyro / body_velocity / world_velocity | **关键：pitch 来自机身 IMU，不是相机姿态。** 相机相对机身的外参（你用 Codey 在补的那一环）必须你自己标。**无官方时间戳**，所以 IMU 与相机帧无法做硬件级同步对齐 —— 取 pitch 和取帧之间要靠你软件侧尽量同时刻读。 |
| **Odometry** | ✅ 有 | 底层 `position()`（[x,y,z]）/ body_velocity / world_velocity，经 `state.pose()` 暴露 x/y/z | **无 reset / 设原点 API，无公开 ROS2 odom topic**，漂移未做表征。身高测量建议**不要依赖 odom 做距离** —— 你的超声 + 几何方案是对的。 |
| **Battery** | ✅ 有 | `state.battery()` → `percent`（0.0–1.0） | **`voltage` 恒为 None、`is_charging` 恒为 False** —— 原生 SDK 没有 voltage / charging 的 getter，这是真实的 SDK 限制，不是我们没接。固件在电量 < 5% 会禁止走路。 |
| **Charging State** | ❌ 无 | — | SDK 里**确实没有**独立充电/在桩状态 API。你表里标 Unknown，坐实=不存在。 |
| **Event / 手柄按钮** | ❌ 无 | 只有 e_stop（`session` 级 EStopEvent 回调 + `adapter.e_stop()`） | **没有手柄按钮 / RT / LT / 模式切换 / 状态变更的事件 API。** 你那套自定义 UDP 转发 RT 触发的做法是当前唯一路径，方向完全正确。 |
| **Dock** | ❌ 无 | — | SDK 无 dock API。 |
| **ROS2** | 🟡 内部有，未公开 | — | 机器人内部确实跑 ROS2 / dog_task / eCAL，但 **ff_sdk 不暴露任何公开 ROS2 topic/service/action**。Aegis 路径走原生 .so（UDP 直连 mc_ctrl），dog_task 路径走 UDP 8081，**两条都不是 ROS2**。目前没有对外的 ROS2 接口文档。 |
| **Python SDK** | ✅ | `ff_sdk 0.1.0a0` | 需 **Python 3.10**（原生 .so 只提供 cp310 ABI）。真机控制需 Linux；Windows/Mac 仅 dry-run。 |
| **C++ SDK** | ✅ | `cpp/` 下 header+库 | connect / stand / move / attitude / presets / battery / control mode / pose / joints。 |
| **joint_states** | ✅ 有 | `state.joint_states()` → 各腿 abad/hip/knee/foot 的 角度 / 速度 / 力矩 | 走 Aegis 路径；dog_task 路径**不**暴露 per-joint。轮足型 eCAL 不通时不可用。 |
| **OTA** | ❌ 无 | — | SDK 无固件/软件升级 API。 |
| **Expansion Port** | ❌ 无 | — | 无官方扩展口 API。你的 Pi/USB/GPIO 传感器属于项目侧自加，这条路就该你自己走。 |
| **Time Sync** | ❌ 无 | — | 无时钟同步 API，相机/IMU/位姿帧无统一时间源。 |
| **Video Stream API** | 🟡 同 Camera | 走 RTSP/OpenCV | 无官方相机元数据 / 内外参 / 同步时间戳。 |

---

## 二、回答你列的 8 个问题

**Q1. 完整 SDK 接口文档** —— 上表即按你的 17 项给了"现在到底有没有/怎么调"。其中 **Charging / Dock / OTA / Expansion / Time Sync 这 5 项是真的不存在**，不是没文档；其余项的可用 function 和限位都在表里。

**Q2. 手柄按钮/RT 的官方事件 API？** —— **没有。** SDK 只暴露 e_stop。RT/LT/按钮事件没有官方回调，你的自定义 UDP 监听就是正解，请继续用。

**Q3. 手柄 `START+B` 模式切换的 SDK 等价？** —— SDK 层没有"组合键模式切换"的直接等价。模式切换是通过具体动作 API 完成的（如 `do_preset('stand')` / `do_preset('damping')`；姿态前进 STAY 由 attitude_control 路径内部处理）。如果你指的是某个特定整机模式，请把按下 START+B 后狗的具体行为描述给我，我对应到具体 API。

**Q4. `attitude_control` 的单位 / 限位 / 帧 / pitch 度每秒映射？**
- 单位：roll/pitch/yaw_vel = **rad/s**，height_vel = **m/s**。
- 限位：**每个轴都 clamp 到 ±0.5**（即 pitch 最大约 ±0.5 rad/s ≈ **±28.6 °/s**）。
- 语义：是**速度**，要像握摇杆一样**持续重复发送**才会持续运动；停发即停。
- ⚠️ **"pitch_vel × 保持时间 = 实际俯仰角度"只是理论积分，原生 SDK 不保证闭环精度。** 你待验证清单里"exact pitch degrees per second on the mounted robot"是对的 —— 这个映射**必须你在装好的真机上标定**，我们给不了一个保证准确的换算常数。建议：固定一个 pitch_vel + 固定保持时间，用你的 charuco/视觉或 Codey 量出实际到位角度，做一张查找表。

**Q5. `attitude_control` 会不会触发 damping？** —— **正常不会。** Aegis 路径下它是纯姿态速度控制，不改 FSM 到 passive。只有在后端异常 fallback 失败、或你显式调 `damping()`/`e_stop()` 时才会进阻尼。你的流程"tilt 完回中立站立、不调 damping"是安全的。前提是狗一直处于站立态。

**Q6. 官方相机流 URL / 分辨率 / 编码 / 延迟 / 重连？** —— 流地址 `rtsp://192.168.234.1:8554/test`，1920×1080。SDK 不封装相机，编码/延迟/重连都由 RTSP 服务端决定，建议你用 `-rtsp_transport tcp` + 上面那组 analyzeduration/probesize 参数降低首帧延迟和卡顿；重连请你自己在 OpenCV/ffmpeg 侧加重试。

**Q7. 相机帧是否带时间戳、是否与 IMU/位姿同步？** —— **否。** 无帧时间戳，无硬件同步。只能软件侧"尽量同时刻"读 pose 和 frame。对身高测量影响：取帧瞬间和读 pitch 瞬间要尽量靠近，狗 tilt 到位后**先 settle 一小段再同时读**最稳。

**Q8. 支持哪些 ROS2 topic/service？** —— 对外**没有**公开 ROS2 接口。运动/相机/IMU/里程计/电量都请走 ff_sdk 的 Python/C++ API（上表），不要假设有可订阅的 ROS2 topic。

---

## 三、针对你"身高测量"项目的 3 条关键提醒

1. **pitch 角的真相**：`state.pose().pitch` 是**机身**俯仰，不是相机俯仰。你的身高几何需要的是相机光轴的俯仰角 = 机身 pitch + 相机相对机身的固定安装角（外参）。这个外参一次性标定即可（你 Codey 那一路其实是在交叉验证它）。**别直接拿 state.pose().pitch 当相机 pitch 用。**

2. **attitude_control 用法**：它是速度、要持续发、需狗先站立、各轴 ±0.5 rad/s。你的流程（站立 → 学背景 → RT → 居中 → tilt 上 → settle → 取图 → 回中 → tilt 下 → settle → 取图 → 回中立、不 damping）完全契合它的语义。**tilt 后务必留 settle 再取图**，因为停发速度到机身真正稳定有惯性延迟。

3. **相机帧仍走你的 RTSP/OpenCV**：SDK 的 vision.frame 还没接线，你现在的路径就是对的，不用等 SDK。等我们接线了会在 release notes 通知你，但你的标定/几何流程不依赖它，无需改动。

---

## 四、一句话小结

你表里标 **Partial 的项**（velocity/gait/attitude/IMU/odom/camera/joint）我们这边都有可调的 function，上表给了确切签名和限位；标 **Unknown 的 5 项**（charging / dock / OTA / expansion / time sync）**确实在 SDK 里不存在**，不用再等我们补文档。对你身高项目最关键的 attitude_control 的单位/限位/语义已坐实（速度、±0.5 rad/s、需持续发、需站立、pitch×时间映射要真机标）。

有任何一项要更细的示例代码（比如 attitude_control 标定脚本、settle+取帧时序），告诉我，我直接给你跑得起来的片段。
