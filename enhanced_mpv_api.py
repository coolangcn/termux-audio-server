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
    import subprocess
    from datetime import datetime
    from collections import deque
    from flask import Flask, request, jsonify, render_template
    from flask_cors import CORS
    import logging.config
    print("All imports successful!")
except Exception as e:
    print(f"Import error: {e}")
    sys.exit(1)

# 配置控制台实时日志记录 - 设置为DEBUG级别以输出详细调试信息
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s',
    handlers=[
        logging.StreamHandler()
    ]
)

# 保留Flask的默认日志，但调整级别
log = logging.getLogger('werkzeug')
log.setLevel(logging.DEBUG)

app = Flask(__name__)
CORS(app)  # 允许跨域请求
app.logger.setLevel(logging.DEBUG)

# MPV Socket路径
MPV_SOCKET_PATH = "/data/data/com.termux/files/usr/tmp/mpv_ctrl/socket"

# 本地缓存目录
LOCAL_DIR = "/data/data/com.termux/files/home/nas_audio_cache"

# 自动缓存线程控制
auto_cache_thread = None
auto_cache_running = False

# 播放结束监控线程控制
playback_monitor_thread = None
playback_monitor_running = False

# 下载进度跟踪
download_progress = {}  # {task_id: {filename, total_size, current_size, status, error, start_time}}
download_lock = threading.Lock()

# 时间轴配置
TIMELINE_DIR = "/data/data/com.termux/files/home/audio_logs/timeline"
os.makedirs(TIMELINE_DIR, exist_ok=True)
TIMELINE_FILE = f"{TIMELINE_DIR}/timeline.json"
TIMELINE_MAX_EVENTS = 500  # 最大事件数量

# 时间轴数据结构
timeline_events = deque(maxlen=TIMELINE_MAX_EVENTS)
current_playing_file = ""
next_playing_file = ""

# 自己记录的播放状态
self_recorded_state = {
    "playing": False,  # 是否正在播放
    "paused": True,    # 是否暂停
    "current_file": "", # 当前播放的文件名
    "volume": 100,     # 当前音量
    "position": 0,     # 当前播放位置（秒）
    "duration": 0,     # 总时长（秒）
    "progress": 0      # 播放进度百分比
}
timeline_lock = threading.RLock()  # 用于线程安全

# 配置操作日志
LOG_DIR = "/data/data/com.termux/files/home/audio_logs"
os.makedirs(LOG_DIR, exist_ok=True)

# 创建专门的操作日志记录器
operation_logger = logging.getLogger('operations')
operation_logger.setLevel(logging.DEBUG)

# 添加控制台处理器，用于实时输出
console_handler = logging.StreamHandler()
console_handler.setLevel(logging.DEBUG)
console_handler.setFormatter(logging.Formatter('%(asctime)s - [OPERATION:%(filename)s:%(lineno)d] - %(message)s'))
operation_logger.addHandler(console_handler)

# 创建文件处理器
file_handler = logging.FileHandler(f"{LOG_DIR}/operations.log")
file_handler.setLevel(logging.DEBUG)

# 创建日志格式
formatter = logging.Formatter('%(asctime)s [%(levelname)s] [%(filename)s:%(lineno)d] %(message)s')
file_handler.setFormatter(formatter)

# 添加处理器到记录器
operation_logger.addHandler(file_handler)
operation_logger.propagate = False  # 防止日志传播到父记录器

# 添加操作日志装饰器 - 简化版本，减少日志输出
def log_operation(operation):
    def decorator(f):
        def wrapper(*args, **kwargs):
            # 记录请求参数
            request_params = request.args.to_dict() if request else {}
            log_message = f"用户执行操作: {operation}"
            
            try:
                # 执行原函数并记录执行结果
                result = f(*args, **kwargs)
                return result
            except Exception as e:
                # 仅在发生错误时记录详细信息
                detailed_log = f"{log_message}, 请求参数: {request_params}, 函数: {f.__name__}"
                operation_logger.error(f"操作 '{operation}' 执行失败: {str(e)}, {detailed_log}", exc_info=True)
                raise
        wrapper.__name__ = f.__name__
        wrapper.__doc__ = f.__doc__
        return wrapper
    return decorator

MPV_RUNTIME_ERROR = None
try:
    import shutil, subprocess
    mpv_bin = shutil.which("mpv")
    if not mpv_bin:
        MPV_RUNTIME_ERROR = "mpv not installed"
        operation_logger.error("mpv not installed")
    else:
        ver = subprocess.run([mpv_bin, "--version"], capture_output=True, text=True)
        if ver.returncode != 0:
            err = (ver.stderr or ver.stdout).strip()
            MPV_RUNTIME_ERROR = err.splitlines()[0] if err else "mpv runtime error"
            operation_logger.error(f"MPV runtime check failed: {MPV_RUNTIME_ERROR}")
except Exception as _e:
    MPV_RUNTIME_ERROR = str(_e)
    operation_logger.error(f"MPV preflight error: {MPV_RUNTIME_ERROR}")

def send_mpv_command(command):
    """使用 socat 向 mpv socket 发送命令"""
    operation_logger.debug(f"[MPV命令] 尝试发送命令: {command}")
    
    # 检查socket文件是否存在
    if not os.path.exists(MPV_SOCKET_PATH):
        extra = f" ({MPV_RUNTIME_ERROR})" if MPV_RUNTIME_ERROR else ""
        error_msg = f"MPV Socket not found at {MPV_SOCKET_PATH}. Is MPV running?{extra}"
        operation_logger.debug(f"[MPV命令] {error_msg}")
        return False, error_msg
    
    # 记录socket文件权限信息以帮助排查权限问题
    if os.path.exists(MPV_SOCKET_PATH):
        import stat
        stat_info = os.stat(MPV_SOCKET_PATH)
        operation_logger.debug(f"[MPV命令] Socket文件存在，权限: {stat.filemode(stat_info.st_mode)}, 所有者: {stat_info.st_uid}:{stat_info.st_gid}")
    
    # 构建JSON命令
    json_command = json.dumps({"command": command})
    operation_logger.debug(f"[MPV命令] 构建的JSON命令: {json_command}")
    
    # 使用 socat 执行命令
    # 转义单引号，防止 shell 注入或语法错误
    safe_json_command = json_command.replace("'", "'\\''")
    # 使用 subprocess.run(shell=True) 以便正确处理管道，同时使用 Python 的 timeout
    cmd = f"echo '{safe_json_command}' | socat -t 0 - UNIX-CONNECT:{MPV_SOCKET_PATH}"
    operation_logger.debug(f"[MPV命令] 执行的系统命令: {cmd}")
    
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            timeout=2,
            capture_output=True,
            text=True
        )
        
        operation_logger.debug(f"[MPV命令] subprocess返回码: {result.returncode}")
        if result.stdout:
            operation_logger.debug(f"[MPV命令] 标准输出: {result.stdout.strip()}")
        
        # 即使成功，如果有 stderr 也记录下来，可能是警告
        if result.stderr:
            operation_logger.debug(f"[MPV命令] 标准错误: {result.stderr.strip()}")
        
        if result.returncode == 0:
            operation_logger.debug(f"[MPV命令] 命令 '{command}' 发送成功")
            return True, "Command sent successfully."
        else:
            error_msg = f"Failed to send command via socat, return code: {result.returncode}, stderr: {result.stderr.strip()}"
            operation_logger.debug(f"[MPV命令] {error_msg}")
            return False, error_msg
            
    except subprocess.TimeoutExpired:
        error_msg = f"Timeout (2s) when sending MPV command: {command}"
        operation_logger.debug(f"[MPV命令] {error_msg}")
        return False, error_msg
    except Exception as e:
        error_msg = f"Exception when sending MPV command: {str(e)}"
        operation_logger.debug(f"[MPV命令] {error_msg}")
        return False, error_msg

def add_to_timeline(action, description, details=None):
    """添加事件到时间轴"""
    global timeline_events
    
    event = {
        "timestamp": datetime.now().isoformat(),
        "action": action,
        "description": description,
        "details": details or {}
    }
    
    with timeline_lock:
        timeline_events.append(event)
        save_timeline()
    
    operation_logger.debug(f"[时间轴] 添加事件: {action} - {description}")


def save_timeline():
    """保存时间轴到文件"""
    try:
        with timeline_lock:
            events_list = list(timeline_events)
        
        with open(TIMELINE_FILE, 'w', encoding='utf-8') as f:
            json.dump(events_list, f, ensure_ascii=False, indent=2)
        
        operation_logger.debug(f"[时间轴] 已保存到文件，共 {len(events_list)} 个事件")
    except Exception as e:
        operation_logger.error(f"[时间轴] 保存失败: {str(e)}", exc_info=True)


def load_timeline():
    """从文件加载时间轴"""
    global timeline_events
    
    try:
        if os.path.exists(TIMELINE_FILE):
            with open(TIMELINE_FILE, 'r', encoding='utf-8') as f:
                events_list = json.load(f)
                timeline_events = deque(events_list, maxlen=TIMELINE_MAX_EVENTS)
            
            operation_logger.debug(f"[时间轴] 从文件加载，共 {len(events_list)} 个事件")
        else:
            operation_logger.debug("[时间轴] 时间轴文件不存在，创建新的")
    except Exception as e:
        operation_logger.error(f"[时间轴] 加载失败: {str(e)}", exc_info=True)
        timeline_events = deque(maxlen=TIMELINE_MAX_EVENTS)


