# Convenience wrapper only: call the single entry point start-plamo.bat.
param(
    [string]$Model = '0.8b',
    [int]$Port = 8000
)
& (Join-Path $PSScriptRoot 'start-plamo.bat') $Model $Port
