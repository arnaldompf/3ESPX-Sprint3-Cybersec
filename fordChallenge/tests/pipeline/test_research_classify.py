"""O classificador de fontes: em quem acreditar quando duas discordam.

O tier é a peça que faz o Pesquisador ser inteligência competitiva e não um agregador de
links. Os testes aqui defendem duas coisas que se contradizem se mal implementadas: ser
**aberto** o bastante para uma montadora fora do catálogo (RAM, Mitsubishi, Nissan) ganhar
T1 na primeira pesquisa, e **fechado** o bastante para que `fakeford.com.br` não herde o
tier da Ford.
"""

from __future__ import annotations

import pytest

from pipeline.research import classify


class TestOficial:
    @pytest.mark.parametrize(
        ("url", "marca"),
        [
            ("https://www.ford.com.br/picapes/ranger/", "Ford"),
            ("https://www.toyota.com.br/modelos/hilux", "Toyota"),
            ("https://media.toyota.com.br/releases/nova-hilux", "Toyota"),
            ("https://www.vw.com.br/pt/carros/amarok.html", "Volkswagen"),
            ("https://www.chevrolet.com.br/picapes/s10", "Chevrolet"),
        ],
    )
    def test_dominio_cadastrado_e_tier_1(self, url: str, marca: str):
        achado = classify.classificar(url, marca=marca)
        assert achado.tier == 1
        assert achado.aceita
        assert achado.motivo

    @pytest.mark.parametrize(
        ("url", "marca"),
        [
            ("https://www.ram.com.br/rampage.html", "RAM"),
            ("https://www.mitsubishimotors.com.br/triton", "Mitsubishi"),
            ("https://www.nissan.com.br/veiculos/frontier.html", "Nissan"),
        ],
    )
    def test_marca_fora_do_mapa_ainda_ganha_tier_1_pelo_nome(self, url: str, marca: str):
        """Sem isto, pesquisar uma picape de marca nova começaria sem fonte oficial — e o
        Pesquisador existe justamente para os veículos que ainda não estão no catálogo."""
        assert classify.classificar(url, marca=marca).tier == 1

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.fakeford.com.br/ranger",
            "https://ford.blogspot.com/ranger",
            "https://ford-noticias.com.br/ranger",
        ],
    )
    def test_dominio_parecido_nao_herda_o_tier_da_marca(self, url: str):
        """O caso perigoso: uma fonte falsa entrando com a autoridade da verdadeira.

        `fakeford.com.br` tem "ford" no host; `ford.blogspot.com` também. Nenhum dos dois é
        a Ford, e dar T1 a eles faria a divergência com o site real ser resolvida a favor
        do impostor.
        """
        achado = classify.classificar(url, marca="Ford")
        assert achado.tier != 1, achado

    def test_pdf_oficial_e_reconhecido_como_pdf(self):
        achado = classify.classificar(
            "https://www.ford.com.br/content/dam/ranger/fbr-ranger-ficha-tecnica.pdf",
            marca="Ford",
        )
        assert achado.tier == 1
        assert achado.e_pdf
        assert "PDF" in achado.motivo


class TestRegistroEImprensa:
    @pytest.mark.parametrize(
        "url",
        [
            "https://veiculos.fipe.org.br/",
            "https://www.gov.br/inmetro/pt-br/assuntos/pbe/tabelas",
        ],
    )
    def test_registro_publico_e_tier_2(self, url: str):
        assert classify.classificar(url, marca="Ford").tier == 2

    @pytest.mark.parametrize(
        "url",
        [
            "https://quatrorodas.abril.com.br/testes/ford-ranger-raptor",
            "https://autoesporte.globo.com/teste-ranger-raptor.ghtml",
            # `motor1.uol.com.br` saiu desta lista em 13/09/2026: a sondagem tentou as duas
            # provas, e as duas voltaram 403/CAPTCHA **inclusive com navegador**. Ele agora
            # está em `reprovados`, com o motivo — ver `TestOTipoDaFonte`.
            "https://www.noticiasautomotivas.com.br/ford-ranger-raptor-ficha/",
        ],
    )
    def test_imprensa_especializada_e_tier_3(self, url: str):
        achado = classify.classificar(url, marca="Ford")
        assert achado.tier == 3
        assert achado.aceita


