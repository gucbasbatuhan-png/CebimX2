import streamlit as st
import sqlite3
import pandas as pd
from datetime import datetime
import plotly.express as px
import yfinance as yf
import time

# Sayfa ayarı her zaman en üstte olmalı
st.set_page_config(page_title="CebimX - Finans", layout="wide")

# --- GİRİŞ (LOGIN) SİSTEMİ BAŞLANGICI ---
if 'giris_yapildi' not in st.session_state:
    st.session_state.giris_yapildi = False
    st.session_state.kullanici_tipi = None

if not st.session_state.giris_yapildi:
    st.title("🔐 CebimX Giriş Ekranı")
    
    kol1, kol2, kol3 = st.columns([1, 1.5, 1])
    with kol2:
        with st.container(border=True):
            kadi = st.text_input("Kullanıcı Adı")
            sifre = st.text_input("Şifre", type="password")
            giris_btn = st.button("Giriş Yap", use_container_width=True)
            
            if giris_btn:
                if kadi == "admin" and sifre == "ipekeva2024": # Kendi şifreni yap
                    st.success("✅ Başarıyla giriş yaptınız! 3 saniye içinde yönlendiriliyorsunuz...")
                    time.sleep(3) 
                    st.session_state.giris_yapildi = True
                    st.session_state.kullanici_tipi = "gercek"
                    st.rerun()
                elif kadi == "deneme" and sifre == "deneme": # Sahte hesap şifresi
                    st.success("✅ Başarıyla giriş yaptınız! 3 saniye içinde yönlendiriliyorsunuz...")
                    time.sleep(3)
                    st.session_state.giris_yapildi = True
                    st.session_state.kullanici_tipi = "sahte"
                    st.rerun()
                else:
                    st.error("❌ Lütfen kullanıcı adı ve şifrenizi kontrol edin.")
    st.stop() # Giriş doğru değilse kodun devamını çalıştırmaz!
# --- GİRİŞ SİSTEMİ BİTİŞİ ---

# Veritabanı seçimi (Giriş tipine göre otomatik değişir)
db_dosyasi = 'finans.db' if st.session_state.kullanici_tipi == "gercek" else 'finans_sahte.db'
conn = sqlite3.connect(db_dosyasi, check_same_thread=False)

# ... Buradan sonrası senin eski sekmelerin, grafiklerin vb. ...
st.title("💸 CebimX:Kişisel Finans Yönetimi")

# --- 1. SAYFA AYARLARI VE TASARIM ---
# Streamlit'te sayfa ayarları her zaman en başta olmalıdır
st.set_page_config(page_title="Pro Finans Uygulamam", layout="wide", initial_sidebar_state="expanded")

st.markdown("""
    <style>
    div[data-testid="metric-container"] { background-color: #1e293b; border: 1px solid #334155; padding: 15px; border-radius: 10px; box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1); }
    </style>
""", unsafe_allow_html=True)

# --- 2. GİRİŞ (LOGIN) SİSTEMİ ---
if 'giris_yapildi' not in st.session_state:
    st.session_state.giris_yapildi = False
    st.session_state.kullanici_tipi = None

# Eğer giriş yapılmamışsa sadece giriş ekranını göster ve durdur
if not st.session_state.giris_yapildi:
    st.title("🔐 CebimX Giriş Ekranı")
    
    kol1, kol2, kol3 = st.columns([1, 2, 1])
    with kol2:
        with st.container(border=True):
            kadi = st.text_input("Kullanıcı Adı")
            sifre = st.text_input("Şifre", type="password")
            giris_btn = st.button("Giriş Yap", use_container_width=True)
            
            if giris_btn:
                # ==========================================
                # ŞİFRELERİ BURADAN DEĞİŞTİREBİLİRSİN KANKA
                # ==========================================
                
                # 1. GERÇEK HESABIN BİLGİLERİ
                if kadi == "admin" and sifre == "ipekeva2024":
                    st.session_state.giris_yapildi = True
                    st.session_state.kullanici_tipi = "gercek"
                    st.rerun()
                
                # 2. SAHTE/GÖSTERİŞ HESABININ BİLGİLERİ
                elif kadi == "deneme" and sifre == "deneme":
                    st.session_state.giris_yapildi = True
                    st.session_state.kullanici_tipi = "sahte"
                    st.rerun()
                
                else:
                    st.error("Hatalı kullanıcı adı veya şifre!")
    st.stop() # Giriş yapılmadıysa uygulamanın geri kalanını okuma

# --- 3. ÇIKIŞ YAPMA BUTONU (YAN MENÜ) ---
with st.sidebar:
    if st.session_state.kullanici_tipi == "gercek":
        st.success("👤 Hesap: **Ana Yönetici**")
    else:
        st.warning("👤 Hesap: **Misafir (Demo)**")
        
    if st.button("🚪 Çıkış Yap", use_container_width=True):
        st.session_state.giris_yapildi = False
        st.session_state.kullanici_tipi = None
        st.rerun()

