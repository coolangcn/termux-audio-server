#!/data/data/com.termux/files/usr/bin/bash

# 修复API服务绑定问题的脚本

echo "🔧 修复API服务绑定问题..."

# 获取实际的网络接口IP地址
echo "🔍 检测网络接口IP地址..."
IP_ADDRESS=$(ifconfig wlan0 | grep -oP 'inet \K[\d.]+' 2>/dev/null || ifconfig eth0 | grep -oP 'inet \K[\d.]+' 2>/dev/null || echo "127.0.0.1")

if [ "$IP_ADDRESS" = "127.0.0.1" ]; then
    echo "⚠️  无法检测到网络接口IP，将使用0.0.0.0绑定所有接口"
    IP_ADDRESS="0.0.0.0"
else
    echo "✅ 检测到网络接口IP: $IP_ADDRESS"
fi

# 创建一个新的API启动脚本
API_START_SCRIPT="$HOME/start_api_server.py"
echo "📝 创建API启动脚本..."

cat > "$API_START_SCRIPT" << 'EOF'
#!/data/data/com.termux/files/usr/bin/python
import os
import sys

# 添加项目目录到Python路径
sys.path.insert(0, os.path.expanduser('~/termux-audio-server'))

# 导入增强版API
from enhanced_mpv_api import app

if __name__ == '__main__':
    # 确保绑定到所有接口
    API_PORT = int(os.environ.get('API_PORT', 5000))
    print(f"🚀 启动API服务器，绑定到 0.0.0.0:{API_PORT}")
    app.run(host='0.0.0.0', port=API_PORT, debug=False)
EOF

chmod +x "$API_START_SCRIPT"

# 更新start_remote_audio.sh中的API启动部分
START_SCRIPT="$HOME/termux-audio-server/start_remote_audio.sh"
if [ -f "$START_SCRIPT" ]; then
    echo "📝 更新启动脚本中的API启动逻辑..."
    
    # 备份原文件
    cp "$START_SCRIPT" "${START_SCRIPT}.api_bak"
    
    # 替换API启动部分
    sed -i '/# --- 4. 启动 Flask API 服务 ---/,/# --- 5. 启动自动缓存服务 ---/c\
# --- 4. 启动 Flask API 服务 ---\
echo "--- 4. 启动 Flask API 服务 (端口 $API_PORT) ---"\
\
# 在后台启动 Python 脚本\
python "$API_START_SCRIPT" >/dev/null 2>&1 &\
API_PID=$!\
echo "✅ API 服务 (PID $API_PID) 已在后台启动。"\
\
# --- 5. 启动自动缓存服务 ---\
echo "--- 5. 启动自动缓存服务 ---"\
# 启动自动缓存（通过API控制）\
sleep 3  # 等待API服务启动\
curl -X POST "http://localhost:$API_PORT/cache/auto?action=start" >/dev/null 2>&1\
echo "✅ 自动缓存服务已启动，将每30分钟检查一次新文件。"\
' "$START_SCRIPT"
    
    # 更新最终提示部分的IP地址获取逻辑
    sed -i '/# --- 6. 最终提示 ---/,$d' "$START_SCRIPT"
    
    cat >> "$START_SCRIPT" << 'EOF'

# --- 6. 最终提示 ---
IP_ADDRESS=$(ifconfig wlan0 | grep -oP 'inet \K[\d.]+' 2>/dev/null || ifconfig eth0 | grep -oP 'inet \K[\d.]+' 2>/dev/null || echo "127.0.0.1")

if [ -z "$IP_ADDRESS" ] || [ "$IP_ADDRESS" = "127.0.0.1" ]; then
    IP_ADDRESS=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")
fi

if [ -z "$IP_ADDRESS" ] || [ "$IP_ADDRESS" = "127.0.0.1" ]; then
    IP_ADDRESS="0.0.0.0"
fi

