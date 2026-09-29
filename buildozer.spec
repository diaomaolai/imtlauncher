[app]

# 应用信息
title = i茅台启动器
package.name = imtlauncher
package.domain = org.personal

# 源码目录（必须包含 main.py）
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,xml,ttf,ttc
source.exclude_dirs = bin,buildozer,.github

# 版本号
version = 0.1.0

# 依赖：python3 + kivy 界面 + pyjnius 调安卓原生 API
requirements = python3,kivy,pyjnius

# 竖屏、不全屏（保留状态栏）
orientation = portrait
fullscreen = 0

# Android 构建配置
# 如首次构建下载 SDK/NDK 失败，可把下面 api/ndk 两行注释掉，
# 使用 python-for-android 当前版本自带的已验证默认值。
#android.api = 35
android.minapi = 24
#android.ndk = 25b

# 只打 arm64-v8a：近 5 年的手机均支持，构建更快、APK 更小。
# 老手机需要 32 位时改为：arm64-v8a, armeabi-v7a
android.archs = arm64-v8a

# Android 11+ 包可见性：声明要检测/启动的 i茅台
android.extra_manifest_xml = extra_manifest.xml

# 兜底扫描全部已安装应用需要（个人自用、不上架 Google Play；
# 上架 Google Play 会被限制，侧载安装不受影响）
android.permissions = QUERY_ALL_PACKAGES

# 自动接受 SDK 许可、启用 AndroidX
android.accept_sdk_license = True
android.enable_androidx = True

# 日志级别（2 = debug，方便排查问题）
log_level = 2
