"""Gera gabarito_v1.json — verdade-terra verificada para o eval do SpecRadar.

Regras de construção:
- Cada atributo tem `status`, `esperado` (forma canônica comparável), `tier` da melhor fonte,
  `fontes` (URLs) e `trecho` (verbatim). Nunca há valor inventado.
- Status: verificado | verificado_tier3 | divergente | nao_disponivel | nao_encontrado |
  pendente_coleta | versao_inexistente.
- Valores do slide interno da Ford ficam em `slide_ford` para o teste "slide × fonte pública".
- Conversões: 1 kgf·m = 9,80665 N·m (registradas como conversão, não como escolha de fonte).


================================ v1.1 · 10/09/2026 ================================

Três mudanças, e cada uma tem o motivo escrito aqui porque `docs/09` é explícito: **só
humano** promove ou altera o gabarito. As três foram autorizadas nominalmente, e nada
além delas foi tocado.

--------------------------------------------------------------------------------
1) `cilindros` passa a exigir **só a contagem**. O arranjo era inferência.
--------------------------------------------------------------------------------
Estava `"4 em linha"` na Hilux e na S10, `"V6"` na Raptor e na Amarok. Dois problemas:

* **o arranjo não estava em fonte.** Varri os snapshots salvos da Hilux procurando
  "cilindr": as fichas trazem `"Cilindrada (cm3) 2755"` e **nada mais**. "4 em linha"
  saiu do que se sabe sobre motores 2.8 diesel, não do que a fonte afirma — e "nunca
  inferir" é a primeira regra inviolável do projeto. Na S10 a contagem **está** na fonte
  ("2.8 turbodiesel de quatro cilindros"), mas o arranjo também não;
* **as duas grafias não eram comparáveis.** `"V6"` traz contagem e arranjo colados; `4`
  traz só contagem. A régua comparava como texto, e a Amarok aparecia `divergente` no
  eval com o motivo `"exato"` — a régua discordando de si mesma.

O que mudou: o `esperado` é a contagem, e a régua extrai a contagem dos dois lados
(`pipeline/eval/compare.CAMPOS_DE_CONTAGEM`: `"V6"` → 6, `"4 em linha"` → 4). O arranjo
**continua no valor que a ficha exibe** — ninguém perde a informação; ele só sai do que é
medido. A Hilux fica `nao_encontrado`, que é o que a fonte sustenta.

--------------------------------------------------------------------------------
2) `pacote_adas` compara **conjuntos de função**, normalizados por sinônimos.
--------------------------------------------------------------------------------
`docs/09` já mandava isso para listas ("comparação de conjuntos após normalização de
sinônimos"), e para `adas_itens` não havia vocabulário — a comparação caía em
similaridade de texto. O problema não é teórico: a Toyota escreve
`"Pre-crash System (PCS) com frenagem automática (carros, pedestres, ciclistas)"` e a
Chevrolet escreve `"frenagem automática de emergência"`. É a **mesma função**, e as duas
frases não compartilham palavra nenhuma além de "frenagem" e "automática" — nenhuma
medida de similaridade ia casá-las.

O vocabulário entrou em `pipeline/synonyms_seed.json` (`adas_itens`: 19 funções
canônicas, 65 redações, todas colhidas dos textos salvos). O comparador tenta sinônimo
primeiro e cai para similaridade só no item que **nenhum** dos lados canoniza.

Uma coisa que isso **expôs** e que fica registrada para revisão humana: a lista de ADAS
da Hilux inclui `"7 airbags"`, que não é ADAS e está duplicado com
`seguranca.airbags_qtd`. Não removi — não estava autorizado. Ele cai no ramo de
similaridade e continua sendo exigido.

--------------------------------------------------------------------------------
3) Entra a **Ford Ranger diesel de topo**, com a marcação de que não é conferida à mão.
--------------------------------------------------------------------------------
`ford_ranger_limited_2027`, Limited 3.0 V6 Diesel 4WD AT 2027, coletada em 10/09/2026 por
`scripts/coleta/coletar_faltantes.py`. Toda entrada dela leva

    origem = "extraído pelo pipeline; confirmação humana pendente"

porque é exatamente isso: nenhum olho humano conferiu campo a campo. Ela **não** é
verdade-terra no mesmo grau que os quatro veículos da coleta de 01/09 — é o melhor que a
máquina produziu, com URL, trecho verbatim e data em cada campo, esperando conferência.

Duas escolhas dela que precisam de confirmação, e estão em `DECISOES_NOITE.md` D-161:

* **a versão.** A escolha foi automática, pela **maior "a partir de" entre as diesel** da
  linha coletada. A página lista também `"Limited 3.0 V6 Diesel 4WD AT 2027 + Kit
  Opcional"` a R$ 372.900 — mesma versão com pacote de acessórios, e por isso ficou fora;
* **o `codigo_fipe` `003497-5`** foi descoberto na navegação da API e conferido contra o
  nome que ela devolve (`"Ranger Limited 3.0 V6 4x4 CD TB Die. Aut"`), não contra
  catálogo. E a FIPE responde por ela no registro **zero-quilômetro**: a tabela de
  setembro/2026 ainda não abriu o ano-modelo 2027.
"""

import datetime
import json

