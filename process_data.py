import os
import requests
import pandas as pd
import json

TOKEN = os.environ.get("INTA_TOKEN")
HEADERS = {"Authorization": f"Token {TOKEN}"}

URL_PRECIPITACIONES = "https://territorios.inta.gob.ar/assets/aYqLUVvU3EYiDa7NoJbPKF/submissions/?format=json"
URL_MAPA = "https://territorios.inta.gob.ar/assets/aFwWKNGXZKppgNYKa33wC8/submissions/?format=json"

def run_etl():
    # 1. Obtener Metadatos (Estaciones)
    r_est = requests.get(URL_MAPA, headers=HEADERS, timeout=60)
    r_est.raise_for_status()
    df_est = pd.DataFrame(r_est.json())

    col_n = next((c for c in df_est.columns if "Nombre_del_Pluviometro" in c), "cod")
    col_depto = next((c for c in df_est.columns if "depto" in c.lower()), None)
    col_prov = next((c for c in df_est.columns if "prov" in c.lower()), None)

    if "Codigo_txt_del_pluviometro" in df_est.columns:
        df_est["cod"] = df_est["Codigo_txt_del_pluviometro"].astype(str).str.replace(".0", "", regex=False).str.strip()
    else:
        df_est["cod"] = df_est.index.astype(str)

    df_est["Pluviómetro"] = df_est[col_n].fillna(df_est["cod"])
    df_est["Departamento"] = df_est[col_depto].fillna("S/D") if col_depto else "S/D"
    df_est["Provincia"] = df_est[col_prov].fillna("S/D") if col_prov else "S/D"
    
    df_est_clean = df_est[["cod", "Pluviómetro", "Departamento", "Provincia"]].drop_duplicates(subset=["cod"])

    # 2. Obtener Precipitaciones
    r_p = requests.get(URL_PRECIPITACIONES, headers=HEADERS, timeout=90)
    r_p.raise_for_status()
    df_p = pd.DataFrame(r_p.json())

    df_p["cod"] = df_p["Pluviometros"].astype(str).str.replace(".0", "", regex=False).str.strip()
    df_p["fecha_dt"] = pd.to_datetime(df_p["Fecha_del_dato"], errors="coerce")
    df_p["mm"] = pd.to_numeric(df_p["Mil_metros_registrados"], errors="coerce").fillna(0.0)
    df_p = df_p.dropna(subset=["fecha_dt"])

    # 3. Merge de datos
    df = df_p.merge(df_est_clean, on="cod", how="left")
    df["Pluviómetro"] = df["Pluviómetro"].fillna(df["cod"])
    df["Departamento"] = df["Departamento"].fillna("S/D")
    df["Provincia"] = df["Provincia"].fillna("S/D")

    # 4. Agregación Mensual y Anual
    df["Año"] = df["fecha_dt"].dt.year
    df["Mes"] = df["fecha_dt"].dt.month

    # Tabla agrupada
    df_mensual = df.groupby(["Año", "Mes", "cod", "Pluviómetro", "Departamento", "Provincia"])["mm"].sum().reset_index()
    
    # Exportar datos resumidos
    data_out = df_mensual.to_dict(orient="records")
    with open("data_acumulados.json", "w", encoding="utf-8") as f:
        json.dump(data_out, f, ensure_ascii=False)

if __name__ == "__main__":
    run_etl()
