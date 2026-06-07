# KPortWatch v3.0 — Kalan İyileştirme Önerileri

Bu belge, analiz raporunda tespit edilen ve v3.0 kapsamında ele alınması önerilen 4 mimari iyileştirmeyi detaylandırmaktadır.

---

## 1. DaemonController Decomposition

### Mevcut Durum
`backend/daemon_controller.py` — **627 satır**, tek bir sınıfta **15+ sorumluluk**:

```
DaemonController (627 satır)
├── Yapılandırma & Başlatma       __init__, _init_components, _handle_sighup
├── Veri Toplama                  _collect_entries, _collect_traffic
├── Veri Zenginleştirme           _enrich_connections, _build_tree
├── Risk Hesaplama                _compute_risk_scores
├── Snapshot Oluşturma            _build_snapshot
├── Yayınlama                     _publish
├── Alert & Bildirim Yönetimi     _handle_notifications (62 satır)
│   ├── Rate limiting
│   ├── TTL deduplication
│   ├── notify-send entegrasyonu
│   └── Cache eviction
├── Kill Yönetimi                 _handle_socket_command, _kill_process (96 satır)
│   ├── PID doğrulama
│   ├── UID yetkilendirme
│   ├── Rate limiting
│   ├── SIGTERM → SIGKILL escalation
│   └── Protected PID koruma
├── Adaptif Yoklama               _adaptive_interval
├── Güncelleme Kontrolü           _check_for_updates
├── Döngü Yönetimi                run, _sleep_remaining
└── Temizlik                      _cleanup
```

### Problem
- **God Object anti-pattern**: Tek sınıf too many reasons to change
- **Test zorluğu**: 627 satırlık bir sınıfı test etmek için her sorumluluğu ayrı mock'lamak gerekiyor
- **Bakım riski**: Bildirim mantığındaki bir değişiklik kill mantığını, kill mantığındaki bir değişiklik veri toplamayı etkileyebilir
- **Okunabilirlik**: Yeni bir geliştirici "bu sınıf ne yapıyor?" sorusuna kolay cevap veremiyor

### Önerilen Mimari

```
backend/
├── daemon_controller.py          # Orkestratör (~200 satır)
│   └── DaemonController
│       ├── _init_components()    # Alt modülleri başlatır
│       ├── run()                 # Ana döngü — alt modülleri çağırır
│       └── _cleanup()            # Alt modülleri kapatır
│
├── notification_manager.py       # Bildirim sorumluluğu (~120 satır)
│   └── NotificationManager
│       ├── handle(alerts)        # Ana dispatch
│       ├── _should_send(alert)   # TTL dedup + rate limit kontrolü
│       ├── _send_desktop(alert)  # notify-send entegrasyonu
│       ├── _evict_expired()      # Cache temizleme
│       └── shutdown()            # Temizlik
│
├── kill_manager.py               # Process termination (~150 satır)
│   └── KillManager
│       ├── handle_command(cmd)   # Komut dispatch + doğrulama
│       ├── _check_uid(pid)       # UID yetkilendirme
│       ├── _check_rate_limit()   # Rate limiting
│       ├── kill(pid)             # SIGTERM → SIGKILL escalation
│       └── PROTECTED_PIDS        # Korunan PID'ler
│
└── update_checker.py             # Güncelleme kontrolü (~80 satır)
    └── UpdateChecker
        ├── check()               # GitHub API kontrol
        ├── _verify_signature()   # GPG doğrulama
        └── _perform_update()     # git pull + pip install
```

### Uygulama Adımları

1. **NotificationManager'ı çıkar** (en düşük risk):
   - `_handle_notifications` + yardımcı metodları yeni dosyaya taşı
   - DaemonController'da `self.notification_mgr = NotificationManager(cfg)` oluştur
   - Mevcut testler yeşil kalmalı

