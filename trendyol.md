Test Siparişi Oluşturma
Test siparişi oluşturma servisi STAGE ortamında talep edilen senaryolarda test siparişi oluşturulması için kullanılacaktır.

İstek yaparken, "SellerID" bilgisini Header içinde göndermelisiniz. Bu değer, kullanılan test satıcısının satıcı ID si olmalıdır.
Header içerisinde göndermiş olduğunuz satıcıId ile basic authentication yapmanız gerekmektedir.
Test ortamı bilgilerini edinmek için Canlı-Test Ortam Bilgileri bölümünü inceleyebilirsiniz.
İstek başarıyla tamamlandığında, tarafınıza gönderilen response içinde "orderNumber" değeri yer alacaktır. Bu sipariş numarasını kullanarak ilgili işlemleri gerçekleştirebilirsiniz.
Kurumsal Faturalı Test Siparişi Oluşturma
Kurumsal faturalı test siparişi oluşturmak için aşağıda yer alan request body içerisinde "commercial" alanı true olarak gönderilmelidir. "commercial" alanının true olduğu durumda, "invoiceAddress" altında bulunan "company", "invoiceTaxNumber" ve "invoiceTaxOffice" alanlarını doldurmanız gerekmektedir.

Mikro İhracat Test Siparişi Oluşturma
Mikro ihracat test siparişi oluşturmak için aşağıda yer alan request body içerisinde "microRegion" alanı doldurulmalıdır.

Eğer Azerbaycan mikro ihracat test siparişi oluşturulmak isteniyorsa "microRegion" alanı "AZ" olarak doldurulmalıdır.
Eğer Gulf bölgesi mikro ihracat test siparişi oluşturulmak isteniyorsa "microRegion" alanı "GULF" olarak doldurulmalıdır.
POST
STAGE
https://stageapigw.trendyol.com/integration/test/order/orders/core

Örnek Servis İsteği

JSON

{
  "customer": {
    "customerFirstName": "Adı",
    "customerLastName": "Soyadı"
  },
  "invoiceAddress": {
    "addressText": "test deneme adresi",
    "city": "İzmir",
    "company": "",
    "district": "Bornova",
    "invoiceFirstName": "Adı",
    "invoiceLastName": "Soyadı",
    "latitude": "string",
    "longitude": "string",
    "neighborhood": "",
    "phone": "5000000000",
    "postalCode": "",
    "email": "musteri@email.com",
    "invoiceTaxNumber": "Firma Tax Number",
    "invoiceTaxOffice": "Firma Tax Office"
  },
  "lines": [
    {
      "barcode": "9900000000486",
      "quantity": 2,
      "discountPercentage": 50
    }
  ],
  "seller": {
    "sellerId": 2738
  },
  "shippingAddress": {
    "addressText": "test deneme adresi",
    "city": "İzmir",
    "company": "",
    "district": "Bornova",
    "latitude": "string",
    "longitude": "string",
    "neighborhood": "",
    "phone": "5000000000",
    "postalCode": "",
    "shippingFirstName": "Adı",
    "shippingLastName": "Soyadı",
    "email": "musteri@email.com"
  },
   "commercial":false,
   "microRegion": "String"
}



Sipariş Paketlerini Çekme (getShipmentPackages)
Trendyol sistemine ilettiğiniz ürünler ile müşteriler tarafından verilen ve ödeme kontrolünde olan her siparişin bilgisini bu method yardımıyla alabilirsiniz. Sistem tarafından ödeme kontrolünden sonra otomatik paketlenerek sipariş paketleri oluşturulur.

Sipariş Sorgulama ve Sıralama:

Bu servise 1 dakika içinde en fazla 1000 adet istek atabilirsiniz.
Servise atılan isteklerde, PackageLastModifiedDate sıralamasına göre bir response alırsınız.
suppliers/(supplierid)/orders?status=Created gibi bir query ile paket statülerine göre sorgulama yapılabilir. Kullanılabilen statüler: Created, Picking, Invoiced, Shipped, Cancelled, Delivered, UnDelivered, Returned, Repack, UnSupplied.
Sipariş bilgilerini çekerken, ürünün createProducts ile gönderilen Barkod değerlerine göre paketleme ve işlemler yapılmalıdır.
Maksimum 1 aylık geçmişe dönük sipariş sorgularını bu servis üzerinden yapabilirsiniz.
Sipariş paketlerini çekme servisi üzerinden dönen "merchantSku" alanı, Product yaratma servisinde bulunan "stockCode" alanından gelmektedir. filterProducts servisi üzerinden kontrol edilebilir.
Alanlar, Veri Tipleri ve Karakter Sayıları:

Body içindeki değerlerin karakter sayıları ve veri tipleri, sipariş sayısının doğal artışıyla birlikte değişebilir. Sisteminizi buna uygun şekilde kurmanız önerilir.
Sipariş datasında bulunan orderNumber, Trendyol sistemindeki ana sipariş numarasını temsil eder. İlgili seviyede yer alan id değeri, oluşturulmuş Sipariş Paketini temsil eder.
customerId, Trendyol müşteri hesabına tanımlı unique bir değerdir.
deliveryAddressType, "Shipment" veya "CollectionPoint" olarak dönebilir. "CollectionPoint" ise sipariş teslimat noktası siparişidir.
orderDate, Timestamp (milliseconds) formatında GMT +3 olarak iletilir. createdDate bilgileri ise GMT formatında iletilir. Convert işlemi yaparken bu bilgiye dikkat edilmelidir.
Hızlı teslimat bilgisi için kullanılan fastDeliveryType alanı, "TodayDelivery", "SameDayShipping", "FastDelivery" değerlerini alabilir.
Trendyol Satıcı Panelinde cargoTrackingNumber değeri için kullanılan barkod CODE128 formatındadır.
Trendyol İhracat Partnerliği kapsamında sipariş paketlerini çekme servisimize yeni bir alan olarak 3pByTrendyol alanını ekledik. Alan boolean bir alandır. Alan değeri true olduğunda ;
micro alanı false değer alacaktır.
invoiceAddress datasında Trendyol’a ait şirket bilgileri yer alacak olup faturalar da buradaki bilgilere göre kesilecektir.
Sipariş Statüleri İle İlgili Bilgiler:

Awaiting statüsündeki siparişleri sadece stok işlemleri için kullanabilirsiniz. Bu statüdeki siparişler ile ilgili farklı bir işlem yapmamanız gerekmektedir. Şu an bu statüdeki siparişler için sizlere servis cevabında gerekli veriler iletilmektedir. İlerleyen günlerde bu veriler sizlere dönmeyecektir.Bu statüdeki siparişleri kargoya teslim ettiğinizde, yaşanabilecek sipariş iptali işlemlerinin olabileceğini ve Trendyol olarak bu konuda bir sorumluluk kabul etmediklerini belirtmek isteriz.
İptal olan siparişler için status=Cancelled,UnSupplied parametresi kullanılabilir.
Bölünmüş siparişler için status=UnPacked parametresi kullanılabilir.
Bir sipariş paketi içindeki bir ya da birden fazla kalem iptal edilirse, orderNumber aynı kalarak sipariş paketi bozulur ve yeni bir id değeri ve kargo barkodu oluşturulur.
Adres Bilgilerine Erişim:

