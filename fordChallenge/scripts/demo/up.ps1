<#
.SYNOPSIS
    Sobe o SpecRadar inteiro com um comando: banco, migracoes, seed, API e web app.

.DESCRIPTION
    Um comando, do zero a tela: prepara a base do onboarding (migracoes, catalogo, as
    quatro fichas com evidencia, os alertas do Fogo Amigo e o dado de demonstracao marcado
    `is_simulated=true`), garante as quatro identidades de papel, constroi o web app se ele
    ainda nao estiver construido, sobe a API e o worker em processos que sobrevivem ao fim
    deste script, confere o `/health` e a pagina inicial, e imprime as URLs.

    Nao ha login nem senha (D-204): a ferramenta abre direto na Consulta e o papel e um
    seletor na barra lateral, guardado no navegador.

    O worker sobe junto de proposito: o documento do cliente sai por job, e sem worker a
    cena do Copiloto para em "pendente" — foi o primeiro defeito que o ensaio da demo
    pegou (docs/demo/ROTEIRO_15SET.md).

    Banco: `data/onboarding/onboarding.db`, proprio e descartavel. NAO toca `data/dev.db`.
    Duas razoes: rodar o onboarding duas vezes tem de dar os mesmos numeros (uma
    apresentacao depende disso), e `seed --simulated-alerts N` soma N alertas a cada
    chamada — num banco reaproveitado a fila do Radar cresceria a cada `up`.

    Rede: nenhuma. `REPLAY_MODE=1` bloqueia socket e as fontes vem dos snapshots salvos.

.PARAMETER Refazer
    Apaga a base do onboarding e monta tudo de novo. Use depois de `git pull` ou quando os
    numeros da tela nao casarem com o roteiro.

.PARAMETER RefazerWeb
    Reconstroi o web app (`npm ci && npm run build`) mesmo que `web/dist` exista.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\demo\up.ps1

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\demo\up.ps1 -Refazer -RefazerWeb
#>
[CmdletBinding()]
param(
    [switch]$Refazer,
    [switch]$RefazerWeb
)

$ErrorActionPreference = 'Stop'

# A raiz do repositorio sai do caminho DESTE arquivo, nunca do diretorio corrente: o
# script tem de funcionar chamado de qualquer lugar.
$RAIZ = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
Set-Location $RAIZ

$PASTA    = Join-Path $RAIZ 'data\onboarding'
$LOGS     = Join-Path $PASTA 'logs'
$PROCS    = Join-Path $PASTA 'processos.json'
$BANCO    = Join-Path $PASTA 'onboarding.db'
$PORTA    = 8000
$HOSTNAME = '127.0.0.1'
$BASE     = "http://${HOSTNAME}:${PORTA}"

function Titulo($texto) {
    Write-Host ''
    Write-Host ('=' * 78) -ForegroundColor DarkGray
    Write-Host $texto -ForegroundColor Cyan
    Write-Host ('=' * 78) -ForegroundColor DarkGray
}
function Passo($texto) { Write-Host "-- $texto" -ForegroundColor White }
function Ok($texto)    { Write-Host "   ok: $texto" -ForegroundColor Green }
function Aviso($texto) { Write-Host "   aviso: $texto" -ForegroundColor Yellow }
function Erro($texto)  { Write-Host "   ERRO: $texto" -ForegroundColor Red }

# ---------------------------------------------------------------- 0. pre-requisitos
Titulo 'SPECRADAR — SUBINDO TUDO'

Passo 'conferindo o que a maquina tem'

$python = Join-Path $RAIZ '.venv\Scripts\python.exe'
if (-not (Test-Path $python)) {
    Erro "nao existe .venv. Rode primeiro:  uv sync"
    exit 1
}
Ok "python do projeto: .venv\Scripts\python.exe"

# Disco: o projeto ja parou uma vez por `ENOSPC` no meio de uma escrita (MANHA.md §4).
# Avisar antes vale mais que descobrir no meio das migracoes.
$livreGB = [math]::Round((Get-PSDrive C).Free / 1GB, 2)
if ($livreGB -lt 2) {
    Aviso "so $livreGB GB livres em C:. O build do web app e as migracoes podem falhar."
    Aviso "libere espaco:  npm cache clean --force  e  uv cache clean"
} else {
    Ok "$livreGB GB livres em C:"
}

$temNode = $null -ne (Get-Command node -ErrorAction SilentlyContinue)
if ($temNode) { Ok "node $(node --version)" } else { Aviso 'node ausente: o web app so sobe se web\dist ja estiver construido' }

