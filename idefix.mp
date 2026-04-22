Authorization

Auth için kullanılan API KEY ve API SECRET KEY bilgilerini oluşturabilmek için Satıcı Paneli’nde yer alan “Hesap Bilgilerim” menüsü altındaki “Entegrasyon Bilgileri” sayfasına giriş yapılarak Yeni API Oluştur butonuna basılmalıdır. Bu işlem sonrasında API KEY ve API SECRET KEY bilgileri, satıcının sistemde kayıtlı e-posta adresine gönderilecektir.

Auth bilgileri prod ve stage ortamlarında farklılık göstermektedir. Alınan bilgiler aşağıdaki formatta kullanılarak ilgili servislerde token oluşturulmalıdır:

VENDOR TOKEN = base64_encode(ApiKEY:ApiSecret)



Entegrasyon servislerine yapılacak isteklerde alınan token, header içerisinde API key tipinde X-API-KEY olarak gönderilmelidir.
❗ Güvenlik Uyarısı: API bilgileri üzerinden tüm entegrasyon işlemleri yapılabildiği için API KEY ve API SECRET KEY bilgilerinizin dışarıya açık herhangi bir platformda paylaşılmaması gerekmektedir.
Örneğin;

Api Key: 8ce68391-d7b3-4e24-9842-cfb3sd232312

Secret Key: 16ae16os-d82e-4fa4-aace-83asdloks21

Token: base64_encode(8ce68391-d7b3-4e24-9842-cfb3sd232312:16ae16os-d82e-4fa4-aace-83asdloks21) olacaktır.auth

❗ Yetkilendirme Hatası: Hatalı authorization yapılması durumunda status: 401 ve "message": "VENDOR_TOKEN_NOT_EXIST" mesajı döner.



https://developer.idefix.com/authorization



Sipariş sevkiyatlarının alınması

shipment list/Sevkiyatlar Listesi (list)
idefix sistemine ilettiğiniz ürünler için müşteriler tarafından sipariş edilen ve ödeme kontrolünden geçmiş olan her shipmentin bilgisini bu method ile alabilirsiniz. Satıcı bazında oluşturulan siparişler dokümanlarda shipment olarak adlandırılacaktır.

Shipment datası alınırken gelen orderNumber değeri, ilgili shipment’ın idefix sistemindeki ana sipariş numarasına karşılık gelir. Aynı seviyede yer alan id değeri ise bu sipariş numarasına bağlı oluşturulmuş sevkiyatı temsil eder.
vendor her satıcının unique bir tanımlayıcısıdır. Zorunlu bir alandır.
Bilgilendirme: Kurumsal fatura için isCommercial değeri kontrol edilmelidir. Kurumsal fatura kesilmesi gereken durumda bu değer "1" olarak döner, bireysel fatura olması durumunda " " (boş) olarak döner. (isCommercial = 1) durumunda "company", "taxNumber" ve "taxOffice" bilgilerini invoiceAddress alanından alabilirsiniz. Bireysel faturada (isCommercial = " ") platformun uyguladığı indirim ve kuponlar response içerisinde ilgili parametrelerde 0 olarak döner. isLikeCommercial parametresi bireysel müşterinin kurumsal fatura talep ettiği durumlarda döner ve isCommercial parametresi ile aynı mantıkta çalışır.
GET list
https://merchantapi.idefix.com/oms/{vendorId}/list
* ile belirtilen alanlar zorunlu parametrelerdir.

