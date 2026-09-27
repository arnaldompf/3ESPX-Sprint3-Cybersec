"""CLI do SpecRadar: `specradar <comando>`.

Cada subcomando importa sua implementação **de forma tardia**, para que um módulo ainda
não escrito dê uma mensagem clara ("WP-XX ainda não implementada") em vez de derrubar
todo o CLI. Isso mantém `python scripts/task.py eval` utilizável desde o primeiro dia.

Comandos:
    eval      roda o gabarito e escreve reports/eval.json + reports/eval.md   (WP-02)
    seed      popula marcas, modelos, sinônimos e o usuário admin              (WP-03)
    worker    consome a tabela `jobs`                                          (WP-14)
    resolve   resolve marca+modelo+versão na linha vigente                     (WP-07)
    extract   roda o pipeline completo para uma versão                         (WP-12)
    refresh   recoleta a watchlist e gera alertas                              (WP-25)
"""

from __future__ import annotations

import argparse
import sys


class NaoImplementadaAinda(SystemExit):
    """Sai com mensagem legível quando a WP responsável ainda não rodou."""

    def __init__(self, comando: str, wp: str) -> None:
        super().__init__(
            f"specradar {comando}: ainda não implementado (responsabilidade da {wp}).\n"
            f"Veja specs/{wp}.md e specs/STATUS.md."
        )


def _cmd_eval(args: argparse.Namespace) -> int:
    try:
        from pipeline.eval.run import main as eval_main
    except ImportError as exc:  # pragma: no cover - caminho de WP não feita
        raise NaoImplementadaAinda("eval", "WP-02") from exc
    return eval_main(
        gabarito=args.gabarito,
        replay=args.replay,
        saida_json=args.out_json,
        saida_md=args.out_md,
        veiculo=args.veiculo,
    )


def _cmd_seed(args: argparse.Namespace) -> int:
    try:
        from api.app.seed import main as seed_main
    except ImportError as exc:  # pragma: no cover
        raise NaoImplementadaAinda("seed", "WP-03") from exc
    codigo = seed_main(simulated_sessions=args.simulated_sessions)
    if args.simulated_alerts:
        # Alerta de demonstracao vive em `pipeline/refresh.py`, junto do gerador de
        # alerta real: as duas rotas usam as MESMAS regras de impacto e reacao, e o que
        # e simulado e o dado, nao o calculo. Um impacto calculado por outro caminho na
        # demo mostraria uma tela que nao existe.
        from pipeline.refresh import semear_alertas_simulados

        semear_alertas_simulados(args.simulated_alerts)
    return codigo


def _cmd_fit(args: argparse.Namespace) -> int:
    """`specradar fit recompute-ranges` — recalcula as faixas de referencia.

    Comando explicito de proposito (`specs/WP-26.md`): se a faixa fosse recalculada a cada
    consulta, a nota de um veiculo cairia porque OUTRO veiculo entrou na base, e o vendedor
    veria o numero mudar sem nada ter mudado no carro dele.
    """
    from pipeline.fit.ranges import main as ranges_main

    if args.acao == "recompute-ranges":
        return ranges_main(incluir_banco=not args.somente_gabarito)
    print(f"fit: acao {args.acao!r} desconhecida")
    return 2


def _cmd_worker(args: argparse.Namespace) -> int:
    try:
        from pipeline.worker import main as worker_main
    except ImportError as exc:  # pragma: no cover
        raise NaoImplementadaAinda("worker", "WP-14") from exc
    return worker_main(once=args.once)


def _cmd_resolve(args: argparse.Namespace) -> int:
    try:
        from pipeline.resolver import main as resolve_main
    except ImportError as exc:  # pragma: no cover
        raise NaoImplementadaAinda("resolve", "WP-07") from exc
    return resolve_main(marca=args.marca, modelo=args.modelo, versao=args.versao)


def _cmd_extract(args: argparse.Namespace) -> int:
    try:
        from pipeline.run import main as run_main
    except ImportError as exc:  # pragma: no cover
        raise NaoImplementadaAinda("extract", "WP-12") from exc
    return run_main(
        marca=args.marca,
        modelo=args.modelo,
        versao=args.versao,
        atributos=args.atributo or [],
        replay=args.replay,
        version_id=args.version_id,
        persistir=args.persistir,
        saida="json" if args.json else "resumo",
    )


