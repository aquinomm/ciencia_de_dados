# Berka: viabilidade da transição ativo → inativo

**Status da branch `berka-temporal`: investigação encerrada para dormancy/churn como alvo preditivo principal.** Os resultados abaixo permanecem como registro do experimento e não oferecem suporte suficiente para manter essa direção como eixo preditivo do projeto. Isso não invalida o Berka como dataset nem define o próximo alvo do projeto; veja o [fechamento no README](../README.md#conclusão-da-branch-e-direção-ainda-em-aberto).

**Resultado principal: categoria B — há algum sinal, mas poucos eventos; a tarefa é apenas exploratória.** Em H=90/A=30, o treino contém 5 episódios em 4 contas (todas as transações) ou 15 episódios em 14 contas (sem rotineiros). O HGB selecionado alcança AP 0,244 [0,149; 0,453] e 0,143 [0,082; 0,257]. O ganho sobre frequência é incerto no primeiro escopo e positivo no segundo, condicionado a esse ajuste; a estabilidade histórica não se sustenta. H=180 com todas as transações é categoria C: zero eventos de treino e nenhum modelo supervisionado ajustável. Esses dados não sustentam uma parte preditiva principal apresentada como robusta ou generalizável.

## Especificação prospectiva e escopo

Este experimento foi definido prospectivamente para contas ativas, sem reutilizar como evidência principal o TEST de um modelo treinado em contas já dormentes. O Berka não possui encerramento observado de relacionamento; o evento é comportamental e não significa churn contratual.

Para escopo de atividade `s`, conta `a` e snapshot T, seja `L_s(a,T)` a data da última atividade qualificante **conhecida em T** e `r_s(a,T)=T−L_s(a,T)` a recência, em dias. A população principal é:

`E_s(a,T; A=30) = conta aberta em T ∧ histórico observável >=180 dias ∧ 0<=r_s(a,T)<=30`.

A elegibilidade é computada **antes de consultar o target**, em treino, validação e TEST. Uma atividade exatamente em T−30 qualifica a conta, conforme o limite inclusivo pedido. As features de contagem em 30 dias usam `(T−30,T]`; portanto, esse caso de fronteira pode ter contagem 30d zero mesmo sendo elegível. Contas sem atividade conhecida não são elegíveis.

Somente nessa população:

`y_s(a,T,H) = 1{nenhuma atividade qualificante em (T,T+H]}`.

H=90 é principal; 120 e 180 são sensibilidades. A=15 e A=60 também são sensibilidades pré-especificadas; A=30 permanece principal, independentemente das métricas. Como A<H, os positivos ainda não tinham completado H dias de silêncio em T: esse marco é atingido no futuro. O target exige ausência durante **todo o horizonte imediatamente posterior a T**. Não mede a ocorrência de qualquer gap de H dias dentro de uma janela arbitrária, nem exige que a conta permaneça inativa para sempre. Reativação depois de T+H é possível.

São mantidos ambos os escopos: `all_transactions` (qualquer lançamento) e `excluding_routine` (exclui `UROK`, `SLUZBY`, `SANKC. UROK`). O filtro não prova iniciativa do titular, pois outras operações podem ser automáticas.

## Reutilização técnica e independência do experimento

O trabalho foi feito exclusivamente na branch `berka-temporal`, sem commit, merge, push ou checkout. As alterações locais anteriores foram revisadas: reutilizamos leitura/cache verificável, 36 features históricas, purge, métricas ponderadas e bootstrap já testados. **Não reutilizamos modelos, thresholds ou escolhas de hiperparâmetros ajustados na população geral.**

A entrada `predict_activity_transition.py` tem configuração própria, nova seed, filtragem prospectiva e auditoria de episódios. A rotina compartilhada de modelagem ganhou um baseline de frequência opcional; seu comportamento anterior continua sendo o padrão para o experimento antigo. A documentação anterior foi marcada como histórica/experimental. A interpretação permanece em Markdown, não em strings analíticas no código.

Os períodos cronológicos são pré-especificados por anos: validação nominal a partir de **1997-01-01**, TEST a partir de **1998-01-01**. Não se aplica a alteração para abril usada na rodada anterior para obter positivos no treino. Treinos vazios de positivos são resultado da avaliação de viabilidade, não motivo para mudar cortes. O TEST de 1998 já foi usado em análises anteriores deste projeto; esta avaliação não é uma confirmação externa em dados nunca examinados. O protocolo e as novas escolhas são congelados antes da leitura das métricas deste novo TEST.

## Dados, calendário e rigor temporal

Cache financeiro verificado: 4.500 contas, 1.056.320 transações de 1993-01-01 a 1998-12-31, incluindo `amount` e `balance`, extraídos do banco público CTU Financial. Proveniência, consultas e SHA-256 são preservados no manifesto. Não houve nova transformação da classe para aumentar artificialmente os positivos.

Snapshots no fim de cada mês (`ME`), configuráveis. O início observável de cada conta é `max(abertura, início global da observação)`. São exigidos 180 dias até T. O funil registra exclusões por histórico, falta de atividade, recência acima de A e censura à direita. Nenhum snapshot com `T+H > fim da base` recebe rótulo.

Regra de purge: `label_end_train < validation_start` e `label_end_validation < test_start`. Nem o primeiro dia do período seguinte participa do target anterior. O TEST usa os snapshots mais recentes com horizonte completo. A mesma conta pode aparecer em períodos diferentes, mas o mesmo episódio positivo não pode atravessar splits; isso é verificado explicitamente.

Features somente até T: idade da conta/histórico observável; recência; contagem acumulada; contagens e dias ativos; valores e entradas/saídas nas janelas 30/90/180; gaps encerrados até T; último saldo e sua idade; média/desvio dos saldos em 180 dias; mudança entre os últimos dois blocos de 30 dias; dispersão e tendência nos seis blocos anteriores. O saldo inclui todos os lançamentos disponíveis em T, mesmo no escopo sem rotineiros. Não acrescentamos variáveis de calendário ou outras famílias de atributos para procurar uma configuração favorável em uma amostra de eventos pequena.

Nenhum identificador, `episode_id`, target, marco futuro ou data final de uma conta entra no modelo. Há lista explícita de features. A recência é truncada pela elegibilidade; qualquer poder preditivo é interpretado **dentro de [0,A]**, não como descoberta de que contas já dormentes continuam dormentes. Imputação, padronização e histogramas são ajustados somente no TRAIN.

## O que conta como evento

Um snapshot positivo não é necessariamente um novo evento. Identificamos um episódio de silêncio pelo par **(account_id, L_s(a,T))**: dois snapshots positivos da mesma conta, sem atividade intermediária, têm a mesma última atividade e pertencem ao mesmo episódio. Uma reativação seguida por novo silêncio produz outro episódio. Transações no mesmo dia não criam episódios adicionais.

O marco de H dias de silêncio é `L+H`, sempre posterior a T na população elegível. As tabelas distinguem:

- snapshots positivos;
- episódios distintos desduplicados;
- contas positivas distintas;
- fração dos snapshots positivos pertencentes a contas com mais de um snapshot positivo;
- redundância além do primeiro snapshot por conta e por episódio;
- episódios representados em cada mês de snapshot e episódios atribuídos uma única vez ao mês do marco `L+H`.

**“Episódios distintos” não significa independência estatística comprovada.** Uma conta pode ter episódios recorrentes e contas distintas podem compartilhar efeitos de calendário. A unidade de reamostragem continua sendo a conta. Contagens mensais de episódios representados não devem ser somadas como se cada representação fosse uma entrada nova.

Também fazemos um censo descritivo dos gaps longos, incluindo episódios que o calendário mensal não captura. Para um último dia ativo L e próximo dia ativo N, um T positivo e elegível pode existir somente em:

`[max(L, início_observável+180), min(L+A, N−H−1 dia, fim_observável−H)]`.

No episódio terminal, N é representado apenas para esse cálculo como `fim_observável+1 dia`, sem inventar uma transação. A janela precisa ser não vazia. O censo conta episódios que admitiriam ao menos um snapshot diário elegível; depois informa quais possuem um T no calendário mensal. Essa análise descritiva usa as datas dos gaps, fica separada das features e não seleciona modelos. O conjunto de episódios capturados e sua contagem de snapshots são conferidos contra o dataset efetivamente construído.

## Baselines, modelos e escolha antes do TEST

| Família | Especificação | Ajuste/seleção |
|---|---|---|
| Prevalência | Probabilidade constante igual à prevalência do TRAIN elegível | Referência probabilística |
| Recência | Logística univariada em `log1p(recency_days)`, C=1 | Ajustada apenas no TRAIN ativo |
| Frequência | Logística univariada em `log1p(count_30d)`, C=1 | Ajustada apenas no TRAIN ativo |
| Logística | 36 features, imputação por mediana/indicadores, padronização, L2 | C em {0,1; 1} |
| HistGradientBoosting | 150 iterações, learning_rate=0,05, early_stopping=False | (folhas, mínimo por folha, L2) em {(7,30,10), (15,60,30)} |

São sete candidatos por combinação. Não há SMOTE, pesos de classe ou busca adicional depois de observar TEST. A distribuição de validation/test é preservada. Seleção de hiperparâmetros e família por maior AP na validação; empate por menor Brier e ordem fixa. Threshold por F2 máximo na validação, desempate pelo maior threshold. F2 é uma convenção exploratória explícita, sem interpretação de custo de negócio.

Sem duas classes no TRAIN, apenas a prevalência é disponibilizada; as demais famílias são marcadas `unavailable_single_class_train`, sem lhes atribuir desempenho de um dummy. Sem duas classes na validação, escolhe-se a prevalência, pois a comparação por AP não é identificável. Sem positivos na validação, o threshold produz nenhuma previsão positiva. Não há retreino em TRAIN+VALIDATION nem reajuste do threshold no TEST.

AP (Average Precision não interpolada) é a métrica principal, com lift AP/prevalência do mesmo conjunto. Também são reportados ROC-AUC, precision, recall, F1, F2, MCC, balanced accuracy, Brier e matriz de confusão. Probabilidades médias e curvas de calibração complementam Brier, que isoladamente pode parecer pequeno apenas pela raridade do evento. Modelos não treináveis têm métricas ausentes, não zero.

## Incerteza, estabilidade e auditoria

Bootstrap percentil IC95%, 1.000 réplicas, seed **20260921**, reamostrando contas com reposição e preservando seus snapshots em bloco. Réplicas sem classes suficientes são omitidas somente nas métricas não identificáveis, com quantidade válida registrada. As mesmas reamostragens sustentam diferenças pareadas entre cada modelo e os três baselines.

Os ICs são condicionais ao ajuste e à seleção congelados, não incluem incerteza de escolha ou mudanças de regime e não corrigem multiplicidade entre comparações. Com poucas contas positivas, sequer um IC estreito em alguma métrica elimina a fragilidade de amostra. Avalia-se também detecção de pelo menos um snapshot por episódio, sem contar duplicatas como acertos independentes.

Dois cortes expanding anteriores ao TEST, na população principal A=30, avaliam janeiro–março e abril–junho de 1997. Cada um usa validação nominal iniciando nove meses antes de sua avaliação e purge por H. Todos os labels desses cortes terminam antes de 1998. Cada janela seleciona apenas na própria validação; não se escolhe o corte mais favorável.

A auditoria inclui invariância de features e elegibilidade à remoção de todas as transações futuras, contagem direta dos targets, disjunção de episódios entre splits, inspeção dos nomes de entrada dos estimadores e replay das previsões dos modelos serializados. Os testes incluem casos de fronteira T, T−A e T+H, episódios repetidos, reativação, censura, histórico mínimo, treino fora da população, ausência de classes e isolamento do TEST.

## Reprodução e artefatos

Na branch `berka-temporal`, com as dependências fixadas em `requirements.txt`:

```powershell
python -X utf8 -m dataset_pk99.predict_activity_transition --source cache --output-dir outputs/berka/activity_transition/reproduction --previous-run outputs/berka/inactivity_prediction/validated
python -X utf8 -m unittest discover -s tests -v
python -m compileall -q dataset_pk99 tests
```

Use `--source database` se não tiver o cache financeiro. `--previous-run` é opcional e acrescenta somente a comparação diagnóstica final. Não lê modelos anteriores. A execução de referência é `outputs/berka/activity_transition/prespecified_v1/`; nenhuma saída anterior é sobrescrita.

| Artefato | Conteúdo |
|---|---|
| `protocol.json`, `run_manifest.json`, `frozen_selection.json` | Configuração, versão do experimento, branch/HEAD, hashes de fontes/dados/saídas, versões, sementes e congelamento |
| `eligibility.csv`, `population_audit.csv`, `split_event_counts.csv` | Funil, população completa e usada, snapshots/episódios/contas e repetição |
| `episodes.csv`, `snapshot_period_events.csv`, `event_crossing_periods.csv` | Episódios desduplicados e atribuição temporal |
| `splits.csv`, `purges.csv` | Datas exatas e perdas por purge |
| `validation_candidates.json`, `validation_metrics.csv` | Candidatos e decisões sem TEST |
| `test_metrics.csv`, `test_confidence_intervals.csv`, `paired_baseline_differences.csv` | Métricas e incerteza agrupada |
| `test_monthly_metrics.csv`, `common_calendar_metrics.csv`, `episode_detection.csv` | Calendário, comparabilidade dos H e detecção de episódios |
| `stability_*` | Métricas, eventos, splits, escolhas, previsões e auditoria dos cortes anteriores |
| `*_leakage_audit.json`, `model_replay_audit.json` | Verificações temporais, elegibilidade, entradas e reprodutibilidade |
| Por combinação | Features elegíveis, labels, censo de episódios, modelos, thresholds, previsões, draws do bootstrap, PR/ROC e calibração |

## Resultados

As contagens de eventos foram produzidas antes do ajuste de qualquer modelo. Os resultados abaixo são exclusivamente deste novo treinamento na população ativa.

Nas tabelas, `—` significa métrica não identificável ou modelo indisponível, não desempenho zero. Contas positivas são distintas dentro do conjunto indicado; não se deve somar contagens de contas de splits diferentes. A proporção “positivos em contas repetidas” inclui todos os snapshots das contas com mais de um positivo; a redundância por episódio conta somente snapshots além do primeiro representante de cada episódio.

### Datas efetivas, iguais nos dois escopos e nas elegibilidades

| H | Split | Intervalo de T | Dias dos targets | Gap de T / último evento ao próximo período |
|---|---|---|---|---|
| 90 | train | 1993-06-30 a 1996-09-30 | 1993-07-01 a 1996-12-29 | 93 / 3 |
| 90 | validation | 1997-01-31 a 1997-09-30 | 1997-02-01 a 1997-12-29 | 93 / 3 |
| 90 | test | 1998-01-31 a 1998-09-30 | 1998-02-01 a 1998-12-29 | — / — |
| 120 | train | 1993-06-30 a 1996-08-31 | 1993-07-01 a 1996-12-29 | 123 / 3 |
| 120 | validation | 1997-01-31 a 1997-08-31 | 1997-02-01 a 1997-12-29 | 123 / 3 |
| 120 | test | 1998-01-31 a 1998-08-31 | 1998-02-01 a 1998-12-29 | — / — |
| 180 | train | 1993-06-30 a 1996-06-30 | 1993-07-01 a 1996-12-27 | 185 / 5 |
| 180 | validation | 1997-01-31 a 1997-06-30 | 1997-02-01 a 1997-12-27 | 185 / 5 |
| 180 | test | 1998-01-31 a 1998-06-30 | 1998-02-01 a 1998-12-27 | — / — |


### Funil de elegibilidade principal (A=30)

| Atividade | H | Candidatos | Histórico insuficiente | Inativos em T | Censura | Elegíveis antes do purge |
|---|---|---|---|---|---|---|
| Todas | 90 | 185615 | 26608 | 466 | 13383 | 145158 |
| Todas | 120 | 185615 | 26608 | 466 | 17863 | 140678 |
| Todas | 180 | 185615 | 26608 | 466 | 26823 | 131718 |
| Sem rotineiros | 90 | 185615 | 26608 | 825 | 13359 | 144823 |
| Sem rotineiros | 120 | 185615 | 26608 | 825 | 17819 | 140363 |
| Sem rotineiros | 180 | 185615 | 26608 | 825 | 26750 | 131432 |


### Purge da população principal

| Atividade | H | Fronteira | Datas T removidas | Snapshots |
|---|---|---|---|---|
| Todas | 90 | before_validation | 1996-10-31 a 1996-12-31 | 8339 |
| Todas | 90 | before_test | 1997-10-31 a 1997-12-31 | 11915 |
| Todas | 120 | before_validation | 1996-09-30 a 1996-12-31 | 10914 |
| Todas | 120 | before_test | 1997-09-30 a 1997-12-31 | 15727 |
| Todas | 180 | before_validation | 1996-07-31 a 1996-12-31 | 15721 |
| Todas | 180 | before_test | 1997-07-31 a 1997-12-31 | 23135 |
| Sem rotineiros | 90 | before_validation | 1996-10-31 a 1996-12-31 | 8313 |
| Sem rotineiros | 90 | before_test | 1997-10-31 a 1997-12-31 | 11887 |
| Sem rotineiros | 120 | before_validation | 1996-09-30 a 1996-12-31 | 10877 |
| Sem rotineiros | 120 | before_test | 1997-09-30 a 1997-12-31 | 15690 |
| Sem rotineiros | 180 | before_validation | 1996-07-31 a 1996-12-31 | 15664 |
| Sem rotineiros | 180 | before_test | 1997-07-31 a 1997-12-31 | 23074 |


### Contagem real de episódios capturados, antes do purge, A=30

| Atividade | H | Snapshots positivos | Episódios distintos | Contas positivas | Episódios possíveis em calendário diário | Não capturados mensalmente |
|---|---|---|---|---|---|---|
| Todas | 90 | 47 | 37 | 28 | 37 | 0 |
| Todas | 120 | 35 | 29 | 26 | 29 | 0 |
| Todas | 180 | 24 | 21 | 21 | 22 | 1 |
| Sem rotineiros | 90 | 79 | 78 | 61 | 87 | 9 |
| Sem rotineiros | 120 | 60 | 59 | 50 | 65 | 6 |
| Sem rotineiros | 180 | 37 | 36 | 34 | 42 | 6 |


### Auditoria por split da população principal

| Atividade | H | Split | Snapshots | Contas | Positivos | Prevalência | Episódios | Contas positivas | Positivos em contas repetidas | Redundância por episódio |
|---|---|---|---|---|---|---|---|---|---|---|
| Todas | 90 | train | 54535 | 2577 | 6 | 0.0110% | 5 | 4 | 66.6667% | 16.6667% |
| Todas | 90 | validation | 31074 | 3817 | 8 | 0.0257% | 6 | 6 | 50.0000% | 25.0000% |
| Todas | 90 | test | 39295 | 4492 | 22 | 0.0560% | 17 | 14 | 63.6364% | 22.7273% |
| Todas | 120 | train | 51960 | 2461 | 3 | 0.0058% | 3 | 3 | 0.0000% | 0.0000% |
| Todas | 120 | validation | 27262 | 3752 | 6 | 0.0220% | 5 | 5 | 33.3333% | 16.6667% |
| Todas | 120 | test | 34815 | 4491 | 13 | 0.0373% | 12 | 12 | 15.3846% | 7.6923% |
| Todas | 180 | train | 47153 | 2252 | 0 | 0.0000% | 0 | 0 | — | — |
| Todas | 180 | validation | 19854 | 3602 | 2 | 0.0101% | 2 | 2 | 0.0000% | 0.0000% |
| Todas | 180 | test | 25855 | 4490 | 8 | 0.0309% | 7 | 7 | 25.0000% | 12.5000% |
| Sem rotineiros | 90 | train | 54456 | 2577 | 15 | 0.0275% | 15 | 14 | 13.3333% | 0.0000% |
| Sem rotineiros | 90 | validation | 31002 | 3817 | 14 | 0.0452% | 14 | 14 | 0.0000% | 0.0000% |
| Sem rotineiros | 90 | test | 39165 | 4491 | 34 | 0.0868% | 33 | 28 | 35.2941% | 2.9412% |
| Sem rotineiros | 120 | train | 51892 | 2461 | 12 | 0.0231% | 12 | 12 | 0.0000% | 0.0000% |
| Sem rotineiros | 120 | validation | 27199 | 3752 | 10 | 0.0368% | 10 | 10 | 0.0000% | 0.0000% |
| Sem rotineiros | 120 | test | 34705 | 4489 | 24 | 0.0692% | 23 | 22 | 16.6667% | 4.1667% |
| Sem rotineiros | 180 | train | 47105 | 2252 | 6 | 0.0127% | 6 | 6 | 0.0000% | 0.0000% |
| Sem rotineiros | 180 | validation | 19815 | 3602 | 5 | 0.0252% | 5 | 5 | 0.0000% | 0.0000% |
| Sem rotineiros | 180 | test | 25774 | 4487 | 10 | 0.0388% | 9 | 9 | 20.0000% | 10.0000% |


### AP no TEST e IC95% por conta, A=30

| Atividade | H | Modelo | Escolhido na validação | AP [IC95%] | AP/prevalência | ROC-AUC | Brier |
|---|---|---|---|---|---|---|---|
| Todas | 90 | Prevalência | não | 0.0006 [0.0003; 0.0009] | 1.00 | 0.5000 | 0.000560 |
| Todas | 90 | Recência | não | 0.1378 [0.0476; 0.2798] | 246.05 | 0.8380 | 0.000553 |
| Todas | 90 | Frequência | não | 0.1162 [0.0314; 0.2555] | 207.63 | 0.9920 | 0.000543 |
| Todas | 90 | Logística | não | 0.1078 [0.0442; 0.2425] | 192.55 | 0.9938 | 0.001110 |
| Todas | 90 | HGB | sim | 0.2443 [0.1495; 0.4531] | 436.31 | 0.9508 | 0.000558 |
| Todas | 120 | Prevalência | não | 0.0004 [0.0002; 0.0006] | 1.00 | 0.5000 | 0.000373 |
| Todas | 120 | Recência | sim | 0.0362 [0.0083; 0.1639] | 96.96 | 0.8041 | 0.000373 |
| Todas | 120 | Frequência | não | 0.0296 [0.0089; 0.1436] | 79.30 | 0.9902 | 0.000369 |
| Todas | 120 | Logística | não | 0.0573 [0.0127; 0.2198] | 153.44 | 0.9053 | 0.001080 |
| Todas | 120 | HGB | não | 0.0630 [0.0182; 0.1817] | 168.65 | 0.9550 | 0.000373 |
| Todas | 180 | Prevalência | sim | 0.0003 [0.0001; 0.0006] | 1.00 | 0.5000 | 0.000309 |
| Todas | 180 | Recência | não | indisponível | — | — | — |
| Todas | 180 | Frequência | não | indisponível | — | — | — |
| Todas | 180 | Logística | não | indisponível | — | — | — |
| Todas | 180 | HGB | não | indisponível | — | — | — |
| Sem rotineiros | 90 | Prevalência | não | 0.0009 [0.0005; 0.0012] | 1.00 | 0.5000 | 0.000868 |
| Sem rotineiros | 90 | Recência | não | 0.0006 [0.0003; 0.0009] | 0.63 | 0.2226 | 0.000868 |
| Sem rotineiros | 90 | Frequência | não | 0.0228 [0.0108; 0.0713] | 26.27 | 0.9554 | 0.000861 |
| Sem rotineiros | 90 | Logística | não | 0.0658 [0.0266; 0.1781] | 75.78 | 0.9592 | 0.001137 |
| Sem rotineiros | 90 | HGB | sim | 0.1433 [0.0821; 0.2571] | 165.10 | 0.9919 | 0.000812 |
| Sem rotineiros | 120 | Prevalência | não | 0.0007 [0.0004; 0.0010] | 1.00 | 0.5000 | 0.000691 |
| Sem rotineiros | 120 | Recência | não | 0.0179 [0.0025; 0.0941] | 25.82 | 0.7657 | 0.000691 |
| Sem rotineiros | 120 | Frequência | não | 0.0212 [0.0070; 0.0943] | 30.70 | 0.9580 | 0.000687 |
| Sem rotineiros | 120 | Logística | sim | 0.0515 [0.0218; 0.1465] | 74.49 | 0.9496 | 0.000910 |
| Sem rotineiros | 120 | HGB | não | 0.1575 [0.0616; 0.3694] | 227.69 | 0.9817 | 0.000658 |
| Sem rotineiros | 180 | Prevalência | não | 0.0004 [0.0002; 0.0007] | 1.00 | 0.5000 | 0.000388 |
| Sem rotineiros | 180 | Recência | não | 0.0003 [0.0001; 0.0010] | 0.88 | 0.2470 | 0.000388 |
| Sem rotineiros | 180 | Frequência | sim | 0.0091 [0.0029; 0.0170] | 23.53 | 0.9736 | 0.000387 |
| Sem rotineiros | 180 | Logística | não | 0.0028 [0.0007; 0.0101] | 7.30 | 0.8544 | 0.000517 |
| Sem rotineiros | 180 | HGB | não | 0.0346 [0.0117; 0.1149] | 89.21 | 0.9902 | 0.000387 |


### TEST no threshold congelado, A=30

| Atividade | H | Modelo | Threshold | Precision | Recall | F1 | F2 | TN / FP / FN / TP |
|---|---|---|---|---|---|---|---|---|
| Todas | 90 | Prevalência | 0.0001100 | 0.0006 | 1.0000 | 0.0011 | 0.0028 | 0 / 39273 / 0 / 22 |
| Todas | 90 | Recência | 0.0136636 | 0.5000 | 0.1818 | 0.2667 | 0.2083 | 39269 / 4 / 18 / 4 |
| Todas | 90 | Frequência | 0.0709922 | 0.5000 | 0.1818 | 0.2667 | 0.2083 | 39269 / 4 / 18 / 4 |
| Todas | 90 | Logística | 0.0385524 | 0.1905 | 0.5455 | 0.2824 | 0.3974 | 39222 / 51 / 10 / 12 |
| Todas | 90 | HGB | 0.0012091 | 0.2500 | 0.3636 | 0.2963 | 0.3333 | 39249 / 24 / 14 / 8 |
| Todas | 120 | Prevalência | 0.0000577 | 0.0004 | 1.0000 | 0.0007 | 0.0019 | 0 / 34802 / 0 / 13 |
| Todas | 120 | Recência | 0.0020431 | 0.1667 | 0.0769 | 0.1053 | 0.0862 | 34797 / 5 / 12 / 1 |
| Todas | 120 | Frequência | 0.0610828 | 0.1667 | 0.0769 | 0.1053 | 0.0862 | 34797 / 5 / 12 / 1 |
| Todas | 120 | Logística | 0.0032777 | 0.0400 | 0.6154 | 0.0751 | 0.1587 | 34610 / 192 / 5 / 8 |
| Todas | 120 | HGB | 0.0004484 | 0.1316 | 0.3846 | 0.1961 | 0.2778 | 34769 / 33 / 8 / 5 |
| Todas | 180 | Prevalência | 0.0000000 | 0.0003 | 1.0000 | 0.0006 | 0.0015 | 0 / 25847 / 0 / 8 |
| Todas | 180 | Recência | — | — | — | — | — | — / — / — / — |
| Todas | 180 | Frequência | — | — | — | — | — | — / — / — / — |
| Todas | 180 | Logística | — | — | — | — | — | — / — / — / — |
| Todas | 180 | HGB | — | — | — | — | — | — / — / — / — |
| Sem rotineiros | 90 | Prevalência | 0.0002755 | 0.0009 | 1.0000 | 0.0017 | 0.0043 | 0 / 39131 / 0 / 34 |
| Sem rotineiros | 90 | Recência | 0.0002578 | 0.0009 | 1.0000 | 0.0017 | 0.0043 | 0 / 39131 / 0 / 34 |
| Sem rotineiros | 90 | Frequência | 0.0441887 | 0.2000 | 0.0294 | 0.0513 | 0.0355 | 39127 / 4 / 33 / 1 |
| Sem rotineiros | 90 | Logística | 0.0536952 | 0.0839 | 0.3824 | 0.1376 | 0.2234 | 38989 / 142 / 21 / 13 |
| Sem rotineiros | 90 | HGB | 0.0020274 | 0.0801 | 0.7353 | 0.1445 | 0.2790 | 38844 / 287 / 9 / 25 |
| Sem rotineiros | 120 | Prevalência | 0.0002312 | 0.0007 | 1.0000 | 0.0014 | 0.0034 | 0 / 34681 / 0 / 24 |
| Sem rotineiros | 120 | Recência | 0.0003879 | 0.2000 | 0.0417 | 0.0690 | 0.0495 | 34677 / 4 / 23 / 1 |
| Sem rotineiros | 120 | Frequência | 0.0364268 | 0.2000 | 0.0417 | 0.0690 | 0.0495 | 34677 / 4 / 23 / 1 |
| Sem rotineiros | 120 | Logística | 0.0516862 | 0.0538 | 0.2083 | 0.0855 | 0.1323 | 34593 / 88 / 19 / 5 |
| Sem rotineiros | 120 | HGB | 0.0023117 | 0.0472 | 0.5000 | 0.0863 | 0.1714 | 34439 / 242 / 12 / 12 |
| Sem rotineiros | 180 | Prevalência | 0.0001274 | 0.0004 | 1.0000 | 0.0008 | 0.0019 | 0 / 25764 / 0 / 10 |
| Sem rotineiros | 180 | Recência | 0.0001941 | 0.0004 | 1.0000 | 0.0008 | 0.0019 | 0 / 25764 / 0 / 10 |
| Sem rotineiros | 180 | Frequência | 0.0281209 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 25759 / 5 / 10 / 0 |
| Sem rotineiros | 180 | Logística | 0.0088025 | 0.0049 | 0.1000 | 0.0093 | 0.0204 | 25560 / 204 / 9 / 1 |
| Sem rotineiros | 180 | HGB | 0.0009719 | 0.0233 | 0.2000 | 0.0417 | 0.0794 | 25680 / 84 / 8 / 2 |


### Demais IC95% do HGB selecionado, H=90/A=30

| Atividade | Métrica | Estimativa [IC95%] |
|---|---|---|
| Todas | average_precision | 0.2443 [0.1495; 0.4531] |
| Todas | ap_lift | 436.3114 [254.8037; 1142.9491] |
| Todas | roc_auc | 0.9508 [0.8597; 0.9993] |
| Todas | precision | 0.2500 [0.1034; 0.4444] |
| Todas | recall | 0.3636 [0.1723; 0.6364] |
| Todas | f1 | 0.2963 [0.1363; 0.4595] |
| Todas | f2 | 0.3333 [0.1534; 0.5263] |
| Todas | brier | 0.000558 [0.000278; 0.000866] |
| Sem rotineiros | average_precision | 0.1433 [0.0821; 0.2571] |
| Sem rotineiros | ap_lift | 165.0987 [109.8711; 337.1635] |
| Sem rotineiros | roc_auc | 0.9919 [0.9862; 0.9965] |
| Sem rotineiros | precision | 0.0801 [0.0492; 0.1131] |
| Sem rotineiros | recall | 0.7353 [0.5937; 0.8750] |
| Sem rotineiros | f1 | 0.1445 [0.0912; 0.1967] |
| Sem rotineiros | f2 | 0.2790 [0.1873; 0.3595] |
| Sem rotineiros | brier | 0.000812 [0.000488; 0.001146] |


### Ganho de AP do HGB sobre os baselines, H=90/A=30

| Atividade | Baseline | Delta AP | IC95% pareado |
|---|---|---|---|
| Todas | Prevalência | 0.2437 | [0.1489; 0.4528] |
| Todas | Recência | 0.1065 | [-0.0578; 0.3415] |
| Todas | Frequência | 0.1280 | [-0.0322; 0.3670] |
| Sem rotineiros | Prevalência | 0.1425 | [0.0814; 0.2562] |
| Sem rotineiros | Recência | 0.1428 | [0.0816; 0.2565] |
| Sem rotineiros | Frequência | 0.1205 | [0.0472; 0.2329] |


### Sensibilidade: modelo escolhido na validação de cada população

| Atividade | A | H | Modelo | Positivos TEST | Episódios TEST | Contas positivas TEST | AP [IC95%] | Precision | Recall |
|---|---|---|---|---|---|---|---|---|---|
| Todas | 30 | 90 | HGB | 22 | 17 | 14 | 0.2443 [0.1495; 0.4531] | 0.2500 | 0.3636 |
| Todas | 30 | 120 | Recência | 13 | 12 | 12 | 0.0362 [0.0083; 0.1639] | 0.1667 | 0.0769 |
| Todas | 30 | 180 | Prevalência | 8 | 7 | 7 | 0.0003 [0.0001; 0.0006] | 0.0003 | 1.0000 |
| Todas | 15 | 90 | HGB | 9 | 9 | 8 | 0.1516 [0.0366; 0.4049] | 0.1562 | 0.5556 |
| Todas | 15 | 120 | HGB | 7 | 7 | 7 | 0.0626 [0.0027; 0.3386] | 0.0223 | 0.5714 |
| Todas | 15 | 180 | Prevalência | 3 | 3 | 3 | 0.0001 [0.0000; 0.0003] | 0.0000 | 0.0000 |
| Todas | 60 | 90 | HGB | 32 | 19 | 16 | 0.3393 [0.2003; 0.5827] | 0.3636 | 0.6250 |
| Todas | 60 | 120 | Recência | 22 | 13 | 13 | 0.2369 [0.1093; 0.4675] | 0.3030 | 0.4545 |
| Todas | 60 | 180 | Prevalência | 15 | 8 | 8 | 0.0006 [0.0002; 0.0010] | 0.0006 | 1.0000 |
| Sem rotineiros | 30 | 90 | HGB | 34 | 33 | 28 | 0.1433 [0.0821; 0.2571] | 0.0801 | 0.7353 |
| Sem rotineiros | 30 | 120 | Logística | 24 | 23 | 22 | 0.0515 [0.0218; 0.1465] | 0.0538 | 0.2083 |
| Sem rotineiros | 30 | 180 | Frequência | 10 | 9 | 9 | 0.0091 [0.0029; 0.0170] | 0.0000 | 0.0000 |
| Sem rotineiros | 15 | 90 | Logística | 9 | 9 | 7 | 0.2146 [0.0050; 0.5147] | 0.0638 | 0.6667 |
| Sem rotineiros | 15 | 120 | HGB | 7 | 7 | 6 | 0.0959 [0.0165; 0.2767] | 0.1200 | 0.4286 |
| Sem rotineiros | 15 | 180 | Prevalência | 3 | 3 | 3 | 0.0002 [0.0001; 0.0004] | 0.0000 | 0.0000 |
| Sem rotineiros | 60 | 90 | Logística | 62 | 38 | 33 | 0.2162 [0.1335; 0.3627] | 0.2293 | 0.5806 |
| Sem rotineiros | 60 | 120 | Recência | 40 | 26 | 25 | 0.1250 [0.0633; 0.2299] | 0.2179 | 0.4250 |
| Sem rotineiros | 60 | 180 | Recência | 18 | 10 | 10 | 0.0923 [0.0381; 0.2008] | 0.1515 | 0.2778 |


### Sensibilidade: quantidade de informação antes do purge

| Atividade | A | H | Snapshots | Positivos | Episódios | Contas positivas | Redundância por episódio |
|---|---|---|---|---|---|---|---|
| Todas | 30 | 90 | 145158 | 47 | 37 | 28 | 21.2766% |
| Todas | 30 | 120 | 140678 | 35 | 29 | 26 | 17.1429% |
| Todas | 30 | 180 | 131718 | 24 | 21 | 21 | 12.5000% |
| Todas | 15 | 90 | 144208 | 21 | 21 | 15 | 0.0000% |
| Todas | 15 | 120 | 139755 | 16 | 16 | 14 | 0.0000% |
| Todas | 15 | 180 | 130845 | 10 | 10 | 10 | 0.0000% |
| Todas | 60 | 90 | 145250 | 67 | 37 | 28 | 44.7761% |
| Todas | 60 | 120 | 140768 | 53 | 29 | 26 | 45.2830% |
| Todas | 60 | 180 | 131803 | 40 | 21 | 21 | 47.5000% |
| Sem rotineiros | 30 | 90 | 144823 | 79 | 78 | 61 | 1.2658% |
| Sem rotineiros | 30 | 120 | 140363 | 60 | 59 | 50 | 1.6667% |
| Sem rotineiros | 30 | 180 | 131432 | 37 | 36 | 34 | 2.7027% |
| Sem rotineiros | 15 | 90 | 93884 | 27 | 27 | 18 | 0.0000% |
| Sem rotineiros | 15 | 120 | 91347 | 20 | 20 | 16 | 0.0000% |
| Sem rotineiros | 15 | 180 | 86320 | 13 | 13 | 12 | 0.0000% |
| Sem rotineiros | 60 | 90 | 145060 | 138 | 78 | 61 | 43.4783% |
| Sem rotineiros | 60 | 120 | 140589 | 104 | 59 | 50 | 43.2692% |
| Sem rotineiros | 60 | 180 | 131639 | 63 | 36 | 34 | 42.8571% |


### Expanding windows, A=30; positivos/episódios/contas

| Atividade | H | Janela | TRAIN: S/E/C | Avaliação: S/E/C | AP prevalência | AP recência | AP frequência | AP logística | AP HGB | Selecionado |
|---|---|---|---|---|---|---|---|---|---|---|
| Todas | 90 | 1 | 0/0/0 | 3/3/3 | 0.0003 | — | — | — | — | Prevalência |
| Todas | 90 | 2 | 0/0/0 | 2/1/1 | 0.0002 | — | — | — | — | Prevalência |
| Todas | 120 | 1 | 0/0/0 | 2/2/2 | 0.0002 | — | — | — | — | Prevalência |
| Todas | 120 | 2 | 0/0/0 | 2/1/1 | 0.0002 | — | — | — | — | Prevalência |
| Todas | 180 | 1 | 0/0/0 | 2/2/2 | 0.0002 | — | — | — | — | Prevalência |
| Todas | 180 | 2 | 0/0/0 | 0/0/0 | — | — | — | — | — | Prevalência |
| Sem rotineiros | 90 | 1 | 2/2/2 | 6/6/6 | 0.0006 | 0.0004 | 0.0492 | 0.0055 | 0.0017 | HGB |
| Sem rotineiros | 90 | 2 | 4/4/4 | 4/4/4 | 0.0004 | 0.0004 | 0.0065 | 0.2724 | 0.1320 | HGB |
| Sem rotineiros | 120 | 1 | 2/2/2 | 5/5/5 | 0.0005 | 0.0003 | 0.0550 | 0.0061 | 0.0019 | HGB |
| Sem rotineiros | 120 | 2 | 4/4/4 | 2/2/2 | 0.0002 | 0.0002 | 0.0019 | 0.5002 | 0.1104 | HGB |
| Sem rotineiros | 180 | 1 | 2/2/2 | 5/5/5 | 0.0005 | 0.0003 | 0.0550 | 0.0044 | 0.0031 | HGB |
| Sem rotineiros | 180 | 2 | 2/2/2 | 0/0/0 | — | — | — | — | — | Frequência |


### TEST mensal: HGB H=90/A=30

| Atividade | T | Positivos | Episódios representados | Contas positivas | AP |
|---|---|---|---|---|---|
| Todas | 1998-01-31 | 6 | 6 | 6 | 0.6911 |
| Todas | 1998-02-28 | 3 | 3 | 3 | 0.3313 |
| Todas | 1998-03-31 | 4 | 4 | 4 | 0.5828 |
| Todas | 1998-04-30 | 2 | 2 | 2 | 0.1178 |
| Todas | 1998-05-31 | 2 | 2 | 2 | 0.1252 |
| Todas | 1998-06-30 | 2 | 2 | 2 | 0.2502 |
| Todas | 1998-07-31 | 1 | 1 | 1 | 0.5000 |
| Todas | 1998-08-31 | 0 | 0 | 0 | — |
| Todas | 1998-09-30 | 2 | 2 | 2 | 0.1370 |
| Sem rotineiros | 1998-01-31 | 10 | 10 | 10 | 0.3725 |
| Sem rotineiros | 1998-02-28 | 4 | 4 | 4 | 0.2674 |
| Sem rotineiros | 1998-03-31 | 5 | 5 | 5 | 0.1601 |
| Sem rotineiros | 1998-04-30 | 2 | 2 | 2 | 0.3125 |
| Sem rotineiros | 1998-05-31 | 3 | 3 | 3 | 0.1324 |
| Sem rotineiros | 1998-06-30 | 4 | 4 | 4 | 0.2931 |
| Sem rotineiros | 1998-07-31 | 2 | 2 | 2 | 0.0432 |
| Sem rotineiros | 1998-08-31 | 2 | 2 | 2 | 0.0506 |
| Sem rotineiros | 1998-09-30 | 2 | 2 | 2 | 0.0530 |


### Comparação diagnóstica com a população geral, H=90

| Atividade | Experimento | Prevalência TEST | Contas positivas TEST | AP recência | AP logística | AP HGB |
|---|---|---|---|---|---|---|
| Todas | Geral anterior | 0.3775% | 27 | 0.8224 | 0.6310 | 0.6744 |
| Sem rotineiros | Geral anterior | 0.5193% | 46 | 0.6965 | 0.4550 | 0.4735 |
| Todas | Ativa: novo treino | 0.0560% | 14 | 0.1378 | 0.1078 | 0.2443 |
| Sem rotineiros | Ativa: novo treino | 0.0868% | 28 | 0.0006 | 0.0658 | 0.1433 |

## Interpretação da quantidade de informação

Para A=30, o calendário inteiro com futuro completo contém **37/29/21 episódios** e **28/26/21 contas positivas** para H=90/120/180, com todas as transações. Sem rotineiros, contém **78/59/36 episódios** e **61/50/34 contas**. Esses horizontes são alternativas para eventos sobrepostos: **não se somam entre si** para obter mais eventos independentes. Os dois escopos também compartilham contas e transações.

Depois do purge, a união dos splits retém somente 28/20/9 episódios (23/19/9 contas) no primeiro escopo e 62/45/20 episódios (52/41/20 contas) no segundo. Em particular, o treino de H=90 possui 5 episódios de 4 contas ou 15 episódios de 14 contas. H=180, todas as transações, tem **zero** episódios de treino. Mesmo a contagem mais otimista do censo diário não resolve a escassez: para H=90/A=30 são 37/87 episódios possíveis, dos quais o calendário captura 37/78.

As 22 linhas positivas de TEST em H=90/todas representam 17 episódios em 14 contas. Cinco linhas são repetições do mesmo episódio (22,73%); 14/22 linhas (63,64%) pertencem a contas com múltiplos positivos, incluindo recorrências. Sem rotineiros, 34 linhas representam 33 episódios em 28 contas: apenas uma linha repete um episódio, mas seis contas têm dois snapshots positivos. Reduzir repetição de episódios não cria mais contas independentes para validação.

Pelo ano do marco de 90 dias sem atividade, os episódios utilizados são:

| Escopo | 1993–1994 | 1995 | 1996 / TRAIN | 1997 / VALIDATION | 1998 / TEST |
|---|---|---|---|---|---|
| Todas | 0 | 0 | 5 | 6 | 17 |
| Sem rotineiros | 0 | 2 no TRAIN | 13 | 14 | 33 |

Os arquivos mensais permitem localizar cada episódio sem somar representações repetidas. A concentração no fim da série limita a utilidade de expanding windows: os primeiros períodos praticamente não oferecem exemplos para aprender a transição.

## Quanto os modelos acrescentam aos baselines

Para H=90/A=30, HGB é escolhido na validação em ambos os escopos, usando (7 folhas, mínimo 30 por folha, L2=10). A logística seleciona C=0,1 nas combinações principais em que pode ser ajustada. Os parâmetros completos, thresholds e candidatos estão nos JSONs; não houve ajustes depois do TEST.

Com todas as transações, AP do HGB é **0,2443**, frente a 0,1378 da recência e 0,1162 da frequência. Contudo, os ganhos pareados têm IC95% **[−0,0578; 0,3415]** sobre recência e **[−0,0322; 0,3670]** sobre frequência: o ganho adicional não é convincente com essa amostra. Superar a prevalência 0,000560 é uma referência muito mais fraca do que superar os comportamentos simples.

Sem rotineiros, AP do HGB é **0,1433**, frente a 0,02281 da frequência. A diferença de **0,1205 [0,0472; 0,2329]** é positiva no bootstrap pareado, evidenciando sinal adicional nesse conjunto. Isso é condicional a um modelo treinado com 14 contas positivas, validado com 14 e testado com 28; não demonstra estabilidade nem generalização externa. A logística não tem vantagem convincente sobre frequência: diferença de AP 0,0430 [−0,0260; 0,1567].

A recência univariada, ajustada somente em contas ativas, tem AP de **0,000550**, abaixo da prevalência 0,000868, no escopo sem rotineiros/H=90. Seu coeficiente aprendido é negativo (−0,2422 para `log1p(recency)`), e o sinal muda para positivo em H=120. Isso expõe a fragilidade de inferir uma relação dentro de uma faixa truncada com poucos exemplos. Não invertemos o ranking nem trocamos a regra olhando o TEST. A recência é um baseline aprendido, não uma afirmação de monotonicidade garantida.

No threshold congelado, HGB/todas detecta **8/22** snapshots positivos com 24 falsos positivos (precision 25%, recall 36,36%). Por episódio, são 8/17 detectados ao menos uma vez. Sem rotineiros, detecta **25/34**, com **287 falsos positivos** (precision 8,01%, recall 73,53%); são 25/33 episódios detectados. A elevada razão AP/prevalência não torna esses alertas automaticamente úteis em operação.

### Incerteza e probabilidades

Os IC95% de AP do HGB em H=90 são **[0,1495; 0,4531]** e **[0,0821; 0,2571]**. Os intervalos de recall são [0,1723; 0,6364] e [0,5937; 0,8750]; de precision, [0,1034; 0,4444] e [0,0492; 0,1131]. Há incerteza substancial sobre a capacidade prática de detecção, mesmo sem incorporar a incerteza da seleção e do treinamento.

Em H=180/todas, uma réplica do bootstrap principal não contém positivos e a AP tem 999 réplicas válidas. Nas sensibilidades, o mínimo é 942/1.000 para métricas dependentes de ambas as classes. Não foram removidas contas difíceis nem forçada estratificação para ocultar esses casos. Réplicas sem positivos não são apresentadas como AP zero. Os contadores por métrica estão nos CSVs.

Probabilidades não estão adequadamente calibradas. HGB/todas em H=90 prevê média aproximadamente **0,0029%**, para prevalência **0,0560%** — quase vinte vezes maior. No bin (0,001; 0,01], a média prevista é 0,00324 e a frequência observada é 0,2647, em somente 34 snapshots. Seu Brier 0,000558 é quase igual ao do dummy 0,000560 e pior que o da frequência 0,000543. Ranking acima do aleatório não implica probabilidades confiáveis.

Sem rotineiros, HGB prevê média **0,0320%**, para frequência observada **0,0868%**. O Brier 0,000812 melhora sobre o dummy 0,000868 e a frequência 0,000861, mas ainda há subestimação em vários bins. Não se ajustou calibração usando TEST; a validação também tem poucos eventos para justificar estimativas flexíveis de calibração.

Curvas locais: [HGB e baselines, todas/H=90](../outputs/berka/activity_transition/prespecified_v1/all_transactions_a30_h90/test_curves.png) e [sem rotineiros/H=90](../outputs/berka/activity_transition/prespecified_v1/excluding_routine_a30_h90/test_curves.png). ROC-AUC alta deve ser lida junto a AP, prevalência, matriz de confusão e quantidade de episódios.

## Estabilidade e sensibilidades

Na janela 1, T de avaliação vai de 1997-01-31 a 1997-03-31; na janela 2, de 1997-04-30 a 1997-06-30. A validação nominal começa em 1996-04-01 e 1996-07-01, respectivamente. Cada H purga os labels nas fronteiras; os arquivos de splits registram os limites efetivos. Não se misturam previsões de janelas diferentes como se formassem um TEST independente maior.

Com todas as transações, **nenhum desses treinos tem positivos**, para nenhum H. As métricas dos modelos discriminativos são indisponíveis. Sem rotineiros/H=90, há apenas 2 e 4 episódios/contas positivas no treino, e 6 e 4 na avaliação. AP de HGB, selecionado na validação das duas janelas, varia de **0,00174 a 0,13196**; frequência varia de 0,04915 a 0,00649. O HGB fica abaixo da frequência na primeira janela. A logística varia de 0,00550 a 0,27236, sem ter sido selecionada. Não há demonstração consistente de estabilidade.

Em H=180, a segunda avaliação antiga não tem **nenhum positivo**, nos dois escopos. AP e ROC-AUC são ausentes; não atribuímos sucesso ao modelo por predizer negativos. No TEST de 1998, os meses de H=90 têm 0–6 positivos (todas) ou 2–10 (sem rotineiros). AP mensal do HGB varia entre 0,1178–0,6911, com um mês sem AP identificável, e 0,0432–0,3725. Um ou dois eventos mudam bastante esses números.

As sensibilidades não levam à troca da especificação principal:

- **A=60:** em H=90, aumenta os positivos completos de 47 para 67 e de 79 para 138, mas preserva exatamente **37 e 78 episódios**, nas mesmas 28/61 contas. A redundância por episódio sobe de 21,28%/1,27% para 44,78%/43,48%. O aumento de AP em algumas combinações não é acompanhado por aumento equivalente de informação independente.
- **A=15:** captura somente 21 e 27 episódios mensais de H=90, em 15 e 18 contas. O TEST tem 8 e 7 contas positivas. A janela de elegibilidade estreita perde episódios no calendário mensal; não melhora a suficiência estatística. Em H=180, não há positivos na validação e a regra pré-especificada escolhe prevalência.
- **H=120:** o escolhido é recência (todas), AP 0,0362 [0,0083; 0,1639], ou logística (sem rotineiros), AP 0,0515 [0,0218; 0,1465]. HGB tem AP maior no TEST do segundo escopo, mas não substitui retrospectivamente o modelo escolhido.
- **H=180:** todas as transações não permitem treino supervisionado. Sem rotineiros, a validação escolhe frequência, AP de TEST 0,00913, com zero detecções no threshold congelado e apenas 9 contas positivas. AP do HGB é 0,03461, mas não foi a seleção da validação.

No calendário comum janeiro–junho/1998, em A=30, AP do HGB para H=90/120 é 0,2787/0,0804 (todas); para H=90/120/180 é 0,1994/0,2269/0,0346 (sem rotineiros). Esse controle não muda o diagnóstico de poucos eventos e instabilidade; H=180/todas continua indisponível.

## Por que os resultados anteriores não são referência de sucesso

O experimento anterior permitia contas já sem atividade há H dias em T. Prever ausência futura nessas contas mede, em grande parte, **persistência de inatividade**. O novo target é estimado em uma população ativa desde a construção, com novos treinos, novos thresholds e nova seleção. Filtrar apenas o TEST anterior teria mantido um modelo aprendido em outra distribuição.

A tabela diagnóstica mostra AP da recência caindo de 0,8224 para 0,1378 (todas) e de 0,6965 para 0,000550 (sem rotineiros), com redução de contas positivas e prevalência. Os números também refletem a mudança explícita do corte de validação para o ano de 1997 e o novo ajuste; **não são uma estimativa causal isolada do efeito do filtro**. Não há uma queda de qualidade do mesmo modelo para o mesmo problema: são populações e estimandos diferentes.

As APs relativamente altas do cenário geral não demonstravam capacidade de antecipar entradas. O diagnóstico anterior restrito a contas recentemente ativas também não substitui o experimento atual. Nenhuma dessas análises fornece rótulo de churn efetivo ou evidência de encerramento contratual.

## Auditoria executada, limites e decisão

Foram executados **44 testes**, todos aprovados, incluindo os 27 anteriores. `compileall` e `git diff --check` passaram. A execução dos 18 experimentos, incluindo as especificações principais e sensibilidades, foi concluída em cerca de **244 segundos**, em CPU com quatro threads, sem GPU. Foram persistidos 78 modelos finais; 12 configurações de famílias ficaram explicitamente indisponíveis por ausência de positivos no treino. Nenhum corte foi mudado após essas contagens.

A auditoria real incluiu **90 contas** (amostra fixa mais todas as contas positivas dos datasets), dois escopos e três datas. Remover o futuro não alterou features nem elegibilidade. Foram conferidos **1.574 targets** por contagem direta, incluindo todos os positivos; o censo de gaps e o agrupamento de snapshots concordaram nas 18 combinações. As janelas de target e os episódios positivos não atravessam splits. O replay dos 78 modelos e a inspeção de suas colunas confirmaram previsões reproduzíveis e ausência de IDs. Os hashes de fontes e **196 artefatos** foram verificados.

O [manifesto de referência](berka_activity_transition_reference.json) preserva configurações, proveniência, hashes, parâmetros, contagens, métricas, intervalos e auditorias. Os resultados são reproduzíveis no ambiente fixado; os artefatos individuais completos permanecem no diretório local de outputs. Não houve commit, merge, push ou alteração de outra branch.

O bootstrap trata dependência por conta, mas não resolve: poucos grupos positivos no treino/validação; seleção entre candidatos em validações diminutas; dependência de calendário entre contas; mudança de prevalência; cobertura administrativa presumida; ausência de validação externa; e conhecimento prévio de 1998 por análises exploratórias. Contagem de episódios desduplicados não transforma essas observações em unidades estatisticamente independentes garantidas.

**Resposta à pergunta central:** há algum sinal além dos baselines — especialmente HGB em H=90 sem rotineiros —, mas **não há quantidade razoável de eventos nem estabilidade suficiente para sustentar seriamente uma modelagem robusta de transição como resultado preditivo principal do projeto**. A classificação global é **B: apenas exploratória**. H=180/todas é **C: treino inviável por zero eventos**; outras sensibilidades também têm evidência extremamente limitada. Não há suporte para a alternativa A nesta extração. O resultado principal do estudo é a insuficiência da amostra efetiva, não o nome do modelo com maior AP.

## Fechamento da investigação

Com base nessas evidências, a linha de dormancy/churn no Berka está encerrada como proposta de alvo preditivo principal nesta branch. A classificação exploratória dos resultados descreve a força da evidência obtida; não constitui uma recomendação de continuar essa direção como eixo principal. Todo o trabalho permanece preservado como registro da investigação.

O Berka continua podendo ser útil para outras perguntas. Caso seja mantido no projeto, o próximo passo será mudar o pivô para um fenômeno que a base efetivamente observa, como empréstimos/default, ou outro alvo diretamente sustentado pelos dados. A escolha e a viabilidade desse alvo ainda precisam ser avaliadas: **não há decisão final de mudança de direção do projeto nem implementação de um novo alvo nesta etapa**.