KGFM = 9.80665
FORD_SITE = "https://www.ford.com.br/picapes/ranger-raptor/raptor-4wd-at/"
FORD_PDF = "https://www.ford.com.br/content/dam/Ford/website-assets/latam/br/nameplate/2025/ranger-raptor/pdf/fbr-ranger-raptor-ficha-tecnica.pdf"
FORD_FIPE = "https://www.tabelafipebrasil.com/carros/FORD/RANGER-RAPTOR-30-V6-BI-TURBO-4WD-AUT/2026-Gasolina"
AE_RAPTOR = "https://autoesporte.globo.com/carros/testes-de-carros/review/2024/05/teste-ford-ranger-raptor-e-piccape-que-acelera-mais-que-muito-esportivo.ghtml"
CNW_RAPTOR = "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=46982"
CNW_LIMITED = "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=49974"
CNW_S10 = "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=47930"
CNW_AMAROK = "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=44849"
CNW_HILUX = "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=41190"
CNW_NOTA = "Fase 2 do plano 18/18 (2026-09-15): CarrosNaWeb (tier 3), ficha por versão+ano."
TOY_SITE = "https://www.toyota.com.br/modelos/hilux-cabine-dupla"
TOY_PDF = "https://media.toyota.com.br/d400f124-b3ac-4d73-a885-5d6828812f11.pdf"
TOY_FIPE_SRXP = (
    "https://www.tabelafipebrasil.com/carros/TOYOTA/HILUX-CD-SRX-PLUS-4X4-28-TDI-DIE-AUT"
)
VW_SITE = "https://www.vw.com.br/pt/carros/amarok.html"
AE_AMAROK = "https://autoesporte.globo.com/setor-automotivo/mercado-automotivo/noticia/2025/08/volkswagen-amarok-2026-precos-versoes-equipamentos.ghtml"
VW_FIPE = "https://www.tabelafipebrasil.com/carros/VW---VOLKSWAGEN/AMAROK-EXTREME-CD-30-4X4-TB-DIES-AUT/2026-Diesel"
GM_SITE = "https://www.chevrolet.com.br/picapes/s10"
AE_S10 = "https://autoesporte.globo.com/setor-automotivo/mercado-automotivo/noticia/2026/07/chevrolet-s10-2027-precos-versoes-equipamentos-consumo.ghtml"
GM_FIPE = "https://www.webmotors.com.br/tabela-fipe/carros/chevrolet/s10/2027/28-16v-turbo-diesel-high-country-cd-4x4-automatico"

# --- coleta de 10/09/2026 (scripts/coleta/coletar_faltantes.py) -------------------
FORD_RANGER_COMPARADOR = "https://www.ford.com.br/picapes/ranger/compare-as-versoes.html"
FORD_RANGER_LIMITED = (
    "https://www.ford.com.br/picapes/ranger/compare-as-versoes/limited-30-diesel-4wd-at.html"
)
FORD_RANGER_PDF = "https://www.ford.com.br/content/dam/Ford/website-assets/latam/br/nameplate/2025/nova-geracao-ranger/pdf/fbr-ranger-ficha-tecnica.pdf"
PBE_TABELA = "https://www.gov.br/inmetro/pt-br/assuntos/regulamentacao/avaliacao-da-conformidade/programa-brasileiro-de-etiquetagem/tabelas-de-eficiencia-energetica/veiculos-automotivos-pbe-veicular"
FIPE_API_RANGER_LIMITED = (
    "https://parallelum.com.br/fipe/api/v1/carros/marcas/22/modelos/10761/anos/32000-3"
)

#: A marcação obrigatória de toda entrada da Ranger Limited. Ver o bloco v1.1 no topo.
PIPELINE = "extraído pelo pipeline; confirmação humana pendente"


def A(esperado, status="verificado", tier=1, fontes=(), trecho=None, **extra):
    d = {"esperado": esperado, "status": status, "tier": tier, "fontes": list(fontes)}
    if trecho:
        d["trecho"] = trecho
    d.update(extra)
    return d


NE = lambda fontes, nota=None: A(
    None, "nao_encontrado", None, fontes, None, **({"nota": nota} if nota else {})
)
PEND = lambda nota: A(None, "pendente_coleta", None, [], None, nota=nota)

