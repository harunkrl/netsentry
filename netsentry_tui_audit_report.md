# 🛡️ NetSentry TUI — Kapsamlı UI/UX Denetim Raporu

> **Proje**: NetSentry v0.4.0  
> **Framework**: Textual (Python TUI)  
> **Tarih**: 2026-06-06  
> **Kapsam**: Tüm TUI ekranları, widget'lar, stil dosyaları ve veri katmanı  

---

## 📋 Yönetici Özeti

NetSentry, ağ bağlantılarını izleyen, coğrafi harita üzerinde görselleştiren ve güvenlik uyarıları üreten bir TUI (Terminal User Interface) uygulamasıdır. Mevcut haliyle temel işlevsellik çalışmaktadır, ancak **ciddi UI/UX sorunları** kullanıcı deneyimini olumsuz etkiliyor. Bu rapor 3 ekran görüntüsü ve tam kaynak kod analizine dayanarak **60+ ayrı bulgu** tespit etmiştir.

### Bulgu Dağılımı

| Öncelik | Sayı | Açıklama |
|---------|------|----------|
| 🔴 Kritik | 12 | Kullanılabilirliği doğrudan engelleyen / crash riski |
| 🟠 Yüksek | 16 | Deneyimi ciddi şekilde bozan |
| 🟡 Orta | 18 | İyileştirilmesi gereken |
| 🟢 Düşük | 10 | Cila/polish seviyesinde |
| 💡 Öneri | 5 | Yeni özellik fırsatları |

---

## 🔴 KRİTİK BULGULAR

### K1. Port Tablosu Her Yenilemede Tamamen Yeniden Oluşturuluyor