# --- 4. VERİTABANI BAĞLANTISI VE TABLOLAR ---
# Kullanıcı tipine göre bağlanılacak veritabanını seçiyoruz
db_dosyasi = 'finans.db' if st.session_state.kullanici_tipi == "gercek" else 'finans_sahte.db'

conn = sqlite3.connect(db_dosyasi, check_same_thread=False)
c = conn.cursor()

c.execute('''CREATE TABLE IF NOT EXISTS islemler (id INTEGER PRIMARY KEY AUTOINCREMENT, tip TEXT, isim TEXT, miktar REAL, tarih TEXT)''')
c.execute('''CREATE TABLE IF NOT EXISTS ticaret (id INTEGER PRIMARY KEY AUTOINCREMENT, urun_adi TEXT, alis_fiyati REAL, tahmini_satis REAL)''')
c.execute('''CREATE TABLE IF NOT EXISTS hedefler (id INTEGER PRIMARY KEY AUTOINCREMENT, hedef_adi TEXT, hedef_tutar REAL, biriken REAL)''')
c.execute('''CREATE TABLE IF NOT EXISTS kredi_kartlari (id INTEGER PRIMARY KEY AUTOINCREMENT, kart_adi TEXT, kart_limit REAL, guncel_borc REAL, hesap_kesim INTEGER DEFAULT 1)''')
c.execute('''CREATE TABLE IF NOT EXISTS taksitler (id INTEGER PRIMARY KEY AUTOINCREMENT, kart_id INTEGER, aciklama TEXT, aylik_tutar REAL, kalan_ay INTEGER)''')
c.execute('''CREATE TABLE IF NOT EXISTS yastik_alti (varlik_tipi TEXT PRIMARY KEY, miktar REAL)''')
c.execute('''CREATE TABLE IF NOT EXISTS manuel_borclar (id INTEGER PRIMARY KEY AUTOINCREMENT, borc_adi TEXT, toplam_miktar REAL, odenen REAL, tarih TEXT)''')

try:
    c.execute("ALTER TABLE islemler ADD COLUMN ihtiyac_mi TEXT DEFAULT 'Belirtilmedi'")
except:
    pass

try:
    c.execute("ALTER TABLE islemler ADD COLUMN kategori TEXT DEFAULT 'Diğer'")
except:
    pass

c.execute("INSERT OR IGNORE INTO yastik_alti (varlik_tipi, miktar) VALUES ('USD', 0), ('EUR', 0), ('GA', 0), ('BTC', 0), ('ETH', 0)")
conn.commit()

# --- 5. CANLI PİYASALAR VE KRİPTO RADARI ---
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
        usd = yf.Ticker("TRY=X").history(period="1d")['Close'].iloc[-1]
        eur = yf.Ticker("EURTRY=X").history(period="1d")['Close'].iloc[-1]
        altin_ons_usd = yf.Ticker("GC=F").history(period="1d")['Close'].iloc[-1] 
        btc_usd = yf.Ticker("BTC-USD").history(period="1d")['Close'].iloc[-1]
        eth_usd = yf.Ticker("ETH-USD").history(period="1d")['Close'].iloc[-1]
        
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

# --- 6. ORTAK VERİLER VE GERÇEK NET VARLIK ---
c.execute("SELECT SUM(miktar) FROM islemler WHERE tip='Gelir'")
toplam_gelir = c.fetchone()[0] or 0.0
c.execute("SELECT SUM(miktar) FROM islemler WHERE tip='Gider'")
toplam_gider = c.fetchone()[0] or 0.0
net_nakit = toplam_gelir - toplam_gider

c.execute("SELECT SUM(kart_limit), SUM(guncel_borc) FROM kredi_kartlari")
kart_verileri = c.fetchone()
toplam_limit = kart_verileri[0] if kart_verileri and kart_verileri[0] else 0.0
toplam_kk_borc = kart_verileri[1] if kart_verileri and kart_verileri[1] else 0.0

c.execute("SELECT varlik_tipi, miktar FROM yastik_alti")
yastik_dict = {row[0]: row[1] for row in c.fetchall()}

yastik_usd_tl = yastik_dict.get('USD', 0) * st.session_state.usd_try
yastik_eur_tl = yastik_dict.get('EUR', 0) * st.session_state.eur_try
yastik_ga_tl = yastik_dict.get('GA', 0) * st.session_state.gr_altin
yastik_btc_tl = yastik_dict.get('BTC', 0) * st.session_state.btc_try
yastik_eth_tl = yastik_dict.get('ETH', 0) * st.session_state.eth_try

c.execute("SELECT SUM(toplam_miktar - odenen) FROM manuel_borclar")
toplam_manuel_borc = c.fetchone()[0] or 0.0

toplam_yastik_tl = yastik_usd_tl + yastik_eur_tl + yastik_ga_tl + yastik_btc_tl + yastik_eth_tl
gercek_net_varlik = net_nakit + toplam_yastik_tl - toplam_kk_borc - toplam_manuel_borc

