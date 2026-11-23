# PVE 中 Windows 的 UU 设备码重复

即使 Windows 分别安装，虚拟硬件仍可能暴露相同的 UUID、序列号或其他标识。不同远控软件的设备识别规则不同，因此 ToDesk 的码不同，不能证明 UU 读取的标识不同。

本目录提供只读检查工具。修复前先比较三台 VM 的实际标识；不根据“用了不同模板”就断定标识已经独立。

在 PVE 节点上，以实际 VMID 替换下列示例数字：

```sh
python3 tools/pve_identity_audit.py 101 102 103 --guest --output /root/uu-identity-audit.json
```

`--guest` 需要三台 Windows 内已有可用的 QEMU Guest Agent。工具不会安装、启用代理。如果没有代理，可分别在 Windows PowerShell 中执行 `tools/windows_identity.ps1`。

报告包含 VM 硬件标识，是私有诊断资料，不要提交到公开仓库或 issue。检查工具不读取 UU 登录令牌，不修改 VM 配置、不重启 Windows、不清理 UU 数据。

处理顺序是：核对实际重复项；备份相关配置；为相应 VM 设置稳定且互不相同的标识；在合适的停机时间让 Windows 读取新硬件；确认 UUID/序列号和 UU 设备码变化；最后同时启动 UU 测试连接。

更改 SMBIOS UUID 时需要保留原 `smbios1` 中的其他字段。仅更新 PVE `vmgenid` 不等于更改 Windows 可见的系统 UUID。磁盘序列号、SMBIOS 序列号和 Windows MachineGuid 也不能相互替代。不要在尚未找出重复来源时批量修改这些值或执行 Sysprep。

当前这些脚本只完成信息采集，不宣称已经修复某一台 PVE 的 UU 设备码。