2. **KillManager'ı çıkar**:
   - `_handle_socket_command` (kill kolu) + `_kill_process` taşı
   - `_kill_timestamps` ve `_MAX_KILL_RATE` da taşınmalı
   - Socket server KillManager'ı çağırmalı

3. **UpdateChecker'ı çıkar**:
   - `_check_for_updates` taşı
   - Mevcut update.py ile ilişkiyi netleştir

### Risk Değerlendirmesi
- **Düşük risk**: Her çıkarma işlemi bağımsız, mevcut testlerle doğrulanabilir
- **Fayda**: Her modül ~100-150 satır, tek sorumluluk, kolay test edilebilir
- **Gerileme önleme**: Mevcut 670 test + yeni modül testleri ile güvence

---

## 2. Connection Map Gömülü String → Dosya Tabanlı

### Mevcut Durum
`tui/screens/connection_map_screen.py` satır 39-59:

```python
_WORLD_MAP: list[str] = [
    r"⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡀⡀⣀⢠⢠⢠⢀⠀⠀⠀⠀⠀⠀⠀...",
    r"⠀⠀⠀⠀⠀⠀⠀⡀⡀⡀⠀⢀⢀⠀⠀⠀⠀⡀⡠⡠⣀⠀⠁⢑⢕⢅⢇⢣⠃⠁⠀⠀⠀⠀⠀⠀⠀...",
    # ... 21 satır Unicode Braille haritası (~1KB)
]
```

### Problem
- **Kaynak kodu şişirmesi**: 21 satırlık gömülü map verisi, dosyanın %4'ünü oluşturuyor
- **Edit zorluğu**: Harita karakterlerini kaynak kodda düzenlemek pratik değil
- **Çoklu çözünürlük desteği yok**: Tek bir harita boyutu var, farklı terminal boyutlarına adapte olmuyor
- **Cache sorunu**: `_get_base_grid()` her çağrıda `[row[:] for row in _BASE_GRID]` ile deep copy yapıyor → gereksiz bellek tahsisi

### Önerilen Çözüm

```
tui/
├── data/
│   ├── worldmap_80x180.txt      # Standart terminal
│   ├── worldmap_40x90.txt       # Küçük terminal
│   └── worldmap_120x270.txt     # Geniş terminal
├── screens/
│   └── connection_map_screen.py  # map_loader kullanır
└── utils/
    └── map_loader.py             # Harita yükleme + caching
```

**map_loader.py:**
```python
from pathlib import Path
from functools import lru_cache

_MAPS_DIR = Path(__file__).parent.parent / "data"

@lru_cache(maxsize=3)
def load_map(width: int, height: int) -> list[list[str]]:
    """Load the best-fitting map for the terminal size."""
    # En yakın dosyayı bul, yükle, 2D grid'e çevir
    ...

def render_with_connections(grid, connections, home_lat, home_lon) -> str:
    """Render map with connection markers."""
    ...
```

### Uygulama Adımları

1. Mevcut `_WORLD_MAP` verisini `tui/data/worldmap_80x180.txt` dosyasına taşı
2. `map_loader.py` oluştur — dosyadan yükleme + `@lru_cache`
3. `_get_base_grid()` yerine `map_loader.load_map()` kullan
4. `_render_map` fonksiyonunu `map_loader.render_with_connections()` olarak taşı
5. (Opsiyonel) Farklı boyutlarda harita dosyaları ekle

### Faydalar
- Kaynak kodu 21 satır kısalır
- Harita verisi bağımsız düzenlenebilir
- Çoklu çözünürlük desteği mümkün olur
- Bellek kullanımı optimize edilir (lru_cache)

---

## 3. Widget QML Testleri

### Mevcut Durum
Widget dosyaları (toplam 1034 satır QML):

