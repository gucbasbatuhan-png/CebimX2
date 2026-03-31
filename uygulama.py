import streamlit as st
import pandas as pd
from datetime import datetime
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

# --- 2. GOOGLE SHEETS BAĞLANTI & AKILLI RAM MOTORU ---
class DirtyTrackerWS:
    def __init__(self, ws, sheet_name):
        self.ws = ws
        self.sheet_name = sheet_name
        
    def _mark_dirty(self):
        if 'dirty_sheets' not in st.session_state:
            st.session_state.dirty_sheets = set()
        st.session_state.dirty_sheets.add(self.sheet_name)
        
    def append_row(self, *args, **kwargs):
        self._mark_dirty()
        return self.ws.append_row(*args, **kwargs)
        
    def update_cell(self, *args, **kwargs):
        self._mark_dirty()
        return self.ws.update_cell(*args, **kwargs)
        
    def delete_rows(self, *args, **kwargs):
        self._mark_dirty()
        return self.ws.delete_rows(*args, **kwargs)
        
    def insert_row(self, *args, **kwargs):
        self._mark_dirty()
        return self.ws.insert_row(*args, **kwargs)

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
        try:
            return ws.get_all_records()
        except:
            return []
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
    
    if 'dirty_sheets' not in st.session_state:
        st.session_state.dirty_sheets = set()
    if 'refresh_tokens' not in st.session_state:
        st.session_state.refresh_tokens = {}
        
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
        
    if df.empty:
        df = pd.DataFrame(columns=cols.get(sheet_name, []))
        
    return df, DirtyTrackerWS(ws, sheet_name)

def get_new_id(df):
    return int(df['id'].max() + 1) if not df.empty and 'id' in df.columns else 1

# YENİ EKLENEN KURŞUN GEÇİRMEZ SATIR BULMA MOTORU
def get_row_idx(df, col_name, value):
    try:
        # Tipi ne olursa olsun (yazı/sayı) string'e çevirip garantili eşleştirme yapar
        return int(df.index[df[col_name].astype(str) == str(value)].tolist()[0] + 2)
    except:
        return None

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

# --- 3. GİRİŞ (LOGIN) SİSTEMİ ---
if 'giris_yapildi' not in st.session_state:
    st.session_state.giris_yapildi = False
    st.session_state.kullanici_tipi = None

if not st.session_state.giris_yapildi:
    st.title("🔐 CebimX Giriş Ekranı")
    kol1, kol2, kol3 = st.columns([1, 2, 1])
    with kol2:
        with st.container(border=True):
            kadi = st.text_input("Kullanıcı Adı")
            sifre = st.text_input("Şifre", type="password")
            giris_btn = st.button("Giriş Yap", use_container_width=True)
            if giris_btn:
                if kadi == "admin" and sifre == st.secrets["kullanici"]["sifre"]:
                    st.success("✅ Başarıyla giriş yaptınız!")
                    time.sleep(1) 
                    st.session_state.giris_yapildi = True
                    st.session_state.kullanici_tipi = "gercek"
                    st.rerun()
                else:
                    st.error("❌ Lütfen kullanıcı adı ve şifrenizi kontrol edin.")
    st.stop()

# --- 4. ÇIKIŞ YAPMA BUTONU (YAN MENÜ) ---
with st.sidebar:
    st.success("👤 Hesap: **Ana Yönetici**")
    if st.button("🚪 Çıkış Yap", use_container_width=True):
        st.session_state.giris_yapildi = False
        st.session_state.kullanici_tipi = None
        st.rerun()

st.title("💸 CebimX:Kişisel Finans Yönetimi")

# --- 5. VERİLERİ GOOGLE SHEETS'TEN ÇEK VE TEMİZLE ---
try:
    df_islemler, ws_islemler = get_df("islemler")
    df_ticaret, ws_ticaret = get_df("ticaret")
    df_hedefler, ws_hedefler = get_df("hedefler")
    df_kartlar, ws_kartlar = get_df("kredi_kartlari")
    df_taksitler, ws_taksitler = get_df("taksitler")
    df_yastik, ws_yastik = get_df("yastik_alti")
    df_borclar, ws_borclar = get_df("manuel_borclar")
    df_abonelikler, ws_abonelikler = get_df("abonelikler")
    df_butceler, ws_butceler = get_df("butceler")
    df_faturalar, ws_faturalar = get_df("faturalar")
    df_notlar, ws_notlar = get_df("notlar")
    
    df_islemler = clean_numeric(df_islemler, ['miktar'])
    df_ticaret = clean_numeric(df_ticaret, ['alis_fiyati', 'tahmini_satis'])
    df_hedefler = clean_numeric(df_hedefler, ['hedef_tutar', 'biriken'])
    df_kartlar = clean_numeric(df_kartlar, ['kart_limit', 'guncel_borc'])
    df_taksitler = clean_numeric(df_taksitler, ['aylik_tutar'])
    df_yastik = clean_numeric(df_yastik, ['miktar'])
    df_borclar = clean_numeric(df_borclar, ['toplam_miktar', 'odenen'])
    df_abonelikler = clean_numeric(df_abonelikler, ['tutar'])
    df_butceler = clean_numeric(df_butceler, ['limit_tutar'])
    if not df_notlar.empty: df_notlar = df_notlar.fillna("")
    
except Exception as e:
    st.error(f"⚠️ Google Sheets'e bağlanırken hata oluştu. Hata: {e}")
    st.stop()

if df_yastik.empty:
    ws_yastik.append_row(['Genel Kasa - USD', 0])
    ws_yastik.append_row(['Genel Kasa - EUR', 0])
    ws_yastik.append_row(['Genel Kasa - GA', 0])
    ws_yastik.append_row(['Genel Kasa - BTC', 0])
    ws_yastik.append_row(['Genel Kasa - ETH', 0])
    clear_cache_and_rerun()

kategoriler = ["Market", "Kira", "Fatura", "Eğlence", "Oyun & Yazılım", "Donanım (Al-Sat)", "Diğer", "Proje & Geliştirici", "Eğitim", "Kişisel Gelişim", "Dışarıdan Yeme", "Dışarıdan İçme", "Ulaşım", "Seyahat", "Giyim", 
              "Kişisel Bakım", "Sağlık", "Eczane", "Berber", "Büşra Kuaför", "Elektrik", "Su", "Doğalgaz", "İnternet", "Aidat", "Depo Kira", "Büşra Telefon", "Batu Telefon"]

if df_butceler.empty:
    for i, kat in enumerate(kategoriler):
        ws_butceler.append_row([i+1, kat, 0])
    clear_cache_and_rerun()

# --- 6. CANLI PİYASALAR VE KRİPTO RADARI ---
st.subheader("🌍 Canlı Piyasalar ve Kripto Radarı")

if 'usd_try' not in st.session_state:
    st.session_state.usd_try = 0.0
    st.session_state.eur_try = 0.0
    st.session_state.gr_altin = 0.0
    st.session_state.btc_try = 0.0
    st.session_state.eth_try = 0.0

kol_kur1, kol_kur2, kol_kur3, kol_kur4, kol_kur5, kol_kur6 = st.columns(6)
with kol_kur6:
    guncelle_basildi = st.button("🔄 Kurları Güncelle")

if guncelle_basildi:
    try:
        usd = yf.Ticker("TRY=X").history(period="5d")['Close'].iloc[-1]
        eur = yf.Ticker("EURTRY=X").history(period="5d")['Close'].iloc[-1]
        altin_ons_usd = yf.Ticker("GC=F").history(period="5d")['Close'].iloc[-1] 
        btc_usd = yf.Ticker("BTC-USD").history(period="5d")['Close'].iloc[-1]
        eth_usd = yf.Ticker("ETH-USD").history(period="5d")['Close'].iloc[-1]
        
        st.session_state.usd_try = usd
        st.session_state.eur_try = eur
        st.session_state.gr_altin = (altin_ons_usd / 31.1034768) * usd
        st.session_state.btc_try = btc_usd * usd
        st.session_state.eth_try = eth_usd * usd
        st.success("Tüm kurlar çekildi!")
    except:
        st.error("Veriler güncellenirken hata oluştu. İnternetinizi kontrol edin.")

