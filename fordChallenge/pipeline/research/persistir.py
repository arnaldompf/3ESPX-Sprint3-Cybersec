"""A ficha pesquisada entra no catálogo: `versions`, `spec_values`, `evidences`, `snapshots`.

Até 13/09/2026 a pesquisa terminava e a ficha **evaporava**: `research.gravar` guardava a
trilha e os contadores, `ResearchRun.version_id` ficava nulo, e o carro pesquisado não
existia para a Ficha, a Matriz nem o Benchmark. "Não tenho a Triton → pesquiso → comparo"
parava no meio (item A do `specs/BACKLOG.md`).

Quatro regras, e nenhuma é nova — são as do resto do pipeline aplicadas aqui:

* **sem versão e sem ano-modelo, não se cria linha em `versions`.** Uma "versão" chamada
  "Triton" seria catálogo falso, e um ano adivinhado colocaria a Triton 2026 ao lado da
  Ranger 2024 sem ninguém notar. Os dois vêm de quem pediu a pesquisa (a conversa pergunta e
  rotula o ano assumido como INFERÊNCIA);
* **a regra "sem `quote` não grava" continua morando em `pipeline/persist.py`.** Este módulo
  chama os mesmos helpers que a extração clássica chama; não há uma segunda gravação com uma
  segunda regra;
* **re-pesquisa segue a política comum de publicação.** Valores anteriores e novos
  são reconciliados por autoridade e aplicabilidade, com observações e decisões
  preservadas. Vazio não apaga valor válido;
* **pesquisa que não fechou campo nenhum não grava ficha vazia.** `benchmark._versoes_do_modelo`
  conta qualquer linha em `spec_values` como "tem ficha"; 55 linhas `nao_encontrado` fariam
  um carro sem dado passar por carro comparável.

`flush`, nunca `commit`: quem abriu a transação (o worker) decide quando confirmar — e
confirma junto com o `fim` da trilha, para a tela nunca ver a pesquisa acabar antes de a
ficha existir. Nunca levanta: erro vira `erros[]`, porque a pesquisa já produziu resultado e
derrubá-la por falha de gravação transformaria uma ficha pronta em nada.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


@dataclass
class ResultadoDaGravacao:
    """O que foi para o catálogo, contado por tabela — e o que não deu, com o motivo."""

    version_id: str | None = None
    criou_versao: bool = False
    spec_values: int = 0
    evidences: int = 0
    snapshots: int = 0
    alerts: int = 0
    apagados: int = 0
    """Linhas de `spec_values` da pesquisa anterior que saíram para a nova entrar."""
    fusao: Any = None
    """O `persist.Fusao`: quantos campos foram preenchidos, mantidos, substituídos, iguais
    e divergentes. É o que a conversa mostra — "completou 18, manteve 12 do gabarito"."""
    ficha_mantida: bool = False
    """A nova pesquisa não fechou campo nenhum e a ficha anterior foi preservada."""
    erros: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.erros

    def to_dict(self) -> dict[str, Any]:
        return {
            "version_id": self.version_id,
            "criou_versao": self.criou_versao,
            "spec_values": self.spec_values,
            "evidences": self.evidences,
            "snapshots": self.snapshots,
            "alerts": self.alerts,
            "apagados": self.apagados,
            "ficha_mantida": self.ficha_mantida,
            "fusao": self.fusao.to_dict() if self.fusao is not None else None,
            "erros": list(self.erros),
            "avisos": list(self.avisos),
        }


def _agora() -> dt.datetime:
    return dt.datetime.now(dt.UTC).replace(tzinfo=None)


def _data(bruto: str) -> dt.datetime:
    """`captured_at` do `fetch` (`AAAA-MM-DD` ou ISO) como `datetime` ingênuo, em UTC."""
    texto = (bruto or "").strip()
    try:
        parsed = dt.datetime.fromisoformat(texto.replace("Z", "+00:00"))
        return parsed.astimezone(dt.UTC).replace(tzinfo=None) if parsed.tzinfo else parsed
    except ValueError:
        pass
    for formato in ("%Y-%m-%dT%H-%M-%SZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(texto, formato)
        except ValueError:
            continue
    return _agora()


def _snapshot_em_disco(fonte, version_id: str) -> tuple[str | None, str]:
    """Escreve a cópia da página em `SNAPSHOT_DIR` fora do replay. Devolve `(text_path, sha256)`.

    Em replay a coleta é somente leitura por construção (`escrever_snapshot` levanta), e
    o texto veio de uma cópia que já está em disco: `text_path` fica vazio e o hash é o do
    texto em mão — fato, não invenção.
    """
    from pipeline import snapshots
    from pipeline.fetch import http

    sha = fonte.sha256 or snapshots.sha256_de(fonte.texto)
    if http.modo_replay():
        return None, sha
    try:
        escrito = snapshots.escrever_snapshot(
            version_id=version_id,
            url_final=fonte.url,
            texto=fonte.texto,
            tier=int(fonte.tier),
            tipo="pdf"
            if fonte.url.lower().endswith(".pdf")
            or (getattr(fonte, "raw_path", "") and Path(fonte.raw_path).suffix.lower() == ".pdf")
            else "html",
            status="consultada",
            http_status=fonte.http_status,
            captured_at=fonte.captured_at or None,
            bruto=Path(fonte.raw_path).read_bytes() if getattr(fonte, "raw_path", "") else None,
            extras={
                "source_kind": fonte.tipo,
                "parse_status": getattr(fonte, "parse_status", ""),
                "fetch_ok": getattr(fonte, "fetch_ok", False),
            },
        )
        if getattr(fonte, "documento_pdf", None) is not None:
            from dataclasses import asdict

            (Path(escrito.caminho) / "tables.json").write_text(
                fonte.documento_pdf.tables_json(), encoding="utf-8"
            )
            (Path(escrito.caminho) / "documento.json").write_text(
                json.dumps(asdict(fonte.documento_pdf), ensure_ascii=False),
                encoding="utf-8",
            )
    except Exception as exc:  # disco cheio, sem permissão: a ficha não depende disto
        log.warning("persistir.snapshot_nao_escrito", extra={"url": fonte.url, "erro": str(exc)})
        return None, sha
    return str(Path(escrito.caminho) / escrito.text_path), escrito.sha256 or sha


def persistir_pesquisa(
    sessao,
    resultado,
    *,
    run_id: str,
    marca: str,
    modelo: str,
    versao: str,
    ano_modelo: int | None,
    job_id: str | None = None,
) -> ResultadoDaGravacao:
    """Grava a ficha de um `pipeline.research.run.Resultado` no catálogo.

    `resultado` é o que `pesquisar()` devolveu; `marca`, `modelo`, `versao` e `ano_modelo`
    são os do **pedido** (a identidade que quem pediu confirmou), não o que alguma página
    disse. `run_id` e `job_id` só entram nos registros de custo e no log.
    """
    from sqlmodel import select

    from api.app.models import SpecValue
    from api.app.repositories import brands, versions
    from pipeline import llm, persist
    from pipeline.version_names import nome_canonico_de_versao

    saida = ResultadoDaGravacao()
    marca, modelo, versao = (marca or "").strip(), (modelo or "").strip(), (versao or "").strip()

    if not marca or not modelo:
        saida.erros.append("sem marca e modelo a ficha não tem onde apontar; nada foi gravado")
        return saida
    if not versao:
        saida.erros.append(
            "sem nome de versão a ficha não tem onde apontar: uma 'versão' com o nome do "
            "modelo seria catálogo falso. Informe a versão e pesquise de novo"
        )
        return saida
    if ano_modelo is None:
        saida.erros.append(
            "sem ano-modelo a versão não entra no catálogo: o Benchmark compara só dentro do "
            "mesmo ano, e um ano adivinhado colocaria carros de anos diferentes lado a lado. "
            "Informe `ano` no pedido"
        )
        return saida

    # O arquivo pode mudar entre a coleta e a transação. Não ligar texto/candidatos
    # anteriores a um PDF diferente nem abrir mutações antes de conferir o original.
    from pipeline.snapshots import sha256_de

    for fonte in resultado.fontes:
        expected = getattr(fonte, "sha256_binario", "")
        raw_path = getattr(fonte, "raw_path", "")
        if not expected or not raw_path:
            continue
        try:
            valid = sha256_de(Path(raw_path).read_bytes()) == expected
        except OSError:
            valid = False
        if not valid:
            saida.erros.append(f"original com integridade inválida: {fonte.url}")
            return saida

    try:
        # ---------------------------------------------------------------- catálogo
        # **O nome que já existe ganha.** O Benchmark casa marca e modelo por texto exato
        # com `segments.yaml`, e uma pesquisa que grave "MITSUBISHI  motors" cria uma
        # segunda marca ao lado da que existe: o carro pesquisado fica com ficha, com
        # evidência e **fora** da comparação. Canonizar aqui é mais barato que descobrir
        # depois por que a Triton não aparece na Matriz.
        marca = _nome_ja_no_catalogo(sessao, "marca", marca)
        marca_row = brands.upsert(sessao, nome=marca)
        modelo = _nome_ja_no_catalogo(sessao, "modelo", modelo, brand_id=marca_row.id)
        modelo_row = brands.upsert_modelo(sessao, brand_id=marca_row.id, nome=modelo)
        nome_exato = nome_canonico_de_versao(modelo, versao) or versao
        existente = versions.get_por_nome(
            sessao, model_id=modelo_row.id, nome_exato=nome_exato, ano_modelo=int(ano_modelo)
        )
        versao_row = versions.upsert(
            sessao,
            model_id=modelo_row.id,
            nome_exato=nome_exato,
            ano_modelo=int(ano_modelo),
            in_lineup=True,
            lineup_checked_at=_agora(),
        )
        saida.version_id = versao_row.id
        saida.criou_versao = existente is None

        # Inclui candidatos rejeitados, preservando o trecho e o motivo para reprocessar.
        import hashlib
        import json

        from api.app.models import FieldObservation

        for observation in getattr(resultado, "observacoes", []):
            fingerprint = hashlib.sha256(
                json.dumps(
                    {"version_id": versao_row.id, **observation}, sort_keys=True, ensure_ascii=False
                ).encode()
            ).hexdigest()
            if (
                sessao.exec(
                    select(FieldObservation).where(FieldObservation.fingerprint == fingerprint)
                ).first()
                is None
            ):
                sessao.add(
                    FieldObservation(
                        version_id=versao_row.id,
                        field=observation["candidate"]["campo"],
                        fingerprint=fingerprint,
                        payload=observation,
                        validation=observation["validation"],
                        reason=observation["reason"],
                    )
                )
        sessao.flush()

        # ------------------------------------------------------- ficha anterior?
        anteriores = list(
            sessao.exec(select(SpecValue).where(SpecValue.version_id == versao_row.id)).all()
        )
        com_valor = int(getattr(resultado.cobertura, "com_valor", 0) or 0)
        grava_valores = True
        tem_conflitos = any(c.status.value == "divergente" for _, c in resultado.spec.itens())
        if com_valor == 0 and not tem_conflitos:
            grava_valores = False
            if anteriores:
                saida.ficha_mantida = True
                saida.avisos.append(
                    "a pesquisa não fechou nenhum campo; a ficha anterior desta versão foi "
                    "mantida e nada foi substituído"
                )
            else:
                saida.avisos.append(
                    "a pesquisa não fechou nenhum campo; a versão entrou no catálogo sem "
                    "ficha, para não passar por carro comparável"
                )

        # --------------------------------------------------------------- snapshots
        baixadas = [f for f in resultado.fontes if f.baixada and f.texto]
        for fonte in baixadas:
            text_path, sha = _snapshot_em_disco(fonte, versao_row.id)
            if persist.gravar_snapshot(
                sessao,
                url=fonte.url,
                tier=int(fonte.tier),
                tipo="pdf" if fonte.url.lower().endswith(".pdf") else "html",
                captured_at=_data(fonte.captured_at),
                sha256=sha,
                text_path=text_path,
                http_status=fonte.http_status,
                version_id=versao_row.id,
            ):
                saida.snapshots += 1
        sessao.flush()

        # ------------------------------------------------------------------ valores
        if grava_valores:
            medicao = getattr(resultado, "medicao", None)
            reais = (medicao.chamadas - medicao.de_fixture) if medicao is not None else 0
            extraction_id = persist.gravar_extracao(
                sessao,
                version_id=versao_row.id,
                modelo_llm=(llm.modelo_pequeno() or "modelo") if reais > 0 else "regra",
                tokens_entrada=int(medicao.tokens_entrada) if medicao is not None else 0,
                tokens_saida=int(medicao.tokens_saida) if medicao is not None else 0,
                custo_usd=float(medicao.custo_usd) if medicao is not None else 0.0,
                job_id=job_id,
            )
            indice = persist.indice_de_snapshots(
                sessao, [f.url for f in baixadas], version_id=versao_row.id
            )
            # **Completar, não substituir.** Medido em 13/09/2026: a pesquisa da S10 voltou
            # com 32 campos e apagou os 12 tier 1 que o gabarito tinha da montadora — três
            # ficaram vazios e `deslocamento_l` virou zero. O que veio de coleta dirigida
            # fica; o que veio de pesquisa anterior é que pode sair.
            fusao = persist.fundir_valores(
                sessao,
                version_id=versao_row.id,
                spec=resultado.spec,
                snapshots=indice,
                extraction_id=extraction_id,
                require_source_proof=True,
            )
            saida.fusao = fusao
            saida.spec_values += fusao.linhas
            saida.evidences += fusao.evidencias
            saida.apagados = fusao.removidas
            saida.erros.extend(fusao.erros)

        # ------------------------------------------------------------ versão nova
        if saida.criou_versao:
            saida.alerts += _alertar_versao_nova(
                sessao,
                version_id=versao_row.id,
                nome=nome_exato,
                ano_modelo=int(ano_modelo),
                run_id=run_id,
            )

        # --------------------------------------------------------------- bloqueadas
        bloqueadas = [f.url for f in resultado.fontes if f.bloqueada]
        if bloqueadas:
            saida.alerts += persist.registrar_fontes_bloqueadas(bloqueadas, versao_row.id, sessao)
        sessao.flush()
    except Exception as exc:  # pragma: no cover - falha de banco
        sessao.rollback()
        saida.erros.append(f"falha ao gravar a ficha no catálogo: {type(exc).__name__}: {exc}")
        log.warning(
            "persistir.falhou",
            extra={"run_id": run_id, "veiculo": f"{marca} {modelo} {versao}", "erro": str(exc)},
        )
    return saida


def _comparavel(nome: str) -> str:
    """O nome sem acento, sem caixa e sem espaço repetido — só para **casar**, nunca para
    gravar. O que vai ao banco é sempre o nome como o catálogo já o escreve."""
    import re
    import unicodedata

    bruto = unicodedata.normalize("NFKD", nome or "").strip().casefold()
    sem_acento = "".join(c for c in bruto if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", sem_acento).strip()


def _nome_ja_no_catalogo(sessao, tipo: str, nome: str, *, brand_id: str | None = None) -> str:
    """O nome que o catálogo já usa para esta marca ou modelo, ou o pedido, como veio.

    Casa por forma comparável e também por **prefixo**: "mitsubishi motors" é a Mitsubishi
    que já está lá, e "MITSUBISHI" também. O que não casa entra como veio — RAM, Rampage e
    qualquer marca que ainda não esteja no catálogo têm de poder nascer na primeira
    pesquisa, e é isso que faz o Pesquisador servir para o que ele existe.
    """
    from sqlmodel import select

    from api.app.models import Brand, VehicleModel

    alvo = _comparavel(nome)
    if not alvo:
        return nome
    if tipo == "marca":
        linhas = sessao.exec(select(Brand)).all()
    else:
        linhas = sessao.exec(select(VehicleModel).where(VehicleModel.brand_id == brand_id)).all()

    for linha in linhas:
        existente = _comparavel(linha.nome)
        if existente and (existente == alvo or alvo.startswith(existente + " ")):
            return linha.nome
    return nome


def _alertar_versao_nova(
    sessao, *, version_id: str, nome: str, ano_modelo: int, run_id: str
) -> int:
    """Grava o alerta `versao_nova` — o tipo que existia em tudo, menos em emissor.

    `AlertType.VERSAO_NOVA` está no enum, `pipeline/radar/reactions.py` tem a linha dele e
    o Radar já desenha o ícone e o rótulo. Faltava quem dissesse: quando a pesquisa cria
    uma versão que o catálogo não tinha, essa é exatamente a notícia que o Radar existe
    para dar — apareceu uma versão que ninguém estava acompanhando.

    Deduplicado por (tipo, versão): re-pesquisar não repete a notícia.
    """
    from sqlmodel import select

    from api.app.models import Alert
    from pipeline.radar import reactions

    ja_existe = sessao.exec(
        select(Alert).where(Alert.type == "versao_nova", Alert.version_id == version_id)
    ).first()
    if ja_existe is not None:
        return 0
    sessao.add(
        Alert(
            type="versao_nova",
            version_id=version_id,
            field=None,
            old=None,
            new={
                "nome": nome,
                "ano_modelo": ano_modelo,
                "origem": "pesquisa",
                "run_id": run_id,
            },
            reactions_json=reactions.to_dict("versao_nova", "neutro"),
            is_simulated=False,
        )
    )
    return 1


__all__ = ["ResultadoDaGravacao", "persistir_pesquisa"]
