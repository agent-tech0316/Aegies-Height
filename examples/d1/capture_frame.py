"""d1/capture_frame — 抓一张相机帧存成 JPEG.

演示新接线的 `vision.frame()`：从机器狗的 RTSP 流抓一帧,返回 JPEG bytes。
内部已封装好 ffmpeg 抓帧 + 软解(避开 RK 硬解卡死)+ 超时/重试,你不用自己搞。

注意:这是 RTSP 帧（H.264 解码后），分辨率即流分辨率（默认 1920×1080）。
它和"从视频流截一帧"是同一路相机——本机没有更高分辨率的独立拍照通道。

Usage:
    FF_SDK_DRY_RUN=1 python d1/capture_frame.py            # 干跑,任何电脑（不出真图）
    python d1/capture_frame.py                             # 默认 rtsp://<host>:8554/test
    python d1/capture_frame.py --source rtsp://192.168.234.1:8554/test
    python d1/capture_frame.py --out /tmp/shot.jpg

前提:跑这台机器能 ping 通机器狗、装了 ffmpeg。
"""
from __future__ import annotations

import argparse
import asyncio
import logging

import ff_sdk
from ff_sdk import Config
from ff_sdk.core.exceptions import CapabilityNotSupported, TransportError


async def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--target", default="D1-DEMO",
                   help="连接目标（默认 D1-DEMO；也可写机器人 host，如 192.168.234.1）")
    p.add_argument("--source", default="default",
                   help="相机源：default=rtsp://<host>:8554/test，或填完整 RTSP URL")
    p.add_argument("--out", default="frame.jpg", help="输出 JPEG 路径")
    args = p.parse_args()

    logging.basicConfig(level=logging.INFO)

    sess = await ff_sdk.connect(args.target, config=Config.from_env())
    try:
        # 抓一帧 —— 返回 CameraFrame：data 是 JPEG bytes，还带 encoding/width/height/source
        frame = await sess.vision.frame(args.source)
        if not frame.data:
            print("（干跑模式：未抓真图。去掉 FF_SDK_DRY_RUN 在能连狗的机器上跑。）")
            return
        with open(args.out, "wb") as f:
            f.write(frame.data)
        print(f"✓ 已存 {args.out}（{len(frame.data)} bytes，源 {frame.source}）")
        print("  接下来可喂给 OpenCV / YOLO：cv2.imdecode(np.frombuffer(open(out,'rb').read(), np.uint8), 1)")
    except CapabilityNotSupported as e:
        print(f"✗ 不可用：{e}（多半是没装 ffmpeg）")
    except TransportError as e:
        print(f"✗ 抓帧失败：{e}（确认 RTSP 流通、能连到狗）")
    finally:
        await sess.close()


if __name__ == "__main__":
    asyncio.run(main())
