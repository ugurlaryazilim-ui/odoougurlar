POST
​/v1​/order​/shipment-packages​/{shipmentPackageId}
shipment packages update

shipment packages update

Parameters
Try it out
Name	Description
shipmentPackageId *
integer
(path)
shipmentPackageId

Request body

application/json
Example Value
Schema
{
  "status": "Picking"
}
Responses
Code	Description	Links
200	
shipment packages update


application/json
Controls Accept header.
Example Value
Schema
{
  "success": true,
  "timestamp": "1705059450"
}
No links
400	
invalid request


application/json
Example Value
Schema
{
  "success": false,
  "error": "invalid_request",
  "error_description": "The request is missing a required parameter, includes an unsupported parameter value, or is otherwise malformed."
}
No links
401	
authorization failed


application/json
Example Value
Schema
{
  "success": false,
  "error": "unauthorized_request",
  "error_description": "Invalid auth header!"
}
No links
500	
system error


application/json
Example Value
Schema
{
  "success": false,
  "error": "system_error",
  "error_description": "System error is occured"
}


GET
​/v1​/orders
get orders merchant

get orders

Parameters
Try it out
Name	Description
status
string
(query)
status

Available values : Awaiting, Created, Cancelled, Picking, Invoiced, Delivered or Shipped

orderLineItemStatusName
string
(query)
"(string) available values:

Created = [Created,Picking,Invoiced,Repack,ReadyToShip]
Shipped = [Shipped,Undelivered]
Delivered = [Delivered]
Cancelled = [Cancelled]
UnSupplied = [UnSupplied]
WaitingRefund = [WaitingRefund,RefundRequested,RefundDelivered]
Returned = [Returned,ReturnAccepted,RefundReturned,RefundedShipped, Refunded, UnDeliveredAndReturned] (iade kayıtlarım)
RefundRejected = [RefundRejected,RefundRejectedShipped]
RefundArrived = [RefundArrived]
Freeze = [Freeze]
Refunded = [Returned,ReturnAccepted,RefundReturned,RefundedShipped, Refunded, UnDeliveredAndReturned]
(Tamamlanan İadeler) "
Available values : Created, Shipped, Delivered, Cancelled, Returned, UnSupplied, WaitingRefund, RefundRejected, RefundArrived, Freeze, Refunded

startDate
integer
(query)
(int) unix timestamp

endDate
integer
(query)
(int) unix timestamp

page
integer
(query)
(int) default: 1

size
string
(query)
order page size

orderByDirection
string
(query)
(string) available values: ASC or DESC

orderByField
string
(query)
(string) default: id. avaiable values: updated_at

orderNumber
string
(query)
order(string) order increment id

shipmentPackageIds
string
(query)
(int) shipment package id

disableCount
boolean
(query)
(bool) disable row count

mainOrderId
string
(query)
(string) main order increment id

Responses
Code	Description	Links
200	
get orders merchant


