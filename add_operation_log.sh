#!/data/data/com.termux/files/usr/bin/bash

# 为音频控制面板添加操作日志功能的脚本

echo "📝 为音频控制面板添加操作日志功能..."

# 获取用户主目录
HOME_DIR=$(eval echo ~)
echo "🏠 用户主目录: $HOME_DIR"

# API脚本路径
API_SCRIPT="$HOME_DIR/termux-audio-server/enhanced_mpv_api.py"

# 检查API脚本是否存在
if [ ! -f "$API_SCRIPT" ]; then
    echo "❌ API脚本不存在: $API_SCRIPT"
    exit 1
fi

echo "📝 备份原API脚本..."
cp "$API_SCRIPT" "${API_SCRIPT}.log_backup"

# 创建日志目录
LOG_DIR="$HOME_DIR/audio_logs"
mkdir -p "$LOG_DIR"
echo "📁 创建日志目录: $LOG_DIR"

# 1. 添加日志功能到API脚本
echo "1. 添加日志功能到API脚本..."

# 添加日志导入和配置
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

# 2. 为每个API端点添加日志记录
echo "2. 为API端点添加日志记录..."

# 为pause_toggle添加日志
sed -i '/def pause_toggle():/a\    logger.info("用户执行操作: 播放/暂停切换")' "$API_SCRIPT"

# 为next_track添加日志
sed -i '/def next_track():/a\    logger.info("用户执行操作: 下一首")' "$API_SCRIPT"

# 为prev_track添加日志
sed -i '/def prev_track():/a\    logger.info("用户执行操作: 上一首")' "$API_SCRIPT"

# 为stop_playback添加日志
sed -i '/def stop_playback():/a\    logger.info("用户执行操作: 停止播放")' "$API_SCRIPT"

# 为shuffle_playlist添加日志
sed -i '/def shuffle_playlist():/a\    logger.info("用户执行操作: 随机播放")' "$API_SCRIPT"

# 为play_track添加日志
sed -i '/def play_track(index):/a\    logger.info(f"用户执行操作: 播放指定歌曲，索引: {index}")' "$API_SCRIPT"

# 为adjust_volume添加日志
sed -i '/def adjust_volume():/a\    logger.info(f"用户执行操作: 调整音量，变化值: {value}")' "$API_SCRIPT"

# 为set_volume添加日志
sed -i '/def set_volume():/a\    logger.info(f"用户执行操作: 设置音量，目标值: {value}")' "$API_SCRIPT"

# 为sync_files添加日志
sed -i '/def sync_files():/a\    logger.info("用户执行操作: 手动同步文件")' "$API_SCRIPT"

# 3. 更新网页控制面板以显示操作日志
echo "3. 更新网页控制面板以显示操作日志..."

# 创建日志查看API端点
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

# 在API脚本中添加日志端点
sed -i '/@app.route.*files.sync.*/a\'"$LOG_ENDPOINT" "$API_SCRIPT"

# 4. 更新网页控制面板HTML以显示日志
echo "4. 更新网页控制面板HTML以显示日志..."

# 备份web_control_panel函数
WEB_BACKUP="$HOME_DIR/web_control_panel_backup.html"
grep -A 1000 "def web_control_panel" "$API_SCRIPT" | grep -B 1000 "return render_template_string" > "$WEB_BACKUP"

# 更新HTML以包含日志显示区域
sed -i '/<div class="file-list">/i\
        <div class="log-section" style="margin-top: 30px;">\
            <h3>📝 操作日志</h3>\
            <div style="display: flex; gap: 10px; margin-bottom: 10px;">\
                <button class="search-btn" onclick="loadLogs()" style="flex: 1;">刷新日志</button>\
                <button class="control-btn danger" onclick="clearLogs()" style="flex: 1; padding: 12px;">清空日志</button>\
            </div>\
            <div id="log-container" style="background: #F2F2F7; border-radius: 16px; padding: 20px; max-height: 300px; overflow-y: auto; font-family: monospace; font-size: 14px;">\
                <div id="log-content" style="white-space: pre-wrap;">加载中...</div>\
            </div>\
        </div>' "$API_SCRIPT"

# 在JavaScript部分添加日志相关函数
sed -i '/function syncFiles()/a\
        \
        // 加载操作日志\
        function loadLogs() {\
            fetch("/logs")\
                .then(response => response.json())\
                .then(data => {\
                    const logContent = document.getElementById("log-content");\
                    if (data.logs && data.logs.length > 0) {\
                        logContent.innerHTML = data.logs.reverse().join("\\n");\
                    } else {\
                        logContent.innerHTML = "暂无操作日志";\
                    }\
                    \
                    // 滚动到底部\
                    const logContainer = document.getElementById("log-container");\
                    logContainer.scrollTop = logContainer.scrollHeight;\
                })\
                .catch(error => {\
                    console.error("加载日志失败:", error);\
                    document.getElementById("log-content").innerHTML = "加载日志失败";\
                });\
        }\
        \
        // 清空操作日志\
        function clearLogs() {\
            if (confirm("确定要清空所有操作日志吗？")) {\
                fetch("/logs/clear", { method: "POST" })\
                    .then(response => response.json())\
                    .then(data => {\
                        if (data.message) {\
                            alert(data.message);\
                            loadLogs();\
                        }\
                    })\
                    .catch(error => {\
                        console.error("清空日志失败:", error);\
                        alert("清空日志失败");\
                    });\
            }\
        }' "$API_SCRIPT"

# 在页面加载时自动加载日志
sed -i '/updateInterval = setInterval(updateStatus, 1000);/a\            // 加载操作日志\
            loadLogs();\
            // 每10秒刷新一次日志\
            setInterval(loadLogs, 10000);' "$API_SCRIPT"

echo "✅ 操作日志功能添加完成!"
echo ""
echo "📌 新增功能:"
echo "   • 所有用户操作都会记录到日志文件"
echo "   • 网页控制面板显示实时操作日志"
echo "   • 支持刷新和清空日志"
echo ""
echo "📁 日志文件位置: $LOG_DIR/operations.log"
echo ""
echo "🔧 使用以下命令查看日志:"
echo "   cat $LOG_DIR/operations.log"
echo ""
echo "📌 请重新启动音频服务器以应用更改："
echo "   ~/stop_audio_server"
echo "   ~/start_audio_server"