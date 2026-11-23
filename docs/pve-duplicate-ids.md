# PVE 中 Windows 的 UU 设备码重复

在 Windows 10、UU **4.48.1.5606** 的 PVE 克隆副本上，已复现“两台上线后使用同一设备码，其中一台设备码变为未就绪”。重建 UU 的客户端身份及缓存后，两份副本同时取得不同设备码。

实际验证包括：Mac UU 的两条远控连接同时返回 `connected` 且无错误；两台 Windows 分别重启后设备码保持不变；重启后再次同时连接成功。这里的远控连接结论来自 UU 自带 CLI 的实时状态，画面与键鼠操作尚需人工复核。

配置中 `C:\ProgramData\Netease\GameViewer\config.ini` 的 `uuid` 会随克隆复制。只替换 UUID 后，旧身份缓存仍使设备码无法就绪；同时重建身份缓存后才恢复。测试也已把其中一台的磁盘和 SMBIOS 序列号恢复到 QEMU 默认值，它仍取得不同设备码。因此，这次克隆问题的有效处理在 Windows 内完成。

不同模板或重装也出现同码时，仍应采集实际标识并验证重建身份后的结果；这次测试没有覆盖所有安装方式。

## 重建 UU 身份

在**需要新设备码的 Windows 客体内**操作，保留一台原设备不处理。先在 UU 中退出账户，保留主窗口，然后以管理员身份打开 PowerShell。下载并检查本仓库的 `tools/windows_uu_identity.ps1`，先执行只读检查：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows_uu_identity.ps1
```

确认目标正确后执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\windows_uu_identity.ps1 -Apply
```

上述执行策略仅作用于这一次 PowerShell 进程。脚本默认只检查；`-Apply` 才会修改，并要求当前 UU 已退出账户、版本相符且只有一个主进程。

脚本先把以下文件备份到 `C:\ProgramData\UUIdentityBackups` 的独立子目录，再更新 `config.ini` 的 UUID、移走其余三份身份缓存：

| 文件 | 所在位置 |
| --- | --- |
| `config.ini` | `C:\ProgramData\Netease\GameViewer` |
| `user_info.ini` | 同上 |
| `remote_assist_code.ini` | 同上 |
| `setting_guest_anonymous_id.ini` | 实际运行 UU 的用户目录下 `AppData\Local\GameViewer` |

备份目录仅允许 SYSTEM 和本机管理员访问；其中可能有匿名令牌和远控验证码，不要上传。其他设置文件和浏览器缓存保持原样。若写入中途出错，脚本尝试恢复备份，再恢复原先运行的服务。

重开 UU 后等待设备码就绪，在 UU 内重新设置远控验证码，再登录所需账户并重新绑定设备。原验证码配置会重置；需要自定义验证码时请在 UU 内重新设置。原来收藏的旧设备码不会自动指向这份副本。脚本不更改 Windows MachineGuid、SID、网卡、虚拟磁盘或 SMBIOS。

需要手动回退时，先退出 UU、停止 `GameViewerService`，按照备份内 `manifest.json` 的文件映射恢复备份文件，然后启动服务和 UU。回退身份可能重新引入同码冲突，应先关闭其他冲突副本。

自动化管理会话可以加 `-NoLaunch`，修改后在已有 Windows 桌面会话自行重开 UU；脚本不会在服务的 Session 0 中创建桌面窗口。

## 只读硬件检查

不同远控软件可以使用不同标识，因此 ToDesk 的码不同，不能单凭这一点定位 UU 的重复来源。以下工具用于检查硬件层面的其他可能原因。

在 PVE 节点上，以实际 VMID 替换下列示例数字：

```sh
python3 tools/pve_identity_audit.py 101 102 103 --guest --output /root/uu-identity-audit.json
```

`--guest` 需要三台 Windows 内已有可用的 QEMU Guest Agent。工具不会安装、启用代理。如果没有代理，可分别在 Windows PowerShell 中执行 `tools/windows_identity.ps1`。

报告包含 VM 硬件标识，是私有诊断资料，不要提交到公开仓库或 issue。检查工具不读取 UU 登录令牌，不修改 VM 配置、不重启 Windows、不清理 UU 数据。

若后续实验证明 UU 仍因某个硬件字段重复而冲突，应先备份配置，再为相应 VM 设置稳定且互不相同的标识。在合适的停机时间让 Windows 读取新硬件，比较实际标识与 UU 设备码，最后同时启动 UU 验证连接。

更改 SMBIOS UUID 时需要保留原 `smbios1` 中的其他字段。仅更新 PVE `vmgenid` 不等于更改 Windows 可见的系统 UUID。磁盘序列号、SMBIOS 序列号和 Windows MachineGuid 也不能相互替代。不要在尚未找出重复来源时批量修改这些值或执行 Sysprep。

`pve_identity_audit.py` 和 `windows_identity.ps1` 始终只读；只有单独执行 `windows_uu_identity.ps1 -Apply` 才会重建当前 Windows 的 UU 身份。