# 时间轴相关API端点
@app.route('/mpv/timeline', methods=['GET'])
@log_operation("获取时间轴")
def get_timeline():
    """获取时间轴数据"""
    global timeline_events, current_playing_file, next_playing_file
    
    try:
        with timeline_lock:
            events_list = list(timeline_events)
        
        return jsonify({
            "events": events_list,
            "current_playing": current_playing_file,
            "next_playing": next_playing_file,
            "total": len(events_list)
        }), 200
    except Exception as e:
        operation_logger.error(f"[时间轴API] 获取时间轴失败: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/mpv/timeline/clear', methods=['POST'])
@log_operation("清空时间轴")
def clear_timeline():
    """清空时间轴数据"""
    global timeline_events
    
    try:
        with timeline_lock:
            timeline_events.clear()
            save_timeline()
        
        add_to_timeline("system", "时间轴已清空", {})
        return jsonify({"status": "ok", "message": "时间轴已清空"}), 200
    except Exception as e:
        operation_logger.error(f"[时间轴API] 清空时间轴失败: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route('/timeline/status', methods=['GET'])
@log_operation("获取播放状态(带时间轴更新)")
def get_status_with_timeline():
    """获取播放状态并更新时间轴"""
    # 这里会在后续实现，先添加一个简单的实现
    try:
        # 获取状态API的实现会在后续添加
        return jsonify({"status": "ok", "message": "功能待实现"}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def get_file_duration(file_path):
    """使用多种方法获取文件时长，作为MPV无法返回时长时的备用方法"""
    try:
        # 检查文件是否存在
        if not os.path.exists(file_path):
            operation_logger.debug(f"[文件时长] 文件不存在: {file_path}")
            return 0
        
        # 尝试使用ffprobe获取时长
        import subprocess
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            file_path
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        if result.returncode == 0 and result.stdout.strip():
            duration = float(result.stdout.strip())
            operation_logger.debug(f"[文件时长] 使用ffprobe获取到时长: {duration}秒")
            return duration
        
        # 尝试使用ffmpeg获取时长
        try:
            cmd = [
                'ffmpeg',
                '-i', file_path,
                '-v', 'error',
                '-f', 'null',
                '-'
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.stderr.strip():
                # 从ffmpeg的错误输出中提取时长
                import re
                duration_match = re.search(r"Duration: (\d+):(\d+):(\d+)\.(\d+)", result.stderr)
                if duration_match:
                    hours = int(duration_match.group(1))
                    minutes = int(duration_match.group(2))
                    seconds = int(duration_match.group(3))
                    milliseconds = int(duration_match.group(4)) / 100
                    duration = hours * 3600 + minutes * 60 + seconds + milliseconds
                    operation_logger.debug(f"[文件时长] 使用ffmpeg获取到时长: {duration}秒")
                    return duration
        except Exception as e:
            operation_logger.debug(f"[文件时长] 使用ffmpeg获取时长失败: {e}")
        
        # 尝试使用mutagen库获取时长
        try:
            import mutagen
            audio = mutagen.File(file_path)
            if audio and hasattr(audio.info, 'length'):
                duration = audio.info.length
                operation_logger.debug(f"[文件时长] 使用mutagen获取到时长: {duration}秒")
                return duration
        except Exception as e:
            operation_logger.debug(f"[文件时长] 使用mutagen获取时长失败: {e}")
            
        operation_logger.debug(f"[文件时长] 无法获取文件时长: {file_path}")
        return 0
    except Exception as e:
        operation_logger.debug(f"[文件时长] 获取文件时长异常: {e}")
        return 0

def get_mpv_property(property_name):
    """获取MPV属性值"""
    operation_logger.debug(f"[MPV属性] 尝试获取属性: {property_name}")
    
    # 检查socket文件是否存在
    if not os.path.exists(MPV_SOCKET_PATH):
        extra = f" ({MPV_RUNTIME_ERROR})" if MPV_RUNTIME_ERROR else ""
        error_msg = f"MPV Socket not found at {MPV_SOCKET_PATH}. Is MPV running?{extra}"
        operation_logger.debug(f"[MPV属性] {error_msg}")
        # 为不同属性返回合理的默认值
        if property_name == "filename":
            return "", error_msg
        elif property_name == "volume":
            return 100, error_msg  # 默认音量100%
        elif property_name in ["time-pos", "duration"]:
            return 0, error_msg  # 默认播放位置和持续时间为0
        elif property_name in ["pause", "eof-reached", "idle-active"]:
            return False, error_msg  # 默认非暂停、未到文件末尾、非空闲
        return None, error_msg
    
    # 构建JSON命令
    json_command = json.dumps({"command": ["get_property", property_name]})
    operation_logger.debug(f"[MPV属性] 构建的JSON命令: {json_command}")
    
    # 使用socat发送命令并获取输出
    import subprocess
    try:
        operation_logger.debug(f"[MPV属性] 执行subprocess命令获取属性")
        result = subprocess.run(
            ['socat', '-t', '1', '-', f'UNIX-CONNECT:{MPV_SOCKET_PATH}'],
            input=json_command,
            text=True,
            capture_output=True,
            timeout=2  # 添加超时限制
        )
        
        operation_logger.debug(f"[MPV属性] subprocess返回码: {result.returncode}")
        operation_logger.debug(f"[MPV属性] 标准输出: '{result.stdout.strip()}'")
        operation_logger.debug(f"[MPV属性] 标准错误: '{result.stderr.strip()}'")
        
        if result.returncode == 0:
            response_text = result.stdout.strip()
            if response_text:
                operation_logger.debug(f"[MPV属性] 收到响应文本: {response_text}")
                try:
                    response = json.loads(response_text)
                    operation_logger.debug(f"[MPV属性] 解析后的响应: {response}")
                    
                    if 'data' in response:
                        operation_logger.debug(f"[MPV属性] 成功获取属性 {property_name}: {response['data']}")
                        # 特殊处理filename属性，确保返回字符串类型
                        if property_name == "filename" and response['data'] is None:
                            operation_logger.debug(f"[MPV属性] filename属性为None，返回空字符串")
                            return "", "Success"
                        return response['data'], "Success"
                    elif 'error' in response:
                        operation_logger.warning(f"[MPV属性] MPV属性错误 {property_name}: {response['error']}")
                        # 对于不同属性返回合理的默认值
                        if property_name == "filename":
                            operation_logger.debug(f"[MPV属性] filename属性出错，返回空字符串")
                            return "", "MPV error but returning empty string for filename"
                        elif property_name == "volume":
                            return 100, f"MPV error but returning default volume"
                        elif property_name in ["time-pos", "duration"]:
                            return 0, f"MPV error but returning default value for {property_name}"
                        elif property_name in ["pause", "eof-reached", "idle-active"]:
                            return False, f"MPV error but returning default value for {property_name}"
                        return None, f"MPV error: {response['error']}"
                    else:
                        operation_logger.warning(f"[MPV属性] 响应中既没有data也没有error字段: {response}")
                        if property_name == "filename":
                            return "", "No data or error but returning empty string for filename"
                        elif property_name == "volume":
                            return 100, f"No data or error but returning default volume"
                        elif property_name in ["time-pos", "duration"]:
                            return 0, f"No data or error but returning default value for {property_name}"
                        elif property_name in ["pause", "eof-reached", "idle-active"]:
                            return False, f"No data or error but returning default value for {property_name}"
                        return None, "Response contains neither data nor error"
                except json.JSONDecodeError:
                    operation_logger.error(f"[MPV属性] 解析MPV响应失败: {response_text}")
                    # 对于不同属性返回合理的默认值
                    if property_name == "filename":
                        return "", "Failed to parse but returning empty string for filename"
                    elif property_name == "volume":
                        return 100, f"Failed to parse but returning default volume"
                    elif property_name in ["time-pos", "duration"]:
                        return 0, f"Failed to parse but returning default value for {property_name}"
                    elif property_name in ["pause", "eof-reached", "idle-active"]:
                        return False, f"Failed to parse but returning default value for {property_name}"
                    return None, "Failed to parse MPV response"
            else:
                operation_logger.debug(f"[MPV属性] 从MPV收到空响应，属性: {property_name}")
                # 对于不同属性返回合理的默认值
                if property_name == "filename":
                    # 特殊处理：如果收到空响应，尝试从path属性获取
                    try:
                        path, path_msg = get_mpv_property("path")
                        if path and isinstance(path, str) and path.strip():
                            filename_from_path = os.path.basename(path)
                            operation_logger.debug(f"[MPV属性] 从path获取filename: {filename_from_path}")
                            return filename_from_path, "Empty response but got filename from path"
                    except Exception as e:
                        operation_logger.debug(f"[MPV属性] 从path获取filename失败: {e}")
                    # 如果从path获取失败，返回空字符串
                    return "", "Empty response but returning empty string for filename"
                elif property_name == "volume":
                    return 100, f"Empty response but returning default volume"
                elif property_name in ["time-pos", "duration"]:
                    return 0, f"Empty response but returning default value for {property_name}"
                elif property_name in ["pause", "eof-reached", "idle-active"]:
                    return False, f"Empty response but returning default value for {property_name}"
                return None, "Empty response from MPV"
        else:
            operation_logger.warning(f"[MPV属性] 获取属性 {property_name} 失败, 返回码: {result.returncode}, 错误输出: {result.stderr}")
            # 对于不同属性返回合理的默认值
            if property_name == "filename":
                # 特殊处理：如果命令执行失败，尝试从path属性获取
                try:
                    path, path_msg = get_mpv_property("path")
                    if path and isinstance(path, str) and path.strip():
                        filename_from_path = os.path.basename(path)
                        operation_logger.debug(f"[MPV属性] 从path获取filename: {filename_from_path}")
                        return filename_from_path, "Command failed but got filename from path"
                except Exception as e:
                    operation_logger.debug(f"[MPV属性] 从path获取filename失败: {e}")
                # 如果从path获取失败，返回空字符串
                return "", "Command failed but returning empty string for filename"
            elif property_name == "volume":
                return 100, f"Command failed but returning default volume"
            elif property_name in ["time-pos", "duration"]:
                return 0, f"Command failed but returning default value for {property_name}"
            elif property_name in ["pause", "eof-reached", "idle-active"]:
                return False, f"Command failed but returning default value for {property_name}"
            return None, f"Command failed with return code {result.returncode}"
    except subprocess.TimeoutExpired:
        operation_logger.error(f"[MPV属性] 获取MPV属性 {property_name} 超时")
        # 对于不同属性返回合理的默认值
        if property_name == "filename":
            # 特殊处理：如果超时，尝试从path属性获取
            try:
                path, path_msg = get_mpv_property("path")
                if path and isinstance(path, str) and path.strip():
                    filename_from_path = os.path.basename(path)
                    operation_logger.debug(f"[MPV属性] 从path获取filename: {filename_from_path}")
                    return filename_from_path, "Timeout but got filename from path"
            except Exception as e:
                operation_logger.debug(f"[MPV属性] 从path获取filename失败: {e}")
            # 如果从path获取失败，返回空字符串
            return "", "Timeout but returning empty string for filename"
        elif property_name == "volume":
            return 100, f"Timeout but returning default volume"
        elif property_name in ["time-pos", "duration"]:
            return 0, f"Timeout but returning default value for {property_name}"
        elif property_name in ["pause", "eof-reached", "idle-active"]:
            return False, f"Timeout but returning default value for {property_name}"
        return None, "Timeout getting MPV property"
    except Exception as e:
        operation_logger.error(f"[MPV属性] 获取MPV属性 {property_name} 异常: {str(e)}", exc_info=True)
        # 对于不同属性返回合理的默认值
        if property_name == "filename":
            # 特殊处理：如果发生异常，尝试从path属性获取
            try:
                path, path_msg = get_mpv_property("path")
                if path and isinstance(path, str) and path.strip():
                    filename_from_path = os.path.basename(path)
                    operation_logger.debug(f"[MPV属性] 从path获取filename: {filename_from_path}")
                    return filename_from_path, "Exception but got filename from path"
            except Exception as e:
                operation_logger.debug(f"[MPV属性] 从path获取filename失败: {e}")
            # 如果从path获取失败，返回空字符串
            return "", "Exception but returning empty string for filename"
        elif property_name == "volume":
            return 100, f"Exception but returning default volume"
        elif property_name in ["time-pos", "duration"]:
            return 0, f"Exception but returning default value for {property_name}"
        elif property_name in ["pause", "eof-reached", "idle-active"]:
            return False, f"Exception but returning default value for {property_name}"
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

def rclone_sync(filename=None):
    """同步NAS文件到本地缓存（一次只缓存一个文件，已缓存的文件不再重复缓存）
    
    Args:
        filename: 要缓存的文件名，如果为None则列出文件但不缓存
        
    Returns:
        tuple: (是否成功, 消息)
    """
    app.logger.debug(f"[RCLONE] 开始同步，目标文件: {filename}")
    try:
        # 确保本地缓存目录存在
        os.makedirs(LOCAL_DIR, exist_ok=True)
        
        # 如果指定了文件名
        if filename:
            # 检查文件是否已经在本地缓存中
            local_file_path = os.path.join(LOCAL_DIR, filename)
            if os.path.exists(local_file_path):
                app.logger.debug(f"[RCLONE] 文件已存在于缓存中: {filename}")
                return True, f"文件 '{filename}' 已存在于缓存中，不需要重新下载"
            
            # 使用rclone_copy_file复制单个文件
            app.logger.debug(f"[RCLONE] 开始缓存文件: {filename}")
            success, message = rclone_copy_file(filename, local_file_path)
            if success:
                app.logger.debug(f"[RCLONE] 文件缓存成功: {filename}")
                return True, f"文件 '{filename}' 缓存成功"
            else:
                app.logger.error(f"[RCLONE] 文件缓存失败: {filename}, 错误: {message}")
                return False, f"文件 '{filename}' 缓存失败: {message}"
        else:
            # 如果没有指定文件名，返回文件列表但不缓存
            app.logger.debug("[RCLONE] 未指定文件名，返回NAS文件列表")
            files, message = rclone_list_files()
            if files is not None:
                return True, f"NAS中有 {len(files)} 个文件可用"
            else:
                return False, message
    except Exception as e:
        app.logger.error(f"[RCLONE] 同步过程中发生异常: {str(e)}", exc_info=True)
        return False, f"同步异常: {str(e)}"

def rclone_list_files():
    """列出NAS上的音频文件（不下载）"""
    app.logger.info("[RCLONE] 开始获取NAS文件列表")
    try:
        rclone_remote = "synology:download/bilibili/push"
        app.logger.debug(f"[RCLONE] 使用远程路径: {rclone_remote}")
        
        # 使用rclone lsjson获取文件列表 - 使用参数列表避免shell注入风险
        cmd_args = [
            'rclone', 'lsjson', rclone_remote,
            '--include', '*.mp4',
            '--include', '*.mp3',
            '--include', '*.flac',
            '--include', '*.ogg',
            '--include', '*.aac',
            '--include', '*.m4a',
            '--include', '*.wav',
            '--include', '*.webm'
        ]
        app.logger.debug(f"[RCLONE] 执行命令: {' '.join(cmd_args)}")
        
        import subprocess
        start_time = time.time()
        result = subprocess.run(cmd_args, capture_output=True, text=True)
        execution_time = time.time() - start_time
        
        app.logger.debug(f"[RCLONE] 命令执行完成，返回码: {result.returncode}，执行时间: {execution_time:.2f}秒")
        app.logger.debug(f"[RCLONE] 标准输出长度: {len(result.stdout)} 字符")
        app.logger.debug(f"[RCLONE] 错误输出长度: {len(result.stderr)} 字符")
        
        if result.stderr.strip():
            app.logger.warning(f"[RCLONE] 命令有错误输出: {result.stderr.strip()}")
        
        if result.returncode == 0:
            app.logger.debug("[RCLONE] 命令执行成功，开始解析JSON输出")
            
            # 检查输出是否为空
            if not result.stdout.strip():
                app.logger.warning("[RCLONE] rclone返回空输出")
                return [], "rclone returned empty output"
            
            try:
                files_data = json.loads(result.stdout)
                app.logger.debug(f"[RCLONE] JSON解析成功，获取到 {len(files_data)} 个项目")
                
                # 确保解析结果是列表
                if not isinstance(files_data, list):
                    app.logger.error("[RCLONE] 解析结果不是列表格式")
                    return [], "Parsed data is not a list"
                
                # 统计目录和文件数量
                dir_count = sum(1 for item in files_data if item.get('IsDir', False))
                file_count = len(files_data) - dir_count
                app.logger.info(f"[RCLONE] 获取到 {dir_count} 个目录和 {file_count} 个文件")
                
                # 检查文件数据中的关键字段
                file_list = []
                for item in files_data:
                    if not item.get('IsDir', False):
                        if 'Name' in item:
                            file_list.append(item['Name'])
                        else:
                            app.logger.warning(f"[RCLONE] 文件项缺少'Name'字段: {item}")
                
                app.logger.info(f"[RCLONE] 最终返回文件列表，长度: {len(file_list)}")
                if file_list:
                    app.logger.debug(f"[RCLONE] 文件列表示例: {file_list[:3]}")
                else:
                    app.logger.warning("[RCLONE] 没有找到匹配的音频文件")
                
                return file_list, "Success"
                
            except json.JSONDecodeError as e:
                app.logger.error(f"[RCLONE] JSON解析失败: {str(e)}")
                # 记录更多详细信息以便调试
                app.logger.debug(f"[RCLONE] 原始输出前500字符: {result.stdout[:500]}")
                return [], f"Failed to parse rclone output: {str(e)}"
            except KeyError as e:
                app.logger.error(f"[RCLONE] 处理文件数据时缺少关键字段: {str(e)}")
                # 尝试提供更有用的错误信息
                return [], f"Key error in rclone data: {str(e)}. Check if 'Name' field exists in all items."
            except Exception as e:
                app.logger.error(f"[RCLONE] 处理文件数据时发生意外错误: {str(e)}", exc_info=True)
                return [], f"Unexpected error processing file data: {str(e)}"
        else:
            app.logger.error(f"[RCLONE] 命令执行失败，返回码: {result.returncode}")
            error_msg = result.stderr.strip() or "No error message provided"
            app.logger.error(f"[RCLONE] 错误详情: {error_msg}")
            return [], f"rclone command failed (code {result.returncode}): {error_msg}"
    except subprocess.SubprocessError as e:
        app.logger.error(f"[RCLONE] 执行rclone命令时出错: {str(e)}", exc_info=True)
        return [], f"Subprocess error: {str(e)}"
    except Exception as e:
        app.logger.error(f"[RCLONE] 获取文件列表时发生未预期异常: {str(e)}", exc_info=True)
        return [], f"Exception during rclone operation: {str(e)}"

def rclone_copy_file(remote_path, local_path, task_id=None):
    """从NAS复制单个文件到本地，支持进度跟踪"""
    app.logger.info(f"[RCLONE] 开始复制文件: 远程={remote_path} -> 本地={local_path}, 任务ID={task_id}")
    
    # 检查本地文件是否已存在
    if os.path.exists(local_path):
        app.logger.info(f"[RCLONE] 文件已存在于本地: {local_path}，跳过复制")
        if task_id:
            with download_lock:
                if task_id in download_progress:
                    download_progress[task_id]['status'] = 'completed'
                    download_progress[task_id]['current_size'] = download_progress[task_id].get('total_size', 0)
        return True, "File already exists locally"
    
    try:
        rclone_remote = "synology:download/bilibili/push"
        remote_file = f"{rclone_remote}/{remote_path}"
        app.logger.debug(f"[RCLONE] 构建远程文件路径: {remote_file}")
        
        # 如果有任务ID，先获取文件大小
        total_size = 0
        if task_id:
            try:
                import subprocess
                # 使用参数列表而不是shell命令，避免空格问题
                size_result = subprocess.run(
                    ['rclone', 'size', remote_file, '--json'],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                if size_result.returncode == 0:
                    size_data = json.loads(size_result.stdout)
                    total_size = size_data.get('bytes', 0)
                    app.logger.debug(f"[RCLONE] 获取到文件大小: {total_size} 字节")
                    
                    # 初始化进度信息
                    with download_lock:
                        download_progress[task_id] = {
                            'filename': remote_path,
                            'total_size': total_size,
                            'current_size': 0,
                            'status': 'downloading',
                            'error': None,
                            'start_time': time.time()
                        }
            except Exception as e:
                app.logger.warning(f"[RCLONE] 获取文件大小失败: {str(e)}")
        
        # 确保本地目录存在
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        app.logger.debug(f"[RCLONE] 确保本地目录存在: {os.path.dirname(local_path)}")
        
        import subprocess
        # 使用参数列表而不是shell命令，这样可以正确处理包含空格的文件名
        cmd_args = ['rclone', 'copyto', remote_file, local_path]
        app.logger.debug(f"[RCLONE] 执行命令: {' '.join(cmd_args)}")
        
        # 在后台线程中执行下载，同时监控进度
        download_complete = threading.Event()
        download_error = [None]  # 使用列表来存储错误，以便在线程中修改
        
        def download_worker():
            try:
                start_time = time.time()
                # 不使用shell=True，直接传递参数列表
                result = subprocess.run(cmd_args, capture_output=True, text=True)
                execution_time = time.time() - start_time
                
                app.logger.debug(f"[RCLONE] 命令执行完成，返回码: {result.returncode}，执行时间: {execution_time:.2f}秒")
                
                if result.stderr.strip():
                    app.logger.warning(f"[RCLONE] 命令有错误输出: {result.stderr.strip()}")
                
                if result.returncode == 0:
                    # 验证文件是否真的被复制成功
                    if os.path.exists(local_path):
                        file_size = os.path.getsize(local_path)
                        app.logger.info(f"[RCLONE] 文件复制成功: {remote_path} -> {local_path}, 文件大小: {file_size} 字节")
                        
                        if task_id:
                            with download_lock:
                                if task_id in download_progress:
                                    download_progress[task_id]['status'] = 'completed'
                                    download_progress[task_id]['current_size'] = file_size
                                    download_progress[task_id]['total_size'] = file_size
                    else:
                        app.logger.error(f"[RCLONE] 文件复制命令成功执行，但目标文件不存在: {local_path}")
                        download_error[0] = "Command succeeded but file not found"
                        if task_id:
                            with download_lock:
                                if task_id in download_progress:
                                    download_progress[task_id]['status'] = 'error'
                                    download_progress[task_id]['error'] = download_error[0]
                else:
                    error_msg = result.stderr.strip() or f"Command failed with exit code {result.returncode}"
                    app.logger.error(f"[RCLONE] 文件复制失败: {remote_path}, 错误: {error_msg}")
                    download_error[0] = error_msg
                    if task_id:
                        with download_lock:
                            if task_id in download_progress:
                                download_progress[task_id]['status'] = 'error'
                                download_progress[task_id]['error'] = error_msg
            except Exception as e:
                app.logger.error(f"[RCLONE] 下载线程异常: {str(e)}", exc_info=True)
                download_error[0] = str(e)
                if task_id:
                    with download_lock:
                        if task_id in download_progress:
                            download_progress[task_id]['status'] = 'error'
                            download_progress[task_id]['error'] = str(e)
            finally:
                download_complete.set()
        
        # 启动下载线程
        download_thread = threading.Thread(target=download_worker, daemon=True)
        download_thread.start()
        
        # 如果有任务ID，监控下载进度
        if task_id and total_size > 0:
            while not download_complete.is_set():
                if os.path.exists(local_path):
                    current_size = os.path.getsize(local_path)
                    with download_lock:
                        if task_id in download_progress:
                            download_progress[task_id]['current_size'] = current_size
                time.sleep(0.5)  # 每0.5秒检查一次
        
        # 等待下载完成
        download_complete.wait()
        
        if download_error[0]:
            return False, download_error[0]
        else:
            return True, f"File copied successfully"
            
    except subprocess.SubprocessError as e:
        app.logger.error(f"[RCLONE] 执行复制命令时出错: {remote_path}, 错误: {str(e)}", exc_info=True)
        if task_id:
            with download_lock:
                if task_id in download_progress:
                    download_progress[task_id]['status'] = 'error'
                    download_progress[task_id]['error'] = str(e)
        return False, f"Subprocess error: {str(e)}"
    except Exception as e:
        app.logger.error(f"[RCLONE] 复制文件时发生未预期错误: {remote_path}, 错误: {str(e)}", exc_info=True)
        if task_id:
            with download_lock:
                if task_id in download_progress:
                    download_progress[task_id]['status'] = 'error'
                    download_progress[task_id]['error'] = str(e)
        return False, f"Unexpected error: {str(e)}"


def get_file_from_cache_or_nas(filename, task_id=None):
    """从缓存获取文件，如果不存在则从NAS拉取"""
    local_file_path = os.path.join(LOCAL_DIR, filename)
    
    # 检查本地是否已存在
    if os.path.exists(local_file_path):
        return True, local_file_path, "File exists in cache", None
    
    # 从NAS拉取文件
    success, message = rclone_copy_file(filename, local_file_path, task_id)
    if success:
        return True, local_file_path, "File copied from NAS", task_id
    else:
        return False, None, f"Failed to get file from NAS: {message}", task_id

def auto_cache_worker():
    """自动缓存工作线程 - 只缓存下一首文件"""
    global auto_cache_running
    app.logger.info("[AUTO_CACHE] 自动缓存线程已启动 (只缓存下一首模式)")
    
    # 检查间隔时间（秒）
    check_interval = 600  # 10分钟
    
    while auto_cache_running:
        try:
            # 获取当前播放的文件信息，以确定下一首需要缓存的文件
            current_file = None
            try:
                # 获取当前播放文件的名称
                current_filename, filename_msg = get_mpv_property("filename")
                if current_filename and isinstance(current_filename, str):
                    current_file = os.path.basename(current_filename)
                    app.logger.info(f"[AUTO_CACHE] 当前播放文件: {current_file}")
                elif not current_filename:
                    app.logger.debug(f"[AUTO_CACHE] 获取filename失败: {filename_msg}")
            except Exception as e:
                app.logger.warning(f"[AUTO_CACHE] 获取当前播放文件信息失败: {str(e)}")
            
            if current_file:
                # 获取NAS文件列表
                files, message = rclone_list_files()
                app.logger.debug(f"[AUTO_CACHE] 获取NAS文件列表结果: 长度={len(files) if files else 0}, 消息={message}")
                
                if files is not None and len(files) > 0:
                    # 排序文件列表，假设是按字母顺序或时间顺序
                    sorted_files = sorted(files)
                    app.logger.debug(f"[AUTO_CACHE] 排序后的文件列表: {sorted_files}")
                    
                    # 找到当前文件在列表中的位置
                    try:
                        current_index = sorted_files.index(current_file)
                        app.logger.debug(f"[AUTO_CACHE] 当前文件索引: {current_index}")
                        
                        # 确定下一首文件（循环播放）
                        if current_index < len(sorted_files) - 1:
                            next_file = sorted_files[current_index + 1]
                        else:
                            # 到列表末尾了，下一首是第一个文件
                            next_file = sorted_files[0]
                        
                        app.logger.info(f"[AUTO_CACHE] 下一首文件: {next_file}")
                        
                        # 检查下一首文件是否已缓存
                        local_file_path = os.path.join(LOCAL_DIR, next_file)
                        if not os.path.exists(local_file_path):
                            app.logger.info(f"[AUTO_CACHE] 开始缓存下一首文件: {next_file} -> {local_file_path}")
                            success, msg = rclone_copy_file(next_file, local_file_path)
                            if success:
                                app.logger.info(f"[AUTO_CACHE] 下一首文件缓存成功: {next_file}")
                            else:
                                app.logger.error(f"[AUTO_CACHE] 下一首文件缓存失败: {next_file}, 错误: {msg}")
                        else:
                            app.logger.info(f"[AUTO_CACHE] 下一首文件已存在于缓存中: {next_file}")
                    except ValueError:
                        app.logger.warning(f"[AUTO_CACHE] 当前播放文件 {current_file} 不在NAS文件列表中")
            
            # 每10分钟检查一次，而不是30分钟，以便及时缓存下一首
            app.logger.debug("[AUTO_CACHE] 检查完成，等待下一次执行 (10分钟)")
            time.sleep(600)  # 10分钟
        except Exception as e:
            app.logger.error(f"[AUTO_CACHE] 自动缓存出错: {str(e)}", exc_info=True)
            # 出错后仍然继续，避免线程退出
            time.sleep(600)  # 出错后也等待10分钟


def playback_monitor_worker():
    """播放结束监控工作线程 - 检测播放结束并自动播放下一首"""
    global playback_monitor_running, current_playing_file, self_recorded_state
    app.logger.info("[PLAYBACK_MONITOR] 播放结束监控线程已启动")
    
    # 检查间隔时间（秒）
    check_interval = 0.5  # 缩短检查间隔，提高响应速度
    
    # 用于跟踪状态变化
    last_status = {
        'progress': 0,
        'paused': self_recorded_state["paused"],
        'playing_file': current_playing_file,
        'time_pos': 0,
        'time_pos_stable_count': 0,
        'stable_threshold': 10
    }
    
    while playback_monitor_running:
        try:
            # 检查MPV是否正在运行
            mpv_running = os.path.exists(MPV_SOCKET_PATH)
            
            if not mpv_running:
                # MPV未运行，重置状态
                if last_status['playing_file']:
                    app.logger.info("[PLAYBACK_MONITOR] MPV已停止运行")
                    current_playing_file = ""
                    last_status['playing_file'] = ""
                time.sleep(check_interval)
                continue
            
            # 获取当前播放文件信息
            filename = self_recorded_state["current_file"]
            
            # 更新当前播放文件
            if filename and filename != last_status['playing_file']:
                app.logger.info(f"[PLAYBACK_MONITOR] 播放文件变更: {last_status['playing_file']} -> {filename}")
                current_playing_file = filename
                last_status['playing_file'] = filename
                # 重置状态，新文件开始播放
                last_status['progress'] = 0
                last_status['time_pos'] = 0
                last_status['time_pos_stable_count'] = 0
                last_status['reminder_sent'] = False
            
            # 定期获取并更新状态，确保自己记录的状态是最新的
            try:
                # 获取MPV属性，增强可靠性
                max_retries = 5
                retry_count = 0
                position = None
                duration = None
                pause_state = None
                eof_reached = None
                idle_active = None
                
                # 重试获取MPV属性，重点获取time-pos
                while retry_count < max_retries:
                    # 单独获取time-pos，增加重试次数
                    time_pos_result = get_mpv_property("time-pos")
                    position = time_pos_result[0]
                    
                    # 获取其他属性
                    duration, _ = get_mpv_property("duration")
                    pause_state, _ = get_mpv_property("pause")
                    eof_reached, _ = get_mpv_property("eof-reached")
                    idle_active, _ = get_mpv_property("idle-active")
                    
                    # 如果获取到了有效位置，就退出重试
                    if position is not None and position > 0:
                        break
                    
                    retry_count += 1
                    time.sleep(0.05)  # 短暂等待后重试，缩短重试间隔
                
                # 获取当前时间，用于更精确的位置计算
                current_time = time.time()
                
                # 更新自己记录的状态
                current_duration = duration if duration is not None else self_recorded_state["duration"]
                
                # 计算当前位置：优先使用MPV返回的position，但如果MPV返回的position为0且自己记录的position大于0，则使用自己记录的位置加上时间差
                if position is not None and position > 0:
                    # MPV返回了有效位置，直接使用
                    current_position = position
                else:
                    # MPV未返回有效位置或返回0，使用自己记录的位置加上精确的时间差
                    if not self_recorded_state["paused"] and self_recorded_state["playing"]:
                        # 正在播放，计算精确的位置增量
                        # 记录上一次更新的时间
                        if "last_update_time" not in self_recorded_state:
                            self_recorded_state["last_update_time"] = current_time
                        
                        # 计算时间差
                        time_diff = current_time - self_recorded_state["last_update_time"]
                        # 更新上一次更新的时间
                        self_recorded_state["last_update_time"] = current_time
                        
                        # 计算位置增量
                        position_increment = time_diff
                        current_position = self_recorded_state["position"] + position_increment
                    else:
                        # 暂停或未播放，保持当前位置
                        current_position = self_recorded_state["position"]
                
                # 确保位置不超过时长
                if current_duration > 0:
                    current_position = min(current_position, current_duration)
                    current_progress = (current_position / current_duration) * 100 if current_position else 0
                    current_progress = round(current_progress, 3)  # 增加精度
                else:
                    # 时长为0时，根据自己记录的位置计算进度
                    current_progress = 0
                
                # 更新自己记录的状态
                self_recorded_state["position"] = current_position
                self_recorded_state["duration"] = current_duration
                self_recorded_state["progress"] = current_progress
                self_recorded_state["last_update_time"] = current_time  # 更新最后更新时间
                
                # 更新暂停和播放状态，即使获取失败也使用默认值
                if pause_state is not None:
                    self_recorded_state["paused"] = pause_state
                    self_recorded_state["playing"] = not pause_state
                else:
                    # 默认状态：未暂停，正在播放
                    self_recorded_state["paused"] = False
                    self_recorded_state["playing"] = True
                
                # 额外的进度保护：如果MPV返回的位置与自己记录的位置差异过大，使用MPV返回的位置
                if position is not None and position > 0:
                    position_diff = abs(position - self_recorded_state["position"])
                    if position_diff > 0.5:  # 差异超过0.5秒，可能是MPV状态异常
                        app.logger.warning(f"[PLAYBACK_MONITOR] MPV位置与自己记录的位置差异过大: {position_diff}秒，使用MPV返回的位置")
                        self_recorded_state["position"] = position
                        current_position = position
                        self_recorded_state["last_update_time"] = current_time  # 更新最后更新时间
            except Exception as e:
                app.logger.debug(f"[PLAYBACK_MONITOR] 更新状态时出错: {str(e)}")
                # 继续执行，使用默认值
                eof_reached = False
                idle_active = False
                # 即使出错，也要尝试更新位置
                if not self_recorded_state["paused"] and self_recorded_state["playing"]:
                    # 正在播放，计算位置增量
                    position_increment = check_interval
                    current_position = self_recorded_state["position"] + position_increment
                    current_duration = self_recorded_state["duration"]
                    
                    # 确保位置不超过时长
                    if current_duration > 0:
                        current_position = min(current_position, current_duration)
                        current_progress = (current_position / current_duration) * 100 if current_position else 0
                        current_progress = round(current_progress, 2)
                    else:
                        current_progress = 0
                    
                    # 更新自己记录的状态
                    self_recorded_state["position"] = current_position
                    self_recorded_state["progress"] = current_progress
            
            # 获取自己记录的状态
            current_progress = self_recorded_state["progress"]
            is_paused = self_recorded_state["paused"]
            is_playing = self_recorded_state["playing"]
            current_position = self_recorded_state["position"]
            current_duration = self_recorded_state["duration"]
            
            app.logger.debug(f"[PLAYBACK_MONITOR] 自己记录的状态 - 进度: {current_progress}%, 暂停: {is_paused}, 播放中: {is_playing}, 当前文件: {filename}, 时长: {current_duration}秒")
            
            # 检测time-pos是否稳定（不再变化）
            time_pos_changed = abs(current_position - last_status['time_pos']) > 0.1  # 允许0.1秒的误差
            if time_pos_changed:
                last_status['time_pos_stable_count'] = 0
                last_status['time_pos'] = current_position
            else:
                # 只有当duration有效或current_position > 0时，才增加稳定计数
                if current_duration > 0 or current_position > 0:
                    last_status['time_pos_stable_count'] += 1
            
            # 检测即将切换下一首的提醒条件
            # 定义提醒阈值（进度达到95%时提醒）
            REMINDER_THRESHOLD = 95.0
            # 记录是否已经发送过提醒
            if 'reminder_sent' not in last_status:
                last_status['reminder_sent'] = False
            
            # 发送遮罩提醒
            if (current_duration > 0 and current_progress >= REMINDER_THRESHOLD and not last_status['reminder_sent'] and is_playing and not is_paused):
                # 发送遮罩提醒
                app.logger.info(f"[NEXT_TRACK_REMINDER] 即将切换下一首歌曲：{filename}（进度: {current_progress}%）")
                # 这里可以添加实际的遮罩提醒逻辑，比如发送API请求或触发其他通知
                # 例如：send_mask_reminder(f"即将切换到下一首歌曲")
                # 标记为已发送提醒
                last_status['reminder_sent'] = True
            
            # 检测播放结束条件，支持多种检测方法：
            # 1. 使用eof-reached属性（MPV直接报告播放结束）
            # 2. 使用idle-active属性（MPV进入空闲状态）
            # 3. 进度接近100%（考虑到可能不会精确到100%）
            # 4. time-pos长时间稳定不变（适用于无法获取duration的情况）
            # 5. 进度有变化或已接近完成
            playback_ended = False
            end_reason = ""
            
            # 优化进度显示：在播放结束时确保进度显示为100%
            if eof_reached or (idle_active and is_playing and not is_paused):
                # 播放结束，确保进度显示为100%
                current_progress = 100.0
                current_position = current_duration
                self_recorded_state["progress"] = current_progress
                self_recorded_state["position"] = current_position
                self_recorded_state["last_update_time"] = time.time()  # 更新最后更新时间
                
                playback_ended = True
                if eof_reached:
                    end_reason = "eof-reached属性检测到播放结束"
                else:
                    end_reason = "idle-active属性检测到播放结束"
            elif current_duration > 0:
                # 检查进度是否接近100%
                if current_progress >= 99.9:
                    # 进度接近100%，确保显示为100%
                    current_progress = 100.0
                    current_position = current_duration
                    self_recorded_state["progress"] = current_progress
                    self_recorded_state["position"] = current_position
                    self_recorded_state["last_update_time"] = time.time()  # 更新最后更新时间
                    
                    playback_ended = True
                    end_reason = f"进度检测到播放结束（进度: {current_progress}%）"
                elif current_progress > 0 and current_progress == last_status['progress'] and current_progress > 95:
                    # 进度在95%以上且不再变化，认为播放结束
                    current_progress = 100.0
                    current_position = current_duration
                    self_recorded_state["progress"] = current_progress
                    self_recorded_state["position"] = current_position
                    self_recorded_state["last_update_time"] = time.time()  # 更新最后更新时间
                    
                    playback_ended = True
                    end_reason = f"进度稳定检测到播放结束（进度: {current_progress}%）"
            elif not is_paused and is_playing and filename and last_status['time_pos_stable_count'] >= last_status['stable_threshold'] and (current_duration > 0 or current_position > 0):
                # 适用于无法获取duration的情况，但只有当duration有效或current_position > 0时才触发
                playback_ended = True
                end_reason = f"time-pos稳定检测到播放结束（稳定次数: {last_status['time_pos_stable_count']}）"
            
            # 如果检测到播放结束
            if playback_ended and not is_paused and filename:
                # 只有状态发生变化时才触发
                if last_status['progress'] < 99.9:
                    app.logger.info(f"[PLAYBACK_MONITOR] {end_reason}，自动播放下一首")
                    # 调用下一首函数
                    next_track()
                    # 重置状态
                    last_status['progress'] = 0
                    last_status['time_pos'] = 0
                    last_status['time_pos_stable_count'] = 0
                    # 重置自己记录的状态，确保下一首从0开始
                    self_recorded_state["position"] = 0
                    self_recorded_state["duration"] = 0
                    self_recorded_state["progress"] = 0
                    self_recorded_state["last_update_time"] = time.time()  # 更新最后更新时间
            
            # 更新状态跟踪
            last_status['progress'] = current_progress
            last_status['paused'] = is_paused
            
            time.sleep(check_interval)
        except Exception as e:
            app.logger.error(f"[PLAYBACK_MONITOR] 播放监控出错: {str(e)}", exc_info=True)
            # 出错后仍然继续，避免线程退出
            time.sleep(check_interval)

@app.route('/cache/auto', methods=['POST'])
@log_operation("控制自动缓存")
def control_auto_cache():
    """控制自动缓存服务的启动和停止"""
    global auto_cache_thread, auto_cache_running
    
    try:
        action = request.args.get('action', '').lower()
        
        if action == 'start':
            if not auto_cache_running:
                # 发送遮罩提醒
                send_mask_reminder("正在启动自动缓存服务", "auto_cache_start")
                
                # 启动自动缓存线程
                app.logger.info("[AUTO_CACHE] 正在启动自动缓存服务")
                auto_cache_running = True
                auto_cache_thread = threading.Thread(target=auto_cache_worker, daemon=True)
                auto_cache_thread.start()
                
                # 发送遮罩提醒
                send_mask_reminder("自动缓存服务已启动", "auto_cache_start_success")
                
                return jsonify({"status": "ok", "message": "自动缓存服务已启动"}), 200
            else:
                # 发送遮罩提醒
                send_mask_reminder("自动缓存服务已经在运行", "auto_cache_already_running")
                return jsonify({"status": "ok", "message": "自动缓存服务已经在运行"}), 200
        
        elif action == 'stop':
            if auto_cache_running:
                # 发送遮罩提醒
                send_mask_reminder("正在停止自动缓存服务", "auto_cache_stop")
                
                app.logger.info("[AUTO_CACHE] 正在停止自动缓存服务")
                auto_cache_running = False
                if auto_cache_thread:
                    auto_cache_thread.join(timeout=5)  # 等待线程结束，最多5秒
                
                # 发送遮罩提醒
                send_mask_reminder("自动缓存服务已停止", "auto_cache_stop_success")
                
                return jsonify({"status": "ok", "message": "自动缓存服务已停止"}), 200
            else:
                # 发送遮罩提醒
                send_mask_reminder("自动缓存服务未运行", "auto_cache_not_running")
                return jsonify({"status": "ok", "message": "自动缓存服务未运行"}), 200
        
        elif action == 'status':
            status_msg = "自动缓存服务正在运行" if auto_cache_running else "自动缓存服务未运行"
            # 发送遮罩提醒
            send_mask_reminder(status_msg, "auto_cache_status")
            
            return jsonify({
                "status": "ok",
                "running": auto_cache_running,
                "thread_alive": auto_cache_thread.is_alive() if auto_cache_thread else False
            }), 200
        
        else:
            # 发送遮罩提醒
            send_mask_reminder("无效的操作，支持的操作: start, stop, status", "auto_cache_error")
            return jsonify({"status": "error", "message": "无效的操作，支持的操作: start, stop, status"}), 400
            
    except Exception as e:
        # 发送遮罩提醒
        send_mask_reminder(f"控制自动缓存服务时出错: {str(e)}", "auto_cache_error")
        
        app.logger.error(f"[AUTO_CACHE] 控制自动缓存服务时出错: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

# 下载进度API
@app.route('/download/progress/<task_id>', methods=['GET'])
def get_download_progress(task_id):
    """获取下载进度"""
    try:
        with download_lock:
            if task_id not in download_progress:
                return jsonify({
                    "status": "error",
                    "message": "Task not found",
                    "progress": 0
                }), 404
            
            task_info = download_progress[task_id].copy()
        
        # 计算进度百分比
        if task_info['total_size'] > 0:
            progress = int((task_info['current_size'] / task_info['total_size']) * 100)
        else:
            progress = 0
        
        return jsonify({
            "status": "ok",
            "task_id": task_id,
            "filename": task_info['filename'],
            "total_size": task_info['total_size'],
            "current_size": task_info['current_size'],
            "progress": progress,
            "download_status": task_info['status'],
            "error": task_info.get('error')
        }), 200
    except Exception as e:
        app.logger.error(f"[进度API] 获取进度失败: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e), "progress": 0}), 500

# API路由

@app.route('/mpv/pause', methods=['GET'])
@log_operation("播放/暂停切换")
def pause_toggle():
    # 检查当前状态
    filename, filename_msg = get_mpv_property("filename")
    pause_state, pause_msg = get_mpv_property("pause")
    idle, idle_msg = get_mpv_property("idle-active")
    
    # 使用全局变量作为后备检查
    global current_playing_file
    
    # 改进播放状态判断：
    # 1. 检查filename是否有值
    # 2. 检查current_playing_file是否有值
    # 3. 检查idle状态，如果不是空闲状态，说明正在播放
    # 4. 检查path属性，作为filename的后备
    path, path_msg = get_mpv_property("path")
    has_path = path and path.strip()
    
    # 详细的调试日志
    operation_logger.debug(f"[播放控制] 原始状态: filename={repr(filename)}, filename_msg={filename_msg}")
    operation_logger.debug(f"[播放控制] 原始状态: pause_state={pause_state}, pause_msg={pause_msg}")
    operation_logger.debug(f"[播放控制] 原始状态: idle={idle}, idle_msg={idle_msg}")
    operation_logger.debug(f"[播放控制] 原始状态: path={repr(path)}, path_msg={path_msg}")
    operation_logger.debug(f"[播放控制] 原始状态: current_playing_file={repr(current_playing_file)}")
    
    # 只要满足以下条件之一，就认为有播放文件：
    # 1. filename有值
    # 2. path有值
    # 3. current_playing_file有值
    # 4. 不是空闲状态（idle为False）
    has_playing_file = False
    
    # 条件1：filename有值
    if filename and isinstance(filename, str) and filename.strip():
        has_playing_file = True
        operation_logger.debug(f"[播放控制] 条件1满足：filename有值")
    
    # 条件2：path有值
    if not has_playing_file and path and isinstance(path, str) and path.strip():
        has_playing_file = True
        operation_logger.debug(f"[播放控制] 条件2满足：path有值")
    
    # 条件3：current_playing_file有值
    if not has_playing_file and current_playing_file and isinstance(current_playing_file, str) and current_playing_file.strip():
        has_playing_file = True
        operation_logger.debug(f"[播放控制] 条件3满足：current_playing_file有值")
    
    # 条件4：不是空闲状态
    if not has_playing_file and idle is False:
        has_playing_file = True
        operation_logger.debug(f"[播放控制] 条件4满足：不是空闲状态")
    
    operation_logger.debug(f"[播放控制] 最终has_playing_file={has_playing_file}")
    
    # 核心逻辑：
    # 1. 如果没有播放文件，直接播放下一首
    # 2. 如果有播放文件，切换播放/暂停状态
    if not has_playing_file:
        # 情况1：没有播放文件，直接播放下一首
        operation_logger.info("[播放控制] 没有播放文件，触发播放下一首")
        # 发送遮罩提醒
        send_mask_reminder("没有播放文件，触发播放下一首", "play_next")
        return next_track()
    else:
        # 情况2：有播放文件，切换播放/暂停状态
        operation_logger.info("[播放控制] 有播放文件，切换播放/暂停状态")
        # 发送遮罩提醒
        new_state = "暂停" if pause_state else "播放"
        send_mask_reminder(f"切换到{new_state}状态", "pause_toggle")
        success, message = send_mpv_command(["cycle", "pause"])
        if success:
            # 获取当前播放文件信息
            current_file_info = filename or os.path.basename(path) if path else current_playing_file or "未知文件"
            # 记录到时间轴
            add_to_timeline(
                "pause_toggle", 
                "播放/暂停切换", 
                {"current_file": current_file_info, "pause_state": not pause_state}
            )
            # 更新自己记录的状态
            global self_recorded_state
            self_recorded_state["paused"] = not pause_state
            self_recorded_state["playing"] = not self_recorded_state["paused"]  # playing状态应该是paused的反义词
            app.logger.debug(f"[播放控制] 自己记录的状态已更新: {json.dumps(self_recorded_state, ensure_ascii=False)}")
            return jsonify({"status": "ok", "action": "pause_toggle", "new_pause_state": not pause_state}), 200
        else:
            # 如果发送命令失败，返回错误信息
            operation_logger.warning(f"[播放控制] 发送暂停命令失败: {message}")
            send_mask_reminder(f"切换播放/暂停状态失败: {message}", "pause_toggle_error")
            return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/next', methods=['GET'])
@log_operation("下一首")
def next_track():
    try:
        global current_playing_file, next_playing_file, self_recorded_state
        
        # 发送遮罩提醒
        send_mask_reminder("正在切换到下一首歌曲", "next_track")
        
        # 获取当前播放的文件名 - 优先使用自己记录的状态
        current_file = self_recorded_state["current_file"]
        
        # 如果自己记录的状态中没有文件名，尝试从MPV获取
        if not current_file:
            current_file, _ = get_mpv_property("filename")
            
            # 如果获取filename失败，尝试从path属性获取
            if not current_file:
                path, _ = get_mpv_property("path")
                if path:
                    current_file = os.path.basename(path)
                    
            # 如果MPV返回空且我们有全局记录，使用全局记录
            if not current_file and current_playing_file:
                current_file = current_playing_file
                app.logger.info(f"MPV当前无文件，使用全局记录的文件计算下一首: {current_file}")
        
        # 获取NAS上的所有音频文件列表
        all_files, message = rclone_list_files()
        if not all_files:
            # 如果NAS获取失败，使用本地文件
            all_files = get_audio_files()
        
        if not all_files:
            # 发送遮罩提醒
            send_mask_reminder("没有找到音频文件", "next_track_error")
            return jsonify({"status": "error", "message": "No audio files found"}), 500
        
        # 找到下一首歌曲
        next_file = None
        if current_file and current_file in all_files:
            # 如果当前文件在列表中，获取下一首
            current_index = all_files.index(current_file)
            next_index = (current_index + 1) % len(all_files)
            next_file = all_files[next_index]
        else:
            # 如果当前文件不在列表中或无法获取当前文件，随机选择一首
            import random
            next_file = random.choice(all_files)
        
        # 生成任务ID用于进度跟踪
        import uuid
        task_id = str(uuid.uuid4())
        
        # 从缓存或NAS获取文件
        success, local_path, message, returned_task_id = get_file_from_cache_or_nas(next_file, task_id)
        
        if not success:
            # 发送遮罩提醒
            send_mask_reminder(f"获取文件失败: {message}", "next_track_error")
            return jsonify({"status": "error", "message": f"Failed to get file: {message}"}), 500
        
        # 更新全局变量
        old_file = current_playing_file
        current_playing_file = next_file
        next_playing_file = next_file
        
        # 更新自己记录的状态
        self_recorded_state["playing"] = True
        self_recorded_state["paused"] = False
        self_recorded_state["current_file"] = next_file
        
        # 播放下一首歌曲
        success, message = send_mpv_command(["loadfile", local_path, "replace"])
        if success:
            # 记录到时间轴
            add_to_timeline(
                "next_track", 
                f"切换到下一首: {next_file}", 
                {
                    "previous_file": old_file or current_file or "未知文件", 
                    "next_file": next_file,
                    "source": "cache" if "exists in cache" in message else "NAS",
                    "task_id": returned_task_id
                }
            )
            return jsonify({
                "status": "ok", 
                "action": "next_track",
                "next_file": next_file,
                "source": "cache" if "exists in cache" in message else "NAS",
                "local_path": local_path,
                "task_id": returned_task_id  # 返回任务ID供前端轮询进度
            }), 200
        
        # 如果loadfile失败，回退到重启MPV的方式
        app.logger.warning("loadfile命令失败，回退到重启MPV的方式")
        
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
                "--idle=yes",  # 保持mpv运行状态
                "--force-window=no",  # 不强制创建窗口
                "--really-quiet",  # 减少输出噪音
                local_path
            ])
            
            return jsonify({
                "status": "ok", 
                "action": "next_track",
                "next_file": next_file,
                "source": "cache" if "exists in cache" in message else "NAS",
                "local_path": local_path,
                "method": "restart",
                "task_id": returned_task_id
            }), 200
        except Exception as e:
        # 发送遮罩提醒
            send_mask_reminder(f"播放文件失败: {str(e)}", "play_file_error")
            return jsonify({"status": "error", "message": f"Failed to play file: {str(e)}"}), 500
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/mpv/prev', methods=['GET'])
@log_operation("上一首")
def prev_track():
    try:
        global current_playing_file, next_playing_file
        
        # 发送遮罩提醒
        send_mask_reminder("正在切换到上一首歌曲", "prev_track")
        
        # 获取当前播放的文件名
        current_file, _ = get_mpv_property("filename")
        
        # 如果获取filename失败，尝试从path属性获取
        if not current_file:
            path, _ = get_mpv_property("path")
            if path:
                current_file = os.path.basename(path)
                
        # 如果MPV返回空且我们有全局记录，使用全局记录
        if not current_file and current_playing_file:
            current_file = current_playing_file
            app.logger.info(f"MPV当前无文件，使用全局记录的文件计算上一首: {current_file}")
        
        # 获取NAS上的所有音频文件列表
        all_files, message = rclone_list_files()
        if not all_files:
            # 如果NAS获取失败，使用本地文件
            all_files = get_audio_files()
        
        if not all_files:
            # 发送遮罩提醒
            send_mask_reminder("没有找到音频文件", "prev_track_error")
            return jsonify({"status": "error", "message": "No audio files found"}), 500
        
        # 找到上一首歌曲
        prev_file = None
        if current_file and current_file in all_files:
            # 如果当前文件在列表中，获取上一首
            current_index = all_files.index(current_file)
            prev_index = (current_index - 1) % len(all_files)
            prev_file = all_files[prev_index]
        else:
            # 如果当前文件不在列表中或无法获取当前文件，随机选择一首
            import random
            prev_file = random.choice(all_files)
        
        # 从缓存或NAS获取文件
        success, local_path, message, _ = get_file_from_cache_or_nas(prev_file)
        
        if not success:
            # 发送遮罩提醒
            send_mask_reminder(f"获取文件失败: {message}", "prev_track_error")
            return jsonify({"status": "error", "message": f"Failed to get file: {message}"}), 500
        
        # 更新全局变量
        old_file = current_playing_file
        next_playing_file = prev_file
        current_playing_file = prev_file
        
        # 更新自己记录的状态
        global self_recorded_state
        self_recorded_state["playing"] = True
        self_recorded_state["paused"] = False
        self_recorded_state["current_file"] = prev_file
        
        # 播放上一首歌曲
        success, message = send_mpv_command(["loadfile", local_path, "replace"])
        if success:
            # 发送遮罩提醒
            send_mask_reminder(f"成功切换到上一首歌曲: {prev_file}", "prev_track_success")
            
            # 记录到时间轴
            add_to_timeline(
                "prev_track", 
                f"切换到上一首: {prev_file}", 
                {
                    "previous_file": old_file or current_file or "未知文件", 
                    "prev_file": prev_file,
                    "source": "cache" if "exists in cache" in message else "NAS"
                }
            )
            return jsonify({
                "status": "ok", 
                "action": "prev_track",
                "prev_file": prev_file,
                "source": "cache" if "exists in cache" in message else "NAS",
                "local_path": local_path
            }), 200
        
        # 如果loadfile失败，回退到重启MPV的方式
        app.logger.warning("loadfile命令失败，回退到重启MPV的方式")
        
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
                "--idle=yes",  # 保持mpv运行状态
                "--force-window=no",  # 不强制创建窗口
                "--really-quiet",  # 减少输出噪音
                local_path
            ])
            
            # 发送遮罩提醒
            send_mask_reminder(f"成功切换到上一首歌曲: {prev_file} (重启MPV方式)", "prev_track_success")
            
            return jsonify({
                "status": "ok", 
                "action": "prev_track",
                "prev_file": prev_file,
                "source": "cache" if "exists in cache" in message else "NAS",
                "local_path": local_path,
                "method": "restart"
            }), 200
        except Exception as e:
            # 发送遮罩提醒
            send_mask_reminder(f"切换到上一首歌曲失败: {str(e)}", "prev_track_error")
            return jsonify({"status": "error", "message": f"Failed to play file: {str(e)}"}), 500
    
    except Exception as e:
        # 发送遮罩提醒
        send_mask_reminder(f"切换到上一首歌曲失败: {str(e)}", "prev_track_error")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/mpv/stop', methods=['GET'])
@log_operation("停止播放")
def stop_playback():
    global current_playing_file
    
    # 获取当前播放文件信息
    file_info = current_playing_file or "未知文件"
    
    # 发送遮罩提醒
    send_mask_reminder(f"正在停止播放: {file_info}", "stop_playback")
    
    success, message = send_mpv_command(["quit"])
    if success:
        # 发送遮罩提醒
        send_mask_reminder(f"成功停止播放: {file_info}", "stop_playback_success")
        
        # 记录到时间轴
        add_to_timeline(
            "stop", 
            "停止播放", 
            {"stopped_file": file_info}
        )
        
        # 重置当前播放文件
        current_playing_file = ""
        
        # 更新自己记录的状态
        global self_recorded_state
        self_recorded_state["playing"] = False
        self_recorded_state["paused"] = True
        self_recorded_state["current_file"] = ""
        
        return jsonify({"status": "ok", "action": "stop"}), 200
    # 发送遮罩提醒
    send_mask_reminder(f"停止播放失败: {message}", "stop_playback_error")
    return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/volume', methods=['GET'])
@log_operation("调整音量")
def adjust_volume():
    try:
        value = int(request.args.get('value', 0))
    except ValueError:
        return jsonify({"status": "error", "message": "Query parameter 'value' must be an integer."}), 400
    
    # 发送遮罩提醒
    send_mask_reminder(f"正在调整音量: {'增加' if value > 0 else '减少'} {abs(value)}%")
    
    success, message = send_mpv_command(["add", "volume", str(value)])
    
    if success:
        # 更新自己记录的状态
        global self_recorded_state
        # 获取当前音量并更新
        current_volume, _ = get_mpv_property("volume")
        if current_volume is not None:
            self_recorded_state["volume"] = current_volume
            # 发送遮罩提醒
            send_mask_reminder(f"音量调整成功，当前音量: {current_volume}%")
        return jsonify({"status": "ok", "action": "adjust_volume", "change": value}), 200
    # 发送遮罩提醒
    send_mask_reminder(f"音量调整失败: {message}", "volume_error")
    return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/volume/set', methods=['GET'])
@log_operation("设置音量")
def set_volume():
    try:
        value = int(request.args.get('value', 50))
        value = max(0, min(100, value))  # 限制在0-100之间
    except ValueError:
        return jsonify({"status": "error", "message": "Query parameter 'value' must be an integer between 0 and 100."}), 400
    
    # 发送遮罩提醒
    send_mask_reminder(f"正在设置音量为: {value}%")
    
    success, message = send_mpv_command(["set", "volume", str(value)])
    
    if success:
        # 更新自己记录的状态
        global self_recorded_state
        self_recorded_state["volume"] = value
        # 发送遮罩提醒
        send_mask_reminder(f"音量设置成功，当前音量: {value}%")
        return jsonify({"status": "ok", "action": "set_volume", "volume": value}), 200
    # 发送遮罩提醒
    send_mask_reminder(f"音量设置失败: {message}", "volume_error")
    return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/shuffle', methods=['GET'])
@log_operation("随机播放")
def shuffle_playlist():
    """随机播放"""
    # 发送遮罩提醒
    send_mask_reminder("正在随机打乱播放列表", "shuffle_playlist")
    
    # 获取当前播放列表
    playlist, msg = get_mpv_property("playlist")
    if playlist is None:
        # 发送遮罩提醒
        send_mask_reminder("获取播放列表失败", "shuffle_error")
        return jsonify({"status": "error", "message": "Failed to get playlist"}), 500
    
    # 随机打乱播放列表
    success, message = send_mpv_command(["playlist-shuffle"])
    if success:
        # 发送遮罩提醒
        send_mask_reminder("播放列表随机打乱成功", "shuffle_success")
        return jsonify({"status": "ok", "action": "shuffle_playlist"}), 200
    # 发送遮罩提醒
    send_mask_reminder(f"播放列表随机打乱失败: {message}", "shuffle_error")
    return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/play/<int:index>', methods=['GET'])
@log_operation("播放指定歌曲")
def play_track(index):
    """播放指定索引的歌曲"""
    # 发送遮罩提醒
    send_mask_reminder(f"正在播放播放列表中索引为 {index} 的歌曲", "play_track")
    
    success, message = send_mpv_command(["playlist-play-index", str(index)])
    if success:
        # 发送遮罩提醒
        send_mask_reminder(f"成功播放播放列表中索引为 {index} 的歌曲", "play_track_success")
        return jsonify({"status": "ok", "action": "play_track", "index": index}), 200
    # 发送遮罩提醒
    send_mask_reminder(f"播放播放列表中索引为 {index} 的歌曲失败: {message}", "play_track_error")
    return jsonify({"status": "error", "message": message}), 500

@app.route('/mpv/seek', methods=['GET'])
@log_operation("调整播放进度")
def seek():
    """调整播放进度"""
    try:
        position = request.args.get('position')
        if not position:
            return jsonify({"status": "error", "message": "Missing position parameter"}), 400
        
        # 转换position为浮点数
        position_float = float(position)
        
        # 发送遮罩提醒
        send_mask_reminder(f"正在调整播放进度到 {position} 秒", "seek")
            
        # 发送seek命令
        success, message = send_mpv_command(["seek", position, "absolute"])
    
        if success:
            # 发送遮罩提醒
            send_mask_reminder(f"播放进度调整成功，当前位置: {position} 秒", "seek_success")
            
            # 更新自己记录的状态，确保进度条停留在拖动到的位置
            global self_recorded_state
            
            # 获取当前时长，用于计算进度
            duration, _ = get_mpv_property("duration")
            current_duration = duration if duration is not None else self_recorded_state["duration"]
            
            # 计算进度
            if current_duration > 0:
                current_progress = (position_float / current_duration) * 100 if position_float else 0
                current_progress = round(current_progress, 3)
            else:
                current_progress = 0
            
            # 更新自己记录的状态
            self_recorded_state["position"] = position_float
            self_recorded_state["progress"] = current_progress
            self_recorded_state["last_update_time"] = time.time()  # 更新最后更新时间
            
            return jsonify({"status": "ok", "action": "seek", "position": position, "progress": current_progress}), 200
        else:
            # 发送遮罩提醒
            send_mask_reminder(f"播放进度调整失败: {message}", "seek_error")
            return jsonify({"status": "error", "message": message}), 500
    except Exception as e:
        # 发送遮罩提醒
        send_mask_reminder(f"播放进度调整失败: {str(e)}", "seek_error")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/mpv/play/file/<path:filename>', methods=['GET'])
@log_operation("播放指定文件")
def play_file(filename):
    """播放指定文件（按需从NAS拉取）"""
    # 声明全局变量
    global current_playing_file, self_recorded_state
    
    # 发送遮罩提醒
    send_mask_reminder(f"正在准备播放文件: {filename}", "play_file")
    
    # 从缓存或NAS获取文件
    success, local_path, message, _ = get_file_from_cache_or_nas(filename)
    
    if not success:
        # 发送遮罩提醒
        send_mask_reminder(f"获取文件失败: {message}", "play_file_error")
        return jsonify({"status": "error", "message": f"Failed to get file: {message}"}), 500
    
    # 发送遮罩提醒
    send_mask_reminder(f"文件获取成功，正在播放: {filename}", "play_file_start")
    
    # 首先尝试将文件添加到播放列表并播放
    success, message = send_mpv_command(["loadfile", local_path, "replace"])
    if success:
        # 立即更新全局当前播放文件和自己记录的状态
        current_playing_file = filename
        
        # 更新自己记录的状态
        self_recorded_state["playing"] = True
        self_recorded_state["paused"] = False
        self_recorded_state["current_file"] = filename
        
        # 发送遮罩提醒
        send_mask_reminder(f"成功播放文件: {filename}", "play_file_success")
        
        return jsonify({
            "status": "ok", 
            "action": "play_file", 
            "file": filename,
            "local_path": local_path,
            "source": "NAS" if "copied from NAS" in message else "cache",
            "method": "loadfile"
        }), 200
    
    # 如果loadfile失败，回退到重启MPV的方式
    app.logger.warning("loadfile命令失败，回退到重启MPV的方式")
    
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
            "--idle=yes",  # 保持mpv运行状态
            "--force-window=no",  # 不强制创建窗口
            "--really-quiet",  # 减少输出噪音
            local_path
        ])
        
        # 更新自己记录的状态
        self_recorded_state["playing"] = True
        self_recorded_state["paused"] = False
        self_recorded_state["current_file"] = filename
        
        # 发送遮罩提醒
        send_mask_reminder(f"成功播放文件: {filename} (重启MPV方式)", "play_file_success")
        
        return jsonify({
            "status": "ok", 
            "action": "play_file", 
            "file": filename,
            "local_path": local_path,
            "source": "NAS" if "copied from NAS" in message else "cache",
            "method": "restart"
        }), 200
    except Exception as e:
        return jsonify({"status": "error", "message": f"Failed to play file: {str(e)}"}), 500

@app.route('/mpv/build_playlist', methods=['POST'])
@log_operation("构建播放列表")
def build_playlist():
    """构建完整播放列表"""
    try:
        # 发送遮罩提醒
        send_mask_reminder("正在构建播放列表", "build_playlist")
        
        # 获取所有音频文件
        all_files, message = rclone_list_files()
        if not all_files:
            # 如果NAS获取失败，使用本地文件
            all_files = get_audio_files()
        
        if not all_files:
            # 发送遮罩提醒
            send_mask_reminder("没有找到音频文件", "build_playlist_error")
            return jsonify({"status": "error", "message": "No audio files found"}), 500
        
        # 清空当前播放列表
        send_mpv_command(["playlist-clear"])
        time.sleep(0.1)
        
        # 逐个添加文件到播放列表
        files_added = 0
        for filename in all_files:
            success, local_path, message, _ = get_file_from_cache_or_nas(filename)
            if success:
                success, msg = send_mpv_command(["loadfile", local_path, "append"])
                if success:
                    files_added += 1
                    app.logger.info(f"Added to playlist: {filename}")
                else:
                    app.logger.warning(f"Failed to add to playlist: {filename}, error: {msg}")
        
        # 发送遮罩提醒
        send_mask_reminder(f"播放列表构建成功，共添加了 {files_added} 个文件，总文件数: {len(all_files)}", "build_playlist_success")
        
        return jsonify({
            "status": "ok", 
            "action": "build_playlist", 
            "total_files": len(all_files),
            "files_added": files_added
        }), 200
        
    except Exception as e:
        # 发送遮罩提醒
        send_mask_reminder(f"播放列表构建失败: {str(e)}", "build_playlist_error")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/mpv/status', methods=['GET'])
@log_operation("获取播放状态")
def get_status():
    """获取播放状态"""
    status = {}
    global current_playing_file, self_recorded_state
    
    app.logger.debug("[状态获取] 开始获取MPV播放状态")
    
    try:
        # 获取MPV状态作为补充
        # 获取播放状态
        app.logger.debug("[状态获取] 尝试获取pause属性")
        pause_state, pause_msg = get_mpv_property("pause")
        app.logger.debug(f"[状态获取] 获取pause属性结果: {pause_state}, 消息: {pause_msg}")
        
        # 获取 idle-active 状态 (是否空闲)
        idle_active, _ = get_mpv_property("idle-active")
        
        # 获取 eof-reached 状态 (是否播放结束)
        eof_reached, _ = get_mpv_property("eof-reached")
        
        # 更新自己记录的播放状态
        if pause_state is not None:
            self_recorded_state["paused"] = pause_state
            self_recorded_state["playing"] = not pause_state
        
        # 优先使用自己记录的状态
        status.update(self_recorded_state)
        
        # 添加额外的状态信息
        status["idle_active"] = idle_active if idle_active is not None else False
        status["eof_reached"] = eof_reached if eof_reached is not None else False
        
        # 获取当前播放文件 - 尝试多种属性
        app.logger.debug("[状态获取] 尝试获取filename属性")
        filename, filename_msg = get_mpv_property("filename")
        app.logger.debug(f"[状态获取] 获取filename属性结果: {filename}, 消息: {filename_msg}")
        
        # 确保filename是字符串类型
        if filename is None:
            filename = ""
            app.logger.debug("[状态获取] filename为None，设置为空字符串")
        
        # 如果MPV返回了文件名，更新自己记录的状态
        if filename and filename.strip():
            self_recorded_state["current_file"] = filename
        
        # 如果MPV没返回文件名，尝试使用全局变量
        if not filename and current_playing_file:
            filename = current_playing_file
            app.logger.debug(f"[状态获取] MPV未返回文件名，使用全局变量: {filename}")

        if not filename:  # 如果filename为空，尝试获取path属性
            app.logger.debug("[状态获取] filename为空，尝试获取path属性")
            path, path_msg = get_mpv_property("path")
            app.logger.debug(f"[状态获取] 获取path属性结果: {path}, 消息: {path_msg}")
            if path:
                # 从路径中提取文件名
                filename = os.path.basename(path)
                app.logger.debug(f"[状态获取] 从path提取文件名: {filename}")
                # 更新自己记录的状态
                self_recorded_state["current_file"] = filename
        
        # 如果还是没有，尝试media-title
        if not filename:
            app.logger.debug("[状态获取] filename仍为空，尝试获取media-title属性")
            media_title, media_msg = get_mpv_property("media-title")
            app.logger.debug(f"[状态获取] 获取media-title属性结果: {media_title}, 消息: {media_msg}")
            if media_title:
                filename = media_title
                app.logger.debug(f"[状态获取] 使用media-title作为文件名: {filename}")
                # 更新自己记录的状态
                self_recorded_state["current_file"] = filename
        
        # 确保最终返回的文件名是字符串类型
        filename = filename if isinstance(filename, str) else ""
        status["current_file"] = filename
        app.logger.debug(f"[状态获取] 最终current_file值: {status['current_file']}, 类型: {type(status['current_file']).__name__}")
        
        # 更新全局当前播放文件并记录时间轴
        if filename and filename != current_playing_file:
            old_file = current_playing_file
            current_playing_file = filename
            add_to_timeline(
                "play", 
                f"开始播放: {filename}", 
                {"previous_file": old_file, "current_file": filename}
            )
            app.logger.info(f"[时间轴] 播放文件变更: 从 '{old_file}' 到 '{filename}'")
        
        # 获取音量
        app.logger.debug("[状态获取] 尝试获取volume属性")
        volume, volume_msg = get_mpv_property("volume")
        app.logger.debug(f"[状态获取] 获取volume属性结果: {volume}, 消息: {volume_msg}")
        if volume is not None:
            status["volume"] = volume
            # 更新自己记录的音量
            self_recorded_state["volume"] = volume
        
        # 获取播放列表
        app.logger.debug("[状态获取] 尝试获取playlist属性")
        playlist, playlist_msg = get_mpv_property("playlist")
        app.logger.debug(f"[状态获取] 获取playlist属性结果: 类型={type(playlist).__name__}, 长度={len(playlist) if isinstance(playlist, list) else 'N/A'}")
        status["playlist"] = playlist if playlist is not None else []
        
        # 获取播放位置和持续时间，增强可靠性
        app.logger.debug("[状态获取] 尝试获取time-pos属性")
        
        # 重试获取time-pos属性
        max_time_pos_retries = 3
        time_pos_retry_count = 0
        position = None
        position_msg = ""
        
        while time_pos_retry_count < max_time_pos_retries and (position is None or position == 0):
            position, position_msg = get_mpv_property("time-pos")
            app.logger.debug(f"[状态获取] 获取time-pos属性结果: {position}, 消息: {position_msg}")
            
            if position is not None and position > 0:
                break
            
            time_pos_retry_count += 1
            time.sleep(0.1)  # 短暂等待后重试
        
        # 如果MPV无法返回有效位置，使用自己记录的位置
        if position is None or position <= 0:
            app.logger.debug("[状态获取] MPV无法返回有效位置，使用自己记录的位置")
            position = self_recorded_state["position"]
        
        # 尝试获取duration属性，增加重试机制
        max_retries = 5
        retry_count = 0
        duration = None
        duration_msg = ""
        
        while retry_count < max_retries and (duration is None or duration == 0):
            app.logger.debug(f"[状态获取] 尝试获取duration属性 (重试 {retry_count+1}/{max_retries})")
            duration, duration_msg = get_mpv_property("duration")
            app.logger.debug(f"[状态获取] 获取duration属性结果: {duration}, 消息: {duration_msg}")
            
            if duration is not None and duration > 0:
                break
            
            retry_count += 1
            time.sleep(0.1)  # 短暂等待后重试
        
        # 如果MPV无法返回有效时长，尝试使用自己记录的时长
        if duration is None or duration <= 0:
            app.logger.debug("[状态获取] MPV无法返回有效时长，使用自己记录的时长")
            duration = self_recorded_state["duration"]
        
        # 如果自己记录的时长也无效，尝试使用文件路径获取时长
        if duration is None or duration <= 0:
            app.logger.debug("[状态获取] 自己记录的时长也无效，尝试使用文件路径获取")
            
            # 尝试获取当前播放文件的本地路径
            try:
                # 获取path属性
                path, path_msg = get_mpv_property("path")
                file_path = None
                
                if path and isinstance(path, str) and path.strip():
                    app.logger.debug(f"[状态获取] 获取到path属性: {path}")
                    file_path = path
                else:
                    # 如果path属性获取失败，尝试从filename构建本地路径
                    filename = status.get("current_file", "")
                    if filename:
                        # 构建本地缓存路径
                        local_path = os.path.join(LOCAL_DIR, filename)
                        app.logger.debug(f"[状态获取] 尝试使用本地缓存路径: {local_path}")
                        file_path = local_path
                
                # 获取多种方式的时长信息
                if file_path and os.path.exists(file_path):
                    # 使用ffprobe获取时长
                    ffprobe_duration = 0
                    try:
                        import subprocess
                        cmd = [
                            'ffprobe',
                            '-v', 'error',
                            '-show_entries', 'format=duration',
                            '-of', 'default=noprint_wrappers=1:nokey=1',
                            file_path
                        ]
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                        if result.returncode == 0 and result.stdout.strip():
                            ffprobe_duration = float(result.stdout.strip())
                            app.logger.debug(f"[状态获取] 使用ffprobe获取到时长: {ffprobe_duration}秒")
                    except Exception as e:
                        app.logger.debug(f"[状态获取] 使用ffprobe获取时长失败: {e}")
                    
                    # 使用ffmpeg获取时长
                    ffmpeg_duration = 0
                    try:
                        cmd = [
                            'ffmpeg',
                            '-i', file_path,
                            '-v', 'error',
                            '-f', 'null',
                            '-'
                        ]
                        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                        if result.stderr.strip():
                            # 从ffmpeg的错误输出中提取时长
                            import re
                            duration_match = re.search(r"Duration: (\d+):(\d+):(\d+)\.(\d+)", result.stderr)
                            if duration_match:
                                hours = int(duration_match.group(1))
                                minutes = int(duration_match.group(2))
                                seconds = int(duration_match.group(3))
                                milliseconds = int(duration_match.group(4)) / 100
                                ffmpeg_duration = hours * 3600 + minutes * 60 + seconds + milliseconds
                                app.logger.debug(f"[状态获取] 使用ffmpeg获取到时长: {ffmpeg_duration}秒")
                    except Exception as e:
                        app.logger.debug(f"[状态获取] 使用ffmpeg获取时长失败: {e}")
                    
                    # 使用mutagen获取时长
                    mutagen_duration = 0
                    try:
                        import mutagen
                        audio = mutagen.File(file_path)
                        if audio and hasattr(audio.info, 'length'):
                            mutagen_duration = audio.info.length
                            app.logger.debug(f"[状态获取] 使用mutagen获取到时长: {mutagen_duration}秒")
                    except Exception as e:
                        app.logger.debug(f"[状态获取] 使用mutagen获取时长失败: {e}")
                    
                    # 选择最佳时长
                    file_duration = 0
                    if ffprobe_duration > 0:
                        file_duration = ffprobe_duration
                    elif ffmpeg_duration > 0:
                        file_duration = ffmpeg_duration
                    elif mutagen_duration > 0:
                        file_duration = mutagen_duration
                    
                    if file_duration > 0:
                        duration = file_duration
                        app.logger.debug(f"[状态获取] 使用文件路径获取到时长: {duration}秒")
                    
                    # 添加所有方式的时长信息到状态
                    status["duration_info"] = {
                        "ffprobe": ffprobe_duration,
                        "ffmpeg": ffmpeg_duration,
                        "mutagen": mutagen_duration,
                        "file_path": file_path
                    }
            except Exception as e:
                app.logger.debug(f"[状态获取] 使用文件路径获取时长失败: {e}")
        
        # 添加进度相关信息到返回状态
        # 优先使用MPV返回的position，但如果MPV返回的position为0且自己记录的position大于0，则使用自己记录的position
        if position is not None and position > 0:
            current_position = position
        else:
            current_position = self_recorded_state["position"]
        
        current_duration = duration if duration is not None else self_recorded_state["duration"]
        
        # 计算播放进度百分比
        if current_duration and current_duration > 0:
            current_progress = (current_position / current_duration) * 100 if current_position else 0
            current_progress = round(current_progress, 2)
            app.logger.debug(f"[状态获取] 计算播放进度: {current_progress}%")
        else:
            # 如果无法计算进度，重置位置和进度
            current_position = 0
            current_progress = 0
            app.logger.debug(f"[状态获取] 无法计算进度，重置位置和进度")
        
        # 确保进度在合理范围内
        current_progress = max(0, min(100, current_progress))
        
        # 更新自己记录的进度状态
        self_recorded_state["position"] = current_position
        self_recorded_state["duration"] = current_duration
        self_recorded_state["progress"] = current_progress
        
        # 添加MPV获取的时长信息
        status["mpv_duration"] = duration
        
        # 确保duration_info字段存在并包含所有方式的时长信息
        if "duration_info" not in status:
            status["duration_info"] = {
                "ffprobe": 0,
                "ffmpeg": 0,
                "mutagen": 0,
                "file_path": None
            }
        
        # 尝试获取当前播放文件的本地路径，用于获取多种方式的时长信息
        try:
            # 获取path属性
            path, path_msg = get_mpv_property("path")
            file_path = None
            
            if path and isinstance(path, str) and path.strip():
                file_path = path
            else:
                # 如果path属性获取失败，尝试从filename构建本地路径
                filename = status.get("current_file", "")
                if filename:
                    # 构建本地缓存路径
                    local_path = os.path.join(LOCAL_DIR, filename)
                    file_path = local_path
            
            # 获取多种方式的时长信息
            if file_path and os.path.exists(file_path):
                # 使用ffprobe获取时长
                ffprobe_duration = 0
                try:
                    import subprocess
                    cmd = [
                        'ffprobe',
                        '-v', 'error',
                        '-show_entries', 'format=duration',
                        '-of', 'default=noprint_wrappers=1:nokey=1',
                        file_path
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if result.returncode == 0 and result.stdout.strip():
                        ffprobe_duration = float(result.stdout.strip())
                        app.logger.debug(f"[状态获取] 使用ffprobe获取到时长: {ffprobe_duration}秒")
                except Exception as e:
                    app.logger.debug(f"[状态获取] 使用ffprobe获取时长失败: {e}")
                
                # 使用ffmpeg获取时长
                ffmpeg_duration = 0
                try:
                    cmd = [
                        'ffmpeg',
                        '-i', file_path,
                        '-v', 'error',
                        '-f', 'null',
                        '-'
                    ]
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                    if result.stderr.strip():
                        # 从ffmpeg的错误输出中提取时长
                        import re
                        duration_match = re.search(r"Duration: (\d+):(\d+):(\d+)\.(\d+)", result.stderr)
                        if duration_match:
                            hours = int(duration_match.group(1))
                            minutes = int(duration_match.group(2))
                            seconds = int(duration_match.group(3))
                            milliseconds = int(duration_match.group(4)) / 100
                            ffmpeg_duration = hours * 3600 + minutes * 60 + seconds + milliseconds
                            app.logger.debug(f"[状态获取] 使用ffmpeg获取到时长: {ffmpeg_duration}秒")
                except Exception as e:
                    app.logger.debug(f"[状态获取] 使用ffmpeg获取时长失败: {e}")
                
                # 使用mutagen获取时长
                mutagen_duration = 0
                try:
                    import mutagen
                    audio = mutagen.File(file_path)
                    if audio and hasattr(audio.info, 'length'):
                        mutagen_duration = audio.info.length
                        app.logger.debug(f"[状态获取] 使用mutagen获取到时长: {mutagen_duration}秒")
                except Exception as e:
                    app.logger.debug(f"[状态获取] 使用mutagen获取时长失败: {e}")
                
                # 更新duration_info字段
                status["duration_info"] = {
                    "ffprobe": ffprobe_duration,
                    "ffmpeg": ffmpeg_duration,
                    "mutagen": mutagen_duration,
                    "file_path": file_path
                }
        except Exception as e:
            app.logger.debug(f"[状态获取] 获取多种方式的时长信息失败: {e}")
        
        # 添加进度相关信息到返回状态
        status["position"] = current_position
        status["duration"] = current_duration
        status["progress"] = current_progress
        
        # 添加自己记录的状态作为备用
        status["self_recorded_position"] = self_recorded_state["position"]
        status["self_recorded_duration"] = self_recorded_state["duration"]
        status["self_recorded_progress"] = self_recorded_state["progress"]
        
        # 添加遮罩提醒信息
        global current_mask_reminder
        if current_mask_reminder:
            # 检查提醒是否过期
            if time.time() > current_mask_reminder['expires_at']:
                current_mask_reminder = None
            else:
                status["mask_reminder"] = current_mask_reminder
        else:
            status["mask_reminder"] = None
        
        status["mpv_ready"] = os.path.exists(MPV_SOCKET_PATH)
        status["mpv_error"] = MPV_RUNTIME_ERROR or ""
        app.logger.debug(f"[状态获取] 完整状态数据: {json.dumps(status, ensure_ascii=False)}")
        app.logger.debug(f"[状态获取] 自己记录的状态: {json.dumps(self_recorded_state, ensure_ascii=False)}")
        return jsonify(status), 200
    except Exception as e:
        app.logger.error(f"[状态获取] 获取状态时发生异常: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"获取状态失败: {str(e)}", "error_type": type(e).__name__}), 500


@app.route('/mpv/status/self', methods=['GET'])
@log_operation("获取自己记录的状态")
def get_self_recorded_status():
    """获取自己记录的播放状态"""
    global self_recorded_state
    app.logger.debug(f"[状态获取] 获取自己记录的状态: {self_recorded_state}")
    return jsonify(self_recorded_state), 200



@app.route('/files', methods=['GET'])
@log_operation("列出文件列表")
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
@log_operation("搜索文件")
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
    # 只允许同步单个文件，禁止同步所有文件
    try:
        # 发送遮罩提醒
        send_mask_reminder("正在手动同步文件", "sync_files")
        
        data = request.get_json() or {}
        filename = data.get('filename')
        
        if not filename:
            operation_logger.warning("[SYNC] 尝试同步所有文件，但已被禁止")
            # 发送遮罩提醒
            send_mask_reminder("尝试同步所有文件，但已被禁止", "sync_files_error")
            return jsonify({"status": "error", "message": "Syncing all files is not allowed"}), 403
        
        operation_logger.debug(f"[SYNC] 请求同步单个文件: {filename}")
        # 发送遮罩提醒
        send_mask_reminder(f"正在同步文件: {filename}", "sync_file")
        
        success, message = rclone_sync(filename=filename)
            
        if success:
            # 发送遮罩提醒
            send_mask_reminder(f"文件同步成功: {message}", "sync_file_success")
            return jsonify({"status": "ok", "message": "Sync completed successfully"}), 200
        # 发送遮罩提醒
        send_mask_reminder(f"文件同步失败: {message}", "sync_file_error")
        return jsonify({"status": "error", "message": message}), 500
    except Exception as e:
        operation_logger.error(f"[SYNC] 同步文件时出错: {str(e)}", exc_info=True)
        # 发送遮罩提醒
        send_mask_reminder(f"同步文件时出错: {str(e)}", "sync_files_error")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/files/cache', methods=['POST'])
@log_operation("缓存指定文件")
def cache_file():
    """缓存指定的单个文件"""
    try:
        # 发送遮罩提醒
        send_mask_reminder("正在缓存指定文件", "cache_file")
        
        data = request.get_json() or {}
        filename = data.get('filename')
        
        if not filename:
            # 发送遮罩提醒
            send_mask_reminder("缺少文件名参数", "cache_file_error")
            return jsonify({"status": "error", "message": "Filename is required"}), 400
            
        operation_logger.debug(f"[CACHE] 请求缓存文件: {filename}")
        # 发送遮罩提醒
        send_mask_reminder(f"正在缓存文件: {filename}", "cache_file_start")
        
        success, message = rclone_sync(filename=filename)
        
        if success:
            # 发送遮罩提醒
            send_mask_reminder(f"文件缓存成功: {filename}", "cache_file_success")
            return jsonify({"status": "ok", "message": f"File '{filename}' cached successfully"}), 200
        # 发送遮罩提醒
        send_mask_reminder(f"文件缓存失败: {message}", "cache_file_error")
        return jsonify({"status": "error", "message": message}), 500
    except Exception as e:
        operation_logger.error(f"[CACHE] 缓存文件时出错: {str(e)}", exc_info=True)
        # 发送遮罩提醒
        send_mask_reminder(f"缓存文件时出错: {str(e)}", "cache_file_error")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/logs', methods=['GET'])
@log_operation("获取操作日志")
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
        # 发送遮罩提醒
        send_mask_reminder("正在清空操作日志", "clear_logs")
        
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
            
            # 发送遮罩提醒
            send_mask_reminder("日志已清空", "clear_logs_success")
            
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
            
            # 发送遮罩提醒
            send_mask_reminder("日志文件已创建并清空", "clear_logs_success")
            
            return jsonify({"message": "日志文件已创建并清空"}), 200
    except Exception as e:
        # 记录错误到控制台
        print(f"清空日志时发生错误: {e}")
        
        # 发送遮罩提醒
        send_mask_reminder(f"清空日志时发生错误: {str(e)}", "clear_logs_error")
        
        return jsonify({"error": str(e)}), 500

@app.route('/mcp/control', methods=['POST'])
@log_operation("MCP接口控制")
def mcp_control():
    """
    提供MCP能力接口供小智AI使用
    
    请求格式:
    {
        "action": "play|pause|next|prev|stop|volume",
        "params": {
            "value": 音量值 (仅volume操作需要)
        }
    }
    
    返回格式:
    {
        "status": "ok|error",
        "message": "操作结果描述",
        "data": {
            "action": "执行的操作",
            "current_status": {
                "playing": true|false,
                "filename": "当前播放文件名",
                "volume": 音量值
            }
        }
    }
    """
    try:
        # 发送遮罩提醒
        send_mask_reminder("正在处理MCP控制请求", "mcp_control")
        
        data = request.json
        if not data or "action" not in data:
            # 发送遮罩提醒
            send_mask_reminder("MCP请求缺少必要的action字段", "mcp_control_error")
            return jsonify({
                "status": "error",
                "message": "Missing required field 'action'",
                "data": {}
            }), 400
        
        action = data["action"]
        params = data.get("params", {})
        
        # 发送遮罩提醒
        send_mask_reminder(f"正在执行MCP操作: {action}", f"mcp_{action}")
        
        # 执行相应的操作
        if action == "play":
            # 获取当前状态，如果已暂停则取消暂停，否则检查是否有正在播放的文件
            paused, _ = get_mpv_property("pause")
            if paused:
                # 如果当前是暂停状态，取消暂停
                success, message = send_mpv_command(["set_property", "pause", "no"])
                # 发送遮罩提醒
                send_mask_reminder("MCP播放操作：取消暂停", "mcp_play_resume")
            else:
                # 检查是否有正在播放的文件
                filename, _ = get_mpv_property("filename")
                if not filename:
                    # 如果没有正在播放的文件，尝试播放下一首
                    # 发送遮罩提醒
                    send_mask_reminder("MCP播放操作：没有正在播放的文件，尝试播放下一首", "mcp_play_next")
                    next_track_result = next_track()
                    return next_track_result
                success, message = True, "Already playing"
                # 发送遮罩提醒
                send_mask_reminder("MCP播放操作：已经在播放中", "mcp_play_already")
                
        elif action == "pause":
            success, message = send_mpv_command(["set_property", "pause", "yes"])
            # 发送遮罩提醒
            send_mask_reminder("MCP暂停操作：已暂停播放", "mcp_pause")
            
        elif action == "next":
            # 发送遮罩提醒
            send_mask_reminder("MCP下一首操作：正在切换到下一首", "mcp_next")
            return next_track()
            
        elif action == "prev":
            # 发送遮罩提醒
            send_mask_reminder("MCP上一首操作：正在切换到上一首", "mcp_prev")
            return prev_track()
            
        elif action == "stop":
            success, message = send_mpv_command(["quit"])
            # 发送遮罩提醒
            send_mask_reminder("MCP停止操作：已停止播放", "mcp_stop")
            
        elif action == "volume":
            value = params.get("value", 0)
            try:
                value = int(value)
                success, message = send_mpv_command(["add", "volume", str(value)])
                # 发送遮罩提醒
                send_mask_reminder(f"MCP音量调整：{'增加' if value > 0 else '减少'} {abs(value)}%", "mcp_volume")
            except (ValueError, TypeError):
                # 发送遮罩提醒
                send_mask_reminder("MCP音量调整：音量值必须是整数", "mcp_volume_error")
                return jsonify({
                    "status": "error",
                    "message": "Volume value must be an integer",
                    "data": {}
                }), 400
                
        else:
            # 发送遮罩提醒
            send_mask_reminder(f"MCP操作：未知的操作类型: {action}", "mcp_unknown_action")
            return jsonify({
                "status": "error",
                "message": f"Unknown action: {action}",
                "data": {}
            }), 400
        
        # 获取当前状态信息
        current_status = {}
        paused, _ = get_mpv_property("pause")
        current_status["playing"] = not paused if paused is not None else False
        
        filename, _ = get_mpv_property("filename")
        if not filename:
            path, _ = get_mpv_property("path")
            if path:
                filename = os.path.basename(path)
        current_status["filename"] = filename or "No file playing"
        
        volume, _ = get_mpv_property("volume")
        current_status["volume"] = float(volume) if volume is not None else 100.0
        
        if success:
            # 发送遮罩提醒
            send_mask_reminder(f"MCP操作 '{action}' 执行成功", f"mcp_{action}_success")
            return jsonify({
                "status": "ok",
                "message": f"Action '{action}' executed successfully",
                "data": {
                    "action": action,
                    "current_status": current_status
                }
            }), 200
        else:
            # 发送遮罩提醒
            send_mask_reminder(f"MCP操作 '{action}' 执行失败: {message}", f"mcp_{action}_error")
            return jsonify({
                "status": "error",
                "message": f"Failed to execute action: {message}",
                "data": {
                    "action": action,
                    "current_status": current_status
                }
            }), 500
            
    except Exception as e:
        # 发送遮罩提醒
        send_mask_reminder(f"MCP控制请求处理出错: {str(e)}", "mcp_control_error")
        return jsonify({
            "status": "error",
            "message": f"Internal server error: {str(e)}",
            "data": {}
        }), 500

@app.route('/cache/info', methods=['GET'])
@log_operation("获取缓存信息")
def cache_info():
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
        # 发送遮罩提醒
        send_mask_reminder("正在清理缓存", "clear_cache")
        
        if not os.path.exists(LOCAL_DIR):
            # 发送遮罩提醒
            send_mask_reminder("缓存目录不存在", "clear_cache_info")
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
        
        # 发送遮罩提醒
        send_mask_reminder(f"缓存已清理，删除了 {removed_count} 个文件，释放了 {round(removed_size / (1024 * 1024), 2)} MB 空间", "clear_cache_success")
        
        return jsonify({
            "status": "ok",
            "message": f"缓存已清理，删除了 {removed_count} 个文件，释放了 {round(removed_size / (1024 * 1024), 2)} MB 空间",
            "removed_count": removed_count,
            "removed_size_mb": round(removed_size / (1024 * 1024), 2)
        }), 200
    except Exception as e:
        # 发送遮罩提醒
        send_mask_reminder(f"清理缓存失败: {str(e)}", "clear_cache_error")
        return jsonify({"error": str(e)}), 500

@app.route('/', methods=['GET'])
@log_operation("访问网页控制面板")
def web_control_panel():
    """网页控制面板"""
    return render_template('index.html')

def start_playback_monitor():
    """启动播放结束监控线程"""
    global playback_monitor_thread, playback_monitor_running
    
    if not playback_monitor_running:
        playback_monitor_running = True
        playback_monitor_thread = threading.Thread(target=playback_monitor_worker, daemon=True)
        playback_monitor_thread.start()
        app.logger.info("[PLAYBACK_MONITOR] 播放结束监控服务已启动")
    
    return True, "播放结束监控服务已启动"


def stop_playback_monitor():
    """停止播放结束监控线程"""
    global playback_monitor_thread, playback_monitor_running
    
    if playback_monitor_running:
        playback_monitor_running = False
        if playback_monitor_thread:
            playback_monitor_thread.join(timeout=5)  # 等待线程结束，最多5秒
        app.logger.info("[PLAYBACK_MONITOR] 播放结束监控服务已停止")
    
    return True, "播放结束监控服务已停止"


@app.route('/monitor/playback', methods=['POST'])
@log_operation("控制播放监控")
def control_playback_monitor():
    """控制播放结束监控服务的启动和停止"""
    try:
        # 发送遮罩提醒
        send_mask_reminder("正在处理播放监控控制请求", "control_playback_monitor")
        
        action = request.args.get('action', '').lower()
        
        if action == 'start':
            # 发送遮罩提醒
            send_mask_reminder("正在启动播放结束监控服务", "playback_monitor_start")
            
            success, message = start_playback_monitor()
            
            # 发送遮罩提醒
            send_mask_reminder("播放结束监控服务已启动", "playback_monitor_start_success")
            
            return jsonify({"status": "ok", "message": message}), 200
        elif action == 'stop':
            # 发送遮罩提醒
            send_mask_reminder("正在停止播放结束监控服务", "playback_monitor_stop")
            
            success, message = stop_playback_monitor()
            
            # 发送遮罩提醒
            send_mask_reminder("播放结束监控服务已停止", "playback_monitor_stop_success")
            
            return jsonify({"status": "ok", "message": message}), 200
        elif action == 'status':
            # 获取状态信息
            status_msg = "播放结束监控服务正在运行" if playback_monitor_running else "播放结束监控服务未运行"
            
            # 发送遮罩提醒
            send_mask_reminder(status_msg, "playback_monitor_status")
            
            return jsonify({
                "status": "ok",
                "running": playback_monitor_running,
                "thread_alive": playback_monitor_thread.is_alive() if playback_monitor_thread else False
            }), 200
        else:
            # 发送遮罩提醒
            send_mask_reminder("无效的操作，支持的操作: start, stop, status", "playback_monitor_error")
            
            return jsonify({"status": "error", "message": "无效的操作，支持的操作: start, stop, status"}), 400
            
    except Exception as e:
        # 发送遮罩提醒
        send_mask_reminder(f"控制播放监控服务时出错: {str(e)}", "playback_monitor_error")
        
        app.logger.error(f"[PLAYBACK_MONITOR] 控制播放监控服务时出错: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500


# 遮罩提醒处理机制
mask_reminder_queue = []
mask_reminder_last_sent = 0
mask_reminder_cooldown = 0.5  # 遮罩提醒冷却时间（秒）
mask_reminder_lock = threading.Lock()
current_mask_reminder = None  # 当前遮罩提醒信息，用于前端获取

def send_mask_reminder(message, action_type="general"):
    """发送遮罩提醒
    
    Args:
        message: 提醒消息内容
        action_type: 动作类型，用于分类和过滤
    
    处理逻辑：
    1. 为了避免多个遮罩同时出现或紧跟出现，添加冷却机制
    2. 短时间内的多个提醒会被合并处理
    3. 冷却时间内的提醒会被记录但不会立即发送
    """
    global mask_reminder_queue, mask_reminder_last_sent, mask_reminder_cooldown, mask_reminder_lock, current_mask_reminder
    
    try:
        with mask_reminder_lock:
            current_time = time.time()
            time_since_last_sent = current_time - mask_reminder_last_sent
            
            # 如果距离上次发送提醒的时间小于冷却时间，将提醒加入队列
            if time_since_last_sent < mask_reminder_cooldown:
                # 检查队列中是否已有相同类型的提醒，如果有则更新，否则添加
                existing_index = next((i for i, item in enumerate(mask_reminder_queue) if item['type'] == action_type), -1)
                if existing_index >= 0:
                    # 更新现有提醒
                    mask_reminder_queue[existing_index] = {
                        'message': message,
                        'type': action_type,
                        'timestamp': current_time
                    }
                else:
                    # 添加新提醒到队列
                    mask_reminder_queue.append({
                        'message': message,
                        'type': action_type,
                        'timestamp': current_time
                    })
                
                app.logger.info(f"[MASK_REMINDER_QUEUED] [{action_type}] {message} (冷却中，已加入队列)")
                return True, "提醒已加入队列，将在冷却后发送"
            
            # 要发送的提醒列表
            reminders_to_send = []
            
            # 如果队列中有等待的提醒，先处理队列中的提醒
            if mask_reminder_queue:
                # 优先处理最新的提醒
                latest_reminder = mask_reminder_queue.pop()
                reminders_to_send.append(latest_reminder)
            
            # 添加当前提醒
            reminders_to_send.append({
                'message': message,
                'type': action_type,
                'timestamp': current_time
            })
            
            # 发送所有提醒
            for reminder in reminders_to_send:
                # 记录并发送提醒
                app.logger.info(f"[MASK_REMINDER] [{reminder['type']}] {reminder['message']}")
                
                # 更新当前遮罩提醒，用于前端获取
                current_mask_reminder = {
                    'message': reminder['message'],
                    'type': reminder['type'],
                    'timestamp': reminder['timestamp'],
                    'expires_at': reminder['timestamp'] + 3  # 提醒3秒后自动过期
                }
                
                mask_reminder_last_sent = current_time
        
        # 这里可以添加实际的遮罩提醒逻辑
        # 例如：发送API请求、触发通知、更新UI等
        # 目前仅记录日志，可根据需要扩展
        
        # 示例：发送HTTP请求到前端
        # import requests
        # requests.post('http://localhost:3000/api/reminder', json={'message': message, 'type': action_type})
        
        return True, "提醒发送成功"
    except Exception as e:
        app.logger.error(f"[MASK_REMINDER] 发送提醒失败: {str(e)}", exc_info=True)
        return False, f"提醒发送失败: {str(e)}"

def auto_play():
    """自动播放函数，在应用启动后延迟执行"""
    import time
    # 延迟1秒执行，确保应用程序完全初始化
    time.sleep(1)
    app.logger.info("[AUTO_PLAY] 开始自动播放")
    # 发送遮罩提醒
    send_mask_reminder("应用启动，开始自动播放", "auto_play")
    try:
        # 调用next_track函数开始播放
        response = next_track()
        app.logger.info(f"[AUTO_PLAY] 自动播放完成，响应: {response}")
    except Exception as e:
        app.logger.error(f"[AUTO_PLAY] 自动播放失败: {str(e)}", exc_info=True)

if __name__ == '__main__':
    # 注意：0.0.0.0 允许从外部设备访问
    import os
    import threading
    
    # 启动播放结束监控线程
    start_playback_monitor()
    
    # 启动自动播放线程
    auto_play_thread = threading.Thread(target=auto_play, daemon=True)
    auto_play_thread.start()
    app.logger.info("[AUTO_PLAY] 自动播放线程已启动")
    
    API_PORT = int(os.environ.get('API_PORT', 5000))
    print(f"🚀 启动API服务，绑定到 0.0.0.0:{API_PORT}")
    app.run(host='0.0.0.0', port=API_PORT, debug=False, threaded=True)
