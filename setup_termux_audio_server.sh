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
mkdir -p ~/termux-audio-server

# 克隆GitHub仓库
echo "🌐 克隆GitHub仓库..."
cd ~
rm -rf termux-audio-server-temp
git clone https://github.com/coolangcn/termux-audio-server.git termux-audio-server-temp

# 复制文件到用户目录
echo "📋 复制文件到用户目录..."
cp -r termux-audio-server-temp/* ~/termux-audio-server/
rm -rf termux-audio-server-temp

# 设置执行权限
echo "🔧 设置执行权限..."
chmod +x ~/termux-audio-server/*.sh
chmod +x ~/termux-audio-server/*.py

# 创建软链接以便于访问
echo "🔗 创建软链接..."
ln -sf ~/termux-audio-server/start_remote_audio.sh ~/start_audio_server
ln -sf ~/termux-audio-server/stop_audio_server.sh ~/stop_audio_server
ln -sf ~/termux-audio-server/fix_mpv_socket.sh ~/fix_mpv_socket
ln -sf ~/termux-audio-server/fix_network_config.sh ~/fix_network_config
ln -sf ~/termux-audio-server/fix_api_binding.sh ~/fix_api_binding
ln -sf ~/termux-audio-server/diagnose_and_fix_api.sh ~/diagnose_api
ln -sf ~/termux-audio-server/fix_logging_path.sh ~/fix_logging
ln -sf ~/termux-audio-server/update_web_ui.sh ~/update_web_ui
ln -sf ~/termux-audio-server/fix_api_after_ui_update.sh ~/fix_api_ui
ln -sf ~/termux-audio-server/comprehensive_diagnose.sh ~/comprehensive_diagnose
ln -sf ~/termux-audio-server/fix_api_binding_issue.sh ~/fix_api_binding_issue
ln -sf ~/termux-audio-server/add_operation_log.sh ~/add_operation_log
ln -sf ~/termux-audio-server/restart_with_logging.sh ~/restart_with_logging
ln -sf ~/termux-audio-server/fix_web_ui_issues.sh ~/fix_web_ui_issues
ln -sf ~/termux-audio-server/simple_fix_ui.sh ~/simple_fix_ui
ln -sf ~/termux-audio-server/direct_fix_ui.py ~/direct_fix_ui

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
echo "  - MPV Socket修复脚本: ~/fix_mpv_socket"
echo "  - 网络配置修复脚本: ~/fix_network_config"
echo "  - API绑定修复脚本: ~/fix_api_binding"
echo "  - API诊断脚本: ~/diagnose_api"
echo "  - 日志路径修复脚本: ~/fix_logging"
echo "  - UI更新脚本: ~/update_web_ui"
echo "  - UI更新后API修复脚本: ~/fix_api_ui"
echo "  - 全面诊断脚本: ~/comprehensive_diagnose"
echo "  - API绑定问题修复脚本: ~/fix_api_binding_issue"
echo "  - 操作日志添加脚本: ~/add_operation_log"
echo "  - 带日志功能的重启脚本: ~/restart_with_logging"
echo "  - 网页UI问题修复脚本: ~/fix_web_ui_issues"
echo "  - 简单UI修复脚本: ~/simple_fix_ui"
echo "  - 直接UI修复脚本: ~/direct_fix_ui"
echo "  - 部署目录: ~/termux-audio-server/"
echo ""
echo "📌 下一步操作:"
echo "1. 配置rclone远程存储 (如果尚未完成)"
echo "2. 编辑 ~/termux-audio-server/start_remote_audio.sh 文件配置您的NAS路径"
echo "3. 运行 '~/start_audio_server' 启动音频服务器"
echo "4. 在浏览器中访问显示的IP地址和端口"
echo ""
echo "💡 使用提示:"
echo "- 启动服务器: ~/start_audio_server"
echo "- 停止服务器: ~/stop_audio_server"
echo "- 修复MPV Socket问题: ~/fix_mpv_socket"
echo "- 修复网络配置问题: ~/fix_network_config"
echo "- 修复API绑定问题: ~/fix_api_binding"
echo "- 诊断API问题: ~/diagnose_api"
echo "- 修复日志路径问题: ~/fix_logging"
echo "- 更新网页UI: ~/update_web_ui"
echo "- 修复UI更新后的API问题: ~/fix_api_ui"
echo "- 全面诊断: ~/comprehensive_diagnose"
echo "- 修复API绑定问题: ~/fix_api_binding_issue"
echo "- 添加操作日志: ~/add_operation_log"
echo "- 带日志功能的重启: ~/restart_with_logging"
echo "- 修复网页UI问题: ~/fix_web_ui_issues"
echo "- 简单UI修复: ~/simple_fix_ui"
echo "- 直接UI修复: ~/direct_fix_ui"
echo "- 查看日志: cat ~/api_server_debug.log"
echo ""
echo "🌐 项目GitHub地址: https://github.com/coolangcn/termux-audio-server"
echo ""
echo "如有任何问题，请查看GitHub上的README.md文件或提交issue。"