Cari Hesap Ekstresi Entegrasyonu
Değişiklik yapılan tüm entegrasyon servislerine ise developers.tgoapps.com adresinden ulaşabilirsiniz. :::

Trendyol sisteminde oluşan muhasebesel kayıtlarınızı bu servis aracılığı ile entegrasyon üzerinden çekebilirsiniz.

Finansal kayıtlar sipariş teslim edildikten sonra oluşmaktadır.
transactionType veya transactionTypes girilmesi zorunludur:
transactionType için 1 istekte yalnızca 1 type girilebilir.
transactionTypes girilmesi halinde 1 istekte birden fazla type girilebilir. Örnek: transactionTypes=Type1, Type2
transactionType ve transactionTypes beraber girilmesi durumunda transactionTypes için girilen değerler geçerli kabul edilir.
paymentOrderId siparişin ödemesi yapıldıktan sonra oluşmaktadır. İstisnalar hariç, her çarşamba, ilgili haftada vadesi gelen siparişler için ödeme emri oluşur.
paymentOrderId ile sipariş ve ödemelerinizi eşleştirebilirsiniz.
Başlangıç ve bitiş tarihi girilmesi zorunludur ve arasındaki süre 15 günden uzun olamaz.
Store bilgileri Marketplace satıcıları için "null" olarak dönecektir.
"affiliate" alanı "TRENDYOLTR" yada "TRENDYOLAZJV" dönebilir.
Kullanılacak olan 2 servis (settlements , otherfinancials) birbirinden ayrı işlem kayıtlarını vermektedir.

"Settlements" servisinden satış, iade, indirim, kupon, provizyon işlemlerinin detaylarına ulaşabilirsiniz.

Transaction Type, SellerRevenuePositive ve CommissionNegative birlikte değerlendirilmelidir.
Transaction Type, SellerRevenueNegative ve CommissionPositive birlikte değerlendirilmelidir.
Transaction Type, SellerRevenuePositiveCancel ve CommissionNegativeCancel birlikte değerlendirilmelidir.
Transaction Type, SellerRevenueNegativeCancel ve CommissionPositiveCancel birlikte değerlendirilmelidir.
"Other Financial" servisinden ise tedarikçi finansmanı, virman, ödemeler (hakediş), faturalar (Trendyoldan tedarikçiye) , tedarikçi faturaları (Tedarikçiden Trendyola), gelen havale, komisyon mutabakat faturaları işlemlerinin detaylarına ulaşabilirsiniz.

GET settlements
PROD
https://apigw.trendyol.com/integration/finance/che/sellers/{sellerId}/settlements

STAGE
https://stageapigw.trendyol.com/integration/finance/che/sellers/{sellerId}/settlements

Önerilen Endpoint'ler

PROD
https://apigw.trendyol.com/integration/finance/che/sellers/{sellerId}/settlements?endDate={endDate}&startDate={startDate}&transactionType={Type}&page=0&size=500

veya

PROD
https://apigw.trendyol.com/integration/finance/che/sellers/{sellerId}/otherfinancials?transactionType=DeductionInvoices&transactionSubType=PlatformServiceFee&startDate={startDate}&endDate={endDate}