Parametre Ad	Açıklama
ids	Shipment numarası bazında sorgulama yapılabilir. Birden fazla değer virgül (,) ile gönderilebilir.
orderNumber	Shipment’ın idefix sistemindeki ana sipariş numarasına karşılık gelir.
state	Shipment statüsüne göre sorgulama yapılabilir. Gönderilebilecek state değerleri response tablosunda yer almaktadır.
startDate	Belirli bir tarihten sonraki shipment’lar için sorgulama yapılabilir. Örnek format: 2022/09/30 23:59:59
endDate	Belirtilen tarihe kadar olan shipment’lar için sorgulama yapılabilir. Örnek format: 2022/09/30 23:59:59
lastUpdatedAt	Shipment’ın durumunun son güncellenme tarihini baz alır. Örnek format: 2022/09/30 23:59:59
page	Sadece belirtilen sayfadaki verileri döndürür. Default değer: 1
limit	Bir sayfada listelenecek maksimum kayıt adedini belirtir. Default değer: 10
sortByField	Sıralama alanını belirtir. Varsayılan olarak shipment ID’ye göre sıralanır. id, createAt, updateAt parametreleri ile sorgulanabilir.
sortDirection	Sıralama yönünü belirtir. Varsayılan olarak güncel ID’den eski ID’ye doğru sıralanır. desc, asc parametreleri ile sorgulanabilir.
vendor *	İlgili satıcının ID bilgisidir.
Örnek Servis Cevabı:
{
    "totalCount": 1,
    "itemCount": 1,
    "pageCount": 1,
    "currentPage": 1,
    "limit": 20,
    "items": [
        {
            "invoiceAddress": {
                "isCommercial": "",
                "isLikeCommercial": "",
                "id": 21403112,
                "firstName": "Derya",
                "lastName": "Kaya",
                "company": null,
                "address1": "Test adresidir.",
                "city": "İstanbul",
                "cityId": 34,
                "cityPlate": "34",
                "postalCode": "",
                "neighboorhood": "Çengelköy",
                "neighboorhoodId": 34000,
                "county": "Üsküdar",
                "countyId": 1708,
                "countryCode": "TR",
                "phone": "5555555555",
                "fullName": "Derya Kaya",
                "fullAddress": "Test adresidir. Çengelköy İstanbul ",
                "taxOffice": "",
                "taxNumber": "",
                "identificationNumber": "52369854125",
                "floor": "1",
                "buildingNumber": "29",
                "doorNumber": "1"
            },
            "shippingAddress": {
                "isCommercial": "",
                "isLikeCommercial": "",
                "id": 21403112,
                "firstName": "Derya",
                "lastName": "Kaya",
                "company": null,
                "address1": "Test adresidir.",
                "city": "İstanbul",
                "cityId": 34,
                "cityPlate": "34",
                "postalCode": "",
                "neighboorhood": "Çengelköy",
                "neighboorhoodId": 34000,
                "county": "Üsküdar",
                "countyId": 1708,
                "countryCode": "TR",
                "phone": "5555555555",
                "fullName": "Derya Kaya",
                "fullAddress": "Test adresidir.Çengelköy İstanbul ",
                "taxOffice": "",
                "taxNumber": "",
                "identificationNumber": "52369854125",
                "floor": "1",
                "buildingNumber": "29",
                "doorNumber": "1"
            },
            "id": 60000003,
            "orderNumber": "IDE642eabe9bd3b2",
            "totalPrice": 54.9,
            "totalDiscount": 0,
            "discountedTotalPrice": 54.9,
            "totalPlatformDiscount": 0,
            "totalVendorDiscount": 0,
            "customerId": 104710723,
            "customerContactName": "Derya Kaya",
            "customerContactMail": "1000019@idefixcustomer.com",
            "customerTcNumber": null,
            "cargoTrackingNumber": "11111",
            "cargoTrackingUrl": "aaa.com",
            "cargoCompany": "Yurtiçi Kargo",
            "cargoTypeId": 1,
            "cargoTypeName": "delivery",
            "cargoProfileId": 3,
            "cargoProfileName": "Yurtiçi Kargo Satıcı Öder",
            "geoCode": null,
            "createdAt": "2023-04-06T14:27:52+03:00",
            "updatedAt": "2023-04-07T17:23:56+03:00",
            "orderDate": "2023-04-06T11:24:25+03:00",
            "histories": [
                {
                    "state": "created",
                    "createdAt": "2023-04-06T14:27:52+03:00"
                },
                {
                    "state": "shipment_ready",
                    "createdAt": "2023-04-06T14:27:52+03:00"
                },
                {
                    "state": "shipment_in_cargo",
                    "createdAt": "2023-04-07T17:23:56+03:00"
                },
                {
                    "state": "shipment_picking",
                    "createdAt": "2023-04-07T14:02:56+03:00"
                },
                {
                    "state": "shipment_invoiced",
                    "createdAt": "2023-04-07T14:04:09+03:00"
                }
            ],
            "status": "shipment_in_cargo",
            "statusUpdatedAt": "2023-04-07T17:23:56+03:00",
            "deliveryType": "regular",
            "estimatedDeliveryDate": "2023-04-07T15:00:59+03:00",
            "vendorTitle": "idefix",
            "vendorId": 3,
            "statusDescription": "Kargoya Verildi",
            "cargoKey": null,
            "items": [
                {
                    "productName": "İnsanın Anlam Arayışı",
                    "id": 10000043,
                    "barcode": "9786054054206",
                    "erpId": "1284814001",
                    "image": "https://static.idefix.net/resize/{size}product/26388/insanin-anlam-arayisi-642e3f0068526.jpg",
                    "price": 54.9,
                    "totalDiscount": null,
                    "platformDiscount": 0,
                    "vendorDiscount": 0,
                    "discountedTotalPrice": 54.9,
                    "currency": "TL",
                    "itemStatus": "in_delivery",
                    "comparePrice": 0,
                    "vendorAmount": 54.9,
                    "stateDescription": null,
                    "brandName": "Okuyan Us Yayınları",
                    "merchantSku": "9786054054206",
                    "vatRate": 0,
                    "commissionAmount": 0,
                    "earningAmount": 32.4,
                    "withholdingAmount": null,
                    "lastShipmentDate": "2023-07-04T15:00:59+03:00",
                    "customizableNote": null,
                    "iban": null

                }
            ]
        }
    ]
}
Response Parametreleri
Parametre Ad	Açıklama
totalPrice	Header: İlgili sevkiyatın indirimler düşülmeden önceki toplam tutarıdır.
totalDiscount	Header: Sevkiyat bazında platform ve vendor indirimlerinin toplamıdır. Items: Item bazında platform ve vendor indirimlerinin toplam tutarıdır.
discountedTotalPrice	Header: Sevkiyat bazında indirimler düşüldükten sonraki toplam shipment tutarıdır. Items: İndirimler düşüldükten sonraki toplam item tutarıdır.
totalPlatformDiscount	Header: Sevkiyat bazında platform tarafından uygulanan toplam indirim tutarıdır.
totalVendorDiscount	Header: Sevkiyat bazında vendor tarafından uygulanan toplam indirim tutarıdır.
platformDiscount	Items: Item bazında platform tarafından uygulanan indirim tutarıdır.
vendorDiscount	Items: Item bazında vendor tarafından uygulanan indirim tutarıdır.
commissionAmount	Items: Item bazında komisyon tutarıdır.
earningAmount	Items: Item bazında satıcının hak ediş tutarıdır.
Shipment Statüleri
Parametre Ad	Açıklama
created	Shipment idefix sisteminde ödemesi başarılı şekilde oluşturulmuştur. Shipment henüz toplanmaya hazır değildir.
shipment_ready	Shipment’in hazırlanmaya başlanabileceğini belirten statüdür.
shipment_picking	Shipment’in artık iptal edilemeyeceğini belirten statüdür. Shipment toplanmaya veya paket hazırlanmaya başlandığında bu statü bildirilmelidir. Bu statüyü beslemek için update-shipment-status servisi kullanılmalıdır.
shipment_invoiced	Shipment’in faturası kesildiğinde bu statü bildirilmelidir. Bu statüyü beslemek için update-shipment-status servisi kullanılmalıdır.
shipment_cancelled	İlgili shipment müşteri tarafından iptal edildiğinde dönen statüdür.
shipment_unsupplied	İlgili shipment temin edilemedi olarak bildirildiğinde dönen statüdür.
shipment_split	İlgili shipment için parçalı işlem yapıldığı durumda dönen statüdür.
shipment_in_cargo	Shipment kargoya verildiğinde dönen statüdür.
shipment_delivered	Shipment müşteriye teslim edildiğinde dönen statüdür.
shipment_undeliver	Shipment müşteriye teslim edilemediğinde dönen statüdür.
shipment_approved	Shipment için tüm süreçler tamamlandığında ve satıcı hak ediş hesaplama sürecine geçildiğinde dönen statüdür.



