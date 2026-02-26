#!/bin/bash
# 快速测试摄像头 - 直接测试 ffmpeg 和 OpenCV

DEVICE="${1:-/dev/video-camera0}"
TEST_IMAGE="/tmp/camera_quick_test.jpg"

echo "======================================"
echo "摄像头快速测试"
echo "设备: $DEVICE"
echo "======================================"
echo ""

# 检查设备并解析符号链接
if [ ! -e "$DEVICE" ]; then
    echo "✗ 设备不存在: $DEVICE"
    exit 1
fi

# 解析实际设备路径
ACTUAL_DEVICE=$(readlink -f "$DEVICE" 2>/dev/null || echo "$DEVICE")
if [ "$ACTUAL_DEVICE" != "$DEVICE" ]; then
    echo "设备信息:"
    echo "  符号链接: $DEVICE"
    echo "  实际路径: $ACTUAL_DEVICE"
    echo ""
fi

# 检查设备类型
if [ ! -c "$ACTUAL_DEVICE" ]; then
    echo "⚠ 警告: $ACTUAL_DEVICE 不是字符设备"
fi

# 检查设备权限
if [ ! -r "$ACTUAL_DEVICE" ]; then
    echo "⚠ 警告: 设备不可读，可能需要 sudo"
fi

# 检测设备类型
IS_RKISP=0
if command -v v4l2-ctl > /dev/null 2>&1; then
    V4L2_INFO=$(v4l2-ctl -d "$ACTUAL_DEVICE" --info 2>/dev/null)
    if echo "$V4L2_INFO" | grep -qi "rkisp"; then
        IS_RKISP=1
        echo "检测到: rkisp 设备 (Multiplanar)"
        echo "注意: ffmpeg 可能无法识别此设备，将优先尝试 gstreamer 和 OpenCV"
        echo ""
    fi
fi

echo ""

# 清理旧文件
rm -f "$TEST_IMAGE"

# 对于 rkisp 设备，优先尝试 OpenCV、gstreamer、fswebcam，最后尝试 ffmpeg 和 v4l2-ctl
# 对于其他设备，按正常顺序测试

# 测试 fswebcam (对于 rkisp 设备优先)
if [ $IS_RKISP -eq 1 ] && command -v fswebcam > /dev/null 2>&1; then
    echo "1. 测试 fswebcam (rkisp 设备推荐)"
    echo "-----------------------------------"
    
    # 清理旧文件
    rm -f "$TEST_IMAGE"
    
    # 尝试多种 fswebcam 方法
    FSWEB_METHODS=(
        "方法 1: 使用 --no-input 参数（跳过输入选择）"
        "方法 2: 不指定分辨率（自动检测）"
        "方法 3: 标准参数"
    )
    
    FSWEB_CMDS=(
        "fswebcam -d \"$ACTUAL_DEVICE\" -r 800x600 --no-banner --no-input --jpeg 95 -F 5 \"$TEST_IMAGE\""
        "fswebcam -d \"$ACTUAL_DEVICE\" --no-banner --no-input --jpeg 95 -F 5 \"$TEST_IMAGE\""
        "fswebcam -d \"$ACTUAL_DEVICE\" -r 800x600 --no-banner --jpeg 95 -F 5 \"$TEST_IMAGE\""
    )
    
    for i in "${!FSWEB_METHODS[@]}"; do
        METHOD="${FSWEB_METHODS[$i]}"
        CMD="${FSWEB_CMDS[$i]}"
        
        echo ""
        echo "$METHOD"
        echo "命令: $CMD"
        
        # 清理旧文件
        rm -f "$TEST_IMAGE"
        
        FSWEB_OUTPUT=$(timeout 10 bash -c "$CMD" 2>&1)
        FSWEB_EXIT=$?
        
        if [ $FSWEB_EXIT -eq 0 ] && [ -f "$TEST_IMAGE" ] && [ -s "$TEST_IMAGE" ]; then
            SIZE=$(stat -c%s "$TEST_IMAGE")
            echo ""
            echo "✓✓✓ fswebcam 拍照成功! ✓✓✓"
            echo "方法: $METHOD"
            echo "文件: $TEST_IMAGE"
            echo "大小: $SIZE 字节"
            echo ""
            echo "可以使用以下命令查看图片:"
            echo "  file $TEST_IMAGE"
            exit 0
        else
            echo "输出:"
            echo "$FSWEB_OUTPUT" | grep -v "^---" | tail -10
            echo ""
            echo "✗ $METHOD 失败"
        fi
    done
    
    echo ""
    echo "✗ 所有 fswebcam 方法都失败"
    echo ""