Sipariş paketlerini çekme servisi tarafından dönen Türkiye, Azerbaycan ve GULF bölgelerinin adres alanlarının id değerlerine (city, district, neighbourhood) Adres Bilgileri Servislerinden ulaşabilirsiniz.

GULF Bölgesi(Suudi Arabistan, Bahreyn, Katar, Kuveyt, Birleşik Arap Emirlikleri ve Umman) siparişlerindeki adres alanları bazı durumlarda boş dönebilir. Özellikle ilçe bilgisi ile ilgili sistemlerinizde kontroller varsa kaldırmanızı rica ederiz.

Menşei Bilgisi:

Mikro ihracat siparişlerinde oluşan paketlerde faturalara menşei bilgisi eklenmesi gerekmektedir. Menşei bilgisi “lines” alanı altından "productOrigin" datası üzerinden dönecektir.
Altın, Gübre ve Yüksek Tutarlı Siparişler:

Altın, gübre veya 5000₺ üzeri siparişlere ait TCKN numarası "IdentityNumber" alanında iletilir.
Kurumsal Faturalı Siparişler

Siparişin kurumsal olup olmadığını belirlemek için sipariş datasındaki commercial değerini kontrol ediniz.

Eğer "commercial" değeri "true" olarak dönerse, kurumsal bir sipariş olduğunu belirtir.

Eğer "commercial" değeri "false" olarak dönerse, siparişin bireysel bir müşteriye ait olduğunu belirtir.

Kurumsal Fatura Bilgileri: Eğer sipariş kurumsal bir müşteriye aitse (commercial=true), aşağıdaki bilgileri invoiceAddress alanından alabilirsiniz:

"company": Kurumun adı

"taxNumber": Kurumun vergi numarası

"taxOffice": Kurumun bağlı olduğu vergi dairesi

E-Fatura Mükellefi Kontrolü: Kurumsal müşterinin e-fatura mükellefi olup olmadığını kontrol etmek için invoiceAddress alanındaki eInvoiceAvailable değerini kullanabilirsiniz.

Eğer "eInvoiceAvailable" değeri "true" ise, müşteri e-fatura mükellefidir.

Eğer "eInvoiceAvailable" değeri "false" ise, müşteri e-fatura mükellefi değildir.

"createdBy" aşağıdaki değerleri alabilir:

"order-creation" -> Paket, gelen siparişle doğrudan oluşturulur
"cancel" -> Paket, kısmi iptalden sonra oluşturulur
"split" -> Paket, paket bölünmesine göre oluşturulur
"transfer" -> Siparişi alan satıcının ürünü olmaması nedeniyle Trendyol tarafından başka bir satıcıya yönlendirilen siparişler.
GET getShipmentPackages
Herhangi bir tarih parametresi vermeden aşağıdaki endpoint ile istek atmanız halinde son bir hafta içerisindeki siparişleriniz sizlere gösterilecektir. startDate ve endDate parametrelerini eklemeniz halinde verilebilecek maksimum aralık iki hafta olacaktır.

PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/orders

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/orders

Önerilen Endpoint

PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/orders?status=Created&startDate={startDate}&endDate={endDate}&orderByField=PackageLastModifiedDate&orderByDirection=DESC&size=50

Servis Parametreleri

Parametre	Parametre Değer	Açıklama	Tip
startDate		Belirli bir tarihten sonraki siparişleri getirir. Timestamp (milliseconds) ve GMT +3 olarak gönderilmelidir.	long
endDate		Belirtilen tarihe kadar olan siparişleri getirir. Timestamp (milliseconds) ve GMT +3 olarak gönderilmelidir.	long
page		Sadece belirtilen sayfadaki bilgileri döndürür	int
size	Maksimum 200	Bir sayfada listelenecek maksimum adeti belirtir.	int
supplierId		İlgili tedarikçinin ID bilgisi gönderilmelidir	long
orderNumber		Sadece belirli bir sipariş numarası verilerek o siparişin bilgilerini getirir	string
status	Created, Picking, Invoiced, Shipped ,Cancelled, Delivered, UnDelivered, Returned, AtCollectionPoint, UnPacked, UnSupplied	Siparişlerin statülerine göre bilgileri getirir.	string
orderByField	PackageLastModifiedDate	Son güncellenme tarihini baz alır.	string
orderByDirection	ASC	Eskiden yeniye doğru sıralar.	string
orderByDirection	DESC	Yeniden eskiye doğru sıralar.	string
shipmentPackageIds		Paket numarasıyla sorgu atılır.	lon
Örnek Servis Cevabı

JSON

