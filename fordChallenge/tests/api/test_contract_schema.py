"""WP-06 — a resposta da API valida contra `schema/canonical_spec.schema.json`.

Este arquivo existe porque o `response_model` do FastAPI **não** é o schema canônico. Ele
valida contra o modelo Pydantic, que é a mesma classe, mas o arquivo JSON Schema é o
contrato que outro time consome — e as duas coisas podem divergir sem que nada acuse: o
Pydantic aceita um campo que o JSON Schema declarou `required`, ou um `status` fora do
`enum`. Se divergirem, o cliente que valida pelo contrato rejeita uma resposta que a API
considera boa.

Também confere o OpenAPI exportado, pelos dois motivos que fazem um contrato gerado falhar
em silêncio: rota prometida ausente e `operationId` repetido (que faz gerador de cliente
sobrescrever uma função com a outra).
"""

from __future__ import annotations

import json

import jsonschema
import pytest

from api.app.models import Role
from pipeline.schema import GRUPOS, json_schema

VEHICLES = "/api/v1/vehicles"


@pytest.fixture
def analista(criar_usuario, logar):
    criar_usuario("analista@suno.example.com", Role.ANALISTA)
    return logar("analista@suno.example.com")


class TestFichaValidaNoSchemaCanonico:
    def test_ficha_com_valores_valida(self, cliente_auth, catalogo, analista):
        ficha = cliente_auth.get(f"{VEHICLES}/{catalogo['raptor']}/specs", headers=analista).json()
        jsonschema.validate(instance=ficha, schema=json_schema())

    def test_ficha_vazia_valida(self, cliente_auth, catalogo, analista):
        """Versão sem extração também tem de produzir ficha válida."""
        ficha = cliente_auth.get(f"{VEHICLES}/{catalogo['srx']}/specs", headers=analista).json()
        jsonschema.validate(instance=ficha, schema=json_schema())

    def test_ficha_filtrada_valida(self, cliente_auth, catalogo, analista):
        """O critério de aceite: filtrada **e** válida.

        Se o filtro omitisse campos, esta validação falharia — o schema exige todos.
        """
        ficha = cliente_auth.get(
            f"{VEHICLES}/{catalogo['raptor']}/specs?attributes=potencia_cv", headers=analista
        ).json()
        jsonschema.validate(instance=ficha, schema=json_schema())

    def test_o_schema_exige_todos_os_grupos(self):
        """Prova de que a validação acima tem dentes.

        Se o JSON Schema não exigisse os grupos, uma ficha sem `motorizacao` passaria e o
        teste de filtro acima não estaria provando nada.
        """
        esquema = json_schema()
        obrigatorios = set(esquema.get("required", []))
        assert set(GRUPOS) <= obrigatorios, set(GRUPOS) - obrigatorios

    def test_ficha_sem_um_grupo_e_recusada(self, cliente_auth, catalogo, analista):
        """O contra-teste: o schema realmente reprova ficha incompleta."""
        ficha = cliente_auth.get(f"{VEHICLES}/{catalogo['raptor']}/specs", headers=analista).json()
        del ficha["motorizacao"]
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(instance=ficha, schema=json_schema())

    @pytest.mark.parametrize("caminho", ["motorizacao.potencia_cv", "transmissao.tipo"])
    def test_todo_campo_traz_status_e_sources_checked(
        self, cliente_auth, catalogo, analista, caminho
    ):
        grupo, campo = caminho.split(".")
        ficha = cliente_auth.get(f"{VEHICLES}/{catalogo['raptor']}/specs", headers=analista).json()
        celula = ficha[grupo][campo]
        assert celula["status"], caminho
        assert "sources_checked" in celula, caminho

    def test_o_status_fica_no_vocabulario_fechado(self, cliente_auth, catalogo, analista):
        from pipeline.schema import Status

        ficha = cliente_auth.get(f"{VEHICLES}/{catalogo['raptor']}/specs", headers=analista).json()
        validos = {s.value for s in Status}
        for grupo in GRUPOS:
            for campo, celula in ficha[grupo].items():
                assert celula["status"] in validos, f"{grupo}.{campo}: {celula['status']}"


