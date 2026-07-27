#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BLE GATT Server base on BlueZ D-Bus API
"""

import json
import logging
import time
from typing import Callable, Optional

import dbus
import dbus.mainloop.glib
import dbus.service
from gi.repository import GLib

import struct
import itertools
import math
import zlib

from ble_json_buffer import MAX_WRITE_BUFFER_SIZE, WRITE_BUFFER_TIMEOUT_SEC, try_parse_complete_json


logger = logging.getLogger(__name__)

# GATT Service 和 Characteristic UUIDs
DEVICE_CONTROL_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
CHAR_WIFI_CONFIG_UUID = "12345678-1234-5678-1234-56789abcdef1"
CHAR_CLOUD_CONFIG_UUID = "12345678-1234-5678-1234-56789abcdef2"
CHAR_CAPTURE_COMMAND_UUID = "12345678-1234-5678-1234-56789abcdef3"
CHAR_STATUS_NOTIFY_UUID = "12345678-1234-5678-1234-56789abcdef4"

CHAR_LASER_CONTROL_UUID = "12345678-1234-5678-1234-56789abcdef5"

# BlueZ D-Bus 路径
BLUEZ_SERVICE_NAME = "org.bluez"
GATT_MANAGER_IFACE = "org.bluez.GattManager1"
GATT_SERVICE_IFACE = "org.bluez.GattService1"
GATT_CHARACTERISTIC_IFACE = "org.bluez.GattCharacteristic1"
DBUS_PROP_IFACE = "org.freedesktop.DBus.Properties"
LE_ADVERTISING_MANAGER_IFACE = "org.bluez.LEAdvertisingManager1"
LE_ADVERTISEMENT_IFACE = "org.bluez.LEAdvertisement1"


class Application(dbus.service.Object):
    """GATT Applications"""

    def __init__(self, bus):
        self.path = "/"
        self.services = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_service(self, service):
        self.services.append(service)

    @dbus.service.method("org.freedesktop.DBus.ObjectManager", out_signature="a{oa{sa{sv}}}")
    def GetManagedObjects(self):
        response = {}
        for service in self.services:
            response[service.get_path()] = service.get_properties()
            chrcs = service.get_characteristics()
            for chrc in chrcs:
                response[chrc.get_path()] = chrc.get_properties()
        return response


class Service(dbus.service.Object):
    """GATT Service Base Class"""

    PATH_BASE = "/org/bluez/example/service"

    def __init__(self, bus, index, uuid, primary):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.uuid = uuid
        self.primary = primary
        self.characteristics = []
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_SERVICE_IFACE: {
                "UUID": self.uuid,
                "Primary": self.primary,
                "Characteristics": dbus.Array(self.get_characteristic_paths(), signature="o"),
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    def add_characteristic(self, characteristic):
        self.characteristics.append(characteristic)

    def get_characteristic_paths(self):
        result = []
        for chrc in self.characteristics:
            result.append(chrc.get_path())
        return result

    def get_characteristics(self):
        return self.characteristics

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_SERVICE_IFACE:
            raise dbus.exceptions.DBusException("org.freedesktop.DBus.Error.InvalidArgs", "Invalid interface")
        return self.get_properties()[GATT_SERVICE_IFACE]


class Characteristic(dbus.service.Object):
    def __init__(self, bus, index, uuid, flags, service):
        self.path = service.path + "/char" + str(index)
        self.bus = bus
        self.uuid = uuid
        self.service = service
        self.flags = flags
        self.notifying = False
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        return {
            GATT_CHARACTERISTIC_IFACE: {
                "Service": self.service.get_path(),
                "UUID": self.uuid,
                "Flags": self.flags,
            }
        }

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != GATT_CHARACTERISTIC_IFACE:
            raise dbus.exceptions.DBusException("org.freedesktop.DBus.Error.InvalidArgs", "Invalid interface")
        return self.get_properties()[GATT_CHARACTERISTIC_IFACE]

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        logger.warning(f"ReadValue not implemented for {self.uuid}")
        raise dbus.exceptions.DBusException("org.bluez.Error.NotSupported", "Read not supported")

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value, options):
        logger.warning(f"WriteValue not implemented for {self.uuid}")
        raise dbus.exceptions.DBusException("org.bluez.Error.NotSupported", "Write not supported")

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE)
    def StartNotify(self):
        if self.notifying:
            return
        self.notifying = True
        logger.info(f"Notify started for {self.uuid}")

    @dbus.service.method(GATT_CHARACTERISTIC_IFACE)
    def StopNotify(self):
        if not self.notifying:
            return
        self.notifying = False
        logger.info(f"Notify stopped for {self.uuid}")

    @dbus.service.signal(DBUS_PROP_IFACE, signature="sa{sv}as")
    def PropertiesChanged(self, interface, changed, invalidated):
        pass

    def send_notify(self, value):
        """发送 Notify 消息"""
        if not self.notifying:
            logger.warning(f"Notify not enabled for {self.uuid}")
            return

        self.PropertiesChanged(GATT_CHARACTERISTIC_IFACE, {"Value": dbus.Array(value, signature="y")}, [])
        logger.debug(f"Notify sent: {value[:50]}...")


class JsonWriteCharacteristic(Characteristic):
    """Accumulate chunked BLE writes until a complete JSON object is received."""

    def __init__(self, bus, index, uuid, service):
        super().__init__(bus, index, uuid, ["write"], service)
        self._write_buffer = bytearray()
        self._last_write_at = 0.0

    def WriteValue(self, value, options):
        try:
            self._accumulate_write(value)
            config = try_parse_complete_json(self._write_buffer)
            if config is None:
                logger.debug(
                    f"{self._config_label()} buffered {len(self._write_buffer)} bytes, waiting for more data"
                )
                return

            value_str = self._write_buffer.decode("utf-8")
            logger.info(f"收到 {self._config_label()}: {value_str}")
            self._write_buffer.clear()
            self._handle_json(config)

        except json.JSONDecodeError as e:
            self._write_buffer.clear()
            logger.error(f"{self._config_label()} JSON 解析失败: {e}")
            raise dbus.exceptions.DBusException("org.bluez.Error.InvalidValueLength", "Invalid JSON format")
        except Exception as e:
            self._write_buffer.clear()
            logger.error(f"{self._config_label()} 处理失败: {e}")
            raise dbus.exceptions.DBusException("org.bluez.Error.Failed", str(e))

    def _accumulate_write(self, value) -> None:
        now = time.time()
        if self._write_buffer and now - self._last_write_at > WRITE_BUFFER_TIMEOUT_SEC:
            logger.warning(f"{self._config_label()} write buffer timeout, discarding partial data")
            self._write_buffer.clear()

        self._write_buffer.extend(value)
        self._last_write_at = now

        if len(self._write_buffer) > MAX_WRITE_BUFFER_SIZE:
            self._write_buffer.clear()
            raise ValueError(f"Write data exceeds {MAX_WRITE_BUFFER_SIZE} bytes")

    def _config_label(self) -> str:
        return "JSON write"

    def _handle_json(self, config: dict) -> None:
        raise NotImplementedError


# 串口控制
class LaserControlCharacteristic(JsonWriteCharacteristic):
    def __init__(self, bus, index, service, on_laser_control: Callable):
        super().__init__(bus, index, CHAR_LASER_CONTROL_UUID, service)
        self.on_laser_control = on_laser_control

    def _config_label(self) -> str:
        return "串口开关指令"

    def _handle_json(self, config: dict) -> None:
        cmd = config.get("switch", "").lower()
        device = config.get("device", "unknown")
        self.service.client_device_model = device
        if cmd in ["on", "off"]:
            if self.on_laser_control:
                self.on_laser_control(cmd)
        else:
            raise ValueError(f"未知串口开关指令: {cmd}，仅支持on/off")


class WiFiConfigCharacteristic(JsonWriteCharacteristic):
    def __init__(self, bus, index, service, on_wifi_config: Callable):
        super().__init__(bus, index, CHAR_WIFI_CONFIG_UUID, service)
        self.on_wifi_config = on_wifi_config

    def _config_label(self) -> str:
        return "WiFi 配置"

    def _handle_json(self, config: dict) -> None:
        ssid = config.get("ssid", "")
        password = config.get("psk", config.get("password", ""))
        device = config.get("device", "unknown")
        # 存入全局缓存
        self.service.client_device_model = device

        if not ssid:
            raise ValueError("SSID 不能为空")

        logger.info(f"触发回调: {ssid}, {password}")
        if self.on_wifi_config:
            self.on_wifi_config(ssid, password)


class CloudConfigCharacteristic(JsonWriteCharacteristic):
    def __init__(self, bus, index, service, on_cloud_config: Callable):
        super().__init__(bus, index, CHAR_CLOUD_CONFIG_UUID, service)
        self.on_cloud_config = on_cloud_config

    def _config_label(self) -> str:
        return "云端配置"

    def _handle_json(self, config: dict) -> None:
        upload_url = config.get("upload_url", "")
        device = config.get("device", "unknown")
        # 存入全局缓存
        self.service.client_device_model = device

        if not upload_url:
            raise ValueError("upload_url 不能为空")

        if self.on_cloud_config:
            self.on_cloud_config(upload_url)


class CaptureCommandCharacteristic(JsonWriteCharacteristic):
    def __init__(self, bus, index, service, on_capture: Callable):
        super().__init__(bus, index, CHAR_CAPTURE_COMMAND_UUID, service)
        self.on_capture = on_capture

    def _config_label(self) -> str:
        return "拍照指令"

    def _handle_json(self, config: dict) -> None:
        cmd = config.get("command", "")
        file_batch = config.get("file_batch", "")
        authorization = config.get("authorization", "")
        device = config.get("device", "unknown")

        # 存入全局缓存
        self.service.client_device_model = device

        if cmd == "capture":
            if self.on_capture:
                self.on_capture(file_batch, authorization)
        else:
            raise ValueError(f"未知指令: {cmd}")


# class StatusNotifyCharacteristic(Characteristic):
#     def __init__(self, bus, index, service):
#         super().__init__(bus, index, CHAR_STATUS_NOTIFY_UUID, ["notify"], service)
#         self._last_notify_time = 0.0

#     # def notify_status(self, status_dict: dict):
#     #     """发送状态通知"""
#     #     try:
#     #         # 转换为 JSON
#     #         status_json = json.dumps(status_dict, ensure_ascii=False)
#     #         value = [dbus.Byte(c) for c in status_json.encode("utf-8")]

#     #         # 发送 Notify
#     #         self.send_notify(value)
#     #         logger.info(f"状态通知已发送: {status_json}")

#     #     except Exception as e:
#     #         logger.error(f"发送状态通知失败: {e}")
#     def notify_status(self, status_dict: dict):
#         """发送状态通知，自动分包，兼容iPhone蓝牙182字节限制"""
#         try:
#             status_json = json.dumps(status_dict, ensure_ascii=False) + "\n" # 追加换行分隔符
#             raw_bytes = status_json.encode("utf-8")
#             MTU = 100
#             offset = 0
#             total_len = len(raw_bytes)

#             while offset < total_len:
#                 end = offset + MTU
#                 chunk = raw_bytes[offset:end]
#                 # 转dbus字节数组
#                 value = [dbus.Byte(b) for b in chunk]
#                 self.send_notify(value)
#                 logger.debug(f"Notify分片发送 offset={offset}, len={len(chunk)}")
#                 offset += MTU
#                 # device_model = self.service.client_device_model
                
#                 # if device_model.startswith("ios"):
#                     # logger.info(f"iOS设备({device_model})，使用短间隔发送分片")
#                     # chunk_sleep = 0.03
#                 # else:
#                     # logger.info(f"安卓设备({device_model})，使用长间隔发送分片")
#                 chunk_sleep = 0.02
#                 time.sleep(chunk_sleep)
#             logger.info(f"状态通知完整发送: {status_json.strip()}")
#         except Exception as e:
#             logger.error(f"发送状态通知失败: {e}")


class StatusNotifyCharacteristic(Characteristic):
    """
    状态通知 Characteristic

    使用自定义 BLE Notify 分包协议：

    每个 BLE Notify 包格式：
    ┌────────────┬────────────┬────────┬────────┬──────────────┬────────────┐
    │ magic      │ msg_id     │ seq    │ total  │ payload_len  │ payload    │
    │ 2 bytes    │ 2 bytes    │ 1 byte │ 1 byte │ 1 byte       │ N bytes    │
    └────────────┴────────────┴────────┴────────┴──────────────┴────────────┘

    magic:
        固定 0xAA55，用于判断是否是本协议包。

    msg_id:
        消息 ID。同一条 JSON 拆出来的所有分片 msg_id 相同。

    seq:
        当前分片序号，从 0 开始。

    total:
        总分片数。

    payload_len:
        当前 payload 实际长度。

    payload:
        JSON UTF-8 字节的一部分。
    """

    MAGIC = 0xAA55

    # 按最保守 BLE Notify 长度处理：20 字节
    # 如果后续你能拿到 negotiated MTU，可以改成 negotiated_mtu - 3
    BLE_PACKET_SIZE = 20

    # magic(2) + msg_id(2) + seq(1) + total(1) + payload_len(1)
    HEADER_SIZE = 7

    PAYLOAD_SIZE = BLE_PACKET_SIZE - HEADER_SIZE

    # > 表示大端序
    # H: unsigned short, 2 bytes
    # B: unsigned char, 1 byte
    HEADER_FORMAT = ">H H B B B"

    _msg_counter = itertools.count(1)

    def __init__(self, bus, index, service):
        super().__init__(bus, index, CHAR_STATUS_NOTIFY_UUID, ["notify"], service)
        self._last_notify_time = 0.0

    def notify_status(self, status_dict: dict):
        """
        发送状态通知，使用二进制包头进行可靠分包。

        客户端必须根据 msg_id + seq + total 重组后，再解析 JSON。
        不允许客户端每收到一包就 JSON.parse。
        """
        try:
            if not self.notifying:
                logger.warning("Notify not enabled, skip status notify")
                return

            # 1. JSON 转 UTF-8 bytes
            raw_bytes = json.dumps(
                status_dict,
                ensure_ascii=False,
                separators=(",", ":")
            ).encode("utf-8")

            total_len = len(raw_bytes)
            if total_len == 0:
                logger.warning("empty status json, skip notify")
                return

            # 2. 计算分包数量
            total_packets = math.ceil(total_len / self.PAYLOAD_SIZE)

            if total_packets > 255:
                raise ValueError(
                    f"status json too large: {total_len} bytes, "
                    f"packets={total_packets}, max packets=255"
                )

            # 3. 生成消息 ID
            msg_id = next(self._msg_counter) & 0xFFFF

            # 可选：日志用 CRC，当前包头没带 CRC，客户端也可以不校验
            crc32_value = zlib.crc32(raw_bytes) & 0xFFFFFFFF

            logger.info(
                f"开始发送状态通知: msg_id={msg_id}, "
                f"json_len={total_len}, packets={total_packets}, crc32={crc32_value:08X}"
            )

            # 4. 分包发送
            for seq in range(total_packets):
                start = seq * self.PAYLOAD_SIZE
                end = start + self.PAYLOAD_SIZE
                payload = raw_bytes[start:end]
                payload_len = len(payload)

                # 5. 构造包头
                header = struct.pack(
                    self.HEADER_FORMAT,
                    self.MAGIC,
                    msg_id,
                    seq,
                    total_packets,
                    payload_len
                )

                packet = header + payload

                # 理论上不能超过 BLE_PACKET_SIZE
                if len(packet) > self.BLE_PACKET_SIZE:
                    raise ValueError(
                        f"packet too large: {len(packet)} > {self.BLE_PACKET_SIZE}"
                    )

                value = [dbus.Byte(b) for b in packet]
                self.send_notify(value)

                logger.debug(
                    f"Notify分片发送: msg_id={msg_id}, "
                    f"seq={seq}/{total_packets - 1}, "
                    f"payload_len={payload_len}, packet_len={len(packet)}"
                )

                # 6. 临时流控
                # 注意：这个 sleep 只是防止蓝牙栈压力过大，
                # 不再承担“判断 JSON 边界”的职责。
                time.sleep(0.03)

            logger.info(
                f"状态通知完整发送: msg_id={msg_id}, "
                f"packets={total_packets}, json_len={total_len}"
            )

        except Exception as e:
            logger.error(f"发送状态通知失败: {e}")



class DeviceControlService(Service):
    def __init__(self, bus, index, on_wifi_config: Callable, on_cloud_config: Callable, on_capture: Callable, on_laser_control: Callable):
        super().__init__(bus, index, DEVICE_CONTROL_SERVICE_UUID, True)

        # 添加 Characteristics
        self.add_characteristic(WiFiConfigCharacteristic(bus, 0, self, on_wifi_config))
        self.add_characteristic(CloudConfigCharacteristic(bus, 1, self, on_cloud_config))
        self.add_characteristic(CaptureCommandCharacteristic(bus, 2, self, on_capture))
        self.add_characteristic(LaserControlCharacteristic(bus, 3, self, on_laser_control))

        # 状态通知 Characteristic（需要引用以便发送通知）
        self.status_notify_char = StatusNotifyCharacteristic(bus, 4, self)
        self.add_characteristic(self.status_notify_char)

        self.client_device_model = "unknown"


    def notify_status(self, status_dict: dict):
        """发送状态通知"""
        self.status_notify_char.notify_status(status_dict)


class Advertisement(dbus.service.Object):
    PATH_BASE = "/org/bluez/example/advertisement"

    def __init__(self, bus, index, advertising_type):
        self.path = self.PATH_BASE + str(index)
        self.bus = bus
        self.ad_type = advertising_type
        self.service_uuids = None
        self.local_name = "BLE-Device"
        self.include_tx_power = True
        dbus.service.Object.__init__(self, bus, self.path)

    def get_properties(self):
        properties = {
            "Type": self.ad_type,
            "LocalName": dbus.String(self.local_name),
            "IncludeTxPower": dbus.Boolean(self.include_tx_power),
        }
        if self.service_uuids:
            properties["ServiceUUIDs"] = dbus.Array(self.service_uuids, signature="s")
        return {LE_ADVERTISEMENT_IFACE: properties}

    def get_path(self):
        return dbus.ObjectPath(self.path)

    @dbus.service.method(DBUS_PROP_IFACE, in_signature="s", out_signature="a{sv}")
    def GetAll(self, interface):
        if interface != LE_ADVERTISEMENT_IFACE:
            raise dbus.exceptions.DBusException("org.freedesktop.DBus.Error.InvalidArgs", "Invalid interface")
        return self.get_properties()[LE_ADVERTISEMENT_IFACE]

    @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature="", out_signature="")
    def Release(self):
        logger.info(f"Advertisement released: {self.path}")


class BLEGattServer:
    def __init__(
        self, on_wifi_config: Callable, on_cloud_config: Callable, on_capture: Callable, on_laser_control: Callable, device_name: str = "BLE-Device"
    ):
        # 初始化 D-Bus
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()

        # 回调函数
        self.on_wifi_config = on_wifi_config
        self.on_cloud_config = on_cloud_config
        self.on_capture = on_capture
        self.on_laser_control = on_laser_control

        # 缓存 MAC 地址
        self._mac_address = None

        # 创建 Application
        self.app = Application(self.bus)

        # 创建 Service
        self.service = DeviceControlService(self.bus, 0, on_wifi_config, on_cloud_config, on_capture, on_laser_control)
        self.app.add_service(self.service)

        # 创建 Advertisement
        self.ad = Advertisement(self.bus, 0, "peripheral")
        self.ad.service_uuids = [DEVICE_CONTROL_SERVICE_UUID]
        self.ad.local_name = device_name

        # GLib 主循环
        self.mainloop = GLib.MainLoop()

    def register_app(self):
        """注册 GATT Application"""
        try:
            adapter_path = self._find_adapter()
            if not adapter_path:
                raise Exception("未找到蓝牙适配器")

            service_manager = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, adapter_path), GATT_MANAGER_IFACE)

            service_manager.RegisterApplication(
                self.app.get_path(), {}, reply_handler=self._register_app_reply, error_handler=self._register_app_error
            )

            logger.info("GATT Application 注册成功")

        except Exception as e:
            logger.error(f"注册 GATT Application 失败: {e}")
            raise

    def register_ad(self):
        """注册 Advertisement"""
        try:
            adapter_path = self._find_adapter()
            if not adapter_path:
                raise Exception("未找到蓝牙适配器")

            ad_manager = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE_NAME, adapter_path), LE_ADVERTISING_MANAGER_IFACE
            )

            ad_manager.RegisterAdvertisement(
                self.ad.get_path(), {}, reply_handler=self._register_ad_reply, error_handler=self._register_ad_error
            )

            logger.info("Advertisement 注册成功")

        except Exception as e:
            logger.error(f"注册 Advertisement 失败: {e}")
            raise

    def notify_status(self, status_dict: dict):
        """发送状态通知"""
        self.service.notify_status(status_dict)

    def run(self):
        """运行 BLE Server"""
        try:
            self.register_app()
            self.register_ad()
            logger.info("BLE GATT Server 启动成功")
            self.mainloop.run()
        except KeyboardInterrupt:
            logger.info("收到中断信号")
        except Exception as e:
            logger.error(f"BLE Server 运行异常: {e}")
        finally:
            self.stop()

    def stop(self):
        """停止 BLE Server"""
        logger.info("停止 BLE GATT Server")
        if self.mainloop.is_running():
            self.mainloop.quit()

    def _find_adapter(self):
        """查找蓝牙适配器"""
        remote_om = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, "/"), "org.freedesktop.DBus.ObjectManager")
        objects = remote_om.GetManagedObjects()

        for o, props in objects.items():
            if GATT_MANAGER_IFACE in props:
                return o

        return None

    def get_device_mac_address(self) -> str:
        """获取蓝牙设备的 MAC 地址（带缓存）"""
        if self._mac_address is not None:
            return self._mac_address

        try:
            adapter_path = self._find_adapter()
            if not adapter_path:
                logger.warning("未找到蓝牙适配器，使用默认 MAC 地址")
                self._mac_address = "000000000000"
                return self._mac_address

            adapter_props = dbus.Interface(self.bus.get_object(BLUEZ_SERVICE_NAME, adapter_path), DBUS_PROP_IFACE)
            mac_address = adapter_props.Get("org.bluez.Adapter1", "Address")
            # 移除 MAC 地址中的冒号
            mac_address = mac_address.replace(":", "")
            self._mac_address = mac_address
            logger.debug(f"获取到蓝牙 MAC 地址: {mac_address}")
            return self._mac_address
        except Exception as e:
            logger.error(f"获取蓝牙 MAC 地址失败: {e}")
            self._mac_address = "000000000000"
            return self._mac_address

    def _register_app_reply(self):
        logger.info("GATT Application 注册回调成功")

    def _register_app_error(self, error):
        logger.error(f"GATT Application 注册失败: {error}")
        self.mainloop.quit()

    def _register_ad_reply(self):
        logger.info("Advertisement 注册回调成功")

    def _register_ad_error(self, error):
        logger.error(f"Advertisement 注册失败: {error}")
        self.mainloop.quit()
