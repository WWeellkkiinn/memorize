# 把 PWA 打包成可下载的 Android APK

本项目（FastAPI + 纯静态前端 `web/static/`）已完成 PWA 化：

- `web/static/manifest.webmanifest`：应用名 `Memorize 背单词`，`display: standalone`，`start_url: "/"`，含 `icon-192.png` / `icon-512.png` / `icon-maskable-512.png`。
- `web/static/service-worker.js`：缓存 app shell（cache-first，跳过 `/api/`）。
- 服务端路由：`GET /manifest.webmanifest`、`GET /service-worker.js`（见 `web/server.py`）。

本文说明如何在此基础上生成一个可安装、可下载的 Android APK。

## 1. 方案说明

采用 **PWA → TWA（Trusted Web Activity）→ APK**：

TWA 本质是一个 Chrome 浏览器壳，全屏指向你的**线上网站**。APK 内部不打包任何前端代码，只记录"打开哪个域名"。

因此关键结论：

> **前端改动无需重新打包 APK，重新部署线上网站即生效。** 用户下次打开 App 就是新版本（受 service worker 缓存策略影响，必要时更新缓存名即可）。

只有在改**包名 / 图标 / 签名 / 启动 URL** 这类 APK 元信息时才需要重新生成 APK。

## 2. 前置条件

TWA 对线上环境有硬性要求，缺一不可：

- 网站已用 **HTTPS** 部署，有**公网域名**（IP 不行，TWA 校验依赖域名）。
- `/manifest.webmanifest` 与 `/service-worker.js` 可正常访问（本项目已满足）。
- manifest 含 `name`、`icons`（≥192 和 512）、`display: standalone`、`start_url`、`theme_color`、`background_color`（本项目已满足）。
- Chrome DevTools 的 **Lighthouse → PWA** 检查全部通过（重点：可安装、有 service worker、HTTPS）。

> 假设线上域名为 `https://memorize.example.com`，下文命令请替换成你的真实域名。

## 3. 具体步骤

两种生成方式，二选一。新手推荐方式 A（网页点几下即可），需要可复现/可脚本化用方式 B。

### 方式 A：PWABuilder 网站（最简单）

1. 打开 https://www.pwabuilder.com
2. 输入线上域名 `https://memorize.example.com`，点 **Start**。
3. 等待它抓取 manifest / service worker 并评分，按提示补齐缺项（本项目应已达标）。
4. 选择 **Android → Generate Package**。
5. Package 类型选 **Android Package (TWA)**，确认包名（如 `com.example.memorize`）、应用名、版本号。
6. 下载生成的 zip，里面包含：
   - `app-release-signed.apk`（已用 PWABuilder 生成的签名签好，可直接安装）
   - `signing.keystore` + `signing-key-info.txt`（**务必妥善保存**，后续更新 APK 必须用同一个 keystore，否则用户需卸载重装）
   - `assetlinks.json`（见第 4 节）

### 方式 B：@bubblewrap/cli 命令行

需要本地 Node.js 与 JDK（首次运行 Bubblewrap 会引导安装 Android SDK）。

```bash
# 1. 全局或临时安装并初始化（指向线上 manifest）
npx @bubblewrap/cli init --manifest https://memorize.example.com/manifest.webmanifest

# 交互过程中确认：
#   - Application name: Memorize 背单词
#   - Package name: com.example.memorize
#   - Host / Start URL: memorize.example.com  /  /
#   - 首次会提示创建签名 keystore，记下 keystore 路径、别名(alias)、密码

# 2. 构建 APK（会同时输出 app-release-signed.apk）
npx @bubblewrap/cli build

# 3. 后续更新版本号后重新构建
npx @bubblewrap/cli update   # 同步线上 manifest 的改动
npx @bubblewrap/cli build
```

`bubblewrap build` 默认会用 init 时创建的 keystore 自动签名，产出 `app-release-signed.apk`。

### 签名（如需手动签名）

