Yetkilendirme(Token Alma)
Token Alma
Api ile işlemlerinizi gerçekleştirebilmek için bir token alıp, ürün ekleme, kategori güncelleme vb. gibi işlemleri yapabilirsiniz. Token alma işlemleri için gereken clientId ve clientSecret bilgilerinizi https://isortagim.pazarama.com/ panelinde yer alan Hesap Bilgileri alanından temin edebilirsiniz.


NOT: Alınan Access Token değerinin geçerlilik süresi 1 saattir.



NOT: Servisler ile ilgili {baseurl} bilgisi “isortagimapi.pazarama.com” olarak girilmelidir


POST: https://isortagimgiris.pazarama.com/connect/token


Body: Form Url Encoded:


grant_type: client_credentials
scope: merchantgatewayapi.fullaccess


Authentication Basic:

clientId: *****

clientSecret: *****


Örnek Token İsteği (Postman);

Postman ekranlarından Body kısmından, urlencoded bölümüne yukarıda iletilen parametreler eklenerek POST isteğinde bulunulur.


Authorization kısmı Basic Auth seçilerek “clientId” ve “clientSecret” girişi yapılır.



Başarılı Token Response Örneği;



url: https://isortagim.pazarama.com/auth/integration/token-alma



Siparişler


Başarılı olarak gerçekleşen siparişlerinizi Sipariş Listeleme yöntemiyle, order item statüsü veya tarih aralığı belirterek dilerseniz de Paging ile sorgulama yapabilirsiniz. Sorgulama için tarih formatı olarak YYYY-AA-GG girmeniz gerekmektedir.
Ayrıca sorgulama için tarih formatıyla birlikte Saat ve Dakika bilgisi de girerek ve statüsüne göre siparişlerinizi listeleyebilirsiniz.


DeliveryType :

Cargo = 1,

Courier = 2,

Store = 3 Digital= 4,

Donation= 5

DeliveryPoint= 10001


Dijital teslimatta iletilecek kod deliveryDetail alanında yer alan phoneNumber bilgisine olmalıdır. Dijital teslimat haricinde bu alan null gelmektedir.



Servis tipi: POST
https://{baseurl}/order/getOrdersForApi



NOT: EndDate parametresinde girilen tarihten önceki siparişleri sistem getirmektedir. İlgili günü kapsamamaktadır.

NOT:Başlangıç ile bitiş tarihi arası 1 ayı geçemez

NOT: Sipariş numarası ile sipariş sorgularken 6 aya kadar olan siparişler gelmekte.



Response Parametreleri:

Parametre
Veri Tipi
Değerleri
InvoiceType
int
1: Bireysel
2: Kurumsal
OrderItemStatus
int
3: Siparişiniz Alındı
6: Siparişiniz İptal Edildi
12: Siparişiniz Hazırlanıyor
18: İptal Süreci Başlatıldı
13: Tedarik Edilemedi
5: Siparişiniz Kargoya Verildi
16: Siparişiniz Mağazada
19: Siparişiniz Teslimat Noktasında
11: Teslim Edildi
14: Teslim Edilemedi
7: İade Süreci Başlatıldı
8: İade Onaylandı
9: İade Reddedildi
10: İade Edildi
PaymentType
int
1: Banka/Kredi Kartı
5: Cüzdan
8: Visa-Tek Tıkla Öde
11: Taksitli Ek Hesap
​



Parametre
Açıklama
Veri Tipi
OrderId
Siparişin Id değerini belirtmektedir.
guid
OrderNumber
Müşteriye önyüz tarafında gösterilecek sipariş numarasını belirtmektedir.
long
OrderDate
Siparişin tarihini belirtmektedir.
datetime
OrderAmount
Siparişin tutarını belirtmektedir
datetime
PaymentType
Ödeme tipini belirtmektedir.
int
Status
Siparişin statüsünü belirtmektedir.
int
CustomerId
Siparişi gerçekleştiren üyenin id bilgisini içermektedir
int
CustomerName
Müşteri adı soyadını belirtmektedir
string
CustomerEmail
Müşterinin e-mail adresini belirtmektedir
string
ShipmentAddress
Taşıma adresinin olduğu alandır.
list
BillingAddress
Fatura adresinin olduğu alandır.
list
OrderItem
Sipariş içerisinde yer alan ürün kalemlerinin olduğu alandır
list
AddressId
Kayıtlı adres başlığına ait id değeridir
guid
Title
Kayıtlı adres başlığıdır. (Ev Adresim)
string
NameSurname
Müşterinin Adı ve Soyadı bilgisini içerir.
string
CityName
Şehir bilgisini içermektedir.
string
DistrictName
İlçe bilgisini içermektedir
string
AddressDetail
Açık adres bilgisini içermektedir.
string
PhoneNumber
Telefon numarası bilgisini içermektedir
string
IdentityNumber
TCKN bilgisini içermektedir
string
InvoiceType
Fatura Tipi bilgisini içermektedir. (Bireysel,Kurumsal)
int
CompanyName
Kurumsal fatura için şirket adı bilgisini içermektedir
string
TaxNumber
Vergi Kimlik Numarasını belirtmektedir
int
TaxOffice
Vergi Dairesini belirtmektedir
string
isEInvoiceObliged
E-Arşiv/E-Fatura mükellefi olma durumunu belirtmektedir.
boolean
Items/id
Sipariş kalemine ait ürünün id değerini belirtmektedir
guid
ProductName
Ürün adını belirtmektedir
string
ProductURL
Ürün linkini belirtmektedir
string
Title
Ürün başlığını belirtmektedir
string
ProductImageUrl
Ürüne ait resmin URL adresini belirtmektedir
string
VariantOptionDisplay
Ürünün varyantlı olup, olmadığını belirtmektedir.
string
Stockcode
Ürünün stok kodu bilgisini belirtmektedir
string
Status
Ürün ile ilgili sipariş durumunu belirtmektedir
int
Quantity
Üründen kaç adet satıldığını belirtmektedir
int
Currency
Ürünün para birimini belirtmektedir
string
ListPrice
Ürünün liste fiyatını belirtmektedir
decimal
SalePrice
Ürünün satış fiyatını belirtmektedir
decimal
TaxIncluded
Ürünün KDV bilgisini belirtmektedir. (True, False)
boolean
TaxAmount
Ürünün vergi tutarını belirtmektedir.
decimal
ShipmentAmount
Ürünün kargo fiyatını belirtmektedir.
decimal
TotalPrice
Siparişin toplam tutarını belirtmektedir
decimal
CargoCompany
Siparişe ait kargo bilgilerini belirtmektedir
string
Name
Kargo firmasının adını belirtmektedir
string
Trackingnumber
Kargo takip numarasının girileceği alanı belirtmektedir.
int
TrackingURL
Kargo takip linkinin girileceği alanı belirtmektedir.
string
orderItemStatus
Siparişe ait ürünün sipariş durumunu belirtmektedir.
int
deliveryType
Ürünün teslimat tipini belirtmektedir
int
shipmentCode
Anlaşmalı kargo entegrasyonunu kullanan firmalar için oluşturulan Gönderi Kodu
alanıdır.
string
shipmentCost
Anlaşmalı kargo entegrasyonu kullanan
firmalar için maliyet bilgisinin gösterildiği alandır
decimal


