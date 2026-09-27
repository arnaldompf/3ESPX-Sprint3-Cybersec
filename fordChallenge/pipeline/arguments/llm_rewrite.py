"""Reescrita consultiva **opcional** do argumentário, com verificação obrigatória.

O fluxo tem uma ordem que não pode ser invertida:

1. o template determinístico produz o texto (`template.py`) — este é o resultado;
2. **se** houver LLM disponível, ele reescreve em tom consultivo;
3. o verificador (`verify.py`) confere todo número contra as células;
4. reprovou, ou não houve LLM: **fica o texto do passo 1**.

Com `LLM_FAKE=1` — que é o default do projeto, do CI e da demo — o passo 2 só acontece se
houver fixture; sem fixture, a resposta sai como `gerado_por="template"` e diz por quê.
Nada de "melhorar" o texto com conhecimento do modelo: o argumentário é o que as células
sustentam.

**Por que reescrever, então?** O template é correto e soa como planilha. Numa conversa de
venda o tom importa, e a reescrita ganha o direito de existir **porque** o verificador
existe — sem ele, a troca seria texto mais bonito por texto menos verdadeiro.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pipeline.arguments import template, verify

#: O que o modelo pode e não pode fazer. Vai no `system`, e é literal de propósito.
SISTEMA = (
    "Você reescreve argumentos de venda de veículos em português do Brasil, em tom "
    "consultivo e curto. Regras absolutas: (1) use SOMENTE os números, unidades e itens "
    "que aparecem no texto de entrada; (2) não acrescente nenhum dado novo; (3) não use "
    "superlativo nem comparativo que os números não sustentem; (4) mantenha a citação da "
    "fonte e da data no fim de cada ponto; (5) mantenha o ponto que diz onde o concorrente "
    "leva vantagem, sem amenizá-lo."
)

MOTIVO_SEM_LLM = (
    "reescrita não pedida: LLM_FAKE=1 sem fixture para este par. O texto é o do template, "
    "que é o caminho padrão do produto"
)
MOTIVO_SEM_TEXTO = "o modelo não devolveu texto; template mantido"


@dataclass
class ResultadoDaReescrita:
    """O texto final, de quem veio, e a verificação que ele passou (ou não)."""

    textos: list[str]
    gerado_por: str
    motivo: str = ""
    verificacao: verify.Resultado | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "textos": list(self.textos),
            "gerado_por": self.gerado_por,
            "motivo": self.motivo,
            "verificacao": self.verificacao.to_dict() if self.verificacao else None,
        }


def _prompt(argumentario: template.Argumentario) -> str:
    pontos = [f"{i + 1}. {p.texto}" for i, p in enumerate(argumentario.pontos)]
    if argumentario.ponto_forte_concorrente is not None:
        pontos.append(f"ATENÇÃO. {argumentario.ponto_forte_concorrente.texto}")
    return (
        "Reescreva cada ponto abaixo em tom consultivo, mantendo todos os números, "
        "unidades, fontes e datas exatamente como estão. Devolva um JSON com a chave "
        '"pontos" contendo a lista de textos reescritos, na mesma ordem.\n\n' + "\n".join(pontos)
    )


def reescrever(
    argumentario: template.Argumentario,
    celulas: dict[str, template.CampoDaCelula],
    *,
    permitir_llm: bool = True,
) -> ResultadoDaReescrita:
    """Tenta a reescrita e **verifica**. Qualquer falha devolve o template.

    Note o que a função **não** faz: não tenta de novo com outro prompt, e não corrige o
    número que o modelo inventou. Um texto que inventou um valor não fica confiável depois
    de trocar aquele valor — o que ele mais tem é o resto que ninguém checou.
    """
    originais = [p.texto for p in argumentario.pontos]
    if argumentario.ponto_forte_concorrente is not None:
        originais.append(argumentario.ponto_forte_concorrente.texto)

    if not permitir_llm:
        return ResultadoDaReescrita(originais, "template", "reescrita desligada nesta chamada")

    from pipeline import llm

    resposta = llm.extrair_json(
        prompt=_prompt(argumentario),
        campos=["pontos"],
        sistema=SISTEMA,
    )
    if not resposta.ok:
        return ResultadoDaReescrita(originais, "template", resposta.motivo or MOTIVO_SEM_LLM)

    reescritos = resposta.dados.get("pontos") or []
    if not isinstance(reescritos, list) or not reescritos:
        return ResultadoDaReescrita(originais, "template", MOTIVO_SEM_TEXTO)

    textos = [str(t) for t in reescritos]
    valores: list[Any] = []
    datas: list[str] = []
    for celula in celulas.values():
        valores.extend([celula.valor_ford, celula.valor_concorrente])
        datas.extend([celula.data_ford, celula.data_concorrente])

    verificacao = verify.verificar(
        " ".join(textos),
        valores,
        datas=datas,
        # Os nomes dos campos entram: "camera 360" cita o nome do item, nao uma medida.
        nomes_de_campo=list(celulas),
    )
    if not verificacao.aprovado:
        return ResultadoDaReescrita(originais, "template", verificacao.motivo, verificacao)

    # Quantidade diferente de pontos é recusa: o modelo pode ter juntado dois pontos num
    # texto só, e aí a lista de fontes por ponto não corresponde mais ao texto exibido.
    if len(textos) != len(originais):
        return ResultadoDaReescrita(
            originais,
            "template",
            (
                f"o modelo devolveu {len(textos)} textos para {len(originais)} pontos; a "
                "correspondência entre texto e fonte se perderia"
            ),
            verificacao,
        )

    return ResultadoDaReescrita(
        textos, "llm", "reescrita verificada contra as células", verificacao
    )
