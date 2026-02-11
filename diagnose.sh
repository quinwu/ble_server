#!/bin/bash
# BLE Device Server 故障排查脚本

echo "======================================"
echo "BLE Device Server 故障排查"
echo "======================================"
echo ""

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查函数
check_item() {
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ $1${NC}"
        return 0
    else
        echo -e "${RED}✗ $1${NC}"
        return 1
    fi
}

# 检查服务状态
echo "1. 检查服务状态"
echo "-----------------------------------"
systemctl is-active --quiet ble-device
check_item "服务运行状态"

systemctl is-enabled --quiet ble-device
check_item "服务开机自启"

echo ""

# 检查蓝牙
echo "2. 检查蓝牙状态"
echo "-----------------------------------"
systemctl is-active --quiet bluetooth
check_item "BlueZ 服务运行"

hciconfig hci0 > /dev/null 2>&1
check_item "蓝牙适配器可用"

if [ $? -eq 0 ]; then
    echo "蓝牙适配器信息:"
    hciconfig hci0 | grep -E "BD Address|UP RUNNING"
fi

echo ""

# 检查网络
echo "3. 检查网络状态"
echo "-----------------------------------"
systemctl is-active --quiet NetworkManager
check_item "NetworkManager 运行"

if nmcli device status | grep -q "wifi.*connected"; then
    echo -e "${GREEN}✓ WiFi 已连接${NC}"
    nmcli device status | grep wifi
else
    echo -e "${YELLOW}⚠ WiFi 未连接${NC}"
fi

echo ""

# 检查摄像头
echo "4. 检查摄像头设备"
echo "-----------------------------------"
if [ -e /dev/video0 ]; then
    echo -e "${GREEN}✓ 摄像头设备存在 (/dev/video0)${NC}"
    ls -l /dev/video* 2>/dev/null
else
    echo -e "${RED}✗ 未找到摄像头设备${NC}"
fi

echo ""

# 检查 Python 依赖
echo "5. 检查 Python 依赖"
echo "-----------------------------------"
python3 -c "import dbus" 2>/dev/null
check_item "dbus-python"

python3 -c "import gi; gi.require_version('GLib', '2.0')" 2>/dev/null
check_item "PyGObject"

python3 -c "import requests" 2>/dev/null
check_item "requests"

echo ""

# 检查文件权限
echo "6. 检查文件和目录"
echo "-----------------------------------"
if [ -d /opt/ble_device ]; then
    echo -e "${GREEN}✓ 程序目录存在${NC}"
else
    echo -e "${RED}✗ 程序目录不存在${NC}"
fi

if [ -d /var/lib/ble_device ]; then
    echo -e "${GREEN}✓ 配置目录存在${NC}"
else
    echo -e "${RED}✗ 配置目录不存在${NC}"
fi

if [ -f /etc/systemd/system/ble-device.service ]; then
    echo -e "${GREEN}✓ systemd 服务文件存在${NC}"
else
    echo -e "${RED}✗ systemd 服务文件不存在${NC}"
fi

echo ""

# 查看最近日志
echo "7. 最近日志（最后 20 行）"
echo "-----------------------------------"
journalctl -u ble-device -n 20 --no-pager

echo ""

# 配置信息
echo "8. 配置信息"
echo "-----------------------------------"
if [ -f /var/lib/ble_device/config.json ]; then
    echo "配置文件内容:"
    cat /var/lib/ble_device/config.json | python3 -m json.tool 2>/dev/null || cat /var/lib/ble_device/config.json
else
    echo -e "${YELLOW} 配置文件不存在${NC}"
fi

echo ""

# 系统资源
echo "9. 系统资源使用"
echo "-----------------------------------"
if systemctl is-active --quiet ble-device; then
    PID=$(systemctl show -p MainPID ble-device | cut -d'=' -f2)
    if [ "$PID" != "0" ]; then
        echo "进程 PID: $PID"
        ps -p $PID -o pid,ppid,%cpu,%mem,cmd --no-headers
    fi
fi

echo ""

# 建议操作
echo "======================================"
echo "建议操作"
echo "======================================"
echo ""
echo "查看完整日志: journalctl -u ble-device -f"
echo "重启服务: sudo systemctl restart ble-device"
echo "查看服务状态: sudo systemctl status ble-device"
echo "测试模块: sudo python3 /opt/ble_device/test_modules.py"
echo ""