Anlaşmalı firmalar için oluşturulan kargo gönderi kodushipmentCodealanında görüntülenecektir. Firmalar bu kod ile kargo süreçlerini yönetebileceklerdir.
Anlaşmalı olmayan firmalar için ise, kargo süreçleri mevcut sistemde olduğu gibi kendileri tarafından yönetilecektir
Anlaşmalı firmalar için kargo maliyet değerlerishipmentCostparametresi içerisinde gösterilecek olup, parçalı gönderim ve kargo barem değerinin üzerinde gönderiler için sonradan hesaplanacak olup, bu alanda yer alan değer güncellenecektir.
Anlaşmalı firmalar için kargo ücreti alanıshipmentAmountalanında bir değer görüntülenmeyecektir.
Anlaşmalı olmayan firmalar için ise, mevcut sistemde olduğu gibi kendi belirledikleri kargo gönderim ücretishipmentAmountalanında görüntülenecektir
Firmanın kargoya veriliş süresi ne kadar ise siparişin veriliş tarihine göre termin süresinin(estimatedShippingDate)gösterimi eklenmiştir


Örnek Request (Order / Saat&Dakika)
{
      
"orderNumber": 
735071747,
      
"startDate": 
"2021-05-14T13:30",
      
"endDate": 
"2021-05-24T17:30"
}
Örnek Request (Paging)
{
      
"pageSize": 
500,
      
"pageNumber": 
1,
      
"startDate": 
"2023-02-01",
      
"endDate": 
"2023-02-17"
}
Örnek Response
{
      
"data": 
[
      
      
{
      
      
      
"orderId": 
"d4fb5f23-6330-4eb0-a81c-35847560df86",
      
      
      
"orderNumber": 
235795225,
      
      
      
"orderDate": 
"2023-01-25 15:22",
      
      
      
"orderAmount": 
1,
      
      
      
"shipmentAmount": 
0,
      
      
      
"discountAmount": 
0.2,
      
      
      
"discountDescription": 
"Moda100",
      
      
      
"currency": 
"TL",
      
      
      
"paymentType": 
1,
      
      
      
"orderStatus": 
3,
      
      
      
"customerId": 
"f442961c-d818-4de3-1e11-08d941fd1d2f",
      
      
      
"customerName": 
"Pazarama Sipariş",
      
      
      
"customerEmail": 
"pzrmsprs@pazarama.com",
      
      
      
"shipmentAddress": 
{
      
      
      
      
"addressId": 
"faeebdb9-7c21-4b59-8b37-03a3793f1978",
      
      
      
      
"title": 
"İş Bankası İkamet Adresi",
      
      
      
      
"nameSurname": 
"Pazarama Sipariş",
      
      
      
      
"customerEmail": 
"pzrmsprs@pazarama.com",
      
      
      
      
"cityName": 
"Kütahya",
      
      
      
      
"districtName": 
"Merkez",
      
      
      
      
"neighborhoodName": 
"Merkez Mah",
      
      
      
      
"addressDetail": 
"Cami sk. NO: 5",
      
      
      
      
"displayAddressText": 
"Merkez Mah Cami sk. NO: 5/ Merkez / Kütahya",
      
      
      
      
"phoneNumber": 
"054243029677"
      
      
      
},
      
      
      
"billingAddress": 
{
      
      
      
      
"addressId": 
"7751ddc7-8071-4dcf-b093-04ec1b8cbdfe",
      
      
      
      
"title": 
"İş Bankası İkamet Adresi",
      
      
      
      
"nameSurname": 
"Pazarama Sipariş",
      
      
      
      
"customerEmail": 
"pzrmsprs@pazarama.com",
      
      
      
      
"cityName": 
"Kütahya",
      
      
      
      
"districtName": 
"Merkez",
      
      
      
      
"neighborhoodName": 
"Merkez Mah",
      
      
      
      
"addressDetail": 
"Cami sk. NO: 5",
      
      
      
      
"displayAddressText": 
"Merkez Mah Cami sk. NO: 5/ Merkez / Kütahya",
      
      
      
      
"phoneNumber": 
"054243029677",
      
      
      
      
"identityNumber": 
null,
      
      
      
      
"invoiceType": 
1,
      
      
      
      
"companyName": 
null,
      
      
      
      
"taxNumber": 
null,
      
      
      
      
"taxOffice": 
null,
      
      
      
      
"isEInvoiceObliged": 
false
      
      
      
},
      
      
      
"items": 
[
      
      
      
      
{
      
      
      
      
      
"orderItemId": 
"5516bd97-5344-4d22-a346-0f263c0f51ca",
      
      
      
      
      
"orderItemStatus": 
3,
      
      
      
      
      
"shipmentCode": 
"",
      
      
      
      
      
"shipmentCost": 
{
      
      
      
      
      
      
"currency": 
"TL",
      
      
      
      
      
      
"value": 
0,
      
      
      
      
      
      
"valueInt": 
0,
      
      
      
      
      
      
"valueString": 
"0,00 TL",
      
      
      
      
      
      
"wholePartString": 
"0",
      
      
      
      
      
      
"fractionPartString": 
"00",
      
      
      
      
      
      
"decimalSeparator": 
","
      
      
      
      
      
},
      
      
      
      
      
"deliveryType": 
1,
      
      
      
      
      
"deliveryDetail": 
{
      
      
      
      
      
      
"phoneNumber": 
"null",
      
      
      
      
      
      
"email": 
null
      
      
      
      
      
},
      
      
      
      
      
"quantity": 
1,
      
      
      
      
      
"listPrice": 
{
      
      
      
      
      
      
"currency": 
"TL",
      
      
      
      
      
      
"value": 
1,
      
      
      
      
      
      
"valueInt": 
100,
      
      
      
      
      
      
"valueString": 
"1,00 TL",
      
      
      
      
      
      
"wholePartString": 
"1",
      
      
      
      
      
      
"fractionPartString": 
"00",
      
      
      
      
      
      
"decimalSeparator": 
","
      
      
      
      
      
},
      
      
      
      
      
"salePrice": 
{
      
      
      
      
      
      
"currency": 
"TL",
      
      
      
      
      
      
"value": 
1,
      
      
      
      
      
      
"valueInt": 
100,
      
      
      
      
      
      
"valueString": 
"1,00 TL",
      
      
      
      
      
      
"wholePartString": 
"1",
      
      
      
      
      
      
"fractionPartString": 
"00",
      
      
      
      
      
      
"decimalSeparator": 
","
      
      
      
      
      
},
      
      
      
      
      
"taxAmount": 
{
      
      
      
      
      
      
"currency": 
"TL",
      
      
      
      
      
      
"value": 
0.15,
      
      
      
      
      
      
"valueInt": 
15,
      
      
      
      
      
      
"valueString": 
"0,15 TL",
      
      
      
      
      
      
"wholePartString": 
"0",
      
      
      
      
      
      
"fractionPartString": 
"15",
      
      
      
      
      
      
"decimalSeparator": 
","
      
      
      
      
      
},
      
      
      
      
      
"shipmentAmount": 
{
      
      
      
      
      
      
"currency": 
"TL",
      
      
      
      
      
      
"value": 
0,
      
      
      
      
      
      
"valueInt": 
0,
      
      
      
      
      
      
"valueString": 
"0,00 TL",
      
      
      
      
      
      
"wholePartString": 
"0",
      
      
      
      
      
      
"fractionPartString": 
"00",
      
      
      
      
      
      
"decimalSeparator": 
","
      
      
      
      
      
},
      
      
      
      
      
"totalPrice": 
{
      
      
      
      
      
      
"currency": 
"TL",
      
      
      
      
      
      
"value": 
1,
      
      
      
      
      
      
"valueInt": 
100,
      
      
      
      
      
      
"valueString": 
"1,00 TL",
      
      
      
      
      
      
"wholePartString": 
"1",
      
      
      
      
      
      
"fractionPartString": 
"00",
      
      
      
      
      
      
"decimalSeparator": 
","
      
      
      
      
      
},
      
      
      
      
      
"discountAmount": 
{
      
      
      
      
      
      
"currency": 
"TL",
      
      
      
      
      
      
"value": 
0.2,
      
      
      
      
      
      
"valueInt": 
20,
      
      
      
      
      
      
"valueString": 
"0,20 TL",
      
      
      
      
      
      
"wholePartString": 
"0",
      
      
      
      
      
      
"fractionPartString": 
"20",
      
      
      
      
      
      
"decimalSeparator": 
","
      
      
      
      
      
},
      
      
      
      
      
"discountDescription": 
"Moda100",
      
      
      
      
      
"taxIncluded": 
true,
      
      
      
      
      
"cargo": 
{
      
      
      
      
      
      
"companyName": 
"PTT",
      
      
      
      
      
      
"trackingNumber": 
null,
      
      
      
      
      
      
"trackingUrl": 
"https://gonderitakip.ptt.gov.tr"
      
      
      
      
      
},
      
      
      
      
      
"product": 
{
      
      
      
      
      
      
"productId": 
"0de9dde9-b7e6-47a8-7205-08daef63e1be",
      
      
      
      
      
      
"name": 
"Deneme Tişört Deneme",
      
      
      
      
      
      
"title": 
null,
      
      
      
      
      
      
"url": 
"deneme-tisort-deneme-p-deneroyaldene-1",
      
      
      
      
      
      
"imageURL": 
"https://cdn.pazarama.com/asset/deneroyaldene-1/images/denemetirtdeneme-1.png",
      
      
      
      
      
      
"variantOptionDisplay": 
"Gece Mavisi - Ekru/S",
      
      
      
      
      
      
"stockCode": 
null,
      
      
      
      
      
      
"code": 
"deneroyaldene-1",
      
      
      
      
      
      
"vatRate": 
18
      
      
      
      
      
}
      
      
      
      
}
      
      
      
]
      
      
}
      
],
      
"success": 
true,
      
"messageCode": 
"ORD0",
      
"message": 
null,
      
"userMessage": 
null,
      
"fromCache": 
false
}