class TestDescarte:
    @pytest.mark.parametrize(
        "url",
        [
            "https://www.youtube.com/watch?v=abc",
            "https://www.reddit.com/r/carros/comments/x",
            "https://produto.mercadolivre.com.br/MLB-123-ranger",
            "https://pt.wikipedia.org/wiki/Ford_Ranger",
        ],
    )
    def test_fonte_descartada_diz_o_motivo(self, url: str):
        """Descarte silencioso é indistinguível de fonte que ninguém viu. A tela mostra as
        URLs consideradas **com o motivo**, e é daí que ele vem."""
        achado = classify.classificar(url, marca="Ford")
        assert achado.aceita is False
        assert len(achado.motivo) > 5

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.nissan.com.br/content/dam/Nissan/br/manuais/Versa/2017/Manual.pdf",
            "https://media.mitsubishimotors.com.br/uploads/originals/3150_F.pdf",
            "https://www.ford.com.br/pos-venda/manual-do-proprietario-ranger.pdf",
        ],
    )
    def test_manual_do_proprietario_e_barrado_mesmo_em_dominio_oficial(self, url: str):
        """**O achado que mais mudou a qualidade da pesquisa**, medido ao vivo em
        13/09/2026: as 18 páginas de uma rodada somaram **141,7 MB** — média de 7,9 MB cada,
        a maior com 19,4 MB. Não eram fichas técnicas: eram manuais de proprietário de 400
        páginas, todos de domínio oficial.

        A regra de tier os aceitava, e com razão — o domínio **é** oficial. O que faltava
        era perguntar **o que** aquele documento é. Um manual do Versa não tem a ficha da
        Frontier; ele só gasta uma das doze páginas e o tempo de leitura.
        """
        achado = classify.classificar(url, marca="Nissan")
        assert achado.aceita is False, achado
        assert "manual" in achado.motivo.lower()

    def test_pdf_de_ficha_tecnica_continua_passando(self):
        """Contra-teste: a regra é sobre manual, não sobre PDF."""
        achado = classify.classificar(
            "https://www.ford.com.br/content/dam/ranger/fbr-ranger-ficha-tecnica.pdf",
            marca="Ford",
        )
        assert achado.aceita is True
        assert achado.tier == 1

    def test_dominio_desconhecido_nao_entra_na_coleta(self):
        achado = classify.classificar("https://blogdocarro.net/ranger", marca="Ford")
        assert achado.aceita is False
        assert achado.tier == classify.TIER_DESCONHECIDO
        assert "não reconhecido" in achado.motivo

    def test_endereco_invalido_nao_derruba_o_run(self):
        assert classify.classificar("isto não é uma url").aceita is False


class TestRelevancia:
    """O domínio certo com o documento errado.

    **O achado que custou uma rodada ao vivo.** Pesquisando a Nissan Frontier, o
    classificador escolheu `nissan.com.br/veiculos/modelos.html`, a página do Kicks Play e
    — o caso que encerra a discussão — o **regulamento de um festival de cultura japonesa**
    hospedado no domínio da Nissan. Todas T1, todas oficiais, nenhuma sobre a Frontier.

    Os quatro motores de busca estudados resolvem isso com rerank por embedding. Aqui basta
    uma pergunta determinística, e ela é verificável sem chamar ninguém.
    """

    def test_pagina_do_modelo_pedido_passa(self):
        achado = classify.classificar(
            "https://www.nissan.com.br/veiculos/modelos/frontier.html",
            marca="Nissan",
            titulo="Nissan Frontier",
            modelo="Frontier",
        )
        assert achado.aceita is True
        assert achado.tier == 1

    @pytest.mark.parametrize(
        ("url", "titulo"),
        [
            ("https://www.nissan.com.br/veiculos/modelos.html", "Modelos Nissan"),
            ("https://www.nissan.com.br/veiculos/modelos/kicks-play.html", "Kicks Play"),
            ("https://www.nissan.com.br/dam/REGULAMENTO_Festival.pdf", "Festival"),
        ],
    )
    def test_dominio_certo_e_veiculo_errado_nao_passa(self, url: str, titulo: str):
        achado = classify.classificar(url, marca="Nissan", titulo=titulo, modelo="Frontier")
        assert achado.aceita is False, achado
        assert "Frontier" in achado.motivo

    def test_o_modelo_e_achado_no_titulo_quando_a_URL_nao_diz(self):
        """Muita ficha em PDF tem nome de arquivo opaco; o título do resultado salva."""
        achado = classify.classificar(
            "https://www.nissan.com.br/dam/3150_F.pdf",
            marca="Nissan",
            titulo="Frontier Pro-4X — ficha técnica",
            modelo="Frontier",
        )
        assert achado.aceita is True

    def test_sem_modelo_pedido_a_regra_nao_bloqueia(self):
        """A regra existe para filtrar, não para barrar quem não a usa."""
        achado = classify.classificar(
            "https://www.nissan.com.br/veiculos/modelos.html", marca="Nissan"
        )
        assert achado.aceita is True

    def test_nome_composto_casa_sem_pontuacao(self):
        assert classify.fala_do_modelo("https://x/ram-rampage-laramie", "", "Rampage")
        assert classify.fala_do_modelo("https://x/s10.html", "", "S10")


