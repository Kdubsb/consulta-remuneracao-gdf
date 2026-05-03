
import re
import unicodedata
import requests
import pandas as pd
import streamlit as st

# Página do dataset (onde estão listados todos os meses e seus links de download)
DATASET_PAGE = "https://www.dados.df.gov.br/dataset/portal-da-transparencia-remuneracao-dos-servidores"  # [5](https://www.dados.df.gov.br/dataset/portal-da-transparencia-remuneracao-dos-servidores)

st.title("Consulta de Remuneração – GDF (dados.df.gov.br)")

def normalizar(txt: str) -> str:
    if txt is None:
        return ""
    txt = str(txt).strip()
    txt = unicodedata.normalize("NFKD", txt)
    txt = "".join(ch for ch in txt if not unicodedata.combining(ch))
    txt = re.sub(r"\s+", " ", txt).upper()
    return txt

def pontuacao(total_bruto: float, salario_minimo: float) -> int:
    if salario_minimo <= 0:
        return 0
    sm = total_bruto / salario_minimo
    if sm <= 4: return 5000
    if sm <= 6: return 4000
    if sm <= 8: return 3000
    if sm <= 10: return 2000
    if sm <= 12: return 1000
    return 0

@st.cache_data(ttl=3600)
def listar_meses_e_links():
    """
    Lê a página do dataset e extrai todos os links do tipo:
    .../download/remuneracaoYYYYMM.csv
    """
    html = requests.get(DATASET_PAGE, timeout=30).text
    # Captura links que terminam com remuneracaoYYYYMM.csv
    # Pode aparecer como URL absoluta ou relativa
    links = re.findall(r'(https?://[^\s"\']+?/download/remuneracao\d{6}\.csv|/dataset/[^\s"\']+?/download/remuneracao\d{6}\.csv)', html, flags=re.IGNORECASE)
    meses = {}
    for lk in links:
        m = re.search(r"remuneracao(\d{6})\.csv", lk, flags=re.IGNORECASE)
        if m:
            mes = m.group(1)
            url = lk
            if url.startswith("/"):
                url = "https://www.dados.df.gov.br" + url
            meses[mes] = url  # se repetir, mantém o último encontrado
    # ordena meses desc
    meses_ordenados = dict(sorted(meses.items(), key=lambda x: x[0], reverse=True))
    return meses_ordenados

st.write("Cole um nome por linha:")
nomes_txt = st.text_area("Nomes")

sal_min = st.number_input("Salário-mínimo do edital (R$)", value=1412.0)

# Descobre meses disponíveis automaticamente
try:
    meses_links = listar_meses_e_links()
except Exception as e:
    st.error(f"Não consegui acessar o dados.df.gov.br agora. Erro: {e}")
    st.stop()

if not meses_links:
    st.error("Não encontrei links de arquivos mensais (remuneracaoYYYYMM.csv) na página do dataset.")
    st.stop()

meses_disponiveis = list(meses_links.keys())
mes_escolhido = st.selectbox("Mês disponível (YYYYMM)", meses_disponiveis, index=0)
download_url = meses_links[mes_escolhido]

st.caption(f"Fonte (download): {download_url}")

def achar_coluna(df_cols, termos):
    cols_norm = [(c, normalizar(c)) for c in df_cols]
    for c, cn in cols_norm:
        for t in termos:
            if t in cn:
                return c
    return None

