Siparis Entegrasyonu Onemli Bilgiler
👍
Önemli Bilgi

Bu dokümanda yer alan endpoint url'leri test ortamına aittir. Dokumanda sayfasında test ortam endpointleri test edilebilir. Canlı ortam url'leri endpoint içinde "-sit" ifadesi kaldırılarak oluşturabilirsiniz. Canlı ortam endpoint'ine canlı ortam için verilen User/Password ile istek gönderilebilir.

📘
Hepsiburada API Authentication Bilgilendirmesi

Mevcuttaki tüm servislerimizin authentication yapısında değişiklik yapılmıştır. Sizlerden servislerimizdeki bu değişikliğin hızla yapılması noktasında desteğinizi rica ederiz.

Entegratöre Servis Anahtarı Ekleme/Görüntüleme işlemleri için hazırladığımız sayfamızı inceleyebilirsiniz.

📘
Hepsiburada Sipariş Entegrasyonu Limitleri

Sipariş Entegrasyonu servislerimize SIT(Test) ve Prod(Canlı) ortamlarımızda gelen isteklerde bir limit değeri eklenecektir. Kullanıcılarımız artık belirli bir zaman dilimi içerisinde limit değeri kadar (1 saniye içerisinde 1k) istek gönderililebiliyor olacak. Limit değerini aşan istekler için 429 TooManyRequest hatası alınacaktır. Bununla birlikte response header içerisinde aşağıdaki bilgiler dönülüyor olacaktır.

X-RateLimit-Remaining : Geçerli zaman aralığında kalan istek sayısı
X-RateLimit-Limit : İzin verilen maksimum request sayısı
X-RateLimit-Reset : Geçerli zaman aralığının yenilenmesine kalan saniye

Test İçin Sipariş Oluşturma
Bu işlev yalnızca TEST ortamında mevcuttur. Testlerinizi tamamlayabilmeniz için sipariş oluşturmanıza olanak tanır.

API, HTTP Basic Auth. ile korunmaktadır, dolayısıyla istemci, kullanıcı adı ve şifreyi HTTP Authorization Header bilgisinde göndermelidir.
Merchantid (gerekli, guid, b2910839-83b9-4d45-adb6-86bad457edcb) Her satıcının unique bir tanımlayıcısıdır.
Ordernumber (gerekli, string,0116431) Sipariş numarası unique bir değer olmalıdır, sipariş oluştururken rastgele değiştirebilirsiniz.
LineItems Doğru bir hbsku değeri ile bir siparişte istediğiniz sayıda lineitem oluşturabilirsiniz. (Aşağıdaki örnek 2 adet lineitem için oluşturulmuştur.)
LineItems.MerchantId MerchantId parametresi URL de sağlanan MerchantId ile aynı olmalıdır.
Örnek Test Sipariş Request Body-JSON

{
"OrderNumber":"041241341",
"OrderDate":"2018-12-21T09:34:47",
"Customer":{
   "CustomerId":"dfc8a27f-faae-4cb2-859c-8a7d50ee77be",
   "Name":"Test User"
},
"DeliveryAddress":{
   "AddressId":"e66765b3-d37d-488c-ae15-47051245dc9b",
   "Name":"Hepsiburada Office",
   "AddressDetail":"Trump Towers",
   "Email":"customer@hepsiburada.com.tr",
   "CountryCode":"TR",
   "PhoneNumber":"902822613231",
   "AlternatePhoneNumber":"045321538212",
   "Town":"Sisli",
   "District":"Kustepe",
   "City":"İstanbul"
},
"LineItems":[
   {
      "Sku":"HBV0000106NM0",
      "MerchantId":"823539cd-1f10-4971-8859-cd648cfb4ff6",
      "Quantity":1,
      "Price":{"Amount":301.4,"Currency":"TRY"},
      "Vat":0,
      "TotalPrice":{"Amount":301.4,"Currency":"TRY"},
      "CargoCompanyId":1,
      "DeliveryOptionId":1
   },
   {
      "Sku":"HBV0000106NLG",
      "MerchantId":"823539cd-1f10-4971-8859-cd648cfb4ff6",
      "Quantity":1,
      "Price":{"Amount":301.4,"Currency":"TRY"},
      "Vat":0,
      "TotalPrice":{"Amount":301.4,"Currency":"TRY"},
      "CargoCompanyId":1,
      "DeliveryOptionId":1
   }
]
}
Ödemesi Tamamlanmış Siparişleri Listeleme
Bu metod ödemesi tamamlanmış yeni siparişleri (Paketlenecek statüdekileri) listeleyebilmenize olanak tanır.

API üzerinden sadece ödemesi tamamlanan siparişler gelecektir. Merchant Panel üzerinde ise Paketlencekler kısmına karşılık gelir. Havaleli olan siparişlerinde ödemesi tamamlandıktan hemen sonra API üzerinden akıtılmaktadır. Havaleli siparişlerin ön bilgileri "Ödemesi Beklenen Siparişler" servisinden alınarak stok rezervesi yapılabilir.
Offset, Limit(opsiyonel, int) Offset ve Limit birbirine bağlı iki parametredir. Sadece bir tanesi gönderildiğinde hata alınacaktır. Kullanım zorunludur.
Limit Offset pagenation yapısı olarak işlev görmektedir. Limit bir sayfada kaç adet sipariş listeleneceğini belirtirken, Offset hangi siparişten sonraki siparişlerin gösterileceğini belirtir.
Limit:10 Offset:0 gönderildiğinde ilk 10 sipariş listelenecektir. Limit:10 Offset:10 gönderildiğinde ilk 10 siparişten sonraki 10 sipariş listelenecektir.
Opsiyonel olan begindate ve enddate parametrelerini kullandığınızda statüleri Open ve Unpacked durumunda olan siparişlerinizi belirli bir tarih arasında listeleyebilirsiniz.
Ödemesi tamamlanmış siparişler endpointinden sonraki adım olan Aynı Pakete Konulabilecek Kalemleri Listeleme endpoint'idir.
Alan Açıklamaları
Alan Adı	Açıklama
totalCount
Anlık olarak kaç adet ödemesi tamamlanan siparişinizin olduğunu belirtir.
limit
Bir sayfada kaç adet siparişin listeleneceğini belirtir.
offset
Hangi siparişten sonraki siparişlerin listeleneceğini belirtir.
pageCount
Toplam kaç adet sayfa olacağını belirtir.
items.dueDate
Siparişin kargoya verilmesi gereken son teslim tarihini belirtir.
items.lastStatusUpdateDate
Sipariş içerisinde bulunan kalemin en son işlem gördüğü tarihtir.
items.id
Sipariş içerisindeki kalemlerin unique değeridir. (Aynı pakete konulabilecek kalemleri listeleme endpointinde kullanılacaktır.)
items.sku
Sipariş içerisindeki listinglerin HBSKU değeridir.
items.orderId
Siparişin hepsiburada tarafında unique değeridir.
items.orderNumber
Sipariş numarasıdır.
items.orderDate
Siparişin oluşturulma tarihidir.
items.quantity
Siparişin içerisindeki kalemlerin adet sayısıdır.
items.merchantId
Merchantın uniqueId değeridir. (Test(SIT) ve canlı ortam için merchantId bilgisi hepsiburada.com tarafından iletilecektir.)
items.totalPrice.currency
Siparişteki kalemlerin her birinin toplam adet tutarının para birimi cinsinden değeridir.
items.totalPrice.amount
Siparişteki kalemlerin her birinin toplam adet tutarıdır.
items.unitPrice.currency
Siparişteki tek bir kalemin tutarının para birimi cinsinden değeridir.
items.unitPrice.amount
Siparişteki tek bir kalemin tutarının değeridir.
items.vat
KDV tutarıdır.
items.vatRate
KDV oranıdır.
items.customerName
Müşterinin adıdır.
items.status
Siparişin durumunu belirtir. Open: Yeni sipariş belirtir. / Unpacked: Paketi bozulan siparişleri belirtir.
items.shippingAddress
Teslimat adresidir.
items.invoice
Fatura bu alan içerisindeki bilgiler ile oluşturulmalıdır.
items.invoice.turkishIdentityNumber
Müşterinin T.C numarasıdır.
items.invoice.taxNumber
Müşterinin vergi dairesinin numarasıdır.
items.invoice.taxOffice
Müşterinin vergi dairesinin adıdır.
items.invoice.address
Siparişin fatura adresidir.
items.invoice.address.addressId
Siparişin hepsiburada.com üzerindeki unique değeridir.
items.invoice.address.address
Fatura adresinin açık adresidir.
items.invoice.address.name
Fatura adresinin isim bilgisidir.
items.invoice.address.email
Fatura adresinin mail bilgisidir.
items.invoice.address.countryCode
Fatura adresinin ülke bilgisinin kısa kodudur.
items.invoice.address.phoneNumber
Fatura adresinin telefon numarasıdır.
items.invoice.address.alternatePhoneNumber
Fatura adresinin alternarif telefon numarasıdır.
items.invoice.address.district
Fatura adresinin mahalle bilgisidir.
items.invoice.address.city
Fatura adresinin şehir bilgisidir.
items.invoice.address.town
Fatura adresinin ilçe bilgisidir.
items.sapNumber
Hepsiburada.com tarafında siparişin içerisinde bulunan kalemlerin sıra bilgisini verir.
items.dispatchTime
Siparişin kargoya verilme süresidir.
items.commission
Hepsiburada.com üzerinden alınan komisyondur.
items.commission.currency
Hepsiburada.com üzerinden alınan komisyon bedelinin komisyon cinsinden değeridir.
items.commission.amount
Hepsiburada.com üzerinden alınan komisyon bedelidir.
items.paymentTermInDays
Listing bazında merchanta ödeme yapılacağı gün verisidir.
items.commissionType
Hepsiburada.com tarafındaki komisyon bedelinin unique değeridir.
items.cargoCompanyModel.id
Kargo firmasının hepsiburada.com üzerindeki unique değeridir.
items.cargoCompanyModel.name
Listingin üzerine tanımlı kargo firmasının isim bilgisidir.
items.cargoCompanyModel.shortName
Listingin üzerine tanımlı kargo firmasının kısa isim bilgisidir.
items.cargoCompanyModel.logoUrl
Listingin üzerine tanımlı kargo firmasının logo url bilgisidir.
items.cargoCompanyModel.trackingUrl
Listingin paketlendikten sonraki kargo takip urlini belirtir.
items.cargoCompany
Listingin üzerine tanımlı kargo firmasının isim bilgisidir.
items.customizedText01
Özelleştirilebilir ürünün içerik bilgisini verir.
items.customizedText02
Özelleştirilebilir ürünün içerik bilgisini verir.
items.customizedText03
Özelleştirilebilir ürünün içerik bilgisini verir.
items.customizedText04
Özelleştirilebilir ürünün içerik bilgisini verir.
items.customizedTextX
Özelleştirilebilir ürünün içerik bilgisini verir.
items.creditCardHolderName
Sipariş verilen kartın üzerinde bulunan isim bilgisidir.
items.isCustomized
Sipariş verilen kalemin kişinin isteklerine göre özelleştirilebilir ürün olduğunu belirtir. True: Özelleştirilebilir ürün. False: Özelleştirilemeyen ürün
items.canCreatePackage
Ürünün paketlenebilir ürün olduğunu belirtir.
items.isCancellable
Listingin iptal edilme durumudur. True: İptal edilebilir ürün / False: İptal edilemez ürün
items.isCancellableByHbAdmin
Listingin Hbadmin tarafından iptal edilebilirlik durumudur. True: Hbadmin tarafından iptal edilebiir. / False: Hbadmin tarafından iptal edilemez.
items.deliveryType
eslimatın teslim verisidir. StandardDelivery: Standart teslimat / BT: Bugün Teslimat / YT: Yarın teslimat
items.deliveryOptionId
Teslimatın teslim verisidir. 1: StandardDelivery / 2: BT(Bugün teslimat) / 4: YT(yarın teslimat)
items.slot
Müşterinin paketi teslim almak için seçtiği saat aralığıdır.
items.pickUpTime
Merchantın kargo firmasına teslim etmesi gereken saat aralığıdır.
unitmerchantDiscount.amount
Merchant tarafından uygulanan birim indirim tutarı
totalmerchantDiscount.amount
Merchant tarafından uygulanan toplam indirim tutarı
items.purchasePrice
Drop çalışan merchantlar için ürünün fiyat bilgisidir.
items.creationReason
Siparişin hangi method ile tekrar yaratıldığını iletmektedir.Yeni Yaratılan : OrderCreated Transfer için : OrderLineTransferred Resend için : OrderLineResend Değişim için : ClaimChangeAccepted Parçalı paketleme : DeliveryCreated
Ödemesi Beklenen Siparişleri Listeleme
Bu metod ödemesi tamamlanmamış (fraud kontrolü , havale ödemeleri) yeni siparişleri listeleyebilmenize olanak tanır.

