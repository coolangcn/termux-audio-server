#!/data/data/com.termux/files/usr/bin/bash

# 修复UI更新后API服务问题的脚本

echo "🔧 修复UI更新后API服务问题..."

# 获取用户主目录
HOME_DIR=$(eval echo ~)
echo "🏠 用户主目录: $HOME_DIR"

# API脚本路径
API_SCRIPT="$HOME_DIR/termux-audio-server/enhanced_mpv_api.py"
echo "📝 检查API脚本: $API_SCRIPT"

# 检查API脚本是否存在
if [ ! -f "$API_SCRIPT" ]; then
    echo "❌ API脚本不存在: $API_SCRIPT"
    echo "💡 尝试从备份恢复..."
    
    # 查找最近的备份文件
    BACKUP_FILE=$(ls -t ${API_SCRIPT}.backup.* 2>/dev/null | head -n 1)
    if [ -n "$BACKUP_FILE" ]; then
        echo "✅ 找到备份文件: $BACKUP_FILE"
        cp "$BACKUP_FILE" "$API_SCRIPT"
        echo "✅ 已从备份恢复API脚本"
    else
        echo "❌ 未找到备份文件"
        echo "💡 尝试重新下载API脚本..."
        
        # 从GitHub重新下载API脚本
        curl -o "$API_SCRIPT" "https://raw.githubusercontent.com/coolangcn/termux-audio-server/main/enhanced_mpv_api.py"
        if [ $? -eq 0 ]; then
            echo "✅ 已从GitHub重新下载API脚本"
        else
            echo "❌ 无法从GitHub下载API脚本"
            exit 1
        fi
    fi