class TestOrdem:
    def test_oficial_vem_antes_de_imprensa_e_pdf_antes_do_site(self):
        """Doze páginas é o orçamento da demo: a ordem decide o que cabe nele.

        O PDF de catálogo é a melhor fonte que existe para ficha técnica — ele **é** a
        ficha, em tabela, sem JavaScript e sem escudo antibot.
        """
        urls = [
            "https://quatrorodas.abril.com.br/ranger",
            "https://www.ford.com.br/picapes/ranger/",
            "https://www.ford.com.br/dam/ranger-ficha.pdf",
            "https://veiculos.fipe.org.br/",
            "https://www.youtube.com/watch?v=x",
        ]
        ordenadas = classify.ordenar([classify.classificar(u, marca="Ford") for u in urls])
        assert [c.tier for c in ordenadas] == [1, 1, 2, 3, classify.TIER_DESCONHECIDO]
        assert ordenadas[0].e_pdf, "o PDF do mesmo tier vem primeiro"
        assert ordenadas[-1].aceita is False, "o descartado vai para o fim"


class TestGovernoNaoEInmetro:
    """Medido em 13/09/2026: um edital da Polícia Civil do DF sobre viaturas L200 entrou como
    PBE/Inmetro (tier 2) e gravou o ano-modelo errado na ficha da Triton 2026."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.pcdf.df.gov.br/transparencia/licitacoes/pregao/9-2020",
            "https://www.gov.br/pt-br/noticias/transito/mitsubishi-triton-frota",
        ],
    )
    def test_pagina_gov_fora_do_inmetro_nao_e_registro(self, url: str):
        c = classify.classificar(
            url, marca="Mitsubishi", titulo="Mitsubishi Triton", modelo="Triton"
        )
        assert not c.aceita
        assert "Inmetro" in c.motivo and "licitação" in c.motivo

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.gov.br/inmetro/pt-br/assuntos/avaliacao-da-conformidade/pbe-veicular-triton",
            "https://pbeveicular.inmetro.gov.br/tabelas/2026/triton",
        ],
    )
    def test_inmetro_e_pbe_continuam_tier_2(self, url: str):
        c = classify.classificar(
            url, marca="Mitsubishi", titulo="PBE Veicular Triton", modelo="Triton"
        )
        assert c.aceita and c.tier == 2


class TestOTipoDaFonte:
    """O tier diz em quem acreditar; o **tipo** diz o que a página é.

    `icarros.com.br/catalogo/…` e `kbb.com.br` são os dois tier 3, e a sondagem de
    13/09/2026 mediu 16 campos por regra no primeiro e 5 no segundo. Sem o tipo, a coleta
    gasta a mesma página nos dois — e o orçamento é de doze.
    """

    def test_site_de_ficha_e_site_de_materia_se_distinguem(self):
        ficha = classify.classificar(
            "https://www.icarros.com.br/catalogo/chevrolet/s10/2026",
            marca="Chevrolet",
            modelo="S10",
        )
        materia = classify.classificar(
            "https://www.kbb.com.br/carro/chevrolet-s10-2026/", marca="Chevrolet", modelo="S10"
        )
        assert (ficha.tier, ficha.tipo) == (3, "ficha")
        assert (materia.tier, materia.tipo) == (3, "imprensa")
        assert "por regra" in ficha.motivo, "o motivo mostra o que a sondagem mediu"

    def test_ficha_vem_antes_de_materia_no_mesmo_tier(self):
        materia = classify.classificar("https://www.kbb.com.br/a", marca="Chevrolet")
        ficha = classify.classificar("https://www.icarros.com.br/b", marca="Chevrolet")
        primeira = classify.ordenar([materia, ficha])[0]
        assert primeira.dominio == "icarros.com.br"

    def test_oficial_declara_o_tipo(self):
        c = classify.classificar(
            "https://www.ford.com.br/picapes/ranger/", marca="Ford", modelo="Ranger"
        )
        assert c.tier == 1 and c.tipo == "oficial"

    def test_quem_exige_navegador_chega_marcado(self):
        c = classify.classificar(
            "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=1", marca="Chevrolet"
        )
        assert c.navegador is True
        assert (
            classify.classificar("https://www.icarros.com.br/x", marca="Chevrolet").navegador
            is False
        )

    def test_dominio_ja_medido_e_reprovado_diz_isso(self):
        """ "Ninguém olhou" e "olhamos, e não serve" pedem ações diferentes de quem lê."""
        c = classify.classificar(
            "https://motor1.uol.com.br/news/ranger", marca="Ford", modelo="Ranger"
        )
        assert not c.aceita
        assert "já medido e reprovado" in c.motivo and "403" in c.motivo

    def test_o_tipo_viaja_para_a_trilha(self):
        c = classify.classificar("https://www.icarros.com.br/x", marca="Chevrolet")
        assert c.to_dict()["tipo"] == "ficha"
        assert c.to_dict()["navegador"] is False


class TestOAnoDaPagina:
    """Uma matéria de 2015 não descreve a picape de 2027 — descreve a anterior.

    Medido na pesquisa ao vivo da S10 High Country 2027, em 14/09/2026. Entre as doze
    páginas coletadas entrou `autoesporte.globo.com/testes/noticia/**2015**/07/...`, um
    teste da geração anterior. Dela saíram, com citação verdadeira e `status=verificado`:
    **200 cv** (a de 2027 tem 207), **500 Nm** (tem 510), **seis marchas** (tem oito) e
    `4 cilindros em linha` num campo que já dizia `4`. Quatro divergências inventadas
    contra o gabarito, todas por ler o carro certo no ano errado.

    O domínio estava aprovado, o modelo aparecia no endereço, o texto era ficha de verdade.
    O que faltava perguntar era **de quando**. A URL diz, e dizer é de graça.
    """

    def test_materia_muito_mais_velha_que_o_ano_modelo_sai(self):
        d = classify.classificar(
            "https://autoesporte.globo.com/testes/noticia/2015/07/chevrolet-s10-high-country.html",
            marca="Chevrolet",
            modelo="S10",
            ano=2027,
        )
        assert not d.aceita
        assert "2015" in d.motivo

    def test_pagina_recente_continua_valendo(self):
        d = classify.classificar(
            "https://autoesporte.globo.com/noticia/2026/07/chevrolet-s10-high-country.html",
            marca="Chevrolet",
            modelo="S10",
            ano=2027,
        )
        assert d.aceita

    def test_o_ano_do_catalogo_e_o_ano_modelo_e_nao_reprova(self):
        """`icarros.com.br/catalogo/chevrolet/s10/2027` leva o ano no caminho — o certo."""
        d = classify.classificar(
            "https://www.icarros.com.br/catalogo/chevrolet/s10/2027",
            marca="Chevrolet",
            modelo="S10",
            ano=2027,
        )
        assert d.aceita

    def test_sem_ano_pedido_a_regra_nao_opina(self):
        d = classify.classificar(
            "https://autoesporte.globo.com/testes/noticia/2015/07/chevrolet-s10.html",
            marca="Chevrolet",
            modelo="S10",
        )
        assert d.aceita

    def test_url_sem_ano_nenhum_passa(self):
        assert classify.ano_da_url("https://www.chevrolet.com.br/picapes/s10") is None
        opaca = "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=47930"
        assert classify.ano_da_url(opaca) is None

    def test_quando_ha_dois_anos_vale_o_mais_novo(self):
        """Barrar pelo mais velho reprovaria `/2026/retrospectiva-2015/` — que é de 2026."""
        assert classify.ano_da_url("https://x.com.br/2026/07/retrospectiva-2015.html") == 2026


class TestPaginaDeComparacao:
    """Tabela com quatro colunas de valor não é ficha de uma versão — é quatro fichas.

    Medido na S10 em 14/09/2026. `carrosnaweb.com.br/resultcompara.asp?modelos=7459-7460-
    7468-8283` põe quatro picapes lado a lado, e cada linha da tabela é
    `Torque máximo⇥44,9 kgfm⇥26,3 kgfm (G)⇥51 kgfm⇥51 kgfm`. O extrator não tem como saber
    qual coluna é a High Country — e não errou por pouco: gravou **dezessete valores de
    torque** para a mesma picape, entre 79 e 440 Nm, cada um com citação verdadeira e
    `status=verificado`. Um deles veio da linha `Torque específico`, em kgfm por litro.

    O domínio é bom e continua bom: `carrosnaweb.com.br/fichadetalhe.asp?codigo=47930` é
    ficha de uma versão só. O que se recusa é a página que compara, não o site.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.carrosnaweb.com.br/resultcompara.asp?modelos=7459-7460-7468-8283",
            "https://www.carrosnaweb.com.br/m/resultcompara.asp?modelos=13205-13206&cont=0",
            "https://www.icarros.com.br/comparativo/chevrolet-s10-x-ford-ranger",
            "https://exemplo.com.br/chevrolet-s10-vs-ford-ranger",
        ],
    )
    def test_pagina_que_compara_varios_veiculos_sai(self, url):
        d = classify.classificar(url, marca="Chevrolet", modelo="S10", ano=2027)
        assert not d.aceita
        assert "compara" in d.motivo

    def test_listagem_de_busca_do_site_tambem_sai(self):
        d = classify.classificar(
            "https://www.carrosnaweb.com.br/catalogo.asp?varnome=s10",
            marca="Chevrolet",
            modelo="S10",
            ano=2027,
        )
        assert not d.aceita

    def test_a_ficha_de_uma_versao_continua_entrando(self):
        d = classify.classificar(
            "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=47930",
            marca="Chevrolet",
            modelo="S10",
            ano=2027,
            snippet="Chevrolet S10 2.8 High Country CD 4x4 — ficha técnica completa",
        )
        assert d.aceita and d.tier == 3


