# BLE Device Server - Linux BLE GATT 

## Project Overview

这是一个运行在 Linux 开发板（如树莓派、ARM SBC）上的 **BLE GATT Server**，用于与微信小程序进行蓝牙通信，实现：

-  **WiFi 配网** - 通过 BLE 配置 WiFi 并自动连接
-  **云端配置** - 配置图片上传服务器地址
-  **远程拍照** - 接收拍照指令并上传到云端
-  **状态通知** - 实时推送设备状态（BLE/WiFi/运行状态）

---

## 系统架构

```
┌─────────────────────────────────────┐
│      微信小程序（BLE Client）        │
└──────────────┬──────────────────────┘
               │ BLE GATT
               ▼
┌──────────────────────────────────────┐
│       BLE GATT Server                │
│  ┌────────────────────────────────┐  │
│  │  Device Control Service        │  │
│  │  - WiFi Config (Write)         │  │
│  │  - Cloud Config (Write)        │  │
│  │  - Capture Command (Write)     │  │
│  │  - Status Notify (Notify)      │  │
│  └────────────────────────────────┘  │
└──────────────┬───────────────────────┘
               │
    ┌──────────┼──────────┐
    │          │          │
    ▼          ▼          ▼
┌────────┐ ┌────────┐ ┌────────┐
│ WiFi   │ │Camera  │ │ Cloud  │
│Manager │ │Control │ │Uploader│
└────────┘ └────────┘ └────────┘
```

---

##  系统要求

### 硬件要求
- Linux 开发板（树莓派 3/4/5、Orange Pi 等）
- 蓝牙 4.0+ (BLE)
- 摄像头（USB 或 CSI）
- WiFi 模块

### 软件要求
- **操作系统**: Ubuntu 20.04+ / Debian 11+ / Raspberry Pi OS
- **BlueZ**: 5.50+
- **Python**: 3.8+
- **NetworkManager**: 用于 WiFi 管理

---

## 快速部署

### 1. 一键安装

```bash
# 克隆或上传代码到开发板
cd /path/to/ble_device

# 运行安装脚本（需要 root 权限）
sudo ./install.sh
```

安装脚本会自动完成：
- 安装系统依赖（BlueZ、Python、NetworkManager 等）
- 安装摄像头工具（fswebcam、v4l-utils）
- 安装 Python 依赖包
- 配置 systemd 服务
- 启动 BLE 服务

### 2. 手动安装

```bash
# 1. 安装系统依赖
sudo apt update
sudo apt install -y bluez python3 python3-pip python3-dbus \
    python3-gi network-manager fswebcam v4l-utils libcairo2-dev pkg-config 

# 2. 安装 Python 依赖
sudo pip3 install --upgrade pip setuptools wheel
sudo pip3 install --break-system-packages -r requirements.txt

# 3. 复制文件到安装目录
sudo mkdir -p /opt/ble_device
sudo cp *.py /opt/ble_device/
sudo chmod +x /opt/ble_device/ble_device_server.py

# 4. 配置 systemd 服务
sudo cp ble-device.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable ble-device
sudo systemctl start ble-device
```

---

## 使用说明

### 服务管理

```bash
# 查看服务状态
sudo systemctl status ble-device

# 查看实时日志
sudo journalctl -u ble-device -f

# 重启服务
sudo systemctl restart ble-device

# 停止服务
sudo systemctl stop ble-device

# 禁用开机自启
sudo systemctl disable ble-device
```

### BLE GATT 协议说明

#### Service UUID
```
12345678-1234-5678-1234-56789abcdef0
```

#### Characteristics

| Characteristic | UUID | 属性 | 功能 |
|---------------|------|------|------|
| WiFi Config | ...def1 | Write | WiFi 配网 |
| Cloud Config | ...def2 | Write | 云端 URL 配置 |
| Capture Command | ...def3 | Write | 拍照指令 |
| Status Notify | ...def4 | Notify | 状态推送 |

---

### 数据格式

#### 1. WiFi 配网（Write to ...def1）

```json
{
  "ssid": "YourWiFiName",
  "password": "YourPassword"
}
```

**响应（Notify）**:
```json
{
  "wifi_state": "connected",
  "wifi_ssid": "YourWiFiName",
  "wifi_ip": "192.168.1.100",
  "timestamp": 1234567890.123
}
```

---

#### 2. 云端配置（Write to ...def2）

```json
{
  "upload_url": "https://your-server.com/api/upload"
}
```

**响应（Notify）**:
```json
{
  "event": "cloud_config_success",
  "upload_url": "https://your-server.com/api/upload",
  "timestamp": 1234567890.123
}
```

---

#### 3. 拍照指令（Write to ...def3）

```json
{
  "command": "capture"
}
```

