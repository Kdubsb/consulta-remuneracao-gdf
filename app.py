import csv
import io
import re
import unicodedata
import requests
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Remuneração GDF + Pontuação", layout="wide")
st.title("Remuneração GDF (dados.df.gov.br) + Pontuação do Edital")

# Exemplo real de CSV que existe (2026-02) no dados.df.gov.br:
DEFAULT_CSV = "https://dados.df.gov.br/dataset/462126f8-8a61-4cec-91a2-38615b7f70f6/resource/426732b2-75f9-41a6-98e9-d3cf6b9ac6f6/download/remuneracao202602.csv"

st.markdown(
    "✅ Cole abaixo o **link CSV oficial** do mês (botão *download* no dados.df.gov.br). "
    "Os arquivos do DF normalmente vêm separados por `;` (ponto e vírgula)."
)

csv_url = st.text_input("Link do CSV do mês (download)", value=DEFAULT_CSV)

sal_min = st.number_input("Salário-mínimo vigente no edital (R$)", value=1412.0, min_value=0.0, step=1.0)

st.write("Cole **um nome por linha**:")
nomes_txt = st.text_area("Nomes", height=160)

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

def parse_num(s: str) -> float:
    if s is None:
        return 0.0
    s = str(s).strip()
    if not s:
        return 0.0
    # padrão BR: milhar '.' e decimal ','
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except:
        return 0.0

def baixar_stream(url: str):
    """
    Baixa CSV com requests e User-Agent de navegador (evita bloqueios do urllib).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/csv,*/*;q=0.9",
    }
    r = requests.get(url, headers=headers, stream=True, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"Falha ao baixar CSV. HTTP {r.status_code}. Verifique o link do CSV.")
    r.encoding = "utf-8"
    return r.iter_lines(decode_unicode=True)

def escolher_indices(header_norm):
    """
    Encontra índices relevantes no CSV do DF:
    - Nome obrigatório (coluna NOME)
    - Colunas de proventos para compor BRUTO (se não houver uma coluna 'BRUTA' explícita)
    """
    def idx(exato):
        try:
            return header_norm.index(exato)
        except ValueError:
            return None

    i_nome = idx("NOME")
    # tenta achar coluna explícita de bruto (se existir em algum mês/layout)
    i_bruto = None
    for cand in ["REMUNERACAO BRUTA", "REMUNERAÇÃO BRUTA", "TOTAL BRUTO", "BRUTO"]:
        i_bruto = idx(cand)
        if i_bruto is not None:
            break

    # rubricas comuns de rendimento (sem descontar IRRF/Seguridade)
    rubricas = {
        "REMUNERACAO BASICA", "REMUNERAÇÃO BÁSICA",
        "BENEFICIOS", "BENEFÍCIOS",
        "VALOR DA FUNCAO", "VALOR DA FUNÇÃO",
        "COMISSAO CONSELHEIRO", "COMISSÃO CONSELHEIRO",
        "HORA EXTRA",
        "VERBAS EVENTUAIS",
        "VERBAS JUDICIAIS",
        "LICENCA PREMIO", "LICENÇA PRÊMIO",
    }
    rub_norm = {normalizar(x) for x in rubricas}
    idx_rub = [i for i, h in enumerate(header_norm) if h in rub_norm]

    return i_nome, i_bruto, idx_rub

col1, col2 = st.columns([1, 1])
testar = col1.button("Testar link (mostrar 5 primeiras linhas)")
consultar = col2.button("Consultar e calcular pontuação", type="primary")

if testar:
    try:
        lines = baixar_stream(csv_url)
        first = [next(lines) for _ in range(5)]
        st.success("✅ Link OK! Abaixo 5 primeiras linhas do arquivo:")
        st.code("\n".join(first))
    except Exception as e:
        st.error(str(e))

if consultar:
    nomes = [n.strip() for n in nomes_txt.splitlines() if n.strip()]
    if not nomes:
        st.error("Informe pelo menos um nome.")
        st.stop()

    chaves = {n: normalizar(n) for n in nomes}
    totais = {n: 0.0 for n in nomes}
    detalhes = []

    try:
        lines = baixar_stream(csv_url)
        reader = csv.reader((ln for ln in lines if ln), delimiter=";")  # DF costuma usar ';' [1](https://dados.df.gov.br/dataset/462126f8-8a61-4cec-91a2-38615b7f70f6/resource/d8ed1c6d-967b-4f3f-888a-605139251370/download/remuneracao202407.csv)
        header = next(reader)
    except Exception as e:
        st.error(str(e))
        st.stop()

    header_norm = [normalizar(h) for h in header]
    i_nome, i_bruto, idx_rub = escolher_indices(header_norm)

    if i_nome is None:
        st.error("Não encontrei a coluna 'NOME' no CSV. Verifique se o link é realmente de remuneração do DF.")
        st.stop()

    # Processa linha a linha (não estoura memória)
    for row in reader:
        if len(row) <= i_nome:
            continue

        nome_encontrado = row[i_nome]
        nome_norm = normalizar(nome_encontrado)

        # verifica se bate com algum nome informado
        for nome_in, chave in chaves.items():
            if chave and chave in nome_norm:
                if i_bruto is not None and i_bruto < len(row):
                    bruto = parse_num(row[i_bruto])
                else:
                    bruto = sum(parse_num(row[i]) for i in idx_rub if i < len(row))

                totais[nome_in] += bruto

                if len(detalhes) < 10000:
                    detalhes.append({
                        "nome_input": nome_in,
                        "nome_encontrado": nome_encontrado,
                        "bruto_linha": bruto
                    })

    # Monta resultado final
    saida = []
    for nome_in, total in totais.items():
        pts = pontuacao(total, float(sal_min))
        saida.append({
            "nome": nome_in,
            "total_bruto_somado": round(total, 2),
            "pontuacao": pts
        })

    df_out = pd.DataFrame(saida)
    st.subheader("Resultado (por nome)")
    st.dataframe(df_out, use_container_width=True)

    st.download_button(
        "Baixar resultado (CSV)",
        df_out.to_csv(index=False).encode("utf-8"),
        file_name="resultado_pontuacao_gdf.csv",
        mime="text/csv"
    )

    st.subheader("Detalhamento (linhas encontradas)")
    df_det = pd.DataFrame(detalhes)
    st.dataframe(df_det, use_container_width=True)

    st.download_button(
        "Baixar detalhamento (CSV)",
        df_det.to_csv(index=False).encode("utf-8"),
        file_name="detalhamento_gdf.csv",
        mime="text/csv"
    )

    if i_bruto is None:
        st.warning(
            "⚠️ Este CSV não trouxe uma coluna explícita de 'BRUTO/TOTAL BRUTO'. "
            "Então eu somei rubricas remuneratórias comuns (remuneração básica, benefícios, função, etc.). "
            "Se você quiser, eu ajusto exatamente conforme o dicionário de dados do GDF."
        )