def _cmd_research(args: argparse.Namespace) -> int:
    """`specradar research` — procura as fontes de um veículo do zero e imprime a trilha.

    Existe para ensaiar a demonstração sem subir a API, e para medir os cinco veículos ao
    vivo da FASE D. A saída padrão é a trilha legível; `--json` devolve o objeto inteiro.
    """
    import json as _json
    import logging
    import sys

    from pipeline.research import gaps
    from pipeline.research.run import pesquisar

    if args.json:
        # Com `--json`, a saída padrão é **só** o JSON. O log estruturado do pipeline
        # também escreve em `stdout`, e misturar os dois faz `jq` — e o `verify` — falharem
        # na primeira linha. O log vai para `stderr`, onde continua visível.
        logging.basicConfig(stream=sys.stderr, force=True)
        try:
            import structlog

            structlog.configure(logger_factory=structlog.PrintLoggerFactory(file=sys.stderr))
        except Exception as exc:  # pragma: no cover - structlog sempre existe aqui
            print(f"aviso: nao consegui silenciar o log ({exc})", file=sys.stderr)

    resultado = pesquisar(
        args.marca,
        args.modelo,
        args.versao,
        ano=args.ano,
        orcamento=gaps.Orcamento(
            rodadas=args.rodadas, paginas=args.paginas, segundos=args.segundos
        ),
        provedor=args.provedor,
        checkpoint_path=args.checkpoint,
    )

    if args.json:
        print(_json.dumps(resultado.to_dict(), ensure_ascii=False, indent=2))
        return 0

    print()
    print(f"pesquisa: {resultado.marca} {resultado.modelo} {resultado.versao}".rstrip())
    print("=" * 78)
    for evento in resultado.trilha.eventos:
        print(f"  {evento.decorrido:6.1f}s  [{evento.etiqueta:10s}] {evento.texto}")
    print("=" * 78)
    cobertura = resultado.cobertura
    print(
        f"  {cobertura.com_valor} de {cobertura.total} campos com valor "
        f"({cobertura.fracao:.0%}) · {resultado.orcamento.paginas_gastas} página(s) · "
        f"{resultado.orcamento.decorrido:.1f}s"
    )
    print(
        "  parou por: " + gaps.explicar(resultado.motivo_da_parada, cobertura, resultado.orcamento)
    )
    if resultado.avisos:
        print("  avisos:")
        for aviso in resultado.avisos[:10]:
            print(f"    - {aviso}")
    print()
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    """Roda o pipeline duas vezes e mostra o que mudou entre as duas.

    Com os mesmos snapshots o resultado e **nenhum alerta**, e isso e o ponto: e o teste
    de determinismo do pipeline que qualquer pessoa pode rodar em dois segundos. Alerta
    aparecendo aqui, em replay, significa que a extracao nao e reproduzivel — e uma ficha
    que muda sozinha nao serve para comparar preco de caminhonete.
    """
    from pipeline.diff import comparar
    from pipeline.run import _version_id_provavel, run

    version_id = args.version_id or _version_id_provavel(args.marca, args.modelo, args.versao)
    comum = {"replay": True, "version_id": version_id}
    antes = run(args.marca, args.modelo, args.versao, job_id="diff:antes", **comum)
    depois = run(args.marca, args.modelo, args.versao, job_id="diff:depois", **comum)

    resultado = comparar(antes, depois)
    print(f"{args.marca} {args.modelo} {args.versao}")
    print(f"  campos inalterados: {resultado.inalterados}")
    print(f"  alertas: {len(resultado.alertas)}")
    for alerta in resultado.alertas:
        print(f"    [{alerta.type}] {alerta.field}: {alerta.old!r} -> {alerta.new!r}")
    if not resultado.alertas:
        print("  (nenhuma mudanca: o pipeline e deterministico com os mesmos snapshots)")
    return 0


