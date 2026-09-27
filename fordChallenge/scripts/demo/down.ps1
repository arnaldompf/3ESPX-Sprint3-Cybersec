<#
.SYNOPSIS
    Derruba o que o `up.ps1` subiu: a API e o worker.

.DESCRIPTION
    Le os PIDs de `data/onboarding/processos.json` e para os dois processos. Se o arquivo
    nao existir (ou os PIDs ja tiverem morrido), procura pela porta — porque o sintoma que
    importa e "a porta 8000 esta presa", e ele tem de ser resolvido mesmo quando o registro
    se perdeu.

    O banco do onboarding NAO e apagado: derrubar nao e desfazer. Para montar tudo de novo,
    `up.ps1 -Refazer`.

.PARAMETER ApagarBanco
    Apaga tambem `data/onboarding/onboarding.db`.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\demo\down.ps1
#>
[CmdletBinding()]
param([switch]$ApagarBanco)

$ErrorActionPreference = 'Stop'

$RAIZ  = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$PASTA = Join-Path $RAIZ 'data\onboarding'
$PROCS = Join-Path $PASTA 'processos.json'
$BANCO = Join-Path $PASTA 'onboarding.db'

function Ok($t)    { Write-Host "   ok: $t" -ForegroundColor Green }
function Aviso($t) { Write-Host "   aviso: $t" -ForegroundColor Yellow }

function PararArvore {
    <#
      Para um processo e todos os descendentes, de baixo para cima.

      Por que NAO `taskkill /T /F`: ele escreve em stderr quando o PID ja morreu, e o
      PowerShell embrulha cada linha de stderr de executavel nativo num ErrorRecord. Com
      `$ErrorActionPreference = 'Stop'`, isso ABORTA o script — foi o que aconteceu: o
      `down` parou no meio, o banco ficou aberto, e o `up -Refazer` seguinte nao conseguiu
      apagar o arquivo. Enumerar os filhos por CIM e chamar `Stop-Process` resolve sem
      nenhum processo externo, e o `-ErrorAction SilentlyContinue` funciona de verdade.

      A arvore importa porque o `python.exe` do `.venv` e um trampolim: ele abre o
      interpretador de verdade como filho. Matar so o pai deixaria a porta presa.
    #>
    param([int]$Alvo)

    $filhos = Get-CimInstance Win32_Process -Filter "ParentProcessId=$Alvo" -ErrorAction SilentlyContinue
    foreach ($filho in $filhos) { PararArvore -Alvo ([int]$filho.ProcessId) }
    Stop-Process -Id $Alvo -Force -ErrorAction SilentlyContinue
}

# O pedido de parada vem ANTES de qualquer kill: o worker sobe dentro de um laco de
# supervisao (`up.ps1 -Vigiar`), e matar o processo sem avisar faria o laco levanta-lo de
# volta na volta seguinte. O arquivo e o unico jeito de dizer "desta vez e para valer".
$FLAG_PARAR = Join-Path $PASTA 'logs\parar.flag'
New-Item -ItemType Directory -Path (Split-Path $FLAG_PARAR) -Force -ErrorAction SilentlyContinue | Out-Null
New-Item -ItemType File -Path $FLAG_PARAR -Force -ErrorAction SilentlyContinue | Out-Null

Write-Host ''
Write-Host 'SPECRADAR — DERRUBANDO' -ForegroundColor Cyan
Write-Host ('=' * 78) -ForegroundColor DarkGray

$porta = 8000
$parados = 0

if (Test-Path $PROCS) {
    $registro = Get-Content -LiteralPath $PROCS -Raw | ConvertFrom-Json
    if ($registro.porta) { $porta = [int]$registro.porta }
    # `$pid` NAO pode ser usado como nome aqui: e variavel automatica do PowerShell (o PID
    # do proprio shell), e escrever nela mata o terminal de quem roda o script.
    #
    # `api` e `worker` sao LISTAS: o `python.exe` do `.venv` e um trampolim que abre o
    # interpretador de verdade como filho, entao cada servico aparece com dois PIDs. Matar
    # so o primeiro deixaria o segundo com a porta na mao — foi assim que o `up` seguinte
    # comecou a sair com "porta em uso".
    $alvos = [ordered]@{ 'API' = @($registro.api); 'worker' = @($registro.worker) }
    foreach ($nome in $alvos.Keys) {
        foreach ($alvo in $alvos[$nome]) {
            if (-not $alvo) { continue }
            $p = Get-Process -Id $alvo -ErrorAction SilentlyContinue
            if ($p) {
                PararArvore -Alvo ([int]$alvo)
                Ok "$nome parado (PID $alvo e filhos)"
                $parados++
            } else {
                Aviso "$nome (PID $alvo) ja nao estava rodando"
            }
        }
    }
    Remove-Item -LiteralPath $PROCS -Force
} else {
    Aviso "nao ha registro em $PROCS — procurando pela porta"
}

# Rede de seguranca: qualquer coisa ainda escutando na porta. Sem isto, um `up` anterior
# que perdeu o registro deixa a porta presa e o proximo `up` sai com "porta em uso" sem
# nenhum caminho de saida.
$restou = Get-NetTCPConnection -LocalPort $porta -State Listen -ErrorAction SilentlyContinue
foreach ($conexao in $restou) {
    $p = Get-Process -Id $conexao.OwningProcess -ErrorAction SilentlyContinue
    if ($p) {
        PararArvore -Alvo ([int]$p.Id)
        Ok "processo na porta $porta parado ($($p.ProcessName), PID $($p.Id))"
        $parados++
    }
}

# Segunda rede: um worker orfao nao aparece na porta (ele nao escuta nada) e, sem registro,
# ficaria rodando para sempre consumindo a fila de um banco que ninguem mais olha.
$orfaos = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -like '*pipeline.cli worker*' -or $_.CommandLine -like '*uvicorn api.app.main:app*' }
foreach ($orfao in $orfaos) {
    PararArvore -Alvo ([int]$orfao.ProcessId)
    Ok "processo orfao do SpecRadar parado (PID $($orfao.ProcessId))"
    $parados++
}

if ($parados -eq 0) { Aviso 'nada estava rodando' }

if ($ApagarBanco -and (Test-Path $BANCO)) {
    Remove-Item -LiteralPath $BANCO -Force
    Ok 'banco do onboarding apagado'
} elseif (Test-Path $BANCO) {
    Write-Host "   o banco continua em $BANCO (derrubar nao e desfazer)" -ForegroundColor DarkGray
}

Write-Host ''
Write-Host '   Para subir de novo:  powershell -ExecutionPolicy Bypass -File scripts\demo\up.ps1' -ForegroundColor Cyan
Write-Host ''
