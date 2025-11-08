import os
import json
import random
import threading
import time
import logging
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import logging.config

# 禁用Flask的默认日志记录
log = logging.getLogger('werkzeug')
log.setLevel(logging.ERROR)

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# MPV Socket路径
MPV_SOCKET_PATH = "/data/data/com.termux/files/usr/tmp/mpv_ctrl/socket"

# 本地缓存目录
LOCAL_DIR = "/data/data/com.termux/files/home/nas_audio_cache"

# 自动缓存线程控制
auto_cache_thread = None
auto_cache_running = False

# 配置操作日志
LOG_DIR = "/data/data/com.termux/files/home/audio_logs"
os.makedirs(LOG_DIR, exist_ok=True)

# 创建专门的操作日志记录器
operation_logger = logging.getLogger('operations')
operation_logger.setLevel(logging.INFO)

# 创建文件处理器
file_handler = logging.FileHandler(f"{LOG_DIR}/operations.log")
file_handler.setLevel(logging.INFO)

# 创建日志格式
formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
file_handler.setFormatter(formatter)

# 添加处理器到记录器
operation_logger.addHandler(file_handler)
operation_logger.propagate = False  # 防止日志传播到父记录器

# 添加操作日志装饰器
def log_operation(operation):
    def decorator(f):
        def wrapper(*args, **kwargs):
            operation_logger.info(f"用户执行操作: {operation}")
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator

def send_mpv_command(command):
    """使用 socat 向 mpv socket 发送命令"""
    if not os.path.exists(MPV_SOCKET_PATH):
        return False, f"MPV Socket not found at {MPV_SOCKET_PATH}. Is MPV running?"

    json_command = json.dumps({"command": command})
    
    # 使用 socat 执行命令
    cmd = f'echo \'{json_command}\' | socat -t 0 - UNIX-CONNECT:{MPV_SOCKET_PATH}'
    result = os.system(cmd)
    
    if result == 0:
        return True, "Command sent successfully."
    else:
        return False, "Failed to send command via socat."

def get_mpv_property(property_name):
    """获取MPV属性值"""
    if not os.path.exists(MPV_SOCKET_PATH):
        return None, f"MPV Socket not found at {MPV_SOCKET_PATH}. Is MPV running?"

    json_command = json.dumps({"command": ["get_property", property_name]})
    
    # 使用socat发送命令并获取输出
    import subprocess
    try:
        result = subprocess.run(
            ['socat', '-t', '1', '-', f'UNIX-CONNECT:{MPV_SOCKET_PATH}'],
            input=json_command,
            text=True,
            capture_output=True
        )
        if result.returncode == 0:
            response = json.loads(result.stdout.strip())
            if 'data' in response:
                return response['data'], "Success"
        return None, "Failed to get property"
    except Exception as e:
        return None, str(e)

def get_audio_files():
    """获取本地缓存目录中的音频文件列表"""
    if not os.path.exists(LOCAL_DIR):
        return []
    
    audio_extensions = ('.mp3', '.flac', '.ogg', '.aac', '.m4a', '.wav', '.mp4')
    files = []
    for file in os.listdir(LOCAL_DIR):
        if file.lower().endswith(audio_extensions):
            files.append(file)
    return sorted(files)

def rclone_sync():
    """同步NAS到本地缓存"""
    try:
        # 这里需要根据实际的rclone配置调整
        rclone_remote = "synology:download/bilibili/push"
        includes = "--include '*.mp4' --include '*.mp3' --include '*.flac' --include '*.ogg' --include '*.aac' --include '*.m4a' --include '*.wav'"
        
        cmd = f"rclone copy '{rclone_remote}' '{LOCAL_DIR}' {includes} -P"
        result = os.system(cmd)
        
        if result == 0:
            return True, "Sync completed successfully"
        else:
            return False, "Sync failed"
    except Exception as e:
        return False, str(e)

def auto_cache_worker():
    """自动缓存工作线程"""
    global auto_cache_running
    while auto_cache_running:
        try:
            # 每30分钟检查一次新文件
            rclone_sync()
            time.sleep(1800)  # 30分钟
        except Exception as e:
            print(f"Auto cache error: {e}")
            time.sleep(1800)

# API路由

@app.route('/mpv/pause', methods=['GET'])
@log_operation("播放/暂停切换")
def pause_toggle():
    success, message = send_mpv_command(["cycle", "pause"])
    if success:
        return jsonify({"status": "ok", "action": "pause_toggle"}), 200
    return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/next', methods=['GET'])
