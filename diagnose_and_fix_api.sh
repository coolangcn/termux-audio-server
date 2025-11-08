#!/data/data/com.termux/files/usr/bin/bash

# 诊断和修复API服务问题的完整脚本

echo "🔍 诊断和修复API服务问题..."
echo "================================"

# 1. 检查必要的依赖
echo "1. 检查必要的依赖..."
echo "   检查Python..."
if ! command -v python &> /dev/null; then
    echo "   ❌ Python未安装"
    echo "   请运行: pkg install python"
    exit 1
else
    echo "   ✅ Python已安装 ($(python --version))"
fi

echo "   检查Flask..."
if ! python -c "import flask" &> /dev/null; then
    echo "   ❌ Flask未安装"
    echo "   请运行: pip install Flask"
    exit 1
else
    echo "   ✅ Flask已安装"
fi

# 2. 检查项目文件
echo ""
echo "2. 检查项目文件..."
PROJECT_DIR="$HOME/termux-audio-server"
if [ ! -d "$PROJECT_DIR" ]; then
    echo "   ❌ 项目目录不存在: $PROJECT_DIR"
    echo "   请重新运行部署脚本"
    exit 1
else
    echo "   ✅ 项目目录存在: $PROJECT_DIR"
fi

API_SCRIPT="$PROJECT_DIR/enhanced_mpv_api.py"
if [ ! -f "$API_SCRIPT" ]; then
    echo "   ❌ API脚本不存在: $API_SCRIPT"
    exit 1
else
    echo "   ✅ API脚本存在: $API_SCRIPT"
fi

# 3. 检查端口占用
echo ""
echo "3. 检查端口占用..."
if command -v netstat &> /dev/null; then
    PORT_CHECK=$(netstat -tulnp 2>/dev/null | grep :5000)
    if [ -n "$PORT_CHECK" ]; then
        echo "   ⚠️  5000端口已被占用:"
        echo "   $PORT_CHECK"
    else
        echo "   ✅ 5000端口未被占用"
    fi
else
    echo "   ⚠️  netstat命令不可用，跳过端口检查"
fi

# 4. 检查进程
echo ""
echo "4. 检查相关进程..."
PYTHON_PROCESSES=$(ps aux 2>/dev/null | grep python | grep -v grep)
if [ -n "$PYTHON_PROCESSES" ]; then
    echo "   ⚠️  发现运行中的Python进程:"
    echo "$PYTHON_PROCESSES"
else
    echo "   ✅ 未发现相关Python进程"
fi

# 5. 创建修复后的API启动脚本
echo ""
echo "5. 创建修复后的API启动脚本..."

# 创建API启动脚本
API_START_SCRIPT="$HOME/start_api_server.py"
cat > "$API_START_SCRIPT" << 'EOF'
#!/data/data/com.termux/files/usr/bin/python
import os
import sys
import logging

# 添加项目目录到Python路径
project_dir = os.path.expanduser('~/termux-audio-server')
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

# 配置日志
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(os.path.expanduser('~/api_server_debug.log')),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)
logger.info("🚀 开始启动API服务器...")

try:
    # 导入增强版API
    logger.info("📥 导入API模块...")
    from enhanced_mpv_api import app
    
    # 确保绑定到所有接口
    API_PORT = int(os.environ.get('API_PORT', 5000))
    logger.info(f"🌐 API服务器将绑定到 0.0.0.0:{API_PORT}")
    
    # 启动Flask应用
    logger.info("🏁 启动Flask应用...")
    app.run(host='0.0.0.0', port=API_PORT, debug=False)
    
except Exception as e:
    logger.error(f"❌ 启动API服务器时发生错误: {e}")
    import traceback
    logger.error(f"详细错误信息: {traceback.format_exc()}")
    sys.exit(1)
EOF

chmod +x "$API_START_SCRIPT"

# 6. 创建测试脚本
echo ""
echo "6. 创建测试脚本..."

TEST_SCRIPT="$HOME/test_api_server.py"
cat > "$TEST_SCRIPT" << 'EOF'
#!/data/data/com.termux/files/usr/bin/python
import os
import sys
import subprocess
import time

# 添加项目目录到Python路径
project_dir = os.path.expanduser('~/termux-audio-server')
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

print("🧪 测试API服务器...")

