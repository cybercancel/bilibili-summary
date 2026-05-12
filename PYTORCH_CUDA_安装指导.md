# PyTorch CUDA 安装指导

> 为 B站视频总结系统 配置 GPU 加速支持的 PyTorch
> 
> 你的设备：**RTX 4060 Laptop GPU (8GB 显存)** | Python 3.13.2

---

## 一、安装前检查

### 1. 确认 NVIDIA 驱动状态

在 **PowerShell** 中运行：

```powershell
nvidia-smi
```

- ✅ 成功：显示 GPU 信息，记下 **CUDA Version**（如 12.4）
- ❌ 失败：`Failed to initialize NVML` → 尝试重启电脑后再试
- 如果始终失败，但不影响使用（见第三节验证方法）

### 2. 确认 Python 环境

```powershell
python --version
# 预期输出: Python 3.13.2

python -c "import sys; print(sys.executable)"
# 确认路径是: C:\Users\22508\AppData\Local\Programs\Python\Python313\python.exe
```

---

## 二、安装 PyTorch CUDA 版本

### 方法一：官方源（速度慢但最可靠）

```powershell
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
```

> `cu124` = CUDA 12.4，适配大多数 RTX 40 系显卡

### 方法二：清华镜像（推荐，速度快）

```powershell
python -m pip install torch torchvision torchaudio -i https://pypi.tuna.tsinghua.edu.cn/simple
```

> ⚠️ 清华镜像的 torch 可能是 CPU 版本，安装后需验证（见第三节）

### 方法三：指定 CUDA 版本 + 镜像（最推荐）

先查看 PyTorch 官网确认当前推荐版本：[https://pytorch.org/get-started/locally/](https://pytorch.org/get-started/locally/)

然后执行对应的安装命令。

---

## 三、验证安装是否成功

安装完成后，**必须**运行以下命令验证：

```powershell
python -c "import torch; print('PyTorch 版本:', torch.__version__); print('CUDA 可用:', torch.cuda.is_available()); print('CUDA 版本:', torch.version.cuda)"
```

### 预期输出（成功）：

```
PyTorch 版本: 2.6.0+cu124
CUDA 可用: True
CUDA 版本: 12.4
```

### 如果 `CUDA 可用: False`：

1. 确认 NVIDIA 驱动已安装：`nvidia-smi`
2. 如果是远程桌面连接，断开远程后本地运行验证
3. 尝试重新安装 CUDA 版本的 torch（不要用 CPU 版）
4. 检查 `nvcuda.dll` 是否存在：
   ```powershell
   python -c "import ctypes; ctypes.cdll.LoadLibrary('nvcuda.dll'); print('CUDA DLL 可用')"
   ```

---

## 四、配置 B站视频总结系统 使用 GPU

### 1. 确认 `transcriber.py` 自动检测逻辑

打开 `bilibili-summary/core/transcriber.py`，确认有以下代码：

```python
if self.device == "auto":
    try:
        import torch
        device = "cuda" if torch.cuda.is_available() else "cpu"
    except ImportError:
        logger.info("torch 未安装，默认使用 CPU")
        device = "cpu"
```

### 2. 运行测试（用有字幕的视频）

```powershell
cd C:\Users\22508\WorkBuddy\2026-05-12-task-9\bilibili-summary
python main.py
```

选择 BV 号：`BV1xBZYBUEr4`（已知有字幕，可快速测试）

观察日志中的设备信息：
- ✅ `[Transcriber] 使用设备: cuda`
- ❌ `[Transcriber] 使用设备: cpu`

---

## 五、性能对比

| 模式 | 12分钟视频转录时间 | 说明 |
|------|------------------|------|
| CPU 模式 | ~3.5 分钟 | 当前状态 |
| GPU 模式 (RTX 4060) | ~30 秒 | 安装成功后 |

---

## 六、常见问题

### Q1: `nvidia-smi` 报错 `Failed to initialize NVML: Unknown Error`

**原因**：远程桌面 (RDP) 会话中会阻断 NVML 访问  
**解决**：断开远程桌面，在本地电脑上运行验证；或者直接测试 `torch.cuda.is_available()`

### Q2: 安装速度太慢

**解决**：使用清华镜像（方法二），或在本地下载 wheel 文件后离线安装：
1. 访问 https://download.pytorch.org/whl/cu124/torch/
2. 下载对应版本（如 `torch-2.6.0+cu124-cp313-cp313-win_amd64.whl`）
3. `python -m pip install 路径\to\下载的.whl`

### Q3: 安装后 `torch.cuda.is_available()` 仍然是 `False`

**原因**：可能安装了 CPU 版本的 torch  
**解决**：
```powershell
python -m pip uninstall torch torchvision torchaudio -y
python -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu124
```

---

## 七、完成标志

当你看到以下输出时，说明安装成功：

```powershell
python -c "import torch; print(torch.cuda.is_available())"
# 输出: True
```

之后运行 `python main.py` 时，日志会显示 `[Transcriber] 使用设备: cuda`，转录速度会明显提升。
