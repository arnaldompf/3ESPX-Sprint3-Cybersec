# Fontes embutidas

As quatro famílias abaixo são distribuídas sob a **SIL Open Font License, Version 1.1**,
que permite uso, modificação e redistribuição embutida em produto, inclusive comercial,
mantida a atribuição e sem venda das fontes isoladamente.

| Família | Autoria | Origem |
| --- | --- | --- |
| Schibsted Grotesk | Schibsted Media Group / Or Type | Google Fonts |
| Hanken Grotesk | Alfredo Marco Pradil | Google Fonts |
| Public Sans | USWDS / Dan O. Williams (baseado em Libre Franklin) | Google Fonts |
| JetBrains Mono | JetBrains s.r.o. | Google Fonts |

Os arquivos `.woff2` desta pasta são os cortes de **eixo variável** (`wght`), subsets
`latin` e `latin-ext`, baixados por `scripts/design/baixar_fontes.py`. O texto integral da
licença acompanha cada família no repositório de origem
(`github.com/google/fonts`, pasta `ofl/<familia>/OFL.txt`).

Nenhuma requisição sai para `fonts.googleapis.com` em tempo de execução: a CSP do web app
é `default-src 'none'` com `font-src 'self'`, e a apresentação acontece numa sala que pode
não ter internet.