Parametre	Parametre Değer	Açıklama	Tip	Zorunlu
transactionType veya transactionTypes	Sale, Return, Discount, DiscountCancel, Coupon, CouponCancel, ProvisionPositive, ProvisionNegative, SellerRevenuePositive, SellerRevenueNegative, CommissionPositive, CommissionNegative, SellerRevenuePositiveCancel, SellerRevenueNegativeCancel, CommissionPositiveCancel, CommissionNegativeCancel	Finansal işlem türüdür.	string	Evet
startDate		Belirli bir tarihten sonraki işlem kayıtlarını getirir. Timestamp milisecond olarak gönderilmelidir.	long	Evet
endDate		Belirli bir tarihten sonraki işlem kayıtlarını getirir. Timestamp milisecond olarak gönderilmelidir.	long	Evet
page		Sadece belirtilen sayfadaki bilgileri döndürür	int	Hayır
size	500 ve 1000 değerlerini alabilir. (Default=500)	Bir sayfada listelenecek maksimum adeti belirtir.	int	Hayır
supplierId		İlgili tedarikçinin ID bilgisi gönderilmelidir	long	Evet
paymentDate		Ödemeye girebileceği en erken tarih	string	Hayır
paymentOrderId		Bu alanla sipariş ve ödemelerinizi eşleştirebilirsiniz.	integer (int64)	Hayır
transactionType için kullanılabilecek işlem türlerinin açıklamaları aşağıdaki gibidir
transactionType	Açıklama
Sale	Siparişlere ait satış kayıtlarını verir
Return	Siparişlere ait iade kayıtlarını verir
Discount	Tedarikçi tarafından karşılanan indirim tutarını gösterir.
DiscountCancel	Ürün iptal veya iade olduğunda atılan kayıttır. İndirim kaydının tersi olarak düşünülebilir
Coupon	Tedarikçi tarafından karşılanan kupon tutarını gösterir.
CouponCancel	Ürün iptal veya iade olduğunda atılan kayıttır. Kupon kaydının tersi olarak düşünülebilir
ProvisionPositive	Gramaj farkından dolayı oluşan tutarlar Provizyon kaydı olarak atılır. Sipariş iptal veya iade olduğunda birbirinin tersi olarak kayıt atılır.
ProvisionNegative	Gramaj farkından dolayı oluşan tutarlar Provizyon kaydı olarak atılır. Sipariş iptal veya iade olduğunda birbirinin tersi olarak kayıt atılır.
ManualRefund	Kısmi iade durumunda atılan kayıttır. Bir ürün için ürün tutarından daha az olacak şekilde iade kaydı oluşturuluyor ise bu kayıt atılmaktadır.
ManualRefundCancel	Kısmi iade olan bir ürün için ürün tamamen iade olduğunda, kısmi iadenin iptali amacıyla bu kayıt atılır. Böylece, daha önceden atılan kısmi iade tutarı için mahsuplaşılır.
TYDiscount	Kurumsal faturalı alışverişlerde, Trendyol’un karşıladığı indirimler için bu kayıt atılır. Bu tutar, ay sonlarında satıcıdan talep edilen fatura ile satıcıya ödenir.
TYDiscountCancel	Kurumsal faturalı alışverişlerde, Trendyol’un karşıladığı indirimler için atılan TYDiscount kaydına istinaden atılır. Ürünün iptal veya iade olması durumunda bu kayıt atılır.
TYCoupon	Kurumsal faturalı alışverişlerde, Trendyol’un karşıladığı kuponlar için bu kayıt atılır. Bu tutar, ay sonlarında satıcıdan talep edilen fatura ile satıcıya ödenir.
TYCouponCancel	Kurumsal faturalı alışverişlerde, Trendyol’un karşıladığı kuponlar için atılan TYCoupon kaydına istinaden atılır. Ürünün iptal veya iade olması durumunda bu kayıt atılır.
SellerRevenuePositive	Hakediş Pozitif Düzeltme
SellerRevenueNegative	Hakediş Negatif Düzeltme
CommissionPositive	Komisyon Pozitif Düzeltme
CommissionNegative	Komisyon Negatif Düzeltme
SellerRevenuePositiveCancel	Hakediş Pozitif Düzeltme İptal
SellerRevenueNegativeCancel	Hakediş Negatif Düzeltme İptal
CommissionPositiveCancel	Komisyon Pozitif Düzeltme İptal
CommissionNegativeCancel	Komisyon Negatif Düzeltme İptal
Örnek Servis Cevabı (transactionType=Sale kullanılmıştır)
JSON