fi

# 测试 OpenCV (对于 rkisp 设备优先)
if [ $IS_RKISP -eq 1 ]; then
    # 检查 OpenCV 是否可用（包括用户安装的）
    OPENCV_AVAILABLE=0
    PYTHON_CMD="python3"
    
    # 先尝试当前用户
    if python3 -c "import cv2" 2>/dev/null; then
        OPENCV_AVAILABLE=1
        PYTHON_CMD="python3"
    # 如果使用 sudo，尝试原用户
    elif [ -n "$SUDO_USER" ] && sudo -u "$SUDO_USER" python3 -c "import cv2" 2>/dev/null; then
        OPENCV_AVAILABLE=1
        PYTHON_CMD="sudo -u $SUDO_USER python3"
    fi
    
    if [ $OPENCV_AVAILABLE -eq 1 ]; then
    echo "2. 测试 OpenCV (rkisp 设备推荐)"
    echo "-----------------------------------"
    echo "注意: 强制使用 V4L2 后端（不使用 GStreamer）"
    if [ "$PYTHON_CMD" != "python3" ]; then
        echo "使用命令: $PYTHON_CMD"
    fi
    echo ""
    $PYTHON_CMD << PYEOF
import cv2
import sys
import os

device = "$DEVICE"
actual_device = "$ACTUAL_DEVICE"
test_image = "$TEST_IMAGE"

# 强制使用 V4L2 后端（不使用 GStreamer）
# 方法 1: 使用 CAP_V4L2 标志
# 方法 2: 设置环境变量（在脚本中通过 os.environ）
os.environ['OPENCV_VIDEOIO_PRIORITY_V4L2'] = '1'

# 尝试打开设备（优先使用实际路径）
devices_to_try = [actual_device, device] if actual_device != device else [device]

cap = None
for dev in devices_to_try:
    print(f"尝试打开设备: {dev} (使用 V4L2 后端)")
    # 尝试使用 V4L2 后端标志
    try:
        # 方法 1: 使用 CAP_V4L2 标志（如果可用）
        if hasattr(cv2, 'CAP_V4L2'):
            cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
            print(f"  使用 CAP_V4L2 标志")
        else:
            # 方法 2: 直接打开（环境变量已设置）
            cap = cv2.VideoCapture(dev)
            print(f"  使用默认后端（环境变量优先 V4L2）")
    except Exception as e:
        print(f"  尝试失败: {e}")
        cap = None
    
    if cap is not None and cap.isOpened():
        print(f"✓ 设备已打开: {dev}")
        break
    else:
        if cap is not None:
            cap.release()
        print(f"✗ 无法打开: {dev}")

if cap is None or not cap.isOpened():
    print("✗ 所有设备路径都无法打开")
    sys.exit(1)

# 设置分辨率
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 800)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 600)

# 读取几帧预热
print("预热设备...")
for i in range(5):
    ret, frame = cap.read()
    if not ret:
        print(f"  预热帧 {i+1} 失败")

# 拍照
print("拍照...")
ret, frame = cap.read()
cap.release()

if not ret or frame is None:
    print("✗ 读取图像失败")
    sys.exit(1)