kol_kur1.info(f"💵 USD: **{st.session_state.usd_try:,.2f}**")
kol_kur2.info(f"💶 EUR: **{st.session_state.eur_try:,.2f}**")
kol_kur3.warning(f"🥇 Altın: **{st.session_state.gr_altin:,.2f}**")
kol_kur4.success(f"₿ BTC: **{st.session_state.btc_try:,.0f} TL**")
kol_kur5.success(f"⟠ ETH: **{st.session_state.eth_try:,.0f} TL**")
st.divider()

# --- 7. ORTAK VERİLER VE GERÇEK NET VARLIK ---
mevcut_ay_str = f"{datetime.now().year}-{datetime.now().month:02d}"

if not df_islemler.empty:
    toplam_gelir = df_islemler[df_islemler['tip'] == 'Gelir']['miktar'].sum()
    toplam_nakit_gider = df_islemler[df_islemler['tip'] == 'Gider']['miktar'].sum()
    toplam_tum_giderler = df_islemler[df_islemler['tip'].isin(['Gider', 'KK Gider'])]['miktar'].sum()
    df_bu_ay_giderler = df_islemler[(df_islemler['tip'].isin(['Gider', 'KK Gider'])) & (df_islemler['tarih'].astype(str).str.startswith(mevcut_ay_str))]
    df_bu_ay_gelirler = df_islemler[(df_islemler['tip'] == 'Gelir') & (df_islemler['tarih'].astype(str).str.startswith(mevcut_ay_str))]
    bu_ay_toplam_gelir = df_bu_ay_gelirler['miktar'].sum() if not df_bu_ay_gelirler.empty else 0.0
else:
    toplam_gelir = 0.0
    toplam_nakit_gider = 0.0
    toplam_tum_giderler = 0.0
    bu_ay_toplam_gelir = 0.0
    df_bu_ay_giderler = pd.DataFrame()
    
net_nakit = toplam_gelir - toplam_nakit_gider

if not df_kartlar.empty:
    toplam_limit = df_kartlar['kart_limit'].sum()
    toplam_kk_borc = df_kartlar['guncel_borc'].sum()
else:
    toplam_limit = 0.0
    toplam_kk_borc = 0.0

if not df_borclar.empty:
    toplam_manuel_borc = pd.to_numeric(df_borclar['toplam_miktar']).sum() - pd.to_numeric(df_borclar['odenen']).sum()
else:
    toplam_manuel_borc = 0.0

# SARRAF VE AİLE KASASI MOTORU
toplam_yastik_tl = 0.0
varlik_kategorileri = {} 
varlik_tipleri = {'USD': 0, 'EUR': 0, 'GA': 0, 'Çeyrek Altın': 0, 'Yarım Altın': 0, 'Tam Altın': 0, 'Ata Altın': 0, 'BTC': 0, 'ETH': 0} 

if not df_yastik.empty:
    for _, row in df_yastik.iterrows():
        v_tip = str(row['varlik_tipi'])
        miktar = safe_float(row['miktar'])
        if " - " in v_tip: kat, birim = v_tip.split(" - ", 1)
        else: kat, birim = "Genel Kasa", v_tip
            
        tl_karsiligi = 0.0
        if birim == 'USD': tl_karsiligi = miktar * st.session_state.usd_try
        elif birim == 'EUR': tl_karsiligi = miktar * st.session_state.eur_try
        elif birim == 'GA': tl_karsiligi = miktar * st.session_state.gr_altin
        elif birim == 'Çeyrek Altın': tl_karsiligi = miktar * (st.session_state.gr_altin * 1.605)
        elif birim == 'Yarım Altın': tl_karsiligi = miktar * (st.session_state.gr_altin * 3.21)
        elif birim == 'Tam Altın': tl_karsiligi = miktar * (st.session_state.gr_altin * 6.42)
        elif birim == 'Ata Altın': tl_karsiligi = miktar * (st.session_state.gr_altin * 6.61)
        elif birim == 'BTC': tl_karsiligi = miktar * st.session_state.btc_try
        elif birim == 'ETH': tl_karsiligi = miktar * st.session_state.eth_try
        
        toplam_yastik_tl += tl_karsiligi
        varlik_kategorileri[kat] = varlik_kategorileri.get(kat, 0.0) + tl_karsiligi
        varlik_tipleri[birim] = varlik_tipleri.get(birim, 0.0) + miktar

gercek_net_varlik = net_nakit + toplam_yastik_tl - toplam_kk_borc - toplam_manuel_borc

# --- 8. SEKMELER (15 SEKME) ---
sekmeler = st.tabs([
    "📊 Kumanda", "🗒️ Notlar", "🟢 Gelir", "🛍️ Gider", "📅 Takvim", "💰 Varlık", "💳 Kart", 
    "📝 Geçmiş", "🐺 Tüccar", "🎯 Hedef", "🔁 Abonelik", "🚧 Bütçe", "👻 Enflasyon", "🤖 Danışman", "💸 Borç"
])

# --- SEKME 1: ANA KUMANDA ---
with sekmeler[0]:
    c_net, c_goz = st.columns([5, 1])
    with c_net:
        st.error(f"💎 GERÇEK NET VARLIĞIN (NET WORTH): **{gercek_net_varlik:,.2f} TL**")
    with c_goz:
        borclari_goster = st.toggle("👁️ Borçları Göster", value=False)

    kol1, kol2, kol3, kol4 = st.columns(4)
    kol1.metric("Net Nakit (TL)", f"{net_nakit:,.2f} TL")
    kol2.metric("Toplam Yastık Altı", f"{toplam_yastik_tl:,.2f} TL")
    
    if borclari_goster:
        kol3.metric("Toplam Kart Borcu", f"{toplam_kk_borc:,.2f} TL")
        kol4.metric("Elden / Diğer Borçlar", f"{toplam_manuel_borc:,.2f} TL")
    else:
        kol3.metric("Toplam Kart Borcu", "👀 Gizli")
        kol4.metric("Elden / Diğer Borçlar", "👀 Gizli")
    
    if varlik_kategorileri:
        st.divider()
        st.subheader("👨‍👩‍👦 Aile Varlık Dağılımı")
        v_kols = st.columns(len(varlik_kategorileri))
        for i, (kat, tutar) in enumerate(varlik_kategorileri.items()):
            v_kols[i].success(f"**{kat}** \n\n {tutar:,.2f} TL")

    st.divider()
    kol_ana1, kol_ana2 = st.columns([1, 1])
    
    with kol_ana1:
        st.subheader("🧾 Aylık Sabit Görev / Fatura Checklist'i")
        if not df_faturalar.empty:
            for idx, row in df_faturalar.iterrows():
                f_id = str(row['id'])
                eski_durum = str(row['durum']).lower() == 'true'
                
                isim_gosterim = f"~~{row['isim']}~~" if eski_durum else f"{row['isim']}"
                yeni_durum = st.checkbox(isim_gosterim, value=eski_durum, key=f"fat_chk_{idx}_{f_id}")
                
                if yeni_durum != eski_durum:
                    row_idx = get_row_idx(df_faturalar, 'id', f_id)
                    if row_idx:
                        ws_faturalar.update_cell(row_idx, 3, str(yeni_durum))
                        clear_cache_and_rerun()
                    else:
                        st.error("Satır bulunamadı!")
                    
            if st.button("🔄 Yeni Ay: Tüm Tikleri Temizle", use_container_width=True):
                for idx in range(len(df_faturalar)):
                    ws_faturalar.update_cell(idx + 2, 3, "False")
                clear_cache_and_rerun()
        else:
            st.info("📌 Checklist boş. 'Gider' sekmesinden ödenecek fatura veya görev ekleyebilirsin.")

    with kol_ana2:
        st.subheader("⏳ Günlük Yaşam Limiti")
        hedef_tarih = st.date_input("Bir Sonraki Maaş / Gelir Gününü Seç:", min_value=datetime.today())
        kalan_gun = (hedef_tarih - datetime.today().date()).days
        
        if kalan_gun > 0:
            if net_nakit > 0:
                gunluk_limit = net_nakit / kalan_gun
                st.success(f"Hedefe **{kalan_gun} gün** var. Artıda kalmak için günde en fazla **{gunluk_limit:,.2f} TL** harcayabilirsin.")
            else:
                st.error(f"Hedefe {kalan_gun} gün var ama nakit bakiyen ekside! Kemerleri sıkma vakti.")
        elif kalan_gun == 0:
            st.info("Gelir günü bugün! Cüzdanı yenileme vakti.")

    st.divider()
    
    st.subheader("⚖️ 50/30/20 Altın Bütçe Kuralı (Bu Ay)")
    if bu_ay_toplam_gelir > 0:
        iht_tutar = df_bu_ay_giderler[df_bu_ay_giderler['ihtiyac_mi'] == 'İhtiyaç']['miktar'].sum() if not df_bu_ay_giderler.empty else 0.0
        ist_tutar = df_bu_ay_giderler[df_bu_ay_giderler['ihtiyac_mi'] == 'İstek']['miktar'].sum() if not df_bu_ay_giderler.empty else 0.0
        kalan_tasarruf = bu_ay_toplam_gelir - iht_tutar - ist_tutar
        
        i_yuzde = (iht_tutar / bu_ay_toplam_gelir) * 100
        k_yuzde = (ist_tutar / bu_ay_toplam_gelir) * 100
        t_yuzde = (kalan_tasarruf / bu_ay_toplam_gelir) * 100 if kalan_tasarruf > 0 else 0
        
        c50, c30, c20 = st.columns(3)
        with c50:
            st.info(f"**🛠️ İhtiyaç (Hedef: Maks %50)**\n\nGerçekleşen: **%{i_yuzde:.1f}** ({iht_tutar:,.0f} TL)")
            st.progress(min(i_yuzde/100, 1.0))
        with c30:
            st.warning(f"**🎮 İstek (Hedef: Maks %30)**\n\nGerçekleşen: **%{k_yuzde:.1f}** ({ist_tutar:,.0f} TL)")
            st.progress(min(k_yuzde/100, 1.0))
        with c20:
            st.success(f"**💰 Kurtarılan / Tasarruf (Hedef: Min %20)**\n\nGerçekleşen: **%{t_yuzde:.1f}** ({kalan_tasarruf:,.0f} TL)")
            if kalan_tasarruf > 0: 
                st.progress(min(t_yuzde/100, 1.0))
    else:
        st.info("Bu aya ait gelir kaydı bulunamadığı için 50/30/20 kuralı hesaplanamıyor. Lütfen 'Gelir' sekmesinden bu ayın gelirini ekleyin.")

    st.divider()
    
    st.subheader("📥 Excel / CSV Dökümü Al")
    if not df_islemler.empty:
        csv_data = df_islemler.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📊 Tüm Muhasebe Geçmişini İndir (CSV)",
            data=csv_data,
            file_name=f"cebimx_dokum_{datetime.now().strftime('%Y%m%d')}.csv",
            mime="text/csv",
            use_container_width=True
        )