{
    "page": 0,
    "size": 500,
    "totalPages": 878,
    "totalElements": 438974,
    "content": [
        {
            "id": "725041340",
            "transactionDate": 1613397671561,  // İşlem Tarihi
            "barcode": "8681385952874",
            "transactionType": "Satış",
            "receiptId": 48376618,             // Dekont No
            "description": "Satış",
            "debt": 0.0,                       // Borç
            "credit": 449.99,                  // Alacak
            "paymentPeriod": 30,               // Vade Süresi
            "commissionRate": 15.0,            // Siparişteki Ürüne Ait Komisyon Oranı
            "commissionAmount": 67.4985,       // Trendyol Komisyon Tutarı
            "commissionInvoiceSerialNumber": null,
            "sellerRevenue": 382.4915,         // Satıcı Hakediş Tutarı
            "orderNumber": "501915861",
            "paymentOrderId": 112360,          // Ödeme Numarası
            "paymentDate": 1615989671561,      // Ödeme Tarihi
            "sellerId": 123456,
            "storeId": null,
            "storeName": null,
            "storeAddress": null,
            "country": "Türkiye",
            "orderDate": 1720107451532,
            "affiliate": "TRENDYOLTR",
            "shipmentPackageId": 1111111111 // sipariş paket numarası
        },
        {
            "id": "725041335",
            "transactionDate": 1613397671557,
            "barcode": "8681387147421",
            "transactionType": "Satış",
            "receiptId": 48376618,
            "description": "Satış",
            "debt": 0.0,
            "credit": 699.99,
            "paymentPeriod": 28,
            "commissionRate": 15.0,
            "commissionAmount": 104.9985,
            "commissionInvoiceSerialNumber": null,
            "sellerRevenue": 594.9915,
            "orderNumber": "501915861",
            "paymentOrderId": 112360,
            "paymentDate": 1615989671557,
            "sellerId": 123456,
            "storeId": null,
            "storeName": null,
            "storeAddress": null,
            "country": "Türkiye",
            "orderDate": 1720107451532,
            "affiliate": "TRENDYOLTR",
            "shipmentPackageId": 1111111111
        }
        ]
}
GET otherfinancials
PROD
https://apigw.trendyol.com/integration/finance/che/sellers/{sellerId}/otherfinancials

STAGE
https://stageapigw.trendyol.com/integration/finance/che/sellers/{sellerId}/otherfinancials

Önerilen Endpoint'ler

PROD
https://apigw.trendyol.com/integration/finance/che/sellers/{sellerId}/otherfinancials?endDate={endDate}&startDate={startDate}&transactionType={Type}&page=0&size=500

veya

PROD
https://apigw.trendyol.com/integration/finance/che/sellers/{sellerId}/otherfinancials?endDate={endDate}&startDate={startDate}&transactionTypes={Type1,Type2}&page=0&size=500

Yalnızca Platform Hizmet Bedeli kayıtlarını filtrelemek için önerilen endpoint

PROD
https://apigw.trendyol.com/integration/finance/che/sellers/{sellerId}/otherfinancials?transactionType=DeductionInvoices&transactionSubType=PlatformServiceFee&startDate={startDate}&endDate={endDate}