class TestOResumoDaBusca:
    """O endereço pode ser um código; o resumo do buscador diz de que carro ele é.

    `carrosnaweb.com.br/fichadetalhe.asp?codigo=47930` é a melhor página da rodada da S10:
    ficha de **uma** versão, tabela rótulo/valor, lida por regra. E ela era descartada por
    "não menciona S10 no endereço nem no título", porque o endereço é um número.

    O resumo é metadado do buscador: decide o que baixar, nunca vira evidência.
    """

    def test_o_resumo_salva_a_pagina_de_endereco_opaco(self):
        assert not classify.fala_do_modelo(
            "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=47930", "Ficha técnica", "S10"
        )
        assert classify.fala_do_modelo(
            "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=47930",
            "Ficha técnica",
            "S10",
            "Chevrolet S10 High Country 2.8 turbodiesel",
        )

    def test_o_resumo_nao_salva_pagina_de_outro_carro(self):
        assert not classify.fala_do_modelo(
            "https://www.carrosnaweb.com.br/fichadetalhe.asp?codigo=1",
            "Ficha técnica",
            "S10",
            "Ford Ranger Raptor 3.0 V6",
        )


class TestOManualQueEscapou:
    """O filtro de manual existia e o manual entrou assim mesmo, por um erro de digitacao.

    Medido na S10 em 14/09/2026. A URL da propria Chevrolet e
    `.../01-pdfs/2025/s10-2025-manual-do-**propietario**.pdf` — sem o segundo R. O padrao
    cadastrado era `manual-do-proprietario`, escrito certo, e nao casou.

    O manual entrou como tier 1 e rendeu **43 das 58 linhas** daquela rodada, todas com
    citacao verdadeira e nenhuma sobre a ficha da picape: `deslocamento_l 5,6` de 'Oleo do
    motor - Reabastecer com troca de filtro 5,6 L', `9,0` do sistema de arrefecimento,
    `3,5` da transmissao manual, `numero_marchas 6` de '(6 velocidades)' e `torque_nm 460`
    da linha 'MT = 460 Nm', que e a versao de cambio manual. Um PDF de 400 paginas tambem
    comeu o relogio: a rodada parou por tempo com seis paginas.

    O padrao passa a casar o prefixo, que e o que os dois jeitos de escrever tem em comum.
    """

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.chevrolet.com.br/content/dam/chevrolet/01-pdfs/2025/s10-2025-manual-do-propietario.pdf",
            "https://www.chevrolet.com.br/content/dam/01-pdfs/s10-manual-do-proprietario.pdf",
            "https://exemplo.com.br/manual_do_propietario_2026.pdf",
            "https://exemplo.com.br/guia-do-proprietario/s10",
        ],
    )
    def test_manual_em_qualquer_grafia_fica_de_fora(self, url):
        d = classify.classificar(url, marca="Chevrolet", modelo="S10", ano=2027)
        assert not d.aceita
        assert "manual" in d.motivo

    def test_a_pagina_da_picape_continua_entrando(self):
        d = classify.classificar(
            "https://www.chevrolet.com.br/picapes/s10",
            marca="Chevrolet",
            modelo="S10",
            ano=2027,
        )
        assert d.aceita and d.tier == 1
