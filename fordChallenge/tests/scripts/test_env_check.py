"""O conferidor do `.env`: ele tem de achar o segredo fora do lugar **sem mostrá-lo**.

Todos os valores deste arquivo são **sintéticos**. Uma credencial de verdade num teste
entra no repositório, e um repositório é para sempre — que é exatamente o problema que o
script testado aqui existe para evitar. As formas são reais; os bytes, não.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
# `scripts/` entra no caminho: `env_check` e um script, nao um pacote. Carregar por
# `spec_from_file_location` sem registrar em `sys.modules` quebra `@dataclass`, que
# procura o modulo do proprio nome para resolver anotacoes.
sys.path.insert(0, str(RAIZ / "scripts"))

import env_check  # noqa: E402

#: A forma exata que vazou em 13/09/2026 — com bytes trocados.
#:
#: O ponto depois de `AQ` é o detalhe que importa: a primeira versão de `parece_segredo`
#: casava `^[A-Za-z0-9_-]{24,}$`, e `.` não está nessa classe. O valor não foi reconhecido
#: como credencial e **saiu inteiro** no relatório que reclamava dele.
TOKEN_GOOGLE_OAUTH = "AQ.Ab8RN6Ixxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
CHAVE_GOOGLE_ESTUDIO = "AIzaSyXxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"
CHAVE_MOONSHOT = "sk-" + "x" * 48
CHAVE_ANTHROPIC = "sk-ant-api03-" + "x" * 40


class TestNaoVaza:
    """O contrato mais importante: nada aqui imprime uma chave inteira."""

    @pytest.mark.parametrize(
        "valor",
        [TOKEN_GOOGLE_OAUTH, CHAVE_GOOGLE_ESTUDIO, CHAVE_MOONSHOT, CHAVE_ANTHROPIC],
    )
    def test_a_mascara_mostra_no_maximo_quatro_caracteres(self, valor: str):
        saida = env_check.mascarar(valor)
        assert valor not in saida
        assert valor[:-4] not in saida
        assert saida.endswith("caracteres)") or valor[-4:] in saida
        # O miolo não aparece de forma nenhuma: nem um pedaço de 8 caracteres dele.
        miolo = valor[4:-4]
        for i in range(0, max(1, len(miolo) - 8)):
            assert miolo[i : i + 8] not in saida

    def test_o_token_com_ponto_e_reconhecido(self):
        """**A regressão.** Antes de 13/09/2026 este caso devolvia `False` e vazava."""
        assert env_check.parece_segredo(TOKEN_GOOGLE_OAUTH) is True
        assert "Google" in env_check.mascarar(TOKEN_GOOGLE_OAUTH)

    def test_nenhuma_mensagem_de_conferencia_carrega_o_valor(self):
        """O caso perigoso: o conferidor vazando ao **apontar** o problema.

        Uma credencial em campo de booleano, de URL e de modelo — os três caminhos de
        mensagem que formatavam o valor com `!r`.
        """
        valores = {
            "AUTH_ENABLED": TOKEN_GOOGLE_OAUTH,
            "REPLAY_MODE": "1",
            "LLM_FAKE": "1",
            "DATABASE_URL": "sqlite:///x.db",
            "LLM_API_BASE": CHAVE_MOONSHOT,
            "LLM_MODEL_ALT": CHAVE_GOOGLE_ESTUDIO,
            "API_PORT": CHAVE_ANTHROPIC,
        }
        texto = " ".join(f"{p.texto} {p.conserto}" for p in env_check.conferir(valores))
        assert texto, "a conferência tinha de reclamar de alguma coisa"
        for segredo in (
            TOKEN_GOOGLE_OAUTH,
            CHAVE_MOONSHOT,
            CHAVE_GOOGLE_ESTUDIO,
            CHAVE_ANTHROPIC,
        ):
            assert segredo not in texto, "o conferidor de segredo vazou o segredo"

    def test_o_relatorio_na_tela_tambem_nao_vaza(self, capsys):
        """`relatar` imprime valores não-secretos por inteiro — de propósito. O risco é
        uma credencial guardada num campo que **não** é declarado como segredo."""
        valores = {"LLM_MODEL_ALT": TOKEN_GOOGLE_OAUTH, "PDF_MOTOR": CHAVE_MOONSHOT}
        env_check.relatar(valores, env_check.conferir(valores))
        saida = capsys.readouterr().out
        assert TOKEN_GOOGLE_OAUTH not in saida
        assert CHAVE_MOONSHOT not in saida


class TestNaoMascaraDemais:
    """O outro lado: mascarar o que é público torna o relatório inútil."""

    @pytest.mark.parametrize(
        "valor",
        [
            "kimi-k2.6",
            "claude-haiku-4-5-20251001",
            "https://api.moonshot.ai/v1",
            "postgresql+psycopg://specradar:senha@localhost:5432/specradar",
            "sqlite:///./data/dev.db",
            "admin@specradar.example.com",
            "data/snapshots",
            "./data/snapshots",
            "127.0.0.1",
            "replay",
        ],
    )
    def test_valor_publico_nao_e_tratado_como_segredo(self, valor: str):
        assert env_check.parece_segredo(valor) is False, valor

    @pytest.mark.parametrize(
        "valor",
        [
            "gemini-2.5-flash",
            "openrouter/moonshotai/kimi-k2",
            "claude-sonnet-5",
            "deepseek-chat",
        ],
    )
    def test_nome_de_modelo_longo_nao_e_segredo(self, valor: str):
        """O custo de falhar fechado, e o limite da isenção: nome de modelo é minúsculo,
        tem separador e tem palavra dentro. Credencial quase nunca tem os três."""
        assert env_check.nome_tecnico(valor) is True
        assert env_check.parece_segredo(valor) is False

    @pytest.mark.parametrize(
        "valor",
        [
            "550e8400-e29b-41d4-a716-446655440000",  # UUID: pedaços são hexadecimal
            "a3f9c2e1b8d7a6f5c4e3b2a1908f7e6d5c4b3a29",  # hex minúsculo, sem separador
            "AQ.Ab8RN6Ixxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",  # maiúsculas
        ],
    )
    def test_a_isencao_de_nome_tecnico_nao_abre_a_porta(self, valor: str):
        """A isenção é estreita de propósito: quem quase passa por ela tem de continuar
        mascarado, ou ela vira o buraco no lugar do detector."""
        assert env_check.parece_segredo(valor) is True

    def test_user_agent_longo_nao_e_segredo(self):
        """Tem 70 caracteres e um e-mail dentro — mas tem espaços, e chave não tem."""
        agente = "SpecRadar/0.1 (FIAP Challenge Ford; contato: alguem@example.com)"
        assert env_check.parece_segredo(agente) is False


class TestAchaOSegredoForaDoLugar:
    def test_credencial_em_campo_de_modelo_e_erro_com_destino(self):
        problemas = env_check.conferir(
            {
                "LLM_MODEL_ALT": CHAVE_GOOGLE_ESTUDIO,
                "REPLAY_MODE": "1",
                "LLM_FAKE": "1",
                "AUTH_ENABLED": "false",
                "DATABASE_URL": "sqlite:///x.db",
            }
        )
        achado = [p for p in problemas if p.nome == "LLM_MODEL_ALT"]
        assert achado, "não reclamou da credencial no campo de modelo"
        assert achado[0].gravidade == "erro"
        assert "LLM_API_KEY_ALT" in achado[0].conserto

    def test_chave_de_um_provedor_com_outro_declarado_e_erro(self):
        """O erro que só aparece na primeira chamada real: chave da Anthropic com
        `LLM_PROVIDER=kimi`. O prefixo já dizia, e ninguém tinha perguntado."""
        problemas = env_check.conferir(
            {
                "LLM_PROVIDER": "kimi",
                "LLM_API_KEY": CHAVE_ANTHROPIC,
                "LLM_MODEL": "kimi-k2.6",
                "REPLAY_MODE": "1",
                "LLM_FAKE": "1",
                "AUTH_ENABLED": "false",
                "DATABASE_URL": "sqlite:///x.db",
            }
        )
        erros = [p for p in problemas if p.nome == "LLM_API_KEY" and p.gravidade == "erro"]
        assert erros, "não viu a chave do provedor errado"
        assert "Anthropic" in erros[0].texto

    def test_apelido_de_provedor_e_aceito(self):
        """`moonshot` funciona em `pipeline/llm.py`. Reprovar aqui mandaria consertar o
        que não está quebrado — por isso a lista é importada de lá, e não copiada."""
        problemas = env_check.conferir(
            {
                "LLM_PROVIDER": "moonshot",
                "LLM_MODEL": "kimi-k2.6",
                "LLM_API_KEY": CHAVE_MOONSHOT,
                "REPLAY_MODE": "1",
                "LLM_FAKE": "1",
                "AUTH_ENABLED": "false",
                "DATABASE_URL": "sqlite:///x.db",
            }
        )
        assert not [p for p in problemas if p.nome == "LLM_PROVIDER"]

    def test_chave_ambigua_nao_vira_erro_de_provedor(self):
        """`sk-` é da Moonshot, da DeepSeek e da OpenAI. Chutar aqui criaria um erro
        falso — e um erro falso num conferidor é o que faz parar de se olhar para ele."""
        assert env_check.impressao(CHAVE_MOONSHOT)[0] == ""


class TestRealoca:
    def test_move_a_credencial_para_a_variavel_de_chave(self):
        novos, feitos = env_check.realocar({"LLM_MODEL_ALT": CHAVE_GOOGLE_ESTUDIO})
        assert novos["LLM_API_KEY_ALT"] == CHAVE_GOOGLE_ESTUDIO
        assert novos["LLM_MODEL_ALT"] == ""
        assert novos["LLM_PROVIDER_ALT"] == "gemini", "o prefixo diz de quem é a chave"
        assert any("LLM_MODEL_ALT" in f for f in feitos)

    def test_nunca_sobrescreve_uma_chave_que_ja_existe(self):
        """Trocaria um problema visível por um invisível, e o invisível é muito pior:
        ninguém percebe que a chave certa sumiu até a chamada falhar."""
        novos, feitos = env_check.realocar(
            {"LLM_MODEL_ALT": CHAVE_GOOGLE_ESTUDIO, "LLM_API_KEY_ALT": CHAVE_ANTHROPIC}
        )
        assert novos["LLM_API_KEY_ALT"] == CHAVE_ANTHROPIC
        assert novos["LLM_MODEL_ALT"] == CHAVE_GOOGLE_ESTUDIO, "não apagou o que não moveu"
        assert any("não movida" in f for f in feitos)

    def test_nome_de_modelo_de_verdade_fica_onde_esta(self):
        novos, feitos = env_check.realocar({"LLM_MODEL_ALT": "gemini-2.5-flash"})
        assert novos["LLM_MODEL_ALT"] == "gemini-2.5-flash"
        assert feitos == []


class TestEscrita:
    def test_variavel_desconhecida_e_preservada(self):
        """Descartar o que não se conhece quebraria o sistema em silêncio."""
        texto = env_check.montar({"UMA_COISA_QUALQUER": "42"}, com_valores=True)
        assert "UMA_COISA_QUALQUER=42" in texto
        assert "OUTRAS" in texto

    def test_o_exemplo_sai_sem_nenhum_valor_de_segredo(self):
        """`.env.example` vai para o Git. Um valor de chave aqui é o vazamento clássico."""
        texto = env_check.montar(
            {
                "LLM_API_KEY": CHAVE_MOONSHOT,
                "SEARCH_API_KEY": "tvly-" + "x" * 30,
                "JWT_SECRET": "z" * 64,
                "UMA_COISA_QUALQUER": "42",
            },
            com_valores=False,
        )
        assert CHAVE_MOONSHOT not in texto
        assert "tvly-" not in texto
        assert "z" * 64 not in texto
        assert "LLM_API_KEY=" in texto, "a variável tem de aparecer, vazia"
        # E o que é desconhecido não vaza para o exemplo: pode ser segredo.
        assert "UMA_COISA_QUALQUER" not in texto

    def test_o_arquivo_gerado_le_de_volta_igual(self):
        """Ida e volta: montar → ler devolve os mesmos valores conhecidos."""
        original = {
            "AUTH_ENABLED": "false",
            "REPLAY_MODE": "1",
            "LLM_FAKE": "1",
            "DATABASE_URL": "sqlite:///./data/dev.db",
            "LLM_PROVIDER": "kimi",
            "LLM_MODEL": "kimi-k2.6",
            "LLM_API_KEY": CHAVE_MOONSHOT,
            "LLM_API_BASE": "https://api.moonshot.ai/v1",
        }
        texto = env_check.montar(original, com_valores=True)
        import tempfile

        with tempfile.TemporaryDirectory() as pasta:
            alvo = Path(pasta) / ".env"
            alvo.write_text(texto, encoding="utf-8")
            relido = env_check.ler(alvo)
        for nome, valor in original.items():
            assert relido[nome] == valor, nome


class TestLeitura:
    @pytest.mark.parametrize(
        ("linha", "esperado"),
        [
            ("A=1", ("A", "1")),
            ("export A=1", ("A", "1")),
            ('A="com aspas"', ("A", "com aspas")),
            ("A='simples'", ("A", "simples")),
            ("  A = 1  ", ("A", "1")),
            ("A=", ("A", "")),
        ],
    )
    def test_formas_aceitas(self, tmp_path: Path, linha: str, esperado: tuple[str, str]):
        alvo = tmp_path / ".env"
        alvo.write_text(f"# comentário\n\n{linha}\n", encoding="utf-8")
        nome, valor = esperado
        assert env_check.ler(alvo).get(nome) == valor


class TestOArquivoDeVerdade:
    """O `.env.example` do repositório — não o que `montar` devolve, o que está no disco.

    É o único dos dois que vai para o GitHub, e é onde um vazamento custaria caro. O teste
    olha o arquivo real justamente porque alguém pode editá-lo à mão depois.
    """

    def test_o_exemplo_versionado_nao_tem_credencial(self):
        exemplo = RAIZ / ".env.example"
        assert exemplo.exists(), ".env.example sumiu — ele é a documentação da configuração"
        for numero, linha in enumerate(exemplo.read_text(encoding="utf-8").splitlines(), 1):
            crua = linha.strip()
            if not crua or crua.startswith("#") or "=" not in crua:
                continue
            nome, _, valor = crua.partition("=")
            assert not env_check.parece_segredo(valor.strip()), (
                f".env.example:{numero}: {nome.strip()} tem valor com formato de "
                f"credencial. O exemplo é versionado; valor de chave não entra nele."
            )

    def test_o_exemplo_cobre_toda_variavel_conhecida(self):
        """Uma variável que existe no mapa e não no exemplo é uma variável que ninguém
        que clonar o repositório vai saber que precisa preencher.

        O teste olha o **nome**, e não a definição: no exemplo quase tudo está sem valor,
        e sem valor a linha sai comentada de propósito (ver `TestVaziaNaoEAusente`).
        """
        texto = (RAIZ / ".env.example").read_text(encoding="utf-8")
        nomes = {
            linha.lstrip("#").partition("=")[0].strip()
            for linha in texto.splitlines()
            if "=" in linha
        }
        faltando = sorted(set(env_check.POR_NOME) - nomes)
        assert not faltando, f"fora do .env.example: {', '.join(faltando)}"

    def test_o_env_de_verdade_nao_tem_erro(self):
        """Se houver `.env` nesta máquina, ele tem de passar no conferidor.

        Pulado onde não há `.env` (CI, clone recém-feito) — o teste é sobre a máquina de
        quem desenvolve, e não sobre o repositório.
        """
        env = RAIZ / ".env"
        if not env.exists():
            pytest.skip("sem .env nesta máquina")
        erros = [p for p in env_check.conferir(env_check.ler(env)) if p.gravidade == "erro"]
        assert not erros, " · ".join(f"{p.nome}: {p.texto}" for p in erros)


class TestVaziaNaoEAusente:
    """**A regressão de 13/09/2026**, e ela custou 37 arquivos num commit.

    `os.environ.get("X", "padrao")` devolve `""` quando `X` existe **vazia** — o default
    não entra. Ao declarar `SEARCH_CACHE_DIR=` num `.env` onde a variável estava ausente,
    `Path("")` virou `.` e o cache de busca passou a gravar na raiz do repositório.

    Ausente e vazia não são a mesma coisa, e o arquivo gerado tem de respeitar isso.
    """

    def test_variavel_sem_valor_sai_comentada(self):
        texto = env_check.montar({"AUTH_ENABLED": "false"}, com_valores=True)
        assert "#SEARCH_CACHE_DIR=" in texto
        ativas = [linha for linha in texto.splitlines() if linha.startswith("SEARCH_CACHE_DIR=")]
        assert not ativas, "a variável sem valor não pode sair definida"

    def test_variavel_com_valor_sai_ativa(self):
        texto = env_check.montar({"SEARCH_CACHE_DIR": "data/search-cache"}, com_valores=True)
        assert "SEARCH_CACHE_DIR=data/search-cache" in texto
        assert "#SEARCH_CACHE_DIR=" not in texto

    def test_o_arquivo_gerado_nao_define_nenhuma_opcional_vazia(self):
        """A garantia geral: ler de volta o que foi escrito não traz chave com valor
        vazio. Se trouxesse, todo `os.environ.get(nome, padrao)` do projeto perderia o
        seu default de uma vez."""
        import tempfile

        texto = env_check.montar({"AUTH_ENABLED": "false", "LLM_FAKE": "1"}, com_valores=True)
        with tempfile.TemporaryDirectory() as pasta:
            alvo = Path(pasta) / ".env"
            alvo.write_text(texto, encoding="utf-8")
            relido = env_check.ler(alvo)
        vazias = sorted(nome for nome, valor in relido.items() if not valor)
        assert not vazias, f"declaradas vazias: {vazias}"

    def test_o_env_desta_maquina_nao_tem_opcional_vazia(self):
        env = RAIZ / ".env"
        if not env.exists():
            pytest.skip("sem .env nesta máquina")
        vazias = sorted(nome for nome, valor in env_check.ler(env).items() if not valor)
        assert not vazias, f"declaradas vazias no .env: {vazias}"