echo "--------------------------------------------------------"
echo "🎉 远程音频控制系统已启动！"
echo "🌐 API 地址: http://$IP_ADDRESS:$API_PORT"
echo "🌐 控制面板: http://$IP_ADDRESS:$API_PORT/"
echo "--------------------------------------------------------"
echo "控制命令示例："
echo "暂停/播放: GET http://$IP_ADDRESS:$API_PORT/mpv/pause"
echo "下一首:   GET http://$IP_ADDRESS:$API_PORT/mpv/next"
echo "上一首:   GET http://$IP_ADDRESS:$API_PORT/mpv/prev"
echo "随机播放: GET http://$IP_ADDRESS:$API_PORT/mpv/shuffle"
echo "搜索歌曲: GET http://$IP_ADDRESS:$API_PORT/files/search?q=关键字"
echo "同步文件: POST http://$IP_ADDRESS:$API_PORT/files/sync"
echo "停止所有服务: killall mpv python && rm -rf $LOCAL_DIR $PLAYLIST_FILE"
echo "--------------------------------------------------------"
EOF
fi

# 创建一个测试API连接的脚本
TEST_SCRIPT="$HOME/test_api_connection.sh"
cat > "$TEST_SCRIPT" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash

echo "🔍 测试API连接..."

# 测试本地连接
echo "📍 测试本地连接 (127.0.0.1:5000)..."
curl -s -m 5 http://127.0.0.1:5000/mpv/status > /dev/null
if [ $? -eq 0 ]; then
    echo "✅ 本地连接成功"
else
    echo "❌ 本地连接失败"
fi

# 测试localhost连接
echo "📍 测试localhost连接..."
curl -s -m 5 http://localhost:5000/mpv/status > /dev/null
if [ $? -eq 0 ]; then
    echo "✅ localhost连接成功"
else
    echo "❌ localhost连接失败"
fi

# 获取实际IP并测试
IP_ADDRESS=$(ifconfig wlan0 | grep -oP 'inet \K[\d.]+' 2>/dev/null || ifconfig eth0 | grep -oP 'inet \K[\d.]+' 2>/dev/null || echo "127.0.0.1")
if [ "$IP_ADDRESS" != "127.0.0.1" ]; then
    echo "📍 测试网络IP连接 ($IP_ADDRESS:5000)..."
    curl -s -m 5 http://$IP_ADDRESS:5000/mpv/status > /dev/null
    if [ $? -eq 0 ]; then
        echo "✅ 网络IP连接成功"
    else
        echo "❌ 网络IP连接失败"
    fi
fi

echo "📋 检查运行中的Python进程..."
ps aux | grep python | grep -v grep

echo "📋 检查端口占用..."
netstat -tulnp 2>/dev/null | grep :5000 || echo "未检测到5000端口占用"

echo "📋 检查API服务日志..."
echo "请查看 ~/api_server.log 获取更多详细信息"
EOF

chmod +x "$TEST_SCRIPT"

# 更新API脚本以添加日志记录
API_SCRIPT="$HOME/termux-audio-server/enhanced_mpv_api.py"
if [ -f "$API_SCRIPT" ]; then
    echo "📝 更新API脚本添加日志记录..."
    
    # 备份原文件
    cp "$API_SCRIPT" "${API_SCRIPT}.log_bak"
    
    # 在文件开头添加日志导入
    sed -i '2i import logging\nimport sys' "$API_SCRIPT"
    
    # 在Flask应用初始化后添加日志配置
    sed -i '/app = Flask(__name__)/a\# 配置日志\nlogging.basicConfig(\n    level=logging.INFO,\n    format='\''%(asctime)s %(levelname)s %(message)s'\'',\n    handlers=[\n        logging.FileHandler('\''~/api_server.log'\''),\n        logging.StreamHandler(sys.stdout)\n    ]\n)\napp.logger.setLevel(logging.INFO)' "$API_SCRIPT"
    
    # 在main函数中添加启动日志
    sed -i '/API_PORT = int(os.environ.get('\''API_PORT'\'', 5000))/a\    app.logger.info(f"🚀 API服务器启动，绑定到 0.0.0.0:{API_PORT}")' "$API_SCRIPT"
fi

echo "✅ API绑定配置修复完成！"
echo ""
echo "📌 请重新启动音频服务器以应用更改："
echo "   ~/stop_audio_server"
echo "   ~/start_audio_server"
echo ""
echo "💡 修复后您应该能够通过以下地址访问控制面板："
echo "   http://0.0.0.0:5000/ (所有网络接口)"
echo ""
echo "🔧 您可以使用以下脚本测试连接："
echo "   ~/test_api_connection.sh"