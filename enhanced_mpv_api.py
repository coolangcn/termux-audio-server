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
    "progress": 0,     # 播放进度百分比
    "last_update_time": 0 # 最后更新时间
}
timeline_lock = threading.RLock()  # 用于线程安全
state_lock = threading.RLock()     # 用于播放状态的线程安全

# 计时线程控制变量
timer_thread_running = False  # 计时线程是否正在运行
timer_thread = None  # 计时线程对象

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
        
        import subprocess
        
        # 方法1: 尝试使用ffprobe获取format时长
        try:
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-show_entries', 'format=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                output = result.stdout.strip()
                if output and output != "N/A":
                    try:
                        duration = float(output)
                        operation_logger.debug(f"[文件时长] 使用ffprobe(format)获取到时长: {duration}秒")
                        return duration
                    except ValueError:
                        pass
        except Exception as e:
            operation_logger.debug(f"[文件时长] ffprobe(format)尝试失败: {e}")

        # 方法2: 尝试使用ffprobe获取流(stream)时长
        try:
            cmd = [
                'ffprobe',
                '-v', 'error',
                '-select_streams', 'a:0',
                '-show_entries', 'stream=duration',
                '-of', 'default=noprint_wrappers=1:nokey=1',
                file_path
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                output = result.stdout.strip()
                if output and output != "N/A":
                    try:
                        duration = float(output)
                        operation_logger.debug(f"[文件时长] 使用ffprobe(stream)获取到时长: {duration}秒")
                        return duration
                    except ValueError:
                        pass
        except Exception as e:
            operation_logger.debug(f"[文件时长] ffprobe(stream)尝试失败: {e}")

        # 方法3: 尝试从ffmpeg输出中解析时长
        try:
            cmd = ['ffmpeg', '-i', file_path]
            # ffmpeg -i 总是返回非0，因为它没有输出文件，错误输出在stderr
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            output = result.stderr
            import re
            # 寻找 "Duration: 00:00:00.00" 格式
            match = re.search(r"Duration: (\d{2}):(\d{2}):(\d{2}\.\d+)", output)
            if match:
                hours, minutes, seconds = map(float, match.groups())
                duration = hours * 3600 + minutes * 60 + seconds
                operation_logger.debug(f"[文件时长] 使用ffmpeg解析获取到时长: {duration}秒")
                return duration
        except Exception as e:
            operation_logger.debug(f"[文件时长] ffmpeg解析尝试失败: {e}")
            
        operation_logger.warning(f"[文件时长] 所有方法均无法获取文件时长: {file_path}")
        return 0
    except Exception as e:
        operation_logger.error(f"[文件时长] 获取文件时长发生未预期异常: {e}", exc_info=True)
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


def fade_in(duration=3.0, target_volume=100):
    """音量淡入效果
    
    Args:
        duration: 淡入持续时间（秒），默认3秒
        target_volume: 目标音量（0-100），默认100
    """
    try:
        app.logger.info(f"[FADE_IN] 开始淡入效果，持续时间: {duration}秒，目标音量: {target_volume}")
        
        # 设置初始音量为0
        send_mpv_command(["set", "volume", "0"])
        
        # 计算步进参数
        steps = 30  # 总步数
        step_duration = duration / steps  # 每步的时间间隔
        volume_step = target_volume / steps  # 每步的音量增量
        
        # 逐步增加音量
        for i in range(steps + 1):
            current_volume = int(volume_step * i)
            send_mpv_command(["set", "volume", str(current_volume)])
            
            # 更新自己记录的状态
            global self_recorded_state
            self_recorded_state["volume"] = current_volume
            
            if i < steps:
                time.sleep(step_duration)
        
        app.logger.info(f"[FADE_IN] 淡入效果完成，当前音量: {target_volume}")
    except Exception as e:
        app.logger.error(f"[FADE_IN] 淡入效果失败: {str(e)}", exc_info=True)


def fade_out(duration=2.0):
    """音量淡出效果
    
    Args:
        duration: 淡出持续时间（秒），默认2秒
    """
    try:
        # 获取当前音量
        current_volume, _ = get_mpv_property("volume")
        if current_volume is None:
            current_volume = 100
        
        app.logger.info(f"[FADE_OUT] 开始淡出效果，持续时间: {duration}秒，起始音量: {current_volume}")
        
        # 计算步进参数
        steps = 20  # 总步数
        step_duration = duration / steps  # 每步的时间间隔
        volume_step = current_volume / steps  # 每步的音量减量
        
        # 逐步降低音量
        for i in range(steps + 1):
            new_volume = int(current_volume - (volume_step * i))
            send_mpv_command(["set", "volume", str(new_volume)])
            
            # 更新自己记录的状态
            global self_recorded_state
            self_recorded_state["volume"] = new_volume
            
            if i < steps:
                time.sleep(step_duration)
        
        app.logger.info(f"[FADE_OUT] 淡出效果完成，当前音量: 0")
    except Exception as e:
        app.logger.error(f"[FADE_OUT] 淡出效果失败: {str(e)}", exc_info=True)


def timer_worker():
    """精确计时线程，每100毫秒更新一次播放位置"""
    global timer_thread_running, self_recorded_state
    app.logger.info("[TIMER_WORKER] 精确计时线程已启动")
    
    # 计时精度（秒）
    timer_precision = 0.1  # 100毫秒
    last_time = time.time()
    
    while timer_thread_running:
        try:
            current_time = time.time()
            # 计算两次循环之间的时间差
            delta = current_time - last_time
            last_time = current_time
            
            # 防止delta过大（例如线程暂停过久）
            if delta > 1.0:
                delta = 1.0
            
            # 检查播放状态
            with state_lock:
                is_playing = self_recorded_state["playing"]
                is_paused = self_recorded_state["paused"]
                current_position = self_recorded_state["position"]
                current_duration = self_recorded_state["duration"]
                
                # 只有当正在播放且未暂停时，才更新播放位置
                if is_playing and not is_paused:
                    # 增加播放位置（基于实际流逝的时间）
                    new_position = current_position + delta
                    
                    # 检查是否达到文件时长
                    if current_duration > 0 and new_position >= current_duration:
                        # 达到文件时长，不再增加，也不重置，等待监控线程处理切换
                        new_position = current_duration
                        
                        # 更新播放状态
                        self_recorded_state["position"] = new_position
                        self_recorded_state["progress"] = 100.0
                    else:
                        # 更新播放位置
                        self_recorded_state["position"] = new_position
                        
                        # 计算并更新播放进度百分比
                        if current_duration > 0:
                            new_progress = (new_position / current_duration) * 100
                            self_recorded_state["progress"] = round(new_progress, 3)
            
            # 等待100毫秒
            time.sleep(timer_precision)
        except Exception as e:
            app.logger.error(f"[TIMER_WORKER] 计时线程出错: {str(e)}", exc_info=True)
            # 出错后继续执行，避免线程退出
            time.sleep(timer_precision)
            # 更新时间，避免出错后delta过大
            last_time = time.time()
    
    app.logger.info("[TIMER_WORKER] 精确计时线程已停止")


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
                # --- 主动同步MPV状态到缓存 ---
                # 批量获取关键属性，减少socket连接次数
                
                # 1. 播放状态
                paused, error_msg = get_mpv_property("pause")
                
                # 2. 更新状态
                with state_lock:
                    # 只有当pause属性获取成功且状态发生变化时，才更新状态
                    # 避免在get_mpv_property返回默认值False时错误更新状态
                    if paused is not None and error_msg == "Success" and paused != self_recorded_state["paused"]:
                        self_recorded_state["paused"] = paused
                        self_recorded_state["playing"] = not paused
                
                # 2. 音量
                volume, _ = get_mpv_property("volume")
                if volume is not None:
                    with state_lock:
                        self_recorded_state["volume"] = volume
                
                # 3. 文件名和路径
                filename_mpv, _ = get_mpv_property("filename") 
                if filename_mpv:
                     # 确保filename是字符串
                    filename_mpv = str(filename_mpv)
                    if filename_mpv != self_recorded_state["current_file"]:
                         with state_lock:
                            self_recorded_state["current_file"] = filename_mpv
                            
                         # 更新全局变量
                         current_playing_file = filename_mpv
                         if filename_mpv != last_status['playing_file']:
                             app.logger.info(f"[PLAYBACK_MONITOR] 播放文件变更(MPV Sync): {last_status['playing_file']} -> {filename_mpv}")
                             last_status['playing_file'] = filename_mpv
                             last_status['progress'] = 0
                             last_status['time_pos'] = 0
                             last_status['time_pos_stable_count'] = 0
                             last_status['reminder_sent'] = False
                             
                             # 记录到时间轴
                             add_to_timeline("play", f"开始播放: {filename_mpv}", {"current_file": filename_mpv})

                # 4. 时长 check
                if 'check_count' not in last_status:
                    last_status['check_count'] = 0
                last_status['check_count'] += 1
                
                current_dur = self_recorded_state["duration"]
                if current_dur <= 0 or last_status['check_count'] % 20 == 0: # 每10秒
                    duration, _ = get_mpv_property("duration")
                    if duration and duration > 0:
                        with state_lock:
                            self_recorded_state["duration"] = float(duration)
                
                # 移除了进度百分比更新逻辑，因为现在由timer_worker函数负责更新播放位置和进度百分比

                # 5. 播放列表 (每10秒)
                if last_status['check_count'] % 20 == 0:
                    playlist, _ = get_mpv_property("playlist")
                    with state_lock:
                        self_recorded_state["playlist"] = playlist if playlist else []
                # ---------------------------

                # 获取 eof-reached 状态 (是否播放结束)
                eof_reached, _ = get_mpv_property("eof-reached")
                idle_active = False 
                
            except Exception as e:
                app.logger.debug(f"[PLAYBACK_MONITOR] 更新状态时出错: {str(e)}")
                # 继续执行，使用默认值
                eof_reached = False
                idle_active = False
                # 计时由专门的timer_worker线程处理，这里不需要更新位置
            
            # 获取自己记录的状态
            with state_lock:
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
                with state_lock:
                    self_recorded_state["progress"] = current_progress
                    self_recorded_state["position"] = current_position
                    self_recorded_state["last_update_time"] = time.time()  # 更新最后更新时间
                
                playback_ended = True
                if eof_reached:
                    end_reason = "eof-reached属性检测到播放结束"
                else:
                    end_reason = "idle-active属性检测到播放结束"
            
            # 检查静音检测
            try:
                # 获取音频过滤器元数据
                af_metadata, _ = get_mpv_property("af-metadata")
                if af_metadata and isinstance(af_metadata, dict):
                    # 检查是否有静音检测信息
                    # silencedetect output format: lavfi.silencedetect.silence_start
                    silence_start = af_metadata.get("lavfi.silencedetect.silence_start")
                    
                    if silence_start:
                        app.logger.info(f"[PLAYBACK_MONITOR] 检测到静音，开始时间: {silence_start}")
                        # 只要检测到静音，就认为播放结束（前提是已经播放了一段时间，比如超过5秒）
                        # 避免开始时的短暂静音导致误判
                        if current_position > 5:
                            playback_ended = True
                            end_reason = f"检测到静音结束 (start: {silence_start})"
                            
                            # 发送遮罩提醒
                            send_mask_reminder("检测到静音，切换下一首", "silence_skip")
            except Exception as e:
                app.logger.debug(f"[PLAYBACK_MONITOR] 检查静音状态失败: {e}")

            if not playback_ended and current_duration > 0:
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
                    with state_lock:
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
    # 使用全局变量
    global self_recorded_state, current_playing_file
    
    # 从自己记录的状态中获取当前状态，作为基准
    with state_lock:
        actual_paused = self_recorded_state["paused"]
        current_file = self_recorded_state["current_file"]
    
    # 尝试从MPV获取当前的暂停状态，如果获取成功则使用这个状态
    # 只有当获取成功时才使用MPV的状态，否则继续使用自己记录的状态
    mpv_paused, error_msg = get_mpv_property("pause")
    if mpv_paused is not None and error_msg == "Success":
        actual_paused = mpv_paused
    
    # 改进播放状态判断：
    # 1. 自己记录的状态中有文件名
    # 2. current_playing_file有值
    
    # 详细的调试日志
    operation_logger.debug(f"[播放控制] 自己记录的原始状态: {json.dumps(self_recorded_state, ensure_ascii=False)}")
    operation_logger.debug(f"[播放控制] current_playing_file: {repr(current_playing_file)}")
    
    # 只要满足以下条件之一，就认为有播放文件：
    # 1. 自己记录的状态中有文件名
    # 2. current_playing_file有值
    has_playing_file = False
    
    # 条件1：自己记录的状态中有文件名
    if current_file and current_file.strip():
        has_playing_file = True
        operation_logger.debug(f"[播放控制] 条件1满足：自己记录的状态中有文件名")
    
    # 条件2：current_playing_file有值
    if not has_playing_file and current_playing_file and current_playing_file.strip():
        has_playing_file = True
        operation_logger.debug(f"[播放控制] 条件2满足：current_playing_file有值")
    
    operation_logger.debug(f"[播放控制] 最终has_playing_file={has_playing_file}")
    
    # 核心逻辑：
    # 1. 总是切换播放/暂停状态，不管是否有播放文件
    # 2. 如果没有播放文件，切换状态后播放下一首
    operation_logger.info("[播放控制] 切换播放/暂停状态")
    # 发送遮罩提醒
    new_state = "播放" if actual_paused else "暂停"
    send_mask_reminder(f"切换到{new_state}状态", "pause_toggle")
    success, message = send_mpv_command(["cycle", "pause"])
    if success:
        # 获取当前播放文件信息
        current_file_info = current_file or current_playing_file or "未知文件"
        
        # 发送命令后，直接切换我们自己记录的状态
        # 不再依赖于从MPV获取的状态，因为get_mpv_property函数在遇到错误时会返回默认值False
        # 而我们已经成功发送了暂停命令，所以可以确定状态已经切换
        with state_lock:
            # 切换暂停状态
            self_recorded_state["paused"] = not self_recorded_state["paused"]
            self_recorded_state["playing"] = not self_recorded_state["paused"]  # playing状态应该是paused的反义词
            
            # 获取切换后的状态
            after_pause = self_recorded_state["paused"]
        
        # 记录到时间轴
        add_to_timeline(
            "pause_toggle", 
            "播放/暂停切换", 
            {"current_file": current_file_info, "pause_state": after_pause}
        )
        app.logger.debug(f"[播放控制] 自己记录的状态已更新: {json.dumps(self_recorded_state, ensure_ascii=False)}")
        
        # 如果没有播放文件，播放下一首
        if not has_playing_file:
            # 情况1：没有播放文件，触发播放下一首
            operation_logger.info("[播放控制] 没有播放文件，触发播放下一首")
            # 发送遮罩提醒
            send_mask_reminder("没有播放文件，触发播放下一首", "play_next")
            return next_track()
        
        # 重新获取最新的paused状态，确保返回正确的状态
        with state_lock:
            new_pause_state = self_recorded_state["paused"]
        return jsonify({"status": "ok", "action": "pause_toggle", "new_pause_state": new_pause_state}), 200
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
        with state_lock:
            self_recorded_state["playing"] = True
            self_recorded_state["paused"] = False
            self_recorded_state["current_file"] = next_file
            self_recorded_state["position"] = 0
            self_recorded_state["progress"] = 0
            self_recorded_state["last_update_time"] = time.time()
        
        # 播放下一首歌曲
        success, message = send_mpv_command(["loadfile", local_path, "replace"])
        if success:
            # 确保播放状态 - 强制取消暂停
            # 为确保万无一失，发送两次解除暂停命令，一次使用字符串，一次使用布尔值(如果MPV支持)
            send_mpv_command(["set", "pause", "no"])
            time.sleep(0.1)
            send_mpv_command(["set", "pause", False])
            
            # double check: 再次确认状态，如果还是暂停则强制播放
            is_paused, _ = get_mpv_property("pause")
            if is_paused:
                app.logger.info("检测到仍处于暂停状态，再次强制解除暂停")
                send_mpv_command(["set", "pause", "no"])
            
            # 启动渐入效果线程
            fade_in_thread = threading.Thread(target=fade_in, args=(3.0,), daemon=True)
            fade_in_thread.start()
            
            # 获取并更新文件时长
            try:
                # 优先使用ffprobe获取准确时长
                duration = get_file_duration(local_path)
                if duration <= 0:
                    # 如果ffprobe失败，尝试从MPV获取
                    duration, _ = get_mpv_property("duration")
                    if duration is None:
                        duration = 0
                
                # 更新状态
                self_recorded_state["duration"] = float(duration)
                app.logger.info(f"已更新文件时长: {duration}秒")
            except Exception as e:
                app.logger.error(f"更新文件时长失败: {e}")
            
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
                "--pause=no",   # 强制不暂停
                "--idle=yes",  # 保持mpv运行状态
                "--force-window=no",  # 不强制创建窗口
                "--really-quiet",  # 减少输出噪音
                "--af=silencedetect=noise=-30dB:d=3.5", # 添加静音检测滤镜: -30dB, 3.5秒
                local_path
            ])
            
            # 启动渐入效果线程（延迟1秒，确保MPV已经启动）
            def delayed_fade_in():
                time.sleep(1.0)  # 等待MPV启动
                fade_in(3.0)
                
                # 在MPV启动后更新文件时长
                try:
                    # 优先使用ffprobe获取准确时长
                    duration = get_file_duration(local_path)
                    if duration <= 0:
                        # 如果ffprobe失败，尝试从MPV获取（可能需要重试几次）
                        for _ in range(3):
                            time.sleep(0.5)
                            duration, _ = get_mpv_property("duration")
                            if duration and duration > 0:
                                break
                        if duration is None:
                            duration = 0
                    
                    # 更新状态
                    self_recorded_state["duration"] = float(duration)
                    app.logger.info(f"已更新文件时长(重启模式): {duration}秒")
                except Exception as e:
                    app.logger.error(f"更新文件时长失败(重启模式): {e}")
            
            fade_in_thread = threading.Thread(target=delayed_fade_in, daemon=True)
            fade_in_thread.start()
            
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
            # 启动渐入效果线程
            fade_in_thread = threading.Thread(target=fade_in, args=(3.0,), daemon=True)
            fade_in_thread.start()
            
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
            
            # 启动渐入效果线程（延迟1秒，确保MPV已经启动）
            def delayed_fade_in():
                time.sleep(1.0)  # 等待MPV启动
                fade_in(3.0)
            
            fade_in_thread = threading.Thread(target=delayed_fade_in, daemon=True)
            fade_in_thread.start()
            
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
def fade_in(duration=3.0):
    """实现音量渐入效果
    
    Args:
        duration: 渐入时长（秒），默认3秒
    """
    try:
        # 先将音量设置为0
        send_mpv_command(["set", "volume", "0"])
        
        # 计算每步的音量增量和间隔时间
        steps = 30  # 分30步完成渐入
        step_duration = duration / steps
        volume_increment = 100 / steps
        
        # 逐渐增加音量
        for i in range(steps + 1):
            current_volume = int(i * volume_increment)
            send_mpv_command(["set", "volume", str(current_volume)])
            time.sleep(step_duration)
        
        app.logger.info(f"[FADE_IN] 音量渐入效果完成，时长: {duration}秒")
    except Exception as e:
        app.logger.error(f"[FADE_IN] 音量渐入效果失败: {str(e)}")


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
        
        # 启动渐入效果线程
        fade_in_thread = threading.Thread(target=fade_in, args=(3.0,), daemon=True)
        fade_in_thread.start()

        # 获取并更新文件时长
        try:
            # 优先使用ffprobe获取准确时长
            duration = get_file_duration(local_path)
            if duration <= 0:
                # 如果ffprobe失败，尝试从MPV获取
                duration, _ = get_mpv_property("duration")
                if duration is None:
                    duration = 0
            
            # 更新状态
            self_recorded_state["duration"] = float(duration)
            app.logger.info(f"已更新文件时长: {duration}秒")
        except Exception as e:
            app.logger.error(f"更新文件时长失败: {e}")
        
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
            "--af=silencedetect=noise=-30dB:d=2.5", # 添加静音检测滤镜: -30dB, 2.5秒
            local_path
        ])
        
        # 更新自己记录的状态
        self_recorded_state["playing"] = True
        self_recorded_state["paused"] = False
        self_recorded_state["current_file"] = filename
        
        # 启动渐入效果线程（延迟1秒，确保MPV已经启动）
        def delayed_fade_in():
            time.sleep(1.0)  # 等待MPV启动
            fade_in(3.0)
            
            # 在MPV启动后更新文件时长
            try:
                # 优先使用ffprobe获取准确时长
                duration = get_file_duration(local_path)
                if duration <= 0:
                    # 如果ffprobe失败，尝试从MPV获取（可能需要重试几次）
                    for _ in range(3):
                        time.sleep(0.5)
                        duration, _ = get_mpv_property("duration")
                        if duration and duration > 0:
                            break
                    if duration is None:
                        duration = 0
                
                # 更新状态
                self_recorded_state["duration"] = float(duration)
                app.logger.info(f"已更新文件时长(重启模式): {duration}秒")
            except Exception as e:
                app.logger.error(f"更新文件时长失败(重启模式): {e}")
        
        fade_in_thread = threading.Thread(target=delayed_fade_in, daemon=True)
        fade_in_thread.start()
        
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
    """获取播放状态 (优化版: 仅从缓存读取)"""
    status = {}
    
    # 完全依赖自己记录的状态
    with state_lock:
        status.update(self_recorded_state)
    
    # 额外状态信息
    eof_reached, _ = get_mpv_property("eof-reached") # 仅保留这个快速检查做校验，也可移除如果完全信任monitor
    status["eof_reached"] = eof_reached if eof_reached is not None else False
    status["idle_active"] = False
    
    # 计算进度
    if status.get("duration", 0) > 0 and status.get("position", 0) >= 0:
         # progress 已经在timer_worker中更新了，这里双重校验可选
         pass
    
    # 遮罩提醒
    global current_mask_reminder
    if current_mask_reminder:
        if time.time() > current_mask_reminder['expires_at']:
            current_mask_reminder = None
        else:
            status["mask_reminder"] = current_mask_reminder
    else:
        status["mask_reminder"] = None
    
    status["mpv_ready"] = os.path.exists(MPV_SOCKET_PATH)
    status["mpv_error"] = MPV_RUNTIME_ERROR or ""
    
    # 调试日志仅在确实需要时打印，避免刷屏
    # app.logger.debug(f"[状态获取] 快速返回: {json.dumps(status, ensure_ascii=False)}")
    
    return jsonify(status), 200


