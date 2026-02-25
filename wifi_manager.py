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
        
        # 确保WiFi设备已启用
        if not self._ensure_wifi_enabled():
            logger.error("WiFi 设备未启用或不可用")
            self._update_state(WiFiState.FAILED)
            return False
        
        for attempt in range(retry_times):
            try:
                # 检查连接是否已存在
                if self._is_connection_exists(ssid):
                    logger.info(f"WiFi 连接 '{ssid}' 已存在，尝试激活")
                    success = self._activate_connection(ssid)
                else:
                    # 创建新连接
                    logger.info(f"创建新的 WiFi 连接: {ssid}")
                    # 先尝试快速连接方式
                    success = self._create_and_connect(ssid, password)
                    # 如果快速方式失败，尝试更可靠的连接方式
                    if not success and attempt == retry_times - 1:
                        logger.info(f"快速连接失败，尝试使用备用连接方式: {ssid}")
                        success = self._create_and_connect_alternative(ssid, password)
                
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
            # 使用 device status 检查实际的 WiFi 设备连接状态（更准确）
            # 而不是 connection show（只检查连接配置）
            result = subprocess.run(
                ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                for line in lines:
                    if not line:
                        continue
                    parts = line.split(':')
                    # 格式: DEVICE:TYPE:STATE:CONNECTION
                    # 例如: wlan0:wifi:connected:danhuang
                    if len(parts) >= 4 and parts[1] == 'wifi':
                        device = parts[0]
                        state = parts[2]
                        connection = parts[3] if len(parts) > 3 else ""
                        
                        # 检查设备状态是否为 connected
                        if state == 'connected' and connection:
                            # 获取 SSID（CONNECTION 字段就是连接名称，通常等于 SSID）
                            ssid = connection
                            return {
                                "connected": True,
                                "ssid": ssid,
                                "ip": self._get_ip_address()
                            }
            
            # 如果没有找到连接的 WiFi 设备，返回未连接状态
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
    
    def _ensure_wifi_enabled(self) -> bool:
        """确保WiFi设备已启用"""
        try:
            # 检查WiFi设备状态
            result = subprocess.run(
                ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if result.returncode != 0:
                logger.error("无法获取设备状态")
                return False
            
            # 查找WiFi设备
            wifi_device = None
            for line in result.stdout.strip().split('\n'):
                if not line:
                    continue
                parts = line.split(':')
                if len(parts) >= 3 and parts[1] == 'wifi':
                    wifi_device = parts[0]
                    state = parts[2]
                    
                    # 如果设备未连接或未启用，尝试启用
                    if state in ['unavailable', 'disconnected']:
                        logger.info(f"启用 WiFi 设备: {wifi_device}")
                        enable_result = subprocess.run(
                            ["nmcli", "radio", "wifi", "on"],
                            capture_output=True,
                            text=True,
                            timeout=5
                        )
                        if enable_result.returncode == 0:
                            # 等待设备就绪
                            time.sleep(2)
                            logger.info(f"WiFi 设备已启用: {wifi_device}")
                        else:
                            logger.warning(f"启用 WiFi 设备失败: {enable_result.stderr}")
                    
                    return True  # 找到WiFi设备
            
            if wifi_device is None:
                logger.error("未找到 WiFi 设备")
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"检查 WiFi 设备状态异常: {e}")
            return False
    
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
        process = None
        try:
            # 使用 nmcli device wifi connect（异步方式）
            logger.info(f"启动 WiFi 连接命令: {ssid}")
            process = subprocess.Popen([
                "nmcli", "device", "wifi", "connect", ssid,
                "password", password
            ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            
            # 轮询检查连接状态，最多等待60秒
            max_wait_time = 60
            check_interval = 2
            elapsed_time = 0
            
            while elapsed_time < max_wait_time:
                # 检查进程是否已完成
                return_code = process.poll()
                if return_code is not None:
                    # 进程已完成，读取输出
                    stdout, stderr = process.communicate()
                    logger.info(f"WiFi 连接命令完成，返回码: {return_code}")
                    if stdout:
                        logger.debug(f"命令输出: {stdout.strip()}")
                    if stderr:
                        logger.debug(f"命令错误输出: {stderr.strip()}")
                    
                    if return_code == 0:
                        logger.info(f"WiFi 连接命令执行成功: {ssid}")
                        # 等待一下确保连接建立
                        time.sleep(3)
                        # 验证连接状态
                        status = self.get_status()
                        logger.info(f"连接状态检查: connected={status['connected']}, ssid={status['ssid']}")
                        if status["connected"] and status["ssid"] == ssid:
                            logger.info(f"WiFi 连接验证成功: {ssid}")
                            return True
                        else:
                            logger.warning(f"连接命令成功但状态验证失败: {ssid}, 当前状态: {status}")
                            # 即使状态验证失败，也再等待一下，可能连接还在建立中
                            time.sleep(2)
                            status = self.get_status()
                            if status["connected"] and status["ssid"] == ssid:
                                logger.info(f"延迟检查后连接成功: {ssid}")
                                return True
                    else:
                        logger.error(f"WiFi 连接命令失败 (返回码 {return_code}): {stderr.strip() if stderr else '无错误输出'}")
                        # 即使命令失败，也检查一下状态（可能连接已建立）
                        status = self.get_status()
                        if status["connected"] and status["ssid"] == ssid:
                            logger.info(f"命令失败但连接已建立: {ssid}")
                            return True
                        return False
                
                # 检查连接状态（可能在命令完成前就已连接）
                status = self.get_status()
                if status["connected"] and status["ssid"] == ssid:
                    logger.info(f"WiFi 连接已建立（命令仍在运行）: {ssid}")
                    # 终止进程（如果还在运行）
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.wait(timeout=2)
                        except subprocess.TimeoutExpired:
                            process.kill()
                    return True
                
                time.sleep(check_interval)
                elapsed_time += check_interval
                if elapsed_time % 10 == 0:
                    logger.debug(f"等待 WiFi 连接中... ({elapsed_time}/{max_wait_time}秒)")
            
            # 超时，检查进程状态
            logger.warning(f"WiFi 连接超时: {ssid}")
            return_code = process.poll()
            if return_code is None:
                # 进程仍在运行，终止它
                logger.info("终止仍在运行的连接进程")
                process.terminate()
                try:
                    stdout, stderr = process.communicate(timeout=2)
                    if stdout:
                        logger.debug(f"终止后的输出: {stdout.strip()}")
                    if stderr:
                        logger.debug(f"终止后的错误输出: {stderr.strip()}")
                except subprocess.TimeoutExpired:
                    process.kill()
                    logger.warning("强制终止连接进程")
            else:
                # 进程已完成，读取输出
                stdout, stderr = process.communicate()
                logger.info(f"超时时进程已完成，返回码: {return_code}")
                if stdout:
                    logger.debug(f"进程输出: {stdout.strip()}")
                if stderr:
                    logger.debug(f"进程错误输出: {stderr.strip()}")
            
            # 最后检查一次状态
            status = self.get_status()
            logger.info(f"超时后最终状态检查: connected={status['connected']}, ssid={status['ssid']}")
            if status["connected"] and status["ssid"] == ssid:
                logger.info(f"超时后检查发现连接已建立: {ssid}")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"创建连接异常: {e}", exc_info=True)
            if process and process.poll() is None:
                try:
                    process.terminate()
                    process.wait(timeout=2)
                except:
                    process.kill()
            return False
    
    def _create_and_connect_alternative(self, ssid: str, password: str) -> bool:
        """备用连接方法：使用 nmcli connection add + up（更可靠但更慢）"""
        try:
            logger.info(f"使用备用方法创建 WiFi 连接: {ssid}")
            
            # 步骤1: 创建连接配置
            logger.info(f"创建连接配置: {ssid}")
            add_result = subprocess.run([
                "nmcli", "connection", "add",
                "type", "wifi",
                "con-name", ssid,
                "ifname", "*",
                "ssid", ssid,
                "wifi-sec.key-mgmt", "wpa-psk",
                "wifi-sec.psk", password
            ], capture_output=True, text=True, timeout=10)
            
            if add_result.returncode != 0:
                # 如果连接已存在，尝试删除后重新创建
                if "already exists" in add_result.stderr.lower():
                    logger.info(f"连接配置已存在，尝试删除后重新创建: {ssid}")
                    subprocess.run(
                        ["nmcli", "connection", "delete", ssid],
                        capture_output=True,
                        timeout=5
                    )
                    # 重新创建
                    add_result = subprocess.run([
                        "nmcli", "connection", "add",
                        "type", "wifi",
                        "con-name", ssid,
                        "ifname", "*",
                        "ssid", ssid,
                        "wifi-sec.key-mgmt", "wpa-psk",
                        "wifi-sec.psk", password
                    ], capture_output=True, text=True, timeout=10)
                
                if add_result.returncode != 0:
                    logger.error(f"创建连接配置失败: {add_result.stderr.strip()}")
                    return False
            
            logger.info(f"连接配置创建成功: {ssid}")
            
            # 步骤2: 激活连接
            logger.info(f"激活连接: {ssid}")
            up_result = subprocess.run(
                ["nmcli", "connection", "up", ssid],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if up_result.returncode != 0:
                logger.error(f"激活连接失败: {up_result.stderr.strip()}")
                return False
            
            logger.info(f"连接激活命令执行成功: {ssid}")
            
            # 步骤3: 等待并验证连接
            max_wait = 20
            for i in range(max_wait):
                time.sleep(1)
                status = self.get_status()
                if status["connected"] and status["ssid"] == ssid:
                    logger.info(f"备用方法连接成功: {ssid}")
                    return True
                if i % 5 == 0:
                    logger.debug(f"等待连接建立... ({i}/{max_wait}秒)")
            
            # 最终检查
            status = self.get_status()
            if status["connected"] and status["ssid"] == ssid:
                logger.info(f"备用方法最终验证成功: {ssid}")
                return True
            
            logger.warning(f"备用方法连接失败，状态验证未通过: {ssid}")
            return False
            
        except subprocess.TimeoutExpired as e:
            logger.error(f"备用连接方法超时: {e}")
            return False
        except Exception as e:
            logger.error(f"备用连接方法异常: {e}", exc_info=True)
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
        # 等待5秒后开始监控
        self._stop_event.wait(5)

        while not self._stop_event.is_set():
            try:
                status = self.get_status()
                logger.debug(f"WiFi 监控检查: connected={status['connected']}, ssid={status['ssid']}")
                
                if status["connected"]:
                    # 连接正常
                    if consecutive_failures > 0:
                        logger.info(f"WiFi 连接恢复: {status['ssid']}")
                    consecutive_failures = 0
                    # 注意：只在状态变化时更新，state_machine 会检查状态是否变化
                    if self.state_callback:
                        self._update_state(WiFiState.CONNECTED)
                else:
                    # 连接断开
                    consecutive_failures += 1
                    logger.warning(f"WiFi 连接断开（连续 {consecutive_failures} 次）")
                    
                    if consecutive_failures >= 3:
                        # 尝试重连
                        logger.info("尝试自动重连 WiFi")
                        if self.current_ssid and self.current_password:
                            self._update_state(WiFiState.CONNECTING)
                            self.connect(self.current_ssid, self.current_password)
                        else:
                            logger.error("无法重连：缺少 WiFi 配置信息")
                        consecutive_failures = 0
                
            except Exception as e:
                logger.error(f"WiFi 监控异常: {e}", exc_info=True)
            
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
