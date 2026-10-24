# Kargo çekirdeği (`cargo`)

Odoo 19. Sağlayıcıdan bağımsız **kargo gönderisi** çekirdeği: gönderi kaydı (`cargo.shipment`), Gönder / Uzlaştır / İptal akışı, belirsiz sonucun uzlaştırılması, etiket PDF'i, il/ilçe eşleme modeli (`cargo.area`), transferden (stock.picking) gönderi açma ve başka modüllerin çağıracağı `create_and_send` API'si. Kargo firması = `delivery.carrier`; sağlayıcıya özgü her şey eklentidedir (ilk eklenti: `cargo_ups`, ayrı README'si var).

Bağımlılıklar: `mail`, `stock_delivery` (Odoo çekirdeği). **Mevcut Uğurlar modüllerine bağımlılık yoktur**, hiçbiri de `cargo`'ya bağlı değildir. Yeni Python paketi yoktur (`requests`, `lxml`, `reportlab` imajda mevcut).

## 1. Kurulum ve güncelleme

- Yeni modül olduğu için canlıda **önce elle kurulur**: `odoo -d <veritabani> -i cargo,cargo_ups --stop-after-init` (ayrıntı 8. bölüm).
- Sonraki sürümlerde: deploy biter bitmez **hemen** `odoo -d <veritabani> -u cargo,cargo_ups --stop-after-init`. Yeni saklanan alanlar `-u` olana kadar yoktur; arada yalnız Kargo ekranları hata verir.
- Test: `odoo -d bc_test -u cargo,cargo_ups --test-tags /cargo,/cargo_ups --stop-after-init --workers=0 --max-cron-threads=0 --db-filter=^bc_test$` (UPS çağrıları taklit edilir; gerçek ağ çağrısı gitmez).

## 2. Gruplar

| Grup | Ne yapar |
|---|---|
| **Kargo / Kullanıcı** | Gönderi açar, gönderir, uzlaştırır, iptal eder, etiket basar; transferden gönderi açar; `create_and_send` çağırabilir. |
| **Kargo / Yönetici** | Kullanıcı yetkileri + firma kapıda ödeme (ODP) bayrakları, sağlayıcı hesap bilgileri, il/ilçe kodları ve diğer adlar. Yönetilen firmanın test/canlı, tip, entegrasyon, etkinlik, şirket ve ürün alanları ile **teslimat ürününün şirketi** (firma şirketi ondan gelir) yalnız bu grupta değişir. |

`base.group_system` bu gruplara **otomatik eklenmez**; kullanıcıya grup elle atanır (en az yetki). Gruba sahip olmayan kullanıcı, `sudo()` ile bile gönderi işlemi yapamaz (AccessError). Gönderi çok şirketlidir: yalnız seçili şirketlerin gönderileri görünür.

## 3. Ayarlar (Ayarlar > Kargo; yalnız sistem yöneticisi)

| Ayar | Not |
|---|---|
| Varsayılan kargo firması | Gönderide firma seçilmezse (ve API'de `carrier` verilmezse) kullanılır. Yalnız kargo çekirdeğinin yönettiği firmalar listelenir. Boşsa "Varsayılan kargo firması ayarlı değil" hatası verilir. |
| Varsayılan paket ağırlığı (kg) | Gönderide ağırlık verilmezse paket başına kullanılır. |
| Kapıda ödeme üst sınırı | 0 = sınırsız. Aşan tutarlı ODP gönderisi açılmaz. **Canlıya geçmeden önce girin** (taslakta tutarı değiştiren kişi chatter'da izlenir ama sınır yoksa her tutar gider). |
| Etiket sayfası | `10x15` termal (varsayılan) ya da `A4`. |

Ayar ekranında **sır yoktur**; hesap bilgileri firma kaydındadır (sağlayıcı README'si). Ayarlar şirket başına `res.company` alanlarında tutulur.

## 4. Firma ve kapıda ödeme (ODP)

- Bir firmanın kargo çekirdeğince yönetilmesi, sağlayıcı eklentisinin `<tip>_cargo_send` metodunu tanımlamasıyla olur. Yönetilen firmanın `integration_level` değeri **`rate`** olmak zorundadır: sevkiyat onayında kargo **otomatik açılmaz**; gönderi yalnız elle açılır.
- Firma formunda (yalnız Kargo / Yönetici): **Kapıda ödeme (ODP) açık**, **ODP: nakit** (varsayılan açık), **ODP: kredi kartı**, **ODP: çek** (ikisi varsayılan kapalı). ODP kapalı firmada tutarlı gönderi açılamaz; kapalı şekil seçilemez.
- Kart/çek yalnız sağlayıcıda o kodun canlıda doğrulanmasından sonra açılır (sağlayıcı README'sinin duman testi listesi).
- `prod_environment` (Odoo delivery'nin "Üretim ortamı" bayrağı) **kapalı = sağlayıcının test ortamı**. Çekirdek çağrıyı engellemez; bayrağa göre uç seçmek sağlayıcının işidir. Gönderim anındaki değer gönderiye `test_mode` olarak yazılır (sonradan bayrak değişse de kayıt oynamaz). Test gönderisi formda/listede **TEST** işaretlidir ve transfere takip numarası yazılmaz.

## 5. Gönderi akışı

`draft/failed → sending → created / failed / uncertain`; `uncertain → (Uzlaştır) → created / failed / uncertain`; `created → (İptal) → cancelled`; elle kapatma (Kargo / Yönetici): `uncertain → failed` (K-28), `created → cancelled` (K-29).

- **Gönder:** doğrulama (tüm hatalar tek mesajda; dış çağrı yok) → satır `FOR UPDATE NOWAIT` kilidi → `sending` yazılır ve **commit** → sağlayıcı çağrılır → sonuç yazılır ve commit → etiket/chatter/transfer yazımı. İkinci oturum aynı gönderiyi "zaten işleniyor" diye reddeder.
- **Belirsiz (`uncertain`):** zaman aşımı/bağlantı kopması gibi sonucun bilinmediği durum. Gönderi kargo firmasında oluşmuş olabilir; **yeniden gönderilmez**. **Uzlaştır** kargo firmasında referansla sorgular: bulunursa `created` (etiket yok), bulunamazsa ve gönderimin üzerinden **15 dakika** geçmişse `failed`, daha yeniyse `uncertain` kalır ("X dk sonra deneyin").
- **Kargo firmasında yok olarak işaretle** (yalnız Kargo / Yönetici, yalnız `uncertain`): Uzlaştır sonuç veremiyorsa (sağlayıcı sorgusu hata dönüyor ya da sorgu ucu yok) gönderi elle `failed` yapılır. **Önce kargo firmasının panelinden** gönderinin (referansla) oluşmadığını kontrol edin; oluşmuşsa işaretlemeyin, aksi halde aynı paket için ikinci gönderi açılır ve iki kez faturalanır. Gerekçe zorunludur, kullanıcı adıyla chatter'a yazılır. Ardından aynı referansla yeni gönderi açılabilir.
- **İptal:** yalnız `created`. Kargoya verilmiş (yolda, dağıtımda, teslim, iade) gönderi iptal edilmez. İptal başarılıysa transferdeki takip numarası yalnız bizim yazdığımızsa temizlenir. İptal sonucu **belirsizse** (zaman aşımı, sağlayıcı sunucu hatası) durum `created` kalır, zamanı **Belirsiz iptal zamanı** alanına yazılır ve formda uyarı çıkar: "İptal et" ile yeniden deneyin.
- **Kargo firmasında iptal edildi olarak işaretle** (yalnız Kargo / Yönetici; yalnız iptal isteği belirsiz kalmış `created` gönderide görünür): belirsiz iptal firmada işlendiyse yeniden deneme "zaten iptal" benzeri bir hata alır ve gönderi `created`'da takılır. **Önce kargo firmasının panelinden** gönderinin iptal edildiğini doğrulayın; iptal edilmemişse işaretlemeyin (paket yola çıkar, transferden açılacak yeni gönderi mükerrer olur). Gerekçe zorunludur, kullanıcı adıyla chatter'a yazılır; gönderi `cancelled` olur, transferdeki takip numarası normal iptaldeki gibi (yalnız bizimkiyse) temizlenir. Kargo firmasına istek gitmez.
- **15 dakika kuralı:** iki elle kapatma da son durum geçişinden/istekten en az **15 dakika** sonra yapılabilir: "yok" işareti son gönderimden (Gönderim zamanı), "iptal edildi" işareti son belirsiz iptal isteğinden (Belirsiz iptal zamanı) ölçülür. Daha erken denenirse kalan dakikayı söyleyen hata çıkar; bu sürede önce Uzlaştır / İptal et ile yeniden deneyin. Neden: kargo firmasında yeni kayıt/iptal sorguda birkaç dakika gecikmeli görünebilir, erken "yok" kararı mükerrer gönderi açtırır. Yaş kaydın oluşturulma zamanından değil son istekten ölçülür (yeniden gönderilen eski kayıt da 15 dk bekler).
- Aynı iş referansıyla (`origin_ref`) aynı anda **tek aktif gönderi** olur: veritabanı kısmi benzersiz indeksi (iptal ve hatalı olanlar hariç). İptal/hata sonrası aynı referansla yeni gönderi açılabilir.

## 6. İl/ilçe eşleme

- İlçe kodları `cargo.area` modelindedir (Kargo > Yapılandırma > İl/İlçe Kodları; yönetici düzenler). Veriyi sağlayıcı eklentisi yükler.
- Eşleme **yalnız tam anahtar** eşleşmesidir: ad normalize edilir (Türkçe harfler ASCII'ye, büyük harf, harf/rakam dışı atılır), alt dize ya da bulanık eşleme, posta kodu ve **varsayılan ilçe yoktur**.
- Otomatik eşlenmeyenler: boş metin, il adı, **büyükşehirde "Merkez"** (30 plakalı büyükşehir listesi), birden çok adaya uyan ad. Bu durumda gönderi formunda **Kargo ilçesi** listeden elle seçilir (liste gönderinin iliyle sınırlıdır). Elle seçim chatter'a `İlçe elle seçildi: "<metin>" → <kayıt>` olarak yazılır.
- **Diğer adlar (yönetici):** ilçe kaydında "Diğer adlar" alanına virgülle ayrılmış adlar yazılır (ör. eski ad, farklı yazım). Kod değişmez; ad eşleşmesi genişler. Yönetici eklediği adlar modül güncellemesinde ezilmez.
- Gönderici (şirket adresi) aynı kuralla eşlenir; eşleşmezse gönderi açılmaz: şirket adresi düzeltilir ya da yönetici diğer ad ekler.

## 7. Etiket

- Sağlayıcıdan gelen etiket görüntüleri (PNG) gönderiye bağlanır; **PDF** oluşturmada ve her "Etiketi Bas"ta bu görüntülerden üretilir (sayfa sayısı = paket sayısı). Etiket görüntüsü gelmediyse gönderide **Etiket yok** uyarısı çıkar; etiket sağlayıcının panelinden basılır.
- **Yazdırırken ölçek %100 / "gerçek boyut" olmalıdır** ("sayfaya sığdır" kapalı). Etiket sağlayıcının referans fiziksel boyutunda yerleştirilir; küçültme barkodu kurye cihazında okunamaz yapabilir.
- `10x15`: etiket 10×15 cm sayfada ortalanır (termal yazıcı). `A4`: etiket sol üstte, 1 cm kenar boşluğu, sayfa başına tek etiket.

## 8. Deploy

Üretim compose'u (`docker-compose.prod.yml`) yalnız `ugurlar_images` ve `ugurlar_ai_studio`'yu otomatik kurar/yükseltir; `cargo` ve `cargo_ups` **kendiliğinden kurulmaz**.

1. Veritabanı yedeği alın ve rollback etiketini atın.
2. Önkoşul kontrolü (salt okunur): `SELECT name, state FROM ir_module_module WHERE name IN ('stock_delivery','delivery','sale_stock');` üçü de `installed` olmalı. (Pazaryeri modülleri `delivery`'ye bağlı olduğundan `stock_delivery` Odoo'nun otomatik kurulumuyla gelmiş olmalıdır; değilse `-i` onu da kurar, sakıncası yoktur.)
3. Redeploy yapın (kod gelir; kurulu hiçbir modül yükseltilmez, mesai dışı zorunlu değil).
4. Hemen komut satırından kurun: `docker exec odoougurlar-odoo-prod odoo -d ugurlar -i cargo,cargo_ups --stop-after-init --no-http`. **Arayüzden Uygulamalar > Kur/Yükselt düğmesini kullanmayın:** canlıda `ir_cron` satır kilidine takılıp zaman aşımına düşer. Yeni modül olduğundan arada çalışan ekran yoktur, kesinti oluşmaz. Üretim kopyasında kurulum ~10 sn sürdü. Python bağımlılığı eklenmedi (requests, lxml, reportlab, Pillow imajda var).
5. Kullanıcılara Kargo / Kullanıcı, yöneticiye Kargo / Yönetici grubu atayın.
6. Sağlayıcı firmasını açın ve duman testini yapın (cargo_ups README). Ayarlar > Kargo'dan varsayılan firmayı seçin.
7. Kontrol: Kargo menüsü görünür; Ayarlar > Teknik > Veri tabanı yapısı > Modeller'de `cargo.shipment` ve `cargo.area` var.

**DB kopyası notu:** üretimden alınan kopyada (test/geliştirme) önce firmanın `prod_environment` bayrağını **kapatın**; firma kaydı test ucuyla gelir ama kopya sonrası bayrağı elle açılmış olabilir. Kopya canlı kargo hesabına gönderi açmamalıdır.

## 9. Geri alma (sırası önemli)

1. **Yumuşak (deploy gerekmez):** firmada `prod_environment` kapatılır (çağrılar test ucuna gider, ücretsizdir) ya da firma arşivlenir (KK-5 hatasıyla seçilemez olur). Kullanıcılardan Kargo gruplarını almak da ekranı kapatır.
2. **Tam kaldırma:** önce gönderi listesini CSV olarak dışa aktarın (kaldırma `cargo_shipment` ve `cargo_area` tablolarını siler). Sonra Uygulamalar'dan **önce `cargo_ups`, sonra `cargo`** kaldırılır. `ups_tr` firmaları: **gönderi kaydı bağlıysa** `fixed` + arşivli kalır (transferlerdeki `carrier_id` korunur); **hiç gönderi yoksa** hazır UPS kaydı silinir ve transferlerdeki `carrier_id` boşalır. Her iki durumda `carrier_tracking_ref` metni kalır, zararsızdır. Yeniden kurulumda arşivli firma `ups_tr` tipine döner ama arşivli kalır; açmadan önce `prod_environment` bayrağını kontrol edin.
3. **Kod geri alma (git revert)** ancak modüller **kaldırıldıktan sonra** yapılır; kurulu modülün kodu silinirse kayıt defteri yüklenirken model/görünüm hatası çıkar.
4. Odoo'dan silinen ama kargo firmasında açık kalan gönderiler firmanın panelinden iptal edilir.

## 10. Başka modülden gönderi açmak: `create_and_send`

```python
shipment = env['cargo.shipment'].create_and_send(
    recipient_name='Ali Veli', phone='05321234567', street='Atatürk Mah. Gül Sk. No:5',
    state=env.ref('base.state_tr_06'), district='Çankaya',
    reference='FATURA-123', cod_amount=300.0, cod_method='cash')
# shipment.state / tracking_ref / error_message / label_pdf_id okunur
```

- Yalnız anahtar-kelime parametreleri: `recipient_name, phone, street, state, district` (zorunlu), `package_count, weight, reference, invoice_no, cod_amount, cod_method, carrier, source, email, partner`. `@api.private`: RPC'den çağrılamaz.
- **Aynı referans**: `reference` aynı olan açık kayıt yalnız aynı `source` ile açılmışsa ve taslak değilse döner; başka kaynağın ya da formla açılmış (kaynaksız) kaydın referansı `UserError` verir. `source` verilmeyen çağrı yalnız yine `source`suz `create_and_send` ile açılmış kayda döner.
- **Sağlayıcı hatası istisna değildir**: kayıt `failed` ya da `uncertain` döner. Doğrulama hataları (`UserError`: telefon, ilçe, ODP, paket sayısı, varsayılan firma yok) kayıt bırakmaz ve dış çağrı yapmaz. Yetkisiz çağrı `AccessError`.
- **Idempotency:** `reference` ile aynı iş referanslı, iptal/hatalı olmayan kayıt varsa **yeni gönderi açılmaz, o kayıt döner** (durumu `sending`/`uncertain` olabilir; yeniden gönderilmez, uzlaştırılır). Eşzamanlı iki çağrıda DB indeksi mükerrerliği engeller; ikincisi "birkaç saniye sonra yeniden deneyin" hatası alır.
- **DIKKAT:** çağrı ortasında `cr.commit()` yapar. Çağıranın o ana kadarki açık işlemi de kalıcılaşır; **savepoint içinden çağrılmaz**. Çağıran kendi kaydını çağrıdan önce tutarlı bırakmalıdır.

## 11. Yeni sağlayıcı eklemek

Çekirdeğe dokunmadan: `delivery.carrier.delivery_type`'a `selection_add` + `<tip>_cargo_send(shipment)`, `_cargo_cancel`, `_cargo_find`, isteğe bağlı `_cargo_cod_code(method)`; ayrıca kendi `cargo.area` verisi (`provider='<tip>'`). Dönüş sözlükleri ve durum değerleri `models/delivery_carrier.py` ve `cargo.shipment` docstring'lerindedir. Sağlayıcı istisna fırlatmaz; çekirdek yine de beklenmeyen istisnayı yakalar (send/cancel: `uncertain`, find: `error`). Hata metni sırlardan temizlenerek döndürülmelidir.
