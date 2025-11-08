#!/data/data/com.termux/files/usr/bin/bash

# 修复日志路径问题的脚本

echo "🔧 修复日志路径问题..."

# 获取用户主目录的绝对路径
HOME_DIR=$(eval echo ~)
echo "🏠 用户主目录: $HOME_DIR"

# 修复enhanced_mpv_api.py中的日志路径
API_SCRIPT="$HOME_DIR/termux-audio-server/enhanced_mpv_api.py"
if [ -f "$API_SCRIPT" ]; then
    echo "📝 修复API脚本中的日志路径..."
    
    # 备份原文件
    cp "$API_SCRIPT" "${API_SCRIPT}.log_bak"
    
    # 替换日志文件路径中的波浪号
    sed -i "s|'~/api_server.log'|'$HOME_DIR/api_server.log'|g" "$API_SCRIPT"
    
    # 同时修复其他可能的波浪号路径
    sed -i "s|logging.FileHandler('~|logging.FileHandler('$HOME_DIR|g" "$API_SCRIPT"
    
    echo "✅ API脚本日志路径已修复"
else
    echo "❌ 未找到API脚本: $API_SCRIPT"
fi

# 修复start_api_server.py中的日志路径
START_API_SCRIPT="$HOME_DIR/start_api_server.py"
if [ -f "$START_API_SCRIPT" ]; then
    echo "📝 修复启动脚本中的日志路径..."
    
    # 备份原文件
    cp "$START_API_SCRIPT" "${START_API_SCRIPT}.log_bak"
    
    # 替换日志文件路径中的波浪号
    sed -i "s|'~/api_server.log'|'$HOME_DIR/api_server.log'|g" "$START_API_SCRIPT"
    sed -i "s|'~/api_server_debug.log'|'$HOME_DIR/api_server_debug.log'|g" "$START_API_SCRIPT"
    
    # 同时修复其他可能的波浪号路径
    sed -i "s|logging.FileHandler('~|logging.FileHandler('$HOME_DIR|g" "$START_API_SCRIPT"
    
    echo "✅ 启动脚本日志路径已修复"
else
    echo "⚠️  未找到启动脚本: $START_API_SCRIPT (将在后续步骤中创建)"
fi

# 创建一个新的、修复后的start_api_server.py
echo "📝 创建修复后的API启动脚本..."

cat > "$START_API_SCRIPT" << EOF
#!/data/data/com.termux/files/usr/bin/python
import os
import sys
import logging

# 添加项目目录到Python路径
project_dir = os.path.expanduser('~/termux-audio-server')
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)

# 配置日志
log_file_path = os.path.expanduser('~/api_server_debug.log')
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(log_file_path),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)
logger.info("🚀 开始启动API服务器...")
logger.info(f"🏠 用户主目录: {os.path.expanduser('~')}")
logger.info(f"📝 日志文件路径: {log_file_path}")

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

chmod +x "$START_API_SCRIPT"

echo "✅ 日志路径问题修复完成!"
echo ""
echo "📌 请重新测试API服务器:"
echo "   ~/test_api_server.py"
echo ""
echo "💡 或者手动启动API服务器:"
echo "   ~/start_api_manual.sh"