{
    "totalElements": 1,
    "totalPages": 1,
    "page": 0,
    "size": 1,
    "content": [
        {
            "shipmentAddress": {
                "id": 11111111,
                "firstName": "Trendyol",
                "lastName": "Customer",
                "company": "",
                "address1": "DSM Grup Danışmanlık İletişim ve Satış Ticaret A.Ş. Maslak Mahallesi Saat Sokak Spine Tower No:5 İç Kapı No:19 Sarıyer/İstanbul",
                "address2": "",
                "city": "İstanbul",
                "cityCode": 34,
                "district": "Sarıyer",
                "districtId": 54,
                "countyId": 0, // CEE bölgesi için gelecektir.
                "countyName": "", // CEE bölgesi için gelecektir.
                "shortAddress": "", // GULF bölgesi için gelecektir.
                "stateName": "", // GULF bölgesi için gelecektir.
                "addressLines": {
                    "addressLine1": "",
                    "addressLine2": ""
                },
                "postalCode": "34200",
                "countryCode": "TR",
                "neighborhoodId": 21111,
                "neighborhood": "Maslak Mahallesi",
                "phone": null,
                "fullAddress": "DSM Grup Danışmanlık İletişim ve Satış Ticaret A.Ş. Maslak Mahallesi Saat Sokak Spine Tower No:5 İç Kapı No:19 Sarıyer/İstanbul",
                "fullName": "Trendyol Customer"
            },
            "orderNumber": "10654411111",
            "grossAmount": 498.90,
            "packageGrossAmount": 498.90,
            "totalDiscount": 0.00,
            "packageSellerDiscount": 0.00,
            "totalTyDiscount": 0.00, // commercial true olduğu durumda dolu gelebilir, false olduğu durumda 0 dönecektir.
            "packageTyDiscount": 0.00, // commercial true olduğu durumda dolu gelebilir, false olduğu durumda 0 dönecektir.
            "packageTotalDiscount": 0.00,
            "discountDisplays": [
                {
                    "displayName": "Sepette %20 İndirim",
                    "discountAmount": 100
                },
                {
                    "displayName": "Trendyol Plus'a Özel Fiyat",
                    "discountAmount": 67.2
                },
                {
                    "displayName": "Sepette %50 İndirim",
                    "discountAmount": 500
                },
                {
                    "displayName": "Sepette %30 İndirim",
                    "discountAmount": 60
                }
            ],
            "taxNumber": null,
            "invoiceAddress": {
                "id": 11111112,
                "firstName": "Trendyol",
                "lastName": "Customer",
                "company": "", // GULF bölgesi siparişlerinde boş gelebilir.
                "address1": "DSM Grup Danışmanlık İletişim ve Satış Ticaret A.Ş. Maslak Mahallesi Saat Sokak Spine Tower No:5 İç Kapı No:19 Sarıyer/İstanbul",
                "address2": "",
                "city": "İstanbul",
                "cityCode": 0,
                "district": "Sarıyer", // GULF bölgesi siparişlerinde boş gelebilir.
                "districtId": 54,
                "countyId": 0, // CEE bölgesi için gelecektir.
                "countyName": "", // CEE bölgesi için gelecektir.
                "shortAddress": "", // GULF bölgesi için gelecektir.
                "stateName": "", // GULF bölgesi için gelecektir.
                "addressLines": {
                    "addressLine1": "",
                    "addressLine2": ""
                },
                "postalCode": "", // GULF bölgesi siparişlerinde boş gelebilir.
                "countryCode": "TR",
                "neighborhoodId": 0,
                "phone": null,
                "latitude": "11.111111",
                "longitude": "22.222222",
                "fullAddress": "DSM Grup Danışmanlık İletişim ve Satış Ticaret A.Ş. Maslak Mahallesi Saat Sokak Spine Tower No:5 İç Kapı No:19 Sarıyer/İstanbul",
                "fullName": "Trendyol Customer",
                "taxOffice": "Company of OMS's Tax Office", // Kurumsal fatura olmadığı durumda (commercial=false ise) body içerisinde dönmeyecektir.
                "taxNumber": "Company of OMS's Tax Number" // Kurumsal fatura olmadığı durumda (commercial=false ise)) body içerisinde dönmeyecektir.
            },
            "customerFirstName": "Trendyol",
            "customerEmail": "pf+j1jm1x11@trendyolmail.com",
            "customerId": 1451111111,
            "supplierId": 2738,
            "customerLastName": "Customer",
            "id": 33301111111,
            "shipmentPackageId": 3330111111,
            "cargoTrackingNumber": 7280027504111111,
            "cargoTrackingLink": "https://tracking.trendyol.com/?id=111111111-1111-1111-1111-11111111",
            "cargoSenderNumber": "210090111111",
            "cargoProviderName": "Trendyol Express",
            "lines": [
                {
                    "quantity": 1,
                    "salesCampaignId": 11,
                    "productSize": "Tek Ebat",
                    "merchantSku": "111111",
                    "sku": "8683771111111",
                    "stockCode": "111111",
                    "productName": "Kuş ve Çiçek Desenli Tepsi - Yeşil / Altın Sarısı - 49 cm, 01SYM134, Tek Ebat",
                    "productCode": 1239111111,
                    "contentId": 1239111111,
                    "productOrigin": "TR",
                    "merchantId": 2738,
                    "sellerId": 2738,
                    "amount": 498.90,
                    "lineGrossAmount": 498.90,
                    "discount": 0.00,
                    "lineTotalDiscount": 0.00,
                    "lineSellerDiscount": 0.00,
                    "tyDiscount": 0.00,
                    "lineTyDiscount": 0.00,
                    "discountDetails": [
                        {
                            "lineItemPrice": 498.90,
                            "lineItemDiscount": 0.00,
                            "lineItemSellerDiscount": 0.00,
                            "lineItemTyDiscount": 0.00
                        }
                    ],
                    "currencyCode": "TRY",
                    "productColor": "Yeşil",
                    "id": 4765111111,
                    "lineId": 4765111111,
                    "vatBaseAmount": 20.00,
                    "vatRate": 20.00,
                    "barcode": "8683772071724",
                    "orderLineItemStatusName": "Delivered",
                    "price": 498.90,
                    "lineUnitPrice": 498.90,
                    "fastDeliveryOptions": [],
                    "productCategoryId": 2710,
                    "commission": 13,
                    "businessUnit": "Sports Shoes",
                    "cancelledBy": "",
                    "cancelReason": "",
                    "cancelReasonCode":
                }
            ],
            "orderDate": 1762253333685,
            "identityNumber": "11111111111",
            "currencyCode": "TRY",
            "packageHistories": [
                {
                    "createdDate": 1762242537624,
                    "status": "Awaiting"
                },
                {
                    "createdDate": 1762242543616,
                    "status": "Created"
                },
                {
                    "createdDate": 1762246983623,
                    "status": "Invoiced"
                },
                {
                    "createdDate": 1762246983623,
                    "status": "Picking"
                },
                {
                    "createdDate": 1762352727000,
                    "status": "Shipped"
                },
                {
                    "createdDate": 1762860180000,
                    "status": "Delivered"
                }
            ],
            "shipmentPackageStatus": "Delivered",
            "status": "Delivered",
            "whoPays": 1, // Eğer satıcı anlaşması ise 1 gelir, trendyol anlaşması ise alan gelmez
            "deliveryType": "normal",
            "timeSlotId": 0,
            "estimatedDeliveryStartDate": 1762858136000,
            "estimatedDeliveryEndDate": 1763030936000,
            "totalPrice": 498.90,
            "packageTotalPrice": 498.90,
            "deliveryAddressType": "Shipment",
            "agreedDeliveryDate": 1762376340000,
            "fastDelivery": false,
            "originShipmentDate": 1762242537619,
            "lastModifiedDate": 1762865408581,
            "commercial": false,
            "fastDeliveryType": "",
            "deliveredByService": false,
            "warehouseId": 372389,
            "invoiceLink": "https://efatura01.evidea.com/11111111111",
            "micro": true,
            "giftBoxRequested": false,
            "3pByTrendyol": false,
            "etgbNo": "25341453EX025864", // micro true olduğunda etgbNo alanı için bilgi dönecektir.
            "etgbDate": 1762646400000, // micro true olduğunda etgbDate alanı için bilgi dönecektir.
            "containsDangerousProduct": false, // micro ihracat siparişlerinde satıcıya gelen siparişte paket içerisinde herhangi bir tehlikeli ürün varsa pil, parfüm vb. gibi, true dönecektir.
            "cargoDeci": 10,
            "isCod": false,
            "createdBy": "order-creation", // Paketin nasıl oluşturulduğunu gösterir, "order-creation", "split", "cancel" veya "transfer" olabilir
            "originPackageIds": null, // Bu alan iptal veya bölme işlemlerinden sonra doldurulur ve bu işlemlerden sonra ilk paketin packageid'sini verir.
            "hsCode": "711111000000", // Bu alan mikro siparişler için string olarak dönecektir.
            "shipmentNumber": 606404425
        }
    ]
}
Paket Statüleri