@app.route('/mpv/status/self', methods=['GET'])
@log_operation("获取自己记录的状态")
def get_self_recorded_status():
    """获取自己记录的播放状态"""
    global self_recorded_state
    # 使用state_lock保护状态读取，确保在多线程环境下状态的一致性
    with state_lock:
        status = self_recorded_state.copy()
    app.logger.debug(f"[状态获取] 获取自己记录的状态: {status}")
    return jsonify(status), 200



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

def tail_file(filename, n=100, block_size=4096):
    """读取文件最后n行"""
    try:
        if not os.path.exists(filename):
            return []
            
        with open(filename, 'rb') as f:
            f.seek(0, 2)
            file_size = f.tell()
            if file_size == 0:
                return []
            
            lines_to_find = n + 1
            block_end_byte = file_size
            blocks = []
            
            while block_end_byte > 0 and lines_to_find > 0:
                if block_end_byte - block_size > 0:
                    f.seek(block_end_byte - block_size)
                    data = f.read(block_size)
                else:
                    f.seek(0)
                    data = f.read(block_end_byte)
                
                lines_found = data.count(b'\n')
                lines_to_find -= lines_found
                blocks.append(data)
                block_end_byte -= block_size
            
            text = b''.join(reversed(blocks)).decode('utf-8', errors='replace')
            return text.splitlines()[-n:]
    except Exception as e:
        app.logger.error(f"Tail file error: {e}")
        return []

