# KPortWatch Tech Stack Analizi

## Mevcut Stack Özeti

| Katman | Teknoloji | Versiyon | Boyut |
|--------|-----------|----------|-------|
| Dil | Python | 3.14.5 | — |
| TUI Framework | Textual | 8.2.7 | 7.6 MB |
| Rich (Textual dependency) | Rich | 15.0.0 | 3.3 MB |
| Widget | QML + Kirigami (Plasma 6) | Qt 6.x | 36 KB |
| Build | setuptools | 82.0.1 | — |
| Test | pytest + pytest-asyncio | 9.0.3 | — |
| Config | TOML (tomllib) | stdlib | — |
| IPC | JSON file + Unix socket | stdlib | — |
| Service | systemd user service | — | — |

**Proje boyutu:** 626 KB (Python: 468 KB, QML: 36 KB)
**Test:** 413 test, hepsi geçiyor
**Runtime dependencies:** sadece `textual` ve `rich` (2 paket)

---

## 🟢 Neler İyi?

### 1. Minimal Dependency Politikası
Sadece 2 runtime dependency (`textual`, `rich`). Backend tamamen stdlib ile çalışıyor — `/proc` parsing, JSON okuma/yazma, Unix socket, DNS lookup, signal handling... Hepsi Python stdlib. Bu çok temiz bir yaklaşım.

### 2. Python'ın Bu Proje İçin Doğru Seçim Olması
- `/proc` dosya sistemini okumak Python'da çok doğal (file I/O + string parsing)
- KDE Plasma zaten Qt/Python bağlantılarına sahip
- Network monitoring araçları Python ekosisteminde olgun (scapy, psutil vb.)
- Hızlı geliştirme, okunabilir kod
- Arch Linux'te Python her zaman mevcut

### 3. TOML Config Sistemi
`tomllib` (Python 3.11+ stdlib) ile TOML tabanlı config. İyi tasarlanmış: hardcoded defaults → TOML dosyası → CLI override öncelik sırası. Dataclass-based `AppConfig` ile tip güvenliği var.

### 4. Atomic JSON Writes
`write_snapshot()` — tmp dosyaya yaz → `os.replace()` ile atomic rename. Widget/TUI asla yarım okuma yapmıyor. Bu doğru bir pattern.

### 5. QML Widget Seçimi
KDE Plasma 6 plasmoid yazmak için QML tek seçenek zaten. Kirigami component'leri kullanılıyor (PromptDialog, InlineMessage, SearchField). Bu doğru.

---

## 🟡 Sorunlu Alanlar

### 1. Textual — Ağır Bir TUI Framework (~11 MB)

**Mevcut durum:** Textual 8.2.7 + Rich 15.0.0 = ~11 MB runtime dependency.

**Sorun:**
- Textual, "terminal framework" olmaktan çıkıp neredeyse bir web framework'e dönüştü. CSS-based styling, reactive programming, widget tree, async event loop... Bunların hepsi bir network monitor TUI'si için overkill.
- Textual'ın cold start süresi ~200-400ms. Basit bir `curses` veya `urwid` uygulaması ~20-50ms'de açılır.
- Textual'ın memory footprint'i ~30-50 MB (kendi heap + rich text rendering buffer). Basit bir terminal UI için fazla.
- Rich'i kullanmak için Textual'a ihtiyaç yok — Rich standalone de kullanılabilir.

**Alternatifler:**

| Framework | Boyut | Start | Memory | Komplekslik |
|-----------|-------|-------|--------|-------------|
| **Textual** (mevcut) | ~11 MB | ~300ms | ~40 MB | Yüksek |
| **urwid** | ~800 KB | ~30ms | ~5 MB | Orta |
| **curses** (stdlib) | 0 | ~10ms | ~2 MB | Düşük |
| **Rich + prompt_toolkit** | ~3 MB | ~50ms | ~10 MB | Orta |

**Öneri:** Textual'ı değiştirmek büyük bir rewrite gerektirir. Şu anki durumda **kalmaya devam edin** — ama yeni projelerde daha hafif alternatifler değerlendirin. Textual'ın getirdiği CSS styling, reactive state, widget composability güzel ama bir network monitor için zorunlu değil.

