#!/bin/bash
# grab_uncompressed_frame.sh — 在机器狗本体上抓一张"未经 H.264 压缩的原始相机帧"
# ============================================================================
# 目的:验证"狗本体直读原始帧" vs "RTSP 抓帧(H.264 压缩)"的画质差距,
#      给身高测量判断值不值得把取帧挪到狗本体。
#
# 原理:相机 /dev/video11 输出原始 NV12,平时被推流器 ffmedia_stream 独占去推
#      RTSP(:8554,H.264 编码)。所以:
#        • 外部(树莓派)只能拿到 RTSP 那一路 = H.264 压缩→解码后的帧。
#        • 想要原始无压缩帧,必须在狗本体上、临时释放 /dev/video11 后直读 V4L2。
#      本脚本各抓一张,放一起对比。
#
# ⚠️ 副作用:第 3 步会临时 SIGKILL 掉 ffmedia_stream 释放相机,
#           期间 RTSP 推流中断约 2-5 秒,robot-launch 会自动把它重新拉起。
#           这是一次性验证工具,**不要常驻跑**。
# ⚠️ 需要 root(kill 推流器 + 直读 V4L2 设备):用 sudo 跑。
#
# 用法:  sudo bash grab_uncompressed_frame.sh
#        OUT=/tmp/cmp W=1920 H=1080 sudo -E bash grab_uncompressed_frame.sh
# ============================================================================
set -u

OUT=${OUT:-/tmp/d1_frame_cmp}
RTSP=${RTSP:-rtsp://127.0.0.1:8554/test}
VIDEO=${VIDEO:-/dev/video11}
W=${W:-1920}
H=${H:-1080}
mkdir -p "$OUT"

need() { command -v "$1" >/dev/null 2>&1 || { echo "缺少 $1,请先安装"; exit 1; }; }
need ffmpeg

echo "============================================================"
echo " 输出目录: $OUT"
echo " RTSP    : $RTSP"
echo " 相机设备: $VIDEO  (${W}x${H})"
echo "============================================================"

# ── 1) 对照组:RTSP(H.264 压缩)帧 —— 先抓,不影响推流 ─────────────────────
echo "[1/4] 抓 RTSP(H.264 压缩)帧 → rtsp_h264.jpg"
# -vcodec h264 强制软解:h264_rkmpp 硬解在 RK3588 上会卡死数分钟
ffmpeg -y -loglevel error -vcodec h264 -rtsp_transport tcp \
    -analyzeduration 500000 -probesize 500000 -i "$RTSP" \
    -frames:v 1 -q:v 2 "$OUT/rtsp_h264.jpg" 2>/dev/null \
    && echo "      ✓ $(du -h "$OUT/rtsp_h264.jpg" | cut -f1)" \
    || echo "      ⚠ RTSP 抓帧失败(流没起?先确认 $RTSP 通)"

# ── 2) 探测相机原生格式(直读参数不对时看这里调) ────────────────────────────
echo "[2/4] 相机原生格式(如下读不出,按这里的 Pixel/Size 调 -input_format / W H):"
if command -v v4l2-ctl >/dev/null 2>&1; then
    v4l2-ctl -d "$VIDEO" --list-formats-ext 2>/dev/null \
        | grep -E "\[|Size:|Pixel" | sed 's/^/      /' | head -20
else
    echo "      (没装 v4l2-ctl,跳过探测;装: apt install v4l-utils)"
fi

# ── 3) 停推流器 → 直读 V4L2 原始帧(无 H.264) ──────────────────────────────
PID=$(pgrep -x ffmedia_stream || true)
echo "[3/4] 停 ffmedia_stream(pid=${PID:-none})→ 直读 $VIDEO 原始帧 → raw.png"
if [ -n "${PID:-}" ]; then
    # SIGKILL:ffmedia_stream 吞 SIGTERM。用 pgrep/kill 精确 pid,
    # 千万别 pkill -f ffmedia_stream —— 会误匹配 sudo 自己的 cmdline 把自己杀了。
    kill -9 "$PID" 2>/dev/null
    sleep 0.4   # 给内核释放 /dev/video11 一点时间;要赶在 robot-launch respawn 前抓到
fi
# 原始 NV12 → PNG(无损,不经 H.264)。失败则让 ffmpeg 自己协商格式再试一次。
if ! ffmpeg -y -loglevel error -f v4l2 -input_format nv12 -video_size "${W}x${H}" \
        -i "$VIDEO" -frames:v 1 "$OUT/raw.png" 2>/dev/null; then
    echo "      nv12 直读失败,改用自动格式重试..."
    ffmpeg -y -loglevel error -f v4l2 -video_size "${W}x${H}" \
        -i "$VIDEO" -frames:v 1 "$OUT/raw.png" 2>/dev/null \
        || echo "      ⚠ 原始帧抓取失败 —— 按第 2 步的格式手动调 -input_format / W H"
fi
[ -s "$OUT/raw.png" ] && echo "      ✓ $(du -h "$OUT/raw.png" | cut -f1)"

# ── 4) 让 robot-launch 自动恢复推流器,验证 RTSP 回来 ──────────────────────
echo "[4/4] 等推流器自动恢复(robot-launch ~2s respawn)..."
sleep 3
if pgrep -x ffmedia_stream >/dev/null; then
    echo "      ✓ ffmedia_stream 已恢复,RTSP 正常"
else
    echo "      ⚠ 推流器未自动恢复!检查: systemctl status robot-launch"
    echo "        手动恢复: reboot,或看 /opt/app_launch/start_push_ffmedia.sh"
fi

# ── 结果 ────────────────────────────────────────────────────────────────────
echo "============================================================"
echo " 原始无压缩帧 : $OUT/raw.png        ($(du -h "$OUT/raw.png" 2>/dev/null | cut -f1 || echo '无'))"
echo " RTSP H.264帧 : $OUT/rtsp_h264.jpg  ($(du -h "$OUT/rtsp_h264.jpg" 2>/dev/null | cut -f1 || echo '无'))"
echo ""
echo " 把这两张拉回树莓派,跑 compare_frames.py 量化对比清晰度:"
echo "   scp <dog>:$OUT/raw.png $OUT/rtsp_h264.jpg ./"
echo "   python3 compare_frames.py raw.png rtsp_h264.jpg"
echo " 直觉判据:raw.png 文件明显更大、放大看边缘没有 8x8 压缩块 = 原始帧更清晰。"
echo "============================================================"