@app.route('/logs', methods=['GET'])
@log_operation("获取操作日志")
def get_logs():
    """获取操作日志"""
    try:
        log_file = f"{LOG_DIR}/operations.log"
        # 使用tail_file优化的读取方式
        logs = tail_file(log_file, 100)
        return jsonify({"logs": logs}), 200
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

def start_timer_thread():
    """启动精确计时线程"""
    global timer_thread, timer_thread_running
    
    if not timer_thread_running:
        timer_thread_running = True
        timer_thread = threading.Thread(target=timer_worker, daemon=True)
        timer_thread.start()
        app.logger.info("[TIMER_WORKER] 精确计时线程已启动")
    
    return True, "精确计时线程已启动"


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
    
    # 启动精确计时线程
    start_timer_thread()
    
    # 启动播放结束监控线程
    start_playback_monitor()
    
    # 启动自动播放线程
    auto_play_thread = threading.Thread(target=auto_play, daemon=True)
    auto_play_thread.start()
    app.logger.info("[AUTO_PLAY] 自动播放线程已启动")
    
    API_PORT = int(os.environ.get('API_PORT', 5000))
    print(f"🚀 启动API服务，绑定到 0.0.0.0:{API_PORT}")
    app.run(host='0.0.0.0', port=API_PORT, debug=False, threaded=True)
