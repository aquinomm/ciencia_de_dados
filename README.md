# Ciência de Dados — exploração de dados bancários

Projeto acadêmico em grupo para estudar dados bancários e discutir a viabilidade com o mentor. **A exploração do Berka com dormancy/churn como alvo preditivo principal está encerrada nesta branch, `berka-temporal`.** Os experimentos não ofereceram suporte suficiente para manter essa direção como eixo preditivo principal do projeto: poucos eventos em contas distintas, incerteza elevada e desempenho sem estabilidade temporal suficiente.

**Não há rótulo explícito de churn no Berka.** Os experimentos avaliaram inatividade comportamental observada, incluindo a transição de contas ativas para ausência futura de atividade; não demonstram encerramento da relação bancária. Os resultados elevados na população geral refletiam, em grande parte, persistência de inatividade já em andamento. A [avaliação prospectiva de transição](docs/berka_activity_transition.md) documenta por que o sinal restante não sustenta essa aplicação como resultado preditivo principal.

Esse encerramento **não invalida o Berka como dataset**. Caso ele seja mantido, o próximo passo será mudar o pivô para um fenômeno efetivamente observado nos dados, como empréstimos/default, ou outro alvo diretamente sustentado pela base. **Essa mudança ainda não é uma decisão final do projeto**: é uma direção condicional decorrente da conclusão desta branch. Nenhum novo alvo foi implementado. Código, testes, resultados e documentação da investigação permanecem preservados para consulta e reprodução.

## Bases consideradas