kategoriler = ["Market", "Kira", "Fatura", "Eğlence", "Oyun & Yazılım", "Donanım (Al-Sat)", "Diğer"]

# --- 7. SEKMELER ---
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
    df_kategori = pd.read_sql_query("SELECT kategori, SUM(miktar) as Tutar FROM islemler WHERE tip='Gider' GROUP BY kategori", conn)
    if not df_kategori.empty:
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
        if st.form_submit_button("Onayla") and islem_miktari > 0:
            zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
            c.execute("INSERT INTO islemler (tip, isim, miktar, tarih, ihtiyac_mi, kategori) VALUES (?, ?, ?, ?, ?, ?)", ('Gelir', islem_adi, islem_miktari, zaman, "Gelir", "Maaş/Gelir"))
            conn.commit()
            st.success("✅ Gelir kaydedildi!")
            time.sleep(1)
            st.rerun()

# --- SEKME 3: AKILLI HARCAMA ---
with sekme_harcama:
    st.subheader("🛍️ Akıllı Harcama ve Kart Asistanı")
    st.write("Sana en mantıklı ödeme yöntemini sunalım.")

    h_kategori = st.selectbox("Harcama Kategorisi", kategoriler)
    h_miktar = st.number_input("Tutar (TL)", min_value=0.0, step=100.0)
    h_ihtiyac = st.radio("Bu harcama gerçekten ZORUNLU bir İhtiyaç mı?", ["Evet, Şart (İhtiyaç)", "Hayır, Keyfi (İstek)"], horizontal=True)
    odeme_tipi = st.radio("Nasıl Ödeyeceksin?", ["Nakit / Banka Kartı", "Kredi Kartı"], horizontal=True)
    
    st.divider()
    c.execute("SELECT id, kart_adi, kart_limit, guncel_borc, hesap_kesim FROM kredi_kartlari")
    kartlar_db = c.fetchall()
    
    t_ay = 1
    secilen_kart_id = None
    
    if odeme_tipi == "Kredi Kartı" and kartlar_db:
        bugun = datetime.now().day
        en_uzun_gun = -1
        en_iyi_kart_id = None
        
        st.info("🧠 **Asistanın Tavsiyesi:**")
        for k_id, k_adi, k_lim, k_borc, k_kesim in kartlar_db:
            if (k_lim - k_borc) >= h_miktar:
                kalan_gun = (k_kesim - bugun) if k_kesim > bugun else (30 - bugun) + k_kesim
                if kalan_gun > en_uzun_gun:
                    en_uzun_gun = kalan_gun
                    en_iyi_kart_id = k_id
        
        if en_iyi_kart_id:
            onerilen_kart_adi = next(k[1] for k in kartlar_db if k[0] == en_iyi_kart_id)
            st.success(f"🎯 Kesinlikle **{onerilen_kart_adi}** ile öde! Hesap kesimine tam **{en_uzun_gun} gün** var.")
        else:
            st.error("Yeterli limiti olan kartın yok!")
    
        kart_secenekleri = {k[0]: k[1] for k in kartlar_db}
        secilen_kart_id = st.selectbox("Hangi Kartı Kullanacaksın?", options=list(kart_secenekleri.keys()), format_func=lambda x: kart_secenekleri[x])
        t_ay = st.number_input("Kaç Taksit?", min_value=1, step=1, max_value=36)
        
    if st.button("Harcamayı Onayla"):
        if h_miktar > 0 and h_kategori != "":
            zaman = datetime.now().strftime("%Y-%m-%d %H:%M")
            ihtiyac_durumu = "İhtiyaç" if "Evet" in h_ihtiyac else "İstek"
            
            if odeme_tipi == "Kredi Kartı" and secilen_kart_id:
                if t_ay > 1:
                    aylik = h_miktar / t_ay
                    c.execute("INSERT INTO taksitler (kart_id, aciklama, aylik_tutar, kalan_ay) VALUES (?, ?, ?, ?)", (secilen_kart_id, f"{h_kategori} ({ihtiyac_durumu})", aylik, t_ay))
                c.execute("UPDATE kredi_kartlari SET guncel_borc = guncel_borc + ? WHERE id = ?", (h_miktar, secilen_kart_id))
                c.execute("INSERT INTO islemler (tip, isim, miktar, tarih, ihtiyac_mi, kategori) VALUES (?, ?, ?, ?, ?, ?)", ('Gider', h_kategori, h_miktar, zaman, ihtiyac_durumu, h_kategori))
            else:
                c.execute("INSERT INTO islemler (tip, isim, miktar, tarih, ihtiyac_mi, kategori) VALUES (?, ?, ?, ?, ?, ?)", ('Gider', h_kategori, h_miktar, zaman, ihtiyac_durumu, h_kategori))
            
            conn.commit()
            st.success("✅ Harcama başarıyla işlendi!")
            time.sleep(1)
            st.rerun()
        else:
            st.warning("Lütfen harcama adını ve tutarını doğru girdiğinden emin ol.")