raptor = {
    "id": "ford_ranger_raptor_2026",
    "marca": "Ford",
    "modelo": "Ranger",
    "versao": "Raptor 3.0 V6 Bi-turbo 4WD AT",
    "ano_modelo": 2026,
    "codigo_fipe": "003506-8",
    "papel": "veiculo_ford_referencia",
    "origem": "Manus rodada 1 (2026-09-01) conferido contra slide Ford; textos brutos em raw/",
    "linha_vigente": [{"nome_exato": "Raptor 4WD AT", "ano_modelo": 2026}],
    "atributos": {
        "motor": A(
            {
                "deslocamento_l": 3.0,
                "cilindros": 6,
                "combustivel": "gasolina",
                "aspiracao": "biturbo",
            },
            fontes=[FORD_SITE, FORD_PDF],
            trecho="Motor 3.0L V6 Bi-turbo de 397cv com 583Nm",
            slide_ford="V6 3.0L Nano bi turbo",
            nota="'Nano' é nome interno; não aparece em fonte pública",
        ),
        "potencia_cv": A(
            397, fontes=[FORD_SITE, FORD_PDF], trecho="Potencia 397cv", slide_ford=397
        ),
        "potencia_rpm": A(
            6250,
            "divergente",
            3,
            [CNW_RAPTOR],
            "cv a 6250 rpm",
            slide_ford=5650,
            nota="Fase 2 do plano 18/18 (2026-09-15): CarrosNaWeb (tier 3) "
            "publica 6250 rpm; slide interno da Ford diz 5650. Fonte pública prevalece "
            "(slide é tier 4 e sempre perde); divergência exposta, não escondida.",
        ),
        "torque_nm": A(583, fontes=[FORD_SITE, FORD_PDF], trecho="Torque 583Nm", slide_ford=583),
        "torque_rpm": A(
            3500,
            "verificado_tier3",
            3,
            [CNW_RAPTOR],
            "kgfm a 3500 rpm",
            slide_ford=3500,
            nota="Fase 2 do plano 18/18 (2026-09-15): CarrosNaWeb (tier 3) "
            "publica 3500 rpm, concorda com o slide interno.",
        ),
        "transmissao": A(
            {"tipo": "automatica", "numero_marchas": 10, "paddle_shifters": True},
            fontes=[FORD_SITE, FORD_PDF],
            trecho="Transmissão AT de 10 velocidades; Paddle Shifters",
            slide_ford="AT de 10 velocidades e paddle shifters",
            nota="Manus perdeu 'Paddle Shifters' embora estivesse na fonte — caso de teste de campo composto",
        ),
        "tracao": A(
            {"tipo": "4x4", "descricao": "4WD"},
            fontes=[FORD_SITE, FORD_PDF],
            trecho="Tração 4WD",
            slide_ford="4WD",
        ),
        "amortecedores": A(
            "FOX Racing 2.5 Live Valve",
            fontes=[FORD_SITE, FORD_PDF],
            trecho="Amortecedores FOX 2.5” Racing com tecnologia Live Valve",
            slide_ford='Live Valve FOX Racing 2.5"',
        ),
        "aceleracao_0_100_s": A(
            5.8,
            "verificado_tier3",
            3,
            [AE_RAPTOR],
            "A Ford declara que a Ranger Raptor vai de 0 a 100 km/h em 5,8 segundos",
            slide_ford=5.8,
            divergencias=[{"valor": 6.5, "fonte": AE_RAPTOR, "nota": "medido em teste"}],
        ),
        "modos_conducao": A(
            ["normal", "sport", "escorregadio", "lama", "areia", "baja", "rock_crawl"],
            fontes=[FORD_SITE, FORD_PDF],
            trecho="7 modos de condução selecionáveis – Normal, Esportivo, Escorregadio, Lama/Terra, Areia, Baja, Rock Crawl",
            slide_ford=["normal", "sport", "escorregadio", "lama", "areia", "rock_crawl", "baja"],
            sinonimos={"esportivo": "sport", "lama/terra": "lama"},
        ),
        "modos_direcao": A(
            ["normal", "conforto", "sport", "off_road"],
            "divergente",
            1,
            [FORD_SITE, FORD_PDF],
            "4 modos de direção selecionáveis – Normal, Conforto, Sport, Off-Road",
            slide_ford=["normal", "sport", "conforto"],
            nota="Slide diz 3 modos de 'volante'; ficha pública diz 4 modos de 'direção'. Sinônimo volante≈direção. Manus marcou nao_encontrado por buscar a palavra 'volante'.",
        ),
        "modos_escapamento": A(
            ["silencioso", "normal", "sport", "baja"],
            fontes=[FORD_SITE, FORD_PDF],
            trecho="4 modos de escapamento selecionáveis – Silencioso, Normal, Sport, Baja",
            slide_ford=["normal", "silencioso", "sport", "baja"],
        ),
        "modos_amortecedor": A(
            ["normal", "sport", "off_road"],
            "divergente",
            1,
            [FORD_SITE, FORD_PDF],
            "3 modos de amortecedor selecionáveis – Normal, Sport e Off-Road",
            slide_ford=["normal", "sport", "baja"],
            nota="Slide diz Baja; fonte pública 2026 diz Off-Road",
        ),
        "farois": A(
            {"tipo": "Matrix LED", "neblina": "LED", "nivelamento": "elétrico"},
            fontes=[FORD_SITE, FORD_PDF],
            trecho="Faróis Matrix Led",
            slide_ford="Matrix LED",
        ),
        "rodas_pneus": A(
            {
                "aro_pol": 17,
                "material": "liga leve",
                "pneus": "285/70 R17",
                "tipo_pneu": "AT",
                "marca_pneu": "General Grabber",
            },
            fontes=[FORD_SITE, FORD_PDF],
            trecho='Pneus 285/70 R17 General Grabber; Rodas de liga leve 17"',
            slide_ford='17" com 285/70 R17 AT',
        ),
        "pacote_adas": A(
            {
                "nome_comercial": None,
                "itens": [
                    "alerta de colisão",
                    "alerta de tráfego cruzado",
                    "frenagem autônoma dianteira e em marcha à ré",
                    "assistente de manobras evasivas",
                    "permanência e centralização em faixa",
                    "ACC Stop and Go",
                    "farol alto automático",
                    "câmera 360°",
                    "BLIS",
                    "sensores dianteiro/traseiro",
                    "Pro Trailer",
                ],
            },
            fontes=[FORD_SITE, FORD_PDF],
            nota="Ford não usa nome comercial na ficha BR (Co-Pilot360 não aparece)",
        ),
        "preco_sugerido_brl": A(
            499000,
            fontes=[FORD_SITE],
            trecho="Raptor 3.0 V6 Bi-turbo 4WD AT 2026 (AOD6) ... R$ 499.000",
            data="2026-09-01",
            slide_ford="R$499.00 (typo do slide; ler R$ 499.000)",
        ),
        "preco_fipe_brl": A(
            452540,
            tier=2,
            fontes=[FORD_FIPE],
            trecho="Referência FIPE: Setembro 2026; Preço: R$ 452.540,00",
            referencia="2026-09",
        ),
    },
}

