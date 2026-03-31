import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.express as px
import yfinance as yf
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. SAYFA AYARLARI ---
st.set_page_config(page_title="CebimX Pro Finans", layout="wide", initial_sidebar_state="expanded")
st.markdown("""<style>div[data-testid="metric-container"] { background-color: #1e293b; border: 1px solid #334155; padding: 15px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); }</style>""", unsafe_allow_html=True)

kategoriler = ["Market", "Kira", "Fatura", "Dışarıda Yemek & Kafe", "Proje & Geliştirici Giderleri", "Eğitim & Kendini Geliştirme", "Oyun & Zevk", "Donanım (Al-Sat)", "Ulaşım", "Giyim & Bakım", "Sağlık", "Diğer"]

# --- 2. GOOGLE SHEETS & CANLI HAFIZA (RAM) MOTORU ---
@st.cache_resource
def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(dict(st.secrets["google_auth"]), scope)
    return gspread.authorize(creds)

def safe_float(val):
    try:
        if isinstance(val, str): val = val.replace(',', '.')
        if val == "" or pd.isna(val): return 0.0
        return float(val)
    except: return 0.0

def get_new_id(df):
    if df.empty or 'id' not in df.columns: return 1
    try: return int(pd.to_numeric(df['id']).max() + 1)
    except: return 1

# SADECE UYGULAMA İLK AÇILDIĞINDA ÇALIŞIR (1 KERE)
@st.cache_data(ttl=3600)
def fetch_all_data():
    client = get_gsheet_client()
    sh = client.open_by_url(st.secrets["gsheets"]["url"])
    worksheets = {ws.title: ws for ws in sh.worksheets()}
    
    cols = {
        "islemler": ["id", "tip", "isim", "miktar", "tarih", "ihtiyac_mi", "kategori"],
        "ticaret": ["id", "urun_adi", "alis_fiyati", "tahmini_satis"],
        "hedefler": ["id", "hedef_adi", "hedef_tutar", "biriken"],
        "kredi_kartlari": ["id", "kart_adi", "kart_limit", "guncel_borc", "hesap_kesim"],
        "taksitler": ["id", "kart_id", "aciklama", "aylik_tutar", "kalan_ay"],
        "yastik_alti": ["varlik_tipi", "miktar"],
        "manuel_borclar": ["id", "borc_adi", "toplam_miktar", "odenen", "tarih"],
        "abonelikler": ["id", "isim", "tutar", "odeme_gunu"],
        "butceler": ["id", "kategori", "limit_tutar"],
        "faturalar": ["id", "isim", "durum"],
        "notlar": ["id", "baslik", "icerik", "tarih"]
    }
    
    dfs = {}
    for name, s_cols in cols.items():
        if name not in worksheets:
            new_ws = sh.add_worksheet(title=name, rows="100", cols="20")
            new_ws.append_row(s_cols)
            dfs[name] = pd.DataFrame(columns=s_cols)
            worksheets[name] = new_ws
        else:
            try:
                data = worksheets[name].get_all_records()
                df = pd.DataFrame(data)
                if not df.empty and 'id' not in df.columns and name in cols:
                    worksheets[name].insert_row(s_cols, index=1)
                    df = pd.DataFrame(worksheets[name].get_all_records())
                dfs[name] = df
            except: dfs[name] = pd.DataFrame(columns=s_cols)
            
        # Rakam hatalarını temizle
        if not dfs[name].empty:
            for col in ['miktar', 'alis_fiyati', 'tahmini_satis', 'hedef_tutar', 'biriken', 'kart_limit', 'guncel_borc', 'aylik_tutar', 'toplam_miktar', 'odenen', 'tutar', 'limit_tutar']:
                if col in dfs[name].columns:
                    dfs[name][col] = dfs[name][col].astype(str).str.replace(',', '.').str.replace(' ', '')
                    dfs[name][col] = pd.to_numeric(dfs[name][col], errors='coerce').fillna(0.0)
                    
    if dfs["yastik_alti"].empty:
        baslangic = [["Genel Kasa - USD", 0], ["Genel Kasa - EUR", 0], ["Genel Kasa - GA", 0], ["Genel Kasa - BTC", 0], ["Genel Kasa - ETH", 0]]
        for b in baslangic: worksheets["yastik_alti"].append_row(b)
        st.cache_data.clear()
        st.rerun()
        
    return dfs, worksheets

# --- HAFIZA (STATE) YÜKLEMESİ ---
if 'db_loaded' not in st.session_state:
    try:
        st.session_state.dfs, st.session_state.wss = fetch_all_data()
        st.session_state.db_loaded = True
    except Exception as e:
        st.error(f"Google Sheets Bağlantı Hatası: {e}")
        st.stop()

