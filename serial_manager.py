#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import serial
import threading
import queue
import logging
from typing import Optional, Callable
logger = logging.getLogger(__name__)

SERIAL_PORT = "/dev/ttyS6"
BAUD = 115200
DATA_BIT = 8
STOP_BIT = 1
PARITY = serial.PARITY_NONE

class SerialManager:
    def __init__(self, port: str = SERIAL_PORT, baudrate: int = BAUD):
        self.port = port
        self.baudrate = baudrate
        self.data_bit = DATA_BIT
        self.stop_bit = STOP_BIT
        self.parity = PARITY
        self.ser: Optional[serial.Serial] = None
        self.serial_lock = threading.Lock()
        self.state_callback: Optional[Callable[[str], None]] = None
        self.send_queue = queue.Queue(maxsize=10)
        self.switch_state = "idle"

    def set_state_callback(self, cb: Callable[[str], None]):
        """注册串口状态上报回调"""
        self.state_callback = cb

    def start(self):
        """启动串口读写线程"""
        try:
            self.ser = serial.Serial(
                port=self.port,
                baudrate=self.baudrate,
                bytesize=self.data_bit,
                stopbits=self.stop_bit,
                parity=self.parity,
                timeout=0.1,
                write_timeout=0.5
            )
            logger.info(f"串口启动成功 {self.port}@{self.baudrate} 8N1")
            self.running = True
            # 读线程
            threading.Thread(target=self._read_loop, daemon=True).start()
            # 写线程
            threading.Thread(target=self._write_loop, daemon=True).start()
            logger.info(f"串口启动成功 {self.port}@{self.baudrate}")
        except Exception as e:
            logger.error(f"串口打开失败: {e}")
            self.running = False

    def stop(self):
        """关闭串口，停止线程"""
        self.running = False
        if self.ser and self.ser.is_open:
            with self.serial_lock:
                self.ser.close()
            logger.info("串口已关闭")

    def send_cmd(self, cmd: str):
        """下发串口指令：cmd0 / cmd1"""
        if not self.running or not self.ser:
            logger.warning("串口未就绪，无法发送指令")
            return
        self.send_queue.put(cmd.strip())

    def _write_loop(self):
        """发送队列循环"""
        while self.running:
            try:
                cmd = self.send_queue.get(timeout=0.2)
                with self.serial_lock:
                    self.ser.write((cmd + "\r\n").encode("utf-8"))
                    logger.info(f"串口下发指令: {cmd}")
            except queue.Empty:
                continue
            except Exception as e:
                logger.error(f"串口发送异常: {e}")

    def _read_loop(self):
        """串口接收循环，解析on/off"""
        buf = bytearray()
        while self.running:
            try:
                with self.serial_lock:
                    data = self.ser.read(self.ser.in_waiting or 1)
                if not data:
                    continue
                buf.extend(data)
                # 按行分割解析
                lines = buf.split(b"\n")
                buf = lines.pop()
                for line in lines:
                    line_str = line.decode("utf-8", errors="ignore").strip().lower()
                    if line_str == "on":
                        self.switch_state = "on"
                        logger.info("串口收到状态: ON")
                        if self.state_callback:
                            self.state_callback("on")
                    elif line_str == "off":
                        self.switch_state = "off"
                        logger.info("串口收到状态: OFF")
                        if self.state_callback:
                            self.state_callback("off")
            except Exception as e:
                logger.debug(f"串口读取异常: {e}")