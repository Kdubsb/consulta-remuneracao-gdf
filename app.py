import csv
import re
import unicodedata
import requests
import pandas as pd
import streamlit as st

# =========================
# Configurações gerais
# =========================
st.set_page_config(page_title="Remuneração GDF + Pontuação", layout="wide")
st.title("Remuneração GDF (dados.df.gov.br) + Pontuação do Edital")

# Página do dataset (onde ficam listados os recursos mensais publicados) [1](https://dados.df.gov.br/pt_BR/dataset/portal-da-transparencia-remuneracao-dos-servidores)
DATASET_PAGE = "https://www.dados.df.gov.br/dataset/portal-da-transparencia-remuneracao-dos-servidores"

# Exemplo real de CSV publicado (2026-02) [4](https://www.dados.df.gov.br/dataset/portal-da-transparencia-remuneracao-dos-servidores/resource/426732b2-75f9-41a6-98e9-d3cf6b9ac6f6)
FALLBACK_CSV = "https://dados.df.gov.br/dataset/462126f8-8a61-4cec-91a2-38615b7f70f6/resource/426732b2-75f9-41a6-98e9-d3cf6b9ac6f6/download/remuneracao202602.csv"

# =========================
# Funções utilitárias
# =========================
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
    Baixa CSV com requests e User-Agent de navegador (evita bloqueios do urllib/pandas).
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
        "Accept": "text/csv,*/*;q=0.9",
    }
    r = requests.get(url, headers=headers, stream=True, timeout=180)
    if r.status_code != 200:
        raise RuntimeError(f"Falha ao baixar CSV. HTTP {r.status_code}.")
    r.encoding = "utf-8"
    return r.iter_lines(decode_unicode=True)

@st.cache_data(ttl=3600)
def listar_meses_publicados():
    """
    Lê a página do dataset e extrai links publicados do tipo:
    .../download/remuneracaoYYYYMM.csv
    (Só meses existentes serão listados, evitando o app quebrar.)
    """
    headers = {"User-Agent": "Mozilla/5.0"}
    html = requests.get(DATASET_PAGE, headers=headers, timeout=30).text

    # Captura URLs absolutas ou relativas que terminam com remuneracaoYYYYMM.csv
    links = re.findall(
        r'(https?://[^\s"\']+?/download/remuneracao\d{6}\.csv|/dataset/[^\s"\']+?/download/remuneracao\d{6}\.csv)',
        html,
        flags=re.IGNORECASE
    )

    meses = {}
    for lk in links:
        m = re.search(r"remuneracao(\d{6})\.csv", lk, flags=re.IGNORECASE)
        if m:
            yyyymm = m.group(1)
            url = lk
            if url.startswith("/"):
                url = "https://www.dados.df.gov.br" + url
            # Normaliza domínio (às vezes aparece sem www)
            url = url.replace("https://dados.df.gov.br/", "https://www.dados.df.gov.br/")
            meses[yyyymm] = url

    # Ordena: mais recente -> mais antigo
    meses = dict(sorted(meses.items(), key=lambda x: x[0], reverse=True))
    return meses

def escolher_indices(header_norm):
    """
    Tenta achar:
    - NOME (obrigatório)
    - BRUTO (se existir explicitamente)
    - caso não exista BRUTO, soma rubricas comuns de rendimentos
    """
    def idx(exato):
        try:
            return header_norm.index(exato)
        except ValueError:
            return None

    i_nome = idx("NOME")

    i_bruto = None
    for cand in ["REMUNERACAO BRUTA", "REMUNERAÇÃO BRUTA", "TOTAL BRUTO", "BRUTO"]:
        i_bruto = idx(cand)
        if i_bruto is not None:
            break

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

# =========================
# UI: seleção de mês (fácil e segura)
# =========================
st.markdown("## 📅 Mês de referência (somente meses publicados)")

# Salário mínimo (usado na pontuação)
sal_min = st.number_input("Salário-mínimo vigente no edital (R$)", value=1412.0, min_value=0.0, step=1.0)

# Lista de meses publicados (se falhar, cai no modo manual)
meses_links = {}
try:
    meses_links = listar_meses_publicados()
except Exception:
    meses_links = {}