hilux_gr_negativo = {
    "id": "toyota_hilux_gr_sport_2026_inexistente",
    "marca": "Toyota",
    "modelo": "Hilux",
    "versao": "GR-Sport",
    "ano_modelo": 2026,
    "codigo_fipe": "002177-6 (histórico, último ano 2024)",
    "papel": "caso_negativo_resolvedor_de_versao",
    "origem": "Manus rodada 2 (2026-09-01)",
    "linha_vigente": [
        {"nome_exato": n, "ano_modelo": 2026}
        for n in ["STD Power Pack AT", "SR AT", "SRV AT", "SRX AT", "SRX Plus AT"]
    ],
    "resultado_esperado": {
        "status": "versao_inexistente",
        "mensagem_contem": ["não está na linha vigente", "SRX Plus"],
        "sugestao_equivalente": "SRX Plus AT",
        "ultimo_ano_fipe": 2024,
        "fontes": [
            TOY_SITE,
            TOY_PDF,
            "https://www.tabelafipebrasil.com/carros/TOYOTA/HILUX-CD-GR-S-4X4-28-TDI-DIES-AUT",
        ],
    },
    "atributos": {},
}

hilux_srxp = {
    "id": "toyota_hilux_srx_plus_at_2026",
    "marca": "Toyota",
    "modelo": "Hilux",
    "versao": "SRX Plus AT (Cabine Dupla)",
    "ano_modelo": 2026,
    "codigo_fipe": "002215-2",
    "papel": "concorrente",
    "origem": "Extraído manualmente do PDF oficial 'HILUX MY26' (páginas 6 e 7) já baixado; layout em raw/toyota_hilux_my26_p6_p7_layout.txt",
    "linha_vigente": hilux_gr_negativo["linha_vigente"],
    "atributos": {
        "motor": A(
            {
                "deslocamento_l": 2.8,
                "cilindros": 4,
                "valvulas": 16,
                "combustivel": "diesel",
                "aspiracao": "turbo geometria variável + intercooler",
            },
            fontes=[TOY_PDF],
            trecho="Motor a Diesel 2.8L 16V Turbo* Intercooler (*Turbo com geometria variável)",
            pagina_pdf=6,
        ),
        "potencia_cv": A(204, fontes=[TOY_PDF], trecho="204/ 3.400 (cv/rpm)", pagina_pdf=6),
        "potencia_rpm": A(3400, fontes=[TOY_PDF], trecho="204/ 3.400 (cv/rpm)", pagina_pdf=6),
        "torque_nm": A(
            round(50.9 * KGFM),
            fontes=[TOY_PDF],
            trecho="50,9/ 2.800 (kgf.m/rpm)",
            pagina_pdf=6,
            valor_bruto="50,9 kgf.m",
            conversao="kgf.m→Nm ×9,80665",
        ),
        "torque_rpm": A(2800, fontes=[TOY_PDF], trecho="50,9/ 2.800 (kgf.m/rpm)", pagina_pdf=6),
        "transmissao": A(
            {"tipo": "automatica", "numero_marchas": 6, "paddle_shifters": None},
            fontes=[TOY_PDF],
            trecho="Automática de 6 velocidades sequencial",
            pagina_pdf=6,
            nota="paddle_shifters: nao_encontrado (lista oficial não cita)",
        ),
        "tracao": A(
            {
                "tipo": "4x4 sob demanda",
                "descricao": "4×2, 4×4; reduzida com acionamento eletrônico; bloqueio do diferencial",
            },
            fontes=[TOY_PDF],
            trecho="4×2, 4×4 Reduzida com acionamento eletrônico ... A-TRC com bloqueio do diferencial",
            pagina_pdf=6,
        ),
        "amortecedores": A(
            {
                "suspensao_dianteira": "independente, braços duplos triangulares, molas helicoidais e barra estabilizadora",
                "suspensao_traseira": "eixo rígido, molas semielípticas de duplo estágio e barra estabilizadora",
                "amortecedores": None,
            },
            fontes=[TOY_PDF],
            trecho="Eixo rígido, molas semielípticas de duplo estágio e barra estabilizadora",
            pagina_pdf=7,
            nota="Marca/modelo de amortecedor não informado (nao_encontrado); suspensão descrita",
        ),
        "aceleracao_0_100_s": A(
            12.0, "verificado_tier3", 3, [CNW_HILUX], "Aceleração 0-100 km/h  | 12 s", nota=CNW_NOTA
        ),
        "modos_conducao": A(
            ["eco", "power"],
            fontes=[TOY_PDF],
            trecho="Modos de seleção de condução Eco e Power",
            pagina_pdf=6,
        ),
        "modos_direcao": NE([TOY_PDF, TOY_SITE], "lista oficial completa de equipamentos não cita"),
        "modos_escapamento": NE(
            [TOY_PDF, TOY_SITE], "lista oficial completa de equipamentos não cita"
        ),
        "modos_amortecedor": NE(
            [TOY_PDF, TOY_SITE], "lista oficial completa de equipamentos não cita"
        ),
        "farois": A(
            {"tipo": "LED", "neblina": "LED", "nivelamento": "automático"},
            fontes=[TOY_PDF],
            trecho="Faróis de LED; Faróis de neblina dianteiros de LED; Nivelamento dos faróis dianteiros automático",
            pagina_pdf=6,
        ),
        "rodas_pneus": A(
            {"aro_pol": 18, "material": "liga leve", "pneus": "265/60 R18", "tipo_pneu": None},
            fontes=[TOY_PDF],
            trecho='Pneus 265/60 R18; Rodas Liga leve 18"',
            pagina_pdf=7,
            nota="coluna SRX AT / SRX Plus AT da tabela",
        ),
        "pacote_adas": A(
            {
                "nome_comercial": "Toyota Safety Sense (TSS)",
                "itens": [
                    "Pre-crash System (PCS) com frenagem automática (carros, pedestres, ciclistas)",
                    "Lane Departure Alert (LDA)",
                    "Adaptive Cruise Control (ACC)",
                    "7 airbags",
                    "câmera 360º (PVM)",
                    "sensores dianteiros (2) e traseiros (4)",
                ],
            },
            fontes=[TOY_PDF],
            trecho="Assistente de pré-colisão frontal (Pre-crash System - PCS) ... TSS",
            pagina_pdf=6,
        ),
        "preco_sugerido_brl": PEND(
            "Site exibe apenas 'A partir de R$ 292.790,00' para a linha (versão de entrada). Coletar no configurador Toyota ou release; não inferir."
        ),
        "preco_fipe_brl": PEND(
            "Código FIPE 002215-2 confirmado (tabelafipebrasil). Coletar via API FIPE na referência do mês vigente."
        )
        | {"fontes": [TOY_FIPE_SRXP]},
    },
}

