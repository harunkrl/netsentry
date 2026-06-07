# KPortWatch — Kapsamlı Proje Analiz Raporu

> **Amaç**: Bu rapor, KPortWatch projesinin tüm kaynak kodunu, testlerini, CI/CD pipeline'ını, kurulum scriptlerini ve dokümantasyonunu detaylıca inceleyerek tespit edilen sorunları ve iyileştirme önerilerini sunar.
> Bir **coding agent'ın** bu raporu okuyarak doğrudan implementasyona geçebilmesi hedeflenmiştir.

> [!IMPORTANT]
> Her madde **Öncelik** (🔴 Kritik / 🟠 Yüksek / 🟡 Orta / 🟢 Düşük) ile işaretlenmiştir.
> Kritik ve yüksek öncelikli maddeler önce ele alınmalıdır.

---

## İçindekiler

1. [Kritik Bug'lar](#1-kritik-buglar)
2. [Güvenlik Açıkları](#2-güvenlik-açıkları)
3. [Performans Sorunları](#3-performans-sorunları)
4. [Mimari ve Tasarım Sorunları](#4-mimari-ve-tasarım-sorunları)
5. [Kod Duplikasyonu](#5-kod-duplikasyonu)
6. [TUI / Widget UI/UX Sorunları](#6-tui--widget-uiux-sorunları)
7. [Test Sorunları](#7-test-sorunları)
8. [CI/CD Sorunları](#8-cicd-sorunları)
9. [Kurulum, Sistem Entegrasyonu & Repository Hijyeni](#9-kurulum-sistem-entegrasyonu--repository-hijyeni)
10. [Dokümantasyon](#10-dokümantasyon)

---

## 1. Kritik Bug'lar

### 1.1 🔴 psutil Import'ları `_HAS_PSUTIL` Guard'ı Olmadan Yapılıyor

**Dosya**: [kportwatch_daemon.py](file:///home/lenovo/Projects/KPortWatch/backend/kportwatch_daemon.py) satır 46–57

**Sorun**: `from backend.collectors.psutil_collector import (collect_connections as _psutil_connections, ...)` import'ları `_HAS_PSUTIL` kontrolü dışında yapılıyor. Eğer `psutil` paketi yüklü değilse, daemon import anında crash eder — runtime'da değil.

**Çözüm**:
```python
_HAS_PSUTIL = False
try:
    import psutil
    from backend.collectors.psutil_collector import (
        collect_connections as _psutil_connections,
        # ...
    )
    _HAS_PSUTIL = True
except ImportError:
    _psutil_connections = None
    # diğer fallback'ler
```

---

### 1.2 🔴 `args.interval` Her Zaman Config'i Override Ediyor

**Dosya**: [kportwatch_daemon.py](file:///home/lenovo/Projects/KPortWatch/backend/kportwatch_daemon.py) satır 319, 540

**Sorun**: `interval = args.interval` kullanılıyor. `argparse` default değer verdiği için `args.interval` her zaman bir değere sahip — bu TOML config'deki `poll_interval` ayarını tamamen geçersiz kılıyor.

**Çözüm**: argparse'de `default=None` kullan, ardından config'den oku:
```python
parser.add_argument("--interval", type=float, default=None, ...)

# daemon_loop içinde:
interval = args.interval if args.interval is not None else cfg.poll_interval
```

---

### 1.3 🔴 `_wait_for(None)` Hiçbir Zaman Başarılı Olmaz

**Dosya**: [kportwatchctl.py](file:///home/lenovo/Projects/KPortWatch/backend/kportwatchctl.py) satır 209

**Sorun**: `_wait_for(None, timeout=5.0)` çağrılıyor. Fonksiyonun mantığı (satır 65–73):
```python
is_alive = _is_alive(pid) if pid else False
```
`pid=None` ve `alive=True` ile çağrıldığında, `is_alive` her zaman `False` olur → fonksiyon hiçbir zaman başarılı olmaz. `restart` komutu yanlış durumu raporlar.

**Çözüm**: PID dosyasından PID oku, veya fonksiyonu PID dosyasının oluşmasını bekleyecek şekilde güncelle:
```python
def _wait_for_pid_file(timeout: float = 5.0) -> int | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with open(PID_FILE) as f:
                return int(f.read().strip())
        except (FileNotFoundError, ValueError):
            time.sleep(0.2)
    return None
```

---

### 1.4 🔴 `--last` Argümanı Parse Ediliyor Ama Kullanılmıyor

**Dosya**: [export.py](file:///home/lenovo/Projects/KPortWatch/backend/export.py) satır 54–59, 84–86

**Sorun**: `parser.add_argument("--last", type=int, default=None, ...)` tanımlanıyor ama export fonksiyonlarına `args.last` hiç geçirilmiyor.

**Çözüm**: Export fonksiyonlarına `last` parametresini ekle ve çağrı noktalarında `args.last` geçir:
```python
count = export_history_csv(outpath, date=args.date, event_type=args.type, last=args.last)
```

---

### 1.5 🔴 Python Versiyon Uyumsuzluğu (3.10 vs 3.11)

**Sorun**: Kritik bir tutarsızlık var:

| Kaynak | Versiyon |
|---|---|
| [pyproject.toml](file:///home/lenovo/Projects/KPortWatch/pyproject.toml) satır 20 | `requires-python = ">=3.11"` |
| [README.md](file:///home/lenovo/Projects/KPortWatch/README.md) satır 10, 119, 420 | "Python 3.10+" |
| [install.sh](file:///home/lenovo/Projects/KPortWatch/install.sh) satır 24 | `>= (3, 10)` kontrolü |
| [ci.yml](file:///home/lenovo/Projects/KPortWatch/.github/workflows/ci.yml) satır 21 | `["3.10", "3.11", "3.12"]` matrix |

**Etki**: CI Python 3.10'da çalışır ama pip, `>=3.11` gereksinimi yüzünden paketi yüklemeyi reddeder.

**Çözüm**: Tek bir gerçek belirle:
- `pyproject.toml`'u `>=3.10`'a düşür VEYA
- Tüm diğer referansları `3.11+` olarak güncelle
- CI matrix'ini buna göre ayarla

---

### 1.6 🔴 `SelectableRow.ValueChanged` Textual Message Değil

**Dosya**: [settings_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/settings_screen.py) satır 202–207

**Sorun**: `ValueChanged` düz bir sınıf, `textual.message.Message` alt sınıfı değil. `post_message()` çağrısı (satır 200) Textual'ın mesaj sisteminde düzgün çalışmaz. `on_selectable_row_value_changed` handler'ı (satır 613) Textual'ın standart mesaj bubbling'i ile tetiklenmez.

**Çözüm**:
```python
from textual.message import Message

class SelectableRow(Static):
    class ValueChanged(Message):
        def __init__(self, row: "SelectableRow", value: str) -> None:
            super().__init__()
            self.row = row
            self.value = value
```

---

### 1.7 🔴 `self.app` Erişimi `__init__`'de (Mount Öncesi)

**Dosyalar**:
- [connection_map_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/connection_map_screen.py) satır 194
- [process_tree_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/process_tree_screen.py) satır 67–69

**Sorun**: `app = self.app` Screen `__init__()` içinde çağrılıyor. Textual'da Screen push edilmeden önce `self.app` mevcut değil — hata fırlatır veya `None` döner.

**Çözüm**: Bu erişimleri `on_mount()` lifecycle hook'una taşı:
```python
def on_mount(self) -> None:
    self.data_provider = getattr(self.app, 'data_provider', None) or DataProvider()
```

---

### 1.8 🔴 Widget `safePorts` Config'i `main.xml`'de Tanımlı Değil

**Dosya**: [ConfigGeneral.qml](file:///home/lenovo/Projects/KPortWatch/widget/contents/ui/config/ConfigGeneral.qml) satır 19, [main.xml](file:///home/lenovo/Projects/KPortWatch/widget/contents/config/main.xml)

**Sorun**: `cfg_safePorts` referans ediliyor ve `safePortsField.text`'e bağlanıyor, ama `main.xml`'de `<entry name="safePorts">` tanımı yok. Bu ayar plasmoid restart'larında kaybolur.

**Çözüm**: `main.xml`'e entry ekle:
```xml
<entry name="safePorts" type="String">
  <default></default>
</entry>
```

---

## 2. Güvenlik Açıkları

### 2.1 🔴 Widget'ta Shell Injection Riski

**Dosya**: [main.qml](file:///home/lenovo/Projects/KPortWatch/widget/contents/ui/main.qml) satır 378

**Sorun**: PID string concatenation ile shell komutuna enjekte ediliyor:
```javascript
killExecSource.connectedSources = ["sh -c 'kportwatchctl kill " + pid + "'"]
```
`pid` değeri parse edilen JSON'dan geliyor ve integer olarak doğrulanmıyor. Kötü niyetli bir JSON dosyası shell injection yapabilir.

**Çözüm**: PID'yi integer'a çevir ve doğrula:
```javascript
var safePid = parseInt(pid, 10);
if (isNaN(safePid) || safePid <= 0) return;
killExecSource.connectedSources = ["kportwatchctl kill " + safePid];
```

---

### 2.2 🟠 `daemon_kill_process()` Yetki Kontrolü Yok

**Dosya**: [kportwatch_daemon.py](file:///home/lenovo/Projects/KPortWatch/backend/kportwatch_daemon.py) satır 269–303

**Sorun**: Unix socket üzerinden gelen kill komutları hiçbir yetki kontrolü olmadan `os.kill(pid, signal.SIGTERM)` çağırıyor. Socket `chmod 0600` ile korunuyor (aynı kullanıcı), ama aynı kullanıcıda çalışan herhangi bir process kill komutu gönderebilir.

**Çözüm**:
1. Kill öncesi PID'nin gerçekten KPortWatch'un izlediği bir port'a ait olduğunu doğrula.
2. Allowlist/denylist mekanizması ekle (ör. sistem process'leri killemeye izin verme):
```python
PROTECTED_PIDS = {1}  # PID 1 (init/systemd) asla killenmez

def daemon_kill_process(pid: int) -> dict:
    if pid in PROTECTED_PIDS or pid <= 0:
        return {"error": f"PID {pid} korumalıdır"}
    # Verify the PID is in our tracked ports
    if not any(e.pid == pid for e in _last_entries):
        return {"error": f"PID {pid} izlenen portlarda bulunamadı"}
    os.kill(pid, signal.SIGTERM)
```

---

### 2.3 🟠 Auto-Update Signature Doğrulaması Yok

**Dosya**: [update.py](file:///home/lenovo/Projects/KPortWatch/backend/update.py) satır 157–163

**Sorun**: `perform_update()` `git pull` ve `pip install -e .` çalıştırıyor. Git remote ele geçirilirse keyfi kod çalıştırılır. GPG signature doğrulaması yapılmıyor.

**Çözüm**:
1. `git pull` sonrası `git verify-commit HEAD` veya `git verify-tag` ekle.
2. Başarısız signature durumunda update'i iptal et ve eski commit'e geri dön:
```python
verify = subprocess.run(["git", "verify-commit", "HEAD"], capture_output=True)
if verify.returncode != 0:
    subprocess.run(["git", "reset", "--hard", "HEAD~1"])
    return {"status": "error", "message": "Signature verification failed"}
```

---

### 2.4 🟠 GeoIP API'si HTTP Kullanıyor (HTTPS Değil)

**Dosya**: [geoip.py](file:///home/lenovo/Projects/KPortWatch/backend/parsers/geoip.py) satır 185–190

**Sorun**: `_api_url = "http://ip-api.com/json/"` — düz HTTP. MITM saldırısı ile sahte coğrafi konum verisi enjekte edilebilir.

**Çözüm**: ip-api.com'un free tier'ı sadece HTTP destekliyor. Alternatif:
1. Uyarı logu ekle: `logger.warning("GeoIP API uses HTTP - data may be tampered")`
2. Pro plan (HTTPS) desteği ekle veya başka bir ücretsiz HTTPS API kullan (ör. `ipinfo.io`)
3. Response'ları basit mantık kontrolleri ile doğrula (lat/lon aralığı, ülke kodu formatı)

---

### 2.5 🟠 `kportwatch_client.py`'de JSON Injection

**Dosya**: [kportwatch_client.py](file:///home/lenovo/Projects/KPortWatch/backend/kportwatch_client.py) satır 35

**Sorun**: f-string ile JSON çıktısı oluşturuluyor:
```python
print(f'{{"error": "Failed to connect to daemon socket: {e}"}}')
```
`e` mesajında tırnak veya özel JSON karakterleri varsa geçersiz JSON üretilir.

**Çözüm**:
```python
import json
print(json.dumps({"error": f"Failed to connect to daemon socket: {e}"}))
```

---

### 2.6 🟡 `save_config_setting()` Thread-Safe Değil

**Dosya**: [config.py](file:///home/lenovo/Projects/KPortWatch/shared/config.py) satır 550–595

**Sorun**: Config dosyası lock olmadan okunup regex ile düzenleniyor. Concurrent erişimde veri kaybı olabilir. Ayrıca section/key isimlerinde regex meta karakterleri sorun çıkarabilir.

**Çözüm**: Dosya kilitleme ve `tomli_w` (veya `tomllib` + yazma) kullan:
```python
import fcntl

def save_config_setting(section: str, key: str, value: Any) -> None:
    with open(CONFIG_PATH, 'r+') as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            content = f.read()
            # tomli_w ile doğru TOML yazımı
            data = tomllib.loads(content)
            data.setdefault(section, {})[key] = value
            f.seek(0)
            f.write(tomli_w.dumps(data))
            f.truncate()
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)
```

---

### 2.7 🟡 Unix Socket'te Mesaj Boyutu Sınırı Yok

**Dosya**: [unix_socket.py](file:///home/lenovo/Projects/KPortWatch/backend/writers/unix_socket.py) satır 167–174

**Sorun**: `send_command` fonksiyonu gelen veriyi sınırsız biriktirir:
```python
while True:
    chunk = sock.recv(4096)
    response_data += chunk
```

**Çözüm**: Maximum mesaj boyutu limiti ekle:
```python
MAX_RESPONSE_SIZE = 10 * 1024 * 1024  # 10MB

while True:
    chunk = sock.recv(4096)
    response_data += chunk
    if len(response_data) > MAX_RESPONSE_SIZE:
        raise ValueError("Response too large")
    if not chunk:
        break
```

---

## 3. Performans Sorunları

### 3.1 🟠 `build_inode_to_pid_map()` Her Cycle'da 2 Kez Çağrılıyor

**Dosya**: [kportwatch_daemon.py](file:///home/lenovo/Projects/KPortWatch/backend/kportwatch_daemon.py) satır 334–356

**Sorun**: Bu fonksiyon `/proc/*/fd/` altındaki tüm symlink'leri tarar (binlerce `readlink` syscall'ı). İlk kez satır 335'te, ikinci kez satır 355'te çağrılıyor.

**Çözüm**: Bir kez çağır, sonucu yeniden kullan:
```python
inode_map = build_inode_to_pid_map()  # Tek çağrı
uid_map = build_uid_process_map()

# ... inode_map'i yeniden kullan:
process_tree = build_process_tree(inode_map)  # inode_map_local yerine
```

---

### 3.2 🟠 PortTable'da O(n²) Satır Araması

**Dosya**: [port_table.py](file:///home/lenovo/Projects/KPortWatch/tui/widgets/port_table.py) satır 338–358

**Sorun**: `_find_row_index()` ve `_row_key_for()` tüm satırları `coordinate_to_cell_key()` ile iterate ediyor. Update döngüsünde her satır için çağrılıyor → O(n²).

**Çözüm**: Bir `row_key → index` dict cache'i tut:
```python
def _rebuild_row_index(self) -> None:
    self._key_to_index: dict[str, int] = {}
    for i in range(self.row_count):
        key = self.coordinate_to_cell_key(Coordinate(i, 0))
        self._key_to_index[str(key.value)] = i

def _find_row_index(self, key: str) -> int | None:
    return self._key_to_index.get(key)
```
Her tablo güncellemesinden sonra `_rebuild_row_index()` çağır.

---

### 3.3 🟠 Widget `reconcileModel()` O(n²) Sıralama

**Dosya**: [main.qml](file:///home/lenovo/Projects/KPortWatch/widget/contents/ui/main.qml) satır 340–352

**Sorun**: Reorder adımı nested loop kullanıyor — her eleman `i` için `i+1`'den ileriye tarayarak eşleşen key'i buluyor.

**Çözüm**: Bir key→index map oluştur:
```javascript
var keyToIndex = {};
for (var i = 0; i < model.count; i++)
    keyToIndex[model.get(i).key] = i;

for (var i = 0; i < sorted.length; i++) {
    var currentIdx = keyToIndex[sorted[i].key];
    if (currentIdx !== i) {
        model.move(currentIdx, i, 1);
        // Update index map after move
        // ...
    }
}
```

---

### 3.4 🟠 Blocking I/O Ana TUI Event Loop'unda

**Dosyalar**:
- [main_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/main_screen.py) satır 258: `action_export()` senkron dosya I/O
- [detail_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/detail_screen.py) satır 145–156: `get_geoip()` senkron ağ çağrısı `compose()` içinde
- [status_bar.py](file:///home/lenovo/Projects/KPortWatch/tui/widgets/status_bar.py) satır 83–89: senkron dosya I/O
- [traffic_bar.py](file:///home/lenovo/Projects/KPortWatch/tui/widgets/traffic_bar.py) satır 22–38: senkron `ioctl` syscall

**Çözüm**: Tüm I/O operasyonlarını `asyncio.to_thread` veya Textual'ın `run_worker` ile async yap:
```python
async def action_export(self) -> None:
    await asyncio.to_thread(self.provider.fetch)
    # ...

# veya Textual worker pattern:
@work(thread=True)
def do_export(self) -> None:
    self.provider.fetch()
    # ...
```

---

### 3.5 🟡 Risk Score Her Cycle'da Yeniden Hesaplanıyor

**Dosya**: [kportwatch_daemon.py](file:///home/lenovo/Projects/KPortWatch/backend/kportwatch_daemon.py) satır 418–427

**Sorun**: Listening socket'lar değişmese bile risk score her cycle'da yeniden hesaplanıyor.

**Çözüm**: Önceki listening port set'ini karşılaştır, sadece değişiklik varsa yeniden hesapla:
```python
listening_set = frozenset((e.local_port, e.proto) for e in listening)
if listening_set != self._prev_listening_set:
    risk_scores = {e.local_port: calculate_risk_score(e, ...) for e in listening}
    self._prev_listening_set = listening_set
```

---

### 3.6 🟡 Snapshot Hash'i String Bazlı

**Dosya**: [kportwatch_daemon.py](file:///home/lenovo/Projects/KPortWatch/backend/kportwatch_daemon.py) satır 481–483

**Sorun**: `str(sorted(...))` ile hash karşılaştırması — verimsiz string oluşturma.

**Çözüm**:
```python
current_hash = hash(frozenset(
    (e.local_port, e.proto, e.state) for e in listening
))
```

---

### 3.7 🟡 `scan_suspects` Property Her Erişimde Yeniden Hesaplanıyor

**Dosya**: [port_table.py](file:///home/lenovo/Projects/KPortWatch/tui/widgets/port_table.py) satır 592–595

**Sorun**: `scan_suspects` property `detect_port_scan()` fonksiyonunu her çağrıda tetikliyor, cache yok.

**Çözüm**: Sonucu cache'le, sadece veri güncellenince invalidate et:
```python
def _invalidate_scan_cache(self) -> None:
    self._scan_suspects_cache = None

@property
def scan_suspects(self) -> set:
    if self._scan_suspects_cache is None:
        self._scan_suspects_cache = detect_port_scan(self._entries)
    return self._scan_suspects_cache
```

---

### 3.8 🟡 History Dosyası Her Cycle'da Açılıp Kapanıyor

**Dosya**: [history.py](file:///home/lenovo/Projects/KPortWatch/backend/history.py) satır 77–84

**Çözüm**: Dosya handle'ını açık tut, periyodik flush yap:
```python
class History:
    def __init__(self):
        self._fh: IO | None = None
    
    def _ensure_file(self) -> IO:
        if self._fh is None or self._fh.closed:
            path = self._get_file_path()
            self._fh = open(path, "a")
        return self._fh
    
    def _append(self, data: dict) -> None:
        fh = self._ensure_file()
        fh.write(json.dumps(data) + "\n")
        fh.flush()
```

---

### 3.9 🟡 Dünya Haritası Her 2 Saniyede Sıfırdan Oluşturuluyor

**Dosya**: [connection_map_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/connection_map_screen.py) satır 84–139

**Sorun**: `_render_map()` 19×70 Unicode braille grid'ini her refresh'te sıfırdan oluşturuyor.

**Çözüm**: Harita grid'ini cache'le, sadece bağlantı noktaları (pinler) değiştiğinde güncelle. Base map sabit kalabilir.

---

### 3.10 🟡 ThreadPoolExecutor'lar Kapatılmıyor

**Dosyalar**:
- [rdns.py](file:///home/lenovo/Projects/KPortWatch/backend/parsers/rdns.py) satır 15
- [geoip.py](file:///home/lenovo/Projects/KPortWatch/backend/parsers/geoip.py) satır 33

**Sorun**: Module-level `ThreadPoolExecutor` instance'ları daemon kapanırken `shutdown()` ile kapatılmıyor.

**Çözüm**: Daemon cleanup fonksiyonunda `_executor.shutdown(wait=False)` çağır:
```python
# rdns.py
def shutdown():
    _executor.shutdown(wait=False)

# kportwatch_daemon.py cleanup
import backend.parsers.rdns as rdns
import backend.parsers.geoip as geoip

def cleanup():
    rdns.shutdown()
    geoip.shutdown()
```

---

## 4. Mimari ve Tasarım Sorunları

### 4.1 🟠 `daemon_loop()` 400 Satırlık Monolitik Fonksiyon

**Dosya**: [kportwatch_daemon.py](file:///home/lenovo/Projects/KPortWatch/backend/kportwatch_daemon.py) satır 182–584

**Sorun**: Tek bir fonksiyon şunları yapıyor: config yükleme, sinyal işleme, veri toplama (4 farklı kaynak), GeoIP zenginleştirme, rDNS zenginleştirme, alert analizi, risk puanlama, snapshot oluşturma, dosya yazma, socket broadcast, history kayıt, bildirim gönderme, update kontrolü, adaptive sleep.

**Çözüm**: Bir `DaemonController` sınıfına decompose et:
```python
class DaemonController:
    def __init__(self, config: Config):
        self.collector = DataCollector(config)
        self.enricher = DataEnricher(config)
        self.alerter = AlertEngine(config)
        self.writer = SnapshotWriter(config)
        self.notifier = Notifier(config)
    
    def cycle(self) -> None:
        entries = self.collector.collect()
        entries = self.enricher.enrich(entries)
        alerts = self.alerter.analyze(entries)
        self.writer.write(entries, alerts)
        self.notifier.notify(alerts)
```

---

### 4.2 🟠 Module-Level Mutable Global State Pattern

**Dosyalar**: [rdns.py](file:///home/lenovo/Projects/KPortWatch/backend/parsers/rdns.py), [geoip.py](file:///home/lenovo/Projects/KPortWatch/backend/parsers/geoip.py), [config.py](file:///home/lenovo/Projects/KPortWatch/shared/config.py)

**Sorun**: Module-level mutable global'ler lock-based senkronizasyon ile kullanılıyor. Test etmek zor, birden fazla instance çalıştırmak imkansız, gizli coupling var.

**Çözüm**: Sınıf tabanlı yaklaşıma geçiş:
```python
# Yerine:
rdns._MAX_CACHE_SIZE = cfg.dns_cache_size  # Encapsulation ihlali!

# Doğrusu:
class RDNSResolver:
    def __init__(self, max_cache_size: int = 1024):
        self._cache = {}
        self._max_cache_size = max_cache_size
    
    def get_hostname(self, ip: str) -> str | None:
        ...
```

---

### 4.3 🟠 Encapsulation İhlalleri

**Dosyalar**:
- [kportwatch_daemon.py](file:///home/lenovo/Projects/KPortWatch/backend/kportwatch_daemon.py) satır 190–191: `rdns._MAX_CACHE_SIZE = ...` (private var'a dışarıdan yazma)
- [kportwatch_daemon.py](file:///home/lenovo/Projects/KPortWatch/backend/kportwatch_daemon.py) satır 412, 423: `alert_engine._baseline_ports` (private var'a dışarıdan okuma)

**Çözüm**: Public API ekle:
```python
# rdns.py
def configure(max_cache_size: int, max_pending: int) -> None:
    global _MAX_CACHE_SIZE, _MAX_PENDING
    _MAX_CACHE_SIZE = max_cache_size
    _MAX_PENDING = max_pending

# alert_engine.py
def get_baseline_ports(self) -> frozenset[int]:
    return frozenset(self._baseline_ports)
```

---

### 4.4 🟠 Widget `main.qml` Monoliti (381 Satır)

**Dosya**: [main.qml](file:///home/lenovo/Projects/KPortWatch/widget/contents/ui/main.qml)

**Sorun**: Tek dosyada: veri çekme, parse, model yönetimi, filtreleme, sıralama, reconciliation, process kill, TUI başlatma, bildirim gönderme, trafik formatlama.

**Çözüm**: Ayrı QML/JS dosyalarına böl:
- `DataModel.qml` — Veri modeli ve parse mantığı
- `SortFilter.qml` — Sıralama ve filtreleme
- `main.qml` — Sadece layout ve bileşen kompozisyonu

---

### 4.5 🟡 DataProvider Singleton Değil

**Dosyalar**:
- [kportwatch_tui.py](file:///home/lenovo/Projects/KPortWatch/tui/kportwatch_tui.py) satır 60: `DataProvider()` oluşturulup `MainScreen`'e geçiriliyor
- [connection_map_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/connection_map_screen.py) satır 195
- [process_tree_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/process_tree_screen.py) satır 69

**Sorun**: `getattr(app, 'data_provider', None) or DataProvider()` — `__init__`'de `self.app` mevcut değilse (bkz. 1.7) yeni instance oluşur.

**Çözüm**: `on_mount()` lifecycle'ında `self.app.data_provider` kullan. Fallback'te yeni instance oluşturma.

---

### 4.6 🟡 Lazy Import'lar Dağınık

**Dosyalar**:
- [main_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/main_screen.py) satır 273, 283, 287, 295
- [settings_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/settings_screen.py) satır 516–518

**Sorun**: Circular import sorunlarını çözmek için fonksiyon içinde import yapılıyor.

**Çözüm**: `TYPE_CHECKING` guard'ı veya `Protocol` kullan:
```python
from __future__ import annotations
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tui.screens.help_screen import HelpScreen
```

---

### 4.7 🟡 Private IP Kontrolü Tutarsız ve Eksik

**Dosya**: [kportwatch_daemon.py](file:///home/lenovo/Projects/KPortWatch/backend/kportwatch_daemon.py) satır 364, 372

**Sorun**: `e.remote_ip.startswith(("127.", "::1", "0.0.0.0", "::"))` string prefix kontrolü yapılıyor. Bu `10.x.x.x`, `172.16–31.x.x`, `192.168.x.x` gibi private range'leri kaçırıyor. `geoip.py`'de ise `ipaddress` modülü ile doğru kontrol var.

**Çözüm**: `geoip.py`'deki `_is_private_ip()` fonksiyonunu `shared/` altına taşı ve her yerde kullan:
```python
# shared/network.py
import ipaddress

def is_private_ip(ip: str) -> bool:
    try:
        return ipaddress.ip_address(ip).is_private
    except ValueError:
        return False
```

---

## 5. Kod Duplikasyonu

### 5.1 🟠 `_read_file_safe()` İki Yerde Tanımlı

**Dosyalar**:
- [inode_map.py](file:///home/lenovo/Projects/KPortWatch/backend/parsers/inode_map.py) satır 14–20
- [process_tree.py](file:///home/lenovo/Projects/KPortWatch/backend/parsers/process_tree.py) satır 28–34

**Çözüm**: `shared/fs_utils.py` oluştur, fonksiyonu oraya taşı. Her iki dosyada import et.

---

### 5.2 🟠 Atomic File Write Pattern 6 Yerde Tekrarlanıyor

**Dosyalar**:
- [json_file.py](file:///home/lenovo/Projects/KPortWatch/backend/writers/json_file.py) satır 29–35, 52–55
- [alert_engine.py](file:///home/lenovo/Projects/KPortWatch/backend/alert_engine.py) satır 106–109
- [update.py](file:///home/lenovo/Projects/KPortWatch/backend/update.py) satır 122–125
- [geoip.py](file:///home/lenovo/Projects/KPortWatch/backend/parsers/geoip.py) satır 120–128
- [kportwatch_daemon.py](file:///home/lenovo/Projects/KPortWatch/backend/kportwatch_daemon.py) satır 73–77

**Çözüm**: `shared/fs_utils.py`'de yardımcı fonksiyon:
```python
import os
import tempfile

def atomic_write(path: str, data: str, mode: int = 0o644) -> None:
    dir_name = os.path.dirname(path)
    os.makedirs(dir_name, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dir_name)
    try:
        with os.fdopen(fd, 'w') as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except:
        os.unlink(tmp)
        raise
```

---

### 5.3 🟠 State/Color Mapping 4+ Yerde Duplike

**Dosyalar**:
- [themes.py](file:///home/lenovo/Projects/KPortWatch/tui/themes.py) satır 94–107: `STATE_COLOURS`
- [connection_log.py](file:///home/lenovo/Projects/KPortWatch/tui/widgets/connection_log.py) satır 21–34: `_STATE_COLOURS` (farklı format)
- [port_table.py](file:///home/lenovo/Projects/KPortWatch/tui/widgets/port_table.py) satır 29–45: `_ROW_COLOURS`, `_ROW_BG`
- [FullRepresentation.qml](file:///home/lenovo/Projects/KPortWatch/widget/contents/ui/FullRepresentation.qml) satır 255, 311–314: inline renk tanımları

**Çözüm**: Tek bir `shared/colors.py` modülünde tanımla, tüm dosyalardan oraya referans ver.

---

### 5.4 🟡 Row Formatting `_apply_diff_update()` ve `_rebuild_table()`'da Tekrarlıyor

**Dosya**: [port_table.py](file:///home/lenovo/Projects/KPortWatch/tui/widgets/port_table.py) satır 273–316, 432–454

**Çözüm**: `_format_row(entry, alert_map) -> tuple` helper fonksiyonu çıkar.

---

### 5.5 🟡 Alert Map Building 2 Yerde Tekrarlıyor

**Dosya**: [port_table.py](file:///home/lenovo/Projects/KPortWatch/tui/widgets/port_table.py) satır 224–228, 395–399

**Çözüm**: `_build_alert_map(alerts) -> dict` helper fonksiyonu çıkar.

---

### 5.6 🟡 Clipboard Copy Mantığı 3 Yerde Tekrarlıyor

**Dosyalar**:
- [main_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/main_screen.py) satır 428–437
- [detail_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/detail_screen.py) satır 232–236
- [connection_map_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/connection_map_screen.py) satır 469–473

**Çözüm**: `shared/clipboard.py` veya `tui/utils/clipboard.py`:
```python
def safe_copy_to_clipboard(text: str) -> bool:
    try:
        import pyperclip
        pyperclip.copy(text)
        return True
    except Exception:
        return False
```

---

### 5.7 🟡 `formatBytes` TUI ve Widget'ta Farklı İmplementasyon

**Dosyalar**:
- [traffic_bar.py](file:///home/lenovo/Projects/KPortWatch/tui/widgets/traffic_bar.py) satır 41–49: `_human_bytes()` (IEC binary: KiB/MiB)
- [main.qml](file:///home/lenovo/Projects/KPortWatch/widget/contents/ui/main.qml) satır 260–265: `formatBytes()` (SI decimal: KB/MB)

**Sorun**: Farklı birim sistemleri (KiB vs KB) — tutarsız kullanıcı deneyimi.

**Çözüm**: Tek bir birim sistemi belirle (IEC binary veya SI decimal) ve her yerde aynısını kullan.

---

### 5.8 🟡 CSS Duplikasyonu: SettingRow ve SelectableRow

**Dosya**: [settings_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/settings_screen.py) satır 33–71, 116–161

**Sorun**: %90 aynı CSS. `.setting-info`, `.setting-title`, `.setting-desc`, `:focus`, `:hover` kuralları kopyalanmış.

**Çözüm**: Ortak CSS'i bir base sınıfa veya Textual CSS dosyasına çıkar.

---

### 5.9 🟡 Filter Rebuilding Pattern 3 Yerde Tekrarlıyor

**Dosya**: [connection_log.py](file:///home/lenovo/Projects/KPortWatch/tui/widgets/connection_log.py) satır 122–127, 154–161, 166–174

**Çözüm**: `_reset_and_rebuild()` helper metodu çıkar.

---

## 6. TUI / Widget UI/UX Sorunları

### 6.1 🟠 Hardcoded Renkler Tema Değişimini Bozuyor

**Dosyalar**:
- [detail_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/detail_screen.py) satır 68, 70–73, 78–79, 96, 107, 128, 160, 179, 196–197, 211
- [settings_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/settings_screen.py) satır 38–65, 117–161, 227–271
- [connection_map_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/connection_map_screen.py) satır 169, 187

**Sorun**: `#00ff99`, `#008855`, `#0a2a1a`, `#0d0d0d` gibi hex renkler doğrudan kullanılıyor. "Daylight" (light) temasında bu renkler okunamaz hale geliyor.

**Çözüm**: Tüm hardcoded renkleri Textual tema değişkenleriyle değiştir:
```css
/* Yanlış: */
color: #00ff99;
background: #0d0d0d;

/* Doğru: */
color: $primary;
background: $surface;
```

---

### 6.2 🟠 Process Tree'de Kill Onayı Yok

**Dosya**: [process_tree_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/process_tree_screen.py) satır 342–364

**Sorun**: `action_kill()` doğrudan SIGTERM gönderiyor, `KillConfirmScreen` gibi bir onay diyaloğu yok. Yanlışlıkla `k` tuşuna basılması kritik bir process'i öldürebilir.

**Çözüm**: MainScreen'deki gibi `KillConfirmScreen` kullan:
```python
async def action_kill(self) -> None:
    if self._selected_pid:
        from tui.screens.kill_confirm import KillConfirmScreen
        await self.app.push_screen(KillConfirmScreen(self._selected_pid, self.provider))
```

---

### 6.3 🟡 Help Screen'de Tema Listesi Güncel Değil

**Dosya**: [help_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/help_screen.py) satır 58–63

**Sorun**: 3 tema listeleniyor ("Cyberpunk", "Midnight", "Hacker") ama `themes.py` satır 61–66'da 4 tema tanımlı ("Daylight" eksik).

**Çözüm**: Tema listesini `themes.py`'den dinamik olarak oku:
```python
from tui.themes import THEMES
theme_list = ", ".join(THEMES.keys())
```

---

### 6.4 🟡 `AVAILABLE_THEMES` Listesi Senkron Değil

**Dosya**: [settings_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/settings_screen.py) satır 24

**Sorun**: `AVAILABLE_THEMES = ["Cyberpunk", "Midnight", "Hacker"]` — "Daylight" eksik.

**Çözüm**: `themes.py`'den import et:
```python
from tui.themes import THEMES
AVAILABLE_THEMES = list(THEMES.keys())
```

---

### 6.5 🟡 Search Bar Davranışı Tutarsız

**Dosyalar**:
- [main_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/main_screen.py) satır 165: Tab → filtre korunur, search kapanır
- [connection_map_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/connection_map_screen.py) satır 228: Tab → search gizlenir, filtre temizlenir

**Çözüm**: Tutarlı davranış seç — Tab her yerde aynı şekilde çalışsın (filtreyi koru ve search bar'ı kapat).

---

### 6.6 🟡 Burst Threshold Toggle UX Kafa Karıştırıcı

**Dosya**: [settings_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/settings_screen.py) satır 341–349

**Sorun**: Sayısal bir değeri temsil etmek için boolean toggle kullanılıyor (ON=3, OFF=5). Kullanıcı slider veya sayısal giriş bekler.

**Çözüm**: `Input` widget'ı ile sayısal giriş veya ayrı bir `NumberInput` bileşeni kullan.

---

### 6.7 🟡 ProcessTreeScreen'de Search Başlangıçta Görünür

**Dosya**: [process_tree_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/process_tree_screen.py) satır 84–87

**Sorun**: Search `Input` widget'ında `classes="hidden"` yok, ekran açıldığında search bar görünür durumda.

**Çözüm**: `classes="hidden"` ekle veya `on_mount()`'da gizle.

---

### 6.8 🟡 Widget Kill Geri Bildirimi Yok

**Dosya**: [main.qml](file:///home/lenovo/Projects/KPortWatch/widget/contents/ui/main.qml) satır 372–375

**Sorun**: `killExecSource.onNewData` hiçbir şey yapmıyor — kullanıcıya başarı/başarısızlık geri bildirimi verilmiyor.

**Çözüm**: Sonucu parse edip desktop notification göster:
```javascript
onNewData: {
    var result = JSON.parse(data.stdout || "{}");
    if (result.error) {
        plasmoid.showPassiveNotification("Kill failed: " + result.error);
    } else {
        plasmoid.showPassiveNotification("Process killed successfully");
    }
}
```

---

### 6.9 🟢 ProcessTreeScreen `on_unmount` Cleanup Yok

**Dosya**: [process_tree_screen.py](file:///home/lenovo/Projects/KPortWatch/tui/screens/process_tree_screen.py) satır 100

**Sorun**: `set_interval(2.0, ...)` ayarlanıyor ama ekran kapandığında durdurulmuyor.

**Çözüm**:
```python
def on_mount(self) -> None:
    self._refresh_handle = self.set_interval(2.0, self._refresh_data)

def on_unmount(self) -> None:
    if self._refresh_handle:
        self._refresh_handle.stop()
```

---

## 7. Test Sorunları

### 7.1 🔴 CI Coverage Sadece 4 Modülü Ölçüyor

**Dosya**: [ci.yml](file:///home/lenovo/Projects/KPortWatch/.github/workflows/ci.yml) satır 40

**Sorun**: `--cov=backend.alert_engine --cov=backend.models --cov=backend.parsers --cov=backend.writers.json_file` — sadece 4 modül. Eksik modüller:
- `backend.parsers.geoip`, `backend.parsers.rdns`, `backend.parsers.process_tree`, `backend.parsers.net_dev`
- `backend.risk_score`, `backend.history`, `backend.update`
- `backend.writers.unix_socket`
- `backend.kportwatch_daemon`, `backend.kportwatchctl`
- `backend.collectors.psutil_collector`
- `tui.*` modülleri
- `shared.*` modülleri

**Çözüm**: Tüm modülleri kapsayan coverage:
```yaml
- run: pytest tests/ --cov=backend --cov=tui --cov=shared --cov-report=xml --cov-fail-under=70
```

---

### 7.2 🟠 `test_process_tree.py` Live /proc'a Bağımlı

**Dosya**: [test_process_tree.py](file:///home/lenovo/Projects/KPortWatch/tests/test_process_tree.py) satır 72–83

**Sorun**: `test_basic_tree()` ve `test_children_populated()` canlı `/proc` filesystem'a karşı çalışıyor. CI ortamında PID 1 ve 2'nin belirli isimlerle mevcut olması garanti değil → flaky test.

**Çözüm**: `/proc` erişimlerini mock'la:
```python
@pytest.fixture
def mock_proc_tree(tmp_path):
    # Sahte /proc yapısı oluştur
    ...
```

---

### 7.3 🟠 `test_proc_net.py`'de Dead Code

**Dosya**: [test_proc_net.py](file:///home/lenovo/Projects/KPortWatch/tests/test_proc_net.py) satır 230–293

**Sorun**: `TestParseAllProc.test_parse_all_proc_combines_all` satır 247–267'de kullanılmayan liste oluşturuyor, patch/unpatch etkisiz.

**Çözüm**: Dead code'u temizle, testi basitleştir.

---

### 7.4 🟡 Proje Kökünde Stray Test Dosyaları

**Dosyalar**:
- [test_tree_cursor.py](file:///home/lenovo/Projects/KPortWatch/test_tree_cursor.py) (971 bytes)
- [test_tree_rebuild.py](file:///home/lenovo/Projects/KPortWatch/test_tree_rebuild.py) (1750 bytes)

**Sorun**: Ad-hoc debug/test dosyaları proje kökünde. `testpaths = ["tests"]` nedeniyle pytest bunları keşfetmez.

**Çözüm**: İçeriklerini değerlendir:
- Geçerliyse `tests/` altına taşı ve uygun isimlendirmeyle yeniden adlandır
- Gereksizse sil

---

### 7.5 🟡 TUI ve Widget İçin Test Yok

**Sorun**: `tui/` ve `widget/` paketleri için hiçbir test mevcut değil.

**Çözüm**: Minimum test senaryoları oluştur:
```
tests/
├── test_tui/
│   ├── test_main_screen.py     # Ekran lifecycle, backend hatası
│   ├── test_port_table.py      # Tablo güncelleme, cursor korunması
│   ├── test_settings_screen.py # Ayar değişiklikleri
│   └── test_formatting.py      # format_bytes ve diğer yardımcılar
├── test_widget/
│   └── test_data_parsing.py    # parseSnapshot JS mantığı
```

Textual test framework'ü kullan:
```python
from textual.testing import AppTest

async def test_app_startup():
    async with AppTest(KPortWatchApp) as pilot:
        assert pilot.app.query_one(PortTable)
```

---

### 7.6 🟡 Coverage Eşik Değeri Düşük

**Dosya**: [ci.yml](file:///home/lenovo/Projects/KPortWatch/.github/workflows/ci.yml) satır 40

**Sorun**: `--cov-fail-under=60` — güvenlik odaklı bir araç için %60 çok düşük.

**Çözüm**: `--cov-fail-under=75` veya `80`'e yükselt. `pyproject.toml`'a da ekle:
```toml
[tool.coverage.report]
fail_under = 75
show_missing = true
```

---

## 8. CI/CD Sorunları

### 8.1 🟠 Python 3.13 Test Edilmiyor (Classifier Var)

**Dosyalar**: [pyproject.toml](file:///home/lenovo/Projects/KPortWatch/pyproject.toml) satır 32, [ci.yml](file:///home/lenovo/Projects/KPortWatch/.github/workflows/ci.yml) satır 21

**Sorun**: `pyproject.toml`'da `Programming Language :: Python :: 3.13` classifier'ı var ama CI matrix'inde 3.13 yok.

**Çözüm**: CI matrix'e `"3.13"` ekle:
```yaml
python-version: ["3.10", "3.11", "3.12", "3.13"]
```

---

### 8.2 🟠 Statik Analiz Eksiklikleri

**Dosya**: [ci.yml](file:///home/lenovo/Projects/KPortWatch/.github/workflows/ci.yml)

**Eksik adımlar**:
- Type checking (mypy/pyright)
- Security scanning (bandit)
- Bağımlılık güvenlik taraması (pip-audit)

**Çözüm**:
```yaml
- name: Type check
  run: mypy backend shared tui

- name: Security scan
  run: bandit -r backend shared -ll

- name: Dependency audit
  run: pip-audit
```

---

### 8.3 🟠 CI Build Testi Eksik Entry Point'lar

**Dosya**: [ci.yml](file:///home/lenovo/Projects/KPortWatch/.github/workflows/ci.yml) satır 92–93

**Sorun**: Sadece `kportwatch-daemon --help` ve `kportwatch-tui --help` test ediliyor. Eksik:
- `kportwatchctl --help`
- `kportwatch-client --help`
- `kportwatch-export --help`
- `kportwatch-update --help`

**Çözüm**: Tüm entry point'ları test et:
```yaml
- name: Test all entry points
  run: |
    kportwatch-daemon --help
    kportwatch-tui --help
    kportwatchctl --help
    kportwatch-export --help
```

---

### 8.4 🟡 Ruff Kuralları Yetersiz

**Dosya**: [pyproject.toml](file:///home/lenovo/Projects/KPortWatch/pyproject.toml) — `[tool.ruff]` bölümü

**Çözüm**: Ek kural setleri ekle:
```toml
[tool.ruff.lint]
select = [
    "E", "W",    # pycodestyle
    "F",          # pyflakes
    "I",          # isort
    "N",          # pep8-naming
    "UP",         # pyupgrade
    "S",          # bandit (security)
    "B",          # bugbear
    "C4",         # comprehensions
    "SIM",        # simplification
    "PTH",        # pathlib
    "RUF",        # ruff-specific
]
```

---

### 8.5 🟡 Dependabot GitHub Actions Takip Etmiyor

**Dosya**: [dependabot.yml](file:///home/lenovo/Projects/KPortWatch/.github/dependabot.yml)

**Çözüm**:
```yaml
- package-ecosystem: "github-actions"
  directory: "/"
  schedule:
    interval: "weekly"
```

---

### 8.6 🟡 Widget QML Dosyaları CI'da Doğrulanmıyor

**Sorun**: QML dosyaları hiçbir CI adımında syntax/lint kontrolünden geçmiyor.

**Çözüm**: `qmllint` adımı ekle veya en azından syntax doğrulama yap.

---

## 9. Kurulum, Sistem Entegrasyonu & Repository Hijyeni

### 9.1 🔴 Repository URL'leri Placeholder

**Dosyalar ve mevcut URL'ler**:

| Dosya | URL |
|---|---|
| [pyproject.toml](file:///home/lenovo/Projects/KPortWatch/pyproject.toml) satır 60 | `https://github.com/user/kportwatch` (placeholder) |
| [README.md](file:///home/lenovo/Projects/KPortWatch/README.md) satır 126 | `https://github.com/harunkrl/kportwatch.git` (doğru) |
| [systemd/kportwatch.service](file:///home/lenovo/Projects/KPortWatch/systemd/kportwatch.service) satır 20 | `https://github.com/user/kportwatch` (placeholder) |
| [contrib/systemd/kportwatch.service](file:///home/lenovo/Projects/KPortWatch/contrib/systemd/kportwatch.service) satır 20 | `https://github.com/user/kportwatch` (placeholder) |
| [polkit policy](file:///home/lenovo/Projects/KPortWatch/polkit/com.kportwatch.helper.policy) satır 7 | `https://github.com/kportwatch` (farklı placeholder) |

**Çözüm**: Tüm URL'leri `https://github.com/harunkrl/kportwatch` olarak güncelle.

---

### 9.2 🔴 Polkit Policy Dead Reference

**Dosya**: [com.kportwatch.helper.policy](file:///home/lenovo/Projects/KPortWatch/polkit/com.kportwatch.helper.policy) satır 18

**Sorun**: `/usr/local/bin/kportwatch-helper` referans ediliyor ama bu dosya `install.sh` tarafından hiç oluşturulmuyor ve hiçbir yerde dokümante edilmemiyor.

**Çözüm**: Ya helper binary'yi oluştur ve install.sh'a ekle, ya da polkit policy'yi mevcut entry point'lara referans verecek şekilde güncelle.

---

### 9.3 🟠 `install.sh` Fallback'te `psutil` Eksik

**Dosya**: [install.sh](file:///home/lenovo/Projects/KPortWatch/install.sh) satır 39–43

**Sorun**: Fallback install path `pip install --quiet textual rich` — sadece 2 bağımlılık yüklüyor, `psutil` eksik. Editable install başarısız olursa psutil kullanılamaz.

**Çözüm**: Fallback'e psutil ekle:
```bash
pip install --quiet textual rich psutil
```

---

### 9.4 🟠 Duplicate systemd Service Dosyaları

**Dosyalar**:
- [systemd/kportwatch.service](file:///home/lenovo/Projects/KPortWatch/systemd/kportwatch.service)
- [contrib/systemd/kportwatch.service](file:///home/lenovo/Projects/KPortWatch/contrib/systemd/kportwatch.service)

**Sorun**: İki dosya birebir aynı. `install.sh` satır 91 `systemd/` kullanıyor, `contrib/` kopyası ölü kod.

**Çözüm**: `contrib/systemd/kportwatch.service`'i sil veya `contrib/`'un amacını belirle ve symlink kullan.

---

### 9.5 🟠 Systemd Unit Güvenlik Sertleştirmesi Eksik

**Dosya**: [systemd/kportwatch.service](file:///home/lenovo/Projects/KPortWatch/systemd/kportwatch.service)

**Mevcut güvenlik** (satır 35–39): `ProtectSystem=strict`, `NoNewPrivileges=true` vb. zaten mevcut ama eksik olanlar:

```ini
[Service]
# Mevcut ayarlara ek olarak:
ProtectControlGroups=true
ProtectKernelModules=true
ProtectKernelTunables=true
RestrictNamespaces=true
RestrictRealtime=true
SystemCallFilter=@system-service
CapabilityBoundingSet=CAP_NET_ADMIN CAP_SYS_PTRACE
```

Ayrıca `ProtectHome=read-only` (satır 36) → `ProtectHome=true` + explicit `BindReadOnlyPaths=` olarak sıkılaştır.

---

### 9.6 🟠 Repo'da Olmaması Gereken Dosyalar

| Dosya | Neden |
|---|---|
| `backend-implement.log` | Implementasyon log dosyası |
| `tui-implement.log` | Implementasyon log dosyası |
| `widget-implement.log` | Implementasyon log dosyası |
| `.coverage` | Test coverage veri dosyası |
| `kportwatch.egg-info/` | Build artifact'i |
| `test_tree_cursor.py` | Proje kökünde stray test |
| `test_tree_rebuild.py` | Proje kökünde stray test |

**Sorun**: `.gitignore`'da `*.log` ve `.coverage` kuralları var ama bu dosyalar kural eklenmeden önce commit edilmiş.

**Çözüm**:
```bash
# Git'ten sil (diskten silme):
git rm --cached backend-implement.log tui-implement.log widget-implement.log
git rm --cached .coverage
git rm --cached -r kportwatch.egg-info/
```

---

### 9.7 🟡 `.gitignore` Tutarsızlıkları

| Satır | Kural | Sorun |
|---|---|---|
| 44 | `CHANGELOG.md` | CHANGELOG gitignore'da ama dosya tracked! Çelişkili. |
| 29 | `*.log` | Kural var ama 3 log dosyası tracked (önceden commit edilmiş) |
| 10 | `.coverage` | Kural var ama dosya tracked |

**Çözüm**: 
- `CHANGELOG.md`'yi `.gitignore`'dan çıkar (tracked olmalı)
- `git rm --cached` ile önceden commit edilmiş dosyaları tracking'den çıkar
- `.ruff_cache/` pattern'ini ekle

---

### 9.8 🟡 `uninstall.sh` Plasma'yı Uyarısız Yeniden Başlatıyor

**Dosya**: [uninstall.sh](file:///home/lenovo/Projects/KPortWatch/uninstall.sh) satır 56–58

**Sorun**: `plasmashell` onay almadan yeniden başlatılıyor — aktif masaüstü oturumunu bozar.

**Çözüm**: Kullanıcıya sor:
```bash
read -p "Plasma shell'i yeniden başlatmak istiyor musunuz? (y/N) " -n 1 -r
if [[ $REPLY =~ ^[Yy]$ ]]; then
    plasmashell --replace &
fi
```

---

### 9.9 🟡 `uninstall.sh` Kullanıcı Ayarlarını Uyarısız Siliyor

**Dosya**: [uninstall.sh](file:///home/lenovo/Projects/KPortWatch/uninstall.sh) satır 44

**Sorun**: `rm -rf "${HOME}/.config/kportwatch"` — tüm konfigürasyon onaysız siliniyor.

**Çözüm**: Purge vs remove seçeneği sun:
```bash
read -p "Konfigürasyon dosyaları silinsin mi? (y/N) " -n 1 -r
if [[ $REPLY =~ ^[Yy]$ ]]; then
    rm -rf "${HOME}/.config/kportwatch"
fi
```

---

### 9.10 🟡 Versiyon Uyumsuzluğu

| Kaynak | Versiyon |
|---|---|
| [pyproject.toml](file:///home/lenovo/Projects/KPortWatch/pyproject.toml) satır 16 | `version = "2.1.0"` |
| [install.sh](file:///home/lenovo/Projects/KPortWatch/install.sh) satır 13 | `v1.0.0` |
| [uninstall.sh](file:///home/lenovo/Projects/KPortWatch/uninstall.sh) satır 8 | `v1.0.0` |
| [CHANGELOG.md](file:///home/lenovo/Projects/KPortWatch/CHANGELOG.md) | Sadece v1.0.0 var |

**Çözüm**: 
1. install.sh ve uninstall.sh versiyonlarını `2.1.0` ile senkronize et
2. CHANGELOG.md'ye v2.0.0 ve v2.1.0 girişlerini ekle

---

## 10. Dokümantasyon

### 10.1 🟠 README "stdlib only" İddiası Yanlış

**Dosya**: [README.md](file:///home/lenovo/Projects/KPortWatch/README.md) satır 397, 420

**Sorun**: "Stdlib-only daemon — no external deps" yazıyor ama `psutil>=5.9` bir bağımlılık ([pyproject.toml](file:///home/lenovo/Projects/KPortWatch/pyproject.toml) satır 40). Ayrıca `textual` ve `rich` de bağımlılık.

**Çözüm**: README'deki bu ifadeleri düzelt:
```markdown
**Backend bağımlılıkları**: psutil >=5.9
**TUI bağımlılıkları**: textual >=0.40, rich
```

---

### 10.2 🟠 README Proje Yapısı Güncel Değil

**Dosya**: [README.md](file:///home/lenovo/Projects/KPortWatch/README.md) satır 202–278

**Eksik dosya/dizinler**:
- `backend/collectors/` ve `psutil_collector.py`
- `tui/themes.py`
- `tui/screens/settings_screen.py`
- `backend/kportwatchctl.py`

**Çözüm**: Proje yapısı bölümünü mevcut dosya ağacıyla güncelle.

---

### 10.3 🟠 README Badge'i Statik

**Dosya**: [README.md](file:///home/lenovo/Projects/KPortWatch/README.md) satır 13

**Sorun**: "413 passed" statik badge. Zamanla güncel olmayacak.

**Çözüm**: GitHub Actions dinamik badge'i kullan:
```markdown
![CI](https://github.com/harunkrl/kportwatch/actions/workflows/ci.yml/badge.svg)
```

---

### 10.4 🟡 `models.py`'de Encoding Artifact

**Dosya**: [models.py](file:///home/lenovo/Projects/KPortWatch/backend/models.py) satır 77

**Sorun**: `# Ö1: First-seen timestamp...` — `Ö1` bir typo veya encoding hatası gibi görünüyor.

**Çözüm**: Yorumu düzelt (muhtemelen madde numarası veya referans kodu olmalı).

---

### 10.5 🟡 Risk Score Ağırlıkları Belgelenmemiş

**Dosya**: [risk_score.py](file:///home/lenovo/Projects/KPortWatch/backend/risk_score.py)

**Sorun**: Puanlama ağırlıkları (80, 60, 40, 25, 15, 10) neden bu değerler seçildi belgelenmemiş.

**Çözüm**: Docstring veya yorum ile scoring metodolojisini açıkla.

---

### 10.6 🟡 Private API Kullanımı Belgelenmemiş

**Dosya**: [psutil_collector.py](file:///home/lenovo/Projects/KPortWatch/backend/collectors/psutil_collector.py) satır 43

**Sorun**: `psutil._common.sconn` private API kullanılıyor. psutil versiyonları arasında kırılabilir.

**Çözüm**: Yorum ekle ve public API alternatifi olup olmadığını kontrol et:
```python
# WARNING: psutil._common.sconn is a private type.
# This may break between psutil versions.
# TODO: Consider using psutil.net_connections() return type directly.
```

---

### 10.7 🟡 Widget QML Dosyalarında Dokümantasyon Yok

**Dosyalar**:
- [main.qml](file:///home/lenovo/Projects/KPortWatch/widget/contents/ui/main.qml)
- [FullRepresentation.qml](file:///home/lenovo/Projects/KPortWatch/widget/contents/ui/FullRepresentation.qml)
- [CompactRepresentation.qml](file:///home/lenovo/Projects/KPortWatch/widget/contents/ui/CompactRepresentation.qml)

**Çözüm**: Dosya başına açıklayıcı yorum bloğu ekle.

---

### 10.8 🟢 Stale Yorum Referansları

**Dosyalar**: TUI dosyaları genelinde

**Sorun**: `Ö1`, `Ö3`, `K2`, `K3`, `K5`, `K6`, `K8`, `Y15` gibi referanslar var ama açıklamaları yok.

**Çözüm**: Bu referansları temizle veya bir legend (açıklama tablosu) ekle.

---

## Özet — Öncelik Matrisi

### 🔴 Kritik (Hemen yapılmalı) — 10 madde
| # | Konu | Bölüm |
|---|---|---|
| 1 | psutil import guard eksik | 1.1 |
| 2 | args.interval config'i override ediyor | 1.2 |
| 3 | _wait_for(None) bug'ı | 1.3 |
| 4 | --last argümanı kullanılmıyor | 1.4 |
| 5 | Python versiyon uyumsuzluğu (3.10 vs 3.11) | 1.5 |
| 6 | SelectableRow.ValueChanged Message değil | 1.6 |
| 7 | self.app __init__'de erişim | 1.7 |
| 8 | Widget safePorts config eksik | 1.8 |
| 9 | Widget shell injection riski | 2.1 |
| 10 | Repository URL'leri placeholder | 9.1 |

### 🟠 Yüksek (Kısa vadede yapılmalı) — 23 madde
| # | Konu | Bölüm |
|---|---|---|
| 11 | Process kill yetki kontrolü | 2.2 |
| 12 | Auto-update signature doğrulaması | 2.3 |
| 13 | GeoIP HTTP (HTTPS değil) | 2.4 |
| 14 | JSON injection kportwatch_client | 2.5 |
| 15 | inode_map 2x çağrı | 3.1 |
| 16 | PortTable O(n²) araması | 3.2 |
| 17 | Widget reconcile O(n²) | 3.3 |
| 18 | Blocking I/O TUI event loop | 3.4 |
| 19 | daemon_loop monoliti | 4.1 |
| 20 | Module-level mutable globals | 4.2 |
| 21 | Encapsulation ihlalleri | 4.3 |
| 22 | Widget main.qml monoliti | 4.4 |
| 23 | _read_file_safe duplikasyonu | 5.1 |
| 24 | Atomic write 6x duplikasyon | 5.2 |
| 25 | State/color mapping 4x duplikasyon | 5.3 |
| 26 | Hardcoded renkler tema'yı bozuyor | 6.1 |
| 27 | Process tree'de kill onayı yok | 6.2 |
| 28 | CI coverage sadece 4 modül | 7.1 |
| 29 | test_process_tree live /proc bağımlılığı | 7.2 |
| 30 | Polkit dead reference | 9.2 |
| 31 | install.sh fallback psutil eksik | 9.3 |
| 32 | README "stdlib only" yanlış | 10.1 |
| 33 | README proje yapısı güncel değil | 10.2 |

### 🟡 Orta (Planlı iterasyonlarda yapılmalı) — 30 madde
| # | Konu | Bölüm |
|---|---|---|
| 34 | save_config_setting thread safety | 2.6 |
| 35 | Socket mesaj boyutu limiti | 2.7 |
| 36–40 | Performans iyileştirmeleri | 3.5–3.9 |
| 41 | ThreadPoolExecutor shutdown | 3.10 |
| 42–44 | Mimari iyileştirmeler | 4.5–4.7 |
| 45–49 | Kod duplikasyonu temizliği | 5.4–5.8 |
| 50–57 | UI/UX iyileştirmeleri | 6.3–6.8 |
| 58–59 | Test iyileştirmeleri | 7.3–7.5 |
| 60–63 | CI/CD iyileştirmeleri | 8.1–8.6 |
| 64–68 | Kurulum/repo iyileştirmeleri | 9.4–9.10 |
| 69–72 | Dokümantasyon | 10.3–10.7 |

### 🟢 Düşük (Fırsat buldukça yapılmalı) — 3 madde
| # | Konu | Bölüm |
|---|---|---|
| 73 | ProcessTreeScreen unmount cleanup | 6.9 |
| 74 | Stale yorum referansları | 10.8 |
| 75 | Filter rebuilding pattern duplikasyonu | 5.9 |