# --- AKILLI GÜNCELLEME FONKSİYONLARI (429 HATASINI BİTİREN KODLAR) ---
def add_row(sheet_name, row_dict):
    st.session_state.wss[sheet_name].append_row(list(row_dict.values()))
    st.session_state.dfs[sheet_name] = pd.concat([st.session_state.dfs[sheet_name], pd.DataFrame([row_dict])], ignore_index=True)

def del_row(sheet_name, row_id):
    df = st.session_state.dfs[sheet_name]
    idx = df.index[df['id'] == row_id].tolist()[0]
    st.session_state.wss[sheet_name].delete_rows(int(idx + 2))
    st.session_state.dfs[sheet_name] = df[df['id'] != row_id].reset_index(drop=True)

def update_cell(sheet_name, row_id, col_name, new_val, col_index):
    df = st.session_state.dfs[sheet_name]
    idx = df.index[df['id'] == row_id].tolist()[0]
    st.session_state.wss[sheet_name].update_cell(int(idx + 2), col_index, str(new_val))
    st.session_state.dfs[sheet_name].at[idx, col_name] = new_val

def update_yastik(tam_isim, yeni_miktar):
    df = st.session_state.dfs['yastik_alti']
    idx_list = df.index[df['varlik_tipi'] == tam_isim].tolist()
    if idx_list:
        idx = idx_list[0]
        st.session_state.wss['yastik_alti'].update_cell(int(idx + 2), 2, str(yeni_miktar))
        st.session_state.dfs['yastik_alti'].at[idx, 'miktar'] = yeni_miktar
    else:
        st.session_state.wss['yastik_alti'].append_row([tam_isim, yeni_miktar])
        new_row = {"varlik_tipi": tam_isim, "miktar": yeni_miktar}
        st.session_state.dfs['yastik_alti'] = pd.concat([st.session_state.dfs['yastik_alti'], pd.DataFrame([new_row])], ignore_index=True)

# --- 3. GİRİŞ KONTROLÜ ---
if 'giris_yapildi' not in st.session_state: st.session_state.giris_yapildi = False
if not st.session_state.giris_yapildi:
    st.title("🔐 CebimX Giriş")
    k1, k2, k3 = st.columns([1, 2, 1])
    with k2:
        with st.container(border=True):
            if st.button("Giriş Yap", use_container_width=True):
                if st.text_input("Kullanıcı") == "admin" and st.text_input("Şifre", type="password") == st.secrets["kullanici"]["sifre"]:
                    st.session_state.giris_yapildi = True
                    st.rerun()
                else: st.error("Hatalı Giriş!")
    st.stop()

with st.sidebar:
    if st.button("🔄 Verileri Eşitle (Sync)"):
        st.cache_data.clear()
        st.session_state.pop('db_loaded', None)
        st.rerun()
    if st.button("🚪 Çıkış Yap"):
        st.session_state.giris_yapildi = False
        st.rerun()

st.title("💸 CebimX:Kişisel Finans Yönetimi")

# --- 4. CANLI PİYASALAR ---
if 'usd_try' not in st.session_state:
    st.session_state.usd_try, st.session_state.eur_try, st.session_state.gr_altin = 0.0, 0.0, 0.0
    st.session_state.btc_try, st.session_state.eth_try = 0.0, 0.0

col_kur = st.columns(6)
with col_kur[5]:
    if st.button("🔄 Kurları Güncelle"):
        try:
            u = yf.Ticker("TRY=X").history(period="1d")['Close'].iloc[-1]
            st.session_state.usd_try = u
            st.session_state.eur_try = yf.Ticker("EURTRY=X").history(period="1d")['Close'].iloc[-1]
            st.session_state.gr_altin = (yf.Ticker("GC=F").history(period="1d")['Close'].iloc[-1] / 31.103) * u
            st.session_state.btc_try = yf.Ticker("BTC-USD").history(period="1d")['Close'].iloc[-1] * u
            st.session_state.eth_try = yf.Ticker("ETH-USD").history(period="1d")['Close'].iloc[-1] * u
            st.success("Kurlar çekildi!")
        except: st.error("Kur hatası.")

col_kur[0].info(f"💵 USD: **{st.session_state.usd_try:,.2f}**")
col_kur[1].info(f"💶 EUR: **{st.session_state.eur_try:,.2f}**")
col_kur[2].warning(f"🥇 Altın: **{st.session_state.gr_altin:,.2f}**")
col_kur[3].success(f"₿ BTC: **{st.session_state.btc_try:,.0f}**")
col_kur[4].success(f"⟠ ETH: **{st.session_state.eth_try:,.0f}**")
st.divider()

# --- 5. HESAPLAMALAR ---
dfs = st.session_state.dfs
ay_str = f"{datetime.now().year}-{datetime.now().month:02d}"

