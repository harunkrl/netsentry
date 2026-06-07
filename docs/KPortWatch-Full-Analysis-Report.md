# KPortWatch — Kapsamlı Analiz Raporu

**Tarih:** 7 Haziran 2026  
**Versiyon Analizi:** v2.1.0  
**Kapsam:** Backend, TUI, Test/CI, Altyapı (install scripts, systemd, polkit, widget, docs)  
**Yöntem:** 4 paralel statik analiz ajanı ile derinlemesine inceleme

---

## 📊 Yönetici Özeti

KPortWatch, KDE Plasma 6 için geliştirilen bir ağ güvenlik monitörü. 3 ana bileşenden oluşuyor: backend daemon, Textual TUI ve Plasma widget. Proje genel olarak iyi yapılandırılmış, ancak **5 KRİTİK**, **16 YÜKSEK** ve **31 ORTA** seviye bulgu tespit edildi.

| Şiddet | Adet |
|--------|------|
| 🔴 KRİTİK | 5 |
| 🟠 YÜKSEK | 16 |
| 🟡 ORTA | 31 |
| 🔵 DÜŞÜK | 32 |
| ⚪ BİLGİ | 39 |

---

## 🔴 KRİTİK BULGULAR

### K1. Kill Komutu Yetkilendirme Eksikliği
**Dosya:** `backend/daemon_controller.py:173-230`, `backend/writers/unix_socket.py:39`

Daemon, Unix socket üzerinden herhangi bir yerel süreç kill etme yetkisi veriyor. Yetkilendirme, denetim günlüğü (audit log) veya oran sınırlaması (rate limiting) yok. Aynı kullanıcıya ait herhangi bir tehlikeli süreç, bu mekanizmayı kullanarak güvenlik araçlarını devre dışı bırakabilir.

**Öneri:** `SO_PEERCRED` ile istemci UID doğrulaması, oran sınırlaması ve denetim günlüğü ekleyin.

---

### K2. Otomatik Güncelleme İmzasız Kod Çalıştırıyor
**Dosya:** `backend/update.py:138-199`

`perform_update()` fonksiyonu `git pull origin main` + `pip install -e .` çalıştırıyor. GPG doğrulama var ama atlanabilir durumda ("does NOT block the update"). MITM saldırısı veya ele geçirilmiş GitHub hesabı durumunda kötü amaçlı kod çalıştırılabilir.

**Öneri:** GPG doğrulamayı zorunlu yapın, commit imza doğrulaması ekleyin, güncelleme öncesi kullanıcı onayı isteyin.

---

### K3. `_build_alert_map` Çift `@staticmethod` Dekoratörü — Runtime Crash
**Dosya:** `tui/widgets/port_table.py:351-352`

```python
@staticmethod
@staticmethod
def _build_alert_map(alerts: list) -> dict[int, str]:
```

Çift dekoratör, `staticmethod` nesnesinin çağrılabilir olmamasına neden oluyor. Alert'ler olduğunda port tablosu sessizce render edemiyor.

**Öneri:** Yinelenen dekoratörü kaldırın (satır 351 veya 352).

---

### K4. Test Kapsamı Eşiği (%75) Uygulanmıyor — CI Bloke Ediyor
**Dosya:** `.github/workflows/ci.yml:26`, `pyproject.toml:62`

CI `--cov-fail-under=75` çalıştırıyor ama gerçek kapsam **%41.1**. Tüm PR'ları bloke ediyor. Ya eşik gerçekçi bir değere düşürülmeli ya da kapsam artırılmalı.

**Öneri:** Kapsamı artırın (öncelik: DaemonController, CLI entry points, MainScreen) veya eşiği geçici olarak ~%45'e düşürün.

---

### K5. DaemonController — En Kritik Modül, %0 Test Kapsamı
**Dosya:** `backend/daemon_controller.py` (400+ satır)

Daemon'un kalbi olan bu sınıf hiç test edilmiyor. Kapsamayan kritik yollar:
- Bileşen başlatma, veri toplama, zenginleştirme
- Alert analizi, snapshot oluşturma, yayınlama
- Soket komut işleme, bildirim yönetimi
- Uyarlanabilir yoklama (adaptive polling)
- Yapılandırma yeniden yükleme (SIGHUP)
- Temizlik (graceful shutdown)

