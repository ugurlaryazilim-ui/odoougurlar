# sms_system

Turatel üzerinden SMS gönderimi, kampanya, İYS ve terzi/inceleme bildirimleri.

## Davranış özeti

**A (güvenilirlik):** Test modu yalnız açık `'False'` ile kapanır. Tekli SMS kuyruğa alınabilir (cron, `SKIP LOCKED`),
yanıtı alınamayan gönderim `uncertain` olur ve otomatik yeniden gönderilmez. Elle günlük sınır negatif olamaz.
**B (vendor/terzi):** Mobil SMS düğmesi kilitlenir, aynı kayıt+şablon için 60 sn içinde ikinci SMS engellenir,
durum geçişleri katıdır.
**C (JSON API):** Ayarlarda API modu (`legacy_xml` varsayılan / `json`). JSON modunda tekli SMS `singlesms`,
kampanya `bulksms` ile gider. Bilgi ve reklam için iki ayrı kimlik seti vardır; ticari kampanya yalnız reklam setiyle
gider (set yoksa onay engellenir, bilgi setine düşmez). Ticari SMS için ret metni (ve Mersis no) zorunludur.
Kişiselleştirme `{ad}` -> `{1}` + `parameter`; en çok 402 karakter. İletim durumu "SMS: İletim durumu" cron'u
(15 dk) ve "Durumu Sorgula" ile izlenir. Test modunda yalnız "Test numaraları" listesindeki numaralara gerçek SMS gider.

## JSON geçişi kontrol listesi

Her deneme adımı en çok 5 SMS ile yapılır. Bir adım başarısızsa sonrakine geçme.

### 1. Deploy öncesi
- [ ] Ayarlar > SMS: **Ret metni** (çıkış talimatı) ve **Mersis no** dolu. Boşsa C sonrası ticari kampanyalar engellenir.
- [ ] **İki kimlik seti** hazır: bilgi (kullanıcı adı/şifre, userId, hesap 9254) ve reklam (ayrı kullanıcı adı/şifre, hesap 65672).
  Reklam seti yoksa geçiş yapılabilir ama JSON modunda ticari kampanya gönderilemez.
- [ ] Canlı sunucunun çıkış IP'si Turatel'de izinli (aksi halde `-22`).
- [ ] `sms_system.test_mode` = `True` (Ayarlar'da Test modu işaretli).
- [ ] `-u` penceresi **mesai dışı**: terzi, inceleme ve "Yeni SMS" ekranları kullanılmıyor. Rollback etiketi ve DB yedeği alındı.

### 2. Redeploy ve hemen `-u sms_system`
- [ ] Redeploy sonrası **aynı dakikada elle** `-u sms_system` çalıştır (otomatik `-u` listesi değişmez).
  Yeni kolonlar: `provider_packet_id`, `delivery_state`, `delivery_code`, `provider_service`, `provider_account_id`.
  Yükseltmeye kadar `sms_system_message`'ı okuyan her şey (SMS cron'ları, terzi "Hazır", inceleme, "Yeni SMS") kolon yok hatası verir.
- [ ] Kontrol: test modu hâlâ `True`, API modu `legacy_xml`, bir terzi SMS'i `test` durumunda oluşuyor,
  Zamanlanmış Eylemler'de "SMS: İletim durumu" var.

### 3. Düğmelerle doğrulama
- [ ] İki kimlik seti girilir, API modu `JSON API`, kaydet.
- [ ] **Hesaplar / Başlıklar / Kredi** düğmeleri **her iki set için** başarılı: bilgi seti 9254'ü, reklam seti 65672'yi görür.

### 4. Test numaralarıyla deneme (test modu AÇIK)
- [ ] Ayarlar > "Test modunda gerçek gönderilecek numaralar": kendi numaraların (en çok 5, virgülle).
- [ ] Tekli SMS: listedeki numara `sent`, listede olmayan `test`.
- [ ] Bilgilendirme kampanyası (listedeki alıcılarla): yalnız listedekiler gider.
- [ ] İsteğe bağlı: kendi İYS onaylı numarana ticari kampanya (reklam seti).
- [ ] "Durumu Sorgula" ve durum cron'u **gerçek satır döndürür** ve "İletildi" yazar; SMS "Onay Bekliyor"da kalmaz.
- [ ] **`-6` doğrulaması:** kayıt varken de `-6` (boş) dönüyorsa durum takibi doğrulanmamıştır; **test modunu kapatma**,
  tarih biçimi/aralığı için takip işi aç. (Kayıt yokken `-6` normaldir ve boş liste sayılır.)

### 5. Test modunu kapatma
- [ ] Ancak 4. adım tamamen başarılıysa Test modunu kapat. Kapatınca liste etkisizdir, SMS herkese gider.

## Geri dönüş
1. **İlk tercih:** Ayarlar > API Modu = `legacy_xml`. Anında etkili, deploy gerekmez; JSON kayıtları korunur,
   eski kimlik bilgileri saklıdır.
2. Kod geri alma: `git revert -m 1` + redeploy. Yeni kolonlar DB'de kalır (zararsız); "SMS: İletim durumu" cron'unu elle pasifleştir.

### Hata kodları
- `-1000`: kimlik seti yanlış ya da hesap o kullanıcıya ait değil (bilgi kullanıcısıyla reklam hesabı gibi) -> seti düzelt.
- `-22`: sunucunun IP'si Turatel'de yetkili değil -> IP iznini ekletin.
- `-6`: durum sorgularında "kayıt yok" (boş liste). Gönderilmiş kayıt varken geliyorsa tarih biçimi/aralığı sorunudur;
  diğer uçlarda normal hatadır.
