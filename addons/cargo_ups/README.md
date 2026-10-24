# Kargo - UPS Türkiye (`cargo_ups`)

Odoo 19. `cargo` çekirdeğinin UPS Türkiye eklentisi: `delivery.carrier` için `ups_tr` tipi, UPS SOAP istemcisi (oluştur / iptal / referansla sorgu), UPS il/ilçe kodları (1014 ilçe, KKTC hariç) ve hazır "UPS Türkiye" firma kaydı. Gönderi akışı, gruplar, etiket PDF'i ve API çekirdekte anlatılır: `addons/cargo/README.md`.

Bağımlılık: yalnız `cargo`. Yeni Python paketi yoktur (`requests`, `lxml` imajda mevcut). Mevcut Uğurlar modüllerine bağımlılık yoktur.

**Kapsam (A1):** gönderi oluşturma, etiket, iptal, uzlaştırma, kapıda ödeme. **Takip (durum güncelleme, cron) bu sürümde yoktur**; gönderi `created`'da kalır.

## 1. Kurulum

- İlk kurulum (canlıda elle, `cargo` ile birlikte): `odoo -d <veritabani> -i cargo,cargo_ups --stop-after-init`. Sonra: `-u cargo,cargo_ups`.
- Kurulum "UPS Türkiye" firma kaydını getirir: **test ucunda** (`prod_environment` kapalı), kapıda ödeme **açık, yalnız nakit**, `integration_level = rate`. Hesap bilgisi **veride yoktur**.
- Firma ve il/ilçe takma ad verisi `noupdate`'dir: yöneticinin firma ayarları ve eklediği diğer adlar `-u` ile **ezilmez** (2 kez `-u` ile doğrulandı). Kod verisi (`cargo.area.csv`) güncellemede yenilenir.

## 2. UPS firma ayarı (Kargo / Yönetici; kargo firması kaydı "UPS Türkiye" > "UPS Türkiye" sekmesi)

| Alan | Not |
|---|---|
| UPS müşteri no, gönderici hesap no, kullanıcı adı, şifre | Gönderi servisi kimliği. **Sırdır**: yalnız Kargo / Yönetici görür; kopyalanan firmaya taşınmaz; loga ve chatter'a yazılmaz (hesap no chatter'da son 2 hane). Değerleri belgeye, koda, ekran görüntüsüne yazmayın. |
| UPS takip kullanıcı adı / şifre | Boşsa gönderi kimliği kullanılır. Bu sürümde takip yok, alanlar A2 içindir. |
| UPS hizmet | Varsayılan Domestic Standard. |
| UPS ödeme türü | Varsayılan "Gönderici öder". "Üçüncü taraf öder" desteklenmez (UPS hata döner, gönderi `failed`). |
| UPS paket türü | Paket / Zarf. |
| Alıcıya SMS (UPS) | Varsayılan kapalı. |

Hizmet alanları (hizmet, ödeme türü, paket türü, SMS) da faturayı belirlediği için **yalnız Kargo / Yönetici** okur ve yazar. Stok ve satış yöneticisi firma kaydını açabilir ama bu alanları değiştiremez (O-1). Firma kaydı değişiklik izi tutmaz; bu alanları değiştiren kişi kayıtta görünmez.

Ayar ekranına (Ayarlar > Kargo) sır girilmez; yalnız varsayılan firma seçilir. Hangi **tüzel kişiliğin** UPS hesabının girildiği (şirket/hesap eşleşmesi) canlıdan önce yöneticiyle teyit edilmelidir.

**Firma şirketler arasında paylaşımlıdır (D-4).** Hazır "UPS Türkiye" kaydında şirket (`company_id`) boştur; alan teslimat ürününün şirketinden gelir, ürün de şirketsizdir. Çok şirketli veritabanında **her şirketin gönderisi aynı UPS hesabıyla açılır ve aynı hesaba faturalanır**. Gönderici adı ve adresi ise gönderiyi açan şirketten gelir. Canlıda birden çok şirket varsa duman testinden önce firmaya ve teslimat ürününe hesabın sahibi olan şirketi atayın. Başka şirket UPS kullanacaksa ona kendi hesabıyla ayrı bir UPS firması açın. Teslimat ürününün şirketini (dolayısıyla firmanın şirketini) yalnız Kargo / Yönetici değiştirebilir; ürün yöneticisi değiştirmeye çalışırsa yetki hatası alır.