**Öneri:** Mock tabanlı entegrasyon testleri ekleyin.

---

## 🟠 YÜKSEK BULGULAR

### Backend (5 bulgu)

| ID | Bulgu | Dosya | Detay |
|----|-------|-------|-------|
| B-H1 | Unix socket TOCTOU yarış durumu | `writers/unix_socket.py:34-36` | `os.path.exists()` + `os.unlink()` atomik değil |
| B-H2 | PID dosyası varsayılan umask izinleri | `kportwatch_daemon.py:192-200` | `XDG_RUNTIME_DIR` yoksa `/tmp`'de world-readable |
| B-H3 | `notify-send` girdi sterilizasyonu yok | `daemon_controller.py:446-455` | Uzun/özel karakterli mesajlar sorun çıkarabilir |
| B-H4 | GeoIP API URL'si yapılandırılabilir → SSRF vektörü | `parsers/geoip.py:78-79` | Dahili ağ adreslerine istek mümkün |
| B-H5 | GeoIP rate limiter thread-unsafe | `parsers/geoip.py:168-174` | Kilitleme dışında sleep, rate limiti atlatır |

### TUI (4 bulgu)

| ID | Bulgu | Dosya | Detay |
|----|-------|-------|-------|
| T-H1 | `action_export` ana thread'i blokluyor | `main_screen.py:268-278` | Senkron disk I/O → TUI donması |
| T-H2 | `ProcessKillConfirm` senkron `os.kill` | `process_tree_screen.py:353-367` | Ana thread'de, escalation pattern kullanmıyor |
| T-H3 | Quick-filter semantik tutarsızlığı | `connection_log.py:159-164` | "warning" filtresi INFO seviye bağlantıları gösteriyor |
| T-H4 | `Snapshot` modelinde `@dataclass` eksik | `backend/models.py:104` | Mutable default argüman tehlikesi |

### Test & CI (4 bulgu)

| ID | Bulgu | Dosya | Detay |
|----|-------|-------|-------|
| C-H1 | TUI ekranları %0 test kapsamı | `tui/screens/*.py` | 6 ekran, hiçbiri test edilmiyor |
| C-H2 | CLI entry point'leri test edilmemiş | `export.py`, `kportwatch_client.py`, `kportwatchctl.py` | 3 dosya, %0 kapsam |
| C-H3 | `psutil_collector` canlı sistemde test ediliyor | `test_psutil_collector.py` | Mock yok, ortama bağlı, deterministik değil |
| C-H4 | Güvenlik taramaları `|| true` ile devre dışı | `.github/workflows/ci.yml:49-53` | Bandit ve pip-audit hiçbir zaman CI'ı başarısız kılmaz |

### Altyapı (3 bulgu)

| ID | Bulgu | Dosya | Detay |
|----|-------|-------|-------|
| I-H1 | `uninstall.sh` güvenlik bayrakları eksik | `uninstall.sh:5` | `set -u` ve `-o pipefail` yok, install.sh'te var |
| I-H2 | `tuiCommand` shell injection riski | `widget/main.qml:196-198` | Kullanıcı yapılandırması doğrudan shell'de |
| I-H3 | Ana döngüde geniş `except Exception` | `daemon_controller.py:574-576` | Programlama hataları sessizce yutuluyor |

---

## 🟡 ORTA BULGULAR

### Backend (9 bulgu)

| ID | Bulgu | Dosya |
|----|-------|-------|
| B-M1 | Baseline dosyası bütünlük doğrulaması yok | `alert_engine.py:102-122` |
| B-M2 | `fnmatch` IP eşleştirmesi güvenilmez | `alert_engine.py:82-88` |
| B-M3 | Geçmiş dosyaları varsayılan izinlerle | `history.py:53-59` |
| B-M4 | Soket yanıtı 10MB sınır çok geniş | `unix_socket.py:209` |
| B-M5 | Modül düzeyinde mutable global durum | `parsers/geoip.py`, `parsers/rdns.py` |
| B-M6 | Singleton config thread-unsafe | `shared/config.py:141` |
| B-M7 | Yinelenen `_write_heartbeat` fonksiyonu | `kportwatch_daemon.py` vs `daemon_controller.py` |
| B-M8 | `notified_alerts` sınırsız büyüme | `daemon_controller.py:462-469` |
| B-M9 | History dosya tanıtıcısı süresiz açık | `history.py:49` |