# --- SEKME 2: NOTLAR ---
with sekmeler[1]:
    st.subheader("📝 Kişisel Not Defteri")
    
    with st.form("yeni_not_formu", clear_on_submit=True):
        n_baslik = st.text_input("Not Başlığı")
        n_icerik = st.text_area("Not İçeriği")
        if st.form_submit_button("Notu Kaydet"):
            if n_baslik and n_icerik:
                new_id = get_new_id(df_notlar)
                zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
                ws_notlar.append_row([new_id, n_baslik, n_icerik, zaman])
                st.success("✅ Not kaydedildi! Sayfa yenileniyor...")
                time.sleep(1)
                clear_cache_and_rerun()
            else:
                st.error("Lütfen başlık ve içerik girin!")

    st.divider()
    col_refresh1, col_refresh2 = st.columns([4,1])
    col_refresh1.write("### 📌 Kayıtlı Notların")
    if col_refresh2.button("🔄 Listeyi Yenile", use_container_width=True):
        clear_cache_and_rerun()

    if df_notlar.empty:
        st.info("Henüz hiç not eklememişsin kanka.")
    else:
        notlar_goster = df_notlar.sort_values(by="id", ascending=False)
        for idx, row in notlar_goster.iterrows():
            with st.expander(f"📌 {row['baslik']} (Tarih: {row['tarih']})"):
                st.write(row['icerik'])
                if st.button("🗑️ Notu Sil", key=f"del_not_{row['id']}"):
                    row_idx = get_row_idx(df_notlar, 'id', row['id'])
                    if row_idx:
                        ws_notlar.delete_rows(row_idx)
                        st.warning("Not silindi!")
                        clear_cache_and_rerun()

# --- SEKME 3: GELİRLER ---
with sekmeler[2]:
    st.subheader("⚡ Gelir Ekle")
    with st.form("hizli_gelir", clear_on_submit=True):
        islem_adi = st.text_input("Açıklama (Örn: Maaş, Parça Satışı)")
        islem_miktari = st.number_input("Tutar (TL)", min_value=0.0, step=100.0)
        if st.form_submit_button("Onayla"):
            if islem_miktari > 0:
                zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
                ws_islemler.append_row([get_new_id(df_islemler), "Gelir", islem_adi, islem_miktari, zaman, "Gelir", "Maaş/Gelir"])
                st.success("✅ Gelir kaydedildi!")
                time.sleep(1)
                clear_cache_and_rerun()

# --- SEKME 4: GİDERLER ---
with sekmeler[3]:
    st.subheader("🛍️ Akıllı Harcama ve Kart Asistanı")
    with st.form("harcama_formu", clear_on_submit=True):
        h_kategori = st.selectbox("Harcama Kategorisi", kategoriler)
        h_miktar = st.number_input("Tutar (TL)", min_value=0.0, step=100.0)
        h_ihtiyac = st.radio("Bu harcama gerçekten ZORUNLU bir İhtiyaç mı?", ["Evet, Şart (İhtiyaç)", "Hayır, Keyfi (İstek)"], horizontal=True)
        odeme_tipi = st.radio("Nasıl Ödeyeceksin?", ["Nakit / Banka Kartı", "Kredi Kartı"], horizontal=True)
        
        t_ay = 1
        secilen_kart_id = None
        
        if odeme_tipi == "Kredi Kartı" and not df_kartlar.empty:
            kart_secenekleri = dict(zip(df_kartlar['id'], df_kartlar['kart_adi']))
            secilen_kart_id = st.selectbox("Hangi Kartı Kullanacaksın?", options=list(kart_secenekleri.keys()), format_func=lambda x: kart_secenekleri[x])
            t_ay = st.number_input("Kaç Taksit?", min_value=1, step=1, max_value=36)
            
        if st.form_submit_button("Harcamayı Onayla"):
            if h_miktar > 0 and h_kategori != "":
                zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
                ihtiyac_durumu = "İhtiyaç" if "Evet" in h_ihtiyac else "İstek"
                
                if odeme_tipi == "Kredi Kartı" and secilen_kart_id:
                    tip_kayit = "KK Gider"
                    if t_ay > 1:
                        aylik = h_miktar / t_ay
                        ws_taksitler.append_row([get_new_id(df_taksitler), secilen_kart_id, f"{h_kategori} ({ihtiyac_durumu})", aylik, t_ay])
                    
                    row_idx = get_row_idx(df_kartlar, 'id', secilen_kart_id)
                    if row_idx:
                        mevcut_borc = safe_float(df_kartlar.loc[df_kartlar['id'].astype(str) == str(secilen_kart_id), 'guncel_borc'].iloc[0])
                        yeni_borc = mevcut_borc + h_miktar
                        ws_kartlar.update_cell(row_idx, 4, yeni_borc)
                else:
                    tip_kayit = "Gider"
                    
                ws_islemler.append_row([get_new_id(df_islemler), tip_kayit, h_kategori, h_miktar, zaman, ihtiyac_durumu, h_kategori])
                st.success("✅ Harcama başarıyla işlendi!")
                time.sleep(1)
                clear_cache_and_rerun()

    st.divider()
    
    st.subheader("📌 Takip Edilecek Fatura / Sabit Görev Ekle")
    st.write("Ana sayfadaki checklist'te görünmesi için faturanın adını yaz. Herhangi bir miktar düşmez, sadece hatırlatıcıdır.")
    
    with st.form("fatura_ekle_formu", clear_on_submit=True):
        f_isim = st.text_input("Fatura/Görev Adı (Örn: Elektrik, Su, Aidat)")
        if st.form_submit_button("Ana Sayfadaki Listeye Ekle"):
            if f_isim:
                ws_faturalar.append_row([get_new_id(df_faturalar), f_isim, "False"])
                st.success("✅ Ana sayfadaki listeye eklendi!")
                time.sleep(1)
                clear_cache_and_rerun()
            else:
                st.error("Lütfen bir isim girin.")
                
    if not df_faturalar.empty:
        with st.expander("🗑️ Checklist'ten Görev / Fatura Sil"):
            for idx, row in df_faturalar.iterrows():
                c1, c2 = st.columns([4, 1])
                c1.write(f"📝 {row['isim']}")
                if c2.button("Listeden Sil", key=f"sil_fat_list_{idx}_{row['id']}"):
                    row_idx = get_row_idx(df_faturalar, 'id', row['id'])
                    if row_idx:
                        ws_faturalar.delete_rows(row_idx)
                        clear_cache_and_rerun()

