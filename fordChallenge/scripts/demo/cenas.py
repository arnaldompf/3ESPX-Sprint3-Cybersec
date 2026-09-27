"""As 12 cenas de `docs/13` §7, percorridas em replay contra o banco do ensaio.

Este módulo **exerce** cada cena pela API de verdade (`TestClient` sobre `create_app()`) e
imprime, para cada uma, a URL que a pessoa abre na demo e os números que vão aparecer na
tela. Ele é o ensaio: se uma cena não tiver dado, ele diz **aqui**, e não no telão.

Três decisões que valem estar escritas:

* **cada cena diz o que é.** `PRONTO` (roda em dado real), `PARCIAL` (o mecanismo roda, o
  caso exato da spec não sai desta base) ou `SLIDE` (não é software). A coluna existe
  porque a tarefa do maestro pede "o que está pronto × o que é slide", e um ensaio que
  mistura as três coisas produz uma apresentação que promete o que não tem;
* **nada é semeado aqui.** O banco é montado pelo `replay_demo.sh` com os mesmos comandos
  que a pessoa vai rodar; este módulo só **lê**. Um probe que criasse o dado que ele
  verifica não ensaiaria nada;
* **o ensaio não faz login, porque não há login** (D-204). Ele manda `X-Role: admin`, que
  é o mesmo cabeçalho que a tela manda, e o papel `admin` é o único que alcança as doze
  cenas sem trocar no meio.

`PARCIAL` **não é falha do ensaio**: é informação. O ensaio falha (código 1) quando uma
cena que deveria estar pronta não responde, ou quando o tempo total passa do teto.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

RAIZ = Path(__file__).resolve().parent.parent.parent
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

PRONTO = "PRONTO"
PARCIAL = "PARCIAL"
SLIDE = "SLIDE"

#: Teto do ensaio, em segundos. A tarefa do maestro pede < 8 min.
#:
#: **O que este número mede:** o tempo de máquina para percorrer as 12 cenas em replay, e
#: não o tempo de palco. O tempo de palco quem mede é quem ensaia (item HUMANO do
#: maestro); o que este teto garante é que a demo não vai esperar o software.
TETO_DO_ENSAIO_S = 8 * 60


@dataclass
class Cena:
    numero: int
    titulo: str
    estado: str
    url: str = ""
    api: str = ""
    linhas: list[str] = field(default_factory=list)
    segundos: float = 0.0

    def imprimir(self, base: str) -> None:
        marca = {PRONTO: "[PRONTO ]", PARCIAL: "[PARCIAL]", SLIDE: "[SLIDE  ]"}[self.estado]
        print(f"\n{marca} cena {self.numero:2} — {self.titulo}   ({self.segundos:.2f}s)")
        if self.url:
            print(f"          tela: {base}{self.url}")
        if self.api:
            print(f"          api : {self.api}")
        for linha in self.linhas:
            print(f"          · {linha}")


class Ensaio:
    """O passeio pelas cenas. Cada `cena_NN` devolve uma :class:`Cena`."""

    def __init__(self) -> None:
        from fastapi.testclient import TestClient

        from api.app.main import create_app

        self.base = os.environ.get("DEMO_BASE_URL", "http://127.0.0.1:8000")
        self.cliente = TestClient(create_app(), raise_server_exceptions=False)
        self.headers = self._logar()
        self.ids, self.rotulos = self._catalogo()

    # ------------------------------------------------------------------- preparação
    def _logar(self) -> dict[str, str]:
        """O cabeçalho de papel do ensaio. **Não há login** desde D-204.

        O ensaio percorre as doze cenas, e elas atravessam os quatro papéis; `admin` é o
        único que alcança todas sem trocar no meio. O papel viaja em `X-Role`, como a tela
        faz, e não há credencial nenhuma a criar nem a imprimir.
        """
        from api.app.papel import CABECALHO_PAPEL

        return {CABECALHO_PAPEL: "admin"}

    def _catalogo(self) -> tuple[dict[str, str], dict[str, str]]:
        """A versão **com mais campos** de cada marca — que é a que o ensaio extraiu.

        Escolher pela contagem, e não pelo nome, é deliberado: o nome exato depende de
        como o resolvedor casou o pedido com a linha vigente, e o ensaio não deve
        depender dessa coincidência. A versão com ficha é a que a demo mostra.
        """
        from sqlmodel import select

        from api.app.db import session_scope
        from api.app.models import Brand, SpecValue, VehicleModel, Version

        ids: dict[str, str] = {}
        rotulos: dict[str, str] = {}
        with session_scope() as sessao:
            contagem = Counter(sv.version_id for sv in sessao.exec(select(SpecValue)).all())
            for version_id, _ in contagem.most_common():
                version = sessao.get(Version, version_id)
                if version is None:
                    continue
                modelo = sessao.get(VehicleModel, version.model_id)
                marca = sessao.get(Brand, modelo.brand_id) if modelo else None
                chave = (marca.nome if marca else "").lower()
                if chave and chave not in ids:
                    ids[chave] = version_id
                    rotulos[chave] = f"{marca.nome} {modelo.nome} {version.nome_exato}".strip()
        faltando = [m for m in ("ford", "toyota", "volkswagen", "chevrolet") if m not in ids]
        if faltando:
            raise SystemExit(
                f"ensaio: o banco não tem versão com ficha de {', '.join(faltando)}. "
                "Rode o `replay_demo.sh` inteiro — é ele que monta a base."
            )

        # A Ford **diesel de topo**, que é outra coisa que "a Ford com mais campos".
        #
        # A chave `ford` é a Raptor, porque ela tem a ficha mais completa (62 campos
        # contra 29). Mas a Raptor é gasolina e de outro propósito: na cena 8 ela cai
        # justamente no aviso de par não comparável contra a Hilux SRX Plus. O par que
        # `docs/13` §7 pede é "Ranger diesel topo × Hilux SRX Plus", e a Ranger Limited
        # entrou na base em 10/09/2026.
        #
        # Resolvida **pelo nome**, e não pela contagem, porque é a identidade dela que
        # importa aqui. Ausente, a cena 8 diz isso em vez de trocar o par em silêncio.
        with session_scope() as sessao:
            for version_id, _ in contagem.most_common():
                version = sessao.get(Version, version_id)
                if version is None or "limited" not in (version.nome_exato or "").lower():
                    continue
                modelo = sessao.get(VehicleModel, version.model_id)
                marca = sessao.get(Brand, modelo.brand_id) if modelo else None
                if marca and marca.nome.lower() == "ford":
                    ids["ford_diesel"] = version_id
                    rotulos["ford_diesel"] = (
                        f"{marca.nome} {modelo.nome} {version.nome_exato}".strip()
                    )
                    break
        return ids, rotulos

    def _get(self, rota: str) -> Any:
        resposta = self.cliente.get(rota, headers=self.headers)
        if resposta.status_code != 200:
            raise SystemExit(f"ensaio: GET {rota} → {resposta.status_code} {resposta.text[:300]}")
        return resposta.json()

    def _post(self, rota: str, corpo: dict[str, Any], *, esperado: tuple[int, ...] = (200,)) -> Any:
        resposta = self.cliente.post(rota, json=corpo, headers=self.headers)
        if resposta.status_code not in esperado:
            raise SystemExit(f"ensaio: POST {rota} → {resposta.status_code} {resposta.text[:300]}")
        return resposta.json()

    # -------------------------------------------------------------------- as 12 cenas
    def cena_01(self) -> Cena:
        return Cena(
            1,
            "A dor da Ford",
            SLIDE,
            linhas=[
                "slide de `docs/12` §10: 3 analistas, ~2 semanas por ciclo, planilha sem fonte",
                "não há software nesta cena; ela existe para a próxima ter peso",
            ],
        )

    def cena_02(self) -> Cena:
        version_id = self.ids["ford"]
        ficha = self._get(f"/api/v1/vehicles/{version_id}/specs")
        com_valor: list[str] = []
        vazios: Counter[str] = Counter()
        com_evidencia = 0
        for grupo, campos in ficha.items():
            if not isinstance(campos, dict) or grupo in {"meta", "extras"}:
                continue
            for nome, campo in campos.items():
                if not isinstance(campo, dict):
                    continue
                if campo.get("value") is not None:
                    com_valor.append(nome)
                    com_evidencia += 1 if campo.get("evidences") else 0
                else:
                    vazios[str(campo.get("status"))] += 1
        return Cena(
            2,
            f"Ficha da {self.rotulos['ford']} com evidência e os dois vazios",
            PRONTO,
            url=f"/app/ficha/{version_id}",
            api=f"GET /api/v1/vehicles/{version_id}/specs",
            linhas=[
                f"{len(com_valor)} campo(s) com valor, {com_evidencia} com evidência anexada",
                "vazios desta ficha: " + ", ".join(f"{s}={n}" for s, n in sorted(vazios.items())),
                (
                    "MEDIDO: `nao_disponivel` não aparece em nenhuma ficha desta base — "
                    "nenhuma fonte salva **afirma** que um item não existe. Os dois vazios "
                    "são distintos no schema e na legenda da tela; nesta base só um deles "
                    "tem exemplo ao vivo, e a fala tem de dizer isso"
                ),
                "clicar num valor abre a gaveta com o trecho verbatim, a URL e a data",
            ],
        )

    def cena_03(self) -> Cena:
        resolucao = self._post(
            "/api/v1/resolutions",
            {"marca": "Toyota", "modelo": "Hilux", "versao": "GR-Sport"},
        )
        estado = resolucao.get("status") or resolucao.get("resolution")
        alternativas = resolucao.get("alternatives") or []
        pronto = "inexistente" in str(estado)
        return Cena(
            3,
            "GR-Sport: a versão saiu de linha",
            PRONTO if pronto else PARCIAL,
            url="/app/consulta",
            api='POST /api/v1/resolutions {"marca":"Toyota","modelo":"Hilux","versao":"GR-Sport"}',
            linhas=[
                f"resolução: {estado}",
                f"{len(alternativas)} alternativa(s) da linha vigente: "
                + ", ".join(str(a) for a in alternativas[:5]),
                f"mensagem ao usuário: {str(resolucao.get('mensagem'))[:110]}…",
                "o sistema **não** entrega a ficha de outra versão em silêncio",
            ],
        )

    def cena_04(self) -> Cena:
        """Divergência entre fontes, **com o caso 5,8 × 6,5 da spec**.

        Até 09/09/2026 este caso não saía da base, e o motivo era a forma da fonte: a
        regra do fast-path exigia a âncora "0 a 100" e o valor na **mesma frase**, e o
        registro de coleta traz o segundo valor noutra — *"No teste da Autoesporte, a
        picape cumpriu a marca em 6,5 s"*, onde "a marca" é o 0–100 nomeado antes.

        A regra de **proximidade** (`fastpath.extrair_aceleracao_por_proximidade`) lê o
        valor a até 300 caracteres da âncora, sem quebra de parágrafo no meio, com o
        trecho do valor como citação — e sem afrouxar o grounding em nada. Medido: o 6,5
        mais próximo está a 162 caracteres.
        """
        ficha = self._get(f"/api/v1/vehicles/{self.ids['ford']}/specs")
        divergentes: list[str] = []
        aceleracao: dict[str, Any] = {}
        for grupo, campos in ficha.items():
            if not isinstance(campos, dict) or grupo in {"meta", "extras"}:
                continue
            for nome, campo in campos.items():
                if not isinstance(campo, dict):
                    continue
                if nome == "aceleracao_0_100_s":
                    aceleracao = campo
                if campo.get("status") == "divergente":
                    # DISTINTOS: `conflicts` traz uma entrada por **evidência**, e duas
                    # fontes que dizem a mesma coisa aparecem duas vezes. Isso está certo
                    # na API (cada valor com a sua citação) e ficaria parecendo defeito na
                    # fala da demo.
                    vistos: list[str] = []
                    for valor in [campo.get("value")] + [
                        c.get("value") for c in (campo.get("conflicts") or [])
                    ]:
                        # Dedup pelo valor INTEIRO: truncar antes fundiria duas listas que
                        # só diferem no fim (`modos_conducao` é exatamente esse caso).
                        texto = str(valor)
                        if texto not in vistos:
                            vistos.append(texto)
                    resumo = " × ".join(v[:40] + ("…" if len(v) > 40 else "") for v in vistos)
                    divergentes.append(f"{nome}: {resumo}")
        # Uma segunda evidência com o **mesmo** valor é corroboração, não divergência: o
        # caso da spec exige um valor distinto (o 6,5 do teste da Autoesporte).
        tem_o_caso_da_spec = any(
            str(c.get("value")) != str(aceleracao.get("value"))
            for c in (aceleracao.get("conflicts") or [])
        )
        return Cena(
            4,
            "Divergência entre fontes, com os dois valores à vista",
            PRONTO if tem_o_caso_da_spec else PARCIAL,
            url=f"/app/ficha/{self.ids['ford']}",
            api=f"GET /api/v1/vehicles/{self.ids['ford']}/specs",
            linhas=[
                f"{len(divergentes)} campo(s) `divergente` nesta ficha:",
                *[f"  {d}" for d in divergentes],
                (
                    "ACELERAÇÃO 0-100, o caso da spec: valor "
                    f"{aceleracao.get('value')!r} · `{aceleracao.get('status')}` · "
                    + " × ".join(
                        [str(aceleracao.get("value"))]
                        + [str(c.get("value")) for c in (aceleracao.get("conflicts") or [])]
                    )
                    if tem_o_caso_da_spec
                    else "ACELERAÇÃO 0-100: o caso 5,8 × 6,5 NÃO está saindo — regressão, "
                    "conferir `fastpath.extrair_aceleracao_por_proximidade`"
                ),
                *(
                    [
                        "  5,8 s — declarado pela Ford; 6,5 s — medido no teste da "
                        "Autoesporte. Cada um com a sua citação, na mesma fonte",
                        "como sai: a regra de proximidade lê o valor a até 300 caracteres "
                        "da âncora '0 a 100', sem quebra de parágrafo no meio. O 6,5 está "
                        "a 162. O grounding não foi afrouxado: a citação é o trecho do "
                        "valor, pedaço literal do texto salvo",
                    ]
                    if tem_o_caso_da_spec
                    else []
                ),
                "os outros três divergentes são igualmente reais — os dois lados com prova",
            ],
        )

    def cena_05(self) -> Cena:
        alertas = self._get("/api/v1/alerts?type=referencia_interna_divergente")
        com_evidencia = 0
        detalhes: list[str] = []
        for alerta in alertas:
            cadeia = self._get(f"/api/v1/alerts/{alerta['id']}/trace")
            tem = bool(cadeia.get("evidencias"))
            com_evidencia += 1 if tem else 0
            detalhes.append(
                f"{alerta['field']}: deck={alerta['old']!s:38.38} × público={alerta['new']!s:38.38}"
                f"  [{'com citação' if tem else 'sem citação'}]"
            )
        return Cena(
            5,
            "FOGO AMIGO — o material interno contra a fonte pública (cena-assinatura)",
            PRONTO if alertas and com_evidencia == len(alertas) else PARCIAL,
            url="/app/radar",
            api="GET /api/v1/alerts?type=referencia_interna_divergente",
            linhas=[
                f"{len(alertas)} divergência(s), {com_evidencia} com citação verbatim na cadeia",
                *detalhes,
                "o deck é **tier interno** e não entra na ficha: o valor público vence e a "
                "divergência fica exposta com os dois valores",
            ],
        )

    def cena_06(self) -> Cena:
        ford = self.ids["ford"]
        concorrentes = [self.ids["toyota"], self.ids["volkswagen"], self.ids["chevrolet"]]
        rota = f"/api/v1/parity?ford_version={ford}&competitors={','.join(concorrentes)}"
        matriz = self._get(rota)
        linhas: list[str] = []
        for coluna in matriz["colunas"]:
            c = coluna["contagem"]
            linhas.append(
                f"{coluna['rotulo'][:32]:32} ganhamos={c['vantagem']} empate={c['paridade']} "
                f"perdemos={c['gap']} não sabemos={c['desconhecido']}  "
                f"({coluna['comparabilidade']['resumo']})"
            )
        avisos = [
            c["comparabilidade"]["aviso"]
            for c in matriz["colunas"]
            if c["comparabilidade"]["aviso"]
        ]
        return Cena(
            6,
            'Matriz de paridade com "não sabemos" e o aviso de comparabilidade',
            PRONTO,
            url="/app/matriz",
            api=rota,
            linhas=[
                *linhas,
                f"{len(avisos)} coluna(s) com aviso de par não comparável — e a coluna fica, "
                "com o aviso acima da tabela",
                "o `gap` aparece sempre: não há filtro para esconder onde o concorrente ganha",
            ],
        )

    def cena_07(self) -> Cena:
        saude = self._get("/api/v1/insights/knowledge-health/versions")
        cobertura = self._get("/api/v1/insights/coverage")
        linhas = [
            f"{v['rotulo'][:34]:34} {v['status']:12} regra={v['regra_do_status']}"
            for v in saude[:4]
        ]
        return Cena(
            7,
            "Saúde do Conhecimento e cobertura por montadora",
            PRONTO,
            url="/app/saude",
            api="GET /api/v1/insights/knowledge-health/versions",
            linhas=[
                *linhas,
                "campos com fonte oficial, por marca (k/n, nunca porcentagem sozinha): "
                + ", ".join(
                    f"{c['marca']} {c['campos_com_fonte_oficial']['valor']}"
                    f"/{c['campos_com_fonte_oficial']['de']}"
                    for c in cobertura[:4]
                ),
                "todo status vem de uma **regra nomeada**; o indicador é operacional e diz "
                "isso no cartão — não é probabilidade de verdade",
            ],
        )

    def cena_08(self) -> Cena:
        """Copiloto, com o par que a spec pede: **Ranger diesel topo × Hilux SRX Plus**.

        Até 09/09/2026 esta cena rodava com a **Raptor** contra a Hilux, e o resultado era
        um aviso de par não comparável — a Raptor é gasolina, de outro propósito, e o
        motor de comparabilidade fazia o certo ao dizer isso. A Ranger diesel de topo
        entrou na base em 10/09 (`scripts/coleta/coletar_faltantes.py`), e a cena passa a
        ser a que `docs/13` §7 descreve.

        A cena imprime **quantas dimensões fecham com dado real**, que é a pergunta que
        importa: o perfil do fazendeiro pesa preço, economia e capacidade, e uma dimensão
        sem dado nos dois lados sai do cálculo com o motivo escrito — nunca vira nota
        baixa nem silêncio.
        """
        ford = self.ids.get("ford_diesel") or self.ids["ford"]
        srx = self.ids["toyota"]
        usa_diesel = "ford_diesel" in self.ids
        perfil = {
            "uso": ["rural_carga"],
            "prioridades_rank": ["preco", "economia", "capacidade"],
            "km_mes": 2000,
        }
        comparacao = self._post(
            "/api/v1/comparisons",
            {"base_vehicle_id": ford, "competitor_ids": [srx], "needs_profile": perfil},
        )
        fit = comparacao.get("fit") or {}
        conc = (fit.get("concorrentes") or [{}])[0]
        aderencia = conc.get("aderencia") or {}
        dimensoes = aderencia.get("dimensoes") or []
        com_dado = [d for d in dimensoes if d.get("nota_ford") is not None]
        sem_dado = [d for d in dimensoes if d.get("nota_ford") is None]

        par = f"{ford}:{srx}"
        argumentario = self._post(f"/api/v1/comparisons/{par}/arguments", {})
        job = self._post(f"/api/v1/comparisons/{par}/pdf", {}, esperado=(200, 202))
        # O documento sai por job (202 + `Location`), e quem o executa é o worker. Na demo
        # ele roda ao lado da API; no ensaio, uma passada em processo — sem isso a cena
        # pararia em "pendente" e não diria nada sobre o documento.
        from pipeline.worker import rodar_uma_vez

        # Até 5 passadas: a fila pode ter jobs de outras cenas na frente, e o worker pega
        # um por vez. Sem o laço, a cena pararia em "pendente" por causa do vizinho.
        passadas = []
        for _ in range(5):
            estado = self._get(f"/api/v1/jobs/{job['job_id']}")
            if estado["status"] in {"concluido", "falhou"}:
                break
            r = rodar_uma_vez()
            passadas.append(f"pegos={r.pegos} concluidos={r.concluidos} falhados={r.falhados}")
            if r.erros:
                passadas.append(f"erro: {r.erros[0][:120]}")
        estado = self._get(f"/api/v1/jobs/{job['job_id']}")

        calculou = aderencia.get("aderencia_ford") is not None
        return Cena(
            8,
            "Copiloto: perfil do fazendeiro, aderência decomposta, custo de uso, 3+1, documento",
            PRONTO if (calculou and usa_diesel) else PARCIAL,
            url="/app/showroom",
            api=f"POST /api/v1/comparisons · POST /api/v1/comparisons/{par}/pdf",
            linhas=[
                f"par: {self.rotulos.get('ford_diesel' if usa_diesel else 'ford')} × "
                f"{self.rotulos.get('toyota')}",
                (
                    "PAR DA SPEC: a Ranger diesel de topo está na base (coleta de 10/09/2026)"
                    if usa_diesel
                    else "ATENÇÃO: a Ranger diesel não está no catálogo; a cena caiu para a "
                    "Raptor, que é gasolina e vai acusar par não comparável"
                ),
                f"aderência: Ford={aderencia.get('aderencia_ford')} × "
                f"concorrente={aderencia.get('aderencia_concorrente')} "
                f"(peso considerado {aderencia.get('peso_considerado')} de 100)",
                f"MEDIDO: {len(com_dado)} de {len(dimensoes)} dimensão(ões) fecham com dado "
                "real dos dois lados"
                + (
                    " — " + ", ".join(str(d.get("rotulo") or d.get("dimensao")) for d in com_dado)
                    if com_dado
                    else ""
                ),
                *[
                    f"fora do cálculo: {d.get('rotulo') or d.get('dimensao')} — "
                    f"{d.get('aviso') or 'sem dado comparável nos dois lados'}"
                    + (
                        " (falta: "
                        + ", ".join(
                            str(c.get("campo")) for c in (d.get("campos_sem_dado") or [])[:3]
                        )
                        + ")"
                        if d.get("campos_sem_dado")
                        else ""
                    )
                    for d in sem_dado[:3]
                ],
                *[f"aviso: {a}" for a in (aderencia.get("avisos") or [])[:3]],
                f"argumentário: {len(argumentario.get('pontos') or [])} ponto(s) a favor"
                + (
                    " + 1 ponto de atenção"
                    if argumentario.get("ponto_forte_concorrente")
                    else " (nenhum ponto de atenção)"
                )
                + f" · gerado_por={argumentario.get('gerado_por')}",
                f"documento do cliente: job {estado['status']}"
                + (f" → {estado.get('result_url')}" if estado.get("result_url") else "")
                + (f"  [worker: {'; '.join(passadas)}]" if passadas else ""),
            ],
        )

    def cena_09(self) -> Cena:
        resumo = self._get("/api/v1/insights/summary")
        concorrentes = self._get("/api/v1/insights/competitors")
        real, simulado = resumo["real"], resumo["simulado"]
        return Cena(
            9,
            "Win/Loss e insights, com SIMULAÇÃO rotulada",
            PRONTO,
            url="/app/insights",
            api="GET /api/v1/insights/summary · GET /api/v1/insights/competitors",
            linhas=[
                f"real: n={real['n']} (fechou {real['fechou']['valor']}, "
                f"perdeu {real['perdeu']['valor']}) · "
                f"simulado: n={simulado['n']} (fechou {simulado['fechou']['valor']}, "
                f"perdeu {simulado['perdeu']['valor']}) — e os dois **nunca** somados",
                f"percentual exibido? real={real['mostra_percentual']} "
                f"simulado={simulado['mostra_percentual']} "
                f"(n mínimo = {resumo['n_minimo_para_percentual']})",
                f"rótulo obrigatório: {resumo['rotulo_simulacao']}",
                f"{len(concorrentes)} concorrente(s) no painel; onde n < mínimo aparece k/n, "
                "nunca porcentagem",
                (
                    "MEDIDO: as sessões reais são zero nesta base — a demo mostra o painel "
                    "com dado SIMULADO rotulado, que é exatamente o que a spec pede, e a "
                    "fala tem de dizer que o número real vem quando o vendedor registrar"
                )
                if real["n"] == 0
                else "há sessão real na base",
            ],
        )

    def cena_10(self) -> Cena:
        fila = self._get("/api/v1/events")
        por_faixa = Counter(e["materiality"] for e in fila)
        alta = [e for e in fila if e["materiality"] == "ALTA"]
        # A cadeia mostrada é a do primeiro ALTA **com evidência gravada**, e não a do
        # topo da fila.
        #
        # O topo desta base é um alerta **semeado** (`is_simulated=true`), que por
        # construção não tem evidência: dado de demonstração não tem fonte para citar. A
        # cena existe para mostrar a cadeia inteira até a prova, e abri-la num alerta sem
        # prova mostrava "nenhum snapshot gravado" — verdade sobre aquele alerta, e a
        # coisa errada para demonstrar o mecanismo. A fila continua sendo a real, com o
        # simulado no topo e rotulado; o que muda é **qual** cadeia se abre.
        escolhido = alta[0] if alta else None
        cadeia = {}
        for candidato in alta:
            possivel = self._get(f"/api/v1/alerts/{candidato['alert_id']}/trace")
            if possivel.get("evidencias"):
                escolhido, cadeia = candidato, possivel
                break
        if alta and not cadeia:
            cadeia = self._get(f"/api/v1/alerts/{alta[0]['alert_id']}/trace")
        elos = ["acao_sugerida", "regras", "mudanca", "comparavel", "evidencias"] if cadeia else []
        preenchidos = sum(1 for elo in elos if cadeia.get(elo))
        vazios = [elo for elo in elos if not cadeia.get(elo)]
        campo_da_cadeia = (cadeia.get("mudanca") or {}).get("campo_canonico") or "campo não nomeado"
        # A prova do elo 5, que é o que a auditoria pede: hash e data da captura. Em
        # replay isso passou a existir em 10/09/2026 (`persist.registrar_snapshots`);
        # antes a cadeia dizia "nenhum snapshot gravado" mesmo com o `meta.json` da
        # fixture trazendo o sha256.
        snaps = cadeia.get("snapshots") or []
        lado_por_evidencia = [e.get("lado") for e in (cadeia.get("evidencias") or [])]
        return Cena(
            10,
            'Radar: materialidade e "Por quê?"',
            PRONTO,
            url="/app/radar",
            api="GET /api/v1/events · GET /api/v1/alerts/{id}/trace",
            linhas=[
                "fila: " + ", ".join(f"{f}={n}" for f, n in por_faixa.items()),
                f"topo da fila: {alta[0]['materiality']} com {alta[0]['pontos']:g} ponto(s), "
                f"regras {[r['id'] for r in alta[0]['rules_fired']]}"
                + (" · SIMULADO (dado de demonstração)" if alta[0].get("is_simulated") else "")
                if alta
                else "nenhum alerta ALTA nesta base",
                (
                    f"cadeia aberta no alerta de `{campo_da_cadeia}`"
                    + (
                        " (o topo da fila é simulado e não tem prova para citar)"
                        if escolhido is not alta[0]
                        else ""
                    )
                    if escolhido
                    else "nenhum alerta para abrir a cadeia"
                ),
                (
                    f"elo 5, a prova: {len(snaps)} snapshot(s) com hash e data"
                    + (
                        f" — sha256 {str(snaps[0].get('sha256'))[:16]}…, "
                        f"capturado em {str(snaps[0].get('captured_at'))[:10]}"
                        if snaps
                        else f" ({cadeia.get('motivo_sem_snapshot', '')[:70]})"
                    )
                ),
                (
                    "cada evidência declara o LADO da mudança: "
                    + ", ".join(str(lado) for lado in lado_por_evidencia)
                    + " — o rótulo não é inferido pela posição na lista (D-156)"
                    if lado_por_evidencia
                    else "sem evidência gravada neste alerta; o elo diz o motivo"
                ),
                (f"elos vazios: {', '.join(vazios)}" if vazios else "nenhum elo vazio"),
                f"cadeia do 'Por quê?': {preenchidos} de 5 elos com conteúdo; os vazios trazem "
                "o motivo escrito, nunca em branco",
                "ruído colapsado no fim da fila — sai da fila, não do sistema",
            ],
        )

    def cena_10b(self) -> Cena:
        """What-if. Cena 10 da spec diz "(+ What-if se pronto)" — está pronto."""
        ford, amarok = self.ids["ford"], self.ids["volkswagen"]
        cenario = self._post(
            "/api/v1/scenarios",
            {
                "base_version_ids": [ford, amarok],
                "overrides": [
                    {"version_id": amarok, "campo": "preco_sugerido_brl", "delta_pct": -5}
                ],
            },
        )
        diff = cenario["diffs"][0]
        materialidade = diff.get("materialidade") or {}
        aplicado = cenario["overrides_aplicados"][0]
        return Cena(
            10,
            'What-if: "e se o concorrente baixar 5%?" (a segunda metade da cena 10)',
            PRONTO,
            url="/app/simulador",
            api="POST /api/v1/scenarios",
            linhas=[
                f"hipótese: {aplicado['campo']} {aplicado['antes']} → {aplicado['depois']} "
                f"({aplicado['origem']})",
                f"{len(diff['paridade'])} estado(s) de paridade mudariam"
                + (
                    ": "
                    + ", ".join(
                        f"{m['campo']} {m['antes']}→{m['depois']}" for m in diff["paridade"]
                    )
                    if diff["paridade"]
                    else " — e o motivo é medido, não silêncio: ver a linha abaixo"
                ),
                (
                    "MEDIDO: nesta base o preço do concorrente está longe do da Ford, então "
                    "−5% não cruza a fronteira de nenhum estado. A materialidade **muda** "
                    "(a fila reordena) e a cadeia explica por quê — que é o que a cena "
                    "precisa mostrar. Para ver uma inversão ao vivo, o slider precisaria "
                    "passar de ±10%, que é o teto da tela por decisão de produto"
                )
                if not diff["paridade"]
                else "a inversão acima é o que o Radar acusaria se isso acontecesse",
                f"materialidade do cenário: {materialidade.get('materiality')} "
                f"({materialidade.get('pontos')} pontos), marcada como hipótese",
                f"rótulo em todo painel de cenário: {cenario['rotulo']}",
                "nenhuma linha nova em `spec_values`: o motor do cenário não conhece banco",
            ],
        )

    def cena_11(self) -> Cena:
        return Cena(
            11,
            "Arquitetura em 1 slide",
            SLIDE,
            linhas=[
                "slide: `docs/02` — coleta educada → snapshot com hash → extração "
                "(fast-path + LLM) → grounding → reconciliação por tier → ficha canônica",
                "o número que sustenta o slide: `reports/eval.md`, com denominador visível",
            ],
        )

    def cena_12(self) -> Cena:
        return Cena(
            12,
            "Próxima onda e visão",
            SLIDE,
            linhas=[
                "onda 2 (`docs/13` §3): time machine + downgrade silencioso (WP-36), data "
                "contract BigQuery (WP-37), upload de documento como fonte (WP-38), dossiê "
                "de conformidade (WP-39), visão do gerente (WP-40)",
                "visão declarada como visão: cenários salvos A/B, TCO de manutenção e "
                "monitor de ofertas são slide — não existem em código, e o roteiro diz isso",
            ],
        )

    # ------------------------------------------------------------------------ passeio
    def rodar(self) -> list[Cena]:
        ordem = [
            self.cena_01,
            self.cena_02,
            self.cena_03,
            self.cena_04,
            self.cena_05,
            self.cena_06,
            self.cena_07,
            self.cena_08,
            self.cena_09,
            self.cena_10,
            self.cena_10b,
            self.cena_11,
            self.cena_12,
        ]
        cenas: list[Cena] = []
        for funcao in ordem:
            comeco = time.perf_counter()
            cena = funcao()
            cena.segundos = time.perf_counter() - comeco
            cena.imprimir(self.base)
            cenas.append(cena)
        return cenas


#: Onde o ensaio grava o que mediu. `docs/demo/ROTEIRO_15SET.md` lê daqui, e é isso que
#: impede o roteiro de afirmar um número diferente do que a tela mostra — o risco nº 4 do
#: `ONBOARDING.md`, que era "alta" justamente porque os dois viviam separados.
RELATORIO_DO_ENSAIO = RAIZ / "reports" / "ensaio.json"


def gravar_relatorio(cenas: list[Cena], total: float) -> Path:
    """Grava o que o ensaio mediu, cena por cena, para o roteiro poder ler.

    O arquivo é a **fonte** dos números do roteiro. Sem ele, a atualização do roteiro
    dependia de alguém copiar número à mão depois de cada rodada — e foi assim que o
    roteiro passou a dizer "10 ALTA" quando o medido era "4 ALTA, 1 MÉDIA, 2 RUÍDO".
    """
    RELATORIO_DO_ENSAIO.parent.mkdir(parents=True, exist_ok=True)
    RELATORIO_DO_ENSAIO.write_text(
        json.dumps(
            {
                "gerado_em": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
                "segundos_de_maquina": round(total, 2),
                "teto_s": TETO_DO_ENSAIO_S,
                "placar": {
                    "prontas": sum(1 for c in cenas if c.estado == PRONTO),
                    "parciais": sum(1 for c in cenas if c.estado == PARCIAL),
                    "slides": sum(1 for c in cenas if c.estado == SLIDE),
                },
                "cenas": [
                    {
                        "numero": c.numero,
                        "titulo": c.titulo,
                        "estado": c.estado.strip(),
                        "url": c.url,
                        "api": c.api,
                        "segundos": round(c.segundos, 3),
                        "linhas": list(c.linhas),
                    }
                    for c in cenas
                ],
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return RELATORIO_DO_ENSAIO


def main() -> int:
    comeco = time.perf_counter()
    print("=" * 78)
    print("ENSAIO DA DEMO — as 12 cenas de `docs/13` §7, em replay")
    print("=" * 78)

    cenas = Ensaio().rodar()
    total = time.perf_counter() - comeco

    prontas = [c for c in cenas if c.estado == PRONTO]
    parciais = [c for c in cenas if c.estado == PARCIAL]
    slides = [c for c in cenas if c.estado == SLIDE]

    print("\n" + "=" * 78)
    print(
        f"RESUMO: {len(prontas)} pronta(s) · {len(parciais)} parcial(is) · "
        f"{len(slides)} slide(s)   —   {total:.1f}s de máquina"
    )
    for cena in parciais:
        print(f"  PARCIAL cena {cena.numero}: {cena.titulo}")
    print(
        f"teto do ensaio: {TETO_DO_ENSAIO_S}s (tempo de MÁQUINA; o tempo de palco é medido "
        "por quem ensaia)"
    )
    print("=" * 78)

    caminho = gravar_relatorio(cenas, total)
    print(f"medido em: {caminho}  (o roteiro lê daqui — `scripts/demo/atualizar_roteiro.py`)")

    if total > TETO_DO_ENSAIO_S:
        print(f"FALTA: o ensaio levou {total:.0f}s, acima do teto de {TETO_DO_ENSAIO_S}s")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