# --- SEKME 4: TAKVİM ---
with sekme_takvim:
    st.subheader("📅 Ödeme Takvimi ve Taksit Kronolojisi")
    
    c.execute("SELECT t.id, t.aciklama, t.aylik_tutar, t.kalan_ay, k.kart_adi, k.hesap_kesim, k.id FROM taksitler t JOIN kredi_kartlari k ON t.kart_id = k.id WHERE t.kalan_ay > 0")
    taksit_verileri = c.fetchall()
    
    if not taksit_verileri:
        st.info("Gelecek aylara sarkan hiçbir taksitli borcun yok. Süpersin!")
    else:
        bugun = datetime.now()
        takvim_satirlari = []
        for t_id, t_aciklama, t_aylik, t_kalan, k_adi, k_kesim, k_id in taksit_verileri:
            for ay_ileri in range(1, t_kalan + 1):
                hesap_ay = bugun.month + ay_ileri - 1
                ek_yil = hesap_ay // 12
                gercek_ay = (hesap_ay % 12) + 1
                gercek_yil = bugun.year + ek_yil
                siralama = int(f"{gercek_yil}{gercek_ay:02d}{k_kesim:02d}")
                tarih_metni = f"{k_kesim:02d}.{gercek_ay:02d}.{gercek_yil}"
                
                takvim_satirlari.append({"Sıralama": siralama, "Tarih": tarih_metni, "Kart": k_adi, "Açıklama": f"{t_aciklama} ({ay_ileri}. Taksit)", "Aylık Tutar (TL)": t_aylik})
        df_takvim = pd.DataFrame(takvim_satirlari).sort_values(by="Sıralama").drop(columns=["Sıralama"])
        st.dataframe(df_takvim, use_container_width=True, hide_index=True)
        
        st.divider()
        st.error("🗑️ Yanlış Eklenen Taksit Planlarını İptal Et")
        for t_id, t_aciklama, t_aylik, t_kalan, k_adi, k_kesim, k_id in taksit_verileri:
            kol1, kol2, kol3, kol4 = st.columns([4, 3, 3, 1])
            kol1.write(f"🛒 **{t_aciklama}**")
            kol2.write(f"💳 {k_adi}")
            kol3.write(f"Kalan: {t_kalan} Ay ({t_aylik * t_kalan:,.2f} TL)")
            if kol4.button("🗑️", key=f"sil_taksit_{t_id}"):
                dusulecek_tutar = t_aylik * t_kalan
                c.execute("UPDATE kredi_kartlari SET guncel_borc = MAX(0, guncel_borc - ?) WHERE id = ?", (dusulecek_tutar, k_id))
                c.execute("DELETE FROM taksitler WHERE id=?", (t_id,))
                conn.commit()
                st.rerun()
            st.markdown("---")

# --- SEKME 5: YASTIK ALTI & KRİPTO ---
with sekme_yastik:
    st.subheader("💰 Fiziksel Birikimler ve Soğuk Cüzdan")
    y_kol1, y_kol2 = st.columns(2)
    with y_kol1:
        with st.form("yastik_form"):
            yeni_usd = st.number_input("Dolar (USD)", min_value=0.0, step=10.0, value=float(yastik_dict.get('USD', 0)))
            yeni_eur = st.number_input("Euro (EUR)", min_value=0.0, step=10.0, value=float(yastik_dict.get('EUR', 0)))
            yeni_ga = st.number_input("Gram Altın (GA)", min_value=0.0, step=0.5, value=float(yastik_dict.get('GA', 0)))
            yeni_btc = st.number_input("Bitcoin (BTC)", min_value=0.0, step=0.001, format="%.6f", value=float(yastik_dict.get('BTC', 0)))
            yeni_eth = st.number_input("Ethereum (ETH)", min_value=0.0, step=0.01, format="%.6f", value=float(yastik_dict.get('ETH', 0)))
            if st.form_submit_button("Cüzdanı Kaydet"):
                c.execute("UPDATE yastik_alti SET miktar=? WHERE varlik_tipi='USD'", (yeni_usd,))
                c.execute("UPDATE yastik_alti SET miktar=? WHERE varlik_tipi='EUR'", (yeni_eur,))
                c.execute("UPDATE yastik_alti SET miktar=? WHERE varlik_tipi='GA'", (yeni_ga,))
                c.execute("UPDATE yastik_alti SET miktar=? WHERE varlik_tipi='BTC'", (yeni_btc,))
                c.execute("UPDATE yastik_alti SET miktar=? WHERE varlik_tipi='ETH'", (yeni_eth,))
                conn.commit()
                st.success("✅ Tüm varlıklar güncellendi!")
                time.sleep(1)
                st.rerun()
                
    with y_kol2:
        st.info(f"💵 **{yastik_dict.get('USD', 0):.2f} USD** = {yastik_usd_tl:,.2f} TL")
        st.info(f"💶 **{yastik_dict.get('EUR', 0):.2f} EUR** = {yastik_eur_tl:,.2f} TL")
        st.warning(f"🥇 **{yastik_dict.get('GA', 0):.2f} Altın** = {yastik_ga_tl:,.2f} TL")
        st.success(f"₿ **{yastik_dict.get('BTC', 0):.6f} BTC** = {yastik_btc_tl:,.2f} TL")
        st.success(f"⟠ **{yastik_dict.get('ETH', 0):.6f} ETH** = {yastik_eth_tl:,.2f} TL")