# --- SEKME 5: TAKVİM ---
with sekmeler[4]:
    st.subheader("📅 Ödeme Takvimi ve Taksit Kronolojisi")
    if df_taksitler.empty or df_kartlar.empty:
        st.info("Gelecek aylara sarkan hiçbir taksitli borcun yok. Süpersin!")
    else:
        df_taksit_aktif = df_taksitler[df_taksitler['kalan_ay'] > 0]
        if df_taksit_aktif.empty:
            st.info("Gelecek aylara sarkan hiçbir taksitli borcun yok. Süpersin!")
        else:
            taksit_verileri = pd.merge(df_taksit_aktif, df_kartlar, left_on='kart_id', right_on='id', suffixes=('_t', '_k'))
            bugun = datetime.now()
            takvim_satirlari = []
            
            for _, row in taksit_verileri.iterrows():
                for ay_ileri in range(1, int(row['kalan_ay']) + 1):
                    hesap_ay = bugun.month + ay_ileri - 1
                    ek_yil = hesap_ay // 12
                    gercek_ay = (hesap_ay % 12) + 1
                    gercek_yil = bugun.year + ek_yil
                    siralama = int(f"{gercek_yil}{gercek_ay:02d}{int(row['hesap_kesim']):02d}")
                    tarih_metni = f"{int(row['hesap_kesim']):02d}.{gercek_ay:02d}.{gercek_yil}"
                    takvim_satirlari.append({"Sıralama": siralama, "Tarih": tarih_metni, "Kart": row['kart_adi'], "Açıklama": f"{row['aciklama']} ({ay_ileri}. Taksit)", "Aylık Tutar (TL)": safe_float(row['aylik_tutar'])})
            
            if takvim_satirlari:
                df_takvim = pd.DataFrame(takvim_satirlari).sort_values(by="Sıralama").drop(columns=["Sıralama"])
                st.dataframe(df_takvim, use_container_width=True, hide_index=True)
            
            st.divider()
            st.error("🗑️ Yanlış Eklenen Taksit Planlarını İptal Et")
            for _, row in taksit_verileri.iterrows():
                kol1, kol2, kol3, kol4 = st.columns([4, 3, 3, 1])
                kol1.write(f"🛒 **{row['aciklama']}**")
                kol2.write(f"💳 {row['kart_adi']}")
                kol3.write(f"Kalan: {int(row['kalan_ay'])} Ay ({safe_float(row['aylik_tutar']) * int(row['kalan_ay']):,.2f} TL)")
                if kol4.button("🗑️", key=f"sil_taksit_{row['id_t']}"):
                    dusulecek_tutar = safe_float(row['aylik_tutar']) * int(row['kalan_ay'])
                    kart_row_idx = get_row_idx(df_kartlar, 'id', row['kart_id'])
                    if kart_row_idx:
                        mevcut_borc = safe_float(df_kartlar.loc[df_kartlar['id'].astype(str) == str(row['kart_id']), 'guncel_borc'].iloc[0])
                        yeni_borc = max(0, mevcut_borc - dusulecek_tutar)
                        ws_kartlar.update_cell(kart_row_idx, 4, yeni_borc)
                    taksit_row_idx = get_row_idx(df_taksitler, 'id', row['id_t'])
                    if taksit_row_idx:
                        ws_taksitler.delete_rows(taksit_row_idx)
                        clear_cache_and_rerun()
                st.markdown("---")

# --- SEKME 6: YASTIK ALTI & KRİPTO ---
with sekmeler[5]:
    st.subheader("💰 Aile Varlıkları ve Fiziksel Birikimler")
    y_kol1, y_kol2 = st.columns(2)
    
    with y_kol1:
        st.write("### ➕ Varlık Ekle / Çıkar")
        with st.form("varlik_ekle_cikar_formu", clear_on_submit=True):
            sahip = st.selectbox("Kimin İçin / Hangi Kasa?", ["Kendim", "Eşim", "Çocuğum", "Ortak Kasa", "Genel Kasa"])
            islem_varlik = st.selectbox("Hangi Varlık?", ["USD", "EUR", "GA", "Çeyrek Altın", "Yarım Altın", "Tam Altın", "Ata Altın", "BTC", "ETH"])
            islem_tipi = st.radio("İşlem Tipi", ["Ekle (+)", "Çıkar (-)"], horizontal=True)
            islem_miktari = st.number_input("Miktar (Örn: 2 Adet Çeyrek, 100 Dolar)", min_value=0.0, step=1.0, format="%.6f")
            
            if st.form_submit_button("İşlemi Kaydet"):
                if islem_miktari > 0:
                    tam_isim = f"{sahip} - {islem_varlik}"
                    mevcut_miktar = 0.0
                    if not df_yastik.empty and tam_isim in df_yastik['varlik_tipi'].values:
                        mevcut_miktar = safe_float(df_yastik[df_yastik['varlik_tipi'] == tam_isim]['miktar'].iloc[0])
                    if "Ekle" in islem_tipi:
                        yeni_miktar = mevcut_miktar + islem_miktari
                        st.success(f"✅ {sahip} cüzdanına eklendi! Yeni Toplam: {yeni_miktar:,.2f}")
                    else:
                        yeni_miktar = max(0.0, mevcut_miktar - islem_miktari)
                        st.success(f"✅ {sahip} cüzdanından çıkarıldı! Yeni Toplam: {yeni_miktar:,.2f}")
                    
                    row_idx = get_row_idx(df_yastik, 'varlik_tipi', tam_isim)
                    if row_idx:
                        ws_yastik.update_cell(row_idx, 2, yeni_miktar)
                    else:
                        ws_yastik.append_row([tam_isim, yeni_miktar])
                    time.sleep(1)
                    clear_cache_and_rerun()
                else:
                    st.error("Lütfen sıfırdan büyük bir miktar gir.")
                    
        st.write("---")
        st.write("### 🗑️ Sıfırlanan Kayıtları Temizle")
        df_sifirlar = df_yastik[df_yastik['miktar'] == 0.0] if not df_yastik.empty else pd.DataFrame()
        if not df_sifirlar.empty:
            if st.button("Sıfırlanan (Miktarı 0 Olan) Varlıkları Listeden Sil"):
                for idx, row in df_sifirlar.iterrows():
                    row_idx = get_row_idx(df_yastik, 'varlik_tipi', row['varlik_tipi'])
                    if row_idx: ws_yastik.delete_rows(row_idx)
                clear_cache_and_rerun()
        else:
            st.info("Listede sıfırlanmış boş varlık kaydı yok, her şey temiz.")
                    
    with y_kol2:
        st.write("### 📊 Toplam Varlık Durumu")
        st.info(f"💵 Tüm Kasa USD: **{varlik_tipleri.get('USD', 0):,.2f}**")
        st.info(f"💶 Tüm Kasa EUR: **{varlik_tipleri.get('EUR', 0):,.2f}**")
        st.warning(f"🥇 Tüm Kasa Gram Altın: **{varlik_tipleri.get('GA', 0):,.2f} Gram**")
        if varlik_tipleri.get('Çeyrek Altın', 0) > 0: st.warning(f"🪙 Tüm Kasa Çeyrek Altın: **{varlik_tipleri.get('Çeyrek Altın', 0):,.0f} Adet**")
        if varlik_tipleri.get('Yarım Altın', 0) > 0: st.warning(f"🪙 Tüm Kasa Yarım Altın: **{varlik_tipleri.get('Yarım Altın', 0):,.0f} Adet**")
        if varlik_tipleri.get('Tam Altın', 0) > 0: st.warning(f"🪙 Tüm Kasa Tam Altın: **{varlik_tipleri.get('Tam Altın', 0):,.0f} Adet**")
        if varlik_tipleri.get('Ata Altın', 0) > 0: st.warning(f"🪙 Tüm Kasa Ata Altın: **{varlik_tipleri.get('Ata Altın', 0):,.0f} Adet**")
        st.success(f"₿ Tüm Kasa BTC: **{varlik_tipleri.get('BTC', 0):.6f}**")
        st.success(f"⟠ Tüm Kasa ETH: **{varlik_tipleri.get('ETH', 0):.6f}**")
        
        st.divider()
        st.write("### 🗂️ Kimin Ne Kadarı Var? (Detaylı Kasa)")
        if not df_yastik.empty:
            df_dolu = df_yastik[df_yastik['miktar'] > 0]
            for _, row in df_dolu.iterrows():
                vtip = str(row['varlik_tipi'])
                vtip_gosterim = vtip.replace(' - ', ' ➡ ') 
                st.markdown(f"🔹 **{vtip_gosterim}** : {safe_float(row['miktar']):,.2f}")

