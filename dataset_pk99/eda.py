import mysql.connector
import pandas as pd

conn = mysql.connector.connect(
    host='relational.fel.cvut.cz',
    port=3306,
    username='guest',
    password='ctu-relational',
    database='financial'
)

# objetivo: obter taxa de churn (clientes inativos a mais de 90 dias em relação à última data)

cursor = conn.cursor()

# tables
cursor.execute("SHOW TABLES")
for table in cursor:
    print(table)


# ---- query - achar data da última transação por cliente;
query_transacao = """
SELECT account_id, MAX(date) as last_trans_date
FROM trans
GROUP BY account_id
"""
df_transacoes = pd.read_sql_query(query_transacao, conn)

# ---- query - achar relação account_id e client_id das contas titulares; um mesmo cliente pode ter 2 contas (dependentes)
query_disp = """
SELECT client_id, account_id
FROM disp
-- WHERE type = 'OWNER'
"""
df_disp = pd.read_sql_query(query_disp, conn)

# --- merge
df_clientes = pd.merge(df_disp, df_transacoes, on='account_id')

# --- find churn
df_clientes['last_trans_date'] = pd.to_datetime(df_clientes['last_trans_date'])

last_date = df_clientes['last_trans_date'].max()
df_clientes['inactive_days'] = (last_date - df_clientes['last_trans_date']).dt.days
df_clientes['flag_churn'] = df_clientes['inactive_days'].apply(lambda x: 1 if x > 90 else 0)

# conclusão
tx_churn = df_clientes['flag_churn'].mean()
qtd_churn = df_clientes['flag_churn'].sum()
qtd_clientes = df_clientes['flag_churn'].count()

print(f'{qtd_churn} de {qtd_clientes} clientes em churn, ou {tx_churn*100:.2f}%')
# 20 de 5369 clientes em churn, ou 0.37%