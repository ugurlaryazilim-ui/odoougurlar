# Sanal POS (`sanal_pos`)

Odoo 19. Fatura numarasıyla Nebim faturasından tutar ve müşteri bilgisini çekip **Paratika ödeme linki** üretir, müşteriye SMS/e-posta ile gönderir (gönderimi Paratika yapar), ödemeyi tek ekranda izler; ödeme iptali (VOID) ve iade (REFUND) buradan yapılır. Sağlayıcı bağımsız tasarlanmıştır; ilk sağlayıcı Paratika'dır.

Başka modüle bağımlılığı yoktur (`ugurlar_tailor` kurulu olmasa da çalışır). Yeni Python bağımlılığı yoktur (`requests`, `pymssql` imajda mevcut).

## 1. Kurulum ve güncelleme

- **Sıra (D-4c):** önce SQL Server'da `data/sql/vw_TerziFaturalar_v2.sql` çalıştırılır ve doğrulanır (5. bölüm), **sonra** modül kurulur. v2 olmadan fatura getirme "Fatura görünümü güncel değil (v2 gerekli)" der.
- **İlk kurulum:** `odoo -d <veritabani> -i sanal_pos --stop-after-init`
- **Öneri (D-4a):** ilk elle kurulumdan sonra `sanal_pos`, üretim compose dosyasındaki otomatik `-u` modül listesine eklenmeli; böylece sonraki deploy'larda güncelleme unutulmaz.
- **Sonraki her sürüm:** deploy biter bitmez **hemen** `odoo -d <veritabani> -u sanal_pos --stop-after-init`.
  Yeni saklanan (stored) alanlar modül güncellenene kadar veritabanında yoktur; arada durum senkronu cron'u (10 dakikada bir) hata verir. Güncellemeyi geciktirmeyin.
  "Sanal POS: bildirim tetikli senkron" cron'u da `-u` ile oluşur; o zamana kadar bildirim tetikleri 10 dakikalık periyodik cron'a kurulur.
- Test: `odoo -d bc_test -u sanal_pos --test-tags /sanal_pos --stop-after-init --workers=0 --max-cron-threads=0` (Paratika ve MSSQL taklit edilir; gerçek çağrı gitmez).

## 2. Ayarlar (Sanal POS > Ayarlar; yalnız sistem yöneticisi)

| Ayar | Not |
|---|---|
| Ortam | **Test** / **Canlı**. Canlıya geçmeden önce 5. bölümü bitirin. |
| Paratika bilgileri | Üye iş yeri kodu, API kullanıcı adı, API şifresi, gizli anahtar (secretKey). Test ve canlı API adresleri ayrı alanlardır. Şifre ve anahtar yalnız sistem yöneticisi görür. |
| MSSQL | Sunucu, port, veritabanı, kullanıcı, şifre, görünüm adı (varsayılan `dbo.vw_TerziFaturalar`). **Terzi ayarlarından kopyala** düğmesi `ugurlar_tailor.mssql_*` değerlerini alır (terzi modülü kurulu olmak zorunda değil). Okuma yetkili ayrı bir SQL kullanıcısı önerilir. |
| Telefon biçimi | `5321112233`, `05321112233`, `905321112233` veya `+905321112233`. Paratika'nın kabul ettiği biçim sandbox'ta belirlenir (5. bölüm). |
| ASCII modu | Paratika Türkçe karakteri bozarsa açın (ç→c, ş→s ...). Varsayılan kapalı (UTF-8). |
| E-posta ve telefon zorunlu | Varsayılan açık. Paratika yeni müşteride ikisini de istiyor; faturada yoksa personel ekrandan elle girer. |
| Link geçerlilik süresi | 1-168 saat (varsayılan 168). |
| Link adresini göster | Varsayılan kapalı; Paratika link adres biçimi teyit edilene kadar kapalı kalmalı. |

Aynı ekranda bildirim ve dönüş adresleri salt okunur gösterilir (aşağıda).

## 3. Kullanıcı grupları

| Grup | Yapabildikleri |
|---|---|
| Grupsuz iç kullanıcı | Hiçbir Sanal POS kaydını ve eylemini göremez. |
| **Sanal POS / Kullanıcı** | Fatura sorgular, link oluşturur, yeniden gönderir, linki iptal eder, durum yeniler; talepleri okur. **Mail Order** başlatır, kart sayfasını açar, Mail Order'ı kapatır (9. bölüm). |
| **Sanal POS / Yönetici** | Kullanıcının hepsi + ödeme iptali (VOID), iade (REFUND), inceleme (kabul/kapat), işlem kayıtları. Mail Order ile alınan ödemenin iptal/iadesi de yalnız yönetici. |
| Sistem yöneticisi (`base.group_system`) | Yalnız **ayarlar**. İade/iptal yetkisi **otomatik gelmez**; gerekirse ayrıca Yönetici grubuna eklenir. |

Sır alanları (API şifresi, secretKey, MSSQL kullanıcı/şifre) hiçbir kayıt, log, chatter, dışa aktarma veya RPC yanıtında görünmez; log gövdelerinde maskelenir.

## 4. Paratika paneli önkoşulları

1. **Bildirim (notify) adresi:** `https://<odoo-alan-adi>/sanal_pos/paratika/notify` (POST). Ayar ekranındaki "Bildirim adresi" ile aynıdır. Bildirim yalnız tetiktir; durum Paratika'ya sorularak doğrulanır. Sabit `200 OK` döner. Reverse proxy'de (nginx/Coolify) bu yola POST ile erişilebildiğini `curl -X POST https://<odoo-alan-adi>/sanal_pos/paratika/notify` ile doğrulayın (yanıt `OK`).
2. **Dönüş (return) adresi:** `https://<odoo-alan-adi>/sanal_pos/paratika/return` (müşterinin ödeme sonrası döndüğü teşekkür sayfası). Yalnız POST kabul eder.
3. API kullanıcısında link, sorgu, **VOID ve REFUND** yetkileri açık olmalı (test ve canlı için ayrı kullanıcılar).
4. Odoo'nun `web.base.url` sistem parametresi gerçek alan adını (`https://`) göstermeli ve `web.base.url.freeze = True` yapılmalı; aksi halde yönetici girişi adresi değiştirebilir, dönüş/bildirim adresleri bozulur (D-3).
5. **Bildirim çoğaltmasına karşı (öneri, reverse proxy):** Modül aynı ödemeye gelen tekrar bildirimlerde tek cron tetiği kurar, ödeme başına en çok dakikada bir sorgu yapar ve bildirim tetiğini yalnız bayraklı kayıtları işleyen ayrı cron'a ("Sanal POS: bildirim tetikli senkron") kurar; 10 dakikalık periyodik tur bildirimle çoğalmaz ve hiçbir kaydı atlamaz. Ek koruma olarak nginx/Coolify'da `/sanal_pos/paratika/` yolları için gövde sınırı ve IP başına hız sınırı önerilir, örnek: `client_max_body_size 16k;` ve `limit_req zone=sanalpos burst=20 nodelay;` (`limit_req_zone $binary_remote_addr zone=sanalpos:1m rate=30r/m;`). Paratika bildirim IP'leri öğrenilirse yalnız onlara izin verilebilir. (Modül bu ayarları yapmaz.)

