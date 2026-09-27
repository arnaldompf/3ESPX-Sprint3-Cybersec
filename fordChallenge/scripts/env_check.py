"""Confere e organiza o `.env` — **sem nunca imprimir o valor de uma chave**.

Este script existe por causa de um defeito real, encontrado em 13/09/2026: a variável
`LLM_MODEL_ALT` do `.env` desta máquina guardava o que tinha **formato de credencial**, e
não nome de modelo. Nenhum código a lia, então nada quebrou — e foi exatamente por isso que
ficou lá. Um segredo na variável errada não dá erro: ele só fica.

O que ele faz, nesta ordem:

1. **lê** o `.env` sem escrever nada;
2. **classifica** cada valor pelo formato — booleano, inteiro, URL, nome de modelo,
   credencial — e reclama quando o formato não combina com o nome da variável;
3. **realoca** o que está no lugar errado, quando dá para saber o lugar certo pelo
   **prefixo público** da credencial (`AIza…` é do Google, `sk-ant-…` é da Anthropic);
4. **reescreve** o `.env` em seções comentadas, preservando tudo o que não conhece.

**A regra que vale acima de todas as outras:** valor de chave não sai daqui. O relatório
mostra os **quatro últimos caracteres** e o comprimento — o bastante para você conferir que
é a chave que pensa que é, e insuficiente para qualquer outra coisa. Um terminal vira
histórico de shell, o histórico vira backup, e o backup vira o problema de alguém.

    python scripts/env_check.py              # confere e relata; não escreve nada
    python scripts/env_check.py --escrever   # reorganiza o .env (com cópia de segurança)
    python scripts/env_check.py --exemplo    # regera o .env.example, sem valores

**Por que conferir é o padrão e escrever é a opção:** assim o script pode entrar no
`verify-quick` como portão sem efeito colateral. Um conferidor que muda o arquivo toda vez
que roda não é conferidor, é migração — e migração não se roda sem querer.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# O console do Windows abre em cp1252, e este script fala português com setas (`→`) no
# relatório de realocação. Sem isto ele morre de `UnicodeEncodeError` **ao explicar o que
# fez** — a pior hora possível para um script que acabou de mexer no `.env`.
if hasattr(sys.stdout, "reconfigure"):  # pragma: no cover - depende do console
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

ENV = RAIZ / ".env"
EXEMPLO = RAIZ / ".env.example"

# A lista de provedores aceitos vem de quem os chama, e não de uma cópia aqui.
#
# Uma segunda lista divergiria em silêncio: `LLM_PROVIDER=moonshot` **funciona** —
# `pipeline/llm.py` tem o apelido para `kimi` —, e um conferidor que não soubesse disso
# reprovaria uma configuração correta. Errar assim é pior que não conferir, porque manda
# consertar o que não está quebrado.
from pipeline.llm import APELIDOS as _APELIDOS  # noqa: E402
from pipeline.llm import PROVEDORES as _PROVEDORES  # noqa: E402

#: Tudo o que `LLM_PROVIDER` aceita: os nomes canônicos e os apelidos.
PROVEDORES_ACEITOS: tuple[str, ...] = tuple(sorted({*_PROVEDORES, *_APELIDOS}))


#: Como cada nome aceito se resolve. Usado para comparar com o prefixo da chave.
def canonico(nome: str) -> str:
    """`moonshot` → `kimi`, `google` → `gemini`, `kimi` → `kimi`."""
    bruto = nome.strip().lower()
    return _APELIDOS.get(bruto, bruto)


# --------------------------------------------------------------------------- formatos

#: Os formatos que uma variável pode ter, e como se reconhece cada um.
#:
#: `modelo` e `segredo` são os dois que importam, e são **opostos**: um nome de modelo é
#: público e curto (`kimi-k2.6`), uma credencial é longa e opaca. Trocar um pelo outro é o
#: defeito que originou este script, e é o par que a conferência de formato pega.
BOOLEANO = re.compile(r"^(0|1|true|false|True|False|yes|no)$")
INTEIRO = re.compile(r"^\d+$")
DECIMAL = re.compile(r"^\d+(\.\d+)?$")
URL = re.compile(r"^https?://\S+$")

#: Formato → (expressão que o valor tem de casar, como dizer isso em português).
#:
#: Tabela e não uma cadeia de `elif`: cinco ramos que só diferem na expressão e no texto
#: são cinco lugares para esquecer de passar o valor por `seguro()` — e esquecer disso
#: **uma vez** é o vazamento que este script existe para não cometer.
POR_EXPRESSAO: dict[str, tuple[re.Pattern[str], str]] = {
    "booleano": (BOOLEANO, "0/1/true/false"),
    "inteiro": (INTEIRO, "um inteiro"),
    "decimal": (DECIMAL, "um número"),
    "url": (URL, "um endereço http(s)://"),
}

#: Comprimento a partir do qual um valor opaco é tratado como credencial.
#:
#: Vinte caracteres: abaixo disso não existe chave de provedor nenhum, e acima disso não
#: existe, neste projeto, nome de modelo, de motor de PDF nem de host.
COMPRIMENTO_SUSPEITO = 20

#: As formas **públicas** que um valor longo pode ter sem ser segredo.
#:
#: Esta é a lista de isenções do detector, e ela é curta de propósito — ver
#: `parece_segredo`, que trata como credencial tudo o que não estiver aqui.
ENDERECO = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.IGNORECASE)  # URL e DSN de banco
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[a-z]{2,}$", re.IGNORECASE)
CAMINHO = re.compile(r"^[.~]{0,2}[/\\]|^[A-Za-z]:[/\\]")  # data/x, ./x, C:/x

#: Nome técnico: modelo, motor, provedor. `claude-haiku-4-5-20251001` tem 25 caracteres.
#:
#: Sem esta isenção o detector, que falha fechado, chamaria de credencial todo nome de
#: modelo longo — e um conferidor que reclama do que está certo é um conferidor que se
#: para de ler. Três condições, e as três importam:
#:
#: 1. **tudo minúsculo.** Credencial quase sempre mistura caixas; nome de modelo, não;
#: 2. **pelo menos um separador** `.` `-` `_` `/`. Chave em hexadecimal minúsculo não tem
#:    nenhum, e continua mascarada;
#: 3. **pelo menos um pedaço que é palavra** — três letras ou mais, só letras. É o que
#:    exclui UUID (`550e8400-e29b-41d4-…`), cujos pedaços são hexadecimais, não palavras.
#:
#: `claude-haiku-4-5-20251001`, `gemini-2.5-flash` e `openrouter/moonshotai/kimi-k2`
#: passam. `AQ.Ab8RN6Ic…` não passa, por causa das maiúsculas — e era o caso do vazamento.
NOME_TECNICO = re.compile(r"^[a-z0-9]+(?:[._/\-][a-z0-9]+)+$")
PALAVRA = re.compile(r"(?:^|[._/\-])[a-z]{3,}(?:[._/\-]|$)")


def nome_tecnico(valor: str) -> bool:
    """`True` para nome de modelo/motor/provedor — as três condições de `NOME_TECNICO`."""
    return bool(NOME_TECNICO.match(valor)) and bool(PALAVRA.search(valor))


#: As impressões digitais **públicas** das credenciais que este projeto encontra.
#:
#: Não são segredo: são os prefixos que os próprios provedores documentam e que todo
#: varredor de chave (gitleaks, o nosso `test_nenhuma_fixture_carrega_segredo`) procura.
#: Reconhecer o prefixo é o que permite dizer *"esta é uma chave do Google"* **sem mostrar
#: a chave** — e é o que faz este script conseguir mover um valor para a variável certa em
#: vez de apenas reclamar que está errada.
#:
#: A ordem importa: `sk-` é prefixo de `sk-ant-` e de `sk-proj-`, então vem por último.
IMPRESSOES: tuple[tuple[str, str, str], ...] = (
    ("sk-ant-", "anthropic", "Anthropic"),
    ("sk-proj-", "openai", "OpenAI (projeto)"),
    ("sk-or-v1-", "openrouter", "OpenRouter"),
    ("AIza", "gemini", "Google AI Studio"),
    # `AQ.` é a forma de token OAuth do Google. Está na lista porque foi exatamente o que
    # esta máquina guardava em `LLM_MODEL_ALT` — e porque o prefixo já é público: todo
    # varredor de segredo o procura.
    ("AQ.", "gemini", "Google (token OAuth)"),
    ("tvly-", "tavily", "Tavily"),
    ("BSA", "brave", "Brave Search"),
    # `sk-` sozinho é ambíguo de propósito: Moonshot, DeepSeek e OpenAI usam os três o
    # mesmo prefixo. O script diz "ambígua" em vez de chutar — chutar aqui mandaria a
    # chave da Moonshot para `OPENAI_API_KEY`, e o erro só apareceria na hora da demo.
    ("sk-", "", "estilo OpenAI (Moonshot, DeepSeek ou OpenAI — ambíguo pelo prefixo)"),
)


def impressao(valor: str) -> tuple[str, str]:
    """Devolve `(slug_do_provedor, nome_legível)` pelo prefixo. Slug vazio = ambíguo."""
    for prefixo, slug, nome in IMPRESSOES:
        if valor.startswith(prefixo):
            return slug, nome
    return "", ""


def parece_segredo(valor: str) -> bool:
    """`True` se o valor tem cara de credencial. **Na dúvida, responde `True`.**

    A primeira versão desta função perguntava *"parece uma chave?"*, com a expressão
    `^[A-Za-z0-9_-]{24,}$`. Ela falhou na estreia, no valor que originou o script: a
    credencial guardada em `LLM_MODEL_ALT` tem um **ponto** no meio, `.` não estava na
    classe de caracteres, e o conferidor de segredo imprimiu o segredo inteiro no terminal
    **ao reclamar dele**.

    A lição não é "faltou o ponto" — é que a pergunta estava invertida. Um detector de
    segredo tem de **falhar fechado**: tratar como credencial tudo o que for longo e sem
    espaço, e abrir exceção apenas para as formas reconhecidamente públicas (endereço,
    e-mail, caminho de arquivo). Errar mascarando um nome de modelo custa um traço no
    relatório; errar mostrando uma chave custa a chave.
    """
    if not valor or " " in valor:
        return False
    if impressao(valor)[1]:
        return True
    if ENDERECO.match(valor) or EMAIL.match(valor) or CAMINHO.match(valor):
        return False
    if nome_tecnico(valor):
        return False
    return len(valor) >= COMPRIMENTO_SUSPEITO


def mascarar(valor: str) -> str:
    """O único jeito que este script tem de falar de um valor secreto.

    Quatro últimos caracteres e o comprimento: o bastante para você reconhecer a chave que
    colou, e insuficiente para reconstruí-la. Valores com menos de 8 caracteres não
    mostram nada — numa chave curta, quatro caracteres é metade dela.
    """
    if not valor:
        return "(vazia)"
    if len(valor) < 8:
        return f"(curta demais: {len(valor)} caracteres)"
    _, nome = impressao(valor)
    etiqueta = f", {nome}" if nome else ""
    return f"····{valor[-4:]} ({len(valor)} caracteres{etiqueta})"


def seguro(valor: str) -> str:
    """`repr` de um valor para mensagem de erro — mascarado se tiver cara de credencial.

    Toda mensagem deste script passa por aqui. Sem isso, uma chave que caísse num campo
    de URL ou de booleano sairia **inteira** na mensagem que reclama dela: o conferidor
    de segredo vazaria o segredo ao apontar o problema.
    """
    return mascarar(valor) if parece_segredo(valor) else repr(valor)


# --------------------------------------------------------------------------- variáveis


@dataclass(frozen=True)
class Variavel:
    """Uma variável do `.env`: onde ela mora, que formato tem e para que serve."""

    nome: str
    formato: str
    ajuda: str
    padrao: str = ""
    obrigatoria: bool = False
    escolhas: tuple[str, ...] = ()


#: O `.env` inteiro, em seções, na ordem em que o arquivo é escrito.
#:
#: Esta estrutura é a especificação: o que não está aqui vai para a seção "OUTRAS" e é
#: **preservado**, nunca descartado. Descartar uma variável desconhecida quebraria o
#: sistema em silêncio, que é o modo de falhar que este projeto mais evita.
SECOES: tuple[tuple[str, str, tuple[Variavel, ...]], ...] = (
    (
        "APLICAÇÃO",
        "Os interruptores. Cada um desliga uma capacidade inteira, e é assim que se\n"
        "# recupera uma demonstração: desliga o interruptor, não conserta no palco.",
        (
            Variavel(
                "AUTH_ENABLED",
                "booleano",
                "login ligado. `false` na demo: a apresentação tem 8 minutos e uma tela "
                "de login gasta 20 deles sem mostrar produto",
                "false",
                obrigatoria=True,
            ),
            Variavel(
                "REPLAY_MODE",
                "booleano",
                "coleta só de cópia salva, sem sair para a rede. `1` = determinístico",
                "1",
                obrigatoria=True,
            ),
            Variavel(
                "LLM_FAKE",
                "booleano",
                "extração por fixture gravada, sem chamar provedor. `1` = custo zero de "
                "verdade, e não estimativa de zero",
                "1",
                obrigatoria=True,
            ),
            Variavel(
                "RESEARCH_ENABLED",
                "booleano",
                "o Pesquisador (WP-41). Desligado, a API **não monta a rota**",
                "true",
            ),
            Variavel(
                "BENCHMARK_ENABLED",
                "booleano",
                "o Benchmark competitivo. Desligado, a rota não existe",
                "false",
            ),
            Variavel("API_HOST", "texto", "endereço em que a API escuta", "127.0.0.1"),
            Variavel("API_PORT", "inteiro", "porta da API", "8000"),
            Variavel(
                "SPECRADAR_USER_AGENT",
                "texto",
                "user-agent da coleta. Identificado, com contato — é o que torna o "
                "scraping educado em vez de anônimo",
            ),
            Variavel("FETCH_RATE_LIMIT_RPS", "decimal", "teto de requisições por segundo", "1"),
            Variavel("SNAPSHOT_DIR", "texto", "onde as cópias das fontes ficam"),
            Variavel("PDF_MOTOR", "texto", "motor de leitura de PDF"),
        ),
    ),
    (
        "BANCO",
        "SQLite na demonstração, Postgres em produção. A demo roda em SQLite de propósito:\n"
        "# um contêiner a menos é um modo de falhar a menos no dia.",
        (
            Variavel(
                "DATABASE_URL",
                "texto",
                "endereço do banco (`sqlite:///…` ou `postgresql+psycopg://…`)",
                "sqlite:///onboarding.db",
                obrigatoria=True,
            ),
            Variavel("ADMIN_EMAIL", "texto", "e-mail do primeiro administrador"),
            Variavel("ADMIN_NOME", "texto", "nome do primeiro administrador"),
            Variavel("ADMIN_PASSWORD", "segredo", "senha do primeiro administrador"),
            Variavel(
                "JWT_SECRET",
                "segredo",
                "segredo de assinatura dos tokens, **mínimo 32 bytes**. Só é lido com "
                "`AUTH_ENABLED=1`, e `api/app/security.py` valida o tamanho na partida — "
                "não no primeiro login",
            ),
        ),
    ),
    (
        "BUSCA",
        "O provedor de busca do Pesquisador. `replay` não sai para a rede e é o padrão da\n"
        "# demonstração; os outros consomem cota.",
        (
            Variavel(
                "SEARCH_PROVIDER",
                "escolha",
                "quem responde a busca",
                "replay",
                escolhas=("replay", "tavily", "brave", "duckduckgo", "searxng"),
            ),
            Variavel("SEARCH_API_KEY", "segredo", "chave do provedor de busca, quando ele exige"),
            Variavel("SEARXNG_URL", "url", "endereço da instância SearXNG, se for o provedor"),
            Variavel("SEARCH_CACHE_DIR", "texto", "onde as respostas de busca ficam em cache"),
        ),
    ),
    (
        "IA PRINCIPAL",
        "O provedor que o pipeline usa para extrair. Com `LLM_FAKE=1` nada aqui é chamado —\n"
        "# a chave pode estar preenchida e o custo continua sendo zero de verdade.",
        (
            Variavel(
                "LLM_PROVIDER",
                "escolha",
                "quem atende",
                "kimi",
                escolhas=PROVEDORES_ACEITOS,
            ),
            Variavel("LLM_MODEL", "modelo", "nome do modelo, exatamente como o provedor o escreve"),
            Variavel("LLM_API_KEY", "segredo", "a chave do provedor principal"),
            Variavel(
                "LLM_API_BASE",
                "url",
                "endereço da API. **Não é luxo**: a Moonshot AI tem dois (`.cn` e `.ai`) e "
                "uma chave de um não vale no outro",
            ),
            Variavel(
                "LLM_MIN_INTERVAL_S", "decimal", "segundos entre duas chamadas (cota do plano)"
            ),
        ),
    ),
    (
        "IA ALTERNATIVA",
        "O segundo provedor, para quando o primeiro está sem saldo, fora do ar ou lento\n"
        "# demais para o orçamento. Mesmos nomes com sufixo `_ALT`.\n"
        "#\n"
        "# **`LLM_MODEL_ALT` é nome de modelo, não chave.** Ela já guardou uma credencial\n"
        "# nesta máquina, e como nenhum código a lia, nada quebrou — um segredo na variável\n"
        "# errada não dá erro, só fica. `scripts/env_check.py` passou a conferir o formato.",
        (
            Variavel(
                "LLM_PROVIDER_ALT",
                "escolha",
                "quem atende quando o principal não atende",
                "",
                escolhas=("", *PROVEDORES_ACEITOS),
            ),
            Variavel("LLM_MODEL_ALT", "modelo", "nome do modelo alternativo"),
            Variavel("LLM_API_KEY_ALT", "segredo", "a chave do provedor alternativo"),
            Variavel("LLM_API_BASE_ALT", "url", "endereço da API alternativa"),
        ),
    ),
)

#: Índice plano, para consulta por nome.
POR_NOME: dict[str, Variavel] = {v.nome: v for _, _, vs in SECOES for v in vs}


# ------------------------------------------------------------------------------ leitura


def ler(caminho: Path) -> dict[str, str]:
    """Lê um `.env` para um dicionário. Aceita `export VAR=`, aspas e comentários."""
    valores: dict[str, str] = {}
    if not caminho.exists():
        return valores
    for linha in caminho.read_text(encoding="utf-8").splitlines():
        crua = linha.strip()
        if not crua or crua.startswith("#"):
            continue
        if crua.startswith("export "):
            crua = crua[len("export ") :].strip()
        if "=" not in crua:
            continue
        nome, _, valor = crua.partition("=")
        nome = nome.strip()
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        valores[nome] = valor
    return valores


# ------------------------------------------------------------------------- conferência


@dataclass
class Problema:
    """Algo errado no `.env`, com a gravidade e — quando dá — o conserto."""

    nome: str
    gravidade: str  # "erro" | "aviso" | "nota"
    texto: str
    conserto: str = ""


def conferir(valores: dict[str, str]) -> list[Problema]:
    """Confere presença e formato de cada variável conhecida. Não escreve nada."""
    problemas: list[Problema] = []

    for nome, var in POR_NOME.items():
        valor = valores.get(nome, "")

        if not valor:
            if var.obrigatoria:
                problemas.append(Problema(nome, "erro", f"obrigatória e ausente — {var.ajuda}"))
            continue

        if var.formato in POR_EXPRESSAO:
            expressao, esperado = POR_EXPRESSAO[var.formato]
            if not expressao.match(valor):
                problemas.append(
                    Problema(nome, "erro", f"deveria ser {esperado}, veio {seguro(valor)}")
                )
        elif var.formato == "escolha" and var.escolhas and valor not in var.escolhas:
            aceitos = ", ".join(c or "(vazio)" for c in var.escolhas)
            problemas.append(
                Problema(nome, "erro", f"{seguro(valor)} não é aceito. Aceitos: {aceitos}")
            )
        elif var.formato == "modelo" and parece_segredo(valor):
            # **O defeito que originou este script.** Repare que a mensagem não mostra o
            # valor: ela mostra o prefixo reconhecido, que é público, e o destino sugerido.
            slug, prov = impressao(valor)
            destino = _destino_de_chave(nome, slug)
            problemas.append(
                Problema(
                    nome,
                    "erro",
                    f"tem formato de **credencial**, não de nome de modelo "
                    f"[{mascarar(valor)}]. Nome de modelo é público e curto "
                    f"(`kimi-k2.6`); isto não é.",
                    conserto=(
                        f"mover para {destino}" + (f" (parece {prov})" if prov else "")
                        if destino
                        else "apagar daqui e colar na variável de chave certa"
                    ),
                )
            )
        elif var.formato == "segredo":
            if not parece_segredo(valor):
                problemas.append(
                    Problema(
                        nome,
                        "aviso",
                        f"não tem formato de credencial [{mascarar(valor)}] — "
                        "placeholder esquecido, ou chave truncada na cópia?",
                    )
                )
            else:
                slug, prov = impressao(valor)
                esperado = _provedor_declarado(nome, valores)
                if slug and esperado and slug != canonico(esperado):
                    problemas.append(
                        Problema(
                            nome,
                            "erro",
                            f"a chave parece ser de **{prov}**, mas o provedor declarado "
                            f"é `{esperado}` [{mascarar(valor)}]",
                            conserto=f"corrija o provedor, ou troque a chave pela de {esperado}",
                        )
                    )

    # Coerência entre provedor e chave: declarar provedor sem chave é configuração que
    # falha na primeira chamada de verdade, e não no `verify`.
    for sufixo in ("", "_ALT"):
        prov = valores.get(f"LLM_PROVIDER{sufixo}", "").strip()
        chave = valores.get(f"LLM_API_KEY{sufixo}", "").strip()
        modelo = valores.get(f"LLM_MODEL{sufixo}", "").strip()
        rotulo = "alternativa" if sufixo else "principal"
        if prov and not chave:
            problemas.append(
                Problema(
                    f"LLM_API_KEY{sufixo}",
                    "aviso",
                    f"a IA {rotulo} declara `{prov}` e não tem chave — com `LLM_FAKE=0` "
                    f"a chamada não acontece e nenhum valor é inventado",
                )
            )
        if prov and not modelo and canonico(prov) != "anthropic":
            problemas.append(
                Problema(
                    f"LLM_MODEL{sufixo}",
                    "aviso",
                    f"`{prov}` não tem modelo padrão neste projeto — defina o nome, "
                    "porque adivinhar nome de modelo é do mesmo tipo de erro que "
                    "adivinhar valor de especificação",
                )
            )

    # Chaves que sobraram em variáveis que este script não conhece.
    for nome, valor in valores.items():
        if nome in POR_NOME or not parece_segredo(valor):
            continue
        _, prov = impressao(valor)
        problemas.append(
            Problema(
                nome,
                "aviso",
                f"variável fora do mapa com formato de credencial [{mascarar(valor)}]"
                + (f", parece {prov}" if prov else ""),
                conserto="mova para a variável certa, ou apague se não for usada",
            )
        )

    return problemas


def _provedor_declarado(nome_da_chave: str, valores: dict[str, str]) -> str:
    """Qual provedor a seção desta chave declara. Vazio quando não há como saber."""
    if nome_da_chave == "LLM_API_KEY":
        return valores.get("LLM_PROVIDER", "").strip().lower()
    if nome_da_chave == "LLM_API_KEY_ALT":
        return valores.get("LLM_PROVIDER_ALT", "").strip().lower()
    # A busca não passa por `pipeline/llm.py` e não tem apelido; comparação direta.
    if nome_da_chave == "SEARCH_API_KEY":
        return valores.get("SEARCH_PROVIDER", "").strip().lower()
    return ""


def _destino_de_chave(nome_errado: str, slug: str) -> str:
    """Para qual variável um valor de chave encontrado em `nome_errado` deveria ir."""
    if nome_errado.endswith("_ALT"):
        return "LLM_API_KEY_ALT"
    if nome_errado.startswith("LLM_"):
        return "LLM_API_KEY"
    if nome_errado.startswith("SEARCH_"):
        return "SEARCH_API_KEY"
    return "LLM_API_KEY_ALT" if slug else ""


# ---------------------------------------------------------------------------- realocar


def realocar(valores: dict[str, str]) -> tuple[dict[str, str], list[str]]:
    """Move credenciais que estão em variável de nome de modelo para a variável de chave.

    **Só move quando o destino está vazio.** Sobrescrever uma chave existente com outra
    trocaria um problema visível (chave no lugar errado) por um invisível (chave certa
    apagada), e a segunda é muito pior: ninguém percebe até a chamada falhar.
    """
    novos = dict(valores)
    feitos: list[str] = []

    for nome, var in POR_NOME.items():
        valor = novos.get(nome, "")
        if var.formato != "modelo" or not valor or not parece_segredo(valor):
            continue
        slug, prov = impressao(valor)
        destino = _destino_de_chave(nome, slug)
        if not destino:
            continue
        if novos.get(destino, "").strip():
            feitos.append(
                f"{nome} → {destino}: **não movida**, o destino já tem valor. "
                f"Decida você qual das duas fica."
            )
            continue
        novos[destino] = valor
        novos[nome] = ""
        feitos.append(f"{nome} → {destino}" + (f" (chave {prov})" if prov else ""))

        # Se o destino é a chave alternativa e não há provedor alternativo declarado, o
        # prefixo diz qual é. Deixar `LLM_PROVIDER_ALT` vazio com chave preenchida seria
        # mover o problema de lugar em vez de resolvê-lo.
        campo_prov = "LLM_PROVIDER_ALT" if destino.endswith("_ALT") else "LLM_PROVIDER"
        if slug and not novos.get(campo_prov, "").strip():
            novos[campo_prov] = slug
            feitos.append(f"{campo_prov} = {slug} (deduzido do prefixo da chave)")

    return novos, feitos


# ----------------------------------------------------------------------------- escrita


def _linha(var: Variavel, valor: str) -> list[str]:
    """Uma variável no arquivo: o comentário de ajuda e depois a linha.

    **Variável sem valor sai comentada**, e isto não é estética. Em Python,
    `os.environ.get("X", "padrao")` devolve `""` quando `X` existe vazia — o default
    **não** entra. Escrever `SEARCH_CACHE_DIR=` (vazia) onde antes a variável estava
    ausente trocou `data/search-cache` por `Path("")`, que é `.`, e o cache de busca
    passou a gravar **na raiz do repositório**: 37 arquivos JSON entraram num commit em
    13/09/2026 por causa disso.

    Ausente e vazia não são a mesma coisa. A linha comentada documenta a variável sem
    defini-la, que é exatamente o que se quer de um arquivo de configuração.
    """
    saida = [f"# {var.ajuda}"]
    if var.escolhas:
        saida.append(f"#   aceitos: {', '.join(c or '(vazio)' for c in var.escolhas)}")
    saida.append(f"{var.nome}={valor}" if valor else f"#{var.nome}=")
    return saida


def montar(valores: dict[str, str], *, com_valores: bool) -> str:
    """Monta o texto do `.env` (ou do `.env.example`, com `com_valores=False`)."""
    carimbo = datetime.now(UTC).strftime("%d/%m/%Y")
    cabecalho = [
        "# SpecRadar — configuração local.",
        "#",
        "# Organizado por `python scripts/env_check.py --escrever`"
        + (f" em {carimbo}." if com_valores else "."),
        "# Confira sem escrever com `python scripts/env_check.py`.",
        "#",
    ]
    if com_valores:
        cabecalho += [
            "# ESTE ARQUIVO TEM SEGREDO DENTRO. Ele está no .gitignore e deve continuar",
            "# lá. Não o cole em chat, ticket, log ou captura de tela.",
            "#",
        ]
    else:
        cabecalho += [
            "# Modelo sem valores. Copie para `.env` e preencha:",
            "#     cp .env.example .env && python scripts/env_check.py",
            "#",
        ]
    linhas = cabecalho

    for titulo, nota, variaveis in SECOES:
        linhas += ["", "# " + "=" * 74, f"# {titulo}", f"# {nota}", "# " + "=" * 74, ""]
        for var in variaveis:
            valor = valores.get(var.nome, var.padrao) if com_valores else ""
            if not com_valores and var.formato not in {"segredo"}:
                # No exemplo, o padrão vale como documentação — menos para segredo, que
                # nunca tem padrão razoável.
                valor = var.padrao
            linhas += _linha(var, valor)
            linhas.append("")

    # Tudo o que este script não conhece é preservado, com o aviso de que é desconhecido.
    outras = sorted(n for n in valores if n not in POR_NOME)
    if outras and com_valores:
        linhas += [
            "# " + "=" * 74,
            "# OUTRAS",
            "# Variáveis que `scripts/env_check.py` não conhece. Elas são **preservadas**",
            "# na reorganização: descartar uma variável desconhecida quebraria o sistema",
            "# em silêncio, que é o modo de falhar que este projeto mais evita.",
            "# " + "=" * 74,
            "",
        ]
        # A mesma regra das conhecidas: sem valor, sai comentada. Uma variável
        # desconhecida declarada vazia pode anular o default de um `os.environ.get`
        # que este script nem sabe que existe.
        linhas += [f"{n}={valores[n]}" if valores[n] else f"#{n}=" for n in outras]
        linhas.append("")

    return "\n".join(linhas).rstrip() + "\n"


# ---------------------------------------------------------------------------- relatório


def relatar(valores: dict[str, str], problemas: list[Problema]) -> None:
    """Imprime o estado do `.env`. Nenhum valor de segredo sai inteiro daqui."""
    print("\nSpecRadar — conferência do .env\n")
    for titulo, _, variaveis in SECOES:
        print(f"  {titulo}")
        for var in variaveis:
            valor = valores.get(var.nome, "")
            # **A máscara segue o valor, não o nome da variável.** Escrito do jeito
            # óbvio — mascarar só onde `formato == "segredo"` —, este relatório
            # imprimiria inteira uma credencial guardada em `LLM_MODEL_ALT`, que é
            # exatamente o caso que originou o script. O que decide é a cara do valor.
            if var.formato == "segredo" or parece_segredo(valor):
                mostrado = mascarar(valor)
            elif not valor:
                mostrado = "(vazia)" + (f"  padrão: {var.padrao}" if var.padrao else "")
            else:
                mostrado = valor
            marca = " " if valor or not var.obrigatoria else "!"
            print(f"   {marca} {var.nome:<24} {mostrado}")
        print()

    erros = [p for p in problemas if p.gravidade == "erro"]
    avisos = [p for p in problemas if p.gravidade == "aviso"]
    for grupo, rotulo in ((erros, "ERRO"), (avisos, "aviso")):
        for p in grupo:
            print(f"  [{rotulo}] {p.nome}: {p.texto}")
            if p.conserto:
                print(f"           conserto: {p.conserto}")
    if not problemas:
        print("  Nada a corrigir.")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--escrever", action="store_true", help="reorganiza o .env (faz cópia de segurança)"
    )
    parser.add_argument("--exemplo", action="store_true", help="regera o .env.example")
    parser.add_argument(
        "--definir",
        action="append",
        metavar="NOME=VALOR",
        help="define uma variável e reescreve o .env (repetível). Recusa valor com "
        "formato de credencial em campo que não é de chave.",
    )
    parser.add_argument(
        "--silencioso", action="store_true", help="só o resultado, para usar em portão"
    )
    args = parser.parse_args()

    if not ENV.exists():
        print(f"não há {ENV.name}. Comece por: cp .env.example .env")
        return 1

    valores = ler(ENV)

    if args.definir:
        for atribuicao in args.definir:
            nome, _, valor = atribuicao.partition("=")
            nome, valor = nome.strip(), valor.strip()
            if not nome:
                print(f"  ignorado (sem nome): {atribuicao}")
                return 1
            var = POR_NOME.get(nome)
            # **O portão vale também para quem escreve pela linha de comando.** Sem isto,
            # o próprio conserto poderia recriar o defeito que o script existe para achar:
            # uma chave colada de novo num campo de nome de modelo.
            if var and var.formato != "segredo" and parece_segredo(valor):
                print(
                    f"  RECUSADO: {nome} é campo de {var.formato} e o valor tem formato de "
                    f"credencial [{mascarar(valor)}]. Se é chave, use a variável de chave."
                )
                return 1
            valores[nome] = valor
            print(f"  definido: {nome} = {mascarar(valor) if parece_segredo(valor) else valor!r}")
        args.escrever = True

    if args.escrever:
        novos, feitos = realocar(valores)
        if feitos:
            print("\n  realocações:")
            for f in feitos:
                print(f"    · {f}")
        valores = novos

    problemas = conferir(valores)
    if not args.silencioso:
        relatar(valores, problemas)

    if args.escrever:
        # A cópia de segurança vem **antes** da escrita, e o nome carrega a hora: um `.env`
        # perdido custa a chave de todo mundo e uma tarde de reconfiguração.
        backup = ENV.with_suffix(f".bak-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}")
        shutil.copy2(ENV, backup)
        ENV.write_text(montar(valores, com_valores=True), encoding="utf-8")
        print(f"  .env reorganizado. Cópia de segurança: {backup.name}")

    if args.exemplo:
        EXEMPLO.write_text(montar(valores, com_valores=False), encoding="utf-8")
        print(f"  {EXEMPLO.name} regerado, sem valores.")

    erros = sum(1 for p in problemas if p.gravidade == "erro")
    if args.silencioso:
        avisos = len(problemas) - erros
        print(f"[env_check] {erros} erro(s), {avisos} aviso(s)")
    return 1 if erros else 0


if __name__ == "__main__":
    raise SystemExit(main())
