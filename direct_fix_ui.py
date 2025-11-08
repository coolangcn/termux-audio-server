#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-

"""
直接修复网页控制面板问题的脚本
通过直接修改API脚本的关键部分来解决日志显示和按钮反馈问题
"""

import os
import re
import shutil

def fix_web_ui_issues():
    """修复网页控制面板问题"""
    print("🔧 直接修复网页控制面板问题...")
    
    # 获取用户主目录
    home_dir = os.path.expanduser("~")
    print(f"🏠 用户主目录: {home_dir}")
    
    # API脚本路径
    api_script = os.path.join(home_dir, "termux-audio-server", "enhanced_mpv_api.py")
    
    # 检查API脚本是否存在
    if not os.path.exists(api_script):
        print(f"❌ API脚本不存在: {api_script}")
        return False
    
    print("📝 备份原API脚本...")
    shutil.copy2(api_script, f"{api_script}.direct_fix_backup")
    
    # 读取API脚本内容
    with open(api_script, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 1. 确保日志目录存在
    log_dir = os.path.join(home_dir, "audio_logs")
    os.makedirs(log_dir, exist_ok=True)
    print(f"📁 确保日志目录存在: {log_dir}")
    
    # 2. 确保导入logging模块
    if "import logging" not in content:
        # 在文件开头添加导入语句
        content = re.sub(
            r'(import os\nimport signal\nimport json\nimport time\nimport threading\nimport subprocess\n)',
            r'\1import logging\nimport datetime\n',
            content,
            count=1
        )
    
    # 3. 添加日志配置（如果不存在）
    if "logger = logging.getLogger" not in content:
        # 找到Flask应用初始化的位置
        app_init_pos = content.find("app = Flask(__name__)")
        if app_init_pos != -1:
            # 在Flask应用初始化后添加日志配置
            log_config = f"""
# 配置操作日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("{log_dir}/operations.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# 添加操作日志装饰器
def log_operation(operation):
    def decorator(f):
        def wrapper(*args, **kwargs):
            logger.info(f"用户执行操作: {{operation}}")
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator
"""
            insert_pos = content.find("\n", app_init_pos) + 1
            content = content[:insert_pos] + log_config + content[insert_pos:]
    
    # 4. 为API端点添加日志装饰器（如果还没有）
    endpoints = [
        ("def pause_toggle()", "播放/暂停切换"),
        ("def next_track()", "下一首"),
        ("def prev_track()", "上一首"),
        ("def stop_playback()", "停止播放"),
        ("def shuffle_playlist()", "随机播放"),
        ("def play_track\\(index\\)", "播放指定歌曲"),
        ("def adjust_volume\\(\\)", "调整音量"),
        ("def set_volume\\(\\)", "设置音量"),
        ("def sync_files\\(\\)", "手动同步文件")
    ]
    
    for endpoint, operation in endpoints:
        pattern = f"(@log_operation\\([^)]*\\)\\s*)?{endpoint}"
        if not re.search(f"@log_operation\\([^)]*\\)\\s*{endpoint}", content):
            content = re.sub(
                f"({endpoint})",
                f"@log_operation('{operation}')\n    \\1",
                content,
                count=1
            )
    
    # 5. 添加日志API端点（如果不存在）
    if "@app.route('/logs'" not in content:
        log_endpoints = f"""
@app.route('/logs', methods=['GET'])
def get_logs():
    \"\"\"获取操作日志\"\"\"
    try:
        log_file = "{log_dir}/operations.log"
        if os.path.exists(log_file):
            with open(log_file, "r") as f:
                lines = f.readlines()
                # 返回最后100行日志
                return jsonify({{"logs": lines[-100:] if len(lines) > 100 else lines}}), 200
        else:
            return jsonify({{"logs": []}}), 200
    except Exception as e:
        return jsonify({{"error": str(e)}}), 500

@app.route('/logs/clear', methods=['POST'])
def clear_logs():
    \"\"\"清空操作日志\"\"\"
    try:
        log_file = "{log_dir}/operations.log"
        if os.path.exists(log_file):
            open(log_file, "w").close()
            logger.info("用户执行操作: 清空操作日志")
            return jsonify({{"message": "日志已清空"}}), 200
        else:
            return jsonify({{"message": "日志文件不存在"}}), 404
    except Exception as e:
        return jsonify({{"error": str(e)}}), 500
"""
        # 在if __name__ == '__main__'之前添加日志端点
        main_pos = content.rfind("if __name__ == '__main__':")
        if main_pos != -1:
            content = content[:main_pos] + log_endpoints + content[main_pos:]
    
    # 6. 替换web_control_panel函数为修复版本
    web_panel_start = content.find("def web_control_panel():")
    if web_panel_start != -1:
        # 找到函数结束位置
        return_pos = content.find("return render_template_string(html_template)", web_panel_start)
        if return_pos != -1:
            # 找到函数结束位置（包括return语句）
            func_end = content.find("\n", return_pos) + 1
            
            # 创建修复后的网页控制面板
            fixed_web_panel = '''@app.route('/', methods=['GET'])
def web_control_panel():
    """修复版网页控制面板 - 解决日志显示和按钮反馈问题"""
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
            grid-template-columns: repeat(3, 1fr);
            gap: 10px;
            margin-bottom: 20px;
        }
        .control-btn {
            padding: 15px;
            font-size: 14px;
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
            max-height: 300px;
            overflow-y: auto;
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
        .feedback {
            position: fixed;
            top: 20px;
            left: 50%;
            transform: translateX(-50%);
            background: #007bff;
            color: white;
            padding: 10px 20px;
            border-radius: 4px;
            z-index: 1000;
            display: none;
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
    
    <div class="feedback" id="feedback">操作成功!</div>

    <script>
        // 显示反馈消息
        function showFeedback(message, isSuccess = true) {
            const feedback = document.getElementById('feedback');
            feedback.textContent = message;
            feedback.style.backgroundColor = isSuccess ? '#28a745' : '#dc3545';
            feedback.style.display = 'block';
            
            setTimeout(() => {
                feedback.style.display = 'none';
            }, 2000);
        }
        
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
        function callAPI(endpoint, options = {}) {
            showFeedback('正在执行操作...', false);
            
            return fetch(endpoint, options)
                .then(response => response.json())
                .then(data => {
                    console.log('API Response:', data);
                    showFeedback('操作成功!');
                    setTimeout(updateStatus, 300);
                    setTimeout(loadLogs, 500);
                    return data;
                })
                .catch(error => {
                    console.error('API Error:', error);
                    showFeedback('操作失败: ' + error.message, false);
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
            document.getElementById('volume-value').textContent = value;
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
                        logContent.innerHTML = data.logs.reverse().join('<br>');
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
                callAPI('/logs/clear', { method: 'POST' })
                    .then(() => {
                        loadLogs();
                    });
            }
        }
        
        // 初始化
        document.addEventListener('DOMContentLoaded', function() {
            updateStatus();
            getAllFiles();
            loadLogs();
            
            // 每3秒更新一次状态
            setInterval(updateStatus, 3000);
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
    return render_template_string(html_template)'''
            
            # 替换整个web_control_panel函数
            content = content[:web_panel_start] + fixed_web_panel + content[func_end:]
    
    # 7. 写入修改后的内容
    with open(api_script, 'w', encoding='utf-8') as f:
        f.write(content)
    
    print("✅ 网页控制面板问题修复完成!")
    print("")
    print("📌 新增功能:")
    print("   • 即时按钮点击反馈")
    print("   • 操作日志实时显示")
    print("   • 简化的界面设计")
    print("")
    print(f"📁 日志文件位置: {log_dir}/operations.log")
    print("")
    print("🔧 请重新启动音频服务器以应用更改：")
    print("   ~/stop_audio_server")
    print("   ~/start_audio_server")
    
    return True

if __name__ == "__main__":
    try:
        fix_web_ui_issues()
    except Exception as e:
        print(f"❌ 修复过程中出现错误: {e}")
        import traceback
        traceback.print_exc()