toplam_gelir = dfs['islemler'][dfs['islemler']['tip'] == 'Gelir']['miktar'].sum() if not dfs['islemler'].empty else 0.0
toplam_nakit_gider = dfs['islemler'][dfs['islemler']['tip'] == 'Gider']['miktar'].sum() if not dfs['islemler'].empty else 0.0
df_ay_gider = dfs['islemler'][(dfs['islemler']['tip'].isin(['Gider', 'KK Gider'])) & (dfs['islemler']['tarih'].astype(str).str.startswith(ay_str))] if not dfs['islemler'].empty else pd.DataFrame()
df_ay_gelir = dfs['islemler'][(dfs['islemler']['tip'] == 'Gelir') & (dfs['islemler']['tarih'].astype(str).str.startswith(ay_str))] if not dfs['islemler'].empty else pd.DataFrame()
ay_gelir_top = df_ay_gelir['miktar'].sum() if not df_ay_gelir.empty else 0.0

net_nakit = toplam_gelir - toplam_nakit_gider
kk_borc = dfs['kredi_kartlari']['guncel_borc'].sum() if not dfs['kredi_kartlari'].empty else 0.0

yastik_tl, varlik_kats = 0.0, {}
if not dfs['yastik_alti'].empty:
    for _, r in dfs['yastik_alti'].iterrows():
        m, tip = safe_float(r['miktar']), str(r['varlik_tipi'])
        kat, b = tip.split(" - ")[0] if " - " in tip else "Genel", tip.split(" - ")[-1] if " - " in tip else tip
        tl = 0.0
        if b == 'USD': tl = m * st.session_state.usd_try
        elif b == 'EUR': tl = m * st.session_state.eur_try
        elif b == 'GA': tl = m * st.session_state.gr_altin
        elif b == 'Çeyrek Altın': tl = m * (st.session_state.gr_altin * 1.605)
        elif b == 'Yarım Altın': tl = m * (st.session_state.gr_altin * 3.21)
        elif b == 'Tam Altın': tl = m * (st.session_state.gr_altin * 6.42)
        elif b == 'Ata Altın': tl = m * (st.session_state.gr_altin * 6.61)
        elif b == 'BTC': tl = m * st.session_state.btc_try
        elif b == 'ETH': tl = m * st.session_state.eth_try
        yastik_tl += tl
        varlik_kats[kat] = varlik_kats.get(kat, 0.0) + tl

net_worth = net_nakit + yastik_tl - kk_borc

# --- 6. SEKMELER ---
sekmeler = st.tabs(["📊 Kumanda", "🗒️ Notlar", "🟢 Gelir", "🛍️ Gider", "📅 Takvim", "💰 Varlık", "💳 Kart", "📝 Geçmiş", "🐺 Tüccar", "🎯 Hedef", "🔁 Abonelik", "🚧 Bütçe", "👻 Enflasyon", "🤖 Danışman", "💸 Borç"])

# --- SEKME 1: KUMANDA ---
with sekmeler[0]:
    st.error(f"💎 GERÇEK NET VARLIĞIN: **{net_worth:,.2f} TL**")
    c1, c2, c3 = st.columns(3)
    c1.metric("Nakit", f"{net_nakit:,.2f} TL")
    c2.metric("Yastık Altı", f"{yastik_tl:,.2f} TL")
    c3.metric("Kart Borcu", f"{kk_borc:,.2f} TL")
    
    if varlik_kats:
        st.divider()
        vk = st.columns(len(varlik_kats))
        for i, (k, t) in enumerate(varlik_kats.items()): vk[i].success(f"**{k}**\n\n{t:,.2f} TL")

    st.divider()
    ca1, ca2 = st.columns(2)
    with ca1:
        st.subheader("🧾 Checklist")
        if not dfs['faturalar'].empty:
            for idx, row in dfs['faturalar'].iterrows():
                f_id = row['id']
                eski = str(row['durum']).lower() == 'true'
                label = f"~~{row['isim']}~~" if eski else row['isim']
                if st.checkbox(label, value=eski, key=f"fchk_{f_id}"):
                    if not eski:
                        update_cell('faturalar', f_id, 'durum', 'True', 3)
                        st.rerun()
                elif eski:
                    update_cell('faturalar', f_id, 'durum', 'False', 3)
                    st.rerun()
            if st.button("🔄 Tikleri Temizle", use_container_width=True):
                for f_id in dfs['faturalar']['id']: update_cell('faturalar', f_id, 'durum', 'False', 3)
                st.rerun()
        else: st.info("Checklist boş.")

    with ca2:
        st.subheader("⏳ Günlük Limit")
        h_tar = st.date_input("Maaş Günü:", min_value=datetime.today())
        k_gun = (h_tar - datetime.today().date()).days
        if k_gun > 0 and net_nakit > 0: st.success(f"Günde maks **{net_nakit/k_gun:,.2f} TL** harcayabilirsin.")
        elif k_gun > 0: st.error("Nakit ekside!")

    st.divider()
    st.subheader("⚖️ 50/30/20 Altın Bütçe Kuralı (Bu Ay)")
    if ay_gelir_top > 0:
        iht_tutar = df_ay_gider[df_ay_gider['ihtiyac_mi'] == 'İhtiyaç']['miktar'].sum() if not df_ay_gider.empty else 0.0
        ist_tutar = df_ay_gider[df_ay_gider['ihtiyac_mi'] == 'İstek']['miktar'].sum() if not df_ay_gider.empty else 0.0
        kalan = ay_gelir_top - iht_tutar - ist_tutar
        c50, c30, c20 = st.columns(3)
        with c50:
            st.info(f"**🛠️ İhtiyaç (Maks %50)**\n\n**%{(iht_tutar/ay_gelir_top)*100:.1f}** ({iht_tutar:,.0f} TL)")
            st.progress(min((iht_tutar/ay_gelir_top), 1.0))
        with c30:
            st.warning(f"**🎮 İstek (Maks %30)**\n\n**%{(ist_tutar/ay_gelir_top)*100:.1f}** ({ist_tutar:,.0f} TL)")
            st.progress(min((ist_tutar/ay_gelir_top), 1.0))
        with c20:
            st.success(f"**💰 Tasarruf (Min %20)**\n\n**%{(kalan/ay_gelir_top)*100:.1f}** ({kalan:,.0f} TL)")
            if kalan > 0: st.progress(min((kalan/ay_gelir_top), 1.0))

