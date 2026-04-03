#!/bin/bash
# BLE Device Server 部署脚本

set -e  # 遇到错误立即退出

echo "======================================"
echo "BLE Device Server 部署脚本"
echo "======================================"

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 检查是否为 root 用户
if [ "$EUID" -ne 0 ]; then 
    echo -e "${RED}错误: 请使用 root 用户运行此脚本${NC}"
    exit 1
fi

# 定义路径
INSTALL_DIR="/opt/ble_device"
CONFIG_DIR="/var/lib/ble_device"
LOG_DIR="/var/log"
SERVICE_FILE="/etc/systemd/system/ble-device.service"

echo -e "${GREEN}[1/8] 检查系统依赖...${NC}"

# 检查并安装系统包
REQUIRED_PACKAGES="bluez python3 python3-pip python3-dbus python3-gi network-manager fswebcam v4l-utils libcairo2-dev libdbus-1-dev pkg-config"
for package in $REQUIRED_PACKAGES; do
    if ! dpkg -l | grep -q "^ii  $package "; then
        echo "安装 $package..."
        apt-get update -qq
        apt-get install -y $package
    else
        echo "$package 已安装"
    fi
done

# 安装摄像头工具（可选）
echo "安装摄像头工具（可选）..."
apt-get install -y fswebcam v4l-utils || echo "摄像头工具安装失败，可后续手动安装"

echo -e "${GREEN}[2/8] 创建目录结构...${NC}"

# 创建必要目录
mkdir -p "$INSTALL_DIR"
mkdir -p "$CONFIG_DIR"
mkdir -p "$LOG_DIR"
mkdir -p "/tmp/ble_device_captures"

# 设置权限
chmod 755 "$INSTALL_DIR"
chmod 700 "$CONFIG_DIR"
chmod 755 "/tmp/ble_device_captures"

echo -e "${GREEN}[3/8] 复制程序文件...${NC}"

# 获取脚本所在目录
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# 复制 Python 文件
cp "$SCRIPT_DIR"/*.py "$INSTALL_DIR/"
cp "$SCRIPT_DIR/requirements.txt" "$INSTALL_DIR/"

# 设置文件权限
chmod 644 "$INSTALL_DIR"/*.py
chmod 755 "$INSTALL_DIR/ble_device_server.py"

echo -e "${GREEN}[4/8] 安装 Python 依赖...${NC}"

# 安装 Python 包
cd "$INSTALL_DIR"
pip3 install --upgrade pip setuptools wheel
pip3 install --break-system-packages -r requirements.txt || \
    pip3 install -r requirements.txt

echo -e "${GREEN}[5/8] 配置 systemd 服务...${NC}"

# 复制并启用服务
cp "$SCRIPT_DIR/ble-device.service" "$SERVICE_FILE"
chmod 644 "$SERVICE_FILE"

# 重载 systemd
systemctl daemon-reload

echo -e "${GREEN}[6/8] 配置蓝牙...${NC}"

# 确保蓝牙服务运行
systemctl enable bluetooth
systemctl start bluetooth

# 设置蓝牙为可发现
hciconfig hci0 up || echo "警告: 无法启用蓝牙适配器"
hciconfig hci0 piscan || echo "警告: 无法设置蓝牙可发现模式"

echo -e "${GREEN}[7/8] PWM 补光（可选）...${NC}"

# 【获取高级权限】本脚本以 root 运行，可写入 /sys/class/pwm
# 【开启 PWM 补光】运行后灯光会亮；无对应 pwmchip 时跳过
enable_pwm_chip() {
    local chipdir="/sys/class/pwm/$1"
    if [ ! -d "$chipdir" ]; then
        echo "未找到 $chipdir，跳过"
        return 0
    fi
    if [ ! -d "$chipdir/pwm0" ]; then
        echo 0 > "$chipdir/export" 2>/dev/null || true
    fi
    if [ -d "$chipdir/pwm0" ]; then
        echo 1000000 > "$chipdir/pwm0/period"
        echo 700000 > "$chipdir/pwm0/duty_cycle"
        echo 1 > "$chipdir/pwm0/enable"
        echo "已启用 $1 的 PWM 补光"
    else
        echo "警告: $chipdir 下未出现 pwm0，跳过"
    fi
}

enable_pwm_chip pwmchip1
enable_pwm_chip pwmchip2

echo -e "${GREEN}[8/8] 启动服务...${NC}"

# 启用并启动服务
systemctl enable ble-device.service
systemctl start ble-device.service

# 等待服务启动
sleep 2

# 检查服务状态
if systemctl is-active --quiet ble-device.service; then
    echo -e "${GREEN}✓ 服务启动成功！${NC}"
else
    echo -e "${RED}✗ 服务启动失败${NC}"
    echo "查看日志: journalctl -u ble-device.service -f"
    exit 1
fi

echo ""
echo "======================================"
echo -e "${GREEN}部署完成！${NC}"
echo "======================================"
echo ""
echo "服务状态: systemctl status ble-device"
echo "查看日志: journalctl -u ble-device -f"
echo "重启服务: systemctl restart ble-device"
echo "停止服务: systemctl stop ble-device"
echo ""
echo "配置文件: $CONFIG_DIR/config.json"
echo "日志文件: /var/log/ble_device.log"
echo ""
