#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import logging
import time
from pathlib import Path
from typing import Optional
from datetime import datetime

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
            result = subprocess.run(
                ["which", command],
                capture_output=True,
                timeout=2
            )
            return result.returncode == 0
        except Exception:
            return False
    
    def _capture_with_fswebcam(self, filepath: Path) -> bool:
        """使用 fswebcam 拍照"""
        try:
            result = subprocess.run([
                "fswebcam",
                "-d", self.device,
                "-r", "1280x720",      # 分辨率
                "--no-banner",          # 不添加水印
                "--jpeg", "95",         # JPEG 质量
                "-F", "5",              # 跳过前 5 帧（预热）
                str(filepath)
            ], capture_output=True, text=True, timeout=15)
            
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
        """使用 v4l2-ctl 拍照"""
        try:
            # 设置格式
            subprocess.run([
                "v4l2-ctl",
                "-d", self.device,
                "--set-fmt-video=width=1280,height=720,pixelformat=MJPG"
            ], capture_output=True, timeout=5)
            
            # 拍照
            result = subprocess.run([
                "v4l2-ctl",
                "-d", self.device,
                "--stream-mmap",
                "--stream-count=1",
                f"--stream-to={filepath}"
            ], capture_output=True, text=True, timeout=15)
            
            if result.returncode != 0:
                logger.error(f"v4l2-ctl 错误: {result.stderr}")
                return False
            
            return True
            
        except subprocess.TimeoutExpired:
            logger.error("v4l2-ctl 拍照超时")
            return False
        except Exception as e:
            logger.error(f"v4l2-ctl 拍照异常: {e}")
            return False
    
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
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    camera = CameraController()
    
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
