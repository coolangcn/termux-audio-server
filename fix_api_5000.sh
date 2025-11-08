#!/data/data/com.termux/files/usr/bin/bash

# 修复API 5000端口无法访问的问题

echo "🔧 修复API 5000端口无法访问的问题..."

# 停止可能正在运行的API服务
echo "🛑 停止可能正在运行的API服务..."
pkill -f "enhanced_mpv_api.py" 2>/dev/null
sleep 2

# 设置环境变量以确保API服务正确绑定
export API_PORT=5000
export FLASK_ENV=production
export FLASK_DEBUG=0

# 进入项目目录
cd ~/termux-audio-server

# 启动API服务
echo "▶️ 启动API服务..."
python enhanced_mpv_api.py > ~/api_server_fixed.log 2>&1 &
API_PID=$!
echo "✅ API服务已在后台启动 (PID: $API_PID)"

# 等待几秒钟让服务启动
sleep 3

# 检查服务是否正常运行
if ps -p $API_PID > /dev/null 2>&1; then
    echo "✅ API服务正在运行"
    
    # 获取IP地址
    IP_ADDRESS=$(ifconfig wlan0 | grep -oP 'inet \K[\d.]+' || echo '127.0.0.1')
    
    # 测试连接
    curl -s -m 3 http://127.0.0.1:5000/mpv/status > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo "✅ API服务可访问"
        echo "🌐 API地址: http://$IP_ADDRESS:5000"
        echo "🌐 控制面板: http://$IP_ADDRESS:5000/"
    else
        echo "❌ API服务不可访问，请检查日志文件"
        echo "📄 日志文件: ~/api_server_fixed.log"
    fi
else
    echo "❌ API服务启动失败"
    echo "📄 请检查日志文件: ~/api_server_fixed.log"
fi