https://isortagim.pazarama.com/auth/integration/siparisler




Kargo Takip Durumunu Bildirme
Kargo Takip Durumunu Bildirme


Kargo Takip durumu ile ilgili güncelleme yapabilmek için kullanılacak servistir. Aşağıdaki örnek Request ile işlem yapabilirsiniz.



Parametre
Açıklama
Veri Tipi
Zorunlu Alan
orderitemid
Kargo statüsü güncellenecek ürünün id değerini iletileceği alandır.
guid
Evet
status
Kargoya verilen siparişin statüsünü güncellemek için kullanılacak alandır.
int
Evet
trackingnumber
Kargo Takip numarasının girileceği alandır.
int
Evet
trackingurl
Kargo takip linkinin girileceği alandır.
string
Opsiyonel
cargoCompanyId
Kargo firmasına ait bilgileri içeren alandır.
guid
Evet


Servis tipi: PUT
https://{baseurl}/order/updateOrderStatus



Örnek Request
{
      
"orderNumber": 
127063369,
      
"item": 
{
      
      
"orderItemId": 
"6b09a841-2fb1-4afb-bdc1-7078f95ba4c5",
      
      
"status": 
5,
      
      
"deliveryType": 
1,
      
      
"shippingTrackingNumber": 
"1615598038857",
      
      
"trackingUrl": 
"https://www.yurticikargo.com/",
      
      
"cargoCompanyId": 
"7b5567ff-abe7-487e-5c79-08d8e480366a"
      
}
}
Örnek Response
{
      
"data": 
null,
      
"success": 
true,
      
"messageCode": 
null,
      
"message": 
null,
      
"userMessage": 
null
}

