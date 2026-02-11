# BLE Device Server - 架构设计文档

## 一、整体架构

### 1.1 系统层次

```
┌─────────────────────────────────────────────────────────────┐
│                    应用层（Application Layer）               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         BLE Device Server (ble_device_server.py)     │   │
│  │  - 主控制器                                           │   │
│  │  - 模块协调                                           │   │
│  │  - 异常处理                                           │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
                            ▲
                            │
┌───────────────────────────┼───────────────────────────────┐
│                    业务层（Business Layer）                 │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐          │
│  │ BLE GATT   │  │   State    │  │   Config   │          │
│  │  Server    │  │  Machine   │  │  Manager   │          │
│  └────────────┘  └────────────┘  └────────────┘          │
│                                                            │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐          │
│  │   WiFi     │  │  Camera    │  │   Cloud    │          │
│  │  Manager   │  │ Controller │  │  Uploader  │          │
│  └────────────┘  └────────────┘  └────────────┘          │
└────────────────────────────────────────────────────────────┘
                            ▲
                            │
┌───────────────────────────┼───────────────────────────────┐
│                  系统层（System Layer）                     │
│  ┌────────────┐  ┌────────────┐  ┌────────────┐          │
│  │   BlueZ    │  │ Network    │  │  V4L2 /    │          │
│  │  D-Bus API │  │  Manager   │  │  fswebcam  │          │
│  └────────────┘  └────────────┘  └────────────┘          │
└────────────────────────────────────────────────────────────┘
```

### 1.2 模块职责

#### 主控制器（Main Controller）
- **文件**: `ble_device_server.py`
- **职责**:
  - 初始化所有子模块
  - 协调模块间通信
  - 处理 BLE 回调事件
  - 全局异常捕获
  - 生命周期管理

#### BLE GATT Server
- **文件**: `ble_gatt_server.py`
- **职责**:
  - GATT Service/Characteristic 注册
  - BLE 广播管理
  - 数据读写处理
  - Notify 消息推送
  - D-Bus 接口封装

#### 状态机（State Machine）
- **文件**: `state_machine.py`
- **职责**:
  - 管理 BLE/WiFi/设备三大状态
  - 状态转换验证
  - 状态变化事件通知
  - 线程安全访问

#### WiFi 管理器（WiFi Manager）
- **文件**: `wifi_manager.py`
- **职责**:
  - WiFi 连接/断开
  - 连接状态监控
  - 自动重连机制
  - NetworkManager 封装

#### 摄像头控制器（Camera Controller）
- **文件**: `camera_controller.py`
- **职责**:
  - 图像采集
  - 多工具适配（fswebcam/v4l2/opencv）
  - 摄像头可用性检测
  - 图像质量控制

#### 云端上传器（Cloud Uploader）
- **文件**: `cloud_uploader.py`
- **职责**:
  - HTTP 文件上传
  - 重试机制
  - 连接测试
  - 分片上传支持

#### 配置管理器（Config Manager）
- **文件**: `config_manager.py`
- **职责**:
  - 配置持久化
  - JSON 序列化/反序列化
  - 配置验证
  - 默认值管理

---

## 二、数据流设计

### 2.1 WiFi 配网流程

```
微信小程序                BLE Server              WiFi Manager
    │                         │                         │
    │──写入 WiFi 配置────────>│                         │
    │  (SSID + Password)      │                         │
    │                         │──保存配置──────────────>│ Config
    │                         │                         │
    │                         │──启动连接──────────────>│
    │                         │                         │
    │                         │<─状态: CONNECTING ──────│
    │<─Notify: connecting ────│                         │
    │                         │                         │
    │                         │<─状态: CONNECTED ───────│
    │<─Notify: connected ─────│  (IP: 192.168.1.100)    │
    │  (wifi_state: connected)│                         │
```

### 2.2 拍照上传流程

```
微信小程序         BLE Server        Camera        Cloud
    │                  │                │              │
    │──写入拍照指令───>│                │              │
    │  {"command":     │                │              │
    │   "capture"}     │                │              │
    │                  │──检查状态────> │              │
    │                  │  (WiFi OK?)    │              │
    │                  │                │              │
    │                  │──拍照─────────>│              │
    │<─Notify: start ──│                │              │
    │                  │<─图片路径──────│              │
    │<─Notify: success─│                │              │
    │                  │                │              │
    │                  │──上传────────────────────────>│
    │<─Notify: upload──│                │              │
    │                  │<─响应 200 ─────────────────────│
    │<─Notify: done────│                │              │
```

