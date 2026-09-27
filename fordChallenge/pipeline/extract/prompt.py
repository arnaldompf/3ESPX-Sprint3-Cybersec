"""Prompt de extração — onde as regras invioláveis viram instrução.

Quatro regras, e todas as quatro existem por um erro real do gabarito:

1. **Só o que está no texto.** O agente genérico da linha de base "completou" campos com
   conhecimento próprio; aqui o campo sem suporte no texto volta `null`.
2. **Quote verbatim de ≤ 25 palavras.** É o que o grounding vai procurar no texto salvo.
   Quote parafraseado falha o grounding e o valor é descartado — então parafrasear não
   ajuda o modelo, atrapalha.
3. **Unidade como no texto.** A conversão é do `pipeline/normalize.py`, não do modelo:
   `kgf.m` sai como `kgf.m` e vira Nm depois, com o `raw_value` preservado na evidência.
4. **Nada de outra versão, outro ano-modelo ou outro mercado.** A ficha da Hilux tem seis
   versões em colunas; a Raptor 2024 e a 2026 diferem. Misturar é o defeito mais caro do
   domínio, porque o resultado parece certo.

A versão do prompt (`VERSAO_DO_PROMPT`) vai gravada em `extractions.prompt_versao`: sem
isso, comparar duas rodadas de eval seria comparar coisas diferentes sem saber.
"""

from __future__ import annotations

import json

from pipeline.schema import CAMPOS_BOOL, CAMPOS_LISTA, UNIDADE_CANONICA, grupo_de

#: Suba isto sempre que o texto do prompt mudar. Fica em `extractions.prompt_versao`.
VERSAO_DO_PROMPT = "1.0"

SISTEMA = """\
Você extrai especificações técnicas de veículos de documentos oficiais, para um sistema \
auditável. Sua saída é lida por máquina e conferida contra o texto original.

Regras absolutas:
1. Extraia SOMENTE o que está escrito no texto fornecido. Nunca use conhecimento próprio \
sobre o veículo. Se o texto não diz, o campo é null.
2. Todo campo com valor precisa de "evidence_quote": um trecho de ATÉ 25 PALAVRAS copiado \
EXATAMENTE do texto, caractere por caractere. Não parafraseie, não corrija, não traduza, \
não normalize espaços nem acentos. O trecho será procurado literalmente no documento; se \
não for encontrado, o valor é descartado.
3. Mantenha a unidade como o texto escreve. Se o texto diz "50,9 kgf.m", devolva \
raw_value "50,9 kgf.m". A conversão é feita depois, por código.
4. O documento pode descrever VÁRIAS versões, anos-modelo ou mercados. Extraia apenas os \
valores da versão pedida. Se não for possível saber a qual versão um valor pertence, \
devolva null para aquele campo.
5. Não invente item de equipamento, não some valores, não calcule nada.

Responda APENAS com um objeto JSON, sem texto antes ou depois."""


def _tipo_esperado(campo: str) -> str:
    if campo in CAMPOS_BOOL:
        return "true/false"
    if campo in CAMPOS_LISTA:
        return "lista de strings"
    unidade = UNIDADE_CANONICA.get(campo)
    if unidade in {"cv", "Nm", "rpm", "mm", "kg", "meses", "pol", "BRL"}:
        return f"número inteiro (unidade canônica: {unidade})"
    if unidade in {"s", "km/h", "km/l", "l"}:
        return f"número (unidade canônica: {unidade})"
    return "texto"


def descrever_campos(campos: list[str]) -> str:
    """Lista os campos pedidos com o tipo e o grupo, para o modelo não chutar formato."""
    linhas = []
    for campo in campos:
        grupo = grupo_de(campo) or "extras"
        linhas.append(f'- "{campo}" ({grupo}): {_tipo_esperado(campo)}')
    return "\n".join(linhas)


def montar(
    *,
    texto: str,
    campos: list[str],
    marca: str = "",
    modelo: str = "",
    versao: str = "",
    fonte: str = "",
    tabelas: str = "",
) -> str:
    """Monta o prompt do usuário para um documento e um conjunto de campos."""
    exemplo = {
        campos[0] if campos else "campo": {
            "raw_value": "como está escrito no texto",
            "value": "valor normalizado, ou null",
            "unit": "unidade como no texto, ou null",
            "evidence_quote": "trecho de até 25 palavras copiado exatamente do texto",
        }
    }
    partes = [
        f"Veículo pedido: {marca} {modelo} — versão **{versao}**".strip(),
        f"Fonte: {fonte}" if fonte else "",
        "",
        "Campos a extrair (use exatamente estas chaves):",
        descrever_campos(campos),
        "",
        "Formato da resposta (uma entrada por campo pedido; campo ausente do texto = null):",
        json.dumps(exemplo, ensure_ascii=False, indent=2),
        "",
    ]
    if tabelas:
        partes += [
            "Tabelas do documento, já recortadas para a versão pedida:",
            "```",
            tabelas,
            "```",
            "",
        ]
    partes += ["Texto do documento:", "```", texto, "```"]
    return "\n".join(partes).strip()


def deve_escalar(
    *, campos_pedidos: int, campos_nulos: int, n_tabelas: int, limite_nulos: float = 0.30
) -> tuple[bool, str]:
    """`docs/05`: escala para o modelo grande se houver > 3 tabelas ou ≥ 30% de nulos.

    Devolve também o **motivo**, que vai para o log: "escalou" sem motivo registrado é
    custo sem explicação.
    """
    if n_tabelas > 3:
        return True, f"documento com {n_tabelas} tabelas (> 3)"
    if campos_pedidos and campos_nulos / campos_pedidos >= limite_nulos:
        fracao = campos_nulos / campos_pedidos
        return True, f"{campos_nulos}/{campos_pedidos} campos nulos na 1a passada ({fracao:.0%})"
    return False, ""
