import os
import json
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
    """改进版网页控制面板 - macOS风格"""
    html_template = '''
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>音频控制面板</title>
    <style>
        :root {
            --macos-blue: #007AFF;
            --macos-gray: #F2F2F7;
            --macos-dark-gray: #8E8E93;
            --macos-light-gray: #E5E5EA;
            --macos-red: #FF3B30;
            --macos-green: #34C759;
            --macos-yellow: #FFCC00;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
        }
        
        body {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        
        .container {
            background: rgba(255, 255, 255, 0.95);
            backdrop-filter: blur(20px);
            border-radius: 20px;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.2);
            width: 100%;
            max-width: 500px;
            padding: 30px;
            border: 1px solid rgba(255, 255, 255, 0.3);
        }
        
        .title-bar {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 30px;
        }
        
        .title-bar h1 {
            font-size: 24px;
            font-weight: 700;
            color: #333;
            background: linear-gradient(45deg, #667eea, #764ba2);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        
        .traffic-lights {
            display: flex;
            gap: 8px;
        }
        
        .traffic-light {
            width: 14px;
            height: 14px;
            border-radius: 50%;
        }
        
        .close {
            background: var(--macos-red);
        }
        
        .minimize {
            background: var(--macos-yellow);
        }
        
        .maximize {
            background: var(--macos-green);
        }
        
        .status-card {
            background: var(--macos-gray);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 25px;
            box-shadow: inset 0 1px 2px rgba(0, 0, 0, 0.1);
        }
        
        .status-item {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
            font-size: 16px;
        }
        
        .status-label {
            color: var(--macos-dark-gray);
            font-weight: 500;
        }
        
        .status-value {
            color: #333;
            font-weight: 600;
            max-width: 60%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
            text-align: right;
        }
        
        .progress-container {
            background: var(--macos-light-gray);
            border-radius: 10px;
            height: 8px;
            margin: 15px 0;
            overflow: hidden;
        }
        
        .progress-bar {
            height: 100%;
            background: linear-gradient(90deg, var(--macos-blue), #5856D6);
            border-radius: 10px;
            width: 0%;
            transition: width 0.3s ease;
        }
        
        .time-info {
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            color: var(--macos-dark-gray);
            margin-top: 5px;
        }
        
        .controls-grid {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin-bottom: 25px;
        }
        
        .control-btn {
            background: rgba(255, 255, 255, 0.9);
            border: 1px solid rgba(0, 0, 0, 0.1);
            border-radius: 20px;
            padding: 18px 0;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 5px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
            position: relative;
            overflow: hidden;
        }
        
        .control-btn::before {
            content: '';
            position: absolute;
            top: 0;
            left: -100%;
            width: 100%;
            height: 100%;
            background: linear-gradient(90deg, transparent, rgba(255, 255, 255, 0.3), transparent);
            transition: left 0.5s;
        }
        
        .control-btn:hover::before {
            left: 100%;
        }
        
        .control-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.15);
        }
        
        .control-btn:active {
            transform: translateY(0);
        }
        
        .primary-btn {
            background: linear-gradient(135deg, var(--macos-blue), #5856D6);
            color: white;
            border: none;
            box-shadow: 0 5px 25px rgba(0, 122, 255, 0.4);
        }
        
        .primary-btn:hover {
            background: linear-gradient(135deg, #0051D5, #4338CA);
            box-shadow: 0 7px 30px rgba(0, 122, 255, 0.5);
        }
        
        .secondary-btn {
            background: var(--macos-gray);
            color: #333;
        }
        
        .danger-btn {
            background: linear-gradient(45deg, var(--macos-red), #FF453A);
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
            color: var(--macos-dark-gray);
            min-width: 40px;
            text-align: right;
        }
        
        .volume-slider {
            width: 100%;
            height: 6px;
            -webkit-appearance: none;
            background: var(--macos-light-gray);
            border-radius: 3px;
            outline: none;
        }
        
        .volume-slider::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 24px;
            height: 24px;
            border-radius: 50%;
            background: linear-gradient(135deg, var(--macos-blue), #5856D6);
            cursor: pointer;
            box-shadow: 0 4px 12px rgba(0, 122, 255, 0.4);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        
        .volume-slider::-webkit-slider-thumb:hover {
            transform: scale(1.1);
            box-shadow: 0 6px 16px rgba(0, 122, 255, 0.6);
        }
        
        .volume-slider::-moz-range-thumb {
            width: 24px;
            height: 24px;
            border-radius: 50%;
            background: linear-gradient(135deg, var(--macos-blue), #5856D6);
            cursor: pointer;
            border: none;
            box-shadow: 0 4px 12px rgba(0, 122, 255, 0.4);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        
        .volume-slider::-moz-range-thumb:hover {
            transform: scale(1.1);
            box-shadow: 0 6px 16px rgba(0, 122, 255, 0.6);
        }
        
        .search-box {
            display: flex;
            gap: 10px;
            margin-bottom: 20px;
        }
        
        .search-input {
            flex: 1;
            padding: 12px 15px;
            border: 1px solid rgba(0, 0, 0, 0.1);
            border-radius: 12px;
            font-size: 16px;
            outline: none;
            transition: border-color 0.2s ease;
            background: rgba(255, 255, 255, 0.8);
        }
        
        .search-input:focus {
            border-color: var(--macos-blue);
            box-shadow: 0 0 0 2px rgba(0, 122, 255, 0.2);
        }
        
        .search-btn {
            padding: 12px 20px;
            background: var(--macos-blue);
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
            border: 1px solid rgba(0, 0, 0, 0.1);
        }
        
        .file-item {
            padding: 15px 20px;
            border-bottom: 1px solid rgba(0, 0, 0, 0.05);
            cursor: pointer;
            transition: all 0.3s ease;
            display: flex;
            align-items: center;
            gap: 10px;
            position: relative;
            overflow: hidden;
        }
        
        .file-item::after {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            width: 4px;
            height: 100%;
            background: linear-gradient(135deg, var(--macos-blue), #5856D6);
            transform: translateX(-100%);
            transition: transform 0.3s ease;
        }
        
        .file-item:hover::after {
            transform: translateX(0);
        }
        
        .file-item:hover {
            background: var(--macos-gray);
            padding-left: 24px;
        }
        
        .file-item:last-child {
            border-bottom: none;
        }
        
        .file-item:hover {
            background: var(--macos-gray);
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
            color: var(--macos-blue);
            font-weight: 600;
        }
        
        /* 滚动条样式 */
        .file-list::-webkit-scrollbar {
            width: 8px;
        }
        
        .file-list::-webkit-scrollbar-track {
            background: rgba(0, 0, 0, 0.05);
            border-radius: 4px;
        }
        
        .file-list::-webkit-scrollbar-thumb {
            background: var(--macos-dark-gray);
            border-radius: 4px;
        }
        
        .file-list::-webkit-scrollbar-thumb:hover {
            background: #666;
        }
        
        /* 响应式设计 */
        @media (max-width: 600px) {
            .container {
                padding: 20px;
                margin: 10px;
            }
            
            .controls-grid {
                gap: 10px;
            }
            
            .control-btn {
                padding: 12px 0;
                font-size: 14px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="title-bar">
            <h1>🎵 音频控制面板</h1>
            <div class="traffic-lights">
                <div class="traffic-light close"></div>
                <div class="traffic-light minimize"></div>
                <div class="traffic-light maximize"></div>
            </div>
        </div>
        
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
            <button class="control-btn secondary-btn" onclick="prevTrack()">
                ⏮️ 上一首
            </button>
            <button class="control-btn primary-btn" onclick="pauseToggle()" id="play-pause-btn">
                ⏯️ 播放
            </button>
            <button class="control-btn secondary-btn" onclick="nextTrack()">
                ⏭️ 下一首
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
    </div>

    <script>
        // 全局变量
        let currentStatus = {};
        let updateInterval;
        
        // 页面加载完成后初始化
        document.addEventListener('DOMContentLoaded', function() {
            // 初始化状态更新
            updateStatus();
            getAllFiles();
            
            // 每1秒更新一次状态（实时更新播放进度）
            updateInterval = setInterval(updateStatus, 1000);
            
            // 搜索框回车事件
            document.getElementById('search-input').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    searchFiles();
                }
            });
        });
        
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
        function callAPI(endpoint) {
            return fetch(endpoint)
                .then(response => response.json())
                .then(data => {
                    console.log('API Response:', data);
                    // 立即更新状态
                    setTimeout(updateStatus, 100);
                    return data;
                })
                .catch(error => {
                    console.error('API Error:', error);
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
        

        
        function playTrack(index) {
            callAPI(`/mpv/play/${index}`);
        }
        
        function adjustVolume(value) {
            document.getElementById('volume-value').textContent = value + '%';
            // 立即更新UI以提供更好的用户体验
            document.getElementById('volume').textContent = value + '%';
            // 调用API设置音量
            fetch(`/mpv/volume/set?value=${value}`)
                .then(response => response.json())
                .then(data => {
                    console.log('Volume set to:', value);
                    // 即使API调用失败，UI也已经更新，用户体验更好
                })
                .catch(error => {
                    console.error('Error setting volume:', error);
                });
        }
    </script>
</body>
</html>
    '''
    return render_template_string(html_template)

if __name__ == '__main__':
    # 注意：0.0.0.0 允许从外部设备访问
    API_PORT = int(os.environ.get('API_PORT', 5000))
    app.run(host='0.0.0.0', port=API_PORT, debug=False)