# --- SEKME 6: KARTLAR ---
with sekme_kart:
    st.subheader("💳 Kredi Kartı Yönetimi")
    kk_kol1, kk_kol2 = st.columns(2)
    with kk_kol1:
        with st.form("yeni_kart_formu", clear_on_submit=True):
            k_isim = st.text_input("Kart Adı")
            k_limit = st.number_input("Kart Limiti (TL)", min_value=0.0, step=1000.0)
            k_kesim = st.number_input("Hesap Kesim Günü", min_value=1, max_value=31, value=15, step=1)
            if st.form_submit_button("Kartı Tanımla") and k_isim:
                c.execute("INSERT INTO kredi_kartlari (kart_adi, kart_limit, guncel_borc, hesap_kesim) VALUES (?, ?, ?, ?)", (k_isim, k_limit, 0.0, k_kesim))
                conn.commit()
                st.rerun()

    with kk_kol2:
        c.execute("SELECT id, kart_adi, kart_limit, guncel_borc, hesap_kesim FROM kredi_kartlari ORDER BY id DESC")
        kartlar_liste = c.fetchall()
        if not kartlar_liste:
            st.info("Henüz eklenmiş bir kartın yok.")
        else:
            for k_id, k_adi, k_limit, k_borc, k_kesim in kartlar_liste:
                kol_k1, kol_k2, kol_k3, kol_k4, kol_k5 = st.columns([3, 2, 2, 2, 1])
                kol_k1.write(f"**{k_adi}**")
                kol_k2.write(f"Limit: {k_limit:,.0f}")
                kol_k3.write(f"Borç: {k_borc:,.0f}")
                kol_k4.write(f"Kesim: {k_kesim}")
                if kol_k5.button("🗑️", key=f"sil_kart_{k_id}"):
                    c.execute("DELETE FROM kredi_kartlari WHERE id=?", (k_id,))
                    c.execute("DELETE FROM taksitler WHERE kart_id=?", (k_id,))
                    conn.commit()
                    st.rerun()
                st.markdown("---")

# --- SEKME 7: GEÇMİŞ ---
with sekme_gecmis:
    st.subheader("📝 Tüm İşlem Geçmişi (Son 50 Kayıt)")
    c.execute("SELECT id, tip, kategori, isim, miktar, tarih FROM islemler ORDER BY id DESC LIMIT 50")
    islemler = c.fetchall()
    if not islemler:
        st.info("Henüz işlem kaydı yok.")
    else:
        b_kol1, b_kol2, b_kol3, b_kol4, b_kol5, b_kol6 = st.columns([1.5, 1, 1.5, 3, 1.5, 1])
        b_kol1.write("**Tarih**")
        b_kol2.write("**Tür**")
        b_kol3.write("**Kategori**")
        b_kol4.write("**Açıklama**")
        b_kol5.write("**Tutar (TL)**")
        b_kol6.write("**Sil**")
        st.divider()
        for islem in islemler:
            i_id, i_tip, i_kat, i_isim, i_mik, i_tarih = islem
            kol1, kol2, kol3, kol4, kol5, kol6 = st.columns([1.5, 1, 1.5, 3, 1.5, 1])
            kol1.write(f"🕒 {i_tarih[:10]}")
            if i_tip == "Gelir": kol2.markdown("🟢 **Gelir**")
            else: kol2.markdown("🔴 **Gider**")
            kol3.write(f"📁 {i_kat}")
            kol4.write(f"📝 {i_isim}")
            kol5.write(f"**{i_mik:,.2f} TL**")
            if kol6.button("🗑️", key=f"sil_{i_id}"):
                c.execute("DELETE FROM islemler WHERE id=?", (i_id,))
                conn.commit()
                st.rerun()
            st.markdown("---")