application/json
Controls Accept header.
Example Value
Schema
{
  "page": 1,
  "size": 200,
  "totalPages": 2,
  "totalElements": 200,
  "content": [
    {
      "lines": [
        {
          "quantity": 1,
          "productId": "23213",
          "salesCampaignId": "2",
          "productSize": "22",
          "merchantSku": "test-sku",
          "productName": "product flo ayakkabi",
          "productCode": "test",
          "merchantId": "10000",
          "amount": "149.90",
          "discount": "0.00",
          "price": "149.90",
          "shippingAmount": "0",
          "fee": "0.00",
          "orderLineItemStatusName": "ReadyToShip",
          "barcode": "testBarcode",
          "vatBaseAmount": "8",
          "sku": "testSku",
          "id": 1234,
          "image": "https://floimages.mncdn.com/media/catalog/product/20-06/08/ea10se084-400_0.jpg",
          "productColor": "Siyah",
          "product_commission": 1.5,
          "currencyCode": "TL",
          "discountDetails": []
        }
      ],
      "packageHistories": [
        {
          "createdDate": 1595254644,
          "status": "Created"
        }
      ],
      "shipmentAddress": [
        {
          "id": 1,
          "firstName": "firstName",
          "lastName": "lastName",
          "address1": "address1",
          "address2": "address2",
          "city": "Istanbul",
          "cityCode": 1518,
          "district": "Beşiktaş",
          "districtId": 15182,
          "postalCode": "34000",
          "countryCode": "TR",
          "phone": "+9045234994534",
          "fullName": "fullName",
          "fullAddress": "fullAddress"
        }
      ],
      "invoiceAddress": [
        {
          "id": 1,
          "firstName": "firstName",
          "lastName": "lastName",
          "address1": "address1",
          "address2": "address2",
          "city": "Istanbul",
          "cityCode": 1518,
          "district": "Beşiktaş",
          "districtId": 15182,
          "postalCode": "34000",
          "countryCode": "TR",
          "phone": "+9045234994534",
          "fullName": "fullName",
          "fullAddress": "fullAddress"
        }
      ],
      "orderNumber": "20072017161903-1903",
      "grossAmount": "149.90",
      "totalDiscount": "149.90",
      "totalPrice": "149.90",
      "totalShippingAmount": "149.90",
      "totalInstallmentFee": "0.90",
      "taxNumber": "99999999999",
      "customerFirstName": "Flo",
      "customerLastName": "Ayakkabi",
      "customerEmail": "flo@flo.com.tr",
      "customerId": 19230,
      "id": 1,
      "cargoTrackingNumber": "test-trc",
      "cargoTrackingLink": "test-link",
      "cargoSenderNumber": "test",
      "cargoProviderName": "Flo Kargo",
      "orderDate": "1595254616",
      "tcIdentityNumber": "99999999999",
      "currencyCode": "TRY",
      "shipmentPackageStatus": "Created",
      "estimatedShippingStart": "1595513816",
      "estimatedShippingEnd": "1595513816",
      "hasInvoice": true
    }
  ]
}
No links
400	
invalid request


application/json
Example Value
Schema
{
  "success": false,
  "error": "invalid_request",
  "error_description": "The request is missing a required parameter, includes an unsupported parameter value, or is otherwise malformed."
}
No links
401	
authorization failed


application/json
Example Value
Schema
{
  "success": false,
  "error": "unauthorized_request",
  "error_description": "Invalid auth header!"
}
No links
500	
system error


application/json
Example Value
Schema
{
  "success": false,
  "error": "system_error",
  "error_description": "System error is occured"
}



GET
​/v1​/order​/claims
get orders claims

get orders claims

Parameters
Try it out
Name	Description
site_id
string
(query)
(integer) site id

return_status
string
(query)
(string)

page
integer
(query)
(int) default: 1

size
integer
(query)
order page size

orderByDirection
string
(query)
(string) available values: ASC or DESC

orderByField
string
(query)
(string) default: id. available values: updated_at

increment_id
string
(query)
(string) increment id

shipping_barcode
string
(query)
(string) shipping barcode

refund_create_date_start
integer
(query)
(int) unix timestamp. example: 1 week ago date timestamp

refund_create_date_end
integer
(query)
(int) unix timestamp. example: now timestamp

Responses
Code	Description	Links
200	
get orders claims