https://isortagim.pazarama.com/auth/integration/kargo-takip-durumu-bildirme



Toplu Sipariş Durumunu Güncelleme


Siparişinize ait durumu ürün / item bazında değil de toplu olarak güncellemenizi sağlamaktadır. Firmaların sipariş statüleri ile ilgili “Sipariş Alındı” statüsünden “Siparişiniz Hazırlanıyor” durumuna toplu güncellenmesi sağlanmaktadır.



Servis Tipi: PUT


https://{baseurl}/order/updateOrderStatusList






Örnek Request
{
      
"orderNumber": 
735071747,
      
"status": 
11
}



Muhasebe ve Finans Servisi


Yapılan satışlarınız, iade işlemleriniz gibi Finansal konuları içeren servislerdir. Tarih aralığı belirterek bu verilere ulaşabilirsiniz.



Servis tipi: POST
https://{baseurl}/order/paymentAgreement



Örnek Request
{
      
"startDate": 
"2023-01-01T00:00:01.768Z",
      
"endDate": 
"2023-01-02T23:59:59.768Z",
      
"allowanceDate": 
null,
      
"orderId": 
null
}
Örnek Response
{
      
"data": 
{
      
      
"transactionList": 
[
      
      
      
{
      
      
      
      
"orderId": 
459916556,
      
      
      
      
"trxCode": 
"ORDER-23003TArH07110322",
      
      
      
      
"trxId": 
"cab6971e-946b-40ec-97ab-08daed6ab000",
      
      
      
      
"amount": 
1,
      
      
      
      
"installmentNumber": 
0,
      
      
      
      
"commissionAmount": 
0,
      
      
      
      
"couponDiscount": 
0,
      
      
      
      
"allowanceAmount": 
1,
      
      
      
      
"status": 
"Satış",
      
      
      
      
"transactionDate": 
"2023-01-03T19:00:00",
      
      
      
      
"transferredDate": 
"2023-02-03T00:00:00"
      
      
      
}
      
      
],
      
      
"totalAmount": 
1,
      
      
"totalCommission": 
0,
      
      
"totalAllowance": 
1
      
},
      
"success": 
true,
      
"messageCode": 
null,
      
"message": 
null,
      
"userMessage": 
null,
      
"fromCache": 
false
}



İptal Durumu ve Güncelleme Servisi


Bu servis ile İptal Taleplerini listelenmesi ve statülerde güncellemeler sağlayabilirsiniz. İptal taleplerini listeledikten sonra “refundId” ve “quantity” değeriyle birlikte işlemlerinizi gerçekleştirebilirsiniz.


