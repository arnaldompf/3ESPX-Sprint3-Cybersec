"""O **Pesquisador**: completar a ficha de um veículo que não está no catálogo.

Até aqui o SpecRadar só sabia falar dos veículos que alguém já tinha coletado. A pergunta
que uma demonstração honesta precisa responder é outra — *"e se eu pedir um carro que não
está aí?"* — e a resposta tem de ser *"eu vou procurar, e vou te mostrar onde achei"*, e
não *"não encontrado"*.

Este pacote é o protocolo que o pesquisador humano seguiu para montar o `gabarito/`,
**escrito em código**: procurar na fonte oficial primeiro, baixar a página, achar o trecho
que diz o número, e só então registrar o valor — com a citação ao lado.

**O que ele não é.** Não é um chatbot que responde sobre carros. O modelo de linguagem
aqui lê documento baixado e devolve campos com o trecho de onde tirou cada um; ele nunca
responde de memória. E isso não é um pedido no prompt: é a arquitetura. O valor só entra na
ficha depois de passar pelo grounding contra o **texto salvo da fonte**, que é o mesmo
portão de `pipeline/ground.py` que o resto do pipeline já atravessa. Um número que o modelo
inventar não terá trecho, e será descartado antes de virar ficha.

O que muda em relação a "buscar na web":

======================  =========================  ===================================
                        busca genérica             o Pesquisador
======================  =========================  ===================================
pergunta                uma, aberta                **58 campos**, fechados
sucesso                 uma resposta boa           **cobertura**, campo a campo
fonte                   a melhor que aparecer      **tier**: oficial → FIPE/PBE → imprensa
evidência               o snippet basta            **trecho verbatim no texto salvo**
parada                  quando responde            quando as lacunas param de fechar
======================  =========================  ===================================

A consequência prática está no planejador: ele não faz **uma** pergunta ao buscador — faz
uma consulta **por tier**, e depois fecha as lacunas com consultas dirigidas ao campo que
falta.
"""