# --- SEKME 2: NOTLAR ---
with sekmeler[1]:
    st.subheader("📝 Kişisel Not Defteri")
    with st.form("n_form", clear_on_submit=True):
        baslik = st.text_input("Başlık")
        icerik = st.text_area("İçerik")
        if st.form_submit_button("Kaydet") and baslik and icerik:
            add_row('notlar', {"id": get_new_id(dfs['notlar']), "baslik": baslik, "icerik": icerik, "tarih": datetime.now().strftime("%Y-%m-%d %H:%M")})
            st.success("Kaydedildi!")
            time.sleep(0.5)
            st.rerun()

    if not dfs['notlar'].empty:
        st.divider()
        for _, row in dfs['notlar'].sort_values(by="id", ascending=False).iterrows():
            with st.expander(f"📌 {row['baslik']} ({row['tarih']})"):
                st.write(row['icerik'])
                if st.button("🗑️ Sil", key=f"dn_{row['id']}"):
                    del_row('notlar', row['id'])
                    st.rerun()

# --- SEKME 3: GELİR ---
with sekmeler[2]:
    st.subheader("⚡ Gelir Ekle")
    with st.form("g_form", clear_on_submit=True):
        g_ad = st.text_input("Açıklama")
        g_tutar = st.number_input("Tutar", min_value=0.0, step=100.0)
        if st.form_submit_button("Onayla") and g_tutar > 0:
            add_row('islemler', {"id": get_new_id(dfs['islemler']), "tip": "Gelir", "isim": g_ad, "miktar": g_tutar, "tarih": datetime.now().strftime("%Y-%m-%d %H:%M"), "ihtiyac_mi": "Gelir", "kategori": "Maaş/Gelir"})
            st.success("Eklendi!")
            time.sleep(0.5)
            st.rerun()

