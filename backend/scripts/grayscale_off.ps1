# AURA - Disable Windows Grayscale Color Filter

$path = "HKCU:\Software\Microsoft\ColorFiltering"
if (Test-Path $path) {
    Set-ItemProperty -Path $path -Name "Active" -Value 0 -Type DWord -Force
}