İşçilik Bedeli Gönderme

İşçilik Bedeli Gönderme (update-labor-cost-amount)
İşçilik bedeli tutarını iletmek için bu servis kullanılmalıdır.

Parametre Ad	Açıklama
orderitemid	İşçilik bedeli gönderilecek ilgili ürünün id'sidir.
laborCostAmount	İlgili orderitem için işçilik bedeli gönderilecek tutardır.
Sevkiyatın statüsü "delivered" olana kadar bu servise istek gönderilebilir. "delivered" statüsü sonrası güncelleme yapılamaz.
"laborCostAmount" 0'dan küçük olamaz ve item’in faturalandırılacak tutarından büyük olamaz.
Yalnızca belirli kategori ID’leri için beslenebilir.
POST
https://merchantapi.idefix.com/oms/{vendor}/update-labor-cost-amount
Örnek Servis İsteği:
{
 "laborCostAmountItemRequests": [
{
      "orderItemId": 2147483647,
      "laborCostAmount": 0
}
  ]
}
Örnek Response:
 {
 "laborCostAmountItemRequests": [
{
      "orderItemId": 2147483647,
      "laborCostAmount": 0
}
  ],
  "laborCostAmountData": [
    "string"
]
}




Shipment Statü Güncelleme

Shipment Statü Bilgileri Güncelleme (update-shipment-status)
Oluşan shipmentlerin statülerini hazırlanıyor ya da faturalandı olarak bildirmek için kullanılacak servistir.

