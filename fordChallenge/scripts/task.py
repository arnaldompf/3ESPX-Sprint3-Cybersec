#!/usr/bin/env python
"""Executor de tarefas do SpecRadar em Python puro.

Substitui o GNU make no Windows (ver DECISOES_NOITE.md D-06). Os alvos sao os
mesmos do CLAUDE.md; o Makefile delega para este arquivo.

    python scripts/task.py <alvo> [WP=07 | 07]

Alvos: up down migrate api worker test lint fmt eval verify verify-quick
       web-test web-smoke qa golden
       seed sync help
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
COMPOSE = ROOT / "infra" / "docker-compose.yml"


# --------------------------------------------------------------------------- util
def _c(code: str, text: str) -> str:
    if os.environ.get("NO_COLOR") or not sys.stdout.isatty():
        return text
    return "\033[" + code + "m" + text + "\033[0m"


def info(msg: str) -> None:
    print(_c("36", "[task] " + msg), flush=True)


def warn(msg: str) -> None:
    print(_c("33", "[task] " + msg), flush=True)


def fail(msg: str, code: int = 1) -> int:
    print(_c("31", "[task] " + msg), file=sys.stderr, flush=True)
    return code


#: Forcado em todo subprocesso. Sem isso, o console do Windows usa cp1252 e qualquer
#: print com acento ou com "≥" derruba o comando com UnicodeEncodeError — foi o que
#: aconteceu com `task.py eval`, que morria na tabela de metas do eval.
ENV_UTF8 = {"PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}


def run(cmd, *, cwd=None, env=None, check=True) -> int:
    printable = cmd if isinstance(cmd, str) else " ".join(cmd)
    info(printable)
    full_env = {**os.environ, **ENV_UTF8, **(env or {})}
    rc = subprocess.call(cmd, cwd=str(cwd or ROOT), env=full_env)
    if rc != 0 and check:
        raise SystemExit(fail("falhou (rc=" + str(rc) + "): " + printable, rc))
    return rc


def has(binary: str) -> bool:
    return shutil.which(binary) is not None


def uv() -> list:
    """uv como executavel ou como modulo (pip install uv nao garante o .exe no PATH)."""
    if has("uv"):
        return ["uv"]
    return [sys.executable, "-m", "uv"]


def uv_run(args: list, **kw) -> int:
    return run([*uv(), "run", *args], **kw)


def docker_up() -> bool:
    """True se o daemon do Docker responde."""
    if not has("docker"):
        return False
    devnull = subprocess.DEVNULL
    return subprocess.call(["docker", "ps"], stdout=devnull, stderr=devnull) == 0


def bash() -> str | None:
    """Git Bash: necessario para os scripts scripts/verify/WP-XX.sh."""
    candidatos_windows = (
        r"C:\Program Files\Git\bin\bash.exe",
        r"C:\Program Files (x86)\Git\bin\bash.exe",
    )
    # `C:\Windows\System32\bash.exe` é o WSL, não o Git Bash. Ele enxerga a API
    # Win32 por outra interface de rede e fazia o smoke concluir que o servidor local
    # nunca subiu. No Windows, prefira explicitamente o executável que esta função promete.
    if os.name == "nt":
        for cand in candidatos_windows:
            if Path(cand).exists():
                return cand
    found = shutil.which("bash")
    if found:
        return found
    for cand in candidatos_windows:
        if Path(cand).exists():
            return cand
    return None


def load_dotenv() -> None:
    """Carrega .env sem sobrescrever o ambiente ja definido."""
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


#: Todo nome de variavel que o `pipeline.llm` aceita como chave de provedor. A mesma lista
#: de `tests/conftest.py` — e ha teste conferindo que as duas cobrem `pipeline/llm.py`.
CHAVES_DE_PROVEDOR = (
    "LLM_API_KEY",
    # A chave da IA alternativa (13/09/2026). Sem ela aqui, `make eval` e `make test`
    # rodariam com o segundo provedor vivo, e o fallback mudaria o numero medido sem
    # ninguem ver: um eval que cai para outra conta nao esta medindo o mesmo sistema.
    "LLM_API_KEY_ALT",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "DEEPSEEK_API_KEY",
    "MOONSHOT_API_KEY",
    "KIMI_API_KEY",
)


def replay_env() -> None:
    """Testes e eval sempre deterministicos (CLAUDE.md / docs/09).

    **O provedor tambem e fixado, e isso nao e zelo.** A fixture de LLM e indexada por
    `hash(modelo, campos, prompt)` (`pipeline/llm.py`), e as gravadas trazem o modelo
    historico do projeto, a Anthropic. Com `LLM_MODEL=kimi-k2.6` no `.env` desta maquina, a
    chave muda, **nenhuma fixture casa** e o pipeline segue em frente com os campos vazios:
    `make eval` passava a medir 102/109 em vez de 104/109 e grounding 105/105 em vez de
    107/107, sem um erro sequer. O numero do eval nao pode depender do `.env` de quem roda.

    A chave tambem sai do ambiente: com `LLM_FAKE=1` ela nao seria usada, mas um comando
    que desligue o modo fake no meio nao deve encontrar credencial de verdade pendurada.
    """
    os.environ["REPLAY_MODE"] = "1"
    os.environ["LLM_FAKE"] = "1"
    for nome in CHAVES_DE_PROVEDOR:
        os.environ.pop(nome, None)
    os.environ["LLM_PROVIDER"] = "anthropic"
    os.environ.pop("LLM_MODEL", None)


# ------------------------------------------------------------------------- alvos
def t_up(_arg) -> int:
    """Sobe o Postgres do compose; sem daemon, segue em SQLite (D-05)."""
    (ROOT / "data").mkdir(exist_ok=True)
    if docker_up():
        if not COMPOSE.exists():
            return fail(str(COMPOSE) + " nao existe (WP-00 cria)")
        run(["docker", "compose", "-f", str(COMPOSE), "up", "-d"])
        info("Postgres de pe. Aponte DATABASE_URL=postgresql+psycopg://... no .env")
        return 0
    warn("daemon do Docker indisponivel -> dev/teste em SQLite (DECISOES_NOITE.md D-05).")
    warn("Postgres continua o alvo de producao; infra/docker-compose.yml esta no repo.")
    return 0


def t_down(_arg) -> int:
    if docker_up() and COMPOSE.exists():
        return run(["docker", "compose", "-f", str(COMPOSE), "down"], check=False)
    warn("nada para derrubar (Docker indisponivel).")
    return 0


def t_migrate(_arg) -> int:
    load_dotenv()
    if not (ROOT / "api" / "alembic.ini").exists():
        return fail("api/alembic.ini nao existe (WP-03 cria)")
    (ROOT / "data").mkdir(exist_ok=True)
    return uv_run(["alembic", "-c", "api/alembic.ini", "upgrade", "head"], check=False)


def t_api(_arg) -> int:
    load_dotenv()
    host = os.environ.get("API_HOST", "127.0.0.1")
    port = os.environ.get("API_PORT", "8000")
    return uv_run(
        ["uvicorn", "api.app.main:app", "--reload", "--host", host, "--port", port],
        check=False,
    )


def t_worker(_arg) -> int:
    load_dotenv()
    return uv_run(["python", "-m", "pipeline.cli", "worker"], check=False)


def limpar_basetemp() -> None:
    """Apaga `.tmp/pytest` antes da suite. Medido em 13/09/2026.

    O `pyproject` fixa `--basetemp=.tmp/pytest`, e no Windows uma pasta daquela arvore
    fica presa quando uma rodada anterior e interrompida (ou quando o antivirus ainda a
    segura). A partir dai **toda** fixture `tmp_path` falha com `PermissionError [WinError
    32]` — foram **642 erros** numa rodada, todos com cara de defeito de codigo, nenhum
    sendo. O portao mentia, e mentia no sentido caro: vermelho sem causa.

    Apagar e barato e sem risco: a arvore e descartavel por definicao. O que nao da para
    apagar (ainda preso) e ignorado — se estiver mesmo travado, o erro volta, e ai ele e
    informacao de verdade.
    """
    import shutil

    shutil.rmtree(ROOT / ".tmp" / "pytest", ignore_errors=True)


def t_test(arg) -> int:
    load_dotenv()
    replay_env()
    limpar_basetemp()
    target = [arg] if arg else ["tests"]
    return uv_run(["pytest", "-q", *target], check=False)


def t_lint(_arg) -> int:
    rc = run([*uv(), "run", "ruff", "check", "."], check=False)
    rc2 = run([*uv(), "run", "ruff", "format", "--check", "."], check=False)
    return rc or rc2


def t_fmt(_arg) -> int:
    run([*uv(), "run", "ruff", "format", "."], check=False)
    return run([*uv(), "run", "ruff", "check", "--fix", "."], check=False)


def t_eval(_arg) -> int:
    load_dotenv()
    replay_env()
    (ROOT / "reports").mkdir(exist_ok=True)
    return uv_run(
        [
            "python",
            "-m",
            "pipeline.cli",
            "eval",
            "--gabarito",
            "gabarito/gabarito_v1.json",
            "--replay",
        ],
        check=False,
    )


def t_seed(arg) -> int:
    load_dotenv()
    extra = arg.split() if arg else []
    return uv_run(["python", "-m", "pipeline.cli", "seed", *extra], check=False)


def t_verify(arg) -> int:
    wp = (arg or os.environ.get("WP") or "").strip()
    if not wp:
        return fail("uso: python scripts/task.py verify WP=07")
    if wp.upper().startswith("WP-"):
        wp = wp[3:]
    wp = wp.zfill(2)
    script = ROOT / "scripts" / "verify" / ("WP-" + wp + ".sh")
    if not script.exists():
        return fail(str(script.relative_to(ROOT)) + " nao existe")
    sh = bash()
    if not sh:
        return fail("bash nao encontrado (instale o Git Bash)")
    load_dotenv()
    return run([sh, str(script)], check=False)


def t_web_smoke(_arg) -> int:
    """As 8 rotas nos 4 papeis, num Chromium de verdade (D-188).

    Sai 0 com um aviso quando falta `web/dist` ou o Chromium — o proprio script decide
    isso e imprime SALTADO. Ele nao pode ser obrigatorio num clone recem-feito, e nao
    pode ser silencioso quando salta.
    """
    sh = bash()
    if not sh:
        warn("web-smoke: bash nao encontrado (instale o Git Bash); saltado")
        return 0
    return run([sh, "scripts/verify/web-smoke.sh"], check=False)


def _npm() -> str | None:
    """O `npm` do PATH. No Windows o executavel e `npm.cmd`."""
    return shutil.which("npm") or shutil.which("npm.cmd")


def t_qa(_arg) -> int:
    """A regressao de tela: os 45 testes de `qa/e2e`, num Chromium de verdade (11/09/2026).

    **Cada teste aqui nasceu de um defeito medido.** O `web-smoke` responde "as oito telas
    abrem nos quatro papeis"; esta suite responde "a cena do roteiro acontece": o login sai
    de `/login`, o contador de fontes nao e zero, a data da evidencia e a da coleta, o
    documento nao gira para sempre sem worker, trocar de papel esquece o papel anterior.

    Precisa do sistema de pe (`scripts/demo/up.ps1`), como o `web-smoke`. Sai 0 com aviso
    quando falta `npm` ou `qa/node_modules` — um portao que so passa depois de um download
    de 90 MB nao e portao, e a proxima pessoa o desliga. Instalar:

        cd qa && npm install && npx playwright install chromium
    """
    npm = _npm()
    if npm is None:
        warn("qa: npm nao encontrado; saltado")
        return 0
    if not (ROOT / "qa" / "node_modules" / "@playwright" / "test").exists():
        warn("qa: `qa/node_modules` ausente; saltado (rode `cd qa && npm install`)")
        return 0
    return run([npm, "test", "--silent"], cwd=ROOT / "qa", check=False)


def t_web_test(_arg) -> int:
    """Os testes de tela em Vitest (`web/src/**/*.test.tsx`), mais a checagem de tipos.

    **Entrou no `verify-quick` em 12/09/2026, e a descoberta de que ele estava de fora foi
    constrangedora:** os 312 testes de tela existiam, passavam, e nenhum portao os rodava.
    O `verify-quick` chamava lint + pytest + `web-smoke` + `qa` — e `web-smoke` so abre as
    rotas num Chromium, nao executa Vitest. Na pratica, qualquer mudanca em `web/src/lib/`
    podia quebrar dezenas de testes de unidade sem que nada ficasse vermelho.

    `tsc --noEmit` vem junto pelo mesmo motivo: o tipo `Etiqueta` e uma uniao fechada, e e
    o compilador que lista todo `Record<Etiqueta, ...>` incompleto quando ela cresce.

    Sai 0 com aviso quando falta `npm` ou `web/node_modules` — mesma regra do `qa`: um
    portao que so passa depois de um `npm ci` nao e portao num clone recem-feito, e nao
    pode ser silencioso quando salta.
    """
    npm = _npm()
    if npm is None:
        warn("web-test: npm nao encontrado; saltado")
        return 0
    if not (ROOT / "web" / "node_modules").exists():
        warn("web-test: `web/node_modules` ausente; saltado (rode `cd web && npm ci`)")
        return 0
    rc_tipos = run([npm, "exec", "--", "tsc", "--noEmit"], cwd=ROOT / "web", check=False)
    rc_teste = run([npm, "test", "--silent"], cwd=ROOT / "web", check=False)
    return rc_tipos or rc_teste


def t_golden(_arg) -> int:
    """O ensaio de palco: as 13 cenas do roteiro, gravadas em `reports/demo/golden_path.webm`.

    Nao entra no `verify-quick` de proposito: leva perto de dois minutos e grava video. E o
    plano B da apresentacao, e se regera quando a demo muda.
    """
    npm = _npm()
    if npm is None:
        return fail("golden: npm nao encontrado")
    if not (ROOT / "qa" / "node_modules" / "@playwright" / "test").exists():
        return fail("golden: rode `cd qa && npm install` antes")
    return run([npm, "run", "golden", "--silent"], cwd=ROOT / "qa", check=False)


def t_verify_quick(_arg) -> int:
    load_dotenv()
    replay_env()
    rc_lint = t_lint(None)
    limpar_basetemp()
    rc_test = run([*uv(), "run", "pytest", "-q", "-m", "not slow", "tests"], check=False)
    # O smoke de tela entra aqui desde 11/09/2026. O motivo esta em D-184: a suite
    # inteira passava verde com a tela abrindo BRANCA no navegador, porque nem o
    # `TestClient` nem o `curl` aplicam CSP. Um portao que nao abre navegador nao
    # responde a pergunta "a tela funciona?", e era essa a pergunta.
    # Os testes de tela em Vitest + `tsc --noEmit`. Estavam FORA de todo portao ate
    # 12/09/2026: 312 testes verdes que nada executava automaticamente.
    rc_unidade = t_web_test(None)
    rc_web = t_web_smoke(None)
    # A regressao de tela entra aqui desde 11/09/2026 (ensaio de QA). O `web-smoke` diz
    # que as telas abrem; esta suite diz que as cenas do roteiro acontecem — e foi ela que
    # pegou o login preso em `/login`, o contador de fontes em zero e a fila do analista
    # aparecendo para o vendedor depois de trocar de papel.
    rc_qa = t_qa(None)
    print()
    info(
        "verify-quick: lint="
        + ("ok" if rc_lint == 0 else "FALHOU")
        + " testes="
        + ("ok" if rc_test == 0 else "FALHOU")
        + " tela="
        + ("ok" if rc_unidade == 0 else "FALHOU")
        + " rotas="
        + ("ok" if rc_web == 0 else "FALHOU")
        + " qa="
        + ("ok" if rc_qa == 0 else "FALHOU")
    )
    return rc_lint or rc_test or rc_unidade or rc_web or rc_qa


def t_sync(_arg) -> int:
    return run([*uv(), "sync"], check=False)


def t_help(_arg) -> int:
    print(__doc__)
    print("Alvos disponiveis: " + " ".join(sorted(TARGETS)))
    return 0


TARGETS = {
    "up": t_up,
    "down": t_down,
    "migrate": t_migrate,
    "api": t_api,
    "worker": t_worker,
    "test": t_test,
    "lint": t_lint,
    "fmt": t_fmt,
    "eval": t_eval,
    "seed": t_seed,
    "verify": t_verify,
    "verify-quick": t_verify_quick,
    "web-smoke": t_web_smoke,
    "web-test": t_web_test,
    "qa": t_qa,
    "golden": t_golden,
    "sync": t_sync,
    "help": t_help,
}


def main(argv: list) -> int:
    if not argv:
        return t_help(None)
    target, rest = argv[0], argv[1:]
    if target not in TARGETS:
        return fail("alvo desconhecido: " + target + ". Alvos: " + " ".join(sorted(TARGETS)))
    arg = None
    for token in rest:
        if token.startswith("WP="):
            arg = token[3:]
        elif arg is None:
            arg = token
        else:
            arg = arg + " " + token
    try:
        return TARGETS[target](arg)
    except SystemExit as exc:
        return int(exc.code or 0)
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
