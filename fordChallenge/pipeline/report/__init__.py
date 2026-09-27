"""O relatório para o cliente (WP-28): HTML determinístico, PDF pelo motor que houver.

`html.py` monta o documento inteiro — comparação, custo de uso, argumentos, onde o
concorrente vence, e a lista de fontes com URL e data. É onde vivem os critérios de aceite,
e é testável sem nenhuma dependência nativa. `CSS` é o estilo do documento; `CSS_XHTML2PDF`
é o mesmo estilo em subconjunto, para o motor de reserva — **só o `<style>` muda**.

`render.py` percorre uma ordem declarada: WeasyPrint (o previsto pela spec, mas depende de
GTK/Pango/Cairo nativos), `xhtml2pdf` (reserva em Python puro) e, se nenhum estiver
disponível, o `.html` **com o motivo por escrito** — o mesmo padrão do Docling (D-34) e do
Playwright. Quem gerou fica registrado no resultado e no payload do job.
"""