# --- SEKME 7: KARTLAR ---
with sekmeler[6]:
    st.subheader("💳 Kredi Kartı Yönetimi")
    kk_kol1, kk_kol2 = st.columns(2)
    with kk_kol1:
        with st.form("yeni_kart_formu", clear_on_submit=True):
            k_isim = st.text_input("Kart Adı")
            k_limit = st.number_input("Kart Limiti (TL)", min_value=0.0, step=1000.0)
            k_kesim = st.number_input("Hesap Kesim Günü", min_value=1, max_value=31, value=15, step=1)
            if st.form_submit_button("Kartı Tanımla"):
                if k_isim:
                    ws_kartlar.append_row([get_new_id(df_kartlar), k_isim, k_limit, 0.0, k_kesim])
                    clear_cache_and_rerun()

    with kk_kol2:
        if df_kartlar.empty:
            st.info("Henüz eklenmiş bir kartın yok.")
        else:
            kartlar_liste = df_kartlar.sort_values(by="id", ascending=False)
            for _, row in kartlar_liste.iterrows():
                k_id = row['id']
                kol_k1, kol_k2, kol_k3, kol_k4, kol_k5 = st.columns([3, 2, 2, 2, 1])
                kol_k1.write(f"**{row['kart_adi']}**")
                kol_k2.write(f"Limit: {safe_float(row['kart_limit']):,.0f}")
                kol_k3.write(f"Borç: {safe_float(row['guncel_borc']):,.0f}")
                kol_k4.write(f"Kesim: {row['hesap_kesim']}")
                if kol_k5.button("🗑️", key=f"sil_kart_{k_id}"):
                    kart_row_idx = get_row_idx(df_kartlar, 'id', k_id)
                    if kart_row_idx: ws_kartlar.delete_rows(kart_row_idx)
                    
                    if not df_taksitler.empty:
                        taksitler_sil = df_taksitler[df_taksitler['kart_id'].astype(str) == str(k_id)]
                        for _, t_row in taksitler_sil.iterrows():
                            t_idx = get_row_idx(df_taksitler, 'id', t_row['id'])
                            if t_idx: ws_taksitler.delete_rows(t_idx)
                    clear_cache_and_rerun()
                st.markdown("---")

# --- SEKME 8: GEÇMİŞ ---
with sekmeler[7]:
    st.subheader("📝 Tüm İşlem Geçmişi (Son 50 Kayıt)")
    if df_islemler.empty:
        st.info("Henüz işlem kaydı yok.")
    else:
        islemler_goster = df_islemler.tail(50).iloc[::-1]
        b_kol1, b_kol2, b_kol3, b_kol4, b_kol5, b_kol6 = st.columns([1.5, 1, 1.5, 3, 1.5, 1])
        b_kol1.write("**Tarih**")
        b_kol2.write("**Tür**")
        b_kol3.write("**Kategori**")
        b_kol4.write("**Açıklama**")
        b_kol5.write("**Tutar (TL)**")
        b_kol6.write("**Sil**")
        st.divider()
        
        for _, row in islemler_goster.iterrows():
            i_id = row['id']
            kol1, kol2, kol3, kol4, kol5, kol6 = st.columns([1.5, 1, 1.5, 3, 1.5, 1])
            kol1.write(f"🕒 {str(row['tarih'])[:10]}")
            
            if row['tip'] == "Gelir": kol2.markdown("🟢 **Gelir**")
            elif row['tip'] == "KK Gider": kol2.markdown("🟠 **Kart Gideri**")
            else: kol2.markdown("🔴 **Nakit Gider**")
                
            kol3.write(f"📁 {row['kategori']}")
            kol4.write(f"📝 {row['isim']}")
            kol5.write(f"**{safe_float(row['miktar']):,.2f} TL**")
            
            if kol6.button("🗑️", key=f"sil_islem_{i_id}"):
                row_idx = get_row_idx(df_islemler, 'id', i_id)
                if row_idx:
                    ws_islemler.delete_rows(row_idx)
                    clear_cache_and_rerun()
            st.markdown("---")

# --- SEKME 9: TÜCCAR ---
with sekmeler[8]:
    st.subheader("🐺 Kurt Tüccar (Al-Sat Envanteri)")
    with st.form("tic_form", clear_on_submit=True):
        st.write("### 📥 Yeni Mal Alışı")
        urun = st.text_input("Ürün Adı (Örn: 2. El Ekran Kartı, Toplu Kasa)")
        alis = st.number_input("Alış Fiyatı (Maliyet - TL)", min_value=0.0, step=100.0)
        
        if st.form_submit_button("Envantere Ekle"):
            if urun and alis > 0:
                ws_ticaret.append_row([get_new_id(df_ticaret), urun, alis, 0.0])
                zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
                ws_islemler.append_row([get_new_id(df_islemler), "Gider", f"Mal Alışı: {urun}", alis, zaman, "İhtiyaç", "Donanım (Al-Sat)"])
                st.success(f"📦 {urun} envantere eklendi ve maliyeti kasadan düşüldü!")
                time.sleep(1)
                clear_cache_and_rerun()
            else:
                st.error("Lütfen ürün adı ve maliyet tutarını girin.")
        
    if not df_ticaret.empty:
        st.divider()
        df_envanter = df_ticaret[df_ticaret['tahmini_satis'] == 0.0].sort_values(by="id", ascending=False)
        df_satilanlar = df_ticaret[df_ticaret['tahmini_satis'] > 0.0].sort_values(by="id", ascending=False)
        
        kol_env, kol_sat = st.columns(2)
        
        with kol_env:
            st.write("### 📦 Elimdeki Envanter")
            if df_envanter.empty:
                st.info("Şu an satılmayı bekleyen ürünün yok.")
            else:
                for _, row in df_envanter.iterrows():
                    t_id = row['id']
                    with st.expander(f"🛒 {row['urun_adi']} (Maliyet: {safe_float(row['alis_fiyati']):,.0f} TL)"):
                        sat_fiyati = st.number_input("Kaça Sattın? (TL)", min_value=0.0, step=50.0, key=f"satis_input_{t_id}")
                        c1, c2 = st.columns(2)
                        
                        if c1.button("✅ Satışı Onayla", key=f"sat_btn_{t_id}"):
                            if sat_fiyati > 0:
                                row_idx = get_row_idx(df_ticaret, 'id', t_id)
                                if row_idx:
                                    ws_ticaret.update_cell(row_idx, 4, sat_fiyati)
                                    zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
                                    ws_islemler.append_row([get_new_id(df_islemler), "Gelir", f"Mal Satışı: {row['urun_adi']}", sat_fiyati, zaman, "Gelir", "Donanım (Al-Sat)"])
                                    st.success("✅ Satış gerçekleşti ve para kasaya eklendi!")
                                    time.sleep(1)
                                    clear_cache_and_rerun()
                            else:
                                st.error("Lütfen satış fiyatı girin!")
                                
                        if c2.button("🗑️ Sil", key=f"sil_env_{t_id}"):
                            row_idx = get_row_idx(df_ticaret, 'id', t_id)
                            if row_idx:
                                ws_ticaret.delete_rows(row_idx)
                                clear_cache_and_rerun()
                            
        with kol_sat:
            st.write("### 💸 Satılanlar ve Kâr Durumu")
            if df_satilanlar.empty:
                st.info("Henüz ürün satışı yapmadın.")
            else:
                for _, row in df_satilanlar.iterrows():
                    t_id = row['id']
                    t_kar = safe_float(row['tahmini_satis']) - safe_float(row['alis_fiyati'])
                    st.markdown(f"**{row['urun_adi']}**")
                    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
                    c1.write(f"Alış: {safe_float(row['alis_fiyati']):,.0f}")
                    c2.write(f"Satış: {safe_float(row['tahmini_satis']):,.0f}")
                    if t_kar >= 0: c3.success(f"+{t_kar:,.0f} TL")
                    else: c3.error(f"{t_kar:,.0f} TL")
                    if c4.button("🗑️", key=f"sil_satilan_{t_id}"):
                        row_idx = get_row_idx(df_ticaret, 'id', t_id)
                        if row_idx:
                            ws_ticaret.delete_rows(row_idx)
                            clear_cache_and_rerun()
                    st.markdown("---")