# Porta ocupada e a falha mais comum de segunda execucao: a API antiga ainda esta de pe e
# a nova morre com "address already in use", num log que ninguem abre.
$ocupada = Get-NetTCPConnection -LocalPort $PORTA -State Listen -ErrorAction SilentlyContinue
if ($ocupada) {
    Aviso "a porta $PORTA ja esta em uso (PID $($ocupada[0].OwningProcess))."
    Aviso "derrube o que esta la antes:  powershell -File scripts\demo\down.ps1"
    exit 1
}
Ok "porta $PORTA livre"

New-Item -ItemType Directory -Force -Path $PASTA | Out-Null
New-Item -ItemType Directory -Force -Path $LOGS  | Out-Null

# ------------------------------------------------------------------------ 1. o banco
# A URL sai do PYTHON, nao do caminho do shell. Defeito real e corrigido (D-148): montada
# a mao no Git Bash, `sqlite:///$(pwd)/...` fica com quatro barras e o SQLite cria o banco
# na RAIZ do drive — o script passava, e o banco ficava no lugar errado.
$BANCO_URL = & $python -c "import pathlib,sys; print('sqlite:///' + pathlib.Path(sys.argv[1]).resolve().as_posix())" $BANCO
$env:DATABASE_URL = $BANCO_URL
$env:PYTHONUTF8   = '1'
$env:REPLAY_MODE  = '1'
$env:LLM_FAKE     = '1'

if ($Refazer -and (Test-Path $BANCO)) {
    # O arquivo do SQLite pode ficar preso alguns instantes depois de o processo morrer.
    # Tentar tres vezes antes de desistir, e desistir com o motivo em portugues: a mensagem
    # crua do PowerShell ("RemoveFileSystemItemIOError") nao diz a ninguem o que fazer.
    $apagado = $false
    for ($tentativa = 1; $tentativa -le 3; $tentativa++) {
        try {
            Remove-Item -LiteralPath $BANCO -Force -ErrorAction Stop
            $apagado = $true
            break
        } catch {
            Start-Sleep -Milliseconds 700
        }
    }
    if ($apagado) {
        Ok 'base anterior do onboarding apagada (-Refazer)'
    } else {
        Erro "nao consegui apagar $BANCO — algum processo ainda o tem aberto."
        Erro 'derrube tudo primeiro:  powershell -ExecutionPolicy Bypass -File scripts\demo\down.ps1'
        exit 1
    }
}

$modo = @()
if (Test-Path $BANCO) {
    Passo 'base do onboarding ja existe: reaproveitando (use -Refazer para montar de novo)'
    $modo = @('--so-usuarios')
}

Passo 'preparando a base'
& $python (Join-Path $RAIZ 'scripts\demo\preparar_base.py') --banco $BANCO_URL @modo --sem-papeis
if ($LASTEXITCODE -ne 0) {
    Erro 'o preparo da base falhou. Leia as linhas FALHOU acima; nada foi subido.'
    exit 1
}

# ---------------------------------------------------------------------- 2. o web app
$indice = Join-Path $RAIZ 'web\dist\index.html'
if ($RefazerWeb -or -not (Test-Path $indice)) {
    if (-not $temNode) {
        Erro 'o web app nao esta construido e node nao existe nesta maquina.'
        Erro 'a API sobe de qualquer forma; a tela em /app vai dar 404.'
    } else {
        Passo 'construindo o web app (leva alguns minutos na primeira vez)'
        Push-Location (Join-Path $RAIZ 'web')
        try {
            if (Test-Path 'node_modules') { npm run build } else { npm ci; if ($?) { npm run build } }
        } finally { Pop-Location }
        if (Test-Path $indice) { Ok 'web\dist construido' } else { Erro 'o build do web app falhou; /app vai dar 404' }
    }
} else {
    Ok 'web app ja construido (use -RefazerWeb para reconstruir)'
}

# --------------------------------------------------------- 3. API e worker, destacados
# Os dois processos precisam sobreviver ao fim deste script. Como isso e feito aqui — e por
# que NAO com `Start-Process -RedirectStandardOutput`, que foi a primeira tentativa e
# travou de verdade:
#
# DEFEITO MEDIDO. Quando qualquer um dos tres fluxos e redirecionado, o PowerShell usa
# `UseShellExecute=$false`, e o .NET cria o processo com `bInheritHandles=TRUE`: o filho
# herda TODOS os handles herdaveis do pai, inclusive o handle de escrita do pipe de saida
# do proprio script. O `python.exe` do `.venv` ainda piora o quadro — ele e um trampolim
# que abre o interpretador de verdade como FILHO e repassa os handles. Resultado: com a
# saida do `up.ps1` indo para um pipe (`up.ps1 | tee`, CI, qualquer captura), o pipe nunca
# fecha e o comando NUNCA RETORNA, mesmo com a API de pe e respondendo. Medido: dez
# minutos de espera com `/health` 200 desde o primeiro segundo.
#
# A correcao: um arquivo `.cmd` por processo, aberto por `Start-Process` SEM nenhum
# `-RedirectStandard*`. Sem redirecionamento o PowerShell usa `ShellExecuteEx`, que nao
# herda handle nenhum, e o proprio `cmd` cuida de escrever o log. De brinde, o `.cmd` fixa
# o diretorio e as variaveis de ambiente: quem for depurar pode dar dois cliques nele e ver
# o mesmo processo subir, sem depender do que estava exportado no shell.
#
# `uvicorn` sem `--reload`: o recarregador sobe supervisor + filho, e o PID guardado aqui
# nao seria o que serve HTTP — o `down` mataria o pai e deixaria a porta presa. Onboarding
# nao precisa de recarga automatica.
Passo 'subindo a API e o worker'