@log_operation("下一首")
def next_track():
    success, message = send_mpv_command(["playlist-next"])
    if success:
        return jsonify({"status": "ok", "action": "next_track"}), 200
    return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/prev', methods=['GET'])
@log_operation("上一首")
def prev_track():
    success, message = send_mpv_command(["playlist-prev"])
    if success:
        return jsonify({"status": "ok", "action": "prev_track"}), 200
    return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/stop', methods=['GET'])
@log_operation("停止播放")
def stop_playback():
    success, message = send_mpv_command(["quit"])
    if success:
        return jsonify({"status": "ok", "action": "stop"}), 200
    return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/volume', methods=['GET'])
@log_operation("调整音量")
def adjust_volume():
    try:
        value = int(request.args.get('value', 0))
    except ValueError:
        return jsonify({"status": "error", "message": "Query parameter 'value' must be an integer."}), 400
    
    success, message = send_mpv_command(["add", "volume", str(value)])
    
    if success:
        return jsonify({"status": "ok", "action": "adjust_volume", "change": value}), 200
    return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/volume/set', methods=['GET'])
@log_operation("设置音量")
def set_volume():
    try:
        value = int(request.args.get('value', 50))
        value = max(0, min(100, value))  # 限制在0-100之间
    except ValueError:
        return jsonify({"status": "error", "message": "Query parameter 'value' must be an integer between 0 and 100."}), 400
    
    success, message = send_mpv_command(["set", "volume", str(value)])
    
    if success:
        return jsonify({"status": "ok", "action": "set_volume", "volume": value}), 200
    return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/shuffle', methods=['GET'])
@log_operation("随机播放")
def shuffle_playlist():
    """随机播放"""
    # 获取当前播放列表
    playlist, msg = get_mpv_property("playlist")
    if playlist is None:
        return jsonify({"status": "error", "message": "Failed to get playlist"}), 500
    
    # 随机打乱播放列表
    success, message = send_mpv_command(["playlist-shuffle"])
    if success:
        return jsonify({"status": "ok", "action": "shuffle_playlist"}), 200
    return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/play/<int:index>', methods=['GET'])
@log_operation("播放指定歌曲")
def play_track(index):
    """播放指定索引的歌曲"""
    success, message = send_mpv_command(["playlist-play-index", str(index)])
    if success:
        return jsonify({"status": "ok", "action": "play_track", "index": index}), 200
    return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/status', methods=['GET'])
def get_status():
    """获取播放状态"""
    status = {}
    
    # 获取播放状态
    pause_state, _ = get_mpv_property("pause")
    status["paused"] = pause_state if pause_state is not None else False
    
    # 获取当前播放文件
    filename, _ = get_mpv_property("filename")
    status["current_file"] = filename if filename is not None else ""
    
    # 获取音量
    volume, _ = get_mpv_property("volume")
    status["volume"] = volume if volume is not None else 0
    
    # 获取播放列表
    playlist, _ = get_mpv_property("playlist")
    status["playlist"] = playlist if playlist is not None else []
    
    # 获取播放位置和持续时间
    position, _ = get_mpv_property("time-pos")
    duration, _ = get_mpv_property("duration")
    status["position"] = position if position is not None else 0
    status["duration"] = duration if duration is not None else 0
    
    return jsonify(status), 200

@app.route('/files', methods=['GET'])
def list_files():
    """列出所有音频文件"""
    files = get_audio_files()
    return jsonify({"files": files}), 200

@app.route('/files/search', methods=['GET'])
def search_files():
    """搜索音频文件"""
    query = request.args.get('q', '').lower()
    all_files = get_audio_files()
    
    if not query:
        return jsonify({"files": all_files}), 200
    
    # 筛选匹配的文件
    matched_files = [f for f in all_files if query in f.lower()]
    return jsonify({"files": matched_files}), 200

@app.route('/files/sync', methods=['POST'])
@log_operation("手动同步文件")
def sync_files():
    """手动同步NAS文件"""
    success, message = rclone_sync()
    if success:
        return jsonify({"status": "ok", "message": "Sync completed successfully"}), 200
    return jsonify({"status": "error", "message": message}), 500