amarok = {
    "id": "vw_amarok_v6_extreme_2026",
    "marca": "Volkswagen",
    "modelo": "Amarok",
    "versao": "V6 Extreme",
    "ano_modelo": 2026,
    "codigo_fipe": "005506-9",
    "papel": "concorrente",
    "origem": "Manus rodada 3 (2026-09-02); textos brutos em raw/ (sem prints)",
    "linha_vigente": [
        {
            "nome_exato": "V6 Comfortline",
            "ano_modelo": 2026,
            "preco_a_partir_brl": 339990,
            "fonte_preco": AE_AMAROK,
            "tier": 3,
        },
        {
            "nome_exato": "V6 Highline",
            "ano_modelo": 2026,
            "preco_a_partir_brl": 356990,
            "fonte_preco": AE_AMAROK,
            "tier": 3,
        },
        {
            "nome_exato": "V6 Extreme",
            "ano_modelo": 2026,
            "preco_a_partir_brl": 379990,
            "fonte_preco": AE_AMAROK,
            "tier": 3,
        },
    ],
    "atributos": {
        "motor": A(
            {
                "deslocamento_l": 3.0,
                "cilindros": 6,
                "combustivel": "diesel",
                "aspiracao": "turbo (TDI)",
            },
            fontes=[VW_SITE],
            trecho="A picape vem com o motor V6 3.0 TDI de 258 cv com 59,1 kgfm de torque",
        ),
        "potencia_cv": A(258, fontes=[VW_SITE], trecho="Motor V6 Potência 258 cv"),
        "potencia_rpm": A(
            3250, "verificado_tier3", 3, [CNW_AMAROK], "cv a 3250 rpm", nota=CNW_NOTA
        ),
        "torque_nm": A(
            round(59.1 * KGFM),
            fontes=[VW_SITE],
            trecho="59,1 kgfm de torque",
            valor_bruto="59,1 kgfm",
            conversao="kgf.m→Nm ×9,80665",
            divergencias=[
                {"valor_bruto": "59 kgfm", "fonte": AE_AMAROK, "nota": "arredondamento da imprensa"}
            ],
        ),
        "torque_rpm": A(
            1400, "verificado_tier3", 3, [CNW_AMAROK], "kgfm a 1400 rpm", nota=CNW_NOTA
        ),
        "transmissao": A(
            {"tipo": "automatica", "numero_marchas": 8, "paddle_shifters": True},
            fontes=[VW_SITE],
            trecho="Transmissão Automática de 8 velocidades; troca de marchas por aletas no volante",
            sinonimos={"aletas no volante": "paddle_shifters"},
        ),
        "tracao": A(
            {"tipo": "4x4 permanente", "descricao": "4Motion (4x4 Permanente)"},
            fontes=[VW_SITE],
            trecho="Tração 4Motion (4x4 Permanente)",
        ),
        "amortecedores": NE([VW_SITE, AE_AMAROK]),
        "aceleracao_0_100_s": A(
            8.0, fontes=[VW_SITE, AE_AMAROK], trecho="indo de 0 a 100 km/h em 8 segundos"
        ),
        "modos_conducao": NE([VW_SITE, AE_AMAROK]),
        "modos_direcao": NE([VW_SITE, AE_AMAROK]),
        "modos_escapamento": NE([VW_SITE, AE_AMAROK]),
        "modos_amortecedor": NE([VW_SITE, AE_AMAROK]),
        "farois": A(
            {
                "tipo": "Full LED",
                "extra": "grade frontal iluminada (light strip); Coming & Leaving home",
            },
            fontes=[VW_SITE],
            trecho="faróis Full LED e rodas de liga leve 20”",
        ),
        "rodas_pneus": A(
            {"aro_pol": 20, "material": "liga leve", "pneus": None},
            fontes=[VW_SITE, AE_AMAROK],
            trecho="rodas de liga leve 20”",
            nota="medida de pneu nao_encontrada",
        ),
        "pacote_adas": A(
            {
                "nome_comercial": "Safer Tag",
                "itens": [
                    "aviso de colisão com pedestres e ciclistas",
                    "Forward collision warning",
                    "Lane alert",
                ],
            },
            fontes=[VW_SITE],
            trecho="Safer Tag – Assistente de condução passiva",
        ),
        "preco_sugerido_brl": A(
            379990,
            "verificado_tier3",
            3,
            [AE_AMAROK],
            "Extreme (R$ 379.990)",
            data="2025-08-26",
            nota="Site oficial não exibiu preço por versão no texto capturado; imprensa como tier 3 — não substitui oficial",
        ),
        "preco_fipe_brl": A(
            339270,
            tier=2,
            fontes=[VW_FIPE],
            trecho="Referência FIPE: Setembro 2026; Preço: R$ 339.270,00",
            referencia="2026-09",
        ),
    },
}

