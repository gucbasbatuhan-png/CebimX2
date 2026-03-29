import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.express as px
import yfinance as yf
import time
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# --- 1. SAYFA AYARLARI VE TASARIM ---
st.set_page_config(page_title="Pro Finans Uygulamam", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    div[data-testid="metric-container"] { background-color: #1e293b; border: 1px solid #334155; padding: 15px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); }
    </style>
""", unsafe_allow_html=True)

# --- 2. GOOGLE SHEETS BAĞLANTI & HAFIZA (CACHE) MOTORU ---
@st.cache_resource
def get_gsheet_client():
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_dict = dict(st.secrets["google_auth"])
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    return gspread.authorize(creds)

@st.cache_resource(ttl=600)
def get_df(sheet_name):
    client = get_gsheet_client()
    sh = client.open_by_url(st.secrets["gsheets"]["url"])
    worksheet = sh.worksheet(sheet_name)
    data = worksheet.get_all_records()
    df = pd.DataFrame(data)
    if df.empty:
        cols = {
            "islemler": ["id", "tip", "isim", "miktar", "tarih", "ihtiyac_mi", "kategori"],
            "ticaret": ["id", "urun_adi", "alis_fiyati", "tahmini_satis"],
            "hedefler": ["id", "hedef_adi", "hedef_tutar", "biriken"],
            "kredi_kartlari": ["id", "kart_adi", "kart_limit", "guncel_borc", "hesap_kesim"],
            "taksitler": ["id", "kart_id", "aciklama", "aylik_tutar", "kalan_ay"],
            "yastik_alti": ["varlik_tipi", "miktar"],
            "manuel_borclar": ["id", "borc_adi", "toplam_miktar", "odenen", "tarih"]
        }
        df = pd.DataFrame(columns=cols.get(sheet_name, []))
    return df, worksheet

def get_new_id(df):
    return int(df['id'].max() + 1) if not df.empty and 'id' in df.columns else 1

def clear_cache_and_rerun():
    st.cache_resource.clear()
    st.rerun()

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
    if st.session_state.kullanici_tipi == "gercek":
        st.success("👤 Hesap: **Ana Yönetici**")
    else:
        st.warning("👤 Hesap: **Misafir (Demo)**")
        
    if st.button("🚪 Çıkış Yap", use_container_width=True):
        st.session_state.giris_yapildi = False
        st.session_state.kullanici_tipi = None
        st.rerun()

st.title("💸 CebimX:Kişisel Finans Yönetimi")

# --- 5. VERİLERİ GOOGLE SHEETS'TEN ÇEK ---
try:
    df_islemler, ws_islemler = get_df("islemler")
    df_ticaret, ws_ticaret = get_df("ticaret")
    df_hedefler, ws_hedefler = get_df("hedefler")
    df_kartlar, ws_kartlar = get_df("kredi_kartlari")
    df_taksitler, ws_taksitler = get_df("taksitler")
    df_yastik, ws_yastik = get_df("yastik_alti")
    df_borclar, ws_borclar = get_df("manuel_borclar")
except Exception as e:
    st.error(f"⚠️ Google Sheets'e bağlanırken hata oluştu: {e}")
    st.stop()

if df_yastik.empty:
    ws_yastik.append_row(['USD', 0])
    ws_yastik.append_row(['EUR', 0])
    ws_yastik.append_row(['GA', 0])
    ws_yastik.append_row(['BTC', 0])
    ws_yastik.append_row(['ETH', 0])
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
if not df_islemler.empty:
    toplam_gelir = df_islemler[df_islemler['tip'] == 'Gelir']['miktar'].sum()
    # YENİ MANTIK: Sadece 'Gider' olanlar nakitten düşer. 'KK Gider' olanlar nakitten DÜŞMEZ!
    toplam_nakit_gider = df_islemler[df_islemler['tip'] == 'Gider']['miktar'].sum()
    toplam_tum_giderler = df_islemler[df_islemler['tip'].isin(['Gider', 'KK Gider'])]['miktar'].sum()
else:
    toplam_gelir = 0.0
    toplam_nakit_gider = 0.0
    toplam_tum_giderler = 0.0
    
net_nakit = toplam_gelir - toplam_nakit_gider

if not df_kartlar.empty:
    toplam_limit = df_kartlar['kart_limit'].sum()
    toplam_kk_borc = df_kartlar['guncel_borc'].sum()
else:
    toplam_limit = 0.0
    toplam_kk_borc = 0.0

if not df_yastik.empty:
    yastik_dict = dict(zip(df_yastik['varlik_tipi'], df_yastik['miktar']))
else:
    yastik_dict = {}

yastik_usd_tl = float(yastik_dict.get('USD', 0)) * st.session_state.usd_try
yastik_eur_tl = float(yastik_dict.get('EUR', 0)) * st.session_state.eur_try
yastik_ga_tl = float(yastik_dict.get('GA', 0)) * st.session_state.gr_altin
yastik_btc_tl = float(yastik_dict.get('BTC', 0)) * st.session_state.btc_try
yastik_eth_tl = float(yastik_dict.get('ETH', 0)) * st.session_state.eth_try

toplam_yastik_tl = yastik_usd_tl + yastik_eur_tl + yastik_ga_tl + yastik_btc_tl + yastik_eth_tl

if not df_borclar.empty:
    toplam_manuel_borc = (pd.to_numeric(df_borclar['toplam_miktar']) - pd.to_numeric(df_borclar['odenen'])).sum()
else:
    toplam_manuel_borc = 0.0

# Gerçek net varlığı hesaplarken kart borcunu düşüyoruz
gercek_net_varlik = net_nakit + toplam_yastik_tl - toplam_kk_borc - toplam_manuel_borc

kategoriler = ["Market", "Kira", "Fatura", "Eğlence", "Oyun & Yazılım", "Donanım (Al-Sat)", "Diğer"]

# --- 8. SEKMELER ---
sekme_ana, sekme_gelir, sekme_harcama, sekme_takvim, sekme_yastik, sekme_kart, sekme_gecmis, sekme_tuccar, sekme_hedef, sekme_enf, sekme_danisman, sekme_borclar = st.tabs([
    "📊 Kumanda", "🟢 Gelirler", "🛍️ Giderler", "📅 Takvim", "💰 Varlıklar", "💳 Kartlar", "📝 Geçmiş", "🐺 Tüccar", "🎯 Hedefler", "👻 Enflasyon", "🤖 Danışman", "💸 Borçlar"
])

# --- SEKME 1: ANA KUMANDA ---
with sekme_ana:
    st.error(f"💎 GERÇEK NET VARLIĞIN (NET WORTH): **{gercek_net_varlik:,.2f} TL**")
    kol1, kol2, kol3 = st.columns(3)
    kol1.metric("Net Nakit (TL)", f"{net_nakit:,.2f} TL")
    kol2.metric("Toplam Varlıklar", f"{toplam_yastik_tl:,.2f} TL")
    kol3.metric("Toplam Kart Borcu", f"{toplam_kk_borc:,.2f} TL")
    st.divider()
    
    st.subheader("🎯 Harcama Dağılımı")
    # Dağılım grafiğinde hem Nakit hem de KK harcamaları görünsün
    if not df_islemler.empty and not df_islemler[df_islemler['tip'].isin(['Gider', 'KK Gider'])].empty:
        df_gider_tum = df_islemler[df_islemler['tip'].isin(['Gider', 'KK Gider'])]
        df_kategori = df_gider_tum.groupby('kategori')['miktar'].sum().reset_index()
        df_kategori.columns = ['kategori', 'Tutar']
        fig = px.pie(df_kategori, values='Tutar', names='kategori', hole=0.4, color_discrete_sequence=px.colors.sequential.RdBu)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Dağılım grafiği için henüz gider girmedin.")

# --- SEKME 2: GELİRLER ---
with sekme_gelir:
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

# --- SEKME 3: AKILLI HARCAMA ---
with sekme_harcama:
    st.subheader("🛍️ Akıllı Harcama ve Kart Asistanı")
    h_kategori = st.selectbox("Harcama Kategorisi", kategoriler)
    h_miktar = st.number_input("Tutar (TL)", min_value=0.0, step=100.0)
    h_ihtiyac = st.radio("Bu harcama gerçekten ZORUNLU bir İhtiyaç mı?", ["Evet, Şart (İhtiyaç)", "Hayır, Keyfi (İstek)"], horizontal=True)
    odeme_tipi = st.radio("Nasıl Ödeyeceksin?", ["Nakit / Banka Kartı", "Kredi Kartı"], horizontal=True)
    st.divider()
    
    t_ay = 1
    secilen_kart_id = None
    
    if odeme_tipi == "Kredi Kartı" and not df_kartlar.empty:
        bugun = datetime.now().day
        en_uzun_gun = -1
        en_iyi_kart_id = None
        
        st.info("🧠 **Asistanın Tavsiyesi:**")
        for _, row in df_kartlar.iterrows():
            k_id = row['id']
            k_adi = row['kart_adi']
            k_lim = float(row['kart_limit'])
            k_borc = float(row['guncel_borc'])
            k_kesim = int(row['hesap_kesim'])
            
            if (k_lim - k_borc) >= h_miktar:
                kalan_gun = (k_kesim - bugun) if k_kesim > bugun else (30 - bugun) + k_kesim
                if kalan_gun > en_uzun_gun:
                    en_uzun_gun = kalan_gun
                    en_iyi_kart_id = k_id
                    onerilen_kart_adi = k_adi
        
        if en_iyi_kart_id:
            st.success(f"🎯 Kesinlikle **{onerilen_kart_adi}** ile öde! Hesap kesimine tam **{en_uzun_gun} gün** var.")
        else:
            st.error("Yeterli limiti olan kartın yok!")
    
        kart_secenekleri = dict(zip(df_kartlar['id'], df_kartlar['kart_adi']))
        secilen_kart_id = st.selectbox("Hangi Kartı Kullanacaksın?", options=list(kart_secenekleri.keys()), format_func=lambda x: kart_secenekleri[x])
        t_ay = st.number_input("Kaç Taksit?", min_value=1, step=1, max_value=36)
        
    if st.button("Harcamayı Onayla"):
        if h_miktar > 0 and h_kategori != "":
            zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
            ihtiyac_durumu = "İhtiyaç" if "Evet" in h_ihtiyac else "İstek"
            
            # YENİ MANTIK: Kredi kartıysa tip olarak "KK Gider" yazıyoruz
            if odeme_tipi == "Kredi Kartı" and secilen_kart_id:
                tip_kayit = "KK Gider"
                if t_ay > 1:
                    aylik = h_miktar / t_ay
                    ws_taksitler.append_row([get_new_id(df_taksitler), secilen_kart_id, f"{h_kategori} ({ihtiyac_durumu})", aylik, t_ay])
                
                row_idx = int(df_kartlar[df_kartlar['id'] == secilen_kart_id].index[0] + 2)
                yeni_borc = float(df_kartlar.loc[row_idx-2, 'guncel_borc']) + h_miktar
                ws_kartlar.update_cell(row_idx, 4, yeni_borc)
            else:
                tip_kayit = "Gider"
                
            ws_islemler.append_row([get_new_id(df_islemler), tip_kayit, h_kategori, h_miktar, zaman, ihtiyac_durumu, h_kategori])
            st.success("✅ Harcama başarıyla işlendi!")
            time.sleep(1)
            clear_cache_and_rerun()

# --- SEKME 4: TAKVİM ---
with sekme_takvim:
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
                    takvim_satirlari.append({"Sıralama": siralama, "Tarih": tarih_metni, "Kart": row['kart_adi'], "Açıklama": f"{row['aciklama']} ({ay_ileri}. Taksit)", "Aylık Tutar (TL)": float(row['aylik_tutar'])})
            
            if takvim_satirlari:
                df_takvim = pd.DataFrame(takvim_satirlari).sort_values(by="Sıralama").drop(columns=["Sıralama"])
                st.dataframe(df_takvim, use_container_width=True, hide_index=True)
            
            st.divider()
            st.error("🗑️ Yanlış Eklenen Taksit Planlarını İptal Et")
            for _, row in taksit_verileri.iterrows():
                kol1, kol2, kol3, kol4 = st.columns([4, 3, 3, 1])
                kol1.write(f"🛒 **{row['aciklama']}**")
                kol2.write(f"💳 {row['kart_adi']}")
                kol3.write(f"Kalan: {int(row['kalan_ay'])} Ay ({float(row['aylik_tutar']) * int(row['kalan_ay']):,.2f} TL)")
                if kol4.button("🗑️", key=f"sil_taksit_{row['id_t']}"):
                    dusulecek_tutar = float(row['aylik_tutar']) * int(row['kalan_ay'])
                    kart_row_idx = int(df_kartlar[df_kartlar['id'] == row['kart_id']].index[0] + 2)
                    yeni_borc = max(0, float(df_kartlar.loc[kart_row_idx-2, 'guncel_borc']) - dusulecek_tutar)
                    ws_kartlar.update_cell(kart_row_idx, 4, yeni_borc)
                    
                    taksit_row_idx = int(df_taksitler[df_taksitler['id'] == row['id_t']].index[0] + 2)
                    ws_taksitler.delete_rows(taksit_row_idx)
                    clear_cache_and_rerun()
                st.markdown("---")

# --- SEKME 5: YASTIK ALTI & KRİPTO ---
with sekme_yastik:
    st.subheader("💰 Fiziksel Birikimler ve Soğuk Cüzdan")
    y_kol1, y_kol2 = st.columns(2)
    
    with y_kol1:
        st.write("### ➕ Varlık Ekle / Çıkar")
        with st.form("varlik_ekle_cikar_formu", clear_on_submit=True):
            islem_varlik = st.selectbox("Hangi Varlık?", ["USD", "EUR", "GA", "BTC", "ETH"])
            islem_tipi = st.radio("İşlem Tipi", ["Ekle (+)", "Çıkar (-)"], horizontal=True)
            islem_miktari = st.number_input("Miktar (Örn: 2 gram, 100 dolar)", min_value=0.0, step=1.0, format="%.6f")
            
            if st.form_submit_button("İşlemi Kaydet"):
                if islem_miktari > 0:
                    mevcut_miktar = float(yastik_dict.get(islem_varlik, 0))
                    
                    if "Ekle" in islem_tipi:
                        yeni_miktar = mevcut_miktar + islem_miktari
                        st.success(f"✅ {islem_varlik} cüzdanına eklendi! Yeni Toplam: {yeni_miktar:,.2f}")
                    else:
                        yeni_miktar = max(0.0, mevcut_miktar - islem_miktari)
                        st.success(f"✅ {islem_varlik} cüzdanından çıkarıldı! Yeni Toplam: {yeni_miktar:,.2f}")
                    
                    try:
                        row_idx = int(df_yastik[df_yastik['varlik_tipi'] == islem_varlik].index[0] + 2)
                        ws_yastik.update_cell(row_idx, 2, yeni_miktar)
                    except:
                        ws_yastik.append_row([islem_varlik, yeni_miktar])
                        
                    time.sleep(1)
                    clear_cache_and_rerun()
                else:
                    st.error("Lütfen sıfırdan büyük bir miktar gir.")
                    
        st.write("---")
        with st.expander("✏️ Toplam Tutarı Elle Düzelt (Eski Sistem)"):
            with st.form("yastik_form"):
                yeni_usd = st.number_input("Dolar (USD)", min_value=0.0, step=10.0, value=float(yastik_dict.get('USD', 0)))
                yeni_eur = st.number_input("Euro (EUR)", min_value=0.0, step=10.0, value=float(yastik_dict.get('EUR', 0)))
                yeni_ga = st.number_input("Gram Altın (GA)", min_value=0.0, step=0.5, value=float(yastik_dict.get('GA', 0)))
                yeni_btc = st.number_input("Bitcoin (BTC)", min_value=0.0, step=0.001, format="%.6f", value=float(yastik_dict.get('BTC', 0)))
                yeni_eth = st.number_input("Ethereum (ETH)", min_value=0.0, step=0.01, format="%.6f", value=float(yastik_dict.get('ETH', 0)))
                
                if st.form_submit_button("Cüzdanı Komple Güncelle"):
                    def safe_update_yastik(varlik, miktar):
                        try:
                            row_idx = int(df_yastik[df_yastik['varlik_tipi'] == varlik].index[0] + 2)
                            ws_yastik.update_cell(row_idx, 2, miktar)
                        except:
                            ws_yastik.append_row([varlik, miktar])
                    
                    safe_update_yastik('USD', int(yeni_usd))
                    safe_update_yastik('EUR', int(yeni_eur))
                    safe_update_yastik('GA', yeni_ga)
                    safe_update_yastik('BTC', yeni_btc)
                    safe_update_yastik('ETH', yeni_eth)
                    st.success("✅ Tüm varlıklar manuel olarak güncellendi!")
                    time.sleep(1)
                    clear_cache_and_rerun()
                    
    with y_kol2:
        st.write("### 📊 Cüzdan Dağılımı")
        st.info(f"💵 **{float(yastik_dict.get('USD', 0)):.2f} USD** = {yastik_usd_tl:,.2f} TL")
        st.info(f"💶 **{float(yastik_dict.get('EUR', 0)):.2f} EUR** = {yastik_eur_tl:,.2f} TL")
        st.warning(f"🥇 **{float(yastik_dict.get('GA', 0)):.2f} Altın** = {yastik_ga_tl:,.2f} TL")
        st.success(f"₿ **{float(yastik_dict.get('BTC', 0)):.6f} BTC** = {yastik_btc_tl:,.2f} TL")
        st.success(f"⟠ **{float(yastik_dict.get('ETH', 0)):.6f} ETH** = {yastik_eth_tl:,.2f} TL")

# --- SEKME 6: KARTLAR ---
with sekme_kart:
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
                kol_k2.write(f"Limit: {float(row['kart_limit']):,.0f}")
                kol_k3.write(f"Borç: {float(row['guncel_borc']):,.0f}")
                kol_k4.write(f"Kesim: {row['hesap_kesim']}")
                if kol_k5.button("🗑️", key=f"sil_kart_{k_id}"):
                    kart_row_idx = int(df_kartlar[df_kartlar['id'] == k_id].index[0] + 2)
                    ws_kartlar.delete_rows(kart_row_idx)
                    if not df_taksitler.empty:
                        taksit_indices = df_taksitler[df_taksitler['kart_id'] == k_id].index.tolist()
                        for idx in sorted(taksit_indices, reverse=True):
                            ws_taksitler.delete_rows(int(idx + 2))
                    clear_cache_and_rerun()
                st.markdown("---")

# --- SEKME 7: GEÇMİŞ ---
with sekme_gecmis:
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
            
            if row['tip'] == "Gelir": 
                kol2.markdown("🟢 **Gelir**")
            elif row['tip'] == "KK Gider": 
                kol2.markdown("🟠 **Kart Gideri**")
            else: 
                kol2.markdown("🔴 **Nakit Gider**")
                
            kol3.write(f"📁 {row['kategori']}")
            kol4.write(f"📝 {row['isim']}")
            kol5.write(f"**{float(row['miktar']):,.2f} TL**")
            
            if kol6.button("🗑️", key=f"sil_islem_{i_id}"):
                row_idx = int(df_islemler[df_islemler['id'] == i_id].index[0] + 2)
                ws_islemler.delete_rows(row_idx)
                clear_cache_and_rerun()
            st.markdown("---")

# --- SEKME 8: TÜCCAR ---
with sekme_tuccar:
    st.subheader("🐺 Kurt Tüccar (Al-Sat Envanteri)")
    
    # 1. Yeni Ürün Ekleme (Sadece Envantere Alış)
    with st.form("tic_form", clear_on_submit=True):
        st.write("### 📥 Yeni Mal Alışı")
        urun = st.text_input("Ürün Adı (Örn: 2. El Ekran Kartı, Toplu Kasa)")
        alis = st.number_input("Alış Fiyatı (Maliyet - TL)", min_value=0.0, step=100.0)
        
        if st.form_submit_button("Envantere Ekle"):
            if urun and alis > 0:
                # 1. Ticaret sekmesine kaydet
                ws_ticaret.append_row([get_new_id(df_ticaret), urun, alis, 0.0])
                
                # 2. Nakit bakiyeden (Gider olarak) düş!
                zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
                ws_islemler.append_row([get_new_id(df_islemler), "Gider", f"Mal Alışı: {urun}", alis, zaman, "İhtiyaç", "Donanım (Al-Sat)"])
                
                st.success(f"📦 {urun} envantere eklendi ve maliyeti ({alis:,.2f} TL) kasadan düşüldü!")
                time.sleep(1)
                clear_cache_and_rerun()
            else:
                st.error("Lütfen ürün adı ve maliyet tutarını girin.")
        
    if not df_ticaret.empty:
        st.divider()
        df_envanter = df_ticaret[df_ticaret['tahmini_satis'] == 0].sort_values(by="id", ascending=False)
        df_satilanlar = df_ticaret[df_ticaret['tahmini_satis'] > 0].sort_values(by="id", ascending=False)
        
        kol_env, kol_sat = st.columns(2)
        
        with kol_env:
            st.write("### 📦 Elimdeki Envanter")
            if df_envanter.empty:
                st.info("Şu an satılmayı bekleyen ürünün yok.")
            else:
                for _, row in df_envanter.iterrows():
                    t_id = row['id']
                    with st.expander(f"🛒 {row['urun_adi']} (Maliyet: {float(row['alis_fiyati']):,.0f} TL)"):
                        sat_fiyati = st.number_input("Kaça Sattın? (TL)", min_value=0.0, step=50.0, key=f"satis_input_{t_id}")
                        c1, c2 = st.columns(2)
                        
                        if c1.button("✅ Satışı Onayla", key=f"sat_btn_{t_id}"):
                            if sat_fiyati > 0:
                                # 1. Satış fiyatını Ticaret sekmesine yaz
                                row_idx = int(df_ticaret[df_ticaret['id'] == t_id].index[0] + 2)
                                ws_ticaret.update_cell(row_idx, 4, sat_fiyati)
                                
                                # 2. Satış gelirini Kasaya (Gelir olarak) ekle!
                                zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
                                ws_islemler.append_row([get_new_id(df_islemler), "Gelir", f"Mal Satışı: {row['urun_adi']}", sat_fiyati, zaman, "Gelir", "Donanım (Al-Sat)"])
                                
                                st.success("✅ Satış gerçekleşti ve para kasaya eklendi!")
                                time.sleep(1)
                                clear_cache_and_rerun()
                            else:
                                st.error("Lütfen satış fiyatı girin!")
                                
                        if c2.button("🗑️ Sil", key=f"sil_env_{t_id}"):
                            row_idx = int(df_ticaret[df_ticaret['id'] == t_id].index[0] + 2)
                            ws_ticaret.delete_rows(row_idx)
                            clear_cache_and_rerun()
                            
        with kol_sat:
            st.write("### 💸 Satılanlar ve Kâr Durumu")
            if df_satilanlar.empty:
                st.info("Henüz ürün satışı yapmadın.")
            else:
                for _, row in df_satilanlar.iterrows():
                    t_id = row['id']
                    t_kar = float(row['tahmini_satis']) - float(row['alis_fiyati'])
                    
                    st.markdown(f"**{row['urun_adi']}**")
                    c1, c2, c3, c4 = st.columns([2, 2, 2, 1])
                    c1.write(f"Alış: {float(row['alis_fiyati']):,.0f}")
                    c2.write(f"Satış: {float(row['tahmini_satis']):,.0f}")
                    
                    if t_kar >= 0:
                        c3.success(f"+{t_kar:,.0f} TL")
                    else:
                        c3.error(f"{t_kar:,.0f} TL")
                        
                    if c4.button("🗑️", key=f"sil_satilan_{t_id}"):
                        row_idx = int(df_ticaret[df_ticaret['id'] == t_id].index[0] + 2)
                        ws_ticaret.delete_rows(row_idx)
                        clear_cache_and_rerun()
                    st.markdown("---")
# --- SEKME 9: HEDEFLER ---
with sekme_hedef:
    st.subheader("🎯 Tasarruf Hedefleri")
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
        st.write("📈 **Hedef İlerleme Grafiği:**")
        df_hedefler["Kalan"] = pd.to_numeric(df_hedefler["hedef_tutar"]) - pd.to_numeric(df_hedefler["biriken"])
        
        df_grafik = df_hedefler.copy()
        df_grafik.rename(columns={'hedef_adi': 'Hedef Adı', 'biriken': 'Biriken', 'hedef_tutar': 'Hedef'}, inplace=True)
        
        fig_hedefler = px.bar(df_grafik, y="Hedef Adı", x=["Biriken", "Kalan"], title=None, barmode='stack', orientation='h', color_discrete_map={'Biriken':'#10b981', 'Kalan':'#334155'}) 
        fig_hedefler.update_layout(xaxis_title="Tutar (TL)", yaxis_title="Hedef Adı", showlegend=False)
        st.plotly_chart(fig_hedefler, use_container_width=True)

        st.divider()
        
        # --- YENİ EKLENEN PARA EKLEME BÖLÜMÜ (NAKİTTEN DÜŞEN VERSİYON) ---
        st.write("### 💰 Kumbaraya Para At")
        kol_hedef1, kol_hedef2 = st.columns(2)
        with kol_hedef1:
            secilen_hedef = st.selectbox("Hangi Hedefe Para Ekliyorsun?", df_hedefler['hedef_adi'].tolist())
            eklenecek_tutar = st.number_input("Eklenecek Tutar (TL)", min_value=0.0, step=100.0)
            
            if st.button("Parayı Ekle"):
                if eklenecek_tutar > 0:
                    row_idx = int(df_hedefler[df_hedefler['hedef_adi'] == secilen_hedef].index[0] + 2)
                    mevcut_biriken = float(df_hedefler.loc[row_idx-2, 'biriken'])
                    yeni_biriken = mevcut_biriken + eklenecek_tutar
                    
                    # 1. Hedefin içindeki parayı artırıyoruz
                    ws_hedefler.update_cell(row_idx, 4, yeni_biriken)
                    
                    # 2. Cebinden parayı (Nakitten) Gider olarak düşüyoruz
                    zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
                    ws_islemler.append_row([get_new_id(df_islemler), "Gider", f"Kumbara: {secilen_hedef}", eklenecek_tutar, zaman, "İhtiyaç", "Diğer"])
                    
                    st.success(f"✅ {secilen_hedef} kumbarasına {eklenecek_tutar:,.2f} TL atıldı ve nakit bakiyenden düşüldü!")
                    time.sleep(1)
                    clear_cache_and_rerun()
                else:
                    st.error("Lütfen sıfırdan büyük bir tutar gir.")

        st.divider()
        st.write("### 📋 Mevcut Hedeflerin")
        goals = df_hedefler.sort_values(by="id", ascending=False)
        for _, row in goals.iterrows():
            h_id = row['id']
            h_tutar = float(row['hedef_tutar'])
            h_biriken = float(row['biriken'])
            
            hkol1, hkol2, hkol3 = st.columns([6, 3, 1])
            with hkol1:
                st.markdown(f"**🎯 {row['hedef_adi']}** - ({h_biriken:,.0f} / {h_tutar:,.0f} TL)")
                st.write(f"Tamamlanan: **%{min(h_biriken / h_tutar if h_tutar > 0 else 0, 1.0) * 100:.1f}**")
            with hkol2:
                 st.progress(min(h_biriken / h_tutar if h_tutar > 0 else 0, 1.0))
            
            if hkol3.button("🗑️", key=f"sil_hedef_{h_id}"):
                row_idx = int(df_hedefler[df_hedefler['id'] == h_id].index[0] + 2)
                ws_hedefler.delete_rows(row_idx)
                clear_cache_and_rerun()
            st.markdown("---")
# --- SEKME 10: ENFLASYON ---
with sekme_enf:
    st.subheader("👻 Enflasyon Simülatörü")
    ana_para = st.number_input("Mevcut Tutar (TL)", value=15000, step=1000)
    enflasyon_orani = st.slider("Enflasyon (%)", 0, 150, 65)
    yil = st.slider("Kaç Yıl Sonrası?", 1, 10, 1)
    gelecek_deger = ana_para * ((1 + (enflasyon_orani / 100)) ** yil)
    st.error(f"Bugünkü **{ana_para:,.0f} TL**, {yil} yıl sonraki fiyatlarla **{gelecek_deger:,.0f} TL** olacak.")

# --- SEKME 11: DANIŞMAN VE TAHMİN MOTORU ---
with sekme_danisman:
    st.subheader("🤖 Harcama Tahmin Motoru ve Danışman")
    bugun_gun = datetime.now().day
    mevcut_ay = f"{datetime.now().year}-{datetime.now().month:02d}"
    
    if not df_islemler.empty:
        bu_ay_df = df_islemler[(df_islemler['tip'].isin(['Gider', 'KK Gider'])) & (df_islemler['tarih'].astype(str).str.startswith(mevcut_ay))]
        bu_ay_giderler = bu_ay_df.groupby('kategori')['miktar'].sum().to_dict() if not bu_ay_df.empty else {}
    else:
        bu_ay_giderler = {}
    
    if not bu_ay_giderler:
        st.info("Bu ay henüz bir harcama girmedin. Harcama yaptıkça sana ay sonu tahminleri üreteceğim.")
    else:
        st.write(f"Bugün ayın **{bugun_gun}.** günü. Şu anki harcama hızına göre ay sonu (30 gün) tahminleri:")
        tahmin_datalari = []
        for kat, miktar in bu_ay_giderler.items():
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

    if gercek_net_varlik > 0:
        st.success(f"🌟 **Zenginlik Yolculuğu:** Toplam net varlığın pozitif ({gercek_net_varlik:,.2f} TL). Yönün yukarı, böyle devam kanka!")
    elif gercek_net_varlik < 0:
        st.error(f"⚠️ **Borç Batağı Uyarısı:** Tüm varlıklarını satsan bile net varlığın ekside ({gercek_net_varlik:,.2f} TL). Yeni harcamaları kesip borç kapatmaya odaklanmalısın.")

    if net_nakit > 0: 
        st.success(f"📈 **Nakit Kraldır:** Gelirlerin nakit giderlerini tokatlamış, kasada {net_nakit:,.2f} TL fazlan var.")
    elif net_nakit < 0: 
        st.error(f"📉 **Acil Durum Freni:** Kırmızı alarm! Nakit giderler geliri {-net_nakit:,.2f} TL aşmış. Eksiye düşüyorsun.")

    if toplam_gelir > 0:
        tasarruf_orani = (net_nakit / toplam_gelir) * 100
        if tasarruf_orani >= 50:
            st.success(f"🚀 **Finansal Dahi:** Gelirinin %{tasarruf_orani:.1f}'sini elinde tutuyorsun. Muazzam bir tasarruf oranı!")
        elif 20 <= tasarruf_orani < 50:
            st.info(f"👍 **Sağlıklı Ekonomi:** Gelirinin %{tasarruf_orani:.1f}'sini biriktiriyorsun. Gayet ideal bir seviye.")
        elif 0 < tasarruf_orani < 20:
            st.warning(f"🐢 **Sınırda Dolaşıyorsun:** Tasarruf oranın sadece %{tasarruf_orani:.1f}. Ay sonunu zor getiriyorsun, harcamaları kısmalısın.")

    if toplam_limit > 0 and toplam_kk_borc == 0: 
        st.success("👑 **Bankaların Düşmanı:** Kredi kartı borcun SIFIR! Finansal özgürlüğün zirvesindesin.")
    elif toplam_limit > 0:
        doluluk = (toplam_kk_borc / toplam_limit) * 100
        if doluluk > 60: 
            st.error(f"💳 **Plastik Kelepçe:** Kredi kartı doluluk oranın %{doluluk:.1f} olmuş. Nakite geçme vakti, bankalara esir olma!")
        elif doluluk > 30:
            st.warning(f"💳 **Sarı Alarm:** Kart doluluk oranın %{doluluk:.1f}. Sınıra yaklaşıyorsun, biraz yavaşla.")
        else: 
            st.info(f"💳 **Dengeli Kart:** Limit doluluk oranın %{doluluk:.1f}. Kredi notun için mükemmel bir seviye.")

    if not df_taksitler.empty and toplam_gelir > 0:
        aylik_taksit_yuku = df_taksitler['aylik_tutar'].sum()
        taksit_gelir_orani = (aylik_taksit_yuku / toplam_gelir) * 100
        if taksit_gelir_orani > 30:
            st.error(f"⛓️ **Geleceğe İpotek:** Aylık gelirinin %{taksit_gelir_orani:.1f}'si direkt kart taksitlerine gidiyor ({aylik_taksit_yuku:,.2f} TL/ay). Yeni taksite kesinlikle girme!")
        elif aylik_taksit_yuku > 0:
            st.warning(f"📅 **Aylık Yük:** Gelecek aylardan yediğin sabit taksit yükün aylık {aylik_taksit_yuku:,.2f} TL.")

    if not df_islemler.empty:
        df_gider_analiz = df_islemler[df_islemler['tip'].isin(['Gider', 'KK Gider'])]
        if not df_gider_analiz.empty:
            en_cok_harcanan = df_gider_analiz.groupby('kategori')['miktar'].sum().idxmax()
            en_cok_tutar = df_gider_analiz.groupby('kategori')['miktar'].sum().max()
            st.error(f"🩸 **Kara Delik:** Paran en çok **{en_cok_harcanan}** kategorisinde eriyor ({en_cok_tutar:,.2f} TL). Oraya acil bir bütçe sınırı koymalısın.")
            
        keyfi_toplam = df_gider_analiz[df_gider_analiz['ihtiyac_mi'] == 'İstek']['miktar'].sum()
        if keyfi_toplam > 0: 
            st.warning(f"🎮 **İstek vs İhtiyaç:** Bu ara 'Keyfi' harcamalara fazla dalmışsın kanka ({keyfi_toplam:,.2f} TL). Para cebinden sadece zevk için uçmuş.")

    toplam_likit = net_nakit + yastik_usd_tl + yastik_eur_tl + yastik_ga_tl
    if toplam_tum_giderler > 0:
        kac_aylik_fon = toplam_likit / (toplam_tum_giderler if toplam_tum_giderler > 0 else 1)
        if kac_aylik_fon >= 6:
            st.success(f"🛡️ **Sırtı Yere Gelmez:** Tüm gelirlerin kesilse bile seni {kac_aylik_fon:.1f} ay idare edecek nakit/altın fonun var. Çok güvenli!")
        elif 1 <= kac_aylik_fon < 6:
            st.info(f"☂️ **Yağmurluk Hazır:** {kac_aylik_fon:.1f} aylık acil durum fonun var. Hedefin bunu 6 aya çıkarmak olsun.")
        elif kac_aylik_fon < 1 and toplam_tum_giderler > 0:
            st.warning("☔ **Savunmasızsın:** Acil bir durumda elindeki likit varlıklar 1 aylık giderini bile karşılamıyor. Acil durum fonu oluşturmaya başla!")

    if yastik_btc_tl + yastik_eth_tl > 10000: 
        st.success(f"🐋 **Kripto Balinası:** Cüzdan sağlam şişmiş kanka ({yastik_btc_tl + yastik_eth_tl:,.2f} TL).")
    if yastik_ga_tl > 10000: 
        st.warning(f"🥇 **Güvenli Liman Ustası:** Yastık altı altınlarla parlıyor ({yastik_ga_tl:,.2f} TL).")

    if not df_ticaret.empty:
        beklenen_kar = (pd.to_numeric(df_ticaret['tahmini_satis']) - pd.to_numeric(df_ticaret['alis_fiyati'])).sum()
        if beklenen_kar > 0: 
            st.info(f"🐺 **Kurt Tüccar Vizyonu:** Al-sat işlemlerinden beklediğin net kâr {beklenen_kar:,.2f} TL.")

    if not df_hedefler.empty:
        tamamlanan = len(df_hedefler[(pd.to_numeric(df_hedefler['biriken']) >= pd.to_numeric(df_hedefler['hedef_tutar'])) & (pd.to_numeric(df_hedefler['hedef_tutar']) > 0)])
        if tamamlanan > 0: 
            st.success(f"🎯 **Hedef Avcısı:** Helal olsun! Koyduğun hedeflerden {tamamlanan} tanesini bitirmişsin.")

# --- SEKME 12: BORÇLAR ---
with sekme_borclar:
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
                islem_tipi = st.radio("İşlem Tipi", ["Borç Ekle (Geçmiş Harcama)", "Borç Öde (Ekstre Ödemesi)"], horizontal=True)
                islem_tutari = st.number_input("Tutar (TL)", min_value=0.0, step=100.0)
                
                if st.form_submit_button("Kartı Güncelle"):
                    if islem_tutari > 0:
                        row_idx = int(df_kartlar[df_kartlar['kart_adi'] == secilen_kart_adi].index[0] + 2)
                        mevcut_borc = float(df_kartlar.loc[row_idx-2, 'guncel_borc'])
                        
                        if "Ekle" in islem_tipi:
                            yeni_borc = mevcut_borc + islem_tutari
                            mesaj = f"✅ {secilen_kart_adi} kartına {islem_tutari:,.2f} TL borç eklendi!"
                        else:
                            yeni_borc = max(0, mevcut_borc - islem_tutari)
                            mesaj = f"✅ {secilen_kart_adi} kartına {islem_tutari:,.2f} TL ödeme yapıldı!"
                            # YENİ MANTIK: Kart borcunu ödediğin an, cüzdanından gerçek Nakit Gider olarak düşer!
                            zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
                            ws_islemler.append_row([get_new_id(df_islemler), "Gider", f"{secilen_kart_adi} Ekstre Ödemesi", islem_tutari, zaman, "İhtiyaç", "Diğer"])
                            
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
                row_idx = int(df_borclar[df_borclar['borc_adi'] == secilen].index[0] + 2)
                mevcut_odenen = float(df_borclar.loc[row_idx-2, 'odenen'])
                ws_borclar.update_cell(row_idx, 4, mevcut_odenen + odeme_tutari)
                clear_cache_and_rerun()
                
        with col2:
            st.write("Tehlikeli Bölge")
            if st.button("Seçili Borcu Tamamen Sil", type="primary"):
                row_idx = int(df_borclar[df_borclar['borc_adi'] == secilen].index[0] + 2)
                ws_borclar.delete_rows(row_idx)
                clear_cache_and_rerun()
