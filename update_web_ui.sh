#!/data/data/com.termux/files/usr/bin/bash

# 更新网页控制面板UI的脚本

echo "🎨 更新网页控制面板UI..."

# 获取用户主目录
HOME_DIR=$(eval echo ~)
echo "🏠 用户主目录: $HOME_DIR"

# 备份原文件
API_SCRIPT="$HOME_DIR/termux-audio-server/enhanced_mpv_api.py"
if [ -f "$API_SCRIPT" ]; then
    echo "📝 备份原API脚本..."
    cp "$API_SCRIPT" "${API_SCRIPT}.backup.$(date +%Y%m%d_%H%M%S)"
fi

# 创建改进版的网页控制面板
echo "📝 创建改进版网页控制面板..."

# 替换enhanced_mpv_api.py中的web_control_panel函数
# 首先备份原文件
cp "$API_SCRIPT" "${API_SCRIPT}.ui_backup"

# 删除原有的web_control_panel函数部分
sed -i '/@app.route\('"'"'\/'"'"', methods=\[('"'"'GET'"'"'\)\]\)/,/return render_template_string(html_template)/d' "$API_SCRIPT"

# 在文件末尾添加新的web_control_panel函数
cat >> "$API_SCRIPT" << 'EOF'

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
            background: rgba(255, 255, 255, 0.8);
            border: 1px solid rgba(0, 0, 0, 0.1);
            border-radius: 14px;
            padding: 15px 0;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 5px;
            box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
        }
        
        .control-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.15);
        }
        
        .control-btn:active {
            transform: translateY(0);
        }
        
        .primary-btn {
            background: linear-gradient(45deg, var(--macos-blue), #5856D6);
            color: white;
            border: none;
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
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: var(--macos-blue);
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
            transition: background 0.2s ease;
            display: flex;
            align-items: center;
            gap: 10px;
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
            <button class="control-btn secondary-btn" onclick="shufflePlaylist()">
                🔀 随机播放
            </button>
            <button class="control-btn secondary-btn" onclick="syncFiles()">
                🔄 同步
            </button>
            <button class="control-btn danger-btn" onclick="stopPlayback()">
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
    </script>
</body>
</html>
    '''
    return render_template_string(html_template)
EOF

echo "✅ 网页控制面板UI更新完成!"
echo ""
echo "📌 请重新启动音频服务器以应用更改："
echo "   ~/stop_audio_server"
echo "   ~/start_audio_server"
echo ""
echo "✨ 新功能特性："
echo "   • macOS风格的现代化界面设计"
echo "   • 实时播放进度条显示"
echo "   • 每秒自动更新播放状态"
echo "   • 正在播放的歌曲高亮显示"
echo "   • 响应式设计，适配移动设备"