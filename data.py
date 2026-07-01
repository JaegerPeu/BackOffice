import streamlit as st
import pandas as pd
import numpy as np

from sheets import get_ws

STATUS_ORDEM = [
    "Em processo", "Aguardando Banker", "Aguardando Cliente", "Feito",
    "Relatorio Gerado", "Pronto para Envio Cliente", "Enviado Cliente",
]
STATUS_DESVIOS = ["Em Revisao", "Bloqueado"]
STATUS_TERMINAL = "Enviado Cliente"

TTL = 60  # segundos de cache antes de reler o Sheets


def parse_pt_number(x):
    if x is None or x == "":
        return np.nan
    if isinstance(x, (int, float)):
        return float(x)
    s = str(x).strip().replace(".", "").replace(",", ".") if "," in str(x) else str(x).strip()
    try:
        return float(s)
    except ValueError:
        return np.nan


@st.cache_data(ttl=TTL)
def load_carteiras():
    rows = get_ws("Carteiras").get_all_records()
    df = pd.DataFrame(rows)
    df["data_inicio"] = pd.to_datetime(df["data_inicio"], errors="coerce")
    df["data_fim"] = pd.to_datetime(df["data_fim"], errors="coerce")
    return df


@st.cache_data(ttl=TTL)
def load_status_historico():
    rows = get_ws("Status_Historico").get_all_records()
    df = pd.DataFrame(rows)
    if df.empty:
        return df
    df["mes_referencia"] = pd.to_datetime(df["mes_referencia"], errors="coerce")
    df["data_mudanca"] = pd.to_datetime(df["data_mudanca"], errors="coerce")
    return df


@st.cache_data(ttl=TTL)
def load_acompanhamento():
    rows = get_ws("Acompanhamento").get_all_records()
    df = pd.DataFrame(rows)
    df["mes_referencia"] = pd.to_datetime(df["mes_referencia"], errors="coerce")
    df["pl_cmd"] = df["pl_cmd"].apply(parse_pt_number)
    df["pl_banco"] = df["pl_banco"].apply(parse_pt_number)
    df["pl_valido"] = df["pl_cmd"].notna() & df["pl_banco"].notna()
    df["erro_num"] = np.where(df["pl_valido"], (df["pl_cmd"] - df["pl_banco"]) / df["pl_banco"], np.nan)
    return df


def clear_cache():
    load_carteiras.clear()
    load_status_historico.clear()
    load_acompanhamento.clear()


def status_atual_por_mes(df_status):
    """Ultimo status (por data_mudanca) de cada carteira x mes + contagem de retrabalho (desvios)."""
    if df_status.empty:
        return pd.DataFrame(columns=["carteira_id", "mes_referencia", "status_atual", "data_status_atual", "n_retrabalho"])
    df_status = df_status.sort_values("data_mudanca")
    ultimo = df_status.groupby(["carteira_id", "mes_referencia"]).tail(1)
    ultimo = ultimo.rename(columns={"status": "status_atual", "data_mudanca": "data_status_atual"})
    retrabalho = (df_status[df_status["status"].isin(STATUS_DESVIOS)]
                  .groupby(["carteira_id", "mes_referencia"]).size()
                  .rename("n_retrabalho").reset_index())
    out = ultimo[["carteira_id", "mes_referencia", "status_atual", "data_status_atual"]].merge(
        retrabalho, on=["carteira_id", "mes_referencia"], how="left")
    out["n_retrabalho"] = out["n_retrabalho"].fillna(0).astype(int)
    return out


COLUNAS_BOARD = ["Sem status"] + STATUS_ORDEM + STATUS_DESVIOS