# --- SEKME 10: HEDEFLER (MİNİMALİST) ---
with sekmeler[9]:
    st.subheader("🎯 Tasarruf Hedefleri")

    if not df_hedefler.empty:
        st.subheader("🎯 Mevcut Durum")
        goals = df_hedefler.sort_values(by="id", ascending=False)
        for _, row in goals.iterrows():
            h_id = row['id']
            h_tutar = safe_float(row['hedef_tutar'])
            h_biriken = safe_float(row['biriken'])
            tamamlama_orani = min(h_biriken / h_tutar if h_tutar > 0 else 0, 1.0)
            
            with st.container(border=True):
                kol_ad, kol_bar, kol_sil = st.columns([5, 4, 1])
                with kol_ad:
                    st.markdown(f"**🎯 {row['hedef_adi']}**")
                    st.write(f"{h_biriken:,.0f} / {h_tutar:,.0f} TL")
                with kol_bar:
                    st.write(f"Tamamlanan: **%{tamamlama_orani * 100:.1f}**")
                    st.progress(tamamlama_orani)
                with kol_sil:
                    if st.button("🗑️", key=f"sil_hedef_top_{h_id}"):
                        row_idx = get_row_idx(df_hedefler, 'id', h_id)
                        if row_idx:
                            ws_hedefler.delete_rows(row_idx)
                            clear_cache_and_rerun()
            st.markdown(" ")
        st.divider()

    st.write("### ➕ Yeni Hedef Oluştur")
    with st.form("hedef_formu", clear_on_submit=True):
        hedef_ad = st.text_input("Yeni Hedefin (Örn: Yeni Parça)")
        hedef_tutari = st.number_input("Hedeflenen Tutar (TL)", min_value=0.0, step=1000.0)
        hedef_biriken = st.number_input("Şu An Elindeki (TL)", min_value=0.0, step=100.0)
        
        if st.form_submit_button("Hedef Oluştur"):
            if hedef_ad:
                ws_hedefler.append_row([get_new_id(df_hedefler), hedef_ad, hedef_tutari, hedef_biriken])
                clear_cache_and_rerun()

    if not df_hedefler.empty:
        st.divider()
        st.write("### 💰 Kumbaraya Para At")
        kol_hedef1, kol_hedef2 = st.columns(2)
        with kol_hedef1:
            secilen_hedef = st.selectbox("Hangi Hedefe Para Ekliyorsun?", df_hedefler['hedef_adi'].tolist())
            eklenecek_tutar = st.number_input("Eklenecek Tutar (TL)", min_value=0.0, step=100.0)
            
            if st.button("Parayı Ekle"):
                if eklenecek_tutar > 0:
                    row_idx = get_row_idx(df_hedefler, 'hedef_adi', secilen_hedef)
                    if row_idx:
                        mevcut_biriken = safe_float(df_hedefler.loc[df_hedefler['hedef_adi'] == secilen_hedef, 'biriken'].iloc[0])
                        ws_hedefler.update_cell(row_idx, 4, mevcut_biriken + eklenecek_tutar)
                        
                        zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
                        ws_islemler.append_row([get_new_id(df_islemler), "Gider", f"Kumbara: {secilen_hedef}", eklenecek_tutar, zaman, "İhtiyaç", "Diğer"])
                        
                        st.success(f"✅ {secilen_hedef} kumbarasına {eklenecek_tutar:,.2f} TL atıldı ve nakit bakiyenden düşüldü!")
                        time.sleep(1)
                        clear_cache_and_rerun()
                else:
                    st.error("Lütfen sıfırdan büyük bir tutar gir.")

# --- SEKME 11: ABONELİKLER (VAMPİRLER) ---
with sekmeler[10]:
    st.subheader("🧛‍♂️ Gizli Vampirler (Abonelikler)")
    st.write("Her ay senden sessizce para çeken aboneliklerini buraya ekle.")
    
    with st.form("abonelik_formu"):
        a_isim = st.text_input("Abonelik Adı (Örn: Duolingo, Pratika, Netflix)")
        a_tutar = st.number_input("Aylık Tutar (TL)", min_value=0.0, step=10.0)
        a_gun = st.number_input("Her Ayın Kaçında Çekiliyor?", min_value=1, max_value=31, step=1)
        
        if st.form_submit_button("Aboneliği Ekle"):
            if a_isim and a_tutar > 0:
                ws_abonelikler.append_row([get_new_id(df_abonelikler), a_isim, a_tutar, a_gun])
                st.success(f"✅ {a_isim} sisteme eklendi!")
                time.sleep(1)
                clear_cache_and_rerun()

    if not df_abonelikler.empty:
        st.divider()
        toplam_abonelik = df_abonelikler['tutar'].apply(safe_float).sum()
        st.error(f"🚨 **Uyarı:** Sadece aboneliklere her ay havadan **{toplam_abonelik:,.2f} TL** ödüyorsun!")
        
        for _, row in df_abonelikler.iterrows():
            kol1, kol2, kol3, kol4 = st.columns([4, 2, 2, 1])
            kol1.write(f"📺 **{row['isim']}**")
            kol2.write(f"{safe_float(row['tutar']):,.2f} TL")
            kol3.write(f"Her Ayın {row['odeme_gunu']}. Günü")
            if kol4.button("🗑️", key=f"sil_ab_{row['id']}"):
                row_idx = get_row_idx(df_abonelikler, 'id', row['id'])
                if row_idx:
                    ws_abonelikler.delete_rows(row_idx)
                    clear_cache_and_rerun()

# --- SEKME 12: BÜTÇE LİMİTLERİ (KIRMIZI ÇİZGİ) ---
with sekmeler[11]:
    st.subheader("🚧 Kırmızı Çizgi (Kategori Sınırları)")
    st.write("Kategorilere limit koy, kırmızıya yaklaştığında frene bas.")
    
    with st.form("butce_formu"):
        b_kategori = st.selectbox("Hangi Kategoriye Sınır Koyacaksın?", kategoriler)
        b_limit = st.number_input("Bu Ayki Maksimum Limit (TL)", min_value=0.0, step=500.0)
        
        if st.form_submit_button("Limiti Güncelle"):
            if b_limit >= 0:
                row_idx = get_row_idx(df_butceler, 'kategori', b_kategori)
                if row_idx:
                    ws_butceler.update_cell(row_idx, 3, b_limit)
                else:
                    ws_butceler.append_row([get_new_id(df_butceler), b_kategori, b_limit])
                st.success(f"✅ {b_kategori} limiti {b_limit} TL olarak ayarlandı!")
                time.sleep(1)
                clear_cache_and_rerun()

    if not df_butceler.empty:
        st.divider()
        for _, row in df_butceler.iterrows():
            kat = row['kategori']
            limit = safe_float(row['limit_tutar'])
            
            if limit > 0:
                harcanan = 0.0
                if not df_bu_ay_giderler.empty:
                    df_kat_harcama = df_bu_ay_giderler[df_bu_ay_giderler['kategori'] == kat]
                    if not df_kat_harcama.empty:
                        harcanan = df_kat_harcama['miktar'].apply(safe_float).sum()
                
                orani = min(harcanan / limit, 1.0)
                
                with st.container(border=True):
                    c1, c2 = st.columns([3,1])
                    c1.markdown(f"**📁 {kat}**")
                    c2.write(f"{harcanan:,.0f} / {limit:,.0f} TL")
                    
                    if orani > 0.8:
                        st.error(f"🚨 Tehlike! Bütçenin %{orani*100:.1f}'ini tükettin!")
                        st.progress(orani)
                    elif orani > 0.5:
                        st.warning(f"⚠️ Yarıyı geçtin. (Doluluk: %{orani*100:.1f})")
                        st.progress(orani)
                    else:
                        st.success(f"✅ Güvendesin. (Doluluk: %{orani*100:.1f})")
                        st.progress(orani)

