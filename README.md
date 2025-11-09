# Termux Audio Server

一个基于Termux的远程音频播放服务器，支持通过Web界面或API控制音乐播放。

## 功能特性

- 🎵 简洁美观的Web界面音频控制面板
- 📱 支持通过API远程控制
- 🔊 优化的音量控制功能
- 🔍 文件搜索功能
- 📝 操作日志记录

## 安装部署

### 准备工作

1. 安装Termux：从[F-Droid](https://f-droid.org/packages/com.termux/)或[Google Play](https://play.google.com/store/apps/details?id=com.termux)下载安装
2. 授予Termux存储权限：`termux-setup-storage`

### 一键部署

```bash
curl -o setup_termux_audio_server.sh https://raw.githubusercontent.com/coolangcn/termux-audio-server/main/setup_termux_audio_server.sh && chmod +x setup_termux_audio_server.sh && ./setup_termux_audio_server.sh
```

## 使用方法

### 启动服务

```bash
./start_remote_audio.sh
```

### Web界面

启动服务后，可以通过浏览器访问：http://<设备IP>:5000/

### API接口

- **播放/暂停**: `GET http://<设备IP>:5000/mpv/pause`
- **下一首**: `GET http://<设备IP>:5000/mpv/next`
- **上一首**: `GET http://<设备IP>:5000/mpv/prev`
- **设置音量**: `GET http://<设备IP>:5000/mpv/volume/set?value=70`
- **调整音量**: `GET http://<设备IP>:5000/mpv/volume?value=10`
- **播放指定歌曲**: `GET http://<设备IP>:5000/mpv/play/<index>`
- **播放指定文件**: `GET http://<设备IP>:5000/mpv/play/file/<filename>`
- **构建播放列表**: `POST http://<设备IP>:5000/mpv/build_playlist`
- **获取播放状态**: `GET http://<设备IP>:5000/mpv/status`
- **列出所有文件**: `GET http://<设备IP>:5000/files`
- **搜索文件**: `GET http://<设备IP>:5000/files/search?q=<关键词>`

## 项目结构

- `enhanced_mpv_api.py`: 主要API实现（已优化）
- `start_remote_audio.sh`: 启动脚本
- `setup_termux_audio_server.sh`: 安装部署脚本
- `requirements.txt`: Python依赖

## 依赖项

- Python 3
- Flask
- Flask-CORS
- MPV
- socat

## 故障排除

如果遇到问题，可以尝试以下操作：

1. 检查MPV是否正常运行
2. 确保socket路径正确
3. 检查网络连接和防火墙设置
4. 查看日志文件获取更多信息

## 更新日志

### v2.1.0
- 修复下一首/上一首功能对WEBM文件无效的问题
- 添加播放列表构建功能，支持所有音频格式
- 改进MPV启动参数，增强稳定性
- 增强错误处理和调试日志

### v2.0.0
- 界面样式全面优化
- 移除不必要的功能按钮（随机播放、同步、停止）
- 修复音量控制问题
- 精简项目结构

## 许可证

MIT