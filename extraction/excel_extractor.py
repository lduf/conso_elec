# extraction/excel_extractor.py
import os
import pandas as pd

def read_xlsx_and_return_df(file_path: str, skip_rows: int = 15, sheet_index: int = 1) -> pd.DataFrame:
    """
    Lit un fichier Excel et renvoie un DataFrame correspondant à la seconde feuille (par défaut sheet_index=1),
    en sautant un certain nombre de lignes (par défaut skip_rows=15).
    """
    df = pd.read_excel(file_path, sheet_name=sheet_index, skiprows=skip_rows)
    return df

def convert_df_to_csv(df: pd.DataFrame, csv_path: str) -> None:
    """
    Convertit un DataFrame en fichier CSV.
    """
    df.to_csv(csv_path, index=False)

def read_xlsx_from_folder(folder_path: str, skip_rows: int = 15, sheet_index: int = 1):
    """
    Parcourt un dossier, lit chaque fichier .xlsx et
    renvoie une liste de DataFrames.
    """
    dfs = []
    for file_name in os.listdir(folder_path):
        if file_name.lower().endswith(".xlsx"):
            full_path = os.path.join(folder_path, file_name)
            df = pd.read_excel(full_path, sheet_name=sheet_index, skiprows=skip_rows)
            dfs.append((file_name, df))
    return dfs