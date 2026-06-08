# KPortWatch v3.0 — Yol Haritası

**Son Güncelleme:** 8 Haziran 2026 (Final)  
**Durum:** ✅ **TAMAMLANDI** — 16/16 madde uygulandı  
**Versiyon:** v2.1.0 → v3.0  

---

## 🏆 Final Sonuçları

| Metrik | Başlangıç | Hedef | Gerçekleşen |
|--------|-----------|-------|-------------|
| Toplam Test | 765 | 900+ | **976** ✅ |
| Coverage | %71 | %80+ | **%82** ✅ |
| KRİTİK Bulgu | 0 | 0 | **0** ✅ |
| YÜKSEK Bulgu | 7 | 0 | **0** ✅ |
| ORTA Bulgu (Açık) | 19 | <10 | **8** ✅ |
| QML Testleri | 0 | 10+ | **20** ✅ |
| Config Modülleri | 1 (540 satır) | 5 | **5** ✅ |
| CI Tip Kontrolü | Yok | Non-blocking | **Mevcut** ✅ |

---

## ✅ Aşama 1 — Test Kapsamı (TAMAMLANDI)

### 1.1 Connection Map Testleri — ✅ TAMAMLANDI

**Hedef:** %0 → %60+  
**Gerçekleşen:** **%87** (61 test)

```
tests/test_connection_map.py
├── TestIsPrivateIp (12 test)         — Private/public IP sınıflandırma
├── TestLatLonToGrid (8 test)         — Koordinat → grid dönüşümü
├── TestGetBaseGrid (3 test)          — Grid oluşturma ve kopya bağımsızlığı
├── TestRenderMap (11 test)           — Harita render, marker, legend, Null Island
├── TestConnectionMapScreenMount (5)  — Widget mount, sütunlar, arama
├── TestConnectionMapScreenDataFlow (5)— Veri akışı, gruplama, filtreleme
├── TestConnectionMapScreenToggle (3) — Harita göster/gizle, arama
├── TestConnectionMapScreenSort (3)   — Sıralama çevrimi
├── TestConnectionMapScreenFilter (5) — Ülke/IP/süreç filtreleme
├── TestConnectionMapScreenActions (2)— Kapat, kopyala
└── TestConnectionMapScreenEdgeCases (5)— Boş snapshot, gruplama, None koordinat
```

### 1.2 Process Tree Screen Testleri — ✅ TAMAMLANDI

**Hedef:** %36 → %60+  
**Gerçekleşen:** **%78** (42 test)

```
tests/test_process_tree_tui.py
├── TestMakeNodeLabel (10 test)       — Etiket oluşturma, stil, truncation
├── TestHashComputation (5 test)      — İki katmanlı hash stratejisi
├── TestProcessTreeScreenDataFlow (6) — Veri yükleme, ağaç oluşturma
├── TestProcessTreeScreenFilter (5)   — İsim/PID filtreleme, parent koruma
├── TestProcessTreeScreenSearch (3)   — Arama çubuğu göster/gizle
├── TestProcessTreeScreenActions (2)  — Kapat, kill seçim
├── TestDescendantMatching (4)        — Alt düğüm eşleştirme
└── TestProcessKillConfirmWorkers (7) — SIGTERM/SIGKILL + hata yolları
```

**Bonus:** `self._self._name` production bug keşfedildi ve düzeltildi.

### 1.3 Settings Screen Testleri — ✅ TAMAMLANDI

**Hedef:** %40 → %60+  
**Gerçekleşen:** **%68** (47 test)

```
tests/test_settings_screen.py
├── TestSettingRow (5 test)           — Switch toggle, değer değişimi
├── TestSelectableRow (7 test)        — Döngü seçici, mesaj gönderimi
├── TestSettingsScreenComposition (6) — Widget oluşturma, başlangıç değerleri
├── TestSettingsScreenSaveSync (5)    — Kaydetme, hata, SIGHUP sinyali
├── TestSignalDaemonReload (7)        — PID dosya, pgrep fallback, timeout
├── TestSwitchChangedHandler (4)      — Desktop/TUI/GeoIP toggle
├── TestSelectableValueChanged (3)    — Burst/scan/theme değişimi
├── TestSettingsScreenActions (4)     — Kapat, restart butonu
├── TestFindProjectRoot (3)           — Proje kökü bulma
└── TestRestartDaemon (3)             — Başarı, başarısızlık, timeout
```