def _cmd_refresh(args: argparse.Namespace) -> int:
    try:
        from pipeline.refresh import main as refresh_main
    except ImportError as exc:  # pragma: no cover
        raise NaoImplementadaAinda("refresh", "WP-25") from exc
    return refresh_main(watchlist=args.watchlist, limite=args.limite)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="specradar", description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="comando", required=True)

    pe = sub.add_parser("eval", help="roda o gabarito e escreve os relatórios")
    pe.add_argument("--gabarito", default="gabarito/gabarito_v1.json")
    pe.add_argument("--replay", action="store_true", help="usa apenas snapshots salvos")
    pe.add_argument("--out-json", default="reports/eval.json")
    pe.add_argument("--out-md", default="reports/eval.md")
    pe.add_argument("--veiculo", default=None, help="avalia só este id do gabarito")
    pe.set_defaults(func=_cmd_eval)

    ps = sub.add_parser("seed", help="popula o banco (idempotente)")
    ps.add_argument(
        "--simulated-sessions",
        type=int,
        default=0,
        help="cria N sessões de showroom com is_simulated=true (rótulo SIMULAÇÃO)",
    )
    ps.add_argument(
        "--simulated-alerts",
        type=int,
        default=0,
        help="cria N alertas de demonstracao com is_simulated=true (rotulo SIMULACAO)",
    )
    ps.set_defaults(func=_cmd_seed)

    pw = sub.add_parser("worker", help="consome a tabela jobs")
    pw.add_argument("--once", action="store_true", help="processa um job e sai")
    pw.set_defaults(func=_cmd_worker)

    pr = sub.add_parser("resolve", help="resolve a versão na linha vigente")
    pr.add_argument("marca")
    pr.add_argument("modelo")
    pr.add_argument("versao")
    pr.set_defaults(func=_cmd_resolve)

    px = sub.add_parser("extract", help="roda o pipeline completo para uma versão")
    px.add_argument("marca")
    px.add_argument("modelo")
    px.add_argument("versao")
    px.add_argument("--atributo", action="append", help="atributo livre (repetível)")
    px.add_argument("--replay", action="store_true")
    px.add_argument("--json", action="store_true", help="imprime a StandardSpec validada")
    px.add_argument("--version-id", default="", help="id do snapshot (senão, é inferido)")
    px.add_argument("--persistir", action="store_true", help="grava a ficha no banco")
    px.set_defaults(func=_cmd_extract)

    prs = sub.add_parser(
        "research", help="procura as fontes de um veículo do zero e completa a ficha"
    )
    prs.add_argument("marca")
    prs.add_argument("modelo")
    prs.add_argument("versao", nargs="?", default="")
    prs.add_argument("--ano", type=int, default=None)
    prs.add_argument("--rodadas", type=int, default=2, help="teto de rodadas de busca")
    prs.add_argument("--paginas", type=int, default=12, help="teto de páginas coletadas")
    prs.add_argument("--segundos", type=float, default=180.0, help="teto de tempo")
    prs.add_argument("--provedor", default="", help="tavily | brave | duckduckgo | searxng")
    prs.add_argument(
        "--checkpoint",
        default="",
        help="salva/retoma fontes e candidatos; limites totais acumulados",
    )
    prs.add_argument("--json", action="store_true", help="imprime o resultado inteiro")
    prs.set_defaults(func=_cmd_research)

    pd = sub.add_parser("diff", help="compara duas coletas da mesma versão e mostra alertas")
    pd.add_argument("marca")
    pd.add_argument("modelo")
    pd.add_argument("versao")
    pd.add_argument("--version-id", default="", help="id do snapshot (senão, é inferido)")
    pd.set_defaults(func=_cmd_diff)

    pf = sub.add_parser("refresh", help="recoleta a watchlist e gera alertas")
    pf.add_argument("--watchlist", action="store_true")
    pf.add_argument("--limite", type=int, default=None, help="para no N-esimo veiculo")
    pf.set_defaults(func=_cmd_refresh)

    pfit = sub.add_parser("fit", help="Customer Need Engine: manutencao das faixas")
    pfit.add_argument(
        "acao",
        choices=["recompute-ranges"],
        help="recompute-ranges: reescreve pipeline/fit/scoring_ranges.yaml",
    )
    pfit.add_argument(
        "--somente-gabarito",
        action="store_true",
        help="ignora o banco e usa so os valores do gabarito (util em CI sem banco)",
    )
    pfit.set_defaults(func=_cmd_fit)

    return p


def main(argv: list[str] | None = None) -> int:
    from dotenv import load_dotenv

    load_dotenv(override=False)
    args = build_parser().parse_args(argv if argv is not None else sys.argv[1:])
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
