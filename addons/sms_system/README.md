# sms_system

Turatel üzerinden SMS gönderimi, kampanya, İYS ve terzi/inceleme bildirimleri.

## Davranış özeti

**A (güvenilirlik):** Test modu yalnız açık `'False'` ile kapanır. Tekli SMS kuyruğa alınabilir (cron, `SKIP LOCKED`),
yanıtı alınamayan gönderim `uncertain` olur ve otomatik yeniden gönderilmez. Elle günlük sınır negatif olamaz.
**B (vendor/terzi):** Mobil SMS düğmesi kilitlenir, aynı kayıt+şablon için 60 sn içinde ikinci SMS engellenir,
durum geçişleri katıdır.
**C (JSON API):** Ayarlarda API modu (`legacy_xml` varsayılan / `json`). JSON modunda tekli SMS `singlesms`,
kampanya `bulksms` ile gider. Bilgi ve reklam için iki ayrı kimlik seti vardır; ticari kampanya yalnız reklam setiyle
gider (set yoksa onay engellenir, bilgi setine düşmez). Ticari SMS için ret metni zorunludur (Mersis no ayrı alan değil, ret metninin içinde yazılır).
Kişiselleştirme `{ad}` -> `{1}` + `parameter`; en çok 402 karakter. İletim durumu "SMS: İletim durumu" cron'u
(15 dk) ve "Durumu Sorgula" ile izlenir. Test modunda yalnız "Test numaraları" listesindeki numaralara gerçek SMS gider.

## JSON geçişi kontrol listesi

Her deneme adımı en çok 5 SMS ile yapılır. Bir adım başarısızsa sonrakine geçme.

### 1. Deploy öncesi
- [ ] Ayarlar > SMS: **Ret metni** dolu; **Mersis no ayrı bir alan değildir, ret metninin içinde** (çıkış talimatıyla aynı alanda) yer alır.
  Ret metni boşsa C sonrası ticari kampanyalar engellenir.
- [ ] **İki kimlik seti** hazır: bilgi (kullanıcı adı/şifre, userId, hesap 9254) ve reklam (ayrı kullanıcı adı/şifre, hesap 65672).
  Reklam seti yoksa geçiş yapılabilir ama JSON modunda ticari kampanya gönderilemez.