if not meses_links:
    st.warning(
        "Não consegui listar automaticamente os meses publicados no dados.df.gov.br agora. "
        "Use o modo manual abaixo."
    )

    csv_url = st.text_input("Link do CSV do mês (download)", value=FALLBACK_CSV)
    mes_escolhido = "manual"
else:
    meses_disponiveis = list(meses_links.keys())  # já ordenado (desc)

    # Estado para botões anterior/próximo funcionarem sem erro
    if "mes_idx" not in st.session_state:
        st.session_state.mes_idx = 0  # 0 = mais recente disponível

    colA, colB, colC = st.columns([1, 2, 1])

    with colA:
        if st.button("⬅ Mês anterior (publicado)"):
            if st.session_state.mes_idx < len(meses_disponiveis) - 1:
                st.session_state.mes_idx += 1

    with colC:
        if st.button("Mês seguinte (publicado) ➡"):
            if st.session_state.mes_idx > 0:
                st.session_state.mes_idx -= 1

    with colB:
        mes_escolhido = st.selectbox(
            "Mês disponível (YYYYMM)",
            meses_disponiveis,
            index=st.session_state.mes_idx
        )
        st.session_state.mes_idx = meses_disponiveis.index(mes_escolhido)

    csv_url = meses_links[mes_escolhido]
    st.caption(f"Fonte (download): {csv_url}")

    # Fallback manual opcional (se você quiser colar um link específico)
    with st.expander("🔧 (Opcional) Colar link manual do CSV"):
        manual = st.text_input("Se colar aqui, o app usa este link no lugar do automático", value="")
        if manual.strip():
            csv_url = manual.strip()
            mes_escolhido = "manual"
            st.caption("Usando link manual.")

# =========================
# Entrada de nomes
# =========================
st.markdown("## 👤 Nomes para consulta")
st.write("Cole **um nome por linha**:")
nomes_txt = st.text_area("Nomes", height=170)

# =========================
# Botões de ação
# =========================
col1, col2 = st.columns([1, 1])
testar = col1.button("Testar CSV selecionado (mostrar 5 primeiras linhas)")
consultar = col2.button("Consultar e calcular pontuação", type="primary")

if testar:
    try:
        lines = baixar_stream(csv_url)
        first = [next(lines) for _ in range(5)]
        st.success("✅ CSV acessível! 5 primeiras linhas:")
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

    # Lê CSV por streaming (para não estourar memória)
    try:
        lines = baixar_stream(csv_url)
        # DF costuma usar ';' em CSV (ponto e vírgula)
        reader = csv.reader((ln for ln in lines if ln), delimiter=";")
        header = next(reader)
    except Exception as e:
        st.error(str(e))
        st.stop()

    header_norm = [normalizar(h) for h in header]
    i_nome, i_bruto, idx_rub = escolher_indices(header_norm)

    if i_nome is None:
        st.error("Não encontrei a coluna 'NOME' no CSV. Verifique se o CSV é de remuneração do DF.")
        st.stop()

    # Processa linha a linha
    for row in reader:
        if len(row) <= i_nome:
            continue

        nome_encontrado = row[i_nome]
        nome_norm = normalizar(nome_encontrado)

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
                        "mes": mes_escolhido,
                        "nome_encontrado": nome_encontrado,
                        "bruto_linha": bruto
                    })

    # Saída consolidada
    saida = []
    for nome_in, total in totais.items():
        pts = pontuacao(total, float(sal_min))
        saida.append({
            "nome": nome_in,
            "mes": mes_escolhido,
            "total_bruto_somado": round(total, 2),
            "pontuacao": pts
        })

    df_out = pd.DataFrame(saida)
    st.subheader("✅ Resultado (por nome)")
    st.dataframe(df_out, use_container_width=True)

    st.download_button(
        "Baixar resultado (CSV)",
        df_out.to_csv(index=False).encode("utf-8"),
        file_name="resultado_pontuacao_gdf.csv",
        mime="text/csv"
    )

    st.subheader("📄 Detalhamento (linhas encontradas)")
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
            "Se você quiser 100% fiel ao layout do mês, podemos ajustar pela tabela do dicionário de dados."
        )
         
