# Memorize

吸附在桌面底部的背单词悬浮窗。鼠标移上去弹出释义和例句，点一下评分，它会自动记住你什么时候该再复习这个词。

底部常驻一个小条，显示当前单词；鼠标移上去向上弹出详情：中文释义、英文例句、音标，并自动播放有道词典发音。

---

## 效果

- **底部常驻一个小条**，显示当前单词，不挡任何东西
- **鼠标移上去**，向上弹出详情：中文释义、英文例句、音标
- **自动播放发音**，也可点击 🔊 反复收听
- **点评分按钮**（忘了 / 模糊 / 记得 / 轻松），下一个词自动出来
- 基于 **FSRS 遗忘曲线**，评分越高间隔越长，不会浪费时间复习已经会的词

> **隐私提示**：发音功能通过有道词典 API 获取音频，每个被学习的单词会发送到有道服务器。如有顾虑可在 `app.js` 中替换为本地 TTS。

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

词库来自开源项目 [kajweb/dict](https://github.com/kajweb/dict)（MIT License），每个词条包含音标、释义、例句和同义词。

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

### 第三步：导入你的单词表

**方式一：使用内置词单（快速开始）**

仓库自带 `data/cet6_starter.txt`，收录了 1362 个已验证有释义的六级核心词，直接运行：

```
python scripts/import_words.py data/cet6_starter.txt
```

**方式二：使用自己的单词表**

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

**退出：** 底部小条上右键双击

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
| 拖动底部条 | 左右移动位置，松手自动保存；拖到屏幕边缘自动回到中央 |
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
  "passive_mode": true,
  "word_change_interval_sec": 10
}
```

---

## 云端模式（可选）

项目附带一个 FastAPI Web 服务端（`web/server.py`），可以部署到自己的服务器上，用浏览器或桌面端共用同一套复习进度。

### 用浏览器访问

部署后直接在手机或电脑浏览器打开 `https://你的域名`（需配置反向代理，见下方部署说明）。

浏览器端支持：自动播放发音、查看释义例句、评分、音标显示。访问时会弹出 HTTP Basic Auth 登录框，输入 `.env` 中配置的用户名和密码即可。

### 让桌面端接入云端服务器

在 `%APPDATA%\memorize\config.json` 里加入以下字段：

```json
{
  "mode": "server",
  "server_url": "https://你的域名",
  "server_user": "用户名",
  "server_pass": "密码"
}
```

重启应用后，单词和评分记录将直接读写服务器，本地不再使用 SQLite。

### 部署服务端（Docker）

**第一步：** 在项目根目录创建 `.env`：

```
AUTH_USER=你的用户名
AUTH_PASS=你的密码（至少8位）
```

**第二步：** 构建并启动：

```bash
docker compose up -d --build
```

**第三步：** 首次导入词库：

```bash
# 方式一：把 data/cet6.json 复制进容器再导入
docker compose cp data/cet6.json memorize:/app/data/cet6.json
docker compose exec memorize python scripts/import_words.py data/cet6.json

# 方式二：在宿主机运行脚本，直接操作 Docker 卷里的数据库
docker run --rm -v memorize_memorize-db:/data/memorize \
  -v $(pwd)/data:/app/data \
  -v $(pwd):/app \
  python:3.11.12-slim \
  bash -c "pip install fsrs -q && python scripts/import_words.py data/cet6.json"
```

**第四步：** 在 Nginx 或 Caddy 前置 TLS，将 HTTPS 流量反向代理到 `127.0.0.1:8881`。**不要直接将 8881 端口暴露到公网**（Basic Auth 在 HTTP 下明文传输）。

---

## 进阶：个性化记忆曲线

用了一段时间、积累了几百条复习记录后，可以用你自己的数据重新拟合 FSRS 参数，让算法更贴合你的记忆规律：

```
pip install torch pandas
python scripts/optimize.py
```

完成后重启应用即可生效。至少需要 512 条跨天复习记录才有意义（数据不足时自动回退到默认参数）。

---

## 项目结构

```
memorize/
├── main.py                    # 桌面端入口
├── memorize.vbs               # 双击启动（无黑窗口）
├── install.py                 # 初始化启动器（只需运行一次）
├── requirements.txt           # 桌面端依赖
├── requirements-web.txt       # 服务端依赖
├── data/
│   └── cet6_starter.txt       # 内置六级核心词单（1362 词，快速开始用）
├── scripts/
│   ├── import_words.py        # 导入单词表
│   ├── optimize.py            # 用个人复习记录优化 FSRS 参数（需 torch + pandas）
│   └── populate_morphemes.py  # 预计算词根词缀拆分（需 nltk，本地运行）
├── web/
│   ├── server.py              # FastAPI 服务端
│   └── static/                # 网页前端（index.html / app.js / style.css）
└── memorize/
    ├── config.py              # 配置（含云端模式字段）
    ├── word_store.py          # SQLite 词库
    ├── scheduler.py           # FSRS 调度（本地）
    ├── remote_scheduler.py    # HTTP 调度（云端模式）
    ├── runtime_env.py         # 运行环境检测
    ├── qt_app.py              # 桌面端主程序
    └── ui/
        ├── bar.qml            # 界面
        ├── bar_bridge.py      # Python ↔ QML 通信
        ├── bar_window.py      # 窗口管理
        └── win32_bar.py       # Win32 窗口裁剪
```

---

## 依赖

- [PySide6](https://pypi.org/project/PySide6/) — Qt 官方 Python 绑定（桌面端）
- [fsrs](https://github.com/open-spaced-repetition/py-fsrs) — FSRS 遗忘曲线算法
- [FastAPI](https://fastapi.tiangolo.com/) + [uvicorn](https://www.uvicorn.org/) — Web 服务端
- 词库数据来自 [kajweb/dict](https://github.com/kajweb/dict)（MIT License）
- `data/cet6_starter.txt` 内容来源于 kajweb/dict，同为 MIT License

---

## License

[MIT](LICENSE)
