Bu sayfa, Pttavm ile çalışacak merchant ve entegratörler için hazırlanmıştır. Entegrasyon süreci ve test işlemleri için gereken tüm bilgileri bu dokümanda bulabilirsiniz.

Soap servisleri ile ilgili erişime ihtiyacınız olması halinde entegrasyon@pttavm.com mail adresimiz üzerinden iletişime geçebilirsiniz.

Yetkilendirme
Pttavm api servislerini kullanabilmeniz için öncelikle kimlik doğrulaması yapılması gerekmektedir. Bu hizmetin kimliği Api Key ve Token ile doğrulanır. Aşağıdaki adımları izleyerek erişiminizi sağlayabilirsiniz:

API isteklerinde token ve api key ile kimlik doğrulaması yapılır.
Token ve Api Key süreci ile ilgili bilgilere [API key documentation.docx]dokümanından erişebilirsiniz.
Erişim bilgileri yalnızca yetkili kullanıcılar ile paylaşılır ve gizliliğin korunması önemlidir.
Not: API erişim bilgilerinizi kimseyle paylaşmayın ve güvenli ortamlarda saklayın.


Bu metod ile mağazanızın kargo profil bilgilerini almanıza olanak tanır.

Endpoint Bilgileri
URL: `https://integration-api.pttavm.com/api/v1/shipping/cargo-profiles
HTTP Metodu: GET
header : Api-Key zorunlu
header : access-token zorunlu
header : X-Correlation-Idzorunlu
header : Content-Type: application/json
Örnek Servis İsteği
curl https://integration-api.pttavm.com/ /api/v1/shipping/cargo-profiles \
  --header 'Api-Key: ' \
  --header 'Access-Token: '
Örnek Servis Cevabı
{
  "cargoProfiles": [
    {
      "id": 1,
      "name": null,
      "description": null,
      "type": null
    }
  ]
}
Parametre	Tür	Açıklama
Id	integer	Profil ID bilgisi
Name	string	Profil adı
Description	string	Profil açıklaması
Type	string	Gönderi profili türüdür. Öncelik 10 ise "birincil", 1 ise "ikincil", bunlardan farklı ise "" değer dönecektir






Sipariş Detay

Bu metod ile mağazanızın siparişlerinize ait detaylara erişmenize olanak tanır.

Endpoint Bilgileri
URL: `https://integration-api.pttavm.com/api/v1/orders/{orderId}
HTTP Metodu: GET
header : Api-Key zorunlu
header : access-token zorunlu
header : X-Correlation-Idzorunlu
header : Content-Type: application/json
Örnek Servis İsteği
Orderid zorunlu

curl 'https://integration-api.pttavm.com/api/v1/orders/{orderId}' \
  --header 'Api-Key: ' \
  --header 'Access-Token: '
Örnek Servis Cevabı

