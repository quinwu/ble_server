#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import subprocess
import time
import yaml
from threading import Event, Thread
from typing import Callable, Optional

from state_machine import WiFiState
import os

logger = logging.getLogger(__name__)

NETPLAN_CONFIG_PATH = "/etc/netplan/52-wlan0-init.yaml"

class WiFiManager:
    """WiFi 管理器 - 使用 systemd-networkd 进行配网"""

    def __init__(self, state_callback: Optional[Callable] = None, status_report_callback: Optional[Callable] = None):
        self.state_callback = state_callback
        self.status_report_callback = status_report_callback
        self._monitor_thread = None
        self._stop_event = Event()

        # 当前连接信息
        self.current_ssid = ""
        self.current_password = ""

    def connect(self, ssid: str, password: str, retry_times: int = 1) -> bool:
        """
        连接到指定 WiFi - 通过修改 Netplan 配置并重启
        
        注意：此方法成功返回 True 表示配置已写入并触发了重启。
        如果配置写入失败，返回 False。
        """
        self.current_ssid = ssid
        self.current_password = password

        logger.info(f"开始配置 WiFi: {ssid} (模式: Netplan + Reboot)")
        self._update_state(WiFiState.CONNECTING)

        try:
            # 1. 读取现有的 Netplan 配置
            if not os.path.exists(NETPLAN_CONFIG_PATH):
                logger.error(f"Netplan 配置文件不存在: {NETPLAN_CONFIG_PATH}")
                self._update_state(WiFiState.FAILED)
                return False

            with open(NETPLAN_CONFIG_PATH, 'r', encoding='utf-8') as f:
                try:
                    config = yaml.safe_load(f)
                except yaml.YAMLError as e:
                    logger.error(f"解析 Netplan YAML 失败: {e}")
                    self._update_state(WiFiState.FAILED)
                    return False
            
            if config is None:
                config = {}

            # 2. 构建 WiFi 配置结构
            # Netplan 结构通常为:
            # network:
            #   version: 2
            #   wifis:
            #     wlan0:  # 或者使用 match 规则
            #       access-points:
            #         "SSID_NAME":
            #           password: "PASSWORD"
            #       dhcp4: true
            
            if 'network' not in config:
                config['network'] = {'version': 2}
            
            if 'wifis' not in config['network']:
                config['network']['wifis'] = {}

            # 确定无线接口名称。通常可能是 wlan0, wlps2s0 等。
            # 为了通用性，我们可以尝试获取当前系统的无线接口名，或者使用 match 规则。
            # 这里假设使用通用的 wlan0，或者如果原文件中有定义，保留原结构。
            # 更稳健的做法是使用 match 规则匹配所有 wifi 设备，或者检测当前接口名。
            
            # 简单策略：检测当前存在的 wifi 接口名
            iface_name = self._get_wifi_interface_name()
            if not iface_name:
                logger.warning("未检测到具体的 WiFi 接口名，默认使用 'wlan0'，可能需要根据硬件调整")
                iface_name = "wlan0"

            # 初始化该接口的配置字典
            if iface_name not in config['network']['wifis']:
                config['network']['wifis'][iface_name] = {}
            
            iface_config = config['network']['wifis'][iface_name]
            
            # 确保 access-points 存在
            if 'access-points' not in iface_config:
                iface_config['access-points'] = {}
            
            # 设置 SSID 和密码
            # 注意：YAML 中 SSID 如果包含特殊字符可能需要引号，pyyaml 会处理
            iface_config['access-points'][ssid] = {
                'password': password
            }
            
            # 确保开启 DHCP
            if 'dhcp4' not in iface_config:
                iface_config['dhcp4'] = True
                
            # 可选：设置 renderer 为 NetworkManager 如果系统混用，但纯 netplan 通常不需要或设为 networkd
            # 如果原文件有 renderer，保持不变；如果没有，且系统是 Ubuntu Server，通常默认 networkd
            # 如果系统是 Desktop 版 Ubuntu，可能需要 renderer: NetworkManager
            # 这里我们尽量不改动 renderer，除非原本没有
            
            # 3. 写回配置文件
            # 先备份
            backup_path = f"{NETPLAN_CONFIG_PATH}.bak"
            try:
                subprocess.run(["cp", NETPLAN_CONFIG_PATH, backup_path], check=True, timeout=5)
                logger.info(f"已备份原配置到 {backup_path}")
            except Exception as e:
                logger.warning(f"备份配置失败: {e}")

            # 写入新配置
            with open(NETPLAN_CONFIG_PATH, 'w', encoding='utf-8') as f:
                yaml.dump(config, f, default_flow_style=False, sort_keys=False)
            
            logger.info(f"Netplan 配置已更新: SSID={ssid}, Interface={iface_name}")

            # 4. 应用配置并重启
            # 先尝试 apply，如果 apply 成功再重启，或者直接重启让 netplan 在启动时应用
            # 直接重启更彻底，避免 apply 可能带来的网络瞬间中断导致 SSH 断开无法执行后续命令
            logger.info("准备重启设备以应用新的 WiFi 配置...")
            self._update_state(WiFiState.CONNECTED) # 标记为已连接（预期行为）
            
            # 异步执行重启，确保日志能刷出来
            def delayed_reboot():
                time.sleep(2) # 等待2秒让日志写入
                logger.warning(">>> 执行系统重启 <<<")
                try:
                    # 使用 systemd reboot 或 shutdown
                    subprocess.run(["reboot"], check=False)
                except Exception as e:
                    logger.error(f"重启命令执行异常: {e}")
                    # 尝试备用重启命令
                    subprocess.run(["shutdown", "-r", "now"], check=False)

            reboot_thread = Thread(target=delayed_reboot, daemon=True)
            reboot_thread.start()
            
            return True

        except Exception as e:
            logger.error(f"配置 WiFi 过程中发生错误: {e}", exc_info=True)
            self._update_state(WiFiState.FAILED)
            return False
    def _get_wifi_interface_name(self) -> Optional[str]:
        """获取第一个 WiFi 接口名称"""
        try:
            result = subprocess.run(
                ["ls", "/sys/class/net"],
                capture_output=True, text=True, timeout=5
            )
            if result.returncode != 0:
                return None
            
            interfaces = result.stdout.strip().split('\n')
            for iface in interfaces:
                # 检查是否为无线接口
                phy_path = f"/sys/class/net/{iface}/wireless"
                if os.path.exists(phy_path):
                    return iface
        except Exception as e:
            logger.error(f"获取 WiFi 接口名异常: {e}")
        
        return None

    # def disconnect(self) -> bool:
    #     """断开当前 WiFi 连接"""
    #     try:
    #         # 停止监控
    #         self.stop_monitoring()

    #         # 断开连接
    #         result = subprocess.run(
    #             ["nmcli", "connection", "down", self.current_ssid], capture_output=True, text=True, timeout=10
    #         )

    #         if result.returncode == 0:
    #             logger.info(f"WiFi 已断开: {self.current_ssid}")
    #             self._update_state(WiFiState.UNCONFIGURED)
    #             return True
    #         else:
    #             logger.warning(f"WiFi 断开失败: {result.stderr}")
    #             return False

    #     except Exception as e:
    #         logger.error(f"WiFi 断开异常: {e}")
    #         return False

    # def get_status(self) -> dict:
    #     """获取 WiFi 状态"""
    #     try:
    #         # 使用 device status 检查实际的 WiFi 设备连接状态（更准确）
    #         # 而不是 connection show（只检查连接配置）
    #         result = subprocess.run(
    #             ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"],
    #             capture_output=True,
    #             text=True,
    #             timeout=5,
    #         )

    #         if result.returncode == 0:
    #             lines = result.stdout.strip().split("\n")
    #             for line in lines:
    #                 if not line:
    #                     continue
    #                 parts = line.split(":")
    #                 # 格式: DEVICE:TYPE:STATE:CONNECTION
    #                 # 例如: wlan0:wifi:connected:danhuang
    #                 if len(parts) >= 4 and parts[1] == "wifi":
    #                     device = parts[0]
    #                     state = parts[2]
    #                     connection = parts[3] if len(parts) > 3 else ""

    #                     # 检查设备状态是否为 connected
    #                     if state == "connected" and connection:
    #                         # 获取 SSID（CONNECTION 字段就是连接名称，通常等于 SSID）
    #                         ssid = connection
    #                         return {"connected": True, "ssid": ssid, "ip": self._get_ip_address()}

    #         # 如果没有找到连接的 WiFi 设备，返回未连接状态
    #         return {"connected": False, "ssid": "", "ip": ""}

    #     except Exception as e:
    #         logger.error(f"获取 WiFi 状态异常: {e}")
    #         return {"connected": False, "ssid": "", "ip": ""}
    
    def get_status(self) -> dict:
        """获取 WiFi 状态 - 增强版：结合 nmcli 和 IP 检测"""
        ssid = ""
        ip = ""
        is_connected = False

        # 方法 1: 尝试从 nmcli 获取详细信息
        # try:
        #     # 强制使用 C 语言环境，避免解析错误
        #     env = os.environ.copy()
        #     env['LC_ALL'] = 'C'
            
        #     result = subprocess.run(
        #         ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE,CONNECTION", "device", "status"],
        #         capture_output=True, text=True, timeout=5,
        #         env=env
        #     )
        #     if result.returncode == 0:
        #         lines = result.stdout.strip().split("\n")
        #         for line in lines:
        #             if not line: continue
        #             parts = line.split(":")
        #             # 调试日志：打印原始解析结果，方便排查
        #             # logger.debug(f"nmcli parse: {parts}")
                    
        #             if len(parts) >= 3 and parts[1].strip() == "wifi":
        #                 device = parts[0].strip()
        #                 state = parts[2].strip()
        #                 connection = parts[3].strip() if len(parts) > 3 else ""

        #                 # 只要状态是 connected，即便 connection 名字为空，也先标记为潜在连接
        #                 if state == "connected":
        #                     is_connected = True
        #                     ssid = connection if connection else self._get_ssid_from_iw(device)
        #                     break
        #                 # 如果状态是 connecting 或 ip-config，也可以视为正在连接
        #                 elif state in ["connecting", "ip-config", "ip-check"]:
        #                     is_connected = False # 暂时视为未完全连接
        # except Exception as e:
        #     logger.debug(f"nmcli 检测异常: {e}")

        # 方法 2: 【关键兜底】如果 nmcli 没检测到，检查是否有 IP 地址
        # 适用于 Netplan/networkd 接管了网络，但 nmcli 状态不同步的情况
        if not is_connected:
            try:
                iface = self._get_wifi_interface_name() or "wlan0"
                ip_result = subprocess.run(
                    ["ip", "-j", "addr", "show", iface],
                    capture_output=True, text=True, timeout=5
                )
                if ip_result.returncode == 0:
                    import json
                    data = json.loads(ip_result.stdout)
                    for addr_info in data:
                        # 检查是否有 inet (IPv4) 地址，且不是 169.254.x.x (APIPA/无效IP)
                        for addr in addr_info.get("addr_info", []):
                            if addr["family"] == "inet" and not addr["local"].startswith("169.254"):
                                is_connected = True
                                ip = addr["local"]
                                # 尝试从 iw 获取 SSID
                                ssid = self._get_ssid_from_iw(iface)
                                # logger.info(f"nmcli 未报告连接，但检测到有效 IP: {ip}，判定为已连接")
                                break
                        if is_connected: break
            except Exception as e:
                logger.debug(f"IP 检测异常: {e}")

        # 如果连上了但还没获取到 IP，再试一次 hostname
        if is_connected and not ip:
            ip = self._get_ip_address()

        return {
            "connected": is_connected, 
            "ssid": ssid, 
            "ip": ip
        }

    def _get_ssid_from_iw(self, interface: str) -> str:
        """通过 iw 命令获取当前连接的 SSID"""
        try:
            res = subprocess.run(["iw", "dev", interface, "info"], 
                                 capture_output=True, text=True, timeout=5)
            for line in res.stdout.split('\n'):
                if 'ssid' in line.lower():
                    return line.split('ssid ')[-1].strip()
        except:
            pass
        return ""

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

    # def _ensure_wifi_enabled(self) -> bool:
    #     """确保WiFi设备已启用"""
    #     try:
    #         # 检查WiFi设备状态
    #         result = subprocess.run(
    #             ["nmcli", "-t", "-f", "DEVICE,TYPE,STATE", "device", "status"],
    #             capture_output=True,
    #             text=True,
    #             timeout=5,
    #         )

    #         if result.returncode != 0:
    #             logger.error("无法获取设备状态")
    #             return False

    #         # 查找WiFi设备
    #         wifi_device = None
    #         for line in result.stdout.strip().split("\n"):
    #             if not line:
    #                 continue
    #             parts = line.split(":")
    #             if len(parts) >= 3 and parts[1] == "wifi":
    #                 wifi_device = parts[0]
    #                 state = parts[2]

    #                 # 如果设备未连接或未启用，尝试启用
    #                 if state in ["unavailable", "disconnected"]:
    #                     logger.info(f"启用 WiFi 设备: {wifi_device}")
    #                     enable_result = subprocess.run(
    #                         ["nmcli", "radio", "wifi", "on"], capture_output=True, text=True, timeout=5
    #                     )
    #                     if enable_result.returncode == 0:
    #                         # 等待设备就绪
    #                         time.sleep(2)
    #                         logger.info(f"WiFi 设备已启用: {wifi_device}")
    #                     else:
    #                         logger.warning(f"启用 WiFi 设备失败: {enable_result.stderr}")

    #                 return True  # 找到WiFi设备

    #         if wifi_device is None:
    #             logger.error("未找到 WiFi 设备")
    #             return False

    #         return True

    #     except Exception as e:
    #         logger.error(f"检查 WiFi 设备状态异常: {e}")
    #         return False

    # def _is_connection_exists(self, ssid: str) -> bool:
    #     """检查连接配置是否存在"""
    #     return self._get_connection_name(ssid) is not None

    # def _get_connection_name(self, ssid: str) -> Optional[str]:
    #     """根据 SSID 获取连接名称"""
    #     try:
    #         # 获取所有 WiFi 连接配置
    #         result = subprocess.run(
    #             ["nmcli", "-t", "-f", "NAME,802-11-wireless.ssid", "connection", "show"],
    #             capture_output=True,
    #             text=True,
    #             timeout=5,
    #         )

    #         if result.returncode != 0:
    #             return None

    #         # 解析输出，查找匹配的 SSID
    #         for line in result.stdout.strip().split("\n"):
    #             if not line:
    #                 continue
    #             parts = line.split(":")
    #             if len(parts) >= 2:
    #                 conn_name = parts[0]
    #                 conn_ssid = parts[1] if len(parts) > 1 else ""
    #                 if conn_ssid == ssid:
    #                     return conn_name

    #         # 如果没找到，尝试直接使用 SSID 作为连接名称（向后兼容）
    #         # 某些情况下连接名称就是 SSID
    #         name_result = subprocess.run(
    #             ["nmcli", "-t", "-f", "NAME", "connection", "show"], capture_output=True, text=True, timeout=5
    #         )
    #         if name_result.returncode == 0 and ssid in name_result.stdout:
    #             return ssid

    #         return None

    #     except Exception as e:
    #         logger.error(f"获取连接名称异常: {e}")
    #         return None

    # def _activate_connection(self, ssid: str) -> bool:
    #     """激活已存在的连接"""
    #     try:
    #         # 首先获取连接名称（可能和 SSID 不同）
    #         connection_name = self._get_connection_name(ssid)
    #         if not connection_name:
    #             logger.error(f"未找到 SSID '{ssid}' 对应的连接配置")
    #             return False

    #         logger.debug(f"激活连接: {connection_name} (SSID: {ssid})")
    #         result = subprocess.run(
    #             ["nmcli", "connection", "up", connection_name], capture_output=True, text=True, timeout=30
    #         )

    #         if result.returncode == 0:
    #             # 等待连接建立（最多等待 5 秒）
    #             for _ in range(10):
    #                 time.sleep(0.5)
    #                 status = self.get_status()
    #                 if status["connected"] and status["ssid"] == ssid:
    #                     logger.info(f"连接已激活: {ssid}")
    #                     return True
    #             logger.warning(f"连接激活命令成功，但未检测到连接状态: {ssid}")
    #             return False
    #         else:
    #             logger.error(f"激活连接失败: {result.stderr.strip()}")
    #             return False

    #     except subprocess.TimeoutExpired:
    #         logger.error(f"激活连接超时: {ssid}")
    #         return False
    #     except Exception as e:
    #         logger.error(f"激活连接异常: {e}")
    #         return False

    # def _create_and_connect(self, ssid: str, password: str) -> bool:
    #     """创建并连接到新的 WiFi"""
    #     process = None
    #     try:
    #         # 使用 nmcli device wifi connect（异步方式）
    #         logger.info(f"启动 WiFi 连接命令: {ssid}")
    #         process = subprocess.Popen(
    #             ["nmcli", "device", "wifi", "connect", ssid, "password", password],
    #             stdout=subprocess.PIPE,
    #             stderr=subprocess.PIPE,
    #             text=True,
    #         )

    #         # 轮询检查连接状态，最多等待60秒
    #         max_wait_time = 60
    #         check_interval = 2
    #         elapsed_time = 0

    #         while elapsed_time < max_wait_time:
    #             # 检查进程是否已完成
    #             return_code = process.poll()
    #             if return_code is not None:
    #                 # 进程已完成，读取输出
    #                 stdout, stderr = process.communicate()
    #                 logger.info(f"WiFi 连接命令完成，返回码: {return_code}")
    #                 if stdout:
    #                     logger.debug(f"命令输出: {stdout.strip()}")
    #                 if stderr:
    #                     logger.debug(f"命令错误输出: {stderr.strip()}")

    #                 if return_code == 0:
    #                     logger.info(f"WiFi 连接命令执行成功: {ssid}")
    #                     # 等待一下确保连接建立
    #                     time.sleep(3)
    #                     # 验证连接状态
    #                     status = self.get_status()
    #                     logger.info(f"连接状态检查: connected={status['connected']}, ssid={status['ssid']}")
    #                     if status["connected"] and status["ssid"] == ssid:
    #                         logger.info(f"WiFi 连接验证成功: {ssid}")
    #                         return True
    #                     else:
    #                         logger.warning(f"连接命令成功但状态验证失败: {ssid}, 当前状态: {status}")
    #                         # 即使状态验证失败，也再等待一下，可能连接还在建立中
    #                         time.sleep(2)
    #                         status = self.get_status()
    #                         if status["connected"] and status["ssid"] == ssid:
    #                             logger.info(f"延迟检查后连接成功: {ssid}")
    #                             return True
    #                 else:
    #                     logger.error(
    #                         f"WiFi 连接命令失败 (返回码 {return_code}): {stderr.strip() if stderr else '无错误输出'}"
    #                     )
    #                     # 即使命令失败，也检查一下状态（可能连接已建立）
    #                     status = self.get_status()
    #                     if status["connected"] and status["ssid"] == ssid:
    #                         logger.info(f"命令失败但连接已建立: {ssid}")
    #                         return True
    #                     return False

    #             # 检查连接状态（可能在命令完成前就已连接）
    #             status = self.get_status()
    #             if status["connected"] and status["ssid"] == ssid:
    #                 logger.info(f"WiFi 连接已建立（命令仍在运行）: {ssid}")
    #                 # 终止进程（如果还在运行）
    #                 if process.poll() is None:
    #                     process.terminate()
    #                     try:
    #                         process.wait(timeout=2)
    #                     except subprocess.TimeoutExpired:
    #                         process.kill()
    #                 return True

    #             time.sleep(check_interval)
    #             elapsed_time += check_interval
    #             if elapsed_time % 10 == 0:
    #                 logger.debug(f"等待 WiFi 连接中... ({elapsed_time}/{max_wait_time}秒)")

    #         # 超时，检查进程状态
    #         logger.warning(f"WiFi 连接超时: {ssid}")
    #         return_code = process.poll()
    #         if return_code is None:
    #             # 进程仍在运行，终止它
    #             logger.info("终止仍在运行的连接进程")
    #             process.terminate()
    #             try:
    #                 stdout, stderr = process.communicate(timeout=2)
    #                 if stdout:
    #                     logger.debug(f"终止后的输出: {stdout.strip()}")
    #                 if stderr:
    #                     logger.debug(f"终止后的错误输出: {stderr.strip()}")
    #             except subprocess.TimeoutExpired:
    #                 process.kill()
    #                 logger.warning("强制终止连接进程")
    #         else:
    #             # 进程已完成，读取输出
    #             stdout, stderr = process.communicate()
    #             logger.info(f"超时时进程已完成，返回码: {return_code}")
    #             if stdout:
    #                 logger.debug(f"进程输出: {stdout.strip()}")
    #             if stderr:
    #                 logger.debug(f"进程错误输出: {stderr.strip()}")

    #         # 最后检查一次状态
    #         status = self.get_status()
    #         logger.info(f"超时后最终状态检查: connected={status['connected']}, ssid={status['ssid']}")
    #         if status["connected"] and status["ssid"] == ssid:
    #             logger.info(f"超时后检查发现连接已建立: {ssid}")
    #             return True

    #         return False

    #     except Exception as e:
    #         logger.error(f"创建连接异常: {e}", exc_info=True)
    #         if process and process.poll() is None:
    #             try:
    #                 process.terminate()
    #                 process.wait(timeout=2)
    #             except:
    #                 process.kill()
    #         return False

    # def _create_and_connect_alternative(self, ssid: str, password: str) -> bool:
    #     """备用连接方法：使用 nmcli connection add + up（更可靠但更慢）"""
    #     try:
    #         logger.info(f"使用备用方法创建 WiFi 连接: {ssid}")

    #         # 步骤1: 创建连接配置
    #         logger.info(f"创建连接配置: {ssid}")
    #         add_result = subprocess.run(
    #             [
    #                 "nmcli",
    #                 "connection",
    #                 "add",
    #                 "type",
    #                 "wifi",
    #                 "con-name",
    #                 ssid,
    #                 "ifname",
    #                 "*",
    #                 "ssid",
    #                 ssid,
    #                 "wifi-sec.key-mgmt",
    #                 "wpa-psk",
    #                 "wifi-sec.psk",
    #                 password,
    #             ],
    #             capture_output=True,
    #             text=True,
    #             timeout=10,
    #         )

    #         if add_result.returncode != 0:
    #             # 如果连接已存在，尝试删除后重新创建
    #             if "already exists" in add_result.stderr.lower():
    #                 logger.info(f"连接配置已存在，尝试删除后重新创建: {ssid}")
    #                 subprocess.run(["nmcli", "connection", "delete", ssid], capture_output=True, timeout=5)
    #                 # 重新创建
    #                 add_result = subprocess.run(
    #                     [
    #                         "nmcli",
    #                         "connection",
    #                         "add",
    #                         "type",
    #                         "wifi",
    #                         "con-name",
    #                         ssid,
    #                         "ifname",
    #                         "*",
    #                         "ssid",
    #                         ssid,
    #                         "wifi-sec.key-mgmt",
    #                         "wpa-psk",
    #                         "wifi-sec.psk",
    #                         password,
    #                     ],
    #                     capture_output=True,
    #                     text=True,
    #                     timeout=10,
    #                 )

    #             if add_result.returncode != 0:
    #                 logger.error(f"创建连接配置失败: {add_result.stderr.strip()}")
    #                 return False

    #         logger.info(f"连接配置创建成功: {ssid}")

    #         # 步骤2: 激活连接
    #         logger.info(f"激活连接: {ssid}")
    #         up_result = subprocess.run(["nmcli", "connection", "up", ssid], capture_output=True, text=True, timeout=30)

    #         if up_result.returncode != 0:
    #             logger.error(f"激活连接失败: {up_result.stderr.strip()}")
    #             return False

    #         logger.info(f"连接激活命令执行成功: {ssid}")

    #         # 步骤3: 等待并验证连接
    #         max_wait = 20
    #         for i in range(max_wait):
    #             time.sleep(1)
    #             status = self.get_status()
    #             if status["connected"] and status["ssid"] == ssid:
    #                 logger.info(f"备用方法连接成功: {ssid}")
    #                 return True
    #             if i % 5 == 0:
    #                 logger.debug(f"等待连接建立... ({i}/{max_wait}秒)")

    #         # 最终检查
    #         status = self.get_status()
    #         if status["connected"] and status["ssid"] == ssid:
    #             logger.info(f"备用方法最终验证成功: {ssid}")
    #             return True

    #         logger.warning(f"备用方法连接失败，状态验证未通过: {ssid}")
    #         return False

    #     except subprocess.TimeoutExpired as e:
    #         logger.error(f"备用连接方法超时: {e}")
    #         return False
    #     except Exception as e:
    #         logger.error(f"备用连接方法异常: {e}", exc_info=True)
    #         return False

    def _get_ip_address(self) -> str:
        """获取当前 IP 地址"""
        try:
            result = subprocess.run(["hostname", "-I"], capture_output=True, text=True, timeout=5)
            return result.stdout.strip().split()[0] if result.returncode == 0 else ""
        except Exception as e:
            logger.error(f"获取 IP 异常: {e}")
            return ""

    def _monitor_loop(self) -> None:
        """WiFi 连接监控循环"""
        consecutive_failures = 0
        # 等待5秒后开始监控
        self._stop_event.wait(2)

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

                    # if consecutive_failures >= 3:
                    #     # 尝试重连
                    #     logger.info("尝试自动重连 WiFi")
                    #     if self.current_ssid and self.current_password:
                    #         self._update_state(WiFiState.CONNECTING)
                    #         self.connect(self.current_ssid, self.current_password)
                    #     else:
                    #         logger.error("无法重连：缺少 WiFi 配置信息")
                    #     consecutive_failures = 0
                    if consecutive_failures >= 3:
                         if self.state_callback:
                            self._update_state(WiFiState.DISCONNECTED)

                # 定期通过 BLE 上报 WiFi 状态（即使状态未变化）
                if self.status_report_callback:
                    try:
                        self.status_report_callback(status)
                    except Exception as e:
                        logger.error(f"WiFi 状态上报回调异常: {e}")

            except Exception as e:
                logger.error(f"WiFi 监控异常: {e}", exc_info=True)

            # 每 30 秒检查一次
            self._stop_event.wait(30)

    def _update_state(self, state: WiFiState) -> None:
        """更新 WiFi 状态"""
        if self.state_callback:
            try:
                self.state_callback(state)
            except Exception as e:
                logger.error(f"WiFi 状态回调异常: {e}")


if __name__ == "__main__":
    # 测试代码
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    def state_changed(state):
        print(f"WiFi 状态变化: {state.value}")

    wifi = WiFiManager(state_callback=state_changed)

    # 获取当前状态
    status = wifi.get_status()
    print(f"当前 WiFi 状态: {status}")

    # 测试连接（请替换为真实的 WiFi 信息）
    # wifi.connect("YourWiFiSSID", "YourPassword")
