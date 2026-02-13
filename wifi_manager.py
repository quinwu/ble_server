#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import logging
import time
from typing import Optional, Callable
from threading import Thread, Event

from state_machine import WiFiState

logger = logging.getLogger(__name__)


class WiFiManager:
    """WiFi 管理器 - 使用 nmcli (NetworkManager) 进行配网"""
    
    def __init__(self, state_callback: Optional[Callable] = None):
        self.state_callback = state_callback
        self._monitor_thread = None
        self._stop_event = Event()
        
        # 当前连接信息
        self.current_ssid = ""
        self.current_password = ""
    
    def connect(self, ssid: str, password: str, retry_times: int = 3) -> bool:
        """
        连接到指定 WiFi
        
        Args:
            ssid: WiFi 名称
            password: WiFi 密码
            retry_times: 重试次数
            
        Returns:
            bool: 连接是否成功
        """
        self.current_ssid = ssid
        self.current_password = password
        
        logger.info(f"开始连接 WiFi: {ssid}")
        self._update_state(WiFiState.CONNECTING)
        
        for attempt in range(retry_times):
            try:
                # 检查连接是否已存在
                if self._is_connection_exists(ssid):
                    logger.info(f"WiFi 连接 '{ssid}' 已存在，尝试激活")
                    success = self._activate_connection(ssid)
                else:
                    # 创建新连接
                    logger.info(f"创建新的 WiFi 连接: {ssid}")
                    success = self._create_and_connect(ssid, password)
                
                if success:
                    logger.info(f"WiFi 连接成功: {ssid}")
                    self._update_state(WiFiState.CONNECTED)
                    
                    # 启动连接监控
                    self.start_monitoring()
                    return True
                else:
                    logger.warning(f"WiFi 连接失败（尝试 {attempt + 1}/{retry_times}）")
                    
            except Exception as e:
                logger.error(f"WiFi 连接异常: {e}")
            
            # 等待后重试
            if attempt < retry_times - 1:
                time.sleep(2)
        
        # 所有重试失败
        logger.error(f"WiFi 连接失败，已重试 {retry_times} 次")
        self._update_state(WiFiState.FAILED)
        return False
    
    def disconnect(self) -> bool:
        """断开当前 WiFi 连接"""
        try:
            # 停止监控
            self.stop_monitoring()
            
            # 断开连接
            result = subprocess.run(
                ["nmcli", "connection", "down", self.current_ssid],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode == 0:
                logger.info(f"WiFi 已断开: {self.current_ssid}")
                self._update_state(WiFiState.UNCONFIGURED)
                return True
            else:
                logger.warning(f"WiFi 断开失败: {result.stderr}")
                return False
                
        except Exception as e:
            logger.error(f"WiFi 断开异常: {e}")
            return False
    
    def get_status(self) -> dict:
        """获取 WiFi 状态"""
        try:
            # 获取当前连接状态
            result = subprocess.run(
                ["nmcli", "-t", "-f", "ACTIVE,SSID", "connection", "show"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    parts = line.split(':')
                    if len(parts) == 2 and parts[0] == 'yes':
                        return {
                            "connected": True,
                            "ssid": parts[1],
                            "ip": self._get_ip_address()
                        }
            
            return {"connected": False, "ssid": "", "ip": ""}
            
        except Exception as e:
            logger.error(f"获取 WiFi 状态异常: {e}")
            return {"connected": False, "ssid": "", "ip": ""}
    
    def start_monitoring(self) -> None:
        """启动 WiFi 连接监控"""
        if self._monitor_thread and self._monitor_thread.is_alive():
            logger.info("WiFi 监控已在运行")
            return
        
        self._stop_event.clear()
        self._monitor_thread = Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        logger.info("WiFi 监控已启动")
    
    def stop_monitoring(self) -> None:
        """停止 WiFi 连接监控"""
        if self._monitor_thread:
            self._stop_event.set()
            self._monitor_thread.join(timeout=3)
            logger.info("WiFi 监控已停止")
    
    # ==================== 内部方法 ====================
    
    def _is_connection_exists(self, ssid: str) -> bool:
        """检查连接配置是否存在"""
        return self._get_connection_name(ssid) is not None
    
    def _get_connection_name(self, ssid: str) -> Optional[str]:
        """根据 SSID 获取连接名称"""
        try:
            # 获取所有 WiFi 连接配置
            result = subprocess.run(
                ["nmcli", "-t", "-f", "NAME,802-11-wireless.ssid", "connection", "show"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                return None
            
            # 解析输出，查找匹配的 SSID
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = line.split(':')
                if len(parts) >= 2:
                    conn_name = parts[0]
                    conn_ssid = parts[1] if len(parts) > 1 else ""
                    if conn_ssid == ssid:
                        return conn_name
            
            # 如果没找到，尝试直接使用 SSID 作为连接名称（向后兼容）
            # 某些情况下连接名称就是 SSID
            name_result = subprocess.run(
                ["nmcli", "-t", "-f", "NAME", "connection", "show"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if name_result.returncode == 0 and ssid in name_result.stdout:
                return ssid
            
            return None
            
        except Exception as e:
            logger.error(f"获取连接名称异常: {e}")
            return None
    
    def _activate_connection(self, ssid: str) -> bool:
        """激活已存在的连接"""
        try:
            # 首先获取连接名称（可能和 SSID 不同）
            connection_name = self._get_connection_name(ssid)
            if not connection_name:
                logger.error(f"未找到 SSID '{ssid}' 对应的连接配置")
                return False
            
            logger.debug(f"激活连接: {connection_name} (SSID: {ssid})")
            result = subprocess.run(
                ["nmcli", "connection", "up", connection_name],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0:
                # 等待连接建立（最多等待 5 秒）
                for _ in range(10):
                    time.sleep(0.5)
                    status = self.get_status()
                    if status["connected"] and status["ssid"] == ssid:
                        logger.info(f"连接已激活: {ssid}")
                        return True
                logger.warning(f"连接激活命令成功，但未检测到连接状态: {ssid}")
                return False
            else:
                logger.error(f"激活连接失败: {result.stderr.strip()}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error(f"激活连接超时: {ssid}")
            return False
        except Exception as e:
            logger.error(f"激活连接异常: {e}")
            return False
    
    def _create_and_connect(self, ssid: str, password: str) -> bool:
        """创建并连接到新的 WiFi"""
        try:
            # 使用 nmcli 创建连接（WPA/WPA2）
            result = subprocess.run([
                "nmcli", "device", "wifi", "connect", ssid,
                "password", password
            ], capture_output=True, text=True, timeout=30)
            
            return result.returncode == 0
            
        except Exception as e:
            logger.error(f"创建连接异常: {e}")
            return False
    
    def _get_ip_address(self) -> str:
        """获取当前 IP 地址"""
        try:
            result = subprocess.run(
                ["hostname", "-I"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.stdout.strip().split()[0] if result.returncode == 0 else ""
        except Exception as e:
            logger.error(f"获取 IP 异常: {e}")
            return ""
    
    def _monitor_loop(self) -> None:
        """WiFi 连接监控循环"""
        consecutive_failures = 0
        
        while not self._stop_event.is_set():
            try:
                status = self.get_status()
                
                if status["connected"]:
                    # 连接正常
                    consecutive_failures = 0
                    if self.state_callback:
                        self._update_state(WiFiState.CONNECTED)
                else:
                    # 连接断开
                    consecutive_failures += 1
                    logger.warning(f"WiFi 连接断开（连续 {consecutive_failures} 次）")
                    
                    if consecutive_failures >= 3:
                        # 尝试重连
                        logger.info("尝试自动重连 WiFi")
                        self._update_state(WiFiState.CONNECTING)
                        self.connect(self.current_ssid, self.current_password)
                        consecutive_failures = 0
                
            except Exception as e:
                logger.error(f"WiFi 监控异常: {e}")
            
            # 每 10 秒检查一次
            self._stop_event.wait(10)
    
    def _update_state(self, state: WiFiState) -> None:
        """更新 WiFi 状态"""
        if self.state_callback:
            try:
                self.state_callback(state)
            except Exception as e:
                logger.error(f"WiFi 状态回调异常: {e}")


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    def state_changed(state):
        print(f"WiFi 状态变化: {state.value}")
    
    wifi = WiFiManager(state_callback=state_changed)
    
    # 获取当前状态
    status = wifi.get_status()
    print(f"当前 WiFi 状态: {status}")
    
    # 测试连接（请替换为真实的 WiFi 信息）
    # wifi.connect("YourWiFiSSID", "YourPassword")
