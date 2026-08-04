# ForenSync Imager — Adli İmaj Alma

Uzak **Linux, macOS ve Windows** sunucularından, hedef sisteme **hiçbir kalıcı
yazılım kurmadan**, sektör standardında **adli bilişim imajı** alabilen
profesyonel bir masaüstü uygulamasıdır.

- **Disk imajı** alırken hedefe **sıfır yazma** yapılır (WriteBlocker zorunlu).
  Parça boyutu (MB) ayarı ile `output.001`, `.002` … split raw çıktı üretebilir.
- **RAM imajı** endüstri standardı **minimal müdahale** prensibiyle alınır
  (Linux/macOS: AVML, Windows: WinPMEM). **8 MiB parça** akışı, her parça
  için SHA-256, akış-boyu hash ile dosya hash'i karşılaştırılır
  (`verified_continuous`). Sunucu diskinde imaj OLUŞMAZ. Bağlantı kesilirse
  resume YOK — yeni `memory-attempt-NNN.001` başlar.
- **Uzantı Hedefli Tarama** — hem uzak sunucu üzerinde (Disk sekmesindeki
  checkbox veya Hedefli Tarama sekmesi) hem yerel imaj dosyasından
  (İnceleme → "Dosya Uzantısı Hedefli Yeni İmaj Al" sekmesi). 11 kategori,
  116 uzantı.
- **Bad Extension** tespiti — dosyanın magic number'ı ile uzantısı
  uyuşmuyorsa turuncu ⚠ ile işaretlenir (canlı ve raporda).
- **İmaj Gezgini** — FTK Imager tarzı Evidence Tree + File List + Hex
  Viewer (pytsk3 varsa NTFS/FAT/ext ağacı; yoksa fallback carver).
- **Resume** — Disk imajları için kaldığı yerden devam eder (split modu
  hariç).
- **Kaynak vs imaj hash doğrulama** — canlı diskin tam hash'i alınıp yerel
  imajla karşılaştırılır (opsiyonel).
- **İmaj İnceleme** — daha önce alınmış RAW/E01/AFF imajlarını salt-okunur
  açıp içeriğini listeler; bad-extension işaretlemesi.
- **6 formatta rapor**: TXT, PDF, JSON, HTML, CSV, XML (chain-of-custody).
- **NTP** ile zaman doğrulama; **RSA** ile dijital imza.
- **Oturum ID'li** eksiksiz log altyapısı.
  
## Kurulum (Geliştirme)

Python **3.10+** gereklidir.

```bash
# 1) Sanal ortam
python -m venv .venv
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# 2) Bağımlılıklar
pip install -r requirements.txt
```

> **Not (PyQt6 wheel):** PyQt6 Windows/macOS/Linux için prebuilt wheel'lerle
> sorunsuz kurulur. Eğer `pip install` kaynak derlemeye zorlanırsa (qmake yok
> hatası), muhtemelen ARM64 gibi wheel bulunmayan bir platformdasınız — o
> zaman sistem paket yöneticisiyle kurun (Debian/Ubuntu: `apt install
> python3-pyqt6`).

> **Not (opsiyonel araçlar):**
> - **E01 dönüşümü** için `ewfacquire` (libewf): Debian/Ubuntu
>   `apt install ewf-tools`, macOS `brew install libewf`.
> - **AFF dönüşümü** için `affconvert` (afflib): `apt install afflib-tools`.
> - **İmaj İnceleme (tam dosya sistemi ağacı)** için opsiyonel olarak:
>   `pip install pytsk3 pyewf` — kurulu değilse ham imza taraması moduna düşer.
> - **Windows RAM** için hedef makinede **WinPMEM** binary'si gereklidir
>   (uygulamadan yolu belirtilir).

## Çalıştırma

```bash
python main.py
```

## Modüller

| Modül | Görev |
|-------|-------|
| `core/ssh_connector.py` | Paramiko ile SSH bağlantısı (her komut WriteBlocker'dan geçer) |
| `core/write_blocker.py` | Yazılımsal write blocker — yalnızca salt-okunur komutlara izin verir |
| `core/os_detector.py` | Uzak OS tespiti (Linux/macOS/Windows) |
| `core/disk_imager.py` | Sıfır-yazma prensibiyle disk imajı + **resume** |
| `core/ram_imager.py` | AVML (Linux/macOS) / WinPMEM (Windows) çapraz platform |
| `core/hasher.py` | MD5/SHA1/SHA256/SHA512/BLAKE2b/SHA3-256; **kaynak-vs-imaj karşılaştırma** |
| `core/crypto_handler.py` | LUKS / BitLocker şifreleme tespiti (salt-okunur) |
| `core/hpa_handler.py` | HPA/DCO tespiti (salt-okunur; kaldırma WriteBlocker tarafından engellenir) |
| `core/ntp_verifier.py` | NTP ile saat sapması doğrulaması |
| `core/digital_signer.py` | RSA ile dosya imzalama / doğrulama |
| `core/format_converter.py` | Gerçek `ewfacquire` / `affconvert` subprocess çağrıları |
| `core/reporter.py` | 6 format: TXT/PDF/JSON/HTML/CSV/XML |
| `core/targeted_imager.py` | Custom Content / triage — uzantı + magic imza + bad extension |
| `core/image_analyzer.py` | Yerel RAW/E01/AFF imaj inceleme (SSH gerektirmez) |
| `core/file_signatures.py` | 25+ türde magic-number tablosu (targeted + analyzer için ortak) |
| `core/acquisition_controller.py` | Tüm süreci koordine eden kontrolcü |
| `gui/*` | PyQt6 arayüzü (referans dizayn: koyu lacivert + beyaz kart) |
| `logs/logger.py` | Oturum ID'li merkezi loglama |

## Mimari değişmez sözleşmeler

- **WriteBlocker merkeziyeti:** Tüm `SSHConnector.exec_command` /
  `open_read_stream` çağrıları paylaşılan `WriteBlocker.verify_command`'dan
  geçer. Yeni bir uzak komut eklerken `write_blocker.py`'deki
  `ALLOWED_READ_COMMANDS` listesine eklenmesi zorunludur.
- **Pause deseni:** `time.sleep(0.5)` — `settimeout` YANLIŞ.
- **`AcquisitionParams` / `ProgressCallback` imzası** tüm modüllerde birebir aynı.
- **Try/finally kuralı:** HPA kaldırma (ileride etkinleşirse) mutlaka
  `HPAHandler` context manager'ıyla sarılıp geri yükleme garantiye alınmalı.

## Paralel çalışma

Her `AcquisitionController` kendi `SSHConnector` + `WriteBlocker`'ını yönetir.
Aynı anda birden fazla `AcquisitionController` örneği ile birden çok sunucuya
veya aynı sunucudaki birden çok diske paralel bağlanabilirsiniz.

## Güvenlik / Adli Bilişim Notları

- **Write Blocker zorunludur:** SSH komutu gönderen tüm bileşenler AYNI
  `WriteBlocker` nesnesini paylaşır.
- **Özel anahtar** (`*.key`, `*.pem`) asla repoya eklenmez (`.gitignore`).
- Tüm işlemler **oturum ID'li** olarak `logs/runtime/` altında loglanır.
- Zaman damgaları **NTP** ile doğrulanır; sapma raporda belirtilir.
- Parolalar **log/rapor dosyalarına yazılmaz**.

## Kapsam dışı

Cloud entegrasyonu, GPU hash hızlandırma, hex viewer + bookmark, REST API,
CLI/scheduling, sertifika/publik-anahtar şifreleme — bu sürümde bilinçli
olarak dahil edilmemiştir.
