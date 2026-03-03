import streamlit as st
import pandas as pd
import io

# Configuración de la página
st.set_page_config(
    page_title="Buscador de Experiencias SuForma",
    page_icon="🔍",
    layout="wide"
)

# Estilos CSS personalizados
st.markdown("""
<style>
    .main { background-color: #f8f9fa; }
    div[data-testid="stMetricValue"] { font-size: 1.6rem; color: #0f54c9; }
    .stTextInput > label { font-weight: bold; color: #333; }
    .stDownloadButton > button {
        width: 100%; background-color: #16a34a !important; color: white !important;
        border-radius: 8px; padding: 0.6rem; font-weight: bold; border: none;
    }
    .company-badge {
        background-color: #f1f5f9;
        color: #1e293b;
        padding: 4px 12px;
        border-radius: 6px;
        font-weight: bold;
        font-size: 0.85rem;
        border: 1px solid #e2e8f0;
    }
</style>
""", unsafe_allow_html=True)

# -----------------------------------------------------------------------------
# FUNCIONES DE PROCESAMIENTO
# -----------------------------------------------------------------------------

def clean_currency_cop(val):
    if pd.isna(val): return 0
    # Eliminar puntos de miles, símbolos de peso y espacios
    val_str = str(val).replace('.', '').replace('$', '').replace(' ', '').strip()
    try:
        # Manejar si hay coma decimal residual
        return int(float(val_str.replace(',', '.')))
    except:
        return 0

def clean_smmlv(val):
    if pd.isna(val): return 0.0
    # Formato latino: 1.000,50 -> 1000.50
    val_str = str(val).replace('.', '').replace(',', '.').strip()
    try:
        return float(val_str)
    except:
        return 0.0

def identify_columns(df):
    """Mapeo inteligente de columnas basado en el nuevo formato suministrado."""
    cols = list(df.columns)
    mapping = {
        'id': None, 
        'consecutivo': None, 
        'empresa': None, 
        'contratante': None, 
        'objeto': None, 
        'valor_cop': None, 
        'valor_smmlv': None, 
        'unspsc': None,
        'total_codigos_file': None # Para detectar si ya trae la cuenta
    }
    
    for col in cols:
        c = str(col).lower().strip()
        # Mapeo de ID (Busca ID o Experiencia_No)
        if ('id' in c or 'experiencia_no' in c) and mapping['id'] is None: mapping['id'] = col
        elif 'consecutivo' in c: mapping['consecutivo'] = col
        elif ('empresa' in c or 'contratista' in c) and mapping['empresa'] is None: mapping['empresa'] = col
        elif 'contratante' in c: mapping['contratante'] = col
        elif 'objeto' in c: mapping['objeto'] = col
        elif ('valor' in c or 'presupuesto' in c) and 'cop' in c: mapping['valor_cop'] = col
        elif 'smmlv' in c: mapping['valor_smmlv'] = col
        # Mapeo de Códigos (Busca Codigos o UNSPSC)
        elif ('codigos' in c or 'unspsc' in c) and 'total' not in c: mapping['unspsc'] = col
        elif 'total' in c and 'codigos' in c: mapping['total_codigos_file'] = col
        
    return mapping

def load_data(uploaded_file):
    try:
        if uploaded_file is not None:
            # Soportar múltiples delimitadores (Punto y coma, Coma, Tabulación)
            encodings = ['utf-8', 'latin-1', 'cp1252']
            seps = [';', ',', '\t']
            
            for enc in encodings:
                for s in seps:
                    try:
                        uploaded_file.seek(0)
                        df = pd.read_csv(uploaded_file, sep=s, encoding=enc)
                        if len(df.columns) >= 5: # Si detectó suficientes columnas, es válido
                            return df
                    except:
                        continue
        return None
    except Exception as e:
        st.error(f"Error crítico al cargar: {e}")
        return None

def format_latino_decimal(val):
    return f"{val:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def format_latino_money(val):
    return f"$ {val:,.0f}".replace(",", ".")