application/json
Controls Accept header.
Example Value
Schema
{
  "totalElements": 24,
  "totalPages": 12,
  "page": 1,
  "size": 2,
  "content": [
    {
      "id": 145984,
      "increment_id": "20061610094087",
      "stock_source_id": 83,
      "shipping_barcode": "9513538",
      "customer_name": "john",
      "sku": "200000078004",
      "qty": 1,
      "refund_total": 37.45,
      "order_item_id": 22747588,
      "reason_text": "Bedeni/numarası uymadı",
      "created_at": "2020-06-16 07:10:16",
      "refund_create_date": "2020-06-20 20:55:21",
      "product_id": 7462302715,
      "name": "Slazenger OUTCLASS Kadın Terlik Fuşya",
      "barcode": "8681174495940",
      "color": "Fuşya",
      "size": 39,
      "return_status_code": "refunded",
      "return_status": "İade Onaylanan",
      "cargo_name": "Aras Kargo",
      "currencyCode": "TRY",
      "hash": "777acdb2f4",
      "images": [
        {
          "url": "https://floimages.mncdn.com/media/catalog/product/22-05/18/sa10sk050-630_0.jpg"
        }
      ],
      "attributes": [
        {
          "attributeName": "Cinsiyet",
          "attributeValue": "Kadın",
          "attributeId": 1,
          "attributeValueId": 777
        }
      ],
      "variantAttributes": [
        {
          "attributeName": "Beden",
          "attributeValue": "37",
          "attributeId": 6
        }
      ],
      "reject_shipping_barcode": "9996272937",
      "reject_tracking_number": "3419424994448",
      "reject_tracking_url": "Beden",
      "tracking_url": "https://kargotakip.araskargo.com.tr/mainpage.aspx?code=xxx",
      "reject_shipping_method": 3,
      "reject_date": "2023-05-29 19:35:31",
      "reject_reason": 17,
      "reject_reason_text": "Ürün kullanılmış",
      "reject_image_urls": "url,url",
      "reject_hash": "23xzcppefsdewr",
      "product_review_hash": "en17prs12xyzcp"
    }
  ]
}
No links
400	
invalid request


application/json
Example Value
Schema
{
  "success": false,
  "error": "invalid_request",
  "error_description": "The request is missing a required parameter, includes an unsupported parameter value, or is otherwise malformed."
}
No links
401	
authorization failed


application/json
Example Value
Schema
{
  "success": false,
  "error": "unauthorized_request",
  "error_description": "Invalid auth header!"
}
No links
500	
system error


application/json
Example Value
Schema
{
  "success": false,
  "error": "system_error",
  "error_description": "System error is occured"
}


POST
​/v1​/order​/claims​/approve
Claims approve

Parameters
Try it out
No parameters

Request body

*/*
order placed for purchasing the path

Example Value
Schema
{
  "items": [
    {
      "quantity": 10,
      "order_code": "20011411249245",
      "sku": "000000100452120004",
      "receipt_item_code": "177",
      "reason_code": "string",
      "return_date": "2020-06-16T07:10:16.000Z",
      "stock_source_id": 1,
      "hash": "string",
      "customer_return_id": 1
    }
  ]
}
Responses
Code	Description	Links
200	
successful operation


application/json
Controls Accept header.
Example Value
Schema
{
  "success": true,
  "message": "message"
}
No links
400	
invalid request


application/json
Example Value
Schema
{
  "success": false,
  "error": "invalid_request",
  "error_description": "The request is missing a required parameter, includes an unsupported parameter value, or is otherwise malformed."
}
No links
401	
authorization failed


application/json
Example Value
Schema
{
  "success": false,
  "error": "unauthorized_request",
  "error_description": "Invalid auth header!"
}
No links
500	
system error


application/json
Example Value
Schema
{
  "success": false,
  "error": "system_error",
  "error_description": "System error is occured"
}



POST
​/v1​/order​/claims​/reject
Claims reject

Parameters
Try it out
No parameters

Request body

*/*
order placed for purchasing the path

Example Value
Schema
{
  "id": 10,
  "reject_hash": "hash",
  "reject_message": "comment",
  "reject_reason": 13,
  "reject_image_urls": "https://floimages.mncdn.com/media/import/images/reject-return/20-12/08/reject_image_5fcf1849c82bb.png,https://floimages.mncdn.com/media/import/images/reject-return/20-12/08/reject_image_5fcf1849c82bb.png"
}
Responses
Code	Description	Links
200	
successful operation


application/json
Controls Accept header.
Example Value
Schema
{
  "success": true,
  "message": "message"
}
No links
400	
invalid request


application/json
Example Value
Schema
{
  "success": false,
  "error": "invalid_request",
  "error_description": "The request is missing a required parameter, includes an unsupported parameter value, or is otherwise malformed."
}
No links
401	
authorization failed


application/json
Example Value
Schema
{
  "success": false,
  "error": "unauthorized_request",
  "error_description": "Invalid auth header!"
}
No links
500	
system error