Ödemesi tamamlanmamış siparişleri listeleme endpointine düşen siparişler kayıt altına alınarak rezerve stoklar oluşturulmalıdır.
Belirli periyotlar ile bu method çağırılmalı ve daha önceden gelen bir siparişin bu method üzerinde dönmediği görüldüğünde ödemesi tamamlanmış siparişleri listeleme endpointine istek atılmalıdır.
Eğer ödemesi tamamlanmış siparişleri listeleme endpointi üzerinde listeleniyor ise sipariş onaylanmıştır ve rezerve stok kaldırılarak gerçek stok onaylanabilir.
Eğer ödemesi tamamlanmış siparişleri listeleme endpointi üzerinde listelenmiyor ise ödemesi tamamlanmamış ve iptal olmuş demektir. Rezerve stok tekrardan artırılabilir.
Alan Açıklamaları

Alan Adı	Açıklama
items.id	Sipariş içerisindeki kalemlerin unique değeridir.
items.sku	Sipariş içerisindeki listinglerin HBSKU değeridir.
items.name	Sipariş içerisindeki listinglerin adını iletir
items.merchantSku	Sipariş içerisindeki listinglerin satıcı stok kodu değeridir
items.OrderNumber	Sipariş içerisindeki listinglerin sipariş numarası değeridir
items.orderDate	Siparişin oluşturulma tarihidir
items.quantity	Siparişin içerisindeki kalemlerin adet sayısıdır
items.merchantId	Merchantın uniqueId değeridir. (Test(SIT) ve canlı ortam için merchantId bilgisi hepsiburada.com tarafından iletilecektir.)
Properties	Sipariş içerisindeki ürünlerin varyant özellik değeri bilgileridir.
Siparişin Kargo Firmasının Değiştirilmesi
Bu method Open statüdeki siparişlerin kargo firmalarının değiştirilmesine olanak tanır. Bu alanda sadece değiştirebileceğiniz kargo firmaları listelenir.

İlk olarak Ödemesi tamamlanmış siparişler endpointinden listelediğiniz kalemlere ait lineitemId bilgisini almanız gerekmektedir. Daha sonra listelenen kargo firmaları içerisinde ShortName değeri ile güncelleme işlemini yapabilirsiniz.
Hata Durumları

Hata Kodu	Hata Mesajı
409	Hata:Kargo değişimi yapılamıyor. ( Statusu uygun değildir. ) Openlar üzerinde işlem yapılmaktadır.
Paketli Siparişin Kargo Firmasının Değiştirilmesi
Bu method Open ve Package statüdeki paketlerin kargo firmalarının değiştirilmesine olanak tanır. Bu alanda sadece değiştirebileceğiniz kargo firmaları listelenir.

API, HTTP Basic Auth. ile korunmaktadır, dolayısıyla istemci, kullanıcı adı ve şifreyi HTTP Authorization Header bilgisinde göndermelidir.
İlk olarak packagenumber bilgisine sahip olmanız gerekmektedir. Daha sonra listelenen kargo firmaları içerisinde ShortName değeri ile güncelleme işlemini yapabilirsiniz.
Kargo değişiklğinde paket numarası ve barkod değişikliği olmayacaktır, aynı barkod kullanılmalıdır.
Hata Durumları​

Hata Kodu	Hata Mesajı
409	Hata:Kargo değişimi yapılamıyor. ( Statusu uygun değildir. )
Aynı Pakete Konulabilecek Kalemleri Listeleme
Bu metod aynı müşteriye gidecek olan tek paket içerisine girebilecek kalemleri görebilmenize olanak tanır.

Merchantid (gerekli, guid, b2910839-83b9-4d45-adb6-86bad457edcb) Her satıcının unique bir tanımlayıcısıdır. Lineitemid (gerekli, guid, 52910839-8369-4dg5-adb6-86bad457edcb) Her sipariş kaleminin unique bir tanımlayıcısıdır. (Bknz: Ödemesi Tamamlanmış Siparişleri Listeleme items.id)
Lineitemid (gerekli, guid, 52910839-8369-4dg5-adb6-86bad457edcb) Her sipariş kaleminin unique bir tanımlayıcısıdır. (Bknz: Ödemesi Tamamlanmış Siparişleri Listeleme items.id)
Bir sipariş içerisinde birden fazla kalem olabilir. Gömlek, pantolon ve ayakkabı aynı sipariş içerisinde ise her biri tek bir kalem olarak değerlendirilir. Url içerisindeki lineitemid alanına karşılık gelmektedir. Bu bilgiye ödemesi tamamlanmış siparişler endpointinde bulunan items.id alanından ulaşabilirsiniz.
Url içerisinde göndermiş olduğunuz items.id değeri response içerisinde bir daha sizlere dönmemektedir. Bu nedenle url içerisindeki items.id değerininde paketlerken kullanılması ve başta quantity değerinin alınması gerekmektedir.
Aynı Pakete Konulabilecek Kalemleri Listeleme enpointinden sonraki adım olan Kalem veya Kalemleri Paketleme enpointidir.
Beraber paketlenebilecek kalem bulunmadığı durumda 404 Not Found dönecektir.
İstekte gönderilen lineitemid open statüsünde değilse hata mesajı 409 Conflict dönecektir. Mesaj: Bu ürün paketlenemez.(line item:{lineitemid} can NOT be packaged!!!)
Alan Açıklamaları

Alan Adı	Açıklama
lineItems.orderNumber	İlgili kalemin sipariş numarasıdır
lineItems.lineItemId	İlgili kalemin unique değeridir
lineItems.quantity	İlgili kalemin adet değeridir
Hata Durumları

Hata Kodu	Hata Mesajı
400	Bad Request: URL içerisindeki parametreleri kontrol edin.
401	Unauthorized: Password ve şifre hatalı girilmiştir. Lütfen kontrol ediniz.
404	Not Found: Paketlenecek başka bir ürün bulunamamıştır. URL içerisindeki Mevcut lineitemid ile paketlemeyi yapabilirsiniz.
405	Not Allowed: Http Protokol hatası. Lütfen kontrol ediniz.
500	Internal Server: İstek bilgilerini body ile kontrol etmenizi öneririz. Hata tekrarlı devam ederse ticket ileterek entegrasyon ekibi ile iletişime geçiniz.
Kalem veya Kalemleri Paketleme
Bu metod kalem veya kalemleri paketlemenize olanak tanır.

Merchantid (gerekli, guid, b2910839-83b9-4d45-adb6-86bad457edcb) Her satıcının unique bir tanımlayıcısıdır.
LineitemId(gerekli, guid, 32910839-83b9-4545-adb6-76dad457edc4) Paket içerisinde gönderilecek olan kalem.
Quantity (gerekli, int, 2) Paket içerisinde bulunan kalemin adet sayısı.
Sipariş üzerinde bir adres değişikliği yapıldıysa adres değişikliği süreci tamamlanana kadar “Order has an ongoing change address demand” hatası alınacaktır. Bu hata alındığında berlirli periyotlar ile tekrar paketleme denenmesi gerekmektedir.
Serial number alanı zorunlu değildir. ürüne ait seri numarasınıda geçmek istediğinizde iletebileceğiniz alandır.
Oluşturmuş olduğunuz paket numarası ile Paket Bilgilerini Listeleme endpointinden Kargo Barkod numarasına ulaşabilirsiniz.
Mağaza hesabı modelinde paketlemede kullanılacak bazı sortname bilgileri aşağıdaki gibidir.

Alan Açıklamalar

Alan Adı	Açıklama
lineItemRequests.id	İlgili kalemin unique değeridir
lineItems.quantity	İlgili kalemin adet değeridir
packageNumber	Oluşturduğunuz paketin numarasıdır
parcelQuantity	Paketteki koli adedi ( optional)
deci	Paket deci bilgisi ( optional)
Hara Durumları

400	Bad Request: URL içerisindeki parametreleri kontrol edin.
401	Unauthorized: Password ve şifre hatalı girilmiştir. Lütfen kontrol ediniz.
404	Not Found: URL hatalı gönderilmiştir. Lütfen kontrol ediniz. İstek gönderdiğiniz limeitem.Id ile paketlenebilecek bir lineıtem.Id bulunmamaktadır.
405	Not Allowed: Http Protokol hatası. Lütfen kontrol ediniz.
409	Conflict: İstek gönderdiğiniz lineıtem.Id ile iptal edilmiştir.
500	Internal Server: İstek bilgilerini body ile kontrol etmenizi öneririz. Hata tekrarlı devam ederse ticket ileterek entegrasyon ekibi ile iletişime geçiniz.
Paket Bozma
Bu metod oluşturduğunuz paketleri bozmanıza olanak tanır.

Paket bozulduktan sonra paket içerisindeki kalemler tekrar ödemesi tamamlanmış siparişler end-point’inde listelenmeye başlayacaktır.
Bozulan (Unpack) Paket Bilgilerini Listeleme
Bu metod merchant’ların unpacked olan paketlerini görüntüleyebilmelerini sağlamaktadır.

API, HTTP Basic Auth. ile korunmaktadır, dolayısıyla istemci, kullanıcı adı ve şifreyi HTTP Authorization Header bilgisinde göndermelidir.
Bozulan (Unpack) paket bilgilerini listeleme endpointinde limit – offset yada beginDate – endDate parametreleri kullanarak istek göndermeniz gerekir.
Alan Açıklamaları

Alan Adı	Açıklama
Total Count	Merchant’a ait unpacked olan paketlerin toplam sayısı
Unpacked Date	Paketin bozulma tarihi
Package Number	Paket numarası
Paket Bilgilerini Listeleme
Bu metod satıcıya ait paket bilgilerine ulaşmanıza olanak tanır.Paketlerin open statüsü vardır.Open statüsündeki paket gönderime hazır anlamına gelmektedir.

Paket bilgilerini listeleme endpointinde limit – offset yada beginDate – endDate parametreleri kullanarak istek göndermeniz performans açısından önem arz etmektedir.
Limit, offset, pagecount, totalcount datalarına response header’ından erişim sağlayabilirsiniz.
Begindate, Enddate parametresi 24 saatlik sorgular için geçerlidir. Eğer 24 saatin dışında bir aralık değeri verilirse sistem otomatik olarak Enddate parametresini ignore edecek, Begindate parametresinde girilen değerin üzerine 24 saat ekleyerek işlem yapacaktır. Paket kaybı olmaması adına sadece 24 saatlik aralık değeri girmeniz gerekmektedir.
Limit-offset parametresi kullanırken limit maximum 10 olacak şekilde kullanılmalıdır.
Timespan parametresi ile tek başına gönderimde sadece 24 saat değeri gönderilebilir ve son 24 saati kapsar eski tarihli açık siparişler için 24 saatlik tarih aralığı verileren begindate enddate ile çekilebilir.
Timespan limit offset ile birlikte kullanımda timespan değeri 24 saat’den büyük verilebilir.
Alan Açıklamaları

