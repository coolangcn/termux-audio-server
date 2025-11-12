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

# 配置控制台实时日志记录 - 设置为DEBUG级别以获取更详细信息
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

# 添加操作日志装饰器 - 增强版本，记录更多详细信息
def log_operation(operation):
    def decorator(f):
        def wrapper(*args, **kwargs):
            # 记录请求参数
            request_params = request.args.to_dict() if request else {}
            log_message = f"用户执行操作: {operation}"
            
            # 详细日志记录，包含请求参数和上下文信息
            detailed_log = f"{log_message}, 请求参数: {request_params}, 函数: {f.__name__}"
            operation_logger.debug(detailed_log)
            
            # 标准日志和实时输出
            operation_logger.info(log_message)
            print(f"[实时日志] {log_message}")
            
            try:
                # 执行原函数并记录执行结果
                result = f(*args, **kwargs)
                # 记录执行成功，但不记录完整响应体以避免过大日志
                operation_logger.debug(f"操作 '{operation}' 执行成功, 函数: {f.__name__}")
                return result
            except Exception as e:
                # 记录异常信息
                operation_logger.error(f"操作 '{operation}' 执行失败: {str(e)}, 函数: {f.__name__}", exc_info=True)
                raise
        wrapper.__name__ = f.__name__
        wrapper.__doc__ = f.__doc__
        return wrapper
    return decorator

def send_mpv_command(command):
    """使用 socat 向 mpv socket 发送命令"""
    operation_logger.debug(f"[MPV命令] 尝试发送命令: {command}")
    
    # 检查socket文件是否存在
    if not os.path.exists(MPV_SOCKET_PATH):
        error_msg = f"MPV Socket not found at {MPV_SOCKET_PATH}. Is MPV running?"
        operation_logger.error(f"[MPV命令] {error_msg}")
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
    cmd = f'echo \'{json_command}\' | socat -t 0 - UNIX-CONNECT:{MPV_SOCKET_PATH}'
    operation_logger.debug(f"[MPV命令] 执行的系统命令: {cmd}")
    
    try:
        result = os.system(cmd)
        operation_logger.debug(f"[MPV命令] 系统命令返回码: {result}")
        
        if result == 0:
            operation_logger.debug(f"[MPV命令] 命令 '{command}' 发送成功")
            return True, "Command sent successfully."
        else:
            error_msg = f"Failed to send command via socat, return code: {result}"
            operation_logger.error(f"[MPV命令] {error_msg}")
            return False, error_msg
    except Exception as e:
        error_msg = f"Exception when sending MPV command: {str(e)}"
        operation_logger.error(f"[MPV命令] {error_msg}", exc_info=True)
        return False, error_msg

