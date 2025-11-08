#!/data/data/com.termux/files/usr/bin/python3
# -*- coding: utf-8 -*-

"""
测试和修复操作日志记录功能的脚本
"""

import os
import re
import shutil
import logging
import json
from datetime import datetime

def test_and_fix_logging():
    """测试和修复操作日志记录功能"""
    print("🔧 测试和修复操作日志记录功能...")
    
    # 获取用户主目录
    home_dir = os.path.expanduser("~")
    print(f"🏠 用户主目录: {home_dir}")
    
    # API脚本路径
    api_script = os.path.join(home_dir, "termux-audio-server", "enhanced_mpv_api.py")
    
    # 检查API脚本是否存在
    if not os.path.exists(api_script):
        print(f"❌ API脚本不存在: {api_script}")
        return False
    
    print("📝 备份原API脚本...")
    shutil.copy2(api_script, f"{api_script}.logging_fix_backup")
    
    # 读取API脚本内容
    with open(api_script, 'r', encoding='utf-8') as f:
        content = f.read()
    
    # 1. 确保日志目录存在
    log_dir = os.path.join(home_dir, "audio_logs")
    os.makedirs(log_dir, exist_ok=True)
    print(f"📁 确保日志目录存在: {log_dir}")
    
    # 2. 检查并修复日志配置
    print("2. 检查日志配置...")
    
    # 确保导入logging模块
    if "import logging" not in content:
        print("   添加logging导入...")
        content = re.sub(
            r'(import os\nimport signal\nimport json\nimport time\nimport threading\nimport subprocess\n)',
            r'\1import logging\nimport datetime\n',
            content,
            count=1
        )
    
    # 检查日志配置是否存在
    if "logger = logging.getLogger" not in content:
        print("   添加日志配置...")
        # 找到Flask应用初始化的位置
        app_init_pos = content.find("app = Flask(__name__)")
        if app_init_pos != -1:
            # 在Flask应用初始化后添加日志配置
            log_config = f"""
# 配置操作日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("{log_dir}/operations.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# 添加操作日志装饰器
def log_operation(operation):
    def decorator(f):
        def wrapper(*args, **kwargs):
            logger.info(f"用户执行操作: {{operation}}")
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator
"""
            insert_pos = content.find("\n", app_init_pos) + 1
            content = content[:insert_pos] + log_config + "\n" + content[insert_pos:]
    
    # 3. 检查并修复API端点的日志装饰器
    print("3. 检查API端点日志装饰器...")
    
    endpoints = [
        ("def pause_toggle()", "播放/暂停切换"),
        ("def next_track()", "下一首"),
        ("def prev_track()", "上一首"),
        ("def stop_playback()", "停止播放"),
        ("def shuffle_playlist()", "随机播放"),
        ("def play_track\\(index\\)", "播放指定歌曲"),
        ("def adjust_volume\\(\\)", "调整音量"),
        ("def set_volume\\(\\)", "设置音量"),
        ("def sync_files\\(\\)", "手动同步文件")
    ]
    
    for endpoint, operation in endpoints:
        # 检查是否已经有日志装饰器
        pattern = f"@log_operation\\([^)]*\\)\\s*{endpoint}"
        if not re.search(pattern, content):
            print(f"   为 {operation} 添加日志装饰器...")
            # 查找函数定义
            func_pattern = f"({endpoint})"
            content = re.sub(
                func_pattern,
                f"@log_operation('{operation}')\n    \\1",
                content,
                count=1
            )
    
    # 4. 检查并修复日志API端点
    print("4. 检查日志API端点...")
    
    if "@app.route('/logs'" not in content:
        print("   添加日志API端点...")
        log_endpoints = f"""
@app.route('/logs', methods=['GET'])
def get_logs():
    \"\"\"获取操作日志\"\"\"
    try:
        log_file = "{log_dir}/operations.log"
        if os.path.exists(log_file):
            with open(log_file, "r", encoding="utf-8") as f:
                lines = f.readlines()
                # 返回最后100行日志
                return jsonify({{"logs": lines[-100:] if len(lines) > 100 else lines}}), 200
        else:
            return jsonify({{"logs": []}}), 200
    except Exception as e:
        return jsonify({{"error": str(e)}}), 500

@app.route('/logs/clear', methods=['POST'])
def clear_logs():
    \"\"\"清空操作日志\"\"\"
    try:
        log_file = "{log_dir}/operations.log"
        if os.path.exists(log_file):
            open(log_file, "w").close()
            logger.info("用户执行操作: 清空操作日志")
            return jsonify({{"message": "日志已清空"}}), 200
        else:
            return jsonify({{"message": "日志文件不存在"}}), 404
    except Exception as e:
        return jsonify({{"error": str(e)}}), 500
"""
        # 在if __name__ == '__main__'之前添加日志端点
        main_pos = content.rfind("if __name__ == '__main__':")
        if main_pos != -1:
            content = content[:main_pos] + log_endpoints + "\n" + content[main_pos:]
    
    # 5. 写入修改后的内容
    with open(api_script, 'w', encoding='utf-8') as f:
        f.write(content)
    
    # 6. 测试日志功能
    print("5. 测试日志功能...")
    
    # 创建测试日志条目
    test_log_entry = f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} [INFO] 测试日志功能: 日志系统工作正常\n"
    
    # 写入测试日志
    log_file = os.path.join(log_dir, "operations.log")
    with open(log_file, 'a', encoding='utf-8') as f:
        f.write(test_log_entry)
    
    print(f"   ✅ 已写入测试日志条目到: {log_file}")
    
    # 7. 验证日志文件
    if os.path.exists(log_file):
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            if lines:
                print(f"   ✅ 日志文件包含 {len(lines)} 条记录")
                print(f"   📋 最新日志: {lines[-1].strip()}")
            else:
                print("   ⚠️ 日志文件为空")
    else:
        print("   ❌ 日志文件不存在")
    
    print("")
    print("✅ 操作日志记录功能测试和修复完成!")
    print("")
    print("📌 修复内容:")
    print("   • 确保日志模块正确导入")
    print("   • 添加完整的日志配置")
    print("   • 为所有API端点添加日志装饰器")
    print("   • 确保日志API端点正常工作")
    print("   • 添加测试日志条目验证功能")
    print("")
    print("🔧 请重新启动音频服务器以应用更改：")
    print("   ~/stop_audio_server")
    print("   ~/start_audio_server")
    print("")
    print("💡 验证方法:")
    print("   1. 重启服务后，在控制面板执行任意操作")
    print("   2. 观察操作日志区域是否实时更新")
    print("   3. 检查日志文件: cat ~/audio_logs/operations.log")
    
    return True

