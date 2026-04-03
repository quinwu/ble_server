#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class CameraController:
    """摄像头控制器 - 使用 fswebcam 或 v4l2 进行图像采集"""

    def __init__(self, device: str = "/dev/video0", save_dir: str = "/tmp/captures"):
        self.device = device
        self.save_dir = Path(save_dir)
        self.save_dir.mkdir(parents=True, exist_ok=True)

        # 检测可用的拍照工具
        self.capture_tool = self._detect_capture_tool()
        logger.info(f"使用拍照工具: {self.capture_tool}")

    def capture(self, filename: Optional[str] = None) -> Optional[str]:
        """
        拍摄一张照片

        Args:
            filename: 文件名（可选，默认使用时间戳）

        Returns:
            str: 图片文件路径，失败返回 None
        """
        try:
            # 生成文件名
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"capture_{timestamp}.jpg"

            filepath = self.save_dir / filename

            logger.info(f"开始拍照: {filepath}")

            # 根据工具选择拍照方法
            if self.capture_tool == "fswebcam":
                success = self._capture_with_fswebcam(filepath)
            elif self.capture_tool == "v4l2":
                success = self._capture_with_v4l2(filepath)
            elif self.capture_tool == "opencv":
                success = self._capture_with_opencv(filepath)
            else:
                logger.error("未找到可用的拍照工具")
                return None

            if success and filepath.exists():
                logger.info(f"拍照成功: {filepath} ({filepath.stat().st_size} bytes)")
                return str(filepath)
            else:
                logger.error("拍照失败")
                return None

        except Exception as e:
            logger.error(f"拍照异常: {e}", exc_info=True)
            return None

    def test_camera(self) -> bool:
        """测试摄像头是否可用"""
        try:
            # 尝试拍摄一张测试图片
            test_file = self.capture("test.jpg")
            if test_file:
                Path(test_file).unlink(missing_ok=True)  # 删除测试文件
                logger.info("摄像头测试成功")
                return True
            else:
                logger.warning("摄像头测试失败")
                return False
        except Exception as e:
            logger.error(f"摄像头测试异常: {e}")
            return False

    # ==================== 内部方法 ====================

    def _detect_capture_tool(self) -> str:
        """检测可用的拍照工具"""
        # 检查 fswebcam
        if self._command_exists("fswebcam"):
            return "fswebcam"

        # 检查 v4l2-ctl
        if self._command_exists("v4l2-ctl"):
            return "v4l2"

        # 检查 OpenCV (通过 Python import)
        try:
            import cv2

            return "opencv"
        except ImportError:
            pass

        logger.warning("未找到任何拍照工具，请安装: fswebcam, v4l-utils 或 opencv-python")
        return "none"

    def _command_exists(self, command: str) -> bool:
        """检查命令是否存在"""
        try:
            result = subprocess.run(["which", command], capture_output=True, timeout=2)
            return result.returncode == 0
        except Exception:
            return False

    def _capture_with_fswebcam(self, filepath: Path) -> bool:
        """使用 fswebcam 拍照"""
        try:
            result = subprocess.run(
                [
                    "fswebcam",
                    "-d",
                    self.device,
                    "-r",
                    "1280x720",  # 分辨率
                    "--no-banner",  # 不添加水印
                    "--jpeg",
                    "95",  # JPEG 质量
                    "-F",
                    "5",  # 跳过前 5 帧（预热）
                    str(filepath),
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )

            if result.returncode != 0:
                logger.error(f"fswebcam 错误: {result.stderr}")
                return False

            return True

        except subprocess.TimeoutExpired:
            logger.error("fswebcam 拍照超时")
            return False
        except Exception as e:
            logger.error(f"fswebcam 拍照异常: {e}")
            return False

    def _capture_with_v4l2(self, filepath: Path) -> bool:
        """使用 v4l2-ctl 拍照，支持多种方法"""
        try:
            # 解析实际设备路径（如果是符号链接）
            actual_device = self._resolve_device_path(self.device)

            # 尝试设置格式（优先使用 MJPG，因为它是压缩格式）
            # 如果设备已经设置了合适的格式，这一步可能会失败，但不影响后续拍照
            format_set = False
            for pixelformat in ["MJPG", "YUYV"]:
                fmt_result = subprocess.run(
                    [
                        "v4l2-ctl",
                        "-d",
                        actual_device,
                        f"--set-fmt-video=width=1280,height=720,pixelformat={pixelformat}",
                    ],
                    capture_output=True,
                    timeout=5,
                )

                if fmt_result.returncode == 0:
                    logger.debug(f"格式设置成功: {pixelformat}")
                    format_set = True
                    break

            if not format_set:
                logger.debug("格式设置失败或已设置，继续尝试拍照")

            # 尝试多种 v4l2-ctl 拍照方法
            capture_methods = [
                (["--stream-mmap", "--stream-count=1", f"--stream-to={filepath}"], "stream-mmap"),
                (["--stream-to", str(filepath), "--stream-count=1"], "stream-to"),
                (["--stream-to", str(filepath)], "stream-to-simple"),
            ]

            for capture_cmd, method_name in capture_methods:
                logger.debug(f"尝试 v4l2-ctl 方法: {method_name}")
                result = subprocess.run(
                    ["v4l2-ctl", "-d", actual_device] + capture_cmd, capture_output=True, text=True, timeout=15
                )

                # 检查文件是否创建且大小大于0
                if filepath.exists():
                    size = filepath.stat().st_size
                    if size > 0:
                        logger.debug(f"v4l2-ctl {method_name} 拍照成功: {size} bytes")
                        # 检查文件格式，如果是原始格式需要转换
                        return self._convert_if_needed(filepath)
                    else:
                        logger.debug(f"v4l2-ctl {method_name} 文件大小为0")
                        filepath.unlink(missing_ok=True)
                elif result.returncode != 0:
                    logger.debug(f"v4l2-ctl {method_name} 失败: {result.stderr[:100] if result.stderr else '未知错误'}")

            logger.error("所有 v4l2-ctl 方法都失败")
            return False

        except subprocess.TimeoutExpired:
            logger.error("v4l2-ctl 拍照超时")
            return False
        except Exception as e:
            logger.error(f"v4l2-ctl 拍照异常: {e}", exc_info=True)
            return False

    def _resolve_device_path(self, device: str) -> str:
        """解析设备路径（如果是符号链接，返回实际路径）"""
        try:
            dev_path = Path(device)
            if dev_path.is_symlink():
                resolved = dev_path.resolve()
                logger.debug(f"设备 {device} 是符号链接，实际路径: {resolved}")
                return str(resolved)
        except Exception as e:
            logger.debug(f"解析设备路径失败: {e}")
        return device

    def _convert_if_needed(self, filepath: Path) -> bool:
        """如果文件是原始格式（如 YUYV），转换为 JPEG"""
        try:
            # 先检查文件头，确认是否为 JPEG
            with open(filepath, "rb") as f:
                header = f.read(2)
                if header == b"\xff\xd8":  # JPEG 文件头
                    logger.debug("文件已经是 JPEG 格式")
                    return True

            # 如果不是 JPEG，检查文件大小判断是否为原始格式
            size = filepath.stat().st_size
            expected_raw_size = 1280 * 720 * 2  # YUYV 格式大小 (1280*720*2 bytes)

            # 如果文件大小接近原始格式大小，尝试转换
            if size > expected_raw_size * 0.9 and size < expected_raw_size * 1.1:
                logger.debug("检测到可能是原始格式 (YUYV)，尝试转换为 JPEG")
                # 使用 ffmpeg 转换
                if self._command_exists("ffmpeg"):
                    temp_file = filepath.with_suffix(".tmp.jpg")
                    result = subprocess.run(
                        [
                            "ffmpeg",
                            "-f",
                            "rawvideo",
                            "-pixel_format",
                            "yuyv422",
                            "-video_size",
                            "1280x720",
                            "-i",
                            str(filepath),
                            "-y",
                            str(temp_file),
                        ],
                        capture_output=True,
                        timeout=10,
                    )

                    if result.returncode == 0 and temp_file.exists() and temp_file.stat().st_size > 0:
                        filepath.unlink()
                        temp_file.rename(filepath)
                        logger.debug("原始格式转换成功")
                        return True
                    else:
                        logger.warning("格式转换失败，使用原文件")
                        if result.stderr:
                            logger.debug(f"ffmpeg 错误: {result.stderr[:200]}")

            logger.warning(f"文件不是 JPEG 格式且无法转换，文件大小: {size} bytes")
            return True  # 即使转换失败，也返回 True（文件已创建）

        except Exception as e:
            logger.debug(f"格式检查/转换异常: {e}")
            return True  # 即使转换失败，也返回 True（文件已创建）

    def _capture_with_opencv(self, filepath: Path) -> bool:
        """使用 OpenCV 拍照"""
        try:
            import cv2

            # 打开摄像头
            cap = cv2.VideoCapture(self.device)
            if not cap.isOpened():
                logger.error("无法打开摄像头")
                return False

            # 预热（读取并丢弃前几帧）
            for _ in range(5):
                cap.read()

            # 拍照
            ret, frame = cap.read()
            cap.release()

            if not ret:
                logger.error("读取图像失败")
                return False

            # 保存图像
            cv2.imwrite(str(filepath), frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
            return True

        except Exception as e:
            logger.error(f"OpenCV 拍照异常: {e}")
            return False


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    camera = CameraController(device="/dev/video51")

    # 测试摄像头
    if camera.test_camera():
        print("摄像头可用")

        # 拍照测试
        photo = camera.capture()
        if photo:
            print(f"拍照成功: {photo}")
        else:
            print("拍照失败")
    else:
        print("摄像头不可用")
