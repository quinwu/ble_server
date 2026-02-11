#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
BLE GATT Server base on BlueZ D-Bus API
"""

import dbus
import dbus.service
import dbus.mainloop.glib
from gi.repository import GLib
import json
import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# GATT Service 和 Characteristic UUIDs
DEVICE_CONTROL_SERVICE_UUID = "12345678-1234-5678-1234-56789abcdef0"
CHAR_WIFI_CONFIG_UUID = "12345678-1234-5678-1234-56789abcdef1"
CHAR_CLOUD_CONFIG_UUID = "12345678-1234-5678-1234-56789abcdef2"
CHAR_CAPTURE_COMMAND_UUID = "12345678-1234-5678-1234-56789abcdef3"
CHAR_STATUS_NOTIFY_UUID = "12345678-1234-5678-1234-56789abcdef4"

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
                "Characteristics": dbus.Array(
                    self.get_characteristic_paths(),
                    signature="o"
                )
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
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs",
                "Invalid interface"
            )
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
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs",
                "Invalid interface"
            )
        return self.get_properties()[GATT_CHARACTERISTIC_IFACE]
    
    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="a{sv}", out_signature="ay")
    def ReadValue(self, options):
        logger.warning(f"ReadValue not implemented for {self.uuid}")
        raise dbus.exceptions.DBusException(
            "org.bluez.Error.NotSupported",
            "Read not supported"
        )
    
    @dbus.service.method(GATT_CHARACTERISTIC_IFACE, in_signature="aya{sv}")
    def WriteValue(self, value, options):
        logger.warning(f"WriteValue not implemented for {self.uuid}")
        raise dbus.exceptions.DBusException(
            "org.bluez.Error.NotSupported",
            "Write not supported"
        )
    
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
        
        self.PropertiesChanged(
            GATT_CHARACTERISTIC_IFACE,
            {"Value": dbus.Array(value, signature="y")},
            []
        )
        logger.debug(f"Notify sent: {value[:50]}...")


class WiFiConfigCharacteristic(Characteristic):
    
    def __init__(self, bus, index, service, on_wifi_config: Callable):
        super().__init__(bus, index, CHAR_WIFI_CONFIG_UUID, ["write"], service)
        self.on_wifi_config = on_wifi_config
    
    def WriteValue(self, value, options):
        try:
            # 解析 JSON
            value_str = bytearray(value).decode("utf-8")
            logger.info(f"收到 WiFi 配置: {value_str}")
            
            config = json.loads(value_str)
            ssid = config.get("ssid", "")
            password = config.get("password", "")
            
            if not ssid:
                raise ValueError("SSID 不能为空")
            
            # 触发回调
            if self.on_wifi_config:
                self.on_wifi_config(ssid, password)
            
        except json.JSONDecodeError as e:
            logger.error(f"WiFi 配置 JSON 解析失败: {e}")
            raise dbus.exceptions.DBusException(
                "org.bluez.Error.InvalidValueLength",
                "Invalid JSON format"
            )
        except Exception as e:
            logger.error(f"WiFi 配置处理失败: {e}")
            raise dbus.exceptions.DBusException(
                "org.bluez.Error.Failed",
                str(e)
            )


class CloudConfigCharacteristic(Characteristic):
    
    def __init__(self, bus, index, service, on_cloud_config: Callable):
        super().__init__(bus, index, CHAR_CLOUD_CONFIG_UUID, ["write"], service)
        self.on_cloud_config = on_cloud_config
    
    def WriteValue(self, value, options):
        try:
            value_str = bytearray(value).decode("utf-8")
            logger.info(f"收到云端配置: {value_str}")
            
            config = json.loads(value_str)
            upload_url = config.get("upload_url", "")
            
            if not upload_url:
                raise ValueError("upload_url 不能为空")
            
            # 触发回调
            if self.on_cloud_config:
                self.on_cloud_config(upload_url)
            
        except json.JSONDecodeError as e:
            logger.error(f"云端配置 JSON 解析失败: {e}")
            raise dbus.exceptions.DBusException(
                "org.bluez.Error.InvalidValueLength",
                "Invalid JSON format"
            )
        except Exception as e:
            logger.error(f"云端配置处理失败: {e}")
            raise dbus.exceptions.DBusException(
                "org.bluez.Error.Failed",
                str(e)
            )


class CaptureCommandCharacteristic(Characteristic):
    
    def __init__(self, bus, index, service, on_capture: Callable):
        super().__init__(bus, index, CHAR_CAPTURE_COMMAND_UUID, ["write"], service)
        self.on_capture = on_capture
    
    def WriteValue(self, value, options):
        try:
            value_str = bytearray(value).decode("utf-8")
            logger.info(f"收到拍照指令: {value_str}")
            
            command = json.loads(value_str)
            cmd = command.get("command", "")
            
            if cmd == "capture":
                # 触发回调
                if self.on_capture:
                    self.on_capture()
            else:
                raise ValueError(f"未知指令: {cmd}")
            
        except json.JSONDecodeError as e:
            logger.error(f"拍照指令 JSON 解析失败: {e}")
            raise dbus.exceptions.DBusException(
                "org.bluez.Error.InvalidValueLength",
                "Invalid JSON format"
            )
        except Exception as e:
            logger.error(f"拍照指令处理失败: {e}")
            raise dbus.exceptions.DBusException(
                "org.bluez.Error.Failed",
                str(e)
            )


class StatusNotifyCharacteristic(Characteristic):
    
    def __init__(self, bus, index, service):
        super().__init__(bus, index, CHAR_STATUS_NOTIFY_UUID, ["notify"], service)
    
    def notify_status(self, status_dict: dict):
        """发送状态通知"""
        try:
            # 转换为 JSON
            status_json = json.dumps(status_dict, ensure_ascii=False)
            value = [dbus.Byte(c) for c in status_json.encode("utf-8")]
            
            # 发送 Notify
            self.send_notify(value)
            logger.info(f"状态通知已发送: {status_json}")
            
        except Exception as e:
            logger.error(f"发送状态通知失败: {e}")


class DeviceControlService(Service):
    
    def __init__(
        self,
        bus,
        index,
        on_wifi_config: Callable,
        on_cloud_config: Callable,
        on_capture: Callable
    ):
        super().__init__(bus, index, DEVICE_CONTROL_SERVICE_UUID, True)
        
        # 添加 Characteristics
        self.add_characteristic(
            WiFiConfigCharacteristic(bus, 0, self, on_wifi_config)
        )
        self.add_characteristic(
            CloudConfigCharacteristic(bus, 1, self, on_cloud_config)
        )
        self.add_characteristic(
            CaptureCommandCharacteristic(bus, 2, self, on_capture)
        )
        
        # 状态通知 Characteristic（需要引用以便发送通知）
        self.status_notify_char = StatusNotifyCharacteristic(bus, 3, self)
        self.add_characteristic(self.status_notify_char)
    
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
            raise dbus.exceptions.DBusException(
                "org.freedesktop.DBus.Error.InvalidArgs",
                "Invalid interface"
            )
        return self.get_properties()[LE_ADVERTISEMENT_IFACE]
    
    @dbus.service.method(LE_ADVERTISEMENT_IFACE, in_signature="", out_signature="")
    def Release(self):
        logger.info(f"Advertisement released: {self.path}")


class BLEGattServer:
    
    def __init__(
        self,
        on_wifi_config: Callable,
        on_cloud_config: Callable,
        on_capture: Callable,
        device_name: str = "BLE-Device"
    ):
        # 初始化 D-Bus
        dbus.mainloop.glib.DBusGMainLoop(set_as_default=True)
        self.bus = dbus.SystemBus()
        
        # 回调函数
        self.on_wifi_config = on_wifi_config
        self.on_cloud_config = on_cloud_config
        self.on_capture = on_capture
        
        # 创建 Application
        self.app = Application(self.bus)
        
        # 创建 Service
        self.service = DeviceControlService(
            self.bus, 0,
            on_wifi_config,
            on_cloud_config,
            on_capture
        )
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
            
            service_manager = dbus.Interface(
                self.bus.get_object(BLUEZ_SERVICE_NAME, adapter_path),
                GATT_MANAGER_IFACE
            )
            
            service_manager.RegisterApplication(
                self.app.get_path(), {},
                reply_handler=self._register_app_reply,
                error_handler=self._register_app_error
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
                self.bus.get_object(BLUEZ_SERVICE_NAME, adapter_path),
                LE_ADVERTISING_MANAGER_IFACE
            )
            
            ad_manager.RegisterAdvertisement(
                self.ad.get_path(), {},
                reply_handler=self._register_ad_reply,
                error_handler=self._register_ad_error
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
        remote_om = dbus.Interface(
            self.bus.get_object(BLUEZ_SERVICE_NAME, "/"),
            "org.freedesktop.DBus.ObjectManager"
        )
        objects = remote_om.GetManagedObjects()
        
        for o, props in objects.items():
            if GATT_MANAGER_IFACE in props:
                return o
        
        return None
    
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