| Dosya | Satır | İşlev |
|-------|-------|-------|
| `main.qml` | 430 | Ana widget mantığı — JSON okuma, model güncelleme, timer |
| `FullRepresentation.qml` | 458 | Genişletilmiş görünüm — tablo, grafik, butonlar |
| `CompactRepresentation.qml` | 59 | Panel gösterimi — bağlantı sayısı, alert badge |
| `ConfigGeneral.qml` | 78 | Ayarlar arayüzü |

**Test coverage: %0** — Widget kodu hiç test edilmiyor.

### Problem
`main.qml:196-198`'de shell injection riski tespit edildi:
```qml
// Mevcut kod:
PlasmaCore.DataSource {
    property string tuiCommand: plasmoid.configuration.tuiCommand || "konsole -e kportwatch"
    onExec: source == "tuiCommand" ? tuiCommand : ...
}
```
Kullanıcı yapılandırması doğrudan shell'de çalıştırılıyor. Test olmadığı için bu tür güvenlik sorunları yakalanamıyor.

### Önerilen Test Yaklaşımı

#### Seviye 1: Statik Analiz
```yaml
# .github/workflows/ci.yml
- name: QML Syntax Check
  run: |
    find widget -name "*.qml" -exec qmllint {} \;
```
`qmllint` ile sözdizimi ve temel kod kalitesi kontrolü.

#### Seviye 2: Birim Testler (Qt Test)
```python
# tests/test_widget_qml.py
class TestWidgetQml:
    def test_main_qml_no_shell_injection(self):
        """Verify tuiCommand doesn't execute arbitrary shell commands."""
        content = Path("widget/contents/ui/main.qml").read_text()
        # Check that command is sanitized
        assert "tuiCommand" in content
        # Should use a predefined whitelist, not arbitrary execution

    def test_model_reconciliation(self):
        """Test the 3-step model update logic."""
        # Simulate JSON data → verify correct model updates

    def test_config_defaults(self):
        """Verify all config keys have defaults."""
        config = Path("widget/contents/config/main.xml").read_text()
        # Check all keys have default values
```

#### Seviye 3: İntegrasyon Testleri
```bash
# plasma-test.sh
# 1. Daemon'ı başlat
# 2. Widget'ı plasma壳 (plasmashell) ile yükle
# 3. JSON verisi gönder
# 4. Widget görüntüsünü doğrula
```

### Güvenlik Düzeltmesi (shell injection)
```qml
// Güvenli versiyon:
property string tuiCommand: {
    var cmd = plasmoid.configuration.tuiCommand || "kportwatch";
    // Whitelist yaklaşımı: sadece bilinen komutlara izin ver
    var allowed = ["kportwatch", "konsole -e kportwatch", "alacritty -e kportwatch"];
    return allowed.indexOf(cmd) >= 0 ? cmd : "kportwatch";
}
```

### Uygulama Öncelikleri
1. **Hemen**: `qmllint` CI adımı ekle (5 dakika)
2. **Kısa vadeli**: Shell injection düzeltmesi + statik testler (1 gün)
3. **Orta vadeli**: Model reconciliation birim testleri (2-3 gün)
4. **Uzun vadeli**: Headless Plasma widget testleri (1 hafta)

---

## 4. Performance Regression Testleri

### Mevcut Durum
Kapsam: %0 — hiçbir performance testi yok.

Potansiyel performans sorunları:
| Kaynak | Risk | Etki |
|--------|------|------|
| `ioctl` her arayüz için her yenilemede | YÜKSEK | TUI donması |
| `_render_map` her çağrıda deep copy | ORTA | Gereksiz bellek |
| `psutil.net_io_counters()` her poll | ORTA | CPU kullanımı |
| ConnectionLog sınırsız büyüyebilir | DÜŞÜK | Bellek sızıntısı |
| Baseline dosya parse her SIGHUP | DÜŞÜK | Gecikme |

### Önerilen Test Çerçevesi

