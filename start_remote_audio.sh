#!/data/data/com.termux/files/usr/bin/bash

# --- 配置区 ---

RCLONE_REMOTE="synology:download/bilibili/push"
LOCAL_DIR=~/nas_audio_cache
MPV_SOCKET_PATH="/data/data/com.termux/files/usr/tmp/mpv_ctrl/socket"

# --idle: 即使列表播完也保持进程存活，继续监听 IPC
# --loop=inf: 循环播放列表
# 移除了随机播放参数
MPV_OPTIONS="--no-video --input-ipc-server=$MPV_SOCKET_PATH --idle --loop=inf"

# 使用增强版API脚本
API_SCRIPT=~/termux-audio-server/enhanced_mpv_api.py

API_PORT=5000
FILE_REGEX='.*\.\(mp4\|mp3\|flac\|ogg\|aac\|m4a\|wav\|webm\)'
RCLONE_INCLUDES='--include "*.mp4" --include "*.mp3" --include "*.flac" --include "*.ogg" --include "*.aac" --include "*.m4a" --include "*.wav" --include "*.webm"'
PLAYLIST_FILE=~/mpv_playlist_fixed.txt 

# 自动缓存配置
AUTO_CACHE_INTERVAL=1800  # 30分钟检查一次新文件

echo "--- 1. 停止旧服务并准备目录 ---"

# 停止所有正在运行的 rclone, mpv 和 python 服务
killall -q rclone mpv python 2>/dev/null 

# 确保本地目录存在
mkdir -p "$LOCAL_DIR"

# --- 2. 准备本地缓存目录 ---
echo "--- 2. 准备本地缓存目录: $LOCAL_DIR ---"
# 只创建目录，不预先复制所有文件
mkdir -p "$LOCAL_DIR"
echo "✅ 本地缓存目录准备完成。"

# --- 3. 启动 MPV 播放器 ---
echo "--- 3. 启动 MPV 播放器并监听 IPC Socket ---"

# 直接从NAS获取文件列表创建播放列表文件
echo "--- 获取NAS文件列表创建播放列表 ---"
# 使用rclone lsjson命令获取文件列表并提取文件名
# 添加调试信息并尝试更可靠的解析方法
echo "调试: 执行rclone命令获取文件列表..."
echo "RCLONE_REMOTE: $RCLONE_REMOTE"
echo "RCLONE_INCLUDES: $RCLONE_INCLUDES"
echo "FILE_REGEX: $FILE_REGEX"
echo "PLAYLIST_FILE: $PLAYLIST_FILE"

# 先测试rclone命令是否正常工作
TEST_OUTPUT=$(eval rclone lsjson "$RCLONE_REMOTE" $RCLONE_INCLUDES 2>&1)

if [ $? -ne 0 ]; then
    echo "❌ rclone命令执行失败: $TEST_OUTPUT"
    exit 1
fi

# 输出原始JSON响应以便调试
echo "调试: rclone原始JSON响应:"
echo "$TEST_OUTPUT"
echo "调试: rclone命令执行成功，开始解析文件名..."

# 检查jq是否可用，如果不可用则使用更可靠的grep回退方案
if command -v jq &> /dev/null; then
    echo "调试: 使用jq解析JSON..."
    echo "$TEST_OUTPUT" | jq -r '.[].Name' | grep -E "$FILE_REGEX" > "$PLAYLIST_FILE"
else
    echo "⚠️ jq命令未找到，使用兼容版grep/sed回退方案解析JSON..."
    # 使用简化的正则表达式，避免依赖[[:space:]]等可能不兼容的特性
    echo "$TEST_OUTPUT" | grep '"Name"' | sed 's/.*"Name":"\([^"]*\)".*/\1/' | grep -E "$FILE_REGEX" > "$PLAYLIST_FILE"
    
    # 显示解析结果
    echo "调试: 解析后的文件列表内容:"
    cat "$PLAYLIST_FILE" 2>/dev/null || echo "空文件"
fi

if [ ! -s "$PLAYLIST_FILE" ]; then
    echo "❌ NAS目录下未找到可播放文件！请检查 $RCLONE_REMOTE 目录中是否有支持的音频文件"
    rm -f "$PLAYLIST_FILE" 2>/dev/null
    exit 1
fi

# 在后台启动 mpv
mpv --playlist="$PLAYLIST_FILE" $MPV_OPTIONS & 
MPV_PID=$!
echo "✅ MPV (PID $MPV_PID) 已在后台启动，将播放 $LOCAL_DIR 下的文件列表。"

# 关键修复：等待 Socket 创建并设置权限
echo "⏳ 正在设置 Socket 权限..."
# 等待 Socket 文件出现，最多等待 5 秒
for i in {1..5}; do
    if [ -S "$MPV_SOCKET_PATH" ]; then
        break
    fi
    sleep 1
done

if [ -S "$MPV_SOCKET_PATH" ]; then
    # 强制设置权限为 666 (所有用户可读写)，允许 Flask/Python 进程连接
    chmod 666 "$MPV_SOCKET_PATH"
    echo "✅ Socket 权限已设置为 666。"
else
    echo "❌ 错误：MPV Socket 文件未创建！API 服务可能无法连接。"
    # 如果 Socket 未创建，Flask 必然失败，但我们让脚本继续运行以诊断问题
fi

# --- 4. 启动 Flask API 服务 ---
echo "--- 4. 启动 Flask API 服务 (端口 $API_PORT) ---"

# 设置环境变量以确保API服务正确绑定
export API_PORT=$API_PORT
export FLASK_ENV=production
export FLASK_DEBUG=0

# 确保在正确的目录中启动API服务
cd ~/termux-audio-server

# 在后台启动 Python 脚本并记录日志以便调试
# 使用修改后的 enhanced_mpv_api.py
python "$API_SCRIPT" > ~/api_server_startup.log 2>&1 &
API_PID=$!
echo "✅ API 服务 (PID $API_PID) 已在后台启动。"

# --- 5. 启动自动缓存服务 ---
echo "--- 5. 启动自动缓存服务 ---"
# 启动自动缓存（通过API控制）
sleep 3  # 等待API服务启动
curl -X POST "http://localhost:$API_PORT/cache/auto?action=start" >/dev/null 2>&1
echo "✅ 自动缓存服务已启动，将每30分钟检查一次新文件。"

# --- 6. 最终提示 ---
IP_ADDRESS=$(ifconfig wlan0 | grep -oP 'inet \K[\d.]+' || echo '127.0.0.1')

echo "--------------------------------------------------------"
echo "🎉 远程音频控制系统已启动！"
echo "🌐 API 地址: http://$IP_ADDRESS:$API_PORT"
echo "🌐 控制面板: http://$IP_ADDRESS:$API_PORT/"
echo "--------------------------------------------------------"
echo "控制命令示例："
echo "暂停/播放: GET http://$IP_ADDRESS:$API_PORT/mpv/pause"
echo "下一首:   GET http://$IP_ADDRESS:$API_PORT/mpv/next"
echo "上一首:   GET http://$IP_ADDRESS:$API_PORT/mpv/prev"
echo "搜索歌曲: GET http://$IP_ADDRESS:$API_PORT/files/search?q=关键字"
echo "停止所有服务: killall mpv python rclone && rm -rf \"$LOCAL_DIR\" \"$PLAYLIST_FILE\""
echo "--------------------------------------------------------"