Statü	Açıklama
orderDate	Müşterinin trendyol.com üzerinde siparişi oluşturduğu zaman dönmektedir.
Awaiting	Müşterinin trendyol.com üzerinde siparişi oluşturduktan sonra ödeme onayından bekleyen siparişler için bu statü dönmektedir. (Bu statüdeki siparişler "Created" statüsüne geçene kadar herhangi bir işlem yapmamanız gerekmektedir. Sadece stok güncellemeleri için bu statüyü kullanabilirsiniz.)
Created	Sipariş gönderime hazır statüsünde olduğu zaman dönmektedir.
Picking	Sizin tarafınızdan iletilebilecek bir statüdür. Siparişi toplamaya başladığınız zaman veya paketi hazırlamaya başladığınız zaman iletebilirsiniz.
Invoiced	Siparişin faturasını kestiğiniz zaman bize iletebileceğiniz statüdür.
Shipped	Taşıma durumuna geçen siparişler bu statüde belirtilmektedir.
AtCollectionPoint	Ürün ilgili PUDO teslimat noktasındadır. Müşterinin PUDO noktasına giderek teslim alması beklenmektedir.
Cancelled	İptal edilen siparişlerdir. Unsupplied siparişleri de kapsar.
UnPacked	Paketi bölünmüş olan siparişlerdir.
Delivered	Teslim edilen siparişlerdir. Bu statüden sonra herhangi bir statü değişikliği yapılamaz.
UnDelivered	Sipariş müşteriye ulaştırılamadığı zaman dönen bilgisidir.
Returned	Müşteriye ulaşmayan siparişin tedarikçiye geri döndüğü bilgisidir. Bu statüden sonra herhangi bir statü değişikliği yapılamaz
Mikro ihracat siparişleri için ülke kodu bilgileri

Ülke	Ülke Kodu
Suudi Arabistan	SA
Birleşik Arap Emirlikleri	AE
Katar	QA
Kuveyt	KW
Umman	OM
Bahreyn	BH
Azerbaycan	AZ
Slovakya	SK
Romanya	RO
Çekya	CZ




Askıdaki Sipariş Paketlerini Çekme (getShipmentPackages)
Ödeme güvenliğinden geçmekte olan ve kargo firmasından kargo bilgisi beklenen siparişlerinizi, bu method yardımıyla alabilirsiniz.Sistem tarafından ödeme kontrolünden ve kargo bilgileri tamamlandıktan sonra otomatik paketlenerek sipariş paketleri oluşturulur.

Awaiting statüsündeki siparişleri sadece stok kontrolleriniz için kullanabilirsiniz.
Ödeme kontrolünden geçen siparişler artık Created statüsünde sizlere dönecektir.
Ödeme kontrolünden geçmeyen siparişler ise Cancelled statüsünde sizlere dönecektir.
GET getShipmentPackages
PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/orders?status=Awaiting

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/orders?status=Awaiting

Servis Parametreleri

Parametre	Parametre Değer	Açıklama	Tip
startDate		Belirli bir tarihten sonraki siparişleri getirir. Timestamp olarak gönderilmelidir.	long
endDate		Belirtilen tarihe kadar olan siparişleri getirir. Timestamp olarak gönderilmelidir.	long
page		Sadece belirtilen sayfadaki bilgileri döndürür	int
size	Maksimum 200	Bir sayfada listelenecek maksimum adeti belirtir.	int
supplierId		İlgili tedarikçinin ID bilgisi gönderilmelidir	long
orderNumber		Sadece belirli bir sipariş numarası verilerek o siparişin bilgilerini getirir	string
orderByField	LastModifiedDate	Son güncellenme tarihini baz alır.	string
orderByField	CreatedDate	Siparişin oluşma tarihini baz alır	string
orderByDirection	ASC	Eskiden yeniye doğru sıralar.	string
orderByDirection	DESC	Yeniden eskiye doğru sıralar.	string
shipmentPackagesId		Paket numarasıyla sorgu atılır.	long
Sipariş Statüleri

Statü	Açıklama
orderDate	Müşterinin trendyol.com üzerinde siparişi oluşturduğu zaman dönmektedir.
Awaiting	Müşterinin trendyol.com üzerinde siparişi oluşturduktan sonra ödeme onayından bekleyen siparişler için bu statü dönmektedir. (Bu statüdeki siparişler "Created" statüsüne geçene kadar herhangi bir işlem yapmamanız gerekmektedir. Sadece stok güncellemeleri için bu statüyü kullanabilirsiniz.)
Örnek Servis Cevabı

JSON

{
    "page": 0,
    "size": 50,
    "totalPages": 1,
    "totalElements": 1,
    "content": [
        {
            "shipmentAddress": {
                "id": 0,
                "firstName": "***",
                "lastName": "***",
                "address1": "***",
                "address2": "***",
                "addressLines": {
                    "addressLine1": "***",
                    "addressLine2": "***"
                },
                "city": "***",
                "cityCode": 0,
                "district": "***",
                "districtId": 0,
                "countyId": 0, //CEE bölgesi için gelecektir.
                "countyName": "***", //CEE bölgesi için gelecektir.
                "shortAddress": "***", //GULF bölgesi için gelecektir.
                "stateName": "***", //GULF bölgesi için gelecektir.
                "postalCode": "***",
                "countryCode": "***",
                "phone": "***",
                "latitude": "***",
                "longitude": "***",
                "fullAddress": "*** *** *** ***",
                "fullName": "*** ***"
            },
            "orderNumber": "252647418",
            "grossAmount": 55.95,
            "totalDiscount": 0.00,
            "taxNumber": "***",
            "invoiceAddress": {
                "id": 0,
                "firstName": "***",
                "lastName": "***",
                "company": "",
                "address1": "***",
                "address2": "***",
                "addressLines": {
                    "addressLine1": "***",
                    "addressLine2": "***"
                },
                "city": "***",
                "cityCode": 0,
                "district": "***",
                "districtId": 0,
                "countyId": 0, //CEE bölgesi için gelecektir.
                "countyName": "***", //CEE bölgesi için gelecektir.
                "shortAddress": "***", //GULF bölgesi için gelecektir.
                "stateName": "***", //GULF bölgesi için gelecektir.
                "postalCode": "***",
                "countryCode": "***",
                "phone": "***",
                "latitude": "***",
                "longitude": "***",
                "fullAddress": "*** *** *** ***",
                "fullName": "*** ***"
            },
            "customerFirstName": "***",
            "customerEmail": "***",
            "customerId": 0,
            "customerLastName": "***",
            "id": 0,
            "cargoTrackingNumber": 0,
            "cargoProviderName": "***",
            "lines": [
                {
                    "quantity": 1,
                    "productId": 197197197,
                    "salesCampaignId": 111111,
                    "productSize": "L",
                    "merchantSku": "merchantSku",
                    "productName": "Kadın Siyah Pantolon",
                    "productCode": 554554554,
                    "amount": 55.95,
                    "discount": 0,
                    "discountDetails": [
                        {
                            "lineItemPrice": 55.95,
                            "lineItemDiscount": 0
                        }
                    ],
                    "currencyCode": "TRY",
                    "productColor": "SIYAH",
                    "id": 444444444,
                    "sku": "skue",
                    "vatBaseAmount": 8.0,
                    "barcode": "6000001036071",
                    "orderLineItemStatusName": "Approved",
                    "price": 55.95,
                    "productCategoryId": 11111,
                    "laborCost": 11.11,
                    "commission": 9,
                    "businessUnit": "Sports Shoes"
                }
            ],
            "orderDate": 1583327549228,
            "identityNumber": "0000000000000",
            "currencyCode": "TRY",
            "packageHistories": [
                {
                    "createdDate": 0,
                    "status": "Awaiting"
                }
            ],
            "shipmentPackageStatus": "Approved",
            "deliveryType": "normal",
            "estimatedDeliveryStartDate": 1583392349000,
            "estimatedDeliveryEndDate": 1583824349000,
            "totalPrice": 55.95,
            "cargoDeci": 0,
            "isCod": false,
            "createdBy": "",
            "originPackageIds": null,
            "whoPays": null,
            "hsCode": "",
            "shipmentNumber": 606404425
        }
    ]
}



