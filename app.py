
import pandas as pd
import requests
import unicodedata
import re
import streamlit as st

st.title("Consulta de Remuneração – GDF")

st.write("Cole um nome por linha:")
nomes_txt = st.text_area("Nomes")

mes = st.text_input("Mês (YYYYMM)", value="202601")
sal_min = st.number_input("Salário-mínimo do edital", value=1412.0)

def normalizar(txt):
    if not txt:
        return ""
    txt = unicodedata.normalize("NFKD", txt)
    txt = txt.encode("ASCII", "ignore").decode("ASCII")
    return re.sub(r"\s+", " ", txt).upper().strip()

if st.button("Consultar"):
    url = f"https://www.dados.df.gov.br/dataset/portal-da-transparencia-remuneracao-dos-servidores"

   
try:
    df = pd.read_csv(
        f"https://www.dados.df.gov.br/datastore/dump/"
        f"?resource_id=portal-da-transparencia-remuneracao-dos-servidores"
    )
except:
    st.error(
        "Os dados deste mês ainda não foram publicados pelo Portal da Transparência do DF. "
        "Tente um mês anterior, como 202503."
    )
    st.stop()


    df["NOME_NORM"] = df["nome_servidor"].astype(str).apply(normalizar)
    df["BRUTO"] = df["remuneracao_bruta"].fillna(0)

    st.subheader("Resultado")

    for nome in nomes_txt.splitlines():
        chave = normalizar(nome)
        sub = df[df["NOME_NORM"].str.contains(chave)]
        total = sub["BRUTO"].sum()

        sm = total / sal_min if sal_min else 0

        if sm <= 4:
            pts = 5000
        elif sm <= 6:
            pts = 4000
        elif sm <= 8:
            pts = 3000
        elif sm <= 10:
            pts = 2000
        elif sm <= 12:
            pts = 1000
        else:
            pts = 0

        st.write(f"**{nome}** → R$ {total:,.2f} → {pts} pontos")
