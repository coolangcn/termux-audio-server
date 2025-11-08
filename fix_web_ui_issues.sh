#!/data/data/com.termux/files/usr/bin/bash

# 修复网页控制面板问题的脚本

echo "🔧 修复网页控制面板问题..."

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
cp "$API_SCRIPT" "${API_SCRIPT}.ui_fix_backup"

# 1. 修复日志功能
echo "1. 修复日志功能..."

# 创建日志目录
LOG_DIR="$HOME_DIR/audio_logs"
mkdir -p "$LOG_DIR"
echo "📁 创建日志目录: $LOG_DIR"

# 添加日志导入和配置（如果不存在）
if ! grep -q "import logging" "$API_SCRIPT"; then
    sed -i '2i import logging\nimport datetime' "$API_SCRIPT"
fi

# 添加日志配置
LOG_CONFIG='
# 配置操作日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("'"$LOG_DIR"'/operations.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# 添加操作日志装饰器
def log_operation(operation):
    def decorator(f):
        def wrapper(*args, **kwargs):
            logger.info(f"用户执行操作: {operation}")
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator
'

# 在适当位置添加日志配置
if ! grep -q "logger = logging.getLogger" "$API_SCRIPT"; then
    # 找到Flask应用初始化的位置
    LINE_NUM=$(grep -n "app = Flask" "$API_SCRIPT" | head -1 | cut -d: -f1)
    sed -i "${LINE_NUM}a\\
$LOG_CONFIG" "$API_SCRIPT"
fi

# 2. 为API端点添加日志装饰器
echo "2. 为API端点添加日志装饰器..."

# 为pause_toggle添加日志装饰器
sed -i '/def pause_toggle():/i\
@log_operation("播放/暂停切换")' "$API_SCRIPT"

# 为next_track添加日志装饰器
sed -i '/def next_track():/i\
@log_operation("下一首")' "$API_SCRIPT"

# 为prev_track添加日志装饰器
sed -i '/def prev_track():/i\
@log_operation("上一首")' "$API_SCRIPT"

# 为stop_playback添加日志装饰器
sed -i '/def stop_playback():/i\
@log_operation("停止播放")' "$API_SCRIPT"

# 为shuffle_playlist添加日志装饰器
sed -i '/def shuffle_playlist():/i\
@log_operation("随机播放")' "$API_SCRIPT"

# 为play_track添加日志装饰器
sed -i '/def play_track(index):/i\
@log_operation("播放指定歌曲")' "$API_SCRIPT"

# 为adjust_volume添加日志装饰器
sed -i '/def adjust_volume():/i\
@log_operation("调整音量")' "$API_SCRIPT"

# 为set_volume添加日志装饰器
sed -i '/def set_volume():/i\
@log_operation("设置音量")' "$API_SCRIPT"

# 为sync_files添加日志装饰器
sed -i '/def sync_files():/i\
@log_operation("手动同步文件")' "$API_SCRIPT"

# 3. 添加日志API端点
echo "3. 添加日志API端点..."

LOG_ENDPOINTS='
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
sed -i '/if __name__ == '\''__main__'\'':/i\'"$LOG_ENDPOINTS" "$API_SCRIPT"

# 4. 修复网页控制面板HTML和JavaScript
echo "4. 修复网页控制面板..."

# 备份web_control_panel函数
WEB_PANEL_START=$(grep -n "def web_control_panel" "$API_SCRIPT" | cut -d: -f1)
WEB_PANEL_END=$(grep -n "return render_template_string(html_template)" "$API_SCRIPT" | cut -d: -f1)

