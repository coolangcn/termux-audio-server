#!/data/data/com.termux/files/usr/bin/bash

# 重启音频服务器并确保操作日志功能正常工作的脚本

echo "🔄 重启音频服务器并启用操作日志功能..."

# 1. 停止当前服务
echo "⏹️ 停止当前音频服务器..."
~/stop_audio_server

# 等待服务完全停止
sleep 3

# 2. 检查是否有残留进程
echo "🔍 检查残留进程..."
RESIDUAL_PROCESSES=$(ps aux 2>/dev/null | grep -E "(mpv|python.*enhanced_mpv|socat)" | grep -v grep)
if [ -n "$RESIDUAL_PROCESSES" ]; then
    echo "⚠️ 发现残留进程，正在强制停止..."
    echo "$RESIDUAL_PROCESSES" | while read line; do
        PID=$(echo "$line" | awk '{print $2}')
        if [ -n "$PID" ]; then
            echo "   强制停止进程 PID: $PID"
            kill -9 "$PID" 2>/dev/null
        fi
    done
fi

# 3. 清理临时文件
echo "🗑️ 清理临时文件..."
rm -f ~/mpv_playlist_* 2>/dev/null

# 4. 创建日志目录（如果不存在）
LOG_DIR="$HOME/audio_logs"
mkdir -p "$LOG_DIR"
echo "📁 确保日志目录存在: $LOG_DIR"

# 5. 检查API脚本是否包含日志功能
HOME_DIR=$(eval echo ~)
API_SCRIPT="$HOME_DIR/termux-audio-server/enhanced_mpv_api.py"

if [ -f "$API_SCRIPT" ]; then
    echo "📝 检查API脚本日志功能..."
    
    # 检查是否已经有日志功能
    if grep -q "@app.route.*/logs.*" "$API_SCRIPT"; then
        echo "   ✅ API脚本已包含日志功能"
    else
        echo "   ⚠️ API脚本缺少日志功能，正在添加..."
        
        # 备份原文件
        cp "$API_SCRIPT" "${API_SCRIPT}.restart_backup"
        
        # 添加日志导入
        if ! grep -q "import logging" "$API_SCRIPT"; then
            sed -i '2i import logging\nimport datetime' "$API_SCRIPT"
        fi
        
        # 添加日志配置
        if ! grep -q "logging.basicConfig" "$API_SCRIPT"; then
            sed -i '/import datetime/a\
\
# 配置操作日志\
logging.basicConfig(\
    level=logging.INFO,\
    format="%(asctime)s [%(levelname)s] %(message)s",\
    handlers=[\
        logging.FileHandler("'"$LOG_DIR"'/operations.log"),\
        logging.StreamHandler()\
    ]\
)\
\
logger = logging.getLogger(__name__)' "$API_SCRIPT"
        fi
        
        # 添加日志端点
        LOG_ENDPOINT='
@app.route('/logs', methods=['GET'])
def get_logs():
    """获取操作日志"""
    try:
        log_file = "'"$LOG_DIR"'/operations.log"
        if os.path.exists(log_file):
            with open(log_file, "r") as f:
                lines = f.readlines()
                # 返回最后100行日志
                return jsonify({"logs": lines[-100:] if len(lines) > 100 else lines}), 200
        else:
            return jsonify({"logs": []}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/logs/clear', methods=['POST'])
def clear_logs():
    """清空操作日志"""
    try:
        log_file = "'"$LOG_DIR"'/operations.log"
        if os.path.exists(log_file):
            open(log_file, "w").close()
            logger.info("用户执行操作: 清空操作日志")
            return jsonify({"message": "日志已清空"}), 200
        else:
            return jsonify({"message": "日志文件不存在"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500
'
        
        # 在API脚本末尾添加日志端点（在if __name__ == '__main__'之前）
        sed -i '/if __name__ == '\''__main__'\''/i\'"$LOG_ENDPOINT" "$API_SCRIPT"
        
        echo "   ✅ 日志功能已添加到API脚本"
    fi
else
    echo "❌ API脚本不存在: $API_SCRIPT"
    exit 1
fi

# 6. 启动音频服务器
echo "▶️ 启动音频服务器..."
~/start_audio_server

# 7. 等待服务启动
echo "⏳ 等待服务启动..."
sleep 5

# 8. 验证服务状态
echo "✅ 验证服务状态..."
curl -s -m 3 http://127.0.0.1:5000/mpv/status > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "🎉 音频服务器启动成功！"
    
    # 记录启动日志
    echo "$(date '+%Y-%m-%d %H:%M:%S') [INFO] 音频服务器重启完成" >> "$LOG_DIR/operations.log"
    
    echo ""
    echo "📋 服务信息:"
    echo "   🎵 MPV播放器: 已启动"
    echo "   🌐 API服务: http://127.0.0.1:5000"
    echo "   📝 操作日志: $LOG_DIR/operations.log"
    echo "   📊 日志API: http://127.0.0.1:5000/logs"
    echo ""
    echo "💡 您现在可以访问控制面板并查看操作日志了！"
else
    echo "❌ 音频服务器启动失败"
    echo "📄 请检查日志文件: ~/api_server_debug.log"
fi