if st.button("Consultar"):
    nomes = [n.strip() for n in nomes_txt.splitlines() if n.strip()]
    if not nomes:
        st.error("Informe pelo menos um nome.")
        st.stop()

    # Normaliza nomes para busca
    chaves = {n: normalizar(n) for n in nomes}
    totais = {n: 0.0 for n in nomes}
    detalhes = []

    # Leitura em chunks para não estourar memória no Streamlit Cloud
    # O CSV costuma ser separado por ';' [4](https://dados.df.gov.br/dataset/462126f8-8a61-4cec-91a2-38615b7f70f6/resource/d8ed1c6d-967b-4f3f-888a-605139251370/download/remuneracao202407.csv)
    try:
        it = pd.read_csv(download_url, sep=";", dtype=str, encoding="utf-8", chunksize=200000)
    except Exception:
        it = pd.read_csv(download_url, sep=";", dtype=str, encoding="latin-1", chunksize=200000)

    # Na primeira iteração, descobrimos colunas relevantes
    nome_col = None
    bruto_col = None

    for chunk in it:
        if nome_col is None:
            nome_col = achar_coluna(chunk.columns, ["NOME"])
            # tenta achar coluna explícita de bruto (se existir)
            bruto_col = achar_coluna(chunk.columns, ["BRUTA", "BRUTO", "REMUNERACAO BRUTA", "REMUNERAÇÃO BRUTA", "TOTAL BRUTO", "TOTALBRUTO"])
            if nome_col is None:
                st.error("Não encontrei a coluna de NOME no CSV. Verifique o dicionário de dados do dataset.")
                st.stop()

        # Filtra linhas que contenham qualquer um dos nomes (normalizado)
        chunk["_NOME_NORM"] = chunk[nome_col].map(normalizar)

        # Se tiver coluna BRUTA explícita, usa ela; senão tenta somar rubricas positivas comuns
        if bruto_col:
            bruto_raw = chunk[bruto_col].fillna("0").astype(str)
            bruto_val = (bruto_raw.str.replace(".", "", regex=False)
                                  .str.replace(",", ".", regex=False))
            chunk["_BRUTO"] = pd.to_numeric(bruto_val, errors="coerce").fillna(0.0)
        else:
            # fallback: soma de rubricas mais comuns (ajusta se o CSV tiver nomes diferentes)
            # OBS: como não há garantia de coluna "bruta" em todos os layouts,
            # esse fallback tenta ser útil e transparente.
            possiveis = [
                "REMUNERACAO BASICA", "REMUNERAÇÃO BÁSICA", "BENEFICIOS", "BENEFÍCIOS",
                "VALOR DA FUNCAO", "VALOR DA FUNÇÃO", "COMISSAO CONSELHEIRO", "COMISSÃO CONSELHEIRO",
                "HORA EXTRA", "VERBAS EVENTUAIS", "VERBAS JUDICIAIS"
            ]
            soma = 0.0
            for col in chunk.columns:
                cn = normalizar(col)
                if cn in [normalizar(x) for x in possiveis]:
                    v = (chunk[col].fillna("0").astype(str)
                                 .str.replace(".", "", regex=False)
                                 .str.replace(",", ".", regex=False))
                    soma += pd.to_numeric(v, errors="coerce").fillna(0.0)
            chunk["_BRUTO"] = soma

        for nome_in, chave in chaves.items():
            sub = chunk[chunk["_NOME_NORM"].str.contains(chave, na=False)]
            if not sub.empty:
                total_sub = float(sub["_BRUTO"].sum())
                totais[nome_in] += total_sub
                # Guarda alguns detalhes (para auditoria)
                for _, r in sub.head(50).iterrows():  # limita por chunk para não explodir
                    detalhes.append({
                        "nome_input": nome_in,
                        "mes": mes_escolhido,
                        "nome_encontrado": r.get(nome_col, ""),
                        "bruto_linha": float(r.get("_BRUTO", 0.0))
                    })

    # Mostra resultados
    st.subheader("Resultado (por nome)")
    saida = []
    for nome_in, total in totais.items():
        pts = pontuacao(total, float(sal_min))
        saida.append({
            "nome": nome_in,
            "mes": mes_escolhido,
            "total_bruto": total,
            "pontuacao": pts
        })
    df_out = pd.DataFrame(saida)
    st.dataframe(df_out, use_container_width=True)

    st.download_button(
        "Baixar resultado (CSV)",
        df_out.to_csv(index=False).encode("utf-8"),
        file_name=f"resultado_gdf_{mes_escolhido}.csv",
        mime="text/csv"
    )

    st.subheader("Detalhamento (linhas encontradas)")
    df_det = pd.DataFrame(detalhes)
    st.dataframe(df_det, use_container_width=True)

    st.download_button(
        "Baixar detalhamento (CSV)",
        df_det.to_csv(index=False).encode("utf-8"),
        file_name=f"detalhamento_gdf_{mes_escolhido}.csv",
        mime="text/csv"
    )

    if not bruto_col:
        st.warning(
            "⚠️ Não encontrei uma coluna explícita de 'remuneração bruta' no CSV deste mês. "
            "Usei a soma de rubricas remuneratórias comuns (remuneração básica, benefícios, função, etc.). "
            "Se você quiser 100% fiel ao layout do GDF, podemos ajustar conforme o dicionário de dados do dataset."
        )