Alan Adı	Açıklama
id	Siparişin hepsiburada tarafında unique değeridir.
status	Siparişin durumu belirtir
customerId	Müşteri unique id değeridir.
orderDate	Siparişin oluşturulma tarihidir.
dueDate	Siparişin kargoya verilmesi gereken son teslim tarihini belirtir.
barcode	Siparişin kargo barkod numarasıdır.
packageNumber	Paket numarasıdır.
cargoCompany	Siparişin tanımlı kargo firmasının isim bilgisidir.
shippingAddressDetail	Teslimat adresidir.
recipientName	Teslim alacak isim bilgisidir.
shippingCountryCode	Ülke kısaltma bilgisi
shippingDistrict	Teslimat adresinin mahalle bilgisidir.
shippingTown	Teslimat adresinin ilçe bilgisidir.
shippingCity	Teslimat adresinin şehir bilgisidir.
email	Mail bilgisidir.
phoneNumber	Telefon numarasıdır.
companyName	Fatura kesilecek isim/şirket ünvanı
billingAddress	Siparişin fatura adresidir.
billingCity	Fatura adresinin şehir bilgisidir.
billingTown	Fatura adresinin ilçe bilgisidir.
billingDistrict	Fatura adresinin mahalle bilgisidir.
billingPostalCode	Fatura adresinin posta kodu bilgisidir.
taxOffice	Fatura vergi dairesi
taxNumber	Vergi Numarası
identityNo	TC Kimlik numarası
totalPrice.currency	Paket içerisindeki kalemlerin her birinin toplam adet tutarının para birimi cinsinden değeridir.
totalPrice.amount	Paket içerisindeki kalemlerin her birinin toplam adet tutarıdır.
items	Kalemler
lineItemId	Sipariş içerisindeki kalemlerin unique değeridir.
listingId	Listing'in unique id değeridir.
merchantId	Merchantın uniqueId değeridir.
hbSku	Sipariş içerisindeki listinglerin HBSKU değeridir.
merchantSku	Sipariş içerisindeki listinglerin Satıcı stok kodu değeridir.
quantity	Siparişin içerisindeki kalemlerin adet sayısıdır.
price.currency	Para birimi cinsinden değerdir.
price.amount	Paket içindeki tek bir kalemin tutarının değeridir.
vat	KDV tutarıdır.
totalPrice	Paket içindeki kalemlerin her birinin toplam adet tutarıdır.
commission.currency	Hepsiburada.com üzerinden alınan komisyon bedelinin komisyon cinsinden para birimi değeridir.
commission.amount	Hepsiburada.com üzerinden alınan komisyon bedelidir.
commissionRate	Komisyon oranı bilgisidir.
unitHBDiscount.amount	Hepsiburada tarafından uygulanan indirim tutarı
totalHBDiscount.amount	Hepsiburada tarafından uygulanan indirimin toplam tutarı
merchantUnitPrice	Merchant birim satış fiyatı
merchantTotalPrice	Merchantın toplam satış fiyat tutarı
cargoPaymentInfo	Kargo bedeli satıcı mı müşteri mi karşılar bilgisidir.
customizedText01	Özelleştirilebilir ürünün içerik bilgisini verir.
customizedText02	Özelleştirilebilir ürünün içerik bilgisini verir.
customizedText03	Özelleştirilebilir ürünün içerik bilgisini verir.
customerName	Müşterinin adıdır.
properties	Siparişteki kalem'in varyant bilgileridir.(Renk, beden vs.)
productName	Ürün adı bilgisidir.
orderNumber	Sipariş numarası
orderDate	Siparişin oluşturulma tarihidir.
deliveryType	Teslimat türü
customerDelivery	Randevulu siparişler için zaman aralığı
pickupTime	Merchantın kargo firmasına teslim etmesi gereken saat aralığıdır.
weight	Paketin ağırlık bilgisi
gtip	ürünlerin gümrük vergileri için kullanılan koddur.
vatRate	KDV oranıdır.
purchasePrice	Drop çalışan merchantlar için ürünün fiyat bilgisidir.
discountToBeBilledToHB	HB’ye faturalandırılacak indirim (KDV dahil) alanı ifade eder.
productBarcode	SKU'nun EAN barcode bilgisini ifade eder.
unitmerchantDiscount.amount
Merchant tarafından uygulanan birim indirim tutarı
totalmerchantDiscount.amount
Merchant tarafından uygulanan toplam indirim tutarı
deptorDifferenceAmount	satıcı tarafından uygulanan indirim tutarı
isCargoChangable	Kargo değişikliğine uygun ise true değilse false değeri alır
creationReason
Siparişin hangi method ile tekrar yaratıldığını iletmektedir.Yeni Yaratılan : OrderCreated Transfer için : OrderLineTransferred Resend için : OrderLineResend Değişim için : ClaimChangeAccepted Parçalı paketleme : DeliveryCreated
Paket Bölme
Bu metod bir paketin kalem bazlı ayrılarak yeniden paketlenmesine olanak tanır.

Merchantid (gerekli, guid, b2910839-83b9-4d45-adb6-86bad457edcb) Her satıcının unique bir tanımlayıcısıdır.
packagenumber (gerekli, int, 5000031611) Her paketin unique bir tanımlayıcısıdır.
OrderLineId(gerekli, guid, 32910839-83b9-4545-adb6-76dad457edc4) Paket içerisinde gönderilecek olan kalem.
Quantity (gerekli, int, 2) Paket içerisinde bulunan kalemin adet sayısı.
parcelQuantity; Paketteki koli adedi ( optional)
deci;Paket deci bilgisi ( optional)
Pakette boşta kalan kalem veya kalemler varsa tek paket olarak otomatik paketlenir.

Hata Kodları

HataKodu	Hata Mesajı
400
Bad Request: URL içerisindeki parametreleri kontrol edin.
401
Unauthorized: Password ve şifre hatalı girilmiştir. Lütfen kontrol ediniz.
404
Not Found: URL hatalı gönderilmiştir. Lütfen kontrol ediniz. İstek gönderdiğiniz limeitem.Id ile paketlenebilecek bir lineıtem.Id bulunmamaktadır.
405
 Not Allowed: Http Protokol hatası. Lütfen kontrol ediniz.
409
Conflict: İstek gönderdiğiniz lineıtem.Id ile iptal edilmiştir.
500
Internal Server: Lütfen Ticket ileterek entegrasyon ekibi ile iletişime geçiniz.
Paket İçin Kargo Bilgilerini Listeleme
Bu metod bir paketin taşıma durumunu ve kargo takip bilgisine ulaşmanıza olanak tanır.

404 Not Found hatası alındığında cannot find package with package number response dönecektir.
Hata Kodları

Hata Kodu	Hata Mesajı
400
Bad Request: URL içerisindeki parametreleri kontrol edin.
401
Unauthorized: Password ve şifre hatalı girilmiştir. Lütfen kontrol ediniz.
404
Not Found: URL hatalı gönderilmiştir. Lütfen kontrol ediniz.
405
Not Allowed: Http Protokol hatası. Lütfen kontrol ediniz.
500
Internal Server: Lütfen Ticket ileterek entegrasyon ekibi ile iletişime geçiniz.
Alan Açıklamaları

Alan Adı	Açıklama
packageNumber
Oluşturulan paketin numarasıdır.
barcode
Oluşturulan paketin kargo barkodudur.
status
Kargo durumunu belirten alandır. Intransit: Nakil halinde / Delivered: Teslim edildi.
cargoCompany
Paketin teslim edildiği kargo firmasını belirtir.
trackingInfoCode
Paketin kargo takip numarasıdır.
trackingInfoUrl
Paketin kargo takip url bilgisidir.
Siparişe Ait Detay Listeleme
Bu metod bir siparişe ait kalemlerin detaylarını listelemenize olanak tanır.

Ödemesi tamamlanmamış bir sipariş numarası ile istek gönderildiğinde hata mesajı dönecektir. Mesaj: Bu sipariş için sonuç bulunmadı, lütfen siparişin ödeme durumunu kontrol ediniz.
Statü Bilgileri

Status	Açıklama
Open
Açık sipariş.
Packaged
Paketlenmiş sipariş.
CancelledByMerchant
Merchant tarafından iptal edilmiş sipariş.
Delivered
Teslim edilmiş sipariş.
InTransit
Kargoda olan sipariş.
ClaimCreated
Talep açılmış kalem.
CancelledByCustomer
Müşteri tarafından iptal edilmiş sipariş.
CancelledBySap
SAP tarafından iptal edilen sipariş Fraud vb durumlarda oluşur.
Fatura Linki Gönderme
Merchant tarafından kendi sisteminde yaratılmış E-Arşiv fatura bilgisini Hepsiburada sistemine transfer ederek müşteri (hepsiburada.com üzerinden sipariş veren) ile faturanın paylaşılması için bu method kullanılacaktır.
Bu servisin tetiklenmesi için fatura url’inin Content-type’ı “application/pdf” veya “text/html” olmalıdır.

Hata Durumları

Hata Kodu	Hata Mesajı
400
Bad Request: Gönderilen link içeriği pdf formatında değil. Lütfen kontrol ediniz.
403
Forbidden Paket istek gönderilen merchant'a ait değil. Lütfen paket numaranızı kontrol ediniz.
409
Conflict: Pakete ait fatura eklenmiş.
Ortak Barkod Oluşturma
API, HTTP Basic Auth. ile korunmaktadır, dolayısıyla istemci, kullanıcı adı ve şifreyi HTTP Authorization Header bilgisinde göndermelidir.

Ortak barkod ilk aşamada yalnızca HepsiJet ve Aras kargo firmasını desteklemektedir.
Desteklenen çıktı formatları; zpl, base64zpl, pdf, png ve jpg Endpoint’de format=zpl, format=pdf gibi desteklenen formatları ekleyerek ilgili çıktı alınabilir. Convert ederek de görseline ulaşabilirsiniz.
*Hata Durumları

Hata Kodu	Hata Mesajı
101
Barcode veremediği durumda alınır. Kargo firması hatasıdır.
102
Barcode veremediği durumda alınır: "Merchant kargo barkod aktif değil"
400
Cargo company does not provide mutual barcodes
500
Internal error: 3 kere hata alınırsa mevcut etiket yapısı ile devam edilmelidir.
İptal Bilgisi Gönderme
Bu metod merchantların sipariş için iptal bilgisini göndermesine olanak sağlar.
Sadece statüsü open olan siparişler için geçerlidir. Yani bir sipariş paketlenirse bu endpoint kullanılamaz. Eğer siparişin paketi var ise önce paket bozulup daha sonra bu endpoint çağırılmalıdır.

IPTAL CEZA KOŞULLARI
Sipariş iptali yapmanız halinde, ürünün satışını yapan farklı bir mağaza varsa sipariş yeni satıcıya transfer edilerek aradaki fiyat farkı ve sözleşmenizde bulunan ceza tutarı mağazanıza fatura edilecektir.

Ürün satışını yapan alternatif bir mağaza yoksa sözleşmenizde yer alan tutarlarda tarafınıza ceza faturası yansıtılacak ve ürün satışa kilitlenecektir.
Müşteri memnuniyetini üst seviyede tutmak için stok ve fiyat takibi konusunda hassasiyet göstermenizi önemle rica ederiz.
Bu endpoint için günlük limit 100’dür.
Ürün Bedeli	Faturalandırılacak Tutar
0-50 TL	10 TL
50,01-100 TL	30 TL
100,01-200 TL	50 TL
200,01-1000 TL	100 TL
1000,01-3000 TL	300 TL
3000,01-6000 TL	600 TL
6000,01-10000 TL	1000 TL
10000,01-20000 TL	1500 TL
20000,01 TL ve Üzeri	2000 TL
Hata Durumları

Hata Kodu	Hata Mesajı
400	Bad Request: URL içerisindeki parametreleri kontrol edin.
401	Unauthorized: Password ve şifre hatalı girilmiştir. Lütfen kontrol ediniz.
404	Not Found: URL hatalı gönderilmiştir. Lütfen kontrol ediniz.
405	Not Allowed: Http Protokol hatası. Lütfen kontrol ediniz.
406	Not Acceptable: Günlük limiti aştınız.
409	Conflict: Kalem iptal edilmiş yada statüsü iptale uygun değildir.
500	Internal Server: İstek bilgilerini body ile kontrol etmenizi öneririz. Hata tekrarlı devam ederse ticket ileterek entegrasyon ekibi ile iletişime geçiniz.
Digital Kod Bilgisi Gönderimi
Delivered Status (Teslim Edildi Statüsüne Alma)

Dijital kod satışı yapıldığında Kodların son kullanıcıya merchant tarafından gönderimi sağlanır ve sipariş teslim edildiğinde deliver end-pointi üzerinden teslim edildi statüsüne çekilmesi gerekmektedir.
Otomatik paketleme kullanılıyor yada kullanılacak ise sipariş içerisindeki kalemlerin “Kalem bazında kargoya hazırlansın” şeklinde otopack’in aktif ettirilmesi gerekir.
API ile paketleme uygulanıyor ise yine kalem bazlı paketleme yapılmalı birden fazla kalem tek paket’e eklenmemelidir.
Digital kategoride bu endpoint’i kullanabilmek için merchantların ek olarak deliver yetkisi istemesi gerekir. Bunun için merchant panel’den aşagıdaki kırılımdan kayıt açılması gerekir.
Örnek Body Format

ONE PIN   package sample : 

{
 "receivedDate": "2020-05-10T11:30:30.230Z",
 "receivedBy": "string",
 "digitalCodes": ["string"]
}

MULTİPLE PIN package sample : 

{
 "receivedDate": "2020-05-10T11:30:30.230Z",
 "receivedBy": "string",
 "digitalCodes": ["xyz123", "t468", "8513", "zyxdfg",]
}


Alan Adı

Alan Adı	Açıklama
receivedDate	Paketin teslim tarihi
receivedBy	Paketin teslim edildiği kişi bilgisi
digitalCodes	Müşteriye gönderilen dijital kod'un bilgisi
Dijital Ürünler kategorisine ait kategori bilgileri aşağıdaki gibidir.

No	Ana Kategori	Alt Kategori
1	Bilgisayar	Online Lisanslar
2	Game	Dijital Oyunlar
3	Game	Dijital Ürünler
4	Kitap	Oyun Pinleri
5	Kitap	Film, Dizi, Yayın Paketleri
6	Kitap	Online Eğitimler
7	Kitap	Dijital Oyunlar
8	Kitap	Online Mimarlık Hizmeti
9	Kitap	Fırsat Menüleri
10	Kitap	Akaryakıt ve Oto Paketleri
11	Kitap	E-Kitaplar
12	Kitap	Hediye Kartları
13	Kitap	Dijital Dergi
14	Kitap	Etkinlik, Aktivite
15	Kitap	Online Lisanslar
16	Kitap	Sesli Kitap
17	Kitap	Dijital Ürünler
İptal Sipariş Bilgileri Listeleme
Bu metod satıcıya ait iptal edilen sipariş ve kalem bilgilerine ulaşmanıza olanak tanır. Servisten sadece son 1 aylık dataya erişilebilir.