**Dosya**: [port_table.py](file:///home/lenovo/Projects/NetSentry/tui/widgets/port_table.py)  
**Sorun**: `update_data()` metodu her 2 saniyede `clear()` + tüm satırları yeniden ekliyor. Bu:
- 📍 Scroll pozisyonunu sıfırlıyor
- 📍 Seçili satırı kaybettiriyor
- 📍 Görsel titreme (flickering) yaratıyor
- 📍 Kullanıcının tabloyla etkileşimini sürekli kesiyor

**Çözüm**: Diff-based güncelleme: Mevcut satırları karşılaştır, sadece değişenleri güncelle, yenileri ekle, kalkanları sil.

---

### K2. Settings Ekranında Metin Kesilmesi (Text Truncation)

**Dosya**: [settings_screen.py](file:///home/lenovo/Projects/NetSentry/tui/screens/settings_screen.py)  
**Sorun**: Ekran görüntüsünde açıkça görünüyor:
- "Show desktop notifications for **daemo**" → "daemon" kelimesi kesilmiş
- "Show pop-up notifications inside the" → cümle yarıda kesilmiş

**Çözüm**: Label'lar için `width: 1fr` ve `text-overflow: ellipsis` yerine `min-width` + scroll veya çok satırlı metin desteği.

---

### K3. Bağlantı Detay Ekranı Raw Dict Gösteriyor

**Dosya**: [detail_screen.py](file:///home/lenovo/Projects/NetSentry/tui/screens/detail_screen.py)  
**Sorun**: `Pretty(connection)` kullanarak Python dict'ini ham olarak gösteriyor. Bu bir debug görünümü, son kullanıcı arayüzü değil.

**Çözüm**: Yapılandırılmış key-value tablosu ile gösterim (Process, PID, Protocol, Local/Remote Address, State, Alert Level, Risk Score, Geo Info vb.).

---

### K4. IPv6 Adresleri Agresif Şekilde Kesiliyor

**Dosya**: [port_table.py](file:///home/lenovo/Projects/NetSentry/tui/widgets/port_table.py), [main_screen.py](file:///home/lenovo/Projects/NetSentry/tui/screens/main_screen.py)  
**Sorun**: `_format_port()` ve `_truncate()` IPv6 adreslerini max 24 karaktere kesiyor. `2a02:e00:ae00:b000:a4af:fd26:fa87:82fc:52096` gibi adresler `2a02:e00:ae00:b000:a4a...` olarak gösteriliyor.

**Çözüm**: 
- IPv6 için kısaltma algoritması (`::` notasyonu)
- Kolon üzerinde hover/expand desteği
- Tooltips veya detail panel

---

### K5. Connection Log Bellek Sızıntısı

**Dosya**: [connection_log.py](file:///home/lenovo/Projects/NetSentry/tui/widgets/connection_log.py)  
**Sorun**: `_seen` set'i sınırsız büyüyor, `RichLog` buffer'ı sınırsız. Uzun süreli kullanımda bellek tüketimi sürekli artar.

**Çözüm**: `_seen` için LRU/max-size, `RichLog` için `max_lines` parametresi.

---

### K6. Synchronous Socket I/O UI'ı Donduruyor

**Dosya**: [provider.py](file:///home/lenovo/Projects/NetSentry/tui/data/provider.py)  
**Sorun**: `refresh()` metodu senkron soket I/O yapıyor. Daemon yavaş yanıt verirse veya bağlantı koparsa UI tamamen donar.

**Çözüm**: `asyncio` tabanlı asenkron iletişim veya `run_in_thread()` ile background thread.

---

### K7. Daemon Bağlantı Hatası İçin UI Yok

**Dosya**: Tüm ekranlar  
**Sorun**: Daemon çalışmıyorsa veya bağlantı koparsa, kullanıcıya hiçbir bilgi verilmiyor. Ekranlar sadece boş kalıyor.

**Çözüm**: 
- Bağlantı durumu göstergesi (status bar'da)
- Yeniden bağlanma denemesi + spinner
- Hata durumu ekranı ("Daemon bağlantısı kurulamadı. Çalıştırmak için: sudo systemctl start netsentry")

---

### K8. Kill İşlemi İçin PermissionError Yakalanmıyor

**Dosya**: [kill_confirm.py](file:///home/lenovo/Projects/NetSentry/tui/screens/kill_confirm.py)  
**Sorun**: `os.kill()` doğrudan çağrılıyor. Root olmayan kullanıcı sistem processleri öldürmeye çalışırsa `PermissionError` fırlatılır ama yakalanmaz.

**Çözüm**: try/except ile hata yakalama, kullanıcıya "Yetki gerekiyor" mesajı, opsiyonel `pkexec` ile yetki yükseltme.

---

### K9. Settings "Restart Daemon" 15 Saniye TUI'ı Donduruyor

**Dosya**: [settings_screen.py](file:///home/lenovo/Projects/NetSentry/tui/screens/settings_screen.py)  
**Sorun**: `_restart_daemon()` metodu `subprocess.run(timeout=15)` ile senkron çalışıyor. Bu süre boyunca TUI tamamen donar — kullanıcı hiçbir etkileşimde bulunamaz.

**Çözüm**: `@work(thread=True)` ile async worker'da çalıştır. Restart sırasında spinner/loading göster.

---

### K10. CSS Class İsim Uyumsuzluğu — Widget Gizleme Kırık

**Dosyalar**: [styles.tcss](file:///home/lenovo/Projects/NetSentry/tui/styles.tcss), [main_screen.py](file:///home/lenovo/Projects/NetSentry/tui/screens/main_screen.py), [process_tree_screen.py](file:///home/lenovo/Projects/NetSentry/tui/screens/process_tree_screen.py), [connection_map_screen.py](file:///home/lenovo/Projects/NetSentry/tui/screens/connection_map_screen.py)  
**Sorun**: Üç farklı CSS class adı kullanılıyor:
- `styles.tcss` → `.hidden { display: none; }`
- `main_screen.py` → `.is-hidden` (farklı isim!)
- `connection_map_screen.py` → `.map-hidden`
- `process_tree_screen.py` → `.hidden`

Bu tutarsızlık bazı ekranlarda widget gizleme/gösterme işlemlerinin çalışmamasına neden olabilir.

**Çözüm**: Tek bir standart class adı belirle (`.hidden`) ve tüm ekranlarda tutarlı kullan.

---

### K11. kill_process() 2 Saniyelik Blocking Sleep

**Dosya**: [provider.py](file:///home/lenovo/Projects/NetSentry/tui/data/provider.py)  
**Sorun**: `kill_process()` metodu `time.sleep(0.1)` × 20 iterasyon = 2 saniye boyunca TUI thread'ini blokluyor. Bu süre zarfında arayüz donar.

**Çözüm**: Kill işlemini `@work(thread=True)` ile background thread'de çalıştır.

---

### K12. Kill Confirm'de Escape Binding Yok

**Dosya**: [kill_confirm.py](file:///home/lenovo/Projects/NetSentry/tui/screens/kill_confirm.py)  
**Sorun**: Modal'ı kapatmak için Escape tuşu bağlı değil. Kullanıcı Cancel butonuna Tab ile geçmek zorunda. Standart UX beklentisine aykırı.

**Çözüm**: `Binding("escape", "cancel")` ekle.

---

## 🟠 YÜKSEK ÖNCELİKLİ BULGULAR

### Y1. Settings Modalı — Aşırı Boş Alan ve Kaba Kenarlık

**Ekran**: Settings (Ekran Görüntüsü #3)  
**Sorun**: 
- Modal `max-height: 30` ama sadece 2 ayar var → devasa boş alan
- Parlak cyan `tall` border aşırı dikkat çekici ve gözü yoruyor
- "Restart Daemon" butonunun sarı arka planı tema ile uyumsuz

**Çözüm**: 
- Auto-height modal
- Daha incelikli border (`round` veya `solid` daha az agresif renkle)
- Buton stilini tema ile uyumlu hale getirme

---

### Y2. Ana Ekran Panel Oranları Dengesiz

**Ekran**: Ana Dashboard (Ekran Görüntüsü #1)  
**Sorun**: Port tablosu ve connection log her ikisi `1fr` alıyor, ancak port tablosu az veriyle bile ekranın yarısını kaplıyor.

**Çözüm**: 
- Port tablosu: `auto` veya `min-height + max-height` ile içeriğe göre boyutlandırma
- Connection log: Kalan alanı doldursun (`1fr`)
- Veya kullanıcının sürükleyerek ayarlayabileceği bir splitter

---

### Y3. Aktif Ekran Göstergesi Yok

**Sorun**: Kullanıcı hangi ekranda olduğunu anlayamıyor. Header sadece "NetSentry — Network Security Analyzer" gösteriyor. Kısayol tuşları (m, t, s) hangi ekranın aktif olduğunu belirtmiyor.

**Çözüm**: 
- Header'da breadcrumb veya tab indicator
- Status bar'daki kısayollarda aktif ekranı highlight etme
- Header subtitle'da ekran adı gösterme

---

### Y4. Search ve Filter Aynı Input Widget'ını Paylaşıyor

**Dosya**: [main_screen.py](file:///home/lenovo/Projects/NetSentry/tui/screens/main_screen.py)  
**Sorun**: `/` (search) ve `f` (filter) aynı Input widget'ını kullanıyor. Aynı anda ikisi aktif olamıyor.

**Çözüm**: Ayrı Input widget'ları veya tek bir birleşik search/filter bar'ı (mode toggle ile).

---

### Y5. Filtre Aktif Olduğunda Görsel İpucu Yok

**Dosya**: [main_screen.py](file:///home/lenovo/Projects/NetSentry/tui/screens/main_screen.py)  
**Sorun**: Veri filtrelendiğinde kullanıcı bunu fark edemiyor. Tablo normal görünüyor ama eksik veriler var.

**Çözüm**: 
- Status bar'da "Filtered: X of Y connections" göstergesi
- Filtre chip/badge'i (tıklanarak kaldırılabilir)
- Tablo başlığında filtre ikonu

---

### Y6. Connection Map'te Sıralama Göstergesi Yok

**Dosya**: [connection_map_screen.py](file:///home/lenovo/Projects/NetSentry/tui/screens/connection_map_screen.py)  
**Sorun**: `s` tuşu ile sıralama değişiyor ama hangi kolona göre sıralandığı ve yönü gösterilmiyor.

**Çözüm**: Aktif sort kolonu header'ında ▲/▼ göstergesi.

---

### Y7. Harita Ölçeklenmiyor

**Dosya**: [connection_map_screen.py](file:///home/lenovo/Projects/NetSentry/tui/screens/connection_map_screen.py)  
**Sorun**: ASCII harita sabit 79×39 boyutunda. Geniş terminallerde küçük ve boş görünüyor.

**Çözüm**: Terminal genişliğine göre harita ölçekleme veya harita alanını center-align yapma.

---

### Y8. Empty State Yok (Hiçbir Ekranda)

**Tüm ekranlar**  
**Sorun**: Bağlantı yokken tablo boş, harita boş, ağaç boş — hiçbir açıklayıcı mesaj yok.

**Çözüm**: Her widget için empty state: ikon + açıklayıcı metin ("No active connections", "Waiting for data..." vb.).

---

### Y9. Status Bar Kısayol Tuşları Okunamıyor

**Ekran**: Ana Dashboard (Ekran Görüntüsü #1)  
**Sorun**: `q Quit k Kill r Refresh t Procs m Map s Settings / Search f Filter e Export c Copy ? Help ^p palette` — tüm kısayollar tek satırda, minimal ayrımla.

**Çözüm**: 
- Tuşları gruplandırma (|  ayracı ile)
- Tuş harflerini highlight etme (bold/farklı renk)
- Veya iki satırlı düzen: üst satırda eylemler, alt satırda navigasyon

---

### Y10. Pyperclip Sessizce Başarısız Olabiliyor

**Dosya**: [main_screen.py](file:///home/lenovo/Projects/NetSentry/tui/screens/main_screen.py)  
**Sorun**: `pyperclip.copy()` Wayland, SSH, headless ortamlarda sessizce başarısız olur.

**Çözüm**: Try/except + hata bildirim toast'u. Alternatif: `xclip`, `xsel`, `wl-copy` fallback'leri.

---

### Y11. Kill Confirm Ekranında Raw Dict Görünümü

**Dosya**: [kill_confirm.py](file:///home/lenovo/Projects/NetSentry/tui/screens/kill_confirm.py)  
**Sorun**: Kapatılacak bağlantılar `Pretty` ile raw dict olarak gösteriliyor.

**Çözüm**: Yapılandırılmış tablo formatı.

---

### Y12. Help Ekranı Key Binding'leri Duplike Ediyor

**Dosya**: [help_screen.py](file:///home/lenovo/Projects/NetSentry/tui/screens/help_screen.py)  
**Sorun**: Kısayollar hem kod'da (`Binding`) hem help text'te hardcoded. Biri değiştiğinde diğeri güncellenmez.

**Çözüm**: Help text'i binding tanımlarından otomatik üretme.

---

## 🟡 ORTA ÖNCELİKLİ BULGULAR

### O1. Renk Tutarsızlıkları
Alert level renkleri 3 farklı yerde tanımlı: `constants.py` (ANSI), widget kodları (Rich markup), `styles.tcss` (CSS). Bunlar birbirinden sapabilir.

### O2. Light Mode Desteği Yok
`watch_dark()` metodu var ama sadece dark mode renkleri tanımlı. Light mode hiçbir zaman çalışmaz.

### O3. Export Yolu ve Formatı Sabit
Her zaman `~/netsentry_export_{timestamp}.json`. Kullanıcı yol veya format (CSV, JSON, PCAP) seçemiyor.

### O4. Process Tree'den Kill Yapılamıyor
Process tree PID gösteriyor ama kill işlevi sunmuyor. Doğal bir beklenti olmasına rağmen eksik.

### O5. Connection Map Filter Kırık
`_apply_filter()` var olmayan `FilterScreen`'i çağırıyor.

### O6. GeoIP Verisi Yokken Null Island'a İşaret
Koordinat bulunamayan bağlantılar (0,0)'a yerleştirilip Atlantik Okyanusu'nda gösteriliyor.

### O7. Process Tree Her Yenilemede Yeniden Oluşturuluyor
Expand/collapse durumu kayboluyor.

### O8. Sıralama Alert Level İçin Fragile
Manuel priority dict kullanıyor. Yeni alert level eklenirse kırılır.

### O9. Connection Log Auto-Scroll Davranışı
Kullanıcı yukarı scroll yapıp eski logları incelerken yeni veri gelince otomatik en alta atlıyor.

### O10. Status Bar'da Interface IP Adresi Yok
Sadece "wlan0" gibi interface adı gösteriliyor, IP adresi yok.

### O11. Config'teki Birçok Ayar TUI'da Gösterilmiyor
`config.py` alert thresholds, scan detection, risk scoring, log levels gibi ~20 ayar içeriyor ama Settings'te sadece 2 toggle var.

### O12. Backend Model'lerde Zengin Veri Var Ama Gösterilmiyor
`risk_score`, `geo_info.org`, `geo_info.asn`, `alert_details` hiçbir yerde gösterilmiyor.

### O13. Restart Daemon İçin Onay Yok
Restart Daemon butonuna basınca doğrudan yeniden başlatılıyor, onay sorulmuyor.

### O14. Traffic Bar Çok Basit
Tek segmentli bir bar. Per-process breakdown, sparkline veya historical trend yok.

### O15. Traffic Bar Birim Etiketi Hatalı
`_human_bytes()` 1024 tabanlı bölme yapıyor ama KB/MB/GB etiketi kullanıyor (doğrusu KiB/MiB/GiB veya 1000 tabanlı bölme).

### O16. Heartbeat Dosya I/O Her Status Güncellemesinde
Status bar her 2 saniyede heartbeat JSON dosyasını diskten okuyor. Dakikada 30 dosya okuma. Cache/TTL mekanizması yok.

### O17. Process Tree'de Auto-Refresh Yok
Veri sadece mount'ta çekiliyor, ekran açık kaldıkça stale kalıyor. Diğer ekranlar 2 saniyede bir yenileniyor.

### O18. Connection Log İlk Çağrıda Filtreleri Bypass Ediyor
`_seen_keys` boşken tüm entry'ler filtre uygulanmadan yazılıyor. Aktif bir filtre varken bile ilk veri filtresiz gösteriliyor.

---

## 🟢 DÜŞÜK ÖNCELİKLİ BULGULAR

### D1. Header'da Versiyon Bilgisi Yok
### D2. Help Text'te Kısayollar Kategorize Edilmemiş
### D3. Detail Screen'de Kopyalama İşlevi Yok
### D4. Table Header'lar Veri Satırlarından Daha Silik
### D5. Block Karakterler (`▓`, `░`) Bazı Terminallerde Sorunlu
### D6. Timestamp Formatı Tutarsız (float vs formatted)
### D7. Connection Map Legend Çok Minimal
### D8. Detail Screen'de Herhangi Bir Tuşa Basınca Kapanıyor
### D9. Help Ekranında Eski/Yanlış Binding Bilgisi
`n: *(removed — use s for settings)*` gibi ölü satırlar var. `Ctrl+F` (log filter cycle) dokümante edilmemiş.
### D10. TCSS'te Tanımlı Ama Kullanılmayan Değişkenler
`$secondary`, `$warning`, `$error` TCSS'te tanımlı ama inline CSS'te kullanılamıyor (Textual inline CSS TCSS değişkenlerini desteklemez).

---

## 💡 YENİ ÖZELLİK ÖNERİLERİ

### Ö1. Sparkline Traffic Graph
Status bar'da veya ayrı bir panelde anlık trafik grafiği (son 60 saniye).

### Ö2. Connection Duration Gösterimi
Bağlantının ne kadar süredir aktif olduğunu gösteren kolon.

### Ö3. DNS Resolution
Remote IP'ler için reverse DNS gösterimi.

### Ö4. Risk Score Görselleştirmesi
Her bağlantı için risk puanını renkli bar veya ikon olarak gösterme.

### Ö5. Theme/Palette Customization
Kullanıcının tema renklerini config'den değiştirebilmesi.

---

## 📊 Ekran Bazlı Görsel Analiz

### Ekran 1: Ana Dashboard

```
┌─────────────────────────────────────────────────────┐
│ ❌ Port tablosu az veriyle fazla yer kaplıyor       │
│ ❌ IPv6 adresleri kesiliyor                         │
│ ❌ Tablo her yenilemede titriyor                    │
│ ⚠️ CmdLine kolonu çoğu zaman kesilmiş             │
│ ⚠️ Alert kolonu bağlam eksik                       │
├─────────────────────────────────────────────────────┤
│ ⚠️ Log satırları çok yoğun                         │
│ ⚠️ Auto-scroll sorunlu                             │
│ ❌ Filtre aktif göstergesi yok                      │
├─────────────────────────────────────────────────────┤
│ ⚠️ Kısayollar sıkışık ve okunamıyor               │
│ ⚠️ Daemon bağlantı durumu yok                     │
└─────────────────────────────────────────────────────┘
```

### Ekran 2: Connection Map

```
┌─────────────────────────────────────────────────────┐
│ ⚠️ Harita sabit boyutlu, ölçeklenmiyor             │
│ ⚠️ Legend minimal                                  │
│ ❌ GeoIP yokken yanlış konum                       │
├─────────────────────────────────────────────────────┤
│ ⚠️ Sıralama göstergesi yok                        │
│ ⚠️ IPv6 tabloda taşıyor                           │
│ ❌ Filter fonksiyonu kırık                          │
└─────────────────────────────────────────────────────┘
```

### Ekran 3: Settings

```
┌─────────────────────────────────────────────────────┐
│ ❌ Metin kesilmesi ("daemo", "inside the")          │
│ ❌ Devasa boş alan                                  │
│ ❌ Aşırı parlak cyan border                        │
│ ⚠️ Sadece 2 ayar (config'te ~20 var)              │
│ ⚠️ Restart onaysız                                 │
│ ⚠️ Buton stili uyumsuz                             │
└─────────────────────────────────────────────────────┘
```

---

## 🎯 Önerilen İyileştirme Sıralaması

### Faz 1: Acil Düzeltmeler (Kritik — 12 madde)
1. Port tablosu diff-based update
2. Settings metin kesilmesi
3. Detail screen yapılandırılmış görünüm
4. IPv6 akıllı kısaltma
5. Connection log bellek sınırı
6. Async data provider
7. Daemon bağlantı hata ekranı
8. Kill işlemi hata yakalama
9. Settings restart blocking düzeltme
10. CSS class isimleri standardizasyonu
11. kill_process() blocking sleep düzeltme
12. Kill confirm escape binding ekleme

### Faz 2: UX İyileştirmeleri (Yüksek — 16 madde)
13. Settings modal boyut ve stil
14. Panel oranları düzeltme
15. Aktif ekran göstergesi
16. Search/filter ayrımı
17. Filtre aktif göstergesi
18. Empty state'ler
19. Status bar okunabilirliği
20. Clipboard hata yakalama
21. Connection log ilk çağrı filtre bypass düzeltme
22. Process tree auto-refresh ekleme
23. Heartbeat dosya I/O cache
24. Connection map toggle harita bug düzeltme
25. Connection map search-dismiss filtre temizleme
26. İki VerticalScroll container birleştirme (settings)
27. DataProvider singleton pattern
28. Key binding `s` çakışması çözümü

### Faz 3: Polish (Orta — 18 madde)
29. Renk sistemi merkezileştirme
30. Export yol/format seçimi
31. Process tree'den kill
32. Config ayarlarını Settings'e ekleme
33. Backend veri alanlarını gösterme
34. Auto-scroll akıllı davranış
35. Traffic bar birim etiketi düzeltme
36. Help ekranı ölü satırlar temizleme
37. TCSS kullanılmayan değişkenler temizliği
38. Connection Map kırık filter düzeltme/kaldırma
39. GeoIP null island düzeltme
40. Process tree expand/collapse state koruma
41. Help screen auto-generate from bindings
42. Connection map sort göstergesi
43. Kill confirm bağlantı listesi formatı
44. Restart daemon onay dialog'u
45. Styles.tcss border refinement
46. Export sonrası bildirim

### Faz 4: Yeni Özellikler (Opsiyonel — 5 madde)
47. Sparkline traffic
48. Connection duration
49. Risk score görseli
50. Theme customization
51. Versiyon bilgisi header'da

---

## 🤖 MASTER PROMPT — Coding Agent İçin

Aşağıdaki prompt'u coding agent'ınıza aynen verebilirsiniz:

---

```
# NetSentry TUI — Kapsamlı UI/UX İyileştirme Görevi

Sen NetSentry projesinin TUI (Terminal User Interface) kısmını iyileştirecek bir coding agent'sın. 
Proje /home/lenovo/Projects/NetSentry dizininde. Python + Textual framework kullanılıyor.

## Proje Yapısı
- tui/netsentry_tui.py → Ana uygulama (Textual App)
- tui/styles.tcss → Global stiller
- tui/screens/ → Ekranlar (main, connection_map, settings, detail, help, kill_confirm, process_tree)
- tui/widgets/ → Widget'lar (port_table, connection_log, status_bar, traffic_bar)
- tui/data/provider.py → Daemon veri sağlayıcı
- shared/config.py → Konfigürasyon
- shared/constants.py → Sabitler ve enum'lar
- backend/models.py → Pydantic veri modelleri

## KRİTİK KURALLAR
1. Mevcut tüm fonksiyonelliği koru — hiçbir özelliği silme veya kırma.
2. Her değişikliği test et — `python -m tui` veya `netsentry-tui` çalıştırarak TUI'ın açıldığını doğrula.
3. Textual framework API'sine uy — https://textual.textualize.io/ dokümantasyonunu referans al.
4. Commit'leri anlamlı grupla — her faz için ayrı commit.

## YAPILACAK İŞLER (Öncelik Sırasına Göre)

### FAZ 1: Kritik Hatalar ve Temel UX (Önce bunları yap)

#### 1.1 Port Tablosu Diff-Based Update
**Dosya**: tui/widgets/port_table.py
- `update_data()` metodu şu anda `clear()` + tüm satırları yeniden ekliyor.
- Bu her 2 saniyede scroll pozisyonunu sıfırlıyor, seçili satırı kaybettiriyor ve görsel titreme yaratıyor.
- ÇÖZÜM: Mevcut satırları connection key'lerine göre karşılaştır (process+pid+local_addr+remote_addr).
  - Değişen satırları yerinde güncelle (`update_cell()`)
  - Yeni bağlantıları ekle (`add_row()`)
  - Kapanan bağlantıları sil (`remove_row()`)
  - Scroll pozisyonunu ve seçimi koru.

#### 1.2 Settings Ekranı Metin Kesilmesi
**Dosya**: tui/screens/settings_screen.py
- Toggle açıklamaları kesilmiş durumda: "Show desktop notifications for daemo" ve "Show pop-up notifications inside the"
- ÇÖZÜM: 
  - Label widget'larına yeterli genişlik ver veya metin sarma (word-wrap) etkinleştir.
  - Container layout'unu düzelt: Horizontal içindeki Label'ın width'ini `1fr` yerine `auto` veya yeterli bir min-width yap.
  - Toggle descriptions'ı tam haliyle göster.

#### 1.3 Detail Screen Yapılandırılmış Görünüm
**Dosya**: tui/screens/detail_screen.py  
- Şu anda `Pretty(connection)` ile raw Python dict gösteriliyor.
- ÇÖZÜM: Yapılandırılmış key-value tablo görünümü oluştur:
  ```
  Process:      chrome
  PID:          12345
  Protocol:     tcp
  Local:        127.0.0.1:8080
  Remote:       142.250.185.46:443
  State:        ESTABLISHED
  Alert:        INFO
  Risk Score:   0.2
  Country:      United States
  City:         Mountain View
  Organization: Google LLC
  ASN:          AS15169
  ```
- Rich Text ile key'leri bold cyan, value'ları white yap.
- Escape ile kapat (herhangi bir tuş değil).
- `c` tuşu ile seçili alanı kopyalama ekle.

#### 1.4 IPv6 Akıllı Kısaltma
**Dosyalar**: tui/widgets/port_table.py, tui/screens/main_screen.py
- IPv6 adreslerini `::` notasyonu ile kısalt (RFC 5952).
- `_format_port()` ve `_truncate()` fonksiyonlarını güncelle.
- Örnek: `2a02:e00:ae00:b000:a4af:fd26:fa87:82fc` → `2a02:e00:ae00:b000::fa87:82fc` (veya uygun kısaltma)
- Port tablosunda Address:Port kolonu için minimum genişlik artır.

#### 1.5 Connection Log Bellek Sınırı
**Dosya**: tui/widgets/connection_log.py
- `_seen` set'ine max boyut ekle (örn: 10000 entry). LRU mantığı ile eski entry'leri temizle.
- `RichLog`'a `max_lines=5000` parametresi ekle.

#### 1.6 Async Data Provider
**Dosya**: tui/data/provider.py
- `refresh()` metodunu Textual'ın `work` decorator'u ile async yap:
  ```python
  @work(thread=True, exclusive=True)
  async def refresh(self):
      ...
  ```
- Veya `run_worker()` kullanarak background thread'de çalıştır.
- Socket timeout ekle (5 saniye).

#### 1.7 Daemon Bağlantı Hata Durumu
**Dosyalar**: tui/data/provider.py, tui/screens/main_screen.py, tui/widgets/status_bar.py
- DataProvider'a `connected: bool` property ekle.
- Bağlantı yokken tüm widget'larda overlay veya banner göster:
  "⚠ Daemon bağlantısı yok. Başlatmak için: sudo systemctl start netsentry"
- Status bar'da bağlantı durumu göstergesi ekle (🟢 connected / 🔴 disconnected).
- Otomatik yeniden bağlanma denemesi (5 saniye aralıkla).

#### 1.8 Kill İşlemi Hata Yakalama
**Dosya**: tui/screens/kill_confirm.py
- `Binding("escape", "cancel")` ekleyerek Escape ile kapatmayı sağla.
- `os.kill()` çağrısını try/except ile sar.
- `PermissionError` → "Bu işlem için yönetici yetkisi gerekiyor" mesajı göster.
- `ProcessLookupError` → "İşlem zaten sonlandırılmış" mesajı göster.
- İşlem sonrası başarı/hata toast notification'ı göster.

#### 1.9 Settings Restart Daemon Blocking Düzeltme
**Dosya**: tui/screens/settings_screen.py
- `_restart_daemon()` metodu `subprocess.run(timeout=15)` ile senkron çalışıyor → TUI 15 saniye donuyor.
- ÇÖZÜM: `@work(thread=True)` ile async worker'da çalıştır.
- Restart sırasında buton textini "Restarting..." yap ve spinner göster.
- Restart sonrası butonu tekrar aktif et (şu anda disabled kalıyor).

#### 1.10 CSS Class Standardizasyonu
**Dosyalar**: tui/styles.tcss, tüm screen dosyaları
- styles.tcss'te `.hidden { display: none; }` tanımlı.
- main_screen.py `.is-hidden` kullanıyor → ÇALIŞMIYOR çünkü tanım yok.
- connection_map_screen.py `.map-hidden` kullanıyor.
- ÇÖZÜM: Hepsini `.hidden`'a standartlaştır. Veya her class'ı TCSS'te tanımla.

#### 1.11 kill_process() Blocking Sleep
**Dosya**: tui/data/provider.py
- `kill_process()` SIGTERM sonrası 0.1s × 20 = 2s boyunca `time.sleep()` ile blokluyor.
- ÇÖZÜM: Kill işlemini `run_worker(thread=True)` ile background'da çalıştır.

#### 1.12 Kill Confirm Escape Binding
**Dosya**: tui/screens/kill_confirm.py
- Modal'da Escape tuşu bağlı değil — Tab ile Cancel'a gitmek gerekiyor.
- ÇÖZÜM: `Binding("escape", "dismiss")` ekle.
- Ayrıca kill sırasında butonları disable et (çift tıklama önleme).

---

### FAZ 2: UX İyileştirmeleri

#### 2.1 Settings Modal Yeniden Tasarım
**Dosyalar**: tui/screens/settings_screen.py, tui/styles.tcss
- Modal boyutunu içeriğe göre otomatik ayarla (auto height, max-width: 70).
- Border stilini `tall $secondary` → `round $primary-lighten-2` olarak değiştir (daha yumuşak).
- Ayar grupları ekle (başlıklar ile):
  - "Notifications" grubu altında mevcut 2 toggle
  - "Advanced" grubu altında config.py'deki diğer ayarları göster (en azından birkaçını)
- "Restart Daemon" butonunu `warning` variant'ına çevir (sarı yerine), onay dialog'u ekle.
- Ayarlar arasına uygun padding/margin ekle.

#### 2.2 Panel Oranlarını Düzeltme
**Dosya**: tui/styles.tcss
- Port tablosu: `height: auto` veya `min-height: 8; max-height: 50%;`
- Connection log: `height: 1fr` (kalan alanı kaplasın)
- Splitter eklemeyi değerlendir (opsiyonel).

#### 2.3 Aktif Ekran Göstergesi
**Dosyalar**: tui/netsentry_tui.py, tui/widgets/status_bar.py
- Header subtitle'ı ekranın adını gösterecek şekilde güncelle.
  Örnek: "NetSentry — Network Security Analyzer │ Dashboard" 
- Veya status bar'daki kısayol listesinde aktif ekranı farklı renkte/bold göster.

#### 2.4 Filtre Aktif Göstergesi
**Dosya**: tui/screens/main_screen.py
- Filtre aktifken status bar'da veya tablo başlığında göster:
  "🔍 Filter active: 'chrome' (5 of 23 connections)"
- Filtre temizleme kısayolu ekle (Escape veya `x`).

#### 2.5 Empty State'ler
**Tüm widget'lar**
- Port tablosu boşken: "No active connections" mesajı (center aligned, dim text).
- Connection log boşken: "Waiting for connection events..." mesajı.
- Connection map veri yokken: "No geo-located connections found" mesajı.
- Process tree boşken: "No processes with network connections" mesajı.

#### 2.6 Status Bar Okunabilirliği
**Dosya**: tui/widgets/status_bar.py
- Kısayol tuşlarını grupla ve görsel olarak ayır:
  ```
  wlan0 ↓ 242 B/s  ↑ 242 B/s  Total: ↓ 1.6 MB  ↑ 4.7 MB  │  🟢 Daemon Connected
  [q]Quit [k]Kill [r]Refresh │ [m]Map [t]Procs [s]Settings │ [/]Search [f]Filter [e]Export [c]Copy [?]Help
  ```
- Tuş harflerini `[bold]` veya farklı renkte göster.
- `│` veya `·` ile grupları ayır.

#### 2.7 Clipboard Hata Yakalama
**Dosya**: tui/screens/main_screen.py
- `pyperclip.copy()` çağrısını try/except ile sar.
- Hata durumunda: "Clipboard kullanılamıyor. xclip veya xsel yükleyin." toast'u göster.

#### 2.8 Search/Filter Ayrımı
**Dosya**: tui/screens/main_screen.py
- Search (/) → Tablodaki metni highlight et (mevcut davranış)
- Filter (f) → Sadece eşleşen satırları göster (mevcut davranış)
- İki farklı Input widget kullan veya Input'un placeholder'ını ve davranışını mode'a göre değiştir.
- Her iki mod için de ayrı visual indicator göster.

#### 2.9 Connection Log İlk Çağrı Filtre Bypass
**Dosya**: tui/widgets/connection_log.py
- `_seen_keys` boşken (ilk çağrı) filtreler uygulanmıyor — tüm veriler filtresiz gösteriliyor.
- ÇÖZÜM: İlk çağrıda da filtre mantığını uygula.

#### 2.10 Process Tree Auto-Refresh
**Dosya**: tui/screens/process_tree_screen.py
- Veri sadece `on_mount`'ta çekiliyor, ekran stale kalıyor.
- ÇÖZÜM: `set_interval(2.0)` ile periyodik yenileme ekle (diğer ekranlarla tutarlı).
- Tree rebuild sırasında expand/collapse state'ini koru.

#### 2.11 Heartbeat File I/O Cache
**Dosya**: tui/widgets/status_bar.py
- `_check_daemon_alive()` her çağrıda JSON dosyası okuyor (dakikada 30 okuma).
- ÇÖZÜM: 5-10 saniyelik TTL cache ekle.

#### 2.12 Connection Map Toggle Bug
**Dosya**: tui/screens/connection_map_screen.py
- `action_toggle_map()` boş `geo_stats={}` ile `_update_map()` çağırıyor → header'daki ülke sayacı sıfırlanıyor.
- ÇÖZÜM: Mevcut geo_stats'ı koru.

#### 2.13 Connection Map Search Dismiss
**Dosya**: tui/screens/connection_map_screen.py
- `_hide_search` Escape ile input'u gizliyor ama filtre temizlenmiyor. Veriler filtrelenmiş kalıyor.
- ÇÖZÜM: Search dismiss olduğunda filtreyi de temizle.

#### 2.14 Settings İki VerticalScroll Birleştirme
**Dosya**: tui/screens/settings_screen.py
- İki ayrı `VerticalScroll` container var, her birinde 1 ayar. Gereksiz karmaşıklık ve boş alan.
- ÇÖZÜM: Tek bir VerticalScroll altında tüm ayarları grupla.

#### 2.15 DataProvider Singleton
- DataProvider birden fazla ekranda ayrı ayrı instantiate ediliyor (main, map, process_tree).
- ÇÖZÜM: App seviyesinde tek instance, ekranlar arası paylaşım.

#### 2.16 Key Binding `s` Çakışması
- MainScreen: `s` → Settings açar
- ConnectionMapScreen: `s` → Sort yapar
- Kullanıcı alışkanlık kazandıktan sonra ekran değiştirdiğinde karışıyor.
- ÇÖZÜM: Tutarlı binding veya connection map'te sort için farklı tuş kullan.

---

### FAZ 3: Polish ve Tutarlılık

#### 3.1 Renk Sistemi Merkezileştirme
- Tüm renk tanımlarını `shared/constants.py` veya `tui/theme.py` altında tek yerde topla.
- Widget'larda ve TCSS'te bu merkezi renkleri referans al.
- Alert level renkleri: CRITICAL→kırmızı, HIGH→turuncu, MEDIUM→sarı, LOW→açık mavi, INFO→cyan
- State renkleri: ESTABLISHED→yeşil, LISTEN→mavi, TIME_WAIT→sarı, CLOSE_WAIT→kırmızı

#### 3.2 Help Screen İyileştirme
**Dosya**: tui/screens/help_screen.py
- Key binding'leri `app.BINDINGS`'den otomatik üret.
- Kategorilere ayır: Navigation, Actions, Views.
- Modal boyutunu içeriğe göre ayarla.

#### 3.3 Connection Map İyileştirmeleri
**Dosya**: tui/screens/connection_map_screen.py
- GeoIP verisi yokken (0,0) yerine marker'ı gösterme veya "Unknown" konumuna yerleştir.
- Sort göstergesini tablo header'ına ekle.
- Kırık filter fonksiyonunu düzelt veya geçici olarak kaldır.
- Legend'ı daha açıklayıcı yap.

#### 3.4 Process Tree İyileştirmeleri
**Dosya**: tui/screens/process_tree_screen.py
- Tree rebuild'de expand/collapse state'ini koru.
- `k` tuşu ile seçili process'i kill etme seçeneği ekle (KillConfirmScreen'e yönlendir).
- Boşken empty state göster.

#### 3.5 Kill Confirm Screen İyileştirme
**Dosya**: tui/screens/kill_confirm.py
- Bağlantı listesini raw dict yerine formatlanmış tablo olarak göster.
- İşlem sonrası sonuç bildirimi (success/error notification).

#### 3.6 Export İyileştirme
**Dosya**: tui/screens/main_screen.py
- Export formatı seçimi (JSON, CSV).
- Export sonrası dosya yolunu notification'da göster.

#### 3.7 Auto-Scroll Akıllı Davranış
**Dosya**: tui/widgets/connection_log.py
- Kullanıcı yukarı scroll yapmışsa auto-scroll'u durdur.
- "New entries below ↓" göstergesi ekle.
- En alta scroll yapınca auto-scroll'u tekrar aktifleştir.

#### 3.8 Styles.tcss Border Refinement
**Dosya**: tui/styles.tcss
- `tall $secondary` border'ları `round $primary-lighten-2` veya `solid $surface-lighten-1` ile değiştir.
- Daha yumuşak, modern bir görünüm hedefle.
- Modal overlay arka planını hafif blur/dim yap.

---

### FAZ 4: Yeni Özellikler (Opsiyonel — Zaman kalırsa)

#### 4.1 Traffic Sparkline
- Status bar'da veya ayrı widget'ta son 60 saniyenin trafik grafiğini göster.
- Braille veya block karakterlerle mini sparkline.

#### 4.2 Connection Duration
- Port tablosuna "Duration" kolonu ekle.
- Backend'den `timestamp` alınarak `now - timestamp` hesapla.
- Format: "2m 30s", "1h 5m" vb.

#### 4.3 Risk Score Görseli  
- Port tablosunda Alert kolonunu zenginleştir: risk_score'u renkli bar olarak göster.
- Veya Detail screen'de risk breakdown göster.

#### 4.4 Versiyon Bilgisi Header'da
- Header subtitle'a versiyon numarası ekle: "v0.4.0"

## GENEL STİL REHBERİ

### Renk Paleti (Dark Theme)
- Background: HSL(200, 15%, 10%) — koyu lacivert-gri
- Surface: HSL(200, 15%, 15%) — biraz açık
- Primary: HSL(170, 80%, 50%) — cyan-yeşil (mevcut)
- Secondary: HSL(170, 60%, 40%) — daha koyu cyan (border'lar için)
- Accent: HSL(45, 90%, 60%) — amber/sarı (uyarılar)
- Error: HSL(0, 70%, 55%) — kırmızı
- Text: HSL(0, 0%, 90%) — açık gri
- Text Dim: HSL(0, 0%, 50%) — orta gri

### Border Stili
- Ana paneller: `round $secondary` (hafif, dikkat dağıtmayan)
- Modaller: `round $primary-darken-2` 
- Aktif/focused: `round $primary`
- ASLA `tall` veya `heavy` border kullanma (çok agresif)

### Spacing
- Panel'ler arası: 1 satır boşluk
- Widget padding: 1 (minimum)
- Modal padding: 2

### Typography
- Başlıklar: bold + primary renk
- Normal metin: default
- Açıklama/hint metinleri: dim
- Değerler: bold
- Hatalar: bold + error renk

## TEST VE DOĞRULAMA
- Her faz sonrası TUI'ı çalıştır ve görsel olarak kontrol et.
- Daemon olmadan çalıştır → hata durumu ekranının göründüğünü doğrula.
- Terminal boyutunu değiştir → layout'un kırılmadığını doğrula.
- Mevcut testleri çalıştır: `python -m pytest tests/`
- Büyük veri seti ile test et (çok sayıda bağlantı).
```

---

> [!IMPORTANT]
> Bu master prompt'u coding agent'ınıza verirken, agent'ın projeye tam erişimi olduğundan ve Textual framework dokümantasyonuna referans verebileceğinden emin olun. Fazları sırasıyla uygulaması önemlidir — özellikle Faz 1'deki kritik hatalar önce çözülmelidir.
