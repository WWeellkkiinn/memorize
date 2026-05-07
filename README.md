# Memorize

吸附在桌面底部的背单词悬浮窗。鼠标移上去弹出释义和例句，点一下评分，它会自动记住你什么时候该再复习这个词。

![示意：底部吸附的单词条，hover 后弹出释义和评分按钮]

---

## 效果

- **底部常驻一个小条**，显示当前单词和音标，不挡任何东西
- **鼠标移上去**，向上弹出详情：中文释义、英文例句、中文例句
- **点评分按钮**（忘了 / 模糊 / 记得 / 轻松），下一个词自动出来
- 每隔 30 分钟（可调）**自动弹出**一次，不用你去找它
- 基于 **FSRS 遗忘曲线**，评分越高间隔越长，不会浪费时间复习已经会的词

---

## 环境要求

- Windows 10 / 11
- Python 3.11+（建议用你日常用的环境，装过 pip 就行）

---

## 第一次使用

### 第一步：安装依赖

```
pip install -r requirements.txt
```

### 第二步：下载词库数据

词库来自开源项目 [kajweb/dict](https://github.com/kajweb/dict)，每个词条包含音标、释义、例句和同义词。

**步骤：**

1. 打开 https://github.com/kajweb/dict/tree/master/book
2. 找到你需要的词库文件（`.zip` 格式），点击文件名进入详情页，再点 **Download** 下载
3. 把下载的 zip 文件用解压软件打开，取出里面的 `.json` 文件
4. 重命名为 `cet6.json`，放到本项目的 `data/cet6.json`

**常用词库文件名对照：**

| 文件名 | 内容 | 词数 |
|--------|------|-----:|
| `1521164668667_CET6_1.zip` | 六级真题核心词 | 1228 |
| `1524052554766_CET6_2.zip` | 六级英语词汇 | 2078 |
| `1521164633851_CET6_3.zip` | 新东方六级词汇 | 2345 |
| `1521164635506_CET4_2.zip` | 四级英语词汇 | 3739 |
| `1521164675301_GaoZhong_2.zip` | 高中英语词汇（正序）| 3668 |
| `1521164679263_GaoZhong_3.zip` | 新东方高中词汇 | 2340 |

**建议：** 同时下载多个（如 CET6_1/2/3），`import_words.py` 只用一个 json，可以手动把多个 zip 内的 json 合并，或直接取内容最全的那个（CET6_3 词数最多）。

> 如果你的单词表里有不少基础词在 CET6 词库里匹配不到，可以额外用 `CET4_2` 或 `GaoZhong_2` 再跑一遍补全——导入脚本只更新空白字段，不会覆盖已有数据（实际上是 `INSERT OR IGNORE`，已有词不会被重复插入）。

### 第三步：导入你的单词表

准备一个 txt 文件，每行一个单词，比如：

```
abandon
accomplish
acquire
...
```

然后运行：

```
python scripts/import_words.py 你的单词表.txt
```

会自动去词库里匹配音标、释义、例句，没匹配上的词也会导入（只是暂时没有释义）。

### 第四步：初始化启动器

```
python install.py
```

这一步会记录你当前 Python 的路径，之后双击 vbs 就能启动了。

---

## 日常使用

**启动：** 双击 `memorize.vbs`（无黑窗口，后台静默运行）

**退出：** 系统托盘右键 → 退出，或者在底部小条上右键双击

---

## 操作说明

| 操作 | 效果 |
|------|------|
| 鼠标移到底部条上 | 弹出当前词的详情卡 |
| 鼠标移开 | 300ms 后自动收起 |
| 点「忘了」 | FSRS 记录失败，明天再复习 |
| 点「模糊」 | 间隔稍微拉长 |
| 点「记得」 | 正常间隔 |
| 点「轻松」 | 大幅拉长间隔，很久后再出现 |
| 拖动底部条 | 左右移动位置，松手自动保存 |
| 右键双击底部条 | 退出程序 |

---

## 配置

数据和配置文件在 `%APPDATA%\memorize\`（即 `C:\Users\你的用户名\AppData\Roaming\memorize\`）：

| 文件 | 说明 |
|------|------|
| `config.json` | 所有设置 |
| `words.db` | 单词库和复习记录（SQLite） |
| `memorize.log` | 运行日志 |

`config.json` 可以直接用文本编辑器改，改完重启生效：

```json
{
  "passive_mode": true,          // 开启被动模式（底部条自动轮换单词）
  "active_mode": true,           // 开启主动提醒（定时自动弹出）
  "word_change_interval_sec": 60, // 底部条多少秒换一个词
  "reminder_interval_min": 30,   // 主动提醒间隔（分钟）
  "auto_dismiss_sec": 8,         // 主动弹出后多少秒没操作自动收起
  "daily_new_words": 20          // 每天最多引入多少个新词
}
```

---

## 项目结构

```
memorize/
├── main.py               # 入口
├── memorize.vbs          # 双击启动（无黑窗口）
├── install.py            # 初始化（只需运行一次）
├── requirements.txt
├── data/
│   └── cet6.json         # 词库数据（需自行下载放入）
├── scripts/
│   └── import_words.py   # 导入单词表
└── memorize/
    ├── config.py         # 配置
    ├── word_store.py     # SQLite 词库
    ├── scheduler.py      # FSRS 调度
    ├── qt_app.py         # 主程序
    └── ui/
        ├── bar.qml       # 界面
        ├── bar_bridge.py # Python ↔ QML 通信
        └── bar_window.py # 窗口管理
```

---

## 依赖

- [PySide6](https://pypi.org/project/PySide6/) — Qt 官方 Python 绑定
- [fsrs](https://github.com/open-spaced-repetition/py-fsrs) — FSRS 遗忘曲线算法
- 词库数据来自 [kajweb/dict](https://github.com/kajweb/dict)（MIT License）