application/json
Example Value
Schema
{
  "success": false,
  "error": "system_error",
  "error_description": "System error is occured"
}


POST
​/v1​/order​/claims​/product-review
Claims product review

Parameters
Try it out
No parameters

Request body

application/json
dispute product review

Example Value
Schema
{
  "customer_return_id": 10,
  "product_review_hash": "hash"
}
Responses
Code	Description	Links
200	
successful operation


*/*
Controls Accept header.
Example Value
Schema
{
  "success": true,
  "message": "message"
}
No links
400	
invalid request


application/json
Example Value
Schema
{
  "success": false,
  "error": "invalid_request",
  "error_description": "The request is missing a required parameter, includes an unsupported parameter value, or is otherwise malformed."
}
No links
401	
authorization failed


application/json
Example Value
Schema
{
  "success": false,
  "error": "unauthorized_request",
  "error_description": "Invalid auth header!"
}
No links
500	
system error


application/json
Example Value
Schema
{
  "success": false,
  "error": "system_error",
  "error_description": "System error is occured"
}



POST
​/v1​/order​/invoice-file-url
Get invoice file url

Getting merchant invoice file url

Parameters
Try it out
Name	Description
shipmentPackageId *
string
(query)
Order line increment id

Responses
Code	Description	Links
200	
successful operation


application/json
Controls Accept header.
Example Value
Schema
{
  "success": true,
  "message": "success",
  "data": {
    "file_url": "aws.com"
  }
}
No links
400	
invalid request


application/json
Example Value
Schema
{
  "success": false,
  "error": "invalid_request",
  "error_description": "The request is missing a required parameter, includes an unsupported parameter value, or is otherwise malformed."
}
No links
401	
authorization failed


application/json
Example Value
Schema
{
  "success": false,
  "error": "unauthorized_request",
  "error_description": "Invalid auth header!"
}
No links
500	
system error


application/json
Example Value
Schema
{
  "success": false,
  "error": "system_error",
  "error_description": "System error is occured"
}


GET
​/v1​/order​/supplier-invoice-links
Get invoice links

Get invoice links

Parameters
Try it out
Name	Description
increment_id *
string
(query)
(string) increment_id

invoice_url *
string
(query)
(string) invoice_url

invoice_serial
string
(query)
(string) invoice_serial

invoice_date
string
(query)
(datetime) invoice_date

Responses
Code	Description	Links
200	
Get invoice links


application/json
Controls Accept header.
Example Value
Schema
{
  "success": true,
  "message": "remote invoice saved."
}
No links
400	
invalid request


application/json
Example Value
Schema
{
  "success": false,
  "error": "invalid_request",
  "error_description": "The request is missing a required parameter, includes an unsupported parameter value, or is otherwise malformed."
}
No links
401	
authorization failed


application/json
Example Value
Schema
{
  "success": false,
  "error": "unauthorized_request",
  "error_description": "Invalid auth header!"
}
No links
500	
system error


application/json
Example Value
Schema
{
  "success": false,
  "error": "system_error",
  "error_description": "System error is occured"
}


POST
​/v1​/order​/supplier-invoice-file
Uploads file

Uploads file

Parameters
Try it out
No parameters

Request body

multipart/form-data
invoice_file
string($binary)
increment_id
string
(string) increment_id

invoice_serial
string
(string) invoice_serial

invoice_date
string($date-time)
(datetime) invoice_date

Responses
Code	Description	Links
200	
Send invoice file


application/json
Controls Accept header.
Example Value
Schema
{
  "success": true,
  "message": "remote invoice saved.",
  "data": "https://flo.s3.eu-central....."
}
No links
400	
invalid request


application/json
Example Value
Schema
{
  "success": false,
  "error": "invalid_request",
  "error_description": "The request is missing a required parameter, includes an unsupported parameter value, or is otherwise malformed."
}
No links
401	
authorization failed


application/json
Example Value
Schema
{
  "success": false,
  "error": "unauthorized_request",
  "error_description": "Invalid auth header!"
}
No links
500	
system error


application/json
Example Value
Schema
{
  "success": false,
  "error": "system_error",
  "error_description": "System error is occured"
}



POST
​/v1​/order​/split-package
Split an order into multiple packages

Splits an order into multiple packages and returns new order numbers for each package.

Parameters
Try it out
No parameters

Request body

application/json
Example Value
Schema
{
  "orderNumber": "test_increment_id",
  "packages": [
    {
      "warehouseCode": 1,
      "products": [
        {
          "barcode": "barcodeA",
          "quantity": 2
        }
      ]
    },
    {
      "warehouseCode": null,
      "products": [
        {
          "barcode": "barcodeB",
          "quantity": 1
        },
        {
          "barcode": "barcodeC",
          "quantity": 1
        }
      ]
    }
  ]
}
Responses
Code	Description	Links
200	
Successful response with new order numbers for each package.


application/json
Controls Accept header.
Example Value
Schema
{
  "success": true,
  "message": "Order has been successfully split into 2 packages.",
  "newOrders": [
    {
      "newOrderNumber": "test_increment_id-1",
      "products": [
        {
          "barcode": "barcodeA",
          "quantity": 2
        }
      ]
    },
    {
      "newOrderNumber": "test_increment_id-2",
      "products": [
        {
          "barcode": "barcodeB",
          "quantity": 1
        },
        {
          "barcode": "barcodeC",
          "quantity": 1
        }
      ]
    }
  ]
}
No links
400	
Invalid request or validation error.


application/json
Example Value
Schema
{
  "success": false,
  "error": "invalid_request",
  "error_description": "Order number is missing."
}
No links
401	
authorization failed


application/json
Example Value
Schema
{
  "success": false,
  "error": "unauthorized_request",
  "error_description": "Invalid auth header!"
}
No links
500	
system error


application/json
Example Value
Schema
{
  "success": false,
  "error": "system_error",
  "error_description": "System error is occured"
}

Shipment
Shipment Operations


GET
​/v1​/shipment​/cargo-company​/
Get cargo companies

Parameters
Try it out
No parameters

Responses
Code	Description	Links
200	
successful operation


application/json
Controls Accept header.
Example Value
Schema
{
  "1": {
    "id": 1,
    "name": "Mng",
    "alias": "FloShippingMng",
    "class_name": "mng"
  },
  "2": {
    "id": 2,
    "name": "Hepsijet",
    "alias": "FloShippingHepsijet",
    "class_name": "hepsijet"
  }
}
No links
400	
invalid request


application/json
Example Value
Schema
{
  "success": false,
  "error": "invalid_request",
  "error_description": "The request is missing a required parameter, includes an unsupported parameter value, or is otherwise malformed."
}
No links
401	
authorization failed


application/json
Example Value
Schema
{
  "success": false,
  "error": "unauthorized_request",
  "error_description": "Invalid auth header!"
}
No links
500	
system error


application/json
Example Value
Schema
{
  "success": false,
  "error": "system_error",
  "error_description": "System error is occured"
}

POST
​/v1​/shipment​/change-cargo-company
Change cargo company

Parameters
Try it out
No parameters

Request body

*/*
order placed for purchasing the path