## 5. Nebim fatura görünümü

- Kaynak `dbo.vw_TerziFaturalar` **v2**'dir: `data/sql/vw_TerziFaturalar_v2.sql` (SQL Server'da bir kez çalıştırılır; Odoo çalıştırmaz, manifest'e ekli değildir). Terzi modülünün kullandığı ilk 18 sütun aynıdır.
- Doğrulama: `UGR2026000012587` faturasının toplamı 9000,00 olmalıdır.
- **Geri alma:** `data/sql/vw_TerziFaturalar_v1_geri_al.sql`. Geri alınırsa Sanal POS "Fatura görünümü güncel değil (v2 gerekli)" der; kayıtlar ve senkron etkilenmez.
- Modül MSSQL'e yalnız parametreli `SELECT` ile bağlanır; yazma yapmaz.

## 6. CANLIYA ALMADAN ÖNCE (zorunlu)

Sıralı özet (ayrıntılar aşağıda ve 1-5. bölümlerde):
1. v2 görünüm SQL'i uygulandı ve 9000,00 doğrulaması yapıldı (5. bölüm).
2. Paratika sandbox denemesi bitti: R-3, P-10, telefon biçimi, link token/adres, PAYBYLINKSTATUS, QUERYTRANSACTION boş yanıtı.
3. Canlı API adresi Paratika ile teyit edildi.
4. Deploy sonrası hemen `-i sanal_pos` (sonraki sürümlerde `-u sanal_pos`); Ayarlar > Teknik > Zamanlanmış Eylemler'de 3 cron göründüğü kontrol edildi (durum senkronu, bildirim tetikli senkron, günlük temizlik ve iade senkronu).
5. Paratika paneline bildirim ve dönüş adresleri girildi (4. bölüm).
6. Şirket ağı dışından `curl -X POST .../sanal_pos/paratika/notify` yanıtı `OK` (WAF/Cloudflare).
7. nginx/Cloudflare'de `/sanal_pos/paratika/` için `limit_req` + 16k gövde sınırı (4. bölüm, madde 5).
8. `web.base.url` doğru ve `web.base.url.freeze = True`.
9. `sanal_pos` üretim compose `-u` listesine eklendi.
10. Kullanıcılara Sanal POS / Kullanıcı ve Yönetici grupları atandı; sistem yöneticisine iade yetkisi gerekiyorsa Yönetici grubu ayrıca verildi.
11. Ortam Canlı yapıldı; 1 TL ödeme + aynı gün iptal ile doğrulandı.