---

## 三、状态机设计

### 3.1 状态定义

#### BLE 状态
```python
class BLEState(Enum):
    ADVERTISING    # 广播中（等待连接）
    CONNECTED      # 已连接
    AUTHENTICATED  # 已认证（可选）
```

**状态转换**:
```
ADVERTISING ──连接───> CONNECTED ──认证───> AUTHENTICATED
     ▲                     │
     └─────断开/超时────────┘
```

#### WiFi 状态
```python
class WiFiState(Enum):
    UNCONFIGURED  # 未配置
    CONNECTING    # 连接中
    CONNECTED     # 已连接
    FAILED        # 连接失败
```

**状态转换**:
```
UNCONFIGURED ──收到配置──> CONNECTING ──成功──> CONNECTED
                                │                  │
                                │                  │
                                └─失败──> FAILED ──┘
                                             │
                                             └──重试──> CONNECTING
```

#### 设备状态
```python
class DeviceState(Enum):
    IDLE       # 空闲
    CAPTURING  # 拍照中
    UPLOADING  # 上传中
    ERROR      # 错误
```

**状态转换**:
```
IDLE ──拍照指令──> CAPTURING ──成功──> UPLOADING ──成功──> IDLE
                      │                   │
                      └─失败──> ERROR ────┘
```

### 3.2 状态依赖关系

```python
# 可以拍照的条件
def is_ready_for_capture():
    return (
        wifi_state == CONNECTED and
        device_state == IDLE
    )
```

---

## 四、BLE GATT 协议设计

### 4.1 Service 结构

```
Service: Device Control Service
UUID: 12345678-1234-5678-1234-56789abcdef0
Primary: True

├── Characteristic: WiFi Config
│   UUID: ...def1
│   Properties: Write
│   Format: JSON
│   
├── Characteristic: Cloud Config
│   UUID: ...def2
│   Properties: Write
│   Format: JSON
│   
├── Characteristic: Capture Command
│   UUID: ...def3
│   Properties: Write
│   Format: JSON
│   
└── Characteristic: Status Notify
    UUID: ...def4
    Properties: Notify
    Format: JSON
```

### 4.2 数据格式规范

#### WiFi Config (Write)
```json
{
  "ssid": "string (required)",
  "password": "string (required)"
}
```

#### Cloud Config (Write)
```json
{
  "upload_url": "string (required, must be https)"
}
```

#### Capture Command (Write)
```json
{
  "command": "capture"
}
```

#### Status Notify (Notify)
```json
{
  "ble_state": "advertising|connected|authenticated",
  "wifi_state": "unconfigured|connecting|connected|failed",
  "device_state": "idle|capturing|uploading|error",
  "ready_for_capture": true|false,
  "timestamp": 1234567890.123,
  
  // 可选字段
  "event": "string",           // 事件类型
  "wifi_ssid": "string",       // WiFi 名称
  "wifi_ip": "string",         // IP 地址
  "error_code": "string",      // 错误码
  "error_message": "string",   // 错误信息
  "file": "string"             // 文件名
}
```

---

## 五、异常处理策略

### 5.1 分级处理

#### Level 1 - 可恢复错误（重试）
- WiFi 连接失败 → 自动重试 3 次
- 云端上传失败 → 自动重试 3 次
- 拍照失败 → 通知用户，等待重新指令

**处理方式**:
```python
for attempt in range(retry_times):
    try:
        # 执行操作
        break
    except Exception:
        if attempt < retry_times - 1:
            time.sleep(delay)
        else:
            # 通知失败
```

#### Level 2 - 状态错误（拒绝）
- WiFi 未连接时拍照 → 返回错误状态
- 设备忙时再次拍照 → 返回错误状态

**处理方式**:
```python
if not state_machine.is_ready_for_capture():
    notify_error("not_ready", "Device not ready")
    return
```

#### Level 3 - 致命错误（记录+报警）
- BLE 初始化失败
- 摄像头完全不可用
- 配置文件损坏

**处理方式**:
```python
try:
    critical_operation()
except Exception as e:
    logger.critical(f"Fatal error: {e}")
    notify_error("fatal", str(e))
    # 保持服务运行，但功能受限
```

### 5.2 全局异常捕获

```python
def safe_execute(func, *args, **kwargs):
    """安全执行函数，捕获所有异常"""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.error(f"Exception in {func.__name__}: {e}")
        return None
```

