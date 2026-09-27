"""Conector genérico (tier 3) para marcas sem conector dedicado.

`docs/05` prevê "conector genérico (busca) para marcas sem conector, tier 3". O que ele
**não** faz: inventar a linha vigente. Sem conector dedicado e sem fixture de replay, a
resposta honesta é uma linha vigente **vazia** com o motivo registrado — o resolvedor
então devolve `versao_inexistente` dizendo que não sabe, em vez de `encontrada` por
otimismo.

A busca web ao vivo é uma pendência declarada: exige um provedor de busca configurado por
env, e nenhum está configurado nesta fase. Enquanto isso, `lineup_live` devolve a linha
vazia com `nota` explicando — nunca um chute.
"""

from __future__ import annotations

from pipeline.connectors.base import Connector, ResultadoLinha, SourceRef, VersionInfo


class GenericConnector(Connector):
    """Atende qualquer marca, com tier 3 e sem garantia de linha vigente."""

    marca = "generico"
    dominio = ""
    modelos = ()
    tier = 3

    def __init__(self, marca: str = "generico") -> None:
        self.marca_consultada = marca

    def atende(self, modelo: str) -> bool:
        """O genérico aceita qualquer modelo — daí ignorar o argumento."""
        del modelo
        return True

    def lineup_replay(self, modelo: str) -> ResultadoLinha:
        # Tenta a fixture; se não houver, devolve vazio com o motivo (não levanta):
        # marca sem conector é situação prevista, não erro de execução.
        try:
            return super().lineup_replay(modelo)
        except Exception:
            return ResultadoLinha(
                nota=(
                    f"sem conector dedicado para {self.marca_consultada} e sem fixture de "
                    f"linha vigente para {modelo}: linha vigente desconhecida"
                )
            )

    def lineup_live(self, modelo: str) -> ResultadoLinha:
        return ResultadoLinha(
            nota=(
                f"conector genérico: busca web não configurada nesta fase, então a linha "
                f"vigente de {self.marca_consultada} {modelo} é desconhecida. "
                "Melhor devolver 'não sei' do que uma linha inventada."
            )
        )

    def sources(self, versao: VersionInfo) -> list[SourceRef]:
        return [SourceRef(versao.url, "busca_generica", 3)] if versao.url else []