def get_mpv_property(property_name):
    """获取MPV属性值"""
    operation_logger.debug(f"[MPV属性] 尝试获取属性: {property_name}")
    
    # 检查socket文件是否存在
    if not os.path.exists(MPV_SOCKET_PATH):
        error_msg = f"MPV Socket not found at {MPV_SOCKET_PATH}. Is MPV running?"
        operation_logger.error(f"[MPV属性] {error_msg}")
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
                        # 对于filename属性，如果出错则返回空字符串而不是None
                        if property_name == "filename":
                            operation_logger.debug(f"[MPV属性] filename属性出错，返回空字符串")
                            return "", "MPV error but returning empty string for filename"
                        return None, f"MPV error: {response['error']}"
                    else:
                        operation_logger.warning(f"[MPV属性] 响应中既没有data也没有error字段: {response}")
                        if property_name == "filename":
                            return "", "No data or error but returning empty string for filename"
                        return None, "Response contains neither data nor error"
                except json.JSONDecodeError:
                    operation_logger.error(f"[MPV属性] 解析MPV响应失败: {response_text}")
                    # 对于filename属性，解析失败时返回空字符串
                    if property_name == "filename":
                        return "", "Failed to parse but returning empty string for filename"
                    return None, "Failed to parse MPV response"
            else:
                operation_logger.warning(f"[MPV属性] 从MPV收到空响应，属性: {property_name}")
                # 对于filename属性，空响应时返回空字符串
                if property_name == "filename":
                    return "", "Empty response but returning empty string for filename"
                return None, "Empty response from MPV"
        else:
            operation_logger.warning(f"[MPV属性] 获取属性 {property_name} 失败, 返回码: {result.returncode}, 错误输出: {result.stderr}")
            # 对于filename属性，命令失败时返回空字符串
            if property_name == "filename":
                return "", "Command failed but returning empty string for filename"
            return None, f"Command failed with return code {result.returncode}"
    except subprocess.TimeoutExpired:
        operation_logger.error(f"[MPV属性] 获取MPV属性 {property_name} 超时")
        # 对于filename属性，超时时返回空字符串
        if property_name == "filename":
            return "", "Timeout but returning empty string for filename"
        return None, "Timeout getting MPV property"
    except Exception as e:
        operation_logger.error(f"[MPV属性] 获取MPV属性 {property_name} 异常: {str(e)}", exc_info=True)
        # 对于filename属性，异常时返回空字符串
        if property_name == "filename":
            return "", "Exception but returning empty string for filename"
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
    app.logger.debug("[RCLONE] 开始获取NAS文件列表")
    try:
        rclone_remote = "synology:download/bilibili/push"
        app.logger.debug(f"[RCLONE] 使用远程路径: {rclone_remote}")
        
        # 使用rclone lsjson获取文件列表
        cmd = f"rclone lsjson '{rclone_remote}' --include '*.mp4' --include '*.mp3' --include '*.flac' --include '*.ogg' --include '*.aac' --include '*.m4a' --include '*.wav' --include '*.webm'"
        app.logger.debug(f"[RCLONE] 执行命令: {cmd}")
        
        import subprocess
        start_time = time.time()
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        execution_time = time.time() - start_time
        
        app.logger.debug(f"[RCLONE] 命令执行完成，返回码: {result.returncode}，执行时间: {execution_time:.2f}秒")
        app.logger.debug(f"[RCLONE] 标准输出长度: {len(result.stdout)} 字符")
        app.logger.debug(f"[RCLONE] 错误输出长度: {len(result.stderr)} 字符")
        
        if result.stderr.strip():
            app.logger.warning(f"[RCLONE] 命令有错误输出: {result.stderr.strip()}")
        
        if result.returncode == 0:
            app.logger.debug("[RCLONE] 命令执行成功，开始解析JSON输出")
            try:
                files_data = json.loads(result.stdout)
                app.logger.debug(f"[RCLONE] JSON解析成功，获取到 {len(files_data)} 个项目")
                
                # 统计目录和文件数量
                dir_count = sum(1 for item in files_data if item.get('IsDir', False))
                file_count = len(files_data) - dir_count
                app.logger.debug(f"[RCLONE] 其中包含 {dir_count} 个目录和 {file_count} 个文件")
                
                # 只返回文件名列表
                file_list = [item['Path'] for item in files_data if not item.get('IsDir', False)]
                app.logger.debug(f"[RCLONE] 最终返回文件列表，长度: {len(file_list)}")
                app.logger.debug(f"[RCLONE] 文件列表示例: {file_list[:3] if len(file_list) > 0 else '空列表'}")
                return file_list, "Success"
            except json.JSONDecodeError as e:
                app.logger.error(f"[RCLONE] JSON解析失败: {str(e)}")
                app.logger.debug(f"[RCLONE] 原始输出前200字符: {result.stdout[:200]}")
                return [], f"Failed to parse rclone output: {str(e)}"
            except KeyError as e:
                app.logger.error(f"[RCLONE] 处理文件数据时缺少关键字段: {str(e)}")
                return [], f"Key error in rclone data: {str(e)}"
        else:
            app.logger.error(f"[RCLONE] 命令执行失败，返回码: {result.returncode}")
            error_msg = result.stderr.strip() or "No error message provided"
            app.logger.error(f"[RCLONE] 错误详情: {error_msg}")
            return [], f"rclone command failed (code {result.returncode}): {error_msg}"
    except Exception as e:
        app.logger.error(f"[RCLONE] 获取文件列表时发生异常: {str(e)}", exc_info=True)
        return [], f"Exception during rclone operation: {str(e)}"