def board_por_mes(status_atual_df, carteiras_df, mes):
    """Monta as colunas do kanban pro mes selecionado: {status: [labels]} + mapa label -> carteira_id."""
    ativas = carteiras_df[(carteiras_df["data_inicio"] <= mes) &
                           (carteiras_df["data_fim"].isna() | (carteiras_df["data_fim"] >= mes))]
    sa_mes = status_atual_df[status_atual_df["mes_referencia"] == mes] if not status_atual_df.empty else status_atual_df
    merged = ativas.merge(sa_mes, on="carteira_id", how="left") if not sa_mes.empty else ativas.assign(status_atual=pd.NA, data_status_atual=pd.NaT)

    colunas = {c: [] for c in COLUNAS_BOARD}
    label_to_id = {}
    for _, row in merged.iterrows():
        status = row["status_atual"] if pd.notna(row.get("status_atual")) else "Sem status"
        data_str = row["data_status_atual"].strftime("%d/%m") if pd.notna(row.get("data_status_atual")) else "sem data"
        label = f"{row['carteira_id']}|{row['nome']} (desde {data_str})"
        colunas.setdefault(status, []).append(label)
        label_to_id[label] = row["carteira_id"]
    return colunas, label_to_id


def tempo_ciclo_por_mes(df_status):
    """Dias entre o primeiro evento do mes e o evento 'Enviado Cliente' (quando existe)."""
    if df_status.empty:
        return pd.DataFrame(columns=["carteira_id", "mes_referencia", "dias_ciclo"])
    primeiro = df_status.groupby(["carteira_id", "mes_referencia"])["data_mudanca"].min().rename("data_inicio_evento")
    enviado = (df_status[df_status["status"] == STATUS_TERMINAL]
               .groupby(["carteira_id", "mes_referencia"])["data_mudanca"].min().rename("data_enviado"))
    out = pd.concat([primeiro, enviado], axis=1).reset_index()
    out["dias_ciclo"] = (out["data_enviado"] - out["data_inicio_evento"]).dt.days
    return out[["carteira_id", "mes_referencia", "dias_ciclo"]]


def filtrar_periodo(df, col_mes, mes_ini, mes_fim):
    return df[(df[col_mes] >= mes_ini) & (df[col_mes] <= mes_fim)]


def entradas_saidas(df_carteiras, mes_ini, mes_fim):
    novas = df_carteiras[(df_carteiras["data_inicio"] >= mes_ini) & (df_carteiras["data_inicio"] <= mes_fim)]
    saidas = df_carteiras[df_carteiras["data_fim"].notna() &
                           (df_carteiras["data_fim"] >= mes_ini) & (df_carteiras["data_fim"] <= mes_fim)]
    return novas, saidas


def _fmt_cell(v):
    if pd.isna(v):
        return ""
    if isinstance(v, pd.Timestamp):
        return v.strftime("%Y-%m-%d")
    return v


def save_acompanhamento(df_full):
    """Sobrescreve a aba Acompanhamento inteira com o dataframe (pl_cmd/pl_banco/obs editados)."""
    ws = get_ws("Acompanhamento")
    cols = ["carteira_id", "mes_referencia", "pl_cmd", "pl_banco", "obs"]
    out = df_full[cols].copy()
    values = [cols] + out.applymap(_fmt_cell).values.tolist()
    ws.clear()
    ws.update(values, value_input_option="USER_ENTERED")
    clear_cache()


def append_status_event(carteira_id, mes_referencia, status, data_mudanca, obs):
    ws = get_ws("Status_Historico")
    ws.append_row([
        carteira_id,
        mes_referencia.strftime("%Y-%m-%d"),
        status,
        data_mudanca.strftime("%Y-%m-%d"),
        obs or "",
    ], value_input_option="USER_ENTERED")
    clear_cache()


def completude_mensal(df_acomp):
    if df_acomp.empty:
        return pd.DataFrame()
    g = df_acomp.groupby(df_acomp["mes_referencia"].dt.strftime("%Y-%m"))
    out = g.apply(lambda d: pd.Series({
        "n_carteiras": len(d),
        "pct_com_pl": round(100 * d["pl_valido"].sum() / len(d), 1),
    }), include_groups=False).reset_index().rename(columns={"mes_referencia": "mes"})
    return out.sort_values("mes")
