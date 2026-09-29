# i茅台启动器

用 Python 写的安卓 APP（Kivy + pyjnius，Buildozer 打包 APK）。
当前版本只有一个功能：**一键启动手机本地已安装的 i茅台 APP**。

## 工程结构

```
i茅台启动器/
├── main.py               # 主入口（Buildozer 要求文件名必须为 main.py）
├── app_ui.py             # 界面模块（主界面布局与控件）
├── android_launcher.py   # 启动模块（pyjnius 调安卓原生 Intent）
├── font_setup.py         # 中文字体注册（否则中文显示方块）
├── config.py             # 全局配置（包名等常量）
├── extra_manifest.xml    # Android 11+ 包可见性声明（<queries>）
├── buildozer.spec        # APK 打包配置
├── requirements.txt      # 电脑端预览用依赖
├── fonts/                # （可选）放兜底中文字体 ttf
└── .github/workflows/
    └── build-apk.yml     # GitHub 云端免费打 APK
```

## 一、电脑端预览界面（可选，手机上才能真正启动）

```powershell
python -m pip install kivy
python main.py
```

> 注意：电脑端预览需要 Python 3.10 ~ 3.13（Kivy 的 Windows 依赖暂不支持
> Python 3.14）。本机若是 3.14 可跳过预览——**不影响打 APK**，Buildozer
> 构建时会使用自己内置的 Python；界面逻辑已通过模拟环境测试。

## 二、打包成 APK

Buildozer **不能在 Windows 上直接运行**，二选一：

### 方式 A：GitHub 云端打包（推荐，免费，不用装 Linux）

1. 注册/登录 GitHub，新建一个**公开仓库**（公开仓库 CI 分钟数免费无限）。
2. 把本文件夹（`i茅台启动器`）**里面的全部内容**上传到仓库根目录：

   ```powershell
   cd "C:\Users\Administrator\Desktop\maotai\实际代码\i茅台启动器"
   git init
   git add .
   git commit -m "init i茅台启动器"
   git branch -M main
   git remote add origin https://github.com/你的用户名/imtlauncher.git
   git push -u origin main
   ```

3. push 后仓库的 **Actions** 页面会自动开始构建（首次约 15~30 分钟）。
4. 构建完成后，点进那次运行记录，在页面底部 **Artifacts** 下载
   `imtlauncher-apk`（解压后即为 APK）。

### 方式 B：本机 WSL2 打包

```powershell
wsl --install -d Ubuntu
```

重启电脑、设置好 Ubuntu 用户名密码后，在 Ubuntu 窗口里执行：

```bash
sudo apt update
sudo apt install -y git zip unzip openjdk-17-jdk python3-pip autoconf \
  libtool pkg-config zlib1g-dev libncurses-dev libstdc++6 cmake \
  libffi-dev libssl-dev build-essential ccache
pip3 install --user --upgrade buildozer
echo 'export PATH=$PATH:~/.local/bin' >> ~/.bashrc && source ~/.bashrc

# 注意：不要直接在 /mnt/c（Windows 盘）上构建，极慢且易出错，
# 先把代码复制到 WSL 家目录：
cp -r "/mnt/c/Users/Administrator/Desktop/maotai/实际代码/i茅台启动器" ~/imtlauncher
cd ~/imtlauncher
buildozer -v android debug

# 构建完成后把 APK 复制回桌面：
cp bin/*.apk /mnt/c/Users/Administrator/Desktop/
```

## 三、安装到手机

- **简单方式**：把 APK 传到手机（微信/QQ/数据线均可），点击安装，
  按提示允许"安装未知来源应用"。
- **adb 方式**（手机开启"开发者选项 → USB 调试"）：

  ```powershell
  adb install -r imtlauncher-0.1-arm64-v8a-debug.apk
  ```

## 四、验证 i茅台包名（拉起失败时排查用）

手机连电脑执行：

```powershell
adb shell pm list packages | findstr moutai
```

正常应输出 `package:com.moutai.mall`。若将来 i茅台改包名导致拉不起来，
APP 界面底部可直接改包名，或用上述命令查到新包名后更新 `config.py`。

## 常见问题

1. **显示"未检测到 i茅台"**：确认手机已安装 i茅台；安卓 11+ 必须靠
   `extra_manifest.xml` 里的 `<queries>` 声明，已在 buildozer.spec 配置好。
2. **老手机装不上/闪退**：把 buildozer.spec 的 `android.archs` 改为
   `arm64-v8a, armeabi-v7a` 重新打包。
3. **中文显示方块**：极个别精简系统 ROM 没有中文字体，往 `fonts/` 目录
   放一个中文字体 ttf（如 Noto Sans SC、思源黑体，OFL 协议可免费使用），
   重新打包即可。
4. **首次构建很慢**：Buildozer 要下载 Android SDK/NDK 和编译 Python，
   属正常现象；GitHub 云端构建有缓存，第二次会快很多。