# --- SEKME 4: GİDER VE CHECKLIST ---
with sekmeler[3]:
    st.subheader("🛍️ Harcama")
    with st.form("h_form", clear_on_submit=True):
        h_kat = st.selectbox("Kategori", kategoriler)
        h_mik = st.number_input("Tutar", min_value=0.0, step=100.0)
        h_iht = st.radio("Zorunlu mu?", ["İhtiyaç", "İstek"], horizontal=True)
        h_tip = st.radio("Ödeme", ["Nakit / Banka", "Kredi Kartı"], horizontal=True)
        
        t_ay, k_id = 1, None
        if h_tip == "Kredi Kartı" and not dfs['kredi_kartlari'].empty:
            k_dict = dict(zip(dfs['kredi_kartlari']['id'], dfs['kredi_kartlari']['kart_adi']))
            k_id = st.selectbox("Kart", options=list(k_dict.keys()), format_func=lambda x: k_dict[x])
            t_ay = st.number_input("Taksit", min_value=1, step=1, max_value=36)
            
        if st.form_submit_button("Harcamayı İşle") and h_mik > 0:
            iht_durum = "İhtiyaç" if h_iht == "İhtiyaç" else "İstek"
            zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
            if h_tip == "Kredi Kartı" and k_id:
                if t_ay > 1: add_row('taksitler', {"id": get_new_id(dfs['taksitler']), "kart_id": k_id, "aciklama": f"{h_kat} ({iht_durum})", "aylik_tutar": h_mik/t_ay, "kalan_ay": t_ay})
                mevcut_borc = safe_float(dfs['kredi_kartlari'].loc[dfs['kredi_kartlari']['id']==k_id, 'guncel_borc'].iloc[0])
                update_cell('kredi_kartlari', k_id, 'guncel_borc', mevcut_borc + h_mik, 4)
                add_row('islemler', {"id": get_new_id(dfs['islemler']), "tip": "KK Gider", "isim": h_kat, "miktar": h_mik, "tarih": zaman, "ihtiyac_mi": iht_durum, "kategori": h_kat})
            else:
                add_row('islemler', {"id": get_new_id(dfs['islemler']), "tip": "Gider", "isim": h_kat, "miktar": h_mik, "tarih": zaman, "ihtiyac_mi": iht_durum, "kategori": h_kat})
            st.success("İşlendi!")
            time.sleep(0.5)
            st.rerun()

    st.divider()
    st.subheader("📌 Fatura/Görev Ekle")
    with st.form("f_form", clear_on_submit=True):
        f_isim = st.text_input("Adı (Elektrik, Su vb.)")
        if st.form_submit_button("Ekle") and f_isim:
            add_row('faturalar', {"id": get_new_id(dfs['faturalar']), "isim": f_isim, "durum": "False"})
            st.success("Listeye eklendi!")
            time.sleep(0.5)
            st.rerun()
            
    if not dfs['faturalar'].empty:
        with st.expander("🗑️ Checklist'ten Sil"):
            for _, r in dfs['faturalar'].iterrows():
                c1, c2 = st.columns([4,1])
                c1.write(r['isim'])
                if c2.button("Sil", key=f"df_{r['id']}"):
                    del_row('faturalar', r['id'])
                    st.rerun()

# --- SEKME 5: TAKVİM ---
with sekmeler[4]:
    st.subheader("📅 Taksit Takvimi")
    df_taksit = dfs['taksitler'][dfs['taksitler']['kalan_ay'] > 0] if not dfs['taksitler'].empty else pd.DataFrame()
    if df_taksit.empty or dfs['kredi_kartlari'].empty: st.info("Taksit yok.")
    else:
        tv = pd.merge(df_taksit, dfs['kredi_kartlari'], left_on='kart_id', right_on='id', suffixes=('_t', '_k'))
        bg = datetime.now()
        satirlar = []
        for _, r in tv.iterrows():
            for a in range(1, int(r['kalan_ay']) + 1):
                ha = bg.month + a - 1
                ey, ga, gy = ha // 12, (ha % 12) + 1, bg.year + (ha // 12)
                satirlar.append({"S": int(f"{gy}{ga:02d}{int(r['hesap_kesim']):02d}"), "Tarih": f"{int(r['hesap_kesim']):02d}.{ga:02d}.{gy}", "Kart": r['kart_adi'], "Açıklama": f"{r['aciklama']} ({a}. Taksit)", "Tutar": safe_float(r['aylik_tutar'])})
        if satirlar: st.dataframe(pd.DataFrame(satirlar).sort_values("S").drop(columns=["S"]), hide_index=True)
        
        st.divider()
        st.error("🗑️ İptal Et")
        for _, r in tv.iterrows():
            c1, c2, c3, c4 = st.columns([4, 3, 3, 1])
            c1.write(r['aciklama'])
            c2.write(r['kart_adi'])
            c3.write(f"Kalan: {int(r['kalan_ay'])} Ay")
            if c4.button("🗑️", key=f"dt_{r['id_t']}"):
                d_tutar = safe_float(r['aylik_tutar']) * int(r['kalan_ay'])
                m_borc = safe_float(dfs['kredi_kartlari'].loc[dfs['kredi_kartlari']['id']==r['kart_id'], 'guncel_borc'].iloc[0])
                update_cell('kredi_kartlari', r['kart_id'], 'guncel_borc', max(0, m_borc - d_tutar), 4)
                del_row('taksitler', r['id_t'])
                st.rerun()