Parametre	Parametre Değer	Açıklama	Tip	Zorunlu
transactionType veya transactionTypes	Stoppage, CashAdvance, WireTransfer, IncomingTransfer, ReturnInvoice, CommissionAgreementInvoice, PaymentOrder, DeductionInvoices, FinancialItem	Finansal işlem türüdür.	string	Evet
transactionSubType	PlatformServiceFee	Platform hizmet bedeli kayıtlarını filtrelemek için kullanılır. Bu parametreyi kullanmak için transactionType=DeductionInvoices ya da transactionTypes içinde DeductionInvoices olacak şekilde istek yapılmalıdır.	string	Hayır
startDate		Belirli bir tarihten sonraki işlem kayıtlarını getirir. Timestamp millisecond olarak gönderilmelidir.	long	Evet
endDate		Belirli bir tarihten sonraki işlem kayıtlarını getirir. Timestamp millisecond olarak gönderilmelidir.	long	Evet
page		Sadece belirtilen sayfadaki bilgileri döndürür	int	Hayır
size	500 ve 1000 değerlerini alabilir. (Default=500)	Bir sayfada listelenecek maksimum adeti belirtir.	int	Hayır
supplierId		İlgili tedarikçinin ID bilgisi gönderilmelidir	long	Evet
paymentDate		Ödemeye girebileceği en erken tarih	string	Hayır
paymentOrderId		Bu alanla sipariş ve ödemelerinizi eşleştirebilirsiniz.	integer (int64)	Hayır
transactionType için kullanılabilecek işlem türlerinin açıklamaları aşağıdaki gibidir.
transactionType	Açıklama
CashAdvance	Vadesi henüz gelmemiş hakedişler için erken ödeme alındığında atılan kayıttır.
WireTransfer	Trendyol ile Tedarikçi arasında yapılan virman için atılan kayıttır.
IncomingTransfer	Borçlu durumundaki tedarikçiden, Trendyola yapılan ödemeler için atılan kayıttır
ReturnInvoice	Tedarikçiden Trendyola kesilen iade faturalarıdır. Bakiyeyi + olarak etkiler.
CommissionAgreementInvoice	Tedarikçinin mahsuplaşma yapılacak alacağı olmadığı durumda, iade gelen ürünler için tedarikçiden alınan komisyon mutabakat faturasıdır.
PaymentOrder	Vadesi gelen işlemlerden hesaplanarak tedarikçiye yapılan hakediş ödemesidir
DeductionInvoices	Trendyol tarafından sağlanan hizmetler için tedarikçiye kesilen faturadır.
FinancialItem	Trendyol tarafından atılan düzeltme kayıtlarıdır.
Stoppage	Bu işlem tipiyle gelindiğinde ilgili tarih aralığındaki E-ticaret Stopajı ve E-ticaret Stopaj İptali kalemleri listelenecek.
Örnek Servis Cevabı (transactionType=PaymentOrder kullanılmıştır)
JSON

{
    "page": 0,
    "size": 500,
    "totalPages": 1,
    "totalElements": 2,
    "content": [
        {
            "id": "1639160",
            "transactionDate": 1613062815995,
            "barcode": null,
            "transactionType": "Ödeme",
            "receiptId": null,
            "description": null,
            "debt": 8754732.06,
            "credit": 0.0,
            "paymentPeriod": null,
            "commissionRate": null,
            "commissionAmount": null,
            "commissionInvoiceSerialNumber": null,
            "sellerRevenue": null,
            "orderNumber": null,
            "paymentOrderId": 112360,
            "paymentDate": null,
            "sellerId": 123456,
            "storeId": null,
            "storeName": null,
            "storeAddress": null,
            "country": "Türkiye",
            "orderDate": 1720107451532,
            "affiliate": "TRENDYOLTR",
            "shipmentPackageId": 1111111111

        },
        {
            "id": "1576967",
            "transactionDate": 1612458029832,
            "barcode": null,
            "transactionType": "Ödeme",
            "receiptId": null,
            "description": null,
            "debt": 5707246.85,
            "credit": 0.0,
            "paymentPeriod": null,
            "commissionRate": null,
            "commissionAmount": null,
            "commissionInvoiceSerialNumber": null,
            "sellerRevenue": null,
            "orderNumber": null,
            "paymentOrderId": 1576967,
            "paymentDate": null,
            "sellerId": 123456,
            "storeId": null,
            "storeName": null,
            "storeAddress": null,
            "country": "Türkiye",
            "orderDate": 1720107451532,
            "affiliate": "TRENDYOLTR",
            "shipmentPackageId": 1111111111
        }
    ]
}
TransactionType	MP	Türkçe	ÖdemeTipi
Sale	+	Satış	Alacak (+)
Return	+	İade	Borç (-)
Discount	+	İndirim	Borç (-)
Discount Cancel	+	İndirim İptal	Alacak (+)
Coupon	+	Kupon	Alacak (+)
Coupon Cancel	+	Kupon İptal	Borç (-)
Provision Positive	-	Provizyon +	Alacak (+)
Provision Negative	-	Provizyon -	Borç (-)
TYDiscount	+	Kurumsal Fatura - TY Promosyon	Borç (-)
TYDiscountCancel	+	Kurumsal Fatura - TY Promosyon İptali	Alacak (+)
TYCoupon	+	Kurumsal Fatura - TY Kupon	Borç (-)
TYCoupon Cancel	+	Kurumsal Fatura - TY Kupon İptali	Alacak (+)
ManuelRefund	-	Kısmi İade	Borç (-)
ManuelRefundCancel	-	Kısmi İade İptal	Alacak (+)
SellerRevenuePositive	+	Hakediş Pozitif Düzeltme	Alacak (+)
SellerRevenueNegative	-	Hakediş Negatif Düzeltme	Borç (-)
CommissionPositive	-	Komisyon Pozitif Düzeltme	Borç (-)
CommissionNegative	+	Komisyon Negatif Düzeltme	Alacak (+)
SellerRevenuePositiveCancel	-	Hakediş Pozitif Düzeltme İptal	Borç (-)
SellerRevenueNegativeCancel	+	Hakediş Negatif Düzeltme İptal	Alacak (+)
CommissionPositiveCancel	+	Komisyon Pozitif Düzeltme İptal	Alacak (+)
CommissionNegativeCancel	-	Komisyon Negatif Düzeltme İptal	Borç (-)
Parametre	comissionAmount	sellerRevenue
Sale	-	+
Return	+	-
Discount	+	-
Discount Cancel	-	+
Coupon	+	-
Coupon Cancel	-	+
Provision Positive	-	+
Provision Negative	+	-
TYDiscount	+	-
TYDiscountCancel	-	+
TYCoupon	+	-
TYCoupon Cancel	-	+
ManuelRefund	+	-
ManuelRefundCancel	-	+
SellerRevenuePositive	0	+
SellerRevenueNegative	0	-
CommissionPositive	+	0
CommissionNegative	-	0
SellerRevenuePositiveCancel	0	-
SellerRevenueNegativeCancel	0	+
CommissionPositiveCancel	-	0
CommissionNegativeCancel	+	0