# -----------------------------------------------------------------------------
# UI PRINCIPAL
# -----------------------------------------------------------------------------

st.title("💼 Buscador de Experiencias SuForma")

with st.sidebar:
    st.header("📂 Gestión de Datos")
    uploaded_file = st.file_uploader("Subir base de datos (CSV)", type=['csv'])
    st.info("Acepta formatos con columnas: EMPRESA, Experiencia_No, Codigos, etc.")

raw_df = load_data(uploaded_file)

if raw_df is not None:
    df = raw_df.copy()
    col_map = identify_columns(df)
    
    # Validar columnas mínimas necesarias
    required = ['id', 'contratante', 'objeto', 'valor_cop', 'valor_smmlv', 'unspsc']
    missing = [k for k in required if col_map[k] is None]
    
    if missing:
        st.error(f"❌ No se detectaron las columnas: {', '.join(missing)}")
        st.write("Columnas encontradas en tu archivo:", list(df.columns))
        st.stop()

    # PROCESAMIENTO DE DATOS
    df['clean_smmlv'] = df[col_map['valor_smmlv']].apply(clean_smmlv)
    df['clean_cop'] = df[col_map['valor_cop']].apply(clean_currency_cop)
    df[col_map['unspsc']] = df[col_map['unspsc']].astype(str)
    
    # Cálculo dinámico de total de códigos (por si el del archivo no es exacto)
    def count_codes(val):
        if pd.isna(val) or val == 'nan': return 0
        codes = [c.strip() for c in str(val).replace(';', ',').split(',') if c.strip()]
        return len(codes)
    
    df['Calculated_Total_Codigos'] = df[col_map['unspsc']].apply(count_codes)

    # Filtros
    st.subheader("🔍 Filtros de Búsqueda")
    col_in1, col_in2 = st.columns([1, 2])
    with col_in1: search_unspsc = st.text_input("Códigos UNSPSC", placeholder="Ej: 14111500")
    with col_in2: search_object = st.text_input("Palabras clave en Objeto", placeholder="Ej: Suministro")

    # Lógica de Filtrado
    filtered_df = df.copy()
    target_codes = [c.strip() for c in search_unspsc.split(',') if c.strip()]

    if search_object:
        filtered_df = filtered_df[filtered_df[col_map['objeto']].str.contains(search_object, case=False, na=False)]

    if target_codes:
        def match_all(val):
            row_codes = [c.strip() for c in str(val).replace(';', ',').split(',')]
            return all(tc in row_codes for tc in target_codes)
        filtered_df = filtered_df[filtered_df[col_map['unspsc']].apply(match_all)]

    filtered_df = filtered_df.sort_values(by='clean_smmlv', ascending=False)

    # DASHBOARD DE MÉTRICAS
    st.markdown("---")
    st.subheader("📊 Resumen de Resultados")
    
    # Métricas Globales
    m1, m2, m3 = st.columns(3)
    count = len(filtered_df)
    m1.metric("Experiencias Totales", f"{count}")
    m2.metric("Valor Total SMMLV", format_latino_decimal(filtered_df['clean_smmlv'].sum()))
    m3.metric("Presupuesto Total COP", format_latino_money(filtered_df['clean_cop'].sum()))

    # Resumen Desglosado por Empresa
    if col_map['empresa']:
        distinct_companies = filtered_df[col_map['empresa']].nunique()
        if distinct_companies > 1:
            st.markdown("#### Desglose por Empresa")
            summary_table = filtered_df.groupby(col_map['empresa']).agg({
                col_map['id']: 'count',
                'clean_smmlv': 'sum',
                'clean_cop': 'sum'
            }).reset_index()
            
            summary_table.columns = ['Empresa', 'Cant. Experiencias', 'Total SMMLV', 'Total COP']
            
            # Formatear la tabla para el usuario
            display_table = summary_table.copy()
            display_table['Total SMMLV'] = display_table['Total SMMLV'].apply(format_latino_decimal)
            display_table['Total COP'] = display_table['Total COP'].apply(format_latino_money)
            
            st.table(display_table)

    # Botón de Descarga
    if count > 0:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            export_df = filtered_df.copy()
            export_df[col_map['valor_smmlv']] = export_df['clean_smmlv'].apply(format_latino_decimal)
            export_df[col_map['valor_cop']] = export_df['clean_cop'].apply(lambda x: f"{x:,.0f}".replace(",", "."))
            # Quitar columnas de proceso internas
            export_df.drop(columns=['clean_smmlv', 'clean_cop', 'Calculated_Total_Codigos']).to_excel(writer, index=False)
        st.download_button(label="📊 Descargar Reporte en Excel", data=output.getvalue(), file_name="reporte_suforma.xlsx")

    st.markdown("---")

    # RESULTADOS EN TARJETAS
    if count == 0:
        st.warning("No se encontraron resultados para los filtros aplicados.")
    else:
        for _, row in filtered_df.iterrows():
            all_codes = [c.strip() for c in str(row[col_map['unspsc']]).replace(';', ',').split(',') if c.strip()]
            badges_html = "".join([f"<span style='background:{'#2563eb' if c in target_codes else '#f1f5f9'}; color:{'white' if c in target_codes else '#64748b'}; padding:2px 10px; border-radius:15px; font-size:12px; margin-right:5px; display:inline-block; margin-bottom:5px; border: 1px solid {'#1d4ed8' if c in target_codes else '#e2e8f0'};'>{c}</span>" for c in all_codes])
            
            empresa_val = row[col_map['empresa']] if col_map['empresa'] else "N/A"
            consecutivo_val = row[col_map['consecutivo']] if col_map['consecutivo'] else "N/A"
            
            card_html = f"""
<div style="background:white; border-radius:12px; border:1px solid #e5e7eb; padding:20px; margin-bottom:20px; box-shadow: 0 4px 6px rgba(0,0,0,0.05);">
<div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:10px;">
<div style="font-size:12px; color:#9ca3af;">ID: {row[col_map['id']]} | Consecutivo: {consecutivo_val}</div>
<div class="company-badge">🏢 {empresa_val}</div>
</div>
<div style="font-size:18px; font-weight:bold; color:#111827; margin-bottom:4px;">{row[col_map['contratante']]}</div>
<div style="font-size:14px; color:#4b5563; margin:12px 0; border-left:4px solid #3b82f6; padding-left:12px; line-height:1.4;">{row[col_map['objeto']]}</div>
<div style="display:grid; grid-template-columns: 1fr 1fr 1fr; gap:10px; background:#f9fafb; padding:12px; border-radius:8px; margin-bottom:15px;">
<div>
<div style="font-size:10px; color:#6b7280; text-transform:uppercase;">Valor COP</div>
<div style="font-size:14px; font-weight:600;">{format_latino_money(row['clean_cop'])}</div>
</div>
<div>
<div style="font-size:10px; color:#6b7280; text-transform:uppercase;">Valor SMMLV</div>
<div style="font-size:14px; font-weight:bold; color:#059669;">{format_latino_decimal(row['clean_smmlv'])}</div>
</div>
<div style="text-align:center; border-left: 1px solid #e5e7eb;">
<div style="font-size:10px; color:#6b7280; text-transform:uppercase;">Cant. Códigos</div>
<div style="font-size:16px; font-weight:bold; color:#3b82f6;">{row['Calculated_Total_Codigos']}</div>
</div>
</div>
<div style="font-size:11px; color:#9ca3af; margin-bottom:6px; font-weight:bold;">CÓDIGOS UNSPSC:</div>
<div>{badges_html}</div>
</div>
"""
            st.markdown(card_html, unsafe_allow_html=True)
else:
    st.info("👋 Bienvenido al Buscador de Experiencias SuForma. Por favor sube tu archivo CSV para comenzar.")