İptal sipariş bilgilerini listeleme endpointinde limit – offset yada beginDate – endDate parametreleri kullanarak istek göndermeniz gerekir.
Servisten sadece son 1 aylık dataya erişilebilir.
Limit, offset, pagecount, totalcount datalarına response bilgisinden erişim sağlayabilirsiniz.
Limit-offset parametresi kullanırken limit maximum 50 olacak şekilde kullanılabilir.
Alan Açıklamaları

Alan Adı	Açıklama
orderNumber
Siparişin unique numarasıdır.
lineItemId
Siparişin kaleminin unique ID bilgisidir.
cancelDate
Siparişin iptal edilme tarihidir.
cancelledBy
Siparişin kimin tarafından iptal edildiğinin bilgisini iletir. Alabileceği statüler : Merchant, Customer
cancelReasonCode
Sipariş iptal nedenidir.
merchantId
İptal edilen siparişin hangi merchanta ait olduğunu gösteren merchantıd bilgisidir.
quantity
Siparişin iptal edilen kaleminin kaç adet olduğunu belirtir.
sku
İptal edilen kalemin hepsiburada sku bilgisidir.
merchantSku
İptal edilen kalemin satıcı stok kodu  bilgisidir.
Teslim Edilemedi Siparişlerin Listelenmesi
Bu metod satıcıya ait kargodan teslim edilemeyen sipariş bilgilerine ulaşmanıza olanak tanır.Servisten sadece son 1 aylık dataya erişilebilir.

Teslim Edilemedi Siparişlerin Listelenmesi endpointinde limit – offset yada beginDate – endDate parametreleri kullanarak istek göndermeniz gerekir.
Servisten sadece son 1 aylık dataya erişilebilir.
Limit, offset, pagecount, totalcount datalarına response bilgisinden erişim sağlayabilirsiniz.
Limit-offset parametresi kullanırken limit maximum 50 olacak şekilde kullanılabilir.
Alan Açıklamaları
Alan Adı	Açıklama
orderNumber
Siparişin unique numarasıdır.
Id
Teslimatın unique ID bilgisidir.
UndeliveredDate
Siparişin teslim edilememe tarihidir.
UndeliveredReason
Teslim edilememe nedeni.
Barcode
Siparişin kargo barkod numarasıdır.
merchantId
Teslim edilemeyen siparişin hangi merchanta ait olduğunu gösteren merchantıd bilgisidir.
PackageNumber
Siparişin paket numarasıdır.
Teslim Edilen Siparişlerin Listelenmesi
Bu metod satıcıya ait kargodan müşteriye teslim edilen sipariş bilgilerine ulaşmanıza olanak tanır. Servisten sadece son 1 aylık dataya erişilebilir.

Teslim Edilen Siparişlerin Listelenmesi endpointinde limit – offset yada beginDate – endDate parametreleri kullanarak istek göndermeniz gerekir.
Servisten sadece son 1 aylık dataya erişilebilir. Eski tarihliler çekilemez.
Limit, offset, pagecount, totalcount datalarına response bilgisinden erişim sağlayabilirsiniz.
Limit-offset parametresi kullanırken limit maximum 50 olacak şekilde kullanılabilir.
Alan Açıklamaları
Alan Adı	Açıklama
orderNumber
Siparişin unique numarasıdır.
Id
Teslimatın unique ID bilgisidir.
PackageNumber
Siparişin paket numarasıdır.
Barcode
Siparişin kargo barkod numarasıdır.
merchantId
Teslim edilemeyen siparişin hangi merchanta ait olduğunu gösteren merchantıd bilgisidir.
DeliveredDate
Paketin teslim edildiği tarih bilgisidir.
Kargoya Verilen Siparişlerin Listelenmesi
Bu metot, satıcıların kargoda adımında bulunan sipariş bilgilerine erişimini sağlamak amacıyla geliştirilmiştir.Servisten sadece son 1 aylık dataya erişilebilir. <br

Kargoya Verilen Siparişlerin Listelenmesi endpointinde limit – offset yada beginDate – endDate parametreleri kullanarak istek göndermeniz gerekir.
Servisten sadece son 1 aylık dataya erişilebilir. Eski tarihliler çekilemez.
Limit, offset, pagecount, totalcount datalarına response bilgisinden erişim sağlayabilirsiniz.
Limit-offset parametresi kullanırken limit maximum 50 olacak şekilde kullanılabilir.
Alan Açıklamaları

Alan Adı	Açıklama
orderNumber
Siparişin unique numarasıdır.
Id
Teslimatın unique ID bilgisidir.
PackageNumber
Siparişin paket numarasıdır.
Barcode
Siparişin kargo barkod numarasıdır.
merchantId
Kargoya teslim edilen siparişin hangi merchanta ait olduğunu gösteren merchantıd bilgisidir.
ShippedDate
Paketin kargoya teslim edildiği tarih bilgisidir.
Deci
Paketin desi bilgisini listeler.


Test siparisi olusturma
post
https://oms-stub-external-sit.hepsiburada.com/orders/merchantId/{merchantId}


Bu servis belirtilen satıcı için test siparişi oluşturulmasını sağlar

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Satıcının unique Id değeridir

Body Params
Oluşturulmak istenen sipariş bilgileridir

Customer
object
Müşteri bilgileri


Customer object
DeliveryAddress
object
Teslimat adresi


DeliveryAddress object
LineItems
array of objects
Siparişteki kalem listesi


ADD object
OrderDate
string
Siparişin oluşturulma tarihi

OrderNumber
string
Sipariş numarası

PaymentStatus
string
Siparişin ödeme durumu

Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

200
OK

Response body
string

400
Bad Request


401
Unauthorized


500
Internal Server Error



import requests

url = "https://oms-stub-external-sit.hepsiburada.com/orders/merchantId/merchantId"

payload = {
    "Customer": {
        "CustomerId": "dfc8a27f-faae-4cb2-859c-8a7d50ee77be",
        "Name": "Test User"
    },
    "DeliveryAddress": {
        "AddressDetail": "Trump Towers",
        "AddressId": "e66765b3-d37d-488c-ae15-47051245dc9b",
        "AlternatePhoneNumber": "045321538212",
        "City": "İstanbul",
        "CountryCode": "TR",
        "District": "Kustepe",
        "Email": "customer@hepsiburada.com.tr",
        "Name": "Hepsiburada Office",
        "PhoneNumber": "902822613231"
    }
}
headers = {
    "accept": "application/json",
    "content-type": "application/json"
}

response = requests.post(url, json=payload, headers=headers)

print(response.text)


Odemesi Tamamlanmis Siparisleri Listeleme
get
https://oms-external-sit.hepsiburada.com/orders/merchantid/{merchantId}


Bu servis, belirli bir satıcıya (merchantId) ait ve sipariş alındı statüsündeki kalemleri listelemek için kullanılır

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Satıcının unique Id değeridir

Query Params
begindate
string
Girilen tarihten itibaren eklenen kalemler esas alınır

enddate
string
Girilen tarihten önce eklenmiş kalemler esas alınır

offset
string
Başlangıçtan belirtilen değer kadar kaydı atlar. Offset: 20, limit: 10 girildiğinde, ilk 20 kaydı atlar ve 21. kayıttan başlayarak 10 kayıt listeler

limit
string
Girilen değer kadar kalem listelenir, ancak en fazla ve varsayılan olarak 100 adet gösterilir. Limit değeri girilmediğinde hata oluşacaktır.

Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

200
OK


400
Bad Request


401
Unauthorized


500
Internal Server Error



import requests

url = "https://oms-external-sit.hepsiburada.com/orders/merchantid/merchantId"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)


Iptal Siparis Bilgileri Listeleme
get
https://oms-external-sit.hepsiburada.com/orders/merchantid/{merchantId}/cancelled


Bu servis, belirli bir satıcıya (merchantId) ait iptal edilmiş siparişleri listelemek için kullanılır

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Listelenmek istenen kalemlerin satıcısının unique Id değeridir

Query Params
begindate
string
Girilen tarihten itibaren iptal olmuş kalemler esas alınır

enddate
string
Girilen tarihten önce iptal olmuş kalemler esas alınır

offset
string
Başlangıçtan belirtilen değer kadar kaydı atlar. Offset: 20, limit: 10 girildiğinde, ilk 20 kaydı atlar ve 21. kayıttan başlayarak 10 kayıt listeler

limit
string
Girilen değer kadar kalem listelenir, ancak en fazla ve varsayılan olarak 50 adet gösterilir

Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

200
OK


400
Bad Request


401
Unauthorized


500
Internal Server Error



import requests

url = "https://oms-external-sit.hepsiburada.com/orders/merchantid/merchantId/cancelled"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

Odemesi Beklenen Siparisleri Listeleme
get
https://oms-external-sit.hepsiburada.com/orders/merchantid/{merchantId}/paymentawaiting


Bu servis, belirli bir satıcıya (merchantId) ait ödemesi beklenen siparişleri listelemek için kullanılır

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Listelenmek istenen kalemlerin satıcısının unique Id değeridir

Query Params
begindate
string
Girilen tarihten itibaren siparişin oluşturulma tarihi esas alınır

enddate
string
Girilen tarihten önce oluşturulmuş sipariş esas alınır

offset
string
Başlangıçtan belirtilen değer kadar kaydı atlar. Offset: 20, limit: 10 girildiğinde, ilk 20 kaydı atlar ve 21. kayıttan başlayarak 10 kayıt listeler

limit
string
Girilen değer kadar kalem listelenir, ancak en fazla ve varsayılan olarak 50 adet gösterilir. Limit değeri 1' den küçük olduğunda hata oluşacaktır

Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

200
OK


400
Bad Request


401
Unauthorized


500
Internal Server Error

import requests

url = "https://oms-external-sit.hepsiburada.com/orders/merchantid/merchantId/paymentawaiting"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

Teslim Edilen Siparislerin Listelenmesi
get
https://oms-external-sit.hepsiburada.com/packages/merchantid/{merchantId}/delivered


Bu servis, belirli bir satıcıya (merchantId) ait teslim edilmiş paketleri listelemek için kullanılır

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Listelenmek istenen paketlerin satıcısının unique Id değeridir

Query Params
begindate
string
Girilen tarihten itibaren teslim olmuş paketler esas alınır

enddate
string
Girilen tarihten önce teslim olmuş paketler esas alınır

offset
string
Başlangıçtan belirtilen değer kadar kaydı atlar. Offset: 20, limit: 10 girildiğinde, ilk 20 kaydı atlar ve 21. kayıttan başlayarak 10 kayıt listeler

limit
string
Girilen değer kadar paket listelenir, ancak en fazla ve varsayılan olarak 50 adet gösterilir

Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

200
OK


400
Bad Request


401
Unauthorized


500
Internal Server Error

import requests

url = "https://oms-external-sit.hepsiburada.com/packages/merchantid/merchantId/delivered"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

Kargoya Verilen Siparislerin Listelenmesi
get
https://oms-external-sit.hepsiburada.com/packages/merchantid/{merchantId}/shipped


Bu servis, belirli bir satıcıya (merchantId) ait kargoya verilen paketleri listelemek için kullanılır

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Listelenmek istenen paketlerin satıcısının unique Id değeridir

Query Params
begindate
string
Girilen tarihten itibaren kargoya teslim edilmiş paketler esas alınır

enddate
string
Girilen tarihten önce kargoya teslim edilmiş paketler esas alınır

offset
string
Başlangıçtan belirtilen değer kadar kaydı atlar. Offset: 20, limit: 10 girildiğinde, ilk 20 kaydı atlar ve 21. kayıttan başlayarak 10 kayıt listeler

limit
string
Girilen değer kadar paket listelenir, ancak en fazla ve varsayılan olarak 50 adet gösterilir

Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

200
OK


400
Bad Request


401
Unauthorized


500
Internal Server Error


import requests

url = "https://oms-external-sit.hepsiburada.com/packages/merchantid/merchantId/shipped"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

Faturası Yüklenmemiş Siparişlerin Listelenmesi
get
https://oms-external-sit.hepsiburada.com/packages/merchantid/{merchantId}/missing-invoice


Bu servis, belirli bir satıcıya (merchantId) ait faturası sisteme yüklenmemiş tüm paketleri listelemek için kullanılır.

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Listelenmek istenen paketlerin satıcısının unique Id değeridir

Query Params
offset
string
Başlangıçtan belirtilen değer kadar kaydı atlar

limit
string
Girilen değer kadar paket listelenir, ancak en fazla ve varsayılan olarak 50 adet gösterilir

Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

200
OK


400
Bad Request


401
Unauthorized


500
Internal Server Error

import requests

url = "https://oms-external-sit.hepsiburada.com/packages/merchantid/merchantId/missing-invoice"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

Bozulan (Unpack) Paket Bilgilerini Listeleme
get
https://oms-external-sit.hepsiburada.com/packages/merchantid/{merchantId}/status/unpacked


Bu servis, belirli bir satıcıya (merchantId) ait bozulan paketlerin bilgilerini listelemek için kullanılır

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Listelenmek istenen paketlerin satıcısının unique Id değeridir