s10 = {
    "id": "chevrolet_s10_high_country_2027",
    "marca": "Chevrolet",
    "modelo": "S10",
    "versao": "High Country",
    "ano_modelo": 2027,
    "codigo_fipe": "004464-4",
    "papel": "concorrente",
    "origem": "Manus rodada 4 (2026-09-01/02), tarefa nova; prints e textos em s10_entrega.zip",
    "linha_vigente": [
        {
            "nome_exato": n,
            "ano_modelo": 2027,
            "preco_a_partir_brl": p,
            "fonte_preco": GM_SITE,
            "tier": 1,
        }
        for n, p in [
            ("S10 Cabine Simples", 265690),
            ("S10 WT MT", 285890),
            ("S10 WT AT", 304590),
            ("S10 Z71", 325290),
            ("S10 LTZ", 333690),
            ("Trail Boss", 341290),
            ("S10 High Country", 348790),
        ]
    ],
    "atributos": {
        "motor": A(
            {"deslocamento_l": 2.8, "cilindros": 4, "combustivel": "diesel", "aspiracao": "turbo"},
            fontes=[GM_SITE, AE_S10],
            trecho="Motor 2.8 turbo diesel de 207 cv",
        ),
        "potencia_cv": A(
            207, fontes=[GM_SITE, AE_S10], trecho="motor turbo diesel mais eficiente de 207 cv"
        ),
        "potencia_rpm": A(3200, "verificado_tier3", 3, [CNW_S10], "cv a 3200 rpm", nota=CNW_NOTA),
        "torque_nm": A(
            round(52 * KGFM),
            fontes=[GM_SITE, AE_S10],
            trecho="e 52 kgfm de torque",
            valor_bruto="52 kgfm",
            conversao="kgf.m→Nm ×9,80665",
        ),
        "torque_rpm": A(2000, "verificado_tier3", 3, [CNW_S10], "kgfm a 2000 rpm", nota=CNW_NOTA),
        "transmissao": A(
            {"tipo": "automatica", "numero_marchas": 8, "paddle_shifters": None},
            fontes=[GM_SITE],
            trecho="Com câmbio automático de 8 marchas",
            nota="paddle_shifters nao_encontrado",
        ),
        "tracao": A(
            {"tipo": "4x4", "descricao": "4x4 em todas as configurações"},
            "verificado_tier3",
            3,
            [AE_S10],
            "4x4 em todas as configurações",
        ),
        "amortecedores": A(
            {"amortecedores": None, "descricao_oficial": "suspensão com calibração refinada"},
            "verificado",
            1,
            [GM_SITE],
            "Suspensão com calibração refinada",
            nota="descrição vaga; sem marca/tipo",
        ),
        "aceleracao_0_100_s": A(
            9.4, "verificado_tier3", 3, [CNW_S10], "Aceleração 0-100 km/h  | 9,4 s", nota=CNW_NOTA
        ),
        "modos_conducao": NE([GM_SITE, AE_S10]),
        "modos_direcao": NE([GM_SITE, AE_S10]),
        "modos_escapamento": NE([GM_SITE, AE_S10]),
        "modos_amortecedor": NE([GM_SITE, AE_S10]),
        "farois": A(
            {"tipo": "LED", "extra": "assinatura em LED"},
            fontes=[GM_SITE],
            trecho="assinatura em LED",
            nota="tipo do farol principal não explícito",
        ),
        "rodas_pneus": A(
            {
                "aro_pol": 18,
                "material": None,
                "pneus": "265/60 R18",
                "descricao_oficial": "novas rodas com design exclusivo",
            },
            "verificado_tier3",
            3,
            [CNW_S10],
            "Dianteiros  | 265/60 R18",
            nota=CNW_NOTA + " Material da roda segue sem fonte.",
        ),
        "pacote_adas": A(
            {
                "nome_comercial": None,
                "itens": [
                    "assistente ativo de permanência em faixa",
                    "alerta de tráfego cruzado traseiro",
                    "frenagem automática de emergência",
                ],
            },
            fontes=[GM_SITE, AE_S10],
            trecho="Sistema auxiliar de permanência em faixa; alerta de tráfego cruzado traseiro; frenagem automática de emergência",
        ),
        "preco_sugerido_brl": A(
            348790,
            fontes=[GM_SITE, AE_S10],
            trecho="S10 High Country A partir de R$ 348.790",
            data="2026-09-01",
        ),
        "preco_fipe_brl": A(
            294378,
            tier=2,
            fontes=[GM_FIPE],
            trecho="R$ 294.378,00 (referência setembro de 2026)",
            referencia="2026-09",
        ),
    },
}

