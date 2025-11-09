import os
import sys
print("Starting enhanced_mpv_api.py...")
print(f"Python version: {sys.version}")

# 导入前的检查
print("Checking imports...")
try:
    import json
    import random
    import threading
    import time
    import logging
    from flask import Flask, request, jsonify, render_template_string
    from flask_cors import CORS
    import logging.config
    print("All imports successful!")
except Exception as e:
    print(f"Import error: {e}")
    sys.exit(1)

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
    
    audio_extensions = ('.mp3', '.flac', '.ogg', '.aac', '.m4a', '.wav', '.mp4', '.webm')
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
        includes = "--include '*.mp4' --include '*.mp3' --include '*.flac' --include '*.ogg' --include '*.aac' --include '*.m4a' --include '*.wav' --include '*.webm'"
        
        cmd = f"rclone copy '{rclone_remote}' '{LOCAL_DIR}' {includes} -P"
        result = os.system(cmd)
        
        if result == 0:
            return True, "Sync completed successfully"
        else:
            return False, "Sync failed"
    except Exception as e:
        return False, str(e)

def rclone_list_files():
    """列出NAS上的音频文件（不下载）"""
    try:
        rclone_remote = "synology:download/bilibili/push"
        
        # 使用rclone lsjson获取文件列表
        cmd = f"rclone lsjson '{rclone_remote}' --include '*.mp4' --include '*.mp3' --include '*.flac' --include '*.ogg' --include '*.aac' --include '*.m4a' --include '*.wav' --include '*.webm'"
        
        import subprocess
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        
        if result.returncode == 0:
            try:
                files_data = json.loads(result.stdout)
                # 只返回文件名列表
                file_list = [item['Path'] for item in files_data if not item.get('IsDir', False)]
                return file_list, "Success"
            except json.JSONDecodeError:
                return [], "Failed to parse rclone output"
        else:
            return [], f"rclone command failed: {result.stderr}"
    except Exception as e:
        return [], str(e)

def rclone_copy_file(remote_path, local_path):
    """从NAS复制单个文件到本地"""
    try:
        rclone_remote = "synology:download/bilibili/push"
        remote_file = f"{rclone_remote}/{remote_path}"
        
        # 确保本地目录存在
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        
        cmd = f"rclone copyto '{remote_file}' '{local_path}'"
        result = os.system(cmd)
        
        if result == 0:
            return True, "File copied successfully"
        else:
            return False, "Failed to copy file"
    except Exception as e:
        return False, str(e)

def get_file_from_cache_or_nas(filename):
    """从缓存获取文件，如果不存在则从NAS拉取"""
    local_file_path = os.path.join(LOCAL_DIR, filename)
    
    # 检查本地是否已存在
    if os.path.exists(local_file_path):
        return True, local_file_path, "File exists in cache"
    
    # 从NAS拉取文件
    success, message = rclone_copy_file(filename, local_file_path)
    if success:
        return True, local_file_path, "File copied from NAS"
    else:
        return False, None, f"Failed to get file from NAS: {message}"

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

