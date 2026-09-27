"""Materiality Engine (WP-34): a resposta a "e daí?", por regra.

`rules.yaml` declara as regras e os pesos — **hipótese do MVP, configuráveis**, e está
escrito assim no arquivo. `engine.py` as aplica e devolve a materialidade, as regras que
dispararam, os estados de paridade que viraram, e a posição na fila de prioridade.

Nada de LLM aqui. A pergunta "isto importa?" tem de ser respondida do mesmo jeito duas
vezes seguidas, e tem de ser possível discordar da resposta lendo uma linha de YAML.
"""
