#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BLE Device Server
"""

import sys
import logging
import signal
import time
from pathlib import Path
from threading import Thread

from config_manager import ConfigManager
from state_machine import StateMachine, BLEState, WiFiState, DeviceState
from wifi_manager import WiFiManager
from camera_controller import CameraController
from cloud_uploader import CloudUploader
from ble_gatt_server import BLEGattServer


class BLEDeviceServer:
    """BLE Device Server"""
    
    def __init__(self, config_dir: str = "/var/lib/ble_device"):
        self.config = ConfigManager(config_dir)
        self.state_machine = StateMachine()
        self.wifi_manager = WiFiManager(
            state_callback=self._on_wifi_state_change
        )
        self.camera = CameraController(
            device="/dev/video0",
            save_dir="/tmp/ble_device_captures"
        )
        self.uploader = CloudUploader(
            upload_url=self.config.get_cloud_url()
        )
        
        # BLE GATT Server
        device_info = self.config.get_device_info()
        self.ble_server = BLEGattServer(
            on_wifi_config=self._on_wifi_config,
            on_cloud_config=self._on_cloud_config,
            on_capture=self._on_capture_command,
            device_name=device_info.get("name", "BLE-Device")
        )
        
        # 注册状态变化监听
        self.state_machine.on_ble_state_change(self._on_ble_state_change)
        self.state_machine.on_wifi_state_change(self._on_wifi_state_notify)
        self.state_machine.on_device_state_change(self._on_device_state_change)
        
        # 运行标志
        self.running = False
    
    def start(self):
        try:
            logger.info("=" * 60)
            logger.info("BLE Device Server 启动中...")
            logger.info("=" * 60)
            
            self.running = True
            
            self._init_wifi()
            
            self.state_machine.set_ble_state(BLEState.ADVERTISING)
            
            logger.info("启动 BLE GATT Server...")
            self.ble_server.run()
            
        except Exception as e:
            logger.error(f"服务启动失败: {e}", exc_info=True)
            self.stop()
    
    def stop(self):
        if not self.running:
            return
        
        logger.info("=" * 60)
        logger.info("BLE Device Server 停止中...")
        logger.info("=" * 60)
        
        self.running = False
        
        try:
            self.wifi_manager.stop_monitoring()
            self.ble_server.stop()
        except Exception as e:
            logger.error(f"停止服务异常: {e}")
        
        logger.info("BLE Device Server 已停止")
    
    # ==================== BLE 回调处理 ====================
    
    def _on_wifi_config(self, ssid: str, password: str):
        logger.info(f"收到 WiFi 配置请求: SSID={ssid}")
        try:
            # 保存配置
            if not self.config.set_wifi_config(ssid, password):
                raise Exception("WiFi 配置保存失败")
            
            # 连接 WiFi（异步）
            Thread(target=self._connect_wifi, args=(ssid, password), daemon=True).start()
            
        except Exception as e:
            logger.error(f"WiFi 配置处理失败: {e}")
            self._notify_error("wifi_config_failed", str(e))
    
    def _on_cloud_config(self, upload_url: str):
        """处理云端配置"""
        logger.info(f"收到云端配置请求: URL={upload_url}")
        
        try:
            # 保存配置
            if not self.config.set_cloud_url(upload_url):
                raise Exception("云端 URL 保存失败")
            
            # 更新上传器配置
            if not self.uploader.set_upload_url(upload_url):
                raise Exception("上传器配置更新失败")
            
            # 测试连接（异步）
            Thread(target=self._test_cloud_connection, daemon=True).start()
            
            # 通知成功
            self._notify_status({
                "event": "cloud_config_success",
                "upload_url": upload_url
            })
            
        except Exception as e:
            logger.error(f"云端配置处理失败: {e}")
            self._notify_error("cloud_config_failed", str(e))
    
    def _on_capture_command(self):
        logger.info("收到拍照指令")
        
        # 检查是否可以拍照
        if not self.state_machine.is_ready_for_capture():
            logger.warning("设备未就绪，无法拍照")
            self._notify_error(
                "capture_not_ready",
                f"WiFi: {self.state_machine.wifi_state.value}, "
                f"Device: {self.state_machine.device_state.value}"
            )
            return
        
        # 异步执行拍照
        Thread(target=self._do_capture, daemon=True).start()
    
    # ==================== 状态变化回调 ====================
    
    def _on_ble_state_change(self, old_state, new_state):
        logger.info(f"BLE 状态: {old_state.value} -> {new_state.value}")
        self._notify_status({"ble_state": new_state.value})
    
    def _on_wifi_state_change(self, new_state: WiFiState):
        self.state_machine.set_wifi_state(new_state)
    
    def _on_wifi_state_notify(self, old_state, new_state):
        logger.info(f"WiFi 状态: {old_state.value} -> {new_state.value}")
        
        status = {
            "wifi_state": new_state.value,
        }
        
        # 如果已连接，添加 IP 信息
        if new_state == WiFiState.CONNECTED:
            wifi_status = self.wifi_manager.get_status()
            status["wifi_ssid"] = wifi_status.get("ssid", "")
            status["wifi_ip"] = wifi_status.get("ip", "")
        
        self._notify_status(status)
    
    def _on_device_state_change(self, old_state, new_state):
        logger.info(f"设备状态: {old_state.value} -> {new_state.value}")
        self._notify_status({"device_state": new_state.value})
    
    # ==================== 内部方法 ====================
    
    def _init_wifi(self):
        """初始化 WiFi（开机自动连接）"""
        wifi_config = self.config.get_wifi_config()
        ssid = wifi_config.get("ssid", "")
        password = wifi_config.get("password", "")
        
        if ssid and password:
            logger.info(f"检测到已保存的 WiFi 配置: {ssid}")
            Thread(target=self._connect_wifi, args=(ssid, password), daemon=True).start()
        else:
            logger.info("未检测到 WiFi 配置")
            self.state_machine.set_wifi_state(WiFiState.UNCONFIGURED)
    
    def _connect_wifi(self, ssid: str, password: str):
        try:
            success = self.wifi_manager.connect(ssid, password)
            
            if success:
                logger.info(f"WiFi 连接成功: {ssid}")
            else:
                logger.error(f"WiFi 连接失败: {ssid}")
                
        except Exception as e:
            logger.error(f"WiFi 连接异常: {e}")
    
    def _test_cloud_connection(self):
        try:
            if self.uploader.test_connection():
                logger.info("云端连接测试成功")
                self._notify_status({"event": "cloud_test_success"})
            else:
                logger.warning("云端连接测试失败")
                self._notify_error("cloud_test_failed", "无法连接到云端服务器")
        except Exception as e:
            logger.error(f"云端连接测试异常: {e}")
    
    def _do_capture(self):
        try:
            # 设置状态为拍照中
            self.state_machine.set_device_state(DeviceState.CAPTURING)
            
            # 通知开始拍照
            self._notify_status({"event": "capture_start"})
            
            # 拍照
            photo_path = self.camera.capture()
            if not photo_path:
                raise Exception("拍照失败")
            
            logger.info(f"拍照成功: {photo_path}")
            
            # 通知拍照完成
            self._notify_status({
                "event": "capture_success",
                "file": Path(photo_path).name
            })
            
            # 设置状态为上传中
            self.state_machine.set_device_state(DeviceState.UPLOADING)
            
            # 通知开始上传
            self._notify_status({"event": "upload_start"})
            
            # 上传到云端
            device_info = self.config.get_device_info()
            metadata = {
                "device_name": device_info.get("name", ""),
                "device_version": device_info.get("version", ""),
                "timestamp": time.time()
            }
            
            upload_success = self.uploader.upload(photo_path, metadata=metadata)
            
            if upload_success:
                logger.info("上传成功")
                self._notify_status({"event": "upload_success"})
            else:
                raise Exception("上传失败")
            
        except Exception as e:
            logger.error(f"拍照/上传失败: {e}")
            self.state_machine.set_device_state(DeviceState.ERROR)
            self._notify_error("capture_upload_failed", str(e))
        
        finally:
            # 恢复空闲状态
            if self.state_machine.device_state != DeviceState.ERROR:
                self.state_machine.set_device_state(DeviceState.IDLE)
    
    def _notify_status(self, status_dict: dict):
        try:
            # 合并完整状态
            full_status = self.state_machine.get_status_dict()
            full_status.update(status_dict)
            full_status["timestamp"] = time.time()
            
            # 通过 BLE 发送
            self.ble_server.notify_status(full_status)
            
        except Exception as e:
            logger.error(f"发送状态通知失败: {e}")
    
    def _notify_error(self, error_code: str, error_message: str):
        self._notify_status({
            "event": "error",
            "error_code": error_code,
            "error_message": error_message
        })


def setup_logging(log_file: str = "/var/log/ble_device.log"):
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    
    # 同时输出到文件和控制台
    handlers = [
        logging.StreamHandler(sys.stdout)
    ]
    
    # 尝试写入日志文件
    try:
        Path(log_file).parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file))
    except Exception as e:
        print(f"警告: 无法创建日志文件 {log_file}: {e}")
    
    logging.basicConfig(
        level=logging.INFO,
        format=log_format,
        handlers=handlers
    )


def signal_handler(sig, frame):
    logger.info(f"收到信号 {sig}")
    if hasattr(signal_handler, 'server'):
        signal_handler.server.stop()
    sys.exit(0)


def main():
    # 配置日志
    setup_logging()
    
    # 创建服务器
    server = BLEDeviceServer()
    
    # 设置信号处理
    signal_handler.server = server
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 启动服务
    try:
        server.start()
    except Exception as e:
        logger.error(f"服务运行异常: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    # 获取 logger
    logger = logging.getLogger(__name__)
    
    # 运行主程序
    main()
