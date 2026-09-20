# i generated data using seed 1234, 6k customers and from 01-01-25 to 01-01-26
# i then concatenated all transaction data into one single csv
# get files from the drive
import pandas as pd



# get last date per customer
df_transactions = pd.read_csv('./dataset_generated/transactions.csv')
df_customers = pd.read_csv('./dataset_generated/customers.csv', sep="|")

df_transactions['trans_date'] = pd.to_datetime(df_transactions['trans_date'])

df_last_transaction = df_transactions.groupby('acct_num')['trans_date'].max().reset_index()
df_last_transaction.rename(columns={'trans_date':'last_trans_date'}, inplace=True)

# last date
last_date = df_transactions['trans_date'].max()

# churners
df_customers = df_customers.merge(df_last_transaction[['acct_num', 'last_trans_date']], on='acct_num')
df_customers['days_inactive'] = (last_date - df_customers['last_trans_date']).dt.days
df_customers['flag_churn'] = df_customers['days_inactive'].apply(lambda x: 1 if x > 90 else 0)

# taxa de churn
tx_churn = df_customers['flag_churn'].mean()
qtd_churn = df_customers['flag_churn'].sum()
qtd_clientes = df_customers['flag_churn'].count()

print(f'{qtd_churn} de {qtd_clientes} clientes em churn, ou {tx_churn*100:.2f}%')
# 600 de 6000 clientes em churn, ou 10.00%