Query Params
limit
string
Girilen değer kadar paket listelenir, ancak en fazla ve varsayılan olarak 10 paket gösterilir. 1'den küçük bir değer girilirse hata alınır

Offset
string
Başlangıçtan belirtilen değer kadar kaydı atlar. Offset: 20, limit: 10 girildiğinde, ilk 20 kaydı atlar ve 21. kayıttan başlayarak 10 kayıt listeler

begindate
string
Girilen tarihten itibaren Unpack olmuş paketler esas alınır

enddate
string
Girilen tarihten önce Unpack olmuş paketler esas alınır

timespan
string
Bugünün tarihinden girilen değer kadar saat geri gidilerek, o zaman aralığındaki Unpack olmuş paketler listelenir. Örneğin, 12 değeri girildiğinde son 12 saat içindeki paketler getirilir

Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

200
OK


400
Bad Request


401
Unauthorized


500
Internal Server Error

import requests

url = "https://oms-external-sit.hepsiburada.com/packages/merchantid/merchantId/status/unpacked"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)


Teslim Edilemedi Siparislerin Listelenmesi
get
https://oms-external-sit.hepsiburada.com/packages/merchantid/{merchantId}/undelivered


Bu servis, belirli bir satıcıya (merchantId) ait teslim edilememiş paketlerin bilgilerini listelemek için kullanılır

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Listelenmek istenen paketlerin satıcısının unique Id değeridir

Query Params
begindate
string
Girilen tarihten itibaren teslim edilememiş paketler esas alınır

enddate
string
Girilen tarihten önce teslim edilememiş paketler esas alınır

offset
string
Başlangıçtan belirtilen değer kadar kaydı atlar. Offset: 20, limit: 10 girildiğinde, ilk 20 kaydı atlar ve 21. kayıttan başlayarak 10 kayıt listeler

limit
string
Girilen değer kadar paket listelenir, ancak en fazla ve varsayılan olarak 50 adet gösterilir

Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

200
OK


400
Bad Request


401
Unauthorized


500
Internal Server Error


import requests

url = "https://oms-external-sit.hepsiburada.com/packages/merchantid/merchantId/undelivered"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

Paketlenecek Siparisin Hangi Kargo Firmasi Ile Degistirilebilecegini Listeleme
get
https://oms-external-sit.hepsiburada.com/delivery/changeablecargocompanies/merchantid/{merchantId}/orderlineid/{orderLineId}


Bu servis, belirli bir satıcıya (merchantId) ait ve paketlenmesi planlanan bir siparişi kalemi (orderLineId) için, hangi kargo firmalarıyla gönderim yapılabileceğini listelemek amacıyla kullanılır

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Paketlenecek kalemin hangi satıcıya ait olduğunu belirten bilgidir

orderLineId
string
required
Paketlenecek kalemin unique Id değeridir

Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

200
OK


400
Bad Request


401
Unauthorized


500
Internal Server Error

import requests

url = "https://oms-external-sit.hepsiburada.com/delivery/changeablecargocompanies/merchantid/merchantId/orderlineid/orderLineId"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

Paketlenecek Siparisin Kargo Firmasini Degistirme
put
https://oms-external-sit.hepsiburada.com/lineitems/merchantid/{merchantId}/orderlineid/{id}/cargocompany


Bu servis, belirli bir satıcıya (merchantId) ait bir sipariş kalemi (id) için kargo firmasını değiştirmek amacıyla kullanılır

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Paketlenecek kalemin hangi satıcıya ait olduğunu belirten bilgidir

id
string
required
Paketlenecek kalemin unique Id değeridir

Body Params
Seçilen kargo firmasının kısa isim bilgisidir

CargoCompanyShortName
string
Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

204
No Content


400
Bad Request


401
Unauthorized


500
Internal Server Error



import requests

url = "https://oms-external-sit.hepsiburada.com/lineitems/merchantid/merchantId/orderlineid/id/cargocompany"

headers = {
    "accept": "application/json",
    "content-type": "application/json"
}

response = requests.put(url, headers=headers)

print(response.text)

Paketli Siparisin Hangi Kargo Firmasi Ile Degistirilebilecegini Listeleme
get
https://oms-external-sit.hepsiburada.com/packages/merchantid/{merchantId}/packagenumber/{packageNumber}/changablecargocompanies


Bu servis, belirli bir satıcıya (merchantId) ait ve paketleme işlemi tamamlanmış bir siparişin hangi kargo firmaları ile gönderilebileceğini listelemek amacıyla kullanılır

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
packageNumber
string
required
Paket numarasıdır

merchantId
string
required
Paketin hangi satıcıya ait olduğunu belirten bilgidir

Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

200
OK


400
Bad Request


404
Not Found

import requests

url = "https://oms-external-sit.hepsiburada.com/packages/merchantid/merchantId/packagenumber/packageNumber/changablecargocompanies"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

Paketli Siparisin Kargo Firmasini Degistirme
put
https://oms-external-sit.hepsiburada.com/packages/merchantid/{merchantId}/packagenumber/{packageNumber}/changecargocompany


Bu servis, belirli bir satıcıya (merchantId) ait ve paketlenmiş bir siparişin kargo firmasını değiştirmek için kullanılır

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Paketin hangi satıcıya ait olduğunu belirten bilgidir

packageNumber
string
required
Paket numarasıdır

Body Params
Seçilen kargo firmasının kısa isim bilgisidir

CargoCompanyShortName
string
Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

204
No Content


400
Bad Request


401
Unauthorized


500
Internal Server Error

import requests

url = "https://oms-external-sit.hepsiburada.com/packages/merchantid/merchantId/packagenumber/packageNumber/changecargocompany"

headers = {
    "accept": "application/json",
    "content-type": "application/json"
}

response = requests.put(url, headers=headers)

print(response.text)

Siparise Ait Detay Listeleme
get
https://oms-external-sit.hepsiburada.com/orders/merchantid/{merchantId}/ordernumber/{orderNumber}


Bu servis, belirli bir sipariş numarasına ait detaylı bilgileri listelemek için kullanılır

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Satıcının unique Id değeridir

orderNumber
string
required
Sipariş numarası

Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

200
OK


400
Bad Request


401
Unauthorized


500
Internal Server Error

import requests

url = "https://oms-external-sit.hepsiburada.com/orders/merchantid/merchantId/ordernumber/orderNumber"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)


Iptal Bilgisi Gonderme
post
https://oms-external-sit.hepsiburada.com/lineitems/merchantid/{merchantId}/id/{lineId}/cancelbymerchant


Bu servis, belirli bir satıcıya (merchantId) ait ve henüz paketlenmemiş bir sipariş kaleminin (lineId) iptal edilmesi için kullanılır

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Siparişin hangi satıcıya ait olduğunu belirten bilgidir

lineId
string
required
İptal edilmek istenen, henüz paketlenmemiş kalemin unique Id değeridir

Body Params
Satıcı iptal kodu

reasonId
integer
Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

200
OK


400
Bad Request


401
Unauthorized


500
Internal Server Error



import requests

url = "https://oms-external-sit.hepsiburada.com/lineitems/merchantid/merchantId/id/lineId/cancelbymerchant"

headers = {
    "accept": "application/json",
    "content-type": "application/json"
}

response = requests.post(url, headers=headers)

print(response.text)

Siparis Kalemi Iscilik Maliyeti Guncelleme
put
https://oms-external-sit.hepsiburada.com/lineitems/merchantid/{merchantId}/orderlineid/{id}/laborcost


Bu servis, belirli bir satıcıya (merchantId) ait bir sipariş kalemi (id) için işçilik maliyetini güncellemek amacıyla kullanılır (sadece altın ürünler için geçerlidir)

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Paketlenecek kalemin hangi satıcıya ait olduğunu belirten bilgidir

id
string
required
İşçilik maliyeti güncelenecek kalemin unique Id değeridir

Body Params
Birim işçilik maliyeti

unitLaborCost
number
Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

204
No Content


400
Bad Request


401
Unauthorized


500
Internal Server Error

import requests

url = "https://oms-external-sit.hepsiburada.com/lineitems/merchantid/merchantId/orderlineid/id/laborcost"

headers = {
    "accept": "application/json",
    "content-type": "application/json"
}

response = requests.put(url, headers=headers)

print(response.text)

Teslimat Statusu Iletme (Teslim Edildi)
post
https://oms-external-sit.hepsiburada.com/packages/merchantid/{merchantId}/packagenumber/{packagenumber}/deliver


Bu servis, belirli bir paket numarası (packagenumber) için teslimat durumunu teslim edildi olarak güncellemek amacıyla kullanılır

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Satıcının unique Id değeridir

packagenumber
string
required
Paket numarasıdır

Body Params
Teslimat bilgisi (Teslim Edildi)

digitalCodes
array of strings
Dijital ürün kodları


ADD string
receivedBy
string
Paketi teslim alacak kişi

receivedDate
string
Paketin teslim edilme tarihi

Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

200
OK


400
Bad Request


401
Unauthorized


404
Not Found


500
Internal Server Error

import requests

url = "https://oms-external-sit.hepsiburada.com/packages/merchantid/merchantId/packagenumber/packagenumber/deliver"

headers = {
    "accept": "application/json",
    "content-type": "application/json"
}

response = requests.post(url, headers=headers)

print(response.text)

Teslimat Statusu Iletme(Kargoda)
post
https://oms-external-sit.hepsiburada.com/packages/merchantid/{merchantId}/packagenumber/{packagenumber}/intransit


Bu servis, belirli bir paket numarası (packagenumber) için teslimat durumunu kargoda olarak güncellemek amacıyla kullanılır

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Paketin satıcısının unique Id değeridir

packagenumber
string
required
Paket numarasıdır

Body Params
Teslimat bilgisidir (Kargoya verildi)

cost
number
Gönderim ücreti

deci
number
Paketin hacimsel ağırlığı

estimatedArrivalDate
string
Paketin tahmini varış tarihi

shippedDate
string
Paketin kargoya verilme tarihi

tax
number
Paketin KDV'si

trackingNumber
string
Kargo takip numarası

trackingPhoneNumber
string
Kargo takip telefon numarası

trackingUrl
string
Kargonun takibi için URL bilgisi

Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

200
OK


400
Bad Request


401
Unauthorized


404
Not Found


500
Internal Server Error

import requests

url = "https://oms-external-sit.hepsiburada.com/packages/merchantid/merchantId/packagenumber/packagenumber/intransit"

headers = {
    "accept": "application/json",
    "content-type": "application/json"
}

response = requests.post(url, headers=headers)

print(response.text)

Teslimat Statusu Iletme(Teslim Edilemedi)
post
https://oms-external-sit.hepsiburada.com/packages/merchantid/{merchantId}/packagenumber/{packagenumber}/undeliver


Bu servis, belirli bir paket numarası (packagenumber) için teslimat durumunu teslim edilemedi olarak güncellemek amacıyla kullanılır

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
string
required
Paketin satıcısının unique Id değeridir

packagenumber
string
required
Paket numarasıdır

Body Params
Teslimat bilgisidir (Teslim Edilemedi)

undeliveredDate
string
Paketin teslim edilememe tarihi

undeliveredReason
string
Paketin teslim edilememe nedeni

Headers
User-Agent
string
required
İsteği yapan client'ın bilgilerini içerir

Responses

200
OK


400
Bad Request


401
Unauthorized


404
Not Found


500
Internal Server Error

import requests

url = "https://oms-external-sit.hepsiburada.com/packages/merchantid/merchantId/packagenumber/packagenumber/undeliver"

headers = {
    "accept": "application/json",
    "content-type": "application/json"
}

response = requests.post(url, headers=headers)

print(response.text)

Muhasebe Önemli Bilgiler
Servis, ödeme ve faturaları listelemenize olanak tanır.

👍
Önemli Bilgiler

Bu dokümanda yer alan endpoint url'leri test ortamına aittir. Dokumanda sayfasında test ortam endpointleri test edilebilir. Canlı ortam url'leri endpoint içinde "-sit" ifadesi kaldırılarak oluşturabilirsiniz. Canlı ortam endpoint'ine canlı ortam için verilen User/Password ile istek gönderilebilir.

📘
Hepsiburada API Authentication Bilgilendirmesi

Mevcuttaki tüm servislerimizin authentication yapısında değişiklik yapılmıştır. Sizlerden servislerimizdeki bu değişikliğin hızla yapılması noktasında desteğinizi rica ederiz.

Entegratöre Servis Anahtarı Ekleme/Görüntüleme işlemleri için hazırladığımız sayfamızı inceleyebilirsiniz.

Finansal kayıtlarınız sipariş teslim edildikten sonra oluşmaktadır.