# 保存图像
success = cv2.imwrite(test_image, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
if success:
    size = os.path.getsize(test_image)
    print("")
    print("✓✓✓ OpenCV 拍照成功! ✓✓✓")
    print(f"文件: {test_image}")
    print(f"大小: {size} 字节")
    print("")
    print("可以使用以下命令查看图片:")
    print(f"  file {test_image}")
    sys.exit(0)
else:
    print("✗ 保存图像失败")
    sys.exit(1)
PYEOF
    
    if [ $? -eq 0 ] && [ -f "$TEST_IMAGE" ] && [ -s "$TEST_IMAGE" ]; then
        exit 0
    fi
    echo "✗ OpenCV 失败"
    echo ""
fi

# 测试 gstreamer (对于 rkisp 设备优先)
if [ $IS_RKISP -eq 1 ] && command -v gst-launch-1.0 > /dev/null 2>&1; then
    echo "3. 测试 gstreamer (rkisp 设备推荐)"
    echo "-----------------------------------"
    
    # 清理旧文件
    rm -f "$TEST_IMAGE"
    
    # 尝试多种 gstreamer 方法
    GST_METHODS=(
        "方法 1: 自动检测格式（不指定 format）"
        "方法 2: 指定 UYVY 格式"
        "方法 3: 使用 videoscale 调整大小"
    )
    
    GST_CMDS=(
        "gst-launch-1.0 -e v4l2src device=$ACTUAL_DEVICE num-buffers=1 ! video/x-raw,width=800,height=600 ! videoconvert ! jpegenc quality=95 ! filesink location=$TEST_IMAGE"
        "gst-launch-1.0 -e v4l2src device=$ACTUAL_DEVICE num-buffers=1 ! video/x-raw,format=UYVY,width=800,height=600 ! videoconvert ! jpegenc quality=95 ! filesink location=$TEST_IMAGE"
        "gst-launch-1.0 -e v4l2src device=$ACTUAL_DEVICE num-buffers=1 ! video/x-raw ! videoscale ! video/x-raw,width=800,height=600 ! videoconvert ! jpegenc quality=95 ! filesink location=$TEST_IMAGE"
    )
    
    for i in "${!GST_METHODS[@]}"; do
        METHOD="${GST_METHODS[$i]}"
        CMD="${GST_CMDS[$i]}"
        
        echo ""
        echo "$METHOD"
        echo "命令: $CMD"
        
        # 清理旧文件
        rm -f "$TEST_IMAGE"
        
        GST_OUTPUT=$(timeout 10 bash -c "$CMD" 2>&1)
        GST_EXIT=$?
        
        if [ $GST_EXIT -eq 0 ] && [ -f "$TEST_IMAGE" ] && [ -s "$TEST_IMAGE" ]; then
            SIZE=$(stat -c%s "$TEST_IMAGE")
            echo ""
            echo "✓✓✓ gstreamer 拍照成功! ✓✓✓"
            echo "方法: $METHOD"
            echo "文件: $TEST_IMAGE"
            echo "大小: $SIZE 字节"
            echo ""
            echo "可以使用以下命令查看图片:"
            echo "  file $TEST_IMAGE"
            exit 0
        else
            echo "输出:"
            echo "$GST_OUTPUT" | grep -E "(错误|error|Error|失败|failed|Failed)" | head -5
            echo ""
            echo "✗ $METHOD 失败"
        fi
    done
    
    echo ""
    echo "✗ 所有 gstreamer 方法都失败"
    echo ""
fi

# 测试 v4l2-ctl (对于 rkisp 设备，可能不支持，但尝试)
if [ $IS_RKISP -eq 1 ] && command -v v4l2-ctl > /dev/null 2>&1; then
    echo "4. 测试 v4l2-ctl (rkisp 设备可能不支持)"
    echo "-----------------------------------"
    
    # 清理旧文件
    rm -f "$TEST_IMAGE"
    
    # 对于 rkisp Multiplanar 设备，v4l2-ctl 通常无法工作，但尝试一下
    echo "注意: rkisp Multiplanar 设备可能不支持 v4l2-ctl 流式传输"
    echo ""
    
    # 尝试设置格式
    echo "尝试设置格式..."
    if v4l2-ctl -d "$ACTUAL_DEVICE" --set-fmt-video=width=800,height=600,pixelformat=UYVY 2>&1; then
        echo "✓ 格式设置成功"
    else
        echo "⚠ 格式设置失败，继续尝试..."
    fi
    
    # 尝试多种 v4l2-ctl 方法
    V4L2_METHODS=(
        "方法 1: --stream-mmap"
        "方法 2: --stream-to"
    )
    
    V4L2_CMDS=(
        "v4l2-ctl -d \"$ACTUAL_DEVICE\" --stream-mmap --stream-count=1 --stream-to=\"$TEST_IMAGE\""
        "v4l2-ctl -d \"$ACTUAL_DEVICE\" --stream-to \"$TEST_IMAGE\" --stream-count=1"
    )
    
    for i in "${!V4L2_METHODS[@]}"; do
        METHOD="${V4L2_METHODS[$i]}"
        CMD="${V4L2_CMDS[$i]}"
        
        echo ""
        echo "$METHOD"
        echo "命令: $CMD"
        
        # 清理旧文件
        rm -f "$TEST_IMAGE"
        
        # 运行命令
        V4L2_OUTPUT=$(timeout 5 bash -c "$CMD" 2>&1)
        V4L2_EXIT=$?
        
        if [ $V4L2_EXIT -eq 0 ] && [ -f "$TEST_IMAGE" ] && [ -s "$TEST_IMAGE" ]; then
            SIZE=$(stat -c%s "$TEST_IMAGE")
            echo ""
            echo "✓✓✓ v4l2-ctl 拍照成功! ✓✓✓"
            echo "方法: $METHOD"
            echo "文件: $TEST_IMAGE"
            echo "大小: $SIZE 字节"
            echo ""
            echo "可以使用以下命令查看图片:"
            echo "  file $TEST_IMAGE"
            exit 0
        else
            echo "输出:"
            echo "$V4L2_OUTPUT" | tail -10
            echo ""
            echo "✗ $METHOD 失败"
        fi
    done
    
    echo ""
    echo "✗ 所有 v4l2-ctl 方法都失败（rkisp Multiplanar 设备通常不支持）"
    echo ""
fi

# 测试 ffmpeg
if command -v ffmpeg > /dev/null 2>&1; then
    if [ $IS_RKISP -eq 1 ]; then
        echo "5. 测试 ffmpeg (rkisp 设备可能不支持)"
    else
        echo "1. 测试 ffmpeg"
    fi
    echo "-----------------------------------"
    
    # 尝试多种 ffmpeg 方法（包括使用 libv4l2 包装器）
    FFMPEG_METHODS=(
        "方法 1: 使用 libv4l2 包装器 + 实际路径"
        "方法 2: 使用实际设备路径，指定格式 uyvy422"
        "方法 3: 使用实际设备路径，自动检测格式"
        "方法 4: 使用 libv4l2 包装器 + 符号链接"
        "方法 5: 使用符号链接，指定格式 uyvy422"
    )
    
    FFMPEG_CMDS=(
        "LD_PRELOAD=libv4l2.so.0 ffmpeg -f v4l2 -input_format uyvy422 -video_size 800x600 -i \"$ACTUAL_DEVICE\" -frames:v 1 -y \"$TEST_IMAGE\""
        "ffmpeg -f v4l2 -input_format uyvy422 -video_size 800x600 -i \"$ACTUAL_DEVICE\" -frames:v 1 -y \"$TEST_IMAGE\""
        "ffmpeg -f v4l2 -video_size 800x600 -i \"$ACTUAL_DEVICE\" -frames:v 1 -y \"$TEST_IMAGE\""
        "LD_PRELOAD=libv4l2.so.0 ffmpeg -f v4l2 -input_format uyvy422 -video_size 800x600 -i \"$DEVICE\" -frames:v 1 -y \"$TEST_IMAGE\""
        "ffmpeg -f v4l2 -input_format uyvy422 -video_size 800x600 -i \"$DEVICE\" -frames:v 1 -y \"$TEST_IMAGE\""
    )
    
    for i in "${!FFMPEG_METHODS[@]}"; do
        METHOD="${FFMPEG_METHODS[$i]}"
        CMD="${FFMPEG_CMDS[$i]}"
        
        echo ""
        echo "$METHOD"
        echo "命令: $CMD"
        
        # 清理旧文件
        rm -f "$TEST_IMAGE"
        
        # 运行命令并捕获输出
        FFMPEG_OUTPUT=$(timeout 10 bash -c "$CMD" 2>&1)
        FFMPEG_EXIT=$?
        
        # 显示错误输出（过滤掉版本信息，保留错误消息）
        if [ $FFMPEG_EXIT -ne 0 ] || [ ! -f "$TEST_IMAGE" ] || [ ! -s "$TEST_IMAGE" ]; then
            echo "输出:"
            # 过滤掉版本信息行，但保留错误和警告
            echo "$FFMPEG_OUTPUT" | grep -v "^  lib" | grep -v "^  " | grep -v "^ffmpeg version" | tail -30
            if [ $FFMPEG_EXIT -ne 0 ]; then
                echo "退出码: $FFMPEG_EXIT"
            fi
            echo ""
            echo "✗ $METHOD 失败"
            continue
        fi
        
        SIZE=$(stat -c%s "$TEST_IMAGE" 2>/dev/null || echo "0")
        if [ "$SIZE" -gt 0 ]; then
            echo ""
            echo "✓✓✓ ffmpeg 拍照成功! ✓✓✓"
            echo "方法: $METHOD"
            echo "文件: $TEST_IMAGE"
            echo "大小: $SIZE 字节"
            echo ""
            echo "可以使用以下命令查看图片:"
            echo "  file $TEST_IMAGE"
            exit 0
        fi
    done
    
    echo ""
    echo "✗ 所有 ffmpeg 方法都失败"
    echo ""
    echo "注意: ffmpeg 可能无法识别 rkisp Multiplanar 设备"
    echo "建议尝试 gstreamer 或 OpenCV"
    echo ""
else
    echo "⚠ ffmpeg 未安装"
    echo "  安装: sudo apt-get install ffmpeg"
    echo ""
fi

# 测试 fswebcam (非 rkisp 设备)
if [ $IS_RKISP -eq 0 ] && command -v fswebcam > /dev/null 2>&1; then
    echo "2. 测试 fswebcam"
    echo "-----------------------------------"
    
    # 清理旧文件
    rm -f "$TEST_IMAGE"
    
    FSWEB_CMD="fswebcam -d \"$ACTUAL_DEVICE\" -r 800x600 --no-banner --jpeg 95 -F 5 \"$TEST_IMAGE\""
    echo "命令: $FSWEB_CMD"
    
    FSWEB_OUTPUT=$(timeout 10 bash -c "$FSWEB_CMD" 2>&1)
    FSWEB_EXIT=$?
    
    if [ $FSWEB_EXIT -eq 0 ] && [ -f "$TEST_IMAGE" ] && [ -s "$TEST_IMAGE" ]; then
        SIZE=$(stat -c%s "$TEST_IMAGE")
        echo ""
        echo "✓✓✓ fswebcam 拍照成功! ✓✓✓"
        echo "文件: $TEST_IMAGE"
        echo "大小: $SIZE 字节"
        echo ""
        echo "可以使用以下命令查看图片:"
        echo "  file $TEST_IMAGE"
        exit 0
    else
        echo "输出:"
        echo "$FSWEB_OUTPUT" | tail -10
        echo ""
        echo "✗ fswebcam 失败"
        echo ""
    fi
elif [ $IS_RKISP -eq 0 ]; then
    echo "⚠ fswebcam 未安装"
    echo "  安装: sudo apt-get install fswebcam"
    echo ""
fi

# 测试 v4l2-ctl (非 rkisp 设备)
if [ $IS_RKISP -eq 0 ] && command -v v4l2-ctl > /dev/null 2>&1; then
    echo "3. 测试 v4l2-ctl"
    echo "-----------------------------------"
    
    # 清理旧文件
    rm -f "$TEST_IMAGE"
    
    # 先设置格式
    echo "设置格式..."
    if v4l2-ctl -d "$ACTUAL_DEVICE" --set-fmt-video=width=800,height=600,pixelformat=UYVY 2>&1; then
        echo "✓ 格式设置成功"
    else
        echo "⚠ 格式设置失败，继续尝试..."
    fi
    
    # 尝试多种方法
    V4L2_METHODS=(
        "方法 1: --stream-mmap"
        "方法 2: --stream-to"
    )
    
    V4L2_CMDS=(
        "v4l2-ctl -d \"$ACTUAL_DEVICE\" --stream-mmap --stream-count=1 --stream-to=\"$TEST_IMAGE\""
        "v4l2-ctl -d \"$ACTUAL_DEVICE\" --stream-to \"$TEST_IMAGE\" --stream-count=1"
    )
    
    for i in "${!V4L2_METHODS[@]}"; do
        METHOD="${V4L2_METHODS[$i]}"
        CMD="${V4L2_CMDS[$i]}"
        
        echo ""
        echo "$METHOD"
        echo "命令: $CMD"
        
        # 清理旧文件
        rm -f "$TEST_IMAGE"
        
        # 运行命令
        V4L2_OUTPUT=$(timeout 5 bash -c "$CMD" 2>&1)
        V4L2_EXIT=$?
        
        if [ $V4L2_EXIT -eq 0 ] && [ -f "$TEST_IMAGE" ] && [ -s "$TEST_IMAGE" ]; then
            SIZE=$(stat -c%s "$TEST_IMAGE")
            echo ""
            echo "✓✓✓ v4l2-ctl 拍照成功! ✓✓✓"
            echo "方法: $METHOD"
            echo "文件: $TEST_IMAGE"
            echo "大小: $SIZE 字节"
            echo ""
            echo "可以使用以下命令查看图片:"
            echo "  file $TEST_IMAGE"
            exit 0
        else
            echo "输出:"
            echo "$V4L2_OUTPUT" | tail -10
            echo ""
            echo "✗ $METHOD 失败"
        fi
    done
    
    echo ""
    echo "✗ 所有 v4l2-ctl 方法都失败"
    echo ""
elif [ $IS_RKISP -eq 0 ]; then
    echo "⚠ v4l2-ctl 未安装"
    echo "  安装: sudo apt-get install v4l-utils"
    echo ""
fi

# 测试 gstreamer (非 rkisp 设备)
if [ $IS_RKISP -eq 0 ] && command -v gst-launch-1.0 > /dev/null 2>&1; then
    echo "4. 测试 gstreamer"
    echo "-----------------------------------"
    
    # 清理旧文件
    rm -f "$TEST_IMAGE"
    
    # 尝试实际设备路径和符号链接
    for GST_DEV in "$ACTUAL_DEVICE" "$DEVICE"; do
        GST_CMD="gst-launch-1.0 -e v4l2src device=$GST_DEV num-buffers=1 ! video/x-raw,format=UYVY,width=800,height=600 ! videoconvert ! jpegenc quality=95 ! filesink location=$TEST_IMAGE"
        echo "命令: $GST_CMD"
        
        GST_OUTPUT=$(timeout 10 bash -c "$GST_CMD" 2>&1)
        GST_EXIT=$?
        
        if [ $GST_EXIT -eq 0 ] && [ -f "$TEST_IMAGE" ] && [ -s "$TEST_IMAGE" ]; then
            SIZE=$(stat -c%s "$TEST_IMAGE")
            echo ""
            echo "✓✓✓ gstreamer 拍照成功! ✓✓✓"
            echo "文件: $TEST_IMAGE"
            echo "大小: $SIZE 字节"
            echo ""
            echo "可以使用以下命令查看图片:"
            echo "  file $TEST_IMAGE"
            exit 0
        else
            echo "输出:"
            echo "$GST_OUTPUT" | tail -10
            echo ""
            if [ "$GST_DEV" = "$ACTUAL_DEVICE" ]; then
                echo "✗ 使用实际路径失败，尝试符号链接..."
                echo ""
            fi
        fi
    done
    
    echo "✗ gstreamer 失败"
    echo ""
elif [ $IS_RKISP -eq 0 ]; then
    echo "⚠ gstreamer 未安装"
    echo "  安装: sudo apt-get install gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good"
    echo ""
fi

# 测试 OpenCV (非 rkisp 设备)
OPENCV_AVAILABLE_NONRKISP=0
PYTHON_CMD_NONRKISP="python3"
if python3 -c "import cv2" 2>/dev/null; then
    OPENCV_AVAILABLE_NONRKISP=1
elif [ -n "$SUDO_USER" ] && sudo -u "$SUDO_USER" python3 -c "import cv2" 2>/dev/null; then
    OPENCV_AVAILABLE_NONRKISP=1
    PYTHON_CMD_NONRKISP="sudo -u $SUDO_USER python3"
fi

if [ $IS_RKISP -eq 0 ] && [ $OPENCV_AVAILABLE_NONRKISP -eq 1 ]; then
    echo "5. 测试 OpenCV"
    echo "-----------------------------------"
    if [ "$PYTHON_CMD_NONRKISP" != "python3" ]; then
        echo "使用命令: $PYTHON_CMD_NONRKISP"
    fi
    $PYTHON_CMD_NONRKISP << PYEOF
import cv2
import sys
import os

device = "$DEVICE"
actual_device = "$ACTUAL_DEVICE"
test_image = "$TEST_IMAGE"

# 尝试打开设备（优先使用实际路径）
devices_to_try = [actual_device, device] if actual_device != device else [device]

cap = None
for dev in devices_to_try:
    print(f"尝试打开设备: {dev}")
    # 尝试使用 V4L2 后端（如果可用）
    try:
        if hasattr(cv2, 'CAP_V4L2'):
            cap = cv2.VideoCapture(dev, cv2.CAP_V4L2)
        else:
            cap = cv2.VideoCapture(dev)
    except Exception as e:
        print(f"  尝试失败: {e}")
        cap = None
    
    if cap is not None and cap.isOpened():
        print(f"✓ 设备已打开: {dev}")
        break
    else:
        if cap is not None:
            cap.release()
        print(f"✗ 无法打开: {dev}")

if cap is None or not cap.isOpened():
    print("✗ 所有设备路径都无法打开")
    sys.exit(1)

# 设置分辨率
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 800)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 600)

