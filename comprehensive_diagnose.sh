#!/data/data/com.termux/files/usr/bin/bash

# 全面诊断和修复API服务问题的脚本

echo "🔍 全面诊断和修复API服务问题..."
echo "=================================="

# 1. 检查基本环境
echo "1. 检查基本环境..."
HOME_DIR=$(eval echo ~)
echo "   🏠 用户主目录: $HOME_DIR"

# 2. 检查API脚本
echo ""
echo "2. 检查API脚本..."
API_SCRIPT="$HOME_DIR/termux-audio-server/enhanced_mpv_api.py"
if [ -f "$API_SCRIPT" ]; then
    echo "   ✅ API脚本存在: $API_SCRIPT"
    
    # 检查脚本大小
    SCRIPT_SIZE=$(ls -l "$API_SCRIPT" | awk '{print $5}')
    echo "   📏 脚本大小: $SCRIPT_SIZE 字节"
    
    # 检查是否有web_control_panel函数
    if grep -q "def web_control_panel" "$API_SCRIPT"; then
        echo "   ✅ 包含web_control_panel函数"
    else
        echo "   ❌ 缺少web_control_panel函数"
    fi
    
    # 检查语法
    python -m py_compile "$API_SCRIPT" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "   ✅ 语法正确"
    else
        echo "   ❌ 语法错误"
    fi
else
    echo "   ❌ API脚本不存在: $API_SCRIPT"
fi

# 3. 检查端口占用
echo ""
echo "3. 检查端口占用..."
if command -v netstat >/dev/null 2>&1; then
    PORT_CHECK=$(netstat -tulnp 2>/dev/null | grep :5000)
    if [ -n "$PORT_CHECK" ]; then
        echo "   ✅ 5000端口已被占用:"
        echo "   $PORT_CHECK"
    else
        echo "   ⚠️  5000端口未被占用"
    fi
elif command -v ss >/dev/null 2>&1; then
    PORT_CHECK=$(ss -tulnp 2>/dev/null | grep :5000)
    if [ -n "$PORT_CHECK" ]; then
        echo "   ✅ 5000端口已被占用:"
        echo "   $PORT_CHECK"
    else
        echo "   ⚠️  5000端口未被占用"
    fi
else
    echo "   ⚠️  无法检查端口占用 (缺少netstat或ss命令)"
fi

# 4. 检查运行中的Python进程
echo ""
echo "4. 检查运行中的Python进程..."
PYTHON_PROCESSES=$(ps aux 2>/dev/null | grep python | grep -v grep)
if [ -n "$PYTHON_PROCESSES" ]; then
    echo "   ✅ 发现运行中的Python进程:"
    echo "$PYTHON_PROCESSES" | while read line; do
        echo "   $line"
    done
else
    echo "   ⚠️  未发现运行中的Python进程"
fi

# 5. 检查API服务PID
echo ""
echo "5. 检查API服务..."
API_PID=$(ps aux 2>/dev/null | grep enhanced_mpv_api | grep -v grep | awk '{print $2}')
if [ -n "$API_PID" ]; then
    echo "   ✅ API服务正在运行 (PID: $API_PID)"
    
    # 检查进程详细信息
    if command -v pwdx >/dev/null 2>&1; then
        PROCESS_DIR=$(pwdx $API_PID 2>/dev/null | awk '{print $2}')
        echo "   📁 进程工作目录: $PROCESS_DIR"
    fi
else
    echo "   ❌ API服务未运行"
fi

# 6. 检查日志文件
echo ""
echo "6. 检查日志文件..."
LOG_FILES=("$HOME_DIR/api_server.log" "$HOME_DIR/api_server_debug.log")
for log_file in "${LOG_FILES[@]}"; do
    if [ -f "$log_file" ]; then
        echo "   📄 日志文件: $log_file"
        echo "   📏 文件大小: $(ls -lh "$log_file" | awk '{print $5}')"
        echo "   🕐 最后修改: $(ls -lh "$log_file" | awk '{print $6" "$7" "$8}')"
        
        # 显示最后10行日志
        echo "   📖 最后10行日志:"
        tail -n 10 "$log_file" 2>/dev/null | while read line; do
            echo "       $line"
        done
    else
        echo "   ⚠️  日志文件不存在: $log_file"
    fi
done

# 7. 网络连接测试
echo ""
echo "7. 网络连接测试..."
echo "   🧪 测试本地连接 (127.0.0.1:5000)..."
curl -s -m 3 http://127.0.0.1:5000/mpv/status > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "   ✅ 本地连接成功"
else
    echo "   ❌ 本地连接失败"
fi

echo "   🧪 测试localhost连接..."
curl -s -m 3 http://localhost:5000/mpv/status > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "   ✅ localhost连接成功"
else
    echo "   ❌ localhost连接失败"
fi

# 8. 创建修复脚本
echo ""
echo "8. 创建修复脚本..."

# 创建API启动脚本
cat > "$HOME_DIR/start_api_debug.sh" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash

echo "🚀 启动API调试模式..."

# 设置环境变量
export FLASK_ENV=development
export FLASK_DEBUG=1

# 停止可能正在运行的API服务
echo "🛑 停止可能正在运行的API服务..."
pkill -f "enhanced_mpv_api.py" 2>/dev/null
sleep 2

# 启动API服务器（前台模式，显示详细输出）
echo "▶️ 启动API服务器（前台模式）..."
cd ~/termux-audio-server
python enhanced_mpv_api.py
EOF

chmod +x "$HOME_DIR/start_api_debug.sh"

# 创建API测试脚本
cat > "$HOME_DIR/test_api_endpoints.sh" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash

echo "🧪 测试API端点..."

ENDPOINTS=(
    "/"
    "/mpv/status"
    "/mpv/pause"
    "/mpv/next"
    "/mpv/prev"
    "/files"
)

for endpoint in "${ENDPOINTS[@]}"; do
    echo "   🧪 测试端点: $endpoint"
    RESPONSE=$(curl -s -w "%{http_code}" -m 3 "http://127.0.0.1:5000$endpoint" -o /dev/null)
    if [ "$RESPONSE" -eq 200 ]; then
        echo "   ✅ $endpoint (HTTP $RESPONSE)"
    else
        echo "   ❌ $endpoint (HTTP $RESPONSE)"
    fi
done
EOF

chmod +x "$HOME_DIR/test_api_endpoints.sh"

echo "✅ 诊断完成!"
echo ""
echo "🔧 使用以下命令进行故障排除:"
echo "   ~/start_api_debug.sh      # 以调试模式启动API服务器"
echo "   ~/test_api_endpoints.sh   # 测试API端点"
echo "   cat ~/api_server_debug.log # 查看详细日志"
echo ""
echo "💡 如果问题仍然存在，请提供以下信息:"
echo "   1. 运行 ~/start_api_debug.sh 的输出"
echo "   2. 日志文件内容"
echo "   3. 运行 ps aux | grep python 的输出"