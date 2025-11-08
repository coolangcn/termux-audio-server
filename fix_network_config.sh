#!/data/data/com.termux/files/usr/bin/bash

# 修复网络配置问题的脚本

echo "🌐 修复网络配置问题..."

# 获取实际的网络接口IP地址
echo "🔍 检测网络接口IP地址..."
IP_ADDRESS=$(ifconfig wlan0 | grep -oP 'inet \K[\d.]+' 2>/dev/null || echo "")

if [ -z "$IP_ADDRESS" ]; then
    IP_ADDRESS=$(ifconfig eth0 | grep -oP 'inet \K[\d.]+' 2>/dev/null || echo "")
fi

if [ -z "$IP_ADDRESS" ]; then
    IP_ADDRESS="127.0.0.1"
    echo "⚠️  无法检测到网络接口IP，使用默认地址: $IP_ADDRESS"
else
    echo "✅ 检测到网络接口IP: $IP_ADDRESS"
fi

# 更新start_remote_audio.sh中的IP地址获取逻辑
START_SCRIPT="$HOME/termux-audio-server/start_remote_audio.sh"
if [ -f "$START_SCRIPT" ]; then
    echo "📝 更新启动脚本中的IP地址获取逻辑..."
    
    # 备份原文件
    cp "$START_SCRIPT" "${START_SCRIPT}.bak"
    
    # 替换IP地址获取部分
    sed -i '/IP_ADDRESS=/,/echo "--------------------------------------------------------"/d' "$START_SCRIPT"
    
    # 插入新的IP地址获取逻辑
    sed -i '/--- 6. 最终提示 ---/i\
# --- 6. 最终提示 ---\
IP_ADDRESS=$(ifconfig wlan0 | grep -oP '"'"'inet \K[\d.]+'"'"' 2>/dev/null || ifconfig eth0 | grep -oP '"'"'inet \K[\d.]+'"'"' 2>/dev/null || echo "127.0.0.1")\
\
if [ -z "$IP_ADDRESS" ]; then\
    IP_ADDRESS="127.0.0.1"\
fi\
' "$START_SCRIPT"
fi

echo "✅ 网络配置修复完成！"
echo ""
echo "📌 请重新启动音频服务器以应用更改："
echo "   ~/stop_audio_server"
echo "   ~/start_audio_server"
echo ""
echo "💡 修复后您应该能够通过以下地址访问控制面板："
echo "   http://$IP_ADDRESS:5000/"