Paket Statü Bildirimi (updatePackage)
Siparişe ait paketi sadece 2 paket statüsü ile güncelleyebilirsiniz. Bu statüler haricindekiler sistem tarafından otomatik olarak pakete aktarılmaktadır. Aşağıda statülerle ilgili detaylı bilgiye ulaşabilirsiniz.

Statü beslemelerini yaparken önce "Picking" sonra "Invoiced" statü beslemesi yapmanız gerekmektedir.
PUT updatePackage (Toplanmaya Başlandı Bildirimi - Picking)
Picking statüsü beslediğiniz an Trendyol panelinde "Sipariş İşleme Alınmıştır" ifadesi gözükecektir. Bu statü ile kendi tarafınızda siparişlerinize ait durumu kontrol edebilirsiniz.

PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}

Örnek Servis İsteği

JSON

{
    "lines": [
        {
        "lineId": {lineId}, // long gönderilmelidir.
        "quantity": 3 // int gönderilmelidir.
        }
    ],
    "params": {},
    "status": "Picking"
}
PUT updatePackage (Fatura Kesme Bildirimi - Invoiced)
Invoiced statüsü beslediğiniz an Trendyol panelinde "Sipariş İşleme Alınmıştır" ifadesi gözükecektir. Bu statü ile kendi tarafınızda siparişlerinize ait durumu kontrol edebilirsiniz.

PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}

Örnek Servis İsteği

JSON

{
    "lines": [
        {
        "lineId": {lineId}, // long gönderilmelidir.
        "quantity": 3 // int gönderilmelidir.
    }
    ],
    "params": {
        "invoiceNumber": "EME2018000025208"
    },
    "status": "Invoiced"
}



Tedarik Edememe Bildirimi (updatePackage)
Tedarikçinin paket içerisindeki ürünlerden bir ya da birkaçını Tedarik Edememe kaynaklı iptal etmesi için kullanılır. Bu method yardımıyla yapılan bir iptal sonrası, iptal edilen paket bozularak yeni ID’li bir paket oluşturulacaktır.

Tedarik edememe bildirimi yapıldıktan sonra Trendyol Order Management System tarafından aynı orderNumber üzerinde yeni bir ShipmentPackageID oluşturulmakta ve daha önceki shipmentpackage iptal edilmektedir. Bu durumda Tedarik Edememe kaydı yapıldıktan sonra tekrar Sipariş Paketlerini Çekme işlemi yapılması gerekmektedir.
Hayır

Evet

Evet

Hayır

Satıcı Picking statüsünü besler (putUpdatePackage)

Satıcı Invoiced (opsiyonel) statusunu besler (putUpdatePackage)

Mevcut shipmentpackageid ve cargoTrackingNumber ile gönderim sağlanır (getShipmentPackages)

Tedarik edememe sebepli iptal edilecek mi? (shipmentpackageId)

Paket oluşturulur

Paketin tamamına iptal isteği yapılır (putUpdatePackage)

Paketin statusu Cancelled olur. Satıcı getShipmentPackage servisinden iptal edilen siparişi görebilir (getShipmentPackages)

Siparişin tamamı mı iptal edilecek? (shipmentpackageId)

Pakete kısmi iptal isteği yapılır (putUpdatePackage)

Mevcut sipariş paketi bozulur ve statüsü Cancelled olarak güncellenir

Aynı ordernumber altında yeni shipmentpackageid ve cargoTrackingNumber oluşur

Yeni paket bilgileri getShipmentPackage servisinden alınır veya veya Webhook yapısı ile dinlenir (getShipmentPackages)

PUT updatePackage
PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/items/unsupplied

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/items/unsupplied

Örnek Servis İsteği

JSON

{
 "lines": [
   {
     "lineId": 0,
     "quantity": 0
   }
 ],
"reasonId":0
 }
Tedarik Edememe Nedenleri

reasonId	name	description
500	Stok tükendi	Ürünün stoğu tükenmesi ve gönderimin gecikmesi gibi sebeplerle tedarik edilememesi durumunda seçilmelidir.
501	Kusurlu/Defolu/Bozuk Ürün	Ürün kusurlu/defolu/bozuk olduğu için gönderilememesi durumunda seçilmelidir.
502	Hatalı Fiyat	Yanlış fiyat beslenmesi durumunda seçilmelidir.
504	Entegrasyon Hatası	Entegrasyon firmasından kaynaklı olarak hatalı fiyat ya da stok aktarımında yaşanan sorunlarda seçilmelidir.
505	Toplu Alım	Üründe yapılan indirim sonrası tek bir üründen ve aynı müşteri tarafından toplu olarak satın alınması durumunda seçilmelidir.
506	Mücbir Sebep	Doğal afet, hastalık, cenaze vb. durumlarda seçilmelidir




Sipariş Paketlerini Bölme (splitShipmentPackage)
Bu servis ile Trendyol üzerinde oluşmuş siparişlerinizi birden fazla paket haline getirebilirsiniz. Bu servisi kulandıktan sonra sipariş numarasına bağlı yeni paketler "UnPacked" statüsünde, asenkron olarak oluşacaktır. Bu nedenle Sipariş Paketlerini Çekme servisinden tekrar güncel paketleri çekmelisiniz.

Hayır

Evet

Satıcı Picking statüsünü besler (putUpdatePackage)

Satıcı Invoiced (opsiyonel) statusunu besler (putUpdatePackage)

Mevcut shipmentpackageid ve cargoTrackingNumber ile gönderim sağlanır

Paket bölünecek mi (shipmentpackageId)

Paket oluşturulur

Bölme isteği yapılır (postSplitShipmentPackage)

Mevcut sipariş paketi bozulur ve statüsü UnPacked olarak güncellenir

Yeni paket bilgileri getShipmentPackages servisinden alınır veya veya Webhook yapısı ile dinlenir (getShipmentPackages)

Aynı ordernumber altında yeni shipmentPackageId ve cargoTrackingNumber oluşur




🤖
Not: Bu videodaki seslendirme ve içerikler, dokümantasyon kaynaklarımız kullanılarak Google NotebookLM yapay zekası ile oluşturulmuştur.