# --- SEKME 8: TÜCCAR ---
with sekme_tuccar:
    st.subheader("🐺 Kurt Tüccar (Al-Sat Envanteri)")
    with st.form("tic_form", clear_on_submit=True):
        urun = st.text_input("Ürün")
        alis = st.number_input("Alış Fiyatı", step=100.0)
        satis = st.number_input("Hedef Satış", step=100.0)
        if st.form_submit_button("Ekle") and urun:
            c.execute("INSERT INTO ticaret (urun_adi, alis_fiyati, tahmini_satis) VALUES (?, ?, ?)", (urun, alis, satis))
            conn.commit()
            st.rerun()
    c.execute("SELECT id, urun_adi, alis_fiyati, tahmini_satis FROM ticaret ORDER BY id DESC")
    tic_kayitlar = c.fetchall()
    if tic_kayitlar:
        st.divider()
        for t_id, t_urun, t_alis, t_satis in tic_kayitlar:
            t_kar = t_satis - t_alis
            tkol1, tkol2, tkol3, tkol4, tkol5 = st.columns([3, 2, 2, 2, 1])
            tkol1.write(f"🛒 **{t_urun}**")
            tkol2.write(f"Alış: {t_alis:,.2f} TL")
            tkol3.write(f"Satış: {t_satis:,.2f} TL")
            tkol4.success(f"Kâr: {t_kar:,.2f} TL")
            if tkol5.button("🗑️", key=f"sil_tic_{t_id}"):
                c.execute("DELETE FROM ticaret WHERE id=?", (t_id,))
                conn.commit()
                st.rerun()
            st.markdown("---")

