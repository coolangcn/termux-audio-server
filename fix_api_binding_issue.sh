#!/data/data/com.termux/files/usr/bin/bash

# 修复API绑定问题的脚本

echo "🔧 修复API绑定问题..."

# 获取用户主目录
HOME_DIR=$(eval echo ~)
echo "🏠 用户主目录: $HOME_DIR"

# API脚本路径
API_SCRIPT="$HOME_DIR/termux-audio-server/enhanced_mpv_api.py"
START_SCRIPT="$HOME_DIR/termux-audio-server/start_remote_audio.sh"

# 1. 检查并修复API脚本中的绑定配置
echo "1. 检查API脚本绑定配置..."

if [ -f "$API_SCRIPT" ]; then
    # 备份原文件
    cp "$API_SCRIPT" "${API_SCRIPT}.bind_fix_backup"
    
    # 检查是否已经有正确的绑定配置
    if grep -q "app.run(host='0.0.0.0'" "$API_SCRIPT"; then
        echo "   ✅ API脚本已有正确的绑定配置"
    else
        echo "   ❌ API脚本缺少正确的绑定配置，正在修复..."
        
        # 替换绑定配置
        sed -i "s/app.run(.*)/app.run(host='0.0.0.0', port=API_PORT, debug=False)/" "$API_SCRIPT"
        echo "   ✅ API绑定配置已修复"
    fi
else
    echo "   ❌ API脚本不存在: $API_SCRIPT"
fi

# 2. 检查并修复启动脚本中的API启动命令
echo "2. 检查启动脚本中的API启动命令..."

if [ -f "$START_SCRIPT" ]; then
    # 备份原文件
    cp "$START_SCRIPT" "${START_SCRIPT}.bind_fix_backup"
    
    # 检查API启动命令
    if grep -q "python.*enhanced_mpv_api.py" "$START_SCRIPT"; then
        echo "   ✅ 启动脚本包含API启动命令"
    else
        echo "   ❌ 启动脚本缺少API启动命令，正在修复..."
        
        # 在适当位置添加API启动命令
        sed -i '/--- 4. 启动 Flask API 服务 ---/a\
# 在后台启动 Python 脚本\
cd ~/termux-audio-server\
python enhanced_mpv_api.py > ~/api_server_debug.log 2>&1 &\
API_PID=$!\
echo "✅ API 服务 (PID $API_PID) 已在后台启动。"' "$START_SCRIPT"
        echo "   ✅ API启动命令已添加"
    fi
else
    echo "   ❌ 启动脚本不存在: $START_SCRIPT"
fi

# 3. 创建专门的API启动脚本
echo "3. 创建专门的API启动脚本..."

cat > "$HOME_DIR/start_api_service.sh" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash

echo "🚀 启动API服务..."

# 设置环境变量
export API_PORT=5000
export FLASK_ENV=production

# 停止可能正在运行的API服务
echo "🛑 停止可能正在运行的API服务..."
pkill -f "enhanced_mpv_api.py" 2>/dev/null
sleep 2

# 进入项目目录
cd ~/termux-audio-server

# 启动API服务
echo "▶️ 启动API服务..."
python enhanced_mpv_api.py > ~/api_server_startup.log 2>&1 &
API_PID=$!
echo "✅ API服务已在后台启动 (PID: $API_PID)"

# 等待几秒钟让服务启动
sleep 3

# 检查服务是否正常运行
if ps -p $API_PID > /dev/null 2>&1; then
    echo "✅ API服务正在运行"
    
    # 测试连接
    curl -s -m 3 http://127.0.0.1:5000/mpv/status > /dev/null 2>&1
    if [ $? -eq 0 ]; then
        echo "✅ API服务可访问"
    else
        echo "❌ API服务不可访问，请检查日志文件"
        echo "📄 日志文件: ~/api_server_startup.log"
    fi
else
    echo "❌ API服务启动失败"
    echo "📄 请检查日志文件: ~/api_server_startup.log"
fi
EOF

chmod +x "$HOME_DIR/start_api_service.sh"

# 4. 创建API测试脚本
echo "4. 创建API测试脚本..."

cat > "$HOME_DIR/test_api_connectivity.sh" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash

echo "🔍 测试API连接性..."

# 测试不同地址的连接
ADDRESSES=("127.0.0.1:5000" "localhost:5000" "0.0.0.0:5000")

for addr in "${ADDRESSES[@]}"; do
    echo "   🧪 测试地址: http://$addr/mpv/status"
    RESPONSE=$(curl -s -w "%{http_code}" -m 3 "http://$addr/mpv/status" -o /dev/null)
    if [ "$RESPONSE" -eq 200 ]; then
        echo "   ✅ 连接成功 (HTTP $RESPONSE)"
    else
        echo "   ❌ 连接失败 (HTTP $RESPONSE)"
    fi
done

# 检查端口监听状态
echo "   📡 检查端口监听状态..."
if command -v netstat >/dev/null 2>&1; then
    netstat -tulnp 2>/dev/null | grep :5000
elif command -v ss >/dev/null 2>&1; then
    ss -tulnp 2>/dev/null | grep :5000
else
    echo "   ⚠️  无法检查端口监听状态"
fi
EOF

chmod +x "$HOME_DIR/test_api_connectivity.sh"

echo "✅ API绑定问题修复完成!"
echo ""
echo "📌 请按以下步骤操作："
echo "1. 停止当前服务: ~/stop_audio_server"
echo "2. 启动修复后的服务: ~/start_api_service.sh"
echo "3. 测试连接性: ~/test_api_connectivity.sh"
echo ""
echo "💡 如果仍有问题，请检查日志文件："
echo "   ~/api_server_startup.log"
echo "   ~/api_server_debug.log"