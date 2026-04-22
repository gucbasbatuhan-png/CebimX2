import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
import plotly.express as px
import yfinance as yf
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. SAYFA AYARLARI VE TASARIM ---
st.set_page_config(page_title="CebimX Pro Finans", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    div[data-testid="metric-container"] { background-color: #1e293b; border: 1px solid #334155; padding: 15px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); }
    </style>
""", unsafe_allow_html=True)

# --- 2. GOOGLE SHEETS BAĞLANTI & KURŞUN GEÇİRMEZ RAM MOTORU ---
class DirtyTrackerWS:
    def __init__(self, ws, sheet_name):
        self.ws = ws
        self.sheet_name = sheet_name
        
    def _mark_dirty(self):
        if 'dirty_sheets' not in st.session_state:
            st.session_state.dirty_sheets = set()
        st.session_state.dirty_sheets.add(self.sheet_name)
        
    def _retry_operation(self, operation, *args, **kwargs):
        self._mark_dirty()
        for i in range(3):
            try:
                return operation(*args, **kwargs)
            except Exception as e:
                if "429" in str(e) and i < 2:
                    time.sleep(2)
                else:
                    raise e

    def append_row(self, *args, **kwargs):
        return self._retry_operation(self.ws.append_row, *args, **kwargs)
        
    def update_cell(self, *args, **kwargs):
        return self._retry_operation(self.ws.update_cell, *args, **kwargs)
        
    def delete_rows(self, *args, **kwargs):
        return self._retry_operation(self.ws.delete_rows, *args, **kwargs)
        
    def insert_row(self, *args, **kwargs):
        return self._retry_operation(self.ws.insert_row, *args, **kwargs)

@st.cache_resource
def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["google_auth"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

@st.cache_resource(ttl=3600)
def get_all_worksheets():
    client = get_gsheet_client()
    sh = client.open_by_url(st.secrets["gsheets"]["url"])
    return sh, {ws.title: ws for ws in sh.worksheets()}

@st.cache_data(ttl=3600)
def fetch_sheet_data(sheet_name, refresh_token):
    sh, worksheets = get_all_worksheets()
    ws = worksheets.get(sheet_name)
    if ws:
        for i in range(3):
            try:
                return ws.get_all_records()
            except Exception as e:
                if "429" in str(e) and i < 2: time.sleep(2)
                else: return []
    return []

def get_df(sheet_name):
    sh, worksheets = get_all_worksheets()
    cols = {
        "islemler": ["id", "tip", "isim", "miktar", "tarih", "ihtiyac_mi", "kategori"],
        "ticaret": ["id", "urun_adi", "alis_fiyati", "tahmini_satis"],
        "hedefler": ["id", "hedef_adi", "hedef_tutar", "biriken"],
        "kredi_kartlari": ["id", "kart_adi", "kart_limit", "guncel_borc", "hesap_kesim"],
        "taksitler": ["id", "kart_id", "aciklama", "aylik_tutar", "kalan_ay"],
        "yastik_alti": ["varlik_tipi", "miktar"],
        "manuel_borclar": ["id", "borc_adi", "toplam_miktar", "odenen", "tarih"],
        "krediler": ["id", "kredi_adi", "toplam_borc", "odenen", "aylik_taksit", "kalan_ay", "tarih"],
        "abonelikler": ["id", "isim", "tutar", "odeme_gunu"],
        "butceler": ["id", "kategori", "limit_tutar"],
        "faturalar": ["id", "isim", "durum"],
        "notlar": ["id", "baslik", "icerik", "tarih"]
    }
    
    if sheet_name not in worksheets:
        ws = sh.add_worksheet(title=sheet_name, rows="100", cols="20")
        ws.append_row(cols[sheet_name])
        worksheets[sheet_name] = ws
        return pd.DataFrame(columns=cols[sheet_name]), DirtyTrackerWS(ws, sheet_name)
        
    ws = worksheets[sheet_name]
    if 'dirty_sheets' not in st.session_state: st.session_state.dirty_sheets = set()
    if 'refresh_tokens' not in st.session_state: st.session_state.refresh_tokens = {}
        
    if sheet_name in st.session_state.dirty_sheets:
        st.session_state.refresh_tokens[sheet_name] = time.time()
        st.session_state.dirty_sheets.remove(sheet_name)
        
    token = st.session_state.refresh_tokens.get(sheet_name, 0)
    data = fetch_sheet_data(sheet_name, token)
    df = pd.DataFrame(data)
    
    if not df.empty and 'id' not in df.columns and sheet_name in cols:
        ws.insert_row(cols[sheet_name], index=1)
        st.session_state.dirty_sheets.add(sheet_name)
        data = ws.get_all_records()
        df = pd.DataFrame(data)
    if df.empty: df = pd.DataFrame(columns=cols.get(sheet_name, []))
    return df, DirtyTrackerWS(ws, sheet_name)

def get_new_id(df):
    return int(df['id'].max() + 1) if not df.empty and 'id' in df.columns else 1

def get_row_idx(df, col_name, value):
    try: return int(df.index[df[col_name].astype(str) == str(value)].tolist()[0] + 2)
    except: return None

def clear_cache_and_rerun():
    st.rerun()

def clean_numeric(df, columns):
    if not df.empty:
        for col in columns:
            if col in df.columns:
                df[col] = df[col].astype(str).str.replace(',', '.').str.replace(' ', '')
                df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
    return df

def safe_float(val):
    try:
        if isinstance(val, str): val = val.replace(',', '.')
        if val == "" or pd.isna(val): return 0.0
        return float(val)
    except: return 0.0

# --- SERİ HESAPLAMA MOTORU (🔥 & ❄️) ---
def calculate_streaks(df):
    if df.empty: return 0, 0
    df = df.copy()
    df['tarih_sadece'] = pd.to_datetime(df['tarih'], errors='coerce').dt.date
    bugun = datetime.now().date()
    
    alev = 0
    t_giderler = df[df['tip'].isin(['Gider', 'KK Gider'])]
    for i in range(365):
        kontrol_tarihi = bugun - timedelta(days=i)
        gunluk_harcama = t_giderler[t_giderler['tarih_sadece'] == kontrol_tarihi]
        if gunluk_harcama.empty: alev += 1
        else: break
            
    buz = 0
    keyfi_giderler = df[(df['tip'].isin(['Gider', 'KK Gider'])) & (df['ihtiyac_mi'] == 'İstek')]
    for i in range(365):
        kontrol_tarihi = bugun - timedelta(days=i)
        gunluk_keyfi = keyfi_giderler[keyfi_giderler['tarih_sadece'] == kontrol_tarihi]
        if gunluk_keyfi.empty: buz += 1
        else: break
            
    return alev, buz

# --- 3. GİRİŞ (LOGIN) SİSTEMİ (YENİLENMİŞ HATASIZ TASARIM) ---
if 'giris_yapildi' not in st.session_state:
    st.session_state.giris_yapildi = False

if not st.session_state.giris_yapildi:
    st.title("🔐 CebimX Giriş Ekranı")
    k1, k2, k3 = st.columns([1, 2, 1])
    with k2:
        with st.form("giris_formu", clear_on_submit=False):
            st.subheader("Hoş Geldiniz")
            kadi = st.text_input("Kullanıcı Adı")
            sifre = st.text_input("Şifre", type="password")
            giris_btn = st.form_submit_button("Giriş Yap", use_container_width=True)
            
            if giris_btn:
                if kadi == "admin" and sifre == st.secrets["kullanici"]["sifre"]:
                    st.success("✅ Başarıyla giriş yaptınız!")
                    time.sleep(1) 
                    st.session_state.giris_yapildi = True
                    st.rerun()
                else: 
                    st.error("❌ Hatalı kullanıcı adı veya şifre!")
    st.stop()

# --- 4. YAN MENÜ ---
with st.sidebar:
    st.success("👤 Hesap: **Ana Yönetici**")
    st.divider()
    st.write("🗓️ **Bütçe Döngüsü**")
    bugun_dt = datetime.now()
    if 'dongu_baslangici' not in st.session_state:
        st.session_state.dongu_baslangici = datetime(bugun_dt.year, bugun_dt.month, 1).date()
    dongu_baslangici = st.date_input("Maaş / Başlangıç Tarihi:", value=st.session_state.dongu_baslangici)
    st.session_state.dongu_baslangici = dongu_baslangici
    dongu_dt = pd.to_datetime(dongu_baslangici)
    st.info("💡 Maaşın geçen ayın sonunda yattıysa o tarihi seç ki bütçen doğru hesaplansın.")
    st.divider()
    if st.button("🚪 Çıkış Yap", use_container_width=True):
        st.session_state.giris_yapildi = False
        st.rerun()

st.title("💸 CebimX:Kişisel Finans Yönetimi")

# --- 5. VERİLERİ YÜKLE ---
try:
    df_islemler, ws_islemler = get_df("islemler")
    df_ticaret, ws_ticaret = get_df("ticaret")
    df_hedefler, ws_hedefler = get_df("hedefler")
    df_kartlar, ws_kartlar = get_df("kredi_kartlari")
    df_taksitler, ws_taksitler = get_df("taksitler")
    df_yastik, ws_yastik = get_df("yastik_alti")
    df_borclar, ws_borclar = get_df("manuel_borclar")
    df_krediler, ws_krediler = get_df("krediler")
    df_abonelikler, ws_abonelikler = get_df("abonelikler")
    df_butceler, ws_butceler = get_df("butceler")
    df_faturalar, ws_faturalar = get_df("faturalar")
    df_notlar, ws_notlar = get_df("notlar")

    df_islemler = clean_numeric(df_islemler, ['miktar'])
    df_kartlar = clean_numeric(df_kartlar, ['kart_limit', 'guncel_borc'])
    df_borclar = clean_numeric(df_borclar, ['toplam_miktar', 'odenen'])
    df_krediler = clean_numeric(df_krediler, ['toplam_borc', 'odenen', 'aylik_taksit'])
except Exception as e:
    st.error(f"⚠️ Veriler yüklenirken hata oluştu. Birazdan tekrar deneyin.")
    st.stop()

if df_yastik.empty:
    ws_yastik.append_row(['Genel Kasa - USD', 0])
    ws_yastik.append_row(['Genel Kasa - EUR', 0])
    ws_yastik.append_row(['Genel Kasa - GA', 0])
    ws_yastik.append_row(['Genel Kasa - BTC', 0])
    ws_yastik.append_row(['Genel Kasa - ETH', 0])
    clear_cache_and_rerun()

kategoriler = ["Market", "Kira", "Fatura", "Eğlence", "Oyun & Yazılım", "Donanım (Al-Sat)", "Diğer", "Proje & Geliştirici", "Eğitim", "Kişisel Gelişim", "Dışarıdan Yeme", "Dışarıdan İçme", "Ulaşım", "Seyahat", "Giyim", "Kişisel Bakım", "Sağlık", "Eczane", "Berber", "Büşra Kuaför", "Elektrik", "Su", "Doğalgaz", "İnternet", "Aidat", "Depo Kira", "Büşra Telefon", "Batu Telefon", "Ek Hesap Ödemesi"]

if df_butceler.empty:
    for i, kat in enumerate(kategoriler):
        ws_butceler.append_row([i+1, kat, 0])
    clear_cache_and_rerun()

# --- 6. CANLI PİYASALAR ---
st.subheader("🌍 Canlı Piyasalar ve Kripto Radarı")
if 'usd_try' not in st.session_state:
    st.session_state.usd_try = st.session_state.eur_try = st.session_state.gr_altin = st.session_state.btc_try = st.session_state.eth_try = 0.0

kol_kur1, kol_kur2, kol_kur3, kol_kur4, kol_kur5, kol_kur6 = st.columns(6)
with kol_kur6:
    if st.button("🔄 Kurları Güncelle"):
        try:
            usd = yf.Ticker("TRY=X").history(period="1d")['Close'].iloc[-1]
            st.session_state.usd_try = usd
            st.session_state.eur_try = yf.Ticker("EURTRY=X").history(period="1d")['Close'].iloc[-1]
            st.session_state.gr_altin = (yf.Ticker("GC=F").history(period="1d")['Close'].iloc[-1] / 31.1034768) * usd
            st.session_state.btc_try = yf.Ticker("BTC-USD").history(period="1d")['Close'].iloc[-1] * usd
            st.session_state.eth_try = yf.Ticker("ETH-USD").history(period="1d")['Close'].iloc[-1] * usd
            st.success("Kurlar çekildi!")
        except: st.error("Kur hatası!")

kol_kur1.info(f"💵 USD: **{st.session_state.usd_try:,.2f}**")
kol_kur2.info(f"💶 EUR: **{st.session_state.eur_try:,.2f}**")
kol_kur3.warning(f"🥇 Altın: **{st.session_state.gr_altin:,.2f}**")
kol_kur4.success(f"₿ BTC: **{st.session_state.btc_try:,.0f} TL**")
kol_kur5.success(f"⟠ ETH: **{st.session_state.eth_try:,.0f} TL**")
st.divider()

# --- 7. ORTAK VERİLER VE GERÇEK NET VARLIK ---
alev_serisi, buz_serisi = calculate_streaks(df_islemler)

if not df_islemler.empty:
    df_islemler['gercek_tarih'] = pd.to_datetime(df_islemler['tarih'], errors='coerce')
    toplam_gelir = df_islemler[df_islemler['tip'] == 'Gelir']['miktar'].sum()
    toplam_nakit_gider = df_islemler[df_islemler['tip'] == 'Gider']['miktar'].sum()
    df_bu_ay_giderler = df_islemler[(df_islemler['tip'].isin(['Gider', 'KK Gider'])) & (df_islemler['gercek_tarih'] >= dongu_dt)]
    df_bu_ay_gelirler = df_islemler[(df_islemler['tip'] == 'Gelir') & (df_islemler['gercek_tarih'] >= dongu_dt)]
    bu_ay_toplam_gelir = df_bu_ay_gelirler['miktar'].sum() if not df_bu_ay_gelirler.empty else 0.0
else:
    toplam_gelir = toplam_nakit_gider = bu_ay_toplam_gelir = 0.0
    df_bu_ay_giderler = pd.DataFrame()

net_nakit = toplam_gelir - toplam_nakit_gider
toplam_kk_borc = df_kartlar['guncel_borc'].sum() if not df_kartlar.empty else 0.0
toplam_manuel_borc = (pd.to_numeric(df_borclar['toplam_miktar']).sum() - pd.to_numeric(df_borclar['odenen']).sum()) if not df_borclar.empty else 0.0
toplam_kredi_borcu = (pd.to_numeric(df_krediler['toplam_borc']).sum() - pd.to_numeric(df_krediler['odenen']).sum()) if not df_krediler.empty else 0.0
toplam_diger_borclar = toplam_manuel_borc + toplam_kredi_borcu

if 'usd_try' not in st.session_state: st.session_state.usd_try = 32.5
toplam_yastik_tl = 0.0
varlik_kats = {}
if not df_yastik.empty:
    for _, r in df_yastik.iterrows():
        m = safe_float(r['miktar'])
        tip = str(r['varlik_tipi'])
        kat = tip.split(" - ")[0] if " - " in tip else "Genel"
        b = tip.split(" - ")[-1] if " - " in tip else tip
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
        toplam_yastik_tl += tl
        varlik_kats[kat] = varlik_kats.get(kat, 0.0) + tl

gercek_net_varlik = net_nakit + toplam_yastik_tl - toplam_kk_borc - toplam_diger_borclar

# --- 8. SEKMELER ---
sekmeler = st.tabs(["📊 Kumanda", "🗒️ Notlar", "🟢 Gelir", "🛍️ Gider", "📅 Takvim", "💰 Varlık", "💳 Kart", "📝 Geçmiş", "🐺 Tüccar", "🎯 Hedef", "🔁 Abonelik", "🚧 Bütçe", "👻 Enflasyon", "🤖 Danışman", "💸 Borç"])

# --- SEKME 1: KUMANDA ---
with sekmeler[0]:
    col_s1, col_s2, col_s3 = st.columns([1, 1, 2])
    with col_s1: st.metric("🔥 Alev Serisi", f"{alev_serisi} Gün", help="Hiç harcama yapmadığın gün sayısı")
    with col_s2: st.metric("❄️ Buz Serisi", f"{buz_serisi} Gün", help="Sadece 'İhtiyaç' aldığın gün sayısı")
    with col_s3:
        if alev_serisi >= 3: st.success(f"Dostum yanıyorsun! {alev_serisi} gündür kuruş harcamadın. 🔥")
        elif buz_serisi >= 5: st.info(f"Tam bir irade ustasısın. {buz_serisi} gündür keyfi harcama yok! ❄️")
        else: st.write("Harika gidiyorsun kanka, tasarruf ettikçe serilerin artacak!")

    st.divider()
    c_net, c_goz = st.columns([5, 1])
    with c_net: st.error(f"💎 GERÇEK NET VARLIĞIN: **{gercek_net_varlik:,.2f} TL**")
    with c_goz: borclari_goster = st.toggle("👁️ Borçları Göster", value=False)

    kol1, kol2, kol3, kol4 = st.columns(4)
    kol1.metric("Net Nakit (TL)", f"{net_nakit:,.2f} TL")
    kol2.metric("Yastık Altı", f"{toplam_yastik_tl:,.2f} TL")
    if borclari_goster:
        kol3.metric("Kart Borcu", f"{toplam_kk_borc:,.2f} TL")
        kol4.metric("Elden / Kredi", f"{toplam_diger_borclar:,.2f} TL")
    else:
        kol3.metric("Kart Borcu", "👀 Gizli")
        kol4.metric("Elden / Kredi", "👀 Gizli")

    if varlik_kats:
        st.divider()
        vk = st.columns(len(varlik_kats))
        for i, (kat, tutar) in enumerate(varlik_kats.items()): vk[i].success(f"**{kat}**\n\n{tutar:,.2f} TL")

    st.divider()
    ca1, ca2 = st.columns([1, 1])
    with ca1:
        st.subheader("🧾 Checklist")
        if not df_faturalar.empty:
            for idx, row in df_faturalar.iterrows():
                f_id = str(row['id'])
                eski = str(row['durum']).lower() == 'true'
                label = f"~~{row['isim']}~~" if eski else row['isim']
                if st.checkbox(label, value=eski, key=f"fchk_{idx}_{f_id}"):
                    ridx = get_row_idx(df_faturalar, 'id', f_id)
                    if ridx: ws_faturalar.update_cell(ridx, 3, str(not eski)); clear_cache_and_rerun()
            if st.button("🔄 Yeni Ay: Tüm Tikleri Temizle", use_container_width=True):
                for i in range(len(df_faturalar)): ws_faturalar.update_cell(i + 2, 3, "False")
                clear_cache_and_rerun()
        else: st.info("Checklist boş.")
    with ca2:
        st.subheader("⏳ Günlük Limit")
        h_tarih = st.date_input("Maaş Günü:", min_value=datetime.today())
        k_gun = (h_tarih - datetime.today().date()).days
        if k_gun > 0 and net_nakit > 0: st.success(f"Günde maks **{net_nakit/k_gun:,.2f} TL** harcayabilirsin.")
        elif k_gun > 0: st.error("Nakit ekside!")

    st.divider()
    st.subheader("⚖️ 50/30/20 Altın Bütçe Kuralı (Maaş Döngüsü)")
    if bu_ay_toplam_gelir > 0:
        i_tutar = df_bu_ay_giderler[df_bu_ay_giderler['ihtiyac_mi'] == 'İhtiyaç']['miktar'].sum() if not df_bu_ay_giderler.empty else 0.0
        k_tutar = df_bu_ay_giderler[df_bu_ay_giderler['ihtiyac_mi'] == 'İstek']['miktar'].sum() if not df_bu_ay_giderler.empty else 0.0
        kalan = bu_ay_toplam_gelir - i_tutar - k_tutar
        c50, c30, c20 = st.columns(3)
        with c50:
            st.info(f"**🛠️ İhtiyaç (Maks %50)**\n\n**%{(i_tutar/bu_ay_toplam_gelir)*100:.1f}** ({i_tutar:,.0f} TL)")
            st.progress(min(i_tutar/bu_ay_toplam_gelir, 1.0))
        with c30:
            st.warning(f"**🎮 İstek (Maks %30)**\n\n**%{(k_tutar/bu_ay_toplam_gelir)*100:.1f}** ({k_tutar:,.0f} TL)")
            st.progress(min(k_tutar/bu_ay_toplam_gelir, 1.0))
        with c20:
            st.success(f"**💰 Tasarruf (Min %20)**\n\n**%{(kalan/bu_ay_toplam_gelir)*100:.1f}** ({kalan:,.0f} TL)")
            if kalan > 0: st.progress(min(kalan/bu_ay_toplam_gelir, 1.0))
    
    st.divider()
    if not df_islemler.empty:
        csv_data = df_islemler.drop(columns=['gercek_tarih'], errors='ignore').to_csv(index=False).encode('utf-8')
        st.download_button("📊 Tüm Muhasebe Geçmişini İndir (CSV)", data=csv_data, file_name=f"cebimx_dokum_{datetime.now().strftime('%Y%m%d')}.csv", mime="text/csv", use_container_width=True)

# --- SEKME 2: NOTLAR ---
with sekmeler[1]:
    st.subheader("📝 Kişisel Not Defteri")
    with st.form("n_form", clear_on_submit=True):
        n_baslik = st.text_input("Başlık")
        n_icerik = st.text_area("İçerik")
        if st.form_submit_button("Kaydet") and n_baslik:
            ws_notlar.append_row([get_new_id(df_notlar), n_baslik, n_icerik, datetime.now().strftime("%Y-%m-%d %H:%M")])
            st.success("Kaydedildi!"); time.sleep(1); clear_cache_and_rerun()
            
    st.divider()
    if not df_notlar.empty:
        for idx, row in df_notlar.sort_values(by="id", ascending=False).iterrows():
            with st.expander(f"📌 {row['baslik']} ({row['tarih']})"):
                st.write(row['icerik'])
                if st.button("🗑️ Sil", key=f"del_not_{row['id']}_{idx}"):
                    ridx = get_row_idx(df_notlar, 'id', row['id'])
                    if ridx: ws_notlar.delete_rows(ridx); clear_cache_and_rerun()

# --- SEKME 3: GELİRLER ---
with sekmeler[2]:
    st.subheader("⚡ Gelir Ekle")
    with st.form("g_form", clear_on_submit=True):
        g_ad = st.text_input("Açıklama")
        g_mik = st.number_input("Tutar (TL)", min_value=0.0, step=100.0)
        if st.form_submit_button("Onayla") and g_mik > 0:
            ws_islemler.append_row([get_new_id(df_islemler), "Gelir", g_ad, g_mik, datetime.now().strftime("%Y-%m-%d %H:%M"), "Gelir", "Maaş/Gelir"])
            st.success("Eklendi!"); time.sleep(1); clear_cache_and_rerun()

# --- SEKME 4: GİDERLER (YENİLENMİŞ HEPSİ BİR ARADA ASİSTAN) ---
with sekmeler[3]:
    st.subheader("🛍️ Akıllı Harcama Asistanı")
    
    islem_modu = st.radio("İşlem Türü Seçin:", ["🛍️ Yeni Harcama Gir", "💳 Kart Borcu / Ekstre Öde"], horizontal=True, label_visibility="collapsed")
    
    if "Yeni Harcama" in islem_modu:
        if not df_kartlar.empty:
            bugun_g = datetime.now().day
            e_kart, max_g = None, -1
            for _, row in df_kartlar.iterrows():
                k_g = int(row['hesap_kesim']) - bugun_g if int(row['hesap_kesim']) > bugun_g else (int(row['hesap_kesim']) + 30) - bugun_g
                if k_g > max_g and (safe_float(row['kart_limit']) - safe_float(row['guncel_borc'])) > 0:
                    max_g, e_kart = k_g, row['kart_adi']
            if e_kart: st.info(f"💡 **Asistan:** Şu an en mantıklı araç **{e_kart}**. (Kesime {max_g} gün var, limit müsait).")
                
        with st.container(border=True):
            h_kat = st.selectbox("Harcama Kategorisi", kategoriler)
            h_mik = st.number_input("Tutar (TL)", min_value=0.0, step=100.0)
            h_iht = st.radio("Tip", ["Evet, Şart (İhtiyaç)", "Hayır, Keyfi (İstek)"], horizontal=True)
            h_tip = st.radio("Ödeme Şekli", ["Nakit / Banka Kartı", "Kredi Kartı"], horizontal=True)
            
            t_ay, k_id = 1, None
            if h_tip == "Kredi Kartı":
                if not df_kartlar.empty:
                    k_sec = dict(zip(df_kartlar['id'], df_kartlar['kart_adi']))
                    v_idx = list(k_sec.values()).index(e_kart) if e_kart and e_kart in k_sec.values() else 0
                    k_id = st.selectbox("Kart", options=list(k_sec.keys()), format_func=lambda x: k_sec[x], index=v_idx)
                    t_ay = st.number_input("Taksit", min_value=1, step=1, max_value=36)
                else: st.warning("Sisteme kayıtlı kart yok!")
                    
            if st.button("Harcamayı Onayla", use_container_width=True, type="primary"):
                if h_mik > 0:
                    i_drm = "İhtiyaç" if "Evet" in h_iht else "İstek"
                    zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
                    if h_tip == "Kredi Kartı" and k_id:
                        if t_ay > 1: ws_taksitler.append_row([get_new_id(df_taksitler), k_id, f"{h_kat} ({i_drm})", h_mik/t_ay, t_ay])
                        ridx = get_row_idx(df_kartlar, 'id', k_id)
                        if ridx:
                            m_borc = safe_float(df_kartlar.loc[df_kartlar['id'].astype(str)==str(k_id), 'guncel_borc'].iloc[0])
                            # Hata vermemesi için explicitly float'a çeviriyoruz
                            ws_kartlar.update_cell(ridx, 4, float(m_borc + h_mik))
                    ws_islemler.append_row([get_new_id(df_islemler), "KK Gider" if h_tip=="Kredi Kartı" else "Gider", h_kat, h_mik, zaman, i_drm, h_kat])
                    st.success("İşlendi! Serini kontrol et 🔥"); time.sleep(1); clear_cache_and_rerun()
    else:
        with st.container(border=True):
            st.write("💳 **Kart Ekstresini Öde (Nakit Kasadan Düşer)**")
            if df_kartlar.empty:
                st.info("Sisteme kayıtlı kredi kartı bulunmuyor.")
            else:
                kart_isimleri = df_kartlar['kart_adi'].tolist()
                secilen_kart_adi = st.selectbox("Ödenecek Kart", kart_isimleri)
                islem_tutari = st.number_input("Ödenen Tutar (TL)", min_value=0.0, step=100.0)
                
                if st.button("Ödemeyi Kasadan Düş", use_container_width=True, type="primary"):
                    if islem_tutari > 0:
                        row_idx = get_row_idx(df_kartlar, 'kart_adi', secilen_kart_adi)
                        if row_idx:
                            mevcut_borc = safe_float(df_kartlar.loc[df_kartlar['kart_adi'].astype(str) == str(secilen_kart_adi), 'guncel_borc'].iloc[0])
                            yeni_borc = max(0, mevcut_borc - islem_tutari)
                            ws_kartlar.update_cell(row_idx, 4, float(yeni_borc))
                            
                            zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
                            ws_islemler.append_row([get_new_id(df_islemler), "Gider", f"{secilen_kart_adi} Ekstre Ödemesi", islem_tutari, zaman, "İhtiyaç", "Diğer"])
                            
                            st.success(f"✅ {secilen_kart_adi} kartına {islem_tutari:,.2f} TL ödeme yapıldı ve nakit bakiyenden düşüldü!")
                            time.sleep(1)
                            clear_cache_and_rerun()
                    else:
                        st.error("Lütfen sıfırdan büyük bir tutar girin.")

    st.divider()
    st.subheader("📌 Görev / Fatura Ekle")
    with st.form("f_form", clear_on_submit=True):
        f_isim = st.text_input("Adı (Elektrik, Su vs.)")
        if st.form_submit_button("Ekle") and f_isim:
            ws_faturalar.append_row([get_new_id(df_faturalar), f_isim, "False"]); st.rerun()
    if not df_faturalar.empty:
        with st.expander("🗑️ Listeden Sil"):
            for idx, r in df_faturalar.iterrows():
                c1, c2 = st.columns([4, 1])
                c1.write(r['isim'])
                if c2.button("Sil", key=f"df_{r['id']}_{idx}"):
                    ridx = get_row_idx(df_faturalar, 'id', r['id'])
                    if ridx: ws_faturalar.delete_rows(ridx); clear_cache_and_rerun()

# --- SEKME 5: TAKVİM ---
with sekmeler[4]:
    st.subheader("📅 Ödeme Takvimi")
    df_tak = df_taksitler[df_taksitler['kalan_ay'] > 0] if not df_taksitler.empty else pd.DataFrame()
    if df_tak.empty or df_kartlar.empty: st.info("Taksitli borcun yok.")
    else:
        tv = pd.merge(df_tak, df_kartlar, left_on='kart_id', right_on='id')
        bg = datetime.now()
        satirlar = []
        for _, r in tv.iterrows():
            for a in range(1, int(r['kalan_ay']) + 1):
                ha = bg.month + a - 1
                ey, ga, gy = ha // 12, (ha % 12) + 1, bg.year + (ha // 12)
                satirlar.append({"S": int(f"{gy}{ga:02d}{int(r['hesap_kesim']):02d}"), "Tarih": f"{int(r['hesap_kesim']):02d}.{ga:02d}.{gy}", "Kart": r['kart_adi'], "Açıklama": f"{r['aciklama']} ({a}. Taksit)", "Tutar (TL)": safe_float(r['aylik_tutar'])})
        if satirlar: st.dataframe(pd.DataFrame(satirlar).sort_values("S").drop(columns=["S"]), hide_index=True)
        st.divider()
        st.error("🗑️ İptal Et")
        for idx, r in tv.iterrows():
            c1, c2, c3, c4 = st.columns([4, 3, 3, 1])
            c1.write(r['aciklama']); c2.write(r['kart_adi']); c3.write(f"Kalan: {int(r['kalan_ay'])} Ay")
            if c4.button("🗑️", key=f"dt_{r['id_x']}_{idx}"):
                ridx = get_row_idx(df_kartlar, 'id', r['kart_id'])
                if ridx: ws_kartlar.update_cell(ridx, 4, float(max(0, safe_float(r['guncel_borc']) - (safe_float(r['aylik_tutar']) * int(r['kalan_ay'])))))
                tidx = get_row_idx(df_taksitler, 'id', r['id_x'])
                if tidx: ws_taksitler.delete_rows(tidx); clear_cache_and_rerun()

# --- SEKME 6: VARLIKLAR ---
with sekmeler[5]:
    st.subheader("💰 Varlıklar")
    y1, y2 = st.columns(2)
    with y1:
        with st.form("y_form", clear_on_submit=True):
            sahip = st.selectbox("Kasa", ["Kendim", "Eşim", "Çocuğum", "Ortak Kasa", "Genel Kasa"])
            var = st.selectbox("Varlık", ["USD", "EUR", "GA", "Çeyrek Altın", "Yarım Altın", "Tam Altın", "Ata Altın", "BTC", "ETH"])
            tip = st.radio("İşlem", ["Ekle (+)", "Çıkar (-)"], horizontal=True)
            mik = st.number_input("Miktar", min_value=0.0, format="%.6f")
            if st.form_submit_button("Kaydet") and mik > 0:
                t_isim = f"{sahip} - {var}"
                mev = safe_float(df_yastik.loc[df_yastik['varlik_tipi']==t_isim, 'miktar'].iloc[0]) if not df_yastik[df_yastik['varlik_tipi']==t_isim].empty else 0.0
                yeni = mev + mik if "Ekle" in tip else max(0.0, mev - mik)
                ridx = get_row_idx(df_yastik, 'varlik_tipi', t_isim)
                if ridx: ws_yastik.update_cell(ridx, 2, float(yeni))
                else: ws_yastik.append_row([t_isim, float(yeni)])
                st.rerun()
        if st.button("🗑️ Sıfırlananları Sil"):
            for _, r in df_yastik[df_yastik['miktar'] == 0.0].iterrows():
                ridx = get_row_idx(df_yastik, 'varlik_tipi', r['varlik_tipi'])
                if ridx: ws_yastik.delete_rows(ridx)
            st.rerun()
    with y2:
        st.write("### 🗂️ Kasa Detayı")
        if not df_yastik.empty:
            for _, r in df_yastik[df_yastik['miktar'] > 0].iterrows(): st.markdown(f"🔹 **{str(r['varlik_tipi']).replace(' - ', ' ➡ ')}** : {safe_float(r['miktar']):,.2f}")

# --- SEKME 7: KARTLAR ---
with sekmeler[6]:
    st.subheader("💳 Kart Yönetimi")
    k1, k2 = st.columns(2)
    with k1:
        with st.form("k_form", clear_on_submit=True):
            k_ad = st.text_input("Kart Adı")
            k_lim = st.number_input("Limit (TL)", min_value=0.0, step=1000.0)
            k_kes = st.number_input("Kesim Günü", min_value=1, max_value=31, value=15)
            if st.form_submit_button("Ekle") and k_ad:
                ws_kartlar.append_row([get_new_id(df_kartlar), k_ad, k_lim, 0.0, k_kes]); st.rerun()
    with k2:
        if not df_kartlar.empty:
            for idx, r in df_kartlar.sort_values("id", ascending=False).iterrows():
                c1, c2, c3, c4, c5 = st.columns([3, 2, 2, 2, 1])
                c1.write(f"**{r['kart_adi']}**"); c2.write(f"Lim: {safe_float(r['kart_limit']):,.0f}"); c3.write(f"Brç: {safe_float(r['guncel_borc']):,.0f}")
                c4.write(f"Kesim: {r['hesap_kesim']}")
                if c5.button("🗑️", key=f"dk_{r['id']}_{idx}"):
                    ridx = get_row_idx(df_kartlar, 'id', r['id'])
                    if ridx: ws_kartlar.delete_rows(ridx)
                    if not df_taksitler.empty:
                        for _, tr in df_taksitler[df_taksitler['kart_id'].astype(str)==str(r['id'])].iterrows():
                            tidx = get_row_idx(df_taksitler, 'id', tr['id'])
                            if tidx: ws_taksitler.delete_rows(tidx)
                    st.rerun()

# --- SEKME 8: GEÇMİŞ ---
with sekmeler[7]:
    st.subheader("📝 İşlem Geçmişi (Son 50)")
    if not df_islemler.empty:
        for idx, r in df_islemler.tail(50).iloc[::-1].iterrows():
            c1, c2, c3, c4, c5, c6 = st.columns([1.5, 1, 1.5, 3, 1.5, 1])
            c1.write(str(r['tarih'])[:10]); c2.markdown("🟢" if r['tip']=="Gelir" else "🔴"); c3.write(r['kategori']); c4.write(r['isim']); c5.write(f"{safe_float(r['miktar']):,.2f} TL")
            if c6.button("🗑️", key=f"di_{r['id']}_{idx}"):
                ridx = get_row_idx(df_islemler, 'id', r['id'])
                if ridx: ws_islemler.delete_rows(ridx); st.rerun()

# --- SEKME 9: TÜCCAR ---
with sekmeler[8]:
    st.subheader("🐺 Al-Sat Envanteri")
    with st.form("t_form", clear_on_submit=True):
        urun = st.text_input("Ürün Adı")
        alis = st.number_input("Alış Fiyatı", min_value=0.0, step=100.0)
        if st.form_submit_button("Ekle") and urun:
            ws_ticaret.append_row([get_new_id(df_ticaret), urun, alis, 0.0])
            ws_islemler.append_row([get_new_id(df_islemler), "Gider", f"Mal Alışı: {urun}", alis, datetime.now().strftime("%Y-%m-%d %H:%M"), "İhtiyaç", "Donanım (Al-Sat)"])
            st.rerun()
    if not df_ticaret.empty:
        t1, t2 = st.columns(2)
        with t1:
            st.write("### 📦 Envanter")
            for idx, r in df_ticaret[df_ticaret['tahmini_satis']==0].iterrows():
                with st.expander(f"🛒 {r['urun_adi']} (Mal: {safe_float(r['alis_fiyati']):,.0f})"):
                    sat = st.number_input("Satış Fiyatı", key=f"ts_{r['id']}_{idx}")
                    c1, c2 = st.columns(2)
                    if c1.button("Sat", key=f"tsb_{r['id']}_{idx}") and sat > 0:
                        ridx = get_row_idx(df_ticaret, 'id', r['id'])
                        if ridx:
                            ws_ticaret.update_cell(ridx, 4, float(sat))
                            ws_islemler.append_row([get_new_id(df_islemler), "Gelir", f"Mal Satışı: {r['urun_adi']}", sat, datetime.now().strftime("%Y-%m-%d %H:%M"), "Gelir", "Donanım (Al-Sat)"])
                            st.rerun()
                    if c2.button("Sil", key=f"td_{r['id']}_{idx}"):
                        ridx = get_row_idx(df_ticaret, 'id', r['id'])
                        if ridx: ws_ticaret.delete_rows(ridx); st.rerun()
        with t2:
            st.write("### 💸 Satılanlar")
            for _, r in df_ticaret[df_ticaret['tahmini_satis']>0].iterrows():
                kar = safe_float(r['tahmini_satis']) - safe_float(r['alis_fiyati'])
                st.write(f"**{r['urun_adi']}** | Kâr: {kar:,.0f} TL")

# --- SEKME 10: HEDEFLER ---
with sekmeler[9]:
    st.subheader("🎯 Hedefler")
    if not df_hedefler.empty:
        for idx, r in df_hedefler.sort_values("id", ascending=False).iterrows():
            t, b = safe_float(r['hedef_tutar']), safe_float(r['biriken'])
            c1, c2, c3 = st.columns([5, 4, 1])
            c1.write(f"**{r['hedef_adi']}** ({b:,.0f}/{t:,.0f})")
            c2.progress(min(b/t if t>0 else 0, 1.0))
            if c3.button("🗑️", key=f"dh_{r['id']}_{idx}"):
                ridx = get_row_idx(df_hedefler, 'id', r['id'])
                if ridx: ws_hedefler.delete_rows(ridx); st.rerun()
    st.divider()
    with st.form("h_form"):
        h_ad = st.text_input("Hedef")
        h_tut = st.number_input("Tutar", min_value=0.0, step=1000.0)
        h_bir = st.number_input("Mevcut", min_value=0.0, step=100.0)
        if st.form_submit_button("Oluştur") and h_ad:
            ws_hedefler.append_row([get_new_id(df_hedefler), h_ad, h_tut, h_bir]); st.rerun()
    if not df_hedefler.empty:
        with st.form("hp_form"):
            h_sec = st.selectbox("Hedef Seç", df_hedefler['hedef_adi'])
            ekle = st.number_input("Eklenecek", min_value=0.0, step=100.0)
            if st.form_submit_button("Para At") and ekle > 0:
                ridx = get_row_idx(df_hedefler, 'hedef_adi', h_sec)
                if ridx:
                    mev = safe_float(df_hedefler.loc[df_hedefler['hedef_adi']==h_sec, 'biriken'].iloc[0])
                    ws_hedefler.update_cell(ridx, 4, float(mev + ekle))
                    ws_islemler.append_row([get_new_id(df_islemler), "Gider", f"Kumbara: {h_sec}", ekle, datetime.now().strftime("%Y-%m-%d %H:%M"), "İhtiyaç", "Diğer"])
                    st.rerun()

# --- SEKME 11: ABONELİKLER ---
with sekmeler[10]:
    st.subheader("🧛‍♂️ Abonelikler")
    with st.form("a_form"):
        a_isim = st.text_input("Adı")
        a_tut = st.number_input("Aylık Tutar", min_value=0.0)
        a_gun = st.number_input("Çekim Günü", min_value=1, max_value=31)
        if st.form_submit_button("Ekle") and a_isim:
            ws_abonelikler.append_row([get_new_id(df_abonelikler), a_isim, a_tut, a_gun]); st.rerun()
    if not df_abonelikler.empty:
        st.error(f"Aylık Toplam: **{df_abonelikler['tutar'].apply(safe_float).sum():,.2f} TL**")
        for idx, r in df_abonelikler.iterrows():
            c1, c2, c3, c4 = st.columns([4, 2, 2, 1])
            c1.write(r['isim']); c2.write(f"{safe_float(r['tutar']):,.2f} TL"); c3.write(f"{r['odeme_gunu']}. Gün")
            if c4.button("🗑️", key=f"da_{r['id']}_{idx}"):
                ridx = get_row_idx(df_abonelikler, 'id', r['id'])
                if ridx: ws_abonelikler.delete_rows(ridx); st.rerun()

# --- SEKME 12: BÜTÇE LİMİTLERİ ---
with sekmeler[11]:
    st.subheader("🚧 Bütçe")
    with st.form("b_form"):
        b_kat = st.selectbox("Kategori", kategoriler)
        b_lim = st.number_input("Limit", min_value=0.0, step=500.0)
        if st.form_submit_button("Güncelle") and b_lim >= 0:
            ridx = get_row_idx(df_butceler, 'kategori', b_kat)
            if ridx: ws_butceler.update_cell(ridx, 3, float(b_lim))
            else: ws_butceler.append_row([get_new_id(df_butceler), b_kat, b_lim])
            st.rerun()
    if not df_butceler.empty:
        for _, r in df_butceler[df_butceler['limit_tutar'].apply(safe_float)>0].iterrows():
            kat = r['kategori']
            harc = df_bu_ay_giderler[df_bu_ay_giderler['kategori']==kat]['miktar'].apply(safe_float).sum() if not df_bu_ay_giderler.empty else 0.0
            lim = safe_float(r['limit_tutar'])
            st.write(f"**{kat}**: {harc:,.0f} / {lim:,.0f}")
            st.progress(min(harc/lim if lim>0 else 0, 1.0))

# --- SEKME 13: ENFLASYON ---
with sekmeler[12]:
    st.subheader("👻 Enflasyon Simülatörü")
    ana = st.number_input("Tutar (TL)", value=15000, step=1000)
    enf = st.slider("Enflasyon (%)", 0, 150, 65)
    yil = st.slider("Yıl", 1, 10, 1)
    st.error(f"Sonuç: **{ana * ((1 + (enf / 100)) ** yil):,.0f} TL**")

# --- SEKME 14: DANIŞMAN ---
with sekmeler[13]:
    st.subheader("🤖 Harcama Tahmini (Danışman)")
    gecen_gun = max(1, (datetime.now().date() - dongu_baslangici).days)
    sabit_kelimeler = ["kira", "fatura", "aidat", "elektrik", "su", "doğalgaz", "internet", "telefon", "kredi", "taksit", "ödeme", "kk", "büşra", "batu", "harçlık", "berber", "eczane", "sağlık", "depo", "ek hesap"]
    
    if df_bu_ay_giderler.empty:
        st.info("Bu döngüde henüz harcama yok.")
    else:
        df_bu_ay_giderler['miktar'] = df_bu_ay_giderler['miktar'].apply(safe_float)
        grup = df_bu_ay_giderler.groupby('kategori')['miktar'].sum().to_dict()
        tah_data = []
        for kat, mik in grup.items():
            if kat in ["Maaş/Gelir", "Diğer"]: continue
            is_sabit = any(k in kat.lower() for k in sabit_kelimeler)
            ay_sonu_tah = mik if is_sabit else (mik / gecen_gun) * 30
            tah_data.append({"Kategori": kat, "Şu Anki Harcama": mik, "Ay Sonu Tahmini": ay_sonu_tah})
            if not is_sabit and ay_sonu_tah > mik * 1.5: 
                st.warning(f"🚨 **{kat}** kategorisinde frene bas! Gidişat: **{ay_sonu_tah:,.0f} TL**")
        
        if tah_data:
            st.plotly_chart(px.bar(pd.DataFrame(tah_data), x="Kategori", y=["Şu Anki Harcama", "Ay Sonu Tahmini"], barmode="group"), use_container_width=True)

# --- SEKME 15: BORÇLAR ---
with sekmeler[14]:
    st.subheader("🏦 Krediler")
    with st.expander("➕ Yeni Kredi Ekle"):
        with st.form("kr_ekle"):
            k_ad = st.text_input("Kredi Adı")
            k_top = st.number_input("Toplam Borç", min_value=0.0)
            k_ode = st.number_input("Ödenen", min_value=0.0)
            k_tak = st.number_input("Aylık Taksit", min_value=0.0)
            k_ay = st.number_input("Kalan Ay", min_value=1)
            if st.form_submit_button("Kaydet") and k_ad:
                ws_krediler.append_row([get_new_id(df_krediler), k_ad, k_top, k_ode, k_tak, k_ay, datetime.now().strftime("%Y-%m-%d")]); st.rerun()
    if not df_krediler.empty:
        for idx, r in df_krediler.iterrows():
            c1, c2, c3, c4 = st.columns([3, 2, 2, 2])
            c1.write(f"**{r['kredi_adi']}**"); c2.write(f"Kalan: {safe_float(r['toplam_borc']) - safe_float(r['odenen']):,.0f}")
            c3.write(f"Taksit: {safe_float(r['aylik_taksit']):,.0f}"); c4.write(f"{int(r['kalan_ay'])} Ay")
            k1, k2, k3 = st.columns([2, 2, 1])
            if k1.button("Normal Taksit Öde", key=f"knt_{r['id']}_{idx}"):
                ridx = get_row_idx(df_krediler, 'id', r['id'])
                if ridx:
                    ws_krediler.update_cell(ridx, 4, float(safe_float(r['odenen']) + safe_float(r['aylik_taksit'])))
                    ws_krediler.update_cell(ridx, 6, max(0, int(r['kalan_ay']) - 1))
                    ws_islemler.append_row([get_new_id(df_islemler), "Gider", f"{r['kredi_adi']} Taksit", safe_float(r['aylik_taksit']), datetime.now().strftime("%Y-%m-%d %H:%M"), "İhtiyaç", "Diğer"])
                    st.rerun()
            if k3.button("🗑️ Sil", key=f"ksil_{r['id']}_{idx}"):
                ridx = get_row_idx(df_krediler, 'id', r['id'])
                if ridx: ws_krediler.delete_rows(ridx); st.rerun()
            st.markdown("---")

    st.subheader("💳 Kart Borcu Yönetimi")
    if not df_kartlar.empty:
        with st.form("kb_form"):
            ks = st.selectbox("Kart", df_kartlar['kart_adi'])
            tip = st.radio("İşlem", ["Borç Ekle", "Ödeme Yap", "Yanlış Ekledim (Geri Al)"], horizontal=True)
            tut = st.number_input("Tutar", min_value=0.0)
            if st.form_submit_button("Güncelle") and tut > 0:
                ridx = get_row_idx(df_kartlar, 'kart_adi', ks)
                if ridx:
                    mev = safe_float(df_kartlar.loc[df_kartlar['kart_adi']==ks, 'guncel_borc'].iloc[0])
                    yeni = mev + tut if "Ekle" in tip else max(0, mev - tut)
                    ws_kartlar.update_cell(ridx, 4, float(yeni))
                    if "Ödeme" in tip: ws_islemler.append_row([get_new_id(df_islemler), "Gider", f"{ks} Ödeme", tut, datetime.now().strftime("%Y-%m-%d %H:%M"), "İhtiyaç", "Diğer"])
                    st.rerun()
                    
    st.subheader("🤝 Elden Borçlar")
    with st.expander("➕ Yeni Ekle"):
        with st.form("eb_form"):
            b_ad = st.text_input("Kişi")
            b_top = st.number_input("Toplam Borç", min_value=0.0)
            if st.form_submit_button("Kaydet") and b_ad:
                ws_borclar.append_row([get_new_id(df_borclar), b_ad, b_top, 0.0, datetime.now().strftime("%Y-%m-%d")]); st.rerun()
    if not df_borclar.empty:
        for idx, r in df_borclar.iterrows():
            c1, c2, c3, c4 = st.columns([3, 2, 2, 1])
            c1.write(r['borc_adi']); c2.write(f"Kalan: {safe_float(r['toplam_miktar']) - safe_float(r['odenen']):,.0f}")
            ode = c3.number_input("Öde", key=f"ebo_{r['id']}_{idx}")
            if c4.button("Öde", key=f"ebob_{r['id']}_{idx}") and ode > 0:
                ridx = get_row_idx(df_borclar, 'id', r['id'])
                if ridx: ws_borclar.update_cell(ridx, 4, float(safe_float(r['odenen']) + ode)); st.rerun()
            if c4.button("🗑️", key=f"ebsil_{r['id']}_{idx}"):
                ridx = get_row_idx(df_borclar, 'id', r['id'])
                if ridx: ws_borclar.delete_rows(ridx); st.rerun()
