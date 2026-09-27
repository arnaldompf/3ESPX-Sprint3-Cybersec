# Créditos das imagens

As fotos dos cinco veículos são **divulgação oficial das montadoras, fornecidas pelo
time**. Elas aparecem em dois lugares e em tamanho pequeno: no topo da Ficha técnica e nas
duas colunas do Showroom. Nenhuma é usada como fundo de tela, e nenhuma carrega informação
que o produto afirme — o que o SpecRadar afirma tem evidência, e foto não é evidência.

| Arquivo | Veículo |
|---|---|
| `veiculos/ranger-raptor.webp` | Ford Ranger Raptor 3.0 V6 Bi-turbo 4WD AT |
| `veiculos/ranger-limited.webp` | Ford Ranger Limited 3.0 V6 Diesel 4WD AT |
| `veiculos/hilux-srx-plus.webp` | Toyota Hilux SRX Plus AT |
| `veiculos/amarok-v6-extreme.webp` | Volkswagen Amarok V6 Extreme |
| `veiculos/s10-high-country.webp` | Chevrolet S10 High Country |

`marca/ford.svg` é o logo da Ford, convertido do EPS de `imagens/logoFordVetorizada.zip`
(o arquivo que o time entregou). Ele aparece **uma vez**, no rodapé da barra lateral, ao
lado de "Ford Challenge FIAP 2026".

## O arquivo da S10 chegou diferente dos outros quatro

As quatro primeiras fotos vieram recortadas, com transparência de verdade. A
`S10 High Country.png` veio em RGB, **com o quadriculado de "isto é transparente"
desenhado nos pixels**. O preparo apaga o quadriculado do fundo (por alastramento a partir
da borda, o que protege o para-choque prateado) e achata os dois cinzas do que ficou preso
dentro do vidro.

**O que sobra, e está dito porque sobra:** no para-brisa, onde o quadriculado aparece
através do vidro escurecido, ele cai abaixo do limiar de claro e não é tratado. Aos 220 e
330 px em que a foto aparece na tela, o resto se confunde com reflexo. Tratá-lo exigiria
baixar o limiar a ponto de apagar reflexo de verdade, e repintar foto de montadora não é
coisa que este projeto faça. Quem tiver o arquivo original sem o quadriculado, troque em
`imagens/` e rode o preparo de novo.

## Duas ressalvas, e as duas são de quem apresenta

1. **`design-kit/020_BRIEF_PRODUTO.md` §identidade diz "não usar nem redesenhar logos da
   Ford ou da FIAP dentro do produto".** O logo está aqui porque a instrução da noite de
   12/09/2026 pediu, explicitamente, o logo no rodapé da barra lateral. A instrução é
   posterior e do dono do produto; o registro fica em `DECISOES_NOITE.md` D-213.
2. **O arquivo do zip vem do Vecteezy**, não do banco de marca da Ford: o pacote inclui
   `Vecteezy-License-Information.pdf`. Para uma apresentação interna isso não é problema.
   Para qualquer material que circule fora, a arte oficial tem de vir da Ford.

Gerado por `scripts/design/preparar_imagens.py`. Os originais ficam em `imagens/`.
