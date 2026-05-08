# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 常用命令

```bash
# 安装依赖
pip install -r requirements.txt

# 启动应用
python main.py

# 导入单词表
python scripts/import_words.py 你的单词表.txt

# 优化 FSRS 参数（需额外安装 torch + pandas）
python scripts/optimize.py

# 初始化启动器（仅首次）
python install.py
```

## 架构概览

### 数据流向

```
WordStore (SQLite)
    ↓
WordScheduler          # FSRS 队列调度
    ↓
MemorizeApp            # Qt 主协调器，持有所有定时器
    ↓ 信号
BarBridge (QObject)    # Python ↔ QML 双向通道
    ↓ Signal/Slot
bar.qml                # 界面渲染
    ↓ win32
BarWindow + win32_bar  # 窗口管理与 Win32 剪裁
```

### 关键设计决策

**窗口高度 = 全屏高度**，但通过 `win32_bar.set_bottom_bar_mask()` 用 Win32 Region 只暴露底部 `bar_h` 像素。展开卡片时增大 mask 高度，而非改变窗口大小。这样避免了 TOPMOST 窗口 resize 时的闪烁问题。

**两种单词模式**：
- `push_word`（主动模式）：由 `WordScheduler` 按 FSRS 优先级调度，用于评分
- `push_passive_word`（被动模式）：随机展示于底部条，调用 `mark_seen` 但不影响 FSRS 状态

**FSRS 调度优先级**（`WordScheduler._pick_next`）：
1. 到期单词（`cards.reps > 0 AND due <= now`）
2. 新词（`reps = 0`，无每日配额，用户自定节奏）
3. 兜底：稳定性最低的已复习词

**数据存储**：所有运行数据在 `%APPDATA%\memorize\`（不在项目目录），包括 `words.db`、`config.json`、`memorize.log`、`fsrs_params.json`。

### 模块分工

| 模块 | 职责 |
|------|------|
| `memorize/config.py` | `Config` dataclass + 原子写入（tmp → replace） |
| `memorize/word_store.py` | SQLite CRUD，`rate()` 用 `BEGIN IMMEDIATE` 保证原子性 |
| `memorize/scheduler.py` | 内存队列 `deque`，仅在空时重建，评分后移除当前词 |
| `memorize/qt_app.py` | `MemorizeApp`：三个 `QTimer`（换词 / 提醒 / 自动收起）+ 托盘 |
| `memorize/ui/bar_bridge.py` | `BarBridge(QObject)`：所有 `Signal` 和 `@Slot` 定义 |
| `memorize/ui/bar_window.py` | QML 引擎启动、窗口定位、拖拽处理、Win32 初始化 |
| `memorize/ui/win32_bar.py` | 纯 Win32 ctypes：Region mask、TOPMOST、ToolWindow 样式 |

### 评分整数映射

`_RATING_MAP`（qt_app.py）：`1=Again, 2=Hard, 3=Good, 4=Easy`，与 QML 中按钮顺序一致。

## 注意事项

- **仅支持 Windows**：`win32_bar.py` 直接调用 `ctypes.windll`，无跨平台兜底。
- QML 中通过 `bridge` context property 访问 `BarBridge`，`scaleFactor` 由 Python 计算后注入。
- `win32_bar.setup_toolwindow` 在 `winId()` 可用后才能调用，`BarWindow._setup_win32` 有最多 5 次 200ms 重试。
- 无测试套件，无 lint 配置。