Shipment depoda hazırlanma durumuna geçtiğinde ve sitenin önyüzünde müşteri tarafından iptale izin verilmek istenmiyor ise "picking" statüsüne güncellenmelidir.
Shipment hazırlanıp faturalandığında ve bir fatura numarası oluşturulduğunda "invoiced" statüsüne güncellenmelidir.
vendor her satıcının unique bir tanımlayıcısıdır. Zorunlu bir alandır.
POST update-shipment-status:
https://merchantapi.idefix.com/oms/{vendorId}/{shipmentId}/update-shipment-status
* ile belirtilen alanlar zorunlu parametrelerdir.
Parametre Ad	Açıklama
shipmentID*	Statüsü güncellenmek istenen ilgili shipment ID bilgisidir.
invoiceNumber	Shipment’in oluşan fatura numarasıdır.
Örnek Servis İsteği:
Picking:

{
  "status": "picking",
  "invoiceNumber": "string"
}
Invoiced:

{
  "status": "invoiced",
  "invoiceNumber": "11111112"
}



Kargo Kodu bildirme

Kargo Kodu Bildirme(update-tracking-number)
Bu method ile herhangi bir siparişin artık platform anlaşması üzerinden değil tedarikçinin kendi anlaşması üzerinden yapılacağı bilgisiyi göndermek üzere kullanılır. Sipariş statüsü shipment_in_cargo olarak otomatik güncellenir.

vendor her satıcının unique bir tanımlayıcısıdır. Zorunlu bir alandır.
trackingUrl parametresine ait link, gönderilen kargo firmasıyla uyumlu olmalıdır. Gönderilmeye çalışılan takip URL’i ile sipariş üzerinde seçilmiş kargo profili uyuşmazlığı olduğunda sistem uyarı/hata vermektedir. Bu durumda change-cargo-provider servisi kullanılarak ilgili shipment’a doğru kargo bilgisi gönderilmelidir.
POST update-tracking-number
https://merchantapi.idefix.com/oms/{vendorId}/{shipmentId}/update-tracking-number
* ile belirtilen alanlar zorunlu alanlardır.

Parametre Ad	Açıklama
shipmentID*	Kargo kodu bildirilecek ilgili shipment ID bilgisidir.
trackingUrl*	Kargo takip URL bilgisidir.
trackingNumber*	Kargo takip numarasıdır.
Örnek Servis İsteği:
{
  "trackingUrl": "string",
  "trackingNumber": "string"
}



İade Listesi (claim-list)
idefix sisteminde iade talebi oluşan shipmentları bu metod ile çekebilirsiniz.

vendor her satıcının unique bir tanımlayıcısıdır. Zorunlu bir alandır.
GET claim-list:
https://merchantapi.idefix.com/oms/{vendorId}/claim-list
* ile belirtilen alanlar zorunlu alanlardır.

