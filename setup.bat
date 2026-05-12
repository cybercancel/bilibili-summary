@echo off
chcp 65001 >nul
cls

echo ========================================
echo B站视频总结系统 v2.0 环境初始化
echo ========================================

REM 检查 Python 版本
python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未检测到 Python，请先安装 Python 3.9+
    pause
    exit /b 1
)

REM 创建虚拟环境（可选）
set /p CREATE_VENV=是否创建虚拟环境? (Y/N):
if /i "%CREATE_VENV%"=="Y" (
    echo 创建虚拟环境...
    python -m venv venv
    call venv\Scripts\activate.bat
)

REM 升级 pip
echo 升级 pip...
python -m pip install --upgrade pip

REM 安装依赖
echo 安装依赖...
pip install -r requirements.txt

REM 检查 FFmpeg
where ffmpeg >nul 2>&1
if errorlevel 1 (
    echo [警告] 未检测到 FFmpeg，请确保已安装 FFmpeg 并添加到 PATH
    echo 下载地址: https://ffmpeg.org/download.html
)

REM 检查 CUDA
nvidia-smi >nul 2>&1
if errorlevel 1 (
    echo [提示] 未检测到 NVIDIA GPU，Whisper 将使用 CPU 运行
) else (
    echo [OK] 检测到 NVIDIA GPU，可使用 GPU 加速
)

echo ========================================
echo 环境初始化完成！
echo ========================================
echo.
echo 使用方法:
echo   单视频: python main.py --url "https://www.bilibili.com/video/BVxxxxxx"
echo   批量处理: python batch_process.py -f urls.txt
echo.
pause