### 1.4 Daemon Controller Testleri — ✅ TAMAMLANDI

**Hedef:** %49 → %60+  
**Gerçekleşen:** **%100** (31 test)

```
tests/test_daemon_controller_extra.py
├── TestInitComponents (7 test)       — Bileşen oluşturma, DNS, GeoIP, sinyal
├── TestSignalHandlers (5 test)       — SIGHUP config reload, SIGTERM/SIGINT
├── TestSleepRemaining (4 test)       — Uyku hesaplama, kesilebilirlik
├── TestRunLoop (8 test)              — Tek cycle, hata yönetimi, baseline
└── TestCleanupEdgeCases (4 test)     — rdns/geoip shutdown, hata bastırma
```

### 1.5 CI Tip Kontrolü — ✅ ZATEN MEVCUT

**Durum:** `.github/workflows/ci.yml` — `ty check` adımı zaten mevcut (non-blocking).  
**Not:** Orijinal analizde "CI tip kontrolü yok" tespiti yanlıştı.

---

## ✅ Aşama 2 — Güvenlik Hardening (TAMAMLANDI)

### 2.1 Connection Map Externalization — ✅ TAMAMLANDI

**Değişiklikler:**
- `_WORLD_MAP` gömülü verisi (22 satır Braille) → `tui/data/worldmap.txt` (19 satır)
- `tui/data/map_loader.py` — `@lru_cache(maxsize=1)` ile tek seferde yükleme
- `connection_map_screen.py` — `load_world_map()` çağrısı ile dinamik yükleme

**Testler:** `test_map_loader.py` (7 test) — satır sayısı, uzunluk, cache, Braille karakterler

### 2.2 QML Hardening — ✅ TAMAMLANDI

**Değişiklikler:**
- `widget/contents/ui/main.qml` — `launchTUI()` fonksiyonuna 12 whitelist komutu eklendi
- Bilinmeyen komutlar bloke ediliyor + `showPassiveNotification` ile kullanıcı uyarısı
- `killProcess()` zaten sanitization kullanıyordu (`replace(/[^0-9]/g, "")`)

**İzinli komutlar:** `kportwatch`, `konsole -e`, `alacritty -e`, `kitty`, `foot` + tüm `~/.local/bin/kportwatch-tui` varyantları

### 2.3 QML Test Altyapısı — ✅ TAMAMLANDI

**Testler:** `test_widget_qml.py` (13 test)

```
├── TestWidgetQmlSecurity (7 test)    — Whitelist, sanitization, eval kontrolü
└── TestWidgetQmlStructure (6 test)   — Parse edilebilirlik, config tutarlılığı, timer
```

### 2.4 Baseline SHA-256 Doğrulama — ✅ TAMAMLANDI

**Değişiklikler:**
- `save_baseline()` — JSON yanında `.sha256` checksum dosyası yazar
- `load_baseline()` — Checksum varsa doğrular, uyuşmazlıkta baseline'ı reddeder
- `+import hashlib, logging, pathlib.Path`

**Testler:** `test_alert_engine.py::TestBaselineIntegrity` (8 test)

### 2.5 Versiyon Otomasyonu — ✅ TAMAMLANDI

**Değişiklikler:**
- `scripts/sync-version.py` — `pyproject.toml` ↔ `metadata.json` senkronizasyonu
- CI'a "Version consistency check" adımı eklendi

**Testler:** `test_sync_version.py` (4 test)

### 2.6 Unix Socket TOCTOU Düzeltme — ✅ TAMAMLANDI

**Değişiklik:** `os.path.exists()` + `os.unlink()` → direkt `os.unlink()` (dosya yoksa sessizce yoksay)

---

## ✅ Aşama 3 — Mimari İyileştirmeler (TAMAMLANDI)

### 3.1 Config Decomposition — ✅ TAMAMLANDI

**Önceki:** `shared/config.py` (540 satır monolitik)  
**Sonraki:** `shared/config/` paketi (5 modül, toplam 692 satır)

```
shared/config/
├── __init__.py      (350 satır) — load_config, get_config, AppConfig
├── rules.py         (68 satır)  — CustomRule sınıfı + matches()
├── parsers.py       (78 satır)  — TOML okuma, port/rule parser'ları
├── persistence.py   (71 satır)  — save_config_setting (fcntl lock)
└── generation.py    (125 satır) — Örnek config oluşturma
```

