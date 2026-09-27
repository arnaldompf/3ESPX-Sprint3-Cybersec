from pipeline.identity import VehicleTarget, claim_rejection
from pipeline.semantics import validate_number

TARGET = VehicleTarget("Ford", "Ranger", "Limited 3.0 V6 Diesel 4WD AT", 2027)


def test_camera_no_bloco_opcional_nao_vira_equipamento_de_serie():
    text = """Ford Ranger MY2027
Limited 3.0 V6 Diesel 4WD AT 2027
Rodas de liga leve 18\"
Limited 3.0 V6 Diesel 4WD AT 2027 + Kit Opcional
Principais itens:
Câmera 360°
Rodas de liga leve 20\"
"""
    assert claim_rejection(TARGET, "Câmera 360°", source_text=text)
    assert claim_rejection(TARGET, 'Rodas de liga leve 20"', source_text=text)
    assert claim_rejection(TARGET, 'Rodas de liga leve 18"', source_text=text) is None


def test_item_repetido_no_bloco_padrao_e_opcional_tem_prova_padrao():
    text = """Limited 3.0 V6 Diesel 4WD AT 2027
Potência 250 cv
Limited 3.0 V6 Diesel 4WD AT 2027 + Kit Opcional
Potência 250 cv
"""
    assert claim_rejection(TARGET, "Potência 250 cv", source_text=text) is None


def test_five_years_e_conversao_exata_para_sessenta_meses():
    assert validate_number("garantia_meses", 60, "Garantia contratual: 5 anos", "meses")
    assert not validate_number("garantia_meses", 5, "Garantia contratual: 5 anos", "meses")
    assert validate_number("garantia_meses", 60, "Garantia: 60 meses", "meses")
    assert not validate_number("garantia_meses", 27, "Ranger 2027: garantia 5 anos", "meses")


def test_whitespace_normalizado_e_subtitulo_opcional_nao_burlam_contexto():
    text = """Câmera 360 graus.
# Ford Ranger Limited 3.0 V6 Diesel 4WD AT 2027
## Kit Opcional
Câmera  360 graus.
"""
    assert claim_rejection(TARGET, "Camera 360 graus.", source_text=text)


def test_noticia_tremor_nao_comprova_limited_citada_apenas_como_comparacao():
    from pipeline.identity import Applicability, assess

    text = """Nova Ford Ranger Tremor estreia no Brasil até 2027
Motor 2.3 turbo de 274 cv, câmbio automático, tração 4x4.
Custa mais que a Ford Ranger Limited 3.0 V6 Diesel 4WD AT, citada como comparação.
"""
    assert (
        assess(TARGET, text, url="https://quatrorodas.abril.com.br/noticias/ranger-tremor").status
        == Applicability.INCOMPATIBLE
    )


def test_pacotes_de_opcionais_sem_cabecalho_de_motor_nao_comprovam_serie():
    target = VehicleTarget("Volkswagen", "Amarok", "V6 Extreme", 2026)
    text = """# Volkswagen Amarok 2026: preços, versões e equipamentos
## Principais equipamentos
* **Highline**: assistente de condução passiva Safer Tag, bancos de couro.
* **Extreme**: itens da Highline + rodas de 20 polegadas.
## Pacotes de opcionais
**Amarok V6 Comfortline**Capota Marítima e estribo lateral - R$ 4.220
Safer Tag (Assistente de condução passiva) - R$ 3.460
### Detalhes do pacote
Acabamento especial opcional
## Dimensões
Comprimento de 5,35 metros
"""
    assert claim_rejection(
        target, "Safer Tag (Assistente de condução passiva) - R$ 3.460", source_text=text
    )
    assert claim_rejection(target, "Acabamento especial opcional", source_text=text)
    assert (
        claim_rejection(
            target, "assistente de condução passiva Safer Tag, bancos de couro.", source_text=text
        )
        is None
    )
    assert claim_rejection(target, "Comprimento de 5,35 metros", source_text=text) is None


def test_fim_do_pacote_nao_apaga_escopo_da_versao_pai():
    text = """# Ford Ranger XLT 3.0 V6 Diesel 2027
## Kit opcional
Câmera 360 graus
## Dimensões
Comprimento 5.370 mm
"""
    assert claim_rejection(TARGET, "Comprimento 5.370 mm", source_text=text)
