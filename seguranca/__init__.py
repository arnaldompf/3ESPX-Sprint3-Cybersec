"""Camada de segurança da Sprint 3 aplicada sobre a solução SpecRadar (`fordChallenge/`).

A solução fica intocada. Tudo aqui entra **por composição**: os módulos importam a API e o
pipeline do `fordChallenge/` e acrescentam controles por cima, com testes próprios em
`tests/`. Em produção, o ponto de entrada passa a ser `seguranca.app_segura:app` (API) e
`python -m seguranca.worker_seguro` (worker), e não mais os módulos originais.

Módulos:

* `solucao`      — localiza o `fordChallenge/` e o coloca no `sys.path`;
* `segredos`     — lê segredos de arquivo (`VAR_FILE`, padrão Docker secrets);
* `app_segura`   — a API endurecida: trava de produção, rate limit com chave verificada,
                   eventos de segurança e `/metrics`;
* `metricas`     — métricas no formato Prometheus, sem dependência nova;
* `ssrf`         — bloqueio de destinos internos nas requisições do pipeline;
* `cripto_local` — AES-256-GCM para dados em repouso (arquivos, exportações, backups);
* `backup`       — backup cifrado, verificação de integridade e restauração;
* `worker_seguro`— o worker do pipeline com a proteção de SSRF ligada.
"""
