# Termux 音频服务器

一个基于 Termux 的远程音频播放控制系统，可通过浏览器控制音乐播放。

## 功能特性

- 🎵 通过浏览器控制音乐播放（暂停/播放、上一首、下一首、音量控制）
- 🔍 搜索本地音乐文件
- 🔀 随机播放模式
- 🌐 网页控制面板
- 📱 手机/电脑浏览器一键控制
- 🔄 自动同步 NAS 音乐文件
- 🎛️ 实时播放状态显示

## 完整链路

```
NAS → rclone → Termux本地缓存 → mpv真·socket → Flask → 手机/电脑浏览器一键暂停/切歌
```

## 一键部署（推荐）

### 使用一键部署脚本（Termux环境）

```bash
# 下载并运行一键部署脚本
curl -O https://raw.githubusercontent.com/coolangcn/termux-audio-server/main/setup_termux_audio_server.sh
chmod +x setup_termux_audio_server.sh
./setup_termux_audio_server.sh
```

脚本将自动完成以下操作：
1. 安装所有必要的依赖（Python, Flask, MPV, Rclone, Socat等）
2. 下载项目文件到 ~/termux-audio-server/
3. 创建启动和停止脚本
4. 引导配置rclone远程存储

## 手动安装与配置

### 1. 安装依赖

```bash
chmod +x ~/install_dependencies.sh
~/install_dependencies.sh
```

### 2. 配置 rclone

```bash
rclone config
```

确保配置了一个名为 `synology` 的远程存储，路径指向包含音乐文件的目录。

### 3. 修改配置（可选）

编辑 [start_remote_audio.sh](file:///d%3A/python/termux-audio-server/start_remote_audio.sh) 文件中的以下变量：

- `RCLONE_REMOTE`: rclone远程存储路径
- `LOCAL_DIR`: 本地缓存目录
- `API_PORT`: Web API端口

## 使用方法

### 启动服务

```bash
chmod +x ~/start_remote_audio.sh
~/start_remote_audio.sh
```

### 访问控制面板

启动成功后，会在终端显示访问地址，类似：
```
🌐 API 地址: http://192.168.1.100:5000
🌐 控制面板: http://192.168.1.100:5000/
```

在手机或电脑浏览器中打开控制面板地址即可使用。

### API 接口

| 接口 | 方法 | 描述 |
|------|------|------|
| [/mpv/pause](file:///d%3A/python/termux-audio-server/%3CINVALID%3E) | GET | 暂停/播放切换 |
| [/mpv/next](file:///d%3A/python/termux-audio-server/%3CINVALID%3E) | GET | 下一首 |
| [/mpv/prev](file:///d%3A/python/termux-audio-server/%3CINVALID%3E) | GET | 上一首 |
| [/mpv/stop](file:///d%3A/python/termux-audio-server/%3CINVALID%3E) | GET | 停止播放 |
| [/mpv/shuffle](file:///d%3A/python/termux-audio-server/%3CINVALID%3E) | GET | 随机播放 |
| [/mpv/volume](file:///d%3A/python/termux-audio-server/%3CINVALID%3E) | GET | 调整音量 (参数: value) |
| [/mpv/status](file:///d%3A/python/termux-audio-server/%3CINVALID%3E) | GET | 获取播放状态 |
| [/files](file:///d%3A/python/termux-audio-server/%3CINVALID%3E) | GET | 列出所有音乐文件 |
| [/files/search](file:///d%3A/python/termux-audio-server/%3CINVALID%3E) | GET | 搜索音乐文件 (参数: q) |
| [/files/sync](file:///d%3A/python/termux-audio-server/%3CINVALID%3E) | POST | 手动同步NAS文件 |

## 停止服务

```bash
killall mpv python && rm -rf ~/nas_audio_cache ~/mpv_playlist_*
```

或者使用我们提供的停止脚本：
```bash
~/stop_audio_server
```

## 未来功能计划

- [ ] 安卓桌面小部件
- [ ] 更丰富的播放列表管理
- [ ] 音乐文件详细信息显示
- [ ] 播放历史记录
- [ ] 多设备同步控制

## 故障排除

如果遇到问题，请检查：

1. 确保 rclone 配置正确
2. 确保 NAS 网络连接正常
3. 检查 MPV 是否正常运行
4. 查看防火墙设置是否阻止了 API 端口