[
  {
    "vergiDaire": null,
    "vergiNo": null,
    "kargoTutari": 1,
    "musteriId": null,
    "eposta": null,
    "tckn": null,
    "islemTarihi": "2026-01-23T10:40:02.399Z",
    "siparisNo": null,
    "musteriAdi": null,
    "musteriSoyadi": null,
    "siparisAdresi": null,
    "telefonNo": null,
    "ilKod": null,
    "ilceKod": null,
    "siparisIli": null,
    "siparisIlce": null,
    "tedarikciFirmaAdi": null,
    "firmaUnvani": null,
    "urunAdi": null,
    "urunKodu": null,
    "siparisUrunler": [
      {
        "urunId": 1,
        "garantiVerenFirma": null,
        "komisyon": 1,
        "siparisDurumu": null,
        "urunBarkod": null,
        "siparisNotu": null,
        "kdvOrani": 1,
        "kdvHaricTutar": 1,
        "kdvHaricToplamTutar": 1,
        "kdvDahilToplamTutar": 1,
        "toplamIslemAdedi": 1,
        "variantBarkod": null,
        "kargoKimden": null,
        "indirimToplam": 1,
        "indirimPttavm": 1,
        "indirimTedarikci": 1,
        "couponAmount": 1,
        "lineItemId": 1,
        "isInvoice": true,
        "urun": null
      }
    ],
    "faturaMusteriAdi": null,
    "faturaMusteriSoyadi": null,
    "faturaAdresi": null,
    "faturaIli": null,
    "faturaIlce": null,
    "farkliAdres": null,
    "faturaTip": null,
    "seriBarkod": true,
    "kargoBarkod": null,
    "barcodes": [
      {
        "barcode": null,
        "type": null
      }
    ]
  }
]
Parametre	Tür	Açıklama
VergiDaire	string	Vergi dairesi bilgisi
VergiNo	string	Vergi numarası bilgisi
KargoTutari	double	Kargo bedeli bilgisi
MusteriId	string	Müşteri kimlik bilgisi
Eposta	string	Müşteri mail adresi
TCKN	string	TC Kimlik bilgisi
IslemTarihi	DateTime	İşlem tarihi alanıdır. (Örnek Tarih Formatı: 2024-01-01T14:57:12)
SiparisNo	string	Sipariş numarası bilgisi
MusteriAdi	string	Müşteri isim bilgisi
MusteriSoyadi	string	Müşteri soyadı bilgisi
SiparisAdresi	string	Sipariş teslimat adres bilgisi
TelefonNo	string	Müşteri telefon numarası bilgisi ( Telefon numarası maskelenmiş olarak görünecektir
IlKod	string	İl kod bilgisi
IlceKod	string	İlçe kod bilgisi
SiparisIli	string	Sipariş il bilgisi
SiparisIlce	string	Sipariş ilçe bilgisi
TedarikciFirmaAdi	string	Mağaza adı bilgisi
FirmaUnvani	string	Şirket adı
UrunAdi	string	Ürün adı
UrunKodu	string	Ürün stok kod bilgisi
UrunId	int	Ürün id bilgisi
GarantiVerenFirma	string	Garantiyi veren firma bilgisi
Komisyon	double	Komisyon bilgisi
SiparisDurumu	string	Siparişin durum bilgisini içerir. Olası dönüş değerleri
kargo_yapilmasi_bekleniyor, havale_onayi_bekleniyor, iptal, gondericisine_teslim_edildi, iade, gonderilmiş, odeme_gecersiz, onay_surecinde, tamamlandi, null [string]
UrunBarkod	string	Ürün barkod bilgisi
SiparisNotu	string	Siparişe ait ek not bilgisi
KdvOrani	double	KDV oranı bilgisi Formül: VAT (Value Added Tax - KDV)
KdvHaricTutar	double	Ürünün KDV hariç tutar bilgisi Formül: VAT (Value Added Tax - KDV)
KdvHaricToplamTutar	string	Kdv hariç toplam tutar bilgisi Formül: ToplamIslemAdedi X KdvHaricTutar
KdvDahilToplamTutar	double	Kdv dahil toplam tutar bilgisi. Formül: ToplamIslemAdedi X KdvDahilTutar
ToplamIslemAdedi	int	Satılan ürünün adet bilgisi
VariantBarkod	string	Satılan ürünün varyantları varsa, varyant kimliği kombinasyonları virgülle ayrılarak döndürülür. (Örnek: 2737667, 2737668, 2737669)
KargoKimden	string	Gönderiyi kimin gönderdiği bilgisi
IndirimToplam	double	Uygulanan toplam indirim tutarı bilgisi
IndirimPttavm	double	Pttavm indirim bilgisi
IndirimTedarikci	double	Tedarikçi(mağaza) indirim bilgisi
couponAmount	integer	Kupon tutar bilgisi
LineItemId	int	Siparişteki ürün id bilgisi
IsInvoice	boolean	Fatura id bilgisi
FaturaMusteriAdi	string	Faturada yer alan müşteri adı bilgisi
FaturaMusteriSoyadi	string	Faturada yer alan müşteri soyadı bilgisi
FaturaAdresi	string	Fatura adresi
FaturaIli	string	Fatura adresindeki il bilgisi
FaturaIlce	string	Fatura adresindeki ilçe bilgisi
FarkliAdres	string	Sipariş içerisinde farklı bir adres bilgisi varsa bu alan 1 olarak, aksi halde 0 olarak dönecektir. 1 dönmesi durumunda 2,5 ₺ (Türk Lirası) ek fatura ücreti alınacaktır.
FaturaType	string	Fatura tipi bilgisi
Bireysel,Kurumsal
SeriBarkod	boolean	Belirtilen durumlar dışında bir sipariş durumu döndürülürse, bu alan true olacaktır; aksi takdirde, false olacaktır.
KargoBarkod	string	Kargo barkod bilgisi


Kargo Bilgi Listesi

Bu metod ile sorgulanan siparişteki ürünlerin kargo durumu bilgisini almanıza olanak tanır.

Endpoint Bilgileri
URL: `https://integration-api.pttavm.com/api/v1/orders/{orderId}/cargo-infos
HTTP Metodu: GET
header : Api-Key zorunlu
header : access-token zorunlu
header : X-Correlation-Idzorunlu
header : Content-Type: application/json
Örnek Servis İsteği
-orderId zorunlu


curl 'https://integration-api.pttavm.com/ /api/v1/orders/{orderId}/cargo-infos' \
  --header 'Api-Key: ' \
  --header 'Access-Token: '
Örnek Servis Cevabı
[
  {
    "productId": null,
    "shopId": 1,
    "inCargo": null,
    "referenceCode": null,
    "currentState": null,
    "deliveryInfo": null
  }
]
Parametre	Tür	Açıklama
ProductId	string	Sipariş numarası bilgisi
ShopId	int	Mağaza id bilgisi.
InCargo	string	Gönderim durum bilgisini içerir. Olası iade değerleri aşağıda listelenmiştir.
null, 1 = KargoDagitimda, 2 = KargoTedarikcide, 3 = KargoPttSubesinde
ReferenceCode	string	Ürünün barkod bilgisi.
CurrentState	string	Sipariş durumunu gösterir. Olası iade değerleri aşağıda listelenmiştir.
kargo_yapilmasi_bekleniyor, havale_onayi_bekleniyor, gondericisine_teslim_edildi, gonderilmis, iptal, odeme_gecersiz, iade, onay_surecinde, tamamlandi
DeliveryInfo	string	Ürünün PTT şubesinden teslim alınıp alınmadığı bilgisini içerir. Olası iade değerleri aşağıda listelenmiştir.
null, 1 = pttSubesindeBekliyor, 2 = pttSubesindenTeslimAlindi



Sipariş Kontrol V2

Bu metod ile mağazanızdaki belirtilen tarih aralığındaki sipariş bilgilerini almanıza olanak tanır. (Siparişte birden fazla ürün varsa ürün kırılımı ile bilgilerin alınmasına olanak tanır.)

Endpoint Bilgileri
URL: `https://integration-api.pttavm.com/api/v1/shipping/cargo-profiles
HTTP Metodu: GET
header : Api-Key zorunlu
header : access-token zorunlu
header : X-Correlation-Idzorunlu
header : Content-Type: application/json
Dikkat Edilmesi Gereken Kurallar
Başlangıç ve bitiş tarihleri arasındaki süre en fazla 40 gün olabilir.
Bitiş tarihi başlangıç tarihinden önce olamaz; aksi takdirde hata dönecektir.
‘isActiveOrders’=true olarak gönderilirse, ‘kargo_yapilmasi_bekleniyor’ durumuna sahip siparişler gösterilir, yani ödeme yapılmıştır ancak sipariş tedarikçi tarafından hazırlanmamıştır. Tüm siparişleri almak için 'isActiveOrders'=false olarak gönderilmesi gerekmektedir.
Parametre	Tür	Açıklama
startDate	string / date-time	Sipariş bilgisini almak istediğiniz başlangıç tarihi ** zorunlu**
endDate	DateTime / date-time	Sipariş bilgisini almak istediğiniz bitiş tarihi **zorunlu**
isActiveOrders	boolean	False olarak gönderilmesi gerekmektedir. ** zorunlu**
Örnek Servis İsteği

curl 'http://integrator-core-api-test.rancher.pttavm.com/api/v1/orders/search?startDate=&endDate=&isActiveOrders=' \
  --header 'Api-Key: ' \
  --header 'Access-Token: '
Örnek Servis Cevabı

[
  {
    "vergiDaire": null,
    "vergiNo": null,
    "kargoTutari": 1,
    "musteriId": null,
    "eposta": null,
    "tckn": null,
    "islemTarihi": "2026-01-23T10:40:02.399Z",
    "siparisNo": null,
    "musteriAdi": null,
    "musteriSoyadi": null,
    "siparisAdresi": null,
    "telefonNo": null,
    "ilKod": null,
    "ilceKod": null,
    "siparisIli": null,
    "siparisIlce": null,
    "tedarikciFirmaAdi": null,
    "firmaUnvani": null,
    "urunAdi": null,
    "urunKodu": null,
    "siparisUrunler": [
      {
        "urunId": 1,
        "garantiVerenFirma": null,
        "komisyon": 1,
        "siparisDurumu": null,
        "urunBarkod": null,
        "siparisNotu": null,
        "kdvOrani": 1,
        "kdvHaricTutar": 1,
        "kdvHaricToplamTutar": 1,
        "kdvDahilToplamTutar": 1,
        "toplamIslemAdedi": 1,
        "variantBarkod": null,
        "kargoKimden": null,
        "indirimToplam": 1,
        "indirimPttavm": 1,
        "indirimTedarikci": 1,
        "couponAmount": 1,
        "lineItemId": 1,
        "isInvoice": true,
        "urun": null
      }
    ],
    "faturaMusteriAdi": null,
    "faturaMusteriSoyadi": null,
    "faturaAdresi": null,
    "faturaIli": null,
    "faturaIlce": null,
    "farkliAdres": null,
    "faturaTip": null,
    "seriBarkod": true,
    "kargoBarkod": null,
    "barcodes": [
      {
        "barcode": null,
        "type": null
      }
    ]
  }
]
Parametre	Tür	Açıklama
VergiDaire	string	Vergi dairesi bilgisi
VergiNo	string	Vergi numarası bilgisi
KargoTutari	double	Kargo bedeli bilgisi
MusteriId	string	Müşteri kimlik bilgisi
Eposta	string	Müşteri mail adresi
TCKN	string	TC Kimlik bilgisi
IslemTarihi	DateTime	İşlem tarihi alanıdır. (Örnek Tarih Formatı: 2024-01-01T14:57:12)
SiparisNo	string	Sipariş numarası bilgisi
MusteriAdi	string	Müşteri isim bilgisi
MusteriSoyadi	string	Müşteri soyadı bilgisi
SiparisAdresi	string	Sipariş teslimat adres bilgisi
TelefonNo	string	Müşteri telefon numarası bilgisi ( Telefon numarası maskelenmiş olarak görünecektir
IlKod	string	İl kod bilgisi
IlceKod	string	İlçe kod bilgisi
SiparisIli	string	Sipariş il bilgisi
SiparisIlce	string	Sipariş ilçe bilgisi
TedarikciFirmaAdi	string	Mağaza adı bilgisi
TedarikciFirmaAdi	string	Mağaza adı bilgisi
FirmaUnvani	string	Şirket adı
UrunAdi	string	Ürün adı
UrunKodu	string	Ürün stok kod bilgisi
UrunId	int	Ürün id bilgisi
GarantiVerenFirma	string	Garantiyi veren firma bilgisi
Komisyon	double	Komisyon bilgisi
SiparisDurumu	string	Siparişin durum bilgisini içerir. Olası dönüş değerleri
kargo_yapilmasi_bekleniyor, havale_onayi_bekleniyor, iptal, gondericisine_teslim_edildi, iade, gonderilmiş, odeme_gecersiz, onay_surecinde, tamamlandi, null [string]
UrunBarkod	string	Ürün barkod bilgisi
siparisNotu	string	Sipariş ile ilgili genel bilgiler
KdvOrani	double	KDV oranı bilgisi Formül: VAT (Value Added Tax - KDV)
KdvHaricTutar	double	Ürünün KDV hariç tutar bilgisi Formül: VAT (Value Added Tax - KDV)
KdvHaricToplamTutar	string	Kdv hariç toplam tutar bilgisi Formül: ToplamIslemAdedi X KdvHaricTutar
KdvDahilToplamTutar	double	Kdv dahil toplam tutar bilgisi. Formül: ToplamIslemAdedi X KdvDahilTutar
ToplamIslemAdedi	int	Satılan ürünün adet bilgisi
VariantBarkod	string	Satılan ürünün varyantları varsa, varyant kimliği kombinasyonları virgülle ayrılarak döndürülür. (Örnek: 2737667, 2737668, 2737669)
KargoKimden	string	Gönderiyi kimin gönderdiği bilgisi
IndirimToplam	double	Uygulanan toplam indirim tutarı bilgisi
IndirimPttavm	double	Pttavm indirim bilgisi
IndirimTedarikci	double	Tedarikçi(mağaza) indirim bilgisi
LineItemId	int	Siparişteki ürün id bilgisi
Urun	string	Ürün bilgisi
FaturaMusteriAdi	string	Faturada yer alan müşteri adı bilgisi
FaturaMusteriSoyadi	string	Faturada yer alan müşteri soyadı bilgisi
FaturaAdresi	string	Fatura adresi
FaturaIli	string	Fatura adresindeki il bilgisi
FaturaIlce	string	Fatura adresindeki ilçe bilgisi
FarkliAdres	string	Sipariş içerisinde farklı bir adres bilgisi varsa bu alan 1 olarak, aksi halde 0 olarak dönecektir. 1 dönmesi durumunda 2,5 ₺ (Türk Lirası) ek fatura ücreti alınacaktır.
faturaTip	string	Fatura tipi
SeriBarkod	boolean	Belirtilen durumlar dışında bir sipariş durumu döndürülürse, bu alan true olacaktır; aksi takdirde, false olacaktır.
KargoBarkod	string	Kargo barkod bilgisi
Barcodes	string	Sipariş barkod bilgisi



Fatura Gönder

Bu metod ile mağazanızın siparişlerinize ait faturaları yüklemenize olanak tanır.

Endpoint Bilgileri
URL: `https://integration-api.pttavm.com/api/v1/products/get-by-barcodes
HTTP Metodu: POST
header : Api-Key zorunlu
header : access-token zorunlu
header : X-Correlation-Idzorunlu
header : Content-Type: application/json
Dikkat Edilmesi Gereken Kurallar
SiparisKontrolListesi ve SiparisKontrolListesiV2 metotlarının döndürdüğü sipariş detaylarında bulunan lineItemId (Mağazanın Siparişteki Ürün Kaydı) gönderilmelidir.
Eğer siparişte birden fazla line varsa bu lineItemId'leri bir dizi formatında gönderilmelidir. Örneğin PTT-örnek-010123 numaralı siparişin 1266416 (Kedi Kumu) ve 1266417 (Kedi Maması) ürünlerini içerdiğini varsayalım. Burada 1266416 ve 1266417 ID'leri "lineItemId" anahtarı altında gönderilmelidir.
Faturanın yüklendiği bir URL varsa, bu URL esas alınacaktır; aksi takdirde aşağıdaki madde geçerlidir.
Yüklenecek faturanın .pdf formatında olması gerekmektedir. İlgili PDF'in Base64 formatına çevrilerek 'içerik' alanına eksiksiz olarak gönderilmesi gerekmektedir.
Örnek Servis İsteği
Orderid zorunlu

curl '`https://integration-api.pttavm.com/api/v1/orders/{orderId}/invoice' \
  --request POST \
  --header 'Api-Key: ' \
  --header 'Access-Token: ' \
  --header 'Content-Type: application/json' \
  --data '{
  "lineItemId": [
    1
  ],
  "content": null,
  "url": null
}'
Örnek Servis Cevabı

{
  "success": true,
  "error_Message": null
}
Parametre	Tür	Açıklama
lineItemId	array	Mağazadan gelen siparişteki ürün ID'lerini içerir.
content	string	Faturanın Base64 verilerini .pdf formatında içerir. (İsteğe bağlı)
url	string	Faturanın .pdf formatında url bilgisi
Success	boolean	İşlem durum bilgisi
Error_Message	string	Hata mesajı



Depo Listeleme

Bu metod ile mağazanıza ait depo bilgilerini almanıza olanak tanır.

Endpoint Bilgileri
URL: https://shipment.pttavm.com/api/v1/get-warehouse
HTTP Metodu: POST
Content-Type: application/json
Authorization: Basic Auth
Örnek Servis İsteği
https://shipment.pttavm.com/api/v1/get-warehouse
Örnek Servis Cevabı
{
    "data": [
        {
            "id": 12345,
            "name": "pttavm"
        },
        {
            "id": 56789,
            "name": "pttavm1"
        },
        {
            "id": 98765,
            "name": " pttavm2"
        }
            ],
    "error": false,
    "msg": null,
    "status": true
}
Alan Adı	Açıklama
id	Depo id bilgisi
name	Depo adı


Barkod Oluştur

Bu metod ile siparişlerinize barkod oluşturmanıza olanak tanır.

Endpoint Bilgileri
URL: https://shipment.pttavm.com/api/v1/create-barcode
HTTP Metodu: POST
Content-Type: application/json
Authorization: Basic Auth
Örnek Servis İsteği
https://shipment.pttavm.com/api/v1/get-warehouse
Örnek Servis Body Bilgisi

{
    "orders": [
        {
            "order_id": "PTT-0BO6M672N-180925", // Sipariş numarası zorunlu
            "warehouse_id": 100301619  // Depo id zorunlu   
        }
    ]
}
Dikkat Edilmesi Gereken Kurallar
Sipariş numaraları aynı olup, depo numaraları farklı olamaz.
Birden fazla siparişe barkod oluşturmak için body içeriğinde order_id ve warehouse_id çoğaltabilirsiniz.
Request sonunda sistem tarafından sizlere bir tracking_id oluşturulur. Bu tracking_id bilgisini barkod sorgulama işleminde kullanmalısınız.
Bulk Servis Body Bilgisi

{
    "orders": [
        {
            "order_id": "PTT-123123-180925", //must
            "warehouse_id": 12345 //must olan 
        },
           {
            "order_id": "PTT-123123-180925", //must
            "warehouse_id": 12345 //must olan 
        }
    ]
}
Örnek Servis Cevabı
{
    "tracking_id": "cb3fa78459a6edae7dca9be0389a9861",
    "count": 2,
    "code": 200,
    "success": true,
    "message": "",
    "error": false
}
Alan Açıklamaları
Parametre	Tür	Açıklama
barcodes	string	Siparişe ait barkod bilgisi
order_id	string	Sipariş numarası.
warehouse_id	int	Depo bilgisi
tracking_id	string	İşlem sonunda sistem tarafından üretilen tracking_id
message	string	Request sonunda iletilen mesaj
Hata Kodları
Alan Adı	Açıklama
200	Success
422	Bad Request



Barkod Oluşturma Kontrolu

Bu metod ile siparişinize ait, oluşturmuş olduğunuz barkod kontrolünü sağlamanıza olanak tanır.

Endpoint Bilgileri
URL: https://shipment.pttavm.com/api/v1/barcode-status
HTTP Metodu: POST
Content-Type: application/json
Authorization: Basic Auth
Dikkat Edilmesi Gereken Kurallar
Barkod oluşturma işlemi sonrasında sistem tarafından sizlere iletilen tracking_id bilgisi ile sorgulama yapılmalıdır.
Örnek Servis İsteği
https://shipment.pttavm.com/api/v1/barcode-status
Örnek Servis Body Bilgisi

{
  "tracking_id": "cb3fa78459a6edae7dca9be0389a9861"
}
Örnek Servis Cevabı
{
    "tracking_id": "cb3fa78459a6edae7dca9be0389a9861",
    "status": "completed",
    "data": [
        {
            "order_id": "PTT-12345-180925",
            "barcodes": [
                "67890"
            ]
        },
        {
            "order_id": "PTT-12345-180925",
            "barcodes": [
                "67890"
            ]
        }
    ],
    "error": ""
}
Status Açıklamaları
Status	Açıklama
completed	Başarılı tamamlandı
error	İşlem sırasında hata alındı
pending	İşlem beklemede
Alan Açıklamaları
Parametre	Tür	Açıklama
barcodes	string	Siparişe ait barkod bilgisi
order_id	string	Sipariş numarası.
error	string	Hata bilgisi
status	string	İşlem durum bilgisi
tracking_id	string	İşlem sonunda sistem tarafından üretilen tracking_id
Hata Kodları
Alan Adı	Açıklama
200	Success
422	Bad Request



Barkod Etiket Bilgisi

Bu metod ile oluşturulan barkodun etiket biçiminde alınmasına olanak tanır.

Endpoint Bilgileri
URL: https://shipment.pttavm.com/api/v1/get-barcode-tag
HTTP Metodu: POST
Content-Type: application/json
Authorization: Basic Auth
Örnek Servis İsteği
https://shipment.pttavm.com/api/v1/get-warehouse
Örnek Servis Body Bilgisi

{
  "barcode": "1234567890",
  "order_id": "PTT-12345-180925",
  "type":"null"
  }
Dikkat Edilmesi Gereken Kurallar
type":"zpl" gönderilirse zebra yazıcılar için formattır(zpl). null gönderilirse html çıktısıdır.
Örnek Servis Cevabı
<!DOCTYPE html>
<html>

<head>
    <title>Print Barcode</title>
    <link rel="stylesheet" href="https://img.pttavm.com/barcode_content/etiket.css">
    <link rel="stylesheet" media="print" href="https://img.pttavm.com/barcode_content/etiket.css">
    <script type="text/javascript" src="https://img.pttavm.com/barcode_content/css_browser_selector.js"></script>
    <meta charset="utf-8" />
</head>

<body onload="">

    <div id="anaCerceve">
        <div class="kabulIsyeri">TARİH</div>
        <div class="kabulIsyeri_icerik">19/09/2025 14:18</div>

        <div class="ortaBaslik">
            <img src="https://img.pttavm.com/barcode_content/topbar-logo_ust.png"
                style="position:relative;top:10px;left:-20px;"
                alt="">
        PTT GENEL MÜDÜRLÜĞÜ
            <img src="https://img.pttavm.com/barcode_content/topbar-logo_ust.png"
                style="position:relative;top:10px;left:20px;"
                alt="">
        </div>

        <div class="logo">
            <img src="https://img.pttavm.com/barcode_content/pttkargo_logo.png" alt="Ptt Kargo"/>
        </div>

        <div class="barkodSol">
            <?xml version="1.0"?>
            <!-- Generated by SVGo -->
            <svg style=" position: absolute; -webkit-transform: rotate(-90deg);margin-top: 135px; margin-left: -125px"
                width="300" height="45" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
                <rect x="0" y="0" width="300" height="55" style="fill:white" />
                <rect x="7" y="0" width="1" height="35" style="fill:black" />
                <rect x="8" y="0" width="1" height="35" style="fill:black" />
                <rect x="9" y="0" width="1" height="35" style="fill:black" />
                <rect x="13" y="0" width="1" height="35" style="fill:black" />
                <rect x="14" y="0" width="1" height="35" style="fill:black" />
                <rect x="15" y="0" width="1" height="35" style="fill:black" />
                <rect x="19" y="0" width="1" height="35" style="fill:black" />
                <rect x="20" y="0" width="1" height="35" style="fill:black" />
                <rect x="21" y="0" width="1" height="35" style="fill:black" />
                <rect x="22" y="0" width="1" height="35" style="fill:black" />
                <rect x="23" y="0" width="1" height="35" style="fill:black" />
                <rect x="24" y="0" width="1" height="35" style="fill:black" />
                <rect x="25" y="0" width="1" height="35" style="fill:black" />
                <rect x="26" y="0" width="1" height="35" style="fill:black" />
                <rect x="27" y="0" width="1" height="35" style="fill:black" />
                <rect x="31" y="0" width="1" height="35" style="fill:black" />
                <rect x="32" y="0" width="1" height="35" style="fill:black" />
                <rect x="33" y="0" width="1" height="35" style="fill:black" />
                <rect x="34" y="0" width="1" height="35" style="fill:black" />
                <rect x="35" y="0" width="1" height="35" style="fill:black" />
                <rect x="36" y="0" width="1" height="35" style="fill:black" />
                <rect x="43" y="0" width="1" height="35" style="fill:black" />
                <rect x="44" y="0" width="1" height="35" style="fill:black" />
                <rect x="45" y="0" width="1" height="35" style="fill:black" />
                <rect x="46" y="0" width="1" height="35" style="fill:black" />
                <rect x="47" y="0" width="1" height="35" style="fill:black" />
                <rect x="48" y="0" width="1" height="35" style="fill:black" />
                <rect x="55" y="0" width="1" height="35" style="fill:black" />
                <rect x="56" y="0" width="1" height="35" style="fill:black" />
                <rect x="57" y="0" width="1" height="35" style="fill:black" />
                <rect x="61" y="0" width="1" height="35" style="fill:black" />
                <rect x="62" y="0" width="1" height="35" style="fill:black" />
                <rect x="63" y="0" width="1" height="35" style="fill:black" />
                <rect x="70" y="0" width="1" height="35" style="fill:black" />
                <rect x="71" y="0" width="1" height="35" style="fill:black" />
                <rect x="72" y="0" width="1" height="35" style="fill:black" />
                <rect x="73" y="0" width="1" height="35" style="fill:black" />
                <rect x="74" y="0" width="1" height="35" style="fill:black" />
                <rect x="75" y="0" width="1" height="35" style="fill:black" />
                <rect x="76" y="0" width="1" height="35" style="fill:black" />
                <rect x="77" y="0" width="1" height="35" style="fill:black" />
                <rect x="78" y="0" width="1" height="35" style="fill:black" />
                <rect x="85" y="0" width="1" height="35" style="fill:black" />
                <rect x="86" y="0" width="1" height="35" style="fill:black" />
                <rect x="87" y="0" width="1" height="35" style="fill:black" />
                <rect x="88" y="0" width="1" height="35" style="fill:black" />
                <rect x="89" y="0" width="1" height="35" style="fill:black" />
                <rect x="90" y="0" width="1" height="35" style="fill:black" />
                <rect x="94" y="0" width="1" height="35" style="fill:black" />
                <rect x="95" y="0" width="1" height="35" style="fill:black" />
                <rect x="96" y="0" width="1" height="35" style="fill:black" />
                <rect x="97" y="0" width="1" height="35" style="fill:black" />
                <rect x="98" y="0" width="1" height="35" style="fill:black" />
                <rect x="99" y="0" width="1" height="35" style="fill:black" />
                <rect x="103" y="0" width="1" height="35" style="fill:black" />
                <rect x="104" y="0" width="1" height="35" style="fill:black" />
                <rect x="105" y="0" width="1" height="35" style="fill:black" />
                <rect x="106" y="0" width="1" height="35" style="fill:black" />
                <rect x="107" y="0" width="1" height="35" style="fill:black" />
                <rect x="108" y="0" width="1" height="35" style="fill:black" />
                <rect x="112" y="0" width="1" height="35" style="fill:black" />
                <rect x="113" y="0" width="1" height="35" style="fill:black" />
                <rect x="114" y="0" width="1" height="35" style="fill:black" />
                <rect x="115" y="0" width="1" height="35" style="fill:black" />
                <rect x="116" y="0" width="1" height="35" style="fill:black" />
                <rect x="117" y="0" width="1" height="35" style="fill:black" />
                <rect x="118" y="0" width="1" height="35" style="fill:black" />
                <rect x="119" y="0" width="1" height="35" style="fill:black" />
                <rect x="120" y="0" width="1" height="35" style="fill:black" />
                <rect x="127" y="0" width="1" height="35" style="fill:black" />
                <rect x="128" y="0" width="1" height="35" style="fill:black" />
                <rect x="129" y="0" width="1" height="35" style="fill:black" />
                <rect x="130" y="0" width="1" height="35" style="fill:black" />
                <rect x="131" y="0" width="1" height="35" style="fill:black" />
                <rect x="132" y="0" width="1" height="35" style="fill:black" />
                <rect x="136" y="0" width="1" height="35" style="fill:black" />
                <rect x="137" y="0" width="1" height="35" style="fill:black" />
                <rect x="138" y="0" width="1" height="35" style="fill:black" />
                <rect x="139" y="0" width="1" height="35" style="fill:black" />
                <rect x="140" y="0" width="1" height="35" style="fill:black" />
                <rect x="141" y="0" width="1" height="35" style="fill:black" />
                <rect x="145" y="0" width="1" height="35" style="fill:black" />
                <rect x="146" y="0" width="1" height="35" style="fill:black" />
                <rect x="147" y="0" width="1" height="35" style="fill:black" />
                <rect x="151" y="0" width="1" height="35" style="fill:black" />
                <rect x="152" y="0" width="1" height="35" style="fill:black" />
                <rect x="153" y="0" width="1" height="35" style="fill:black" />
                <rect x="157" y="0" width="1" height="35" style="fill:black" />
                <rect x="158" y="0" width="1" height="35" style="fill:black" />
                <rect x="159" y="0" width="1" height="35" style="fill:black" />
                <rect x="160" y="0" width="1" height="35" style="fill:black" />
                <rect x="161" y="0" width="1" height="35" style="fill:black" />
                <rect x="162" y="0" width="1" height="35" style="fill:black" />
                <rect x="163" y="0" width="1" height="35" style="fill:black" />
                <rect x="164" y="0" width="1" height="35" style="fill:black" />
                <rect x="165" y="0" width="1" height="35" style="fill:black" />
                <rect x="169" y="0" width="1" height="35" style="fill:black" />
                <rect x="170" y="0" width="1" height="35" style="fill:black" />
                <rect x="171" y="0" width="1" height="35" style="fill:black" />
                <rect x="178" y="0" width="1" height="35" style="fill:black" />
                <rect x="179" y="0" width="1" height="35" style="fill:black" />
                <rect x="180" y="0" width="1" height="35" style="fill:black" />
                <rect x="193" y="0" width="1" height="35" style="fill:black" />
                <rect x="194" y="0" width="1" height="35" style="fill:black" />
                <rect x="195" y="0" width="1" height="35" style="fill:black" />
                <rect x="199" y="0" width="1" height="35" style="fill:black" />
                <rect x="200" y="0" width="1" height="35" style="fill:black" />
                <rect x="201" y="0" width="1" height="35" style="fill:black" />
                <rect x="205" y="0" width="1" height="35" style="fill:black" />
                <rect x="206" y="0" width="1" height="35" style="fill:black" />
                <rect x="207" y="0" width="1" height="35" style="fill:black" />
                <rect x="220" y="0" width="1" height="35" style="fill:black" />
                <rect x="221" y="0" width="1" height="35" style="fill:black" />
                <rect x="222" y="0" width="1" height="35" style="fill:black" />
                <rect x="226" y="0" width="1" height="35" style="fill:black" />
                <rect x="227" y="0" width="1" height="35" style="fill:black" />
                <rect x="228" y="0" width="1" height="35" style="fill:black" />
                <rect x="229" y="0" width="1" height="35" style="fill:black" />
                <rect x="230" y="0" width="1" height="35" style="fill:black" />
                <rect x="231" y="0" width="1" height="35" style="fill:black" />
                <rect x="232" y="0" width="1" height="35" style="fill:black" />
                <rect x="233" y="0" width="1" height="35" style="fill:black" />
                <rect x="234" y="0" width="1" height="35" style="fill:black" />
                <rect x="241" y="0" width="1" height="35" style="fill:black" />
                <rect x="242" y="0" width="1" height="35" style="fill:black" />
                <rect x="243" y="0" width="1" height="35" style="fill:black" />
                <rect x="247" y="0" width="1" height="35" style="fill:black" />
                <rect x="248" y="0" width="1" height="35" style="fill:black" />
                <rect x="249" y="0" width="1" height="35" style="fill:black" />
                <rect x="262" y="0" width="1" height="35" style="fill:black" />
                <rect x="263" y="0" width="1" height="35" style="fill:black" />
                <rect x="264" y="0" width="1" height="35" style="fill:black" />
                <rect x="271" y="0" width="1" height="35" style="fill:black" />
                <rect x="272" y="0" width="1" height="35" style="fill:black" />
                <rect x="273" y="0" width="1" height="35" style="fill:black" />
                <rect x="283" y="0" width="1" height="35" style="fill:black" />
                <rect x="284" y="0" width="1" height="35" style="fill:black" />
                <rect x="285" y="0" width="1" height="35" style="fill:black" />
                <rect x="289" y="0" width="1" height="35" style="fill:black" />
                <rect x="290" y="0" width="1" height="35" style="fill:black" />
                <rect x="291" y="0" width="1" height="35" style="fill:black" />
                <text x="11" y="43" style="text-anchor:middle;font-size:10px;">2</text>
                <text x="34" y="43" style="text-anchor:middle;font-size:10px;">7</text>
                <text x="57" y="43" style="text-anchor:middle;font-size:10px;">1</text>
                <text x="80" y="43" style="text-anchor:middle;font-size:10px;">0</text>
                <text x="103" y="43" style="text-anchor:middle;font-size:10px;">2</text>
                <text x="126" y="43" style="text-anchor:middle;font-size:10px;">8</text>
                <text x="149" y="43" style="text-anchor:middle;font-size:10px;">2</text>
                <text x="172" y="43" style="text-anchor:middle;font-size:10px;">9</text>
                <text x="195" y="43" style="text-anchor:middle;font-size:10px;">3</text>
                <text x="218" y="43" style="text-anchor:middle;font-size:10px;">6</text>
                <text x="241" y="43" style="text-anchor:middle;font-size:10px;">4</text>
                <text x="264" y="43" style="text-anchor:middle;font-size:10px;">6</text>
                <text x="287" y="43" style="text-anchor:middle;font-size:10px;">8</text>
            </svg>

        </div>

        <div class="barkodSag">
            <?xml version="1.0"?>
            <!-- Generated by SVGo -->
            <svg style="position: absolute; -webkit-transform: rotate(90deg); margin-top: 95px; margin-left: -85px "
                width="290" height="121" xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
                <rect x="0" y="0" width="290" height="131" style="fill:white" />
                <rect x="2" y="0" width="1" height="111" style="fill:black" />
                <rect x="3" y="0" width="1" height="111" style="fill:black" />
                <rect x="4" y="0" width="1" height="111" style="fill:black" />
                <rect x="8" y="0" width="1" height="111" style="fill:black" />
                <rect x="9" y="0" width="1" height="111" style="fill:black" />
                <rect x="10" y="0" width="1" height="111" style="fill:black" />
                <rect x="14" y="0" width="1" height="111" style="fill:black" />
                <rect x="15" y="0" width="1" height="111" style="fill:black" />
                <rect x="16" y="0" width="1" height="111" style="fill:black" />
                <rect x="17" y="0" width="1" height="111" style="fill:black" />
                <rect x="18" y="0" width="1" height="111" style="fill:black" />
                <rect x="19" y="0" width="1" height="111" style="fill:black" />
                <rect x="20" y="0" width="1" height="111" style="fill:black" />
                <rect x="21" y="0" width="1" height="111" style="fill:black" />
                <rect x="22" y="0" width="1" height="111" style="fill:black" />
                <rect x="26" y="0" width="1" height="111" style="fill:black" />
                <rect x="27" y="0" width="1" height="111" style="fill:black" />
                <rect x="28" y="0" width="1" height="111" style="fill:black" />
                <rect x="29" y="0" width="1" height="111" style="fill:black" />
                <rect x="30" y="0" width="1" height="111" style="fill:black" />
                <rect x="31" y="0" width="1" height="111" style="fill:black" />
                <rect x="38" y="0" width="1" height="111" style="fill:black" />
                <rect x="39" y="0" width="1" height="111" style="fill:black" />
                <rect x="40" y="0" width="1" height="111" style="fill:black" />
                <rect x="41" y="0" width="1" height="111" style="fill:black" />
                <rect x="42" y="0" width="1" height="111" style="fill:black" />
                <rect x="43" y="0" width="1" height="111" style="fill:black" />
                <rect x="50" y="0" width="1" height="111" style="fill:black" />
                <rect x="51" y="0" width="1" height="111" style="fill:black" />
                <rect x="52" y="0" width="1" height="111" style="fill:black" />
                <rect x="56" y="0" width="1" height="111" style="fill:black" />
                <rect x="57" y="0" width="1" height="111" style="fill:black" />
                <rect x="58" y="0" width="1" height="111" style="fill:black" />
                <rect x="65" y="0" width="1" height="111" style="fill:black" />
                <rect x="66" y="0" width="1" height="111" style="fill:black" />
                <rect x="67" y="0" width="1" height="111" style="fill:black" />
                <rect x="68" y="0" width="1" height="111" style="fill:black" />
                <rect x="69" y="0" width="1" height="111" style="fill:black" />
                <rect x="70" y="0" width="1" height="111" style="fill:black" />
                <rect x="71" y="0" width="1" height="111" style="fill:black" />
                <rect x="72" y="0" width="1" height="111" style="fill:black" />
                <rect x="73" y="0" width="1" height="111" style="fill:black" />
                <rect x="80" y="0" width="1" height="111" style="fill:black" />
                <rect x="81" y="0" width="1" height="111" style="fill:black" />
                <rect x="82" y="0" width="1" height="111" style="fill:black" />
                <rect x="83" y="0" width="1" height="111" style="fill:black" />
                <rect x="84" y="0" width="1" height="111" style="fill:black" />
                <rect x="85" y="0" width="1" height="111" style="fill:black" />
                <rect x="89" y="0" width="1" height="111" style="fill:black" />
                <rect x="90" y="0" width="1" height="111" style="fill:black" />
                <rect x="91" y="0" width="1" height="111" style="fill:black" />
                <rect x="92" y="0" width="1" height="111" style="fill:black" />
                <rect x="93" y="0" width="1" height="111" style="fill:black" />
                <rect x="94" y="0" width="1" height="111" style="fill:black" />
                <rect x="98" y="0" width="1" height="111" style="fill:black" />
                <rect x="99" y="0" width="1" height="111" style="fill:black" />
                <rect x="100" y="0" width="1" height="111" style="fill:black" />
                <rect x="101" y="0" width="1" height="111" style="fill:black" />
                <rect x="102" y="0" width="1" height="111" style="fill:black" />
                <rect x="103" y="0" width="1" height="111" style="fill:black" />
                <rect x="107" y="0" width="1" height="111" style="fill:black" />
                <rect x="108" y="0" width="1" height="111" style="fill:black" />
                <rect x="109" y="0" width="1" height="111" style="fill:black" />
                <rect x="110" y="0" width="1" height="111" style="fill:black" />
                <rect x="111" y="0" width="1" height="111" style="fill:black" />
                <rect x="112" y="0" width="1" height="111" style="fill:black" />
                <rect x="113" y="0" width="1" height="111" style="fill:black" />
                <rect x="114" y="0" width="1" height="111" style="fill:black" />
                <rect x="115" y="0" width="1" height="111" style="fill:black" />
                <rect x="122" y="0" width="1" height="111" style="fill:black" />
                <rect x="123" y="0" width="1" height="111" style="fill:black" />
                <rect x="124" y="0" width="1" height="111" style="fill:black" />
                <rect x="125" y="0" width="1" height="111" style="fill:black" />
                <rect x="126" y="0" width="1" height="111" style="fill:black" />
                <rect x="127" y="0" width="1" height="111" style="fill:black" />
                <rect x="131" y="0" width="1" height="111" style="fill:black" />
                <rect x="132" y="0" width="1" height="111" style="fill:black" />
                <rect x="133" y="0" width="1" height="111" style="fill:black" />
                <rect x="134" y="0" width="1" height="111" style="fill:black" />
                <rect x="135" y="0" width="1" height="111" style="fill:black" />
                <rect x="136" y="0" width="1" height="111" style="fill:black" />
                <rect x="140" y="0" width="1" height="111" style="fill:black" />
                <rect x="141" y="0" width="1" height="111" style="fill:black" />
                <rect x="142" y="0" width="1" height="111" style="fill:black" />
                <rect x="146" y="0" width="1" height="111" style="fill:black" />
                <rect x="147" y="0" width="1" height="111" style="fill:black" />
                <rect x="148" y="0" width="1" height="111" style="fill:black" />
                <rect x="152" y="0" width="1" height="111" style="fill:black" />
                <rect x="153" y="0" width="1" height="111" style="fill:black" />
                <rect x="154" y="0" width="1" height="111" style="fill:black" />
                <rect x="155" y="0" width="1" height="111" style="fill:black" />
                <rect x="156" y="0" width="1" height="111" style="fill:black" />
                <rect x="157" y="0" width="1" height="111" style="fill:black" />
                <rect x="158" y="0" width="1" height="111" style="fill:black" />
                <rect x="159" y="0" width="1" height="111" style="fill:black" />
                <rect x="160" y="0" width="1" height="111" style="fill:black" />
                <rect x="164" y="0" width="1" height="111" style="fill:black" />
                <rect x="165" y="0" width="1" height="111" style="fill:black" />
                <rect x="166" y="0" width="1" height="111" style="fill:black" />
                <rect x="173" y="0" width="1" height="111" style="fill:black" />
                <rect x="174" y="0" width="1" height="111" style="fill:black" />
                <rect x="175" y="0" width="1" height="111" style="fill:black" />
                <rect x="188" y="0" width="1" height="111" style="fill:black" />
                <rect x="189" y="0" width="1" height="111" style="fill:black" />
                <rect x="190" y="0" width="1" height="111" style="fill:black" />
                <rect x="194" y="0" width="1" height="111" style="fill:black" />
                <rect x="195" y="0" width="1" height="111" style="fill:black" />
                <rect x="196" y="0" width="1" height="111" style="fill:black" />
                <rect x="200" y="0" width="1" height="111" style="fill:black" />
                <rect x="201" y="0" width="1" height="111" style="fill:black" />
                <rect x="202" y="0" width="1" height="111" style="fill:black" />
                <rect x="215" y="0" width="1" height="111" style="fill:black" />
                <rect x="216" y="0" width="1" height="111" style="fill:black" />
                <rect x="217" y="0" width="1" height="111" style="fill:black" />
                <rect x="221" y="0" width="1" height="111" style="fill:black" />
                <rect x="222" y="0" width="1" height="111" style="fill:black" />
                <rect x="223" y="0" width="1" height="111" style="fill:black" />
                <rect x="224" y="0" width="1" height="111" style="fill:black" />
                <rect x="225" y="0" width="1" height="111" style="fill:black" />
                <rect x="226" y="0" width="1" height="111" style="fill:black" />
                <rect x="227" y="0" width="1" height="111" style="fill:black" />
                <rect x="228" y="0" width="1" height="111" style="fill:black" />
                <rect x="229" y="0" width="1" height="111" style="fill:black" />
                <rect x="236" y="0" width="1" height="111" style="fill:black" />
                <rect x="237" y="0" width="1" height="111" style="fill:black" />
                <rect x="238" y="0" width="1" height="111" style="fill:black" />
                <rect x="242" y="0" width="1" height="111" style="fill:black" />
                <rect x="243" y="0" width="1" height="111" style="fill:black" />
                <rect x="244" y="0" width="1" height="111" style="fill:black" />
                <rect x="257" y="0" width="1" height="111" style="fill:black" />
                <rect x="258" y="0" width="1" height="111" style="fill:black" />
                <rect x="259" y="0" width="1" height="111" style="fill:black" />
                <rect x="266" y="0" width="1" height="111" style="fill:black" />
                <rect x="267" y="0" width="1" height="111" style="fill:black" />
                <rect x="268" y="0" width="1" height="111" style="fill:black" />
                <rect x="278" y="0" width="1" height="111" style="fill:black" />
                <rect x="279" y="0" width="1" height="111" style="fill:black" />
                <rect x="280" y="0" width="1" height="111" style="fill:black" />
                <rect x="284" y="0" width="1" height="111" style="fill:black" />
                <rect x="285" y="0" width="1" height="111" style="fill:black" />
                <rect x="286" y="0" width="1" height="111" style="fill:black" />
                <text x="11" y="119" style="text-anchor:middle;font-size:10px;">2</text>
                <text x="33" y="119" style="text-anchor:middle;font-size:10px;">7</text>
                <text x="55" y="119" style="text-anchor:middle;font-size:10px;">1</text>
                <text x="77" y="119" style="text-anchor:middle;font-size:10px;">0</text>
                <text x="99" y="119" style="text-anchor:middle;font-size:10px;">2</text>
                <text x="121" y="119" style="text-anchor:middle;font-size:10px;">8</text>
                <text x="143" y="119" style="text-anchor:middle;font-size:10px;">2</text>
                <text x="165" y="119" style="text-anchor:middle;font-size:10px;">9</text>
                <text x="187" y="119" style="text-anchor:middle;font-size:10px;">3</text>
                <text x="209" y="119" style="text-anchor:middle;font-size:10px;">6</text>
                <text x="231" y="119" style="text-anchor:middle;font-size:10px;">4</text>
                <text x="253" y="119" style="text-anchor:middle;font-size:10px;">6</text>
                <text x="275" y="119" style="text-anchor:middle;font-size:10px;">8</text>
            </svg>

            <div class="pttSupplier">100301619</div>

        </div>

        <div class="gondericiBaslik"><span>GÖNDERİCİ</span></div>

        <div class="gondericiAd">ADI SOYADI :
            <span>PtteM</span> |
            <span style="font-weight:bold;">TEL/GSM : </span>
            <span>-</span> |
            <span style="font-weight:bold;color:red">DEPO : </span><span>BuluttaBul</span>
        </div>

        <div class="gonderi">GÖNDERİ TÜRÜ :
            <label style="font-weight:normal;"> KARGO</label>
        </div>

        <div class="gondericiAdres">ADRES :
            <span>Çankaya/ANKARA  </span>
        </div>

        <div class="aliciBaslik">
            <span>ALICI</span>
        </div>

        <div class="aliciAd">ADI SOYADI :
            <span>PTT Merkez</span>
        </div>

        <div class="aliciAdres">ADRES : <span style="line-height:15px;">
        Çankaya/ANKARA</span>
        </div>

        <div class="ilce-il">
            <label style="font-weight:bold;">Çankaya/ANKARA
        </label>
        </div>

        <div class="aliciTel">
            <b>TEL/GSM :</b>
            05123456789
        </div>

        <div class="gonderiAgirlik"><b>GÖNDERİNİN AĞIRLIĞI :
        </b> 7000 gr.
        </div>
        <div class="desiBilgisi">
            <b>DESİ :</b> 7
        </div>

        <div class="ekHizmet"><b>EK HİZMET :</b> DKKT</div>

        <div class="gonderiUcreti"><b style="font-size:12px;">ÜRÜN BEDELİ :
         </b>
            <b style="display:block;clear:both;margin-top:2px;font-size:19px;font-size:14px;">

                 -

            </b>
        </div>
        <div class="yeniLogo">
            <img src="https://img.pttavm.com/barcode_content/epttavm_siyah.png" alt=""/>
        </div>

        <div class="product-details">
            <div class="product-details-title">Ürün Bilgileri</div>
            <div class="product-details-table-field">
                <table>
                    <thead>
                        <tr>
                            <th>Adet:</th>
                            <th>Ürün Adı:</th>
                        </tr>
                    </thead>
                    <tbody>

                        <tr>
                            <td>1</td>
                            <td>
                                <div>
                                    Boron Aqua Bor Toz Çamaşır Deterjanı 6 Kg Beyazlar

                                </div>
                            </td>
                        </tr>

                    </tbody>
                </table>

            </div>
        </div>

        <div class="supplier_id_barcode">
            <?xml version="1.0"?>
            <!-- Generated by SVGo -->
            <svg style="position: absolute; top: 1px; right: -22px; " width="200" height="40"
                xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">
                <rect x="0" y="0" width="200" height="50" style="fill:white" />
                <rect x="22" y="0" width="1" height="30" style="fill:black" />
                <rect x="25" y="0" width="1" height="30" style="fill:black" />
                <rect x="27" y="0" width="1" height="30" style="fill:black" />
                <rect x="28" y="0" width="1" height="30" style="fill:black" />
                <rect x="30" y="0" width="1" height="30" style="fill:black" />
                <rect x="31" y="0" width="1" height="30" style="fill:black" />
                <rect x="33" y="0" width="1" height="30" style="fill:black" />
                <rect x="35" y="0" width="1" height="30" style="fill:black" />
                <rect x="36" y="0" width="1" height="30" style="fill:black" />
                <rect x="38" y="0" width="1" height="30" style="fill:black" />
                <rect x="41" y="0" width="1" height="30" style="fill:black" />
                <rect x="43" y="0" width="1" height="30" style="fill:black" />
                <rect x="45" y="0" width="1" height="30" style="fill:black" />
                <rect x="46" y="0" width="1" height="30" style="fill:black" />
                <rect x="48" y="0" width="1" height="30" style="fill:black" />
                <rect x="50" y="0" width="1" height="30" style="fill:black" />
                <rect x="53" y="0" width="1" height="30" style="fill:black" />
                <rect x="54" y="0" width="1" height="30" style="fill:black" />
                <rect x="56" y="0" width="1" height="30" style="fill:black" />
                <rect x="57" y="0" width="1" height="30" style="fill:black" />
                <rect x="59" y="0" width="1" height="30" style="fill:black" />
                <rect x="61" y="0" width="1" height="30" style="fill:black" />
                <rect x="63" y="0" width="1" height="30" style="fill:black" />
                <rect x="66" y="0" width="1" height="30" style="fill:black" />
                <rect x="67" y="0" width="1" height="30" style="fill:black" />
                <rect x="69" y="0" width="1" height="30" style="fill:black" />
                <rect x="70" y="0" width="1" height="30" style="fill:black" />
                <rect x="72" y="0" width="1" height="30" style="fill:black" />
                <rect x="74" y="0" width="1" height="30" style="fill:black" />
                <rect x="75" y="0" width="1" height="30" style="fill:black" />
                <rect x="77" y="0" width="1" height="30" style="fill:black" />
                <rect x="78" y="0" width="1" height="30" style="fill:black" />
                <rect x="81" y="0" width="1" height="30" style="fill:black" />
                <rect x="83" y="0" width="1" height="30" style="fill:black" />
                <rect x="85" y="0" width="1" height="30" style="fill:black" />
                <rect x="87" y="0" width="1" height="30" style="fill:black" />
                <rect x="89" y="0" width="1" height="30" style="fill:black" />
                <rect x="92" y="0" width="1" height="30" style="fill:black" />
                <rect x="93" y="0" width="1" height="30" style="fill:black" />
                <rect x="95" y="0" width="1" height="30" style="fill:black" />
                <rect x="96" y="0" width="1" height="30" style="fill:black" />
                <rect x="98" y="0" width="1" height="30" style="fill:black" />
                <rect x="100" y="0" width="1" height="30" style="fill:black" />
                <rect x="101" y="0" width="1" height="30" style="fill:black" />
                <rect x="103" y="0" width="1" height="30" style="fill:black" />
                <rect x="106" y="0" width="1" height="30" style="fill:black" />
                <rect x="108" y="0" width="1" height="30" style="fill:black" />
                <rect x="110" y="0" width="1" height="30" style="fill:black" />
                <rect x="111" y="0" width="1" height="30" style="fill:black" />
                <rect x="113" y="0" width="1" height="30" style="fill:black" />
                <rect x="115" y="0" width="1" height="30" style="fill:black" />
                <rect x="116" y="0" width="1" height="30" style="fill:black" />
                <rect x="119" y="0" width="1" height="30" style="fill:black" />
                <rect x="120" y="0" width="1" height="30" style="fill:black" />
                <rect x="122" y="0" width="1" height="30" style="fill:black" />
                <rect x="124" y="0" width="1" height="30" style="fill:black" />
                <rect x="126" y="0" width="1" height="30" style="fill:black" />
                <rect x="127" y="0" width="1" height="30" style="fill:black" />
                <rect x="129" y="0" width="1" height="30" style="fill:black" />
                <rect x="132" y="0" width="1" height="30" style="fill:black" />
                <rect x="134" y="0" width="1" height="30" style="fill:black" />
                <rect x="136" y="0" width="1" height="30" style="fill:black" />
                <rect x="137" y="0" width="1" height="30" style="fill:black" />
                <rect x="139" y="0" width="1" height="30" style="fill:black" />
                <rect x="141" y="0" width="1" height="30" style="fill:black" />
                <rect x="142" y="0" width="1" height="30" style="fill:black" />
                <rect x="145" y="0" width="1" height="30" style="fill:black" />
                <rect x="147" y="0" width="1" height="30" style="fill:black" />
                <rect x="148" y="0" width="1" height="30" style="fill:black" />
                <rect x="150" y="0" width="1" height="30" style="fill:black" />
                <rect x="152" y="0" width="1" height="30" style="fill:black" />
                <rect x="154" y="0" width="1" height="30" style="fill:black" />
                <rect x="155" y="0" width="1" height="30" style="fill:black" />
                <rect x="157" y="0" width="1" height="30" style="fill:black" />
                <rect x="159" y="0" width="1" height="30" style="fill:black" />
                <rect x="162" y="0" width="1" height="30" style="fill:black" />
                <rect x="163" y="0" width="1" height="30" style="fill:black" />
                <rect x="165" y="0" width="1" height="30" style="fill:black" />
                <rect x="168" y="0" width="1" height="30" style="fill:black" />
                <rect x="170" y="0" width="1" height="30" style="fill:black" />
                <rect x="171" y="0" width="1" height="30" style="fill:black" />
                <rect x="173" y="0" width="1" height="30" style="fill:black" />
                <rect x="174" y="0" width="1" height="30" style="fill:black" />
                <rect x="176" y="0" width="1" height="30" style="fill:black" />
            </svg>

        </div>

        <div class="gonderiUrunler">
            <div style="font:bold 14px Arial;">Bu ürün <img style="top:10px;position:relative;" src="https://img.pttavm.com/barcode_content/topbar-logo_ust.png" alt=""> tarafından gönderilmiştir.
            </div>

        </div>
    </div>

</body>

</html>
Hata Kodları
Alan Adı	Açıklama
200	Success
400	Bad Request


Barkod Status Güncelle

Bu metod, kargo sürecine tabi olmayan (ör. dijital ürünler), hazırlık ve gönderilmiş aşamasındaki siparişlerinizi ' teslim edildi ' statüsüne çekmenize olanak tanır.

Endpoint Bilgileri
URL: https://shipment.pttavm.com/api/v1/update-no-shipping-order
HTTP Metodu: POST
Content-Type: application/json
Authorization: Basic Auth
Dikkat Edilmesi Gereken Kurallar
Dijital ürün kategorisinde olan siparişler (kargo sürecine tabi olmayan) için bu method kullanılmalıdır.
Hazırlık ve gönderilmiş aşamasında olan siparişler teslim edildi statüsüne çekilebilir.

Dijital Ürün Kategorileri
İşletim Sistemleri
Antivirüs Programları
Ofis Programları
Grafik ve Tasarım
Eğitim Yazılımları
Ticari Yazılımlar
Dijital İndirilebilir Lisanslar
Oyun Pinleri
Örnek Servis İsteği
https://shipment.pttavm.com/api/v1/update-no-shipping-order
Örnek Servis Body Bilgisi

{
  "order_id": "PTT-12345-061024"
}
Başarılı Örnek Servis Cevabı

{
  "message": "string",
  "status": true
}
Başarısız Örnek Servis Cevabı

{
    "status": false,
    "message": "Available no shipping order"
}
Hata Kodları
Alan Adı	Açıklama
200	Success
400	Bad Request