# A Ford diesel de topo. Toda entrada leva `origem=PIPELINE`: nenhum olho humano
# conferiu campo a campo, e o gabarito diz isso em vez de deixar parecer conferido.
ranger_limited = {
    "id": "ford_ranger_limited_2027",
    "marca": "Ford",
    "modelo": "Ranger",
    "versao": "Limited 3.0 V6 Diesel 4WD AT",
    "ano_modelo": 2027,
    "codigo_fipe": "003497-5",
    "papel": "veiculo_ford_diesel_topo",
    "origem": "coleta ao vivo de 2026-09-10 por scripts/coleta/coletar_faltantes.py; " + PIPELINE,
    "nota": "Escolha automática da versão pela maior 'a partir de' entre as 11 diesel da "
    "linha coletada. A página lista também 'Limited 3.0 V6 Diesel 4WD AT 2027 + "
    "Kit Opcional' a R$ 372.900 — mesma versão com pacote de acessórios, por isso "
    "fora. CONFIRMAR (DECISOES_NOITE.md D-161).",
    "linha_vigente": [{"nome_exato": "Limited 3.0 V6 Diesel 4WD AT", "ano_modelo": 2027}],
    "atributos": {
        "motor": A(
            {"deslocamento_l": 3.0, "cilindros": 6, "combustivel": "diesel", "aspiracao": "turbo"},
            fontes=[FORD_RANGER_LIMITED],
            trecho="Motor 3.0 V6 Turbo Diesel",
            origem=PIPELINE,
        ),
        "potencia_cv": A(
            250, fontes=[FORD_RANGER_LIMITED], trecho="Potência 250 cv @ 3.250rpm", origem=PIPELINE
        ),
        "potencia_rpm": A(
            3250, fontes=[FORD_RANGER_LIMITED], trecho="Potência 250 cv @ 3.250rpm", origem=PIPELINE
        ),
        "torque_nm": A(
            600, fontes=[FORD_RANGER_LIMITED], trecho="Torque 600 Nm @ 1.750 rpm", origem=PIPELINE
        ),
        "torque_rpm": A(
            1750, fontes=[FORD_RANGER_LIMITED], trecho="Torque 600 Nm @ 1.750 rpm", origem=PIPELINE
        ),
        "transmissao": A(
            {"tipo": "automatica", "numero_marchas": 10, "paddle_shifters": None},
            fontes=[FORD_RANGER_LIMITED],
            trecho="Transmissão Automática de 10 velocidades",
            origem=PIPELINE,
            nota="paddle_shifters não mencionado na página",
        ),
        "tracao": A(
            {"tipo": "4x4", "descricao": "4WD"},
            fontes=[FORD_RANGER_LIMITED],
            trecho="Tração 4WD",
            origem=PIPELINE,
        ),
        # A página descreve a suspensão pelo equipamento, não pelo componente: não há
        # marca nem tipo de amortecedor. `nao_encontrado` é o que a fonte sustenta.
        "amortecedores": NE(
            [FORD_RANGER_LIMITED, FORD_RANGER_PDF],
            "a página da versão não nomeia amortecedor; o PDF de ficha técnica "
            "tem a página de especificações em IMAGEM, sem texto extraível",
        )
        | {"origem": PIPELINE},
        "aceleracao_0_100_s": A(
            9.2,
            "verificado_tier3",
            3,
            [CNW_LIMITED],
            "Aceleração 0-100 km/h  | 9,2 s",
            nota=CNW_NOTA,
        )
        | {"origem": PIPELINE},
        "consumo_urbano_kml": A(
            8.3,
            tier=2,
            fontes=[PBE_TABELA],
            origem=PIPELINE,
            trecho="Picape FORD Nova Ranger 4x4 LTD 3.0 V6 - 24V",
            nota="tabela PBEV 2026, 18º ciclo (atualizada em 31/08/2026); "
            "a linha traz urbano 8,3 · rodoviário 10,1 · combinado 9,0",
        ),
        "consumo_rodoviario_kml": A(
            10.1,
            tier=2,
            fontes=[PBE_TABELA],
            origem=PIPELINE,
            trecho="Picape FORD Nova Ranger 4x4 LTD 3.0 V6 - 24V",
        ),
        "modos_conducao": A(
            ["normal", "eco", "reboque", "escorregadio", "lama", "areia"],
            fontes=[FORD_RANGER_LIMITED],
            origem=PIPELINE,
            trecho="6 modos de condução selecionáveis – Normal, Eco, Rebocar/Transp, Escorregadio, Lama/Terra, Areia",
            sinonimos={"rebocar/transp": "reboque", "lama/terra": "lama"},
        ),
        "modos_direcao": NE([FORD_RANGER_LIMITED], "a Limited não oferece modos de direção")
        | {"origem": PIPELINE},
        "modos_escapamento": NE([FORD_RANGER_LIMITED], "exclusivo da Raptor na linha Ranger")
        | {"origem": PIPELINE},
        "modos_amortecedor": NE([FORD_RANGER_LIMITED], "exclusivo da Raptor na linha Ranger")
        | {"origem": PIPELINE},
        "farois": A(
            {"tipo": "Full LED", "neblina": "LED"},
            fontes=[FORD_RANGER_LIMITED],
            trecho="Faróis FullLed",
            origem=PIPELINE,
            nota="a página lista 'Faróis FullLed' e 'Faróis de neblina em Led' como itens de equipamento",
        ),
        "rodas_pneus": A(
            {"aro_pol": 18, "material": "liga leve", "pneus": "255/65 R18", "tipo_pneu": "AT"},
            fontes=[FORD_RANGER_LIMITED],
            origem=PIPELINE,
            trecho='Pneus 255/65 R18 All Terrain; Rodas de liga leve 18"',
        ),
        "pacote_adas": A(
            {
                "nome_comercial": None,
                "itens": [
                    "assistente de permanência em faixa",
                    "assistente autônomo de frenagem",
                    "alerta de colisão",
                    "reconhecimento de sinais de trânsito",
                    "farol alto automático",
                    "câmera de ré",
                    "sensor de estacionamento dianteiro",
                    "sensor de estacionamento traseiro",
                ],
            },
            fontes=[FORD_RANGER_LIMITED],
            origem=PIPELINE,
            nota="a Ford não usa nome comercial na ficha BR; os itens estão na seção "
            "SEGURANÇA da página da versão",
        ),
        "preco_sugerido_brl": A(
            346900,
            fontes=[FORD_RANGER_LIMITED],
            origem=PIPELINE,
            trecho="Ranger Limited 3.0 V6 Diesel 4WD AT 2027 Preço a partir de R$ 346.900",
            data="2026-09-10",
        ),
        "preco_fipe_brl": A(
            343735,
            tier=2,
            fontes=[FIPE_API_RANGER_LIMITED],
            origem=PIPELINE,
            trecho='"Valor":"R$ 343.735,00"',
            referencia="2026-09",
            nota="a FIPE de setembro/2026 ainda não abriu o ano-modelo 2027: o "
            "valor é o do registro ZERO-QUILÔMETRO (AnoModelo 32000)",
        ),
    },
}