Merchantid = Zorunludur, Her satıcının unique bir tanımlayıcısıdır.
transactionTypes= Opsiyoneldir, kayıt tiplerini belirtir. Bu parametre verilmediğinde tüm kayıt tipleri listelenecektir. Spesifik tipler bakılmak istenirse sorgulanacak tipler virgülle ayrılarak yazılabilir. Örnek; transactiontypes=Commission, Payment
recordDateStart - recordDateEnd
dueDateStart - dueDateEnd
orderDateStart - orderDateEnd
paymentDateStart – paymentDateEnd
4 tarih aralığı parametresinden biri girilmek zorundadır. Bir tanesi girildikten sonra kalanlar opsiyonel eklenebilir. orderNumber, packageNumber, sku, invoiceNumber arametrelerinden en az biri verilirse tarih parametreleri zorunlu olmayacaktır.
offset/limit = Girişi zorunludur. Offset, kaçıncı kayıttan itibaren gösterileceğini verir. Limit, servisten kaç tane kayıt döneceğini belirler. Limit en fazla 100 olabilir.
Örnek; Kayıtlar yüzer yüzer çekildiğinde yani limiti 100 belirlendiğinde, 3. sayfayı göstermek için offset=200&limit=100 girilecektir.
status = Opsiyoneldir. İlgili kaydın ödeme statüsünü belirtir.
Örnek; status=Paid
Paid : Ödenenler
WillBePaid : Henüz ödenmeyenleri belirtir.
orderNumber = Opsiyoneldir. Sipariş numarası olarak geçer.
Örnek; orderNumber=0019531668
packageNumber = Opsiyoneldir. Paket numarası
Örnek; packageNumber=0019531668
sku = Opsiyoneldir. Ürün Hepsiburada numarasıdır.
Örnek; sku=HBV0000058C3H
ReferenceDocument = Opsiyoneldir. Kayıt ya da Fatura numarasına karşılık gelir.
Örnek; ReferenceDocument=HD12018000104453
transactionTypes parametresi “InvoiceTransactions“ olarak beslendiğinde yalnızca faturalar için listeleme yapılacaktır.
IsInvoice : Bu alan ilgili kaydın fatura mı değil mi bilgisini döner. True döndüğü durumda kaydın fatura olduğu anlaşılır. False döndüğü durumda kaydın fatura tipinde olmadığı anlaşılır.
IsIncome : Bu alan ilgili kaydın gelir mi gider mi bilgisini döner. True döndüğü durumda geliri ifade eder, false döndüğü durumda gideri ifade eder.
currencyCode	Açıklama
949	TRY
840	USD
Birden fazla currency ile sonuç dönmesi durumunda 409 uyarısı ve uyarı mesajı olarak aşagıdaki response dönecektir;

ErrorMessage: More than one currencies exist in the results. MerchantId : {merchant.SapId}. Merchant Name : {merchant.Name}

ExceptionCode: MoreThanOneCurrenciesExistInTheResults

Kayıt Tipi Bilgileri

Transaction Type	Açıklama	Detay Bilgi
Payment	Sipariş tutarı	Siparişe ait ürünün satış tutarını ifade etmektedir.
DeliveryProcessingFee	İşlem Bedeli	Her bir teslimat başına alınan işlem bedelidir.
DeliveryProcessingFeeRefund	İşlem Bedeli İadesi	Her bir teslimat başına alınan işlem bedelinin iadesidir.
Return	İade tutarı	İade edilen sipariş tutarlarını ifade etmektedir.
Commission	Komisyon tutarı	Siparişe ait komisyon faturalarını ifade etmektedir.
CommissionInvoiceRefund	Komisyon iadesi	Hepsiburada'ya düzenlediğiniz komisyon iade faturaları ile iadesi onaylanan siparişlerinizde, mağazanıza geri ödenen komisyon tutarlarını gösterir.
CommissionRefund	Komisyon iade tutarı	Siparişe ait iade edilen komisyon faturalarını ifade etmektedir.
CommissionCorrection	Komisyon düzeltme	Komisyon faturalarında KDV farkından dolayı tarafınıza yapılan fazla ödeme için düzenlenen istek tipini ifade etmektedir.
ShipmentCostSharingExpense	Kargo katkı payı gideri	Hepsiburada anlaşmalı kargo desi/fiyat tablosuna ve kampanya süreçlerine göre düzenlenen kargo faturalarıdır.
ShipmentCostSharingIncome	Kargo katkı payı iadesi	Siparişe ait paketler üzerinden uygulanan kargo giderleri için düzenlenen iade faturalarıdır.
ProcessingFeeExpense	Hizmet bedeli	Siparişe ait ürünler üzerinden uygulanan hizmet bedeli tutarıdır.
ProcessingFeeExpenseRefund	Hizmet bedeli iadesi	Hizmet bedeli iade faturalarıdır.
CustomerSatisfaction	Müşteri memnuniyeti yansıtma	Tedarik gecikmesi ve sipariş iptallerinden doğan işlemler için düzenlenen faturalardır.
CustomerSatisfactionRefund	Müşteri memnuniyeti yansıtma iadesi	Sipariş gecikme ve iptal ücretlendirmeleri karşılığında düzenlenen iade faturalarıdır.
LineItemTransferExpense	Sipariş transfer gideri	Tedarik edilemeyen ve iptali sağlanan siparişler için kesilen "sipariş kaydırma" tutarlarını ifade etmektedir.
LineItemTransferIncome	Sipariş transfer geliri	Sipariş transfer gideri faturaları karşılığında düzenlenen iade faturalarıdır.
CampaignDiscount	Kampanya indirimleri	Hepsiburada\'ya düzenlediğiniz kampanya faturaları ile Hepsiburada\'nın siparişlerinizde karşıladığı, komisyonunuzdan düşen indirim tutarlarını gösterir.
CampaignDiscountRefund	Kampanya indirimleri iadesi	Siparişe ait iade edilen kampanya indirimleri faturalarını ifade etmektedir.
RevenueExpense	Ciro gideri	Anlaşmalı ciro gideri faturalarını ifade etmektedir.
RevenueIncome	Ciro geliri	Anlaşmalı ciro geliri faturalarını ifade etmektedir.
CargoMargin	Kargo marj	Siparişe ait paketler üzerinden uygulanan kargo giderleri için düzenlenen iade faturalarıdır.
CargoCompensationIncomeRefund	Kargo tazmin geliri iadesi	Sipariş tazminleri için kestiğiniz faturaları ifade eder.
MpScrapIncome	Hurda geliri	Müşteri memnuniyeti adına iadesi onaylanan siparişleriniz için Hepsiburada\'ya düzenlediğiniz faturalardır.
RefusedInvoiceExpenseRefund	Reddedilen faturalar	Hepsiburada\'ya düzenlenen ancak onaylanmayan faturalardır.
RefusedInvoiceExpense	Reddedilen fatura bedeli	Hepsiburada\'ya düzenlenen ancak onaylanmayan faturaları ifade etmektedir.
Deposit	Depozito tutarı	Depozito faturalarını ifade etmektedir.
AdSharingExpense	Reklam katılım gideri	Reklam katılım bedeli faturalarıdır.
AdSharingExpenseRefund	Reklam katılım gideri iadesi	Reklam katılım bedeli iade faturalarıdır.
DropShipmentCostSharingExpense	Drop kargo katkı payı gideri	Hepsiburada anlaşmalı kargo desi/fiyat tablosuna ve kampanya süreçlerine göre düzenlenen kargo faturalarıdır.
DropShipmentCostSharingIncome	Drop kargo katkı payı geliri	Siparişe ait paketler üzerinden uygulanan kargo giderleri için düzenlenen iade faturalarıdır.
Chargeout	Masraf yansıtma tutarı	Masraf yansıtma faturalarını ifade etmektedir.
LineItemTransferIncome	Sipariş transfer geliri	Sipariş Transfer Gideri faturaları karşılığında düzenlenen iade faturalarıdır.
CargoCompensationSellerSatisfactionIncome	Kargo tazmin satıcı memnuniyet geliri	Satıcı memnuniyeti sebebiyle tarafınızdan alınan iade tazmin faturalarını ifade eder.
ReturnShipmentCostSharingExpense	Kargo Bedeli (İade Sipariş)	Hepsiburada anlaşmalı kargo desi/fiyat tablosuna ve kampanya süreçlerine göre iade siparişleri için düzenlenen kargo faturalarıdır.
MarketingExpense	Pazarlama bedeli	Pazarlama/reklam faturalarını ifade etmektedir.
MarketingExpenseRefund	Pazarlama bedeli iadesi	İade edilen pazarlama faturalarını ifade etmektedir.
StudioExpense	Stüdyo kullanım bedeli	Stüdyo kullanım bedeli faturalarıdır.
ReturnDeliveryProcessingFee	İşlem Bedeli (İade Sipariş)	Her bir iade başına alınan işlem bedelidir.
PriceDifferenceExpense	Fiyat farkı bedeli	Maliyetlerde meydana gelen değişikliklerin yansıtıldığı faturaları ifade eder.
PriceDifferenceRefund	Fiyat farkı iadesi	Maliyetlerde meydana gelen değişikliklerin firma tarafından HB\'ye iletilmesini ifade etmektedir.
LateInterestExpense	Vade farkı gideri	Vade farkı sebebiyle kesilen faturaladır.
CargoCostRefund	Kargo iade	Kargo tutar iadesi sebebiyle düzenlediğiniz faturalardır.
RoadAssistanceExpenseRefund	Yol yardım iadesi	İade edilen yol yardım faturalarını ifade etmektedir.
RoadAssistanceExpense	Yol yardım bedeli	Yol yardım faturalarını ifade etmektedir.
SponsorshipFee	Sponsorluk bedeli	Sponsorluk faturalarını ifade etmektedir.
OverseasCommissionRefund	Yurtdışı komisyon iadesi	Yurtdışı siparişe ait iade edilen komisyon faturalarını ifade etmektedir.
MpScrapExpense	Hurda gideri	Sipariş özelinde HB\'nın düzenlemiş olduğu memnuniyet faturalarını ifade etmektedir.
MpCompensationIncome	MP operasyon departmanı tazmin geliri	Kampanya döneminde düzenlenen Hizmet Bedeli faturasının iadesidir.
CargoCompensationExpenseRefund	Kargo tazmin gideri iadesi	Sipariş tazminleri için düzenlediğiniz faturaların iadesidir.
VAT	KDV	Katma değer vergisi faturalarını ifade etmektedir.
BalanceCorrection	Düzeltme kaydı	Muhasebe/Finans tarafından ekstre üzerinde uygulanan ters kayıt işlemlerini ifade etmektedir.
SfsInterest	TFS vade farkı	TFS işlemi sonrası firmaya yansıtılan tfs gideri
ProductsReportedByService	MP servis raporlu ürünler	MP Servis Raporlu Ürünler
FacebookAdExpense	MP Facebook reklam gideri	Facebook reklam katılım bedeli faturalarıdır.
CargoLimitExcessCompensationIncome	Kargo limit aşımı tazmin geliri	Sipariş tazminleri için kestiğiniz faturaları ifade eder.
OrderBasedTransactions	Sipariş bazlı kayıtlar	Sipariş bazlı kayıtlarınızı listeler
ContractualOrSpecialCaseTransactions	Sözleşmeye bağlı / Özel durum kayıtlar	Sözleşmeye bağlı / Özel durum kayıtlarınızı listeler
CommissionSettlementTransactions	Komisyon mahsuplaşma kayıtları	Komisyon mahsup içerisinde yer alan tüm kayıtlarınızı listeler(Mahsup içerisindeki komisyon, kampanya indirimleri gibi.)
InvoiceTransactions	Faturalar	Fatura tipindeki kayıtlarınızı listeler
IncomeTransactions	Tüm gelir kayıtları	Gelir tipindeki tüm kayıtlarınızı listeler
ExpenseTransactions	Tüm gider kayıtları	Gider tipindeki tüm kayıtlarınızı listeler
AdBalanceTopUpFromAllowance	Reklam Bakiye Yüklemesi	Hak edişinizden reklam bakiyesi olarak yüklediğiniz tutarı ifade etmektedir. Kullanım detayları için Merchant paneldeki Reklam sayfasını ziyaret edebilirsiniz.
EInvoiceSalesRefund	E-Fatura Satış Tutarı İadesi	E-fatura satış tutarının hakedişinize iade edilen tutarı ifade etmektedir.
EInvoiceSales	Mp outlet gider kalemi	Müşteri memnuniyeti için kestiğiniz fatura tutarının iadesi için kesilen tutarını ifade etmektedir.
BnplOrder	BNPL Sipariş Tutarı	BNPL Siparişe ait ürünün satış tutarını ifade etmektedir.
BnplRefund	BNPL İade Tutarı	İade edilen BNPL sipariş tutarlarını ifade etmektedir.
MpOutletProductExpense	E-Fatura Satış Tutarı	E-fatura satış tutarının hakedişinizden mahsup edilen tutarı ifade etmektedir.
AdBalanceTopUpFromAllowanceRefund	Reklam bakiye iadesi	Reklam bakiyenizden hak edişinize iade edilen tutarı ifade etmektedir.
PaymentServiceCostReflection	Ödeme Servisi Maliyet Yansıtma	Hepsiburada'nın katlandığı kredi kartı pos maliyetlerine ilişkin yansıtılan faturalardır.
PaymentServiceCostReflectionRefund	Ödeme Servisi Maliyet Yansıtma İadesi	Hepsiburada'nın katlandığı kredi kartı pos maliyetlerine ilişkin yansıtılan tutarların iadesidir.
MarketingSupportParticipation	Pazarlama Destek Katılım	Fenomen reklamlarından gelen siparişleriniz için kesilen katılım tutarınızı ifade etmektedir.
Stoppage	MP Stopaj	Gelir İdaresi Başkanlığı tarafından yürürlüğe sokulan mevzuat kapsamında yapılan stopaj kesintisidir.
StoppageRefund	MP Stopaj İade	Gelir İdaresi Başkanlığı tarafından yürürlüğe sokulan mevzuat kapsamında yapılan stopaj kesintisinin iadesidir.
TransportExpense	Taşıma Gideri	Anlaşmalı olunan tutar üzerinden taşıma gideri yansıtmasıdır.
TransportExpenseRefund	Taşıma Gideri İadesi	Kesilen taşıma yansıtma bedeli faturalarının iadesidir.
BnplProcessingFee	BNPL İşlem Ücreti İadesi	BNPL ödeme yöntemini kullandığınız için sipariş bazlı kesilen katılım tutarının iadesini ifade etmektedir.
BnplProcessingFeeRefund	BNPL İşlem Ücreti	BNPL ödeme yöntemini kullandığınız için sipariş bazlı kesilen katılım tutarını ifade etmektedir.
MarketingSupportParticipationRefund	Pazarlama Destek Katılım İptal / İade	Fenomen reklamlarından gelen siparişleriniz için kesilen katılım tutarınızın iptal veya iadesidir.
ReturnProcessingFeeExpense	Hizmet Bedeli (İade Sipariş)	İade siparişe ait ürünler üzerinden uygulanan hizmet bedeli tutarıdır.
GoldLaborStoppage	Altın İşçilik Bedeli Stopajı	Gelir İdaresi Başkanlığı tarafından yürürlüğe sokulan mevzuat kapsamında yapılan stopaj kesintisidir.
GoldLaborStoppageRefund	Altın İşçilik Bedeli Stopajı İadesi	Gelir İdaresi Başkanlığı tarafından yürürlüğe sokulan mevzuat kapsamında yapılan stopaj kesintisinin iadesidir.
Performans Servisi
Servis, sipariş ve ürün detayı bazında finansal performansın listelenmesine olanak tanır. Finansal kayıtlarınız sipariş teslim edildikten sonra oluşmaktadır.

