import os
import json
import subprocess
from flask import Flask, request, jsonify
from flask_cors import CORS

app = Flask(__name__)
CORS(app)  # 允许跨域请求

# MPV_SOCKET_PATH = "/data/data/com.termux/files/home/mpv-socket"
MPV_SOCKET_PATH = "/data/data/com.termux/files/usr/tmp/mpv_ctrl/socket"  # 改这行！

# 或者直接用软链接也行："/data/data/com.termux/files/home/mpv-socket"

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
    
    return jsonify(status), 200

if __name__ == '__main__':
    # 注意：0.0.0.0 允许从外部设备访问
    API_PORT = int(os.environ.get('API_PORT', 5000))
    app.run(host='0.0.0.0', port=API_PORT, debug=False)