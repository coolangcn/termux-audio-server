#!/data/data/com.termux/files/usr/bin/bash

echo "正在安装音频服务器依赖..."

# 更新包列表
pkg update -y

# 安装必要的系统工具
pkg install -y python socat rclone mpv

# 安装Python依赖
pip install -r ~/requirements.txt

echo "依赖安装完成！"
echo "请确保已配置好rclone远程存储:"
echo "  rclone config"