# --- SEKME 6: VARLIKLAR ---
with sekmeler[5]:
    st.subheader("💰 Varlıklar")
    y1, y2 = st.columns(2)
    with y1:
        with st.form("y_form", clear_on_submit=True):
            sahip = st.selectbox("Kasa", ["Kendim", "Eşim", "Çocuğum", "Ortak Kasa", "Genel Kasa"])
            varlik = st.selectbox("Varlık", ["USD", "EUR", "GA", "Çeyrek Altın", "Yarım Altın", "Tam Altın", "Ata Altın", "BTC", "ETH"])
            islem = st.radio("Tipi", ["Ekle (+)", "Çıkar (-)"], horizontal=True)
            mik = st.number_input("Miktar", min_value=0.0, format="%.6f")
            if st.form_submit_button("Kaydet") and mik > 0:
                t_isim = f"{sahip} - {varlik}"
                mevcut = safe_float(dfs['yastik_alti'].loc[dfs['yastik_alti']['varlik_tipi']==t_isim, 'miktar'].iloc[0]) if not dfs['yastik_alti'][dfs['yastik_alti']['varlik_tipi']==t_isim].empty else 0.0
                yeni = mevcut + mik if "Ekle" in islem else max(0.0, mevcut - mik)
                update_yastik(t_isim, yeni)
                st.success("Güncellendi!")
                time.sleep(0.5)
                st.rerun()
        if st.button("🗑️ Sıfırlananları Temizle"):
            for _, r in dfs['yastik_alti'][dfs['yastik_alti']['miktar'] == 0.0].iterrows():
                idx = dfs['yastik_alti'].index[dfs['yastik_alti']['varlik_tipi'] == r['varlik_tipi']].tolist()[0]
                st.session_state.wss['yastik_alti'].delete_rows(int(idx + 2))
            st.session_state.dfs['yastik_alti'] = dfs['yastik_alti'][dfs['yastik_alti']['miktar'] > 0.0].reset_index(drop=True)
            st.rerun()
            
    with y2:
        st.write("### 🗂️ Kasa Detayı")
        if not dfs['yastik_alti'].empty:
            for _, r in dfs['yastik_alti'][dfs['yastik_alti']['miktar']>0].iterrows():
                st.markdown(f"🔹 **{r['varlik_tipi'].replace(' - ', ' ➡ ')}** : {safe_float(r['miktar']):,.2f}")

# --- SEKME 7: KARTLAR ---
with sekmeler[6]:
    st.subheader("💳 Kartlar")
    k1, k2 = st.columns(2)
    with k1:
        with st.form("k_form", clear_on_submit=True):
            k_ad = st.text_input("Kart Adı")
            k_lim = st.number_input("Limit", min_value=0.0)
            k_kes = st.number_input("Kesim Günü", min_value=1, max_value=31, value=15)
            if st.form_submit_button("Ekle") and k_ad:
                add_row('kredi_kartlari', {"id": get_new_id(dfs['kredi_kartlari']), "kart_adi": k_ad, "kart_limit": k_lim, "guncel_borc": 0.0, "hesap_kesim": k_kes})
                st.rerun()
    with k2:
        if not dfs['kredi_kartlari'].empty:
            for _, r in dfs['kredi_kartlari'].iterrows():
                c1, c2, c3, c4 = st.columns([3,2,2,1])
                c1.write(r['kart_adi'])
                c2.write(f"Limit: {safe_float(r['kart_limit']):,.0f}")
                c3.write(f"Borç: {safe_float(r['guncel_borc']):,.0f}")
                if c4.button("🗑️", key=f"dk_{r['id']}"):
                    del_row('kredi_kartlari', r['id'])
                    # Taksitleri de sil
                    for _, tr in dfs['taksitler'][dfs['taksitler']['kart_id'] == r['id']].iterrows(): del_row('taksitler', tr['id'])
                    st.rerun()

# --- SEKME 8: GEÇMİŞ ---
with sekmeler[7]:
    st.subheader("📝 İşlem Geçmişi (Son 50)")
    if not dfs['islemler'].empty:
        for _, r in dfs['islemler'].tail(50).iloc[::-1].iterrows():
            c1, c2, c3, c4, c5 = st.columns([1.5, 1, 3, 1.5, 1])
            c1.write(str(r['tarih'])[:10])
            c2.markdown("🟢" if r['tip']=="Gelir" else "🔴")
            c3.write(r['isim'])
            c4.write(f"{safe_float(r['miktar']):,.2f} TL")
            if c5.button("🗑️", key=f"disl_{r['id']}"):
                del_row('islemler', r['id'])
                st.rerun()