# 创建新的网页控制面板
NEW_WEB_PANEL='
@app.route('/', methods=['GET'])
def web_control_panel():
    """改进版网页控制面板 - 带操作反馈和日志显示"""
    html_template = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>音频控制面板</title>
    <style>
        :root {
            --primary-color: #007AFF;
            --success-color: #34C759;
            --danger-color: #FF3B30;
            --warning-color: #FFCC00;
            --gray-color: #F2F2F7;
            --dark-gray: #8E8E93;
            --light-gray: #E5E5EA;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
        }
        
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(10px);
            border-radius: 20px;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.2);
            max-width: 600px;
            margin: 0 auto;
            padding: 30px;
        }
        
        h1 {
            text-align: center;
            color: #333;
            margin-bottom: 30px;
            background: linear-gradient(45deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .status-card {
            background: var(--gray-color);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 25px;
        }
        
        .status-item {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
        }
        
        .status-label {
            color: var(--dark-gray);
            font-weight: 500;
        }
        
        .status-value {
            color: #333;
            font-weight: 600;
            text-align: right;
            max-width: 60%;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        
        .progress-container {
            background: var(--light-gray);
            border-radius: 10px;
            height: 8px;
            margin: 15px 0;
            overflow: hidden;
        }
        
        .progress-bar {
            height: 100%;
            background: linear-gradient(90deg, var(--primary-color), #5856D6);
            border-radius: 10px;
            width: 0%;
            transition: width 0.3s ease;
        }
        
        .time-info {
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            color: var(--dark-gray);
            margin-top: 5px;
        }
        
        .controls-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin-bottom: 25px;
        }
        
        .control-btn {
            background: white;
            border: 1px solid var(--light-gray);
            border-radius: 14px;
            padding: 15px 5px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 5px;
        }
        
        .control-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.15);
        }
        
        .control-btn:active {
            transform: translateY(0);
        }
        
        .control-btn.primary {
            background: linear-gradient(45deg, var(--primary-color), #5856D6);
            color: white;
            border: none;
        }
        
        .control-btn.success {
            background: linear-gradient(45deg, var(--success-color), #30D158);
            color: white;
            border: none;
        }
        
        .control-btn.danger {
            background: linear-gradient(45deg, var(--danger-color), #FF453A);
            color: white;
            border: none;
        }
        
        .volume-control {
            margin-bottom: 25px;
        }
        
        .volume-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 10px;
        }
        
        .volume-label {
            font-size: 16px;
            font-weight: 600;
            color: #333;
        }
        
        .volume-value {
            font-size: 14px;
            color: var(--dark-gray);
            min-width: 40px;
            text-align: right;
        }
        
        .volume-slider {
            width: 100%;
            height: 6px;
            -webkit-appearance: none;
            background: var(--light-gray);
            border-radius: 3px;
            outline: none;
        }
        
        .volume-slider::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: var(--primary-color);
            cursor: pointer;
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
        }
        
        .search-box {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        
        .search-input {
            flex: 1;
            padding: 12px 15px;
            border: 1px solid var(--light-gray);
            border-radius: 12px;
            font-size: 16px;
            outline: none;
            transition: border-color 0.2s ease;
        }
        
        .search-input:focus {
            border-color: var(--primary-color);
            box-shadow: 0 0 0 2px rgba(0, 122, 255, 0.2);
        }
        
        .search-btn {
            padding: 12px 20px;
            background: var(--primary-color);
            color: white;
            border: none;
            border-radius: 12px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s ease;
        }
        
        .search-btn:hover {
            background: #0062CC;
        }
        
        .file-list {
            max-height: 300px;
            overflow-y: auto;
            border-radius: 16px;
            background: rgba(255, 255, 255, 0.8);
            border: 1px solid var(--light-gray);
            margin-bottom: 25px;
        }
        
        .file-item {
            padding: 15px 20px;
            border-bottom: 1px solid var(--light-gray);
            cursor: pointer;
            transition: background 0.2s ease;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        .file-item:last-child {
            border-bottom: none;
        }
        
        .file-item:hover {
            background: var(--gray-color);
        }
        
        .file-icon {
            font-size: 18px;
        }
        
        .file-name {
            flex: 1;
            font-size: 16px;
            color: #333;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        
        .playing-indicator {
            color: var(--primary-color);
            font-weight: 600;
        }
        
        .log-section {
            margin-top: 30px;
        }
        
        .log-section h3 {
            margin-bottom: 15px;
            color: #333;
        }
        
        .log-buttons {
            display: flex;
            gap: 10px;
            margin-bottom: 10px;
        }
        
        .log-btn {
            flex: 1;
            padding: 10px;
            border: none;
            border-radius: 8px;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        
        .log-btn.refresh {
            background: var(--primary-color);
            color: white;
        }
        
        .log-btn.clear {
            background: var(--danger-color);
            color: white;
        }
        
        .log-container {
            background: var(--gray-color);
            border-radius: 12px;
            padding: 15px;
            max-height: 200px;
            overflow-y: auto;
            font-family: "Courier New", monospace;
            font-size: 12px;
            line-height: 1.4;
        }
        
        .log-entry {
            margin-bottom: 5px;
            word-break: break-all;
        }
        
        .feedback-message {
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(0, 0, 0, 0.8);
            color: white;
            padding: 10px 20px;
            border-radius: 8px;
            z-index: 1000;
            opacity: 0;
            transition: opacity 0.3s ease;
        }
        
        .feedback-message.show {
            opacity: 1;
        }
        
        /* 滚动条样式 */
        .file-list::-webkit-scrollbar, .log-container::-webkit-scrollbar {
            width: 8px;
        }
        
        .file-list::-webkit-scrollbar-track, .log-container::-webkit-scrollbar-track {
            background: rgba(0, 0, 0, 0.05);
            border-radius: 4px;
        }
        
        .file-list::-webkit-scrollbar-thumb, .log-container::-webkit-scrollbar-thumb {
            background: var(--dark-gray);
            border-radius: 4px;
        }
        
        .file-list::-webkit-scrollbar-thumb:hover, .log-container::-webkit-scrollbar-thumb:hover {
            background: #666;
        }
        
        @media (max-width: 600px) {
            .container {
                padding: 20px;
                margin: 10px;
            }
            
            .controls-grid {
                gap: 10px;
            }
            
            .control-btn {
                padding: 12px 5px;
                font-size: 12px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎵 音频控制面板</h1>
        
        <div class="status-card">
            <div class="status-item">
                <span class="status-label">当前播放:</span>
                <span class="status-value" id="current-file">未知</span>
            </div>
            <div class="status-item">
                <span class="status-label">播放状态:</span>
                <span class="status-value" id="play-status">未知</span>
            </div>
            <div class="status-item">
                <span class="status-label">音量:</span>
                <span class="status-value" id="volume">0%</span>
            </div>
            
            <div class="progress-container">
                <div class="progress-bar" id="progress-bar"></div>
            </div>
            <div class="time-info">
                <span id="current-time">00:00</span>
                <span id="total-time">00:00</span>
            </div>
        </div>
        
        <div class="controls-grid">
            <button class="control-btn" onclick="prevTrack()">
                ⏮️ 上一首
            </button>
            <button class="control-btn primary" onclick="pauseToggle()" id="play-pause-btn">
                ⏯️ 播放
            </button>
            <button class="control-btn" onclick="nextTrack()">
                ⏭️ 下一首
            </button>
            <button class="control-btn" onclick="shufflePlaylist()">
                🔀 随机播放
            </button>
            <button class="control-btn success" onclick="syncFiles()">
                🔄 同步
            </button>
            <button class="control-btn danger" onclick="stopPlayback()">
                ⏹️ 停止
            </button>
        </div>
        
        <div class="volume-control">
            <div class="volume-header">
                <span class="volume-label">🔈 音量控制</span>
                <span class="volume-value" id="volume-value">50%</span>
            </div>
            <input type="range" class="volume-slider" id="volume-slider" min="0" max="100" value="50" oninput="adjustVolume(this.value)">
        </div>
        
        <div class="search-box">
            <input type="text" class="search-input" id="search-input" placeholder="搜索歌曲...">
            <button class="search-btn" onclick="searchFiles()">搜索</button>
        </div>
        
        <div class="file-list" id="file-list">
            <!-- 文件列表将在这里显示 -->
        </div>
        
        <div class="log-section">
            <h3>📝 操作日志</h3>
            <div class="log-buttons">
                <button class="log-btn refresh" onclick="loadLogs()">刷新日志</button>
                <button class="log-btn clear" onclick="clearLogs()">清空日志</button>
            </div>
            <div class="log-container" id="log-container">
                <div id="log-content">加载中...</div>
            </div>
        </div>
    </div>
    
    <div class="feedback-message" id="feedback-message"></div>

    <script>
        // 全局变量
        let currentStatus = {};
        let updateInterval;
        let logUpdateInterval;
        
        // 显示反馈消息
        function showFeedback(message, type = 'info') {
            const feedback = document.getElementById('feedback-message');
            feedback.textContent = message;
            feedback.className = 'feedback-message show';
            
            // 3秒后隐藏消息
            setTimeout(() => {
                feedback.className = 'feedback-message';
            }, 3000);
        }
        
        // 格式化时间（秒转为mm:ss）
        function formatTime(seconds) {
            if (isNaN(seconds) || seconds <= 0) return '00:00';
            const mins = Math.floor(seconds / 60);
            const secs = Math.floor(seconds % 60);
            return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
        }
        
        // 更新状态信息
        function updateStatus() {
            fetch('/mpv/status')
                .then(response => response.json())
                .then(data => {
                    currentStatus = data;
                    
                    // 更新基本信息
                    document.getElementById('current-file').textContent = data.current_file || '无';
                    document.getElementById('play-status').textContent = data.paused ? '已暂停' : '正在播放';
                    document.getElementById('volume').textContent = Math.round(data.volume) + '%' || '0%';
                    document.getElementById('volume-slider').value = Math.round(data.volume) || 0;
                    document.getElementById('volume-value').textContent = Math.round(data.volume) + '%' || '0%';
                    
                    // 更新播放进度
                    const progressBar = document.getElementById('progress-bar');
                    const currentTime = document.getElementById('current-time');
                    const totalTime = document.getElementById('total-time');
                    
                    if (data.position && data.duration) {
                        const progress = (data.position / data.duration) * 100;
                        progressBar.style.width = progress + '%';
                        currentTime.textContent = formatTime(data.position);
                        totalTime.textContent = formatTime(data.duration);
                    } else {
                        progressBar.style.width = '0%';
                        currentTime.textContent = '00:00';
                        totalTime.textContent = '00:00';
                    }
                    
                    // 更新播放/暂停按钮文本
                    const playPauseBtn = document.getElementById('play-pause-btn');
                    playPauseBtn.innerHTML = data.paused ? '▶️ 播放' : '⏸️ 暂停';
                })
                .catch(error => {
                    console.error('Error updating status:', error);
                });
        }
        
        // 更新文件列表
        function updateFileList(files) {
            const fileList = document.getElementById('file-list');
            fileList.innerHTML = '';
            
            files.forEach((file, index) => {
                const fileItem = document.createElement('div');
                fileItem.className = 'file-item';
                
                // 检查是否是当前播放的文件
                const isPlaying = currentStatus.current_file === file;
                
                fileItem.innerHTML = `
                    <span class="file-icon">🎵</span>
                    <span class="file-name${isPlaying ? ' playing-indicator' : ''}">${file}${isPlaying ? ' (正在播放)' : ''}</span>
                `;
                
                fileItem.onclick = () => playTrack(index);
                fileList.appendChild(fileItem);
            });
        }
        
        // 获取所有文件
        function getAllFiles() {
            fetch('/files')
                .then(response => response.json())
                .then(data => {
                    updateFileList(data.files);
                })
                .catch(error => {
                    console.error('Error fetching files:', error);
                });
        }
        
        // 搜索文件
        function searchFiles() {
            const query = document.getElementById('search-input').value;
            const url = query ? `/files/search?q=${encodeURIComponent(query)}` : '/files';
            
            fetch(url)
                .then(response => response.json())
                .then(data => {
                    updateFileList(data.files);
                })
                .catch(error => {
                    console.error('Error searching files:', error);
                });
        }
        
        // 控制API调用
        function callAPI(endpoint, options = {}) {
            showFeedback('正在执行操作...');
            
            return fetch(endpoint, options)
                .then(response => response.json())
                .then(data => {
                    console.log('API Response:', data);
                    showFeedback('操作成功!', 'success');
                    // 立即更新状态
                    setTimeout(updateStatus, 100);
                    // 重新加载日志
                    setTimeout(loadLogs, 200);
                    return data;
                })
                .catch(error => {
                    console.error('API Error:', error);
                    showFeedback('操作失败: ' + error.message, 'error');
                    throw error;
                });
        }
        
        // 控制函数
        function pauseToggle() {
            callAPI('/mpv/pause');
        }
        
        function nextTrack() {
            callAPI('/mpv/next');
        }
        
        function prevTrack() {
            callAPI('/mpv/prev');
        }
        
        function stopPlayback() {
            if (confirm('确定要停止播放吗？')) {
                callAPI('/mpv/stop');
            }
        }
        
        function shufflePlaylist() {
            callAPI('/mpv/shuffle');
        }
        
        function playTrack(index) {
            callAPI(`/mpv/play/${index}`);
        }
        
        function adjustVolume(value) {
            document.getElementById('volume-value').textContent = value + '%';
            callAPI(`/mpv/volume/set?value=${value}`);
        }
        
        function syncFiles() {
            if (confirm('确定要同步NAS文件吗？')) {
                callAPI('/files/sync', { method: 'POST' });
            }
        }
        
        // 日志相关函数
        function loadLogs() {
            fetch('/logs')
                .then(response => response.json())
                .then(data => {
                    const logContent = document.getElementById('log-content');
                    if (data.logs && data.logs.length > 0) {
                        // 反转日志顺序，最新的在上面
                        logContent.innerHTML = data.logs.reverse().map(log => 
                            `<div class="log-entry">${log.trim()}</div>`
                        ).join('');
                    } else {
                        logContent.innerHTML = '<div class="log-entry">暂无操作日志</div>';
                    }
                    
                    // 滚动到底部
                    const logContainer = document.getElementById('log-container');
                    logContainer.scrollTop = logContainer.scrollHeight;
                })
                .catch(error => {
                    console.error('Error loading logs:', error);
                    document.getElementById('log-content').innerHTML = '<div class="log-entry">加载日志失败</div>';
                });
        }
        
        function clearLogs() {
            if (confirm('确定要清空所有操作日志吗？')) {
                callAPI('/logs/clear', { method: 'POST' })
                    .then(() => {
                        loadLogs();
                    });
            }
        }
        
        // 页面加载完成后初始化
        document.addEventListener('DOMContentLoaded', function() {
            // 初始化状态更新
            updateStatus();
            getAllFiles();
            loadLogs();
            
            // 每1秒更新一次状态（实时更新播放进度）
            updateInterval = setInterval(updateStatus, 1000);
            
            // 每5秒更新一次日志
            logUpdateInterval = setInterval(loadLogs, 5000);
            
            // 搜索框回车事件
            document.getElementById('search-input').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    searchFiles();
                }
            });
        });
        
        // 页面卸载时清理定时器
        window.addEventListener('beforeunload', function() {
            if (updateInterval) clearInterval(updateInterval);
            if (logUpdateInterval) clearInterval(logUpdateInterval);
        });
    </script>
</body>
</html>
    """
    return render_template_string(html_template)
'

# 替换整个web_control_panel函数
sed -i "${WEB_PANEL_START},${WEB_PANEL_END}d" "$API_SCRIPT"
echo "$NEW_WEB_PANEL" >> "$API_SCRIPT"

echo "✅ 网页控制面板问题修复完成!"
echo ""
echo "📌 新增功能:"
echo "   • 即时按钮点击反馈"
echo "   • 操作日志实时显示"
echo "   • 响应式设计优化"
echo "   • 更好的用户体验"
echo ""
echo "📁 日志文件位置: $LOG_DIR/operations.log"
echo ""
echo "🔧 请重新启动音频服务器以应用更改："
echo "   ~/stop_audio_server"
echo "   ~/start_audio_server"