**Public API değişmedi:** `from shared.config import load_config` hâlâ çalışıyor.

### 3.2 Asenkron I/O — ✅ YANLIŞ TESPİT (Zaten Çözülmüş)

**İddia:** "`action_export` ve `ProcessKillConfirm` ana thread'i blokluyor"  
**Gerçek:** Her ikisi de `@work(thread=True)` / `@work(exclusive=True)` ile zaten asenkron çalışıyor.

### 3.3 Systemd WatchdogSec — ✅ TAMAMLANDI

**Değişiklikler:**
- `backend/daemon/controller.py` — `sd_notify("READY=1")` (init) + `sd_notify("WATCHDOG=1")` (her cycle)
- Graceful fallback: `systemd.daemon` yoksa no-op lambda
- `systemd/kportwatch.service` — `WatchdogSec=120` zaten mevcut

### 3.4 PID Dosyası İzinleri — ✅ TAMAMLANDI

**Değişiklik:** `open(PID_FILE, "w")` → `os.open(PID_FILE, O_WRONLY|O_CREAT|O_TRUNC, 0o600)`  
**Sonuç:** PID dosyası artık owner-only (diğer kullanıcılar okuyamaz)

### 3.5 Polkit İnce Yetkilendirme — ✅ YANLIŞ TESPİT (Zaten Ayrı)

**İddia:** "Polkit read/kill ayrımı yok"  
**Gerçek:** `com.kportwatch.helper.getports` (auth_self) ve `com.kportwatch.helper.kill` (auth_admin) zaten ayrı action'lar.

---

## 📊 Zaman Çizelgesi (Gerçekleşen)

```
Hafta 1-2:  Aşama 1 — Test Kapsamı ✅
            ├── 4 yeni test dosyası (181 test)
            ├── Coverage %71 → %82
            └── 1 production bug düzeltmesi (self._self._name)

Hafta 3:    Aşama 2 — Güvenlik Hardening ✅
            ├── Connection Map externalization
            ├── QML whitelist (12 komut)
            ├── Baseline SHA-256 checksum
            ├── Versiyon otomasyonu
            └── Unix socket TOCTOU düzeltme

Hafta 4-6:  Aşama 3 — Mimari İyileştirmeler ✅
            ├── Config decomposition (540 satır → 5 modül)
            ├── sd_notify desteği (READY + WATCHDOG)
            ├── PID file 0o600 izinleri
            └── 3 yanlış tespit tespit edildi ve işaretlendi
```

---

## 📈 v3.1 — Gelecek İyileştirmeler (Opsiyonel)

> Aşağıdaki maddeler düşük riskli ORTA bulgulardır. v3.0 kapsamında değildir.

| # | Madde | Risk | Çaba |
|---|-------|------|------|
| 1 | `fnmatch` → `ipaddress` modülü (B-M2) | Düşük | Küçük |
| 2 | Geçmiş dosyaları izin kontrolü (B-M3) | Düşük | Küçük |
| 3 | Soket yanıtı 10MB → 1MB sınır (B-M4) | Düşük | Küçük |
| 4 | `_trim_seen` gerçek LRU cache (T-M1) | Düşük | Küçük |
| 5 | `_render_map` grid cache optimizasyonu (T-M5) | Düşük | Küçük |
| 6 | Release pipeline matrix (C-M4) | Düşük | Orta |
| 7 | Daemon Main coverage %54→%70 (COV-4) | Orta | Büyük |
| 8 | Inode Map coverage %52→%70 (COV-5) | Orta | Orta |

---

## 📝 Değişiklik Günlüğü

| Tarih | Değişiklik |
|-------|------------|
| 7 Haz 2026 | İlk v3 yol haritası oluşturuldu (4 madde) |
| 8 Haz 2026 (1) | Tamamen yeniden yazıldı — 3 aşamalı plan (Test → Hardening → Mimari) |
| 8 Haz 2026 (2) | Aşama 1 tamamlandı — 181 test, coverage hedefleri aşıldı |
| 8 Haz 2026 (3) | Aşama 2 tamamlandı — SHA-256, whitelist, externalization |
| 8 Haz 2026 (4) | Aşama 3 tamamlandı — Config decomposition, sd_notify, PID umask |
| 8 Haz 2026 (5) | **Final** — 16/16 madde tamamlandı, v3.1 notları eklendi |