NOT: Firmalar tüm statüleri listeleyebilir. Ancak güncelleme işlemi için sadece Onaylama (Statü:2) ve Ret (Statü:3) numaralı statüler ile işlem yapabilirler.





Parametre
Veri Tipi
Değer/ Açıklama
requestNo
int
İlgili işleme ait request numarasını belirtmektedir

int
1: Onay Bekliyor
2: Tedarikçi Tarafından Onaylandı
3: Tedarikçi Tarafından Reddedildi
4: Backoffice Tarafından Onaylandı
5: Backoffice Tarafından Reddedildi
6- Auto Approved
7-Talep İptal Edildi
8: Direkt Onay


Tedarikçi Tarafından Onaylandı: Firmaların onaylamış olduğu iptal talebi sonrasında finansal işlemler gerçekleşmesi için gerekli adımlar arka planda uygulanmaktadır.


Tedarikçi Tarafından Reddedildi: Firmaların kabul etmediği iptal için bu talepler Backoffice (Admin) ekranlarına düşmektedir.


Backoffice Tarafından Onaylandı: Firmaların kabul etmediği iptaller için bu ekranlar üzerinden yetkililer firma ve müşterilerle görüşerek iptal talebini kabul edebilir veya reddedebilir. Kabul etmesi durumunda ise, finansal iade işleminin gerçekleşmesi için gerekli adımlar arka planda uygulanmaktadır.


Backoffice Tarafından Reddedildi: Firmaların kabul etmediği iptaller için bu ekranlar üzerinden yetkililer firma ve müşterilerle görüşerek iptal talebini reddedebilir. İptal talebinin kabul edilmemesi durumunda finansal olarak arka planda herhangi bir aksiyon alınmamaktadır.



Servis Tipi: PUT
https://{baseurl}/order/api/cancel

Örnek Request
{
      
"refundId": 
"59eff35d-b399-407d-bc0e-62821ce9f623",
      
"status": 
3
}
Örnek Response
{
      
"data": 
{
      
      
"orderNumber": 
696730236,
      
      
"requestNo": 
0,
      
      
"refundId": 
"59eff35d-b399-407d-bc0e-62821ce9f623",
      
      
"orderItemId": 
"37287b10-f93f-44ef-b10b-2566709cfd64",
      
      
"refundType": 
"Yanlış adres seçtim",
      
      
"refundStatus": 
"Tedarikçi Tarafından Reddedildi"
      
},
      
"success": 
true,
      
"messageCode": 
"ORD0",
      
"message": 
null,
      
"userMessage": 
null,
      
"fromCache": 
false
}


İptal Taleplerini Sorgulama Servisi


Servis Tipi: POST
https://{baseurl}/order/api/cancel/items

Örnek Request
{
      
"pageSize": 
10,
      
"pageNumber": 
1,
      
"refundStatus": 
null,
      
"requestStartDate": 
"2024-02-20",
      
"requestEndDate": 
"2024-03-02",
      
"orderNumber": 
null
}
Örnek Response
{
      
"data": 
{
      
      
"responsePage": 
{
      
      
      
"pageSize": 
10,
      
      
      
"pageIndex": 
1,
      
      
      
"totalCount": 
1,
      
      
      
"totalPages": 
0
      
      
},
      
      
"pageReport": 
{
      
      
      
"totalRefundCount": 
12,
      
      
      
"totalWaitingRefundCount": 
5,
      
      
      
"totalApprovedRefundCount": 
6,
      
      
      
"totalRejectedRefundCount": 
1
      
      
},
      
      
"refundList": 
[
      
      
      
{
      
      
      
      
"id": 
1,
      
      
      
      
"refundId": 
"59eff35d-b399-407d-bc0e-62821ce9f623",
      
      
      
      
"orderNumber": 
696730236,
      
      
      
      
"orderDate": 
"1 Mart 2024 10:12",
      
      
      
      
"refundType": 
"Yanlış adres seçtim",
      
      
      
      
"refundStatus": 
1,
      
      
      
      
"refundStatusName": 
"Onay Bekliyor",
      
      
      
      
"paymentType": 
"Banka/Kredi Kartı",
      
      
      
      
"refundDate": 
"1 Mart 2024 10:21",
      
      
      
      
"totalAmount": 
{
      
      
      
      
      
"currency": 
"TL",
      
      
      
      
      
"value": 
2,
      
      
      
      
      
"valueInt": 
200,
      
      
      
      
      
"valueString": 
"2,00 TL",
      
      
      
      
      
"wholePartString": 
"2",
      
      
      
      
      
"fractionPartString": 
"00",
      
      
      
      
      
"decimalSeparator": 
","
      
      
      
      
},
      
      
      
      
"refundAmount": 
{
      
      
      
      
      
"currency": 
"TL",
      
      
      
      
      
"value": 
2,
      
      
      
      
      
"valueInt": 
200,
      
      
      
      
      
"valueString": 
"2,00 TL",
      
      
      
      
      
"wholePartString": 
"2",
      
      
      
      
      
"fractionPartString": 
"00",
      
      
      
      
      
"decimalSeparator": 
","
      
      
      
      
},
      
      
      
      
"customerId": 
"7bcacd8f-bf33-451b-de91-08d9e273c96f",
      
      
      
      
"customerName": 
"Mehmet Sincap",
      
      
      
      
"customerEmail": 
"mehmet.sincap@pazarama.com",
      
      
      
      
"customerPhoneNumber": 
"5327329889",
      
      
      
      
"customerAddress": 
" Itri Sk. Bina No:6 Kat:3 Daire:15 Ersoy K2 Blok ",
      
      
      
      
"productName": 
"Beyaz Peynir",
      
      
      
      
"productCode": 
"BPD55555",
      
      
      
      
"productStockCode": 
"BP55550",
      
      
      
      
"shipmentCompanyName": 
null,
      
      
      
      
"shipmentCode": 
null,
      
      
      
      
"description": 
null,
      
      
      
      
"boDescription": 
null,
      
      
      
      
"quantity": 
1
      
      
      
}
      
      
]
      
},
      
"success": 
true,
      
"messageCode": 
"ORD0",
      
"message": 
null,
      
"userMessage": 
null,
      
"fromCache": 
false
}




