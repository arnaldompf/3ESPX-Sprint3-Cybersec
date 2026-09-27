"""Documentos ligados pela montadora entram na fila, sem virar prova da versão."""

from pipeline.research.discovery import document_links, url_key


def test_chave_deduplica_fragmento_e_rastreamento_sem_apagar_codigo_da_ficha():
    assert url_key("https://www.ford.com.br/ranger/?utm_source=ad#pdf") == url_key(
        "https://ford.com.br/ranger"
    )
    assert url_key("https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=10") != url_key(
        "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=11"
    )


def test_descobre_pdf_relativo_no_html_e_nao_navegacao_ou_links_inseguros():
    html = """<a href="/content/dam/ranger-ficha-tecnica.pdf">Ficha técnica</a>
    <a href="/contato">Contato</a><a href="javascript:alert(1)">Catálogo</a>
    <a href="https://user:pass@www.ford.com.br/catalogo.pdf">PDF</a>"""
    assert document_links(html, "https://www.ford.com.br/picapes/ranger/") == [
        ("https://www.ford.com.br/content/dam/ranger-ficha-tecnica.pdf", "Ficha técnica")
    ]


def test_markdown_do_extrator_preserva_link_e_nao_confunde_ano_do_path_com_modelo():
    text = (
        "[Baixe a ficha técnica](/assets/2025/ranger.pdf)\n[Ficha](/assets/2025/ranger.pdf#page=4)"
    )
    assert document_links(text, "https://www.ford.com.br/ranger/") == [
        ("https://www.ford.com.br/assets/2025/ranger.pdf", "Baixe a ficha técnica")
    ]


def test_limite_de_links_e_apenas_documentos_nao_imagens():
    text = "\n".join(f"[Ficha {n}](https://www.ford.com.br/{n}.pdf)" for n in range(20))
    text += "\n![Ficha](https://www.ford.com.br/ficha.jpg)"
    assert len(document_links(text, "https://www.ford.com.br", limit=4)) == 4


def test_link_malformado_nao_aborta_descoberta_dos_demais_documentos():
    html = '<a href="https://[invalido/catalogo.pdf">Ficha ruim</a>'
    html += '<a href="/ranger.pdf">Ficha Ranger</a>'
    assert document_links(html, "https://www.ford.com.br") == [
        ("https://www.ford.com.br/ranger.pdf", "Ficha Ranger")
    ]


def test_chave_de_url_invalida_nao_aborta_classificacao_da_resposta_de_busca():
    from pipeline.research.classify import classificar

    malformed = "https://[invalido/catalogo.pdf"
    assert url_key(malformed)
    assert not classificar(malformed, marca="Ford", modelo="Ranger").aceita


def test_link_com_senha_e_usuario_vazio_tambem_e_rejeitado():
    text = "[Ficha](https://:segredo@www.ford.com.br/ranger.pdf)"
    assert document_links(text, "https://www.ford.com.br") == []


def test_limite_nulo_nao_adiciona_documentos():
    text = "[Ficha](https://www.ford.com.br/ranger.pdf)"
    assert document_links(text, "https://www.ford.com.br", limit=0) == []


def test_parametro_de_caminho_pode_identificar_configuracoes_diferentes():
    assert url_key("https://www.ford.com.br/ranger;versao=limited") != url_key(
        "https://www.ford.com.br/ranger;versao=xlt"
    )


def test_pdf_oficial_em_pasta_de_assets_antiga_e_lido_antes_de_julgar_ano_modelo():
    from pipeline.research.classify import classificar

    decision = classificar(
        "https://www.ford.com.br/content/dam/assets/2025/ranger-ficha.pdf",
        marca="Ford",
        modelo="Ranger",
        ano=2027,
    )
    assert decision.aceita
    # A exceção é de localização, não aceita imprensa velha nem muda a identidade.
    old = classificar(
        "https://quatrorodas.abril.com.br/2023/ranger/", marca="Ford", modelo="Ranger", ano=2027
    )
    assert not old.aceita

    obsolete_asset = classificar(
        "https://www.ford.com.br/content/dam/assets/2021/ranger-2021.pdf",
        marca="Ford",
        modelo="Ranger",
        ano=2027,
    )
    assert not obsolete_asset.aceita


def test_pesquisa_segue_documento_linkado_e_nao_recoleta_alias(monkeypatch):
    from pipeline.research import acervo, gaps, run, search
    from pipeline.schema import empty_spec

    base = "https://www.ford.com.br/ranger/"
    pdf = "https://www.ford.com.br/content/dam/ranger-ficha.pdf"
    monkeypatch.setattr(acervo, "known_sources", lambda alvo: [])
    monkeypatch.setattr(
        search,
        "buscar",
        lambda q, **kw: search.Resposta(
            q,
            "teste",
            [
                search.Achado(base, "Ranger", "", 1, "teste", q),
                search.Achado(base + "?utm_source=outro#ficha", "Ranger", "", 2, "teste", q),
            ],
        ),
    )
    seen = []

    def collect(url, **kw):
        seen.append(url)
        return run.Coleta(
            texto="Fonte original sem especificações. " * 40,
            links=[(pdf, "Ficha técnica Ranger")] if url == base else [],
        )

    monkeypatch.setattr(run, "_coletar", collect)
    monkeypatch.setattr(run.Leitor, "ler", lambda *a, **kw: (empty_spec(), []))
    result = run.pesquisar(
        "Ford",
        "Ranger",
        "Limited",
        ano=2027,
        campos=["potencia_cv"],
        orcamento=gaps.Orcamento(rodadas=1, paginas=3, segundos=15, chamadas_llm=0),
    )
    assert seen == [base, pdf]
    assert result.cobertura.com_valor == 0
    assert result.fontes[1].consulta == "link em " + base
