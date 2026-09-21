# Berka: previsão de inatividade futura de contas

**Registro histórico de uma linha encerrada como eixo preditivo principal na branch `berka-temporal`.** A investigação de dormancy/churn não reuniu suporte suficiente para esse papel no projeto. O encerramento não invalida o Berka nem decide o próximo alvo; veja a [conclusão da branch](../README.md#conclusão-da-branch-e-direção-ainda-em-aberto).

**Experimento anterior, exploratório, com população geral.** Seus modelos e resultados não definem a metodologia do experimento posterior de transição ativo → inativo. A especificação prospectiva, treinada exclusivamente em contas ativas, está em [berka_activity_transition.md](berka_activity_transition.md). O filtro diagnóstico de TEST desta página não substitui esse treinamento. Os resultados e procedimentos abaixo são preservados como evidência da investigação.

## Problema e população

O Berka não observa encerramento de conta ou rescisão contratual. Este estudo prevê **ausência futura de atividade observada (dormancy)**. A ausência pode ser um proxy comportamental potencialmente associado ao risco de churn; não é evidência de churn efetivo.

Para a conta `a`, data de referência `T`, horizonte `H` em dias corridos e definição de atividade `s`:

`y_s(a,T,H) = 1{ soma de eventos qualificantes da conta em (T,T+H] = 0 }`.

O dia T pertence exclusivamente ao histórico; T+H pertence ao target. H=90 é a análise principal. H=120 e H=180 são sensibilidades previamente especificadas. São reportados `all_transactions` (qualquer transação) e `excluding_routine` (sem `UROK`, `SLUZBY`, `SANKC. UROK`). O segundo filtro ainda inclui pagamentos potencialmente automáticos; não identifica ação voluntária do titular. Não escolhemos a definição ou H com melhor resultado.

Unidade: conta-snapshot. A mesma conta pode aparecer em diferentes períodos; o objetivo é generalização temporal. Não são usados `account_id`, `client_id`, `trans_id`, datas futuras, última observação global individual ou métricas descritivas do histórico completo como preditores.

## Dados, reprodução e artefatos

A extração inclui 4.500 contas e 1.056.320 transações, entre 1993-01-01 e 1998-12-31. O cache financeiro acrescenta `amount` e `balance` à consulta anterior. Todas as colunas compartilhadas foram comparadas e coincidem exatamente com o cache da EDA. As consultas são somente de leitura, com ordenação por conta/data/trans_id e SHA-256 dos arquivos. Fonte: [CTU Financial](https://relational.fel.cvut.cz/dataset/Financial).

```powershell
python -X utf8 -m dataset_pk99.predict_inactivity --source database
# Para reproduzir a extração local já verificada:
python -X utf8 -m dataset_pk99.predict_inactivity --source cache --output-dir outputs/berka/inactivity_prediction/reproduction
python -X utf8 -m dataset_pk99.audit_inactivity --output-dir outputs/berka/inactivity_prediction/reproduction
python -X utf8 -m unittest discover -s tests -v
python -m compileall -q dataset_pk99 tests
```

A execução de referência usa `outputs/berka/inactivity_prediction/validated/`. Saídas e dados são locais e ignorados pelo Git; estas tabelas e o manifesto de referência preservam os resultados versionados. O diretório de uma nova execução deve estar vazio.

- `protocol.json`, `run_manifest.json`: configurações, seed, threads, versões, hashes de código/dados/outputs, consultas, datas e horários.
- `frozen_selection.json`: modelo escolhido por combinação e hashes das escolhas e modelos, escrito antes da avaliação final.
- `eligibility.csv`, `splits.csv`, `purges.csv`: população, exclusões e limites exatos.
- `validation_candidates.json`: todos os candidatos e suas métricas de validação.
- `test_metrics.csv`, `test_confidence_intervals.csv`, `paired_baseline_differences.csv`: métricas e incerteza agrupada.
- `stability_metrics.csv`, `stability_splits.csv`, `stability_candidates.json`, `stability_predictions.csv.gz`: cortes anteriores ao TEST e suas escolhas independentes.
- `diagnostic_cohorts.csv`, `persistence_diagnostics.csv`, `test_monthly_metrics.csv`: persistência, atividade recente, calendário comum e evolução mensal.
- Auditoria suplementar: `real_data_leakage_audit.csv`, `recent_activity_confidence_intervals.csv`, `model_vs_recency_paired_intervals.csv`, `positive_concentration.csv`. São diagnósticos sem retreinamento ou novas escolhas.
- Por combinação: `selection.json`, `fitted_models.joblib`, labels, previsões de validação e TEST, réplicas bootstrap, calibração e curvas em `test_curves.png`.

## Snapshots e features

Calendário principal: fim de cada mês (`ME`), configurável, de janeiro de 1993 a dezembro de 1998. Uma conta precisa estar aberta em T, ter pelo menos 180 dias desde `max(abertura, início global da observação)` e ao menos uma atividade qualificante até T. Contas sem atividade conhecida são excluídas explicitamente. O histórico mínimo é observável, não uma condição calculada usando a última transação. Neste cache, a primeira transação de ambos os escopos coincide com a abertura. A escolha de mínimo 1, em vez dos 5 ilustrados na EDA, preserva cinco snapshots adicionais sem positivos.

Cada H exclui `T+H > 1998-12-31`. Não há rótulo positivo ou negativo além do fim observável. A cobertura até essa data é uma hipótese administrativa comum, não uma prova de captura contínua por conta.

São 36 features numéricas, com lista explícita em `inactivity_features.py` e no protocolo:

- Idade da conta e dias observáveis em T; contagem acumulada e recência da atividade do escopo.
- Contagens, dias ativos, soma/média/desvio de valores e entradas/saídas em `(T-w,T]`, para w=30/90/180.
- Média, desvio e máximo dos gaps **encerrados até T** entre dias ativos distintos. O gap corrente é representado pela recência.
- Diferença e razão suavizada de contagens entre os dois últimos blocos de 30 dias; desvio e inclinação linear das contagens nos seis blocos de 30 dias anteriores a T.
- Último saldo conhecido e idade desse registro; média e desvio dos saldos dos lançamentos nos últimos 180 dias. Saldo sempre considera todos os lançamentos, inclusive os rotineiros: é informação disponível sobre a conta em T, independentemente da definição do target.

Entradas são `PRIJEM`; saídas são `VYDAJ`/`VYBER`. Valores são unidades monetárias originais, sem ajuste inflacionário. Estatísticas de saldo são ponderadas por lançamento, não por tempo. Empates no mesmo dia usam `trans_id` para ordenação determinística, sem usá-lo como feature; a base não informa hora intradiária. Janelas sem eventos têm contagem/volume zero e momentos ausentes. Imputação e padronização são ajustadas somente no treino. O HGB trata valores ausentes nativamente.

## Seleção, isolamento temporal e threshold

As definições de atividade, features e H foram fixadas antes de inspecionar métricas de TEST. O limite da validação foi ajustado durante o desenvolvimento, exclusivamente pelas contagens do treino: iniciá-la em janeiro de 1997 deixava H=180, todas as transações, sem positivos após purge. O protocolo final fixa **1997-04-01 para validação e 1998-01-01 para TEST**, igualmente para os seis experimentos. Ainda restam apenas 4 positivos de 3 contas naquele treino. Não houve escolha dos cortes por performance no TEST.

Regra conservadora: `label_end_train < validation_start` e `label_end_validation < test_start`. Nem eventos no próprio primeiro dia do próximo período entram nos labels anteriores. Snapshots que não satisfazem a regra são purgados. Features do próximo período podem usar passado anterior ao corte; isso corresponde à informação disponível em produção. Não há split aleatório.

Comparações:

| Modelo | Ajuste no treino | Seleção na validação |
|---|---|---|
| Prevalência | `DummyClassifier(strategy='prior')`: probabilidade constante igual à prevalência do treino | Threshold por F2; não usa a prevalência do TEST como previsão |
| Recência | Uma regressão logística sobre `log1p(recency_days)`, C=1, sem outros atributos | Cutoff equivalente em dias e threshold por F2 |
| Logística | Medianas + indicadores de ausentes, StandardScaler, L2; C em {0,1; 1} | Maior AP; empate por menor Brier e ordem fixa |
| HistGradientBoosting | 150 iterações, learning_rate=0,05, sem early stopping aleatório; (folhas, mínimo por folha, L2) em {(7,30,10), (15,60,30)} | Mesmo critério de AP e desempate |

São seis candidatos por combinação, sem SMOTE, pesos de classe ou reamostragem no treino. Validação e TEST mantêm as classes reais. A família vencedora também é escolhida por AP da validação, com os mesmos desempates. Cada família é reportada no TEST, mesmo quando não foi selecionada.

Threshold de cada modelo/escopo/H: máximo F2 na validação, desempate pelo maior threshold. F2 prioriza recall e é um critério exploratório, não uma função de custo de negócio. O baseline constante tende a classificar tudo como positivo sob esse critério; isso é reportado, não corrigido usando o TEST. Não há novo ajuste dos modelos em treino+validação, para preservar a correspondência entre escala das probabilidades e threshold congelado. Não há calibração posterior com TEST.

O código de seleção recebe somente treino e validação. Todas as escolhas e modelos são persistidos e seus hashes congelados antes de avaliar o TEST na execução final. Métricas diagnósticas de TEST não levam a novos modelos, features, thresholds ou busca.

Rastro do desenvolvimento: uma execução preliminar terminou com uma janela de validação vazia para H=180; outra foi interrompida ao corrigir o corte principal por falta de positivos no treino. Esta segunda chegou automaticamente ao arquivo de congelamento, mas suas métricas e previsões de TEST não foram inspecionadas nem usadas na revisão do protocolo. Os resultados aqui são exclusivamente da execução `validated`. Depois dela, só houve auditoria dos artefatos e correção visual da curva PR para desenho em degraus, sem mudar métricas, predições ou escolhas; o manifesto registra esse pós-processamento separadamente.

## Métricas e incerteza

AP é a Average Precision não interpolada, usada como resumo da curva PR; não é integração trapezoidal de PR. Lift = AP / prevalência do **mesmo conjunto avaliado**. ROC-AUC, precision, recall, F1, F2, MCC, balanced accuracy, Brier e matriz `[[TN, FP], [FN, TP]]` complementam a avaliação. Não usamos accuracy como indicador principal. AP/ROC e recall ficam ausentes quando não identificáveis; precision sem predições positivas e MCC degenerado usam zero. Veja a definição na [documentação de Average Precision](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.average_precision_score.html).

IC95% percentil, 1.000 réplicas, seed **20260920**, amostragem de N contas com reposição entre as N contas do TEST, mantendo juntos todos os snapshots de cada conta e sua multiplicidade. Não há bootstrap de linhas nem estratificação artificial por classe. Mesmas reamostragens entre modelos permitem diferenças pareadas contra os baselines. Réplicas degeneradas são omitidas somente da métrica não identificável, e o número válido é registrado.

Os intervalos são condicionais aos modelos e thresholds já ajustados: não incluem incerteza de treinamento, seleção ou mudança de regime. Agrupar por conta trata a dependência longitudinal dentro da conta, mas não efeitos temporais comuns entre contas. Com poucos grupos positivos, os intervalos podem ser amplos e a evidência externa permanece limitada.

Brier precisa ser comparado à referência probabilística: classes muito raras permitem Brier pequeno mesmo sem discriminação. As curvas e tabelas de calibração mostram probabilidades médias e taxas observadas em bins fixos, inclusive na região de eventos raros. Não se conclui boa calibração apenas por Brier pequeno; consulte a [documentação de calibração](https://scikit-learn.org/stable/modules/calibration.html).

## Resultados da execução

As tabelas e a interpretação quantitativa abaixo registram a execução final, sem reajuste após a leitura do TEST.

### Datas efetivas dos splits (iguais nos dois escopos)

| H | Split | Datas T | Dias utilizados pelos targets | Gap de T ao próximo período | Gap do último evento ao próximo período |
|---|---|---|---|---|---|
| 90 | train | 1993-06-30 a 1996-12-31 | 1993-07-01 a 1997-03-31 | 91 | 1 |
| 90 | validation | 1997-04-30 a 1997-09-30 | 1997-05-01 a 1997-12-29 | 93 | 3 |
| 90 | test | 1998-01-31 a 1998-09-30 | 1998-02-01 a 1998-12-29 | — | — |
| 120 | train | 1993-06-30 a 1996-11-30 | 1993-07-01 a 1997-03-30 | 122 | 2 |
| 120 | validation | 1997-04-30 a 1997-08-31 | 1997-05-01 a 1997-12-29 | 123 | 3 |
| 120 | test | 1998-01-31 a 1998-08-31 | 1998-02-01 a 1998-12-29 | — | — |
| 180 | train | 1993-06-30 a 1996-09-30 | 1993-07-01 a 1997-03-29 | 183 | 3 |
| 180 | validation | 1997-04-30 a 1997-06-30 | 1997-05-01 a 1997-12-27 | 185 | 5 |
| 180 | test | 1998-01-31 a 1998-06-30 | 1998-02-01 a 1998-12-27 | — | — |


### Snapshots purgados (por escopo)

| H | Fronteira | Datas T removidas | Snapshots removidos |
|---|---|---|---|
| 90 | before_validation | 1997-01-31 a 1997-03-31 | 9440 |
| 90 | before_test | 1997-10-31 a 1997-12-31 | 11955 |
| 120 | before_validation | 1996-12-31 a 1997-03-31 | 12336 |
| 120 | before_test | 1997-09-30 a 1997-12-31 | 15776 |
| 180 | before_validation | 1996-10-31 a 1997-03-31 | 17794 |
| 180 | before_test | 1997-07-31 a 1997-12-31 | 23204 |


### Frequência mensal e perdas de snapshots (por escopo)

| H | Candidatos após abertura | Perda por histórico <180d | Perda por contagem | Perda por censura | Elegíveis antes do purge | Usados em treino/val/TEST |
|---|---|---|---|---|---|---|
| 90 | 185615 | 26608 | 0 | 13500 | 145507 | 124112 |
| 120 | 185615 | 26608 | 0 | 18000 | 141007 | 112895 |
| 180 | 185615 | 26608 | 0 | 27000 | 132007 | 91009 |


### População em cada split

| Atividade | H | Split | Snapshots | Contas | Positivos | Contas positivas | Prevalência |
|---|---|---|---|---|---|---|---|
| Todas | 90 | train | 62922 | 2896 | 22 | 7 | 0.0350% |
| Todas | 90 | validation | 21716 | 3821 | 43 | 9 | 0.1980% |
| Todas | 90 | test | 39474 | 4500 | 149 | 27 | 0.3775% |
| Todas | 120 | train | 60026 | 2772 | 13 | 5 | 0.0217% |
| Todas | 120 | validation | 17895 | 3756 | 34 | 9 | 0.1900% |
| Todas | 120 | test | 34974 | 4500 | 119 | 22 | 0.3403% |
| Todas | 180 | train | 54568 | 2577 | 4 | 3 | 0.0073% |
| Todas | 180 | validation | 10467 | 3606 | 18 | 6 | 0.1720% |
| Todas | 180 | test | 25974 | 4500 | 78 | 17 | 0.3003% |
| Sem rotineiros | 90 | train | 62922 | 2896 | 73 | 18 | 0.1160% |
| Sem rotineiros | 90 | validation | 21716 | 3821 | 61 | 17 | 0.2809% |
| Sem rotineiros | 90 | test | 39474 | 4500 | 205 | 46 | 0.5193% |
| Sem rotineiros | 120 | train | 60026 | 2772 | 52 | 14 | 0.0866% |
| Sem rotineiros | 120 | validation | 17895 | 3756 | 45 | 14 | 0.2515% |
| Sem rotineiros | 120 | test | 34974 | 4500 | 154 | 36 | 0.4403% |
| Sem rotineiros | 180 | train | 54568 | 2577 | 25 | 10 | 0.0458% |
| Sem rotineiros | 180 | validation | 10467 | 3606 | 21 | 7 | 0.2006% |
| Sem rotineiros | 180 | test | 25974 | 4500 | 90 | 21 | 0.3465% |


### Seleção congelada; recência venceu todas as combinações

| Atividade | H | C logística | HGB folhas/mínimo/L2 | AP validação recência | Threshold recência | Cutoff dias | Threshold logística | Threshold HGB |
|---|---|---|---|---|---|---|---|---|
| Todas | 90 | 0.1 | 7/30/10.0 | 0.8798 | 0.1036 | 51 | 0.1857 | 0.0008 |
| Todas | 120 | 1.0 | 7/30/10.0 | 0.8630 | 0.0500 | 51 | 0.0123 | 0.0014 |
| Todas | 180 | 0.1 | 7/30/10.0 | 0.8960 | 0.0077 | 51 | 0.0056 | 0.0001 |
| Sem rotineiros | 90 | 0.1 | 15/60/30.0 | 0.7415 | 0.0294 | 51 | 0.1643 | 0.0434 |
| Sem rotineiros | 120 | 0.1 | 15/60/30.0 | 0.7593 | 0.0200 | 51 | 0.0919 | 0.0021 |
| Sem rotineiros | 180 | 0.1 | 7/30/10.0 | 0.8357 | 0.0080 | 51 | 0.0146 | 0.0034 |


### TEST: discriminação e probabilidades, todos os modelos

| Atividade | H | Modelo | AP | AP/prevalência | ROC-AUC | Brier |
|---|---|---|---|---|---|---|
| Todas | 90 | Prevalência | 0.0038 | 1.00 | 0.5000 | 0.003772 |
| Todas | 90 | Recência | 0.8224 | 217.87 | 0.9757 | 0.001497 |
| Todas | 90 | Logística | 0.6310 | 167.18 | 0.9986 | 0.001918 |
| Todas | 90 | HGB | 0.6744 | 178.67 | 0.9980 | 0.002643 |
| Todas | 120 | Prevalência | 0.0034 | 1.00 | 0.5000 | 0.003401 |
| Todas | 120 | Recência | 0.8066 | 237.06 | 0.9782 | 0.001773 |
| Todas | 120 | Logística | 0.6390 | 187.81 | 0.9985 | 0.002050 |
| Todas | 120 | HGB | 0.6104 | 179.39 | 0.9983 | 0.002866 |
| Todas | 180 | Prevalência | 0.0030 | 1.00 | 0.5000 | 0.003003 |
| Todas | 180 | Recência | 0.7826 | 260.60 | 0.9926 | 0.002686 |
| Todas | 180 | Logística | 0.0435 | 14.50 | 0.2539 | 0.003540 |
| Todas | 180 | HGB | 0.4146 | 138.06 | 0.9972 | 0.003001 |
| Sem rotineiros | 90 | Prevalência | 0.0052 | 1.00 | 0.5000 | 0.005183 |
| Sem rotineiros | 90 | Recência | 0.6965 | 134.11 | 0.9619 | 0.002756 |
| Sem rotineiros | 90 | Logística | 0.4550 | 87.61 | 0.9961 | 0.003801 |
| Sem rotineiros | 90 | HGB | 0.4735 | 91.18 | 0.9967 | 0.003681 |
| Sem rotineiros | 120 | Prevalência | 0.0044 | 1.00 | 0.5000 | 0.004396 |
| Sem rotineiros | 120 | Recência | 0.6829 | 155.10 | 0.9623 | 0.002407 |
| Sem rotineiros | 120 | Logística | 0.4052 | 92.02 | 0.9961 | 0.003494 |
| Sem rotineiros | 120 | HGB | 0.3005 | 68.25 | 0.9935 | 0.003847 |
| Sem rotineiros | 180 | Prevalência | 0.0035 | 1.00 | 0.5000 | 0.003462 |
| Sem rotineiros | 180 | Recência | 0.6838 | 197.34 | 0.9713 | 0.002194 |
| Sem rotineiros | 180 | Logística | 0.0810 | 23.38 | 0.4963 | 0.003980 |
| Sem rotineiros | 180 | HGB | 0.1794 | 51.79 | 0.9922 | 0.003451 |


### TEST: decisão no threshold congelado

| Atividade | H | Modelo | Precision | Recall | F1 | F2 | MCC | Balanced accuracy | TN / FP / FN / TP |
|---|---|---|---|---|---|---|---|---|---|
| Todas | 90 | Prevalência | 0.0038 | 1.0000 | 0.0075 | 0.0186 | 0.0000 | 0.5000 | 0 / 39325 / 0 / 149 |
| Todas | 90 | Recência | 0.7593 | 0.8255 | 0.7910 | 0.8113 | 0.7909 | 0.9123 | 39286 / 39 / 26 / 123 |
| Todas | 90 | Logística | 0.6579 | 0.8389 | 0.7375 | 0.7952 | 0.7418 | 0.9186 | 39260 / 65 / 24 / 125 |
| Todas | 90 | HGB | 0.5148 | 0.9329 | 0.6635 | 0.8025 | 0.6916 | 0.9648 | 39194 / 131 / 10 / 139 |
| Todas | 120 | Prevalência | 0.0034 | 1.0000 | 0.0068 | 0.0168 | 0.0000 | 0.5000 | 0 / 34855 / 0 / 119 |
| Todas | 120 | Recência | 0.7203 | 0.8655 | 0.7863 | 0.8320 | 0.7888 | 0.9322 | 34815 / 40 / 16 / 103 |
| Todas | 120 | Logística | 0.4542 | 0.9580 | 0.6162 | 0.7840 | 0.6582 | 0.9770 | 34718 / 137 / 5 / 114 |
| Todas | 120 | HGB | 0.5774 | 0.8151 | 0.6760 | 0.7531 | 0.6848 | 0.9065 | 34784 / 71 / 22 / 97 |
| Todas | 180 | Prevalência | 0.0030 | 1.0000 | 0.0060 | 0.0148 | 0.0000 | 0.5000 | 0 / 25896 / 0 / 78 |
| Todas | 180 | Recência | 0.6262 | 0.8590 | 0.7243 | 0.7995 | 0.7325 | 0.9287 | 25856 / 40 / 11 / 67 |
| Todas | 180 | Logística | 0.1324 | 0.1154 | 0.1233 | 0.1184 | 0.1211 | 0.5566 | 25837 / 59 / 69 / 9 |
| Todas | 180 | HGB | 0.4321 | 0.8974 | 0.5833 | 0.7384 | 0.6213 | 0.9469 | 25804 / 92 / 8 / 70 |
| Sem rotineiros | 90 | Prevalência | 0.0052 | 1.0000 | 0.0103 | 0.0254 | 0.0000 | 0.5000 | 0 / 39269 / 0 / 205 |
| Sem rotineiros | 90 | Recência | 0.6070 | 0.7610 | 0.6753 | 0.7242 | 0.6778 | 0.8792 | 39168 / 101 / 49 / 156 |
| Sem rotineiros | 90 | Logística | 0.4809 | 0.7366 | 0.5819 | 0.6658 | 0.5926 | 0.8662 | 39106 / 163 / 54 / 151 |
| Sem rotineiros | 90 | HGB | 0.4318 | 0.9415 | 0.5920 | 0.7616 | 0.6351 | 0.9675 | 39015 / 254 / 12 / 193 |
| Sem rotineiros | 120 | Prevalência | 0.0044 | 1.0000 | 0.0088 | 0.0216 | 0.0000 | 0.5000 | 0 / 34820 / 0 / 154 |
| Sem rotineiros | 120 | Recência | 0.5516 | 0.7987 | 0.6525 | 0.7330 | 0.6620 | 0.8979 | 34720 / 100 / 31 / 123 |
| Sem rotineiros | 120 | Logística | 0.4219 | 0.8766 | 0.5696 | 0.7212 | 0.6059 | 0.9357 | 34635 / 185 / 19 / 135 |
| Sem rotineiros | 120 | HGB | 0.2530 | 0.9675 | 0.4011 | 0.6183 | 0.4913 | 0.9774 | 34380 / 440 / 5 / 149 |
| Sem rotineiros | 180 | Prevalência | 0.0035 | 1.0000 | 0.0069 | 0.0171 | 0.0000 | 0.5000 | 0 / 25884 / 0 / 90 |
| Sem rotineiros | 180 | Recência | 0.4583 | 0.8556 | 0.5969 | 0.7292 | 0.6246 | 0.9260 | 25793 / 91 / 13 / 77 |
| Sem rotineiros | 180 | Logística | 0.1290 | 0.4000 | 0.1951 | 0.2817 | 0.2227 | 0.6953 | 25641 / 243 / 54 / 36 |
| Sem rotineiros | 180 | HGB | 0.1855 | 0.7111 | 0.2943 | 0.4539 | 0.3594 | 0.8501 | 25603 / 281 / 26 / 64 |


### IC95% agrupados: AP, F2 e Brier de todos os modelos

| Atividade | H | Modelo | AP [IC95%] | F2 [IC95%] | Brier [IC95%] |
|---|---|---|---|---|---|
| Todas | 90 | Prevalência | 0.0038 [0.0022; 0.0055] | 0.0186 [0.0109; 0.0268] | 0.003772 [0.002202; 0.005484] |
| Todas | 90 | Recência | 0.8224 [0.6536; 0.9103] | 0.8113 [0.7108; 0.8872] | 0.001497 [0.000844; 0.002150] |
| Todas | 90 | Logística | 0.6310 [0.4549; 0.8339] | 0.7952 [0.6911; 0.8761] | 0.001918 [0.001092; 0.002796] |
| Todas | 90 | HGB | 0.6744 [0.5207; 0.8311] | 0.8025 [0.6889; 0.8809] | 0.002643 [0.001530; 0.003879] |
| Todas | 120 | Prevalência | 0.0034 [0.0019; 0.0051] | 0.0168 [0.0095; 0.0249] | 0.003401 [0.001915; 0.005072] |
| Todas | 120 | Recência | 0.8066 [0.6032; 0.9151] | 0.8320 [0.7451; 0.9005] | 0.001773 [0.000956; 0.002626] |
| Todas | 120 | Logística | 0.6390 [0.4155; 0.8679] | 0.7840 [0.6708; 0.8575] | 0.002050 [0.001042; 0.003068] |
| Todas | 120 | HGB | 0.6104 [0.4141; 0.7950] | 0.7531 [0.5838; 0.8681] | 0.002866 [0.001622; 0.004274] |
| Todas | 180 | Prevalência | 0.0030 [0.0016; 0.0046] | 0.0148 [0.0079; 0.0225] | 0.003003 [0.001583; 0.004588] |
| Todas | 180 | Recência | 0.7826 [0.5371; 0.9187] | 0.7995 [0.6844; 0.8859] | 0.002686 [0.001433; 0.004125] |
| Todas | 180 | Logística | 0.0435 [0.0064; 0.1467] | 0.1184 [0.0334; 0.2174] | 0.003540 [0.002018; 0.005249] |
| Todas | 180 | HGB | 0.4146 [0.2652; 0.6003] | 0.7384 [0.5763; 0.8471] | 0.003001 [0.001582; 0.004585] |
| Sem rotineiros | 90 | Prevalência | 0.0052 [0.0035; 0.0071] | 0.0254 [0.0173; 0.0346] | 0.005183 [0.003493; 0.007100] |
| Sem rotineiros | 90 | Recência | 0.6965 [0.5342; 0.8035] | 0.7242 [0.6287; 0.8052] | 0.002756 [0.001927; 0.003697] |
| Sem rotineiros | 90 | Logística | 0.4550 [0.3346; 0.6001] | 0.6658 [0.5674; 0.7464] | 0.003801 [0.002661; 0.004996] |
| Sem rotineiros | 90 | HGB | 0.4735 [0.3581; 0.5964] | 0.7616 [0.6816; 0.8228] | 0.003681 [0.002532; 0.004966] |
| Sem rotineiros | 120 | Prevalência | 0.0044 [0.0028; 0.0063] | 0.0216 [0.0137; 0.0307] | 0.004396 [0.002773; 0.006277] |
| Sem rotineiros | 120 | Recência | 0.6829 [0.4806; 0.8037] | 0.7330 [0.6311; 0.8104] | 0.002407 [0.001501; 0.003419] |
| Sem rotineiros | 120 | Logística | 0.4052 [0.2753; 0.5750] | 0.7212 [0.6158; 0.7965] | 0.003494 [0.002373; 0.004601] |
| Sem rotineiros | 120 | HGB | 0.3005 [0.2004; 0.4375] | 0.6183 [0.5065; 0.7040] | 0.003847 [0.002453; 0.005418] |
| Sem rotineiros | 180 | Prevalência | 0.0035 [0.0020; 0.0052] | 0.0171 [0.0097; 0.0257] | 0.003462 [0.001961; 0.005240] |
| Sem rotineiros | 180 | Recência | 0.6838 [0.4201; 0.8355] | 0.7292 [0.6111; 0.8125] | 0.002194 [0.001195; 0.003352] |
| Sem rotineiros | 180 | Logística | 0.0810 [0.0204; 0.1872] | 0.2817 [0.1457; 0.3997] | 0.003980 [0.002657; 0.005628] |
| Sem rotineiros | 180 | HGB | 0.1794 [0.1108; 0.2871] | 0.4539 [0.2918; 0.5844] | 0.003451 [0.002028; 0.005121] |


### H=90: demais IC95% do modelo selecionado (recência)

| Métrica | Todas | Sem rotineiros |
|---|---|---|
| prevalence | 0.0038 [0.0022; 0.0055] | 0.0052 [0.0035; 0.0071] |
| ap_lift | 217.8685 [155.7274; 351.7929] | 134.1061 [101.1850; 186.2115] |
| roc_auc | 0.9757 [0.9515; 0.9925] | 0.9619 [0.9355; 0.9806] |
| precision | 0.7593 [0.6264; 0.8699] | 0.6070 [0.4912; 0.7098] |
| recall | 0.8255 [0.7314; 0.9005] | 0.7610 [0.6684; 0.8366] |
| f1 | 0.7910 [0.6827; 0.8757] | 0.6753 [0.5698; 0.7644] |
| mcc | 0.7909 [0.6829; 0.8756] | 0.6778 [0.5760; 0.7660] |
| balanced_accuracy | 0.9123 [0.8652; 0.9498] | 0.8792 [0.8327; 0.9168] |


### Sensibilidade no mesmo calendário de TEST: janeiro a junho de 1998

| Atividade | H | Snapshots | Positivos | Contas positivas | Prevalência | AP recência | AP logística | AP HGB |
|---|---|---|---|---|---|---|---|---|
| Todas | 90 | 25974 | 102 | 25 | 0.3927% | 0.7826 | 0.6629 | 0.6223 |
| Todas | 120 | 25974 | 90 | 22 | 0.3465% | 0.7657 | 0.6425 | 0.5856 |
| Todas | 180 | 25974 | 78 | 17 | 0.3003% | 0.7826 | 0.0435 | 0.4146 |
| Sem rotineiros | 90 | 25974 | 142 | 42 | 0.5467% | 0.6710 | 0.4926 | 0.4627 |
| Sem rotineiros | 120 | 25974 | 117 | 34 | 0.4505% | 0.6622 | 0.4144 | 0.2898 |
| Sem rotineiros | 180 | 25974 | 90 | 21 | 0.3465% | 0.6838 | 0.0810 | 0.1794 |


### Diagnóstico de persistência

| Atividade | H | Positivos | Já sem atividade há H dias | Fração persistente | Positivos com recência <=30d | Contas positivas já positivas no treino |
|---|---|---|---|---|---|---|
| Todas | 90 | 149 | 108 | 72.4832% | 22 | 6 |
| Todas | 120 | 119 | 80 | 67.2269% | 13 | 3 |
| Todas | 180 | 78 | 42 | 53.8462% | 8 | 2 |
| Sem rotineiros | 90 | 205 | 127 | 61.9512% | 34 | 8 |
| Sem rotineiros | 120 | 154 | 91 | 59.0909% | 24 | 5 |
| Sem rotineiros | 180 | 90 | 45 | 50.0000% | 10 | 2 |


### Recência: diagnóstico somente entre contas ativas nos últimos 30 dias

| Atividade | H | Snapshots | Positivos | Contas positivas | Prevalência | AP | Recall congelado |
|---|---|---|---|---|---|---|---|
| Todas | 90 | 39295 | 22 | 14 | 0.0560% | 0.1378 | 0.0000 |
| Todas | 120 | 34815 | 13 | 12 | 0.0373% | 0.0362 | 0.0000 |
| Todas | 180 | 25855 | 8 | 7 | 0.0309% | 0.0362 | 0.0000 |
| Sem rotineiros | 90 | 39165 | 34 | 28 | 0.0868% | 0.0155 | 0.0000 |
| Sem rotineiros | 120 | 34705 | 24 | 22 | 0.0692% | 0.0179 | 0.0000 |
| Sem rotineiros | 180 | 25774 | 10 | 9 | 0.0388% | 0.0042 | 0.0000 |


### Expanding windows: performance separada por janela

| Atividade | H | Janela | Contas positivas treino | Positivos avaliação | Contas positivas avaliação | AP prevalência | AP recência | AP logística | AP HGB | Seleção pela validação | Fallback treino sem positivos |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Todas | 90 | 1 | 0 | 17 | 8 | 0.0018 | 0.0018 | 0.0018 | 0.0018 | Prevalência | sim |
| Todas | 90 | 2 | 0 | 20 | 7 | 0.0019 | 0.0019 | 0.0019 | 0.0019 | Prevalência | sim |
| Todas | 120 | 1 | 0 | 15 | 7 | 0.0016 | 0.0016 | 0.0016 | 0.0016 | Prevalência | sim |
| Todas | 120 | 2 | 0 | 20 | 7 | 0.0019 | 0.0019 | 0.0019 | 0.0019 | Prevalência | sim |
| Todas | 180 | 1 | 0 | 14 | 6 | 0.0015 | 0.0015 | 0.0015 | 0.0015 | Prevalência | sim |
| Todas | 180 | 2 | 0 | 18 | 6 | 0.0017 | 0.0017 | 0.0017 | 0.0017 | Prevalência | sim |
| Sem rotineiros | 90 | 1 | 2 | 24 | 11 | 0.0025 | 0.4179 | 0.2148 | 0.0454 | Logística | não |
| Sem rotineiros | 90 | 2 | 4 | 30 | 13 | 0.0029 | 0.7296 | 0.2349 | 0.3555 | Recência | não |
| Sem rotineiros | 120 | 1 | 2 | 22 | 10 | 0.0023 | 0.4103 | 0.1707 | 0.0034 | Logística | não |
| Sem rotineiros | 120 | 2 | 4 | 27 | 11 | 0.0026 | 0.7617 | 0.2341 | 0.3566 | Recência | não |
| Sem rotineiros | 180 | 1 | 2 | 20 | 9 | 0.0021 | 0.3790 | 0.0664 | 0.0041 | Logística | não |
| Sem rotineiros | 180 | 2 | 2 | 21 | 7 | 0.0020 | 0.8357 | 0.0580 | 0.0470 | HGB | não |


### Estabilidade mensal no TEST, H=90, recência congelada

| Atividade | T | Positivos | AP | Brier |
|---|---|---|---|---|
| Todas | 1998-01-31 | 19 | 0.7497 | 0.002404 |
| Todas | 1998-02-28 | 15 | 0.7959 | 0.001730 |
| Todas | 1998-03-31 | 18 | 0.7069 | 0.002166 |
| Todas | 1998-04-30 | 18 | 0.8216 | 0.001866 |
| Todas | 1998-05-31 | 16 | 0.8430 | 0.001292 |
| Todas | 1998-06-30 | 16 | 0.8494 | 0.001381 |
| Todas | 1998-07-31 | 16 | 0.8501 | 0.001168 |
| Todas | 1998-08-31 | 15 | 0.9438 | 0.000686 |
| Todas | 1998-09-30 | 16 | 0.9036 | 0.000904 |
| Sem rotineiros | 1998-01-31 | 28 | 0.6637 | 0.004351 |
| Sem rotineiros | 1998-02-28 | 23 | 0.7218 | 0.003332 |
| Sem rotineiros | 1998-03-31 | 24 | 0.6849 | 0.003192 |
| Sem rotineiros | 1998-04-30 | 23 | 0.6853 | 0.002840 |
| Sem rotineiros | 1998-05-31 | 21 | 0.7542 | 0.002127 |
| Sem rotineiros | 1998-06-30 | 23 | 0.6732 | 0.002954 |
| Sem rotineiros | 1998-07-31 | 22 | 0.7623 | 0.002321 |
| Sem rotineiros | 1998-08-31 | 20 | 0.7567 | 0.001929 |
| Sem rotineiros | 1998-09-30 | 21 | 0.7724 | 0.001930 |

## Interpretação e investigação dos resultados altos

**O principal sinal é a persistência de inatividade já observável.** A recência selecionada corresponde a classificar `recency_days >= 51`, cutoff escolhido exclusivamente na validação, nos seis experimentos. H=90 alcança AP 0,8224 [0,6536; 0,9103] e 0,6965 [0,5342; 0,8035], para todas as transações e sem rotineiros. O lift de 217,9 e 134,1 vezes precisa ser lido junto às prevalências muito pequenas, 0,3775% e 0,5193%; não significa 218 vezes mais clientes detectados nem capacidade equivalente para antecipar novos episódios.

Há 108/149 positivos (72,48%) e 127/205 (61,95%) já sem atividade há pelo menos 90 dias em T. Somente 27 e 46 contas geram todos esses positivos. As cinco contas com mais positivos respondem por 45/149 (30,20%) e 45/205 (21,95%) deles. Portanto, 39.474 linhas de TEST não são 39.474 eventos independentes. O bootstrap por conta reflete parte dessa fragilidade.

Para investigar leakage e artefatos, além dos testes sintéticos:

1. Selecionamos 30 contas aleatórias com seed fixa e acrescentamos todas as contas positivas do TEST: **76 contas**. Em três datas (1996-12-31, 1997-06-30, 1998-06-30), reconstruímos as features dos dois escopos após remover todas as transações posteriores a T. Nenhum valor mudou. Para os três H, os labels também foram conferidos por filtragem direta do intervalo: **18 verificações escopo/data/H**.
2. Verificamos que os artefatos mantêm os hashes congelados, que nenhum identificador está na entrada dos modelos e que as previsões dos 24 modelos serializados reproduzem os CSVs salvos. Na leitura das features, `float_precision='round_trip'` é necessário: diferenças mínimas do parser padrão podem atravessar uma fronteira de árvore. Isso foi corrigido no replay, sem alterar os resultados originais.
3. As métricas foram repetidas, sem novos ajustes, em contas recentemente ativas, em contas ainda não inativas por H dias, em calendário comum e em contas nunca positivas no treino. Os dois escopos foram mantidos. A EDA já havia mostrado a forte periodicidade dos lançamentos de juros/tarifas no fim do mês; ela pode tornar a ausência desses lançamentos especialmente informativa na primeira definição.

Os checks não encontraram evidência de uso de futuro nas features ou sobreposição indevida dos targets. Isso não prova ausência de problemas na captura original nem valida o significado econômico dos registros. A combinação de snapshots no fim do mês, lançamentos periódicos e persistência do target é uma explicação mais sustentada para o desempenho alto do que uma interpretação ampla de antecipação de churn.

### Atividade recente: sinal residual e limites

Restringir o TEST a `recency_days <= 30` é um diagnóstico de uma população distinta, feito **sem trocar modelo ou threshold**. Não transforma o target principal em incidência: até 30 dias de silêncio ainda podem estar presentes em T. O tamanho efetivo continua pequeno.

| Atividade | H | AP recência [IC95%] | AP HGB [IC95%] | Contas positivas |
|---|---|---|---|---|
| Todas | 90 | 0,1378 [0,0468; 0,2752] | 0,2418 [0,1388; 0,4685] | 14 |
| Todas | 120 | 0,0362 [0,0079; 0,1589] | 0,1269 [0,0327; 0,3965] | 12 |
| Todas | 180 | 0,0362 [0,0171; 0,0970] | 0,1435 [0,0129; 0,4786] | 7 |
| Sem rotineiros | 90 | 0,0155 [0,0038; 0,0635] | 0,2775 [0,1522; 0,4270] | 28 |
| Sem rotineiros | 120 | 0,0179 [0,0026; 0,0795] | 0,1025 [0,0530; 0,2253] | 22 |
| Sem rotineiros | 180 | 0,0042 [0,0010; 0,0176] | 0,0944 [0,0377; 0,2354] | 9 |

O cutoff congelado de recência, 51 dias, produz **recall zero** nessa coorte por construção. Em H=90, o HGB já treinado detecta 17/22 positivos com 99 falsos positivos (precision 14,66%; recall 77,27%) e 24/34 com 146 falsos positivos (precision 14,12%; recall 70,59%). Existe sinal residual além da recência nessas contas, mas com precisão operacional modesta, intervalos amplos e poucas contas. Esse diagnóstico de TEST não autoriza substituir o vencedor da validação por HGB. Uma tarefa restrita à população recentemente ativa precisaria ser pré-especificada e avaliada em novos períodos.

Entre contas com `recency_days < H`, a AP da recência em H=90 é 0,3454 e 0,2505: menor do que na população completa. Excluir contas já positivas no treino ainda deixa AP 0,7916 e 0,6515, com 21 e 38 contas positivas. Portanto, memorizar contas anteriormente positivas não explica sozinho o resultado; isso tampouco constitui teste de contas inteiramente desconhecidas.

### Comparação com baselines e calibração

O baseline probabilístico usa a prevalência do treino, não a do TEST. Sua AP no TEST é exatamente a prevalência avaliada e seu lift é 1. A recência o supera nas seis combinações, mas os modelos com 36 features **não superam a recência em AP global**.

Em H=90, a diferença AP logística − recência é −0,1913, IC95% pareado [−0,2831; −0,0376], com todas as transações; HGB − recência é −0,1480 [−0,2660; −0,0135]. Sem rotineiros, as diferenças são −0,2415 [−0,3597; −0,0731] e −0,2229 [−0,3146; −0,0915]. Os intervalos pareados também são negativos nos outros horizontes. São comparações condicionais e não ajustadas por multiplicidade; não constituem superioridade universal entre algoritmos.

As probabilidades da recência **subestimam o risco médio no TEST**:

| Atividade | H | Probabilidade média prevista | Prevalência observada |
|---|---|---|---|
| Todas | 90 | 0,2574% | 0,3775% |
| Todas | 120 | 0,1648% | 0,3403% |
| Todas | 180 | 0,0297% | 0,3003% |
| Sem rotineiros | 90 | 0,3877% | 0,5193% |
| Sem rotineiros | 120 | 0,3197% | 0,4403% |
| Sem rotineiros | 180 | 0,1632% | 0,3465% |

H=180 com todas as transações é especialmente problemático: a probabilidade média é aproximadamente **dez vezes menor** que a taxa observada, apesar da AP 0,7826. A recência melhora o Brier frente ao dummy, mas não fornece probabilidades adequadamente calibradas de forma geral. Por exemplo, em H=90, todas as transações, o bin de probabilidade (0,25; 0,5] prevê média 0,3809 para frequência observada 0,7429, em apenas 35 snapshots. A escassez de eventos e a mudança de prevalência entre treino e TEST limitam o ajuste; não foi aplicada correção usando o TEST.

Curvas locais: [H=90, todas](../outputs/berka/inactivity_prediction/validated/all_transactions_h90/test_curves.png) e [H=90, sem rotineiros](../outputs/berka/inactivity_prediction/validated/excluding_routine_h90/test_curves.png). O gráfico PR é em degraus, coerente com AP não interpolada. As tabelas de calibração incluem denominadores por bin.

## Estabilidade temporal e sensibilidade

Os cortes adicionais são anteriores ao TEST de 1998 e não selecionam o período mais favorável:

- Janela 1: validação nominal a partir de 1996-04-01, avaliação de T=1997-01-31 a 1997-03-31 (9.440 snapshots, 3.264 contas).
- Janela 2: validação nominal a partir de 1996-07-01, avaliação de T=1997-04-30 a 1997-06-30 (10.467 snapshots, 3.606 contas).

Cada janela recomeça o treino no início do histórico e expande o limite final, com purge por H antes da validação e da avaliação. Todos os labels da avaliação terminam antes de 1998-01-01; para H=90/120/180, o último dia de target da janela 1 é 1997-06-29/07-29/09-27, e da janela 2 é 1997-09-28/10-28/12-27. `stability_splits.csv` registra todos os intervalos de treino/validação/avaliação e contagens.

Para todas as transações, ambos os cortes têm **zero positivos no treino**. As linhas marcadas como fallback são previsões constantes, não modelos discriminativos treinados. Não há dados suficientes para demonstrar estabilidade histórica dessa definição por esse protocolo.

Sem rotineiros, H=90 treina com apenas 2 e 4 contas positivas: AP da recência varia de 0,4179 para 0,7296; HGB de 0,0454 para 0,3555. A logística é selecionada na validação da primeira janela, mas tem AP de avaliação 0,2148. Em H=180, a seleção da segunda janela escolhe HGB e sua AP de avaliação é só 0,0470, frente a 0,8357 da recência. Isso expõe **instabilidade da seleção com validações pequenas**, sem escolher retrospectivamente o melhor modelo da janela.

No TEST mensal de H=90, a AP da recência varia entre 0,7069–0,9438 (todas) e 0,6637–0,7724 (sem rotineiros). São meses correlacionados e muitos positivos persistentes; a regularidade em 1998 não resolve a insuficiência dos cortes anteriores.

A análise principal permanece H=90. Em H=120/180, a AP global da recência continua alta, mas os treinos ficam menores, a calibração piora e a logística perde desempenho: em H=180, ROC-AUC 0,2539/0,4963 e AP 0,0435/0,0810, com apenas 3/10 contas positivas no treino. Não ajustamos novos hiperparâmetros depois de ver essa falha.

O calendário comum janeiro–junho de 1998 mantém exatamente 25.974 snapshots por combinação, evitando atribuir a H uma diferença que venha de meses distintos. Nele, AP da recência é 0,7826/0,7657/0,7826 para H=90/120/180, todas as transações, e 0,6710/0,6622/0,6838 sem rotineiros. A conclusão qualitativa se mantém: forte ranking de persistência, falta de ganho global dos modelos mais complexos e evidência limitada de antecipação ampla.

## Verificação, limitações e conclusão quantitativa

Executados **27 testes automatizados**, todos aprovados, incluindo os 12 testes anteriores. Verificam invariância a mudanças futuras, features em T e início aberto das janelas, target `(T,T+H]`, censura, histórico mínimo, purge para os três H, ausência de IDs, ajuste do preprocessamento somente no treino, escolhas pela validação, isolamento do TEST, bootstrap por conta, métricas ponderadas contra scikit-learn, fallback explícito e reprodução de probabilidades após exportação/importação. `compileall` e `git diff --check` passaram. A EDA também foi executada após remover o relatório narrativo embutido. A execução principal levou aproximadamente **99 segundos**, em CPU com limite de quatro threads, mais a auditoria suplementar; não há dependência de CUDA.

O [manifesto de referência](berka_inactivity_prediction_reference.json) preserva ambiente, parâmetros, provenance, hashes, resultados e verificação. O manifesto original conserva os hashes do código utilizado no treino; `postprocessing_audit` registra os hashes posteriores, a correção visual PR e os diagnósticos sem retreinamento. Os 24 conjuntos de predições foram reproduzidos dos modelos salvos com tolerância numérica de 1e−10 relativa/1e−12 absoluta.

As principais limitações são: ausência de encerramento observado; cobertura administrativa presumida; periodicidade de juros/tarifas; um único banco/período; poucas contas positivas; janelas correlacionadas; prevalência crescente; ICs condicionais sem incerteza de seleção; e ausência de confirmação independente em período posterior a 1998. Os ICs não justificam extrapolação para clientes, bancos ou regimes distintos.

**Conclusão:** há sinal quantitativo forte para **continuar ou entrar em ausência de atividade na população completa**, com AP de H=90 em 0,8224/0,6965, mas grande parte dele já está resumida na recência e em episódios em andamento. O threshold selecionado é simplesmente 51 dias sem atividade, e a recência supera logística e HGB na avaliação global. Para antecipar inatividade entre contas ativas nos últimos 30 dias, a evidência é menor e incerta: HGB chega a AP 0,2418/0,2775, com precision perto de 14%, somente 14/28 contas positivas e intervalos amplos. Calibração insuficiente e instabilidade nos cortes antigos impedem afirmar prontidão operacional ou capacidade robusta de prever novos episódios. **Nada desses resultados demonstra previsão de churn efetivo.**