| Alternativa | Natureza e origem | Situação no projeto |
| --- | --- | --- |
| PKDD'99 / Berka Financial Dataset | Dataset bancário real, anonimizado e relacional; extraído do banco `financial` do [CTU Relational Repository](https://relational.fel.cvut.cz/dataset/Financial). | Investigação de dormancy/churn encerrada como eixo preditivo principal. O dataset continua sendo uma possibilidade para outro alvo; sua permanência não foi decidida. |
| Sparkov / dados sintéticos | O [Sparkov Data Generation](https://github.com/namebrandon/Sparkov_Data_Generation) gera transações sintéticas, incluindo fraude simulada. | Alternativa para estudo. O rascunho local não foi redesenhado nem os dados ajustados para imitar o Berka. A proveniência exata da geração local ainda precisa ser documentada. |

A estrutura relacional do Berka inclui contas, clientes, disposições, transações, ordens, empréstimos, cartões e distritos. A EDA registrada extrai somente `account`, `trans` e os vínculos `OWNER` de `disp`. `DISPONENT` não vira uma segunda observação da conta. Esse recorte atende à pergunta de inatividade investigada nesta branch.

## Estrutura

```text
README.md
requirements.txt
.gitattributes                 # padronização LF para código e documentação
.gitignore                     # ambiente, segredos, dados e outputs locais
dataset_pk99/
  data.py                      # consultas SQL, conexão e cache verificável
  eda.py                       # EDA temporal e interface de linha de comando
  predict_inactivity.py        # execução da previsão temporal em CPU
  inactivity_features.py      # features disponíveis em T e targets futuros
  inactivity_evaluation.py    # purge, seleção, métricas e bootstrap por conta
  audit_inactivity.py         # auditoria de execução congelada, sem retreinamento
  activity_transition.py     # população ativa e contagem de episódios distintos
  predict_activity_transition.py # experimento prospectivo registrado; exige berka-temporal
dataset_generated/
  eda.py                       # rascunho sintético; lógica analítica preservada
  customers.csv                # local, não versionado
  transactions.csv             # local, não versionado
docs/
  berka_eda.md                  # evidências revisadas e perguntas para o mentor
  berka_inactivity_prediction.md # metodologia, resultados e limitações da previsão
  berka_activity_transition.md # experimento ativo → inativo e conclusão de viabilidade
  berka_reference_manifest.json # parâmetros, versões e hashes da execução registrada
tests/
  test_berka_temporal.py        # testes pequenos de limites temporais e censura
  test_inactivity_prediction.py # leakage, seleção e incerteza agrupada
  test_activity_transition.py # elegibilidade prospectiva, episódios e isolamento
data/berka/                    # cache de extração; não versionado
outputs/berka/                 # CSVs, gráficos e relatórios gerados; não versionados
```

## Ambiente

Python **3.11 ou superior**; execução registrada com Python 3.14.4. No PowerShell, a partir da raiz do repositório:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\Activate.ps1
```

Se não quiser ativar o ambiente, substitua `python` nos comandos abaixo por `.\.venv\Scripts\python.exe`. Em Linux/macOS, use `.venv/bin/python` e, opcionalmente, `source .venv/bin/activate`.

Dependências diretas: pandas, NumPy, mysql-connector-python, Matplotlib, scikit-learn, joblib e threadpoolctl. As versões estão fixadas em `requirements.txt`; os manifestos registram o ambiente. Os experimentos são executáveis em CPU, sem CUDA.

## Executar o Berka

```powershell
python -X utf8 -m dataset_pk99.eda
```

A execução padrão consulta o servidor, salva cache em `data/berka/` e cria um diretório de resultados com data/hora em `outputs/berka/`. Requer internet e acesso MySQL à porta 3306. A conexão e o cursor são fechados inclusive em caso de falha. Nenhuma consulta modifica o banco.

O acesso público padrão é `relational.fel.cvut.cz:3306`, banco `financial`, usuário `guest` e senha pública `ctu-relational`. Pode ser substituído pelas variáveis de ambiente `BERKA_DB_HOST`, `BERKA_DB_PORT`, `BERKA_DB_NAME`, `BERKA_DB_USER` e `BERKA_DB_PASSWORD`. Arquivos `.env` são ignorados pelo Git, mas **não são carregados automaticamente**. Não registre credenciais privadas em código.

Para repetir exatamente a extração armazenada, sem nova consulta:

```powershell
python -X utf8 -m dataset_pk99.eda --source cache
```

O cache contém CSVs comprimidos e `manifest.json` com origem, horário UTC, consultas, contagens e SHA-256. O modo cache verifica integridade e compatibilidade. Não há fallback silencioso para uma extração antiga. Sem banco e sem cache completo, a EDA não pode produzir resultados reais.

Exemplos de configuração:

```powershell
python -X utf8 -m dataset_pk99.eda --source cache --history-days 90 180 365 --min-transactions 1 5 --horizons 90 120 180 --thresholds 90 120 180 --snapshot-freq ME
python -X utf8 -m dataset_pk99.eda --source cache --snapshot-dates 1996-06-30 1997-06-30 1998-06-30
python -X utf8 -m dataset_pk99.eda --source cache --history-days 180 --min-transactions 5 --max-recency-days 30
python -X utf8 -m dataset_pk99.eda --help
```

Também há `--snapshot-start`, `--snapshot-end`, `--reactivation-days`, `--scopes`, `--cache-dir` e `--output-dir`. Datas explícitas substituem a frequência; não podem ser combinadas com os limites do calendário. Use uma pasta de saída vazia para não misturar execuções. `ME` significa fim de mês; `QS`, início de trimestre.

### Definição temporal

A unidade é `account_id`. Para cada data `T`, a contagem histórica inclui o próprio dia `T`. Uma conta é elegível quando:

1. Já está aberta; o período observado começa em `max(abertura, início global da extração)`.
2. Tem ao menos o histórico mínimo configurado tanto desde esse início quanto desde sua primeira transação do escopo analisado, conhecida em `T`.
3. Tem ao menos o número mínimo de transações até `T`; se solicitado, satisfaz a recência máxima em `T`.
4. `T + H` não ultrapassa o fim global da extração.

`future_inactivity_flag = 1` significa **nenhuma transação em `(T, T + H]`**; `0` significa ao menos uma. Janelas incompletas são excluídas, nunca transformadas em positivos. Datas têm resolução de um dia; `H` representa dias corridos, não meses.

Por padrão, são testados históricos de 90/180/365 dias, mínimos de 1/5 transações, horizontes de 90/120/180 dias e snapshots mensais. São alternativas exploratórias, sem escolha baseada na conveniência da proporção de classe. `all_complete` usa todas as janelas completas para cada H; `common_calendar` restringe todos os H ao mesmo calendário completo para o maior horizonte, permitindo comparar H sem mudar as datas da coorte.

São analisados dois escopos: `all_transactions` e `excluding_routine`. O segundo exclui os símbolos `UROK`, `SLUZBY` e `SANKC. UROK` (juros e tarifas selecionados) como sensibilidade ao conceito de atividade. Outros pagamentos ou transferências podem ser automáticos; esse filtro **não prova iniciativa do cliente** e não constitui uma definição de atividade aprovada.

O limite global de observação é uma hipótese de cobertura administrativa: a última transação de uma conta não é usada para encerrar seu acompanhamento. A base não permite comprovar cobertura contínua de cada conta nem seu encerramento real.

### Outputs e interpretação

Cada execução gera `run_manifest.json`, `transaction_composition.csv`, `monthly_coverage.csv`, `gap_summary.csv` e `target_summary.csv`. A interpretação está em `docs/berka_eda.md`; o código não gera narrativa analítica. Cada escopo também contém:

| Arquivo | Uso |
| --- | --- |
| `account_metrics.csv`, `account_distribution.csv` | Abertura, primeira/última atividade, tempo observado, frequência, gaps e recência. Descrevem o período completo; **não usar como preditores em T**. |
| `gap_distribution.csv` | Intervalos entre transações (inclui zeros no mesmo dia) e entre dias ativos distintos. |
| `long_gap_episodes.csv`, `gap_counts_by_account.csv` | Episódios acima do menor threshold, retornos e períodos terminais censurados; distribuição da quantidade de episódios por conta. |
| `features_by_snapshot.csv.gz` | Somente informações disponíveis até T, inclusive candidatos ainda sem histórico elegível. |
| `future_labels.csv.gz` | Rótulos com futuro completo, elegíveis sob os menores histórico/contagem configurados. Para outras regras, juntar por conta/T e reaplicar elegibilidade. `next_transaction_after_T` é diagnóstico futuro, **nunca preditor**. |
| `eligibility_by_snapshot.csv` | Contas abertas, filtros de histórico, contagem, recência e exclusão por futuro incompleto, por T/H/configuração. |
| `target_summary.csv`, `target_by_snapshot.csv` | Prevalências, positivos, contas distintas, sequências positivas e acompanhamento posterior. |
| `overview.png` | Distribuição dos gaps, recência e prevalência por T. |

Um gap encerrado mede a diferença entre datas de dias ativos consecutivos; no episódio terminal, a diferença até o fim da base é apenas um limite inferior da duração. O critério é estritamente `gap_days > threshold`. Contas sem qualquer transação não geram episódios após atividade e são excluídas dos targets pela elegibilidade. O intervalo abertura–primeira transação é descrito separadamente.

Gaps encerrados sempre apresentam retorno por construção. As taxas de retorno observadas incluem também episódios terminais e **não são probabilidades de retorno definitivo**. Para reduzir diferenças de tempo de acompanhamento, também são calculados retornos em 180 dias após `início_do_gap + threshold`, só quando essa janela está completa. Para snapshots positivos, o acompanhamento fixo começa em `T + H`. Os denominadores constam dos CSVs; ausência de denominador produz valor ausente, não taxa zero.

Uma conta pode aparecer em múltiplos snapshots com janelas sobrepostas. As observações **não são independentes**. A previsão implementada permite a mesma conta em períodos diferentes, pois avalia generalização temporal, e purga janelas de rótulo que atravessem o corte. A incerteza usa bootstrap por conta. Não há divisão aleatória de linhas.

## Registro do experimento: transição ativo → inativo

As instruções abaixo preservam a reprodução da investigação encerrada. Para reproduzir esse experimento, utilize a branch `berka-temporal`. O programa verifica a branch e recusa executar em outra; não faz checkout, commit ou push.

```powershell
python -X utf8 -m dataset_pk99.predict_activity_transition --source cache --output-dir outputs/berka/activity_transition/reproduction
python -X utf8 -m unittest discover -s tests -v
```

Sem o cache financeiro `data/berka_prediction/`, use `--source database` na primeira execução. Leia [metodologia, auditoria de episódios e resultados](docs/berka_activity_transition.md).

A população principal exige `recency_days <= 30` **antes dos targets e de todos os splits/ajustes**. Sensibilidades: 15/60 dias de atividade recente e H=120/180, com H=90 principal; ambas as definições de atividade são mantidas. Snapshots mensais, histórico mínimo 180 dias, validação nominal em 1997 e TEST em 1998, com purge por H. Datas não são deslocadas para esconder treinos sem positivos. Modelos indisponíveis por treino de classe única são sinalizados explicitamente.

Há três baselines (prevalência, recência, frequência recente), logística e HistGradientBoosting; AP seleciona na validação e F2 define o threshold. Os arquivos incluem snapshots positivos, episódios desduplicados, contas positivas, contagens mensais, gaps não capturados pelo calendário, ICs por conta e cortes temporais anteriores. `--previous-run outputs/berka/inactivity_prediction/validated` acrescenta uma comparação diagnóstica após o TEST; nenhum modelo anterior é reutilizado.

Parâmetros: `--active-windows 30 15 60`, `--horizons 90 120 180`, `--snapshot-freq ME`, `--history-days 180`, `--bootstrap-repetitions 1000`, `--seed 20260921`, `--threads 4`; consulte `--help`. A saída de cada execução deve ser uma pasta vazia.

## Experimento anterior: inatividade futura na população geral

Consulte [metodologia e resultados](docs/berka_inactivity_prediction.md). A primeira extração precisa incluir `amount` e `balance`, em cache separado e verificável:

```powershell
python -X utf8 -m dataset_pk99.predict_inactivity --source database
python -X utf8 -m dataset_pk99.predict_inactivity --source cache
python -X utf8 -m dataset_pk99.predict_inactivity --help
```

O primeiro comando também executa a análise; os demais reaproveitam o cache `data/berka_prediction/`. Os resultados ficam em `outputs/berka/inactivity_prediction/<execução>/`. O cache anterior da EDA continua compatível. A previsão requer também scikit-learn, joblib e threadpoolctl, fixados nos requisitos; não exige GPU.

Padrões: snapshots mensais (`ME`), histórico observável mínimo de 180 dias, ao menos uma atividade histórica, horizontes 90/120/180 dias e ambas as definições de atividade. Validação começa em 1997-04-01 e TEST em 1998-01-01, com purge específico para H. Features, hiperparâmetros e thresholds são congelados antes da avaliação final. A seleção usa AP na validação; thresholds usam F2 na validação. Há dois cortes anteriores ao TEST e 1.000 réplicas de bootstrap por conta, seed 20260920. Não há SMOTE nem pesos de classe.

As opções `--snapshot-freq`, `--history-days`, `--min-transactions`, `--horizons`, `--scopes`, `--validation-start`, `--test-start`, `--bootstrap-repetitions`, `--threads` e `--seed` permitem reproduzir outras configurações. `--no-stability` desativa os cortes adicionais. `--output-dir` deve apontar para uma pasta vazia. Os CSVs contêm métricas, splits, perdas por elegibilidade, previsões e intervalos; os JSONs registram configuração, candidatos, thresholds, hashes e versões. Curvas PR/ROC e calibração são salvas em PNG.

Para repetir também a auditoria de leakage com dados reais e os ICs da coorte recentemente ativa, execute `python -X utf8 -m dataset_pk99.audit_inactivity --output-dir outputs/berka/inactivity_prediction/<execução>`. Esse comando verifica os artefatos congelados e reproduz previsões; não treina nem seleciona modelos.

## Análise sintética existente

Obtenha os arquivos locais do grupo e coloque `customers.csv` e `transactions.csv` em `dataset_generated/`. O CSV de clientes usa `|`; o de transações usa vírgula.

```powershell
python -X utf8 dataset_generated/eda.py
```

O rascunho registra seed 1234, 6.000 clientes e período de 2025-01-01 a 2026-01-01. Faltam a revisão do gerador, os perfis, o comando original e a localização estável dos arquivos para uma reprodução completa. Esses comentários não comprovam sozinhos a proveniência dos CSVs disponíveis. O script mantém seu cálculo exploratório anterior; o nome interno `flag_churn` é legado e a saída agora explicita que se trata de proxy. A análise carrega os CSVs em memória; o arquivo de transações local tem aproximadamente 1,65 GB. Não foi executada nem redesenhada nesta tarefa.

## Dados não versionados e validação

Datasets, cache, gráficos e outputs gerados ficam locais. Código, testes, requisitos, documentação e o manifesto de referência são versionados. O `.gitignore` usa caminhos específicos para dados, preservando a possibilidade de versionar pequenos CSVs de referência ou testes. LF é padronizado em arquivos de código e documentação; não é necessário renormalizar datasets.

```powershell
python -m compileall -q dataset_pk99 dataset_generated tests
python -X utf8 -m unittest discover -s tests -v
```

Os testes verificam fronteiras em T/T+H, exclusão de futuro incompleto, invariância das features a alterações futuras, elegibilidade, integridade de vínculos e censura/reativação.

## Conclusão da branch e direção ainda em aberto

As [evidências da EDA](docs/berka_eda.md), o [experimento na população geral](docs/berka_inactivity_prediction.md) e a [avaliação de transição](docs/berka_activity_transition.md) fundamentam o encerramento de dormancy/churn como alvo preditivo principal no Berka. A conclusão preserva o valor da investigação, mas não recomenda manter essa linha como eixo preditivo do projeto.

A escolha final do dataset e do problema permanece em aberto para discussão do grupo com o mentor. Se o Berka for mantido, será necessário avaliar um alvo diretamente observado, como empréstimos/default, incluindo sua definição e viabilidade. Essa possibilidade não representa um alvo já escolhido, validado ou implementado; o fechamento aqui se limita à conclusão desta branch.