# --- SEKME 13: ENFLASYON ---
with sekmeler[12]:
    st.subheader("👻 Enflasyon Simülatörü")
    ana_para = st.number_input("Mevcut Tutar (TL)", value=15000, step=1000)
    enflasyon_orani = st.slider("Enflasyon (%)", 0, 150, 65)
    yil = st.slider("Kaç Yıl Sonrası?", 1, 10, 1)
    gelecek_deger = ana_para * ((1 + (enflasyon_orani / 100)) ** yil)
    st.error(f"Bugünkü **{ana_para:,.0f} TL**, {yil} yıl sonraki fiyatlarla **{gelecek_deger:,.0f} TL** olacak.")

# --- SEKME 14: DANIŞMAN VE TAHMİN MOTORU ---
with sekmeler[13]:
    st.subheader("🤖 Harcama Tahmin Motoru ve Danışman")
    bugun_gun = datetime.now().day
    
    bu_ay_giderler = df_bu_ay_giderler.copy()
    if not bu_ay_giderler.empty:
        bu_ay_giderler['miktar'] = bu_ay_giderler['miktar'].apply(safe_float)
        grouped_giderler = bu_ay_giderler.groupby('kategori')['miktar'].sum().to_dict()
    else:
        grouped_giderler = {}
    
    if not grouped_giderler:
        st.info("Bu ay henüz bir harcama girmedin. Harcama yaptıkça sana ay sonu tahminleri üreteceğim.")
    else:
        st.write(f"Bugün ayın **{bugun_gun}.** günü. Şu anki harcama hızına göre ay sonu (30 gün) tahminleri:")
        tahmin_datalari = []
        for kat, miktar in grouped_giderler.items():
            if kat == "Maaş/Gelir" or kat == "Diğer": continue
            ay_sonu_tahmin = (miktar / bugun_gun) * 30
            tahmin_datalari.append({"Kategori": kat, "Şu Anki Harcama": miktar, "Ay Sonu Tahmini": ay_sonu_tahmin})
            if ay_sonu_tahmin > miktar * 1.5: 
                st.warning(f"🚨 **{kat}** kategorisinde frene bas! Şu an {miktar:,.0f} TL harcadın, bu gidişle ay sonu **{ay_sonu_tahmin:,.0f} TL**'yi bulacak!")
        
        if tahmin_datalari:
            fig_bar = px.bar(pd.DataFrame(tahmin_datalari), x="Kategori", y=["Şu Anki Harcama", "Ay Sonu Tahmini"], barmode="group", color_discrete_sequence=['#3498db', '#e74c3c'], title="Mevcut Durum vs Ay Sonu Beklentisi")
            st.plotly_chart(fig_bar, use_container_width=True)

    st.divider()
    st.subheader("💡 Yapay Zeka Finansal Analizlerin (PRO Sürüm)")
    
    d_usd_tl = varlik_tipleri.get('USD', 0) * st.session_state.usd_try
    d_eur_tl = varlik_tipleri.get('EUR', 0) * st.session_state.eur_try
    d_ga_tl = (varlik_tipleri.get('GA', 0) * st.session_state.gr_altin) + \
                   (varlik_tipleri.get('Çeyrek Altın', 0) * (st.session_state.gr_altin * 1.605)) + \
                   (varlik_tipleri.get('Yarım Altın', 0) * (st.session_state.gr_altin * 3.21)) + \
                   (varlik_tipleri.get('Tam Altın', 0) * (st.session_state.gr_altin * 6.42)) + \
                   (varlik_tipleri.get('Ata Altın', 0) * (st.session_state.gr_altin * 6.61))
    d_btc_tl = varlik_tipleri.get('BTC', 0) * st.session_state.btc_try
    d_eth_tl = varlik_tipleri.get('ETH', 0) * st.session_state.eth_try
    toplam_likit = net_nakit + d_usd_tl + d_eur_tl + d_ga_tl

    if gercek_net_varlik > 0: st.success(f"🌟 **Zenginlik Yolculuğu:** Toplam net varlığın pozitif ({gercek_net_varlik:,.2f} TL). Yönün yukarı, böyle devam kanka!")
    elif gercek_net_varlik < 0: st.error(f"⚠️ **Borç Batağı Uyarısı:** Tüm varlıklarını satsan bile net varlığın ekside ({gercek_net_varlik:,.2f} TL). Yeni harcamaları kesip borç kapatmaya odaklanmalısın.")

    if net_nakit > 0: st.success(f"📈 **Nakit Kraldır:** Gelirlerin nakit giderlerini tokatlamış, kasada {net_nakit:,.2f} TL fazlan var.")
    elif net_nakit < 0: st.error(f"📉 **Acil Durum Freni:** Kırmızı alarm! Nakit giderler geliri {-net_nakit:,.2f} TL aşmış. Eksiye düşüyorsun.")

    if toplam_gelir > 0:
        tasarruf_orani = (net_nakit / toplam_gelir) * 100
        if tasarruf_orani >= 50: st.success(f"🚀 **Finansal Dahi:** Gelirinin %{tasarruf_orani:.1f}'sini elinde tutuyorsun. Muazzam bir tasarruf oranı!")
        elif 20 <= tasarruf_orani < 50: st.info(f"👍 **Sağlıklı Ekonomi:** Gelirinin %{tasarruf_orani:.1f}'sini biriktiriyorsun. Gayet ideal bir seviye.")
        elif 0 < tasarruf_orani < 20: st.warning(f"🐢 **Sınırda Dolaşıyorsun:** Tasarruf oranın sadece %{tasarruf_orani:.1f}. Ay sonunu zor getiriyorsun, harcamaları kısmalısın.")

    if toplam_limit > 0 and toplam_kk_borc == 0: st.success("👑 **Bankaların Düşmanı:** Kredi kartı borcun SIFIR! Finansal özgürlüğün zirvesindesin.")
    elif toplam_limit > 0:
        doluluk = (toplam_kk_borc / toplam_limit) * 100
        if doluluk > 60: st.error(f"💳 **Plastik Kelepçe:** Kredi kartı doluluk oranın %{doluluk:.1f} olmuş. Nakite geçme vakti, bankalara esir olma!")
        elif doluluk > 30: st.warning(f"💳 **Sarı Alarm:** Kart doluluk oranın %{doluluk:.1f}. Sınıra yaklaşıyorsun, biraz yavaşla.")
        else: st.info(f"💳 **Dengeli Kart:** Limit doluluk oranın %{doluluk:.1f}. Kredi notun için mükemmel bir seviye.")

    if not df_taksitler.empty and toplam_gelir > 0:
        aylik_taksit_yuku = df_taksitler['aylik_tutar'].apply(safe_float).sum()
        taksit_gelir_orani = (aylik_taksit_yuku / toplam_gelir) * 100
        if taksit_gelir_orani > 30: st.error(f"⛓️ **Geleceğe İpotek:** Aylık gelirinin %{taksit_gelir_orani:.1f}'si direkt kart taksitlerine gidiyor ({aylik_taksit_yuku:,.2f} TL/ay). Yeni taksite kesinlikle girme!")
        elif aylik_taksit_yuku > 0: st.warning(f"📅 **Aylık Yük:** Gelecek aylardan yediğin sabit taksit yükün aylık {aylik_taksit_yuku:,.2f} TL.")

    if not df_islemler.empty:
        df_gider_analiz = df_islemler[df_islemler['tip'].isin(['Gider', 'KK Gider'])]
        if not df_gider_analiz.empty:
            df_gider_analiz['miktar'] = df_gider_analiz['miktar'].apply(safe_float)
            en_cok_harcanan = df_gider_analiz.groupby('kategori')['miktar'].sum().idxmax()
            en_cok_tutar = df_gider_analiz.groupby('kategori')['miktar'].sum().max()
            st.error(f"🩸 **Kara Delik:** Paran en çok **{en_cok_harcanan}** kategorisinde eriyor ({en_cok_tutar:,.2f} TL). Oraya acil bir bütçe sınırı koymalısın.")

    if toplam_tum_giderler > 0:
        kac_aylik_fon = toplam_likit / (toplam_tum_giderler if toplam_tum_giderler > 0 else 1)
        if kac_aylik_fon >= 6: st.success(f"🛡️ **Sırtı Yere Gelmez:** Tüm gelirlerin kesilse bile seni {kac_aylik_fon:.1f} ay idare edecek nakit/altın fonun var. Çok güvenli!")
        elif 1 <= kac_aylik_fon < 6: st.info(f"☂️ **Yağmurluk Hazır:** {kac_aylik_fon:.1f} aylık acil durum fonun var. Hedefin bunu 6 aya çıkarmak olsun.")
        elif kac_aylik_fon < 1 and toplam_tum_giderler > 0: st.warning("☔ **Savunmasızsın:** Acil bir durumda elindeki likit varlıklar 1 aylık giderini bile karşılamıyor. Acil durum fonu oluşturmaya başla!")

    if d_btc_tl + d_eth_tl > 10000: st.success(f"🐋 **Kripto Balinası:** Cüzdan sağlam şişmiş kanka ({d_btc_tl + d_eth_tl:,.2f} TL).")
    if d_ga_tl > 10000: st.warning(f"🥇 **Güvenli Liman Ustası:** Yastık altı altınlarla parlıyor ({d_ga_tl:,.2f} TL).")

    if not df_ticaret.empty:
        beklenen_kar = (pd.to_numeric(df_ticaret['tahmini_satis']) - pd.to_numeric(df_ticaret['alis_fiyati'])).sum()
        if beklenen_kar > 0: st.info(f"🐺 **Kurt Tüccar Vizyonu:** Al-sat işlemlerinden beklediğin net kâr {beklenen_kar:,.2f} TL.")

