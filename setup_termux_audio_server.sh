#!/data/data/com.termux/files/usr/bin/bash

# Termux 音频服务器一键部署脚本
# 作者: 
# 日期: 2025-11-08

echo "🎵 Termux 音频服务器一键部署脚本"
echo "======================================"
echo ""

# 检查是否在 Termux 环境中运行
if [ -z "$TERMUX_VERSION" ]; then
    echo "❌ 错误: 此脚本必须在 Termux 环境中运行!"
    echo "请先安装 Termux 应用，然后在 Termux 中运行此脚本。"
    exit 1
fi

echo "✅ 检测到 Termux 环境"

# 更新包列表
echo "🔄 更新包列表..."
pkg update -y

# 安装必要的系统工具
echo "📥 安装必要的系统工具..."
pkg install -y python socat rclone mpv git

# 安装Python依赖
echo "🐍 安装Python依赖..."
pip install Flask flask-cors

# 创建项目目录
echo "📁 创建项目目录..."
rm -rf ~/termux-audio-server/
mkdir -p ~/termux-audio-server

# 克隆GitHub仓库
echo "🌐 克隆GitHub仓库..."
cd ~
rm -rf termux-audio-server-temp
git clone https://github.com/coolangcn/termux-audio-server.git termux-audio-server-temp || {
    echo "克隆仓库失败，尝试下载单个文件..."
    mkdir -p termux-audio-server-temp
    cd termux-audio-server-temp
    # 使用修改优化后的enhanced_mpv_api.py版本
    curl -o enhanced_mpv_api.py "https://raw.githubusercontent.com/coolangcn/termux-audio-server/main/enhanced_mpv_api.py"
    # 确保文件有执行权限
    chmod +x enhanced_mpv_api.py
}

# 复制文件到用户目录
echo "📋 复制文件到用户目录..."
cp -r termux-audio-server-temp/* ~/termux-audio-server/
# 特别复制优化后的enhanced_mpv_api.py到主目录以便快速访问
cp termux-audio-server-temp/enhanced_mpv_api.py ~/enhanced_mpv_api.py
chmod +x ~/enhanced_mpv_api.py
rm -rf termux-audio-server-temp

# 设置执行权限
echo "🔧 设置执行权限..."
chmod +x ~/termux-audio-server/*.sh
chmod +x ~/termux-audio-server/*.py

# 创建软链接以便于访问
echo "🔗 创建软链接..."
ln -sf ~/termux-audio-server/start_remote_audio.sh ~/start_audio_server
ln -sf ~/termux-audio-server/stop_audio_server.sh ~/stop_audio_server

# 配置rclone
echo ""
echo "⚙️  配置rclone远程存储"
echo "请按照以下步骤配置rclone:"
echo "1. 运行 'rclone config' 命令"
echo "2. 创建一个新的远程存储配置"
echo "3. 命名远程存储为 'synology'"
echo "4. 配置完成后按回车键继续"
echo ""
read -p "按回车键运行rclone配置工具..." -n1 -s
rclone config

echo ""
echo "📝 重要配置说明:"
echo "请确保您的rclone配置中包含一个名为 'synology' 的远程存储"
echo "并且该远程存储指向包含音乐文件的目录"

# 创建停止脚本
echo "⏹️  创建停止脚本..."
cat > ~/termux-audio-server/stop_audio_server.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash

echo "⏹️  停止音频服务器..."

# 停止所有正在运行的 rclone, mpv 和 python 服务
killall -q rclone mpv python socat 2>/dev/null 

# 清理临时文件
rm -f ~/mpv_playlist_* 2>/dev/null

echo "✅ 音频服务器已停止"
echo "🗑️  临时文件已清理"
EOF

chmod +x ~/termux-audio-server/stop_audio_server.sh

# 创建系统服务脚本（可选）
echo "⚙️  创建系统服务脚本..."
cat > ~/termux-audio-server/install_as_service.sh << 'EOF'
#!/data/data/com.termux/files/usr/bin/bash

# 安装 Termux:Boot 应用以支持开机自启
echo "请从 F-Droid 安装 Termux:Boot 应用以支持开机自启功能"
echo "安装完成后，在 ~/../com.termux.boot/ 目录中创建启动脚本"

# 创建开机自启脚本示例
mkdir -p ~/../com.termux.boot
cat > ~/../com.termux.boot/audio_server.sh << 'INNEREOF'
#!/data/data/com.termux/files/usr/bin/bash
cd ~
./start_audio_server
INNEREOF

chmod +x ~/../com.termux.boot/audio_server.sh

echo "✅ 系统服务脚本已创建"
echo "请安装 Termux:Boot 应用以启用开机自启功能"
EOF

chmod +x ~/termux-audio-server/install_as_service.sh

echo ""
echo "🎉 部署完成!"
echo "========================"
echo "已安装的组件:"
echo "  - Python Flask API服务器"
echo "  - MPV 音频播放器"
echo "  - Rclone 文件同步工具"
echo "  - Socat Socket工具"
echo ""
echo "已创建的脚本:"
echo "  - 启动脚本: ~/start_audio_server"
echo "  - 停止脚本: ~/stop_audio_server"