@app.route('/logs', methods=['GET'])
def get_logs():
    """获取操作日志"""
    try:
        log_file = f"{LOG_DIR}/operations.log"
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
@log_operation("清空操作日志")
def clear_logs():
    """清空操作日志"""
    try:
        log_file = f"{LOG_DIR}/operations.log"
        if os.path.exists(log_file):
            open(log_file, "w").close()
            return jsonify({"message": "日志已清空"}), 200
        else:
            return jsonify({"message": "日志文件不存在"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/', methods=['GET'])
def web_control_panel():
    """网页控制面板"""
    html_template = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>音频控制面板</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f0f0f0;
        }
        .container {
            background: linear-gradient(135deg, #f5f7fa 0%, #c3cfe2 100%);
            border-radius: 15px;
            padding: 25px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
            border: 1px solid rgba(255,255,255,0.2);
        }
        h1 {
            text-align: center;
            color: #333;
        }
        .controls {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin-bottom: 20px;
        }
        .control-btn {
            padding: 18px;
            font-size: 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            transition: all 0.3s ease;
            font-weight: 500;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        .control-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }
        .primary {
            background-color: #007bff;
            color: white;
        }
        .secondary {
            background-color: #6c757d;
            color: white;
        }
        .success {
            background-color: #28a745;
            color: white;
        }
        .danger {
            background-color: #dc3545;
            color: white;
        }
        .volume-control {
            display: flex;
            align-items: center;
            gap: 10px;
            margin-bottom: 20px;
        }
        .volume-control input {
            flex: 1;
            height: 10px;
            border-radius: 5px;
            background: #ddd;
            outline: none;
            transition: all 0.3s;
        }
        .volume-control input::-webkit-slider-thumb {
            appearance: none;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: #007bff;
            cursor: pointer;
            box-shadow: 0 2px 6px rgba(0,0,0,0.2);
            transition: all 0.2s;
        }
        .volume-control input::-webkit-slider-thumb:hover {
            transform: scale(1.2);
            background: #0056b3;
        }
        .file-list {
            margin-top: 20px;
        }
        .file-item {
            padding: 12px 15px;
            border-bottom: 1px solid #e9ecef;
            cursor: pointer;
            transition: all 0.3s ease;
            border-radius: 6px;
            margin-bottom: 5px;
        }
        .file-item:hover {
            background-color: rgba(0,123,255,0.1);
            transform: translateX(5px);
            border-left: 4px solid #007bff;
        }
        .status {
            padding: 10px;
            background-color: #e9ecef;
            border-radius: 5px;
            margin-bottom: 20px;
        }
        .search-box {
            margin-bottom: 20px;
        }
        .search-box input {
            width: 70%;
            padding: 10px;
            border: 1px solid #ddd;
            border-radius: 5px;
        }
        .search-box button {
            padding: 10px 15px;
            background-color: #007bff;
            color: white;
            border: none;
            border-radius: 5px;
            cursor: pointer;
        }
        .log-section {
            margin-top: 30px;
        }
        .log-section h3 {
            margin-bottom: 10px;
        }
        .log-buttons {
            margin-bottom: 10px;
        }
        .log-btn {
            padding: 8px 12px;
            margin-right: 10px;
            border: none;
            border-radius: 4px;
            cursor: pointer;
        }
        .log-container {
            background: #f8f9fa;
            border: 1px solid #dee2e6;
            border-radius: 4px;
            padding: 10px;
            height: 200px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎵 音频控制面板</h1>
        
        <div class="status" id="status">
            <div>当前播放: <span id="current-file">未知</span></div>
            <div>播放状态: <span id="play-status">未知</span></div>
            <div>音量: <span id="volume">0</span>%</div>
        </div>
        
        <div class="controls">
            <button class="control-btn primary" onclick="pauseToggle()">⏯️ 播放/暂停</button>
            <button class="control-btn primary" onclick="nextTrack()">⏭️ 下一首</button>
            <button class="control-btn primary" onclick="prevTrack()">⏮️ 上一首</button>
        </div>
        
        <div class="volume-control">
            <span>🔈 音量控制:</span>
            <input type="range" id="volume-slider" min="0" max="100" value="50" oninput="adjustVolume(this.value)">
            <span id="volume-value">50</span>%
        </div>
        
        <div class="search-box">
            <input type="text" id="search-input" placeholder="搜索歌曲...">
            <button onclick="searchFiles()">搜索</button>
        </div>
        
        <div class="file-list">
            <h3>🎵 歌曲列表</h3>
            <div id="file-list">
                <!-- 文件列表将在这里显示 -->
            </div>
        </div>
        
        <div class="log-section">
            <h3>📝 操作日志</h3>
            <div class="log-buttons">
                <button class="log-btn primary" onclick="loadLogs()">刷新日志</button>
                <button class="log-btn danger" onclick="clearLogs()">清空日志</button>
            </div>
            <div class="log-container" id="log-container">
                <div id="log-content">加载中...</div>
            </div>
        </div>
    </div>

    <script>
        // 更新状态信息
        function updateStatus() {
            fetch('/mpv/status')
                .then(response => response.json())
                .then(data => {
                    document.getElementById('current-file').textContent = data.current_file || '无';
                    document.getElementById('play-status').textContent = data.paused ? '已暂停' : '正在播放';
                    document.getElementById('volume').textContent = Math.round(data.volume) || 0;
                    document.getElementById('volume-slider').value = Math.round(data.volume) || 0;
                    document.getElementById('volume-value').textContent = Math.round(data.volume) || 0;
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
                fileItem.textContent = file;
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
        function callAPI(endpoint) {
            fetch(endpoint)
                .then(response => {
                    if (!response.ok) {
                        throw new Error('Network response was not ok');
                    }
                    return response.json();
                })
                .then(data => {
                    console.log('API Response:', data);
                    if (data.status === 'error') {
                        alert('操作失败: ' + data.message);
                    } else {
                        // 操作成功，更新状态和日志
                        setTimeout(updateStatus, 500); // 稍后更新状态
                        loadLogs(); // 更新日志
                    }
                })
                .catch(error => {
                    console.error('API Error:', error);
                    alert('API调用失败: ' + error.message);
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
        
        // 这些功能已被移除但保留函数定义以避免错误
        function stopPlayback() {}
        function shufflePlaylist() {}
        
        function playTrack(index) {
            callAPI(`/mpv/play/${index}`);
        }
        
        function adjustVolume(value) {
            // 立即更新UI
            document.getElementById('volume-value').textContent = value;
            
            // 发送API请求设置音量
            fetch(`/mpv/volume/set?value=${value}`)
                .then(response => response.json())
                .then(data => {
                    console.log('音量设置成功:', data);
                    // 强制更新状态以确保同步
                    setTimeout(updateStatus, 100);
                })
                .catch(error => {
                    console.error('音量设置失败:', error);
                });
        }
        
        // 同步文件功能已被移除
        function syncFiles() {}
        
        // 日志相关函数
        function loadLogs() {
            fetch('/logs')
                .then(response => response.json())
                .then(data => {
                    const logContent = document.getElementById('log-content');
                    if (data.logs && data.logs.length > 0) {
                        // 保持日志的正确顺序（最新的在底部）
                        logContent.innerHTML = data.logs.join('<br>');
                    } else {
                        logContent.innerHTML = '暂无操作日志';
                    }
                    
                    const logContainer = document.getElementById('log-container');
                    logContainer.scrollTop = logContainer.scrollHeight;
                })
                .catch(error => {
                    console.error('Error loading logs:', error);
                    document.getElementById('log-content').innerHTML = '加载日志失败';
                });
        }
        
        function clearLogs() {
            if (confirm('确定要清空所有操作日志吗？')) {
                fetch('/logs/clear', { method: 'POST' })
                    .then(response => response.json())
                    .then(data => {
                        alert(data.message);
                        loadLogs();
                    })
                    .catch(error => {
                        console.error('Clear logs error:', error);
                        alert('清空日志失败');
                    });
            }
        }
        
        // 初始化
        document.addEventListener('DOMContentLoaded', function() {
            updateStatus();
            getAllFiles();
            loadLogs(); // 加载日志
            
            // 每5秒更新一次状态
            setInterval(updateStatus, 5000);
            // 每10秒更新一次日志
            setInterval(loadLogs, 10000);
            
            // 搜索框回车事件
            document.getElementById('search-input').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    searchFiles();
                }
            });
        });
    </script>
</body>
</html>
    """
    return render_template_string(html_template)

if __name__ == '__main__':
    # 注意：0.0.0.0 允许从外部设备访问
    import os
    API_PORT = int(os.environ.get('API_PORT', 5000))
    print(f"🚀 启动API服务，绑定到 0.0.0.0:{API_PORT}")
    app.run(host='0.0.0.0', port=API_PORT, debug=False, threaded=True)