# --- SEKME 9: HEDEFLER ---
with sekme_hedef:
    st.subheader("🎯 Tasarruf Hedefleri")
    with st.form("hedef_formu", clear_on_submit=True):
        hedef_ad = st.text_input("Hedefin (Örn: Yeni Parça)")
        hedef_tutari = st.number_input("Hedeflenen Tutar (TL)", min_value=0.0, step=1000.0)
        hedef_biriken = st.number_input("Şu An Elindeki (TL)", min_value=0.0, step=100.0)
        if st.form_submit_button("Hedef Oluştur") and hedef_ad:
            c.execute("INSERT INTO hedefler (hedef_adi, hedef_tutar, biriken) VALUES (?, ?, ?)", (hedef_ad, hedef_tutari, hedef_biriken))
            conn.commit()
            st.rerun()

    df_hedefler = pd.read_sql_query("SELECT id, hedef_adi as 'Hedef Adı', hedef_tutar as 'Hedef', biriken as 'Biriken' FROM hedefler ORDER BY id DESC", conn)
    
    if not df_hedefler.empty:
        st.divider()
        st.write("📈 **Hedef İlerleme Grafiği:**")
        df_hedefler["Kalan"] = df_hedefler["Hedef"] - df_hedefler["Biriken"]
        fig_hedefler = px.bar(df_hedefler, 
                              y="Hedef Adı", 
                              x=["Biriken", "Kalan"], 
                              title=None,
                              barmode='stack', 
                              orientation='h',
                              color_discrete_map={'Biriken':'#10b981', 'Kalan':'#334155'}) 
        
        fig_hedefler.update_layout(xaxis_title="Tutar (TL)", yaxis_title="Hedef Adı", showlegend=False)
        st.plotly_chart(fig_hedefler, use_container_width=True)

    c.execute("SELECT id, hedef_adi, hedef_tutar, biriken FROM hedefler ORDER BY id DESC")
    goals = c.fetchall()
    
    if goals:
        st.divider()
        for h_id, h_adi, h_tutar, h_biriken in goals:
            hkol1, hkol2, hkol3 = st.columns([6, 3, 1])
            with hkol1:
                st.markdown(f"**🎯 {h_adi}** - ({h_biriken:,.0f} / {h_tutar:,.0f} TL)")
                percentage = min(h_biriken / h_tutar if h_tutar > 0 else 0, 1.0) * 100
                st.write(f"Tamamlanan: **%{percentage:.1f}**")
            with hkol2:
                 st.progress(min(h_biriken / h_tutar if h_tutar > 0 else 0, 1.0))
            
            if hkol3.button("🗑️", key=f"sil_hedef_{h_id}"):
                c.execute("DELETE FROM hedefler WHERE id=?", (h_id,))
                conn.commit()
                st.rerun()
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
    
    # 1. TAHMİN MOTORU (MEVCUT GRAFİK)
    c.execute("SELECT kategori, SUM(miktar) FROM islemler WHERE tip='Gider' AND tarih LIKE ? GROUP BY kategori", (f"{mevcut_ay}%",))
    bu_ay_giderler = dict(c.fetchall())
    
    if not bu_ay_giderler:
        st.info("Bu ay henüz bir harcama girmedin. Harcama yaptıkça sana ay sonu tahminleri üreteceğim.")
    else:
        st.write(f"Bugün ayın **{bugun_gun}.** günü. Şu anki harcama hızına göre ay sonu (30 gün) tahminleri:")
        tahmin_datalari = []
        for kat, miktar in bu_ay_giderler.items():
            if kat == "Maaş/Gelir" or kat == "Diğer": continue
            gunluk_hiz = miktar / bugun_gun
            ay_sonu_tahmin = gunluk_hiz * 30
            tahmin_datalari.append({"Kategori": kat, "Şu Anki Harcama": miktar, "Ay Sonu Tahmini": ay_sonu_tahmin})
            if ay_sonu_tahmin > miktar * 1.5: 
                st.warning(f"🚨 **{kat}** kategorisinde frene bas! Şu an {miktar:,.0f} TL harcadın, bu gidişle ay sonu **{ay_sonu_tahmin:,.0f} TL**'yi bulacak!")
        
        if tahmin_datalari:
            df_tahmin = pd.DataFrame(tahmin_datalari)
            fig_bar = px.bar(df_tahmin, x="Kategori", y=["Şu Anki Harcama", "Ay Sonu Tahmini"], barmode="group", 
                             color_discrete_sequence=['#3498db', '#e74c3c'], title="Mevcut Durum vs Ay Sonu Beklentisi")
            st.plotly_chart(fig_bar, use_container_width=True)

    st.divider()
    
    # 2. YAPAY ZEKA FİNANSAL ANALİZ KISMI
    st.subheader("💡 Yapay Zeka Finansal Analizlerin")

    if net_nakit > 0:
        st.success(f"📈 **Nakit Kraldır:** Kanka gelirlerin giderlerini tokatlamış, kasada {net_nakit:,.2f} TL fazlan var. Bu parayı boşta bekletme, hedeflerine veya yastık altına at!")
    elif net_nakit < 0:
        st.error(f"📉 **Acil Durum Freni:** Kanka kırmızı alarm! Bu ay içeri girmişiz, giderler geliri {-net_nakit:,.2f} TL aşmış. Gereksiz abonelikleri ve keyfi harcamaları acil kesiyoruz.")

    if toplam_limit > 0 and toplam_kk_borc == 0:
        st.success("👑 **Bankaların Düşmanı:** Kredi kartı borcun SIFIR! Finansal özgürlüğün zirvesindesin, borçsuz hayatın tadını çıkar kanka.")
    elif toplam_limit > 0:
        doluluk = (toplam_kk_borc / toplam_limit) * 100
        if doluluk > 50:
            st.warning(f"💳 **Plastik Kelepçe:** Kredi kartı doluluk oranın %{doluluk:.1f} olmuş. Kırmızı çizgiye yaklaşıyorsun, bir süre kartı unutup nakitle yaşama vakti.")
        else:
            st.info(f"💳 **Dengeli Kart:** Limit doluluk oranın %{doluluk:.1f}. Kredi notun için mükemmel bir seviye, böyle devam.")

    kripto_toplam = yastik_btc_tl + yastik_eth_tl
    if kripto_toplam > 5000:
        st.success(f"🐋 **Kripto Balinası:** Cüzdan sağlam şişmiş kanka ({kripto_toplam:,.2f} TL). Elon Musk mısın mübarek? Ama piyasa serttir, kâr realizasyonu yapmayı unutma.")

    if yastik_ga_tl > 5000:
        st.warning(f"🥇 **Güvenli Liman Ustası:** Yastık altı altınlarla parlıyor kanka ({yastik_ga_tl:,.2f} TL). Enflasyon kopsa, kriz çıksa sana işlemez!")

    c.execute("SELECT SUM(tahmini_satis - alis_fiyati) FROM ticaret")
    beklenen_kar = c.fetchone()[0] or 0.0
    if beklenen_kar > 0:
        st.info(f"🐺 **Kurt Tüccar Vizyonu:** Al-sat işlemlerinden beklediğin net kâr {beklenen_kar:,.2f} TL. Bu ticaret zekasıyla yakında holding kurarsın kanka!")

    c.execute("SELECT COUNT(*) FROM hedefler WHERE biriken >= hedef_tutar AND hedef_tutar > 0")
    tamamlanan = c.fetchone()[0] or 0
    if tamamlanan > 0:
        st.success(f"🎯 **Hedef Avcısı:** Helal olsun kanka! Koyduğun hedeflerden tam {tamamlanan} tanesini %100 bitirmişsin. Başarı hissinin tadını çıkar!")

    c.execute("SELECT SUM(miktar) FROM islemler WHERE tip='Gider' AND ihtiyac_mi='İstek'")
    keyfi_toplam = c.fetchone()[0] or 0.0
    if keyfi_toplam > 0:
        st.warning(f"🎮 **İstek vs İhtiyaç:** Bu ara 'Keyfi' harcamalara biraz fazla dalmışsın kanka ({keyfi_toplam:,.2f} TL). O parayı al-sat sermayesine eklesek daha iyi olmaz mıydı?")

    if net_nakit > 10000 and toplam_yastik_tl < 1000:
        st.error("🔥 **Enflasyon Ateşi:** Kanka elinde 10.000 TL'den fazla nakit tutuyorsun ama yastık altı (döviz/altın) bomboş! Enflasyon canavarı paranı eritmeden o nakiti yatırıma çevir.")

    with sekme_borclar:
    
    # 1. BORÇ EKLEME FORMU
     with st.expander("➕ Yeni Borç/Yükümlülük Ekle", expanded=True):
        with st.form("borc_ekle_formu"):
            b_adi = st.text_input("Borç Veren Kişi / Açıklama")
            b_miktar = st.number_input("Toplam Borç Tutarı (TL)", min_value=0.0, step=100.0)
            b_odenen = st.number_input("Şu ana kadar ödenen (TL)", min_value=0.0, step=100.0)
            
            if st.form_submit_button("Borcu Sisteme Kaydet"):
                if b_adi != "" and b_miktar > 0:
                    zaman = datetime.now().strftime("%Y-%m-%d")
                    c.execute("INSERT INTO manuel_borclar (borc_adi, toplam_miktar, odenen, tarih) VALUES (?, ?, ?, ?)", 
                             (b_adi, b_miktar, b_odenen, zaman))
                    conn.commit()
                    st.success(f"✅ {b_adi} borcu kaydedildi!")
                    time.sleep(1)
                    st.rerun()
                else:
                    st.error("Lütfen bir isim ve tutar gir!")

    st.divider()

    # 2. MEVCUT BORÇLARI LİSTELEME
    st.write("### Mevcut Borç Listen")
    df_borclar = pd.read_sql_query("SELECT borc_adi as 'Açıklama', toplam_miktar as 'Toplam', odenen as 'Ödenen', (toplam_miktar - odenen) as 'Kalan Borç' FROM manuel_borclar", conn)
    
    if not df_borclar.empty:
        st.dataframe(df_borclar, use_container_width=True, hide_index=True)
        
        # 3. BORÇ ÖDEME VE SİLME PANELİ
        st.write("---")
        col1, col2 = st.columns(2)
        
        with col1:
            secilen = st.selectbox("İşlem Yapılacak Borç", df_borclar['Açıklama'].tolist())
            odeme_tutari = st.number_input("Ödenen Miktarı Güncelle (TL)", min_value=0.0, step=50.0)
            if st.button("Ödemeyi Kaydet"):
                c.execute("UPDATE manuel_borclar SET odenen = odenen + ? WHERE borc_adi = ?", (odeme_tutari, secilen))
                conn.commit()
                st.success("Ödeme güncellendi!")
                st.rerun()
                
        with col2:
            st.write("Tehlikeli Bölge")
            if st.button("Seçili Borcu Tamamen Sil", type="primary"):
                c.execute("DELETE FROM manuel_borclar WHERE borc_adi = ?", (secilen,))
                conn.commit()
                st.warning("Borç kaydı silindi.")
                st.rerun()
    else:
        st.info("Henüz kaydedilmiş bir elden borç bulunmuyor.")

        # --- BORÇLAR SEKMESİ İÇERİĞİ ---
