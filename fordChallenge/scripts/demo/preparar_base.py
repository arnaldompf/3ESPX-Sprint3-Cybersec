"""Prepara a base do onboarding: migracoes, catalogo, fichas, alertas e os quatro papeis.

Por que este arquivo existe em Python, e nao duplicado em `.ps1` e `.sh`: a sequencia de
preparo tem doze passos, e manter doze passos identicos em dois shells e como manter duas
copias de uma regra — a segunda divergiria da primeira na primeira correcao. Os dois
scripts (`up.ps1` e `up.sh`) sao casca: eles cuidam de processo (subir API e worker,
esperar o `/health`, imprimir URL) e chamam este arquivo para tudo que e banco.

O que ele NAO faz: nao toca `data/dev.db`. O banco do onboarding e proprio
(`data/onboarding/onboarding.db`), descartavel, e existe justamente para que rodar o
onboarding duas vezes de os MESMOS numeros — o que uma apresentacao precisa, e o que um
banco acumulado nao da (`seed --simulated-alerts N` soma N alertas a cada chamada; nao e
idempotente, e nem deveria ser: quem pede tres alertas de demonstracao quer tres).

Rede: ZERO. `REPLAY_MODE=1` bloqueia socket; as fontes vem de `tests/fixtures/snapshots/`.
`LLM_FAKE=1` garante custo real zero. Sao os mesmos dois interruptores do ensaio da demo.

Credenciais: NENHUMA, e nao ha o que esconder. Desde D-204 a ferramenta nao tem login: a
API nao pede token e o papel vem do cabecalho `X-Role`, escolhido no seletor da barra
lateral. Os quatro papeis existem como IDENTIDADE — a linha de `users` a que
`showroom_sessions.vendedor_id` aponta e o nome que a barra mostra —, e nascem sem senha
utilizavel. `DEMO_PASSWORD` deixou de ser sorteada e gravada no `.env`.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys

RAIZ = pathlib.Path(__file__).resolve().parents[2]
ENV = RAIZ / ".env"


#: As CINCO versoes com snapshot salvo. Sem elas a tela mostra ficha vazia — que e a
#: resposta honesta antes de o pipeline rodar, e nao serve para um passeio guiado.
#:
#: A Ranger Limited entrou em 10/09/2026, coletada ao vivo: e a Ford **diesel de topo**
#: que a cena 8 compara com a Hilux SRX Plus. Ate 09/09 o par da cena era Raptor x Hilux,
#: que cai no aviso de par nao comparavel — a Raptor e gasolina e de outro proposito.
#:
#: Os nomes sao os CANONICOS (`pipeline/version_names.py`), os mesmos que o catalogo grava
#: desde a migracao 0006. Ate 10/09 a Hilux entrava aqui como "SRX Plus AT (Cabine Dupla)"
#: e a S10 como "High Country" enquanto a linha vigente tinha "S10 High Country": eram duas
#: linhas em `versions` para o mesmo carro, e o seletor oferecia primeiro a vazia.
VERSOES = (
    ("Ford", "Ranger", "Raptor 3.0 V6 Bi-turbo 4WD AT"),
    ("Ford", "Ranger", "Limited 3.0 V6 Diesel 4WD AT"),
    ("Toyota", "Hilux", "SRX Plus AT"),
    ("Volkswagen", "Amarok", "V6 Extreme"),
    ("Chevrolet", "S10", "High Country"),
)

#: Quantos registros de demonstracao. Os mesmos numeros do ensaio (`replay_demo.sh`), para
#: que o onboarding e a demo contem a mesma historia.
ALERTAS_SIMULADOS = 3
SESSOES_SIMULADAS = 40


def _uv() -> list[str]:
    """`uv` como executavel ou como modulo: `pip install uv` nao garante o `.exe` no PATH."""
    from shutil import which

    return ["uv"] if which("uv") else [sys.executable, "-m", "uv"]


def carregar_env() -> None:
    """Le o `.env` sem sobrescrever o que ja esta no ambiente.

    Mesma precedencia do `scripts/task.py`: quem exporta a variavel na mao manda mais que o
    arquivo. E o que permite ao `up.ps1` escolher o banco do onboarding sem editar o `.env`.
    """
    if not ENV.exists():
        return
    for bruta in ENV.read_text(encoding="utf-8").splitlines():
        linha = bruta.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


def rodar(argumentos: list[str], *, filtro: str | None = None) -> int:
    """Roda um comando do projeto e mostra so as linhas que interessam.

    O `filtro` existe porque `seed` e `extract` sao conversadores e o onboarding tem de
    caber numa tela. Codigo de saida diferente de zero e sempre reportado.
    """
    processo = subprocess.run(
        argumentos,
        cwd=RAIZ,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    saida = (processo.stdout or "") + (processo.stderr or "")
    for linha in saida.splitlines():
        if filtro is None or filtro in linha:
            print(f"   {linha.rstrip()}")
    if processo.returncode != 0:
        print(f"   FALHOU (codigo {processo.returncode})")
        cauda = [linha for linha in saida.splitlines() if linha.strip()][-8:]
        for linha in cauda:
            print(f"   | {linha.rstrip()}")
    return processo.returncode


def criar_papeis() -> list[str]:
    """Cria as quatro identidades de papel que faltarem.

    Delega para `api.app.papel.garantir_identidades`, que e o mesmo codigo que a API usa
    quando alguem chega com um `X-Role` cujo papel ainda nao existe no banco. Uma copia so:
    duas divergiriam no e-mail ou no marcador de "sem senha", e a divergencia apareceria
    como uma sessao de showroom apontando para um usuario que ninguem ve na barra.
    """
    from sqlmodel import Session

    from api.app.db import engine
    from api.app.papel import DOMINIO_DOS_PAPEIS, garantir_identidades

    with Session(engine()) as sessao:
        criados = garantir_identidades(sessao)
        sessao.commit()
    if not criados:
        return [f"os quatro papeis ja existiam (@{DOMINIO_DOS_PAPEIS})"]
    return [f"{papel}: criado (sem senha)" for papel in criados]


def main(argv: list[str] | None = None) -> int:
    analisador = argparse.ArgumentParser(
        prog="preparar_base",
        description="Migracoes, catalogo, fichas, alertas e os quatro papeis do onboarding.",
    )
    analisador.add_argument(
        "--banco",
        default="",
        help="DATABASE_URL a usar. Sem isto, o que estiver no .env.",
    )
    analisador.add_argument(
        "--so-usuarios",
        action="store_true",
        help="migracoes + as quatro identidades de papel; nao mexe em catalogo, ficha nem "
        "alerta (e o que o `up` usa quando a base do onboarding ja existe)",
    )
    analisador.add_argument(
        "--so-papeis",
        action="store_true",
        help="nao toca em nada: apenas imprime quem e cada papel",
    )
    analisador.add_argument(
        "--sem-papeis",
        action="store_true",
        help="prepara e nao imprime o bloco dos papeis (o `up` imprime no fim, uma vez so)",
    )
    argumentos = analisador.parse_args(argv)

    carregar_env()
    if argumentos.banco:
        os.environ["DATABASE_URL"] = argumentos.banco
    os.environ["PYTHONUTF8"] = "1"
    os.environ["REPLAY_MODE"] = "1"
    os.environ["LLM_FAKE"] = "1"
    os.environ.setdefault("LOG_LEVEL", "WARNING")

    banco = os.environ.get("DATABASE_URL", "(padrao do config: sqlite:///./data/dev.db)")
    uv = _uv()
    cli = [*uv, "run", "python", "-m", "pipeline.cli"]

    falhas = 0

    if not argumentos.so_papeis:
        print("=" * 78)
        print("PREPARO DA BASE DO ONBOARDING")
        print("=" * 78)
        print(f"banco:  {banco}")
        print("rede:   nenhuma (REPLAY_MODE=1); custo de LLM: zero (LLM_FAKE=1)")
        print("")

        print("-- [1/5] migracoes do banco")
        falhas += (
            1 if rodar([*uv, "run", "alembic", "-c", "api/alembic.ini", "upgrade", "head"]) else 0
        )
        print("   ok: schema na ultima versao")

    if not (argumentos.so_usuarios or argumentos.so_papeis):
        print("-- [2/5] catalogo, sinonimos, watchlist, equivalencias, deck interno, admin")
        falhas += 1 if rodar([*cli, "seed"], filtro="seed:") else 0

        print("-- [3/5] fichas das cinco versoes (replay, com evidencia, persistidas)")
        for marca, modelo, versao in VERSOES:
            print(f"   {marca} {modelo} {versao}")
            falhas += (
                1
                if rodar(
                    [*cli, "extract", marca, modelo, versao, "--replay", "--persistir"],
                    filtro="campos com valor",
                )
                else 0
            )

        print("-- [4/5] refresh da watchlist (e o Fogo Amigo contra o deck da Ford)")
        falhas += 1 if rodar([*cli, "refresh", "--watchlist"], filtro="refresh:") else 0

        print(
            f"-- [5/5] dado de demonstracao ({ALERTAS_SIMULADOS} alertas, "
            f"{SESSOES_SIMULADAS} sessoes), todo com is_simulated=true"
        )
        falhas += (
            1
            if rodar(
                [
                    *cli,
                    "seed",
                    "--simulated-alerts",
                    str(ALERTAS_SIMULADOS),
                    "--simulated-sessions",
                    str(SESSOES_SIMULADAS),
                ],
                filtro="SIMULAD",
            )
            else 0
        )
        print("")

    if not argumentos.so_papeis:
        print("-- as identidades de papel")
        try:
            for linha in criar_papeis():
                print(f"   {linha}")
        except Exception as erro:  # o motivo tem de chegar na tela do usuario, nao no traceback
            print(f"   FALHOU ao criar os papeis: {type(erro).__name__}: {erro}")
            falhas += 1
        print("")

    if argumentos.sem_papeis:
        return 1 if falhas else 0

    from api.app.papel import NOME_DO_PAPEL, email_do_papel

    print("PAPEIS (nao ha login: o papel e um seletor na barra lateral do app)")
    for papel in ("vendedor", "analista", "gestor", "admin"):
        print(f"   {papel:9s} {email_do_papel(papel):38s} {NOME_DO_PAPEL[papel]}")
    print("")
    print("   Nenhuma senha. A API le o papel do cabecalho X-Role e nao pede credencial")
    print("   (AUTH_ENABLED=false e o padrao). Para o fluxo com login de docs/04, ponha")
    print("   AUTH_ENABLED=1 e JWT_SECRET no .env e rode `python -m pipeline.cli seed`.")
    print("")
    if falhas:
        print(f"ATENCAO: {falhas} passo(s) falharam. Leia as linhas marcadas FALHOU acima.")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
