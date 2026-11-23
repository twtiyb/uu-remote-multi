# Read-only: collect identifiers relevant to duplicate remote-control device IDs.
# No account tokens, passwords, or UU configuration contents are read.
$ErrorActionPreference = 'Stop'
$product = Get-CimInstance Win32_ComputerSystemProduct
$bios = Get-CimInstance Win32_BIOS
$board = Get-CimInstance Win32_BaseBoard
$processors = @(Get-CimInstance Win32_Processor | ForEach-Object { $_.ProcessorId })
$disks = @(Get-CimInstance Win32_DiskDrive | ForEach-Object {
    [ordered]@{ Model = $_.Model; SerialNumber = $_.SerialNumber }
})
$network = @(Get-CimInstance Win32_NetworkAdapterConfiguration -Filter 'IPEnabled=True' | ForEach-Object {
    [ordered]@{ Description = $_.Description; MACAddress = $_.MACAddress }
})
$machineGuid = (Get-ItemProperty -LiteralPath 'HKLM:\SOFTWARE\Microsoft\Cryptography' -Name MachineGuid).MachineGuid
[ordered]@{
    ComputerName = $env:COMPUTERNAME
    SystemUUID = $product.UUID
    SystemIdentifyingNumber = $product.IdentifyingNumber
    BIOSSerial = $bios.SerialNumber
    BaseboardSerial = $board.SerialNumber
    ProcessorIds = $processors
    Disks = $disks
    Network = $network
    WindowsMachineGuid = $machineGuid
} | ConvertTo-Json -Depth 6 -Compress