Parametre Ad	Açıklama
ids	Tekil olarak ilgili iadenin detayını çekmek için claim ID ile istek atılabilir.
orderNumber	Shipment’in idefix sistemindeki ana sipariş numarasına karşılık gelir.
claimReason	İlgili reason ID’ye göre oluşturulmuş claim’leri listelemek için kullanılır.
startDate	Belirli bir tarihten sonraki iadeler için sorgulama yapılabilir. Örnek format: 2022/09/30 23:59:59
endDate	Belirtilen tarihe kadar olan iadeler için sorgulama yapılabilir. Örnek format: 2022/09/30 23:59:59
lastUpdatedAt	İadenin durumunun son güncellenme tarihini baz alır. Örnek format: 2022/09/30 23:59:59
Örnek Servis Cevabı:
{
    "totalCount": 2,
    "itemCount": 2,
    "pageCount": 1,
    "currentPage": 1,
    "limit": 50,
    "items": [
        {
            "customerId": 104710723,
            "customerName": "Derya Kaya",
            "vendorTitle": "idefix",
            "createdAt": "2023-05-17T18:56:29+03:00",
            "orderCreatedAt": "2023-05-03T16:04:12+03:00",
            "orderNumber": "IDE64525bcc2d1c6",
            "id": 241,
            "cargoTrackingUrl": null,
            "cargoTrackingNumber": null,
            "cargoKey": "CLMY241",
            "cargoCompanyId": 74,
            "cargoCompanyName": "Yurtiçi Kargo",
            "cargoProfileId": 1,
            "cargoProfileName": "Yurtiçi Kargo Platform Öder",
            "cargoTypeId": 3,
            "cargoTypeName": "return",
            "items": [
                {
                    "productPrice": 10.05,
                    "vendorPrice": 10.05,
                    "discountedTotalPrice": 10.05,
                    "platformDiscount": 0,
                    "vendorDiscount": 0,
                    "totalDiscount": null,
                    "interestPrice": 0,
                    "vat": 0,
                    "totalPrice": 10.05,
                    "productName": "Tezus",
                    "productImage": "https://static.idefix.net/resize/{size}product/263195/tezus-64372d7596f8c.jpg",
                    "productCode": "IDE-1681337716963",
                    "barcode": "9786057903372",
                    "erpId": "1819603001",
                    "slug": "tezus-p-263195",
                    "note": null,
                    "customerNote": null,
                    "vendorNote": "müşteri ürünü fazla göndermiş",
                    "platformReason": null,
                    "platformReasonId": null,
                    "vendorReason": "Teslim edilemeyen gönderi",
                    "vendorReasonId": 3015,
                    "customerReason": null,
                    "customerReasonId": null,
                    "stateUpdatedAt": "2023-05-17T18:57:22+03:00",
                    "declineRequestNote": null,
                    "declineRequestReasonName": null,
                    "state": "approved",
                    "stateName": "İade onaylandı",
                    "orderLineId": 10000375,
                    "id": 262,
                    "autoApproveDate": "2023-05-19T23:59:59+03:00",
                    "isAutoApprove": false,
                    "approvedAt": "2023-05-17T18:57:22+03:00",
                    "isControversial": false
                }
            ]
        },
        {
            "customerId": 104710723,
            "customerName": "Derya Kaya",
            "vendorTitle": "idefix",
            "createdAt": "2023-05-16T09:39:26+03:00",
            "orderCreatedAt": "2023-05-03T16:04:12+03:00",
            "orderNumber": "IDE64525bcc2d1c6",
            "id": 232,
            "cargoTrackingUrl": "https://www.yurticikargo.com/tr/online-servisler/gonderi-sorgula?code=91687272748",
            "cargoTrackingNumber": "916872729748",
            "cargoKey": "CLMY232",
            "cargoCompanyId": 74,
            "cargoCompanyName": "Yurtiçi Kargo",
            "cargoProfileId": 1,
            "cargoProfileName": "Yurtiçi Kargo Platform Öder",
            "cargoTypeId": 3,
            "cargoTypeName": "return",
            "items": [
                {
                    "productPrice": 10.9,
                    "vendorPrice": 10.9,
                    "discountedTotalPrice": 10.9,
                    "platformDiscount": 0,
                    "vendorDiscount": 0,
                    "totalDiscount": null,
                    "interestPrice": 0,
                    "vat": 0,
                    "totalPrice": 10.9,
                    "productName": "Köy Hayatından Sahneler",
                    "productImage": "https://static.idefix.net/resize/{size}product/214882/koy-hayatindan-sahneler-6436b3c3a468e.jpg",
                    "productCode": "IDE-1681306562203",
                    "barcode": "9786050923131",
                    "erpId": "1582829001",
                    "slug": "koy-hayatindan-sahneler-p-214882",
                    "note": null,
                    "customerNote": null,
                    "vendorNote": null,
                    "platformReason": null,
                    "platformReasonId": null,
                    "vendorReason": null,
                    "vendorReasonId": null,
                    "customerReason": "Modelini beğenmedim",
                    "customerReasonId": 6251,
                    "stateUpdatedAt": "2023-05-17T17:05:42+03:00",
                    "declineRequestNote": null,
                    "declineRequestReasonName": null,
                    "state": "approved",
                    "stateName": "İade onaylandı",
                    "orderLineId": 10000376,
                    "id": 252,
                    "autoApproveDate": "2023-08-02T23:59:59+03:00",
                    "isAutoApprove": false,
                    "approvedAt": "2023-05-17T17:05:42+03:00",
                    "isControversial": false
                }
            ]
        }
    ]
}
Response Parametreleri
Parametre Ad	Açıklama
totalDiscount	Item bazında platform ve vendor indirimlerinin toplam tutarıdır.
discountedTotalPrice	İndirimler düşüldükten sonraki toplam item tutarıdır.
platformDiscount	Platform tarafından uygulanan toplam indirim tutarıdır.
vendorDiscount	Vendor tarafından uygulanan toplam indirim tutarıdır.
Shipment Statüleri
Parametre Ad	Açıklama
ready	İadesi oluşan shipment’in ilk statüsüdür. Müşteri önyüzden iade butonuna bastığında oluşur.
in_cargo	İade talebi oluşturulduktan sonra müşteri ürünü kargoya teslim eder. Sistem kargodan ürünün durumunu sorgular. Ürünün kargoya ulaştığını bildiren statüdür.
waiting_vendor_approve	İade talebi oluşan shipment’in ilgili satıcının deposuna ulaştığını bildiren statüdür. Bu statüde satıcının iadeyi inceleyerek onay veya red talebinde bulunması beklenir.
approved	Gelen iadenin onaylandığını bildiren statüdür.
decline	Gelen iadenin reddedildiğini bildiren statüdür.
vendor_decline_request	Gelen iadenin satıcı tarafından incelendiğini ve red talebi statüsüne gönderildiğini bildiren statüdür. Bu statüde iade red sebebi idefix sistemi tarafından kontrol edilir.



