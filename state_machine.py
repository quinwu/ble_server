#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
from enum import Enum
from typing import Callable, Optional
from threading import Lock

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
        
        # 线程锁
        self._lock = Lock()
        
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
        with self._lock:
            if self._wifi_state != new_state:
                old_state = self._wifi_state
                self._wifi_state = new_state
                logger.info(f"WiFi 状态变化: {old_state.value} -> {new_state.value}")
                
                # 触发回调
                for callback in self._wifi_callbacks:
                    try:
                        callback(old_state, new_state)
                    except Exception as e:
                        logger.error(f"WiFi 状态回调错误: {e}")
    
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
        return (self.wifi_state == WiFiState.CONNECTED and 
                self.device_state == DeviceState.IDLE)
    
    def is_ble_ready(self) -> bool:
        """BLE 是否就绪（已连接或已认证）"""
        return self.ble_state in [BLEState.CONNECTED, BLEState.AUTHENTICATED]
    
    def get_status_dict(self) -> dict:
        """获取完整状态字典（用于 Notify）"""
        return {
            "ble_state": self.ble_state.value,
            "wifi_state": self.wifi_state.value,
            "device_state": self.device_state.value,
            "ready_for_capture": self.is_ready_for_capture()
        }


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