- [ ] Canlı sunucunun çıkış IP'si Turatel'de izinli (aksi halde `-22`).
- [ ] `sms_system.test_mode` = `True` (Ayarlar'da Test modu işaretli).
- [ ] `-u` penceresi **mesai dışı**: terzi, inceleme ve "Yeni SMS" ekranları kullanılmıyor. Rollback etiketi ve DB yedeği alındı.
- [ ] Aşağıdaki komutlar önceden hazır (kapatılan cron id'leri not edilecek).

### 2. Deploy sırası: cron'ları durdur, redeploy, aynı dakikada `-u`, cron'ları aç
Yeni kolonlar redeploy ile `-u sms_system` arasında yoktur; bu pencerede `sms_system_message`'ı okuyan her şey
(SMS cron'ları, terzi "Hazır", inceleme, "Yeni SMS") kolon yok hatası verir. Pencereyi kısa tutmak için:
1. **Mesai dışında SMS cron'larını durdur** ve dönen id'leri not et:
   ```sql
   UPDATE ir_cron SET active = false
    WHERE active AND (cron_name LIKE 'SMS:%'
                      OR cron_name LIKE 'Terzi: Teslim alınmayanlara hatırlatma SMS%'
                      OR cron_name LIKE 'Tedarikçi İnceleme: Teslim alınmayanlara hatırlatma SMS%')
   RETURNING id, cron_name;
   ```
2. Merge + redeploy. Konteyner sağlıklı olur olmaz **hemen** (komut önceden hazır, aynı dakika; otomatik `-u` listesi değişmez):
   ```
   docker exec <odoo-konteyner> odoo -d <veritabanı_adı> -u sms_system --stop-after-init --no-http
   ```
   `<veritabanı_adı>`: canlı veritabanının adı; Coolify'daki Odoo servisinin `DB_NAME`/`POSTGRES_DB` ortam değişkeninde ya da
   `psql -l` çıktısında görünür (emin değilsen komutu çalıştırma, önce adı doğrula).
   tailor/vendor_claim bağımlı olarak birlikte yükselir. Yeni kolonlar: `provider_packet_id`, `delivery_state`,
   `delivery_code`, `provider_service`, `provider_account_id`.
3. `-u` biter bitmez **cron'ları aç** (not edilen id'lerle):
   ```sql
   UPDATE ir_cron SET active = true WHERE id IN (<not edilen id'ler>);
   ```
4. İsteğe bağlı: Coolify'dan restart (kolonlar için şart değil, worker'ları tazelemek için önerilir).
- [ ] Kontrol: sms_system sürümü 19.0.2.0.0, test modu hâlâ `True`, API modu `legacy_xml`, bir terzi SMS'i `test`
  durumunda oluşuyor, Zamanlanmış Eylemler'de "SMS: İletim durumu" **aktif**.

### 3. Düğmelerle doğrulama
- [ ] İki kimlik seti girilir, API modu `JSON API`, kaydet.
- [ ] **Hesaplar / Başlıklar / Kredi** düğmeleri **her iki set için** başarılı: bilgi seti 9254'ü, reklam seti 65672'yi görür.

### 4. Test numaralarıyla deneme (test modu AÇIK)
- [ ] Ayarlar > "Test modunda gerçek gönderilecek numaralar": kendi numaraların (en çok 5; virgül, noktalı virgül ya da satır sonuyla
  ayır; numara içinde boşluk olabilir: `0532 111 22 33`). Alan yalnız sistem yöneticisine görünür.
- [ ] Tekli SMS: listedeki numara `sent`, listede olmayan `test`.
- [ ] Bilgilendirme kampanyası (listedeki alıcılarla): yalnız listedekiler gider.
- [ ] **ZORUNLU: kendi numaranla `{ad}` içeren kişiselleştirilmiş kampanya.** Listede kendi numaranı kendi adınla
  kaydet, bilgilendirme kampanyası metninde `{ad}` kullan (ör. "Merhaba {ad}, test mesajıdır"), gönder.
  Telefondaki SMS'te **adın doğru çözüldüğünü** ve kayıttaki `body` ile aynı olduğunu gör. **`{1}` (ya da başka
  bir yer tutucu) görünüyorsa test modunu KAPATMA**: `{ad}` -> `{1}` + `parameter` sözdizimi canlıda henüz
  görülmedi (C0 SendSms'i kapsamadı); yanlışsa ilk gerçek kampanya binlerce alıcıya "Merhaba {1}" olarak gider.
- [ ] **Jeton yenilemesi:** jeton ~30 dk önbellekte tutulur. İlk SMS'ten en az 30 dk sonra bir SMS daha gönder ve
  başarılı gittiğini gör (jeton yenilemesi canlıda yalnız böyle görülür).
- [ ] **Turatel adresleri** (Ayarlar > tekli/toplu servis adresi) `https://` ile başlamalı; `http://` kaydedilmez.
- [ ] İsteğe bağlı: kendi İYS onaylı numarana ticari kampanya (reklam seti). Mersis no ret metninin içinde olmalı.
- [ ] "Durumu Sorgula" ve durum cron'u **gerçek satır döndürür** ve "İletildi" yazar; SMS "Onay Bekliyor"da kalmaz.
- [ ] **`-6` doğrulaması:** kayıt varken de `-6` (boş) dönüyorsa durum takibi doğrulanmamıştır; **test modunu kapatma**,
  tarih biçimi/aralığı için takip işi aç. (Kayıt yokken `-6` normaldir ve boş liste sayılır.)

### 5. Test modunu kapatma
- [ ] Ancak 4. adım (özellikle `{ad}` doğrulaması ve iletim durumu) tamamen başarılıysa Test modunu kapat. Kapatınca liste etkisizdir, SMS herkese gider.

## Geri dönüş
1. **İlk tercih ve yeterli yol:** Ayarlar > API Modu = `legacy_xml`. Anında etkili, deploy gerekmez; `json` dışı her değer
   eski XML sayılır, JSON kimlik bilgileri saklı kalır. Kuyruktaki (`queued`) kayıtlar sonraki cron turunda
   eski yolla gider; `uncertain` kayıtlar asla yeniden gönderilmez.
2. **Kod geri alma yalnız zorunluysa** (`git revert -m 1` + redeploy):
   - **Eski kodla `-u sms_system` ÇALIŞTIRMA.** Eski modül tanımında 5 yeni kolon (`provider_packet_id`, `delivery_state`,
     `delivery_code`, `provider_service`, `provider_account_id`) olmadığı için Odoo kolonları DB'den siler;
     iletim durumu verisi gider (mesaj kayıtları kalır). Revert sonrası `-u` yapılmazsa kolonlar DB'de kalır ve zararsızdır.
   - Revert edilen kodda "SMS: İletim durumu" cron'u olmayan metodu çağırır: **elle pasifleştir**
     (`UPDATE ir_cron SET active = false WHERE cron_name = 'SMS: İletim durumu';`).
   - Eski kod `uncertain` durumunu bilmez: önce `UPDATE sms_system_message SET state='error', retry_count=3 WHERE state='uncertain';`
     Kampanyada "Hatalıları Yeniden Gönder" kullanma (mükerrer SMS riski).

### Hata kodları
- `-1000`: kimlik seti yanlış ya da hesap o kullanıcıya ait değil (bilgi kullanıcısıyla reklam hesabı gibi) -> seti düzelt.
- `-22`: sunucunun IP'si Turatel'de yetkili değil -> IP iznini ekletin.
- `-6`: durum sorgularında "kayıt yok" (boş liste). Gönderilmiş kayıt varken geliyorsa tarih biçimi/aralığı sorunudur;
  diğer uçlarda normal hatadır.
