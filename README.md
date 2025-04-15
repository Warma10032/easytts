# EasyTTS

一个基于Flask的智能文本转语音(TTS)服务，集成了说话人识别功能，支持一键式多角色对话生成。

项目演示视频：[哔哩哔哩](https://www.bilibili.com/video/BV1eoQfY8Ezc)

目前该项目仍处于早期阶段，正在积极开发中。有任何问题欢迎反馈。

## 功能特点

- 文本转语音：支持将文本转换为自然流畅的语音
- 说话人识别：基于BERT的说话人识别模型，可自动识别对话中的说话人
- 多角色语音：支持为不同角色分配不同的语音
- 文本预处理：智能分句、引号检测等
- Web API支持：提供RESTful API接口
- 跨平台GUI界面：基于PyQt6的图形界面

## 系统要求

- Python <= 3.11
- CUDA支持（用于GPU加速）
- 8GB+ RAM

## 安装说明

### 克隆仓库

```bash
git clone https://github.com/Warma10032/easytts.git
cd easytts
```

### 安装UV

推荐使用 [uv](https://docs.astral.sh/uv/) 作为依赖管理工具。

如果你更想用conda/venv来管理环境也是可以的，我们提供了统一的requirements.txt。

uv安装方法：

```bash
# Windows:
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
# 安装完成后按提示设置环境变量

# macOS/Linux:
# 方法1: curl
curl -LsSf https://astral.sh/uv/install.sh | sh
# 方法2: wget
wget -qO- https://astral.sh/uv/install.sh | sh

# 重要：安装完成后请运行以下命令重新加载配置文件，或者重启命令行 / IDE
source ~/.bashrc  # 如果使用 bash
source ~/.zshrc   # 如果使用 zsh
```

更多 uv 安装方法参考：[Installing uv](https://docs.astral.sh/uv/getting-started/installation/)

确认 uv 已正确安装:

```bash
uv --version
```

### 安装依赖

创建环境并安装依赖:

```bash
# 确保你在项目根目录下运行这个命令
uv sync
# 这个命令将创建一个 `.venv` 虚拟环境，并一键安装好项目所需的包
```

### 下载模型文件

到 [huggingface](https://huggingface.co/Warma10032/chinese-roberta-wwm-ext-large-csi-v1/) 下载模型后

将模型文件放置在项目的根目录的 `model/chinese-roberta-wwm-ext-large-csi-v1/` 目录下

## 使用方法

### 启动服务器

```bash
uv run python app.py
```

服务器默认运行在 `http://localhost:10032`

### 启动GUI客户端

```bash
uv run python main.py
```

## 项目结构

```
.
├── app.py              # Flask服务器主程序
├── main.py             # GUI客户端主程序
├── src/
│   ├── client/         # TTS客户端实现
│   ├── speaker_identification/  # 说话人识别模块
│   ├── ui/             # GUI界面定义
│   └── utils.py        # 工具函数
└── cache/              # 缓存目录
    ├── audio/          # 音频文件缓存
    ├── text/           # 文本文件缓存
    └── speaker_identification/  # 说话人识别结果缓存
```


## 贡献

欢迎提交Issue和Pull Request！

## 致谢

- [Edge-TTS](https://github.com/rany2/edge-tts) - 提供Edge TTS服务支持
- [chinese-roberta-wwm-ext-large](https://github.com/ymcui/Chinese-BERT-wwm) - 中文预训练BERT模型
- [yudiandoris/csi: End-to-End Chinese Speaker Identification](https://github.com/yudiandoris/csi) - 端到端引文说话人识别模块


## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=Warma10032/easytts&type=Date)](https://www.star-history.com/#Warma10032/easytts&Date)