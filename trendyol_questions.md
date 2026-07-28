

# Müşteri Sorularını Çekme

Trendyol üzerinden müşterilerin iş ortaklarımıza sormuş olduğu soruların tümünü bu servis aracılığı ile çekebilirsiniz.

### **GET** questionsFilter

Herhangi bir tarih parametresi vermeden aşağıdaki endpoint ile istek atmanız halinde son bir hafta içerisindeki sorularınız sizlere gösterilecektir. startDate ve endDate parametrelerini eklemeniz halinde verilebilecek maksimum aralık iki hafta olacaktır.

<NoLinkCallout type="info" title="PROD">
  [https://apigw.trendyol.com/integration/qna/sellers/\{sellerId}/questions/filter](https://apigw.trendyol.com/integration/qna/sellers/\{sellerId}/questions/filter)
</NoLinkCallout>

<NoLinkCallout type="info" title="STAGE">
  [https://stageapigw.trendyol.com/integration/qna/sellers/\{sellerId}/questions/filter](https://stageapigw.trendyol.com/integration/qna/sellers/\{sellerId}/questions/filter)
</NoLinkCallout>

**Önerilen Endpoint**

<NoLinkCallout type="info" title="PROD">
  [https://apigw.trendyol.com/integration/qna/sellers/\{sellerId}/questions/filter?startDate=\{startDate}\&endDate=\{endDate}\&status=WAITING\_FOR\_ANSWER](https://apigw.trendyol.com/integration/qna/sellers/\{sellerId}/questions/filter?startDate=\{startDate}\&endDate=\{endDate}\&status=WAITING_FOR_ANSWER)
</NoLinkCallout>

**Servis Parametreleri**

* **supplierId** zorunlu alan olarak istekte gönderilmelidir

| Parametre        | Parametre Değer                                                | Açıklama                                                                                      | Tip    |
| :--------------- | -------------------------------------------------------------- | --------------------------------------------------------------------------------------------- | ------ |
| barcode          |                                                                | Belirli barcode değerine ait olan sorular için kullanılabilir.                                | string |
| page             |                                                                | Sadece belirtilen sayfadaki bilgileri döndürür                                                | int    |
| size             | Varsayılan: 20, Maksimum: 50                                   | Bir sayfada listelenecek maksimum adeti belirtir.                                             | int    |
| supplierId       |                                                                | İlgili tedarikçinin ID bilgisi gönderilmelidir                                                | long   |
| endDate          |                                                                | Belirtilen tarihe kadar olan soruları getirir. Timestamp(millisecond) olarak gönderilmelidir. | long   |
| startDate        |                                                                | Belirtilen tarihten sonraki soruları getirir. Timestamp(millisecond) olarak gönderilmelidir.  | long   |
| status           | WAITING\_FOR\_ANSWER, ANSWERED, REPORTED, REJECTED, UNANSWERED | Soruların statülerine göre bilgilerini getirir.                                               | string |
| orderByField     | LastModifiedDate                                               | Son güncellenme tarihini baz alır.                                                            | string |
| orderByField     | CreatedDate                                                    | Sorunun oluşma tarihini baz alır                                                              | string |
| orderByDirection | ASC                                                            | Eskiden yeniye doğru sıralar.                                                                 | string |
| orderByDirection | DESC                                                           | Yeniden eskiye doğru sıralar.                                                                 | string |

<br />

| Status               | Açıklama                                               |
| :------------------- | :----------------------------------------------------- |
| WAITING\_FOR\_ANSWER | Müşteri sorusu satıcı tarafından cevaplanmayı bekliyor |
| ANSWERED             | Soru cevaplanmış ve yayınlanmış                        |
| REPORTED             | Satıcı tarafından raporlanmış soru                     |
| REJECTED             | Satıcının cevabı reddedilmiş                           |
| UNANSWERED           | Cevaplanmamış soru (cevaplama süresi dolmuş)           |

<br />

### Örnek Servis Cevabı

```json
{
  "content": [
    {
      "answer": {
        "creationDate": 0, //Cevabın verildiği tarih
        "hasPrivateInfo": true,
        "id": 0,
        "reason": "string",
        "text": "string"
      },
      "answeredDateMessage": "string",
      "creationDate": 0,
      "customerId": 0,
      "id": 0, //Sorunun id'si
      "imageUrl": "string",
      "productName": "string",
      "public": true,
      "reason": "string",
      "rejectedAnswer": {
        "creationDate": 0, //En son red edilen cevabın oluşturulma tarihi
        "id": 0,
        "reason": "string",
        "text": "string"
      },
      "rejectedDate": 0,
      "reportReason": "string",
      "reportedDate": 0,
      "showUserName": true,
      "status": "string",
      "text": "string",
      "userName": "string",
      "webUrl": "string",
    }
  ],
  "page": 10,
  "size": 2,
  "totalElements": 864,
  "totalPages": 432
}
```

### **GET** questionsFilterById

<NoLinkCallout type="info" title="PROD">
  [https://apigw.trendyol.com/integration/qna/sellers/\{sellerId}/questions/\{id}](https://apigw.trendyol.com/integration/qna/sellers/\{sellerId}/questions/\{id})
</NoLinkCallout>

<NoLinkCallout type="info" title="STAGE">
  [https://stageapigw.trendyol.com/integration/qna/sellers/\{sellerId}/questions/\{id}](https://stageapigw.trendyol.com/integration/qna/sellers/\{sellerId}/questions/\{id})
</NoLinkCallout>

Yukarıdaki servisten dönen sorunun id değeri ile soruları tekil olarak çekip işlem yapabilirsiniz.

| Field İsmi          | Açıklama                                                                                                    |
| :------------------ | :---------------------------------------------------------------------------------------------------------- |
| id                  | Sorunun benzersiz kimlik numarasıdır.                                                                       |
| text                | Müşterinin sorduğu soru metnidir.                                                                           |
| customerId          | Müşterinin trendyol.com üzerinde kayıtlı id değeridir.                                                      |
| userName            | Müşterinin adıdır. (showUserName false ise boş döner)                                                       |
| showUserName        | Müşterinin adının trendyol.com üzerinden görünüp görünmediğini ileten parametredir.                         |
| status              | Sorunun statüsüdür.                                                                                         |
| creationDate        | Müşterinin trendyol.com üzerinde soruyu sorduğu tarih. (timestamp millisecond)                              |
| public              | Sorunun trendyol.com'da gösterilip gösterilmeyeceğini gösteren değerdir.                                    |
| reason              | Eğer soru reddedilmiş ise red sebebidir.                                                                    |
| reportReason        | Satıcının soruyu raporlarken yazdığı açıklamadır. Bu işlem sadece Trendyol Satıcı Panelinden yapılmaktadır. |
| reportedDate        | Satıcının soruyu raporladığı tarihtir. (timestamp millisecond)                                              |
| rejectedDate        | Sorunun reddedilme tarihidir. (timestamp millisecond)                                                       |
| answeredDateMessage | Sorunun cevaplanma süresi mesajıdır.                                                                        |
| imageUrl            | Sorusu sorulan ürünün görsel linki değeridir.                                                               |
| productName         | Sorusu sorulan ürünün isim değeridir.                                                                       |
| productMainId       | Ürünün model kodudur.                                                                                       |
| webUrl              | Ürünün web sayfası linkidir.                                                                                |
| answer              | Sorunun aktif cevabıdır. (varsa)                                                                            |
| rejectedAnswer      | Sorunun en son reddedilmiş cevabının detaylarıdır.                                                          |

<br />

**Answer Object Alanları**

| Field İsmi     | Açıklama                                                   |
| :------------- | :--------------------------------------------------------- |
| id             | Cevabın benzersiz kimlik numarasıdır.                      |
| text           | Cevap metnidir.                                            |
| creationDate   | Cevabın verildiği tarihtir. (timestamp millisecond)        |
| hasPrivateInfo | Cevabın özel bilgi içerip içermediğidir.                   |
| reason         | Cevabın reddedilme sebebidir. (sadece rejectedAnswer için) |

<br />

<Callout icon="❗️">
  Tarih Aralığı Sınırlaması startDate ve endDate parametreleri kullanıldığında, maksimum tarih aralığı 2 hafta ile sınırlıdır. Bu süreyi aşan isteklerde endDate otomatik olarak startDate + 2 hafta şeklinde ayarlanır.
</Callout>

<Callout icon="📘" theme="info">
  Sayfalama Sayfalama 0'dan başlar. İlk sayfa için page=0 kullanılmalıdır. Maksimum sayfa boyutu 50'dir.
</Callout>




# Müşteri Sorularını Cevaplama

[Trendyol Müşteri Sorularını Çekme Servisi](https://integration-documentation-udwy.readme.io/docs/m%C3%BC%C5%9Fteri-sorular%C4%B1n%C4%B1-%C3%A7ekme) üzerinden çekmiş olduğunuz sorulara bu servis aracılığı ile cevap verebilirsiniz.

* Cevap mesajı minimum 10, maksimum 2000 karakter aralığında olmalıdır.
* Cevaplar yasaklı kelime kontrolünden geçirilir. Yasaklı kelime içeren cevaplar reddedilir.

### **POST** createAnswer

<NoLinkCallout type="info" title="PROD">
  [https://apigw.trendyol.com/integration/qna/sellers/\{sellerId}/questions/\{id}/answers](https://apigw.trendyol.com/integration/qna/sellers/\{sellerId}/questions/\{id}/answers)
</NoLinkCallout>

<NoLinkCallout type="info" title="STAGE">
  [https://stageapigw.trendyol.com/integration/qna/sellers/\{sellerId}/questions/\{id}/answers](https://stageapigw.trendyol.com/integration/qna/sellers/\{sellerId}/questions/\{id}/answers)
</NoLinkCallout>

**Örnek Servis İsteği**

```json
{
  "text": "string"
}
```

**Örnek Servis Cevabı**

```json
{
  "answerId": 0
}
```

**Field Açıklamaları:**

| Field İsmi | Açıklama                                                               |
| :--------- | :--------------------------------------------------------------------- |
| id         | Ürün sorusunun id'sidir. Ürün sorularını çekme servisinden alınabilir. |
| text       | Cevap metnidir                                                         |
| sellerId   | İlgili tedarikçinin id bilgisidir..                                    |

**Hata Durumları:**

Cevaplama işlemi sırasında aşağıdaki hata durumları ile karşılaşabilirsiniz:

| Hata Durumu                   | Açıklama                                                                        |
| :---------------------------- | :------------------------------------------------------------------------------ |
| Soru daha önce cevaplanmış    | Bu soru daha önce cevaplandı. Cevaplanmış sorular tekrar cevaplanamaz.          |
| Süre limiti aşılmış           | Belirtilen süre içinde cevap vermediğiniz için soru kapatılmıştır.              |
| Yasaklı kelime limiti aşılmış | Cevabınızda yasaklı kelime kullanma limitini aştığınız için soru kapatılmıştır. |
| Cevap çok kısa                | Cevabınız 10 karakterden uzun olmalıdır.                                        |
| Cevap çok uzun                | Cevabınız 2000 karakterden uzun olamaz.                                         |
| Cevap boş                     | Bir cevap giriniz.                                                              |

**Hangi Statüdeki Sorular Cevaplanabilir?**

| Statü                | Cevaplanabilir mi? | Açıklama                                                                                   |
| :------------------- | :----------------- | :----------------------------------------------------------------------------------------- |
| WAITING\_FOR\_ANSWER | Evet               | Sadece bu statüdeki sorular cevaplanabilir.                                                |
| ANSWERED             | Hayır              | Soru cevaplanmış.                                                                          |
| REPORTED             | Hayır              | Soru raporlanmış, admin değerlendirmesi bekleniyor.                                        |
| REJECTED             | Hayır              | Soru reddedilmiş ve kapatılmış.                                                            |
| UNANSWERED           | Hayır              | 3 iş günü içinde yanıtlanmama veya yasaklı kelime limitinin aşılması nedeniyle kapatılmış. |

<br />

<Callout icon="📘" theme="info">
  **ÖNEMLİ NOTLAR:**

  * Cevap verdikten sonra cevabınız yasaklı kelime kontrolünden geçirilir.
  * Yasaklı kelime tespit edilirse cevabınız reddedilir ve soru tekrar **WAITING_FOR_ANSWER** statüsüne döner.
  * Belirli sayıda yasaklı kelime içeren cevap verirseniz, soru **UNANSWERED** statüsüne geçer ve bir daha cevaplayamazsınız.
</Callout>





# Stage Ortamda Müşteri Sorusu Oluşturma

Stage ortamdaki testlerinizi ilerletebilmek için aşağıdaki servis ile ürün sorusu oluşturabilirsiniz.

Belirli bir ürün için yeni bir müşteri sorusu oluşturmak amacıyla bu servisi kullanabilirsiniz.

* Soru metni boş olmamalıdır.
* Oluşturulan soru Trendyol'da yayınlanmadan önce değerlendirilir.

**POST CreateQuestion**

<NoLinkCallout type="info" title="STAGE">
  [https://stageapigw.trendyol.com/integration/qna/sellers/\{sellerId}/questions](https://stageapigw.trendyol.com/integration/qna/sellers/\{sellerId}/questions)
</NoLinkCallout>

**Örnek Servis İsteği**

```json
{
  "text": "Bu ürünün kumaşı pamuk mu?",
  "contentId": 2397814,
  "userId": 4147346,
  "userFullName": "Test Kullanıcı",
  "showUserName": false,
  "channelId": 1
}
```

**Örnek Servis Yanıtı**

```json
{
  "questionId": 42
}
```

**Field Açıklamaları**

| Field İsmi   | Field Açıklaması                                                                                     |
| ------------ | ---------------------------------------------------------------------------------------------------- |
| sellerId     | Trendyol'da kayıtlı satıcının benzersiz kimlik numarasıdır. Path parametresi olarak gönderilmelidir. |
| text         | Oluşturulacak sorunun metnidir.                                                                      |
| contentId    | Sorunun sorulacağı ürünün içerik ID'sidir.                                                           |
| userId       | Soruyu soran kullanıcının ID'sidir. Servis isteği örneğindeki ID'yi (4147346) girebilirsiniz.        |
| userFullName | Soruyu soran kullanıcının adı soyadıdır.                                                             |
| showUserName | Kullanıcı adının gösterilip gösterilmeyeceğini belirten parametredir.                                |
| channelId    | Kanal ID bilgisidir.                                                                                 |
| questionId   | Oluşturulan sorunun benzersiz kimlik numarasıdır.                                                    |

**Zorunlu Alanlar**

| Field İsmi   | Zorunluluk Bilgisi |
| ------------ | ------------------ |
| sellerId     | Evet               |
| text         | Evet               |
| contentId    | Evet               |
| userId       | Evet               |
| showUserName | Evet               |
| userFullName | Hayır              |
| channelId    | Hayı               |

<br />

**Hata Durumları:**

Soru oluşturma sürecinde aşağıdaki hatalarla karşılaşabilirsiniz:

| Hata Durumu        | Açıklama                       |
| ------------------ | ------------------------------ |
| Boş soru metni     | Lütfen bir soru metni giriniz. |
| contentId eksik    | contentId zorunludur.          |
| userId eksik       | userId zorunludur.             |
| showUserName eksik | showUserName zorunludur.       |
| sellerId eksik     | sellerId zorunludur.           |

**ÖNEMLİ NOTLAR:**

* sellerId path parametresi olarak gönderilmelidir.
* userFullName ve channelId opsiyonel alanlardır.
* channelId için 1 değerini gönderebilirsiniz.

