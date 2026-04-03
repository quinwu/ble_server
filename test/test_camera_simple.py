#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单的摄像头测试脚本
用于快速检查摄像头是否可用
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path


def run_command(cmd, description):
    """运行命令并返回结果"""
    print(f"\n{'=' * 60}")
    print(f"测试: {description}")
    print(f"命令: {' '.join(cmd)}")
    print("=" * 60)

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)

        if result.stdout:
            print("标准输出:")
            print(result.stdout)

        if result.stderr:
            print("错误输出:")
            print(result.stderr)

        print(f"返回码: {result.returncode}")

        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print("❌ 命令超时")
        return False
    except Exception as e:
        print(f"❌ 执行失败: {e}")
        return False


def main():
    # 解析命令行参数
    parser = argparse.ArgumentParser(description="摄像头硬件快速测试")
    parser.add_argument(
        "--card-type-filter", type=str, default=None, help='设备类型过滤（如 "USB Camera"），只测试匹配的设备'
    )
    args = parser.parse_args()

    print("=" * 60)
    print("摄像头硬件快速测试")
    print("=" * 60)

    if args.card_type_filter:
        print(f"\n设备类型过滤: {args.card_type_filter}")

    # 1. 检查设备
    print("\n1. 检查设备文件")
    video_devices = list(Path("/dev").glob("video*"))
    if video_devices:
        print(f"✓ 找到 {len(video_devices)} 个视频设备:")
        for dev in video_devices:
            print(f"  - {dev}")
            if dev.is_symlink():
                print(f"    符号链接 -> {dev.resolve()}")
    else:
        print("❌ 未找到视频设备")
        return 1

    # 2. 检查 v4l2-ctl
    if not Path("/usr/bin/v4l2-ctl").exists() and not Path("/usr/local/bin/v4l2-ctl").exists():
        # 尝试 which
        result = subprocess.run(["which", "v4l2-ctl"], capture_output=True)
        if result.returncode != 0:
            print("\n❌ v4l2-ctl 未安装")
            print("   安装: sudo apt-get install v4l-utils")
            return 1

    # 3. 测试每个设备（优先测试 rkisp 和 UVC 设备）
    # 先找出 rkisp 和 UVC 设备，并根据 card_type_filter 过滤
    priority_devices = []
    other_devices = []

    for dev in video_devices:
        dev_str = str(dev)
        # 检查设备信息
        try:
            result = subprocess.run(["v4l2-ctl", "-d", dev_str, "--info"], capture_output=True, text=True, timeout=3)

            if result.returncode != 0:
                continue

            # 解析设备信息
            card_type = None
            driver = None

            for line in result.stdout.split("\n"):
                if "Card type" in line:
                    card_type = line.split(":", 1)[1].strip()
                elif "Driver name" in line:
                    driver = line.split(":", 1)[1].strip()

            # 如果指定了 card_type_filter，检查是否匹配
            if args.card_type_filter:
                if args.card_type_filter.lower() not in (card_type or "").lower():
                    print(f"  跳过设备 {dev_str} (Card type: {card_type or 'Unknown'}, 不匹配过滤条件)")
                    continue

            # 检查是否是 rkisp 或 UVC 设备（用于优先级排序）
            if "rkisp" in (driver or "").lower() or "uvc" in (driver or "").lower():
                priority_devices.append(dev)
            else:
                other_devices.append(dev)
        except subprocess.TimeoutExpired:
            print(f"  检测设备 {dev_str} 超时，跳过")
            continue
        except Exception as e:
            print(f"  检测设备 {dev_str} 异常: {e}，跳过")
            continue

    # 先测试优先设备
    devices_to_test = priority_devices + other_devices

    if not devices_to_test:
        print("\n❌ 未找到符合条件的设备")
        if args.card_type_filter:
            print(f"   过滤条件: {args.card_type_filter}")
        return 1

    print(
        f"\n✓ 找到 {len(devices_to_test)} 个符合条件的设备（优先设备: {len(priority_devices)}, 其他设备: {len(other_devices)}）"
    )
    success_list = []
    for dev in devices_to_test:
        dev_str = str(dev)
        print(f"\n{'=' * 60}")
        print(f"测试设备: {dev_str}")
        print("=" * 60)

        # 3.1 获取设备信息
        run_command(["v4l2-ctl", "-d", dev_str, "--info"], "获取设备信息")

        # 3.2 获取支持的格式
        run_command(["v4l2-ctl", "-d", dev_str, "--list-formats-ext"], "获取支持的格式")

        # 3.3 获取当前格式
        run_command(["v4l2-ctl", "-d", dev_str, "--get-fmt-video"], "获取当前格式")

        # 3.4 尝试设置格式并拍照
        print(f"\n{'=' * 60}")
        print("尝试设置格式并拍照")
        print("=" * 60)

        test_image = f"/tmp/test_camera_{dev.name}.jpg"

        # 检查是否是 Multiplanar 设备
        is_mplane = False
        info_result = subprocess.run(["v4l2-ctl", "-d", dev_str, "--info"], capture_output=True, text=True, timeout=5)
        if "Multiplanar" in info_result.stdout:
            is_mplane = True
            print("检测到 Multiplanar 设备，将使用特殊流程")

        # 先尝试设置格式（如果还没有设置）
        fmt_result = subprocess.run(
            ["v4l2-ctl", "-d", dev_str, "--set-fmt-video=width=800,height=600,pixelformat=UYVY"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if fmt_result.returncode == 0:
            print("✓ 格式设置成功")
        else:
            print("⚠ 格式设置失败，尝试不设置格式")
            if fmt_result.stderr:
                print(fmt_result.stderr)

        # 解析实际设备路径（如果是符号链接）
        actual_dev_str = dev_str
        if dev.is_symlink():
            try:
                actual_dev_str = str(dev.resolve())
                if actual_dev_str != dev_str:
                    print(f"使用实际设备路径: {actual_dev_str}")
            except:
                pass

        # 尝试拍照 - 多种方法
        print(f"\n尝试拍照到: {test_image}")

        # 对于 Multiplanar 设备，优先尝试替代方法
        if is_mplane:
            print("\n⚠ 检测到 Multiplanar 设备，v4l2-ctl 可能无法工作")
            print("尝试使用替代方法...")

            # 方法 1: 尝试 fswebcam（对 rkisp 设备最可靠）
            if subprocess.run(["which", "fswebcam"], capture_output=True).returncode == 0:
                print("\n尝试方法: fswebcam")
                fsweb_methods = [
                    (
                        [
                            "-d",
                            actual_dev_str,
                            "-r",
                            "800x600",
                            "--no-banner",
                            "--no-input",
                            "--jpeg",
                            "95",
                            "-F",
                            "5",
                            test_image,
                        ],
                        "with --no-input",
                    ),
                    (
                        ["-d", actual_dev_str, "-r", "800x600", "--no-banner", "--jpeg", "95", "-F", "5", test_image],
                        "standard",
                    ),
                    (
                        ["-d", actual_dev_str, "--no-banner", "--no-input", "--jpeg", "95", "-F", "5", test_image],
                        "auto resolution",
                    ),
                ]

                for fsweb_cmd, desc in fsweb_methods:
                    fsweb_result = subprocess.run(["fswebcam"] + fsweb_cmd, capture_output=True, text=True, timeout=10)

                    if Path(test_image).exists() and Path(test_image).stat().st_size > 0:
                        size = Path(test_image).stat().st_size
                        print(f"✓ fswebcam 拍照成功 ({desc})! 文件大小: {size} 字节")
                        print(f"  文件保存在: {test_image}")
                        sys.exit(0)
                    elif fsweb_result.returncode != 0 and fsweb_result.stderr:
                        print(f"  {desc} 失败: {fsweb_result.stderr.strip()[:100]}")

                print("✗ fswebcam 所有方法都失败")

            # 方法 2: 尝试 OpenCV（强制使用 V4L2 后端）
            try:
                import cv2

                print("\n尝试方法: OpenCV (强制 V4L2)")
                # 设置环境变量强制使用 V4L2
                env = os.environ.copy()
                env["OPENCV_VIDEOIO_PRIORITY_V4L2"] = "1"
                env["OPENCV_VIDEOIO_PRIORITY_LIST"] = "V4L2"

                cap = cv2.VideoCapture(actual_dev_str, cv2.CAP_V4L2)
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 800)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 600)
                    # 预热
                    for _ in range(5):
                        cap.read()
                    ret, frame = cap.read()
                    cap.release()

                    if ret and frame is not None and frame.size > 0:
                        cv2.imwrite(test_image, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                        if Path(test_image).exists() and Path(test_image).stat().st_size > 0:
                            size = Path(test_image).stat().st_size
                            print(f"✓ OpenCV 拍照成功! 文件大小: {size} 字节")
                            print(f"  文件保存在: {test_image}")
                            sys.exit(0)
                print("✗ OpenCV 拍照失败")
            except ImportError:
                print("⚠ OpenCV 未安装，跳过")
            except Exception as e:
                print(f"✗ OpenCV 异常: {e}")

            # 方法 3: 尝试 GStreamer
            if subprocess.run(["which", "gst-launch-1.0"], capture_output=True).returncode == 0:
                print("\n尝试方法: GStreamer")
                gst_methods = [
                    (
                        f"gst-launch-1.0 v4l2src device={actual_dev_str} ! video/x-raw,width=800,height=600,format=UYVY ! jpegenc ! filesink location={test_image}",
                        "UYVY format",
                    ),
                    (
                        f"gst-launch-1.0 v4l2src device={actual_dev_str} ! video/x-raw,width=800,height=600 ! jpegenc ! filesink location={test_image}",
                        "auto format",
                    ),
                ]

                for gst_cmd, desc in gst_methods:
                    gst_result = subprocess.run(gst_cmd, shell=True, capture_output=True, text=True, timeout=10)

                    if Path(test_image).exists() and Path(test_image).stat().st_size > 0:
                        size = Path(test_image).stat().st_size
                        print(f"✓ GStreamer 拍照成功 ({desc})! 文件大小: {size} 字节")
                        print(f"  文件保存在: {test_image}")
                        sys.exit(0)
                    elif gst_result.returncode != 0 and gst_result.stderr:
                        print(f"  {desc} 失败")

                print("✗ GStreamer 所有方法都失败")

            # 方法 4: 尝试 ffmpeg（多种变体）
            if subprocess.run(["which", "ffmpeg"], capture_output=True).returncode == 0:
                print("\n尝试方法: ffmpeg")
                ffmpeg_methods = [
                    (
                        [
                            "ffmpeg",
                            "-f",
                            "v4l2",
                            "-input_format",
                            "uyvy422",
                            "-video_size",
                            "800x600",
                            "-i",
                            actual_dev_str,
                            "-frames:v",
                            "1",
                            "-y",
                            test_image,
                        ],
                        "actual device, uyvy422",
                    ),
                    (
                        [
                            "ffmpeg",
                            "-f",
                            "v4l2",
                            "-video_size",
                            "800x600",
                            "-i",
                            actual_dev_str,
                            "-frames:v",
                            "1",
                            "-y",
                            test_image,
                        ],
                        "actual device, auto format",
                    ),
                    (
                        [
                            "ffmpeg",
                            "-f",
                            "v4l2",
                            "-input_format",
                            "uyvy422",
                            "-video_size",
                            "800x600",
                            "-i",
                            dev_str,
                            "-frames:v",
                            "1",
                            "-y",
                            test_image,
                        ],
                        "symlink, uyvy422",
                    ),
                ]

                # 尝试使用 libv4l2 包装器
                libv4l2_path = None
                for lib_path in ["/usr/lib/aarch64-linux-gnu/libv4l2.so.0", "/usr/lib/libv4l2.so.0"]:
                    if Path(lib_path).exists():
                        libv4l2_path = lib_path
                        break

                use_libv4l2 = False
                if libv4l2_path:
                    ffmpeg_methods.insert(
                        0,
                        (
                            [
                                "ffmpeg",
                                "-f",
                                "v4l2",
                                "-input_format",
                                "uyvy422",
                                "-video_size",
                                "800x600",
                                "-i",
                                actual_dev_str,
                                "-frames:v",
                                "1",
                                "-y",
                                test_image,
                            ],
                            "libv4l2 wrapper, actual device",
                        ),
                    )
                    use_libv4l2 = True

                for idx, (ffmpeg_cmd, desc) in enumerate(ffmpeg_methods):
                    env = os.environ.copy()
                    if use_libv4l2 and idx == 0:
                        env["LD_PRELOAD"] = libv4l2_path

                    ffmpeg_result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=10, env=env)

                    if Path(test_image).exists() and Path(test_image).stat().st_size > 0:
                        size = Path(test_image).stat().st_size
                        print(f"✓ ffmpeg 拍照成功 ({desc})! 文件大小: {size} 字节")
                        print(f"  文件保存在: {test_image}")
                        sys.exit(0)
                    elif ffmpeg_result.stderr:
                        # 过滤掉版本信息
                        error_lines = [
                            l
                            for l in ffmpeg_result.stderr.split("\n")
                            if l and not l.startswith("  lib") and not l.startswith("ffmpeg version")
                        ]
                        if error_lines:
                            print(f"  {desc} 失败: {error_lines[-1][:100]}")

                print("✗ ffmpeg 所有方法都失败")

        # 尝试 v4l2-ctl 方法（对于非 Multiplanar 设备或作为最后尝试）
        if not is_mplane:
            print("\n尝试方法: v4l2-ctl")
            capture_methods = [
                (["--stream-mmap", "--stream-count=1", f"--stream-to={test_image}"], "stream-mmap"),
                (["--stream-to", test_image, "--stream-count=1"], "stream-to"),
                (["--stream-to", test_image], "stream-to (simple)"),
            ]

            for capture_cmd, desc in capture_methods:
                print(f"\n尝试: {desc}")
                try:
                    capture_result = subprocess.run(
                        ["v4l2-ctl", "-d", actual_dev_str] + capture_cmd, capture_output=True, text=True, timeout=10
                    )

                    print(f"返回码: {capture_result.returncode}")
                    if capture_result.stderr:
                        print("错误输出:")
                        print(capture_result.stderr[:200])

                    # 检查文件
                    test_image_path = Path(test_image)
                    if test_image_path.exists():
                        try:
                            size = test_image_path.stat().st_size
                            if size > 0:
                                print(f"✅ 拍照成功! 文件大小: {size} 字节")
                                print(f"  文件保存在: {test_image}")
                                success_list.append(
                                    {"capture_cmd": capture_cmd, "desc": desc, "test_image": test_image}
                                )
                                break
                            else:
                                print(f"✗ 文件大小为 0")
                                test_image_path.unlink()
                        except Exception as e:
                            print(f"✗ 检查文件大小失败: {e}")
                    else:
                        print("✗ 文件未创建")
                except subprocess.TimeoutExpired:
                    print(f"✗ 命令超时")
                except Exception as e:
                    print(f"✗ 异常: {e}")

        if is_mplane:
            print("\n建议:")
            print("1. 安装 fswebcam: sudo apt-get install fswebcam")
            print("2. 安装 OpenCV: pip3 install opencv-python")
            print(
                "3. 安装 GStreamer: sudo apt-get install gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good"
            )
            print("4. 安装 ffmpeg: sudo apt-get install ffmpeg")
            print(f"5. 尝试运行: sudo ./test/test_camera_quick.sh {dev_str}")

    print("\n" + "=" * 60)
    print("测试完成", success_list)
    print("=" * 60)

    return 0


if __name__ == "__main__":
    # sudo python3 test_camera_simple.py --card-type-filter "USB Camera"
    sys.exit(main())
