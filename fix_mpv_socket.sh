#!/data/data/com.termux/files/usr/bin/bash

# 修复MPV Socket连接问题的脚本

echo "🔧 修复MPV Socket连接问题..."

# 创建MPV控制目录
MPV_CTRL_DIR="/data/data/com.termux/files/usr/tmp/mpv_ctrl"
echo "📁 创建MPV控制目录: $MPV_CTRL_DIR"
mkdir -p "$MPV_CTRL_DIR"

# 设置正确的MPV Socket路径
MPV_SOCKET_PATH="$MPV_CTRL_DIR/socket"
echo "📍 设置MPV Socket路径: $MPV_SOCKET_PATH"

# 更新start_remote_audio.sh中的配置
START_SCRIPT="$HOME/termux-audio-server/start_remote_audio.sh"
if [ -f "$START_SCRIPT" ]; then
    echo "📝 更新启动脚本中的MPV配置..."
    sed -i "s|MPV_SOCKET_PATH=.*|MPV_SOCKET_PATH=\"$MPV_SOCKET_PATH\"|" "$START_SCRIPT"
    sed -i "s|--input-ipc-server=[^ ]*|--input-ipc-server=$MPV_SOCKET_PATH|" "$START_SCRIPT"
fi

# 更新API脚本中的配置
API_SCRIPT_ENHANCED="$HOME/termux-audio-server/enhanced_mpv_api.py"
if [ -f "$API_SCRIPT_ENHANCED" ]; then
    echo "📝 更新增强API脚本中的MPV配置..."
    sed -i "s|MPV_SOCKET_PATH = .*|MPV_SOCKET_PATH = \"$MPV_SOCKET_PATH\"|" "$API_SCRIPT_ENHANCED"
fi

API_SCRIPT_BASIC="$HOME/termux-audio-server/mpv_get_api.py"
if [ -f "$API_SCRIPT_BASIC" ]; then
    echo "📝 更新基础API脚本中的MPV配置..."
    sed -i "s|MPV_SOCKET_PATH = .*|MPV_SOCKET_PATH = \"$MPV_SOCKET_PATH\"  # 改这行！|" "$API_SCRIPT_BASIC"
fi

# 确保MPV控制目录权限正确
echo "🔐 设置目录权限..."
chmod 755 "$MPV_CTRL_DIR"

echo "✅ MPV Socket配置修复完成！"
echo ""
echo "📌 请重新启动音频服务器以应用更改："
echo "   ~/stop_audio_server"
echo "   ~/start_audio_server"
echo ""
echo "💡 如果仍有问题，请检查："
echo "   1. MPV版本是否支持IPC socket"
echo "   2. 是否有足够的存储空间"
echo "   3. Termux是否具有正确的文件系统权限"