---

## 六、性能与资源管理

### 6.1 资源限制

#### systemd 配置
```ini
CPUQuota=50%           # 限制 CPU 使用
MemoryLimit=512M       # 限制内存使用
LimitNOFILE=65536      # 文件描述符限制
```

#### 线程管理
- WiFi 监控线程：每 10 秒检查一次
- BLE GLib 主循环：事件驱动
- 拍照/上传：独立线程，完成后自动结束

### 6.2 日志管理

#### 日志级别
- **DEBUG**: 详细调试信息
- **INFO**: 正常运行日志（默认）
- **WARNING**: 可恢复的异常
- **ERROR**: 错误但不致命
- **CRITICAL**: 致命错误

#### 日志轮转
```python
# 未来扩展：使用 RotatingFileHandler
handler = RotatingFileHandler(
    '/var/log/ble_device.log',
    maxBytes=10*1024*1024,  # 10MB
    backupCount=3
)
```

---

## 七、安全考虑

### 7.1 当前实现

配置文件权限限制（0600）  
密码不记录到日志  
HTTPS 强制校验（云端 URL）  
输入验证（JSON 格式、必填字段）

### 7.2 建议增强

#### 1. BLE 配对与绑定
```python
# 在 Advertisement 中启用认证
properties["AuthenticationRequired"] = True
properties["Bonding"] = True
```

#### 2. 数据加密
- 使用 BLE Security Manager
- 启用 LE Secure Connections
- PIN 码或数字密钥验证

#### 3. 访问控制
```python
# 添加设备白名单
ALLOWED_DEVICES = ["AA:BB:CC:DD:EE:FF"]

def check_device_allowed(device_address):
    return device_address in ALLOWED_DEVICES
```

#### 4. 敏感操作确认
```python
# 拍照需要二次确认
def on_capture_command():
    if not self.capture_confirmed:
        notify("请再次发送拍照指令确认")
        self.capture_confirmed = True
        return
    # 执行拍照
```

---

## 八、扩展方向

### 8.1 功能扩展

1. **OTA 固件升级**
   - 新增 Firmware Update Characteristic
   - 分片下载固件
   - 校验 + 应用更新

2. **多摄像头支持**
   - 摄像头列表管理
   - 切换摄像头指令
   - 同时拍摄多个视角

3. **视频录制**
   - 启动/停止录制
   - 流式上传
   - 时长控制

4. **传感器数据上报**
   - 温度、湿度、光照等
   - 定时上报
   - 数据聚合

### 8.2 性能优化

1. **连接池复用**
   ```python
   # HTTP 连接池
   session = requests.Session()
   adapter = HTTPAdapter(pool_connections=10, pool_maxsize=20)
   session.mount('https://', adapter)
   ```

2. **图片压缩**
   ```python
   # 使用 Pillow 压缩
   from PIL import Image
   img = Image.open(filepath)
   img.save(output, quality=85, optimize=True)
   ```

3. **异步上传**
   ```python
   # 使用队列异步上传
   upload_queue = Queue()
   upload_thread = Thread(target=upload_worker)
   ```

---

## 九、测试策略

### 9.1 单元测试

每个模块独立测试：
```bash
python3 config_manager.py
python3 state_machine.py
python3 wifi_manager.py
```

### 9.2 集成测试

使用 `test_modules.py` 验证模块协作。

### 9.3 压力测试

1. **连续拍照测试**
   ```python
   for i in range(100):
       send_capture_command()
       wait_for_completion()
   ```

2. **WiFi 断连重连测试**
   ```bash
   while true; do
       nmcli connection down WiFi-Name
       sleep 10
       # 检查自动重连
   done
   ```

3. **BLE 连接稳定性测试**
   - 频繁连接/断开
   - 长时间保持连接
   - Notify 消息压力测试

---

## 十、部署建议

### 10.1 生产环境检查清单

- [ ] 蓝牙适配器正常工作
- [ ] 摄像头设备可访问
- [ ] NetworkManager 已安装
- [ ] 防火墙规则配置
- [ ] 日志轮转已配置
- [ ] 监控告警已设置
- [ ] 备份策略已制定

### 10.2 监控指标

```bash
# systemd 监控
systemctl status ble-device
journalctl -u ble-device --since "1 hour ago"

# 资源监控
ps aux | grep ble_device_server
top -p $(pidof python3)

# 连接监控
hcitool con
nmcli device status
```