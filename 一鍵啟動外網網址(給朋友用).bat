@echo off
chcp 65001 >nul
title 報寶貝火箭隊即時情報雷達 - 外網分享版
cd /d "%~dp0"
python share_radar.py
pause