### TUI (9 bulgu)

| ID | Bulgu | Dosya |
|----|-------|-------|
| T-M1 | `_trim_seen` gerçek LRU değil | `connection_log.py:213-217` |
| T-M2 | `_mini_sparkline` string concatenation hatası | `traffic_bar.py:41` |
| T-M3 | `ioctl` her arayüz için her yenilemede blokluyor | `traffic_bar.py:63-72` |
| T-M4 | Büyük world map string kaynak kodunda gömülü | `connection_map_screen.py:39-59` |
| T-M5 | `_render_map` her çağrıda derin kopya | `connection_map_screen.py` |
| T-M6 | `ConfirmRestart` metot içinde tanımlanmış | `settings_screen.py:397-433` |
| T-M7 | `_find_project_root` her restart'ta FS yürüyor | `settings_screen.py:476-482` |
| T-M8 | Ekranlar `_refresh_handle` tutarsız temizliyor | Çoklu dosya |
| T-M9 | Hata detayları soket istemcisine sızdırılıyor | `unix_socket.py:100-104` |

### Test & CI (7 bulgu)

| ID | Bulgu | Dosya |
|----|-------|-------|
| C-M1 | CI'da tip kontrolü yok (mypy/ty) | `.github/workflows/ci.yml` |
| C-M2 | `test_inode_map.py` düşük kapsam | `test_inode_map.py` |
| C-M3 | `update.py` main() test edilmiyor | `test_update.py` |
| C-M4 | Release pipeline matrix eksik | `.github/workflows/release.yml` |
| C-M5 | CI'da pip önbellek yok | `.github/workflows/ci.yml` |
| C-M6 | Kapsam raporlaması yüklenmiyor | `.github/workflows/ci.yml` |
| C-M7 | `test_daemon_lifecycle` gerçek entegrasyon değil | `test_daemon_lifecycle.py` |

### Altyapı (6 bulgu)

| ID | Bulgu | Dosya |
|----|-------|-------|
| I-M1 | Versiyon 3 yerde manuel bakım | `constants.py`, `pyproject.toml`, `metadata.json` |
| I-M2 | Widget metadata'da yanlış GitHub URL | `widget/metadata.json:18` |
| I-M3 | Config örneğinde eski GeoIP referansları | `contrib/kportwatch-config-example.toml` |
| I-M4 | Systemd CapabilityBoundingSet yanıltıcı | `systemd/kportwatch.service:39,46` |
| I-M5 | Systemd WatchdogSec yok | `systemd/kportwatch.service` |
| I-M6 | Polkit read/kill ayrımı yok | `polkit/com.kportwatch.helper.policy` |

---

## 🏗️ Mimari Gözlemler

### Olumlu Yönler ✅

1. **Temiz katmanlı mimari** — Backend → JSON → TUI/Widget veri akışı net
2. **Atomik dosya yazmaları** — `atomic_write()` ile tutarlı kullanım
3. **Diff-tabanlı TUI güncellemeleri** — Titreme önleme ve scroll koruma
4. **Güçlü systemd sandboxing** — `ProtectSystem=strict`, `PrivateTmp`, `RestrictNamespaces`
5. **İyi veri modelleme** — Dataclass'lar, tip ipuçları, doğru serileştirme
6. **`eval()`/`exec()`/`pickle` yok** — Tehlikeli deserialization kullanılmıyor
7. **Shell injection yok** — Tüm subprocess çağrıları liste formunda
8. **Widget model reconciliation** — Sophisticated 3-adımlı güncelleme
9. **Auto-scroll algılama** — Kullanıcı yukarı kaydırdığında duraklatma
10. **Düşük bağımlılık ayak izi** — Sadece 3 runtime dependency