# --- SEKME 9: TÜCCAR ---
with sekmeler[8]:
    st.subheader("🐺 Tüccar (Al-Sat)")
    with st.form("t_form", clear_on_submit=True):
        urun = st.text_input("Ürün Adı")
        alis = st.number_input("Alış Fiyatı", min_value=0.0)
        if st.form_submit_button("Ekle") and urun and alis > 0:
            add_row('ticaret', {"id": get_new_id(dfs['ticaret']), "urun_adi": urun, "alis_fiyati": alis, "tahmini_satis": 0.0})
            add_row('islemler', {"id": get_new_id(dfs['islemler']), "tip": "Gider", "isim": f"Mal Alışı: {urun}", "miktar": alis, "tarih": datetime.now().strftime("%Y-%m-%d %H:%M"), "ihtiyac_mi": "İhtiyaç", "kategori": "Donanım (Al-Sat)"})
            st.success("Eklendi!")
            time.sleep(0.5)
            st.rerun()
            
    if not dfs['ticaret'].empty:
        t1, t2 = st.columns(2)
        with t1:
            st.write("### 📦 Envanter")
            for _, r in dfs['ticaret'][dfs['ticaret']['tahmini_satis'] == 0.0].iterrows():
                with st.expander(f"🛒 {r['urun_adi']} (Maliyet: {safe_float(r['alis_fiyati']):,.0f})"):
                    sat = st.number_input("Kaça Sattın?", min_value=0.0, key=f"ts_{r['id']}")
                    c1, c2 = st.columns(2)
                    if c1.button("Sat", key=f"tsb_{r['id']}") and sat > 0:
                        update_cell('ticaret', r['id'], 'tahmini_satis', sat, 4)
                        add_row('islemler', {"id": get_new_id(dfs['islemler']), "tip": "Gelir", "isim": f"Mal Satışı: {r['urun_adi']}", "miktar": sat, "tarih": datetime.now().strftime("%Y-%m-%d %H:%M"), "ihtiyac_mi": "Gelir", "kategori": "Donanım (Al-Sat)"})
                        st.rerun()
                    if c2.button("Sil", key=f"td_{r['id']}"):
                        del_row('ticaret', r['id'])
                        st.rerun()
        with t2:
            st.write("### 💸 Satılanlar")
            for _, r in dfs['ticaret'][dfs['ticaret']['tahmini_satis'] > 0.0].iterrows():
                st.write(f"**{r['urun_adi']}** | Kâr: **{safe_float(r['tahmini_satis']) - safe_float(r['alis_fiyati']):,.0f} TL**")

# --- SEKME 10: HEDEFLER ---
with sekmeler[9]:
    st.subheader("🎯 Hedefler")
    if not dfs['hedefler'].empty:
        for _, r in dfs['hedefler'].iterrows():
            t = safe_float(r['hedef_tutar'])
            b = safe_float(r['biriken'])
            c1, c2, c3 = st.columns([5,4,1])
            c1.write(f"**{r['hedef_adi']}** ({b:,.0f}/{t:,.0f})")
            c2.progress(min(b/t if t>0 else 0, 1.0))
            if c3.button("🗑️", key=f"hds_{r['id']}"):
                del_row('hedefler', r['id'])
                st.rerun()
    st.divider()
    with st.form("h_form"):
        h_ad = st.text_input("Hedef")
        h_tut = st.number_input("Hedef Tutar", min_value=0.0)
        h_bir = st.number_input("Şu an elindeki", min_value=0.0)
        if st.form_submit_button("Oluştur") and h_ad:
            add_row('hedefler', {"id": get_new_id(dfs['hedefler']), "hedef_adi": h_ad, "hedef_tutar": h_tut, "biriken": h_bir})
            st.rerun()
    if not dfs['hedefler'].empty:
        with st.form("h_para"):
            h_sec = st.selectbox("Hedef Seç", dfs['hedefler']['hedef_adi'])
            ekle = st.number_input("Eklenecek", min_value=0.0)
            if st.form_submit_button("Para At") and ekle > 0:
                h_id = dfs['hedefler'].loc[dfs['hedefler']['hedef_adi']==h_sec, 'id'].iloc[0]
                m_bir = safe_float(dfs['hedefler'].loc[dfs['hedefler']['id']==h_id, 'biriken'].iloc[0])
                update_cell('hedefler', h_id, 'biriken', m_bir + ekle, 4)
                add_row('islemler', {"id": get_new_id(dfs['islemler']), "tip": "Gider", "isim": f"Kumbara: {h_sec}", "miktar": ekle, "tarih": datetime.now().strftime("%Y-%m-%d %H:%M"), "ihtiyac_mi": "İhtiyaç", "kategori": "Diğer"})
                st.success("Eklendi!")
                time.sleep(0.5)
                st.rerun()

# --- SEKME 11: ABONELİKLER ---
with sekmeler[10]:
    st.subheader("🧛‍♂️ Abonelikler")
    with st.form("a_form"):
        a_isim = st.text_input("Abonelik Adı")
        a_tut = st.number_input("Tutar", min_value=0.0)
        a_gun = st.number_input("Çekim Günü", min_value=1, max_value=31)
        if st.form_submit_button("Ekle") and a_isim:
            add_row('abonelikler', {"id": get_new_id(dfs['abonelikler']), "isim": a_isim, "tutar": a_tut, "odeme_gunu": a_gun})
            st.rerun()
    if not dfs['abonelikler'].empty:
        st.error(f"Aylık Toplam: **{dfs['abonelikler']['tutar'].apply(safe_float).sum():,.2f} TL**")
        for _, r in dfs['abonelikler'].iterrows():
            c1, c2, c3 = st.columns([4,2,1])
            c1.write(r['isim'])
            c2.write(f"{safe_float(r['tutar']):,.2f} TL")
            if c3.button("🗑️", key=f"ab_{r['id']}"):
                del_row('abonelikler', r['id'])
                st.rerun()