# --- SEKME 15: BORÇLAR ---
with sekmeler[14]:
    st.subheader("💳 Kredi Kartı Borç Yönetimi")
    if df_kartlar.empty:
        st.info("Sisteme kayıtlı kredi kartı bulunmuyor. Önce 'Kartlar' sekmesinden kart ekle.")
    else:
        kk_borc_kol1, kk_borc_kol2 = st.columns(2)
        with kk_borc_kol1:
            st.write("### ➕ Kart Borcu Ekle / Öde")
            with st.form("kk_borc_formu"):
                kart_isimleri = df_kartlar['kart_adi'].tolist()
                secilen_kart_adi = st.selectbox("İşlem Yapılacak Kart", kart_isimleri)
                islem_tipi = st.radio("İşlem Tipi", ["Borç Ekle (Geçmiş Harcama)", "Borç Öde (Ekstre Ödemesi)", "Asgari Ödeme Yap", "Yanlış Ekledim (Geri Al)"], horizontal=True)
                islem_tutari = st.number_input("Tutar (TL)", min_value=0.0, step=100.0)
                
                if st.form_submit_button("Kartı Güncelle"):
                    if islem_tutari > 0:
                        row_idx = get_row_idx(df_kartlar, 'kart_adi', secilen_kart_adi)
                        if row_idx:
                            mevcut_borc = safe_float(df_kartlar.loc[df_kartlar['kart_adi'].astype(str) == str(secilen_kart_adi), 'guncel_borc'].iloc[0])
                            
                            if "Yanlış" in islem_tipi or "Geri Al" in islem_tipi:
                                yeni_borc = max(0, mevcut_borc - islem_tutari)
                                mesaj = f"✅ Yanlış eklenen {islem_tutari:,.2f} TL kart borcundan silindi!"
                            elif "Ekle" in islem_tipi:
                                yeni_borc = mevcut_borc + islem_tutari
                                mesaj = f"✅ {secilen_kart_adi} kartına {islem_tutari:,.2f} TL borç eklendi!"
                            else:
                                yeni_borc = max(0, mevcut_borc - islem_tutari)
                                mesaj = f"✅ {secilen_kart_adi} kartına {islem_tutari:,.2f} TL ödeme yapıldı!"
                                islem_adi = f"{secilen_kart_adi} Ekstre Ödemesi" if "Ekstre" in islem_tipi else f"{secilen_kart_adi} Asgari Ödemesi"
                                zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
                                ws_islemler.append_row([get_new_id(df_islemler), "Gider", islem_adi, islem_tutari, zaman, "İhtiyaç", "Diğer"])
                                
                            ws_kartlar.update_cell(row_idx, 4, yeni_borc)
                            st.success(mesaj)
                            time.sleep(1)
                            clear_cache_and_rerun()
                    else:
                        st.error("Lütfen sıfırdan büyük bir tutar girin.")
                        
        with kk_borc_kol2:
            st.write("### 📊 Güncel Kart Durumları")
            df_goster_kk = df_kartlar.copy()
            df_goster_kk['Kalan Limit'] = pd.to_numeric(df_goster_kk['kart_limit']) - pd.to_numeric(df_goster_kk['guncel_borc'])
            df_goster_kk = df_goster_kk.rename(columns={'kart_adi': 'Kart Adı', 'kart_limit': 'Limit', 'guncel_borc': 'Güncel Borç'})
            st.dataframe(df_goster_kk[['Kart Adı', 'Limit', 'Güncel Borç', 'Kalan Limit']], use_container_width=True, hide_index=True)

    st.divider()
    
    st.subheader("🤝 Elden / Eski Borç Takibi")
    with st.expander("➕ Yeni Borç/Yükümlülük Ekle", expanded=True):
        with st.form("borc_ekle_formu"):
            b_adi = st.text_input("Borç Veren Kişi / Açıklama")
            b_miktar = st.number_input("Toplam Borç Tutarı (TL)", min_value=0.0, step=100.0)
            b_odenen = st.number_input("Şu ana kadar ödenen (TL)", min_value=0.0, step=100.0)
            
            if st.form_submit_button("Borcu Sisteme Kaydet"):
                if b_adi != "" and b_miktar > 0:
                    zaman = datetime.now().strftime("%Y-%m-%d")
                    ws_borclar.append_row([get_new_id(df_borclar), b_adi, b_miktar, b_odenen, zaman])
                    st.success(f"✅ {b_adi} borcu kaydedildi!")
                    time.sleep(1)
                    clear_cache_and_rerun()
                else: 
                    st.error("Lütfen bir isim ve tutar gir!")

    if not df_borclar.empty:
        df_goster_borc = df_borclar.copy()
        df_goster_borc['Kalan Borç'] = pd.to_numeric(df_goster_borc['toplam_miktar']) - pd.to_numeric(df_goster_borc['odenen'])
        df_goster_borc = df_goster_borc.rename(columns={'borc_adi': 'Açıklama', 'toplam_miktar': 'Toplam', 'odenen': 'Ödenen'})
        
        st.write("### Mevcut Elden Borç Listen")
        st.dataframe(df_goster_borc[['Açıklama', 'Toplam', 'Ödenen', 'Kalan Borç']], use_container_width=True, hide_index=True)
        st.write("---")
        col1, col2 = st.columns(2)
        
        with col1:
            secilen = st.selectbox("İşlem Yapılacak Elden Borç", df_goster_borc['Açıklama'].tolist())
            odeme_tutari = st.number_input("Ödenen Miktarı Güncelle (TL)", min_value=0.0, step=50.0)
            
            if st.button("Ödemeyi Kaydet"):
                row_idx = get_row_idx(df_borclar, 'borc_adi', secilen)
                if row_idx:
                    mevcut_odenen = safe_float(df_borclar.loc[df_borclar['borc_adi'].astype(str) == str(secilen), 'odenen'].iloc[0])
                    ws_borclar.update_cell(row_idx, 4, mevcut_odenen + odeme_tutari)
                    clear_cache_and_rerun()
                
        with col2:
            st.write("Tehlikeli Bölge")
            if st.button("Seçili Borcu Tamamen Sil", type="primary"):
                row_idx = get_row_idx(df_borclar, 'borc_adi', secilen)
                if row_idx:
                    ws_borclar.delete_rows(row_idx)
                    clear_cache_and_rerun()
