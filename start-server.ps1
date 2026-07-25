$ErrorActionPreference = "Stop"

Set-Location -LiteralPath $PSScriptRoot
python -u app.py @args