### 2. `/proc` Parsing — Manuel vs psutil

**Mevcut durum:** `backend/parsers/` altında manuel `/proc/net/tcp`, `/proc/net/udp`, `/proc/[pid]/stat` parsing. Toplam ~700 satır parsing kodu.

**Sorun:**
- `/proc/net/tcp` formatı kernel versiyonları arasında değişebilir
- Edge case'ler çok (IPv6 mapping, huge inode numbers, zombie processes)
- Kendi `netstat`/`ss` implementasyonunuzu yazıyorsunuz

**Alternatif:**
```python
# psutil ile aynı bilgi
import psutil
for conn in psutil.net_connections(kind='inet'):
    print(conn.laddr, conn.raddr, conn.status, conn.pid)
```

| Yaklaşım | Kod Miktarı | Bağımlılık | Bakım |
|----------|------------|------------|-------|
| Manuel `/proc` parsing | ~700 satır | 0 | Yüksek |
| `psutil.net_connections()` | ~50 satır | psutil (~2 MB) | Düşük |
| `ss -tupln` shell out | ~30 satır | iproute2 (zaten kurulu) | Çok düşük |

**Öneri:** `psutil` ekleyin. Network connection parsing'i `psutil`'a bırakın. `/proc` parsing'ini kaldırın veya fallback olarak tutun. Bu ~700 satırı ~50 satıra indirir, kernel format değişikliklerinden sizi korur. `psutil` Linux monitoring araçlarında endüstri standardı.

### 3. Widget ↔ Daemon İletişimi: `cat` + JSON

**Mevcut durum:** Widget her 2 saniyede `cat` ile JSON dosyası okuyor. Tüm snapshot parse ediliyor (~processes dict 100KB+ olabilir).

**Sorun:**
- Shell spawn overheadi her 2 saniye
- Widget kullanmadığı halde `processes` ve `geo_stats` verisini parse ediyor
- Atomic write olsa da, `cat` ile okuma arasında timing race var

**Daha iyi alternatifler:**

| Yöntem | Açıklama | Pros | Cons |
|--------|---------|------|------|
| **D-Bus** | Daemon D-Bus service expose eder | Plasma'nın native IPC'si, QML'den doğrudan erişim | D-Bus boilerplate |
| **Signals/Slots via Qt** | Python Qt binding ile daemon çalışır | En verimli, gerçek zamanlı | Qt dependency daemon'a ekler |
| **İki ayrı JSON dosyası** | Widget-only payload ayrı yazılır | Basit implementasyon | Çift disk yazımı |
| **Shared memory (mmap)** | Daemon shared memory yazar | Sıfır I/O overhead | Kompleks implementasyon |

**Öneri:** En pragmatik çözüm **iki ayrı JSON dosyası**. Daemon zaten `write_snapshot()` yapıyor — yanında `write_widget_snapshot()` ile `processes` ve `geo_stats` olmadan ikinci bir dosya yazsın. Widget bu dosyayı okusun. Tek dosyalık değişiklik.

### 4. systemd Service'te Hardcoded Path

**Mevcut sorun:**
```ini
ExecStart=%h/Projects/KPortWatch/.venv/bin/python -m backend.kportwatch_daemon --foreground
WorkingDirectory=%h/Projects/KPortWatch
```

Bu `%h/Projects/KPortWatch` herkeste farklı. `pip install` sonrası entry point `~/.local/bin/kportwatch-daemon` olmalı.

**Öneri:**
```ini
ExecStart=%h/.local/bin/kportwatch-daemon --foreground
```

### 5. Python 3.14 Kullanımı

**Mevcut durum:** Python 3.14.5 ile çalışıyorsunuz. `pyproject.toml` `>=3.10` diyor.

**Sorun:**
- Python 3.14 çok yeni (Mayıs 2026). Çoğu Linux dağıtımında henüz yok.
- `tomllib` Python 3.11+ gerektiriyor — 3.10 ile uyumsuz
- Install script'te `pip install -e .` Python 3.14'te bazı sorunlar yaşıyor (`getpath null-char issue`)

