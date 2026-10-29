<#
.SYNOPSIS
    Registra (ou remove) a tarefa "JARVIS" no Agendador do Windows para iniciar o JARVIS no seu logon.

.DESCRIPTION
    A tarefa roda .venv\Scripts\pythonw.exe -m jarvis: a API sobe sem janela 30 s depois do logon e serve o
    HUD em http://127.0.0.1:8000. Roda com o seu usuário, sem privilégio de administrador, sem limite de tempo
    e é reiniciada até 3 vezes se cair. A saída vai para logs\api-console.log.

    Nada é registrado sem você executar este script. Use -DryRun para só ver o que seria feito.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File .\scripts\registrar-jarvis-logon.ps1 -DryRun
    powershell -ExecutionPolicy Bypass -File .\scripts\registrar-jarvis-logon.ps1
    powershell -ExecutionPolicy Bypass -File .\scripts\registrar-jarvis-logon.ps1 -Remover
#>
[CmdletBinding()]
param(
    [switch]$DryRun,   # só mostra a tarefa, não registra
    [switch]$Remover,  # apaga a tarefa do Agendador (não mexe em nenhum arquivo do JARVIS)
    [string]$Nome = "JARVIS"
)
$ErrorActionPreference = "Stop"

$raiz = Split-Path -Parent $PSScriptRoot
$pythonw = Join-Path $raiz ".venv\Scripts\pythonw.exe"
$usuario = "$env:USERDOMAIN\$env:USERNAME"

if ($Remover) {
    if (Get-ScheduledTask -TaskName $Nome -ErrorAction SilentlyContinue) {
        if ($DryRun) { "Removeria a tarefa '$Nome'."; return }
        Stop-ScheduledTask -TaskName $Nome -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $Nome -Confirm:$false
        "Tarefa '$Nome' removida. O JARVIS não inicia mais no logon."
    } else {
        "Não há tarefa '$Nome' no Agendador."
    }
    return
}

if (-not (Test-Path $pythonw)) {
    throw "Não achei $pythonw. Crie o ambiente: python -m venv .venv; .venv\Scripts\pip install -e .[dev]"
}
if (-not (Test-Path (Join-Path $raiz "jarvis-hud\dist\index.html"))) {
    Write-Warning "HUD sem build: a API vai subir, mas sem a interface. Rode 'npm run build' em jarvis-hud."
}

$acao = New-ScheduledTaskAction -Execute $pythonw -Argument "-m jarvis" -WorkingDirectory $raiz
$gatilho = New-ScheduledTaskTrigger -AtLogOn -User $usuario
$gatilho.Delay = "PT30S"  # dá tempo para a rede e o disco D: ficarem prontos
$config = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -MultipleInstances IgnoreNew -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId $usuario -LogonType Interactive -RunLevel Limited
$descricao = "Inicia o J.A.R.V.I.S. (API + HUD em http://127.0.0.1:8000) no logon de $usuario."

if ($DryRun) {
    "Tarefa que seria registrada (nada foi alterado):"
    "  Nome:      $Nome"
    "  Usuário:   $usuario (sem administrador)"
    "  Gatilho:   no logon, 30 s depois"
    "  Executa:   `"$pythonw`" -m jarvis"
    "  Pasta:     $raiz"
    "  Regras:    sem limite de tempo; reinicia até 3x (1 min); não duplica; roda na bateria"
    "  Log:       $(Join-Path $raiz 'logs\api-console.log')"
    return
}

Register-ScheduledTask -TaskName $Nome -Description $descricao -Action $acao -Trigger $gatilho `
    -Settings $config -Principal $principal -Force | Out-Null
"Tarefa '$Nome' registrada: o JARVIS inicia 30 s depois do seu logon, em http://127.0.0.1:8000."
"Para iniciar agora sem sair da conta:  Start-ScheduledTask -TaskName $Nome"
"Para remover:  powershell -ExecutionPolicy Bypass -File .\scripts\registrar-jarvis-logon.ps1 -Remover"