Example Value
Schema
{
  "new_shipping_method_id": 1,
  "increment_id": "1"
}
Responses
Code	Description	Links
200	
successful operation


application/json
Controls Accept header.
Example Value
Schema
{
  "success": true,
  "message": "Kargo değişim işlemi başarılı."
}
No links
400	
invalid request


application/json
Example Value
Schema
{
  "success": false,
  "error": "invalid_request",
  "error_description": "The request is missing a required parameter, includes an unsupported parameter value, or is otherwise malformed."
}
No links
401	
authorization failed


application/json
Example Value
Schema
{
  "success": false,
  "error": "unauthorized_request",
  "error_description": "Invalid auth header!"
}
No links
500	
system error


application/json
Example Value
Schema
{
  "success": false,
  "error": "system_error",
  "error_description": "System error is occured"
}


POST
​/v1​/shipment​/update-package
Update Package

Parameters
Try it out
No parameters

Request body

application/json
Example Value
Schema
{
  "increment_id": "12345678"
}
Responses
Code	Description	Links
200	
successful operation


application/json
Controls Accept header.
Example Value
Schema
{
  "success": true,
  "message": "Successfully Updated",
  "data": {
    "pdf": "pdfcontent",
    "incrementId": 1234567,
    "shipmentService": "Hepsijet",
    "is_changed": false,
    "isDummyBarcode": false
  }
}
No links
400	
invalid request