İptal Sebep Listesi(reasons/cancel)
İdefix sisteminde müşteriler tarafından oluşturulmuş iptallerin sebeplerine ait Id listesidir.

vendor her satıcının unique bir tanımlayıcısıdır. Zorunlu bir alandır.
GET cancel
https://merchantapi.idefix.com/oms/{vendorId}/reasons/cancel
Örnek Servis Cevabı:
[
    {
        "id": 607,
        "name": "Teslimat tarihi gecikti",
        "reasonType": "cancel",
        "description": "Doğal afet, hastalık, cenaze vb. durumlarda seçilmeli.",
        "createdAt": "2022-09-05T18:35:14+03:00",
        "updatedAt": "2022-09-05T18:35:34+03:00",
        "deletedAt": null
    },
    {
        "id": 609,
        "name": "Yanlış kartla ödeme yaptım",
        "reasonType": "cancel",
        "description": "Yanlış kart ile ödeme yapıldığında iptal etmek için seçelir.",
        "createdAt": "2022-09-05T18:35:14+03:00",
        "updatedAt": "2022-09-05T18:35:34+03:00",
        "deletedAt": null
    },
    {
        "id": 610,
        "name": "Fiyat sebebiyle vazgeçtim",
        "reasonType": "cancel",
        "description": "Ürün fiyat sebebi işe iptal edilmek istenildiğinde seçilir.",
        "createdAt": "2022-09-05T18:35:14+03:00",
        "updatedAt": "2022-09-05T18:35:34+03:00",
        "deletedAt": null
    },
    {
        "id": 611,
        "name": "Adreste bulunmayacağım",
        "reasonType": "cancel",
        "description": "Adres değişikliği durumlarında seçilmeli.",
        "createdAt": "2022-09-05T18:35:14+03:00",
        "updatedAt": "2022-09-05T18:35:34+03:00",
        "deletedAt": null
    },
    {
        "id": 608,
        "name": "Vazgeçtim",
        "reasonType": "cancel",
        "description": "Ürünü yanlışlıkla aldım",
        "createdAt": "2022-09-05T18:35:14+03:00",
        "updatedAt": "2022-09-05T18:35:34+03:00",
        "deletedAt": null
    }
]



