import os
import pandas as pd
import azure.functions as func
from azure.storage.blob import ContainerClient, BlobClient
import pyodbc

SERVER = os.environ.get("DB_SERVER")
DB_NAME = os.environ.get("DB_NAME")
USERNAME = os.environ.get("DB_USERNAME")
PASSWORD = os.environ.get("DB_PASSWORD")
CONN_STRING = os.environ.get("CONN_STRING")
CONTAINER_NAME = 'data'
TABLE_NAME = 'Transactions'


def get_data(conn_str: str, container_name: str) -> pd.DataFrame:
    """Fetches transactions csv files from Blob store, read into Pandas DataFrames and concatenate them all into one DataFrame.

    Arguments:
       conn_str (str): connection string of storage account in which the blob store resides
       container_name (str): name of the container in which the csv files reside
       
    Returns:
       data (pd.DataFrame): one single dataframe that contains all the fetched transactions
    """

    container = ContainerClient.from_connection_string(
        conn_str=conn_str,
        container_name = container_name
        )

    blob_list = container.list_blobs()

    if not os.path.exists('./data'):
        os.makedirs('./data')

    dfs = []

    for blob in blob_list:

        blob_client = BlobClient.from_connection_string(conn_str=conn_str,
                                                        container_name=container_name, 
                                                        blob_name=blob.name)

        with open(blob.name, "wb") as my_blob:
                blob_data = blob_client.download_blob()
                blob_data.readinto(my_blob)

        raw_data = pd.read_csv(blob.name)

        dfs.append(raw_data)

    return pd.concat(dfs)


def write_to_sql(cursor: pyodbc.Cursor, data: pd.DataFrame, table_name: str) -> None:
    """Inserts or updates rows of the input DataFrame.

    Arguments:
       cursor (pyodbc.Cursor): pyodbc database cursor
       data (pd.DataFrame): DataFrame that contains the rows that ought to be written to the SQL database
    """
    
    for index, row in data.iterrows():
        cursor.execute(f'''MERGE INTO {table_name} as Target
        USING (SELECT * FROM (VALUES (?, ?, ?, ?)) AS s (transaction_id, store, product, price)) AS Source
        ON Target.transaction_id=Source.transaction_id
        WHEN NOT MATCHED THEN
        INSERT (transaction_id, store, product, price) VALUES (Source.transaction_id, Source.store, Source.product, Source.price)
        WHEN MATCHED THEN
        UPDATE SET transaction_id=Source.transaction_id, store=Source.store, product=Source.product, price=Source.price;
        ''',
                    row['transaction_id'],
                    row['store'],
                    row['product'],
                    row['price'],
                    )


def main(mytimer: func.TimerRequest) -> None:
    """The main function expected by the Azure Functions runtime
    """

    # fetch the data

    data = get_data(CONN_STRING, CONTAINER_NAME)

    # transform the data

    data['transaction_id'] = data['transaction_id'].astype(int)
    data['store'] = data['store'].astype(str)
    data['product'] = data['product'].astype(str)
    data['price'] = data['price'].astype(float)

    data['product'] = data['product'].apply(lambda x: x.replace('shoo', 'shoe').lower())
    
    # connect with our SQL database

    cnxn = pyodbc.connect(f'DRIVER={{ODBC Driver 17 for SQL Server}};SERVER={SERVER};DATABASE={DB_NAME};UID={USERNAME};PWD={PASSWORD}', 
                      autocommit=True,
                      timeout=60)
    
    cursor = cnxn.cursor()
    
    # write the data to the SQL database

    write_to_sql(cursor, data, TABLE_NAME)

