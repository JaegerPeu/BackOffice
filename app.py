import datetime as dt

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data as d

st.set_page_config(page_title="CRM Back Office SWM", layout="wide")

PLOTLY_TEMPLATE = "plotly_dark"
COR = {"acc": "#5b8af5", "pos": "#2ecc71", "neg": "#e74c3c", "amb": "#f0a030"}

st.title("CRM Back Office — SWM")
st.caption("Prazo (etapas do funil) + Erro (PL CMD × PL Banco) — fonte: Google Sheets `kpi-swm`")

col_reload, _ = st.columns([1, 8])
if col_reload.button("🔄 Recarregar dados"):
    d.clear_cache()
    st.rerun()

# ---- carga ----
df_carteiras = d.load_carteiras()
df_status = d.load_status_historico()
df_acomp = d.load_acompanhamento()

if df_acomp.empty:
    st.warning("Nenhum dado encontrado em Acompanhamento.")
    st.stop()

status_atual = d.status_atual_por_mes(df_status)
tempo_ciclo = d.tempo_ciclo_por_mes(df_status)

meses_disponiveis = sorted(df_acomp["mes_referencia"].dropna().unique())
mes_min, mes_max = meses_disponiveis[0], meses_disponiveis[-1]

# ---- filtro de periodo ----
st.sidebar.header("Filtro de período")
labels = [pd.Timestamp(m).strftime("%Y-%m") for m in meses_disponiveis]
ini_label, fim_label = st.sidebar.select_slider(
    "Mês inicial → final", options=labels, value=(labels[0], labels[-1])
)
mes_ini = pd.Timestamp(ini_label + "-01")
mes_fim = pd.Timestamp(fim_label + "-01")

acomp_p = d.filtrar_periodo(df_acomp, "mes_referencia", mes_ini, mes_fim)
status_p = d.filtrar_periodo(status_atual, "mes_referencia", mes_ini, mes_fim) if not status_atual.empty else status_atual
ciclo_p = d.filtrar_periodo(tempo_ciclo, "mes_referencia", mes_ini, mes_fim) if not tempo_ciclo.empty else tempo_ciclo

base = acomp_p.merge(df_carteiras, on="carteira_id", how="left")
if not status_p.empty:
    base = base.merge(status_p, on=["carteira_id", "mes_referencia"], how="left")
else:
    base["status_atual"] = pd.NA
    base["n_retrabalho"] = 0
if not ciclo_p.empty:
    base = base.merge(ciclo_p, on=["carteira_id", "mes_referencia"], how="left")
else:
    base["dias_ciclo"] = pd.NA

# =========================================================
# KPIs
# =========================================================
st.subheader("Visão geral do período")

n_carteiras = base["carteira_id"].nunique()
mediana_ciclo = round(base["dias_ciclo"].dropna().median(), 1) if "dias_ciclo" in base and base["dias_ciclo"].notna().any() else None
total_retrab = int(base["n_retrabalho"].sum()) if "n_retrabalho" in base else 0
valid_erro = base.loc[base["pl_valido"], "erro_num"]
mediana_erro = round(float(valid_erro.median()) * 100, 3) if len(valid_erro) else None
pct_divergente = round(100 * (valid_erro.abs() > 0.005).sum() / len(valid_erro), 1) if len(valid_erro) else None
pct_sem_pl = round(100 * (~base["pl_valido"]).sum() / len(base), 1) if len(base) else None

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Carteiras no período", n_carteiras)
c2.metric("Dias medianos de ciclo", mediana_ciclo if mediana_ciclo is not None else "—")
c3.metric("Eventos de retrabalho", total_retrab)
c4.metric("Erro mediano PL", f"{mediana_erro}%" if mediana_erro is not None else "—")
c5.metric("Sem PL comparável", f"{pct_sem_pl}%" if pct_sem_pl is not None else "—")

# =========================================================
# Funil do mes mais recente do periodo
# =========================================================
st.subheader(f"Funil — {fim_label}")
funil_df = base[base["mes_referencia"] == mes_fim]
if "status_atual" in funil_df and funil_df["status_atual"].notna().any():
    contagem = funil_df["status_atual"].value_counts()
    cols = st.columns(len(contagem) + 1)
    for i, (status, n) in enumerate(contagem.items()):
        cols[i].metric(status, int(n))
    cols[-1].metric("Total", len(funil_df))
else:
    st.info("Sem eventos de status registrados para este mês ainda.")

# =========================================================
# Evolucao mensal
# =========================================================
st.subheader("Evolução mensal")
evo_cols = st.columns(2)

evo_ciclo = base.dropna(subset=["dias_ciclo"]).groupby(base["mes_referencia"].dt.strftime("%Y-%m"))["dias_ciclo"].median().reset_index()
fig1 = go.Figure()
fig1.add_trace(go.Scatter(x=evo_ciclo["mes_referencia"], y=evo_ciclo["dias_ciclo"], mode="lines+markers", line_color=COR["acc"], name="Dias de ciclo (mediana)"))
fig1.update_layout(template=PLOTLY_TEMPLATE, height=300, margin=dict(t=10, b=10))
evo_cols[0].plotly_chart(fig1, width="stretch")

evo_erro = (base[base["pl_valido"]].groupby(base["mes_referencia"].dt.strftime("%Y-%m"))["erro_num"]
            .median().mul(100).reset_index())
fig2 = go.Figure()
fig2.add_trace(go.Scatter(x=evo_erro["mes_referencia"], y=evo_erro["erro_num"], mode="lines+markers", line_color=COR["neg"], name="Erro mediano %"))
fig2.update_layout(template=PLOTLY_TEMPLATE, height=300, margin=dict(t=10, b=10))
evo_cols[1].plotly_chart(fig2, width="stretch")