**Öneri:** `requires-python = ">=3.11"` yapın (tomllib için zaten gerekli). Install script'teki Python 3.14 workaround'larını temizleyin.

---

## 🔴 Kritik Olmayan Ama İyi Olacak Değişiklikler

### 6. Build System: setuptools → hatchling veya flit

**Neden:** setuptools iyi çalışıyor ama daha modern ve minimal alternatifler var:

| Build Tool | Config | Özellik |
|------------|--------|---------|
| setuptools | pyproject.toml | Klasik, her yerde desteklenir |
| **hatchling** | pyproject.toml | Hızlı, modern, versiyonlama built-in |
| **flit** | pyproject.toml | Ultra-minimal, pure Python için ideal |

**Öneri:** setuptools ile devam edin. Değiştirmeye gerek yok — çalışıyor ve her CI ortamında destekleniyor. Ama eğer rewrite yapıyorsanız `hatchling` daha temiz.

### 7. Test Coverage ve Tooling

**Mevcut:** 413 test var (çok iyi!), ama coverage ölçümü yok. Ruff veya mypy da yok.

**Eklenecekler:**

```toml
[project.optional-dependencies]
dev = [
    "pytest>=7.0",
    "pytest-asyncio",
    "pytest-cov",       # Coverage reporting
]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.mypy]
python_version = "3.11"
warn_return_any = true
```

**Öneri:** `ruff` ekleyin (hem linter hem formatter, `flake8` + `black` + `isort` yerine tek araç). CI pipeline'a `ruff check` ve `pytest --cov` ekleyin.

### 8. TUI Themes — 320 Satır Hardcoded CSS

**Mevcut:** `tui/themes.py` 320 satır. 4 tema var (dark, nord, solarized, light). Her tema için inline CSS string üretiliyor.

**Daha iyi yaklaşım:** Textual'ın native theme sistemini kullanın (Textual 0.80+). TCSS dosyalarında CSS custom properties ile tema değişkenlerini tanımlayın, Python'da string interpolation ile CSS üretmek yerine.

### 9. Error Monitoring / Telemetry

Hiçbir crash reporting yok. Daemon crash olursa sadece systemd journal'a yazar. Kullanıcı hatayı göremez.

**Öneri:** Basit bir crash log dosyası: `~/.local/share/kportwatch/crash.log`. Daemon'un `__main__` bloğunda global exception handler ile yazın.

---

## 📊 Öncelik Sıralaması

| Öncelik | Değişiklik | Efor | Etki |
|---------|-----------|------|------|
| 🔴 1 | systemd service path fix | 5 dk | Kullanıcılar kuramıyor |
| 🔴 2 | `requires-python = ">=3.11"` | 2 dk | Python 3.10 ile bozuluyor |
| 🟡 3 | `psutil` ile `/proc` parsing'i basitleştir | 2-3 gün | ~700 satır → ~50 satır |
| 🟡 4 | Widget-only JSON payload (ikinci dosya) | 3-4 saat | Widget performansı %50+ iyileşir |
| 🟡 5 | `ruff` ekle | 1 saat | Kod kalitesi |
| 🟢 6 | `pytest-cov` ile coverage | 30 dk | Test kalitesi |
| 🟢 7 | Textual theme sistemine geçiş | 3-4 saat | Temizlik |
| 🟢 8 | Crash log dosyası | 30 dk | Debugging |

---

## 🎯 Sonuç

**Stack doğru mu?** Evet, büyük resimde. Python + Textual + QML üçlüsü bir KDE network monitorü için makul. Tek değişmesi gereken şey manuel `/proc` parsing yerine `psutil` kullanmak.

**En kritik 3 değişiklik:**
1. **systemd path fix** — şu an başka birinede çalışmaz
2. **`requires-python >= 3.11`** — tomllib zaten 3.11 gerektiriyor
3. **`psutil` ile parsing basitleştirme** — en çok bakım yükü olan alan

**Textual'ı değiştirmeli mi?** Hayır. Rewrite maliyeti, kazanacaınız RAM/startup süresinden çok daha fazla. Ama Textual'ı **sadece** TUI için kullanın, backend'den tamamen bağımsız tutun (zaten öyle).
