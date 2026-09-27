"""WP-25 — a semente de `equivalents` de `docs/12` §6.1.

O teste que carrega o peso é `test_par_sem_contraparte_fica_pendente`: três dos quatro
pares da spec apontam para uma **Ranger diesel de topo que o gabarito não descreve**.
Cadastrar aqueles pares exigiria criar uma linha em `versions` com um nome de versão
inventado — e a partir daí o resolvedor (WP-07) encontraria no banco uma versão sem
nenhuma evidência atrás, que é o defeito que o produto inteiro existe para não ter.

O caminho honesto é o par ficar pendente **com o motivo dito**, e o impacto do alerta sair
com `motivo_sem_gap` em vez de um gap zero — que é o que a tela mostra.
"""

from __future__ import annotations

import pytest
from sqlmodel import select

from api.app.seed import SEMENTE_DE_EQUIVALENCIA, _semear_equivalencias


@pytest.fixture
def semente(catalogo):
    """Roda a semente sobre o catálogo mínimo dos testes.

    A Hilux `SRX Plus AT` entra aqui com o nome **canônico** (`pipeline.version_names`) —
    a fixture `catalogo` guarda a grafia anterior, `SRX Plus AT (Cabine Dupla)`, que é um
    catálogo ainda não migrado pela `0006`. Sem esta linha, o par da Hilux ficaria pendente
    pelo lado do concorrente, e o teste não exercitaria o caso que importa: a **contraparte
    Ford** faltando.
    """
    from api.app.db import session_scope
    from api.app.models import VehicleModel, Version

    with session_scope() as sessao:
        hilux = sessao.exec(select(VehicleModel).where(VehicleModel.nome == "Hilux")).first()
        assert hilux is not None
        sessao.add(
            Version(model_id=hilux.id, nome_exato="SRX Plus AT", ano_modelo=2026, in_lineup=True)
        )
        sessao.flush()
        resultado = _semear_equivalencias(sessao)
        sessao.commit()
    return resultado


def test_a_semente_e_a_da_spec(semente):
    """Os quatro pares de `docs/12` §6.1, nem mais nem menos."""
    assert len(SEMENTE_DE_EQUIVALENCIA) == 4
    concorrentes = {par[0][2] for par in SEMENTE_DE_EQUIVALENCIA}
    assert concorrentes == {
        "SRX Plus AT",
        "High Country",
        "V6 Extreme",
        "Raptor 3.0 V6 Bi-turbo 4WD AT",
    }


def test_a_raptor_entra_como_sem_par_direto(semente, catalogo):
    """`ford_version_id=None` é afirmação, não lacuna — e é o que a spec manda dizer."""
    from api.app.db import session_scope
    from api.app.models import Equivalent

    with session_scope() as sessao:
        linha = sessao.exec(
            select(Equivalent).where(Equivalent.competitor_version_id == catalogo["raptor"])
        ).first()
        assert linha is not None
        assert linha.ford_version_id is None
        assert "sem par direto" in linha.nota


def test_par_sem_contraparte_fica_pendente_com_o_motivo(semente):
    """Pendente e **dito**. Silêncio aqui viraria "não há equivalente" por omissão."""
    pendentes = semente["pendentes"]
    assert any("contraparte Ford nao esta no catalogo" in p for p in pendentes)
    # O par da Hilux nomeia as duas pontas, para o gestor saber o que cadastrar.
    assert any("SRX Plus AT" in p and "Ranger" in p for p in pendentes)
    assert not any("Raptor" in p for p in pendentes)


def test_concorrente_fora_do_catalogo_tem_motivo_proprio(semente):
    """Concorrente ausente e contraparte ausente são pendências diferentes.

    A S10 e a Amarok não estão no catálogo mínimo dos testes, e o motivo tem de dizer
    **qual** das duas pontas faltou — juntar as duas num "não foi possível" faria o gestor
    procurar a versão errada.
    """
    pendentes = semente["pendentes"]
    assert any("versao do concorrente nao esta no catalogo" in p for p in pendentes)
    assert any("High Country" in p for p in pendentes)


def test_nao_inventa_par_para_o_gap_ter_numero(semente, catalogo):
    """Nenhuma equivalência aponta a Hilux para a Raptor.

    Seria o atalho tentador: a Raptor é a única Ford Ranger do catálogo, e usá-la faria o
    gap da demo exibir um número. Número errado, porém — a Raptor é picape de desempenho a
    gasolina, e a própria spec diz que ela não tem par de trabalho.
    """
    from api.app.db import session_scope
    from api.app.models import Equivalent

    with session_scope() as sessao:
        linhas = sessao.exec(select(Equivalent)).all()
        assert all(linha.ford_version_id != catalogo["raptor"] for linha in linhas)


def test_rodar_duas_vezes_nao_duplica(semente, catalogo):
    from api.app.db import session_scope
    from api.app.models import Equivalent

    with session_scope() as sessao:
        segunda = _semear_equivalencias(sessao)
        sessao.commit()
        assert segunda["inseridos"] == 0
        linhas = sessao.exec(
            select(Equivalent).where(Equivalent.competitor_version_id == catalogo["raptor"])
        ).all()
        assert len(linhas) == 1