İadeler


Bu servis iade taleplerini listelemenize olanak sağlamaktadır. İade talepleri ile ilgili tüm detaylar servis içerisinde yer almaktadır. Aşağıda örnek sorgulama parametreleri bulunmaktadır.


Ayrıca sorgulama için tarih formatıyla birlikte Saat ve Dakika bilgisi de girerek iadelerinizi listeyebilirsiniz.



NOT: Anlaşmalı kargo kullanan firmalar için “İade Kargo Kodu” üretilmektedir. Bu üretilen kod için parametre ismi shipmentCode olarak belirlenmiştir.

NOT: Teslim edilemedi siparişlerin iadesinde shiptmentcompanyname alanı dolu gelecek şekilde ayarlanmıştır.



Parametre
Açıklama
Veri Tipi
refundId
İadenin Id değerini belirtmektedir
guid
OrderNumber
Müşteriye önyüz tarafında gösterilecek sipariş numarasını belirtmektedir.
long
OrderDate
Siparişin tarihini belirtmektedir.
datetime
RefundNumber
İade numarasını belirtmektedir..
long
RefunsStatus
İade statüsünü belirtmektedir
int
RefundType
İade sebebini belirtmektedir.
string
RefundStatusName
İade statüsünün ismini belirtmektedir.
string
PaymentType
Ödeme tipini belirtmektedir.
int
RefundDate
İade talebinin tarihini belirtmektedir
datetime
TotalAmount
Siparişin toplam tutarını belirtmektedir
decimal
RefundAmount
İade edilecek ürünün toplam tutarını belirtmektedir
decimal
CustomerId
İşlemi gerçekleştiren üyenin id bilgisini içermektedir.
guid
CustomerName
Müşteri adı soyadını belirtmektedir.
string
CustomerEmail
Müşterinin e-mail adresini belirtmektedir.
string
CustomerPhoneNumber
Müşterinin telefon numarasını belirtmektedir
string
CustomerAddress
Müşterinin adres bilgisini belirtmektedir.
string
OrderItem
Sipariş içerisinde yer alan ürün kalemlerinin olduğu alandır.
list
productCode
Ürün barkod bilgisini belirtmektedir
string
ProductName
Ürün adını belirtmektedir.
string
ProductStockCode
Ürünün stok kodu bilgisini belirtmektedir.
string
ShipmentCompanyName
Kargo firmasının ismini belirtmektedir.
string
Description
İade sebebiyle ilgili açıklama alanı girilen bölümdür
string
shipmentCode
Anlaşmalı kargo entegrasyonunu kullanan
firmalar için oluşturulan İade işlemindeki Kargo Kodu alanıdır.
string


Servis Tipi: POST

https://{baseurl}/order/getRefund

Örnek Request
{
      
"pageSize": 
10,
      
"pageNumber": 
1,
      
"refundStatus": 
1,
      
"requestStartDate": 
"2021-10-01",
      
"requestEndDate": 
"2021-10-08"
}
Örnek Response
{
      
"data": 
{
      
      
"responsePage": 
{
      
      
      
"pageSize": 
100,
      
      
      
"pageIndex": 
1,
      
      
      
"totalCount": 
49,
      
      
      
"totalPages": 
1
      
      
},
      
      
"pageReport": 
{
      
      
      
"totalRefundCount": 
49,
      
      
      
"totalWaitingRefundCount": 
5,
      
      
      
"totalApprovedRefundCount": 
31,
      
      
      
"totalRejectedRefundCount": 
13
      
      
},
      
      
"refundList": 
[
      
      
      
{
      
      
      
      
"id": 
1,
      
      
      
      
"refundId": 
"ef2affaf-fdfc-4128-b5bc-3a4c1129e662",
      
      
      
      
"orderNumber": 
818589784,
      
      
      
      
"orderDate": 
"6 Ekim 2021 14:53",
      
      
      
      
"refundNumber": 
564213,
      
      
      
      
"refundType": 
"Ürünün parçası eksik",
      
      
      
      
"refundStatus": 
1,
      
      
      
      
"refundStatusName": 
"İade Onayı Bekliyor",
      
      
      
      
"paymentType": 
"Banka/Kredi Kartı",
      
      
      
      
"refundDate": 
"6 Ekim 2021 19:46",
      
      
      
      
"totalAmount": 
{
      
      
      
      
      
"value": 
23.5,
      
      
      
      
      
"valueInt": 
2350,
      
      
      
      
      
"valueString": 
"23,50 TL",
      
      
      
      
      
"currency": 
"TL"
      
      
      
      
},
      
      
      
      
"refundAmount": 
{
      
      
      
      
      
"value": 
1.75,
      
      
      
      
      
"valueInt": 
175,
      
      
      
      
      
"valueString": 
"1,75 TL",
      
      
      
      
      
"currency": 
"TL"
      
      
      
      
},
      
      
      
      
"customerId": 
"9075e6da-2a3e-4959-29b6-08d91e2de243",
      
      
      
      
"customerName": 
"Dilara Demiral",
      
      
      
      
"customerEmail": 
"dilara.demiral@pazarama.com",
      
      
      
      
"customerPhoneNumber": 
"5352629133",
      
      
      
      
"customerAddress": 
" Bahçelievler/İstanbul",
      
      
      
      
"productName": 
"Böğürtlen Reçeli 30 g.",
      
      
      
      
"productCode": 
"201040500",
      
      
      
      
"productStockCode": 
null,
      
      
      
      
"shipmentCompanyName": 
"MNG",
      
      
      
      
"shipmentCode": 
54895647251356,
      
      
      
      
"description": 
"test",
      
      
      
      
"boDescription": 
null
      
      
      
}
      
      
]
      
},
      
"success": 
true,
      
"messageCode": 
"ORD0",
      
"message": 
" null ",
      
"userMessage": 
null,
      
"fromCache": 
false
}