```python
# tests/test_performance.py
import time
import pytest
from unittest.mock import patch, MagicMock

class TestDaemonPerformance:
    """Performance regression tests for the daemon."""

    def test_snapshot_build_under_50ms(self):
        """Snapshot creation should complete in under 50ms with 1000 connections."""
        from backend.daemon_controller import DaemonController
        # 1000 bağlantılı sahne oluştur
        entries = [make_socket_entry(port=i) for i in range(1000)]

        start = time.perf_counter()
        snapshot = controller._build_snapshot(entries, [], traffic={}, alerts=[])
        elapsed = time.perf_counter() - start

        assert elapsed < 0.050, f"Snapshot build took {elapsed*1000:.1f}ms (>50ms)"

    def test_alert_engine_under_10ms(self):
        """Alert analysis should complete in under 10ms with 500 ports."""
        from backend.alert_engine import AlertEngine
        engine = AlertEngine(set(), {})
        listening = [make_socket_entry(port=i) for i in range(500)]

        start = time.perf_counter()
        alerts = engine.analyze(listening, frozenset())
        elapsed = time.perf_counter() - start

        assert elapsed < 0.010, f"Alert analysis took {elapsed*1000:.1f}ms (>10ms)"

    def test_history_write_under_100ms(self):
        """History file write should complete in under 100ms."""
        from backend.history import HistoryRecorder
        # 10.000 girdilik sahne oluştur
        ...

    def test_notification_rate_limit_memory(self):
        """Rate limiter should not grow unbounded."""
        # 10.000 bildirim simüle et
        # Bellek kullanımını doğrula

class TestTUIPerformance:
    """Performance tests for TUI rendering."""

    def test_port_table_render_under_16ms(self):
        """Port table should render within one frame (60fps = 16ms)."""
        # 100 port ile PortTable oluştur
        # Render süresini ölç

    def test_connection_log_trim_efficiency(self):
        """Connection log trim should be O(1), not O(n)."""
        # 10.000 girdi ekle
        # Trim süresini ölç

    def test_map_render_under_50ms(self):
        """Connection map render should complete in under 50ms."""
        # 50 bağlantı ile harita oluştur
        # Render süresini ölç
```

### CI Entegrasyonu

```yaml
# .github/workflows/ci.yml
- name: Performance regression tests
  run: |
    .venv/bin/python -m pytest tests/test_performance.py -v \
      --timeout=60 \
      --json-report --json-report-file=perf-report.json
  # Performance testleri non-blocking (başarısız olsa CI kırmaz)
  continue-on-error: true
```

### Performans Metrik Hedefleri

| Bileşen | Hedef | Maksimum |
|---------|-------|----------|
| Snapshot oluşturma (1000 bağlantı) | <30ms | 50ms |
| Alert analizi (500 port) | <5ms | 10ms |
| Port table render (100 port) | <10ms | 16ms |
| Connection map render (50 bağlantı) | <30ms | 50ms |
| History yazma (10000 girdi) | <50ms | 100ms |
| Bellek büyümesi (1 saat) | <10MB | 50MB |

### Uygulama Adımları
1. `tests/test_performance.py` oluştur + temel metrik testleri ekle
2. CI'a non-blocking performans adımı ekle
3. `pytest-benchmark` entegrasyonu (opsiyonel)
4. Bellek profilleme (opsiyonel — `memory_profiler`)
5. Performance dashboard (grafana/github actions annotation)

---

## Öncelik Sırası

| Öncelik | Görev | Tahmini Süre | Risk |
|---------|-------|-------------|------|
| **P1** | Widget QML testleri + shell injection fix | 1-2 gün | Düşük |
| **P2** | Connection map dosya tabanlı yap | 0.5 gün | Çok düşük |
| **P3** | Performance regression testleri | 1 gün | Düşük |
| **P4** | DaemonController decomposition | 3-5 gün | Orta |

**Önerilen sıralama:** P1 → P2 → P3 → P4

P1 ve P2 hızlı kazanım (quick win). P3 foundation sağlar. P4 en büyük değişiklik ama en yüksek uzun vadeli fayda.