# 测试1: 检查API脚本语法
print("\n1. 检查API脚本语法...")
try:
    with open(os.path.expanduser('~/termux-audio-server/enhanced_mpv_api.py'), 'r') as f:
        compile(f.read(), 'enhanced_mpv_api.py', 'exec')
    print("   ✅ API脚本语法正确")
except Exception as e:
    print(f"   ❌ API脚本语法错误: {e}")
    sys.exit(1)

# 测试2: 尝试导入Flask应用
print("\n2. 测试导入Flask应用...")
try:
    from enhanced_mpv_api import app
    print("   ✅ Flask应用导入成功")
except Exception as e:
    print(f"   ❌ Flask应用导入失败: {e}")
    import traceback
    print(f"   详细错误信息: {traceback.format_exc()}")
    sys.exit(1)

# 测试3: 检查依赖
print("\n3. 检查必要依赖...")
required_packages = ['flask', 'flask_cors']
for package in required_packages:
    try:
        __import__(package)
        print(f"   ✅ {package} 已安装")
    except ImportError:
        print(f"   ❌ {package} 未安装")
        sys.exit(1)

print("\n✅ 所有测试通过!")
print("💡 您可以运行以下命令启动API服务器:")
print("   python ~/start_api_server.py")
EOF

chmod +x "$TEST_SCRIPT"

# 7. 创建启动脚本
echo ""
echo "7. 创建手动启动脚本..."

START_MANUAL_SCRIPT="$HOME/start_api_manual.sh"
cat > "$START_MANUAL_SCRIPT" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash

echo "🚀 手动启动API服务器..."

# 设置环境变量
export API_PORT=5000
export FLASK_ENV=production

# 停止可能正在运行的API服务
echo "🛑 停止可能正在运行的API服务..."
pkill -f "start_api_server.py" 2>/dev/null
pkill -f "enhanced_mpv_api.py" 2>/dev/null

# 等待进程结束
sleep 2

# 启动API服务器
echo "▶️ 启动API服务器..."
cd ~
python ~/start_api_server.py &

# 获取进程ID
API_PID=$!
echo "✅ API服务器已在后台启动 (PID: $API_PID)"

# 等待几秒钟让服务器启动
sleep 3

# 测试连接
echo "🔍 测试API连接..."
curl -s -m 5 http://127.0.0.1:5000/mpv/status > /dev/null
if [ $? -eq 0 ]; then
    echo "✅ API服务器启动成功!"
    echo "🌐 您可以通过以下地址访问:"
    echo "   http://127.0.0.1:5000/"
else
    echo "❌ API服务器启动失败"
    echo "📋 检查日志文件获取更多信息:"
    echo "   cat ~/api_server_debug.log"
fi
EOF

chmod +x "$START_MANUAL_SCRIPT"

# 8. 创建停止脚本
echo ""
echo "8. 创建停止脚本..."

STOP_API_SCRIPT="$HOME/stop_api_server.sh"
cat > "$STOP_API_SCRIPT" << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash

echo "⏹️ 停止API服务器..."

# 停止API服务
pkill -f "start_api_server.py" 2>/dev/null
pkill -f "enhanced_mpv_api.py" 2>/dev/null
pkill -f "flask" 2>/dev/null

# 等待进程结束
sleep 2

# 检查是否还有相关进程
PYTHON_PROCESSES=$(ps aux 2>/dev/null | grep python | grep -v grep)
if [ -n "$PYTHON_PROCESSES" ]; then
    echo "⚠️  仍有Python进程在运行:"
    echo "$PYTHON_PROCESSES"
else
    echo "✅ 所有API相关进程已停止"
fi

echo "🗑️ 清理日志文件..."
rm -f ~/api_server_debug.log 2>/dev/null
EOF

chmod +x "$STOP_API_SCRIPT"

echo ""
echo "✅ 诊断和修复脚本创建完成!"
echo ""
echo "🔧 使用以下命令进行故障排除:"
echo "   ~/test_api_server.py        # 测试API服务器"
echo "   ~/start_api_manual.sh       # 手动启动API服务器"
echo "   ~/stop_api_server.sh        # 停止API服务器"
echo "   cat ~/api_server_debug.log  # 查看详细日志"
echo ""
echo "💡 如果问题仍然存在，请提供以下信息:"
echo "   1. 运行 ~/test_api_server.py 的输出"
echo "   2. ~/api_server_debug.log 文件内容"
echo "   3. 运行 ps aux | grep python 的输出"