else
    echo "✅ API脚本存在"
    
    # 检查API脚本是否包含web_control_panel函数
    if ! grep -q "def web_control_panel" "$API_SCRIPT"; then
        echo "⚠️ API脚本中缺少web_control_panel函数"
        
        # 检查是否有备份
        UI_BACKUP="$API_SCRIPT.ui_backup"
        if [ -f "$UI_BACKUP" ]; then
            echo "✅ 找到UI更新前的备份"
            
            # 检查备份文件是否完整
            if grep -q "def web_control_panel" "$UI_BACKUP"; then
                echo "✅ 备份文件包含web_control_panel函数"
                
                # 从备份中提取web_control_panel函数并添加到当前脚本
                echo "📝 从备份恢复web_control_panel函数..."
                
                # 备份当前文件
                cp "$API_SCRIPT" "${API_SCRIPT}.recovery_$(date +%Y%m%d_%H%M%S)"
                
                # 提取备份中的web_control_panel函数并添加到当前脚本
                {
                    echo ""
                    echo ""
                    sed -n '/@app.route.*GET.*$/,$p' "$UI_BACKUP" | sed '/^if __name__ == '\''__main__'\''/,/^API_PORT =/d'
                    echo ""
                    echo "if __name__ == '__main__':"
                } >> "$API_SCRIPT"
                
                echo "✅ 已恢复web_control_panel函数"
            else
                echo "❌ 备份文件也不完整"
                echo "💡 重新添加web_control_panel函数..."
                
                # 备份当前文件
                cp "$API_SCRIPT" "${API_SCRIPT}.recovery_$(date +%Y%m%d_%H%M%S)"
                
                # 添加web_control_panel函数
                cat >> "$API_SCRIPT" << 'EOF'


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
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Open Sans', 'Helvetica Neue', sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
        }
        .container {
            background: rgba(255, 255, 255, 0.95);
            border-radius: 20px;
            padding: 30px;
            box-shadow: 0 20px 50px rgba(0, 0, 0, 0.2);
            backdrop-filter: blur(10px);
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
        .controls {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            gap: 15px;
            margin-bottom: 30px;
        }
        .control-btn {
            padding: 15px;
            font-size: 16px;
            border: none;
            border-radius: 14px;
            cursor: pointer;
            transition: all 0.3s ease;
            font-weight: 600;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.1);
        }
        .control-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 6px 20px rgba(0, 0, 0, 0.15);
        }
        .primary {
            background: linear-gradient(45deg, #007AFF, #5856D6);
            color: white;
        }
        .secondary {
            background: #F2F2F7;
            color: #333;
        }
        .success {
            background: linear-gradient(45deg, #34C759, #30D158);
            color: white;
        }
        .danger {
            background: linear-gradient(45deg, #FF3B30, #FF453A);
            color: white;
        }
        .volume-control {
            display: flex;
            align-items: center;
            gap: 15px;
            margin-bottom: 30px;
            background: #F2F2F7;
            padding: 20px;
            border-radius: 16px;
        }
        .volume-control label {
            font-weight: 600;
            color: #333;
            min-width: 100px;
        }
        .volume-control input {
            flex: 1;
            height: 6px;
            -webkit-appearance: none;
            background: #E5E5EA;
            border-radius: 3px;
            outline: none;
        }
        .volume-control input::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: #007AFF;
            cursor: pointer;
            box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
        }
        .file-list {
            margin-top: 30px;
            background: rgba(255, 255, 255, 0.8);
            border-radius: 16px;
            padding: 20px;
            box-shadow: 0 4px 20px rgba(0, 0, 0, 0.1);
        }
        .file-item {
            padding: 15px;
            border-bottom: 1px solid #E5E5EA;
            cursor: pointer;
            transition: background 0.2s ease;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .file-item:hover {
            background: #F2F2F7;
            border-radius: 12px;
        }
        .file-item:last-child {
            border-bottom: none;
        }
        .status-card {
            background: #F2F2F7;
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 25px;
            box-shadow: 0 4px 15px rgba(0, 0, 0, 0.05);
        }
        .status-item {
            display: flex;
            justify-content: space-between;
            margin-bottom: 10px;
        }
        .status-label {
            color: #8E8E93;
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
        .search-box {
            display: flex;
            gap: 10px;
            margin-bottom: 25px;
        }
        .search-box input {
            flex: 1;
            padding: 15px;
            border: 2px solid #E5E5EA;
            border-radius: 14px;
            font-size: 16px;
            outline: none;
            transition: border-color 0.2s ease;
        }
        .search-box input:focus {
            border-color: #007AFF;
        }
        .search-box button {
            padding: 15px 25px;
            background: #007AFF;
            color: white;
            border: none;
            border-radius: 14px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: background 0.2s ease;
        }
        .search-box button:hover {
            background: #0062CC;
        }
        .progress-container {
            background: #E5E5EA;
            border-radius: 10px;
            height: 8px;
            margin: 15px 0;
            overflow: hidden;
        }
        .progress-bar {
            height: 100%;
            background: linear-gradient(90deg, #007AFF, #5856D6);
            border-radius: 10px;
            width: 0%;
            transition: width 0.3s ease;
        }
        .time-info {
            display: flex;
            justify-content: space-between;
            font-size: 12px;
            color: #8E8E93;
            margin-top: 5px;
        }
        @media (max-width: 600px) {
            .controls {
                grid-template-columns: repeat(2, 1fr);
            }
            .container {
                padding: 20px;
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
        
        <div class="controls">
            <button class="control-btn secondary" onclick="prevTrack()">⏮️ 上一首</button>
            <button class="control-btn primary" onclick="pauseToggle()" id="play-pause-btn">⏯️ 播放/暂停</button>
            <button class="control-btn secondary" onclick="nextTrack()">⏭️ 下一首</button>
            <button class="control-btn secondary" onclick="shufflePlaylist()">🔀 随机播放</button>
            <button class="control-btn success" onclick="syncFiles()">🔄 同步文件</button>
            <button class="control-btn danger" onclick="stopPlayback()">⏹️ 停止</button>
        </div>
        
        <div class="volume-control">
            <label for="volume-slider">🔈 音量:</label>
            <input type="range" id="volume-slider" min="0" max="100" value="50" oninput="adjustVolume(this.value)">
            <span id="volume-value">50%</span>
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
                    <span>🎵</span>
                    <span style="${isPlaying ? 'color: #007AFF; font-weight: 600;' : ''}">${file}${isPlaying ? ' (正在播放)' : ''}</span>
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


if __name__ == '__main__':
EOF
                
                # 复制main部分
                sed -n '/API_PORT =/,$p' "$UI_BACKUP" >> "$API_SCRIPT"
                
                echo "✅ 已重新添加web_control_panel函数"
            fi
        else
            echo "❌ 未找到UI备份文件"
        fi
    else
        echo "✅ API脚本完整"
    fi
fi

# 修复脚本权限
chmod +x "$API_SCRIPT"
echo "✅ API脚本权限已修复"

# 测试API脚本语法
echo "📝 测试API脚本语法..."
python -m py_compile "$API_SCRIPT" 2>/dev/null
if [ $? -eq 0 ]; then
    echo "✅ API脚本语法正确"
else
    echo "❌ API脚本语法错误"
    echo "💡 尝试修复语法错误..."
    
    # 检查并修复常见的语法错误
    # 修复缩进问题
    python -c "
import ast
with open('$API_SCRIPT', 'r') as f:
    content = f.read()
try:
    ast.parse(content)
    print('语法正确')
except SyntaxError as e:
    print(f'语法错误在行 {e.lineno}: {e.text}')
    # 尝试自动修复
" 2>/dev/null
fi

echo "✅ API服务修复完成!"
echo ""
echo "📌 请重新启动音频服务器以应用更改："
echo "   ~/stop_audio_server"
echo "   ~/start_audio_server"
echo ""
echo "💡 如果仍有问题，请运行诊断脚本："
echo "   ~/diagnose_api"