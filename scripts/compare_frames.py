#!/usr/bin/env python3
"""compare_frames.py — 量化对比"原始无压缩帧" vs "RTSP H.264 帧"的清晰度。

配合 grab_uncompressed_frame.sh 用:在树莓派(已装 opencv)上,对抓回来的
两张图做客观对比,判断把取帧挪到狗本体到底值不值。

用法:
    python3 compare_frames.py raw.png rtsp_h264.jpg

指标:
  • 文件大小       —— PNG 无损通常大得多
  • 分辨率
  • 锐度(Laplacian 方差) —— 高频能量,越高越锐。H.264 压缩抹掉高频 → 这个值会更低。
  • (尺寸一致时)平均像素差 / PSNR —— H.264 相对原始改了多少
"""
import os
import sys

try:
    import cv2
    import numpy as np
except ImportError:
    sys.exit("需要 opencv-python + numpy(树莓派上一般已装):pip install opencv-python numpy")


def sharpness(gray) -> float:
    """Laplacian 方差 —— 经典清晰度/对焦指标,越高越锐。"""
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def load(path):
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        sys.exit(f"读不了图片: {path}")
    return img


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit("用法: python3 compare_frames.py <raw.png> <rtsp_h264.jpg>")
    pa, pb = sys.argv[1], sys.argv[2]
    a, b = load(pa), load(pb)
    sa = sharpness(cv2.cvtColor(a, cv2.COLOR_BGR2GRAY))
    sb = sharpness(cv2.cvtColor(b, cv2.COLOR_BGR2GRAY))

    col = lambda s: f"{s:>24}"
    print(f"{'':16}{col('原始 ' + os.path.basename(pa))}{col('RTSP ' + os.path.basename(pb))}")
    print(f"{'文件大小':16}{col(f'{os.path.getsize(pa)/1024:.1f} KB')}{col(f'{os.path.getsize(pb)/1024:.1f} KB')}")
    print(f"{'分辨率':16}{col(f'{a.shape[1]}x{a.shape[0]}')}{col(f'{b.shape[1]}x{b.shape[0]}')}")
    print(f"{'锐度(Lap方差)':16}{col(f'{sa:.1f}')}{col(f'{sb:.1f}')}")

    if a.shape == b.shape:
        diff = cv2.absdiff(a, b)
        mae = float(diff.mean())
        mse = float((diff.astype(np.float64) ** 2).mean())
        psnr = 99.0 if mse == 0 else float(10 * np.log10((255.0 ** 2) / mse))
        print(f"{'平均像素差':16}{col(f'{mae:.2f}')}{col('(两图差异)')}")
        print(f"{'PSNR(dB)':16}{col(f'{psnr:.2f}')}{col('越低=H.264改越多')}")
    else:
        print("(两图分辨率不同,跳过逐像素对比)")

    print("-" * 64)
    ratio = sa / sb if sb else float("inf")
    if sa > sb * 1.05:
        print(f"结论: 原始帧更锐({ratio:.2f}× 高频能量)。H.264 抹掉了细节,")
        print("      身高边界检测能受益 → 值得把取帧挪到狗本体。")
    elif sb > sa * 1.05:
        print("结论: 反而 RTSP 更锐?多半是 raw 抓糊/没对焦/抓到坏帧,重抓一次再比。")
    else:
        print(f"结论: 两者锐度接近({ratio:.2f}×)。这分辨率下 H.264 损失不大,")
        print("      继续用 RTSP 抓帧即可,不必折腾狗本体取帧。")


if __name__ == "__main__":
    main()
