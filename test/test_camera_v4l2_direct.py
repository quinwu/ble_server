#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
直接使用 V4L2 API 测试摄像头（适用于 rkisp Multiplanar 设备）
使用 v4l2-python3 库直接操作设备
"""

import sys
import os
import struct
import fcntl
import mmap
from pathlib import Path

# 尝试导入 v4l2-python3 库
V4L2_AVAILABLE = False
V4L2_IMPORT_CMD = None

# 先尝试直接导入
try:
    import v4l2
    V4L2_AVAILABLE = True
except ImportError:
    # 如果使用 sudo，检查用户是否安装了库，但不在当前进程中使用
    # 因为无法在 sudo 进程中导入用户安装的库
    sudo_user = os.getenv('SUDO_USER')
    if sudo_user:
        import subprocess
        try:
            # 检查用户是否安装了 v4l2（仅用于提示）
            result = subprocess.run(
                ['sudo', '-u', sudo_user, 'python3', '-c', 'import v4l2'],
                capture_output=True,
                timeout=2
            )
            if result.returncode == 0:
                # 库在用户目录，但当前无法使用
                print("⚠ v4l2-python3 库在用户目录，但当前在 sudo 下运行")
                print("  建议:")
                print(f"    1. 不使用 sudo 运行: python3 test_camera_v4l2_direct.py {sys.argv[1] if len(sys.argv) > 1 else '<设备>'}")
                print("    2. 或将用户添加到 video 组: sudo usermod -aG video $USER")
                print("    3. 然后重新登录或运行: newgrp video")
        except:
            pass
    
    if not V4L2_AVAILABLE:
        print("⚠ v4l2-python3 库未安装或无法访问")
        print("  安装: pip3 install v4l2-python3")

# V4L2 常量定义
V4L2_BUF_TYPE_VIDEO_CAPTURE = 1
V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE = 9
V4L2_MEMORY_MMAP = 1
V4L2_MEMORY_USERPTR = 2
V4L2_PIX_FMT_UYVY = ord('U') | (ord('Y') << 8) | (ord('V') << 16) | (ord('Y') << 24)

# ioctl 定义
VIDIOC_QUERYCAP = 0x80685600
VIDIOC_S_FMT = 0x402C2D0C
VIDIOC_G_FMT = 0xC0CC2D04
VIDIOC_REQBUFS = 0x40085640
VIDIOC_QUERYBUF = 0xC0445601
VIDIOC_QBUF = 0x4008560F
VIDIOC_DQBUF = 0xC0445611
VIDIOC_STREAMON = 0x40045612
VIDIOC_STREAMOFF = 0x40045613

def capture_with_v4l2_library(device, output_file):
    """使用 v4l2-python3 库捕获图像"""
    print("使用 v4l2-python3 库捕获图像...")
    
    # 确保 v4l2 已导入
    try:
        import v4l2
    except ImportError:
        raise ImportError("v4l2 模块无法导入，请确保库已正确安装")
    
    fd = os.open(device, os.O_RDWR | os.O_NONBLOCK)
    
    try:
        # 设置格式
        fmt = v4l2.v4l2_format()
        fmt.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
        fmt.fmt.pix_mp.width = 800
        fmt.fmt.pix_mp.height = 600
        fmt.fmt.pix_mp.pixelformat = v4l2.V4L2_PIX_FMT_UYVY
        fmt.fmt.pix_mp.num_planes = 1
        fmt.fmt.pix_mp.field = v4l2.V4L2_FIELD_NONE
        fmt.fmt.pix_mp.colorspace = v4l2.V4L2_COLORSPACE_SRGB
        
        fcntl.ioctl(fd, v4l2.VIDIOC_S_FMT, fmt)
        print("✓ 格式设置成功")
        print(f"  实际格式: {fmt.fmt.pix_mp.width}x{fmt.fmt.pix_mp.height}, "
              f"planes: {fmt.fmt.pix_mp.num_planes}, "
              f"pixelformat: {hex(fmt.fmt.pix_mp.pixelformat)}")
        
        # 请求缓冲区
        req = v4l2.v4l2_requestbuffers()
        req.count = 4
        req.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
        req.memory = v4l2.V4L2_MEMORY_MMAP
        
        fcntl.ioctl(fd, v4l2.VIDIOC_REQBUFS, req)
        print(f"✓ 缓冲区请求成功，获得 {req.count} 个缓冲区")
        
        if req.count == 0:
            print("✗ 没有可用的缓冲区")
            return False
        
        # 映射缓冲区
        buffers = []
        num_planes = fmt.fmt.pix_mp.num_planes
        
        for i in range(req.count):
            querybuf = v4l2.v4l2_buffer()
            querybuf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
            querybuf.memory = v4l2.V4L2_MEMORY_MMAP
            querybuf.index = i
            
            # 对于 Multiplanar，需要创建 planes 数组
            # 使用 ctypes 数组来创建正确大小的 planes 数组
            import ctypes
            plane_array = (v4l2.v4l2_plane * num_planes)()
            querybuf.m.planes = plane_array
            querybuf.length = num_planes  # 设置 planes 数组长度
            
            try:
                fcntl.ioctl(fd, v4l2.VIDIOC_QUERYBUF, querybuf)
            except OSError as e:
                print(f"✗ 查询缓冲区 {i} 失败: {e}")
                # 尝试使用单个 plane（对于 UYVY，虽然是 Multiplanar 设备，但可能只有一个 plane）
                if num_planes > 1:
                    print(f"  尝试使用单个 plane...")
                    querybuf.length = 1
                    plane_array = (v4l2.v4l2_plane * 1)()
                    querybuf.m.planes = plane_array
                    try:
                        fcntl.ioctl(fd, v4l2.VIDIOC_QUERYBUF, querybuf)
                    except OSError as e2:
                        print(f"  ✗ 单 plane 查询也失败: {e2}")
                        raise
                else:
                    raise
            
            # 获取第一个 plane 的信息
            plane = querybuf.m.planes[0]
            length = plane.length
            offset = plane.m.mem_offset
            
            try:
                buffer_mmap = mmap.mmap(fd, length, mmap.MAP_SHARED, mmap.PROT_READ | mmap.PROT_WRITE, offset=offset)
                buffers.append((buffer_mmap, length, i))
                print(f"✓ 缓冲区 {i} 映射成功，大小: {length} 字节，偏移: {offset}")
            except Exception as e:
                print(f"✗ 映射缓冲区 {i} 失败: {e}")
                raise
        
        # 将所有缓冲区入队
        import ctypes
        for i in range(req.count):
            buf = v4l2.v4l2_buffer()
            buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
            buf.memory = v4l2.V4L2_MEMORY_MMAP
            buf.index = i
            
            # 创建 planes 数组
            plane_array = (v4l2.v4l2_plane * num_planes)()
            buf.m.planes = plane_array
            buf.length = num_planes
            
            try:
                fcntl.ioctl(fd, v4l2.VIDIOC_QBUF, buf)
                print(f"✓ 缓冲区 {i} 已入队")
            except OSError as e:
                print(f"✗ 缓冲区 {i} 入队失败: {e}")
                raise
        
        print("✓ 所有缓冲区已入队")
        
        # 检查设备是否被占用
        import subprocess
        try:
            result = subprocess.run(['lsof', device], capture_output=True, text=True, timeout=2)
            if result.returncode == 0 and result.stdout:
                print(f"⚠ 设备可能被占用: {result.stdout.strip()}")
        except:
            pass
        
        # 检查设备能力
        print("")
        print("检查设备能力...")
        try:
            cap = v4l2.v4l2_capability()
            fcntl.ioctl(fd, v4l2.VIDIOC_QUERYCAP, cap)
            print(f"  驱动: {cap.driver.decode('utf-8', errors='ignore').strip()}")
            print(f"  卡: {cap.card.decode('utf-8', errors='ignore').strip()}")
            print(f"  总线: {cap.bus_info.decode('utf-8', errors='ignore').strip()}")
            print(f"  能力: {hex(cap.capabilities)}")
            if cap.capabilities & v4l2.V4L2_CAP_VIDEO_CAPTURE:
                print("  ✓ 支持视频捕获")
            if cap.capabilities & v4l2.V4L2_CAP_STREAMING:
                print("  ✓ 支持流式传输")
            if cap.capabilities & v4l2.V4L2_CAP_VIDEO_CAPTURE_MPLANE:
                print("  ✓ 支持 Multiplanar 捕获")
        except Exception as e:
            print(f"  ⚠ 查询设备能力失败: {e}")
        
        # 检查 media 框架（对于 rkisp 设备可能需要）
        print("")
        print("检查 media 框架状态...")
        rkisp_media_devices = []
        try:
            # 查找相关的 media 设备
            media_devices = list(Path("/dev").glob("media*"))
            if media_devices:
                print(f"  找到 {len(media_devices)} 个 media 设备")
                for med in media_devices[:5]:  # 检查前5个
                    try:
                        result = subprocess.run(
                            ['media-ctl', '-d', str(med), '-p'],
                            capture_output=True,
                            text=True,
                            timeout=2
                        )
                        if 'rkisp' in result.stdout.lower():
                            print(f"  ✓ 找到 rkisp media 设备: {med}")
                            rkisp_media_devices.append(med)
                            # 打印拓扑信息
                            print(f"    拓扑信息:")
                            for line in result.stdout.split('\n')[:10]:  # 只显示前10行
                                if line.strip():
                                    print(f"      {line}")
                    except FileNotFoundError:
                        print("  ⚠ media-ctl 未安装，无法检查 media 框架")
                        break
                    except:
                        pass
        except:
            pass
        
        # 尝试配置 media 框架链路（如果找到 rkisp media 设备）
        if rkisp_media_devices:
            print("")
            print("尝试配置 media 框架链路...")
            for med in rkisp_media_devices[:1]:  # 只尝试第一个
                try:
                    # 尝试获取链路信息
                    result = subprocess.run(
                        ['media-ctl', '-d', str(med), '-l'],
                        capture_output=True,
                        text=True,
                        timeout=2
                    )
                    if result.returncode == 0:
                        print(f"  当前链路状态 ({med}):")
                        for line in result.stdout.split('\n')[:5]:
                            if line.strip():
                                print(f"    {line}")
                    
                    # 尝试查找并启用链路（如果链路存在但未启用）
                    # 注意：这需要根据实际的硬件配置来调整
                    # 通常 rkisp 设备的链路格式是: "rkisp-isp-subdev:0 -> rkisp-vir0:0"
                    # 但这里我们只尝试查询，不强制设置
                    
                except Exception as e:
                    print(f"  ⚠ 配置 media 框架失败: {e}")
        
        # 在启动流之前，再次查询格式以确保设备状态正确
        print("")
        print("验证设备格式状态...")
        try:
            verify_fmt = v4l2.v4l2_format()
            verify_fmt.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
            fcntl.ioctl(fd, v4l2.VIDIOC_G_FMT, verify_fmt)
            print(f"  当前格式: {verify_fmt.fmt.pix_mp.width}x{verify_fmt.fmt.pix_mp.height}, "
                  f"pixelformat: {hex(verify_fmt.fmt.pix_mp.pixelformat)}, "
                  f"planes: {verify_fmt.fmt.pix_mp.num_planes}")
            if verify_fmt.fmt.pix_mp.width == 0 or verify_fmt.fmt.pix_mp.height == 0:
                print("  ⚠ 警告: 格式宽度或高度为 0，设备可能未正确初始化")
        except Exception as e:
            print(f"  ⚠ 查询格式失败: {e}")
        
         # 启动流
        # VIDIOC_STREAMON 需要一个指向缓冲区类型的指针
        # 在 Python 中，fcntl.ioctl 可以直接接受 ctypes 对象
        buf_type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
        # 创建一个可写的 c_uint32 对象（fcntl 会自动处理为指针）
        buf_type_val = ctypes.c_uint32(buf_type)
        
        print("")
        print("尝试启动流...")
        print(f"  缓冲区类型: {buf_type} (V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE)")
        print(f"  已入队缓冲区数量: {req.count}")
        print(f"  Planes 数量: {num_planes}")
        
        try:
            # 尝试启动流
            fcntl.ioctl(fd, v4l2.VIDIOC_STREAMON, buf_type_val)
            print("✓ 流已启动")
        except (OSError, TypeError) as e:
            print(f"✗ 启动流失败: {e}")
            if isinstance(e, OSError):
                print(f"  错误码: {e.errno} ({os.strerror(e.errno)})")
            print("")
            print("  可能的原因:")
            print("    1. rkisp 设备需要先配置 media 框架")
            print("    2. 设备驱动问题或设备未准备好")
            print("    3. 设备已被其他进程占用")
            print("    4. Multiplanar 设备需要特殊的初始化顺序")
            print("")
            print("  建议:")
            print("    1. 检查 media 框架: media-ctl -d /dev/media0 -p")
            print("    2. 尝试使用 OpenCV（如果支持 V4L2）")
            print("    3. 检查设备驱动: dmesg | grep rkisp")
            print("    4. 重启设备或重新加载驱动")
            print("")
            print("  注意: rkisp Multiplanar 设备可能需要:")
            print("    - 先配置 media 框架链路")
            print("    - 确保传感器已初始化")
            print("    - 检查设备是否在正确的状态")
            print("")
            print("  调试信息:")
            print(f"    - 缓冲区类型: {buf_type} (V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE)")
            print(f"    - 缓冲区数量: {req.count}")
            print(f"    - Planes 数量: {num_planes}")
            print(f"    - 设备: {device}")
            print("")
            print("  尝试回退到基础方法...")
            return False  # 返回 False 而不是 raise，让脚本尝试基础方法
        
        # 从队列中取出一个缓冲区（捕获一帧）
        print("等待捕获图像...")
        buf = v4l2.v4l2_buffer()
        buf.type = v4l2.V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE
        buf.memory = v4l2.V4L2_MEMORY_MMAP
        
        # 创建 planes 数组
        import ctypes
        plane_array = (v4l2.v4l2_plane * num_planes)()
        buf.m.planes = plane_array
        buf.length = num_planes
        
        # 使用 select 等待数据就绪（非阻塞模式）
        import select
        while True:
            try:
                fcntl.ioctl(fd, v4l2.VIDIOC_DQBUF, buf)
                break
            except OSError as e:
                if e.errno == 11:  # EAGAIN
                    select.select([fd], [], [])
                    continue
                else:
                    raise
        
        buf_index = buf.index
        bytesused = buf.m.planes[0].bytesused
        print(f"✓ 捕获到图像，缓冲区索引: {buf_index}, 长度: {bytesused} 字节")
        
        # 读取图像数据
        buffer_mmap, length, _ = buffers[buf_index]
        # 只读取实际使用的字节数
        image_data = buffer_mmap[:bytesused] if bytesused > 0 else buffer_mmap[:length]
        
        # 保存原始 UYVY 文件
        raw_output = output_file.replace('.jpg', '.uyvy')
        with open(raw_output, 'wb') as f:
            f.write(image_data)
        
        print(f"✓ 原始图像已保存: {raw_output} ({len(image_data)} 字节)")
        
        # 将缓冲区重新入队（使用相同的 buf 结构）
        # 重置 planes 数组
        plane_array = (v4l2.v4l2_plane * num_planes)()
        buf.m.planes = plane_array
        buf.length = num_planes
        fcntl.ioctl(fd, v4l2.VIDIOC_QBUF, buf)
        
        # 停止流
        # VIDIOC_STREAMOFF 也需要一个指向缓冲区类型的指针
        buf_type_val = ctypes.c_uint32(buf_type)
        fcntl.ioctl(fd, v4l2.VIDIOC_STREAMOFF, buf_type_val)
        print("✓ 流已停止")
        
        # 清理
        for buffer_mmap, _ in buffers:
            buffer_mmap.close()
        
        # 尝试转换为 JPEG
        print("")
        print("尝试转换为 JPEG...")
        import subprocess
        result = subprocess.run(
            ["ffmpeg", "-f", "rawvideo", "-pixel_format", "uyvy422", 
             "-video_size", "800x600", "-i", raw_output, "-y", output_file],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode == 0 and Path(output_file).exists():
            size = Path(output_file).stat().st_size
            print(f"✓✓✓ JPEG 转换成功! ✓✓✓")
            print(f"文件: {output_file}")
            print(f"大小: {size} 字节")
            return True
        else:
            print(f"⚠ JPEG 转换失败: {result.stderr}")
            print(f"原始 UYVY 文件已保存: {raw_output}")
            return False
        
    finally:
        os.close(fd)

def main():
    if len(sys.argv) < 2:
        print("用法: python3 test_camera_v4l2_direct.py <设备路径> [输出文件]")
        sys.exit(1)
    
    device = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else "/tmp/camera_v4l2_direct_test.jpg"
    
    print(f"设备: {device}")
    print(f"输出: {output_file}")
    print("")
    
    # 检查设备
    if not Path(device).exists():
        print(f"✗ 设备不存在: {device}")
        sys.exit(1)
    
    # 如果 v4l2-python3 可用，使用它
    if V4L2_AVAILABLE:
        try:
            result = capture_with_v4l2_library(device, output_file)
            if result is True:
                print("")
                print("✓✓✓ 图像捕获成功! ✓✓✓")
                sys.exit(0)
            elif result is False:
                # 捕获失败，但已显示错误信息，继续尝试基础方法
                print("")
                print("v4l2-python3 库方法失败，尝试基础方法...")
                print("")
            else:
                print("")
                print("⚠ 捕获了原始图像，但 JPEG 转换失败")
                sys.exit(1)
        except ImportError as e:
            print(f"✗ v4l2-python3 库无法导入: {e}")
            sudo_user = os.getenv('SUDO_USER')
            if sudo_user:
                print("")
                print("⚠ 在 sudo 下无法导入用户安装的库")
                print("  建议不使用 sudo 运行，或将用户添加到 video 组")
                print("")
            print("尝试使用基础方法...")
            print("")
        except Exception as e:
            print(f"✗ v4l2-python3 库捕获失败: {e}")
            import traceback
            traceback.print_exc()
            print("")
            print("尝试使用基础方法...")
            print("")
    else:
        print("")
        print("⚠ v4l2-python3 库不可用，使用基础方法")
        print("  提示: 如果库已安装在用户目录，请尝试:")
        print(f"    python3 test_camera_v4l2_direct.py {device}")
        print("  或确保有设备访问权限（将用户添加到 video 组）")
        print("")
    
    # 基础方法（使用 v4l2-ctl）
    try:
        # 打开设备
        print("打开设备...")
        fd = os.open(device, os.O_RDWR | os.O_NONBLOCK)
        print("✓ 设备已打开")
        
        # 查询设备能力
        print("查询设备能力...")
        cap = struct.pack('I', 0) * 16  # v4l2_capability 结构
        try:
            fcntl.ioctl(fd, VIDIOC_QUERYCAP, cap)
            print("✓ 设备能力查询成功")
        except Exception as e:
            print(f"⚠ 设备能力查询失败: {e}")
        
        # 设置格式
        # 对于 Multiplanar 设备，使用 v4l2_pix_format_mplane 结构
        # 结构: type(4) + fmt.pix_mp.width(4) + fmt.pix_mp.height(4) + fmt.pix_mp.pixelformat(4) + 
        #       fmt.pix_mp.field(4) + fmt.pix_mp.colorspace(4) + fmt.pix_mp.num_planes(4) + 
        #       fmt.pix_mp.flags(4) + fmt.pix_mp.ycbcr_enc(1) + fmt.pix_mp.quantization(1) + 
        #       fmt.pix_mp.xfer_func(1) + reserved(1) + planes[8*4] + reserved2[4*4]
        print("设置格式: UYVY 800x600 (Multiplanar)...")
        
        # v4l2_format 结构体（Multiplanar）
        # type(4) + fmt.pix_mp结构
        # pix_mp: width(4) + height(4) + pixelformat(4) + field(4) + colorspace(4) + 
        #         num_planes(4) + flags(4) + ycbcr_enc(1) + quantization(1) + xfer_func(1) + reserved(1) +
        #         plane_fmt[8个plane，每个16字节] + reserved2[4*4]
        
        # 简化版本：只设置基本字段
        # type(4) + width(4) + height(4) + pixelformat(4) + field(4) + colorspace(4) + 
        # num_planes(4) + flags(4) + ycbcr_enc(1) + quantization(1) + xfer_func(1) + reserved(1)
        fmt = struct.pack('IIIIIIIIBBBB', 
                          V4L2_BUF_TYPE_VIDEO_CAPTURE_MPLANE,  # type (4 bytes)
                          800,                                  # width (4 bytes)
                          600,                                  # height (4 bytes)
                          V4L2_PIX_FMT_UYVY,                   # pixelformat (4 bytes)
                          0,                                    # field (4 bytes)
                          0,                                    # colorspace (4 bytes)
                          1,                                    # num_planes (4 bytes) - UYVY 是单平面
                          0,                                    # flags (4 bytes)
                          0,                                    # ycbcr_enc (1 byte)
                          0,                                    # quantization (1 byte)
                          0,                                    # xfer_func (1 byte)
                          0)                                    # reserved (1 byte)
        
        # 然后需要添加 plane_fmt 数组（8个plane，每个16字节）和 reserved2（16字节）
        # 但为了简化，我们先尝试最小结构
        # 实际上 v4l2_pix_format_mplane 结构更大，需要完整定义
        
        # 使用 v4l2-ctl 设置格式并捕获图像
        import subprocess
        
        print("使用 v4l2-ctl 设置格式...")
        result = subprocess.run(
            ["v4l2-ctl", "-d", device, "--set-fmt-video=width=800,height=600,pixelformat=UYVY"],
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            print("✓ 格式设置成功")
        else:
            print(f"✗ 格式设置失败: {result.stderr}")
            os.close(fd)
            sys.exit(1)
        
        # 尝试请求缓冲区（Multiplanar）
        print("")
        print("请求缓冲区 (Multiplanar)...")
        reqbufs_methods = [
            (["--reqbufs-mplane", "count=4", "type=video", "memory=mmap"], "mplane mmap"),
            (["--reqbufs", "count=4", "type=video", "memory=mmap"], "standard mmap"),
        ]
        
        reqbufs_success = False
        for reqbufs_cmd, desc in reqbufs_methods:
            result = subprocess.run(
                ["v4l2-ctl", "-d", device] + reqbufs_cmd,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                print(f"✓ 缓冲区请求成功 ({desc})")
                reqbufs_success = True
                break
            else:
                print(f"✗ 缓冲区请求失败 ({desc}): {result.stderr.strip()}")
        
        if not reqbufs_success:
            print("⚠ 缓冲区请求失败，但继续尝试捕获...")
        
        # 尝试捕获图像
        print("")
        print("尝试捕获图像...")
        
        # 先保存为原始格式（UYVY）
        raw_output = output_file.replace('.jpg', '.uyvy')
        
        capture_methods = [
            (["--stream-mmap", "--stream-count=1", f"--stream-to={raw_output}"], "stream-mmap"),
            (["--stream-to", raw_output, "--stream-count=1"], "stream-to"),
        ]
        
        capture_success = False
        for capture_cmd, desc in capture_methods:
            print(f"尝试方法: {desc}")
            result = subprocess.run(
                ["v4l2-ctl", "-d", device] + capture_cmd,
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0 and Path(raw_output).exists() and Path(raw_output).stat().st_size > 0:
                size = Path(raw_output).stat().st_size
                print(f"✓ 捕获成功! 文件大小: {size} 字节")
                print(f"  原始文件: {raw_output}")
                capture_success = True
                break
            else:
                if result.stderr:
                    print(f"  错误: {result.stderr.strip()}")
        
        os.close(fd)
        
        if capture_success:
            print("")
            print("✓✓✓ 图像捕获成功! ✓✓✓")
            print(f"原始 UYVY 文件: {raw_output}")
            print("")
            print("注意: UYVY 是原始格式，需要转换为 JPEG")
            print("可以使用以下工具转换：")
            print(f"  - ffmpeg: ffmpeg -f rawvideo -pixel_format uyvy422 -video_size 800x600 -i {raw_output} -y {output_file}")
            print(f"  - ImageMagick: convert -size 800x600 -depth 8 uyvy:{raw_output} {output_file}")
            print("")
            print("或者直接查看原始文件:")
            print(f"  file {raw_output}")
        else:
            print("")
            print("✗ 图像捕获失败")
        print("")
        if not V4L2_AVAILABLE:
            print("建议安装 v4l2-python3 库以获得更好的支持:")
            print("  pip3 install v4l2-python3")
            print("")
        print("注意: 直接使用 V4L2 API 需要更复杂的缓冲区管理")
        print("对于 rkisp Multiplanar 设备，建议：")
        print("1. 使用 v4l2-python3 库（已安装，但可能遇到问题）")
        print("2. 使用 OpenCV（如果支持 V4L2）")
        print("3. 检查设备驱动和权限")
        
    except PermissionError:
        print("✗ 权限不足，请使用 sudo 运行")
        sys.exit(1)
    except Exception as e:
        print(f"✗ 错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