**Webhook dış erişim testi (D-3):** Sunucu Cloudflare Tunnel/Coolify arkasında olduğundan WAF/Bot kuralları Paratika'nın POST'unu engelleyebilir. Canlıda şirket ağı **dışından** `curl -X POST https://<odoo-alan-adi>/sanal_pos/paratika/notify` çalıştırın; yanıt `OK` olmalı (403/challenge sayfası gelirse WAF'ta bu yol için istisna tanımlayın). Bildirim gelmezse ödeme yine cron sorgusuyla (10 dk) yakalanır ama gecikir.

**Paratika sandbox denemesi (test ortamı, uçtan uca):** link (SMS+e-posta), Türkçe ad görünümü, test kartla ödeme, webhook ile "Ödendi", başarısız kart, link iptali, aynı gün iptal, ertesi gün kısmi ve tam iade. Bu deneme şu belirsizlikleri kapatır; sonuca göre çoğunlukla yalnız ayar veya eşleme değişir:

- **R-3 / REFUND `pgTranId`:** REFUND yanıtındaki `pgTranId` iade işleminin mi, satışın mı? QUERYTRANSACTION VOID/REFUND/PTREFUND'u hangi biçimde döndürüyor? (Eşleşmezse iade satırı `Belirsiz` kalır ve yönetici uyarılır; para çıkışı için kritik.) Gerçek yanıtları `tests/` taklitlerine örnek olarak ekleyin.
- **P-10 gün sonu saati:** VOID'den REFUND'a geçiş saati ve kısmi iade sayısı sınırı.
- **Telefon biçimi:** hangi biçim SMS'i ulaştırıyor (Ayarlar > Telefon biçimi).
- ~~**Link token ve adres**~~ — teyit edildi (2026-10-21, canlı SMS): `sessionToken` linkteki token ile aynı; adres `https://vpos.paratika.com.tr/payment/<token>?lang=tr` (`/merchant/payment/` hata verir).
- **QUERYTRANSACTION boş yanıt:** Paratika'da hiç oluşmamış bir `MERCHANTPAYMENTID` için `responseCode=00` + boş liste mi döner, hata kodu mu? (Hata kodu dönerse "link bulunamadı" kayıtları link süresi boyunca kilitli kalır.)
- **PAYBYLINKSTATUS değerleri:** yalnız `SD` görüldü; tüm değerler listelenip eşleme doğrulanır.
- Dönüşün POST olduğunu doğrulayın (GET gelirse tasarım değişikliği gerekir).

**Canlı adres:** `paratika_live_url` (varsayılan `https://vpos.paratika.com.tr/paratika/api/v2`) Paratika ile **teyit edilmelidir**. Sonra ortamı Canlı yapın, 1 TL ödeme + aynı gün iptal ile doğrulayın, mağazalara açın.

**Paratika'ya sorulacaklar** (ayrıntı: `.ekip/20261019-sanal-pos/01-gereksinimler.md` §12):
1. P-1 Canlı API/ödeme sayfası kök adresi; canlı kullanıcı; API kullanıcısında VOID/REFUND yetkisi.
2. P-2 `sessionToken` ve `PAYBYLINKTOKEN` aynı mı; link URL biçimi.
3. P-3 SMS telefon biçimi; SMS/e-posta metni ve gönderen adı özelleştirme; SMS ücreti/kredisi; teslim raporu.
4. P-4 Yalnız SMS seçilince e-posta zorunlu mu (ERR10244)?
5. P-5 `PAYBYLINKSTATUS` değer listesi; `SESSIONEXPIRY` alt/üst sınırı.
6. P-6 Aynı `CUSTOMER` koduyla farklı ad/telefon/e-posta gönderilirse hangisi geçerli?
7. P-7 Bildirim için yeniden deneme, imza/kaynak IP doğrulaması; başarısız ve iptal olayları için bildirim var mı?
8. P-8 Başarısız denemeden sonra link açık kalıyor mu; ödenmiş linkin `MERCHANTPAYMENTID` değeri yeniden kullanılabilir mi?
9. P-9 Karakter kodlaması UTF-8 mi; Türkçe ad SMS'te ve ödeme sayfasında doğru mu?
10. P-10 Gün sonu saati; kısmi iade sınırı; QUERYTRANSACTION iade işlemlerini orijinal `MERCHANTPAYMENTID` ile döndürüyor mu?

## 6a. İade onay akışı ve geçiş (19.0.1.2.0)

**Davranış değişikliği:** Paratika iadeyi finans onayına bırakabilir. REFUND `responseCode=00` artık "iade edildi" değil "Paratika isteği kabul etti" demektir: iade satırı **Onay bekliyor** (`pending_approval`), ödeme **İade onay bekliyor** (`refund_pending`) olur. Kesin sonucu QUERYTRANSACTION senkronu verir: onaylı (AP) → **Başarılı**, açık red (FA / bilinen ret kodu) → **Reddedildi** (ret sebebi satırda ve chatter'da), diğer her durum beklemeye devam eder. "Bulunamadı" hiçbir zaman red sayılmaz. Bekleyen iade varken yeni iade/iptal yapılamaz. 72 saatten uzun bekleyen iade için yönetici grubuna ve iadeyi yapana tek seferlik uyarı gider.

**Deploy (sıra önemli):**
0. Önce rollback etiketini atın ve veritabanı yedeği alın (geri alma bunlara dayanır).
1. **Mesai dışında** merge ve redeploy yapın; ardından **hemen** `odoo -d <veritabani> -u sanal_pos --stop-after-init`. Redeploy ile `-u` arasında Python kodu yeni kolonları (`sanal_pos_refund.provider_status`, `provider_status_detail`, `pending_alert_sent`) okur; bu sürede üç Sanal POS cron'u ("durum senkronu", "bildirim tetikli senkron", "günlük temizlik ve iade senkronu"), ödeme formu (İade Geçmişi) ve iade/iptal sihirbazı hata verir. Pencereyi kısa tutun, kullanıcılara önceden haber verin; bu üç cron'u redeploy öncesi pasif yapıp doğrulama SQL'inden (adım 2) sonra açmanız önerilir.
2. `-u` sonrası doğrulama (salt okunur SQL): `SELECT indexdef FROM pg_indexes WHERE tablename='sanal_pos_refund' AND indexdef ILIKE '%pending_approval%';` 1 satır dönmeli; `\d sanal_pos_refund` 3 yeni kolonu göstermeli.
3. **Sanal POS > İade Onay Geçişi** (yalnız Sanal POS / Yönetici): **Paratika ile Karşılaştır** raporu inceleyin. Bu adım salt okunurdur (yalnız işlem kaydı yazar). Her satır için planlanan eylem görünür: *Değişmez (AP)*, *Onay bekliyor'a alınacak*, *Atlanacak: sebep*. Atlananlar elle incelenir: devam eden işlem var, aynı ödemede birden fazla dönüşecek satır, belirsiz eşleşme (işlem no ile bire bir eşleşmeyen satır yalnız satırdan sonra tarihli işlemle değerlendirilir; tutar eşleşmesi tek başına yetmez), Paratika'da işlem bulunamadı, sorgu hatası, kayıt kilitli. İkinci bölüm, yeni kuralın mevcut durumdan farklı sonuç verdiği kayıtları listeler (yalnız bildirir).
4. Rapor uygunsa **Geçişi Uygula**: her ödeme yeniden sorgulanır (önizleme bayatlamış olabilir), kısa kilit altında yalnız Paratika'da onaylı görünmeyen "Başarılı" satırlar "Onay bekliyor"a alınır, normal senkron kuralları çalışır (açık red hemen "Reddedildi" olur ve bildirim gider), ödeme başına commit edilir. İşlem **idempotenttir**; tekrar çalıştırılabilir. Büyük kümelerde süre sınırı (60 sn) aşılırsa kalanlar raporlanır ve işlem tekrar çalıştırılır. Son çalışma zamanı `sanal_pos.refund_approval_migration_at` parametresindedir. Geçiş migrate betiğiyle yapılmaz: migrate içinde dış API çağrısı yoktur.
5. İlk günlerde log'da `tanınmayan transactionStatus` WARNING'ini izleyin; görülen kod bildirilirse eşlemesi ayrı küçük iş olur.
6. Başka modülün yükseltilmesi gerekmez (bağımlı modül yok).

*Kabul edilen sınır:* Paratika bekleyen iadeyi de AP gösteriyorsa kayıt "İade edildi" kalır; bu eski davranıştan kötü değildir.

**Geri alma (iade onay akışı):** önkoşul merge öncesi rollback etiketi ve `-u` öncesi veritabanı yedeği.
Eski kodda `pending_approval`, `rejected` ve `refund_pending` değerleri yoktur; DB'de varchar olarak kalır ve görünümde etiketsiz görünür. `refund_pending` ödemede eski iade düğmesi görünmez, RPC ile çağrılırsa reddedilir (çift iade yolu açılmaz); ancak kayıt hiç güncellenmez. Adımlar:
1. Üç Sanal POS cron'unu pasif yapın: "durum senkronu", "bildirim tetikli senkron" ve "günlük temizlik ve iade senkronu" (günlük cron da iade senkronu yapar).
2. Veriyi eski anlama çevirin (tek transaction, yalnız SQL, dış API yok). Bekleyen = eski davranış "iade edildi":
   ```sql
   BEGIN;
   UPDATE sanal_pos_refund SET state='done', done_at=COALESCE(done_at, create_date) WHERE state='pending_approval';
   UPDATE sanal_pos_refund SET state='failed' WHERE state='rejected';
   UPDATE sanal_pos_payment p SET refunded_amount = COALESCE((SELECT SUM(r.amount) FROM sanal_pos_refund r
          WHERE r.payment_id=p.id AND r.state='done'),0)
    WHERE p.id IN (SELECT payment_id FROM sanal_pos_refund);
   UPDATE sanal_pos_payment SET state = CASE WHEN refunded_amount >= paid_amount THEN 'refunded'
          WHEN refunded_amount > 0 THEN 'partial_refund' ELSE 'paid' END
    WHERE state='refund_pending';
   COMMIT;
   ```
3. Rollback etiketine dönün, yeniden deploy edin ve `-u sanal_pos` çalıştırın (yeni kolonlar yetim ve zararsız kalır, sihirbaz modeli kaldırılır).
4. Cron'ları açın; `SELECT count(*) FROM sanal_pos_payment WHERE state='refund_pending'` 0 olmalı.

Not: 2. adım bekleyen iadeleri "iade edildi" sayar; Paratika sonradan reddederse eski kod bunu görmez (bugünkü durumla aynı risk). `rejected` → `failed` dönüşümünde işlem no (`provider_ref`) korunur ve eski kod bu numarayı "bilinen" sayar: Paratika reddettiği iadeyi sonradan onaylarsa (yeni kodun güvenlik ağı vakası) eski kod bunu saymaz; para iade edilmiş olduğu hâlde Odoo tutarı iade edilebilir gösterir. Geri alma sonrası hem bekleyen hem de reddedilmiş (`rejected` iken `failed` yapılan) iadeleri Paratika panelinden elle izleyin; listeyi 2. adımdan **önce** alın: `SELECT id, payment_id, amount, provider_ref, state FROM sanal_pos_refund WHERE state IN ('pending_approval','rejected');`

## 7. Geri alma planı

1. **Hızlı (veri korunur):** Ayarlarda ortamı Test'e alın veya kullanıcıların Sanal POS grubunu kaldırın; "Sanal POS: durum senkronu" ve "günlük temizlik ve iade senkronu" cron'larını pasif yapın; Paratika panelinden bildirim adresini kaldırın. Açık linkleri Paratika panelinden iptal edin.
2. **Modül kaldırma:** önce Ödeme Talepleri ve iade geçmişini dışa aktarın (finansal kayıt; kaldırma tabloları siler). Sonra Uygulamalar > Sanal POS > Kaldır. Başka modül sanal_pos'a bağlı değildir.
3. **Kod:** önceki sürüm etiketine dönüp yeniden deploy edin, ardından `-u sanal_pos`.
4. **Fatura görünümü:** yalnız terzi modülünde sorun görülürse SSMS'te `vw_TerziFaturalar_v1_geri_al.sql` çalıştırın.

## 8. Yeni sağlayıcı eklemek (PayTR / iyzico)

Çekirdek yalnız `sanal.pos.provider` arayüzünü ve normalize sonuç sözlüklerini bilir (`models/provider.py` modül açıklaması sözleşmeyi tanımlar). Adımlar:
1. `sanal.pos.payment.provider` alanına `selection_add` ile yeni kodu ekleyin.
2. `sanal.pos.provider.<kod>` adlı bir `AbstractModel` yazın (`models/provider_paratika.py` örnek); arayüz metotları `create_link`, `resend`, `cancel_link`, `find_link`, `query_status`, `void`, `refund`, `parse_notification`. **Hepsi `@api.private` olmalı** (RPC ile çağrılırsa dış çağrı tetiklenir). Sağlayıcı koduna özgü durum/hata kodları yalnız bu modelde kalır; durum kararını çekirdek verir.
3. Ayar alanlarını `res.config.settings` içine ekleyin; sır alanlarına `groups='base.group_system'` verin ve `models/res_config_settings.py` içindeki `_SECRET_FIELDS` listesine yazın.
4. Loglardan sır süzme (`tools.py`) yeni sağlayıcının parola/anahtar alan adlarını kapsamalıdır.
5. `tests/test_hardening.py` RPC yüzeyi taraması, listelenmemiş her public metotta kırılır; tarama sizi ACL ve rol testlerine yönlendirir.

## 9. Mail Order (Direct POST 3D) — 19.0.1.3.0

Müşteri kartını telefonla bildirir; personel kartı **Odoo'nun sunduğu kart sayfasına** girer, sayfa kartı **doğrudan Paratika'ya** gönderir (`/paratika/api/v2/post/sale3d/<oturum anahtarı>`), banka 3D doğrulaması yapılır. Kart verisi Odoo sunucusuna, veritabanına, loglara ve chatter'a hiç girmez (tasarım K-13). Hep 3D'lidir; 3D'siz (MOTO) yol yoktur.

### 9.1 Akış
1. **Sanal POS > Mail Order** (menü, "Yeni Ödeme Linki"nin yanında). Fatura numarasını yazıp **Faturayı Getir**; tutar faturadan gelir ve değiştirilemez. Müşteri adı zorunlu; telefon/e-posta girilirse biçimi denetlenir.
2. **Kart Sayfasını Aç**: tek ödeme kaydı (Yöntem = Mail Order) ve tek Paratika oturumu açılır, tarayıcı **aynı sekmede** kart sayfasına gider. Oturum 1 saat geçerlidir. Aynı faturaya açık bir link ya da Mail Order varsa ikincisi açılmaz (DB indeksi; mesaj açık kaydın yöntemini söyler).
3. Kart sayfasında müşteriden alınan ad, kart numarası (boşluksuz), son kullanma, CVV ve taksit girilir; **Öde (3D Secure)**. Adres çubuğu Paratika/banka alan adına döner.
4. Banka SMS kodunu müşterinin telefonuna gönderir; personel kodu **müşteriden telefonla alıp yalnız banka sayfasına** girer.
5. Dönüşte Odoo durumu Paratika'ya sorar (`QUERYTRANSACTION`; dönüş gövdesi okunmaz) ve ödeme kaydını açar: **Ödendi**, ya da başarısızsa son hatanın kodu ve Türkçe mesajı kayıtta. Dönüş gelmezse bildirim ya da 10 dakikalık cron yakalar.
6. Kayıt formunda: **Kart Bilgisi Gir** (açık ve süresi dolmamış oturumda aynı sayfayı yeniden açar, yeni oturum açmaz), **Mail Order'ı Kapat** (Paratika'da onaylı/bekleyen satış yoksa kaydı "Süresi doldu" yapar ve yeni denemeye izin verir; satış varsa kapatmaz ve nedenini söyler; Paratika yanıt vermezse de kapatmaz). Hata sonrası ya aynı oturumda yeniden denenir ya da kapatılıp yeni Mail Order açılır. **Kapat Paratika oturumunu bitiremez** (iptal API'si yok): son oturum anahtarının alınmasından itibaren 1 saat içinde açılan yeni deneme yeni kayıt açmaz, **aynı kaydı aynı ödeme numarasıyla** yeniden açar; önce Paratika sorgulanır, eski oturumda ödeme alınmışsa yeni oturum açılmaz ve kayıt Ödendi olur (açık kalmış bir sekmeden ikinci tahsilat olmasın diye; tasarım K-15). Bu 1 saat içinde fatura tutarı değiştiyse yeni deneme ve aynı faturaya **link** de açılamaz; mesaj bekleme saatini söyler. Yeniden açmada kayıt başka bir kullanıcının denemesiyse sahip yeni kullanıcıya geçer; kayıt notunda önceki sahip yazılır ve ona bildirim gider. Sihirbaz, canlı önceki deneme varsa müşteri bilgilerinin oradan alınacağını önceden gösterir; farklı girilen alanlar notta listelenir.
7. Ödenmiş Mail Order'ın iptali (VOID), iadesi ve iade onayı link ödemesiyle birebir aynıdır (yalnız Yönetici). Mail Order kayıtlarında Yeniden Gönder / Linki İptal Et / Yeni Link düğmeleri yoktur.

Paratika oturumu açılamazsa (zaman aşımı, 5xx, anahtar yok) kayıt **Hata** olur (Belirsiz değil): anahtar hiçbir tarayıcıya ulaşmadığı için ödeme yapılamaz ve hemen yeni deneme açılabilir.

### 9.2 Yetki
Menü, sihirbaz, kart sayfası ve sonuç sayfası **Sanal POS / Kullanıcı** (ve Yönetici) grubuna açıktır; grupsuz iç kullanıcı menüyü görmez, RPC/HTTP ile denerse erişim reddedilir ve Paratika'ya istek gitmez. Kart sayfası ve sonuç rotası `auth='user'`'dır (public değil). `mo_return` rotası public'tir ama yalnız tetiktir (sipariş numarasını okur, durum değiştirmez).

### 9.3 PCI notu (kart verisi) — işyerinin yükümlülükleri
- **Modül tarafı (kodla zorlanır):** kart sayfasında tek bir satır içi `<script>` vardır (aşağıdaki script envanteri; dış kaynak yok); sıkı CSP (`default-src 'none'`, `script-src` yalnız o betiğin sha256'sı, `form-action` yalnız Paratika, iframe yasak); kart alanlarında `value` yok; Odoo hiçbir rotada kart alanı kabul etmez; hiçbir modelde kart no/SKT/CVV/kart sahibi alanı yok (yalnız `card_last4`). Odoo→Paratika isteklerinde kart numarası/SKT/CVV yoktur; tek istisna BIN ucunun taşıdığı ilk 8 hanedir (9.7; saklanmaz, loglanmaz). Savunma olarak log/işlem kaydı gövdelerinde Luhn-geçerli kart numaraları ve kart anahtarları maskelenir. `tests/test_mail_order_pci.py` bunları her çalıştırmada denetler (yeni bir controller, rota, model alanı ya da sağlayıcı metodu kart alanı eklerse kırılır).
- **Kapsam:** kart sayfasını Odoo sunduğu için işyeri PCI DSS'te "kart girişi sayfasını sunan sunucu" yükümlülüğünü taşır (**SAQ A-EP benzeri**; kart Odoo'dan geçmediği için SAQ D değildir). Resmî SAQ türünü bankanız/Paratika ile teyit edin. Bu yükümlülüğün işlevsel karşılığı:
  - **Sunucu güncelliği:** işletim sistemi, Docker imajı, Odoo ve Python bağımlılıkları güncel tutulur; şablon/modül değişiklikleri incelemeden geçer (kart sayfası şablonu ve `controllers/mail_order.py` kritik dosyadır). Ters vekil/Cloudflare tarafında sayfaya script enjekte eden özellikler (Rocket Loader, Auto Minify, analytics) kapalı tutulur; enjekte script CSP ile zaten çalışmaz ama konsolda ihlal olarak görünür.
  - **Personel bilgisayarları:** güncel tarayıcı ve işletim sistemi, kötü amaçlı yazılım koruması; Mail Order yalnız bu bilgisayarlardan yapılır.
  - **Tarayıcıda kart kaydetme kapalı:** Chrome/Edge politikası `AutofillCreditCardEnabled=false` (ve parola yöneticisinde kart kaydı kapalı). Sayfa `autocomplete="off"` ve CVV `password` alanıdır ama asıl önlem tarayıcı politikasıdır.
- **Script envanteri (PCI DSS 6.4.3 / 11.6.1, tasarım K-16):** kart sayfasında çalışan tek betik budur; başka script yoktur.
  - Yol: `static/src/js/mail_order_card.js` (hiçbir assets paketine girmez; `tools.mail_order_script()` okuyup `<head>`'e satır içi basar). Amaç: kart numarası gruplama/Luhn/marka, SKT denetimi, seçilen taksidin toplamını düğme ve özete yansıtma, kalan süre sayacı ve gönderimde fail-closed doğrulama; Aşama 2'den itibaren kart numarasının ilk 8 hanesiyle kart türüne göre taksit süzme. Tek ağ isteği: `POST /sanal_pos/mail_order/bin` (aynı köken, gövde yalnız `payment_id` + 8 hane; CSP `connect-src` yalnız bu yol; formda `data-bin="1"` yoksa istek yok). Tam kart numarasını okuyabildiği için incelemeye tabidir.
  - Sabitlenmiş özet: `SCRIPT_SHA256 = shzuFBD/bBX6iqmULEIgTR1nKugJ2sWS6Fr6eosXgo0=` (`tests/test_mail_order_pci.py` ve çalışma anı onayı `tools.MAIL_ORDER_SCRIPT_SHA256`; test üçünün aynı olduğunu denetler). CSP `script-src` değeri dosyadan türetilir; dosyanın hash'i onaylı değeri tutmazsa betik **sunulmaz**, sayfa script'siz açılır ve log'a `MailOrderScriptHashMismatch` yazılır (testsiz birleştirilen değişikliğe karşı).
  - Değişiklik kuralı: betik değişirse `SCRIPT_SHA256`, `tools.MAIL_ORDER_SCRIPT_SHA256` ve bu satır **aynı commit'te** güncellenir ve değişiklik kod incelemesinden geçer; hash testi bu yüzden bilerek kırılır.
  - Kapatma anahtarı (D-4 izin listesi): `sanal_pos.mail_order_script` sistem parametresi yoksa ya da değeri `true`, `1`, `yes`, `evet` ise (büyük/küçük harf ve baş/son boşluk önemsiz) betik açıktır; diğer her değerde (`False`, `off`, `hayır`, boş…) betik, `script-src`/`connect-src` kalkar ve BIN ucu 409 döner; sayfa script'siz modda tam çalışır, dağıtım gerekmez.
  - Uyarı: Cloudflare **Rocket Loader / Auto Minify** (HTML/JS) betiği değiştirirse hash tutmaz; tarayıcı betiği engeller ve sayfa script'siz moda düşer (güvenli başarısızlık, ama canlıda bu özellikler kapalı olmalı ve canlı sayfa kontrol edilmelidir).
  - Uyarı: Cloudflare **Email Address Obfuscation** özetteki maskeli e-postayı (`***@alan.com`) bağlantıya çevirir ve `/cdn-cgi/…/email-decode.min.js` betiğini enjekte eder; CSP bunu engeller (açık oluşmaz) ama özet bozulur ve konsolda CSP ihlali çıkar. `/sanal_pos/*` için Configuration Rule ile kapatın. Canlı kontrol: kart sayfası yanıtında `/cdn-cgi/` ya da `__cf_email__` geçmemeli ve `<script` sayısı tam 1 olmalı.
  - Geri alma (kart sayfası Aşama 1): `git revert` sonrası redeploy ile `-u sanal_pos` arasında kart sayfası **500 verir** (eski Python, DB'deki yeni şablonun beklediği değerleri üretmez; kapatma anahtarı bu pencerede işe yaramaz). Revert redeploy'undan **hemen sonra** `-u sanal_pos` çalıştırın (9.4 adım 4'teki komut); arada kart sayfası açılmaz. Şema/veri değişikliği yoktur.
- **Prosedür (kodla zorlanmaz):** kart bilgisi **kâğıda, e-postaya, WhatsApp/mesajlaşmaya, chatter'a, ek dosyaya yazılmaz**; telefon görüşmesi kaydı varsa kart bilgisi bölümü saklanmaz; kart yalnız Mail Order ekranından açılan kart sayfasına girilir. Banka SMS kodu yalnız banka sayfasına girilir, başka yere yazılmaz.
- **Taksit:** betik açıksa kart numarasının ilk 8 hanesiyle (BIN) kart türüne göre süzülür (9.7). Betik kapalıysa, kart Amex/Diners ise ya da BIN sorgusu yanıt vermezse işyerinin kart programı tablosu listelenir; personel müşteriden kart programını öğrenip seçer. Kartın desteklemediği sayıyı Paratika reddeder (aynı oturumda tekrar denenir). Komisyonlu taksitte Paratika vade farkını tutara kendisi ekler: tahsil edilen tutar, işlemin taksit sayısı için `QUERYINSTALLMENT` oranıyla hesaplanan toplama (fatura tutarı x (1 + oran/100), kuruşa yuvarlı) taksit sayısı kadar kuruş payıyla eşitse kayıt **Ödendi** olur ve nota "Vade farkı X TL (n taksit, %r)" yazılır. Oran durum sorgusu anında Paratika'dan alınır (saklanmaz); işlemin kart programı biliniyorsa yalnız onun oranı geçerlidir. Tutmuyorsa (fazla, az, oran bilinmiyor/sorgu yanıtsız, tek çekim, %0 oran) kayıt **İnceleme**'ye düşer. Link ve Mail Order aynı kuralı kullanır. Ödenen Tutar (iade/iptal üst sınırı) vade farkı dahil tahsil edilen tutardır.

### 9.4 Deploy (yeni stored alan `payment_method`)
**Mesai dışında** yapın; kullanıcılara önceden haber verin.
1. Veritabanı yedeği alın ve `rollback-pre-mail-order` etiketini (merge öncesi) atın.
2. Üç Sanal POS cron'unu **pasif** yapın: "durum senkronu", "bildirim tetikli senkron", "günlük temizlik ve iade senkronu".
3. Redeploy.
4. **Hemen** `-u sanal_pos` (yeni modül/bağımlılık yok; yeni model, görünüm, menü ve kayıt kuralı bu adımda oluşur). **Prod compose (`docker-compose.prod.yml`) açılışta yalnız `ugurlar_images,ugurlar_ai_studio` modüllerini `-u` eder; sanal_pos otomatik güncellenmez.** Yeni konteyner ayağa kalkınca elle çalıştırın (çalışan sunucu ayrıdır, `--stop-after-init` HTTP portu bağlamaz):
   `docker exec odoougurlar-odoo-prod odoo -d <veritabani> -u sanal_pos --stop-after-init`
   Pencere, konteynerin kendi açılış `-u`'su bitip bu komut tamamlanana kadar sürer.
5. Doğrulama: `SELECT payment_method, count(*) FROM sanal_pos_payment GROUP BY 1;` yalnız `link` döndürmeli (eski kayıtlar varsayılanla dolar, migrasyon betiği yok). Modül sürümü 19.0.1.3.0.
6. Cron'ları tekrar **aktif** edin.
7. Sanal POS kullanıcısıyla Mail Order menüsünü ve kart sayfası açılışını deneyin (gerçek ödeme yapmadan, ardından **Mail Order'ı Kapat**).
8. Canlı kabul (9.6 şartları sağlandıysa): küçük tutarlı gerçek fatura, gerçek kart, Ödendi, aynı gün İptal. Canlı veritabanı dökümü alınmaz; yalnız `sanal_pos_log` ve kayıt kontrol edilir; tarayıcı konsolunda CSP ihlali olmadığına bakılır.

Redeploy ile `-u` arasında `payment_method` sütunu yoktur: Sanal POS cron'ları ve ödeme listesi "column does not exist" hatası verir. Cron'ların pasif olması ve pencerenin kısa tutulması bu yüzdendir. `web.base.url` HTTPS ve **ASCII** olmalıdır (Paratika dönüş adresi bundan türer). Paratika paneline yeni ayar gerekmez (bildirim adresi aynı).

### 9.5 Geri alma
1. **Önkoşul:** Paratika oturumu canlı olabilecek Mail Order kalmamalı. "Kapat" Paratika oturumunu sonlandırmaz (K-15): kapatılmış veya hatalı ama son oturumu 60 dakikadan yeni ve ödenmemiş kayıtlar da sayılır; sıfır değilse en fazla 60 dakika bekleyin. Sorgu (`sent_at` UTC saklanır):
   ```sql
   SELECT count(*) FROM sanal_pos_payment
    WHERE payment_method = 'mail_order'
      AND (state IN ('sending', 'sent')
           OR (state IN ('expired', 'error') AND paid_at IS NULL
               AND sent_at > (now() AT TIME ZONE 'UTC') - interval '1 hour'));
   ```
   sonucu 0 olmalı.
2. **Eski koda dönmeden ÖNCE** veritabanında çalıştırın:
   `ALTER TABLE sanal_pos_payment ALTER COLUMN payment_method SET DEFAULT 'link';`
   NEDEN: `payment_method` NOT NULL'dır ama DB varsayılanı yoktur; eski kod bu sütunu INSERT'e koymaz ve bu satır olmadan geri dönüşten sonra **hiçbir yeni link oluşturulamaz** (`NotNullViolation`).
3. Kodu `rollback-pre-mail-order` etiketine döndürüp redeploy edin ve **hemen** eski kodla `-u sanal_pos` çalıştırın (prod'da 9.4 adım 4'teki `docker exec … -u sanal_pos --stop-after-init`; sanal_pos otomatik güncellenmez). `-u` eski görünüm/menü kayıtlarını geri yükler (DB'deki yeni görünümler `payment_method` alanını ve Mail Order düğmelerini referanslar) ve Mail Order menüsünü kaldırır. `payment_method` sütunu veritabanında kalır (zararsız); sonradan yeni sürüme ileri `-u` yapılırsa ORM sütunu kendi tanımına getirir.
4. Eski kodda Mail Order kayıtları "link" gibi görünür: `sent` olanlar senkronla Ödendi/Süresi doldu olur; ödenmişlerin iptal/iadesi link yoluyla çalışır. Bu kayıtlarda Yeniden Gönder / Linki İptal Et görünür ama Paratika hata döner (zararsız); personele bu düğmeleri kullanmamaları söylenir.
5. Paratika tarafında geri alınacak ayar yoktur (dönüş adresi oturum başınadır). Veri kaybı yoktur; geri dönüş için gereken tek SQL adım 2'deki `SET DEFAULT` satırıdır.

### 9.6 G0 canlı denemesi ve canlıya çıkış şartı
Dokümanda Direct POST'un işyeri bazında açılması gerekip gerekmediği yazmaz; Paratika TEST kimlik bilgisi olmadığından deneme **canlı işyerinde** yapılır. Mail Order yalnız şu şartlar sağlanınca canlıda kullanıma açılır:
1. **Paratika'dan yazılı sale3d teyidi:** "Canlı işyerimizde Direct POST 3D (`/paratika/api/v2/post/sale3d/`) açık mı? Açık değilse açar mısınız? (MOTO yetkisi istemiyoruz.)" Kapalıysa oturum/ödeme `ERR10136` (entegrasyon modeli işyerine kapalı) ya da `ERR10154` (3D kısıtı) gibi bir hata döner; kayıt Hata olur ve mesaj Türkçe gösterilir.
2. **G0 spike'ı:** `.ekip/20261022-mail-order/spike_sale3d.py` (yalnız standart kütüphane; adımlar `spike-talimat.md`). 1,00 TL gerçek çekim, kullanıcı kendi kartıyla yapar, aynı gün betik ile **VOID** edilir (mümkünse mesai içinde, sabah). Kart bilgisi betiğe ve geliştiriciye gelmez (kart sayfası yerelde açılır, form doğrudan Paratika'ya gider); kimlik bilgileri dosyaya yazılmaz. Ölçülen belirsizlikler `spike-direct-post.md`'ye işlenir: sale3d'nin 302 mi HTML mi döndüğü (302 ise CSP `form-action` değerine `https:` eklenir: `controllers/mail_order.py` `FORM_ACTION_EXTRA_SOURCES`), **aynı ödeme numarasıyla (MPID) ikinci satışın Paratika'da reddedildiği (spike adım 12a; K-15'in dayanağı, reddedilmezse tasarım yeniden açılır)**, `SESSIONEXPIRY` için kabul edilen en kısa değer, dönüş POST alan adları, hata sonrası aynı oturumla yeniden deneme, taksit alanı ve `QUERYINSTALLMENT` biçimi, yarım kalan 3D'nin Paratika'daki görünümü.
3. Spike sonucuna göre gerekirse küçük ayar yapılır (yalnız `FORM_ACTION_EXTRA_SOURCES`, `mo_return` yöntemi/alan adı, `installmentCount` tek çekim değeri, `query_installments`/`direct_post_url` biçimi), testler yeniden koşulur ve 9.4 adım 8'deki canlı kabul tamamlanır.

Kod, G0 sonucu gelmeden tasarım varsayımlarıyla yazılmıştır; sonuç beklenen biçimde gelmezse değişecek yerler yukarıdaki listeyle sınırlıdır.

### 9.7 Kart türüne göre taksit (BIN, Aşama 2)
Personel kart numarasının 8. hanesini yazınca betik ilk 8 haneyi (BIN) Odoo'ya gönderir; Odoo Paratika'ya `QUERYBIN` (kredi kartında ayrıca `QUERYPAYMENTSYSTEMS`) sorar ve taksit kartlarını süzer. Kart numarasının geri kalanı, SKT ve CVV Odoo'ya gitmez (K-13 daraltılmış istisnası).
- **Kart türü kuralı (K-19), öncelik sırasıyla:** yurt dışı kart (ülke dolu ve `TUR` değil) → yalnız tek çekim, "Yurt dışı kartla taksit yapılamaz."; banka kartı / ön ödemeli → yalnız tek çekim; kredi kartı → yalnız kartın programının taksitleri (oran programın oranı). Boş ülke yurt içi sayılır. Ekranda "Banka · Program · Kredi kartı" yazar; yabancı kartta program yazılmaz ("Banka · Kredi kartı · Yurt dışı"). Tanınmayan banka kodu başlık biçiminde görünür (kod listesi `tools._BANK_ALIASES`; canlıda yeni kod görülürse eklenir).
- **Uç:** `POST /sanal_pos/mail_order/bin`, gövde JSON `{"payment_id": <int>, "bin": "<8 rakam>"}` (en fazla 256 bayt), `auth='user'`, Sanal POS grubu. Yanıt `200` (`ok, card_type, foreign, bank, program, brand, detected, installments, note, rows`), hata gövdesi `{"ok": false, "error": …}`: `400` biçim, `403` yetki, `404` kayıt yok, `409` kayıt kapalı/süresi dolmuş ya da betik kapalı (D-4 anahtarı), `429` hız sınırı, `502` Paratika hatası/zaman aşımı/adres izinli değil. Her hatada sayfa tüm seçenekleri gösterir ve "Kartın taksitleri doğrulanamadı…" uyarısını yazar; ödeme hiçbir durumda engellenmez.
- **Amex / Diners (34, 37, 300-305, 36, 38, 39):** 14-15 haneli kartta ilk 8 hane PCI kesme sınırını aşar (PCI SSC FAQ 1091); BIN sorulmaz, uç 400 verir, sayfa "Bu kartta taksit sorgulanmaz…" yazar ve tüm seçenekleri gösterir.
- **BIN saklanmaz:** model alanı yoktur; `sanal.pos.log` satırında BIN `***` olarak maskelenir, yanıttaki yankısı ve hata metinlerinden silinir; uygulama logu, chatter ve ödeme kaydına girmez. V-4: Odoo `debug_rpc` HTTP istek gövdesini loglamaz; ters vekil/Cloudflare tarafında **istek gövdesi kaydı (payload logging) kapalı** olmalıdır.
- **Hız sınırı:** son 1 saatte kayıt başına 20, kullanıcı başına 60 `QUERYBIN`; aşımda `429`, pencere başına kullanıcı için tek `BIN_RATE_LIMIT` log satırı ve tek uyarı. Reddedilen ve geçersiz istekler sayılmaz. BIN log satırları ödemeye FK ile bağlanmaz (KK-2.8: ödeme satırında kilit alınmaz); kayıt `request_body` sonundaki `"_payment_id": <id>` işaretiyle tanınır, bu yüzden **log ekranında bu satırların Ödeme sütunu boştur**. Eşzamanlı istekler kullanıcı ve kayıt başına `pg_advisory_xact_lock` ile sıralanır (bekleme en çok 0,5 sn, alınamazsa `429`).
- **Süre bütçesi (NFR-2.1, 5 sn):** iki kilit en çok 2 × 0,5 sn + `QUERYBIN` en çok 3,5 sn; kredi kartında ikinci çağrı yalnız istek başından 1,0 sn geçmediyse yapılır (aksi `502`). Betik 6 sn'de isteği keser.
- **Paratika adresi:** BIN yalnız `https` ve kart formuyla aynı izin listesindeki hosta (`vpos.paratika.com.tr`, `test.paratika.com.tr`; port ve kullanıcı bilgisi yok) gider; ayar başka adres gösterirse istek yapılmaz, log satırı yazılmaz, uç `502` döner ve log'a hata yazılır.
- **Betik bütçesi:** `mail_order_card.js` en çok 12 KB (12288 bayt, `test_mail_order_pci.py` denetler); değişiklikte 9.3'teki hash kuralı geçerlidir.
- **Canlı kontrol:** kart sayfası yanıt başlığındaki CSP'de `connect-src https://<alan adı>/sanal_pos/mail_order/bin` olmalı. Bunun için Odoo `proxy_mode = True` çalışmalı ve ters vekil `X-Forwarded-Proto: https` ile `X-Forwarded-Host` göndermelidir; aksi halde istek http görünür, `connect-src` ve `data-bin` hiç basılmaz, log'a "BIN taksit sorgusu kapalı, kart sayfası https değil" uyarısı düşer ve sayfa Aşama 1 gibi tüm seçenekleri gösterir (güvenli başarısızlık). Cloudflare payload logging kapalı olmalı (yukarıda). **Cloudflare Tunnel arkasında** (`X-Forwarded-Host` gelmez, Odoo 19 `proxy_mode` ProxyFix'i atlar, istek http görünür): `web.base.url` `https://<alan adı>` olmalı **ve `web.base.url.freeze = True` olmalı** (yoksa Odoo 19 yönetici girişinde `web.base.url`'i istek adresine, yani `http://`'ye yeniden yazar ve BIN özelliği sessizce kapanır). Modül `web.base.url` https ise ve ana makinesi isteğin `Host`'uyla birebir aynıysa sayfayı https sayar; `X-Forwarded-Proto` başlığına güvenmez. Eşleşmezse uyarı log'u hangi koşulun tutmadığını söyler.
- **Deploy:** yeni model alanı, tablo ya da bağımlılık yoktur; redeploy sonrası `-u sanal_pos` (9.4 adım 4'teki komut) yeni rota/şablon için gerekir. Redeploy ile `-u` arasında sayfa Aşama 1 davranışıyla çalışır (formda `data-bin` yoktur, betik istek atmaz). Kapatma: `sanal_pos.mail_order_script = False` (9.3) betiği ve BIN ucunu birlikte kapatır.

### 9.8 Tekrar dene / Bunun yerine link gönder (Aşama 3)
Ödeme kaydı formunda ve sonuç sayfasında (CSRF'li POST formu, betiksiz) iki eylem vardır; yalnız mail order kaydında, durum `Gönderildi`, `Süresi doldu` ya da `Hata` iken ve ödeme alınmamışken çalışır. Yetki modelde denetlenir (Sanal POS grubu; kayıt sahibi şartı yok).
- **Tekrar dene / Yeni deneme aç:** önce fatura sınırı (son 24 saatte 3 başarısız deneme) bakılır; sonra fatura Nebim'den yeniden getirilir (okunamazsa hiçbir şey kapatılmaz, kayıt açık kalır); açık kayıt varsa Kapat çalışır (sorgu yanıtsız, bekleyen işlem, ödeme ya da inceleme çıkarsa yeni oturum AÇILMAZ, bildirim döner); en son Mail Order sihirbazı müşteri bilgileri kayıttan alınarak çalıştırılır. K-15 gereği canlı oturumu olabilecek önceki deneme aynı MPID ile yeniden açılır.
- **Bunun yerine link gönder:** son başarılı oturumdan (`sent_at`) 1 saat geçmeden hiçbir yazım ya da Paratika çağrısı yapılmaz, en erken saat söylenir (S3.2). Sonra Kapat ve ön dolu link sihirbazı (`/odoo/action-sanal_pos.action_sanal_pos_payment_create_wizard/<id>`, 303).
- **Uçlar:** `POST /sanal_pos/mail_order/retry/<id>`, `POST /sanal_pos/mail_order/link/<id>`; `auth='user'`, CSRF zorunlu. Yanıt: kart sayfası/sihirbaz için 303, iş kuralı engelinde sonuç sayfası 409, yetkisizde 403, olmayan kayıtta 404.
- **Eşikte oturumu kapatma (güvenlik eki):** her durum senkronunun sonunda, fatura sınırı dolmuşsa fatura kilidi (`pg_advisory_xact_lock`, 2 sn) altında faturanın açık mail order oturumu Odoo'da kapatılır: token silinir, `expires_at` şimdiye çekilir; durum o anda değişmez, sonraki senkron Kapat ile aynı kuralla `Süresi doldu` yapar (aynı MPID'nin onayı gelirse `Ödendi`). Eşik geçişi ile kapatma aynı senkrondaysa kayda tek not düşer ("Deneme sınırı doldu … Mail order oturumu kapatıldı", oluşturana bildirim); başarısız her işlemin kendi deneme notu ayrıca kalır. Aynı faturanın başka açık kaydı kilitlenebiliyorsa bayraklanır ve kendi senkronunda kapanır. O kaydı başka bir senkron tutuyorsa ona yazılmaz: Odoo REPEATABLE READ çalıştığı için tutan işlem yeni sayıyı göremeyebilir; periyodik durum senkronu 1 dk sonrasına çekilir ve kayıt orada kapanır (bu arada kart sayfası, "Kart Bilgisi Gir" ve BIN ucu sınırı yine kendi işleminde uygular). Paratika çağrısı ve commit yoktur.
- **Sonuç sayfası ve K-15:** deneme satırı görüldüğü oturumun başlangıcını (`session_sent_at`) taşır; aynı kayıt K-15 ile yeniden açıldıysa önceki oturumun reddi geçmişte görünür ama "Tekrar dene" açtırmaz, sayfa yeni oturumun sonucunu bekler.
- **Bilinen sınırlama:** Paratika oturumu Odoo'dan sonlandırılamaz (iptal API'si yok). Eşikten önce açılmış bir sekme, token Paratika'da hâlâ geçerliyse doğrudan Paratika'ya gönderebilir; bu kapatma yalnız Odoo tarafını kapatır. Böyle bir onay, kayıt `Süresi doldu`'ya geçmeden (sonraki senkrondan önce) gelirse kayıt `Ödendi` olur; sonra gelirse geç ödeme kuralıyla `İncelemede` olur (cron `Süresi doldu` mail order'ı sorgulamaz; "Durumu Sorgula" ya da yeni link öncesi sorgu yakalar). Paratika'nın başarısız denemeden sonra aynı token'ı kabul edip etmediği G0 canlı denemesinde ölçülecek (`MO_TOKEN_REUSABLE_AFTER_FAIL`, varsayılan `False`: Tekrar dene her zaman yeni oturum açar).
- **Deploy (YENİ TABLO `sanal_pos_payment_attempt`; sürüm 19.0.1.4.0):** 9.4'teki gibi **mesai dışında**:
  1. Üç Sanal POS cron'unu **pasif** yapın (durum senkronu, bildirim tetikli senkron, günlük temizlik ve iade senkronu).
  2. Redeploy, ardından **hemen** `docker exec odoougurlar-odoo-prod odoo -d <veritabani> -u sanal_pos --stop-after-init` (prod açılışı sanal_pos'u güncellemez).
  3. Doğrulama: `SELECT to_regclass('sanal_pos_payment_attempt');` boş olmamalı; Uygulamalar'da modül sürümü 19.0.1.4.0; bir mail order kaydının formunda "Deneme Geçmişi" sekmesi açılmalı.
  4. Cron'ları **elle** tekrar aktif edin (cron kayıtları `noupdate=1`; `-u` onları açmaz).
  Redeploy ile `-u` arasında tablo yoktur: mail order senkronu, kart sayfası, BIN ucu ve Mail Order sihirbazı `UndefinedTable` hatası verir (link akışı etkilenmez); cron'ların pasif olması ve pencerenin kısa tutulması bu yüzdendir.
  **Geri alma:** önceki imajı redeploy edin ve yine **hemen** `-u sanal_pos` çalıştırın; aksi halde DB'deki form görünümü olmayan `attempt_ids` alanını referanslar (`Invalid field 'attempt_ids'`) ve **hiçbir ödeme formu açılmaz**. Tablo veritabanında yetim kalır (zararsız; ödemeler etkilenmez).