application/json
Example Value
Schema
{
  "success": false,
  "error": "invalid_request",
  "error_description": "The request is missing a required parameter, includes an unsupported parameter value, or is otherwise malformed."
}
No links
401	
authorization failed


application/json
Example Value
Schema
{
  "success": false,
  "error": "unauthorized_request",
  "error_description": "Invalid auth header!"
}
No links
500	
system error


application/json
Example Value
Schema
{
  "success": false,
  "error": "system_error",
  "error_description": "System error is occured"
}


Merchant

POST
​/sapigw​/suppliers​/{supplierId}​/merchant​/stop-sale
Tatil Modu - Satışı Durdur

Satıcının tüm ürünlerini satışa kapatır (Tatil Modu). stop_sale=1 ve status=SUSPENDED yapılır. Ayrıca ilgili bildirimler gönderilir.

Parameters
Try it out
Name	Description
supplierId *
integer
(path)
Satıcı (merchant) ID

Responses
Code	Description	Links
200	
Başarılı

No links
400	
Geçersiz istek

No links
401	
Yetkilendirme başarısız

No links


POST
​/sapigw​/suppliers​/{supplierId}​/merchant​/start-sale
Tatil Modu - Satışı Başlat

Satıcının ürünlerini tekrar satışa açar (Tatil Modu kapatma). stop_sale=0 ve status=ACTIVE yapılır. Ayrıca ilgili bildirimler gönderilir.

Parameters
Try it out
Name	Description
supplierId *
integer
(path)
Satıcı (merchant) ID

Responses
Code	Description	Links
200	
Başarılı

No links
400	
Geçersiz istek

No links
401	
Yetkilendirme başarısız

No links


GET
​/v1​/brands
get brands

get all brands
Parameters
Try it out
Name	Description
size
integer
(query)
Limit per page

page
integer
(query)
Size

all
integer
(query)
gives a list of all brands.

Responses
Code	Description	Links
200	
get all brands


application/json
Controls Accept header.
Example Value
Schema
{
  "brands": [
    {
      "id": 12,
      "name": "FloAyakkabi",
      "slug": "flo-ayakkabi",
      "status": 2,
      "frontend_brand_settings": {
        "site_id": "1",
        "is_image_show": "1",
        "image": "url",
        "short_description": "Flo Ayakkabi",
        "description": "Flo Ayakkabi",
        "meta_title": "Flo Ayakkabi",
        "meta_description": "Flo Ayakkabi",
        "sort_order": "1"
      },
      "updated_at": "2023-12-18 07:50:35",
      "order_no": "3500.000000",
      "item_id": "1256207",
      "seo": "flo-ayakkabi",
      "title": "FloAyakkabi",
      "segment": "B Brand"
    }
  ]
}
No links
400	
invalid request


application/json
Example Value
Schema
{
  "success": false,
  "error": "invalid_request",
  "error_description": "The request is missing a required parameter, includes an unsupported parameter value, or is otherwise malformed."
}
No links
401	
authorization failed


application/json
Example Value
Schema
{
  "success": false,
  "error": "unauthorized_request",
  "error_description": "Invalid auth header!"
}
No links
500	
system error


application/json
Example Value
Schema
{
  "success": false,
  "error": "system_error",
  "error_description": "System error is occured"
}


GET
​/v1​/brands​/name
get brand name

get brand name
Parameters
Try it out
Name	Description
name *
string
(query)
name is camelCase

Responses
Code	Description	Links
200	
get brand


application/json
Controls Accept header.
Example Value
Schema
{
  "brands": [
    {
      "id": 12,
      "name": "FloAyakkabi"
    }
  ]
}
No links
400	
invalid request


