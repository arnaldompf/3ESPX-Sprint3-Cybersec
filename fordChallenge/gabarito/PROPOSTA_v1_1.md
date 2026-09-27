# Proposta de gabarito v1.1 — pendências para promoção humana

`docs/09` é explícito: **só humano** promove `pendente_coleta` → `verificado`, editando
`build_gabarito.py` com URL e trecho. Este arquivo é o que a noite conseguiu apurar,
escrito para ser conferido e aplicado por uma pessoa — **nada aqui foi gravado em
`gabarito_v1.json`**, que segue intocado.

Escopo pedido por `docs/12` §6.10 para o v1.1:

1. Ford Ranger **diesel topo de linha** vigente (nome exato via resolvedor no ford.com.br)
2. Consumo PBE/Inmetro dos 5 veículos (ou declarado oficial)
3. FIPE de outubro quando publicada (gera o Change Radar real)
4. Promover os 2 campos `pendente_coleta` da Hilux SRX Plus (preço e FIPE)

---

## 1. Ford Ranger diesel topo de linha — `pendente_coleta`

**Status: não foi possível coletar. Fonte bloqueada, sem tentativa de contornar.**

A instrução da noite era: se a WP-07 conseguisse listar a linha Ranger no ford.com.br,
escolher a diesel de maior preço, registrar "escolha automática, confirmar" e seguir;
se não conseguisse por rede ou bloqueio, criar a entrada com `pendente_coleta`.

### O que foi tentado, na ordem
1. **robots.txt de `ford.com.br`** — consultado primeiro. Permite `/picapes/ranger/`
   para o nosso user-agent (`SpecRadar/0.1`). Nenhuma rota foi acessada sem essa checagem.
2. **`GET https://www.ford.com.br/picapes/ranger/`** com user-agent identificado,
   1 req/s, timeout 30 s → **HTTP 403** (394 bytes, sem CAPTCHA no corpo).
3. **Diagnóstico das quatro marcas**, uma requisição cada, 1 s de intervalo:

   | Marca | URL | Resultado |
   |---|---|---|
   | Ford | `ford.com.br/picapes/ranger/` | **403** |
   | Ford | `ford.com.br/picapes/ranger-raptor/raptor-4wd-at/` | **403** |
   | Toyota | `toyota.com.br/modelos/hilux-cabine-dupla` | **403** |
   | Volkswagen | `vw.com.br/pt/carros/amarok.html` | 200 (1,2 MB) |
   | Chevrolet | `chevrolet.com.br/picapes/s10` | **403** |

   Três das quatro montadoras recusam cliente HTTP simples na borda (WAF/CDN), com
   robots.txt permitindo a rota. Não é CAPTCHA e não é proibição por robots — é filtro de
   cliente.

### O que **não** foi feito, de propósito
Nenhuma troca de user-agent, nenhum header de navegador falso, nenhuma retentativa em
cascata, nenhuma rotação de IP. `docs/12` §3.12 e `docs/02` ADR-7 são claros: bloqueio
vira status e fallback, não truque. O status registrado é `fonte_bloqueada`.

### Caminho para destravar (para a pessoa que for conferir)
`docs/05` já especifica o fetcher correto: **Crawl4AI (Playwright headless)** — um
navegador real, que é a ferramenta prevista do projeto, não um contorno. É escopo da
**WP-08**. Depois de `uv sync --extra collect` e `uv run crawl4ai-setup`, a coleta da
página do modelo Ranger deve funcionar. Alternativa manual: salvar a página do navegador
e rodar `python scripts/build_fixtures.py` com o arquivo em `gabarito/raw/`.

### Entrada proposta para `build_gabarito.py`

```python
# Acrescentar em veiculos[], depois da conferência humana da coleta:
{
    "id": "ford_ranger_diesel_topo_2026",
    "marca": "Ford",
    "modelo": "Ranger",
    "versao": "<NOME EXATO — preencher com o que o resolvedor listar>",
    "ano_modelo": 2026,
    "codigo_fipe": None,  # pendente
    "papel": "veiculo_ford_equivalente_aos_concorrentes_diesel",
    "origem": "pendente_coleta — ford.com.br/picapes/ranger respondeu 403 em 2026-09-08",
    "linha_vigente": [],  # preencher com a linha completa da Ranger
    "atributos": {
        # todos os atributos entram como pendente_coleta até a coleta acontecer
        "motor": {
            "esperado": None,
            "status": "pendente_coleta",
            "tier": None,
            "fontes": ["https://www.ford.com.br/picapes/ranger/"],
            "nota": "fonte_bloqueada em 2026-09-08 (HTTP 403 a cliente HTTP simples)",
        },
        # ... idem para os outros 17 atributos
    },
}
```

### Regra de escolha, para quando a linha estiver disponível
"Diesel de maior preço" — o campo `preco_a_partir_brl` de cada `VersionInfo` da linha
vigente, filtrando por `combustivel == "diesel"`. O resolvedor já entrega os dois dados;
falta a fonte. Quando a coleta acontecer, a escolha fica registrada como
**"escolha automática, confirmar"** em `specs/STATUS.md`, como a instrução pede.