Merchantid = Zorunludur, Her satıcının unique bir tanımlayıcısıdır.
orderDateStart - orderDateEnd
dueDateStart – dueDateEnd
2 tarih aralığı parametresinden biri girilmek zorundadır. Bir tanesi girildikten sonra kalanlar opsiyonel eklenebilir. orderNumber, Sku parametrelerinden en az biri verilirse tarih parametreleri zorunlu olmayacaktır.
Örnek format;
orderDateStart=2021-08-01& orderDateEnd=2021-08-31
dueDateStart=2021-08-01& dueDateEnd=2021-08-31
offset/limit = Girişi zorunludur. Offset, kaçıncı kayıttan itibaren gösterileceğini verir. Limit, servisten kaç tane kayıt döneceğini belirler. Limit en fazla 100 olabilir.
Örnek; Kayıtlar yüzer yüzer çekildiğinde yani limiti 100 belirlendiğinde, 3. sayfayı göstermek için offset=200&limit=100 girilecektir.
orderNumber = Opsiyoneldir. Sipariş numarası olarak geçer.
Örnek; orderNumber=0019531668
sku = Opsiyoneldir. Ürün Hepsiburada numarasıdır.
Örnek; sku=HBV0000058C3H
İstek içerisinde orderNumber, sku parametreleri verilerek çağrım yapılırsa sipariş numarası ve ürün numarasına ait net kazanç, gelir, gider performansı gözlemlenebilir.
Döviz Cinsi Kodları; currencyCode alanında dönen bilgidir.
currencyCode	Açıklama
949	TRY
840	USD

**Birden fazla currency ile sonuç dönmesi durumunda 409 uyarısı ve uyarı mesajı olarak aşagıdaki response dönecektir;
ErrorMessage: More than one currencies exist in the results. MerchantId : {merchant.SapId}. Merchant Name : {merchant.Name}
ExceptionCode: MoreThanOneCurrenciesExistInTheResults**
Servisten Dönen Alan Açıklamaları

Transaction Type	Açıklama	Detay Bilgi
Payment	Sipariş tutarı	Siparişe ait ürünün satış tutarını ifade etmektedir.
DeliveryProcessingFee	İşlem Bedeli	Her bir teslimat başına alınan işlem bedelidir.
DeliveryProcessingFeeRefund	İşlem Bedeli İadesi	Her bir teslimat başına alınan işlem bedelinin iadesidir.
Return	İade tutarı	İade edilen sipariş tutarlarını ifade etmektedir.
Commission	Komisyon tutarı	Siparişe ait komisyon faturalarını ifade etmektedir.
CommissionInvoiceRefund	Komisyon iadesi	Hepsiburada'ya düzenlediğiniz komisyon iade faturaları ile iadesi onaylanan siparişlerinizde, mağazanıza geri ödenen komisyon tutarlarını gösterir.
CommissionRefund	Komisyon iade tutarı	Siparişe ait iade edilen komisyon faturalarını ifade etmektedir.
CommissionCorrection	Komisyon düzeltme	Komisyon faturalarında KDV farkından dolayı tarafınıza yapılan fazla ödeme için düzenlenen istek tipini ifade etmektedir.
ShipmentCostSharingExpense	Kargo katkı payı gideri	Hepsiburada anlaşmalı kargo desi/fiyat tablosuna ve kampanya süreçlerine göre düzenlenen kargo faturalarıdır.
ShipmentCostSharingIncome	Kargo katkı payı iadesi	Siparişe ait paketler üzerinden uygulanan kargo giderleri için düzenlenen iade faturalarıdır.
ProcessingFeeExpense	Hizmet bedeli	Siparişe ait ürünler üzerinden uygulanan hizmet bedeli tutarıdır.
ProcessingFeeExpenseRefund	Hizmet bedeli iadesi	Hizmet bedeli iade faturalarıdır.
CustomerSatisfaction	Müşteri memnuniyeti yansıtma	Tedarik gecikmesi ve sipariş iptallerinden doğan işlemler için düzenlenen faturalardır.
CustomerSatisfactionRefund	Müşteri memnuniyeti yansıtma iadesi	Sipariş gecikme ve iptal ücretlendirmeleri karşılığında düzenlenen iade faturalarıdır.
LineItemTransferExpense	Sipariş transfer gideri	Tedarik edilemeyen ve iptali sağlanan siparişler için kesilen "sipariş kaydırma" tutarlarını ifade etmektedir.
LineItemTransferIncome	Sipariş transfer geliri	Sipariş transfer gideri faturaları karşılığında düzenlenen iade faturalarıdır.
CampaignDiscount	Kampanya indirimleri	Hepsiburada\'ya düzenlediğiniz kampanya faturaları ile Hepsiburada\'nın siparişlerinizde karşıladığı, komisyonunuzdan düşen indirim tutarlarını gösterir.
CampaignDiscountRefund	Kampanya indirimleri iadesi	Siparişe ait iade edilen kampanya indirimleri faturalarını ifade etmektedir.
RevenueExpense	Ciro gideri	Anlaşmalı ciro gideri faturalarını ifade etmektedir.
RevenueIncome	Ciro geliri	Anlaşmalı ciro geliri faturalarını ifade etmektedir.
CargoMargin	Kargo marj	Siparişe ait paketler üzerinden uygulanan kargo giderleri için düzenlenen iade faturalarıdır.
CargoCompensationIncomeRefund	Kargo tazmin geliri iadesi	Sipariş tazminleri için kestiğiniz faturaları ifade eder.
MpScrapIncome	Hurda geliri	Müşteri memnuniyeti adına iadesi onaylanan siparişleriniz için Hepsiburada\'ya düzenlediğiniz faturalardır.
RefusedInvoiceExpenseRefund	Reddedilen faturalar	Hepsiburada\'ya düzenlenen ancak onaylanmayan faturalardır.
RefusedInvoiceExpense	Reddedilen fatura bedeli	Hepsiburada\'ya düzenlenen ancak onaylanmayan faturaları ifade etmektedir.
Deposit	Depozito tutarı	Depozito faturalarını ifade etmektedir.
AdSharingExpense	Reklam katılım gideri	Reklam katılım bedeli faturalarıdır.
AdSharingExpenseRefund	Reklam katılım gideri iadesi	Reklam katılım bedeli iade faturalarıdır.
DropShipmentCostSharingExpense	Drop kargo katkı payı gideri	Hepsiburada anlaşmalı kargo desi/fiyat tablosuna ve kampanya süreçlerine göre düzenlenen kargo faturalarıdır.
DropShipmentCostSharingIncome	Drop kargo katkı payı geliri	Siparişe ait paketler üzerinden uygulanan kargo giderleri için düzenlenen iade faturalarıdır.
Chargeout	Masraf yansıtma tutarı	Masraf yansıtma faturalarını ifade etmektedir.
LineItemTransferIncome	Sipariş transfer geliri	Sipariş Transfer Gideri faturaları karşılığında düzenlenen iade faturalarıdır.
CargoCompensationSellerSatisfactionIncome	Kargo tazmin satıcı memnuniyet geliri	Satıcı memnuniyeti sebebiyle tarafınızdan alınan iade tazmin faturalarını ifade eder.
ReturnShipmentCostSharingExpense	Kargo Bedeli (İade Sipariş)	Hepsiburada anlaşmalı kargo desi/fiyat tablosuna ve kampanya süreçlerine göre iade siparişleri için düzenlenen kargo faturalarıdır.
MarketingExpense	Pazarlama bedeli	Pazarlama/reklam faturalarını ifade etmektedir.
MarketingExpenseRefund	Pazarlama bedeli iadesi	İade edilen pazarlama faturalarını ifade etmektedir.
StudioExpense	Stüdyo kullanım bedeli	Stüdyo kullanım bedeli faturalarıdır.
ReturnDeliveryProcessingFee	İşlem Bedeli (İade Sipariş)	Her bir iade başına alınan işlem bedelidir.
PriceDifferenceExpense	Fiyat farkı bedeli	Maliyetlerde meydana gelen değişikliklerin yansıtıldığı faturaları ifade eder.
PriceDifferenceRefund	Fiyat farkı iadesi	Maliyetlerde meydana gelen değişikliklerin firma tarafından HB\'ye iletilmesini ifade etmektedir.
LateInterestExpense	Vade farkı gideri	Vade farkı sebebiyle kesilen faturaladır.
CargoCostRefund	Kargo iade	Kargo tutar iadesi sebebiyle düzenlediğiniz faturalardır.
RoadAssistanceExpenseRefund	Yol yardım iadesi	İade edilen yol yardım faturalarını ifade etmektedir.
RoadAssistanceExpense	Yol yardım bedeli	Yol yardım faturalarını ifade etmektedir.
SponsorshipFee	Sponsorluk bedeli	Sponsorluk faturalarını ifade etmektedir.
OverseasCommissionRefund	Yurtdışı komisyon iadesi	Yurtdışı siparişe ait iade edilen komisyon faturalarını ifade etmektedir.
MpScrapExpense	Hurda gideri	Sipariş özelinde HB\'nın düzenlemiş olduğu memnuniyet faturalarını ifade etmektedir.
MpCompensationIncome	MP operasyon departmanı tazmin geliri	Kampanya döneminde düzenlenen Hizmet Bedeli faturasının iadesidir.
CargoCompensationExpenseRefund	Kargo tazmin gideri iadesi	Sipariş tazminleri için düzenlediğiniz faturaların iadesidir.
VAT	KDV	Katma değer vergisi faturalarını ifade etmektedir.
BalanceCorrection	Düzeltme kaydı	Muhasebe/Finans tarafından ekstre üzerinde uygulanan ters kayıt işlemlerini ifade etmektedir.
SfsInterest	TFS vade farkı	TFS işlemi sonrası firmaya yansıtılan tfs gideri
ProductsReportedByService	MP servis raporlu ürünler	MP Servis Raporlu Ürünler
FacebookAdExpense	MP Facebook reklam gideri	Facebook reklam katılım bedeli faturalarıdır.
CargoLimitExcessCompensationIncome	Kargo limit aşımı tazmin geliri	Sipariş tazminleri için kestiğiniz faturaları ifade eder.
OrderBasedTransactions	Sipariş bazlı kayıtlar	Sipariş bazlı kayıtlarınızı listeler
ContractualOrSpecialCaseTransactions	Sözleşmeye bağlı / Özel durum kayıtlar	Sözleşmeye bağlı / Özel durum kayıtlarınızı listeler
CommissionSettlementTransactions	Komisyon mahsuplaşma kayıtları	Komisyon mahsup içerisinde yer alan tüm kayıtlarınızı listeler(Mahsup içerisindeki komisyon, kampanya indirimleri gibi.)
InvoiceTransactions	Faturalar	Fatura tipindeki kayıtlarınızı listeler
IncomeTransactions	Tüm gelir kayıtları	Gelir tipindeki tüm kayıtlarınızı listeler
ExpenseTransactions	Tüm gider kayıtları	Gider tipindeki tüm kayıtlarınızı listeler
AdBalanceTopUpFromAllowance	Reklam Bakiye Yüklemesi	Hak edişinizden reklam bakiyesi olarak yüklediğiniz tutarı ifade etmektedir. Kullanım detayları için Merchant paneldeki Reklam sayfasını ziyaret edebilirsiniz.
EInvoiceSalesRefund	E-Fatura Satış Tutarı İadesi	E-fatura satış tutarının hakedişinize iade edilen tutarı ifade etmektedir.
EInvoiceSales	Mp outlet gider kalemi	Müşteri memnuniyeti için kestiğiniz fatura tutarının iadesi için kesilen tutarını ifade etmektedir.
BnplOrder	BNPL Sipariş Tutarı	BNPL Siparişe ait ürünün satış tutarını ifade etmektedir.
BnplRefund	BNPL İade Tutarı	İade edilen BNPL sipariş tutarlarını ifade etmektedir.
MpOutletProductExpense	E-Fatura Satış Tutarı	E-fatura satış tutarının hakedişinizden mahsup edilen tutarı ifade etmektedir.
AdBalanceTopUpFromAllowanceRefund	Reklam bakiye iadesi	Reklam bakiyenizden hak edişinize iade edilen tutarı ifade etmektedir.
PaymentServiceCostReflection	Ödeme Servisi Maliyet Yansıtma	Hepsiburada'nın katlandığı kredi kartı pos maliyetlerine ilişkin yansıtılan faturalardır.
PaymentServiceCostReflectionRefund	Ödeme Servisi Maliyet Yansıtma İadesi	Hepsiburada'nın katlandığı kredi kartı pos maliyetlerine ilişkin yansıtılan tutarların iadesidir.
MarketingSupportParticipation	Pazarlama Destek Katılım	Fenomen reklamlarından gelen siparişleriniz için kesilen katılım tutarınızı ifade etmektedir.
Stoppage	MP Stopaj	Gelir İdaresi Başkanlığı tarafından yürürlüğe sokulan mevzuat kapsamında yapılan stopaj kesintisidir.
StoppageRefund	MP Stopaj İade	Gelir İdaresi Başkanlığı tarafından yürürlüğe sokulan mevzuat kapsamında yapılan stopaj kesintisinin iadesidir.
TransportExpense	Taşıma Gideri	Anlaşmalı olunan tutar üzerinden taşıma gideri yansıtmasıdır.
TransportExpenseRefund	Taşıma Gideri İadesi	Kesilen taşıma yansıtma bedeli faturalarının iadesidir.
BnplProcessingFee	BNPL İşlem Ücreti İadesi	BNPL ödeme yöntemini kullandığınız için sipariş bazlı kesilen katılım tutarının iadesini ifade etmektedir.
BnplProcessingFeeRefund	BNPL İşlem Ücreti	BNPL ödeme yöntemini kullandığınız için sipariş bazlı kesilen katılım tutarını ifade etmektedir.
MarketingSupportParticipationRefund	Pazarlama Destek Katılım İptal / İade	Fenomen reklamlarından gelen siparişleriniz için kesilen katılım tutarınızın iptal veya iadesidir.
ReturnProcessingFeeExpense	Hizmet Bedeli (İade Sipariş)	İade siparişe ait ürünler üzerinden uygulanan hizmet bedeli tutarıdır.
GoldLaborStoppage	Altın İşçilik Bedeli Stopajı	Gelir İdaresi Başkanlığı tarafından yürürlüğe sokulan mevzuat kapsamında yapılan stopaj kesintisidir.
GoldLaborStoppageRefund	Altın İşçilik Bedeli Stopajı İadesi	Gelir İdaresi Başkanlığı tarafından yürürlüğe sokulan mevzuat kapsamında yapılan stopaj kesintisinin iadesidir.


