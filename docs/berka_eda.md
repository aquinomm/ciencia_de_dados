# Berka: evidências exploratórias de comportamento e inatividade

Execução de 20/09/2026. A escolha do dataset e do problema permanece em aberto. Estes resultados avaliam uma proxy operacional e não identificam encerramento comprovado de contas ou da relação bancária.

## Reprodução e escopo

Origem: banco MySQL `financial`, no [CTU Relational Repository](https://relational.fel.cvut.cz/dataset/Financial). Extração somente de `account`, `trans` e `disp WHERE type = 'OWNER'`. Consulte o [manifesto de referência](berka_reference_manifest.json) para consultas, hashes, versões, datas dos snapshots e parâmetros. O cache foi extraído do banco às 19:51 UTC; a análise e sua sensibilidade foram executadas sobre essa mesma extração.

```powershell
python -X utf8 -m dataset_pk99.eda --source cache --output-dir outputs/berka/reproduction
python -X utf8 -m dataset_pk99.eda --source cache --history-days 180 --min-transactions 5 --max-recency-days 30 --output-dir outputs/berka/reproduction_recent
```

Na ausência do cache, execute primeiro com `--source database`. Uma nova extração pode produzir hashes diferentes; confirme contagens, datas e origem. Os resultados locais revisados estão em `outputs/berka/temporal/` e `outputs/berka/recent_activity_full/`, ignorados pelo Git. Este documento preserva uma síntese versionada das evidências, não os registros individuais.

Grade principal: snapshots no fim de cada mês, de janeiro de 1993 a dezembro de 1998; históricos mínimos de 90/180/365 dias; mínimos de 1/5 transações; H de 90/120/180 dias. Cada janela `(T,T+H]` precisa estar completa. Todas as elegibilidades usam somente o passado até T. A idade observada é limitada pelo início global da extração e também se exige histórico desde a primeira transação. São dias corridos.

Os dois escopos são todas as transações (`all_transactions`) e a sensibilidade sem `UROK`, `SLUZBY`, `SANKC. UROK` (`excluding_routine`). A exclusão de juros/tarifas foi motivada pelo significado dos lançamentos, antes da leitura das prevalências; não foi feita para obter uma classe mais conveniente. Não identifica necessariamente atividade deliberada do titular: pagamentos e transferências automáticos continuam possíveis.

## Cobertura e comportamento antes do target

- **4.500 contas, 4.500 vínculos OWNER e 1.056.320 transações**, de **1993-01-01 a 1998-12-31**.
- Nenhuma conta sem OWNER ou sem transações; nenhum OWNER associado a mais de uma conta nesta extração. A unidade continua sendo a conta.
- As validações não encontraram IDs duplicados, referências a contas inexistentes, datas ausentes ou transações anteriores à abertura.
- **241.552 lançamentos adicionais em dias já ativos** não foram descartados da frequência ou das contagens. Apenas a análise de gaps entre dias ativos elimina repetições de data.
- Há transações em todos os 72 meses, mas isso não prova captura completa de cada conta.
- **340.523 lançamentos (32,24%)** têm os três símbolos excluídos na sensibilidade. Restam **715.797 transações**, ainda em 4.500 contas.

| Métrica por conta | Todas as transações | Sem lançamentos rotineiros selecionados |
| --- | ---: | ---: |
| Mediana do total de transações | 208 | 141 |
| Mediana de dias ativos | 161 | 126 |
| Mediana de dias observados até o fim da base | 1.094 | 1.094 |
| Mediana de transações por 30 dias observados | 5,42 | 3,63 |
| Mediana da recência no fim da base | 0 dias | 13 dias |
| Maior recência terminal | 858 dias | 858 dias |

A primeira transação coincide com a abertura em todas as contas, nos dois escopos. O tempo observado vai da abertura ao limite global, incluindo o período terminal sem atividade; não termina na última transação individual. Frequências usam o número de dias do intervalo inclusivo no denominador. A recência zero em 4.317 contas na análise completa evidencia a influência dos lançamentos no último dia da base.

| Intervalo entre dias ativos, por episódio encerrado | Todas | Sem rotineiros |
| --- | ---: | ---: |
| Quantidade de intervalos | 810.268 | 641.787 |
| Mediana | 5 dias | 5 dias |
| P90 | 16 dias | 23 dias |
| P95 | 19 dias | 26 dias |
| P99 | 26 dias | 30 dias |
| Máximo | 510 dias | 510 dias |

Esses quantis são ponderados por episódios, não igualmente por contas. Os CSVs também trazem média, desvio e quantis de gaps de cada conta e a distribuição entre transações individuais, incluindo gaps zero no mesmo dia. As estatísticas do período completo são descritivas e não podem ser usadas como atributos de snapshots passados.

## Gaps longos e reativações

Um episódio começa em um dia ativo e termina na próxima atividade ou fica censurado no fim da base. O threshold usa a diferença entre datas, estritamente `> 90`, `> 120` ou `> 180`. Os dias estritamente entre duas transações são essa diferença menos um. Os episódios terminais têm apenas um limite inferior de duração. O período abertura–primeira atividade é tratado à parte.

| Escopo | Gap > dias | Contas com gap | Contas com algum retorno observado | Episódios encerrados / total | Episódios terminais censurados |
| --- | ---: | ---: | ---: | ---: | ---: |
| Todas | 90 | 28 | 17 (60,7%) | 22 / 38 | 16 |
| Todas | 120 | 26 | 14 (53,8%) | 16 / 30 | 14 |
| Todas | 180 | 22 | 9 (40,9%) | 9 / 23 | 14 |
| Sem rotineiros | 90 | 65 | 50 (76,9%) | 67 / 88 | 21 |
| Sem rotineiros | 120 | 55 | 39 (70,9%) | 47 / 66 | 19 |
| Sem rotineiros | 180 | 39 | 24 (61,5%) | 27 / 43 | 16 |

A proporção por conta significa “teve ao menos um retorno em algum episódio”. Uma conta pode ter um gap encerrado e depois outro censurado; as colunas não são categorias exclusivas por conta. Considerar somente gaps encerrados daria retorno de 100% por construção. Ausência de retorno observado também não comprova permanência futura da inatividade.

Gaps acima de 90 dias afetam **0,62%** das contas com todos os lançamentos e **1,44%** sem os rotineiros selecionados. Portanto, são incomuns no conjunto, mas o retorno é frequente entre as contas que os apresentam. A mediana dos gaps encerrados acima de 90 dias é 149 dias na análise completa e 151 na sensibilidade; o P90 é 267 e 318,6 dias, respectivamente.

Distribuição dos episódios >90 dias: com todos os lançamentos, 19 contas tiveram um episódio, 8 tiveram dois e 1 teve três. Sem rotineiros: 49 tiveram um, 10 tiveram dois, 5 tiveram três e 1 teve quatro. A recorrência impede interpretar todos esses episódios como desligamentos distintos.

Para comparar acompanhamento de duração fixa, contamos retorno em **180 dias após `início_do_gap + threshold`**, somente quando essa janela termina dentro da base:

| Gap > dias | Todas: retornos / episódios acompanhados | Sem rotineiros: retornos / episódios acompanhados |
| --- | ---: | ---: |
| 90 | 18 / 32 (56,3%) | 51 / 72 (70,8%) |
| 120 | 11 / 24 (45,8%) | 31 / 51 (60,8%) |
| 180 | 6 / 16 (37,5%) | 19 / 32 (59,4%) |

São proporções descritivas em coortes com acompanhamento completo, com denominadores pequenos. Não são estimativas de probabilidade de retorno definitivo nem de encerramento.

## Targets temporais

O rótulo é `future_inactivity_flag`: nenhuma transação do escopo em `(T,T+H]`. O quadro usa histórico mínimo de **180 dias**, ao menos **5 transações até T**, sem filtro de recência. A escolha dessa linha para apresentação é ilustrativa; a grade inteira foi calculada e nenhum parâmetro foi aprovado como target final.

| Escopo | H | Snapshots elegíveis | Positivos | Contas distintas positivas | Prevalência |
| --- | ---: | ---: | ---: | ---: | ---: |
| Todas | 90 | 145.502 | 266 | 28 | 0,1828% |
| Todas | 120 | 141.002 | 229 | 26 | 0,1624% |
| Todas | 180 | 132.002 | 176 | 21 | 0,1333% |
| Sem rotineiros | 90 | 145.502 | 407 | 61 | 0,2797% |
| Sem rotineiros | 120 | 141.002 | 330 | 50 | 0,2340% |
| Sem rotineiros | 180 | 132.002 | 226 | 34 | 0,1712% |

Cada linha usa todas as datas com futuro completo para aquele H. Os denominadores caem para horizontes maiores. Na comparação com **calendário comum até 1998-06-30**, há 132.002 observações em cada H: com todos os lançamentos, são 219 / 200 / 176 positivos (0,1659% / 0,1515% / 0,1333%); sem rotineiros, 344 / 293 / 226 (0,2606% / 0,2220% / 0,1712%). Nessa comparação, a diferença entre H não depende da inclusão de meses mais recentes.

Os 266 snapshots positivos em H=90 na análise completa correspondem a **37 sequências positivas** no calendário elegível e somente 28 contas. Na sensibilidade, 407 snapshots representam 78 sequências e 61 contas. Sequências também não equivalem automaticamente a eventos independentes de abandono: a cadência mensal pode ocultar atividade entre snapshots.

### Impacto da elegibilidade

Para H=90 e mínimo de 5 transações:

| Histórico mínimo | Snapshots, todas | Positivos, todas | Prevalência, todas | Snapshots, sem rotineiros | Positivos, sem rotineiros | Prevalência, sem rotineiros |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 90 dias | 157.976 | 266 | 0,1684% | 157.922 | 407 | 0,2577% |
| 180 dias | 145.502 | 266 | 0,1828% | 145.502 | 407 | 0,2797% |
| 365 dias | 118.333 | 263 | 0,2223% | 118.333 | 402 | 0,3397% |

Exigir mais histórico remove sobretudo observações negativas e aumenta a prevalência, sem criar uma população positiva substancialmente maior. Isso não é justificativa para escolher 365 dias.

Para histórico de 180 dias e H=90, os 185.615 conta-snapshots após abertura passam a 159.007 com histórico suficiente, 159.002 com pelo menos 5 transações e 145.502 após excluir 13.500 observações sem futuro completo. Esse funil é igual nos dois escopos. Reduzir o mínimo de 5 para 1 transação adiciona somente 5 observações nessa configuração, sem novos positivos. Com histórico de 90 dias, a regra de contagem tem efeito maior; os detalhes estão em `eligibility_by_snapshot.csv` e `target_summary.csv`.

**Inatividade existente versus futura:** em H=90, 177 dos 266 positivos completos e 227 dos 407 sem rotineiros já tinham recência de pelo menos 90 dias em T. O target básico mede continuar ou entrar em inatividade; não é exclusivamente a incidência de novos episódios.

Como sensibilidade à população em risco, exigimos atividade nos últimos 30 dias (`recency_days <= 30`), mantendo histórico 180 e mínimo 5:

| H | Todas: positivos / observações | Contas positivas | Sem rotineiros: positivos / observações | Contas positivas |
| --- | ---: | ---: | ---: | ---: |
| 90 | 47 / 145.155 (0,0324%) | 28 | 79 / 144.820 (0,0546%) | 61 |
| 120 | 35 / 140.675 (0,0249%) | 26 | 60 / 140.360 (0,0427%) | 50 |
| 180 | 24 / 131.715 (0,0182%) | 21 | 37 / 131.429 (0,0282%) | 34 |

O filtro é conhecido em T e não usa o futuro. Reduz a repetição de inatividade já em andamento, mas não estabelece um critério de negócio definitivo. Aqui não aumenta a quantidade de contas positivas.

### Retorno depois do horizonte e distribuição no tempo

Na configuração ilustrativa, após H=90 houve retorno observado em **73/266 snapshots positivos (27,4%)**, envolvendo **16/28 contas**. Sem rotineiros, houve retorno em **195/407 (47,9%)**, envolvendo **45/61 contas**. Os tempos restantes até o fim da base são desiguais.

Restringindo a uma janela adicional completa de 180 dias após `T+H`:

| H | Todas: retornos / positivos acompanhados | Sem rotineiros: retornos / positivos acompanhados |
| --- | ---: | ---: |
| 90 | 47 / 169 (27,8%) | 135 / 277 (48,7%) |
| 120 | 30 / 138 (21,7%) | 94 / 215 (43,7%) |
| 180 | 15 / 98 (15,3%) | 50 / 136 (36,8%) |

Esses denominadores são **snapshots positivos**, repetidos dentro de contas; não devem ser confundidos com os episódios do quadro de gaps.

Na análise completa, nenhum snapshot de 1993–1995 é positivo para os H testados, com histórico 180 e mínimo 5. Para H=90, os positivos se distribuem em 22 (1996), 95 (1997) e 149 (1998). Sem rotineiros, surgem em 1995: 13 (1995), 60 (1996), 129 (1997) e 205 (1998). As quantidades e prevalências por data estão salvas; o aumento temporal pode envolver mudanças de composição, histórico disponível ou captura. Não há evidência para atribuí-lo diretamente a mudanças de comportamento dos clientes.

## Limitações e implicações para a decisão

1. O Berka não fornece churn explícito ou data de encerramento. Ausência de lançamentos pode representar inatividade, falha de captura ou outro fenômeno não distinguível nesta extração.
2. A hipótese de cobertura comum até 1998-12-31 é necessária para rotular ausência; não é comprovada pela data máxima. Nem o encerramento da conta nem o fim da relação do cliente são observados.
3. Retornos depois de gaps de até 510 dias mostram que longos silêncios podem ser reversíveis. Retornos por juros/tarifas também não significam retomada voluntária do cliente.
4. Centenas de snapshots positivos se concentram em poucas dezenas de contas. O tamanho efetivo para avaliação é muito menor do que a contagem de linhas.
5. Snapshots mensais e horizontes sobrepostos criam dependência. O alinhamento ao fim do mês pode interagir com periodicidades; outra cadência pode ser investigada, sem procurar uma proporção de classe desejada.
6. A concentração temporal dos positivos torna uma separação treino/teste realista difícil. Há períodos iniciais inteiros sem positivos na análise completa.
7. A sensibilidade sem rotineiros mantém pagamentos potencialmente automáticos e símbolos vazios. O significado de atividade precisa de validação de domínio.
8. OWNER é usado somente para vínculo descritivo; `disp` não oferece histórico de alterações de titularidade para reconstruir proprietários em cada T.

**Leitura provisória:** é possível definir e reproduzir um target temporal de inatividade. Os resultados atuais não sustentam chamá-lo de churn bancário comprovado e mostram limitações fortes para uma futura classificação: poucas contas positivas, repetição, retornos e concentração no fim da série. Ainda não há evidência suficiente para adotar essa aplicação. Manter aberta uma mudança de pergunta ou de dataset é metodologicamente apropriado; aumentar a prevalência artificialmente não resolve esses problemas.

## Levar ao mentor

- A pergunta relevante é ausência futura de lançamentos, entrada em inatividade a partir de contas recentemente ativas ou encerramento da relação? Só as duas primeiras são operacionalizáveis aqui.
- Que operações representam atividade para essa pergunta? Juros, tarifas e pagamentos automáticos devem contar? Há documentação sobre cobertura e interrupções por conta?
- Qual H e histórico mínimo têm sentido no contexto acadêmico e de domínio, independentemente da distribuição de classes?
- Dezenas de contas positivas, com forte concentração temporal, permitem uma avaliação defensável respeitando contas e tempo? Como purgar horizontes que atravessam o corte?
- Vale priorizar uma análise descritiva de regularidade/reativação, outra pergunta preditiva no Berka ou a alternativa sintética? Em Sparkov, quais conclusões seriam apenas sobre o mecanismo de simulação e como registrar sua geração?

## Verificação realizada

Conexão MySQL real e extração completa executadas; cache verificado por hashes; EDA principal e sensibilidade de recência executadas; CSVs, funis e gráficos inspecionados. Os 12 testes com históricos pequenos passaram, verificando fronteiras inclusivas/exclusivas, futuro incompleto, invariância de atributos ao futuro, calendário comum, recência, ausência de atividade, integridade e censura. Uma auditoria independente por filtros booleanos conferiu 250 rótulos e 250 históricos por escopo, além das 72 linhas de resumo e seus funis; a repetição reproduziu as estatísticas. Sintaxe e `git diff --check` validados. Nenhum modelo ou técnica de balanceamento foi implementado.
