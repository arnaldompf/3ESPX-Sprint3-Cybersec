"""Reação sugerida por papel — tabela de regras, sem LLM.

`docs/12` §6.1 pede `reactions(tipo_alerta, direcao) → {marketing, vendas, produto, ci}`,
com textos "em português, curtos, acionáveis".

Por que tabela e não modelo de linguagem, mesmo aqui onde só se redige texto: o texto
sugere **ação sobre dinheiro**. "Revisar a comunicação de valor" e "avaliar gap de preço"
são decisões que custam, e um texto gerado varia entre execuções — duas pessoas lendo o
mesmo alerta receberiam conselhos diferentes, e ninguém saberia qual era o certo. A spec
permite LLM "apenas para redigir, com verificação numérica"; a tabela entrega o mesmo
resultado sem essa complicação, e é conferível.

O que a tabela **não** faz: dizer o que decidir. Cada texto é um próximo passo verificável
("reverificar a fonte em 7 dias"), não uma conclusão comercial ("baixar o preço").
A decisão é de quem tem o mandato.

`ci` é *competitive intelligence* — a área que mantém o dado. A reação dela é quase sempre
sobre **a fonte**, porque é dela a responsabilidade de o alerta ser verdade.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

PAPEIS = ("marketing", "vendas", "produto", "ci")


@dataclass
class Reacoes:
    """Um próximo passo por área. Os quatro sempre preenchidos."""

    marketing: str
    vendas: str
    produto: str
    ci: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


#: A tabela. Chave: `(tipo_de_alerta, direcao)`.
#:
#: `direcao` vem de `pipeline/radar/impact.py` e já está do ponto de vista da Ford, o que
#: evita cada área interpretar o sinal do delta por conta própria.
TABELA: dict[tuple[str, str], Reacoes] = {
    ("preco_oficial", "desfavorece_ford"): Reacoes(
        marketing="Revisar o battlecard e a comunicação de valor: o concorrente ficou mais barato.",
        vendas="Reforçar os argumentos das dimensões onde a Ford ganha, com evidência na ficha.",
        produto="Avaliar o novo gap de preço frente ao posicionamento da versão.",
        ci="Reverificar o preço na fonte oficial em 7 dias e confirmar se é promoção ou tabela.",
    ),
    ("preco_oficial", "favorece_ford"): Reacoes(
        marketing="Atualizar o comparativo de preço: a diferença melhorou para a Ford.",
        vendas="Usar o novo gap na conversa, sempre com a data da coleta à vista.",
        produto="Registrar a janela de oportunidade no posicionamento da versão.",
        ci="Confirmar na fonte oficial em 7 dias — aumento pode ser correção temporária.",
    ),
    ("preco_fipe", "desfavorece_ford"): Reacoes(
        marketing="Revisar o material de revenda: a FIPE do concorrente subiu.",
        vendas="Recalcular a conversa de valor de revenda com a referência do mês.",
        produto="Acompanhar a curva de desvalorização frente à versão equivalente.",
        ci="Conferir a referência mensal da FIPE e registrar o mês na evidência.",
    ),
    ("preco_fipe", "favorece_ford"): Reacoes(
        marketing="Destacar a retenção de valor da Ford com a referência FIPE do mês.",
        vendas="Levar a comparação de revenda para a conversa, citando o mês de referência.",
        produto="Registrar o movimento na análise de valor residual.",
        ci="Confirmar a referência mensal e a data de publicação da tabela.",
    ),
    ("versao_nova", "neutro"): Reacoes(
        marketing="Preparar comparativo com a versão nova antes de ela chegar às lojas.",
        vendas="Aguardar a ficha completa: ainda não há dado verificado para argumentar.",
        produto="Avaliar sobreposição de posicionamento com a linha atual.",
        ci="Coletar a ficha técnica oficial e o preço da versão nova com prioridade.",
    ),
    ("versao_removida", "neutro"): Reacoes(
        marketing="Retirar a versão dos comparativos publicados.",
        vendas="Não usar mais esta versão como referência: ela saiu de linha.",
        produto="Verificar qual versão do concorrente ocupou a faixa.",
        ci="Confirmar a saída de linha na fonte oficial e registrar a data.",
    ),
    ("campo_alterado", "neutro"): Reacoes(
        marketing="Conferir se algum material publicado cita o valor antigo.",
        vendas="Usar o valor novo; o antigo pode estar em material impresso.",
        produto="Avaliar se a mudança altera a comparação técnica da dimensão afetada.",
        ci="Confirmar a mudança na fonte e guardar as duas evidências.",
    ),
    ("fonte_bloqueada", "neutro"): Reacoes(
        marketing="Nenhuma ação: é indisponibilidade de coleta, não mudança de mercado.",
        vendas="Os dados desta fonte ficam com a data da última coleta bem-sucedida.",
        produto="Nenhuma ação imediata.",
        ci="Tentar coleta pelo navegador e registrar o motivo do bloqueio. Sem contorná-lo.",
    ),
    ("referencia_interna_divergente", "neutro"): Reacoes(
        marketing="Corrigir o material interno: ele diverge da fonte pública da montadora.",
        vendas="Usar o valor da fonte pública; o material interno está desatualizado.",
        produto="Avaliar de onde saiu o valor interno e se houve mudança de especificação.",
        ci="Anexar as duas evidências e acionar quem mantém o material interno.",
    ),
}

#: Quando o tipo existe na tabela mas a direção não, cai na direção neutra do mesmo tipo.
#: Preço com `direcao="neutro"` acontece: delta zero por arredondamento de exibição.
_NEUTRO_POR_TIPO = {
    "preco_oficial": Reacoes(
        marketing="Conferir se o material publicado cita o valor antigo.",
        vendas="Usar o valor novo, com a data da coleta.",
        produto="Movimento sem efeito prático no gap; nenhuma ação.",
        ci="Confirmar na fonte oficial se a mudança é de tabela ou de exibição.",
    ),
    "preco_fipe": Reacoes(
        marketing="Nenhuma ação: variação sem efeito prático.",
        vendas="Usar a referência do mês na conversa de revenda.",
        produto="Nenhuma ação.",
        ci="Registrar a referência mensal da nova tabela.",
    ),
}

#: Último recurso. Diz que **não há** reação mapeada, em vez de inventar uma.
SEM_REGRA = Reacoes(
    marketing="Sem reação mapeada para este tipo de alerta.",
    vendas="Sem reação mapeada. Confira o antes e o depois com a evidência.",
    produto="Sem reação mapeada para este tipo de alerta.",
    ci="Mapear a reação deste tipo em `pipeline/radar/reactions.py`.",
)


def sugerir(tipo: str, direcao: str = "neutro") -> Reacoes:
    """A reação de cada área. Sempre os quatro papéis, sempre preenchidos.

    Devolver `SEM_REGRA` em vez de texto genérico plausível é deliberado: um conselho
    inventado sobre dinheiro é pior que a admissão de que não há conselho, e a última
    linha diz onde mapear.
    """
    achada = TABELA.get((tipo, direcao))
    if achada is not None:
        return achada
    neutra = TABELA.get((tipo, "neutro")) or _NEUTRO_POR_TIPO.get(tipo)
    return neutra or SEM_REGRA


def to_dict(tipo: str, direcao: str = "neutro") -> dict[str, Any]:
    return sugerir(tipo, direcao).to_dict()


def tipos_mapeados() -> set[str]:
    """Os tipos que têm ao menos uma reação. Usado no teste de cobertura da tabela."""
    return {tipo for tipo, _ in TABELA}
