#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import json
import os
import logging
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class ConfigManager:
        
    def __init__(self, config_dir: str = "/var/lib/ble_device"):
        self.config_dir = Path(config_dir)
        self.config_file = self.config_dir / "config.json"
        
        # 创建配置目录
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # 默认配置
        self.config = {
            "wifi": {
                "ssid": "",
                "password": ""
            },
            "cloud": {
                "upload_url": ""
            },
            "device": {
                "name": "BLE-Device",
                "version": "1.0.0"
            },
            "camera": {
                "card_type_filter": "USB Camera"
            }
        }
        
        # 加载配置
        self.load()
    
    def load(self) -> Dict:
        """从文件加载配置"""
        try:
            if self.config_file.exists():
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    loaded_config = json.load(f)
                    # 合并配置（保留默认值）
                    self._deep_update(self.config, loaded_config)
                    logger.info(f"配置加载成功: {self.config_file}")
            else:
                logger.info("配置文件不存在，使用默认配置")
                self.save()  # 创建默认配置文件
        except Exception as e:
            logger.error(f"配置加载失败: {e}")
        
        return self.config
    
    def save(self) -> bool:
        """保存配置到文件"""
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(self.config, f, indent=2, ensure_ascii=False)
            
            # 设置文件权限（只有 root 可读写）
            os.chmod(self.config_file, 0o600)
            logger.info(f"配置保存成功: {self.config_file}")
            return True
        except Exception as e:
            logger.error(f"配置保存失败: {e}")
            return False
    
    def get_wifi_config(self) -> Dict[str, str]:
        """获取 WiFi 配置"""
        return self.config.get("wifi", {})
    
    def set_wifi_config(self, ssid: str, password: str) -> bool:
        """设置 WiFi 配置"""
        try:
            self.config["wifi"]["ssid"] = ssid
            self.config["wifi"]["password"] = password
            return self.save()
        except Exception as e:
            logger.error(f"设置 WiFi 配置失败: {e}")
            return False
    
    def get_cloud_url(self) -> str:
        """获取云端上传 URL"""
        return self.config.get("cloud", {}).get("upload_url", "")
    
    def set_cloud_url(self, url: str) -> bool:
        """设置云端上传 URL"""
        try:
            self.config["cloud"]["upload_url"] = url
            return self.save()
        except Exception as e:
            logger.error(f"设置云端 URL 失败: {e}")
            return False
    
    def get_device_info(self) -> Dict[str, str]:
        """获取设备信息"""
        return self.config.get("device", {})
    
    def get_camera_card_type_filter(self) -> Optional[str]:
        """获取摄像头设备类型过滤"""
        return self.config.get("camera", {}).get("card_type_filter")
    
    def set_camera_card_type_filter(self, card_type_filter: str) -> bool:
        """设置摄像头设备类型过滤"""
        try:
            if "camera" not in self.config:
                self.config["camera"] = {}
            self.config["camera"]["card_type_filter"] = card_type_filter
            return self.save()
        except Exception as e:
            logger.error(f"设置摄像头设备类型过滤失败: {e}")
            return False
    
    def _deep_update(self, base_dict: Dict, update_dict: Dict) -> Dict:
        """深度更新字典"""
        for key, value in update_dict.items():
            if isinstance(value, dict) and key in base_dict:
                self._deep_update(base_dict[key], value)
            else:
                base_dict[key] = value
        return base_dict


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO)
    
    config = ConfigManager("/tmp/ble_device_test")
    
    # 设置 WiFi 配置
    config.set_wifi_config("TestWiFi", "password123")
    
    # 设置云端 URL
    config.set_cloud_url("https://example.com/upload")
    
    # 读取配置
    print("WiFi Config:", config.get_wifi_config())
    print("Cloud URL:", config.get_cloud_url())
    print("Device Info:", config.get_device_info())
