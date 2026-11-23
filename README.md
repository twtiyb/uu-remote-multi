# UU Remote Multi / UU 远程 macOS 双开

在 Apple Silicon Mac 上，从本机安装的 UU 远程生成一份独立账户副本。目标用途是在同一个桌面登录两个账户，访问各自 Windows 设备的终端（Shell）。

实验版，仍在本机验证中。已经通过第二账户登录、Windows PowerShell 执行、重启后保留第二账户并重新连接终端的实际测试。UU 自带 CLI 也确认原版与副本拥有不同设备码。

双账户长时间同时保持登录还需复验：测试机器原先残留多个原版主进程，原版曾退出登录，已整理为单一主进程，正在等待原版重新登录。项目暂不宣称已经解决所有并行登录问题。

## 当前支持范围

- Apple Silicon macOS，原版 UU 远程 **4.48.3，构建 635**。
- 严格核对原版主程序 SHA-256；其他版本或修改过的版本会被拒绝。
- 第二份使用独立 Bundle ID、偏好设置、MMKV、共享状态目录、文件锁和钥匙串命名空间。
- 副本进程内使用独立且持久化的硬件 UUID 和 MAC 标识，避免仍以原机身份初始化 UU 客户端。
- 保留原版 App 和数据；不读取或复制原账户凭据。
- 不包含 UU 安装包，不是网易官方项目。

## 使用

需要 Python 3 和 Xcode Command Line Tools（`codesign`、`lipo`）。

```sh
python3 uu_remote_multi.py --launch
```

默认生成 `~/Applications/UU Remote Account 2.app`。也可以指定位置：

```sh
python3 uu_remote_multi.py \
  --source /Applications/UURemote.app \
  --output "$PWD/UU Remote Account 2.app" \
  --launch
```

在原版保留账户一，在副本中登录账户二。工具拒绝覆盖已有副本。重建到其他路径仍会使用相同的第二账户数据目录。

每个账户只运行一个相应的主程序。若此前反复执行过 `open -n`，先退出多余的原版进程；多个原版进程仍会共享同一份账户状态。

登录后可以检查实际运行状态（不显示账户 ID 或设备码）：

```sh
python3 uu_remote_multi.py --check
```

检查会通过 UU 自带 CLI 验证两个账户都已登录、账户不同、设备码不同，且每份程序只有一个主进程。

## 原理

参考 [WeChatTweak](https://github.com/sunnyyoung/WeChatTweak) 和[微信 macOS 客户端无限多开功能实践](https://blog.sunnyyoung.net/wei-xin-macos-ke-hu-duan-wu-xian-duo-kai-gong-neng-shi-jian/)的客户端修改思路。

UU 的多个主进程会共用配置，仅执行 `open -n` 无法隔离账户。本工具复制本机 App，在副本内修改固定长度的应用标识，并对已核对的两个 arm64 共享目录构造例程进行替换。额外编译一个本地动态库，隔离钥匙串读写、兜底重定向共享文件访问，并在副本进程内提供稳定的硬件标识。该库写入副本的 Mach-O 依赖项，启动时无需环境变量。最后为副本及嵌套组件做本地 ad hoc 签名。

原版使用 `com.netease.uuremote`、`/Users/Shared/UURemote` 和 `/Library/Caches/UURemote`；副本使用 `com.netease.uualt002`、`/Users/Shared/UUSecond` 和 `/Library/Caches/UUSecond`。

独立 UUID 保存在 `org.uumulti.identity.profile02` 偏好域中。重建 App 会继续使用该身份；不要在正常使用时重置此域。硬件标识替换仅作用于副本进程，不会修改这台 Mac 的真实 UUID、网卡配置或其他应用。

## 更新与限制

副本经过本地修改，其签名不再是网易的开发者签名。权限和行为需要单独验证。当前目标是主控端双账户和 Windows Shell；不承诺 Mac 被控、自动启动、远程升级、音视频等功能。

不要在副本中直接使用 UU 的内置升级。原版升级后，应等待本工具支持相应版本，再重新生成副本；官方安装包直接覆盖副本会丢失隔离修改。

卸载工具或删除副本不会自动删除账户数据。第二账户数据保存在用户的 `Library` 以及上述独立共享目录内。项目不自动清理这些目录，避免意外删除仍在使用的账户资料。

## 本地验证

```sh
python3 -m unittest discover -s tests -v
```

原生测试验证钥匙串条目的隔离、删除副本条目后原条目仍存在、共享文件访问重定向，以及独立 UUID 跨进程保持不变。完整 UU 的离线初始化也已验证 UUID、客户端 ID、MAC 三项独立且跨重启稳定。Windows Shell 已在副本重启前后执行测试命令并获得正常输出；双账户长时间同时在线尚待原版重新登录后复验。

开发时使用 `./script/build_and_run.sh --verify` 进行重建和启动。脚本只停止生成的副本，并将旧副本保存在 `work/build-backups`，不会停止原版。

## PVE / Windows 设备码重复

另附 [PVE Windows 同码处理](docs/pve-duplicate-ids.md)：已在两份 Windows 10 克隆副本上复现同码，并通过重建 UU 客户端身份及缓存获得不同设备码。两条远控连接同时由 UU CLI 确认为 `connected`，重启后设备码保持不变且能再次同时连接；画面和键鼠仍需人工复核。`tools/windows_uu_identity.ps1` 默认只检查，显式加 `-Apply` 才会备份并重建身份，要求 UU 已退出账户；目前仅支持实测的 Windows UU **4.48.1.5606**。

同时保留只读硬件采集工具，用于比较 PVE 配置与 Windows 实际看到的 UUID、序列号和 MAC。

开源仓库只提交工具源码和文档，不提交生成的 App、日志、账户配置或设备信息。