https://isortagim.pazarama.com/auth/integration/iadeler


İade Durum Güncelleme Servisi


Bu servis ile İade Taleplerine ait statülerde güncellemeler sağlayabilirsiniz. İadelerinizi listeledikten sonra “refundId” değeriyle birlikte işlemlerinizi gerçekleştirebilirsiniz. Tedarikçi Tarafından Reddedildi statüsü için RefundRejectType Status iletilmelidir.



Parametre
Veri Tipi
Değer/ Açıklama
RefundRejectType Status
int
1: Gelen ürün bana ait değil
2: Gelen ürün defolu/zarar görmüş
3: Gelen ürün adedi eksik
4: Gelen ürün yanlış
5: Gelen ürün kullanılmış
6: Gelen ürün sahte
7: Gelen ürünün parçası/aksesuarı eksik
8: Gönderdiğim ürün kusurlu değil
9: Gönderdiğim ürün yanlış değil
10: İade paketi boş geldi
11: İade paketi elime ulaşmadı
12: Diğer


Parametre
Veri Tipi
Değer/ Açıklama
requestNo
int
İlgili işleme ait request numarasını belirtmektedir
status/refundStatus
int
1: Onay Bekliyor
2: Tedarikçi Tarafından Onaylandı
3: Tedarikçi Tarafından Reddedildi
4: Backoffice Tarafından Onaylandı
5: Backoffice Tarafından Reddedildi
6- Auto Approved
7-Talep İptal Edildi
8: Direkt Onay




NOT: Firmalar tüm statüleri listeleyebilir. Ancak güncelleme işlemi için sadece Onaylama (Statü:2) ve Ret (Statü:3) numaralı statüler ile işlem yapabilirler.



Tedarikçi Tarafından Onaylandı: Firmaların onaylamış olduğu iade talebi sonrasında finansal işlemler gerçekleşmesi için gerekli adımlar arka planda uygulanmaktadır.


Tedarikçi Tarafından Reddedildi: Firmaların kabul etmediği iadeler için bu talepler Backoffice (Admin) ekranlarına düşmektedir.


Backoffice Tarafından Onaylandı: Firmaların kabul etmediği iadeler için bu ekranlar üzerinden yetkililer firma ve müşterilerle görüşerek iade talebini kabul edebilir veya reddedebilir. Kabul etmesi durumunda ise, finansal iade işleminin gerçekleşmesi için gerekli adımlar arka planda uygulanmaktadır.


Backoffice Tarafından Reddedildi: Firmaların kabul etmediği iadeler için bu ekranlar üzerinden yetkililer firma ve müşterilerle görüşerek iade talebini reddedebilir. İade talebinin kabul edilmemesi durumunda finansal olarak arka planda herhangi bir aksiyon alınmamaktadır.





Önemli Not:

Açıklamalı  İade Akışı:



 İadelerde siparişin sipariş servisi ile eşleşebileceği "orderNumber" ve ürün ile eşleşebileceği "productCode" alanları yer almaktadır. Ayrıca iadeler "refundNumber" ile ayrıştırılmaktadır.
Son kullanıcı iade süreci başlattığında getOrdersForApi servisinde statü 7: İade Süreci Başlatıldı olarak görülmektedir. getRefund servisinde de 1: İade Onayı Bekliyor olarak yansımaktadır.
İade talebi tedarikçi panelde de İade Onayı Bekliyor olarak görülür.
Süreç istenirse tedarikçi panelden onaylanır veya reddedilir veya API de updateRefund servisinden statü 2: Tedarikçi Tarafından Onaylandı veya 3: Tedarikçi Tarafından Reddedildi olarak güncellenir ve getRefund servisinde aynı statüde görüntülenir.
Talebe istinaden tarafımızca yapılan manuel iadeler ise getRefund servisinde 4: Backoffice Tarafından Onaylandı veya 5: Backoffice Tarafından Reddedildi olarak görülür.
İade tedarikçi tarafından işleme alınmaz ise 6: Auto Approved ile sistem tarafından otomatik onaylanacaktır.

 Süreç aşağıdaki tabloda özetlenmiştir.
 getRefund order             getOrdersForApi

1: İade Onayı Bekliyor/ 7: İade Süreci Başlatıldı

2: Tedarikçi Tarafından Onaylandı/ 8: İade Onaylandı

3: Tedarikçi Tarafından Reddedildi/ 9: İade Reddedildi