**响应（Notify）**:
```json
// 拍照开始
{
  "event": "capture_start",
  "device_state": "capturing",
  "timestamp": 1234567890.123
}

// 拍照完成
{
  "event": "capture_success",
  "file": "capture_20240101_120000.jpg",
  "device_state": "uploading",
  "timestamp": 1234567890.124
}

// 上传完成
{
  "event": "upload_success",
  "device_state": "idle",
  "timestamp": 1234567890.130
}
```

---

#### 4. 状态通知（Notify from ...def4）

```json
{
  "ble_state": "connected",
  "wifi_state": "connected",
  "device_state": "idle",
  "ready_for_capture": true,
  "timestamp": 1234567890.123
}
```

**状态枚举**:
- `ble_state`: `advertising` | `connected` | `authenticated`
- `wifi_state`: `unconfigured` | `connecting` | `connected` | `failed`
- `device_state`: `idle` | `capturing` | `uploading` | `error`

---

## 故障排查

### 问题 1: 服务无法启动

```bash
# 查看详细错误日志
sudo journalctl -u ble-device -n 50

# 检查蓝牙状态
sudo systemctl status bluetooth
sudo hciconfig -a

# 检查 Python 依赖
python3 -c "import dbus; import gi; print('OK')"
```

### 问题 2: 微信小程序无法发现设备

```bash
# 检查蓝牙广播
sudo hcitool lescan

# 手动启动广播
sudo hciconfig hci0 up
sudo hciconfig hci0 piscan

# 检查防火墙
sudo ufw status
```

### 问题 3: WiFi 连接失败

```bash
# 检查 NetworkManager
sudo systemctl status NetworkManager

# 手动测试连接
sudo nmcli device wifi connect "YourSSID" password "YourPassword"

# 查看已保存的连接
sudo nmcli connection show
```

### 问题 4: 摄像头拍照失败

```bash
# 检查摄像头设备
ls -l /dev/video*

# 测试摄像头
fswebcam -d /dev/video0 test.jpg

# 检查权限
sudo usermod -aG video root
```

---

## 文件结构

```
/opt/ble_device/                    # 安装目录
├── ble_device_server.py            # 主程序
├── ble_gatt_server.py              # BLE GATT Server
├── wifi_manager.py                 # WiFi 管理
├── camera_controller.py            # 摄像头控制
├── cloud_uploader.py               # 云端上传
├── config_manager.py               # 配置管理
├── state_machine.py                # 状态机
└── requirements.txt                # Python 依赖

/var/lib/ble_device/                # 配置目录
└── config.json                     # 配置文件

/var/log/                           # 日志目录
└── ble_device.log                  # 日志文件

/etc/systemd/system/                # 服务目录
└── ble-device.service              # systemd 服务
```

---

## 安全建议

### 1. 添加认证机制

在 `BLEState` 中增加 `AUTHENTICATED` 状态，要求配对后才能执行敏感操作：

```python
# 在 ble_gatt_server.py 中添加认证逻辑
def _check_authenticated(self):
    if self.state_machine.ble_state != BLEState.AUTHENTICATED:
        raise dbus.exceptions.DBusException(
            "org.bluez.Error.NotPermitted",
            "Authentication required"
        )
```

### 2. 加密通信

使用 BLE Pairing 和 Bonding 功能，确保数据加密传输。

### 3. 限制访问

```bash
# 修改 service 文件，使用非 root 用户
User=ble_user
Group=ble_user

# 创建专用用户
sudo useradd -r -s /bin/false ble_user
sudo usermod -aG bluetooth,video ble_user
```

---

## 扩展功能

### 1. 添加新的 Characteristic

在 `DeviceControlService` 中添加：

```python
# 例如：添加设备重启功能
class RebootCharacteristic(Characteristic):
    def __init__(self, bus, index, service, on_reboot: Callable):
        super().__init__(bus, index, "12345678-...-def5", ["write"], service)
        self.on_reboot = on_reboot
    
    def WriteValue(self, value, options):
        if self.on_reboot:
            self.on_reboot()
```

### 2. 多摄像头支持

修改 `camera_controller.py`：

```python
class CameraController:
    def __init__(self, devices: list = ["/dev/video0", "/dev/video1"]):
        self.devices = devices
        self.current_device = 0
    
    def switch_camera(self):
        self.current_device = (self.current_device + 1) % len(self.devices)
```

### 3. 视频流支持

集成 **Motion** 或 **FFmpeg** 进行视频流推送。

---

## 开发测试

### 单元测试

```bash
# 测试各模块
python3 config_manager.py
python3 state_machine.py
python3 wifi_manager.py
python3 camera_controller.py
python3 cloud_uploader.py
```

### 手动测试 BLE

使用 `gatttool` 或 `bluetoothctl` 进行测试：

```bash
# 扫描设备
sudo bluetoothctl scan on

# 连接设备
sudo bluetoothctl connect <MAC_ADDRESS>

# 列出服务
sudo gatttool -b <MAC_ADDRESS> --primary

# 写入数据
sudo gatttool -b <MAC_ADDRESS> --char-write-req \
    --handle=<HANDLE> --value=<HEX_VALUE>
```