gabarito = {
    "versao": "1.1",
    "gerado_em": datetime.date.today().isoformat(),
    "descricao": "Verdade-terra para o eval do SpecRadar. 1 veículo Ford de referência + 1 Ford diesel de topo (v1.1, extraída pelo pipeline e pendente de confirmação) + 3 concorrentes + 1 caso negativo.",
    "status_possiveis": {
        "verificado": "valor em fonte oficial (tier 1) ou FIPE (tier 2), trecho verbatim confere",
        "verificado_tier3": "valor apenas em imprensa especializada; aceitável, com confiança menor",
        "divergente": "fontes oficiais divergem entre si ou do slide interno; todos os valores preservados",
        "nao_disponivel": "fonte oficial afirma que o item não existe/não é oferecido",
        "nao_encontrado": "nenhuma fonte consultada menciona; lista de fontes registrada",
        "pendente_coleta": "fora do gabarito por enquanto; o pipeline deve coletar (não é erro do pipeline não bater)",
        "versao_inexistente": "versão pedida não está na linha vigente; resposta esperada do resolvedor",
    },
    "regras_eval": {
        "numericos": "igualdade com tolerância: cv/Nm ±1, rpm ±50, segundos ±0,1, preço ±0,5% ou mesma referência",
        "listas": "comparação de conjuntos após normalização de sinônimos (esportivo→sport, lama/terra→lama, comfort→conforto, off-road→off_road)",
        "cilindros": "v1.1: só a CONTAGEM é medida. 'V6'→6, '4 em linha'→4. O arranjo era inferência (nenhuma fonte pública da Hilux o afirma) e as duas grafias não eram comparáveis entre si. O arranjo segue no valor exibido, fora da medida.",
        "adas_itens": "v1.1: conjuntos de FUNÇÃO, normalizados pelo vocabulário de sinônimos de pipeline/synonyms_seed.json (19 funções, 65 redações). 'Pre-crash System (PCS)' e 'frenagem automática de emergência' são a mesma função; nenhuma similaridade de texto casaria as duas. Item que nenhum lado canoniza cai em similaridade (limiar 72).",
        "objetos": "campo a campo; None no gabarito = não avaliar aquele subcampo",
        "status": "o pipeline deve reproduzir o status (nao_encontrado não pode virar valor inventado; divergente deve expor os valores)",
        "grounding": "todo valor não-nulo do pipeline precisa de trecho encontrado no texto salvo da fonte (string-match após normalização de espaços/aspas)",
        "slide_ford": "teste separado: o sistema deve apontar as 2 divergências (modos_direcao, modos_amortecedor) e os 2 rpm ausentes em fonte pública",
    },
    "veiculos": [raptor, ranger_limited, hilux_gr_negativo, hilux_srxp, amarok, s10],
}

with open("gabarito_v1.json", "w", encoding="utf-8") as f:
    json.dump(gabarito, f, ensure_ascii=False, indent=2)
print(
    "ok",
    sum(len(v["atributos"]) for v in gabarito["veiculos"]),
    "atributos em",
    len(gabarito["veiculos"]),
    "veículos",
)