Sipariş Paketlerini Birden Fazla Barkod İle Bölme
Bu servisi kulandıktan sonra sipariş numarasına bağlı yeni paketler asenkron olarak oluşacaktır. Bu nedenle Sipariş Paketlerini Çekme servisinden tekrar güncel paketleri çekmelisiniz.

Bu method ile bir sipariş paketinin içerisinde olan ürünleri miktar ve ilgili barkodun orderLineId değeri ile pakette toplayarak işlem yapabilirsiniz.

Eğer istek atarken dışarıda bıraktığınız bir ürün/ler olursa o ürün/ler ayrı ve yeni bir pakette oluşacaktır.
POST splitMultiPackageByQuantity
PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/split-packages

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/split-packages

Örnek Servis İsteği

JSON

{
  "splitPackages": [
    {
      "packageDetails": [
        {
          "orderLineId": 12345,
          "quantities": 2
        },
        {
          "orderLineId": 123456,
          "quantities": 1
        }
      ]
    },
    {
      "packageDetails": [
        {
          "orderLineId": 123,
          "quantities": 1
        },
        {
          "orderLineId": 1234,
          "quantities": 1
        }
      ]
    }
  ]
}
POST splitShipmentPackage
PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/split

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/split

Örnek Servis İsteği

JSON

{
 "orderLineIds": [{orderLineId}]
}
Sipariş Paketlerini Bölme (Tek Request İle Birden Fazla Paket Oluşturma)
Bu servisi kulandıktan sonra sipariş numarasına bağlı yeni paketler asenkron olarak oluşacaktır. Bu nedenle Sipariş Paketlerini Çekme servisinden tekrar güncel paketleri çekmelisiniz.

POST splitShipmentPackage
PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/multi-split

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/multi-split

Örnek Servis İsteği

Örnekte paket içerisineki 3,5,6 orderLine’ları için bir paket, 7,8,9 orderLine’ları için başka bir paket ve kalan orderLine’lar için de bir tane olmak üzere 3 paket oluşacaktır.

Bir paket üzerinde üzerindeki bütün orderLine’lar bu servis gönderilmemelidir. Kalan orderLine’lar için otomatik paket zaten sistem tarafından yaratılacaktır.
JSON

{
    "splitGroups": [{
            "orderLineIds": [
                3, 5, 6
            ]
        },
        {
            "orderLineIds": [
                7, 8, 9
            ]
        }

    ]
}
Sipariş Paketlerini Barkod Bazlı Bölme
Bu servisi kulandıktan sonra sipariş numarasına bağlı yeni paketler asenkron olarak oluşacaktır. Bu nedenle Sipariş Paketlerini Çekme servisinden tekrar güncel paketleri çekmelisiniz.

POST splitShipmentPackageByQuantity
PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/quantity-split

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/quantity-split

Örnek Servis İsteği

JSON

{
  "quantitySplit": [
    {
      "orderLineId": 0,
      "quantities": [
       2,2
       ]
    }
  ]
}



Desi ve Koli Bilgisi Bildirimi (updateBoxInfo)
Bu servis ile Horoz ve CEVA Lojistik firmalarına ait sipariş paketleriniz için desi ve koli bilgisi besleyebilirsiniz.

Horoz ve CEVA Lojistik için "boxQuantity" ve "deci" değerleri zorunludur.
PUT updateBoxInfo
PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/box-info

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/box-info

Örnek Servis İsteği

JSON

{
  "boxQuantity": 4,
  "deci": 4.4
}



Alternatif Teslimat İle Gönderim
Oluşturularan sipariş paketinin müşteriye teslim etmek için alternatif gönderim seçeneklerinin kullanıldığı ve bu işlemleri Trendyol'a aşağıdaki servisler ile iletebilirsiniz.*

PUT processAlternativeDelivery (Kargo Linki ile Gönderim)
Sipariş paketini gönderdikten sonra elinizde olan kargo takip linki ile besleme yapabilirsiniz. Bu isteği başarılı bir şekilde ilettikten sonra sipariş otomatik olarak "Shipped" (Taşıma Durumunda) statüsüne geçecektir.

PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/alternative-delivery

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/alternative-delivery

Örnek Servis İsteği

JSON

{
"isPhoneNumber": false,
"trackingInfo": "http://tex....", //Kargo firmasının takip linki paylaşılmalıdır.
"params": {}
}
PUT processAlternativeDelivery (Telefon Numarası ile Gönderim)
Sipariş paketini gönderdikten sonra siparişin durumu ile alakalı müşterilerin bilgi alabileceği bir telefon numarası ile besleme yapabilirsiniz. Bu isteği başarılı bir şekilde ilettikten sonra sipariş otomatik olarak "Shipped" (Taşıma Durumunda) statüsüne geçecektir.

PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/alternative-delivery

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/alternative-delivery

Örnek Servis İsteği

JSON

{
"isPhoneNumber": true,
"trackingInfo": "5555555555",
"params":{},
"boxQuantity": 1,
"deci": 1.4
}
Data Tipleri

Alan	Data Tipi	Açıklama	Zorunluluk
isPhoneNumber	bool	her zaman "true" olmalıdır	Zorunlu
trackingInfo	string	Teslim edecek kişinin telefon numarası	Zorunlu
params	map	Her zaman boş olmalıdır	Zorunlu
boxQuantity	int	Kutu Sayısı	Opsiyonel
deci	float64	Paketin Desi miktarı	Opsiyonel
Örnek Servis Cevapları

200 cevabını aldıktan sonra sipariş paketlerini çekme servisinden güncel cargoTrackingNumber değerine ulaşabilir ve bu değer ile müşteri siparişi teslim aldıktan sonra bu değeri bize iletebilirsiniz.

JSON

"200 OK";
PUT manualDeliver - Kargo Takip Numarası (Alternatif Teslimat ile Gönderilmiş Paketi Teslim Etme)
Bu isteği yaparken bir JSON body ihtiyacı yoktur. İsteği attıktan sonra size 200 OK cevabı dönecektir.

PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/manual-deliver/{cargoTrackingNumber}

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/manual-deliver/{cargoTrackingNumber}

PUT manualDeliver - Paket Numarası (Alternatif Teslimat ile Gönderilmiş Paketi Teslim Etme)
Bu isteği yaparken bir JSON body ihtiyacı yoktur. İsteği attıktan sonra size 200 OK cevabı dönecektir.

PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/manual-deliver

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/manual-deliver

Alternatif Teslimat İle İade Gerçekleştirme
PUT manualReturn - Kargo Takip Numarası (Alternatif Teslimat ile Gönderilmiş Paketin Iade Edilmesi)
Bu servisi, tarafınızdan "shipped" statüsüne geçirilip müşteriye teslim edilemediği durumda deponuza geri dönen ve bu sebeple "delivered" statüsüne geçirilemeyen siparişler için kullanabilirsiniz. Bu isteği yaparken bir JSON body ihtiyacı yoktur. İsteği attıktan sonra size 200 OK cevabı dönecektir.

PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/manual-return/{cargoTrackingNumber}

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/manual-return/{cargoTrackingNumber}