Kargo Faturası Detayları
Trendyol tarafından satıcılara kesilen kargo faturalarını detayına bu servis üzerinden ulaşabilirsiniz.

❗️
DİKKAT Mevcut entegrasyon servislerimizde api.trendyol.com olarak kullandığımız base URL, 9 Ocak 2025 Perşembe günü itibarıyla api.tgoapis.com üzerinden çalışacak şekilde güncellenecektir. Sistemlerinizde bu değişikliği belirtilen tarihe kadar yapmanızı önemle rica ederiz.

Değişiklik yapılan tüm entegrasyon servislerine ise developers.tgoapps.com adresinden ulaşabilirsiniz.

-Kargo Faturasının seri numarasını nasıl bulurum ?

Cari Hesap Ekstresi Entegrasyonu üzerinden transactionType='DeductionInvoices' responsundan dönen data içerisinde ki alanlardan transactionType değeri "Kargo Faturası" yada "Kargo Fatura" olan kayıtların "Id" değeri "invoiceSerialNumber" değeridir.

GET cargo-invoice
PROD
https://apigw.trendyol.com/integration/finance/che/sellers/{sellerId}/cargo-invoice/{invoiceSerialNumber}/items

STAGE
https://stageapigw.trendyol.com/integration/finance/che/sellers/{sellerId}/cargo-invoice/{invoiceSerialNumber}/items

Örnek Servis Cevabı

JSON

{
    "page": 0,
    "size": 500,
    "totalPages": 1,
    "totalElements": 25,
    "content": [
        {
            "shipmentPackageType": "Gönderi Kargo Bedeli",
            "parcelUniqueId": 7260001151141191,
            "orderNumber": "2111681160",
            "amount": 34.24,
            "desi": 1
        },
        {
            "shipmentPackageType": "İade Kargo Bedeli",
            "parcelUniqueId": 7265609146531138,
            "orderNumber": "2111161312",
            "amount": 34.24,
            "desi": 1
        }
    ]
}