### İyileştirme Alanları ⚠️

1. **DaemonController "god object"** olmaya yaklaşıyor — ~540 satır, 15+ sorumluluk
2. **Global mutable state** — GeoIP ve rDNS modülleri test edilebilirliği zorlaştırıyor
3. **TUI ekranları hiç test edilmiyor** — Headless Textual test imkanı var ama kullanılmıyor
4. **Versiyon triple-maintenance** — 3 dosyada manuel senkronizasyon riskli

---

## 📋 Öncelikli Düzeltme Planı

### Aşama 1 — Acil (1-2 gün)
| Öncelik | Bulgu | Çaba |
|----------|---------|--------|
| P0 | K3: Çift `@staticmethod` dekoratörünü kaldır | 1 dakika |
| P0 | K4: Kapsam eşiğini geçici olarak düşür | 5 dakika |
| P0 | I-H1: `uninstall.sh`'e `set -u -o pipefail` ekle | 1 dakika |
| P0 | I-M2: metadata.json GitHub URL'sini düzelt | 1 dakika |

### Aşama 2 — Yüksek Öncelik (1 hafta)
| Öncelik | Bulgu | Çaba |
|----------|---------|--------|
| P1 | K1: Kill komutuna yetkilendirme ekle | Orta |
| P1 | K2: GPG doğrulamayı zorunlu yap | Küçük |
| P1 | T-H1: `action_export`'u asenkron yap | Küçük |
| P1 | T-H2: Process kill'i async yap | Küçük |
| P1 | B-H4: GeoIP URL doğrulaması ekle | Küçük |
| P1 | B-H5: Rate limiter thread-safety düzelt | Orta |
| P1 | I-M1: Versiyon yönetimini otomatikleştir | Orta |

### Aşama 3 — Test Altyapısı (2 hafta)
| Öncelik | Bulgu | Çaba |
|----------|---------|--------|
| P2 | K5: DaemonController testleri ekle | Büyük |
| P2 | C-H1: MainScreen headless testleri ekle | Büyük |
| P2 | C-H2: CLI entry point testleri ekle | Orta |
| P2 | C-M1: Tip kontrolü (mypy/ty) ekle | Orta |
| P2 | C-H4: Güvenlik taramalarını etkinleştir | Küçük |

### Aşama 4 — Mimari İyileştirmeler (1 ay)
| Öncelik | Bulgu | Çaba |
|----------|---------|--------|
| P3 | B-M5: Global state'i sınıflara taşı | Büyük |
| P3 | B-M6: Config singleton'ı thread-safe yap | Orta |
| P3 | DaemonController'u böl (notification, update) | Büyük |
| P3 | I-M5: WatchdogSec ekle | Küçük |
| P3 | I-M6: Polkit read/kill ayır | Orta |

---

## 📈 Sayısal Özet

```
Toplam Bulgu:                    123
├── KRİTİK:                       5  ← Hemen düzelt
├── YÜKSEK:                      16  ← Bu sprint
├── ORTA:                        31  ← Sonraki sprint
├── DÜŞÜK:                       32  ← Fırsat buldukça
└── BİLGİ:                       39  ← İyi uygulamalar

Kapsam:                        41.1%  (Hedef: 75%)
Test Sayısı:                    474   (Hepsi geçiyor)
Runtime Dependency:               3   (textual, rich, psutil)
Desteklenen Python:        3.11, 3.12, 3.13
```

---

## 📁 Detaylı Raporlar

Tam analiz çıktıları proje kök dizininde:

| Rapor | Dosya | Boyut |
|-------|-------|-------|
| Backend & Güvenlik | `analysis-backend.md` | 23.6 KB |
| TUI & UX | `analysis-tui.md` | 20.8 KB |
| Test & CI/CD | `analysis-tests-ci.md` | 15.8 KB |
| Altyapı & Cross-cutting | `analysis-crosscutting.md` | 20.2 KB |

---

*Rapor 4 paralel statik analiz ajanı tarafından oluşturulmuştur. Her bulgu kaynak kodda dosya ve satır referansları ile doğrulanmıştır.*