PUT manualReturn - Paket Numarası (Alternatif Teslimat ile Gönderilmiş Paketin İade Edilmesi)
Bu servisi, tarafınızdan "shipped" statüsüne geçirilip müşteriye teslim edilemediği durumda deponuza geri dönen ve bu sebeple "delivered" statüsüne geçirilemeyen siparişler için kullanabilirsiniz. Bu isteği yaparken bir JSON body ihtiyacı yoktur. İsteği attıktan sonra size 200 OK cevabı dönecektir.

PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/manual-return

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/manual-return

Alternatif Teslimat İle Dijital Ürün Gönderimi
PUT processAlternativeDelivery (Dijital Ürün Teslimatı)
Bu servisi çağırdığınız zaman verdiğiniz bilgiler müşterilere otomatik olarak sms ve e-mail olarak iletilecektir.

digitalCode alanı 6-120 karakter arasında olmalıdır.
Sipariş paketleri çekme servisi ya da webhook modelde businessUnit alanı "Digital Goods" olmayan bir sipariş paketi için dijital kod gönderimi yapılmak istendiği durumda; sistem tarafından "digital.good.business.unit.not.valid" hatası dönecektir.
PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/alternative-delivery

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/alternative-delivery

Örnek Servis İsteği

Dijital ürünler için var olan bu serviste siparişin teslim edildi bilgisi Trendyol tarafından otomatik iletilecektir.

JSON

{
"isPhoneNumber": true,
"trackingInfo": "5555555555",
"params":
{
    "digitalCode": "AX4567fasdf"
}
}



Yetkili Servis İle Gönderim
Ürünlerini yetkili servise kargolayan satıcılarımızın bu servisi çağırmaları gerekmektedir

Lojistik firmalarıyla Tedarikçi Öder entegrasyonu yapan ve ürünlerini yetkili servise kargolayan satıcılarımızın bu servisi çağırmaları gerekmektedir. (Mevcut durumda lojistik firmalarından sadece Horoz Lojistik ile tedarikçi öder çalışmamız bulunmaktadır.)

Paket shipped statusune geçirilene kadar herhangi bir zamanda bu servis çağırılabilir
PUT delivered-by-service
PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/delivered-by-service

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/delivered-by-service




Paket Kargo Firması Değiştirme(changeCargoProvider)
Bu metod sipariş paketlerinin kargo firmalarının değiştirilmesi için kullanılmaktadır.

Bu işlem bir paket için 5 dakika içerisinde yalnızca 1 kere yapılabilir.
Kargo değişiminden sonra ilgili paketi sipariş servisimizden tekrar çekerek kontrol etmeniz gerekmektedir.
Kargo firması TEX olarak gönderilen güncelleme istekleri satıcının TEX kotasının dolduğu durumlarda geçersiz olacaktır.
PUT changeCargoProvider (Paket Kargo Firması Değiştirme)
PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/cargo-providers

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/cargo-providers

Örnek Servis İsteği

JSON

{
  "cargoProvider": "string"
}
cargoProvider değeri için kullanılabilecek değerler aşağıdaki gibidir :

“YKMP”
“ARASMP”
“SURATMP”
“HOROZMP”
“DHLECOMMP”
“PTTMP”
“CEVAMP”
“TEXMP”
"KOLAYGELSINMP"
"CEVATEDARIK"



Depo Bilgisi Güncelleme
Bu servis sadece Trendyol Express kullanan satıcılarımız için geçerli olacaktır. Bu servis ile Sipariş Paketlerini Çekme servisinden dönen "WarehouseId" alanı güncellenebilecektir.

Eğer sevkiyat adresi eklenmesi isteniyor ise satıcı paneli üzerinden ekleme yapılabilmektedir.
PUT updateWarehouse
PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/warehouse

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/warehouse

Örnek Servis İsteği

JSON

{
	“warehouseId”: int
}
Başarılı Servis Cevabı

JSON

"200 OK";
Hatalı Servis Cevabı

JSON

"400 Bad Request"; // paket statusu update etmeye uygun değilse (Created, Invoiced, Picking dışında ise)



Test Siparişlerinde Statü Güncellemeleri
Test senaryolarınızı gerçekleştirmek adına stage ortamda vermiş olduğunuz siparişler için statüleri aşağıdaki servis aracılığıyla "Shipped", "AtCollectionPoint", "Delivered", "UnDelivered" ve "Returned" olarak güncelleyebilirsiniz.

Bu servis sadece stage ortamı için kullanılmaktadır.
Header içinde SellerID gönderilmelidir. Değeri ise kullanmış olduğunuz test satıcısının satıcıId si olmalıdır.
Header içerisinde göndermiş olduğunuz satıcıId ile basic authentication yapmanız gerekmektedir.
Statüler sıralı ilerlemektedir. Örneğin "Delivered" olan bir paket "AtCollectionPoint" ve "Shipped" statüsüne geri çekilemez.
Status	Açıklama
Shipped	Paket kargoya verildi
AtCollectionPoint	Paket kargo firmasının dağıtım noktasına ulaştı
Delivered	Paket teslimat noktasına ulaştı
UnDelivered	Paket teslim edilemedi (kargonun dağıtım merkezine geri döndü)
Returned	Paket geri gönderildi
Method PUT
STAGE
https://stageapigw.trendyol.com/integration/test/order/sellers/{sellerId}/shipment-packages/{packageId}/status

Örnek Servis İsteği

JSON

{
    "lines": [
        {
            "lineId": 4944785,
            "quantity": 1
        }
    ],
    "params": {
    },
    "status": "Delivered"
}
Başarılı Servis Cevabı

JSON

"200 OK";
İade Test Siparişlerini WaitingInAction Statüsüne Çekme
Test senaryolarınızı gerçekleştirmek adına stage ortamda vermiş olduğunuz siparişler için yaratmış olduğunuz iade talepleri sonrasında iade statüsünü waitinginaction'a çekmek için aşağıdaki servisi kullanabilirsiniz.

Bu servis sadece stage ortamı için kullanılmaktadır.
Method PUT
📘
STAGE

https://stageapigw.trendyol.com/integration/test/order/sellers/{sellerId}/claims/waiting-in-action
Örnek Servis İsteği

JSON

{
    "shipmentPackageId": 56526451 // getClaims servisinden dönen "orderShipmentPackageId" değerine karşılık gelmektedir,
}
Başarılı Servis Cevabı

JSON

"200 OK";



Adres Bilgileri
Sipariş paketlerini çekme servisinden dönen adres bilgilerine aşağıdaki servisler üzerinden ulaşabilirsiniz.

Ülke Bilgisi
HTTP METHOD: GET

Ülke bilgisine aşağıdaki servisten ulaşabilirsiniz.

Servis Endpointleri

PROD
https://apigw.trendyol.com/integration/member/countries

STAGE
https://stageapigw.trendyol.com/integration/member/countries

GULF ve CEE Ülkeleri İçin İl Bilgisi
HTTP METHOD: GET

Gulf ve Cee ülkeleri için ilgili ülke kodu ile o ülkenin il bilgisine aşağıdaki servisten ulaşabilirsiniz.

CountryCode bilgisini ülke bilgisi servisinden dönen "code" alanından almalısınız.
Servis Endpointleri

