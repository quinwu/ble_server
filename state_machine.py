#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from enum import Enum
from typing import Callable, Optional
from threading import RLock

logger = logging.getLogger(__name__)


class BLEState(Enum):
    """BLE 连接状态"""
    ADVERTISING = "advertising"      # 广播中（等待连接）
    CONNECTED = "connected"          # 已连接
    AUTHENTICATED = "authenticated"  # 已认证（可选）


class WiFiState(Enum):
    """WiFi 连接状态"""
    UNCONFIGURED = "unconfigured"  # 未配置
    CONNECTING = "connecting"      # 连接中
    CONNECTED = "connected"        # 已连接
    FAILED = "failed"              # 连接失败


class DeviceState(Enum):
    """设备运行状态"""
    IDLE = "idle"            # 空闲
    CAPTURING = "capturing"  # 拍照中
    UPLOADING = "uploading"  # 上传中
    ERROR = "error"          # 错误


class StateMachine:
    """状态机 - 管理所有状态转换"""
    
    def __init__(self):
        self._ble_state = BLEState.ADVERTISING
        self._wifi_state = WiFiState.UNCONFIGURED
        self._device_state = DeviceState.IDLE
        
        # 线程锁（使用 RLock 避免死锁）
        self._lock = RLock()
        
        # 状态变化回调
        self._ble_callbacks = []
        self._wifi_callbacks = []
        self._device_callbacks = []
    
    # ==================== BLE 状态管理 ====================
    
    @property
    def ble_state(self) -> BLEState:
        """获取 BLE 状态"""
        with self._lock:
            return self._ble_state
    
    def set_ble_state(self, new_state: BLEState) -> None:
        """设置 BLE 状态"""
        with self._lock:
            if self._ble_state != new_state:
                old_state = self._ble_state
                self._ble_state = new_state
                logger.info(f"BLE 状态变化: {old_state.value} -> {new_state.value}")
                
                # 触发回调
                for callback in self._ble_callbacks:
                    try:
                        callback(old_state, new_state)
                    except Exception as e:
                        logger.error(f"BLE 状态回调错误: {e}")
    
    def on_ble_state_change(self, callback: Callable) -> None:
        """注册 BLE 状态变化回调"""
        self._ble_callbacks.append(callback)
    
    # ==================== WiFi 状态管理 ====================
    
    @property
    def wifi_state(self) -> WiFiState:
        """获取 WiFi 状态"""
        with self._lock:
            return self._wifi_state
    
    def set_wifi_state(self, new_state: WiFiState) -> None:
        """设置 WiFi 状态"""
        logger.info(f"set_wifi_state 开始，新状态: {new_state.value}")
        logger.info(f"准备获取锁...")
        with self._lock:
            logger.info(f"锁已获取，当前状态: {self._wifi_state.value}")
            if self._wifi_state != new_state:
                old_state = self._wifi_state
                self._wifi_state = new_state
                logger.info(f"WiFi 状态变化: {old_state.value} -> {new_state.value}")
                
                # 触发回调
                logger.info(f"准备触发 {len(self._wifi_callbacks)} 个回调")
                for i, callback in enumerate(self._wifi_callbacks):
                    try:
                        logger.info(f"触发回调 {i+1}/{len(self._wifi_callbacks)}")
                        callback(old_state, new_state)
                        logger.info(f"回调 {i+1}/{len(self._wifi_callbacks)} 完成")
                    except Exception as e:
                        logger.error(f"WiFi 状态回调错误: {e}", exc_info=True)
                logger.info(f"所有回调完成")
            else:
                logger.info(f"状态未变化，跳过回调")
        logger.info(f"set_wifi_state 完成，释放锁")
    
    def on_wifi_state_change(self, callback: Callable) -> None:
        """注册 WiFi 状态变化回调"""
        self._wifi_callbacks.append(callback)
    
    # ==================== 设备状态管理 ====================
    
    @property
    def device_state(self) -> DeviceState:
        """获取设备状态"""
        with self._lock:
            return self._device_state
    
    def set_device_state(self, new_state: DeviceState) -> None:
        """设置设备状态"""
        with self._lock:
            if self._device_state != new_state:
                old_state = self._device_state
                self._device_state = new_state
                logger.info(f"设备状态变化: {old_state.value} -> {new_state.value}")
                
                # 触发回调
                for callback in self._device_callbacks:
                    try:
                        callback(old_state, new_state)
                    except Exception as e:
                        logger.error(f"设备状态回调错误: {e}")
    
    def on_device_state_change(self, callback: Callable) -> None:
        """注册设备状态变化回调"""
        self._device_callbacks.append(callback)
    
    # ==================== 组合状态查询 ====================
    
    def is_ready_for_capture(self) -> bool:
        """是否可以执行拍照（WiFi 已连接 + 设备空闲）"""
        logger.info("is_ready_for_capture 开始")
        try:
            wifi = self.wifi_state
            logger.info(f"wifi_state 获取: {wifi}")
            device = self.device_state
            logger.info(f"device_state 获取: {device}")
            result = (wifi == WiFiState.CONNECTED and device == DeviceState.IDLE)
            logger.info(f"is_ready_for_capture 结果: {result}")
            return result
        except Exception as e:
            logger.error(f"is_ready_for_capture 异常: {e}", exc_info=True)
            return False
    
    def is_ble_ready(self) -> bool:
        """BLE 是否就绪（已连接或已认证）"""
        return self.ble_state in [BLEState.CONNECTED, BLEState.AUTHENTICATED]
    
    def get_status_dict(self) -> dict:
        """获取完整状态字典（用于 Notify）"""
        logger.info("get_status_dict 开始")
        try:
            logger.info("准备获取 ble_state")
            ble_state = self.ble_state.value
            logger.info(f"ble_state 获取完成: {ble_state}")
            logger.info("准备获取 wifi_state")
            wifi_state = self.wifi_state.value
            logger.info(f"wifi_state 获取完成: {wifi_state}")
            logger.info("准备获取 device_state")
            device_state = self.device_state.value
            logger.info(f"device_state 获取完成: {device_state}")
            logger.info("准备调用 is_ready_for_capture()")
            ready = self.is_ready_for_capture()
            logger.info(f"is_ready_for_capture() 完成: {ready}")
            result = {
                "ble_state": ble_state,
                "wifi_state": wifi_state,
                "device_state": device_state,
                "ready_for_capture": ready
            }
            logger.info(f"get_status_dict 完成: {result}")
            return result
        except Exception as e:
            logger.error(f"get_status_dict 异常: {e}", exc_info=True)
            raise


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)
    
    sm = StateMachine()
    
    # 注册回调
    def on_ble_change(old, new):
        print(f"BLE 回调: {old.value} -> {new.value}")
    
    def on_wifi_change(old, new):
        print(f"WiFi 回调: {old.value} -> {new.value}")
    
    sm.on_ble_state_change(on_ble_change)
    sm.on_wifi_state_change(on_wifi_change)
    
    # 测试状态变化
    sm.set_ble_state(BLEState.CONNECTED)
    sm.set_wifi_state(WiFiState.CONNECTING)
    sm.set_wifi_state(WiFiState.CONNECTED)
    
    print("\n当前状态:", sm.get_status_dict())
    print("可以拍照:", sm.is_ready_for_capture())