application/json
Example Value
Schema
{
  "success": false,
  "error": "invalid_request",
  "error_description": "The request is missing a required parameter, includes an unsupported parameter value, or is otherwise malformed."
}
No links
401	
authorization failed


application/json
Example Value
Schema
{
  "success": false,
  "error": "unauthorized_request",
  "error_description": "Invalid auth header!"
}
No links
500	
system error


application/json
Example Value
Schema
{
  "success": false,
  "error": "system_error",
  "error_description": "System error is occured"
}

POST
​/v1​/store-order​/save
store order add in json format

store order add in json format

Parameters
Try it out
No parameters

Request body

application/json
Example Value
Schema
[
  {
    "store_id": 2358,
    "billing_phone": "5525555555",
    "order_code": "42290011511306090000",
    "created": "2023-11-15 10:25:04",
    "final_status": "Successful",
    "customer_id": 517200008789111,
    "product_code": "000000101413341003",
    "order_item_id": 6014000229183,
    "state": "complete",
    "product_name": "3S CAPS 3PR,SIYAH, 42",
    "product_brand": "OXIDE",
    "order_total_amount_with_vat": 899.99
  },
  {
    "store_id": 2358,
    "billing_phone": "5525555555",
    "order_code": "42290011511306090000",
    "created": "2023-11-15 10:25:04",
    "final_status": "Successful",
    "customer_id": 517200008789111,
    "product_code": "000000101481264001",
    "order_item_id": 6014000229184,
    "state": "complete",
    "product_name": "3W KNTX YTY 3PR,SIYAH, STD",
    "product_brand": "KINETIX",
    "order_total_amount_with_vat": 169.99
  },
  {
    "store_id": 2358,
    "billing_phone": "5525555555",
    "order_code": "42290011511306090000",
    "created": "2023-11-15 10:25:04",
    "final_status": "Successful",
    "customer_id": 517200008789111,
    "product_code": "000000100479637001",
    "order_item_id": 6014000229185,
    "state": "complete",
    "product_name": "8D FLO BEZ TORBA 40*45+10 KULPLU,RENKSIZ",
    "product_brand": "MARKASIZ",
    "order_total_amount_with_vat": 2
  },
  {
    "store_id": 2358,
    "billing_phone": "5525555555",
    "order_code": "42290011511306090000",
    "created": "2023-11-15 10:42:39",
    "final_status": "Successful",
    "customer_id": 61720003116545,
    "product_code": "000000101352396005",
    "order_item_id": 6014000229186,
    "state": "complete",
    "product_name": "3M WILMA W 3FX,SU YESILI, 40",
    "product_brand": "PROSHOT",
    "order_total_amount_with_vat": 399.99
  },
  {
    "store_id": 2358,
    "billing_phone": "5525555555",
    "order_code": "RFDM42290011511306090000",
    "created": "2023-11-15 10:42:39",
    "final_status": "UnSuccessful",
    "customer_id": 61720003116545,
    "product_code": "000000101413453003",
    "order_item_id": 6014000229187,
    "state": "complete",
    "product_name": "3F LOIS 3PR,SIYAH, 42",
    "product_brand": "DOWN TOWN",
    "order_total_amount_with_vat": 549.99
  }
]
Responses
Code	Description	Links
200	
"success": true, "message": "Başarılı Kayıt"


application/json
Controls Accept header.
Example Value
Schema
{
  "0": {
    "success": true,
    "order_item_id": [
      6014000229183,
      6014000229184
    ]
  },
  "1": {
    "success": false,
    "message": "Hatalı Kayıt",
    "order_item_id": [
      6014000229184
    ]
  }
}
No links
400	
invalid request

No links
401	
authorization failed


application/json
Example Value
Schema
{
  "success": false,
  "error": "unauthorized_request",
  "error_description": "Invalid auth header!"
}
No links
500	
system error


application/json
Example Value
Schema
{
  "success": false,
  "error": "system_error",
  "error_description": "System error is occured"
}


https://api.flo.com.tr/api/docs/index#/