PROD
https://apigw.trendyol.com/integration/member/countries/{CountryCode}/cities

STAGE
https://stageapigw.trendyol.com/integration/member/countries/{CountryCode}/cities

CEE ülkeleri için ilçe bilgisi servisimizde bulunmamaktadır.
GULF Ülkeleri İçin İlçe Bilgisi
HTTP METHOD: GET

Gulf ülkeleri için ilçe bilgilerine aşağıdaki servisten ulaşabilirsiniz.

CityCode bilgisini il bilgisi servisinden dönen "id" alanından almalısınız.
Servis Endpointleri

PROD
https://apigw.trendyol.com/integration/member/countries/{CountryCode}/cities/{cityId}/districts

STAGE
https://stageapigw.trendyol.com/integration/member/countries/{CountryCode}/cities/{cityId}/districts

Azerbaycan İçin İl Bilgisi
HTTP METHOD: GET

Azerbaycan için il bilgilerine aşağıdaki servisten ulaşabilirsiniz.

Servis Endpointleri

PROD
https://apigw.trendyol.com/integration/member/countries/domestic/AZ/cities

STAGE
https://stageapigw.trendyol.com/integration/member/countries/domestic/AZ/cities

Azerbaycan İçin İlçe Bilgisi
HTTP METHOD: GET

Azerbaycan için ilçe bilgilerine aşağıdaki servisten ulaşabilirsiniz.

CityCode bilgisini il bilgisi servisinden dönen "id" alanından almalısınız.
Servis Endpointleri

PROD
https://apigw.trendyol.com/integration/member/countries/domestic/AZ/cities/{cityCode}/districts

STAGE
https://stageapigw.trendyol.com/integration/member/countries/domestic/AZ/cities/{cityCode}/districts

Türkiye İçin İl Bilgisi
HTTP METHOD: GET

Türkiye için il bilgisine aşağıdaki servisten ulaşabilirsiniz.

Servis Endpointleri

PROD
https://apigw.trendyol.com/integration/member/countries/domestic/TR/cities

STAGE
https://stageapigw.trendyol.com/integration/member/countries/domestic/TR/cities

Türkiye İçin İlçe Bilgisi
HTTP METHOD: GET

Türkiye için ilçe bilgilerine aşağıdaki servisten ulaşabilirsiniz.

CityCode bilgisini il bilgisi servisinden dönen "id" alanından almalısınız.
Servis Endpointleri

PROD
https://apigw.trendyol.com/integration/member/countries/domestic/TR/cities/{CityCode}/districts

STAGE
https://stageapigw.trendyol.com/integration/member/countries/domestic/TR/cities/{CityCode}/districts

Türkiye İçin Mahalle Bilgisi
HTTP METHOD: GET

Türkiye için mahalle bilgilerine aşağıdaki servisten ulaşabilirsiniz.

CityCode bilgisini il bilgisi servisinden dönen "id" alanından almalısınız.
DistrictCode bilgisini ilçe bilgisi servisinden dönen "id" alanından almalısınız.
Servis Endpointleri

PROD
https://apigw.trendyol.com/integration/member/countries/domestic/TR/cities/{CityCode}/districts/{DistrictCode}/neighborhoods

STAGE
https://stageapigw.trendyol.com/integration/member/countries/domestic/TR/cities/{CityCode}/districts/{DistrictCode}/neighborhoods


İşçilik Bedeli Tutarı Gönderme
İşçilik bedeli tutarını beslemek için bu servisi kullanmanız gerekmektedir.

"laborCostPerItem" alanı line üzerindeki tek bir item için işçilik bedeline karşılık gelmektedir.
Paket statusu "delivered" olana kadar bu besleme yapılabilir, "delivered" statusu sonrası güncelleme yapılamaz.
"laborCostPerItem" 0'dan küçük olamaz, itemin faturalandırılacak tutarından büyük olamaz.
Yalnızca belirli kategorid'ler için beslenebilir, kategori id listesine aşağıdaki tablodan ulaşabilirsiniz.
Bu servis ile paket statusu "delivered" olana kadar güncellenebilir.
"laborCostPerItem" beslenmesi zorunlu değildir.
Girilen değerler sipariş paketlerini çekme servisinden ilerleyen dönemde dönecektir. ("lines" alanı altından.)
İşçilik Bedeli Tutarı Gönderme
HTTP METHOD: PUT

PROD
https://apigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/labor-costs

STAGE
https://stageapigw.trendyol.com/integration/order/sellers/{sellerId}/shipment-packages/{packageId}/labor-costs

Örnek Servis İsteği

JSON

[
  {
    orderLineId: 3653527482,
    laborCostPerItem: 32.12,
  },
  {
    orderLineId: 3653527483,
    laborCostPerItem: 78.65,
  },
];
Başarılı Servis Cevabı

JSON

"200 OK";
İşcilik Bedeli Beslenmesi Gereken Kategori Listesi

MainCategory	SubCategory	CategoryId
Mücevher	Altın Bileklik	1238
Mücevher	Pırlanta Bileklik	1240
Mücevher	Altın Kolye	1246
Mücevher	Pırlanta Kolye	1248
Mücevher	Altın Küpe	1254
Mücevher	Pırlanta Küpe	1256
Mücevher	Altın Yüzük	1258
Mücevher	Pırlanta Yüzük	1260
Mücevher	Altın Set & Takım	1264
Mücevher	Pırlanta Set & Takım	1266
Mücevher	Altın Kıkırdak Küpe	3418
Mücevher	Pırlanta Kıkırdak Küpe	3419
Mücevher	Altın Halhal	3501
Mücevher	Altın Şahmeran	3504
Mücevher	Elmas Bileklik	3883
Mücevher	Elmas Kolye	3884
Mücevher	Elmas Küpe	3885
Mücevher	Elmas Yüzük	3886
Mücevher	Elmas Set & Takım	3887
Mücevher	Altın Kolye Ucu	5255
Sarrafiye	Tam Altın	1229
Sarrafiye	Yarım Altın	1230
Sarrafiye	Çeyrek Altın	1231
Sarrafiye	Gram Altın	1232
Sarrafiye	Cumhuriyet Altını	1234
Sarrafiye	Reşat Altın	1236
Sarrafiye	Ata Altın	1237
Sarrafiye	Yatırımlık Altın Bilezik	3017
Sarrafiye	Gram Gümüş	4050
Sarrafiye	Sarrafiyeli Takılar	5317
Takı	Gümüş Bileklik	1239
Takı	Gümüş Halhal	3499
Takı	Gümüş Kıkırdak Küpe	3416
Takı	Gümüş Kolye	1247
Takı	Gümüş Küpe	1255
Takı	Gümüş Şahmeran	3502
Takı	Gümüş Set & Takım	1265
Takı	Gümüş Yüzük	1259
Takı	İnci Bileklik	3171
Takı	İnci Kolye	3168
Takı	İnci Küpe	3170
Takı	İnci Set Takım	5209
Takı	İnci Yüzük	3169
Mücevher	Altın Alyans	5597
Takı	Gümüş Alyans	5598