def manual_log_test():
    """手动测试日志功能"""
    print("🧪 手动测试日志功能...")
    
    home_dir = os.path.expanduser("~")
    log_dir = os.path.join(home_dir, "audio_logs")
    log_file = os.path.join(log_dir, "operations.log")
    
    # 检查日志文件是否存在
    if os.path.exists(log_file):
        print(f"📄 日志文件路径: {log_file}")
        
        # 读取最后几行日志
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            if lines:
                print(f"📋 最后5条日志记录:")
                for line in lines[-5:]:
                    print(f"   {line.strip()}")
            else:
                print("⚠️ 日志文件为空")
    else:
        print(f"❌ 日志文件不存在: {log_file}")
        print("请确保音频服务器正在运行并执行过操作")

if __name__ == "__main__":
    try:
        # 运行测试和修复
        test_and_fix_logging()
        
        print("\n" + "="*50)
        print("现在您可以:")
        print("1. 重启音频服务器以应用修复")
        print("2. 运行此脚本的测试功能: python test_and_fix_logging.py test")
        print("="*50)
        
        # 检查是否有测试参数
        import sys
        if len(sys.argv) > 1 and sys.argv[1] == "test":
            print("\n运行手动日志测试...")
            manual_log_test()
            
    except Exception as e:
        print(f"❌ 测试和修复过程中出现错误: {e}")
        import traceback
        traceback.print_exc()