# --- SEKME 12: BÜTÇE LİMİTLERİ ---
with sekmeler[11]:
    st.subheader("🚧 Bütçe")
    with st.form("b_form"):
        b_kat = st.selectbox("Kategori", kategoriler)
        b_lim = st.number_input("Limit", min_value=0.0)
        if st.form_submit_button("Güncelle"):
            idx_list = dfs['butceler'].index[dfs['butceler']['kategori'] == b_kat].tolist()
            if idx_list: update_cell('butceler', dfs['butceler'].at[idx_list[0], 'id'], 'limit_tutar', b_lim, 3)
            else: add_row('butceler', {"id": get_new_id(dfs['butceler']), "kategori": b_kat, "limit_tutar": b_lim})
            st.rerun()
    if not dfs['butceler'].empty:
        for _, r in dfs['butceler'][dfs['butceler']['limit_tutar'].apply(safe_float) > 0].iterrows():
            harc = df_ay_gider[df_ay_gider['kategori'] == r['kategori']]['miktar'].sum() if not df_ay_gider.empty else 0.0
            lim = safe_float(r['limit_tutar'])
            st.write(f"**{r['kategori']}**: {harc:,.0f} / {lim:,.0f} TL")
            st.progress(min(harc/lim, 1.0))

# --- SEKME 13: ENFLASYON ---
with sekmeler[12]:
    st.subheader("👻 Enflasyon")
    p = st.number_input("Mevcut Tutar (TL)", value=15000)
    e = st.slider("Enflasyon (%)", 0, 150, 65)
    y = st.slider("Kaç Yıl Sonrası?", 1, 10, 1)
    st.error(f"Sonuç: **{p * ((1 + (e / 100)) ** y):,.0f} TL**")

# --- SEKME 14: DANIŞMAN ---
with sekmeler[13]:
    st.subheader("🤖 Analiz")
    if not df_ay_gider.empty:
        tah_df = df_ay_gider.groupby('kategori')['miktar'].sum().reset_index()
        tah_df['Ay Sonu Tahmini'] = (tah_df['miktar'] / datetime.now().day) * 30
        st.plotly_chart(px.bar(tah_df, x="kategori", y=["miktar", "Ay Sonu Tahmini"], barmode="group"), use_container_width=True)

# --- SEKME 15: BORÇLAR ---
with sekmeler[14]:
    st.subheader("💳 Kart Ödeme")
    if not dfs['kredi_kartlari'].empty:
        with st.form("ko_form"):
            ks = st.selectbox("Kart", dfs['kredi_kartlari']['kart_adi'])
            om = st.number_input("Ödeme Tutarı", min_value=0.0)
            if st.form_submit_button("Öde") and om > 0:
                k_id = dfs['kredi_kartlari'].loc[dfs['kredi_kartlari']['kart_adi']==ks, 'id'].iloc[0]
                m_b = safe_float(dfs['kredi_kartlari'].loc[dfs['kredi_kartlari']['id']==k_id, 'guncel_borc'].iloc[0])
                update_cell('kredi_kartlari', k_id, 'guncel_borc', max(0, m_b - om), 4)
                add_row('islemler', {"id": get_new_id(dfs['islemler']), "tip": "Gider", "isim": f"{ks} Ödeme", "miktar": om, "tarih": datetime.now().strftime("%Y-%m-%d %H:%M"), "ihtiyac_mi": "İhtiyaç", "kategori": "Diğer"})
                st.success("Ödendi!")
                time.sleep(0.5)
                st.rerun()
                
    st.divider()
    st.subheader("🤝 Elden Borç")
    with st.form("eb_form"):
        e_ad = st.text_input("Kişi/Kurum")
        e_mik = st.number_input("Toplam Borç", min_value=0.0)
        if st.form_submit_button("Ekle") and e_ad:
            add_row('manuel_borclar', {"id": get_new_id(dfs['manuel_borclar']), "borc_adi": e_ad, "toplam_miktar": e_mik, "odenen": 0.0, "tarih": datetime.now().strftime("%Y-%m-%d")})
            st.rerun()
    if not dfs['manuel_borclar'].empty:
        for _, r in dfs['manuel_borclar'].iterrows():
            c1, c2, c3, c4 = st.columns([3,2,2,1])
            c1.write(r['borc_adi'])
            c2.write(f"Kalan: {safe_float(r['toplam_miktar']) - safe_float(r['odenen']):,.0f}")
            ode = c3.number_input("Öde", min_value=0.0, key=f"eb_{r['id']}")
            if c4.button("Öde", key=f"ebbtn_{r['id']}") and ode > 0:
                update_cell('manuel_borclar', r['id'], 'odenen', safe_float(r['odenen']) + ode, 4)
                st.rerun()