$logApi    = Join-Path $LOGS 'api.log'
$logWorker = Join-Path $LOGS 'worker.log'

# O pedido de parada: um arquivo. O `down` o cria ANTES de matar, e o laco de supervisao
# o le a cada volta. Sem ele, matar o worker faria o proprio supervisor levanta-lo de volta
# — e o `down` nunca terminaria.
$FLAG_PARAR = Join-Path $LOGS 'parar.flag'
Remove-Item -LiteralPath $FLAG_PARAR -Force -ErrorAction SilentlyContinue

function IniciarDestacado {
    <#
      `-Vigiar` envolve o comando num laco que o levanta de novo se ele cair.

      Por que (12/09/2026): um avaliador pediu o documento do cliente e a tela girou ate
      desistir. O worker tinha morrido em algum momento depois da subida, e nada o
      levantava: `Start-Process` e chamada unica, e a unica conferencia de vida acontecia
      no segundo em que o `up` terminava.

      O laco e `cmd`, e nao um servico do Windows: a demo roda numa maquina de trabalho, e
      um portao que exige instalar um supervisor e um portao que ninguem liga.
    #>
    param([string]$Rotulo, [string[]]$Argumentos, [string]$Log, [switch]$Vigiar)

    $arquivo = Join-Path $LOGS "iniciar_$Rotulo.cmd"
    $comando = '"' + $python + '" ' + ($Argumentos -join ' ') + " >> `"$Log`" 2>&1"
    $corpo = if ($Vigiar) {
        @(
            ':laco',
            "if exist `"$FLAG_PARAR`" goto fim",
            $comando,
            "if exist `"$FLAG_PARAR`" goto fim",
            "echo [%date% %time%] $Rotulo caiu; subindo de novo em 2 s >> `"$Log`"",
            'timeout /t 2 /nobreak > nul',
            'goto laco',
            ':fim'
        )
    } else {
        @($comando)
    }
    $linhas = @(
        '@echo off',
        "rem Gerado por scripts\demo\up.ps1. Pode ser executado a mao para depurar.",
        "cd /d `"$RAIZ`"",
        "set DATABASE_URL=$BANCO_URL",
        'set PYTHONUTF8=1',
        'set REPLAY_MODE=1',
        'set LLM_FAKE=1',
        # O Pesquisador (WP-41) sobe ligado na demo, em modo replay: as respostas de busca
        # vem de `tests/fixtures/search`, gravadas com as URLs reais dos snapshots. A
        # apresentacao nao pode depender de o buscador estar de pe, de haver saldo na
        # conta, nem de a internet do auditorio funcionar.
        'set RESEARCH_ENABLED=1',
        'set BENCHMARK_ENABLED=1',
        'set SEARCH_PROVIDER=replay'
    ) + $corpo
    # Codepage ANSI: e a que o `cmd.exe` usa para ler o arquivo de lote. UTF-8 com BOM
    # faria o `cmd` engolir o BOM como parte do primeiro comando.
    [System.IO.File]::WriteAllLines($arquivo, $linhas, [System.Text.Encoding]::Default)

    Start-Process -FilePath $arquivo -WindowStyle Hidden | Out-Null
    return $arquivo
}

$cmdApi    = IniciarDestacado -Rotulo 'api'    -Log $logApi    -Argumentos @('-m','uvicorn','api.app.main:app','--host',$HOSTNAME,'--port',"$PORTA")
$cmdWorker = IniciarDestacado -Rotulo 'worker' -Log $logWorker -Argumentos @('-m','pipeline.cli','worker') -Vigiar

# Os PIDs sao DESCOBERTOS pela linha de comando, nao devolvidos pelo `Start-Process`: o que
# ele devolveria e o `cmd.exe` intermediario, e o `.venv\python.exe` acrescenta mais um
# nivel. O `down` precisa dos PIDs reais, senao mata o embrulho e deixa a porta presa.
function PidsDaLinha([string]$padrao) {
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -like "*$padrao*" } |
        Select-Object -ExpandProperty ProcessId
}

$pidsApi = @(); $pidsWorker = @()
for ($tentativa = 1; $tentativa -le 20; $tentativa++) {
    $pidsApi    = @(PidsDaLinha 'uvicorn api.app.main:app')
    $pidsWorker = @(PidsDaLinha 'pipeline.cli worker')
    if ($pidsApi.Count -gt 0 -and $pidsWorker.Count -gt 0) { break }
    Start-Sleep -Milliseconds 500
}

@{
    api        = $pidsApi
    worker     = $pidsWorker
    porta      = $PORTA
    banco      = $BANCO_URL
    log_api    = $logApi
    log_worker = $logWorker
    cmd_api    = $cmdApi
    cmd_worker = $cmdWorker
} | ConvertTo-Json | Set-Content -LiteralPath $PROCS -Encoding utf8

if ($pidsApi.Count -eq 0)    { Erro 'nao encontrei o processo da API' }    else { Ok "API nos PIDs $($pidsApi -join ', ')" }
if ($pidsWorker.Count -eq 0) { Erro 'nao encontrei o processo do worker' } else { Ok "worker nos PIDs $($pidsWorker -join ', ')" }

# --------------------------------------------------------------------- 4. conferencia
Passo 'conferindo /health e a pagina inicial do web app'

$saude = $null
for ($tentativa = 1; $tentativa -le 40; $tentativa++) {
    try {
        $r = Invoke-WebRequest -Uri "$BASE/api/v1/health" -UseBasicParsing -TimeoutSec 3
        if ($r.StatusCode -eq 200) { $saude = $r.Content; break }
    } catch { Start-Sleep -Milliseconds 500 }
}

if ($null -eq $saude) {
    Erro "a API nao respondeu em $BASE/api/v1/health depois de 20 s."
    Erro "o log esta em $logApi"
    if (Test-Path $logApi) { Get-Content $logApi -Tail 15 | ForEach-Object { Write-Host "   | $_" -ForegroundColor DarkGray } }
    exit 1
}
Ok "/health respondeu 200 -> $saude"

try {
    $app = Invoke-WebRequest -Uri "$BASE/app" -UseBasicParsing -TimeoutSec 5
    if ($app.StatusCode -eq 200) { Ok "/app respondeu 200 ($($app.RawContentLength) bytes de HTML)" }
} catch {
    Erro "/app nao respondeu ($($_.Exception.Message)). O web app pode nao estar construido."
}

$workerVivo = $pidsWorker | Where-Object { Get-Process -Id $_ -ErrorAction SilentlyContinue }
if ($workerVivo) {
    Ok "worker de pe (PID $($workerVivo -join ', ')) — o documento do cliente sai por job e precisa dele"
} else {
    Erro "o worker morreu. Log em $logWorker"
    if (Test-Path $logWorker) { Get-Content $logWorker -Tail 10 | ForEach-Object { Write-Host "   | $_" -ForegroundColor DarkGray } }
}

# ---------------------------------------------------------------------- 5. as URLs
Titulo 'ESTA DE PE — AS URLS'

Write-Host ''
Write-Host '   Entrada (abre direto na Consulta; nao ha login):' -ForegroundColor White
Write-Host "     $BASE/app" -ForegroundColor Cyan
Write-Host ''
Write-Host '   As telas, na ordem do passeio guiado:' -ForegroundColor White
foreach ($par in @(
    @('consulta  ', 'pedir um veiculo pelo nome'),
    @('radar     ', 'a fila de prioridade e o Fogo Amigo'),
    @('matriz    ', 'onde ganhamos, empatamos, perdemos e nao sabemos'),
    @('saude     ', 'cobertura por montadora e as divergencias'),
    @('showroom  ', 'o perfil do cliente e o argumentario'),
    @('insights  ', 'win/loss das conversas de showroom'),
    @('simulador ', 'e se o concorrente baixar 5%?')
)) {
    Write-Host ("     $BASE/app/" + $par[0].Trim().PadRight(11) + '  ' + $par[1]) -ForegroundColor Gray
}
Write-Host ''
Write-Host '   Aba de seguranca (a mesma resposta pela API, se uma tela travar):' -ForegroundColor White
Write-Host "     $BASE/docs" -ForegroundColor Cyan
Write-Host ''

& $python (Join-Path $RAIZ 'scripts\demo\preparar_base.py') --banco $BANCO_URL --so-papeis

Write-Host '   Para derrubar tudo:' -ForegroundColor White
Write-Host '     powershell -ExecutionPolicy Bypass -File scripts\demo\down.ps1' -ForegroundColor Cyan
Write-Host ''
Write-Host "   Logs: $logApi  e  $logWorker" -ForegroundColor DarkGray
Write-Host "   Banco desta sessao: $BANCO_URL" -ForegroundColor DarkGray
Write-Host ''
