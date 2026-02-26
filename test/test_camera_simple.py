#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
简单的摄像头测试脚本
用于快速检查摄像头是否可用
"""

import subprocess
import sys
import os
from pathlib import Path

def run_command(cmd, description):
    """运行命令并返回结果"""
    print(f"\n{'='*60}")
    print(f"测试: {description}")
    print(f"命令: {' '.join(cmd)}")
    print('='*60)
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10
        )
        
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
    print("="*60)
    print("摄像头硬件快速测试")
    print("="*60)
    
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
    # 先找出 rkisp 和 UVC 设备
    priority_devices = []
    other_devices = []
    
    for dev in video_devices:
        dev_str = str(dev)
        # 检查是否是 rkisp 或 UVC 设备
        try:
            result = subprocess.run(
                ["v4l2-ctl", "-d", dev_str, "--info"],
                capture_output=True,
                text=True,
                timeout=3
            )
            if "rkisp" in result.stdout.lower() or "uvc" in result.stdout.lower():
                priority_devices.append(dev)
            else:
                other_devices.append(dev)
        except:
            other_devices.append(dev)
    
    # 先测试优先设备
    devices_to_test = priority_devices + other_devices[:5]  # 只测试前5个其他设备
    
    for dev in devices_to_test:
        dev_str = str(dev)
        print(f"\n{'='*60}")
        print(f"测试设备: {dev_str}")
        print('='*60)
        
        # 3.1 获取设备信息
        run_command(
            ["v4l2-ctl", "-d", dev_str, "--info"],
            "获取设备信息"
        )
        
        # 3.2 获取支持的格式
        run_command(
            ["v4l2-ctl", "-d", dev_str, "--list-formats-ext"],
            "获取支持的格式"
        )
        
        # 3.3 获取当前格式
        run_command(
            ["v4l2-ctl", "-d", dev_str, "--get-fmt-video"],
            "获取当前格式"
        )
        
        # 3.4 尝试设置格式并拍照
        print(f"\n{'='*60}")
        print("尝试设置格式并拍照")
        print('='*60)
        
        test_image = f"/tmp/test_camera_{dev.name}.jpg"
        
        # 检查是否是 Multiplanar 设备
        is_mplane = False
        info_result = subprocess.run(
            ["v4l2-ctl", "-d", dev_str, "--info"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if "Multiplanar" in info_result.stdout:
            is_mplane = True
            print("检测到 Multiplanar 设备，将使用特殊流程")
        
        # 先尝试设置格式（如果还没有设置）
        fmt_result = subprocess.run(
            ["v4l2-ctl", "-d", dev_str, "--set-fmt-video=width=800,height=600,pixelformat=UYVY"],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if fmt_result.returncode == 0:
            print("✓ 格式设置成功")
        else:
            print("⚠ 格式设置失败，尝试不设置格式")
            if fmt_result.stderr:
                print(fmt_result.stderr)
        
        # 对于 Multiplanar 设备，尝试请求缓冲区
        if is_mplane:
            print("\n尝试请求缓冲区 (REQBUFS)...")
            
            # 尝试多种缓冲区请求方式
            reqbufs_methods = [
                (["--reqbufs-mplane", "count=4", "type=video", "memory=mmap"], "mplane mmap"),
                (["--reqbufs-mplane", "count=2", "type=video", "memory=mmap"], "mplane mmap (2 buffers)"),
                (["--reqbufs", "count=4", "type=video", "memory=mmap"], "standard mmap"),
            ]
            
            reqbufs_success = False
            for reqbufs_cmd, desc in reqbufs_methods:
                reqbufs_result = subprocess.run(
                    ["v4l2-ctl", "-d", dev_str] + reqbufs_cmd,
                    capture_output=True,
                    text=True,
                    timeout=5
                )
                
                if reqbufs_result.returncode == 0:
                    print(f"✓ 缓冲区请求成功 ({desc})")
                    reqbufs_success = True
                    break
                else:
                    print(f"✗ 缓冲区请求失败 ({desc})")
                    if reqbufs_result.stderr:
                        print(f"  错误: {reqbufs_result.stderr.strip()}")
            
            if not reqbufs_success:
                print("⚠ 所有缓冲区请求方式都失败，继续尝试拍照")
        
        # 尝试拍照 - 多种方法
        print(f"\n尝试拍照到: {test_image}")
        
        # 对于 rkisp 设备，v4l2-ctl 可能无法工作，先尝试替代方法
        if is_mplane:
            print("\n⚠ 检测到 Multiplanar 设备，v4l2-ctl 可能无法工作")
            print("尝试使用替代方法...")
            
            # 方法 1: 尝试 ffmpeg
            if subprocess.run(["which", "ffmpeg"], capture_output=True).returncode == 0:
                print("\n尝试方法: ffmpeg")
                ffmpeg_result = subprocess.run(
                    ["ffmpeg", "-f", "v4l2", "-input_format", "uyvy422", 
                     "-video_size", "800x600", "-i", dev_str, 
                     "-frames:v", "1", "-y", test_image],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if Path(test_image).exists() and Path(test_image).stat().st_size > 0:
                    size = Path(test_image).stat().st_size
                    print(f"✓ ffmpeg 拍照成功! 文件大小: {size} 字节")
                    print(f"  文件保存在: {test_image}")
                    continue  # 跳过其他设备测试
                else:
                    print("✗ ffmpeg 拍照失败")
                    if ffmpeg_result.stderr:
                        print("错误输出:")
                        print(ffmpeg_result.stderr[:500])
            
            # 方法 2: 尝试 OpenCV
            try:
                import cv2
                print("\n尝试方法: OpenCV")
                cap = cv2.VideoCapture(dev_str)
                if cap.isOpened():
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 800)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 600)
                    # 预热
                    for _ in range(3):
                        cap.read()
                    ret, frame = cap.read()
                    cap.release()
                    
                    if ret and frame is not None:
                        cv2.imwrite(test_image, frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
                        if Path(test_image).exists() and Path(test_image).stat().st_size > 0:
                            size = Path(test_image).stat().st_size
                            print(f"✓ OpenCV 拍照成功! 文件大小: {size} 字节")
                            print(f"  文件保存在: {test_image}")
                            continue  # 跳过其他设备测试
                print("✗ OpenCV 拍照失败")
            except ImportError:
                print("⚠ OpenCV 未安装，跳过")
            except Exception as e:
                print(f"✗ OpenCV 异常: {e}")
        
        # 尝试 v4l2-ctl 方法
        capture_methods = [
            (["--stream-mmap", "--stream-count=1", f"--stream-to={test_image}"], "stream-mmap"),
            (["--stream-to", test_image, "--stream-count=1"], "stream-to"),
            (["--stream-to", test_image], "stream-to (simple)"),
        ]
        
        capture_success = False
        for capture_cmd, desc in capture_methods:
            print(f"\n尝试方法: {desc}")
            try:
                capture_result = subprocess.run(
                    ["v4l2-ctl", "-d", dev_str] + capture_cmd,
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                print(f"返回码: {capture_result.returncode}")
                if capture_result.stderr:
                    print("错误输出:")
                    print(capture_result.stderr)
                
                # 检查文件
                if Path(test_image).exists():
                    size = Path(test_image).stat().st_size
                    if size > 0:
                        print(f"✓ 拍照成功! 文件大小: {size} 字节")
                        print(f"  文件保存在: {test_image}")
                        capture_success = True
                        break
                    else:
                        print(f"✗ 文件大小为 0")
                        Path(test_image).unlink()
                else:
                    print("✗ 文件未创建")
            except subprocess.TimeoutExpired:
                print(f"✗ 命令超时")
            except Exception as e:
                print(f"✗ 异常: {e}")
        
        if not capture_success:
            print("\n❌ 所有拍照方法都失败")
            if is_mplane:
                print("\n建议:")
                print("1. 安装 ffmpeg: sudo apt-get install ffmpeg")
                print("2. 安装 OpenCV: pip3 install opencv-python")
                print("3. 运行: sudo ./test_rkisp_alternative.sh", dev_str)
    
    print("\n" + "="*60)
    print("测试完成")
    print("="*60)
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