### Por que isso importa para a demo de 15/09
`docs/13` §7, cena 8, é "Copiloto: fazendeiro, **Ranger diesel × Hilux SRX Plus**". Sem a
Ranger diesel no gabarito, essa cena precisa de um dos dois caminhos:
- rodar a WP-08 com Playwright e coletar a linha (caminho preferido); ou
- apresentar a cena com a **Raptor** (gasolina) contra a Hilux, dizendo em tela que a
  comparação de combustível diferente está rotulada — o custo de uso já trata isso
  (`docs/12` §6.3 usa o combustível correto de cada veículo).

---

## 2. Consumo PBE/Inmetro dos 5 veículos — `pendente_coleta`

Conector PBE/Inmetro é **novo** (`docs/12` §6.3: "tabela anual do programa, parse com
Docling") e não foi implementado nesta noite. O que já existe de consumo em fonte salva:

| Veículo | Consumo encontrado | Onde | Observação |
|---|---|---|---|
| Toyota Hilux SRX Plus | 9,7 km/l cidade · 10,6 km/l estrada | `toyota_hilux_site.md` (nota de rodapé, PBEV/Inmetro 2024) | **declarado oficial**, versão "SRX Plus (Wide Tread) 2.8 Automático" |
| Toyota Hilux SRV/SRX | 10,1 km/l cidade · 11,3 km/l estrada | `toyota_hilux_site.md` | outra versão — **não** vale para a SRX Plus |
| Ford Raptor | — | — | não consta nas fontes salvas |
| VW Amarok V6 Extreme | — | — | não consta nas fontes salvas |
| Chevrolet S10 High Country | — | — | não consta nas fontes salvas |

**Atenção ao aplicar:** os dois números da Toyota são de versões diferentes. Atribuir o de
uma versão à outra seria exatamente a inferência proibida ("nada inferido de outra versão").

---

## 3. FIPE de outubro — `pendente_coleta`

Depende do conector FIPE (**WP-13**) e da publicação da tabela. A referência atual no
gabarito v1 é `2026-09`. Quando a de outubro sair, `specradar refresh` gera o Change Radar
real — é o alerta `preco_fipe` de `docs/12` §6.1.

---

## 4. Preço e FIPE da Hilux SRX Plus — seguem `pendente_coleta`

Os dois campos continuam pendentes no v1. As URLs de FIPE já estão registradas na fixture
(`tests/fixtures/snapshots/toyota_hilux_srx_plus_at_2026/fontes.json`, fonte
`fipe_srx_plus` com `status: pendente_coleta`). Falta a coleta.

---

## 5. Achado da extração: `rodas_pneus.tipo_pneu = "AT"` da Raptor não tem apoio público

**Isto não é uma pendência de coleta, é uma incoerência de evidência.** Vale conferir.

O gabarito registra, para a Ford Ranger Raptor:

- `rodas_pneus.esperado.tipo_pneu = "AT"`, com `status: verificado`, `tier: 1`
- `trecho: "Pneus 285/70 R17 General Grabber; Rodas de liga leve 17\""`

O trecho citado **não contém "AT"**. Rodando o grounding contra as três fontes salvas da
Raptor (página da versão, ficha técnica oficial e registro de evidências), nenhuma
menciona o tipo do pneu. Onde "AT" aparece é no `slide_ford` do próprio atributo
(`17" com 285/70 R17 AT`) — ou seja, na **referência interna**, não na fonte pública.

Poder-se-ia argumentar que "General Grabber" é uma linha all-terrain e portanto AT. Isso
é exatamente a inferência que o projeto proíbe: derivar a característica a partir do nome
comercial do produto, sem a fonte dizer.

**Consequência hoje:** o pipeline devolve `nao_encontrado` para `exterior.pneus_tipo` da
Raptor, e o eval conta isso como um erro de `field_accuracy` — quando o comportamento é o
correto. É 1 dos 84 campos medidos.

**Três saídas, em ordem de preferência:**
1. Achar fonte pública que diga o tipo do pneu (a ficha técnica completa em PDF talvez
   traga) e atualizar o `trecho` do atributo.
2. Mudar o status desse subcampo para `nao_encontrado` no `build_gabarito.py`, mantendo
   o valor do slide em `slide_ford` — e assim ele passa a ser **mais uma divergência
   slide × fonte pública**, que é justamente a cena de Fogo Amigo (`docs/13` §5.1).
3. Deixar como está e aceitar 1/84 de perda no eval, com esta nota como explicação.

A saída 2 é a mais interessante para a demo: transforma um erro de métrica em um exemplo
do produto funcionando.

---

## Checklist para a pessoa que for aplicar

- [ ] Rodar a WP-08 (Crawl4AI/Playwright) e coletar `ford.com.br/picapes/ranger`
- [ ] Conferir os nomes exatos das versões diesel e escolher a de maior preço
- [ ] Editar `gabarito/build_gabarito.py` com URL + trecho verbatim de cada campo
- [ ] Subir a versão do gabarito para `1.1` e regerar `gabarito_v1.json`
- [ ] Rodar `python scripts/build_fixtures.py` e `python scripts/task.py eval`
- [ ] Conferir que `field_accuracy` não caiu (a entrada nova entra com campos pendentes)
- [ ] Decidir o que fazer com `rodas_pneus.tipo_pneu` da Raptor (seção 5 acima)