若拿到的是未签名的 `app-release-unsigned.apk`，用 [uber-apk-signer](https://github.com/patrickfav/uber-apk-signer)：

```bash
java -jar uber-apk-signer.jar --apks app-release-unsigned.apk
# 输出 app-release-unsigned-aligned-signed.apk
```

或用已有 keystore 手动 `apksigner`：

```bash
apksigner sign --ks signing.keystore --out memorize.apk app-release-unsigned.apk
```

> 记住对应签名的 **SHA-256 指纹**，第 4 节 assetlinks 要用：
> ```bash
> keytool -list -v -keystore signing.keystore -alias <你的alias>
> ```

### 部署 APK 供下载

把签好名的文件重命名为 `memorize.apk`，放进静态目录：

```
web/static/memorize.apk
```

它会自动通过已挂载的 `/static`（`app.mount("/static", StaticFiles(...))`）暴露为 `/static/memorize.apk`。

如果想要一个更短、带正确 MIME 的下载链接 `/memorize.apk`，在 `web/server.py` 加一个路由（`FileResponse` 已在文件顶部导入）：

```python
@app.get("/memorize.apk")
def download_apk():
    return FileResponse(
        _STATIC / "memorize.apk",
        media_type="application/vnd.android.package-archive",
        filename="memorize.apk",
    )
```

之后用户访问 `https://memorize.example.com/memorize.apk` 即可下载安装。

## 4. assetlinks.json（Digital Asset Links）

TWA 要**去掉顶部浏览器地址栏**（变成真正的全屏 App），必须证明"这个域名授权了这个 APK"。做法是在**域名根**放置 `/.well-known/assetlinks.json`，内容里写 APK 的签名 SHA-256 指纹。指纹不匹配时 App 仍能用，但会显示地址栏。

示例内容（指纹替换成第 3 节 keytool 输出的真实值，包名替换成你的）：

```json
[
  {
    "relation": ["delegate_permission/common.handle_all_urls"],
    "target": {
      "namespace": "android_app",
      "package_name": "com.example.memorize",
      "sha256_cert_fingerprints": [
        "AA:BB:CC:DD:...:FF"
      ]
    }
  }
]
```

把它保存为 `web/static/assetlinks.json`，然后在 `web/server.py` 暴露到固定路径 `/.well-known/assetlinks.json`：

```python
@app.get("/.well-known/assetlinks.json")
def asset_links():
    return FileResponse(
        _STATIC / "assetlinks.json",
        media_type="application/json",
    )
```

部署后用浏览器访问 `https://memorize.example.com/.well-known/assetlinks.json` 确认能拿到 JSON，地址栏才会消失。

> 提示：PWABuilder 和 Bubblewrap 都会在产物里直接给出对应你签名的 `assetlinks.json`，直接拷过来用即可，不用手填指纹。

## 5. 更新维护

| 改动内容 | 是否要重新生成 APK |
|---|---|
| 前端页面、样式、JS、文案、功能逻辑 | **否**，重新部署线上网站即可 |
| service worker 缓存内容 | 否（改 `CACHE` 版本名让旧缓存失效即可） |
| 包名 / 应用名 / 图标 / 启动 URL / 签名 | **是**，需重新 `build` 并保留同一 keystore |

日常迭代基本只动网站。重新生成 APK 时**务必复用最初的 keystore**，否则签名指纹变化会导致：assetlinks 失效（地址栏回来）+ 用户必须卸载旧版重装。

## 6. 已知限制

- **底部系统导航栏颜色固化在 APK 内**：TWA 的 `navigationBarColor` 在打包时写死，线上改 `theme_color` 不会更新它。要改这个颜色，必须重新生成并发布 APK。
- 通过 APK 下载分发（非 Google Play）时，用户首次安装需手动允许"安装未知来源应用"。
- iOS 无此方案对应物，iPhone 用户仍走 Safari「添加到主屏幕」的 PWA 路径。