def rclone_copy_file(remote_path, local_path):
    """从NAS复制单个文件到本地"""
    app.logger.info(f"[RCLONE] 开始复制文件: 远程={remote_path} -> 本地={local_path}")
    
    # 检查本地文件是否已存在
    if os.path.exists(local_path):
        app.logger.info(f"[RCLONE] 文件已存在于本地: {local_path}，跳过复制")
        return True, "File already exists locally"
    
    try:
        rclone_remote = "synology:download/bilibili/push"
        remote_file = f"{rclone_remote}/{remote_path}"
        app.logger.debug(f"[RCLONE] 构建远程文件路径: {remote_file}")
        
        # 确保本地目录存在
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        app.logger.debug(f"[RCLONE] 确保本地目录存在: {os.path.dirname(local_path)}")
        
        import subprocess
        cmd = f"rclone copyto '{remote_file}' '{local_path}'"
        app.logger.debug(f"[RCLONE] 执行命令: {cmd}")
        
        start_time = time.time()
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        execution_time = time.time() - start_time
        
        app.logger.debug(f"[RCLONE] 命令执行完成，返回码: {result.returncode}，执行时间: {execution_time:.2f}秒")
        
        if result.stderr.strip():
            app.logger.warning(f"[RCLONE] 命令有错误输出: {result.stderr.strip()}")
        
        if result.returncode == 0:
            # 验证文件是否真的被复制成功
            if os.path.exists(local_path):
                file_size = os.path.getsize(local_path)
                app.logger.info(f"[RCLONE] 文件复制成功: {remote_path} -> {local_path}, 文件大小: {file_size} 字节")
                return True, f"File copied successfully (size: {file_size} bytes)"
            else:
                app.logger.error(f"[RCLONE] 文件复制命令成功执行，但目标文件不存在: {local_path}")
                return False, "Command succeeded but file not found"
        else:
            error_msg = result.stderr.strip() or f"Command failed with exit code {result.returncode}"
            app.logger.error(f"[RCLONE] 文件复制失败: {remote_path}, 错误: {error_msg}")
            return False, error_msg
            
    except subprocess.SubprocessError as e:
        app.logger.error(f"[RCLONE] 执行复制命令时出错: {remote_path}, 错误: {str(e)}", exc_info=True)
        return False, f"Subprocess error: {str(e)}"
    except Exception as e:
        app.logger.error(f"[RCLONE] 复制文件时发生未预期错误: {remote_path}, 错误: {str(e)}", exc_info=True)
        return False, f"Unexpected error: {str(e)}"

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
    """自动缓存工作线程 - 只缓存下一首文件"""
    global auto_cache_running
    app.logger.info("[AUTO_CACHE] 自动缓存线程已启动 (只缓存下一首模式)")
    
    while auto_cache_running:
        try:
            # 获取当前播放的文件信息，以确定下一首需要缓存的文件
            current_file = None
            try:
                # 获取当前播放文件的名称
                current_filename = get_mpv_property("filename")
                if current_filename:
                    current_file = os.path.basename(current_filename)
                    app.logger.info(f"[AUTO_CACHE] 当前播放文件: {current_file}")
            except Exception as e:
                app.logger.warning(f"[AUTO_CACHE] 获取当前播放文件信息失败: {str(e)}")
            
            if current_file:
                # 获取NAS文件列表
                files, message = rclone_list_files()
                if files is not None and len(files) > 0:
                    # 排序文件列表，假设是按字母顺序或时间顺序
                    sorted_files = sorted(files)
                    
                    # 找到当前文件在列表中的位置
                    try:
                        current_index = sorted_files.index(current_file)
                        
                        # 确定下一首文件（循环播放）
                        if current_index < len(sorted_files) - 1:
                            next_file = sorted_files[current_index + 1]
                        else:
                            # 到列表末尾了，下一首是第一个文件
                            next_file = sorted_files[0]
                        
                        # 检查下一首文件是否已缓存
                        local_file_path = os.path.join(LOCAL_DIR, next_file)
                        if not os.path.exists(local_file_path):
                            app.logger.info(f"[AUTO_CACHE] 开始缓存下一首文件: {next_file}")
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

