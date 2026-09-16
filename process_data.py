import json
import os
import pandas as pd
import requests

TOKEN = os.environ.get("INTA_TOKEN")
HEADERS = {"Authorization": f"Token {TOKEN}"}

URL_PRECIPITACIONES = "https://territorios.inta.gob.ar/assets/aYqLUVvU3EYiDa7NoJbPKF/submissions/?format=json"
URL_MAPA = "https://territorios.inta.gob.ar/assets/aFwWKNGXZKppgNYKa33wC8/submissions/?format=json"


def fetch_all_kobo_data(url):
    results = []
    current_url = url

    while current_url:
        r = requests.get(current_url, headers=HEADERS, timeout=90)
        r.raise_for_status()
        data = r.json()

        if isinstance(data, list):
            results.extend(data)
            break

        if isinstance(data, dict):
            if "results" in data:
                results.extend(data["results"])
                current_url = data.get("next")
            else:
                break

    return results


def run_etl():
    print("Descargando metadatos de estaciones...")
    est_raw = fetch_all_kobo_data(URL_MAPA)
    df_est = pd.DataFrame(est_raw)

    if not df_est.empty:
        col_n = next(
            (c for c in df_est.columns if "Nombre_del_Pluviometro" in c), "cod"
        )
        col_depto = next(
            (c for c in df_est.columns if "depto" in c.lower()), None
        )
        col_prov = next(
            (c for c in df_est.columns if "prov" in c.lower()), None
        )

        if "Codigo_txt_del_pluviometro" in df_est.columns:
            df_est["cod"] = (
                df_est["Codigo_txt_del_pluviometro"]
                .astype(str)
                .str.replace(".0", "", regex=False)
                .str.strip()
            )
        else:
            df_est["cod"] = df_est.index.astype(str)

        df_est["Pluviómetro"] = df_est[col_n].fillna(df_est["cod"])
        df_est["Departamento"] = (
            df_est[col_depto].fillna("S/D") if col_depto else "S/D"
        )
        df_est["Provincia"] = (
            df_est[col_prov].fillna("S/D") if col_prov else "S/D"
        )

        # Extraer Coordenadas
        df_est["lat"] = None
        df_est["lng"] = None

        for idx, row in df_est.iterrows():
            geo = row.get("_geolocation")
            if isinstance(geo, list) and len(geo) >= 2:
                try:
                    df_est.at[idx, "lat"] = float(geo[0])
                    df_est.at[idx, "lng"] = float(geo[1])
                except (ValueError, TypeError):
                    pass

        df_est_clean = df_est[
            ["cod", "Pluviómetro", "Departamento", "Provincia", "lat", "lng"]
        ].drop_duplicates(subset=["cod"])
    else:
        df_est_clean = pd.DataFrame(
            columns=[
                "cod",
                "Pluviómetro",
                "Departamento",
                "Provincia",
                "lat",
                "lng",
            ]
        )

    print("Descargando historial de precipitaciones...")
    p_raw = fetch_all_kobo_data(URL_PRECIPITACIONES)

    df_p = pd.DataFrame(p_raw)
    if df_p.empty:
        print("No se encontraron registros de precipitaciones.")
        return

    col_pluv = next(
        (
            c
            for c in df_p.columns
            if "Pluviometros" in c or "pluviometro" in c.lower()
        ),
        None,
    )
    col_fecha = next(
        (c for c in df_p.columns if "Fecha" in c or "fecha" in c.lower()), None
    )
    col_mm = next(
        (
            c
            for c in df_p.columns
            if "Mil_metros" in c or "registrados" in c or "mm" in c.lower()
        ),
        None,
    )

    df_p["cod"] = (
        df_p[col_pluv]
        .astype(str)
        .str.replace(".0", "", regex=False)
        .str.strip()
    )
    df_p["fecha_dt"] = pd.to_datetime(df_p[col_fecha], errors="coerce")
    df_p["mm"] = pd.to_numeric(df_p[col_mm], errors="coerce").fillna(0.0)
    df_p = df_p.dropna(subset=["fecha_dt"])

    # Merge con estaciones y coordenadas
    df = df_p.merge(df_est_clean, on="cod", how="left")
    df["Pluviómetro"] = df["Pluviómetro"].fillna(df["cod"])
    df["Departamento"] = df["Departamento"].fillna("S/D")
    df["Provincia"] = df["Provincia"].fillna("S/D")

    df["Año"] = df["fecha_dt"].dt.year
    df["Mes"] = df["fecha_dt"].dt.month

    # Agrupación incluyendo lat y lng
    df_mensual = (
        df.groupby(
            [
                "Año",
                "Mes",
                "cod",
                "Pluviómetro",
                "Departamento",
                "Provincia",
                "lat",
                "lng",
            ],
            dropna=False,
        )["mm"]
        .sum()
        .reset_index()
    )

    data_out = df_mensual.to_dict(orient="records")
    with open("data_acumulados.json", "w", encoding="utf-8") as f:
        json.dump(data_out, f, ensure_ascii=False, indent=2)

    print(
        f"Éxito: Se procesaron {len(data_out)} filas acumuladas con coordenadas."
    )


if __name__ == "__main__":
    run_etl()
