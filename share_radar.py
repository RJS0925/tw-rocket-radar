# -*- coding: utf-8 -*-
"""
報寶貝火箭隊雷達 - 外網分享與不休眠伺服器管理器
"""

import os
import sys
import time
import subprocess
import re
import socket

def copy_to_clipboard(text):
    try:
        process = subprocess.Popen('clip', stdin=subprocess.PIPE, shell=True)
        process.communicate(text.encode('utf-8'))
        return True
    except Exception:
        return False

def check_port_in_use(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(('127.0.0.1', port)) == 0

def main():
    os.system("cls" if os.name == "nt" else "clear")
    print("=" * 65)
    print("  ⚡ 報寶貝 · 全台灣火箭隊即時情報雷達 (外網分享版)")
    print("  🛡️  特色：完全不休眠、手機秒開零等待、報寶貝台灣IP不封鎖")
    print("=" * 65)
    print()

    base_dir = os.path.dirname(os.path.abspath(__file__))
    cloudflared_path = os.path.join(base_dir, "cloudflared.exe")

    # 1. 檢查並下載 cloudflared
    if not os.path.exists(cloudflared_path):
        print("[-] 正在下載專屬安全通道工具 cloudflared (約需 10 秒)...")
        cmd_dl = "powershell -Command \"Invoke-WebRequest -Uri 'https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe' -OutFile 'cloudflared.exe'\""
        os.system(cmd_dl)

    # 2. 檢查本地後端是否運行
    backend_proc = None
    if not check_port_in_use(5050):
        print("[1/2] 正在啟動本地雷達後端服務 (Port 5050)...")
        backend_proc = subprocess.Popen([sys.executable, "app.py"], cwd=base_dir)
        time.sleep(2)
    else:
        print("[1/2] 本地雷達後端已在背景運行中！")

    # 3. 啟動 Cloudflare Tunnel
    print("[2/2] 正在向 Cloudflare 申請專屬外網網址 (永久不休眠)...")
    print()

    tunnel_proc = subprocess.Popen(
        [cloudflared_path, "tunnel", "--url", "http://127.0.0.1:5050"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="ignore",
        bufsize=1
    )

    url_found = False
    url_pattern = re.compile(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com')

    try:
        for line in iter(tunnel_proc.stdout.readline, ''):
            if not line:
                break
            
            # 尋找網址
            match = url_pattern.search(line)
            if match and not url_found:
                url_found = True
                url = match.group(0)
                copy_to_clipboard(url)
                
                print()
                print("*" * 65)
                print("  🎉【外網專屬網址已成功建立，並已自動複製到剪貼簿！】")
                print()
                print(f"  👉 朋友專屬連線網址： {url}")
                print()
                print("  📌 使用說明：")
                print("  1. 直接去 LINE 或通訊軟體按【Ctrl + V】即可傳給朋友！")
                print("  2. 這個網址『完全不休眠』，朋友在外點開秒讀取，不必等待。")
                print("  3. 只要保持此視窗開著，雷達就會持續 24 小時服務。")
                print("*" * 65)
                print()
            
            # 過濾只顯示關鍵狀態
            if "trycloudflare.com" in line or "Registered tunnel connection" in line or "Connection" in line:
                print(f"  [Cloudflare 狀態] {line.strip()}")

        tunnel_proc.wait()
    except KeyboardInterrupt:
        print("\n正在安全關閉外網通道...")
    finally:
        if tunnel_proc:
            tunnel_proc.terminate()
        if backend_proc:
            backend_proc.terminate()

if __name__ == "__main__":
    main()
