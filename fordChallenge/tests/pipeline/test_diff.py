"""WP-12 — diff entre duas coletas e os alertas que ele gera.

Critério de aceite da spec: *"dada uma segunda execução com snapshot cujo preço mudou,
então existe `alert(type='preco', old, new)`"*.

O resto do arquivo cuida do outro lado do mesmo problema: **alerta que dispara demais não
é alerta**. Se `nao_encontrado` → `nao_encontrado` gerasse aviso, o usuário aprenderia a
ignorar a caixa de alertas — e aí o alerta que importa passa junto.
"""

from __future__ import annotations

from pipeline.diff import CAMPOS_DE_PRECO, comparar
from pipeline.schema import Conflict, Evidence, SpecField, Status, empty_spec


def _com(spec, caminho: str, valor, status: Status = Status.VERIFICADO):
    """Preenche um campo da ficha com o status pedido e a evidencia que ele exige."""
    evidencias = []
    if status in {Status.VERIFICADO, Status.DIVERGENTE}:
        evidencias = [
            Evidence(
                evidence_id="e",
                source_url="https://oficial",
                tier=1,
                quote=f"R$ {valor}",
                captured_at="2026-09-01",
            )
        ]
    conflitos = []
    if status is Status.DIVERGENTE:
        conflitos = [
            Conflict(value=valor + 1 if isinstance(valor, int) else "outro", evidence=evidencias[0])
        ]
    spec.set(
        caminho,
        SpecField(
            value=valor,
            status=status,
            confidence=0.9,
            evidences=evidencias,
            conflicts=conflitos,
        ),
    )
    return spec


class TestCriterioDeAceiteDoAlertaDePreco:
    def test_preco_que_mudou_entre_coletas_gera_alerta_com_old_e_new(self):
        antes = _com(empty_spec(job_id="1"), "comercial.preco_sugerido_brl", 499000)
        depois = _com(empty_spec(job_id="2"), "comercial.preco_sugerido_brl", 512000)

        diff = comparar(antes, depois)
        alertas = diff.por_campo("preco_sugerido_brl")
        assert len(alertas) == 1
        alerta = alertas[0]
        assert alerta.type == "preco"
        assert (alerta.old, alerta.new) == (499000, 512000)

    def test_o_alerta_carrega_a_evidencia_do_valor_NOVO(self):
        # Alerta nasce provável, não como boato: quem recebe tem de poder conferir o
        # número novo na fonte, sem ir procurar.
        antes = _com(empty_spec(job_id="1"), "comercial.preco_sugerido_brl", 499000)
        depois = _com(empty_spec(job_id="2"), "comercial.preco_sugerido_brl", 512000)
        (alerta,) = comparar(antes, depois).por_campo("preco_sugerido_brl")
        assert "512000" in alerta.quote

    def test_todos_os_campos_comerciais_sao_do_tipo_preco(self):
        assert "preco_fipe_brl" in CAMPOS_DE_PRECO
        antes = _com(empty_spec(job_id="1"), "comercial.preco_fipe_brl", 452540)
        depois = _com(empty_spec(job_id="2"), "comercial.preco_fipe_brl", 460000)
        assert comparar(antes, depois).de_preco


class TestAlertaQueNaoDeveDisparar:
    def test_ficha_identica_nao_gera_alerta(self):
        antes = _com(empty_spec(job_id="1"), "motorizacao.potencia_cv", 397)
        depois = _com(empty_spec(job_id="2"), "motorizacao.potencia_cv", 397)
        diff = comparar(antes, depois)
        assert not diff.alertas
        assert diff.inalterados > 0

    def test_vazio_para_vazio_do_mesmo_tipo_nao_e_mudanca(self):
        diff = comparar(empty_spec(job_id="1"), empty_spec(job_id="2"))
        assert not diff.alertas

    def test_397_e_397_ponto_zero_nao_sao_mudanca(self):
        # A comparação é a MESMA do eval. Com `!=`, a ficha anunciaria "a potência
        # mudou" a cada coleta em que o parser devolvesse float em vez de int.
        antes = _com(empty_spec(job_id="1"), "motorizacao.potencia_cv", 397)
        depois = _com(empty_spec(job_id="2"), "motorizacao.potencia_cv", 397.0)
        assert not comparar(antes, depois).por_campo("potencia_cv")


class TestMudancaDeStatusSemMudancaDeValor:
    def test_mesmo_valor_com_status_diferente_gera_alerta_de_STATUS(self):
        # Um preço que virou `divergente` mantendo o número é notícia — mas não é "o
        # preço subiu". Misturar as duas coisas num tipo só faria o filtro da watchlist
        # mentir.
        antes = _com(empty_spec(job_id="1"), "comercial.preco_sugerido_brl", 499000)
        depois = _com(
            empty_spec(job_id="2"), "comercial.preco_sugerido_brl", 499000, Status.DIVERGENTE
        )
        (alerta,) = comparar(antes, depois).por_campo("preco_sugerido_brl")
        assert alerta.type == "status"
        assert (alerta.old_status, alerta.new_status) == ("verificado", "divergente")

    def test_os_dois_vazios_distintos_geram_alerta_de_status(self):
        # `nao_disponivel` ("a fonte diz que não tem") ≠ `nao_encontrado` ("ninguém
        # menciona"). A troca entre os dois é informação, e das boas.
        antes = _com(empty_spec(job_id="1"), "exterior.rodas_material", None, Status.NAO_ENCONTRADO)
        depois = _com(
            empty_spec(job_id="2"), "exterior.rodas_material", None, Status.NAO_DISPONIVEL
        )
        (alerta,) = comparar(antes, depois).por_campo("rodas_material")
        assert alerta.type == "status"
        assert alerta.new_status == "nao_disponivel"


class TestValorQueApareceOuDesaparece:
    def test_campo_que_ganhou_valor_gera_alerta(self):
        antes = _com(empty_spec(job_id="1"), "motorizacao.potencia_cv", None, Status.NAO_ENCONTRADO)
        depois = _com(empty_spec(job_id="2"), "motorizacao.potencia_cv", 397)
        (alerta,) = comparar(antes, depois).por_campo("potencia_cv")
        assert (alerta.old, alerta.new) == (None, 397)

    def test_campo_que_perdeu_valor_gera_alerta(self):
        # O site tirou a informação do ar. Isso é mudança, e das que interessam.
        antes = _com(empty_spec(job_id="1"), "motorizacao.potencia_cv", 397)
        depois = _com(
            empty_spec(job_id="2"), "motorizacao.potencia_cv", None, Status.NAO_ENCONTRADO
        )
        (alerta,) = comparar(antes, depois).por_campo("potencia_cv")
        assert (alerta.old, alerta.new) == (397, None)
