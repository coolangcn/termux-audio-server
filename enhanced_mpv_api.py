import os
import json
import random
import threading
import time
from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# MPV Socket路径
MPV_SOCKET_PATH = "/data/data/com.termux/files/usr/tmp/mpv_ctrl/socket"

# 本地缓存目录
LOCAL_DIR = "/data/data/com.termux/files/home/nas_audio_cache"

# 自动缓存线程控制
auto_cache_thread = None
auto_cache_running = False

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
def pause_toggle():
    success, message = send_mpv_command(["cycle", "pause"])
    if success:
        return jsonify({"status": "ok", "action": "pause_toggle"}), 200
    return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/next', methods=['GET'])
def next_track():
    success, message = send_mpv_command(["playlist-next"])
    if success:
        return jsonify({"status": "ok", "action": "next_track"}), 200
    return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/prev', methods=['GET'])
def prev_track():
    success, message = send_mpv_command(["playlist-prev"])
    if success:
        return jsonify({"status": "ok", "action": "prev_track"}), 200
    return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/stop', methods=['GET'])
def stop_playback():
    success, message = send_mpv_command(["quit"])
    if success:
        return jsonify({"status": "ok", "action": "stop"}), 200
    return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/volume', methods=['GET'])
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
    
    # 获取播放位置
    position, _ = get_mpv_property("time-pos")
    status["position"] = position if position is not None else 0
    
    # 获取总时长
    duration, _ = get_mpv_property("duration")
    status["duration"] = duration if duration is not None else 0
    
    return jsonify(status), 200

@app.route('/files', methods=['GET'])
def list_files():
    """列出本地音频文件"""
    files = get_audio_files()
    return jsonify({"files": files}), 200

@app.route('/files/search', methods=['GET'])
def search_files():
    """搜索音频文件"""
    query = request.args.get('q', '').lower()
    files = get_audio_files()
    if query:
        files = [f for f in files if query in f.lower()]
    return jsonify({"files": files}), 200

@app.route('/files/sync', methods=['POST'])
def sync_files():
    """手动同步NAS文件"""
    success, message = rclone_sync()
    if success:
        return jsonify({"status": "ok", "message": message}), 200
    return jsonify({"status": "error", "message": message}), 500

@app.route('/cache/auto', methods=['POST'])
def toggle_auto_cache():
    """切换自动缓存功能"""
    global auto_cache_thread, auto_cache_running
    
    action = request.args.get('action', 'start')
    
    if action == 'start':
        if not auto_cache_running:
            auto_cache_running = True
            auto_cache_thread = threading.Thread(target=auto_cache_worker)
            auto_cache_thread.daemon = True
            auto_cache_thread.start()
            return jsonify({"status": "ok", "message": "Auto cache started"}), 200
        else:
            return jsonify({"status": "ok", "message": "Auto cache already running"}), 200
    elif action == 'stop':
        auto_cache_running = False
        return jsonify({"status": "ok", "message": "Auto cache stopped"}), 200
    else:
        return jsonify({"status": "error", "message": "Invalid action. Use 'start' or 'stop'"}), 400

@app.route('/', methods=['GET'])
def web_control_panel():
    """网页控制面板"""
    html_template = '''
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
            background-color: white;
            border-radius: 10px;
            padding: 20px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }
        h1 {
            text-align: center;
            color: #333;
        }
        .controls {
            display: grid;
            grid-template-columns: repeat(2, 1fr);
            gap: 10px;
            margin-bottom: 20px;
        }
        .control-btn {
            padding: 15px;
            font-size: 16px;
            border: none;
            border-radius: 5px;
            cursor: pointer;
            transition: background-color 0.3s;
        }
        .control-btn:hover {
            opacity: 0.9;
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
        }
        .file-list {
            margin-top: 20px;
        }
        .file-item {
            padding: 10px;
            border-bottom: 1px solid #eee;
            cursor: pointer;
        }
        .file-item:hover {
            background-color: #f8f9fa;
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
            <button class="control-btn secondary" onclick="shufflePlaylist()">🔀 随机播放</button>
            <button class="control-btn success" onclick="syncFiles()">🔄 同步文件</button>
            <button class="control-btn danger" onclick="stopPlayback()">⏹️ 停止</button>
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
                .then(response => response.json())
                .then(data => {
                    console.log('API Response:', data);
                    setTimeout(updateStatus, 500); // 稍后更新状态
                })
                .catch(error => {
                    console.error('API Error:', error);
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
            document.getElementById('volume-value').textContent = value;
            callAPI(`/mpv/volume/set?value=${value}`);
        }
        
        function syncFiles() {
            if (confirm('确定要同步NAS文件吗？')) {
                fetch('/files/sync', { method: 'POST' })
                    .then(response => response.json())
                    .then(data => {
                        alert(data.message);
                        if (data.status === 'ok') {
                            getAllFiles(); // 更新文件列表
                        }
                    })
                    .catch(error => {
                        console.error('Sync Error:', error);
                    });
            }
        }
        
        // 初始化
        document.addEventListener('DOMContentLoaded', function() {
            updateStatus();
            getAllFiles();
            
            // 每5秒更新一次状态
            setInterval(updateStatus, 5000);
            
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
    '''
    return render_template_string(html_template)

if __name__ == '__main__':
    # 注意：0.0.0.0 允许从外部设备访问
    API_PORT = int(os.environ.get('API_PORT', 5000))
    app.run(host='0.0.0.0', port=API_PORT, debug=False)