@app.route('/mpv/play/file/<path:filename>', methods=['GET'])
@log_operation("播放指定文件")
def play_file(filename):
    """播放指定文件（按需从NAS拉取）"""
    # 从缓存或NAS获取文件
    success, local_path, message = get_file_from_cache_or_nas(filename)
    
    if not success:
        return jsonify({"status": "error", "message": f"Failed to get file: {message}"}), 500
    
    # 停止当前播放
    send_mpv_command(["quit"])
    time.sleep(0.5)  # 等待mpv退出
    
    # 使用mpv播放文件
    import subprocess
    try:
        # 启动mpv播放指定文件
        subprocess.Popen([
            "mpv", 
            "--no-video", 
            "--input-ipc-server=/data/data/com.termux/files/usr/tmp/mpv_ctrl/socket",
            "--cache=yes",
            "--cache-secs=60",
            local_path
        ])
        
        return jsonify({
            "status": "ok", 
            "action": "play_file", 
            "file": filename,
            "local_path": local_path,
            "source": "NAS" if "copied from NAS" in message else "cache"
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to play file: {str(e)}"}), 500

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
    """列出所有音频文件（从NAS获取列表）"""
    files, message = rclone_list_files()
    if files:
        return jsonify({"files": sorted(files)}), 200
    else:
        # 如果NAS获取失败，回退到本地文件
        local_files = get_audio_files()
        return jsonify({"files": local_files, "warning": f"Failed to get files from NAS: {message}"}), 200

@app.route('/files/search', methods=['GET'])
def search_files():
    """搜索音频文件（从NAS获取列表）"""
    query = request.args.get('q', '').lower()
    
    # 从NAS获取文件列表
    nas_files, message = rclone_list_files()
    
    if not nas_files:
        # 如果NAS获取失败，回退到本地文件
        nas_files = get_audio_files()
    
    if not query:
        return jsonify({"files": sorted(nas_files)}), 200
    
    # 筛选匹配的文件
    matched_files = [f for f in nas_files if query in f.lower()]
    return jsonify({"files": sorted(matched_files)}), 200

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
        
        # 确保日志目录存在
        os.makedirs(LOG_DIR, exist_ok=True)
        
        if os.path.exists(log_file):
            # 使用更安全的方式清空文件
            with open(log_file, "w", encoding='utf-8') as f:
                f.write("")
            
            # 重新配置日志处理器以确保日志继续工作
            for handler in operation_logger.handlers[:]:
                operation_logger.removeHandler(handler)
            
            # 重新添加文件处理器
            file_handler = logging.FileHandler(f"{LOG_DIR}/operations.log")
            file_handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
            file_handler.setFormatter(formatter)
            operation_logger.addHandler(file_handler)
            operation_logger.propagate = False
            
            # 记录清空操作
            operation_logger.info("操作日志已清空")
            
            return jsonify({"message": "日志已清空"}), 200
        else:
            # 如果文件不存在，创建空文件
            with open(log_file, "w", encoding='utf-8') as f:
                f.write("")
            
            # 重新配置日志处理器
            for handler in operation_logger.handlers[:]:
                operation_logger.removeHandler(handler)
            
            file_handler = logging.FileHandler(f"{LOG_DIR}/operations.log")
            file_handler.setLevel(logging.INFO)
            formatter = logging.Formatter('%(asctime)s [%(levelname)s] %(message)s')
            file_handler.setFormatter(formatter)
            operation_logger.addHandler(file_handler)
            operation_logger.propagate = False
            
            operation_logger.info("操作日志已清空（新建文件）")
            
            return jsonify({"message": "日志文件已创建并清空"}), 200
    except Exception as e:
        # 记录错误到控制台
        print(f"清空日志时发生错误: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/cache/info', methods=['GET'])
def get_cache_info():
    """获取缓存信息"""
    try:
        if not os.path.exists(LOCAL_DIR):
            return jsonify({"files": [], "total_size": 0, "file_count": 0}), 200
        
        files_info = []
        total_size = 0
        file_count = 0
        
        for filename in os.listdir(LOCAL_DIR):
            file_path = os.path.join(LOCAL_DIR, filename)
            if os.path.isfile(file_path):
                size = os.path.getsize(file_path)
                mtime = os.path.getmtime(file_path)
                files_info.append({
                    "name": filename,
                    "size": size,
                    "size_mb": round(size / (1024 * 1024), 2),
                    "modified": time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(mtime))
                })
                total_size += size
                file_count += 1
        
        return jsonify({
            "status": "ok",
            "files": sorted(files_info, key=lambda x: x["name"]),
            "total_size": f"{round(total_size / (1024 * 1024), 2)} MB",
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "file_count": file_count,
            "cache_dir": LOCAL_DIR
        }), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/cache/clear', methods=['POST'])
@log_operation("清理缓存")
def clear_cache():
    """清理缓存文件"""
    try:
        if not os.path.exists(LOCAL_DIR):
            return jsonify({"message": "缓存目录不存在"}), 200
        
        removed_count = 0
        removed_size = 0
        
        for filename in os.listdir(LOCAL_DIR):
            file_path = os.path.join(LOCAL_DIR, filename)
            if os.path.isfile(file_path):
                size = os.path.getsize(file_path)
                os.remove(file_path)
                removed_count += 1
                removed_size += size
        
        return jsonify({
            "status": "ok",
            "message": f"缓存已清理，删除了 {removed_count} 个文件，释放了 {round(removed_size / (1024 * 1024), 2)} MB 空间",
            "removed_count": removed_count,
            "removed_size_mb": round(removed_size / (1024 * 1024), 2)
        }), 200
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
        /* 音乐App风格样式 - 清爽简洁 */
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
            background-color: #f7f7f7;
            color: #333;
            max-width: 600px;
            margin: 0 auto;
            padding: 15px;
            min-height: 100vh;
        }
        
        .container {
            background: white;
            border-radius: 20px;
            padding: 20px;
            box-shadow: 0 4px 12px rgba(0,0,0,0.05);
        }
        
        h1 {
            text-align: center;
            color: #1a1a1a;
            font-size: 24px;
            margin-bottom: 25px;
            font-weight: 600;
        }
        
        /* 音乐信息卡片 */
        .status {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 20px;
            border-radius: 15px;
            margin-bottom: 25px;
            text-align: center;
        }
        
        .status div {
            margin: 8px 0;
            font-weight: 500;
        }
        
        #current-file {
            font-size: 18px;
            font-weight: 600;
            margin-top: 5px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        
        #play-status {
            font-size: 16px;
            opacity: 0.9;
        }
        
        #volume {
            font-weight: 600;
        }
        
        /* 控制按钮区域 - 音乐App风格大按钮 */
        .controls {
            display: flex;
            justify-content: center;
            align-items: center;
            gap: 15px;
            margin-bottom: 30px;
        }
        
        .control-btn {
            border: none;
            border-radius: 50%;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s ease;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }
        
        .control-btn.primary {
            background-color: #667eea;
            color: white;
            width: 60px;
            height: 60px;
            font-size: 20px;
        }
        
        .control-btn.secondary {
            background-color: #f0f0f0;
            color: #333;
            width: 50px;
            height: 50px;
            font-size: 18px;
        }
        
        .control-btn:hover {
            transform: scale(1.05);
            box-shadow: 0 4px 12px rgba(0,0,0,0.15);
        }
        
        .control-btn:active {
            transform: scale(0.95);
        }
        
        /* 音量控制 */
        .volume-control {
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 25px;
            padding: 15px;
            background-color: #f9f9f9;
            border-radius: 12px;
        }
        
        .volume-control span {
            font-weight: 500;
            color: #555;
        }
        
        .volume-control input {
            flex: 1;
            height: 6px;
            border-radius: 3px;
            background: #ddd;
            outline: none;
            -webkit-appearance: none;
        }
        
        .volume-control input::-webkit-slider-thumb {
            -webkit-appearance: none;
            width: 22px;
            height: 22px;
            border-radius: 50%;
            background: #667eea;
            cursor: pointer;
            box-shadow: 0 2px 6px rgba(102, 126, 234, 0.3);
            transition: all 0.2s;
        }
        
        .volume-control input::-webkit-slider-thumb:hover {
            transform: scale(1.2);
            background: #5a67d8;
        }
        
        /* 搜索框 */
        .search-box {
            margin-bottom: 25px;
            position: relative;
        }
        
        .search-box input {
            width: 100%;
            padding: 15px 15px 15px 45px;
            border: 1px solid #e0e0e0;
            border-radius: 12px;
            font-size: 16px;
            transition: border-color 0.3s;
        }
        
        .search-box input:focus {
            outline: none;
            border-color: #667eea;
        }
        
        .search-box button {
            position: absolute;
            right: 5px;
            top: 50%;
            transform: translateY(-50%);
            background-color: #667eea;
            color: white;
            border: none;
            border-radius: 8px;
            padding: 8px 12px;
            cursor: pointer;
            font-size: 14px;
        }
        
        /* 文件列表 */
        .file-list {
            margin-top: 30px;
        }
        
        .file-list h3 {
            font-size: 18px;
            margin-bottom: 15px;
            color: #1a1a1a;
        }
        
        #file-list {
            max-height: 400px;
            overflow-y: auto;
            border: 1px solid #e0e0e0;
            border-radius: 8px;
            background: white;
        }
        
        .file-item {
            padding: 15px;
            border-bottom: 1px solid #f0f0f0;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
        }
        
        .file-item:last-child {
            border-bottom: none;
        }
        
        .file-item:hover {
            background-color: #f9f9f9;
            padding-left: 20px;
        }
        
        /* 日志区域 - 简化显示 */
        .log-section {
            margin-top: 30px;
            padding: 15px;
            background-color: #f9f9f9;
            border-radius: 12px;
        }
        
        .log-section h3 {
            font-size: 16px;
            margin-bottom: 10px;
            color: #555;
        }
        
        .log-buttons {
            display: flex;
            gap: 10px;
            margin-bottom: 10px;
        }
        
        .log-btn {
            padding: 8px 16px;
            border: none;
            border-radius: 8px;
            cursor: pointer;
            font-size: 14px;
            transition: background-color 0.2s;
        }
        
        .log-btn.primary {
            background-color: #667eea;
            color: white;
        }
        
        .log-btn.danger {
            background-color: #ff6b6b;
            color: white;
        }
        
        .log-container {
            background: white;
            border-radius: 8px;
            padding: 10px;
            height: 150px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 12px;
            border: 1px solid #e0e0e0;
        }
        
        /* 缓存管理区域 */
        .cache-section {
            margin-top: 30px;
            padding: 15px;
            background-color: #f0f8ff;
            border-radius: 12px;
            border: 1px solid #e1f0ff;
        }
        
        .cache-section h3 {
            font-size: 16px;
            margin-bottom: 10px;
            color: #4a90e2;
        }
        
        .cache-buttons {
            display: flex;
            gap: 10px;
            margin-bottom: 10px;
        }
        
        .cache-info {
            background: white;
            border-radius: 8px;
            padding: 10px;
            height: 100px;
            overflow-y: auto;
            font-family: monospace;
            font-size: 12px;
            border: 1px solid #e1f0ff;
        }
        
        /* 响应式设计 */
        @media (max-width: 480px) {
            body {
                padding: 10px;
            }
            
            .container {
                padding: 15px;
            }
            
            .control-btn.primary {
                width: 50px;
                height: 50px;
                font-size: 18px;
            }
            
            .control-btn.secondary {
                width: 40px;
                height: 40px;
                font-size: 16px;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎵 音频控制面板</h1>
        
        <div class="status" id="status">
            <div>🎵 当前播放</div>
            <div id="current-file">无</div>
            <div>播放状态: <span id="play-status">未播放</span></div>
            <div>音量: <span id="volume">0</span>%</div>
        </div>
        
        <div class="controls">
            <button class="control-btn secondary" onclick="prevTrack()">⏮️</button>
            <button class="control-btn primary" onclick="pauseToggle()">⏯️</button>
            <button class="control-btn secondary" onclick="nextTrack()">⏭️</button>
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
        
        <div class="cache-section">
            <h3>💾 缓存管理</h3>
            <div class="cache-buttons">
                <button class="log-btn primary" onclick="getCacheInfo()">刷新缓存信息</button>
                <button class="log-btn danger" onclick="clearCache()">清空缓存</button>
            </div>
            <div class="cache-info" id="cache-info">
                <div id="cache-content">加载中...</div>
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
                .then(function(response) { return response.json(); })
                .then(function(data) {
                    // 修复播放状态显示逻辑：当没有当前文件时显示"未播放"
                    var hasCurrentFile = data.current_file && data.current_file.trim() !== '';
                    document.getElementById('current-file').textContent = hasCurrentFile ? data.current_file : '无';
                    
                    // 根据是否有当前文件和暂停状态来正确显示播放状态
                    if (!hasCurrentFile) {
                        document.getElementById('play-status').textContent = '未播放';
                    } else {
                        document.getElementById('play-status').textContent = data.paused ? '已暂停' : '正在播放';
                    }
                    
                    // 修复音量显示问题：如果用户最近3秒内设置了音量，则不覆盖用户设置
                    var currentTime = Date.now();
                    if (currentTime - lastVolumeSetTime > VOLUME_UPDATE_DELAY) {
                        var volumeValue = Math.round(data.volume) || 0;
                        document.getElementById('volume').textContent = volumeValue;
                        document.getElementById('volume-slider').value = volumeValue;
                        document.getElementById('volume-value').textContent = volumeValue;
                    }
                })
                .catch(function(error) {
                    console.error('Error updating status:', error);
                });
        }
        
        // 更新文件列表
        function updateFileList(files) {
            const fileList = document.getElementById('file-list');
            fileList.innerHTML = '';
            
            // 存储当前文件列表到全局变量
            window.currentFileList = files;
            
            files.forEach((file, index) => {
                const fileItem = document.createElement('div');
                fileItem.className = 'file-item';
                fileItem.textContent = file;
                fileItem.onclick = () => playFileByName(file);
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
        
        function playFileByName(filename) {
            // 显示加载状态
            const fileList = document.getElementById('file-list');
            const loadingMsg = document.createElement('div');
            loadingMsg.id = 'loading-msg';
            loadingMsg.style.cssText = 'color: #666; font-style: italic; padding: 10px; text-align: center;';
            loadingMsg.textContent = `正在加载: ${filename}...`;
            fileList.appendChild(loadingMsg);
            
            // 调用新的播放API
            fetch(`/mpv/play/file/${encodeURIComponent(filename)}`)
                .then(response => response.json())
                .then(data => {
                    // 移除加载消息
                    const loadingElement = document.getElementById('loading-msg');
                    if (loadingElement) {
                        loadingElement.remove();
                    }
                    
                    if (data.status === 'ok') {
                        console.log('播放成功:', data);
                        // 更新状态和日志
                        setTimeout(updateStatus, 500);
                        loadLogs();
                        
                        // 显示成功消息
                        const source = data.source === 'cache' ? '缓存' : 'NAS';
                        showNotification(`开始播放: ${filename} (来自${source})`);
                    } else {
                        alert('播放失败: ' + data.message);
                    }
                })
                .catch(error => {
                    // 移除加载消息
                    const loadingElement = document.getElementById('loading-msg');
                    if (loadingElement) {
                        loadingElement.remove();
                    }
                    
                    console.error('播放失败:', error);
                    alert('播放失败: ' + error.message);
                });
        }
        
        function showNotification(message) {
            // 创建通知元素
            const notification = document.createElement('div');
            notification.style.cssText = `
                position: fixed;
                top: 20px;
                right: 20px;
                background: #28a745;
                color: white;
                padding: 10px 15px;
                border-radius: 5px;
                box-shadow: 0 2px 5px rgba(0,0,0,0.2);
                z-index: 1000;
                font-size: 14px;
                max-width: 300px;
            `;
            notification.textContent = message;
            
            document.body.appendChild(notification);
            
            // 3秒后自动移除
            setTimeout(() => {
                if (notification.parentNode) {
                    notification.parentNode.removeChild(notification);
                }
            }, 3000);
        }
        
        // 添加音量设置时间跟踪
        var lastVolumeSetTime = 0;
        const VOLUME_UPDATE_DELAY = 3000; // 音量设置后3秒内不自动更新
        
        function adjustVolume(value) {
            // 立即更新所有音量显示元素，确保即时反馈
            document.getElementById('volume').textContent = value;
            document.getElementById('volume-value').textContent = value;
            document.getElementById('volume-slider').value = value;
            
            // 记录最后设置音量的时间
            lastVolumeSetTime = Date.now();
            
            // 发送API请求设置音量
            fetch('/mpv/volume/set?value=' + value)
                .then(function(response) { return response.json(); })
                .then(function(data) {
                    console.log('音量设置成功:', data);
                    // 音量设置成功后，再发送一次确认请求确保设置生效
                    setTimeout(function() {
                        fetch('/mpv/volume/set?value=' + value);
                    }, 500);
                })
                .catch(function(error) {
                    console.error('音量设置失败:', error);
                    // 出错时仍然保持UI更新，因为用户可能已经调整了滑块
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
        
        // 缓存管理函数
        function getCacheInfo() {
            const cacheContent = document.getElementById('cache-content');
            cacheContent.innerHTML = '<span style="color: #666;">正在获取缓存信息...</span>';
            
            fetch('/cache/info')
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'ok') {
                        let infoHtml = `<strong>缓存信息:</strong><br>`;
                        infoHtml += `总大小: ${data.total_size}<br>`;
                        infoHtml += `文件数量: ${data.file_count}<br>`;
                        infoHtml += `缓存目录: ${data.cache_dir}<br>`;
                        
                        if (data.files && data.files.length > 0) {
                            infoHtml += `<br><strong>缓存文件列表:</strong><br>`;
                            data.files.forEach(file => {
                                infoHtml += `• ${file.name} (${file.size}, ${file.modified})<br>`;
                            });
                        } else {
                            infoHtml += `<br><em>暂无缓存文件</em>`;
                        }
                        
                        cacheContent.innerHTML = infoHtml;
                    } else {
                        cacheContent.innerHTML = `<span style="color: #ff6b6b;">获取缓存信息失败: ${data.message}</span>`;
                    }
                })
                .catch(error => {
                    console.error('Error getting cache info:', error);
                    cacheContent.innerHTML = '<span style="color: #ff6b6b;">获取缓存信息失败</span>';
                });
        }
        
        function clearCache() {
            if (confirm('确定要清空所有缓存文件吗？')) {
                const cacheContent = document.getElementById('cache-content');
                cacheContent.innerHTML = '<span style="color: #666;">正在清空缓存...</span>';
                
                fetch('/cache/clear', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    }
                })
                .then(response => response.json())
                .then(data => {
                    if (data.status === 'ok') {
                        cacheContent.innerHTML = `<span style="color: #28a745;">缓存已清空: 删除了 ${data.removed_count} 个文件，释放了 ${data.removed_size_mb} MB</span>`;
                        
                        // 2秒后重新获取缓存信息
                        setTimeout(function() {
                            getCacheInfo();
                        }, 2000);
                    } else {
                        cacheContent.innerHTML = `<span style="color: #ff6b6b;">清空缓存失败: ${data.message}</span>`;
                    }
                })
                .catch(error => {
                    console.error('Error clearing cache:', error);
                    cacheContent.innerHTML = '<span style="color: #ff6b6b;">清空缓存失败</span>';
                });
            }
        }
        
        function clearLogs() {
            if (confirm('确定要清空所有操作日志吗？')) {
                // 显示清空中状态
                const logContent = document.getElementById('log-content');
                logContent.innerHTML = '<span style="color: #666;">正在清空日志...</span>';
                
                // 使用更可靠的fetch调用方式，添加错误处理和超时
                var timeoutId = setTimeout(function() {
                    logContent.innerHTML = '<span style="color: #ff6b6b;">清空日志请求超时，请稍后重试</span>';
                    setTimeout(function() {
                        loadLogs(); // 重新加载日志
                    }, 2000);
                }, 8000);
                
                fetch('/logs/clear', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    timeout: 7000 // 设置7秒超时
                })
                .then(function(response) {
                    clearTimeout(timeoutId);
                    if (!response.ok) {
                        throw new Error('响应状态: ' + response.status);
                    }
                    return response.json();
                })
                .then(function(data) {
                    console.log('日志清空成功:', data);
                    // 清空后立即更新UI
                    logContent.innerHTML = '<span style="color: #28a745;">日志已清空</span>';
                    
                    // 显示成功消息，2秒后重新加载日志
                    setTimeout(function() {
                        loadLogs();
                    }, 2000);
                })
                .catch(function(error) {
                    clearTimeout(timeoutId);
                    console.error('清空日志失败:', error);
                    logContent.innerHTML = '<span style="color: #ff6b6b;">清空日志失败: ' + error.message + '</span>';
                    
                    // 3秒后重新加载日志
                    setTimeout(function() {
                        loadLogs();
                    }, 3000);
                });
            }
        }
        
        // 自动播放下一首功能
        let autoPlayInterval;
        let lastFileCount = 0;
        
        function checkAndAutoPlayNext() {
            // 获取当前播放状态
            fetch('/mpv/status')
                .then(response => response.json())
                .then(data => {
                    // 检查是否播放结束（当前文件为空且之前有文件在播放）
                    if (!data.current_file && data.position === 0 && data.duration === 0) {
                        // 获取文件列表
                        fetch('/files')
                            .then(response => response.json())
                            .then(fileData => {
                                if (fileData.files && fileData.files.length > 0) {
                                    // 随机选择下一首歌曲
                                    const randomIndex = Math.floor(Math.random() * fileData.files.length);
                                    const nextFile = fileData.files[randomIndex];
                                    console.log('自动播放下一首:', nextFile);
                                    playFileByName(nextFile);
                                }
                            })
                            .catch(error => {
                                console.error('获取文件列表失败:', error);
                            });
                    }
                })
                .catch(error => {
                    console.error('获取播放状态失败:', error);
                });
        }
        
        // 定时更新文件列表功能
        function checkAndUpdateFileList() {
            fetch('/files')
                .then(response => response.json())
                .then(data => {
                    if (data.files && data.files.length !== lastFileCount) {
                        console.log('检测到文件列表变化，从', lastFileCount, '更新到', data.files.length);
                        lastFileCount = data.files.length;
                        updateFileList(data.files);
                        
                        // 显示更新通知
                        showNotification(`文件列表已更新，共 ${data.files.length} 首歌曲`);
                    }
                })
                .catch(error => {
                    console.error('更新文件列表失败:', error);
                });
        }
        
        // 初始化
        document.addEventListener('DOMContentLoaded', function() {
            // 立即初始化状态显示
            document.getElementById('current-file').textContent = '无';
            document.getElementById('play-status').textContent = '未播放';
            document.getElementById('volume').textContent = '0';
            document.getElementById('volume-slider').value = '50';
            document.getElementById('volume-value').textContent = '50';
            
            // 加载数据
            updateStatus();
            getAllFiles();
            loadLogs();
            getCacheInfo(); // 获取缓存信息
            
            // 每5秒更新一次状态
            setInterval(updateStatus, 5000);
            // 每10秒更新一次日志
            setInterval(loadLogs, 10000);
            // 每30秒更新一次缓存信息
            setInterval(getCacheInfo, 30000);
            
            // 每3秒检查一次是否需要自动播放下一首
            setInterval(checkAndAutoPlayNext, 3000);
            // 每15秒检查一次文件列表是否有更新
            setInterval(checkAndUpdateFileList, 15000);
            
            // 搜索框回车事件
            document.getElementById('search-input').addEventListener('keypress', function(e) {
                if (e.keyCode === 13) { // 使用keyCode兼容性更好
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