# 读取几帧预热
print("预热设备...")
for i in range(5):
    ret, frame = cap.read()
    if not ret:
        print(f"  预热帧 {i+1} 失败")

# 拍照
print("拍照...")
ret, frame = cap.read()
cap.release()

if not ret or frame is None:
    print("✗ 读取图像失败")
    sys.exit(1)

# 保存图像
success = cv2.imwrite(test_image, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
if success:
    size = os.path.getsize(test_image)
    print("")
    print("✓✓✓ OpenCV 拍照成功! ✓✓✓")
    print(f"文件: {test_image}")
    print(f"大小: {size} 字节")
    print("")
    print("可以使用以下命令查看图片:")
    print(f"  file {test_image}")
    sys.exit(0)
else:
    print("✗ 保存图像失败")
    sys.exit(1)
PYEOF
    
    if [ $? -eq 0 ] && [ -f "$TEST_IMAGE" ] && [ -s "$TEST_IMAGE" ]; then
        exit 0
    fi
    echo "✗ OpenCV 失败"
    echo ""
    else
        echo "⚠ OpenCV 未安装或无法访问"
        echo "  安装: pip3 install opencv-python"
        echo "  注意: 如果已安装但检测不到，可能需要使用 sudo -u \$USER 运行"
        echo ""
    fi
fi

echo "======================================"
echo "所有方法都失败"
echo "======================================"
echo ""

# 对于 rkisp 设备，特别强调 OpenCV
if [ $IS_RKISP -eq 1 ]; then
    echo "⚠⚠⚠ 重要提示 ⚠⚠⚠"
    echo ""
    echo "对于 rkisp Multiplanar 设备，OpenCV 通常是最可靠的方法！"
    echo ""
    if python3 -c "import cv2" 2>/dev/null; then
        echo "OpenCV 已安装，但可能使用了错误的视频后端。"
        echo "脚本已尝试强制使用 V4L2 后端。"
        echo ""
        echo "如果仍然失败，可以尝试："
        echo "1. 检查 OpenCV 版本: python3 -c 'import cv2; print(cv2.__version__)'"
        echo "2. 检查可用的后端: python3 -c 'import cv2; print([i for i in dir(cv2) if \"CAP_\" in i])'"
        echo "3. 重新编译 OpenCV 以支持 V4L2"
    else
        echo "请安装 OpenCV 后重新运行测试："
        echo "  sudo pip3 install opencv-python"
        echo ""
        echo "或者使用系统包管理器："
        echo "  sudo apt-get update"
        echo "  sudo apt-get install python3-opencv"
    fi
    echo ""
    echo "安装后再次运行："
    echo "  sudo ./test_camera_quick.sh /dev/video-camera0"
    echo ""
fi

echo "建议:"
echo "1. 安装 fswebcam: sudo apt-get install fswebcam"
echo "2. 安装 v4l-utils: sudo apt-get install v4l-utils"
echo "3. 安装 OpenCV: pip3 install opencv-python"
echo "4. 安装 gstreamer: sudo apt-get install gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good"
echo "5. 安装 ffmpeg: sudo apt-get install ffmpeg"
echo "6. 检查设备: v4l2-ctl -d $ACTUAL_DEVICE --all"
echo ""
echo "调试信息:"
echo "- 设备路径: $DEVICE"
if [ "$ACTUAL_DEVICE" != "$DEVICE" ]; then
    echo "- 实际路径: $ACTUAL_DEVICE"
fi
echo "- 检查设备权限: ls -l $ACTUAL_DEVICE"
echo "- 检查设备格式: v4l2-ctl -d $ACTUAL_DEVICE --get-fmt-video"
echo ""
echo "其他尝试方法:"
echo "- 检查 OpenCV 安装: python3 -c 'import cv2; print(cv2.__version__)'"
echo "- 检查 OpenCV 后端: python3 -c 'import cv2; print([i for i in dir(cv2) if \"CAP_\" in i])'"
echo "- 尝试直接 V4L2 API: python3 test_camera_v4l2_direct.py $ACTUAL_DEVICE"
echo "- 安装 v4l2-python3: pip3 install v4l2-python3"

exit 1
