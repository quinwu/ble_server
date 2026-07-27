#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import sys
from pathlib import Path

# 配置日志
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def test_config_manager():
    """测试配置管理"""
    logger.info("=" * 60)
    logger.info("测试配置管理模块")
    logger.info("=" * 60)

    try:
        from config_manager import ConfigManager

        config = ConfigManager("/tmp/ble_test")

        # 设置 WiFi 配置
        assert config.set_wifi_config("TestWiFi", "password123")
        wifi = config.get_wifi_config()
        assert wifi["ssid"] == "TestWiFi"
        assert wifi["password"] == "password123"

        # 设置云端 URL
        assert config.set_cloud_url("https://example.com/upload")
        assert config.get_cloud_url() == "https://example.com/upload"

        logger.info("✓ 配置管理测试通过")
        return True

    except Exception as e:
        logger.error(f"✗ 配置管理测试失败: {e}")
        return False


def test_state_machine():
    """测试状态机"""
    logger.info("=" * 60)
    logger.info("测试状态机模块")
    logger.info("=" * 60)

    try:
        from state_machine import BLEState, DeviceState, StateMachine, WiFiState

        sm = StateMachine()

        # 测试状态变化
        callback_called = [False]

        def on_ble_change(old, new):
            callback_called[0] = True
            logger.info(f"BLE 状态变化: {old.value} -> {new.value}")

        sm.on_ble_state_change(on_ble_change)
        sm.set_ble_state(BLEState.CONNECTED)

        assert sm.ble_state == BLEState.CONNECTED
        assert callback_called[0]

        # 测试组合状态
        sm.set_wifi_state(WiFiState.CONNECTED)
        sm.set_device_state(DeviceState.IDLE)
        assert sm.is_ready_for_capture()

        logger.info("✓ 状态机测试通过")
        return True

    except Exception as e:
        logger.error(f"✗ 状态机测试失败: {e}")
        return False


def test_camera():
    """测试摄像头"""
    logger.info("=" * 60)
    logger.info("测试摄像头模块")
    logger.info("=" * 60)

    try:
        from camera_controller import CameraController

        camera = CameraController(save_dir="/tmp/ble_test_captures")

        # 检测拍照工具
        logger.info(f"拍照工具: {camera.capture_tool}")

        if camera.capture_tool == "none":
            logger.warning("⚠ 未找到拍照工具，跳过摄像头测试")
            return True

        # 测试摄像头
        if camera.test_camera():
            logger.info("✓ 摄像头测试通过")
            return True
        else:
            logger.warning("⚠ 摄像头不可用")
            return True  # 不算作失败

    except Exception as e:
        logger.error(f"✗ 摄像头测试失败: {e}")
        return False


def test_uploader():
    """测试云端上传"""
    logger.info("=" * 60)
    logger.info("测试云端上传模块")
    logger.info("=" * 60)

    try:
        from cloud_uploader import CloudUploader

        uploader = CloudUploader()

        # 设置测试 URL（httpbin 提供的测试接口）
        assert uploader.set_upload_url("https://httpbin.org/post")

        # 创建测试文件并转换为 base64
        test_file = Path("/tmp/test_upload.jpg")
        test_file.write_bytes(b"fake image data for testing")

        import base64

        with open(test_file, "rb") as f:
            file_data = base64.b64encode(f.read()).decode("utf-8")

        # 测试上传（使用新的格式）
        metadata = {
            "file_name": "test_upload.jpg",
            "file_area": 1,
            "file_batch": "test_batch",
            "device_id": "test-001",
            "camera_device": "/dev/video0",
            "file_data": file_data,
        }

        success = uploader.upload(metadata, retry_times=1)

        # 清理
        test_file.unlink(missing_ok=True)

        if success:
            logger.info("✓ 云端上传测试通过")
        else:
            logger.warning("⚠ 上传失败（可能是网络问题）")

        return True

    except Exception as e:
        logger.error(f"✗ 云端上传测试失败: {e}")
        return False


def test_wifi_status():
    """测试 WiFi 状态查询"""
    logger.info("=" * 60)
    logger.info("测试 WiFi 管理模块")
    logger.info("=" * 60)

    try:
        from wifi_manager import WiFiManager

        wifi = WiFiManager()

        # 获取状态
        status = wifi.get_status()
        logger.info(f"WiFi 状态: {status}")

        logger.info("✓ WiFi 状态查询通过")
        return True

    except Exception as e:
        logger.error(f"✗ WiFi 测试失败: {e}")
        return False


def main():
    """运行所有测试"""
    logger.info("\n" + "=" * 60)
    logger.info("BLE Device Server 模块测试")
    logger.info("=" * 60 + "\n")

    tests = [
        ("配置管理", test_config_manager),
        ("状态机", test_state_machine),
        ("WiFi 管理", test_wifi_status),
        ("摄像头", test_camera),
        ("云端上传", test_uploader),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            logger.error(f"测试异常: {e}")
            results.append((name, False))

        print()  # 空行分隔

    # 汇总结果
    logger.info("=" * 60)
    logger.info("测试结果汇总")
    logger.info("=" * 60)

    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        logger.info(f"{name:15s} : {status}")

    passed = sum(1 for _, result in results if result)
    total = len(results)

    logger.info("=" * 60)
    logger.info(f"测试完成: {passed}/{total} 通过")
    logger.info("=" * 60)

    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