@app.route('/cache/auto', methods=['POST'])
@log_operation("控制自动缓存")
def control_auto_cache():
    """控制自动缓存服务的启动和停止"""
    global auto_cache_thread, auto_cache_running
    
    try:
        action = request.args.get('action', '').lower()
        
        if action == 'start':
            if not auto_cache_running:
                # 启动自动缓存线程
                app.logger.info("[AUTO_CACHE] 正在启动自动缓存服务")
                auto_cache_running = True
                auto_cache_thread = threading.Thread(target=auto_cache_worker, daemon=True)
                auto_cache_thread.start()
                return jsonify({"status": "ok", "message": "自动缓存服务已启动"}), 200
            else:
                return jsonify({"status": "ok", "message": "自动缓存服务已经在运行"}), 200
        
        elif action == 'stop':
            if auto_cache_running:
                app.logger.info("[AUTO_CACHE] 正在停止自动缓存服务")
                auto_cache_running = False
                if auto_cache_thread:
                    auto_cache_thread.join(timeout=5)  # 等待线程结束，最多5秒
                return jsonify({"status": "ok", "message": "自动缓存服务已停止"}), 200
            else:
                return jsonify({"status": "ok", "message": "自动缓存服务未运行"}), 200
        
        elif action == 'status':
            return jsonify({
                "status": "ok",
                "running": auto_cache_running,
                "thread_alive": auto_cache_thread.is_alive() if auto_cache_thread else False
            }), 200
        
        else:
            return jsonify({"status": "error", "message": "无效的操作，支持的操作: start, stop, status"}), 400
            
    except Exception as e:
        app.logger.error(f"[AUTO_CACHE] 控制自动缓存服务时出错: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

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
    try:
        # 获取当前播放的文件名
        current_file, _ = get_mpv_property("filename")
        if not current_file:
            # 如果获取filename失败，尝试从path属性获取
            path, _ = get_mpv_property("path")
            if path:
                current_file = os.path.basename(path)
        
        # 获取NAS上的所有音频文件列表
        all_files, message = rclone_list_files()
        if not all_files:
            # 如果NAS获取失败，使用本地文件
            all_files = get_audio_files()
        
        if not all_files:
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
        
        # 从缓存或NAS获取文件
        success, local_path, message = get_file_from_cache_or_nas(next_file)
        
        if not success:
            return jsonify({"status": "error", "message": f"Failed to get file: {message}"}), 500
        
        # 播放下一首歌曲
        success, message = send_mpv_command(["loadfile", local_path, "replace"])
        if success:
            return jsonify({
                "status": "ok", 
                "action": "next_track",
                "next_file": next_file,
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
            
            return jsonify({
                "status": "ok", 
                "action": "next_track",
                "next_file": next_file,
                "source": "cache" if "exists in cache" in message else "NAS",
                "local_path": local_path,
                "method": "restart"
            }), 200
        except Exception as e:
            return jsonify({"status": "error", "message": f"Failed to play file: {str(e)}"}), 500
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/mpv/prev', methods=['GET'])
@log_operation("上一首")
def prev_track():
    try:
        # 获取当前播放的文件名
        current_file, _ = get_mpv_property("filename")
        if not current_file:
            # 如果获取filename失败，尝试从path属性获取
            path, _ = get_mpv_property("path")
            if path:
                current_file = os.path.basename(path)
        
        # 获取NAS上的所有音频文件列表
        all_files, message = rclone_list_files()
        if not all_files:
            # 如果NAS获取失败，使用本地文件
            all_files = get_audio_files()
        
        if not all_files:
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
        success, local_path, message = get_file_from_cache_or_nas(prev_file)
        
        if not success:
            return jsonify({"status": "error", "message": f"Failed to get file: {message}"}), 500
        
        # 播放上一首歌曲
        success, message = send_mpv_command(["loadfile", local_path, "replace"])
        if success:
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
            
            return jsonify({
                "status": "ok", 
                "action": "prev_track",
                "prev_file": prev_file,
                "source": "cache" if "exists in cache" in message else "NAS",
                "local_path": local_path,
                "method": "restart"
            }), 200
        except Exception as e:
            return jsonify({"status": "error", "message": f"Failed to play file: {str(e)}"}), 500
    
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

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
    
    # 首先尝试将文件添加到播放列表并播放
    success, message = send_mpv_command(["loadfile", local_path, "replace"])
    if success:
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
        # 获取所有音频文件
        all_files, message = rclone_list_files()
        if not all_files:
            # 如果NAS获取失败，使用本地文件
            all_files = get_audio_files()
        
        if not all_files:
            return jsonify({"status": "error", "message": "No audio files found"}), 500
        
        # 清空当前播放列表
        send_mpv_command(["playlist-clear"])
        time.sleep(0.1)
        
        # 逐个添加文件到播放列表
        files_added = 0
        for filename in all_files:
            success, local_path, message = get_file_from_cache_or_nas(filename)
            if success:
                success, msg = send_mpv_command(["loadfile", local_path, "append"])
                if success:
                    files_added += 1
                    app.logger.info(f"Added to playlist: {filename}")
                else:
                    app.logger.warning(f"Failed to add to playlist: {filename}, error: {msg}")
        
        return jsonify({
            "status": "ok", 
            "action": "build_playlist", 
            "total_files": len(all_files),
            "files_added": files_added
        }), 200
        
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/mpv/status', methods=['GET'])
@log_operation("获取播放状态")
def get_status():
    """获取播放状态"""
    status = {}
    
    app.logger.debug("[状态获取] 开始获取MPV播放状态")
    
    try:
        # 获取播放状态
        app.logger.debug("[状态获取] 尝试获取pause属性")
        pause_state, pause_msg = get_mpv_property("pause")
        app.logger.debug(f"[状态获取] 获取pause属性结果: {pause_state}, 消息: {pause_msg}")
        status["paused"] = pause_state if pause_state is not None else False
        if pause_state is None:
            app.logger.warning(f"[状态获取] 获取pause状态失败: {pause_msg}")
        
        # 获取当前播放文件 - 尝试多种属性
        app.logger.debug("[状态获取] 尝试获取filename属性")
        filename, filename_msg = get_mpv_property("filename")
        app.logger.debug(f"[状态获取] 获取filename属性结果: {filename}, 消息: {filename_msg}")
        
        # 确保filename是字符串类型
        if filename is None:
            filename = ""
            app.logger.debug("[状态获取] filename为None，设置为空字符串")
        
        if not filename:  # 如果filename为空，尝试获取path属性
            app.logger.debug("[状态获取] filename为空，尝试获取path属性")
            path, path_msg = get_mpv_property("path")
            app.logger.debug(f"[状态获取] 获取path属性结果: {path}, 消息: {path_msg}")
            if path:
                # 从路径中提取文件名
                filename = os.path.basename(path)
                app.logger.debug(f"[状态获取] 从path提取文件名: {filename}")
        
        # 如果还是没有，尝试media-title
        if not filename:
            app.logger.debug("[状态获取] filename仍为空，尝试获取media-title属性")
            media_title, media_msg = get_mpv_property("media-title")
            app.logger.debug(f"[状态获取] 获取media-title属性结果: {media_title}, 消息: {media_msg}")
            if media_title:
                filename = media_title
                app.logger.debug(f"[状态获取] 使用media-title作为文件名: {filename}")
        
        # 确保最终返回的文件名是字符串类型
        status["current_file"] = filename if isinstance(filename, str) else ""
        app.logger.debug(f"[状态获取] 最终current_file值: {status['current_file']}, 类型: {type(status['current_file']).__name__}")
        
        # 获取音量
        app.logger.debug("[状态获取] 尝试获取volume属性")
        volume, volume_msg = get_mpv_property("volume")
        app.logger.debug(f"[状态获取] 获取volume属性结果: {volume}, 消息: {volume_msg}")
        status["volume"] = volume if volume is not None else 0
        
        # 获取播放列表
        app.logger.debug("[状态获取] 尝试获取playlist属性")
        playlist, playlist_msg = get_mpv_property("playlist")
        app.logger.debug(f"[状态获取] 获取playlist属性结果: 类型={type(playlist).__name__}, 长度={len(playlist) if isinstance(playlist, list) else 'N/A'}")
        status["playlist"] = playlist if playlist is not None else []
        
        # 获取播放位置和持续时间
        app.logger.debug("[状态获取] 尝试获取time-pos属性")
        position, position_msg = get_mpv_property("time-pos")
        app.logger.debug(f"[状态获取] 获取time-pos属性结果: {position}, 消息: {position_msg}")
        status["position"] = position if position is not None else 0
        
        app.logger.debug("[状态获取] 尝试获取duration属性")
        duration, duration_msg = get_mpv_property("duration")
        app.logger.debug(f"[状态获取] 获取duration属性结果: {duration}, 消息: {duration_msg}")
        status["duration"] = duration if duration is not None else 0
        
        # 计算播放进度百分比
        if duration and duration > 0:
            progress = (position / duration) * 100 if position else 0
            status["progress"] = round(progress, 2)
            app.logger.debug(f"[状态获取] 计算播放进度: {status['progress']}%")
        
        app.logger.debug(f"[状态获取] 完整状态数据: {json.dumps(status, ensure_ascii=False)}")
        return jsonify(status), 200
    except Exception as e:
        app.logger.error(f"[状态获取] 获取状态时发生异常: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": f"获取状态失败: {str(e)}", "error_type": type(e).__name__}), 500

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
        data = request.get_json() or {}
        filename = data.get('filename')
        
        if not filename:
            operation_logger.warning("[SYNC] 尝试同步所有文件，但已被禁止")
            return jsonify({"status": "error", "message": "Syncing all files is not allowed"}), 403
        
        operation_logger.debug(f"[SYNC] 请求同步单个文件: {filename}")
        success, message = rclone_sync(filename=filename)
            
        if success:
            return jsonify({"status": "ok", "message": "Sync completed successfully"}), 200
        return jsonify({"status": "error", "message": message}), 500
    except Exception as e:
        operation_logger.error(f"[SYNC] 同步文件时出错: {str(e)}", exc_info=True)
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route('/files/cache', methods=['POST'])
@log_operation("缓存指定文件")
def cache_file():
    """缓存指定的单个文件"""
    try:
        data = request.get_json() or {}
        filename = data.get('filename')
        
        if not filename:
            return jsonify({"status": "error", "message": "Filename is required"}), 400
            
        operation_logger.debug(f"[CACHE] 请求缓存文件: {filename}")
        success, message = rclone_sync(filename=filename)
        
        if success:
            return jsonify({"status": "ok", "message": f"File '{filename}' cached successfully"}), 200
        return jsonify({"status": "error", "message": message}), 500
    except Exception as e:
        operation_logger.error(f"[CACHE] 缓存文件时出错: {str(e)}", exc_info=True)
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
        data = request.json
        if not data or "action" not in data:
            return jsonify({
                "status": "error",
                "message": "Missing required field 'action'",
                "data": {}
            }), 400
        
        action = data["action"]
        params = data.get("params", {})
        
        # 执行相应的操作
        if action == "play":
            # 获取当前状态，如果已暂停则取消暂停，否则检查是否有正在播放的文件
            paused, _ = get_mpv_property("pause")
            if paused:
                # 如果当前是暂停状态，取消暂停
                success, message = send_mpv_command(["set_property", "pause", "no"])
            else:
                # 检查是否有正在播放的文件
                filename, _ = get_mpv_property("filename")
                if not filename:
                    # 如果没有正在播放的文件，尝试播放下一首
                    next_track_result = next_track()
                    return next_track_result
                success, message = True, "Already playing"
                
        elif action == "pause":
            success, message = send_mpv_command(["set_property", "pause", "yes"])
            
        elif action == "next":
            return next_track()
            
        elif action == "prev":
            return prev_track()
            
        elif action == "stop":
            success, message = send_mpv_command(["quit"])
            
        elif action == "volume":
            value = params.get("value", 0)
            try:
                value = int(value)
                success, message = send_mpv_command(["add", "volume", str(value)])
            except (ValueError, TypeError):
                return jsonify({
                    "status": "error",
                    "message": "Volume value must be an integer",
                    "data": {}
                }), 400
                
        else:
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
            return jsonify({
                "status": "ok",
                "message": f"Action '{action}' executed successfully",
                "data": {
                    "action": action,
                    "current_status": current_status
                }
            }), 200
        else:
            return jsonify({
                "status": "error",
                "message": f"Failed to execute action: {message}",
                "data": {
                    "action": action,
                    "current_status": current_status
                }
            }), 500
            
    except Exception as e:
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
@log_operation("访问网页控制面板")
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
                    console.log('Status data received:', data);
                    
                    // 修复播放状态显示逻辑：当没有当前文件时显示"未播放"
                    // 确保current_file是字符串类型
                    var currentFile = typeof data.current_file === 'string' ? data.current_file : '';
                    var hasCurrentFile = currentFile && currentFile.trim() !== '';
                    document.getElementById('current-file').textContent = hasCurrentFile ? currentFile : '无';
                    
                    // 根据是否有当前文件和暂停状态来正确显示播放状态
                    if (!hasCurrentFile) {
                        document.getElementById('play-status').textContent = '未播放';
                    } else {
                        document.getElementById('play-status').textContent = data.paused ? '已暂停' : '正在播放';
                    }
                    
                    // 修复音量显示问题：总是更新音量显示，除非用户正在主动调整
                    // 这样可以确保显示正确的音量值
                    var volumeValue = Math.round(data.volume) || 0;
                    console.log('Updating volume display:', volumeValue);
                    document.getElementById('volume').textContent = volumeValue;
                    document.getElementById('volume-slider').value = volumeValue;
                    document.getElementById('volume-value').textContent = volumeValue;
                })
                .catch(function(error) {
                    console.error('Error updating status:', error);
                    // 出错时也更新UI，显示错误状态
                    document.getElementById('current-file').textContent = '无';
                    document.getElementById('play-status').textContent = '未播放';
                    document.getElementById('volume').textContent = '0';
                    document.getElementById('volume-slider').value = '50';
                    document.getElementById('volume-value').textContent = '50';
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
            
            // 首先构建播放列表，然后播放指定文件
            fetch('/mpv/build_playlist', {method: 'POST'})
                .then(response => response.json())
                .then(playlistData => {
                    console.log('播放列表构建成功:', playlistData);
                    
                    // 然后播放指定文件
                    return fetch(`/mpv/play/file/${encodeURIComponent(filename)}`);
                })
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
        
        function adjustVolume(value) {
            console.log('Adjusting volume to:', value);
            // 立即更新所有音量显示元素，确保即时反馈
            document.getElementById('volume').textContent = value;
            document.getElementById('volume-value').textContent = value;
            document.getElementById('volume-slider').value = value;
            
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
        let lastFileCount = 0;
        let lastCurrentFile = null; // 记录上一首播放的文件
        let isPlaying = false; // 记录播放状态
        
        function checkAndAutoPlayNext() {
            // 获取当前播放状态
            fetch('/mpv/status')
                .then(response => response.json())
                .then(data => {
                    console.log('Auto-play check:', data);
                    
                    // 确保current_file是字符串类型
                    const currentFile = typeof data.current_file === 'string' ? data.current_file : '';
                    const hasCurrentFile = currentFile && currentFile.trim() !== '';
                    const currentIsPlaying = hasCurrentFile && !data.paused;
                    
                    // 检测播放结束的三种方式：
                    // 1. 播放位置接近文件末尾（相差不到2秒，更宽松的条件）
                    // 2. 从有文件播放到无文件，且上一首是播放状态
                    // 3. 文件改变了，但上一个文件是存在的（可能是手动切换的）
                    const isNearEndOfPlayback = hasCurrentFile && data.position > 0 && 
                                              data.duration > 0 && 
                                              (data.duration - data.position) < 2.0; // 小于2秒时认为即将结束
                    
                    const isFileEnded = !hasCurrentFile && lastCurrentFile && isPlaying;
                    const isFileChanged = hasCurrentFile && lastCurrentFile && currentFile !== lastCurrentFile;
                    
                    if (isNearEndOfPlayback || isFileEnded) {
                        console.log('检测到播放结束或接近结束，当前状态:', {
                            isNearEndOfPlayback,
                            isFileEnded,
                            currentFile,
                            lastFile: lastCurrentFile,
                            position: data.position,
                            duration: data.duration
                        });
                        
                        // 直接调用后端的next_track API，与手动点击下一首按钮保持一致
                        fetch('/mpv/next')
                            .then(response => response.json())
                            .then(nextData => {
                                if (nextData.status === 'ok') {
                                    console.log('自动播放下一首成功:', nextData.next_file);
                                    showNotification(`自动播放下一首: ${nextData.next_file}`);
                                } else {
                                    console.error('自动播放下一首失败:', nextData.message);
                                }
                            })
                            .catch(error => {
                                console.error('自动播放下一首请求失败:', error);
                            });
                    }
                    
                    // 更新状态记录
                    lastCurrentFile = hasCurrentFile ? currentFile : null;
                    isPlaying = currentIsPlaying;
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