class TestMatrizDeComparacao:
    def test_cada_celula_e_um_specfield_com_diff(self, cliente_auth, catalogo, analista):
        corpo = cliente_auth.post(
            "/api/v1/comparisons",
            headers=analista,
            json={
                "base_vehicle_id": catalogo["raptor"],
                "competitor_ids": [catalogo["srx"]],
                "attributes": ["potencia_cv", "torque_nm"],
            },
        ).json()

        assert len(corpo["cells"]) == len(corpo["attributes"]) == 2
        for linha in corpo["cells"]:
            assert len(linha) == len(corpo["vehicles"])
            for celula in linha:
                # A célula é um `SpecField` serializado, mais o `diff`.
                assert {"value", "status", "confidence", "diff"} <= set(celula)

    def test_a_coluna_do_proprio_veiculo_base_nunca_difere_de_si(
        self, cliente_auth, catalogo, analista
    ):
        corpo = cliente_auth.post(
            "/api/v1/comparisons",
            headers=analista,
            json={
                "base_vehicle_id": catalogo["raptor"],
                "competitor_ids": [catalogo["srx"]],
                "attributes": ["potencia_cv"],
            },
        ).json()
        assert corpo["cells"][0][0]["diff"] is False


class TestOpenApi:
    @pytest.fixture(scope="class")
    def esquema(self):
        from scripts.export_openapi import gerar

        return gerar()

    def test_o_contrato_fecha(self, esquema):
        """Rota prometida ausente e `operationId` repetido são falhas silenciosas."""
        from scripts.export_openapi import conferir

        assert conferir(esquema) == []

    def test_standard_spec_esta_nos_componentes(self, esquema):
        assert "StandardSpec" in esquema["components"]["schemas"]

    def test_toda_rota_da_api_declara_seguranca_menos_as_publicas(self, esquema):
        """`/health` e `/auth/login` são públicos por contrato; o resto, não."""
        publicas = {"/api/v1/health", "/api/v1/auth/login", "/api/v1/auth/refresh"}
        sem_auth = []
        for rota, metodos in esquema["paths"].items():
            if rota in publicas or not rota.startswith("/api"):
                continue
            for verbo, operacao in metodos.items():
                if verbo not in {"get", "post", "patch", "delete"}:
                    continue
                if not operacao.get("security"):
                    sem_auth.append(f"{verbo.upper()} {rota}")
        assert not sem_auth, f"rotas sem exigência de credencial no contrato: {sem_auth}"

    def test_o_arquivo_exportado_bate_com_o_app(self, esquema, raiz):
        """`reports/openapi.json` desatualizado é contrato mentindo sobre a API."""
        caminho = raiz / "reports" / "openapi.json"
        if not caminho.exists():
            pytest.skip(
                "reports/openapi.json ainda não foi gerado (rode scripts/export_openapi.py)"
            )
        assert json.loads(caminho.read_text(encoding="utf-8")) == esquema


class TestProblemJsonEmTodoErro:
    @pytest.mark.parametrize(
        ("rota", "status"),
        [
            ("/api/v1/vehicles/nao-existe", 404),
            ("/api/v1/evidences/nao-existe", 404),
            ("/api/v1/jobs/nao-existe", 404),
        ],
    )
    def test_erro_sai_em_problem_json(self, cliente_auth, catalogo, analista, rota, status):
        resposta = cliente_auth.get(rota, headers=analista)
        assert resposta.status_code == status
        assert resposta.headers["content-type"].startswith("application/problem+json")
        corpo = resposta.json()
        assert {"type", "title", "status", "detail", "instance"} <= set(corpo)

    def test_422_lista_os_campos_invalidos(self, cliente_auth, catalogo, analista):
        resposta = cliente_auth.post("/api/v1/resolutions", headers=analista, json={})
        assert resposta.status_code == 422
        assert resposta.json()["errors"]