4: Backoffice Tarafından Onaylandı/ 8: İade Onaylandı

5: Backoffice Tarafından Reddedildi/9: İade Reddedildi

6: Auto Approved

10: İade Edildi



Servis Tipi: POST
https://{baseurl}/order/updateRefund

​



​



Örnek Request
{
      
"refundId": 
"ef2affaf-fdfc-4128-b5bc-3a4c1129e662",
      
"status": 
2
}
Örnek Request
{
      
"refundId": 
"ef2affaf-fdfc-4128-b5bc-3a4c1129e662",
      
"status": 
3,
      
"RefundRejectType": 
1
}

https://isortagim.pazarama.com/auth/integration/iade-durum-guncelleme


Sipariş İade Yönetimi Satıcının Güncelleme Sağlayabilmesi


Api üzerinden Pazarama' ya iletilen iade talebi başlatma, iade reddi veya incelemeye gönderilme talebi isteklerinde, işlemlerin sonuçlandırılması için zaman zaman ek veriye ihtiyaç duyulmaktadır. Bu nedenle Pazarama tarafından revizyon talep edilerek api üzerinden satıcılara revizyon talebi iletebileceğimiz bir yapı kurulmuştur.



Not:

-Ürün bazlı işlem yapılabilir.
-Açıklama alanı zorunludur. (Manuel girilmektedir.)



https://isortagimapi.pazarama.com/order/api/refund/revision

Örnek Request
{
      
"refundId": 
"3fa85f64-5717-4562-b3fc-2c963f66afa6",
      
"documentObjects": 
[
      
      
{
      
      
      
"name": 
"string",
      
      
      
"bytes": 
"string"
      
      
}
      
],
      
"description": 
"string"
}
Örnek Response
{
      
"success": 
true,
      
"messageCode": 
"string",
      
"message": 
"string",
      
"userMessage": 
"string",
      
"fromCache": 
true
}

https://isortagim.pazarama.com/auth/integration/siparis-iade-yonetimi-saticinin-guncelleme-saglayabilmesi

Apiye "İncelemeye Gönder" seçeneği eklenmesi ve Görsel Ekleme


İade talep aksiyonlarında apiye bazı yenilikler eklenmiştir.


İade talep edilen ürün/ürünler için incelemeye gönderme seçeneği eklendi. İncelemeye gönderme ve reddetme seçeneklerinde fotoğraf eklenebilir duruma getirilmiştir.



https://isortagimapi.pazarama.com/order/updateRefund, apiden iade değişimi servisine eklenen yeni alanlar;

List<DocumentObject> DocumentObjects => doküman listesi, byte array listesi şeklinde,
RefundReviewType? RefundReviewType => inceleme tipi,
string Description => açıklama

RefundReviewType:


[Display(Name = "Üretici firma incelemesi")]
ManufacturerReview = 1,


[Display(Name = "Yetkili servis incelemesi")]
AuthorizedServiceReview = 2,


[Display(Name = "Diğer")]
Other = 3,
}



Not:

Yapılan değişiklikler aşağıda belirtilmiştir.


• İncelemeye gönder ve reddetme işlemlerinde Fotoğraf yüklenebilmektedir.
• İade red sebeplerinde bulunan “iade paketi boş geldi” ve “iade paketi elime ulaşmadı” seçimleri harici tüm sebeplerde görsel yükleme zorunlu tutulmalıdır.
• Bir ürün için en fazla 3 dosya ekleyebilir ve dosya boyutu 5 MB’ı geçmemelidir.
• İncelemeye gönderme ve reddetme işlemlerine açıklama alanı eklenmiştir.


• Aşağıdaki inceleme türleri eklenmiştir
- Üretici firma incelemesi,
- Yetkili servis incelemesi,
- Diğer seçenekleri görüntülenmelidir.
İncelemeye gönderme sürecinde: Diğer seçeneği seçilmesi durumunda “Problem detayı” girişi zorunludur. Geri kalan iki seçenekte (Üretici firma incelemesi, Yetkili servis incelemesi) zorunlu değildir.
Reddetme sürecinde: açıklama alanı her bir seçim için zorunludur.


İlgili kurallar tek ürün için geçerlidir.

https://isortagimapi.pazarama.com/order/updateRefund



Örnek Request
{
      
"refundId": 
"14ecbc64-5a01-4979-980b-7f7a60ebb5e8",
      
"status": 
9,
      
"quantity": 
1,
      
"refundRejectType": 
0,
      
"documentObjects": 
[
      
      
{
      
      
      
"name": 
"images.png",
      
      
      
"bytes": 
"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"
      
      
}
      
],
      
"refundReviewType": 
2,
      
"description": 
"apiden iade incelecelemey gönderme test- fotograf var, yorum var"
}
Örnek Response
{
      
"data": 
{
      
      
"orderNumber": 
0,
      
      
"requestNo": 
0,
      
      
"refundId": 
"00000000-0000-0000-0000-000000000000",
      
      
"orderItemId": 
"00000000-0000-0000-0000-000000000000",
      
      
"refundType": 
null,
      
      
"refundStatus": 
"İncelemeye Gönderme Talep Edildi"
      
},
      
"success": 
true,
      
"messageCode": 
"ORD0",
      
"message": 
null,
      
"userMessage": 
null,
      
"fromCache": 
false
}

https://isortagim.pazarama.com/auth/integration/apiye-incelemeye-gonder-gorsel-ekleme