with sekme_borclar:
    st.subheader("🤝 Elden / Eski Borç Takibi")
    
    # Yeni Borç Ekleme
    with st.expander("➕ Yeni Borç Ekle", expanded=True):
        with st.form("borc_ekleme_yeni"):
            b_adi = st.text_input("Kime Borcun Var?")
            b_tutar = st.number_input("Toplam Borç (TL)", min_value=0.0)
            b_baslangic_odeme = st.number_input("Ödenen Kısım (TL)", min_value=0.0)
            
            if st.form_submit_button("Borcu Kaydet"):
                if b_adi and b_tutar > 0:
                    tarih = datetime.now().strftime("%Y-%m-%d")
                    c.execute("INSERT INTO manuel_borclar (borc_adi, toplam_miktar, odenen, tarih) VALUES (?, ?, ?, ?)", 
                             (b_adi, b_tutar, b_baslangic_odeme, tarih))
                    conn.commit()
                    st.success("Borç eklendi!")
                    st.rerun()
                else:
                    st.error("İsim ve tutar girmelisin!")

    st.divider()

    # Borçları Tablo Halinde Göster
    df_borc_listesi = pd.read_sql_query("SELECT id, borc_adi as 'Borçlu Olunan', toplam_miktar as 'Toplam', odenen as 'Ödenen', (toplam_miktar - odenen) as 'Kalan' FROM manuel_borclar", conn)
    
    if not df_borc_listesi.empty:
        st.dataframe(df_borc_listesi.drop(columns=['id']), use_container_width=True, hide_index=True)
        
        # Güncelleme Alanı
        col1, col2 = st.columns(2)
        with col1:
            secilen_isim = st.selectbox("İşlem Yapılacak Borç", df_borc_listesi['Borçlu Olunan'].tolist())
            ek_odeme = st.number_input("Ödeme Yap (TL)", min_value=0.0)
            if st.button("Ödemeyi Sisteme İşle"):
                c.execute("UPDATE manuel_borclar SET odenen = odenen + ? WHERE borc_adi = ?", (ek_odeme, secilen_isim))
                conn.commit()
                st.rerun()
        with col2:
            st.write("Yönetim")
            if st.button("Borcu Kapat ve Sil"):
                c.execute("DELETE FROM manuel_borclar WHERE borc_adi = ?", (secilen_isim,))
                conn.commit()
                st.rerun()
    else:
        st.info("Kayıtlı borç bulunamadı.") 
