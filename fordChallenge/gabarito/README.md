# Gabarito v1 — como ler e como usar

`gabarito_v1.json` é a verdade-terra do eval. 5 veículos, 72 atributos, gerado por `build_gabarito.py`
a partir de 4 execuções do Manus (agente genérico seguindo o nosso protocolo) + extração manual do
PDF oficial da Toyota. **Ninguém do time inventou valor**: cada atributo tem status, URL, trecho e tier.

| Veículo | Papel | Fonte principal |
|---|---|---|
| Ford Ranger Raptor 2026 | referência Ford; teste "slide × fonte pública" | ford.com.br + PDF oficial |
| Toyota Hilux GR-Sport | caso negativo (versão fora da linha 2026) | toyota.com.br + PDF MY26 |
| Toyota Hilux SRX Plus AT 2026 | concorrente | PDF oficial MY26 p.6–7 (`raw/toyota_hilux_my26_*`) |
| VW Amarok V6 Extreme 2026 | concorrente | vw.com.br |
| Chevrolet S10 High Country 2027 | concorrente | chevrolet.com.br |

## O que o eval mede (ver `docs/09_EVAL_E_GABARITO.md`)
- **Exatidão por campo** (valor bate dentro da tolerância) — só em `verificado`/`verificado_tier3`.
- **Fidelidade de status** — `nao_encontrado` do gabarito não pode virar valor no pipeline; `divergente` deve expor os dois valores.
- **Grounding** — 100% dos valores não-nulos com trecho localizado no texto salvo.
- **Resolvedor** — GR-Sport deve retornar `versao_inexistente` com sugestão `SRX Plus AT`.
- **Slide Ford** — o sistema deve apontar as 2 divergências (modos_direcao, modos_amortecedor) e os 2 rpm ausentes.

`pendente_coleta` (2 campos da Hilux SRX Plus: preço e FIPE) não conta como erro; quando o pipeline coletar,
um humano confere e promove para `verificado` via `build_gabarito.py`.

## Lições que viraram requisito (não perca isso no pitch)
1. Slide interno da Ford ≠ ficha pública 2026 (Baja→Off-Road; 3→4 modos de direção). Planilha estática envelhece.
2. Sinônimos matam extração ingênua: volante≈direção, aletas≈paddle shifters, Esportivo≈Sport.
3. Cobertura varia por marca: Toyota publica rpm em PDF; Ford, VW e GM não publicam rpm.
4. Versões saem de linha (GR-Sport). O produto precisa de "passo 0": resolver a versão na linha vigente.
5. Anti-bot é real (sala de imprensa GM = CAPTCHA). Fallback de fontes e modo replay são obrigatórios.