Kayıt Bazlı Muhasebe Servisi
get
https://mpfinance-external-sit.hepsiburada.com/transactions/merchantid/{merchantId}


Servis, ödeme ve faturaları listelemenize olanak tanır.

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
uuid
required
Query Params
Offset
int32
required
Defaults to 0
0
Limit
int32
required
Defaults to 100
100
OrderNumber
string
PackageNumber
string
ReferenceDocument
string
TransactionTypes
string
Transaction type filter. Leave it empty for all types. Or provide one or more types as a comma-separated string.

Allowed values: MpOutletProductExpense, DeliveryProcessingFeeRefund, OutboundCustomerSatisfaction, CargoMargin, Commission, MpCompensationIncome, OverseasCommissionRefund, CustomerSatisfactionRefund, Return, InboundCustomerSatisfaction, StoppageRefund, ShipmentCostSharingIncome, CommissionCorrection, CampaignDiscount, CargoCompensationIncomeRefund, BnplOrder, MarketingSupportParticipation, FaturaLab, PaymentServiceCostReflection, ProductsReportedByService, OneClickReturnShipmentCostSharingExpense, LineItemTransferIncome, PaymentServiceCostReflectionRefund, CommissionRefund, ReturnProcessingFeeExpense, BnplProcessingFee, AdSharingExpense, Deposit, RefusedInvoiceExpenseRefund, HepsiGlobalCampaignDiscount, CargoCostRefund, InternationalOperationFeeRefund, TotalPayment, RevenueExpense, Chargeout, MpScrapExpense, AdBalanceTopUpFromAllowance, CargoLimitExcessCompensationIncome, RoadAssistanceExpense, BnplRefund, CargoCompensationSellerSatisfactionIncome, GoldLaborStoppageRefund, HepsiGlobalTransferIncome, InboundCustomerSatisfactionRefund, AdSharingExpenseRefund, OutboundCustomerSatisfactionRefund, CustomerSatisfaction, Payment, TransportExpenseRefund, EInvoiceSales, LineItemTransferExpense, GoldLaborStoppage, VAT, SfsInterest, TransportExpense, CargoCompensationIncome, BnplProcessingFeeRefund, ProcessingFeeExpenseRefund, LateInterestExpense, PriceDifferenceRefund, StudioExpense, BalanceCorrection, MpScrapIncome, SponsorshipFee, InternationalOperationFee, CommissionInvoiceRefund, FacebookAdExpense, CargoCompensationExpenseRefund, RoadAssistanceExpenseRefund, MarketingExpenseRefund, ProcessingFeeExpense, HepsiGlobalTransferExpense, FigoPara, AdBalanceTopUpFromAllowanceRefund, EInvoiceSalesRefund, CampaignDiscountRefund, RefusedInvoiceExpense, ReturnDeliveryProcessingFee, MarketingSupportParticipationRefund, RevenueIncome, DropShipmentCostSharingExpense, DropShipmentCostSharingIncome, Stoppage, MarketingExpense, PriceDifferenceExpense, DeliveryProcessingFee, ShipmentCostSharingExpense, ReturnShipmentCostSharingExpense

Status
string
Status filter. Leave it empty for all statuses. Or provide one or more types as a comma-separated string.

Allowed values: Paid, WillBePaid

Sku
string
OrderDateStart
date-time
Prioritize OrderDate over other date filters, for better response times

OrderDateEnd
date-time
Prioritize OrderDate over other date filters, for better response times

DueDateStart
date-time
DueDateEnd
date-time
RecordDateStart
date-time
RecordDateEnd
date-time
PaymentDateStart
date-time
PaymentDateEnd
date-time
Headers
User-Agent
string
required
Integrator application identifier. Required for authentication.

Responses

200
OK


400
Bad Request


401
Unauthorized


403
Forbidden


404
Not Found


500
Internal Server Error



import requests

url = "https://mpfinance-external-sit.hepsiburada.com/transactions/merchantid/merchantId?Offset=0&Limit=100"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

Kayıt Bazlı Muhasebe Servisi
get
https://mpfinance-external-sit.hepsiburada.com/transactions/cursor/merchantid/{merchantId}


Kayıt bazlı muhasebe verilerini imleç (cursor) tabanlı sayfalama ile getirir.

Sıralama ve imleç için OrderDate (sipariş tarihi) alanı baz alınır.

Sayfalama Nasıl Çalışır?

İlk istek için cursorId'yi boş gönderin, veya en son kaldığınız yeri girebilirsiniz .
İlk istek için cursorDate'i 0001-01-01 gönderin, veya istediğiniz başlangıç tarihini verin.
Her başarılı response içinde bir sonraki sayfa için kullanılacak cursor bilgisi döner.
Bir sonraki sayfayı almak için, bir önceki yanıttan aldığınız cursor'ı tekrar isteğe ekleyin.
Tüm veriler alındığında veya sonraki sayfa olmadığında, cursor null veya boş dönecektir.
Önemli Not: OrderDate alanı null olan kayıtlar mevcut olabilir. Bu kayıtlar sayfalama yapılırken her zaman en sonda listelenir.

Recent Requests
Log in to see full request history
Time	Status	User Agent	
Make a request to see history.
0 Requests This Month

Path Params
merchantId
uuid
required
Query Params
Limit
int32
required
Defaults to 100
100
OrderNumber
string
PackageNumber
string
ReferenceDocument
string
TransactionTypes
string
Transaction type filter. Leave it empty for all types. Or provide one or more types as a comma-separated string.

Allowed values: MpOutletProductExpense, DeliveryProcessingFeeRefund, OutboundCustomerSatisfaction, CargoMargin, Commission, MpCompensationIncome, OverseasCommissionRefund, CustomerSatisfactionRefund, Return, InboundCustomerSatisfaction, StoppageRefund, ShipmentCostSharingIncome, CommissionCorrection, CampaignDiscount, CargoCompensationIncomeRefund, BnplOrder, MarketingSupportParticipation, FaturaLab, PaymentServiceCostReflection, ProductsReportedByService, OneClickReturnShipmentCostSharingExpense, LineItemTransferIncome, PaymentServiceCostReflectionRefund, CommissionRefund, ReturnProcessingFeeExpense, BnplProcessingFee, AdSharingExpense, Deposit, RefusedInvoiceExpenseRefund, HepsiGlobalCampaignDiscount, CargoCostRefund, InternationalOperationFeeRefund, TotalPayment, RevenueExpense, Chargeout, MpScrapExpense, AdBalanceTopUpFromAllowance, CargoLimitExcessCompensationIncome, RoadAssistanceExpense, BnplRefund, CargoCompensationSellerSatisfactionIncome, GoldLaborStoppageRefund, HepsiGlobalTransferIncome, InboundCustomerSatisfactionRefund, AdSharingExpenseRefund, OutboundCustomerSatisfactionRefund, CustomerSatisfaction, Payment, TransportExpenseRefund, EInvoiceSales, LineItemTransferExpense, GoldLaborStoppage, VAT, SfsInterest, TransportExpense, CargoCompensationIncome, BnplProcessingFeeRefund, ProcessingFeeExpenseRefund, LateInterestExpense, PriceDifferenceRefund, StudioExpense, BalanceCorrection, MpScrapIncome, SponsorshipFee, InternationalOperationFee, CommissionInvoiceRefund, FacebookAdExpense, CargoCompensationExpenseRefund, RoadAssistanceExpenseRefund, MarketingExpenseRefund, ProcessingFeeExpense, HepsiGlobalTransferExpense, FigoPara, AdBalanceTopUpFromAllowanceRefund, EInvoiceSalesRefund, CampaignDiscountRefund, RefusedInvoiceExpense, ReturnDeliveryProcessingFee, MarketingSupportParticipationRefund, RevenueIncome, DropShipmentCostSharingExpense, DropShipmentCostSharingIncome, Stoppage, MarketingExpense, PriceDifferenceExpense, DeliveryProcessingFee, ShipmentCostSharingExpense, ReturnShipmentCostSharingExpense

Status
string
Status filter. Leave it empty for all statuses. Or provide one or more types as a comma-separated string.

Allowed values: Paid, WillBePaid

Sku
string
CursorId
uuid
The Curser.Id returned from the last request. Leave it empty, if it is first request

CursorDate
date
The Curser.Date returned from the last request. Or Lowerbound date if it is first request

CursorDateUpperBound
date
Inclusive optinal upper bound date. Leave it empty, if you want to fetch all records after the CursorDate

Headers
User-Agent
string
required
Integrator application identifier. Required for authentication.

Responses

200
OK


400
Bad Request


401
Unauthorized


403
Forbidden


404
Not Found


500
Internal Server Error

import requests

url = "https://mpfinance-external-sit.hepsiburada.com/transactions/cursor/merchantid/merchantId?Limit=100"

headers = {"accept": "application/json"}

response = requests.get(url, headers=headers)

print(response.text)

