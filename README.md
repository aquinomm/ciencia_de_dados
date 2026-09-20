# Ciência de Dados — exploração de dados bancários

Projeto acadêmico em grupo para formular uma pergunta de análise de dados, estudar a qualidade e a adequação das bases e discutir a viabilidade com o mentor. O trabalho está em **fase exploratória**: ainda não foram definidos o dataset nem o problema final. Churn, fraude e outros problemas descritivos ou preditivos continuam em aberto.

A análise atual do Berka investiga comportamento transacional e possíveis definições temporais de inatividade. **Não há rótulo explícito de churn no Berka.** Uma proxy derivada de transações não é ground truth de encerramento da relação bancária. Resultados exploratórios não devem ser apresentados como conclusões finais sobre clientes ou sobre o projeto.

## Bases consideradas

| Alternativa | Natureza e origem | Situação no projeto |
| --- | --- | --- |
| PKDD'99 / Berka Financial Dataset | Dataset bancário real, anonimizado e relacional; extraído do banco `financial` do [CTU Relational Repository](https://relational.fel.cvut.cz/dataset/Financial). | EDA por conta, com histórico completo, gaps e snapshots temporais. A ausência de churn observado limita essa aplicação. |
| Sparkov / dados sintéticos | O [Sparkov Data Generation](https://github.com/namebrandon/Sparkov_Data_Generation) gera transações sintéticas, incluindo fraude simulada. | Alternativa para estudo. O rascunho local não foi redesenhado nem os dados ajustados para imitar o Berka. A proveniência exata da geração local ainda precisa ser documentada. |

A estrutura relacional do Berka inclui contas, clientes, disposições, transações, ordens, empréstimos, cartões e distritos. A EDA atual extrai somente `account`, `trans` e os vínculos `OWNER` de `disp`. `DISPONENT` não vira uma segunda observação da conta. Não é necessário juntar todas as tabelas para responder à pergunta atual.

## Estrutura

```text
README.md
requirements.txt
.gitattributes                 # padronização LF para código e documentação
.gitignore                     # ambiente, segredos, dados e outputs locais
dataset_pk99/
  data.py                      # consultas SQL, conexão e cache verificável
  eda.py                       # EDA temporal e interface de linha de comando
dataset_generated/
  eda.py                       # rascunho sintético; lógica analítica preservada
  customers.csv                # local, não versionado
  transactions.csv             # local, não versionado
docs/
  berka_eda.md                  # evidências revisadas e perguntas para o mentor
  berka_reference_manifest.json # parâmetros, versões e hashes da execução registrada
tests/
  test_berka_temporal.py        # testes pequenos de limites temporais e censura
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

Dependências diretas: pandas (tabelas e datas), NumPy (busca vetorizada no histórico), mysql-connector-python (extração SQL) e Matplotlib (gráficos estáticos). Matplotlib foi adicionado para visualizar caudas dos gaps e evolução temporal. Faker foi removido porque este repositório não executa um gerador; python-dateutil e six não são usados diretamente e dependências transitivas ficam a cargo do instalador. As versões diretas estão fixadas no `requirements.txt`; o manifesto registra o ambiente executado.

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

Cada execução gera `report.txt`, `run_manifest.json`, `transaction_composition.csv`, `monthly_coverage.csv`, `gap_summary.csv` e `target_summary.csv`. Cada escopo também contém:

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

Uma conta pode aparecer em múltiplos snapshots com janelas sobrepostas. As observações **não são independentes**. Uma futura avaliação deverá respeitar conta e temporalidade, impedir compartilhamento de contas entre os conjuntos conforme o desenho escolhido e purgar janelas de rótulo que atravessem o corte. Não fazer divisão aleatória de linhas. Contagens por conta e sequências positivas ajudam a não confundir snapshots repetidos com novos eventos.

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

## Decisões em aberto

Veja [evidências e questões para o mentor](docs/berka_eda.md). Ainda precisamos decidir o dataset, a pergunta, o que conta como atividade, a população em risco, H, histórico mínimo, protocolo temporal e critérios de suficiência de exemplos. Se inatividade não for conceitualmente defensável ou tiver poucas contas/eventos, devemos considerar outra pergunta no Berka ou outra base. Não há modelagem, balanceamento, geração artificial de positivos ou tuning nesta etapa.