## 3. Test ucu / canlı bayrağı (K-26)

- Firmadaki **Üretim ortamı (`prod_environment`)** bayrağı: **kapalı = UPS test ucu** (`wsCreateShipmenttest`), **açık = canlı**. Kurulumda kapalı gelir; canlıya geçiş yöneticinin elle yaptığı bir eylemdir ve duman testi (6. bölüm) bittikten sonra yapılır.
- Test ucu yalnız oluştur / iptal / oturum içindir. UPS'in **sorgu (takip) servisinin test ucu yoktur**: test modunda "referansla sorgu" UPS'e **gitmez** ve "bulunamadı" döner. Test gönderisi ücretsiz kabul edilir; 15 dk kuralı yine uygulanır.
- Test gönderisi formda/listede **TEST** işaretlidir. Test ucunun canlı kimlik bilgisini kabul edip etmediği canlıda ilk adımdır (CD-1).
- **Test modunda transfere hiçbir şey yazılmaz (K-26):** ne kargo firması (`carrier_id`) ne takip numarası. Transferin "Takip numarası" alanı boş kalır ve pazaryerine/Shopify'a takip gitmez. Bu bilinçlidir: test barkodu gerçek değildir, müşteriye gitmemelidir. Gönderi, takip numarası ve etiket yalnız gönderi kaydında (Kargo menüsü ve transferdeki gönderi bağlantısı) görünür. Duman testinde "transferde takip no yok" bir hata **değildir**; takip no yalnız canlı gönderide yazılır. Canlıda da pazaryeri transferine yazılmaz.
- Canlı gönderi iptal edilince transferdeki takip numarası silinir; kargo firması (`carrier_id`) transferde kalabilir.
- **DB kopyasında** firmanın bayrağını kapatın (kopya canlı UPS'e değil test ucuna gitmeli).

## 4. Kapıda ödeme (ODP)

- UPS hesabında ODP açıktır (kullanıcı kararı); kayıtta **ODP açık, yalnız nakit**. Tutar `ValueOfGoods` olarak noktalı ondalıkla gider (ör. `1249.90`), tahsilat tutarıdır; sigorta ayrı alandır.
- **Kart ve çek kapalıdır.** UPS kodları: nakit = 1, çek = 2, kart = 3; yalnız **nakit** canlıda kullanılmış ve doğrulanmıştır. Kart/çek yalnız, canlıda bir ODP gönderisi UPS panelinde o kodla doğrulandıktan sonra Kargo / Yönetici tarafından firma formundan açılır (CD-4).
- Çekirdekteki "Kapıda ödeme üst sınırı" (Ayarlar > Kargo) UPS için de geçerlidir.

## 5. İl/ilçe eşleme, diğer adlar ve elle seçim (K-25)

- Veri: UPS "Güncel il ilçe listesi" sayfası, **1014 satır**, 81 il. KKTC ilçeleri alınmamıştır.
- Eşleme yalnız **tam ad anahtarıyla**; geri düşüş yoktur. İl adı, boş ilçe ve büyükşehirde "Merkez" otomatik eşlenmez: operatör gönderi formundan **Kargo ilçesi**'ni seçer (shopicargo'daki sessiz yanlış ilçe sorununun bedeli budur).
- Veriye **yalnız kesin ad değişiklikleri** diğer ad olarak girilmiştir: `EYUP` ← Eyüpsultan, `KAZAN` ← Kahramankazan, `BEYLIKAHIR(B.OVA)` ← Beylikova. Parantezli/eğik çizgili 19 kayıt, parçalarından eşlenir (`KALE (DEMRE)` → `DEMRE`, ancak gerçek `DEMRE` kaydı varsa o kazanır).
- Yönetici diğer ad ekler: Kargo > Yapılandırma > İl/İlçe Kodları > kaydı aç > **Diğer adlar** (virgülle). Yönetici adları güncellemede korunur.
- **Açık sorular (UPS'e sorulacak, CD-12):**
  - Hatay `MERKEZ` = Antakya mı? Diyarbakır `MERKEZ` (283) = Yenişehir mi? Teyitten önce bu adlar **eklenmemelidir**; operatör elle seçer.
  - **Antalya Aksu** UPS listesinde yoktur; kodu nedir? Teyide kadar Aksu adresleri elle (UPS'in belirttiği ilçeyle) seçilir.
  - Güncel il/ilçe listesi var mı?
  - Teyit gelince yönetici diğer adları ekler; kod değişmez.

## 6. Etiket: %100 ölçek (10x15 termal)

- UPS PNG'si **96,5 × 137,2 mm** referans boyutunda yerleştirilir (barkod ≥2 cm geniş, ≥12 cm yüksekliğe yakın, ≥200 dpi, sessiz bölge ≥7 mm). `10x15` sayfada ortalanır (varsayılan, termal yazıcı); `A4` sol üstte.
- **Yazdırırken ölçek %100 / gerçek boyut olmalıdır**, "sayfaya sığdır" kapalı. Yazıcı sürücüsünde kenar boşluğu ve ölçek ayarını kontrol edin; küçülen etiketin barkodu kurye cihazında okunmayabilir (CD-5).
- Not: oranı koruyarak 10 cm'e sığdırılan etikette barkod yüksekliği ~11,8 cm kalır (UPS'in kendi örneği de dikeyde ~%6 esnetir); okunurluk canlıda doğrulanır.

## 7. Deploy ve geri alma

Deploy adımları `addons/cargo/README.md` 8. bölümdedir (canlıda yeni modül: önce `-i cargo,cargo_ups`; üretim compose'u bunları otomatik kurmaz). Özet: yedek + rollback etiketi → redeploy → `-i cargo,cargo_ups` → grup atama → UPS hesabı → (çok şirketse) firmaya şirket ata (D-4, 2. bölüm) → duman testi → bayrağı canlıya al. **Canlıda UPS'e ilk çağrıdan önce sunucunun çıkış IP'sinin UPS izin listesinde olması gerekiyorsa ekletin (CD-2).**

Geri alma sırası: (1) firmada `prod_environment` kapat / firmayı arşivle; (2) gönderi listesini CSV dışa aktar, **önce `cargo_ups`, sonra `cargo`** kaldır (`ups_tr` firmaları: gönderi kaydı varsa `fixed` + arşivli, yoksa hazır UPS kaydı silinir ve transferlerde `carrier_id` boşalır); (3) git revert ancak modüller kaldırıldıktan sonra; (4) UPS'te açık kalan gönderileri UPS panelinden iptal et.

## 8. CANLI DUMAN TESTİ (CD-1..CD-12)

Kullanıcıyla birlikte yapılır; her satır geçince işaretlenir. Önce firma **test ucundayken** (bayrak kapalı), ardından canlıda. Durum: *Açık* = canlıda doğrulanacak, *Kısmen*/*Kapandı* = tasarımda kanıt var.

| # | Doğrulanacak | Durum | Nasıl bakılır |
|---|---|---|---|
| CD-1 | Test ucu canlı kimlikle oturum açıyor mu; oluştur + iptal çalışıyor mu; **telefon biçimi** | Açık | Bayrak kapalı: ODP'siz 1 gönderi oluştur, hemen iptal et. Test ucu kimliği reddederse UPS'ten test hesabı iste ya da canlıda ODP'siz 1 gönderi oluşturup hemen iptal et (iptalin ücretlendirilip ücretlendirilmediğini UPS'e sor). **Telefon biçimi:** telefon rakamlara indirgenip olduğu gibi gider; `+90 532 123 45 67` → `905321234567` (12 hane, 90 önekli), `0532…` → `05321234567`. Cep numarası cep alanına, diğerleri sabit alana gider. İlk gönderide UPS panelinde alıcı ve gönderici telefonunun doğru göründüğünü (Alıcıya SMS açıksa SMS'in de gittiğini) kontrol et; UPS 10 hane (`5321234567`) isterse düzeltme tek yerdedir (`models/delivery_carrier.py` `_phones`). |
| CD-2 | Sunucu IP'si UPS izin listesine alınmalı mı | Açık | İlk çağrıda bağlantı/yetki hatası geliyorsa IP'yi UPS'e bildir. |
| CD-3 | Kuruşlu ODP tutarı panelde aynen görünüyor mu | Kısmen (noktalı ondalık canlıda kabul ediliyor) | İlk ODP gönderisi (ör. 1249,90): UPS panelinde kuruşu karşılaştır. |
| CD-4 | ODP ödeme kodları: nakit=1 doğrulandı; kart=3, çek=2 açık | Nakit kapandı; kart/çek açık | Kart/çek gerekirse tek gönderiyle panelde doğrula, sonra firma formundan aç. |
| CD-5 | Etiketin kurye cihazında okunması (barkod, ≥200 dpi) ve Türkçe karakterler | Açık | 10x15 termal yazıcıda %100 ölçekle bas; barkodu okut; ad/adres karakterlerini kontrol et. |
| CD-6 | İptal hangi aşamaya kadar mümkün; yeni gönderi referans sorgusunda kaç dakikada görünüyor | Açık | Kurye almadan/aldıktan sonra iptal dene; oluşturduktan N dakika sonra Uzlaştır'la bul (15 dk eşiği buna göre doğrulanır). |
| CD-7 | İade gönderene teslim kodu (`StatusCode=2` + `ReturnFlag` mı, ayrı takip no mu); takip yanıtında kimlik alanı | Açık (A2) | Takip A2'dedir; bu sürümde yalnız not al. |
| CD-8 | `ValueOfGoods` = tahsil tutarı | Kapandı | shopicargo canlı kullanımı + hesapta ODP açık teyidi. |
| CD-9 | SOAP Fault türleri (K-27) | Destekleniyor, canlıda gözlem | `soap:Client` Fault (istek okunamadı) = işlenmedi → gönderi `failed`, yeniden gönderilebilir. `soap:Server` ya da kodsuz/bilinmeyen Fault oluştur/iptalde **belirsiz** sayılır (UPS kaydı yazdıktan sonra da hata verebilir): gönderi `uncertain` kalır, yeniden gönderilmez, Uzlaştır ile ya da UPS panelinden kontrol edilir. Bilerek hatalı istek gönderme; canlıda Fault görülürse türünü ve panelde kayıt olup olmadığını not al. Fault metni kayda yazılır (sırlar temizlenir). |
| CD-10 | Takip sorgusu liste üst sınırı (50 varsayıldı) | A2, kapsam dışı | - |
| CD-11 | `ProcessTimeStamp` saat dilimi (Türkiye saati varsayıldı) | A2, kapsam dışı | - |
| CD-12 | UPS'e sorulacaklar: Hatay/Diyarbakır `MERKEZ`, Antalya Aksu kodu, güncel liste | Açık | Bu README 5. bölüm. |

**G9 ek maddeleri (canlıda bakılacak):**
- **"Bulunamadı" yanıt biçimi:** referansla sorguda kayıt yokken UPS boş liste mi, `ErrorCode≠0` mı dönüyor? `ErrorCode≠0` dönerse sonuç `error` olur ve gönderi `uncertain` kalır (güvenli; kargo yöneticisi gönderi formundaki "Kargo firmasında yok" eylemiyle gerekçe yazarak kapatır, K-28). Test ucunda sorgu olmadığından yalnız canlıda görülebilir: ilk gönderiden sonra Uzlaştır'ı bir kez dene, ayrıca olmayan bir referansla.
- **Fault türü** (CD-9: yalnız `soap:Client` işlenmedi sayılır) ve **test ucunun canlı kimliği kabulü** (CD-1, R13).
- **Barkod PNG:** yanıttaki `BarkodArrayPng` blokundan etiket görüntüsü geliyor mu, paket sayısı kadar mı, PDF doğru mu (CD-5).
- **Çok paketli sorgu:** 2+ paketli bir gönderi oluştur; takip no tek mi, etiket sayısı paket sayısına eşit mi, referans sorgusu `count>1` uyarısı vermeden doğru mu?
- **Takip bağlantısı:** firma formundaki/transferdeki UPS takip bağlantısı gönderinin takip numarasıyla UPS sayfasında doğru gönderiyi açıyor mu (`ups_tr_get_tracking_link`).

**Canlıya geçiş sırası:** CD-1 (test ucu) → hesap bilgilerini canlıda doğrula → bayrağı aç → ODP'siz 1 gönderi → ODP nakit 1 gönderi (CD-3) → etiket basımı (CD-5) → iptal (CD-6) → kullanıcılara aç.
