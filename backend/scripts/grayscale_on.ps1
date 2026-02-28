# AURA - Enable Windows Grayscale Color Filter
# Requires Windows 10 1809+ (Color Filters feature)
# Uses registry (user-level, no admin required)

$path = "HKCU:\Software\Microsoft\ColorFiltering"
if (-not (Test-Path $path)) {
    New-Item -Path $path -Force | Out-Null
}
Set-ItemProperty -Path $path -Name "Active" -Value 1 -Type DWord -Force
Set-ItemProperty -Path $path -Name "FilterType" -Value 1 -Type DWord -Force
# FilterType: 0=Off, 1=Grayscale, 2=Invert, 3=Inverted grayscale, 4-6=Color blindness
