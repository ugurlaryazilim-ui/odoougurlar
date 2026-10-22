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
| **Sanal POS / Kullanıcı** | Fatura sorgular, link oluşturur, yeniden gönderir, linki iptal eder, durum yeniler; talepleri okur. |
| **Sanal POS / Yönetici** | Kullanıcının hepsi + ödeme iptali (VOID), iade (REFUND), inceleme (kabul/kapat), işlem kayıtları. |
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
1. **Mesai dışında** merge ve redeploy yapın; ardından **hemen** `odoo -d <veritabani> -u sanal_pos --stop-after-init`. Redeploy ile `-u` arasında Python kodu yeni kolonları (`sanal_pos_refund.provider_status`, `provider_status_detail`, `pending_alert_sent`) okur; bu sürede üç Sanal POS cron'u ("durum senkronu", "bildirim tetikli senkron", "günlük temizlik ve iade senkronu"), ödeme formu (İade Geçmişi) ve iade/iptal sihirbazı hata verir. Pencereyi kısa tutun, kullanıcılara önceden haber verin; isteğe bağlı olarak bu üç cron'u redeploy öncesi pasif yapıp `-u` sonrası açın.
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