# =========================================================
# Faixas de divergencia
# =========================================================
st.subheader("Faixas de divergência (PL CMD × PL Banco)")
if len(valid_erro):
    bins = [-float("inf"), 0.001, 0.005, 0.01, float("inf")]
    labels_bin = ["< 0,1%", "0,1% – 0,5%", "0,5% – 1%", "> 1%"]
    faixa = pd.cut(valid_erro.abs(), bins=bins, labels=labels_bin)
    tab_faixa = faixa.value_counts().reindex(labels_bin).reset_index()
    tab_faixa.columns = ["Faixa", "Carteiras"]
    tab_faixa["%"] = round(100 * tab_faixa["Carteiras"] / tab_faixa["Carteiras"].sum(), 1)
    st.dataframe(tab_faixa, hide_index=True, width="stretch")
else:
    st.info("Sem dado de PL suficiente no período pra calcular divergência.")

# =========================================================
# Rankings
# =========================================================
st.subheader("Rankings")
rank_cols = st.columns(2)

with rank_cols[0]:
    st.markdown("**Por Banker**")
    rb = (base.dropna(subset=["banker"]).groupby("banker").agg(
        carteiras=("carteira_id", "nunique"),
        pl_banco_medio=("pl_banco", "mean"),
        dias_ciclo_mediano=("dias_ciclo", "median"),
        erro_mediano=("erro_num", "median"),
    ).reset_index())
    rb["pl_banco_medio"] = rb["pl_banco_medio"].round(0)
    rb["erro_mediano"] = (rb["erro_mediano"] * 100).round(3)
    st.dataframe(rb.sort_values("pl_banco_medio", ascending=False), hide_index=True, width="stretch")

with rank_cols[1]:
    st.markdown("**Por Instituição**")
    ri = (base.dropna(subset=["instituicao"]).groupby("instituicao").agg(
        carteiras=("carteira_id", "nunique"),
        pl_banco_medio=("pl_banco", "mean"),
        erro_mediano=("erro_num", "median"),
    ).reset_index())
    ri["pl_banco_medio"] = ri["pl_banco_medio"].round(0)
    ri["erro_mediano"] = (ri["erro_mediano"] * 100).round(3)
    st.dataframe(ri.sort_values("pl_banco_medio", ascending=False), hide_index=True, width="stretch")

# =========================================================
# Entradas e saidas
# =========================================================
st.subheader("Carteiras — entradas e saídas no período")
novas, saidas = d.entradas_saidas(df_carteiras, mes_ini, mes_fim)
ent_cols = st.columns(2)
ent_cols[0].markdown(f"**Novas ({len(novas)})**")
ent_cols[0].dataframe(novas[["carteira_id", "nome", "banker", "data_inicio"]], hide_index=True, width="stretch")
ent_cols[1].markdown(f"**Encerradas ({len(saidas)})**")
ent_cols[1].dataframe(saidas[["carteira_id", "nome", "banker", "data_fim"]], hide_index=True, width="stretch")

# =========================================================
# Completude de dados
# =========================================================
st.subheader("Completude de dados por mês")
st.dataframe(d.completude_mensal(acomp_p), hide_index=True, width="stretch")

# =========================================================
# Edicao
# =========================================================
st.divider()
st.header("Edição")

tab1, tab2 = st.tabs(["Editar PL do mês", "Registrar mudança de status"])

with tab1:
    mes_edit_label = st.selectbox("Mês", labels, index=len(labels) - 1, key="mes_edit_pl")
    mes_edit = pd.Timestamp(mes_edit_label + "-01")
    linhas_mes = df_acomp[df_acomp["mes_referencia"] == mes_edit].merge(
        df_carteiras[["carteira_id", "nome"]], on="carteira_id", how="left")
    editado = st.data_editor(
        linhas_mes[["carteira_id", "nome", "pl_cmd", "pl_banco", "obs"]],
        hide_index=True, width="stretch", num_rows="fixed", key="editor_pl",
    )
    if st.button("💾 Salvar alterações de PL"):
        df_full = df_acomp.copy()
        df_full = df_full[df_full["mes_referencia"] != mes_edit]
        editado_full = editado.drop(columns=["nome"]).copy()
        editado_full["mes_referencia"] = mes_edit
        df_full = pd.concat([df_full, editado_full[["carteira_id", "mes_referencia", "pl_cmd", "pl_banco", "obs"]]], ignore_index=True)
        d.save_acompanhamento(df_full.sort_values(["mes_referencia", "carteira_id"]))
        st.success("Salvo. Recarregando...")
        st.rerun()

with tab2:
    with st.form("form_status"):
        carteira_sel = st.selectbox("Carteira", sorted(df_carteiras["carteira_id"].unique()))
        mes_sel_label = st.selectbox("Mês de referência", labels, index=len(labels) - 1)
        status_sel = st.selectbox("Novo status", d.STATUS_ORDEM + d.STATUS_DESVIOS)
        data_sel = st.date_input("Data da mudança", value=dt.date.today())
        obs_sel = st.text_input("Observação (opcional)")
        enviado = st.form_submit_button("➕ Registrar evento")
    if enviado:
        d.append_status_event(carteira_sel, pd.Timestamp(mes_sel_label + "-01"), status_sel, pd.Timestamp(data_sel), obs_sel)
        st.success("Evento registrado. Recarregando...")
        st.rerun()
